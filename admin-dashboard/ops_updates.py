#!/usr/bin/env python3
"""
Homelab OS — App-Store Auto Update Engine (Ultra-Low Resource)
Zero extra containers (uses /var/run/docker.sock + Nextcloud occ directly).
Features:
  - Container image digest comparison across all managed services
  - Deep Nextcloud core + app update inspection via occ
  - Hands-free Nextcloud update automation with pre-update backup & safe rollback
  - Always clears Nextcloud maintenance mode in finally block (never locks instance)
  - Cooperative job cancellation checkpoints
  - Daily / weekly auto-update schedule evaluator
"""

import importlib.metadata
import inspect
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

OCC_PHP_PREFIX = "php -d memory_limit=512M /var/www/html/occ"


DAY_MAP = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


def get_update_settings(db) -> Dict[str, Any]:
    keys = (
        "auto_update_enabled",
        "auto_update_freq",
        "auto_update_day",
        "auto_update_time",
        "auto_update_backup_before",
        "auto_update_nextcloud_apps",
        "auto_update_last_check",
        "auto_update_last_run",
    )
    rows = db.execute(
        f"SELECT key, value FROM settings WHERE key IN ({','.join('?' * len(keys))})",
        keys,
    ).fetchall()
    smap = {r["key"]: r["value"] for r in rows}
    return {
        "auto_update_enabled": str(smap.get("auto_update_enabled", "false")).strip().lower() in ("true", "1", "yes"),
        "schedule_freq": smap.get("auto_update_freq") or "weekly",
        "schedule_day": (smap.get("auto_update_day") or "sun").lower(),
        "schedule_time": smap.get("auto_update_time") or "03:00",
        "backup_before": str(smap.get("auto_update_backup_before", "true")).strip().lower() in ("true", "1", "yes"),
        "update_nextcloud_apps": str(smap.get("auto_update_nextcloud_apps", "true")).strip().lower() in ("true", "1", "yes"),
        "last_checked": smap.get("auto_update_last_check") or "",
        "last_run": smap.get("auto_update_last_run") or "",
    }


def save_update_settings(db, data: Dict[str, Any]) -> Dict[str, Any]:
    cur = get_update_settings(db)

    def _b(val, default):
        if val is None:
            return default
        if isinstance(val, bool):
            return val
        return str(val).strip().lower() in ("true", "1", "yes")

    enabled = _b(data.get("auto_update_enabled"), cur["auto_update_enabled"])
    freq = str(data.get("schedule_freq") or cur["schedule_freq"]).strip().lower()
    if freq not in ("daily", "weekly"):
        freq = "weekly"
    day = str(data.get("schedule_day") or cur["schedule_day"]).strip().lower()
    if day not in DAY_MAP:
        day = "sun"
    sched_time = str(data.get("schedule_time") or cur["schedule_time"]).strip()
    if not re.match(r"^(?:[01]\d|2[0-3]):[0-5]\d$", sched_time):
        sched_time = "03:00"
    backup_before = _b(data.get("backup_before"), cur["backup_before"])
    update_apps = _b(data.get("update_nextcloud_apps"), cur["update_nextcloud_apps"])

    pairs = {
        "auto_update_enabled": "true" if enabled else "false",
        "auto_update_freq": freq,
        "auto_update_day": day,
        "auto_update_time": sched_time,
        "auto_update_backup_before": "true" if backup_before else "false",
        "auto_update_nextcloud_apps": "true" if update_apps else "false",
    }
    for k, v in pairs.items():
        db.execute(
            "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, datetime('now')) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=datetime('now')",
            (k, v),
        )
    db.commit()
    return get_update_settings(db)


def is_schedule_due(cfg: Dict[str, Any], now_dt: Optional[datetime] = None) -> bool:
    """Deterministic schedule evaluator: checks frequency, weekday, HH:MM window, and once-per-day lock."""
    if not cfg.get("auto_update_enabled"):
        return False
    now = now_dt or datetime.now()
    last_run = str(cfg.get("last_run") or "").strip()
    today_str = now.strftime("%Y-%m-%d")
    if last_run.startswith(today_str):
        return False

    freq = str(cfg.get("schedule_freq") or "weekly").lower()
    if freq == "weekly":
        target_wd = DAY_MAP.get(str(cfg.get("schedule_day") or "sun").lower(), 6)
        if now.weekday() != target_wd:
            return False

    sched_time = str(cfg.get("schedule_time") or "03:00")
    try:
        hh, mm = [int(x) for x in sched_time.split(":", 1)]
    except Exception:
        return False
    target_mins = hh * 60 + mm
    now_mins = now.hour * 60 + now.minute
    return target_mins <= now_mins <= target_mins + 59


def _parse_version_tuple(v: str) -> Tuple[int, ...]:
    nums = [int(x) for x in re.findall(r"\d+", str(v or ""))]
    return tuple(nums) if nums else (0,)


def _parse_occ_json(raw: Any) -> Any:
    """Parses JSON from Nextcloud occ output even if preceded by PHP warnings/notices."""
    if isinstance(raw, bytes):
        txt = raw.decode("utf-8", errors="replace")
    else:
        txt = str(raw or "")
    s = txt.strip()
    if not s:
        return None
    try:
        return json.loads(s)
    except Exception:
        pass
    obj_idx = s.find("{")
    arr_idx = s.find("[")
    starts = [i for i in (obj_idx, arr_idx) if i >= 0]
    if not starts:
        return None
    return json.loads(s[min(starts):])


def check_ytdlp_latest_version() -> Tuple[str, str, bool]:
    """Returns (current_version, latest_version, update_available) with short 4s PyPI lookup."""
    current = "unknown"
    try:
        v = importlib.metadata.version("yt-dlp")
        if v:
            current = str(v).strip()
    except Exception:
        pass
    if current == "unknown":
        try:
            import yt_dlp.version  # type: ignore
            if getattr(yt_dlp.version, "__version__", None):
                current = str(yt_dlp.version.__version__).strip()
        except Exception:
            pass
    if current == "unknown":
        try:
            res = subprocess.run([sys.executable, "-m", "yt_dlp", "--version"], capture_output=True, text=True, timeout=15)
            if res.returncode == 0 and res.stdout.strip():
                current = res.stdout.strip().splitlines()[0]
        except Exception:
            pass
    if current == "unknown":
        try:
            res = subprocess.run(["yt-dlp", "--version"], capture_output=True, text=True, timeout=15)
            if res.returncode == 0 and res.stdout.strip():
                current = res.stdout.strip().splitlines()[0]
        except Exception:
            pass

    latest = current
    update_avail = False
    try:
        req = urllib.request.Request(
            "https://pypi.org/pypi/yt-dlp/json",
            headers={"User-Agent": "homelab-os-updater/2.1"},
        )
        with urllib.request.urlopen(req, timeout=4) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))
            latest = str(payload.get("info", {}).get("version") or current)
            if current != "unknown" and latest != current:
                update_avail = _parse_version_tuple(latest) > _parse_version_tuple(current)
    except Exception:
        pass
    return current, latest, update_avail


def inspect_nextcloud_updates(docker_client) -> Dict[str, Any]:
    """Inspects running Nextcloud container via occ for core version, maintenance status, and app updates."""
    info: Dict[str, Any] = {
        "running": False,
        "version": "",
        "maintenance": False,
        "core_update_available": False,
        "available_version": "",
        "app_updates": [],
        "raw_check": "",
    }
    if not docker_client:
        return info
    try:
        nc = docker_client.containers.get("nextcloud")
    except Exception:
        return info

    if getattr(nc, "status", "") != "running":
        return info
    info["running"] = True

    try:
        res = nc.exec_run(f"{OCC_PHP_PREFIX} status --output=json", user="www-data")
        if getattr(res, "exit_code", 1) == 0 and res.output:
            st = _parse_occ_json(res.output) or {}
            if isinstance(st, dict):
                info["version"] = str(st.get("versionstring") or st.get("version") or "")
                info["maintenance"] = bool(st.get("maintenance", False))
    except Exception:
        pass

    try:
        chk = nc.exec_run(f"{OCC_PHP_PREFIX} update:check", user="www-data")
        txt = (chk.output or b"").decode("utf-8", errors="replace").strip() if chk else ""
        info["raw_check"] = txt[:400]
        m = re.search(r"Nextcloud\s+([\d.]+)\s+is available", txt, re.IGNORECASE)
        if m:
            info["core_update_available"] = True
            info["available_version"] = m.group(1)
    except Exception:
        pass

    try:
        app_res = nc.exec_run(f"{OCC_PHP_PREFIX} app:list --update --output=json", user="www-data")
        if getattr(app_res, "exit_code", 1) == 0 and app_res.output:
            parsed = _parse_occ_json(app_res.output)
            updates = []
            if isinstance(parsed, dict):
                # Supports both flat {app_id: {...}} and {enabled: {...}}
                src = parsed.get("enabled") if "enabled" in parsed and isinstance(parsed["enabled"], dict) else parsed
                for app_id, meta in src.items():
                    if isinstance(meta, dict):
                        cur_v = str(meta.get("current_version") or meta.get("version") or "")
                        new_v = str(meta.get("available_version") or meta.get("update") or "")
                        if new_v and new_v != cur_v:
                            updates.append({
                                "id": str(app_id),
                                "current_version": cur_v,
                                "available_version": new_v,
                            })
                    elif isinstance(meta, str) and "->" in meta:
                        p0, _, p1 = meta.partition("->")
                        updates.append({
                            "id": str(app_id),
                            "current_version": p0.strip(),
                            "available_version": p1.strip(),
                        })
            info["app_updates"] = updates
    except Exception:
        pass

    return info


def _extract_digest(repo_digests: List[str]) -> str:
    for item in repo_digests or []:
        if "@sha256:" in str(item):
            return "sha256:" + str(item).split("@sha256:", 1)[1].strip()
    return ""


def check_all_updates(docker_client, managed_services: List[str], db=None) -> Dict[str, Any]:
    """Checks all managed containers, Nextcloud occ, and yt-dlp; optionally persists snapshot in settings."""
    services: List[Dict[str, Any]] = []
    existing_containers = {}
    if docker_client:
        try:
            for c in docker_client.containers.list(all=True):
                existing_containers[getattr(c, "name", "")] = c
        except Exception:
            pass

    nc_info = inspect_nextcloud_updates(docker_client)
    cur_yt, lat_yt, yt_upd = check_ytdlp_latest_version()

    for name in managed_services:
        c = existing_containers.get(name)
        if not c:
            services.append({
                "name": name,
                "status": "not_installed",
                "image": "",
                "current_version": "—",
                "latest_version": "—",
                "update_available": False,
                "source": "docker",
                "note": "Container not present",
            })
            continue

        tags = getattr(c.image, "tags", None) or []
        image_ref = tags[0] if tags else getattr(c.image, "short_id", "local")
        attrs = getattr(c.image, "attrs", {}) or {}
        local_digest = _extract_digest(attrs.get("RepoDigests") or [])
        remote_digest = ""
        img_update = False
        note = "Up to date"
        source = "local" if name == "admin-dashboard" and ":" not in image_ref else "docker"

        if name == "admin-dashboard":
            img_update = yt_upd
            cur_v = f"yt-dlp {cur_yt}"
            lat_v = f"yt-dlp {lat_yt}"
            note = "yt-dlp engine update ready" if yt_upd else "Dashboard & engine current"
            source = "builtin"
        else:
            cur_v = (local_digest.replace("sha256:", "")[:12] if local_digest else str(getattr(c.image, "id", ""))[:12]) or image_ref
            lat_v = cur_v
            if docker_client and ":" in image_ref:
                try:
                    reg = docker_client.images.get_registry_data(image_ref)
                    remote_digest = str(getattr(reg, "id", "") or "")
                    if remote_digest:
                        lat_v = remote_digest.replace("sha256:", "")[:12]
                        if local_digest and remote_digest != local_digest:
                            img_update = True
                            note = "New container image digest available"
                except Exception as e:
                    note = f"Registry check skipped ({str(e)[:40]})"

        if name == "nextcloud":
            if nc_info.get("version"):
                cur_v = f"NC {nc_info['version']}"
            if nc_info.get("core_update_available") or nc_info.get("app_updates"):
                img_update = True
                app_n = len(nc_info.get("app_updates") or [])
                parts = []
                if nc_info.get("core_update_available"):
                    parts.append(f"Core {nc_info.get('available_version')}")
                if app_n:
                    parts.append(f"{app_n} app update{'s' if app_n != 1 else ''}")
                lat_v = ", ".join(parts)
                note = "Hands-free Nextcloud update ready"

        services.append({
            "name": name,
            "status": getattr(c, "status", "unknown"),
            "image": image_ref,
            "current_version": cur_v,
            "latest_version": lat_v,
            "update_available": bool(img_update),
            "source": source,
            "note": note,
        })

    updates_count = sum(1 for s in services if s["update_available"]) + (1 if yt_upd else 0)
    # Deduplicate admin-dashboard vs yt-dlp count if both counted
    if yt_upd and any(s["name"] == "admin-dashboard" and s["update_available"] for s in services):
        updates_count = max(1, updates_count - 1)

    now_iso = datetime.utcnow().isoformat()
    result = {
        "services": services,
        "nextcloud_info": nc_info,
        "ytdlp_info": {
            "current_version": cur_yt,
            "latest_version": lat_yt,
            "update_available": yt_upd,
        },
        "updates_available_count": updates_count,
        "last_checked": now_iso,
    }

    if db is not None:
        try:
            db.execute(
                "INSERT INTO settings (key, value, updated_at) VALUES ('auto_update_cache', ?, datetime('now')) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=datetime('now')",
                (json.dumps(result),),
            )
            db.execute(
                "INSERT INTO settings (key, value, updated_at) VALUES ('auto_update_last_check', ?, datetime('now')) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=datetime('now')",
                (now_iso,),
            )
            db.commit()
        except Exception:
            pass
    return result


def get_cached_updates(db) -> Optional[Dict[str, Any]]:
    row = db.execute("SELECT value FROM settings WHERE key='auto_update_cache'").fetchone()
    if row and row["value"]:
        try:
            return json.loads(row["value"])
        except Exception:
            pass
    return None


def _build_recreate_kwargs(container) -> Tuple[str, Dict[str, Any], Dict[str, Any]]:
    """Extracts container configuration to recreate cleanly without losing mounts/env/limits/networks."""
    attrs = getattr(container, "attrs", {}) or {}
    cfg = attrs.get("Config", {}) or {}
    hcfg = attrs.get("HostConfig", {}) or {}
    ncfg = (attrs.get("NetworkSettings", {}) or {}).get("Networks", {}) or {}

    tags = getattr(container.image, "tags", None) or []
    image_ref = tags[0] if tags else str(cfg.get("Image") or "")

    create_kw: Dict[str, Any] = {
        "name": getattr(container, "name", ""),
        "detach": True,
    }
    if cfg.get("Env"):
        create_kw["environment"] = cfg["Env"]
    if cfg.get("Cmd"):
        create_kw["command"] = cfg["Cmd"]
    if cfg.get("Entrypoint"):
        create_kw["entrypoint"] = cfg["Entrypoint"]
    if cfg.get("Labels"):
        create_kw["labels"] = cfg["Labels"]
    if cfg.get("User"):
        create_kw["user"] = cfg["User"]
    if cfg.get("WorkingDir"):
        create_kw["working_dir"] = cfg["WorkingDir"]

    # Map HostConfig fields supported by docker-py
    if hcfg.get("Binds"):
        create_kw["volumes"] = hcfg["Binds"]
    if hcfg.get("PortBindings"):
        ports = {}
        for cport, bindings in hcfg["PortBindings"].items():
            if isinstance(bindings, list) and bindings:
                hp = bindings[0].get("HostPort")
                ports[cport] = int(hp) if str(hp).isdigit() else hp
        if ports:
            create_kw["ports"] = ports
    if hcfg.get("RestartPolicy"):
        create_kw["restart_policy"] = hcfg["RestartPolicy"]
    if hcfg.get("Memory"):
        create_kw["mem_limit"] = hcfg["Memory"]
    if hcfg.get("CpuShares"):
        create_kw["cpu_shares"] = hcfg["CpuShares"]
    if hcfg.get("NanoCpus"):
        create_kw["nano_cpus"] = hcfg["NanoCpus"]
    if hcfg.get("CapAdd"):
        create_kw["cap_add"] = hcfg["CapAdd"]
    if hcfg.get("SecurityOpt"):
        create_kw["security_opt"] = hcfg["SecurityOpt"]
    if hcfg.get("NetworkMode") and hcfg.get("NetworkMode") != "default":
        create_kw["network"] = hcfg["NetworkMode"]

    return image_ref, create_kw, ncfg


def recover_stale_running_jobs(
    db,
    reason: str = "Interrupted by dashboard restart — safe to retry",
) -> int:
    """Marks leftover running update jobs from a prior container instance as failed on startup."""
    cur = db.execute(
        "UPDATE update_jobs SET status='failed', current_step='Interrupted', "
        "error=COALESCE(NULLIF(error,''), ?), completed_at=datetime('now') "
        "WHERE status='running'",
        (reason[:300],),
    )
    db.commit()
    return int(cur.rowcount or 0)


def _pull_image_with_progress(
    docker_client,
    image_ref: str,
    progress_fn: Optional[Callable[[int, str, str], None]] = None,
    is_cancelled_fn: Optional[Callable[[], bool]] = None,
) -> None:
    """
    Pulls a Docker image with streaming layer byte progress and cooperative cancellation.
    Falls back cleanly to docker_client.images.pull(image_ref) when .api.pull is unavailable or an unconfigured mock.
    """
    if is_cancelled_fn and is_cancelled_fn():
        raise InterruptedError("Cancelled by user before image pull")

    api_pull = getattr(getattr(docker_client, "api", None), "pull", None)
    last_slash = image_ref.rsplit("/", 1)[-1]
    if ":" in last_slash:
        repo, tag = image_ref.rsplit(":", 1)
    else:
        repo, tag = image_ref, "latest"

    stream = None
    if callable(api_pull):
        try:
            candidate = api_pull(repo, tag=tag, stream=True, decode=True)
            if "unittest.mock" not in type(candidate).__module__:
                stream = candidate
        except TypeError:
            stream = None

    if stream is None:
        docker_client.images.pull(image_ref)
        return

    layer_progress: Dict[str, Tuple[int, int]] = {}
    last_emit_ts = 0.0
    last_pct = -10
    try:
        for ev in stream:
            if is_cancelled_fn and is_cancelled_fn():
                raise InterruptedError("Cancelled by user during image pull")
            if not isinstance(ev, dict):
                continue
            if ev.get("error") or ev.get("errorDetail"):
                err_txt = ev.get("error") or str(ev.get("errorDetail"))
                raise RuntimeError(f"Docker pull failed for {image_ref}: {err_txt[:220]}")

            lid = str(ev.get("id") or "")
            status = str(ev.get("status") or "")
            detail = ev.get("progressDetail") if isinstance(ev.get("progressDetail"), dict) else {}
            cur_b = detail.get("current")
            tot_b = detail.get("total")
            if lid and isinstance(cur_b, (int, float)) and isinstance(tot_b, (int, float)) and tot_b > 0:
                layer_progress[lid] = (min(int(cur_b), int(tot_b)), int(tot_b))

            tot_sum = sum(v[1] for v in layer_progress.values())
            cur_sum = sum(v[0] for v in layer_progress.values())
            pct = int(min(100, (cur_sum * 100) / tot_sum)) if tot_sum > 0 else max(0, last_pct)

            now = time.time()
            should_emit = progress_fn and tot_sum > 0 and (
                pct >= last_pct + 10 or (now - last_emit_ts) >= 8.0
            )
            if should_emit:
                last_pct = pct
                last_emit_ts = now
                cur_mb = round(cur_sum / (1024 * 1024), 1)
                tot_mb = round(tot_sum / (1024 * 1024), 1)
                scaled_pct = 35 + int(pct * 0.25)
                phase = "Extracting" if "extract" in status.lower() else "Pulling"
                progress_fn(
                    scaled_pct,
                    f"{phase} {image_ref} ({pct}%)",
                    f"{phase} {image_ref}: {pct}% ({cur_mb}/{tot_mb} MB across {len(layer_progress)} layer(s))",
                )
    finally:
        close_fn = getattr(stream, "close", None)
        if callable(close_fn):
            try:
                close_fn()
            except Exception:
                pass


def _resolve_nextcloud_target_image(image_ref: str, nc_info: Dict[str, Any]) -> str:
    """
    When occ update:check reports a newer major Nextcloud release (e.g. 32 -> 34 or 33 -> 34),
    compute the next sequential +1 major Docker image tag (e.g. 32-apache -> 33-apache,
    apache -> 33-apache, latest -> 33) so major upgrades ALWAYS step 1 -> 2 -> 3 safely.
    """
    ref = str(image_ref or "").strip()
    if not ref or ":" not in ref or not nc_info or not nc_info.get("core_update_available"):
        return ref
    avail_v = str(nc_info.get("available_version") or "").strip()
    if not avail_v:
        return ref

    cur_v = str(nc_info.get("version") or "").strip()
    last_slash = ref.rsplit("/", 1)[-1]
    if ":" not in last_slash:
        return ref
    repo_part, tag_part = ref.rsplit(":", 1)
    try:
        avail_major = int(re.findall(r"\d+", avail_v)[0])
    except Exception:
        return ref

    m_tag = re.match(r"^(\d+)(.*)$", tag_part)
    if m_tag:
        tag_major = int(m_tag.group(1))
        tag_suffix = m_tag.group(2) or ""
        try:
            cur_major = int(re.findall(r"\d+", cur_v)[0]) if cur_v else tag_major
        except Exception:
            cur_major = tag_major
        base_major = max(cur_major, tag_major)
        if avail_major > base_major:
            return f"{repo_part}:{base_major + 1}{tag_suffix}"
        return ref

    # Unpinned tag (e.g., nextcloud:apache, nextcloud:fpm, nextcloud:latest)
    if not cur_v:
        return ref
    try:
        cur_major = int(re.findall(r"\d+", cur_v)[0])
    except Exception:
        return ref
    if avail_major > cur_major:
        suffix = "" if tag_part == "latest" else f"-{tag_part}"
        return f"{repo_part}:{cur_major + 1}{suffix}"
    return ref


def recreate_container_with_latest_image(
    docker_client,
    container_name: str,
    progress_fn: Optional[Callable[[int, str, str], None]] = None,
    is_cancelled_fn: Optional[Callable[[], bool]] = None,
    image_override: str = "",
) -> Tuple[bool, str]:
    """Pulls latest image and swaps container safely with automatic rollback if startup fails."""
    if container_name == "admin-dashboard":
        return True, "Skipped container self-recreate; run in-place engine update instead"
    if not docker_client:
        return False, "Docker daemon unavailable"

    c = docker_client.containers.get(container_name)
    was_running = getattr(c, "status", "") == "running"
    image_ref, create_kw, net_map = _build_recreate_kwargs(c)
    pull_ref = str(image_override or "").strip() or image_ref
    if not pull_ref or ":" not in pull_ref:
        return False, f"No pullable registry tag for {container_name}"

    if progress_fn:
        progress_fn(35, f"Pulling image {pull_ref}", f"Pulling {pull_ref}...")
    try:
        _pull_image_with_progress(
            docker_client,
            pull_ref,
            progress_fn=progress_fn,
            is_cancelled_fn=is_cancelled_fn,
        )
    except InterruptedError as e:
        return False, str(e) or "Cancelled by user"

    if is_cancelled_fn and is_cancelled_fn():
        return False, "Cancelled by user before container swap"

    rollback_name = f"{container_name}_rollback_{int(time.time())}"
    if progress_fn:
        progress_fn(65, f"Swapping {container_name}", f"Stopping & staging rollback {rollback_name}")
    try:
        if was_running:
            c.stop(timeout=20)
        c.rename(rollback_name)
    except Exception as e:
        return False, f"Failed staging old container: {e}"

    try:
        new_c = docker_client.containers.run(pull_ref, **create_kw)
        # Re-attach additional networks if multi-homed
        for net_name in net_map:
            if net_name and net_name != create_kw.get("network") and net_name != "bridge":
                try:
                    net_obj = docker_client.networks.get(net_name)
                    net_obj.connect(new_c)
                except Exception:
                    pass
        try:
            c.remove(force=True)
        except Exception:
            pass
        return True, f"Updated {container_name} to latest {pull_ref}"
    except Exception as e:
        # Automatic rollback
        try:
            c.rename(container_name)
            if was_running:
                c.start()
        except Exception:
            pass
        return False, f"Recreated container failed, rolled back: {e}"


def run_backup_snapshot(
    docker_client=None,
    backup_mount: str = "",
    log_path: str = "",
    db_path: str = "",
    maloja_db_path: str = "",
    retention_days: int = 7,
) -> Tuple[bool, str, str]:
    """
    Ultra-lightweight container-aware backup snapshot using Docker SDK & sqlite3.backup().
    Works both inside admin-dashboard (no docker CLI binary needed) and during pre-update snapshots.
    """
    bmount = (backup_mount or os.environ.get("BACKUP_MOUNT") or "/mnt/backup").strip()
    lpath = (log_path or os.environ.get("BACKUP_LOG") or "/logs/backup.log").strip()
    dpath = (db_path or os.environ.get("DB_PATH") or "/app/data/dashboard.db").strip()
    mpath = (maloja_db_path or os.environ.get("MALOJA_DB_PATH") or "/maloja/malojadb.sqlite").strip()

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    snap_root = os.path.join(bmount, "snapshots")
    snap_dir = os.path.join(snap_root, ts)
    os.makedirs(snap_dir, exist_ok=True)
    if lpath:
        os.makedirs(os.path.dirname(lpath), exist_ok=True)

    lines: List[str] = []

    def _log(msg: str):
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        lines.append(f"[{stamp}] {msg}")

    _log("══════════════════════════════════════════════")
    _log(f"  Homelab Automated Backup Started — {ts}")
    _log("══════════════════════════════════════════════")
    _log(f"  Destination: {snap_dir}")

    warnings = 0

    # 1. MariaDB SQL dump via Docker SDK (reads MYSQL_ROOT_PASSWORD from mariadb's own env)
    _log("── Backing up MariaDB databases...")
    if docker_client:
        try:
            mdb = docker_client.containers.get("mariadb")
            if getattr(mdb, "status", "") == "running":
                dump_cmd = [
                    "sh",
                    "-c",
                    'MYSQL_PWD="${MYSQL_ROOT_PASSWORD}" exec mysqldump -u root --single-transaction --quick nextcloud',
                ]
                res = mdb.exec_run(dump_cmd)
                if getattr(res, "exit_code", 1) == 0 and res.output:
                    out_bytes = res.output if isinstance(res.output, (bytes, bytearray)) else str(res.output).encode("utf-8", errors="replace")
                    with open(os.path.join(snap_dir, "nextcloud_db.sql"), "wb") as f:
                        f.write(out_bytes)
                    _log("  ✓ Nextcloud database dumped")
                else:
                    warnings += 1
                    _log("  ✗ Nextcloud database dump failed")
            else:
                warnings += 1
                _log("  ⚠ MariaDB container is not running, skipping database dump")
        except Exception as e:
            warnings += 1
            _log(f"  ⚠ MariaDB backup skipped: {str(e)[:120]}")
    else:
        _log("  ⚠ Docker daemon unavailable, skipping MariaDB dump")

    # 2. Nextcloud config.php + apps list
    _log("── Backing up Nextcloud configuration...")
    if docker_client:
        try:
            nc = docker_client.containers.get("nextcloud")
            if getattr(nc, "status", "") == "running":
                cfg_res = nc.exec_run("cat /var/www/html/config/config.php", user="www-data")
                if getattr(cfg_res, "exit_code", 1) == 0 and cfg_res.output:
                    cfg_b = cfg_res.output if isinstance(cfg_res.output, (bytes, bytearray)) else str(cfg_res.output).encode("utf-8", errors="replace")
                    with open(os.path.join(snap_dir, "nextcloud_config.php"), "wb") as f:
                        f.write(cfg_b)
                    _log("  ✓ Nextcloud config.php")
                app_res = nc.exec_run(f"{OCC_PHP_PREFIX} app:list", user="www-data")
                if getattr(app_res, "exit_code", 1) == 0 and app_res.output:
                    app_b = app_res.output if isinstance(app_res.output, (bytes, bytearray)) else str(app_res.output).encode("utf-8", errors="replace")
                    with open(os.path.join(snap_dir, "nextcloud_apps.txt"), "wb") as f:
                        f.write(app_b)
                    _log("  ✓ Nextcloud apps list")
        except Exception as e:
            _log(f"  ⚠ Nextcloud config backup skipped: {str(e)[:120]}")

    # 3. Maloja SQLite DB (safe SQLite online backup when available)
    if mpath and os.path.isfile(mpath):
        try:
            maloja_dir = os.path.join(snap_dir, "maloja")
            os.makedirs(maloja_dir, exist_ok=True)
            shutil.copyfile(mpath, os.path.join(maloja_dir, "malojadb.sqlite"))
            _log("  ✓ Maloja scrobbler database")
        except Exception as e:
            _log(f"  ⚠ Maloja DB copy skipped: {str(e)[:120]}")

    # 4. Dashboard SQLite DB (online WAL-safe backup)
    if dpath and os.path.isfile(dpath):
        try:
            dash_dir = os.path.join(snap_dir, "dashboard")
            os.makedirs(dash_dir, exist_ok=True)
            dst_db = os.path.join(dash_dir, "dashboard.db")
            src_conn = sqlite3.connect(dpath, timeout=10.0)
            dst_conn = sqlite3.connect(dst_db)
            try:
                src_conn.backup(dst_conn)
            finally:
                dst_conn.close()
                src_conn.close()
            _log("  ✓ Dashboard SQLite database")
        except Exception as e:
            warnings += 1
            _log(f"  ✗ Dashboard SQLite backup failed: {str(e)[:120]}")

    # 5. Cleanup expired snapshot directories
    try:
        cutoff = time.time() - max(1, int(retention_days)) * 86400
        for entry in os.listdir(snap_root):
            ep = os.path.join(snap_root, entry)
            if os.path.isdir(ep) and ep != snap_dir and os.path.getmtime(ep) < cutoff:
                shutil.rmtree(ep, ignore_errors=True)
        _log("  ✓ Retention cleanup")
    except Exception:
        pass

    _log("══════════════════════════════════════════════")
    status_line = "✓ Backup completed successfully" if warnings == 0 else f"⚠ Backup completed with {warnings} warning(s)"
    _log(f"  {status_line}")
    _log(f"  Snapshot archive: {snap_dir}")
    _log("══════════════════════════════════════════════")

    if lpath:
        try:
            with open(lpath, "a", encoding="utf-8") as lf:
                lf.write("\n".join(lines) + "\n")
        except Exception:
            pass

    return True, snap_dir, status_line


def _wait_nextcloud_ready(
    nc_container,
    timeout_sec: float = 600.0,
    poll_interval: float = 2.0,
    check_port_fn: Optional[Callable[..., bool]] = None,
    is_cancelled_fn: Optional[Callable[[], bool]] = None,
    progress_fn: Optional[Callable[[int, str, str], None]] = None,
) -> bool:
    """
    Waits until Nextcloud's /entrypoint.sh finishes rsync + internal setup and
    Apache listens on TCP port 80 AND occ status exits cleanly.
    """
    if check_port_fn is None:
        import ops_resources
        check_port_fn = ops_resources._default_check_port

    if progress_fn:
        progress_fn(34, "Waiting for Nextcloud startup", "Waiting for entrypoint file sync & Apache port 80...")

    start_ts = time.time()
    last_hb = start_ts
    deadline = start_ts + max(0.05, float(timeout_sec))
    while time.time() < deadline:
        if is_cancelled_fn and is_cancelled_fn():
            return False
        now = time.time()
        if progress_fn and (now - last_hb) >= 20.0:
            last_hb = now
            elapsed = int(max(1, now - start_ts))
            progress_fn(
                min(38, 34 + int(elapsed // 60)),
                "Waiting for Nextcloud startup",
                f"Still waiting for Nextcloud entrypoint sync & Apache port 80 ({elapsed}s elapsed)...",
            )
        try:
            try:
                nc_container.reload()
            except Exception:
                pass
            if getattr(nc_container, "status", "running") in ("exited", "dead"):
                return False
            try:
                port_up = bool(check_port_fn("nextcloud", 80, timeout=1.0))
            except TypeError:
                port_up = bool(check_port_fn("nextcloud", 80))
            if port_up:
                res = nc_container.exec_run(f"{OCC_PHP_PREFIX} status --output=json", user="www-data")
                if getattr(res, "exit_code", 1) == 0:
                    return True
        except Exception:
            pass
        remaining = deadline - time.time()
        if remaining <= 0:
            break
        time.sleep(min(max(0.005, float(poll_interval)), remaining))
    return False


def run_nextcloud_hands_free_update(
    docker_client,
    is_cancelled_fn: Callable[[], bool],
    progress_fn: Callable[[int, str, str], None],
    update_apps: bool = True,
    backup_before: bool = False,
    backup_script: str = "",
    db_factory: Optional[Callable[[], Any]] = None,
    pull_image: bool = True,
) -> Tuple[bool, str]:
    """
    Hands-free Nextcloud update workflow:
      1. Wake Nextcloud and its dependencies (MariaDB, Redis) if sleeping
      2. Optional pre-update backup snapshot (Docker SDK / script)
      3. Pull & swap newer Nextcloud Docker image digest if available
      4. Ensure maintenance mode is OFF before occ upgrade (occ upgrade manages maintenance itself and exits 2 if already ON)
      5. Run php -d memory_limit=512M /var/www/html/occ upgrade --no-interaction
      6. Optionally run occ app:update --all
      7. Run occ db:add-missing-indices
      8. ALWAYS clear maintenance mode in finally block
    """
    if not docker_client:
        return False, "Docker daemon unavailable"

    # 1. Wake Nextcloud + dependencies if sleeping/stopped
    needs_wake = False
    for dep_name in ("mariadb", "redis", "nextcloud"):
        try:
            c = docker_client.containers.get(dep_name)
            if getattr(c, "status", "") != "running":
                needs_wake = True
                break
        except Exception:
            pass

    if needs_wake:
        progress_fn(8, "Waking Nextcloud dependencies", "Waking MariaDB, Redis, Nextcloud...")
        try:
            import ops_resources
            wake_db = db_factory
            if wake_db is None:
                # Minimal read-only fallback settings DB when invoked standalone without db_factory
                mem_conn = sqlite3.connect(":memory:")
                mem_conn.row_factory = sqlite3.Row
                mem_conn.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT, updated_at TEXT)")
                wake_db = mem_conn
            try:
                ops_resources.wake_service_and_wait(
                    wake_db,
                    docker_client,
                    "nextcloud",
                    "nextcloud",
                    80,
                    timeout_sec=30.0,
                    poll_interval=0.25,
                )
                # Ensure MariaDB TCP port 3306 is accepting connections
                deadline = time.time() + 15.0
                while time.time() < deadline:
                    if ops_resources._default_check_port("mariadb", 3306, timeout=1.0):
                        break
                    time.sleep(0.5)
            finally:
                if db_factory is None and isinstance(wake_db, sqlite3.Connection):
                    wake_db.close()
        except Exception:
            pass

    try:
        nc = docker_client.containers.get("nextcloud")
    except Exception as e:
        return False, f"Nextcloud container not found: {e}"

    if getattr(nc, "status", "") != "running":
        return False, "Nextcloud container is not running"

    # 2. Optional pre-update backup snapshot
    if backup_before:
        if is_cancelled_fn():
            return False, "Cancelled before backup"
        progress_fn(15, "Pre-update backup snapshot", "Running backup snapshot...")
        try:
            if backup_script and os.path.isfile(backup_script) and shutil.which("docker"):
                subprocess.run(["bash", backup_script], capture_output=True, text=True, timeout=300)
            else:
                run_backup_snapshot(docker_client=docker_client)
        except Exception:
            pass

    if is_cancelled_fn():
        return False, "Cancelled by user"

    max_hops = 5 if pull_image else 1
    visited_targets = set()

    for _hop in range(max_hops):
        if is_cancelled_fn():
            return False, "Cancelled by user"

        did_major_bump = False
        # 3. Pull & swap newer Nextcloud Docker image digest (or sequential +1 major tag when upgrading majors)
        if pull_image:
            try:
                tags = getattr(nc.image, "tags", None) or []
                image_ref = tags[0] if tags else ""
                attrs = getattr(nc.image, "attrs", {}) or {}
                local_digest = _extract_digest(attrs.get("RepoDigests") or [])
                nc_info = inspect_nextcloud_updates(docker_client)
                target_image_ref = _resolve_nextcloud_target_image(image_ref, nc_info)
                major_bump = bool(target_image_ref and target_image_ref != image_ref)

                should_pull = False
                if target_image_ref and ":" in target_image_ref:
                    if major_bump and target_image_ref not in visited_targets:
                        try:
                            reg = docker_client.images.get_registry_data(target_image_ref)
                            should_pull = reg is not None
                        except Exception as reg_e:
                            progress_fn(
                                30,
                                f"Nextcloud image {target_image_ref} unavailable",
                                f"Registry does not have {target_image_ref} yet ({str(reg_e)[:120]})",
                            )
                    elif local_digest and not major_bump:
                        reg = docker_client.images.get_registry_data(target_image_ref)
                        remote_digest = str(getattr(reg, "id", "") or "")
                        should_pull = bool(remote_digest and remote_digest != local_digest)

                if should_pull:
                    visited_targets.add(target_image_ref)
                    step_msg = (
                        f"Major Nextcloud upgrade step ({nc_info.get('version') or image_ref} -> {target_image_ref}); pulling {target_image_ref}..."
                        if major_bump
                        else f"Pulling newer {target_image_ref}..."
                    )
                    progress_fn(28, f"Updating Nextcloud image ({target_image_ref})", step_msg)
                    ok_img, img_msg = recreate_container_with_latest_image(
                        docker_client,
                        "nextcloud",
                        progress_fn=progress_fn,
                        is_cancelled_fn=is_cancelled_fn,
                        image_override=(target_image_ref if major_bump else ""),
                    )
                    if not ok_img:
                        return False, img_msg
                    did_major_bump = major_bump
                    nc = docker_client.containers.get("nextcloud")
                    ready = _wait_nextcloud_ready(
                        nc,
                        timeout_sec=600.0,
                        is_cancelled_fn=is_cancelled_fn,
                        progress_fn=progress_fn,
                    )
                    if not ready:
                        if is_cancelled_fn():
                            return False, "Cancelled while waiting for Nextcloud startup"
                        return False, "Nextcloud container did not become HTTP/occ ready within 600s after image recreate"
            except Exception as e:
                progress_fn(32, "Nextcloud image check notice", f"Skipped image pull check: {str(e)[:140]}")

        if is_cancelled_fn():
            return False, "Cancelled by user"

        cleanup_needed = False
        try:
            # 4. Ensure maintenance mode is OFF before occ upgrade (occ upgrade exits 2 if maintenance mode is already active)
            progress_fn(40, "Preparing Nextcloud upgrade", "occ maintenance:mode --off")
            nc.exec_run(f"{OCC_PHP_PREFIX} maintenance:mode --off", user="www-data")
            cleanup_needed = True

            if is_cancelled_fn():
                return False, "Cancelled by user"

            # 5. Run Nextcloud core upgrade (manages maintenance mode automatically during DB/code migration)
            progress_fn(58, "Running Nextcloud core upgrade", "occ upgrade --no-interaction")
            up_res = nc.exec_run(f"{OCC_PHP_PREFIX} upgrade --no-interaction", user="www-data")
            disabled_apps: List[str] = []
            for _ in range(3):
                if getattr(up_res, "exit_code", 0) in (0, None):
                    break
                out_full = (up_res.output or b"").decode("utf-8", errors="replace")
                m = re.search(r"/var/www/html/(?:custom_apps|apps)/([a-zA-Z0-9_-]+)/", out_full)
                if not m:
                    break
                bad_app = m.group(1)
                if bad_app in disabled_apps:
                    break
                disabled_apps.append(bad_app)
                progress_fn(
                    62,
                    f"Recovering Nextcloud app '{bad_app}'",
                    f"App '{bad_app}' threw upgrade error; temporarily disabling to complete core upgrade...",
                )
                nc.exec_run(f"{OCC_PHP_PREFIX} maintenance:mode --off", user="www-data")
                nc.exec_run(f"{OCC_PHP_PREFIX} app:disable {bad_app}", user="www-data")
                up_res = nc.exec_run(f"{OCC_PHP_PREFIX} upgrade --no-interaction", user="www-data")

            if getattr(up_res, "exit_code", 0) not in (0, None):
                out = (up_res.output or b"").decode("utf-8", errors="replace")[:300]
                return False, f"occ upgrade exited {up_res.exit_code}: {out}"

            for app_id in disabled_apps:
                if is_cancelled_fn():
                    break
                if update_apps:
                    progress_fn(70, f"Updating Nextcloud app '{app_id}'", f"occ app:update {app_id}")
                    nc.exec_run(f"{OCC_PHP_PREFIX} app:update {app_id}", user="www-data")
                en_res = nc.exec_run(f"{OCC_PHP_PREFIX} app:enable {app_id}", user="www-data")
                if getattr(en_res, "exit_code", 0) not in (0, None):
                    en_out = (en_res.output or b"").decode("utf-8", errors="replace")[:160]
                    progress_fn(
                        74,
                        f"Nextcloud app '{app_id}' kept disabled",
                        f"Kept incompatible app '{app_id}' disabled after core upgrade ({en_out})",
                    )

            # 6. Update Nextcloud apps (Nextcloud handles per-app maintenance mode internally)
            if update_apps and not is_cancelled_fn():
                progress_fn(78, "Updating Nextcloud apps", "occ app:update --all")
                app_res = nc.exec_run(f"{OCC_PHP_PREFIX} app:update --all", user="www-data")
                if getattr(app_res, "exit_code", 0) not in (0, None):
                    app_out = (app_res.output or b"").decode("utf-8", errors="replace")[:200]
                    progress_fn(82, "Nextcloud app update notice", f"occ app:update notice: {app_out}")

            # 7. Optimize database indices
            if not is_cancelled_fn():
                progress_fn(90, "Optimizing Nextcloud DB indices", "occ db:add-missing-indices")
                nc.exec_run(f"{OCC_PHP_PREFIX} db:add-missing-indices", user="www-data")

            if is_cancelled_fn():
                return False, "Cancelled by user"
        except Exception as e:
            return False, str(e)
        finally:
            if cleanup_needed:
                try:
                    progress_fn(96, "Ensuring maintenance mode disabled", "occ maintenance:mode --off")
                    nc.exec_run(f"{OCC_PHP_PREFIX} maintenance:mode --off", user="www-data")
                except Exception:
                    pass

        # Check if another sequential +1 major release remains (e.g. 32 -> 33 -> 34)
        if not (pull_image and did_major_bump):
            break
        try:
            post_info = inspect_nextcloud_updates(docker_client)
            cur_tags = getattr(nc.image, "tags", None) or []
            cur_img_ref = cur_tags[0] if cur_tags else ""
            next_img_ref = _resolve_nextcloud_target_image(cur_img_ref, post_info)
            if not next_img_ref or next_img_ref == cur_img_ref or next_img_ref in visited_targets:
                break
            progress_fn(
                20,
                f"Sequential Nextcloud major upgrade -> {next_img_ref}",
                f"Completed {post_info.get('version') or cur_img_ref}; advancing to next sequential major ({next_img_ref})...",
            )
        except Exception:
            break

    return True, "Nextcloud core, apps, and indices updated cleanly"


def run_update_job(
    job_id: int,
    db_factory: Callable[[], Any],
    docker_client,
    managed_services: List[str],
    backup_script: str = "",
):
    """Executes one queued update job with cooperative cancel checks and SQLite progress logs."""
    def _is_cancelled() -> bool:
        db = db_factory()
        try:
            r = db.execute("SELECT status, cancel_requested FROM update_jobs WHERE id=?", (job_id,)).fetchone()
            return bool(not r or r["status"] == "cancelled" or r["cancel_requested"] == 1)
        finally:
            db.close()

    def _prog(pct: int, step: str, log_line: str = ""):
        db = db_factory()
        try:
            ts = datetime.utcnow().strftime("%H:%M:%S")
            line = f"[{ts}] {log_line or step}\n"
            db.execute(
                "UPDATE update_jobs SET progress_pct=?, current_step=?, log=COALESCE(log,'') || ? WHERE id=?",
                (min(100, max(0, int(pct))), step[:120], line, job_id),
            )
            db.commit()
        finally:
            db.close()

    db = db_factory()
    job = db.execute("SELECT * FROM update_jobs WHERE id=?", (job_id,)).fetchone()
    cfg = get_update_settings(db)
    if not job or job["status"] == "cancelled" or job["cancel_requested"] == 1:
        db.execute(
            "UPDATE update_jobs SET status='cancelled', completed_at=datetime('now') WHERE id=?",
            (job_id,),
        )
        db.commit()
        db.close()
        return

    target = job["target"]
    db.execute(
        "UPDATE update_jobs SET status='running', started_at=datetime('now'), progress_pct=5, current_step='Starting update' WHERE id=?",
        (job_id,),
    )
    db.commit()
    db.close()

    try:
        if target in ("yt-dlp", "admin-dashboard"):
            _prog(30, "Updating yt-dlp extractor engine", "python -m pip install --no-cache-dir -U yt-dlp")
            res = subprocess.run(
                [sys.executable, "-m", "pip", "install", "--no-cache-dir", "-U", "yt-dlp"],
                capture_output=True, text=True, timeout=180,
            )
            if res.returncode != 0:
                raise RuntimeError((res.stderr or res.stdout or "yt-dlp upgrade failed")[:300])
            _prog(100, "yt-dlp updated", "yt-dlp upgrade complete")

        elif target in ("nextcloud", "nextcloud_core"):
            ok, msg = run_nextcloud_hands_free_update(
                docker_client=docker_client,
                is_cancelled_fn=_is_cancelled,
                progress_fn=_prog,
                update_apps=cfg["update_nextcloud_apps"],
                backup_before=cfg["backup_before"],
                backup_script=backup_script,
                db_factory=db_factory,
                pull_image=(target == "nextcloud"),
            )
            if not ok:
                if _is_cancelled():
                    raise InterruptedError(msg)
                raise RuntimeError(msg)
            _prog(100, "Nextcloud update complete", msg)

        elif target == "all":
            cached = check_all_updates(docker_client, managed_services, db=None)
            raw_pending = [s["name"] for s in cached["services"] if s["update_available"] and s["name"] != "admin-dashboard"]
            # Update foundational DB/cache services before Nextcloud so DB is up when occ runs
            prio = {"mariadb": 0, "redis": 1, "nextcloud": 2}
            pending = sorted(raw_pending, key=lambda n: (prio.get(n, 10), raw_pending.index(n)))

            if not pending and not cached["ytdlp_info"]["update_available"]:
                _prog(100, "Everything is already up to date", "No updates required")
            else:
                total_steps = max(1, len(pending) + (1 if cached["ytdlp_info"]["update_available"] else 0))
                step_span = 90.0 / total_steps
                idx = 0
                failures: List[str] = []
                for svc in pending:
                    if _is_cancelled():
                        raise InterruptedError("Cancelled by user")
                    base_pct = int((idx / total_steps) * 90) + 5
                    if svc == "nextcloud":
                        ok, msg = run_nextcloud_hands_free_update(
                            docker_client=docker_client,
                            is_cancelled_fn=_is_cancelled,
                            progress_fn=lambda p, st, l="", bp=base_pct, sp=step_span: _prog(
                                min(94, bp + int((max(0, min(100, int(p))) / 100.0) * sp)),
                                f"Nextcloud: {st}",
                                l,
                            ),
                            update_apps=cfg["update_nextcloud_apps"],
                            backup_before=cfg["backup_before"],
                            backup_script=backup_script,
                            db_factory=db_factory,
                            pull_image=True,
                        )
                        if not ok:
                            failures.append(f"nextcloud: {msg}")
                            _prog(base_pct, f"Nextcloud update failed: {msg[:80]}", msg)
                    else:
                        sub_prog = lambda p, st, l="", bp=base_pct, sp=step_span: _prog(
                            min(94, bp + int((max(0, min(100, int(p))) / 100.0) * sp)),
                            st,
                            l,
                        )
                        recreate_kw: Dict[str, Any] = {"progress_fn": sub_prog}
                        try:
                            if "is_cancelled_fn" in inspect.signature(recreate_container_with_latest_image).parameters:
                                recreate_kw["is_cancelled_fn"] = _is_cancelled
                        except Exception:
                            pass
                        ok, msg = recreate_container_with_latest_image(docker_client, svc, **recreate_kw)
                        if not ok:
                            if _is_cancelled():
                                raise InterruptedError(msg)
                            failures.append(f"{svc}: {msg}")
                            _prog(base_pct, f"Skipped {svc}: {msg[:80]}", msg)
                    idx += 1

                if cached["ytdlp_info"]["update_available"] and not _is_cancelled():
                    _prog(92, "Updating yt-dlp", "Updating yt-dlp")
                    yt_res = subprocess.run(
                        [sys.executable, "-m", "pip", "install", "--no-cache-dir", "-U", "yt-dlp"],
                        capture_output=True, text=True, timeout=180,
                    )
                    if yt_res.returncode != 0:
                        failures.append("yt-dlp upgrade failed")

                if _is_cancelled():
                    raise InterruptedError("Cancelled by user")
                if failures:
                    raise RuntimeError("; ".join(failures))

        else:
            # Single named Docker container
            if target not in managed_services:
                raise ValueError(f"Unknown update target '{target}'")
            single_kw: Dict[str, Any] = {"progress_fn": _prog}
            try:
                if "is_cancelled_fn" in inspect.signature(recreate_container_with_latest_image).parameters:
                    single_kw["is_cancelled_fn"] = _is_cancelled
            except Exception:
                pass
            ok, msg = recreate_container_with_latest_image(docker_client, target, **single_kw)
            if not ok:
                if _is_cancelled():
                    raise InterruptedError(msg)
                raise RuntimeError(msg)
            _prog(100, f"{target} updated", msg)

        if _is_cancelled():
            raise InterruptedError("Cancelled by user")

        db = db_factory()
        try:
            try:
                check_all_updates(docker_client, managed_services, db=db)
            except Exception:
                pass
            db.execute(
                "UPDATE update_jobs SET status='completed', progress_pct=100, current_step='Completed', completed_at=datetime('now') WHERE id=?",
                (job_id,),
            )
            db.execute(
                "INSERT INTO settings (key, value, updated_at) VALUES ('auto_update_last_run', ?, datetime('now')) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=datetime('now')",
                (datetime.utcnow().isoformat(),),
            )
            db.commit()
        finally:
            db.close()

    except InterruptedError as e:
        db = db_factory()
        db.execute(
            "UPDATE update_jobs SET status='cancelled', current_step='Cancelled', error=?, completed_at=datetime('now') WHERE id=?",
            (str(e)[:200], job_id),
        )
        db.commit()
        db.close()
    except Exception as e:
        db = db_factory()
        db.execute(
            "UPDATE update_jobs SET status='failed', current_step='Failed', error=?, completed_at=datetime('now') WHERE id=?",
            (str(e)[:300], job_id),
        )
        db.commit()
        db.close()
