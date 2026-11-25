#!/usr/bin/env python3
"""
Homelab OS — Memory, CPU & Auto Sleep Engine (Ultra-Low Resource)
Zero extra containers, stdlib + psutil + docker SDK only.
Features:
  - Live host RAM/swap/cache telemetry & per-container limits
  - 1-Click RAM compaction (Python GC + Redis MEMORY PURGE + best-effort drop_caches)
  - Live container memory & CPU limit updates (docker container.update)
  - 1-Click Power Profiles (Eco / Balanced / Performance) + Thermal/CPU auto-throttle state
  - Smart Container Eco-Sleep (pause/stop selectable heavy containers while protecting pihole & admin-dashboard)
  - Scheduled sleep window + idle auto-sleep + optional host S3 suspend capability
"""

import gc
import json
import os
import re
import shutil
import socket
import subprocess
import threading
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

import psutil

PROTECTED_SLEEP_CONTAINERS = {"pihole", "admin-dashboard"}
SLEEPABLE_SERVICES = ["nextcloud", "mariadb", "redis", "navidrome", "maloja", "samba"]
SERVICE_DEPENDENCIES = {"nextcloud": ["mariadb", "redis"]}
# samba lacks a default WakeProxy listener on TCP 445, so exclude it from default auto-sleep targets unless user opts in
DEFAULT_SLEEP_TARGETS = ["nextcloud", "mariadb", "redis", "navidrome", "maloja"]

_req_lock = threading.Lock()
_start_ts = time.time()
_container_last_req: Dict[str, float] = {s: _start_ts for s in SLEEPABLE_SERVICES}
_server_last_req: float = _start_ts
_wake_locks_guard = threading.Lock()
_wake_locks: Dict[str, threading.Lock] = {}


def reset_idle_trackers(now_ts: Optional[float] = None) -> None:
    """Initialize or reset all container and server idle timestamps (used at boot and in tests)."""
    ts = float(now_ts if now_ts is not None else time.time())
    with _req_lock:
        global _server_last_req
        _server_last_req = ts
        for s in SLEEPABLE_SERVICES:
            _container_last_req[s] = ts


def touch_server_request(now_ts: Optional[float] = None) -> None:
    """Record real server-wide request activity (must exclude background auto-poll requests)."""
    ts = float(now_ts if now_ts is not None else time.time())
    with _req_lock:
        global _server_last_req
        if ts > _server_last_req:
            _server_last_req = ts
        else:
            _server_last_req = ts


def touch_container_request(service: str, now_ts: Optional[float] = None) -> None:
    """Record request activity for a service, its internal dependencies, and the server globally."""
    ts = float(now_ts if now_ts is not None else time.time())
    svc = (service or "").strip()
    if not svc:
        return
    with _req_lock:
        global _server_last_req
        _container_last_req[svc] = ts
        for dep in SERVICE_DEPENDENCIES.get(svc, []):
            _container_last_req[dep] = ts
        _server_last_req = ts


def get_server_idle_seconds(now_ts: Optional[float] = None) -> float:
    now = float(now_ts if now_ts is not None else time.time())
    with _req_lock:
        return max(0.0, now - _server_last_req)


def get_container_idle_seconds(service: str, now_ts: Optional[float] = None) -> float:
    now = float(now_ts if now_ts is not None else time.time())
    with _req_lock:
        ts = _container_last_req.get(service, _server_last_req)
        return max(0.0, now - ts)


def _get_wake_lock(service: str) -> threading.Lock:
    with _wake_locks_guard:
        if service not in _wake_locks:
            _wake_locks[service] = threading.Lock()
        return _wake_locks[service]

PROFILE_SHARES = {
    "eco": {
        "pihole": 1024,
        "admin-dashboard": 512,
        "nginx-proxy": 512,
        "redis": 256,
        "samba": 256,
        "mariadb": 256,
        "nextcloud": 256,
        "navidrome": 128,
        "maloja": 128,
    },
    "balanced": {
        "pihole": 1024,
        "nginx-proxy": 768,
        "admin-dashboard": 512,
        "samba": 512,
        "mariadb": 512,
        "redis": 512,
        "nextcloud": 512,
        "navidrome": 256,
        "maloja": 256,
    },
    "performance": {
        "pihole": 1024,
        "nginx-proxy": 768,
        "admin-dashboard": 512,
        "mariadb": 1024,
        "nextcloud": 1024,
        "navidrome": 512,
        "maloja": 384,
        "samba": 512,
        "redis": 512,
    },
}


def _upsert_settings(db, pairs: Dict[str, str]):
    for k, v in pairs.items():
        db.execute(
            "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, datetime('now')) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=datetime('now')",
            (k, str(v)),
        )
    db.commit()


def _get_settings_map(db, keys: Tuple[str, ...]) -> Dict[str, str]:
    rows = db.execute(
        f"SELECT key, value FROM settings WHERE key IN ({','.join('?' * len(keys))})",
        keys,
    ).fetchall()
    return {r["key"]: r["value"] for r in rows}


def get_resource_settings(db) -> Dict[str, Any]:
    smap = _get_settings_map(
        db,
        ("power_profile", "mem_auto_reclaim_pct", "cpu_throttle_pct", "cpu_throttle_temp_c", "download_rate_limit"),
    )
    prof = str(smap.get("power_profile") or "balanced").strip().lower()
    if prof not in PROFILE_SHARES:
        prof = "balanced"
    try:
        reclaim_pct = int(float(smap.get("mem_auto_reclaim_pct") or 88))
    except Exception:
        reclaim_pct = 88
    try:
        cpu_pct = int(float(smap.get("cpu_throttle_pct") or 85))
    except Exception:
        cpu_pct = 85
    try:
        temp_c = int(float(smap.get("cpu_throttle_temp_c") or 80))
    except Exception:
        temp_c = 80
    return {
        "power_profile": prof,
        "mem_auto_reclaim_pct": max(50, min(99, reclaim_pct)),
        "cpu_throttle_pct": max(40, min(99, cpu_pct)),
        "cpu_throttle_temp_c": max(55, min(105, temp_c)),
        "download_rate_limit": str(smap.get("download_rate_limit") or "").strip(),
    }


def save_resource_settings(db, data: Dict[str, Any]) -> Dict[str, Any]:
    cur = get_resource_settings(db)
    prof = str(data.get("power_profile") or cur["power_profile"]).strip().lower()
    if prof not in PROFILE_SHARES:
        prof = cur["power_profile"]

    def _clamped_int(k, lo, hi):
        raw = data.get(k, cur[k])
        try:
            v = int(float(raw))
        except Exception:
            v = cur[k]
        return max(lo, min(hi, v))

    reclaim = _clamped_int("mem_auto_reclaim_pct", 50, 99)
    cpu_thr = _clamped_int("cpu_throttle_pct", 40, 99)
    temp_thr = _clamped_int("cpu_throttle_temp_c", 55, 105)
    rate_lim = str(data.get("download_rate_limit", cur["download_rate_limit"]) or "").strip()
    if rate_lim and not re.match(r"^\d+(?:\.\d+)?[KMGkmg]?$", rate_lim):
        rate_lim = ""

    _upsert_settings(
        db,
        {
            "power_profile": prof,
            "mem_auto_reclaim_pct": str(reclaim),
            "cpu_throttle_pct": str(cpu_thr),
            "cpu_throttle_temp_c": str(temp_thr),
            "download_rate_limit": rate_lim,
        },
    )
    return get_resource_settings(db)


def get_sleep_settings(db) -> Dict[str, Any]:
    smap = _get_settings_map(
        db,
        (
            "eco_sleep_enabled",
            "sleep_mode",
            "sleep_targets",
            "sleep_schedule_enabled",
            "sleep_start",
            "sleep_end",
            "idle_sleep_enabled",
            "idle_minutes",
            "container_idle_sleep_enabled",
            "container_idle_minutes",
            "server_idle_sleep_enabled",
            "server_idle_minutes",
            "wake_all_on_server_wake",
            "wake_timeout_sec",
            "host_sleep_enabled",
            "sleep_active",
        ),
    )

    def _b(key, default=False):
        if key not in smap or smap[key] is None:
            return default
        return str(smap[key]).strip().lower() in ("true", "1", "yes")

    mode = str(smap.get("sleep_mode") or "stop").strip().lower()
    if mode not in ("stop", "pause"):
        mode = "stop"

    targets = list(DEFAULT_SLEEP_TARGETS)
    if smap.get("sleep_targets"):
        try:
            parsed = json.loads(smap["sleep_targets"])
            if isinstance(parsed, list):
                targets = [str(x).strip() for x in parsed if str(x).strip() and str(x).strip() not in PROTECTED_SLEEP_CONTAINERS]
        except Exception:
            pass

    s_start = str(smap.get("sleep_start") or "00:00").strip()
    s_end = str(smap.get("sleep_end") or "07:00").strip()
    try:
        idle_m = max(1, min(720, int(smap.get("idle_minutes") or 60)))
    except Exception:
        idle_m = 60
    try:
        ctr_idle_m = max(1, min(720, int(smap.get("container_idle_minutes") or 15)))
    except Exception:
        ctr_idle_m = 15
    try:
        srv_idle_m = max(1, min(720, int(smap.get("server_idle_minutes") or 30)))
    except Exception:
        srv_idle_m = 30
    try:
        wake_timeout = max(5, min(120, int(smap.get("wake_timeout_sec") or 25)))
    except Exception:
        wake_timeout = 25

    return {
        "eco_sleep_enabled": _b("eco_sleep_enabled", True),
        "sleep_mode": mode,
        "sleep_targets": targets,
        "schedule_enabled": _b("sleep_schedule_enabled", False),
        "sleep_start": s_start,
        "sleep_end": s_end,
        "idle_sleep_enabled": _b("idle_sleep_enabled", False),
        "idle_minutes": idle_m,
        "container_idle_sleep_enabled": _b("container_idle_sleep_enabled", True),
        "container_idle_minutes": ctr_idle_m,
        "server_idle_sleep_enabled": _b("server_idle_sleep_enabled", True),
        "server_idle_minutes": srv_idle_m,
        "wake_all_on_server_wake": _b("wake_all_on_server_wake", False),
        "wake_timeout_sec": wake_timeout,
        "host_sleep_enabled": _b("host_sleep_enabled", False),
        "sleeping_now": _b("sleep_active", False),
    }


def save_sleep_settings(db, data: Dict[str, Any], managed_services: List[str]) -> Dict[str, Any]:
    cur = get_sleep_settings(db)

    def _b(key, default):
        if key not in data or data[key] is None:
            return default
        v = data[key]
        return v if isinstance(v, bool) else str(v).strip().lower() in ("true", "1", "yes")

    mode = str(data.get("sleep_mode") or cur["sleep_mode"]).strip().lower()
    if mode not in ("stop", "pause"):
        mode = cur["sleep_mode"]

    targets = cur["sleep_targets"]
    if "sleep_targets" in data and isinstance(data["sleep_targets"], list):
        targets = [
            str(x).strip()
            for x in data["sleep_targets"]
            if str(x).strip() in managed_services and str(x).strip() not in PROTECTED_SLEEP_CONTAINERS
        ]

    s_start = str(data.get("sleep_start") or cur["sleep_start"]).strip()
    s_end = str(data.get("sleep_end") or cur["sleep_end"]).strip()
    if not re.match(r"^(?:[01]\d|2[0-3]):[0-5]\d$", s_start):
        s_start = cur["sleep_start"]
    if not re.match(r"^(?:[01]\d|2[0-3]):[0-5]\d$", s_end):
        s_end = cur["sleep_end"]

    def _clamped_int(key, lo, hi, fallback):
        if key not in data or data[key] is None or data[key] == "":
            return fallback
        try:
            return max(lo, min(hi, int(data[key])))
        except Exception:
            return fallback

    idle_m = _clamped_int("idle_minutes", 1, 720, cur["idle_minutes"])
    ctr_idle_m = _clamped_int("container_idle_minutes", 1, 720, cur["container_idle_minutes"])
    srv_idle_m = _clamped_int("server_idle_minutes", 1, 720, cur["server_idle_minutes"])
    wake_timeout = _clamped_int("wake_timeout_sec", 5, 120, cur["wake_timeout_sec"])

    _upsert_settings(
        db,
        {
            "eco_sleep_enabled": "true" if _b("eco_sleep_enabled", cur["eco_sleep_enabled"]) else "false",
            "sleep_mode": mode,
            "sleep_targets": json.dumps(targets),
            "sleep_schedule_enabled": "true" if _b("schedule_enabled", cur["schedule_enabled"]) else "false",
            "sleep_start": s_start,
            "sleep_end": s_end,
            "idle_sleep_enabled": "true" if _b("idle_sleep_enabled", cur["idle_sleep_enabled"]) else "false",
            "idle_minutes": str(idle_m),
            "container_idle_sleep_enabled": "true" if _b("container_idle_sleep_enabled", cur["container_idle_sleep_enabled"]) else "false",
            "container_idle_minutes": str(ctr_idle_m),
            "server_idle_sleep_enabled": "true" if _b("server_idle_sleep_enabled", cur["server_idle_sleep_enabled"]) else "false",
            "server_idle_minutes": str(srv_idle_m),
            "wake_all_on_server_wake": "true" if _b("wake_all_on_server_wake", cur["wake_all_on_server_wake"]) else "false",
            "wake_timeout_sec": str(wake_timeout),
            "host_sleep_enabled": "true" if _b("host_sleep_enabled", cur["host_sleep_enabled"]) else "false",
        },
    )
    return get_sleep_settings(db)


def is_in_sleep_window(start_hhmm: str, end_hhmm: str, now_dt: Optional[datetime] = None) -> bool:
    """Evaluates whether now_dt falls inside [start_hhmm, end_hhmm), supporting overnight wrap."""
    try:
        sh, sm = [int(x) for x in start_hhmm.split(":", 1)]
        eh, em = [int(x) for x in end_hhmm.split(":", 1)]
    except Exception:
        return False
    now = now_dt or datetime.now()
    now_m = now.hour * 60 + now.minute
    start_m = sh * 60 + sm
    end_m = eh * 60 + em
    if start_m == end_m:
        return False
    if start_m < end_m:
        return start_m <= now_m < end_m
    return now_m >= start_m or now_m < end_m


def collect_resource_status(db, docker_client, container_cache: List[Dict[str, Any]], managed_services: List[str]) -> Dict[str, Any]:
    settings = get_resource_settings(db)
    sleep_cfg = get_sleep_settings(db)

    mem = psutil.virtual_memory()
    try:
        swap = psutil.swap_memory()
        swap_total_mb = round(swap.total / 1048576, 1)
        swap_used_mb = round(swap.used / 1048576, 1)
        swap_pct = round(swap.percent, 1)
    except Exception:
        swap_total_mb = swap_used_mb = swap_pct = 0.0

    cpu_pct = round(psutil.cpu_percent(interval=0.1), 1)
    freq_ghz = None
    try:
        f = psutil.cpu_freq()
        freq_ghz = round(f.current / 1000.0, 2) if f else None
    except Exception:
        pass
    try:
        load_avg = [round(x, 2) for x in os.getloadavg()]
    except Exception:
        load_avg = [0.0, 0.0, 0.0]

    max_temp = None
    try:
        raw_t = psutil.sensors_temperatures() or {}
        vals = [e.current for entries in raw_t.values() for e in entries if getattr(e, "current", None)]
        if vals:
            max_temp = round(max(vals), 1)
    except Exception:
        pass

    throttled = bool(
        cpu_pct >= settings["cpu_throttle_pct"]
        or (max_temp is not None and max_temp >= settings["cpu_throttle_temp_c"])
    )

    cache_map = {c.get("name"): c for c in (container_cache or []) if isinstance(c, dict)}
    containers_out: List[Dict[str, Any]] = []
    if docker_client:
        try:
            for c in docker_client.containers.list(all=True):
                name = getattr(c, "name", "")
                if name not in managed_services:
                    continue
                attrs = getattr(c, "attrs", {}) or {}
                hcfg = attrs.get("HostConfig", {}) or {}
                mem_lim_b = int(hcfg.get("Memory") or 0)
                cpu_shares = int(hcfg.get("CpuShares") or 512)
                nano_cpus = int(hcfg.get("NanoCpus") or 0)
                if nano_cpus > 0:
                    cpu_quota_pct = round(nano_cpus / 10_000_000, 0)
                else:
                    cq = int(hcfg.get("CpuQuota") or 0)
                    cp = int(hcfg.get("CpuPeriod") or 100000) or 100000
                    cpu_quota_pct = round((cq / cp) * 100, 0) if cq > 0 else 0

                cached = cache_map.get(name, {})
                st = getattr(c, "status", cached.get("status", "unknown"))
                containers_out.append({
                    "name": name,
                    "status": st,
                    "mem_mb": cached.get("mem_mb", 0.0),
                    "mem_limit_mb": round(mem_lim_b / 1048576, 0) if mem_lim_b > 0 else 0,
                    "cpu_percent": cached.get("cpu_percent", 0.0),
                    "cpu_shares": cpu_shares,
                    "cpu_quota_pct": int(cpu_quota_pct),
                    "protected": name in PROTECTED_SLEEP_CONTAINERS,
                    "sleeping": st in ("paused", "exited") and name in sleep_cfg["sleep_targets"],
                })
        except Exception:
            pass
    containers_out.sort(key=lambda x: x["name"])

    return {
        "memory": {
            "total_mb": round(mem.total / 1048576, 1),
            "used_mb": round(mem.used / 1048576, 1),
            "available_mb": round(mem.available / 1048576, 1),
            "cached_mb": round(getattr(mem, "cached", 0) / 1048576, 1),
            "buffers_mb": round(getattr(mem, "buffers", 0) / 1048576, 1),
            "percent": round(mem.percent, 1),
            "swap_total_mb": swap_total_mb,
            "swap_used_mb": swap_used_mb,
            "swap_percent": swap_pct,
        },
        "cpu": {
            "percent": cpu_pct,
            "count": psutil.cpu_count() or 1,
            "freq_ghz": freq_ghz,
            "load_avg": load_avg,
            "max_temp_c": max_temp,
            "throttled": throttled,
        },
        "profile": settings["power_profile"],
        "settings": settings,
        "containers": containers_out,
        "sleep": {
            **sleep_cfg,
            "sleeping_containers": [c["name"] for c in containers_out if c["sleeping"]],
        },
    }


def compact_memory(docker_client=None) -> Dict[str, Any]:
    """Reclaims Python GC memory, purges Redis fragmented memory if running, and drops page cache if writable."""
    before = psutil.virtual_memory()
    before_mb = round(before.used / 1048576, 1)
    actions = []

    collected = gc.collect()
    actions.append(f"gc.collect ({collected} objects)")

    if docker_client:
        try:
            r = docker_client.containers.get("redis")
            if getattr(r, "status", "") == "running":
                pw = os.environ.get("REDIS_PASSWORD", "").strip()
                cmd = f"redis-cli -a {pw} MEMORY PURGE" if pw else "redis-cli MEMORY PURGE"
                r.exec_run(cmd)
                actions.append("redis MEMORY PURGE")
        except Exception:
            pass

    if os.access("/proc/sys/vm/drop_caches", os.W_OK):
        try:
            with open("/proc/sys/vm/drop_caches", "w") as f:
                f.write("1\n")
            actions.append("kernel drop_caches=1")
        except Exception:
            pass

    after = psutil.virtual_memory()
    after_mb = round(after.used / 1048576, 1)
    freed_mb = round(max(0.0, before_mb - after_mb), 1)
    return {
        "ok": True,
        "before_mb": before_mb,
        "after_mb": after_mb,
        "freed_mb": freed_mb,
        "actions": actions,
    }


def apply_power_profile(db, docker_client, profile: str) -> Tuple[bool, str, List[str]]:
    prof = (profile or "").strip().lower()
    if prof not in PROFILE_SHARES:
        return False, f"Invalid profile '{profile}' (use eco, balanced, or performance)", []
    _upsert_settings(db, {"power_profile": prof})
    updated = []
    shares_map = PROFILE_SHARES[prof]
    if docker_client:
        for name, shares in shares_map.items():
            try:
                c = docker_client.containers.get(name)
                c.update(cpu_shares=shares)
                updated.append(name)
            except Exception:
                pass
    return True, f"Applied '{prof}' power profile", updated


def update_container_limits(
    docker_client,
    name: str,
    mem_limit_mb: Optional[int] = None,
    cpu_shares: Optional[int] = None,
    cpu_quota_pct: Optional[int] = None,
) -> Tuple[bool, str, Dict[str, Any]]:
    if not docker_client:
        return False, "Docker daemon unavailable", {}

    kwargs: Dict[str, Any] = {}
    out: Dict[str, Any] = {"name": name}

    if mem_limit_mb is not None:
        m = int(mem_limit_mb)
        if m != 0 and m < 32:
            return False, "mem_limit_mb must be 0 (unlimited) or >= 32 MB", {}
        if m > 0:
            kwargs["mem_limit"] = m * 1024 * 1024
        out["mem_limit_mb"] = m

    if cpu_shares is not None:
        cs = int(cpu_shares)
        if cs < 2 or cs > 262144:
            return False, "cpu_shares must be between 2 and 262144", {}
        kwargs["cpu_shares"] = cs
        out["cpu_shares"] = cs

    if cpu_quota_pct is not None:
        cq = int(cpu_quota_pct)
        if cq < 0 or cq > 400:
            return False, "cpu_quota_pct must be between 0 and 400", {}
        kwargs["nano_cpus"] = cq * 10_000_000
        out["cpu_quota_pct"] = cq

    if not kwargs:
        return False, "No valid limit fields provided", {}

    try:
        c = docker_client.containers.get(name)
        c.update(**kwargs)
        return True, f"Updated limits for {name}", out
    except Exception as e:
        return False, str(e), {}


def _sleep_one_container(docker_client, name: str, mode: str) -> bool:
    try:
        c = docker_client.containers.get(name)
        if getattr(c, "status", "") == "running":
            if mode == "pause":
                c.pause()
            else:
                c.stop(timeout=15)
            return True
    except Exception:
        pass
    return False


def _wake_one_container(docker_client, name: str) -> bool:
    try:
        c = docker_client.containers.get(name)
        try:
            c.reload()
        except Exception:
            pass
        st = getattr(c, "status", "")
        if st == "paused":
            c.unpause()
            return True
        elif st in ("exited", "created", "stopped"):
            c.start()
            return True
    except Exception:
        pass
    return False


def _default_check_port(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def get_idle_telemetry(
    managed_services: List[str],
    now_ts: Optional[float] = None,
    docker_client=None,
    sleep_targets: Optional[List[str]] = None,
) -> Dict[str, Any]:
    now = float(now_ts if now_ts is not None else time.time())
    targets = set(sleep_targets if sleep_targets is not None else DEFAULT_SLEEP_TARGETS)
    status_map: Dict[str, str] = {}
    if docker_client:
        try:
            for c in docker_client.containers.list(all=True):
                status_map[getattr(c, "name", "")] = getattr(c, "status", "unknown")
        except Exception:
            pass

    containers_idle: Dict[str, Dict[str, Any]] = {}
    with _req_lock:
        srv_ts = _server_last_req
        req_copy = dict(_container_last_req)

    for svc in SLEEPABLE_SERVICES:
        if managed_services and svc not in managed_services:
            continue
        ts = req_copy.get(svc, srv_ts)
        idle_s = max(0.0, now - ts)
        st = status_map.get(svc, "unknown")
        containers_idle[svc] = {
            "service": svc,
            "status": st,
            "sleeping": st in ("paused", "exited", "stopped") and svc in targets,
            "idle_seconds": round(idle_s, 1),
            "idle_minutes": round(idle_s / 60.0, 1),
            "last_request_iso": datetime.utcfromtimestamp(ts).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "dependencies": SERVICE_DEPENDENCIES.get(svc, []),
            "target": svc in targets,
        }

    return {
        "server_idle_seconds": round(max(0.0, now - srv_ts), 1),
        "server_idle_minutes": round(max(0.0, now - srv_ts) / 60.0, 1),
        "server_last_request_iso": datetime.utcfromtimestamp(srv_ts).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "containers": containers_idle,
    }


def apply_container_sleep(db, docker_client, mode: Optional[str] = None, targets: Optional[List[str]] = None) -> Tuple[bool, str, List[str]]:
    if not docker_client:
        return False, "Docker daemon unavailable", []
    cfg = get_sleep_settings(db)
    use_mode = (mode or cfg["sleep_mode"]).lower()
    if use_mode not in ("stop", "pause"):
        use_mode = "stop"
    use_targets = [
        t for t in (targets if targets is not None else cfg["sleep_targets"])
        if t not in PROTECTED_SLEEP_CONTAINERS
    ]
    affected = []
    for name in use_targets:
        if _sleep_one_container(docker_client, name, use_mode):
            affected.append(name)
    if targets is None or set(use_targets) >= set(cfg.get("sleep_targets") or []):
        _upsert_settings(db, {"sleep_active": "true"})
    return True, f"Eco-Sleep ({use_mode}) applied to {len(affected)} service(s)", affected


def wake_sleeping_containers(db, docker_client, targets: Optional[List[str]] = None) -> Tuple[bool, str, List[str]]:
    if not docker_client:
        return False, "Docker daemon unavailable", []
    cfg = get_sleep_settings(db)
    raw_targets = list(targets if targets is not None else cfg["sleep_targets"])
    # Bring up infrastructure dependencies first (mariadb/redis before nextcloud)
    order = ["mariadb", "redis", "samba", "navidrome", "maloja", "nextcloud"]
    ordered = [x for x in order if x in raw_targets] + [x for x in raw_targets if x not in order]

    woken = []
    for name in ordered:
        if _wake_one_container(docker_client, name):
            woken.append(name)
            touch_container_request(name)
    _upsert_settings(db, {"sleep_active": "false"})
    return True, f"Woke {len(woken)} service(s)", woken


def recover_untargeted_sleeping_containers(db, docker_client) -> List[str]:
    """
    On startup (or after removing a service from sleep_targets), automatically wake
    any sleepable service (e.g. samba) that is stopped/paused without being an active sleep target.
    """
    if not docker_client:
        return []
    cfg = get_sleep_settings(db)
    targets = set(cfg.get("sleep_targets") or [])
    woken: List[str] = []
    for svc in SLEEPABLE_SERVICES:
        if svc in targets or svc in PROTECTED_SLEEP_CONTAINERS:
            continue
        if _wake_one_container(docker_client, svc):
            touch_container_request(svc)
            woken.append(svc)
    return woken


def wake_service_and_wait(
    db,
    docker_client,
    service: str,
    target_host: str = "",
    target_port: int = 0,
    timeout_sec: Optional[float] = None,
    check_port_fn: Optional[Callable[[str, int], bool]] = None,
    poll_interval: float = 0.25,
) -> Tuple[bool, str, List[str]]:
    """
    Single-flight wake for a service and its dependencies (e.g. mariadb -> redis -> nextcloud),
    waiting until target_host:target_port accepts TCP connections (if provided).
    `db` may be an open sqlite3.Connection or a callable db_factory returning one (thread-safe).
    """
    touch_container_request(service)
    if not docker_client:
        return False, "Docker daemon unavailable", []

    own_db = callable(db)
    conn = db() if own_db else db
    try:
        cfg = get_sleep_settings(conn)
    finally:
        if own_db and conn is not None:
            try:
                conn.close()
            except Exception:
                pass

    wait_budget = float(timeout_sec if timeout_sec is not None else cfg.get("wake_timeout_sec", 25))
    probe = check_port_fn or _default_check_port

    with _get_wake_lock(service):
        touch_container_request(service)
        woken: List[str] = []

        loop_conn = db() if own_db else db
        try:
            if cfg.get("wake_all_on_server_wake") and cfg.get("sleeping_now"):
                _, _, all_woken = wake_sleeping_containers(loop_conn, docker_client)
                woken.extend(all_woken)
            else:
                deps = [d for d in SERVICE_DEPENDENCIES.get(service, []) if d not in PROTECTED_SLEEP_CONTAINERS]
                for dep in deps:
                    if _wake_one_container(docker_client, dep):
                        woken.append(dep)
                if _wake_one_container(docker_client, service):
                    woken.append(service)
                _upsert_settings(loop_conn, {"sleep_active": "false"})
        finally:
            if own_db and loop_conn is not None:
                try:
                    loop_conn.close()
                except Exception:
                    pass

        if target_host and target_port:
            deadline = time.time() + max(0.5, wait_budget)
            ready = False
            while time.time() < deadline:
                if probe(target_host, int(target_port)):
                    ready = True
                    break
                time.sleep(max(0.005, float(poll_interval)))
            if not ready:
                return False, f"Timed out waiting for {service} ({target_host}:{target_port})", woken

        return True, f"{service} ready", woken


def evaluate_idle_sleep(
    db,
    docker_client,
    busy: bool = False,
    now_ts: Optional[float] = None,
    now_dt: Optional[datetime] = None,
) -> Dict[str, Any]:
    """
    Two-tier auto-sleep evaluator:
      1. Schedule window or server-wide idle timeout -> sleeps all targets + sets sleep_active=true.
      2. Per-container idle timeout -> sleeps individual idle targets, and sleeps mariadb/redis once no dependent is running.
    """
    now = float(now_ts if now_ts is not None else time.time())
    cfg = get_sleep_settings(db)
    if not cfg.get("eco_sleep_enabled") or not docker_client or busy:
        return {"slept": [], "woken": [], "reason": "skipped", "server_idle_sleep": False}

    use_mode = cfg.get("sleep_mode", "stop")
    targets = [t for t in cfg.get("sleep_targets", []) if t not in PROTECTED_SLEEP_CONTAINERS]
    if not targets:
        return {"slept": [], "woken": [], "reason": "no_targets", "server_idle_sleep": False}

    status_map: Dict[str, str] = {}
    try:
        for c in docker_client.containers.list(all=True):
            status_map[getattr(c, "name", "")] = getattr(c, "status", "unknown")
    except Exception:
        pass
    for t in targets:
        if t not in status_map:
            try:
                status_map[t] = getattr(docker_client.containers.get(t), "status", "unknown")
            except Exception:
                pass

    in_window = cfg.get("schedule_enabled") and is_in_sleep_window(
        cfg.get("sleep_start", "00:00"), cfg.get("sleep_end", "07:00"), now_dt=now_dt
    )
    server_idle_s = get_server_idle_seconds(now)
    server_idle_due = (
        (cfg.get("server_idle_sleep_enabled") and server_idle_s >= cfg.get("server_idle_minutes", 30) * 60.0)
        or (cfg.get("idle_sleep_enabled") and server_idle_s >= cfg.get("idle_minutes", 60) * 60.0)
    )

    # 1. Server-wide sleep (either scheduled night window OR server-wide idle timeout)
    if in_window or server_idle_due:
        slept = []
        for t in targets:
            if status_map.get(t) == "running" and _sleep_one_container(docker_client, t, use_mode):
                slept.append(t)
                status_map[t] = "paused" if use_mode == "pause" else "exited"
        if not cfg.get("sleeping_now"):
            _upsert_settings(db, {"sleep_active": "true"})
        return {
            "slept": slept,
            "woken": [],
            "reason": "schedule" if in_window else f"server_idle_{int(server_idle_s // 60)}m",
            "server_idle_sleep": True,
        }

    # 2. Schedule exited window -> restore if server was sleeping for schedule
    if cfg.get("sleeping_now") and cfg.get("schedule_enabled") and not in_window:
        _, _, woken = wake_sleeping_containers(db, docker_client, targets=targets)
        return {"slept": [], "woken": woken, "reason": "schedule_wake", "server_idle_sleep": False}

    # 3. Per-container independent idle sleep
    if not cfg.get("container_idle_sleep_enabled"):
        return {"slept": [], "woken": [], "reason": "active", "server_idle_sleep": False}

    ctr_threshold_s = cfg.get("container_idle_minutes", 15) * 60.0
    dep_services = {d for deps in SERVICE_DEPENDENCIES.values() for d in deps}

    slept: List[str] = []
    # First sleep primary / leaf containers
    for t in targets:
        if t in dep_services:
            continue
        if status_map.get(t) == "running" and get_container_idle_seconds(t, now) >= ctr_threshold_s:
            if _sleep_one_container(docker_client, t, use_mode):
                slept.append(t)
                status_map[t] = "paused" if use_mode == "pause" else "exited"

    # Then sleep shared dependency containers (mariadb, redis) ONLY if no dependent container is running
    for dep in [t for t in targets if t in dep_services]:
        if status_map.get(dep) != "running":
            continue
        dependents = [svc for svc, deps in SERVICE_DEPENDENCIES.items() if dep in deps]
        any_dep_running = any(status_map.get(d) == "running" for d in dependents)
        if not any_dep_running and get_container_idle_seconds(dep, now) >= ctr_threshold_s:
            if _sleep_one_container(docker_client, dep, use_mode):
                slept.append(dep)
                status_map[dep] = "paused" if use_mode == "pause" else "exited"

    return {
        "slept": slept,
        "woken": [],
        "reason": "container_idle" if slept else "active",
        "server_idle_sleep": False,
    }


def trigger_host_sleep(wake_minutes: int = 0) -> Tuple[bool, bool, str]:
    """
    Optional Host System S3 Suspend (only works if host systemd/rtcwake/sysfs is exposed).
    Returns: (ok, supported, message)
    """
    try:
        mins = max(0, int(wake_minutes or 0))
    except Exception:
        mins = 0

    if mins > 0 and shutil.which("rtcwake"):
        try:
            subprocess.Popen(["rtcwake", "-m", "mem", "-s", str(mins * 60)])
            return True, True, f"Host scheduled S3 sleep for {mins} minute(s)"
        except Exception as e:
            return False, True, str(e)

    if shutil.which("systemctl"):
        try:
            res = subprocess.run(["systemctl", "suspend"], capture_output=True, text=True, timeout=10)
            if res.returncode == 0:
                return True, True, "Host suspend initiated via systemctl"
            return False, False, (res.stderr or res.stdout or "systemctl suspend failed")[:240]
        except Exception as e:
            return False, False, str(e)

    if os.access("/sys/power/state", os.W_OK):
        try:
            with open("/sys/power/state", "w") as f:
                f.write("mem")
            return True, True, "Host S3 suspend written to /sys/power/state"
        except Exception as e:
            return False, True, str(e)

    return (
        False,
        False,
        "Host suspend requires privileged systemd/sysfs access (rtcwake/systemctl/sysfs unavailable inside container). Container Eco-Sleep works without host privileges.",
    )
