"""
Tests for v2.1 Optimization, Auto-Update, Power/Sleep & Music Enhancements:
  1. Low-resource sequential Song Download queue + command builder + Navidrome rescan
  2. App-Store Auto Update engine + Nextcloud hands-free update + cancel + scheduler
  3. Memory management + CPU power profiles + thermal/auto-reclaim guard
  4. Auto Sleep mode (Container Eco-Sleep + optional Host Sleep)
  5. Deterministic Music Recommendation scoring + Smart Mixes + M3U export + Queue track
  6. Frontend HTML/JS controls for Updates, Power & Resources, Download, Recommendations
"""

import os
import re
import sys
import json
import time
import tempfile
import threading
import subprocess
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
import pytest
from starlette.testclient import TestClient

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADMIN_DASHBOARD_DIR = os.path.join(ROOT_DIR, "admin-dashboard")
if ADMIN_DASHBOARD_DIR not in sys.path:
    sys.path.insert(0, ADMIN_DASHBOARD_DIR)

import app as app_module

def _fetch_spa_bundle(client):
    res = client.get("/dashboard")
    assert res.status_code == 200
    html = res.text
    combined = html
    for asset_path in re.findall(r'(?:src|href)="(/assets/[^"]+)"', html):
        asset_res = client.get(asset_path)
        assert asset_res.status_code == 200
        combined += "\n" + asset_res.text
    return html, combined


@pytest.fixture
def client_env():
    """Isolated SQLite DB, Music dir, Playlist dir, and authenticated TestClient."""
    orig_db = app_module.DB_PATH
    orig_music = app_module.MUSIC_DIR
    orig_pl = getattr(app_module, "PLAYLIST_DIR", "")
    orig_docker = app_module.docker_client

    with tempfile.TemporaryDirectory() as tmpdir:
        test_db = os.path.join(tmpdir, "test_v21.db")
        music_dir = os.path.join(tmpdir, "music")
        pl_dir = os.path.join(music_dir, "_playlists")
        os.makedirs(music_dir, exist_ok=True)
        os.makedirs(pl_dir, exist_ok=True)

        app_module.DB_PATH = test_db
        app_module.MUSIC_DIR = music_dir
        app_module.PLAYLIST_DIR = pl_dir
        app_module.docker_client = None
        app_module.init_db()

        client = TestClient(app_module.app, follow_redirects=False)
        res = client.post(
            "/login",
            data={
                "username": os.environ.get("ADMIN_DEFAULT_USER", "admin"),
                "password": os.environ.get("ADMIN_DEFAULT_PASSWORD", "admin123"),
            },
        )
        assert res.status_code == 303
        yield client, test_db, music_dir, pl_dir

    app_module.DB_PATH = orig_db
    app_module.MUSIC_DIR = orig_music
    app_module.PLAYLIST_DIR = orig_pl
    app_module.docker_client = orig_docker


# ── Task 1: Song Download Enhancement Tests ───────────────────────────────────

def test_download_command_builder_low_resource_flags(tmp_path):
    """Verify build_ytdlp_command uses audio-only bestaudio, ionice/nice, rate limit, archive & thumbnail flag."""
    music_dir = str(tmp_path / "music")
    os.makedirs(music_dir, exist_ok=True)

    with patch("shutil.which", return_value="/usr/bin/ionice"):
        cmd = app_module.build_ytdlp_command(
            url="https://www.youtube.com/watch?v=abc123",
            music_dir=music_dir,
            quality="mp3_320",
            is_playlist=False,
            nice_level=19,
            rate_limit="1M",
            embed_thumbnail=False,
            archive_skip=True,
        )

    assert cmd[:5] == ["ionice", "-c", "3", "nice", "-n"]
    assert cmd[5] == "19"
    assert "yt-dlp" in cmd
    assert "--format" in cmd
    fmt_val = cmd[cmd.index("--format") + 1]
    assert "bestaudio" in fmt_val
    assert "--concurrent-fragments" in cmd
    assert cmd[cmd.index("--concurrent-fragments") + 1] == "1"
    assert "--limit-rate" in cmd
    assert cmd[cmd.index("--limit-rate") + 1] == "1M"
    assert "--no-overwrites" in cmd
    assert "--download-archive" in cmd
    assert "--embed-thumbnail" not in cmd
    assert "--no-playlist" in cmd

    # Without ionice binary + with embed_thumbnail=True + archive_skip=False
    with patch("shutil.which", return_value=None):
        cmd2 = app_module.build_ytdlp_command(
            url="https://www.youtube.com/playlist?list=PL123",
            music_dir=music_dir,
            quality="opus",
            is_playlist=True,
            nice_level=15,
            rate_limit="",
            embed_thumbnail=True,
            archive_skip=False,
        )
    assert cmd2[0] == "nice"
    assert "--embed-thumbnail" in cmd2
    assert "--download-archive" not in cmd2
    assert "--limit-rate" not in cmd2
    assert "--no-playlist" not in cmd2


def test_download_queue_single_worker_serialization_and_api_options(client_env):
    """Verify /api/music/download persists low-resource options and executes at most 1 job concurrently."""
    client, test_db, music_dir, _ = client_env

    active_count = 0
    max_concurrent = 0
    lock = threading.Lock()
    executed_jobs = []

    def fake_run_download(job_id, url, mdir, quality="mp3_320", **kwargs):
        nonlocal active_count, max_concurrent
        with lock:
            active_count += 1
            max_concurrent = max(max_concurrent, active_count)
            executed_jobs.append((job_id, url))
        time.sleep(0.08)
        db = app_module.get_db()
        db.execute("UPDATE download_queue SET status='completed', completed_at=datetime('now') WHERE id=?", (job_id,))
        db.commit()
        db.close()
        with lock:
            active_count -= 1

    with patch.object(app_module, "_run_download", side_effect=fake_run_download):
        r1 = client.post("/api/music/download", json={
            "url": "https://www.youtube.com/watch?v=111",
            "quality": "opus",
            "embed_thumbnail": False,
            "rate_limit": "750K",
            "archive_skip": True,
        })
        r2 = client.post("/api/music/download", json={
            "url": "https://www.youtube.com/watch?v=222",
            "quality": "mp3_320",
            "embed_thumbnail": True,
            "rate_limit": "",
            "archive_skip": False,
        })
        assert r1.status_code == 200
        assert r2.status_code == 200
        j1 = r1.json()["job_id"]
        j2 = r2.json()["job_id"]

        # Ensure worker is running and drains both jobs sequentially
        app_module.ensure_download_worker_started()
        deadline = time.time() + 3.0
        while time.time() < deadline:
            q = client.get("/api/music/queue").json()
            statuses = {row["id"]: row["status"] for row in q}
            if statuses.get(j1) == "completed" and statuses.get(j2) == "completed":
                break
            time.sleep(0.03)

    assert len(executed_jobs) == 2
    assert max_concurrent == 1, f"Expected strict sequential execution (1), got {max_concurrent}"

    q = {row["id"]: row for row in client.get("/api/music/queue").json()}
    assert q[j1]["status"] == "completed"
    assert q[j1]["embed_thumbnail"] == 0
    assert q[j1]["rate_limit"] == "750K"
    assert q[j1]["archive_skip"] == 1
    assert q[j2]["status"] == "completed"
    assert q[j2]["embed_thumbnail"] == 1
    assert q[j2]["archive_skip"] == 0


def test_trigger_navidrome_scan_best_effort(client_env):
    """Verify _trigger_navidrome_scan runs container scan or Subsonic API gracefully without crashing."""
    mock_docker = MagicMock()
    mock_nav = MagicMock()
    mock_nav.status = "running"
    mock_nav.exec_run.return_value = MagicMock(exit_code=0, output=b"Scan started")
    mock_docker.containers.get.return_value = mock_nav

    orig_docker = app_module.docker_client
    app_module.docker_client = mock_docker
    try:
        ok = app_module._trigger_navidrome_scan()
        assert ok is True
        mock_nav.exec_run.assert_called_once()
    finally:
        app_module.docker_client = orig_docker

    # Graceful when docker_client is None
    app_module.docker_client = None
    assert app_module._trigger_navidrome_scan() in (True, False)


# ── Task 2: App-Store Auto Update Engine Tests ───────────────────────────────

def test_updates_auth_required():
    """Verify all /api/updates/* endpoints require authentication (303 redirect)."""
    c = TestClient(app_module.app, follow_redirects=False)
    for ep in ["/api/updates/status", "/api/updates/settings", "/api/updates/jobs"]:
        res = c.get(ep)
        assert res.status_code == 303
    for ep in ["/api/updates/check", "/api/updates/settings", "/api/updates/apply", "/api/updates/1/cancel"]:
        res = c.post(ep, json={})
        assert res.status_code == 303


def test_updates_check_status_and_settings(client_env):
    """Verify /api/updates/check inspects Docker images + Nextcloud occ and settings persist cleanly."""
    client, _, _, _ = client_env

    # Configure mock Docker containers (pihole has newer digest, nextcloud has app update)
    mock_docker = MagicMock()
    pihole_c = MagicMock()
    pihole_c.name = "pihole"
    pihole_c.status = "running"
    pihole_c.image = MagicMock(tags=["pihole/pihole:latest"], id="sha256:oldpihole", attrs={"RepoDigests": ["pihole/pihole@sha256:olddigest"]})

    nc_c = MagicMock()
    nc_c.name = "nextcloud"
    nc_c.status = "running"
    nc_c.image = MagicMock(tags=["nextcloud:33-apache"], id="sha256:nc1", attrs={"RepoDigests": ["nextcloud@sha256:samedigest"]})

    def nc_exec(cmd, **kw):
        if "status --output=json" in cmd:
            return MagicMock(exit_code=0, output=json.dumps({"versionstring": "33.0.1", "maintenance": False}).encode())
        if "update:check" in cmd:
            return MagicMock(exit_code=0, output=b"Everything up to date\n1 app update available")
        if "app:list" in cmd:
            return MagicMock(exit_code=0, output=json.dumps({"calendar": {"current_version": "4.7.0", "available_version": "4.7.2"}}).encode())
        return MagicMock(exit_code=0, output=b"ok")

    nc_c.exec_run.side_effect = nc_exec

    def get_container(name):
        if name == "pihole":
            return pihole_c
        if name == "nextcloud":
            return nc_c
        raise Exception("not found")

    def get_registry(image):
        reg = MagicMock()
        reg.id = "sha256:newdigest" if "pihole" in image else "sha256:samedigest"
        return reg

    mock_docker.containers.list.return_value = [pihole_c, nc_c]
    mock_docker.containers.get.side_effect = get_container
    mock_docker.images.get_registry_data.side_effect = get_registry

    orig_docker = app_module.docker_client
    app_module.docker_client = mock_docker
    try:
        with patch("ops_updates.check_ytdlp_latest_version", return_value=("2025.01.01", "2025.02.01", True)):
            chk = client.post("/api/updates/check")
            assert chk.status_code == 200
            data = chk.json()
            svcs = {s["name"]: s for s in data["services"]}
            assert svcs["pihole"]["update_available"] is True
            assert svcs["nextcloud"]["update_available"] is True  # app update detected
            assert data["nextcloud_info"]["version"] == "33.0.1"
            assert data["ytdlp_info"]["update_available"] is True
            assert data["updates_available_count"] >= 3

        st = client.get("/api/updates/status")
        assert st.status_code == 200
        assert len(st.json()["services"]) >= 2
    finally:
        app_module.docker_client = orig_docker

    # Settings persistence & validation
    upd_s = client.post("/api/updates/settings", json={
        "auto_update_enabled": True,
        "schedule_freq": "daily",
        "schedule_day": "sun",
        "schedule_time": "03:30",
        "backup_before": True,
        "update_nextcloud_apps": True,
    })
    assert upd_s.status_code == 200
    assert upd_s.json()["auto_update_enabled"] is True
    assert upd_s.json()["schedule_time"] == "03:30"

    got_s = client.get("/api/updates/settings").json()
    assert got_s["auto_update_enabled"] is True
    assert got_s["schedule_freq"] == "daily"
    assert got_s["schedule_time"] == "03:30"


def test_updates_apply_cancel_and_nextcloud_hands_free_safety(client_env):
    """Verify Nextcloud update toggles maintenance mode off even on cancellation or failure, and jobs cancel cleanly."""
    client, _, _, _ = client_env
    import ops_updates

    # 1. Queue & immediately cancel queued update job
    with patch("ops_updates.run_update_job") as mock_runner:
        # Pause dispatcher by checking queued cancel directly before worker runs
        db = app_module.get_db()
        cur = db.execute(
            "INSERT INTO update_jobs (target, status, current_step, triggered_by) VALUES ('pihole', 'queued', 'Waiting', 'manual')"
        )
        jid = cur.lastrowid
        db.commit()
        db.close()

        c_res = client.post(f"/api/updates/{jid}/cancel")
        assert c_res.status_code == 200
        assert c_res.json()["ok"] is True
        jobs = {j["id"]: j for j in client.get("/api/updates/jobs").json()}
        assert jobs[jid]["status"] == "cancelled"

    # 2. Nextcloud hands-free update flow MUST turn maintenance:mode --off even if upgrade step throws or cancels
    mock_docker = MagicMock()
    nc_c = MagicMock()
    nc_c.name = "nextcloud"
    nc_c.status = "running"
    nc_c.image = MagicMock(tags=["nextcloud:33-apache"], attrs={"RepoDigests": []})
    nc_c.attrs = {
        "Config": {"Image": "nextcloud:33-apache", "Env": ["TZ=UTC"]},
        "HostConfig": {"RestartPolicy": {"Name": "unless-stopped"}},
        "NetworkSettings": {"Networks": {"homelab": {}}},
    }
    exec_calls = []

    def exec_run_side(cmd, **kw):
        exec_calls.append(cmd)
        if "occ upgrade" in cmd:
            raise RuntimeError("Simulated upgrade failure")
        return MagicMock(exit_code=0, output=b"ok")

    nc_c.exec_run.side_effect = exec_run_side
    mock_docker.containers.get.return_value = nc_c

    logs = []
    ok, err = ops_updates.run_nextcloud_hands_free_update(
        docker_client=mock_docker,
        is_cancelled_fn=lambda: False,
        progress_fn=lambda pct, step, msg="": logs.append((pct, step, msg)),
        update_apps=True,
        backup_before=False,
    )
    assert ok is False
    assert "Simulated upgrade failure" in err
    upgrade_idx = next(i for i, c in enumerate(exec_calls) if "occ upgrade" in c)
    assert all("-d memory_limit=512M" in c for c in exec_calls if "occ " in c)
    assert not any("maintenance:mode --on" in c for c in exec_calls[:upgrade_idx]), (
        "Nextcloud occ upgrade fails with exit code 2 if maintenance:mode --on is enabled beforehand!"
    )
    assert any("maintenance:mode --off" in c for c in exec_calls[upgrade_idx:]), (
        "Nextcloud MUST clear maintenance mode in finally block on error!"
    )


def test_updates_schedule_due_calculation():
    """Verify daily/weekly schedule evaluation avoids duplicate runs on same day."""
    import ops_updates

    # Weekly Sunday 03:30 -> Sunday 03:32 is due if never run today
    sunday_dt = datetime(2026, 11, 15, 3, 32)  # 2026-11-15 is Sunday
    cfg = {
        "auto_update_enabled": True,
        "schedule_freq": "weekly",
        "schedule_day": "sun",
        "schedule_time": "03:30",
        "last_run": "",
    }
    assert ops_updates.is_schedule_due(cfg, now_dt=sunday_dt) is True

    # Already ran today -> not due again
    cfg["last_run"] = "2026-11-15T03:31:00"
    assert ops_updates.is_schedule_due(cfg, now_dt=sunday_dt) is False

    # Wrong day -> False
    cfg["last_run"] = ""
    monday_dt = datetime(2026, 11, 16, 3, 32)
    assert ops_updates.is_schedule_due(cfg, now_dt=monday_dt) is False

    # Daily mode -> True on Monday too
    cfg["schedule_freq"] = "daily"
    assert ops_updates.is_schedule_due(cfg, now_dt=monday_dt) is True


# ── Task 3: Memory, CPU Profiles & Auto Sleep Mode Tests ──────────────────────

def test_resources_and_sleep_auth_required():
    """Verify all /api/resources/* and /api/sleep/* routes enforce login (303)."""
    c = TestClient(app_module.app, follow_redirects=False)
    for ep in ["/api/resources/status", "/api/resources/settings", "/api/sleep/status", "/api/sleep/settings"]:
        assert c.get(ep).status_code == 303
    for ep in [
        "/api/resources/memory/compact",
        "/api/resources/profile",
        "/api/resources/settings",
        "/api/resources/container/nextcloud/limits",
        "/api/sleep/settings",
        "/api/sleep/now",
        "/api/sleep/wake",
        "/api/sleep/host",
    ]:
        assert c.post(ep, json={}).status_code == 303


def test_memory_compact_cpu_profiles_and_container_limits(client_env):
    """Verify RAM compaction, power profile switching, and live container resource limit updates."""
    client, _, _, _ = client_env

    mock_docker = MagicMock()
    nc_c = MagicMock()
    nc_c.name = "nextcloud"
    nc_c.status = "running"
    nc_c.attrs = {"HostConfig": {"Memory": 512 * 1024 * 1024, "CpuShares": 512, "NanoCpus": 700_000_000}}
    redis_c = MagicMock()
    redis_c.name = "redis"
    redis_c.status = "running"
    redis_c.attrs = {"HostConfig": {"Memory": 64 * 1024 * 1024, "CpuShares": 512, "NanoCpus": 0}}
    redis_c.exec_run.return_value = MagicMock(exit_code=0, output=b"OK")
    pi_c = MagicMock()
    pi_c.name = "pihole"
    pi_c.status = "running"
    pi_c.attrs = {"HostConfig": {"Memory": 128 * 1024 * 1024, "CpuShares": 1024, "NanoCpus": 0}}

    cmap = {"nextcloud": nc_c, "redis": redis_c, "pihole": pi_c}
    mock_docker.containers.list.return_value = [pi_c, nc_c, redis_c]
    mock_docker.containers.get.side_effect = lambda n: cmap[n]

    orig_docker = app_module.docker_client
    app_module.docker_client = mock_docker
    try:
        # 1. Resources status
        st = client.get("/api/resources/status")
        assert st.status_code == 200
        sdata = st.json()
        assert "memory" in sdata and "total_mb" in sdata["memory"]
        assert "cpu" in sdata and "percent" in sdata["cpu"]
        assert sdata["profile"] in ("eco", "balanced", "performance")

        # 2. Memory compaction triggers gc + Redis purge
        cmp_res = client.post("/api/resources/memory/compact")
        assert cmp_res.status_code == 200
        cdata = cmp_res.json()
        assert cdata["ok"] is True
        assert "freed_mb" in cdata
        assert "gc" in ",".join(cdata["actions"]).lower()
        redis_c.exec_run.assert_called()

        # 3. Power profile switch -> Eco trims nextcloud cpu_shares, keeps pihole high
        prof_res = client.post("/api/resources/profile", json={"profile": "eco"})
        assert prof_res.status_code == 200
        assert prof_res.json()["profile"] == "eco"
        nc_c.update.assert_called()
        assert any(call.kwargs.get("cpu_shares") == 256 for call in nc_c.update.call_args_list)

        # 4. Per-container limits update
        lim_res = client.post("/api/resources/container/nextcloud/limits", json={
            "mem_limit_mb": 384,
            "cpu_shares": 400,
            "cpu_quota_pct": 60,
        })
        assert lim_res.status_code == 200
        assert lim_res.json()["ok"] is True
        last_kw = nc_c.update.call_args.kwargs
        assert last_kw["mem_limit"] == 384 * 1024 * 1024
        assert last_kw["cpu_shares"] == 400
        assert last_kw["nano_cpus"] == 600_000_000

        # Invalid low memory limit rejected
        bad_lim = client.post("/api/resources/container/nextcloud/limits", json={"mem_limit_mb": 8})
        assert bad_lim.status_code == 400
    finally:
        app_module.docker_client = orig_docker


def test_auto_sleep_container_eco_and_host_fallback(client_env):
    """Verify Container Eco-Sleep pauses/stops target containers while protecting pihole & admin-dashboard, plus schedule/host fallback."""
    client, _, _, _ = client_env
    import ops_resources

    nc_c = MagicMock(name="nextcloud")
    nc_c.name = "nextcloud"
    nc_c.status = "running"
    nav_c = MagicMock(name="navidrome")
    nav_c.name = "navidrome"
    nav_c.status = "running"
    pi_c = MagicMock(name="pihole")
    pi_c.name = "pihole"
    pi_c.status = "running"
    dash_c = MagicMock(name="admin-dashboard")
    dash_c.name = "admin-dashboard"
    dash_c.status = "running"

    cmap = {"nextcloud": nc_c, "navidrome": nav_c, "pihole": pi_c, "admin-dashboard": dash_c}
    mock_docker = MagicMock()
    mock_docker.containers.get.side_effect = lambda n: cmap[n]
    mock_docker.containers.list.return_value = list(cmap.values())

    orig_docker = app_module.docker_client
    app_module.docker_client = mock_docker
    try:
        # Configure pause mode targets (try sneaking admin-dashboard in; backend must protect it!)
        set_r = client.post("/api/sleep/settings", json={
            "eco_sleep_enabled": True,
            "sleep_mode": "pause",
            "sleep_targets": ["nextcloud", "navidrome", "admin-dashboard"],
            "schedule_enabled": True,
            "sleep_start": "23:00",
            "sleep_end": "06:30",
            "idle_sleep_enabled": True,
            "idle_minutes": 45,
            "host_sleep_enabled": True,
        })
        assert set_r.status_code == 200
        saved = set_r.json()
        assert "admin-dashboard" not in saved["sleep_targets"]
        assert "nextcloud" in saved["sleep_targets"]

        # Trigger Eco-Sleep now
        slp = client.post("/api/sleep/now")
        assert slp.status_code == 200
        assert set(slp.json()["affected"]) == {"nextcloud", "navidrome"}
        nc_c.pause.assert_called_once()
        nav_c.pause.assert_called_once()
        pi_c.pause.assert_not_called()

        # Simulate paused state & wake
        nc_c.status = "paused"
        nav_c.status = "paused"
        wk = client.post("/api/sleep/wake")
        assert wk.status_code == 200
        assert set(wk.json()["woken"]) == {"nextcloud", "navidrome"}
        nc_c.unpause.assert_called_once()
        nav_c.unpause.assert_called_once()

        # Host sleep graceful unprivileged failure check
        with patch("shutil.which", return_value=None), patch("os.access", return_value=False):
            hst = client.post("/api/sleep/host", json={"wake_minutes": 60})
            assert hst.status_code == 400
            assert hst.json()["supported"] is False
    finally:
        app_module.docker_client = orig_docker

    # Overnight window helper tests (23:00 -> 06:30)
    assert ops_resources.is_in_sleep_window("23:00", "06:30", datetime(2026, 11, 12, 23, 30)) is True
    assert ops_resources.is_in_sleep_window("23:00", "06:30", datetime(2026, 11, 13, 3, 15)) is True
    assert ops_resources.is_in_sleep_window("23:00", "06:30", datetime(2026, 11, 13, 12, 0)) is False


# ── Task 4: Deterministic Music Recommendation Enhancement Tests ──────────────

def test_recommendation_smart_mixes_weighted_scoring_and_m3u_export(client_env):
    """Verify zero-AI deterministic time-decay/completion scoring, smart_mixes, .m3u export, and missing-track queueing."""
    client, test_db, music_dir, pl_dir = client_env

    # Create sample music files in MUSIC_DIR so M3U resolver matches local tracks
    track1_path = os.path.join(music_dir, "Arijit Singh - Tum Hi Ho.mp3")
    track2_path = os.path.join(music_dir, "Pink Floyd - Time.mp3")
    with open(track1_path, "wb") as f:
        f.write(b"ID3")
    with open(track2_path, "wb") as f:
        f.write(b"ID3")

    db = app_module.get_db()
    now_dt = datetime.utcnow()
    old_ts = (now_dt - timedelta(days=45)).strftime("%Y-%m-%d %H:%M:%S")
    recent_ts = (now_dt - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")

    # 3 recent completed plays for Pink Floyd - Time
    for i in range(3):
        db.execute(
            "INSERT INTO listen_events (username, track_path, track_title, artist, genre, duration_sec, listened_sec, completed, hour_of_day, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("admin", "Pink Floyd - Time.mp3", "Time", "Pink Floyd", "Rock", 300, 295, 1, now_dt.hour, recent_ts),
        )
    # 2 older completed plays (>21 days ago) -> Deep Cut Rediscover candidate
    for i in range(2):
        db.execute(
            "INSERT INTO listen_events (username, track_path, track_title, artist, genre, duration_sec, listened_sec, completed, hour_of_day, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("admin", "Arijit Singh - Tum Hi Ho.mp3", "Tum Hi Ho", "Arijit Singh", "Bollywood", 260, 250, 1, 21, old_ts),
        )
    # 4 skipped plays for another track
    for i in range(4):
        db.execute(
            "INSERT INTO listen_events (username, track_path, track_title, artist, genre, duration_sec, listened_sec, completed, hour_of_day, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("admin", "skip_track.mp3", "Skipped Intro", "Various", "Pop", 200, 15, 0, 14, recent_ts),
        )
    db.commit()
    db.close()

    # Point MALOJA_DB_PATH to nonexistent path so listen_events scoring runs deterministically
    orig_maloja = app_module.MALOJA_DB_PATH
    app_module.MALOJA_DB_PATH = os.path.join(music_dir, "nonexistent_maloja.sqlite")
    try:
        rec = client.get("/api/music/recommendations/admin")
        assert rec.status_code == 200
        rdata = rec.json()
        # Preserve legacy keys
        for k in ("username", "total_scrobbles", "top_artists", "top_tracks", "listening_clock", "suggestions", "playlist_suggestions"):
            assert k in rdata

        # Enhanced smart_mixes & weighted score
        assert "smart_mixes" in rdata
        assert len(rdata["smart_mixes"]) >= 2
        mix_types = {m["based_on"] for m in rdata["smart_mixes"]}
        assert "deep_cuts" in mix_types or "skip_free" in mix_types
        # Check Pink Floyd - Time scores higher than Skipped Intro despite fewer raw plays
        scores = {t["title"]: t.get("weighted_score", 0) for t in rdata["top_tracks"]}
        assert scores.get("Time", 0) > scores.get("Skipped Intro", 0)
    finally:
        app_module.MALOJA_DB_PATH = orig_maloja

    # Export Smart Mix to .m3u in PLAYLIST_DIR
    exp = client.post("/api/music/playlists/export-m3u", json={
        "name": "../../Evil Mix Name!!",
        "username": "admin",
        "tracks": [
            {"title": "Time", "artist": "Pink Floyd", "track_path": "Pink Floyd - Time.mp3"},
            {"title": "Tum Hi Ho", "artist": "Arijit Singh", "track_path": ""},
        ],
    })
    assert exp.status_code == 200
    edata = exp.json()
    assert edata["ok"] is True
    assert edata["track_count"] == 2
    assert os.path.dirname(os.path.abspath(edata["path"])) == os.path.abspath(pl_dir)
    with open(edata["path"], "r", encoding="utf-8") as f:
        m3u_txt = f.read()
    assert "#EXTM3U" in m3u_txt
    assert "Pink Floyd - Time.mp3" in m3u_txt
    assert "Arijit Singh - Tum Hi Ho.mp3" in m3u_txt

    # Queue missing track via recommendation button
    with patch.object(app_module, "_notify_download_worker"):
        qt = client.post("/api/music/recommendations/queue-track", json={
            "title": "Echoes",
            "artist": "Pink Floyd",
            "quality": "opus",
        })
        assert qt.status_code == 200
        qdata = qt.json()
        assert qdata["ok"] is True
        assert qdata["url"].startswith("ytsearch1:")
        db = app_module.get_db()
        db.execute("DELETE FROM download_queue WHERE id=?", (qdata["job_id"],))
        db.commit()
        db.close()


# ── Task 5: Dashboard UI Element Contracts ────────────────────────────────────

def test_dashboard_v21_ui_sections_and_controls(client_env):
    """Verify Updates, Power & Resources, Eco-Download & Smart Mix export controls exist in Preact SPA bundle."""
    client, _, _, _ = client_env
    _, bundle = _fetch_spa_bundle(client)

    # Sidebar & tabs
    assert "App-Store Updates" in bundle
    assert "Power & Resources" in bundle

    # Auto Update App-Store controls & endpoints
    for token in [
        "/api/updates/status", "/api/updates/check", "/api/updates/settings",
        "/api/updates/apply", "Auto-Update Scheduler", "Cancel Update",
    ]:
        assert token in bundle

    # Memory, CPU & Auto Sleep controls & endpoints
    for token in [
        "/api/resources/memory/compact", "/api/resources/profile", "/api/sleep/settings",
        "Auto-Sleep & WakeProxy", "Host S3 Suspend",
    ]:
        assert token in bundle

    # Download & Recommendation enhancements
    for token in [
        "Embed cover art", "Skip already downloaded", "Export .m3u",
        "/api/music/playlists/export-m3u", "/api/music/recommendations/queue-track",
    ]:
        assert token in bundle


# ── Task 6: Per-Container & Server-Wide Wake-on-Request Auto-Sleep (TDD) ──────

def test_idle_sleep_settings_persistence(client_env):
    """Verify per-container and server-wide idle sleep settings validate and persist via API."""
    client, _, _, _ = client_env

    res = client.post("/api/sleep/settings", json={
        "eco_sleep_enabled": True,
        "sleep_mode": "stop",
        "container_idle_sleep_enabled": True,
        "container_idle_minutes": 12,
        "server_idle_sleep_enabled": True,
        "server_idle_minutes": 35,
        "wake_all_on_server_wake": False,
        "wake_timeout_sec": 30,
    })
    assert res.status_code == 200
    saved = res.json()
    assert saved["container_idle_sleep_enabled"] is True
    assert saved["container_idle_minutes"] == 12
    assert saved["server_idle_sleep_enabled"] is True
    assert saved["server_idle_minutes"] == 35
    assert saved["wake_all_on_server_wake"] is False
    assert saved["wake_timeout_sec"] == 30

    # Clamp bounds check
    res2 = client.post("/api/sleep/settings", json={
        "container_idle_minutes": 0,
        "server_idle_minutes": 9999,
        "wake_timeout_sec": 1,
    })
    assert res2.status_code == 200
    clamped = res2.json()
    assert clamped["container_idle_minutes"] >= 1
    assert clamped["server_idle_minutes"] <= 720
    assert clamped["wake_timeout_sec"] >= 5


def test_per_container_idle_sleep_and_shared_dependency_protection(client_env):
    """Verify idle container sleeps independently while active container stays awake, and mariadb/redis follow nextcloud."""
    import ops_resources

    db = app_module.get_db()
    ops_resources.save_sleep_settings(db, {
        "eco_sleep_enabled": True,
        "sleep_mode": "stop",
        "sleep_targets": ["nextcloud", "mariadb", "redis", "navidrome", "maloja", "samba"],
        "container_idle_sleep_enabled": True,
        "container_idle_minutes": 10,
        "server_idle_sleep_enabled": True,
        "server_idle_minutes": 30,
    }, app_module.MANAGED)

    containers = {}
    for name in ["nextcloud", "mariadb", "redis", "navidrome", "maloja", "samba"]:
        c = MagicMock()
        c.name = name
        c.status = "running"
        def make_stop(obj):
            def _stop(**kw):
                obj.status = "exited"
            return _stop
        c.stop.side_effect = make_stop(c)
        containers[name] = c

    mock_docker = MagicMock()
    mock_docker.containers.get.side_effect = lambda n: containers[n]
    mock_docker.containers.list.return_value = list(containers.values())

    base_ts = 1_700_000_000.0
    ops_resources.reset_idle_trackers(base_ts)

    # Scenario A: 12 mins pass, ONLY navidrome had recent activity (2 mins ago)
    ops_resources.touch_container_request("navidrome", now_ts=base_ts + 600.0)
    res_a = ops_resources.evaluate_idle_sleep(db, mock_docker, busy=False, now_ts=base_ts + 720.0)

    assert "navidrome" not in res_a["slept"]
    assert containers["navidrome"].status == "running"
    assert "nextcloud" in res_a["slept"]
    # Dependencies must sleep now because nextcloud slept
    assert "mariadb" in res_a["slept"]
    assert "redis" in res_a["slept"]
    assert containers["nextcloud"].status == "exited"
    assert containers["mariadb"].status == "exited"
    assert containers["redis"].status == "exited"
    # Server is NOT sleeping because navidrome was active 2m ago (< 30m)
    assert res_a["server_idle_sleep"] is False

    # Scenario B: Bring nextcloud/mariadb/redis/samba back running; keep nextcloud active while mariadb itself wasn't touched directly
    for k in ("nextcloud", "mariadb", "redis", "samba"):
        containers[k].status = "running"
    ops_resources.reset_idle_trackers(base_ts)
    ops_resources.touch_container_request("nextcloud", now_ts=base_ts + 700.0)
    res_b = ops_resources.evaluate_idle_sleep(db, mock_docker, busy=False, now_ts=base_ts + 720.0)
    # mariadb & redis MUST NOT sleep while nextcloud is awake!
    assert "nextcloud" not in res_b["slept"]
    assert "mariadb" not in res_b["slept"]
    assert "redis" not in res_b["slept"]
    assert "samba" in res_b["slept"]
    db.close()


def test_server_wide_idle_sleep_and_dependency_ordered_single_flight_wake(client_env):
    """Verify full server enters sleep when all services idle past server_idle_minutes, and waking nextcloud starts deps first."""
    import ops_resources

    db = app_module.get_db()
    ops_resources.save_sleep_settings(db, {
        "eco_sleep_enabled": True,
        "sleep_mode": "stop",
        "sleep_targets": ["nextcloud", "mariadb", "redis", "navidrome", "maloja", "samba"],
        "container_idle_sleep_enabled": True,
        "container_idle_minutes": 15,
        "server_idle_sleep_enabled": True,
        "server_idle_minutes": 30,
        "wake_all_on_server_wake": False,
        "wake_timeout_sec": 10,
    }, app_module.MANAGED)

    wake_order = []
    containers = {}
    for name in ["nextcloud", "mariadb", "redis", "navidrome", "maloja", "samba"]:
        c = MagicMock()
        c.name = name
        c.status = "running"
        def make_stop(obj):
            return lambda **kw: setattr(obj, "status", "exited")
        def make_start(obj, nm):
            def _start():
                wake_order.append(nm)
                obj.status = "running"
            return _start
        c.stop.side_effect = make_stop(c)
        c.start.side_effect = make_start(c, name)
        containers[name] = c

    mock_docker = MagicMock()
    mock_docker.containers.get.side_effect = lambda n: containers[n]
    mock_docker.containers.list.return_value = list(containers.values())

    base_ts = 1_700_000_000.0
    ops_resources.reset_idle_trackers(base_ts)

    # All services quiet for 35 minutes -> entire server sleeps
    res = ops_resources.evaluate_idle_sleep(db, mock_docker, busy=False, now_ts=base_ts + 2100.0)
    assert res["server_idle_sleep"] is True
    assert set(res["slept"]) == {"nextcloud", "mariadb", "redis", "navidrome", "maloja", "samba"}
    assert ops_resources.get_sleep_settings(db)["sleeping_now"] is True

    # Incoming request for nextcloud wakes mariadb -> redis -> nextcloud ONLY, respecting single-flight lock
    port_checks = []
    def fake_check_port(host, port):
        port_checks.append((host, port))
        return len(port_checks) >= 2  # simulates 1st probe not ready, 2nd ready

    # Launch 4 parallel wake calls simulating browser burst
    results = []
    threads = []
    for _ in range(4):
        t = threading.Thread(
            target=lambda: results.append(
                ops_resources.wake_service_and_wait(
                    db=app_module.get_db,
                    docker_client=mock_docker,
                    service="nextcloud",
                    target_host="127.0.0.1",
                    target_port=80,
                    timeout_sec=5.0,
                    check_port_fn=fake_check_port,
                    poll_interval=0.01,
                )
            )
        )
        threads.append(t)
        t.start()
    for t in threads:
        t.join(timeout=5.0)

    assert len(results) == 4
    assert all(r[0] is True for r in results)
    # Dependency order: mariadb and redis started before nextcloud, each started ONCE despite 4 parallel calls
    assert wake_order.count("mariadb") == 1
    assert wake_order.count("redis") == 1
    assert wake_order.count("nextcloud") == 1
    assert wake_order.index("mariadb") < wake_order.index("nextcloud")
    assert wake_order.index("redis") < wake_order.index("nextcloud")
    assert containers["navidrome"].status == "exited"  # unrelated container stays asleep!
    db.close()


def test_wake_proxy_tcp_roundtrip_wakes_sleeping_container(client_env):
    """End-to-end asyncio TCP wake-proxy test: wakes sleeping container+deps and proxies TCP bytes transparently."""
    import asyncio
    import ops_resources

    containers = {}
    wake_order = []
    for name in ("mariadb", "redis", "nextcloud"):
        c = MagicMock()
        c.name = name
        c.status = "exited"
        def make_start(obj, nm):
            def _start():
                wake_order.append(nm)
                obj.status = "running"
            return _start
        c.start.side_effect = make_start(c, name)
        containers[name] = c

    mock_docker = MagicMock()
    mock_docker.containers.get.side_effect = lambda n: containers[n]

    async def _run():
        # Ephemeral local TCP backend simulating Nextcloud port
        async def handle_backend(reader, writer):
            data = await reader.read(1024)
            writer.write(b"ECHO:" + data)
            await writer.drain()
            writer.close()

        backend_srv = await asyncio.start_server(handle_backend, "127.0.0.1", 0)
        backend_port = backend_srv.sockets[0].getsockname()[1]

        proxy_mgr = app_module.WakeProxyManager(
            routes=[("nextcloud", 0, "127.0.0.1", backend_port)],
            host="127.0.0.1",
        )

        orig_docker = app_module.docker_client
        app_module.docker_client = mock_docker
        try:
            ops_resources.reset_idle_trackers(time.time() - 3600)
            await proxy_mgr.start()
            proxy_port = proxy_mgr.bound_ports["nextcloud"]
            assert proxy_port > 0

            r, w = await asyncio.open_connection("127.0.0.1", proxy_port)
            w.write(b"GET /status.php HTTP/1.0\r\n\r\n")
            if w.can_write_eof():
                w.write_eof()
            await w.drain()
            resp = await asyncio.wait_for(r.read(4096), timeout=3.0)
            w.close()

            assert resp == b"ECHO:GET /status.php HTTP/1.0\r\n\r\n"
            assert containers["mariadb"].status == "running"
            assert containers["redis"].status == "running"
            assert containers["nextcloud"].status == "running"
            assert wake_order.index("mariadb") < wake_order.index("nextcloud")
            assert wake_order.index("redis") < wake_order.index("nextcloud")
            assert ops_resources.get_container_idle_seconds("nextcloud") < 2.0
        finally:
            await proxy_mgr.stop()
            backend_srv.close()
            await backend_srv.wait_closed()
            app_module.docker_client = orig_docker

    asyncio.run(_run())


def test_background_poll_header_does_not_reset_idle_and_http_wake_proxy(client_env):
    """Verify X-Background-Poll: 1 skips idle reset, /api/sleep/status includes per-container idle, and /svc/{service} wakes+proxies."""
    client, _, _, _ = client_env
    import ops_resources

    stale_ts = time.time() - 1800  # 30 minutes ago
    ops_resources.reset_idle_trackers(stale_ts)
    app_module._last_activity_ts = stale_ts

    # 1. Background poll must NOT reset idle timer
    bg = client.get("/api/sleep/status", headers={"X-Background-Poll": "1"})
    assert bg.status_code == 200
    bdata = bg.json()
    assert "containers_idle" in bdata
    assert bdata["server_idle_seconds"] >= 1795
    assert "wake_proxy_routes" in bdata

    # 2. Real user request (without background header) MUST reset idle timer
    fg = client.get("/api/sleep/status")
    assert fg.status_code == 200
    assert fg.json()["server_idle_seconds"] < 5.0

    # 3. HTTP fallback route /svc/{service} wakes sleeping service and proxies response
    nav_c = MagicMock()
    nav_c.name = "navidrome"
    nav_c.status = "exited"
    nav_c.start.side_effect = lambda: setattr(nav_c, "status", "running")
    mock_docker = MagicMock()
    mock_docker.containers.get.side_effect = lambda n: nav_c

    orig_docker = app_module.docker_client
    app_module.docker_client = mock_docker
    try:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b'{"subsonic":"ok"}'
        mock_resp.headers = {"content-type": "application/json"}

        with patch("ops_resources.wake_service_and_wait", return_value=(True, "ready", ["navidrome"])) as mock_wake, \
             patch("httpx.AsyncClient.request", return_value=mock_resp):
            r = client.get("/svc/navidrome/rest/ping")
            assert r.status_code == 200
            assert b"subsonic" in r.content
            mock_wake.assert_called_once()
    finally:
        app_module.docker_client = orig_docker


def test_wake_proxy_ui_controls_and_compose_ports(client_env):
    """Verify Preact SPA has per-container/server-wide idle sleep controls + X-Background-Poll, and docker-compose assigns ports to admin-dashboard."""
    client, _, _, _ = client_env
    _, bundle = _fetch_spa_bundle(client)
    for token in [
        "container_idle_sleep_enabled", "container_idle_minutes",
        "server_idle_sleep_enabled", "server_idle_minutes",
        "wake_all_on_server_wake", "wake_timeout_sec",
        "Wake-Proxy Active", "X-Background-Poll",
        "/api/sleep/wake", "/api/sleep/now",
    ]:
        assert token in bundle

    compose_path = os.path.join(ROOT_DIR, "docker-compose.yml")
    with open(compose_path, "r", encoding="utf-8") as f:
        comp = f.read()
    assert "${NEXTCLOUD_PORT:-8081}:8081" in comp
    assert "${NAVIDROME_PORT:-4533}:4533" in comp
    assert "${MALOJA_PORT:-42010}:42010" in comp
    assert '"445:445"' not in comp
    assert "http://admin-dashboard:42010/apis/listenbrainz/1/" in comp


def test_nextcloud_inspect_handles_php_memory_warning_and_uses_512m(client_env):
    """Regression: leading PHP memory warning before occ JSON must not wipe out version detection."""
    import ops_updates

    mock_docker = MagicMock()
    nc_c = MagicMock()
    nc_c.name = "nextcloud"
    nc_c.status = "running"
    calls = []

    def nc_exec(cmd, **kw):
        calls.append(cmd)
        if "status --output=json" in cmd:
            payload = (
                "The current PHP memory limit is below the recommended value of 512MB.\n"
                + json.dumps({"installed": True, "versionstring": "33.0.9", "maintenance": False})
            )
            return MagicMock(exit_code=0, output=payload.encode())
        if "update:check" in cmd:
            return MagicMock(exit_code=0, output=b"Nextcloud 33.0.10 is available.\n1 update available")
        if "app:list" in cmd:
            return MagicMock(
                exit_code=0,
                output=(
                    "The current PHP memory limit is below the recommended value of 512MB.\n"
                    + json.dumps({"enabled": {"files": {"current_version": "1.0", "available_version": "1.1"}}})
                ).encode(),
            )
        return MagicMock(exit_code=0, output=b"ok")

    nc_c.exec_run.side_effect = nc_exec
    mock_docker.containers.get.return_value = nc_c

    info = ops_updates.inspect_nextcloud_updates(mock_docker)
    assert info["running"] is True
    assert info["version"] == "33.0.9"
    assert info["core_update_available"] is True
    assert info["available_version"] == "33.0.10"
    assert len(info["app_updates"]) == 1
    assert all("-d memory_limit=512M" in c for c in calls if "occ " in c)


def test_nextcloud_hands_free_update_wakes_dependencies_and_pulls_new_image(client_env):
    """Regression: Nextcloud update must wake sleeping mariadb/redis/nextcloud, pull newer image digest, and run occ upgrade cleanly."""
    import ops_updates

    mariadb_c = MagicMock(name="mariadb", status="exited")
    mariadb_c.name = "mariadb"
    mariadb_c.start.side_effect = lambda: setattr(mariadb_c, "status", "running")

    redis_c = MagicMock(name="redis", status="exited")
    redis_c.name = "redis"
    redis_c.start.side_effect = lambda: setattr(redis_c, "status", "running")

    old_nc = MagicMock()
    old_nc.name = "nextcloud"
    old_nc.status = "exited"
    old_nc.image = MagicMock(tags=["nextcloud:33-apache"], attrs={"RepoDigests": ["nextcloud@sha256:olddigest"]})
    old_nc.attrs = {"Config": {"Image": "nextcloud:33-apache", "Env": ["TZ=UTC"]}, "HostConfig": {}, "NetworkSettings": {"Networks": {}}}
    old_nc.start.side_effect = lambda: setattr(old_nc, "status", "running")

    new_nc = MagicMock()
    new_nc.name = "nextcloud"
    new_nc.status = "running"
    new_nc.image = MagicMock(tags=["nextcloud:33-apache"], attrs={"RepoDigests": ["nextcloud@sha256:newdigest"]})
    exec_calls = []

    def new_nc_exec(cmd, **kw):
        exec_calls.append(cmd)
        if "occ maintenance:mode --off" in cmd:
            return MagicMock(exit_code=0, output=b"Maintenance mode disabled")
        if "occ upgrade" in cmd:
            return MagicMock(exit_code=0, output=b"Nextcloud is already latest version")
        if "occ app:update" in cmd or "occ db:add-missing-indices" in cmd:
            return MagicMock(exit_code=0, output=b"ok")
        return MagicMock(exit_code=0, output=b"ok")

    new_nc.exec_run.side_effect = new_nc_exec

    state = {"nc": old_nc}
    mock_docker = MagicMock()

    def get_c(name):
        if name == "mariadb":
            return mariadb_c
        if name == "redis":
            return redis_c
        if name == "nextcloud":
            return state["nc"]
        raise Exception("not found")

    def run_new(image, **kw):
        state["nc"] = new_nc
        return new_nc

    reg = MagicMock(id="sha256:newdigest")
    mock_docker.containers.get.side_effect = get_c
    mock_docker.containers.run.side_effect = run_new
    mock_docker.images.get_registry_data.return_value = reg

    with patch("ops_resources._default_check_port", return_value=True):
        ok, msg = ops_updates.run_nextcloud_hands_free_update(
            docker_client=mock_docker,
            is_cancelled_fn=lambda: False,
            progress_fn=lambda pct, st, l="": None,
            update_apps=True,
            backup_before=False,
            db_factory=app_module.get_db,
        )

    assert ok is True, msg
    assert mariadb_c.status == "running"
    assert redis_c.status == "running"
    mock_docker.images.pull.assert_called_once_with("nextcloud:33-apache")
    assert any("occ upgrade --no-interaction" in c for c in exec_calls)
    upgrade_idx = next(i for i, c in enumerate(exec_calls) if "occ upgrade" in c)
    assert not any("maintenance:mode --on" in c for c in exec_calls[:upgrade_idx])
    assert any("maintenance:mode --off" in c for c in exec_calls[:upgrade_idx + 1])


def test_update_all_updates_deps_first_and_continues_after_single_failure(client_env):
    """Regression: update job 'all' must not skip remaining services when one service fails."""
    _, _, _, _ = client_env
    import ops_updates

    db = app_module.get_db()
    cur = db.execute("INSERT INTO update_jobs (target, status, current_step) VALUES ('all', 'queued', 'Queued')")
    jid = cur.lastrowid
    db.commit()
    db.close()

    order = []
    cached = {
        "services": [
            {"name": "nextcloud", "update_available": True},
            {"name": "mariadb", "update_available": True},
            {"name": "pihole", "update_available": True},
        ],
        "ytdlp_info": {"update_available": False},
    }

    def fake_recreate(dc, name, progress_fn=None):
        order.append(name)
        return True, f"Updated {name}"

    def fake_nc(**kw):
        order.append("nextcloud")
        return False, "Simulated Nextcloud failure"

    with patch("ops_updates.check_all_updates", return_value=cached), \
         patch("ops_updates.recreate_container_with_latest_image", side_effect=fake_recreate), \
         patch("ops_updates.run_nextcloud_hands_free_update", side_effect=fake_nc):
        ops_updates.run_update_job(
            job_id=jid,
            db_factory=app_module.get_db,
            docker_client=MagicMock(),
            managed_services=["nextcloud", "mariadb", "pihole"],
        )

    assert "mariadb" in order and "pihole" in order, "Remaining services must still update when one fails!"
    assert order.index("mariadb") < order.index("nextcloud"), "mariadb must update before nextcloud"

    db = app_module.get_db()
    row = dict(db.execute("SELECT * FROM update_jobs WHERE id=?", (jid,)).fetchone())
    db.close()
    assert row["status"] == "failed"
    assert "Simulated Nextcloud failure" in (row["error"] or "")


def test_ytdlp_version_detection_and_container_backup_snapshot(client_env, tmp_path):
    """Regression: yt-dlp check uses Python metadata without slow subprocess; backup works via Docker SDK without docker CLI."""
    import ops_updates

    with patch("subprocess.run", side_effect=RuntimeError("subprocess skipped")), \
         patch("importlib.metadata.version", return_value="2026.03.17"), \
         patch("urllib.request.urlopen") as mock_url:
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"info": {"version": "2026.10.26"}}).encode()
        mock_resp.__enter__.return_value = mock_resp
        mock_url.return_value = mock_resp
        cur_v, lat_v, has_upd = ops_updates.check_ytdlp_latest_version()

    assert cur_v == "2026.03.17"
    assert lat_v == "2026.10.26"
    assert has_upd is True

    # Container-aware backup via Docker SDK (no docker CLI binary needed)
    mariadb_c = MagicMock(name="mariadb", status="running")
    mariadb_c.exec_run.return_value = MagicMock(exit_code=0, output=b"-- MySQL dump 10.11\nSELECT 1;")
    nc_c = MagicMock(name="nextcloud", status="running")
    nc_c.exec_run.side_effect = [
        MagicMock(exit_code=0, output=b"<?php $CONFIG = [];"),
        MagicMock(exit_code=0, output=b"Enabled:\n - files: 2.0.0"),
    ]
    mock_docker = MagicMock()
    mock_docker.containers.get.side_effect = lambda n: mariadb_c if n == "mariadb" else nc_c

    bk_mount = str(tmp_path / "mnt_backup")
    bk_log = str(tmp_path / "backup.log")
    ok, snap_dir, msg = ops_updates.run_backup_snapshot(
        docker_client=mock_docker,
        backup_mount=bk_mount,
        log_path=bk_log,
        db_path=app_module.DB_PATH,
    )
    assert ok is True, msg
    assert os.path.isfile(os.path.join(snap_dir, "nextcloud_db.sql"))
    assert b"MySQL dump" in open(os.path.join(snap_dir, "nextcloud_db.sql"), "rb").read()
    assert os.path.isfile(os.path.join(snap_dir, "nextcloud_config.php"))
    assert os.path.isfile(os.path.join(snap_dir, "nextcloud_apps.txt"))
    assert os.path.isfile(os.path.join(snap_dir, "dashboard", "dashboard.db"))
    assert "MariaDB container is not running" not in open(bk_log).read()


def test_wait_nextcloud_ready_waits_for_apache_port_even_when_occ_returns_early():
    """Regression: _wait_nextcloud_ready must wait for TCP port 80 (entrypoint rsync/upgrade complete) even if occ status exits 0 early."""
    import ops_updates

    nc_c = MagicMock(name="nextcloud", status="running")
    nc_c.exec_run.return_value = MagicMock(exit_code=0, output=b'{"installed":true,"version":"33.0.10"}')

    port_sequence = iter([False, False, True])
    port_checks = []

    def fake_port(host, port, timeout=1.0):
        port_checks.append((host, port))
        return next(port_sequence, True)

    ok = ops_updates._wait_nextcloud_ready(
        nc_c,
        timeout_sec=5.0,
        poll_interval=0.01,
        check_port_fn=fake_port,
    )
    assert ok is True
    assert len(port_checks) == 3, "Must NOT return while Apache port 80 is closed during entrypoint rsync!"
    assert nc_c.exec_run.call_count == 1, "Should only run occ status once Apache port 80 is open"

    # Must return False cleanly on timeout when port 80 stays closed
    timed_out = ops_updates._wait_nextcloud_ready(
        nc_c,
        timeout_sec=0.05,
        poll_interval=0.01,
        check_port_fn=lambda h, p, timeout=1.0: False,
    )
    assert timed_out is False


def test_nextcloud_hands_free_update_recovers_conflicting_app_typeerror(client_env):
    """Regression: if occ upgrade hits an app TypeError under /apps/<id> or /custom_apps/<id>, disable -> core upgrade -> update/re-enable -> clear maintenance."""
    import ops_updates

    nc_c = MagicMock(name="nextcloud", status="running")
    nc_c.image = MagicMock(tags=["nextcloud:33-apache"], attrs={"RepoDigests": []})
    nc_c.attrs = {"Config": {"Image": "nextcloud:33-apache", "Env": ["TZ=UTC"]}, "HostConfig": {}, "NetworkSettings": {"Networks": {}}}

    exec_calls = []
    upgrade_attempts = {"count": 0}
    activity_disabled = {"flag": False}

    def nc_exec(cmd, **kw):
        exec_calls.append(cmd)
        if "occ maintenance:mode --off" in cmd:
            return MagicMock(exit_code=0, output=b"Maintenance mode disabled")
        if "occ upgrade --no-interaction" in cmd:
            upgrade_attempts["count"] += 1
            if not activity_disabled["flag"]:
                return MagicMock(
                    exit_code=1,
                    output=b"OCA\\Activity\\MailQueueHandler::__construct(): Argument #9 ($appConfig) must be of type OCP\\IAppConfig, OC\\AllConfig given, called in /var/www/html/apps/activity/lib/AppInfo/Application.php on line 111\nAn unhandled exception has been thrown:\nTypeError",
                )
            return MagicMock(exit_code=0, output=b"Nextcloud or one of the apps require upgrade\nUpdate successful")
        if "occ app:disable activity" in cmd:
            activity_disabled["flag"] = True
            return MagicMock(exit_code=0, output=b"activity disabled")
        if "occ app:update activity" in cmd:
            return MagicMock(exit_code=0, output=b"activity updated")
        if "occ app:enable activity" in cmd:
            activity_disabled["flag"] = False
            return MagicMock(exit_code=0, output=b"activity enabled")
        return MagicMock(exit_code=0, output=b"ok")

    nc_c.exec_run.side_effect = nc_exec
    mock_docker = MagicMock()
    mock_docker.containers.get.return_value = nc_c

    logs = []
    ok, msg = ops_updates.run_nextcloud_hands_free_update(
        docker_client=mock_docker,
        is_cancelled_fn=lambda: False,
        progress_fn=lambda pct, step, detail="": logs.append((pct, step, detail)),
        update_apps=True,
        backup_before=False,
        pull_image=False,
    )
    assert ok is True, msg
    assert upgrade_attempts["count"] == 2
    assert any("occ app:disable activity" in c for c in exec_calls)
    assert any("occ app:update activity" in c for c in exec_calls)
    assert any("occ app:enable activity" in c for c in exec_calls)
    assert any("occ db:add-missing-indices" in c for c in exec_calls)
    assert "occ maintenance:mode --off" in exec_calls[-1]


def test_streaming_image_pull_reports_progress_and_supports_cancel():
    """Regression: image pull must stream layer progress incrementally and abort immediately on cancel without stopping the container."""
    import ops_updates

    c = MagicMock()
    c.name = "nginx-proxy"
    c.status = "running"
    c.image = MagicMock(tags=["jc21/nginx-proxy-manager:latest"])
    c.attrs = {"Config": {"Image": "jc21/nginx-proxy-manager:latest"}, "HostConfig": {}, "NetworkSettings": {"Networks": {}}}

    # Fake streaming pull generator returning layer byte progress
    class FakeStream:
        def __init__(self, events):
            self._it = iter(events)
            self.closed = False
        def __iter__(self):
            return self
        def __next__(self):
            return next(self._it)
        def close(self):
            self.closed = True

    stream_ok = FakeStream([
        {"id": "l1", "status": "Downloading", "progressDetail": {"current": 50_000_000, "total": 200_000_000}},
        {"id": "l2", "status": "Downloading", "progressDetail": {"current": 150_000_000, "total": 200_000_000}},
        {"id": "l1", "status": "Extracting", "progressDetail": {"current": 200_000_000, "total": 200_000_000}},
        {"id": "l2", "status": "Extracting", "progressDetail": {"current": 200_000_000, "total": 200_000_000}},
        {"status": "Status: Downloaded newer image for jc21/nginx-proxy-manager:latest"},
    ])

    mock_docker = MagicMock()
    mock_docker.containers.get.return_value = c
    mock_docker.api.pull.return_value = stream_ok
    new_c = MagicMock(name="nginx-proxy", status="running")
    mock_docker.containers.run.return_value = new_c

    prog_events = []
    ok, msg = ops_updates.recreate_container_with_latest_image(
        mock_docker,
        "nginx-proxy",
        progress_fn=lambda pct, step, detail="": prog_events.append((pct, step, detail)),
        is_cancelled_fn=lambda: False,
    )
    assert ok is True, msg
    assert mock_docker.api.pull.called
    mock_docker.images.pull.assert_not_called()
    assert any("%" in detail or "Pulling" in detail for _, _, detail in prog_events)
    # Must show sub-progress between 35 and 65 during download/extract
    pull_pcts = [pct for pct, _, _ in prog_events if 35 <= pct <= 62]
    assert len(set(pull_pcts)) >= 2, f"Expected advancing pull percentages, got {prog_events}"

    # Cancel mid-stream MUST abort without stopping container
    c2 = MagicMock()
    c2.name = "nginx-proxy"
    c2.status = "running"
    c2.image = MagicMock(tags=["jc21/nginx-proxy-manager:latest"])
    c2.attrs = {"Config": {"Image": "jc21/nginx-proxy-manager:latest"}, "HostConfig": {}, "NetworkSettings": {"Networks": {}}}
    stream_cancel = FakeStream([
        {"id": "l1", "status": "Downloading", "progressDetail": {"current": 10_000_000, "total": 200_000_000}},
        {"id": "l1", "status": "Downloading", "progressDetail": {"current": 20_000_000, "total": 200_000_000}},
    ])
    mock_docker2 = MagicMock()
    mock_docker2.containers.get.return_value = c2
    mock_docker2.api.pull.return_value = stream_cancel
    cancel_state = {"calls": 0}
    def cancel_after_one():
        cancel_state["calls"] += 1
        return cancel_state["calls"] >= 2

    ok2, msg2 = ops_updates.recreate_container_with_latest_image(
        mock_docker2,
        "nginx-proxy",
        progress_fn=lambda *a: None,
        is_cancelled_fn=cancel_after_one,
    )
    assert ok2 is False
    assert "cancel" in msg2.lower()
    assert stream_cancel.closed is True
    c2.stop.assert_not_called()
    c2.rename.assert_not_called()


def test_stale_running_job_recovery_and_force_cancel_and_subprogress(client_env):
    """Regression: startup recovers orphaned running jobs, second cancel click force-cancels stalled jobs, and 'all' advances percentage within a service."""
    client, _, _, _ = client_env
    import ops_updates

    db = app_module.get_db()
    c1 = db.execute("INSERT INTO update_jobs (target, status, progress_pct, current_step) VALUES ('all', 'running', 50, 'Pulling image jc21/nginx-proxy-manager:latest')")
    stale_id = c1.lastrowid
    c2 = db.execute("INSERT INTO update_jobs (target, status, progress_pct, current_step) VALUES ('pihole', 'completed', 100, 'Completed')")
    done_id = c2.lastrowid
    db.commit()

    recovered = ops_updates.recover_stale_running_jobs(db)
    assert recovered >= 1
    row_stale = dict(db.execute("SELECT * FROM update_jobs WHERE id=?", (stale_id,)).fetchone())
    row_done = dict(db.execute("SELECT * FROM update_jobs WHERE id=?", (done_id,)).fetchone())
    assert row_stale["status"] == "failed"
    assert "restart" in (row_stale["error"] or "").lower()
    assert row_done["status"] == "completed"

    # Second cancel click force-cancels a stalled running job immediately
    c3 = db.execute("INSERT INTO update_jobs (target, status, progress_pct, current_step, cancel_requested) VALUES ('nginx-proxy', 'running', 50, 'Pulling...', 0)")
    hung_id = c3.lastrowid
    db.commit()
    db.close()

    r1 = client.post(f"/api/updates/{hung_id}/cancel")
    assert r1.status_code == 200
    assert r1.json()["status"] == "cancelling"
    r2 = client.post(f"/api/updates/{hung_id}/cancel")
    assert r2.status_code == 200
    assert r2.json()["status"] == "cancelled"
    jobs = {j["id"]: j for j in client.get("/api/updates/jobs").json()}
    assert jobs[hung_id]["status"] == "cancelled"

    # 'all' job advances progress_pct within a service slice instead of staying frozen at base_pct
    db = app_module.get_db()
    c4 = db.execute("INSERT INTO update_jobs (target, status, current_step) VALUES ('all', 'queued', 'Queued')")
    all_id = c4.lastrowid
    db.commit()
    db.close()

    seen_pcts = []
    cached = {
        "services": [{"name": "nginx-proxy", "update_available": True}],
        "ytdlp_info": {"update_available": False},
    }

    def fake_recreate(dc, name, progress_fn=None, is_cancelled_fn=None):
        progress_fn(35, "Pulling", "Pulling...")
        seen_pcts.append(app_module.get_db().execute("SELECT progress_pct FROM update_jobs WHERE id=?", (all_id,)).fetchone()["progress_pct"])
        progress_fn(60, "Pulling (100%)", "Pulling 100%")
        seen_pcts.append(app_module.get_db().execute("SELECT progress_pct FROM update_jobs WHERE id=?", (all_id,)).fetchone()["progress_pct"])
        return True, "Updated"

    with patch("ops_updates.check_all_updates", return_value=cached), \
         patch("ops_updates.recreate_container_with_latest_image", side_effect=fake_recreate):
        ops_updates.run_update_job(
            job_id=all_id,
            db_factory=app_module.get_db,
            docker_client=MagicMock(),
            managed_services=["nginx-proxy"],
        )
    assert len(set(seen_pcts)) >= 2 and seen_pcts[1] > seen_pcts[0], f"Expected sub-step progress increase, got {seen_pcts}"


def test_nextcloud_major_version_tag_bump_from_33_to_34(client_env):
    """Regression: when Nextcloud runs pinned tag nextcloud:33-apache (33.0.10) and occ update:check reports Core 34.0.5, hands-free update must bump image tag +1 major to nextcloud:34-apache."""
    import ops_updates

    # 1. Unit checks for _resolve_nextcloud_target_image
    assert ops_updates._resolve_nextcloud_target_image(
        "nextcloud:33-apache",
        {"version": "33.0.10", "core_update_available": True, "available_version": "34.0.5"},
    ) == "nextcloud:34-apache"
    # Never skip a major version (32 -> 33 before 34)
    assert ops_updates._resolve_nextcloud_target_image(
        "nextcloud:32-fpm-alpine",
        {"version": "32.0.9", "core_update_available": True, "available_version": "34.0.5"},
    ) == "nextcloud:33-fpm-alpine"
    # Same-major patch stays on same tag
    assert ops_updates._resolve_nextcloud_target_image(
        "nextcloud:34-apache",
        {"version": "34.0.1", "core_update_available": True, "available_version": "34.0.5"},
    ) == "nextcloud:34-apache"

    # 2. End-to-end Nextcloud hands-free update where 33-apache digest is unchanged, yet 34.0.5 is available
    old_nc = MagicMock()
    old_nc.name = "nextcloud"
    old_nc.status = "running"
    old_nc.image = MagicMock(tags=["nextcloud:33-apache"], attrs={"RepoDigests": ["nextcloud@sha256:digest33"]})
    old_nc.attrs = {"Config": {"Image": "nextcloud:33-apache", "Env": ["TZ=UTC"]}, "HostConfig": {}, "NetworkSettings": {"Networks": {}}}

    def old_exec(cmd, **kw):
        if "status --output=json" in cmd:
            return MagicMock(exit_code=0, output=b'{"versionstring":"33.0.10","maintenance":false}')
        if "update:check" in cmd:
            return MagicMock(exit_code=0, output=b"Nextcloud 34.0.5 is available.")
        return MagicMock(exit_code=0, output=b"{}")

    old_nc.exec_run.side_effect = old_exec

    new_nc = MagicMock()
    new_nc.name = "nextcloud"
    new_nc.status = "running"
    new_nc.image = MagicMock(tags=["nextcloud:34-apache"], attrs={"RepoDigests": ["nextcloud@sha256:digest34"]})
    new_exec_calls = []

    def new_exec(cmd, **kw):
        new_exec_calls.append(cmd)
        if "status --output=json" in cmd:
            return MagicMock(exit_code=0, output=b'{"versionstring":"34.0.5","maintenance":false}')
        return MagicMock(exit_code=0, output=b"ok")

    new_nc.exec_run.side_effect = new_exec

    state = {"nc": old_nc}
    mock_docker = MagicMock()
    mock_docker.containers.get.side_effect = lambda n: state["nc"] if n == "nextcloud" else MagicMock(status="running")

    def run_new(image, **kw):
        state["nc"] = new_nc
        return new_nc

    mock_docker.containers.run.side_effect = run_new
    mock_docker.images.get_registry_data.side_effect = lambda ref: MagicMock(
        id="sha256:digest34" if "34-apache" in ref else "sha256:digest33"
    )

    with patch("ops_resources._default_check_port", return_value=True):
        ok, msg = ops_updates.run_nextcloud_hands_free_update(
            docker_client=mock_docker,
            is_cancelled_fn=lambda: False,
            progress_fn=lambda *a: None,
            update_apps=True,
            backup_before=False,
            pull_image=True,
        )
    assert ok is True, msg
    mock_docker.images.pull.assert_called_once_with("nextcloud:34-apache")
    assert mock_docker.containers.run.call_args.args[0] == "nextcloud:34-apache"
    assert any("occ upgrade --no-interaction" in c for c in new_exec_calls)


def test_nextcloud_sequential_multi_major_upgrade_steps_one_by_one(client_env):
    """Regression: multi-major Nextcloud upgrades (e.g. 32 -> 34) MUST upgrade sequentially 32 -> 33 -> 34 (one major at a time, never skipping), including unpinned tags."""
    import ops_updates

    # 1. Unpinned tags (:apache, :latest) also resolve to sequential +1 major tags
    assert ops_updates._resolve_nextcloud_target_image(
        "nextcloud:apache",
        {"version": "32.0.9", "core_update_available": True, "available_version": "34.0.5"},
    ) == "nextcloud:33-apache"
    assert ops_updates._resolve_nextcloud_target_image(
        "nextcloud:latest",
        {"version": "32.0.9", "core_update_available": True, "available_version": "34.0.5"},
    ) == "nextcloud:33"

    # 2. Sequential 32 -> 33 -> 34 multi-hop execution in one click
    nc_32 = MagicMock()
    nc_32.name = "nextcloud"
    nc_32.status = "running"
    nc_32.image = MagicMock(tags=["nextcloud:32-apache"], attrs={"RepoDigests": ["nextcloud@sha256:d32"]})
    nc_32.attrs = {"Config": {"Image": "nextcloud:32-apache", "Env": ["TZ=UTC"]}, "HostConfig": {}, "NetworkSettings": {"Networks": {}}}
    nc_32.exec_run.side_effect = lambda cmd, **kw: (
        MagicMock(exit_code=0, output=b'{"versionstring":"32.0.9","maintenance":false}') if "status --output=json" in cmd else
        MagicMock(exit_code=0, output=b"Nextcloud 34.0.5 is available.") if "update:check" in cmd else
        MagicMock(exit_code=0, output=b"ok")
    )

    nc_33 = MagicMock()
    nc_33.name = "nextcloud"
    nc_33.status = "running"
    nc_33.image = MagicMock(tags=["nextcloud:33-apache"], attrs={"RepoDigests": ["nextcloud@sha256:d33"]})
    nc_33.attrs = {"Config": {"Image": "nextcloud:33-apache", "Env": ["TZ=UTC"]}, "HostConfig": {}, "NetworkSettings": {"Networks": {}}}
    nc33_calls = []
    def nc33_exec(cmd, **kw):
        nc33_calls.append(cmd)
        if "status --output=json" in cmd:
            return MagicMock(exit_code=0, output=b'{"versionstring":"33.0.10","maintenance":false}')
        if "update:check" in cmd:
            return MagicMock(exit_code=0, output=b"Nextcloud 34.0.5 is available.")
        return MagicMock(exit_code=0, output=b"ok")
    nc_33.exec_run.side_effect = nc33_exec

    nc_34 = MagicMock()
    nc_34.name = "nextcloud"
    nc_34.status = "running"
    nc_34.image = MagicMock(tags=["nextcloud:34-apache"], attrs={"RepoDigests": ["nextcloud@sha256:d34"]})
    nc_34.attrs = {"Config": {"Image": "nextcloud:34-apache", "Env": ["TZ=UTC"]}, "HostConfig": {}, "NetworkSettings": {"Networks": {}}}
    nc34_calls = []
    def nc34_exec(cmd, **kw):
        nc34_calls.append(cmd)
        if "status --output=json" in cmd:
            return MagicMock(exit_code=0, output=b'{"versionstring":"34.0.5","maintenance":false}')
        if "update:check" in cmd:
            return MagicMock(exit_code=0, output=b"Everything up to date")
        return MagicMock(exit_code=0, output=b"ok")
    nc_34.exec_run.side_effect = nc34_exec

    state = {"nc": nc_32}
    pulled = []
    run_order = []

    mock_docker = MagicMock()
    mock_docker.containers.get.side_effect = lambda n: state["nc"] if n == "nextcloud" else MagicMock(status="running")
    mock_docker.images.pull.side_effect = lambda ref: pulled.append(ref)

    def run_side(image, **kw):
        run_order.append(image)
        if "33-apache" in image:
            state["nc"] = nc_33
            return nc_33
        if "34-apache" in image:
            state["nc"] = nc_34
            return nc_34
        raise AssertionError(f"Unexpected image jump: {image}")

    mock_docker.containers.run.side_effect = run_side
    mock_docker.images.get_registry_data.side_effect = lambda ref: MagicMock(
        id=("sha256:d34" if "34" in ref else "sha256:d33" if "33" in ref else "sha256:d32")
    )

    with patch("ops_resources._default_check_port", return_value=True):
        ok, msg = ops_updates.run_nextcloud_hands_free_update(
            docker_client=mock_docker,
            is_cancelled_fn=lambda: False,
            progress_fn=lambda *a: None,
            update_apps=True,
            backup_before=False,
            pull_image=True,
        )

    assert ok is True, msg
    assert pulled == ["nextcloud:33-apache", "nextcloud:34-apache"], f"Must upgrade sequentially +1 major at a time! Got {pulled}"
    assert run_order == ["nextcloud:33-apache", "nextcloud:34-apache"]
    assert any("occ upgrade --no-interaction" in c for c in nc33_calls), "Must run occ upgrade on intermediate v33 before moving to v34!"
    assert any("occ upgrade --no-interaction" in c for c in nc34_calls), "Must run occ upgrade on v34!"


def test_samba_not_in_default_sleep_targets_and_auto_recovered_when_not_targeted(client_env):
    """Regression: samba lacks a default WakeProxy on port 445, so it must NOT be auto-stopped by default Eco-Sleep, and exited samba not in sleep_targets recovers on boot."""
    import ops_resources

    db = app_module.get_db()
    # Ensure no explicit sleep_targets row exists (default behavior)
    db.execute("DELETE FROM settings WHERE key IN ('sleep_targets', 'eco_sleep_enabled', 'container_idle_sleep_enabled', 'server_idle_sleep_enabled')")
    db.commit()

    cfg = ops_resources.get_sleep_settings(db)
    assert "samba" not in cfg["sleep_targets"], "samba must not be auto-slept by default without an active SMB wake-proxy!"
    for svc in ("nextcloud", "mariadb", "redis", "navidrome", "maloja"):
        assert svc in cfg["sleep_targets"]

    # After 40 minutes idle with default settings, samba MUST stay running
    now = 3_000_000.0
    ops_resources.reset_idle_trackers(now_ts=now - 2400.0)
    samba_c = MagicMock(name="samba", status="running")
    nav_c = MagicMock(name="navidrome", status="running")
    cmap = {"samba": samba_c, "navidrome": nav_c}
    mock_docker = MagicMock()
    mock_docker.containers.list.return_value = [samba_c, nav_c]
    mock_docker.containers.get.side_effect = lambda n: cmap[n]

    res = ops_resources.evaluate_idle_sleep(db, mock_docker, now_ts=now)
    assert "samba" not in res["slept"]
    samba_c.stop.assert_not_called()

    # Boot recovery helper restarts exited samba when samba is not in sleep_targets, while leaving sleeping navidrome paused/exited
    samba_exited = MagicMock(name="samba", status="exited")
    nav_exited = MagicMock(name="navidrome", status="exited")
    mock_docker2 = MagicMock()
    mock_docker2.containers.get.side_effect = lambda n: {"samba": samba_exited, "navidrome": nav_exited}[n]
    woken = ops_resources.recover_untargeted_sleeping_containers(db, mock_docker2)
    db.close()
    assert "samba" in woken
    samba_exited.start.assert_called_once()
    nav_exited.start.assert_not_called()


def test_wait_nextcloud_ready_uses_600s_budget_and_emits_heartbeat():
    """Regression: Nextcloud major upgrades on Celeron HDD need >=600s startup wait with progress heartbeats."""
    import ops_updates

    nc_c = MagicMock(name="nextcloud", status="running")
    nc_c.exec_run.return_value = MagicMock(exit_code=0, output=b'{"installed":true}')

    # Simulate 25s of closed port 80 followed by open port 80 via stepped time
    fake_t = {"t": 100.0}
    port_calls = {"n": 0}
    def fake_time():
        return fake_t["t"]
    def fake_sleep(s):
        fake_t["t"] += 15.0
    def fake_port(host, port, timeout=1.0):
        port_calls["n"] += 1
        return port_calls["n"] >= 3

    hb_logs = []
    with patch.object(ops_updates.time, "time", side_effect=fake_time), \
         patch.object(ops_updates.time, "sleep", side_effect=fake_sleep):
        ok = ops_updates._wait_nextcloud_ready(
            nc_c,
            check_port_fn=fake_port,
            progress_fn=lambda pct, st, msg="": hb_logs.append((pct, st, msg)),
        )
    assert ok is True
    assert len(hb_logs) >= 2, f"Expected initial + heartbeat progress logs while waiting, got {hb_logs}"
    import inspect
    default_timeout = inspect.signature(ops_updates._wait_nextcloud_ready).parameters["timeout_sec"].default
    assert default_timeout >= 600.0


def test_harvester_suppresses_spurious_alerts_for_eco_sleeping_containers(client_env):
    """Regression: Eco-Sleep stopping a targeted container (exit code 143) must not log 'unhealthy'/'exited' error spam."""
    if hasattr(app_module, "_harvester_dedup_cache"):
        app_module._harvester_dedup_cache.clear()

    db = app_module.get_db()
    db.execute("DELETE FROM activity_log WHERE category='containers'")
    db.execute("DELETE FROM settings WHERE key='sleep_targets'")
    db.commit()
    db.close()

    nav_sleeping = MagicMock()
    nav_sleeping.name = "navidrome"
    nav_sleeping.status = "exited"
    nav_sleeping.attrs = {"State": {"Health": {"Status": "unhealthy"}, "ExitCode": 143}}
    nav_sleeping.logs.return_value = b""

    mock_docker = MagicMock()
    mock_docker.containers.list.return_value = [nav_sleeping]
    orig_docker = app_module.docker_client
    app_module.docker_client = mock_docker
    try:
        app_module.harvest_system_and_container_logs()
        db = app_module.get_db()
        rows = db.execute("SELECT * FROM activity_log WHERE category='containers' AND target='navidrome'").fetchall()
        db.close()
        assert len(rows) == 0, f"Unexpected container error/warning logs for intentionally sleeping navidrome: {[dict(r) for r in rows]}"
    finally:
        app_module.docker_client = orig_docker









