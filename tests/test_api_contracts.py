"""
Comprehensive API Contract & Regression Test Suite
Validates:
  1. Database initialization and migrations
  2. Dual-hash password verification (legacy SHA-256 transparent upgrade to scrypt)
  3. Session authentication & access controls
  4. 100% frozen frontend API JSON schemas (preventing JavaScript errors in dashboard.html)
  5. PWA manifest and service worker delivery
"""

import os
import re
import sys
import tempfile
import sqlite3
import hashlib
import time
import subprocess
import pytest
from starlette.testclient import TestClient

ADMIN_DASHBOARD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "admin-dashboard")
sys.path.insert(0, ADMIN_DASHBOARD_DIR)

import app as app_module

def _fetch_spa_bundle(client):
    """Fetch /dashboard HTML and its compiled Preact JS + CSS assets served by FastAPI."""
    res = client.get("/dashboard")
    assert res.status_code == 200
    html = res.text
    combined = html
    for asset_path in re.findall(r'(?:src|href)="(/assets/[^"]+)"', html):
        asset_res = client.get(asset_path)
        assert asset_res.status_code == 200, f"SPA asset {asset_path} returned {asset_res.status_code}"
        combined += "\n" + asset_res.text
    return html, combined

@pytest.fixture(scope="module")
def test_env():
    """Sets up an isolated SQLite database and test client."""
    td_kwargs = {"ignore_cleanup_errors": True} if sys.version_info >= (3, 10) else {}
    with tempfile.TemporaryDirectory(**td_kwargs) as tmpdir:
        test_db = os.path.join(tmpdir, "test_dashboard.db")
        app_module.DB_PATH = test_db
        app_module.init_db()

        # Seed with legacy SHA-256 admin password to test transparent migration
        legacy_hash = hashlib.sha256("admin123".encode()).hexdigest()
        db = app_module.get_db()
        db.execute("DELETE FROM admins")
        db.execute("INSERT INTO admins (username, password_hash) VALUES (?, ?)", ("admin", legacy_hash))
        db.commit()
        db.close()

        client = TestClient(app_module.app, follow_redirects=False)
        try:
            yield client, test_db
        finally:
            client.close()
            import gc
            gc.collect()

def test_pwa_static_assets(test_env):
    """Verify PWA manifest and service worker are served properly."""
    client, _ = test_env
    res = client.get("/static/manifest.json")
    assert res.status_code == 200
    manifest = res.json()
    assert manifest["name"] == "Homelab Admin OS"
    assert manifest["display"] == "standalone"
    assert manifest["start_url"] == "/dashboard"

    sw_res = client.get("/static/sw.js")
    assert sw_res.status_code == 200
    assert "self.addEventListener('fetch'" in sw_res.text

def test_unauthenticated_redirects(test_env):
    """Verify all protected routes redirect unauthenticated users to /login."""
    client, _ = test_env
    # Index redirect
    res = client.get("/")
    assert res.status_code == 303
    assert res.headers["location"] == "/login"

    # Dashboard redirect
    res = client.get("/dashboard")
    assert res.status_code == 303
    assert res.headers["location"] == "/login"

    # Protected API endpoints redirect
    protected_apis = [
        "/api/system",
        "/api/containers",
        "/api/users",
        "/api/backup/status",
        "/api/logs",
        "/api/bans",
        "/api/login-attempts",
        "/api/network/live",
        "/api/settings/zero-trust",
    ]
    for endpoint in protected_apis:
        res = client.get(endpoint)
        assert res.status_code == 303, f"Endpoint {endpoint} returned status {res.status_code} instead of 303"
        assert res.headers["location"] == "/login"

def test_dual_hash_migration(test_env):
    """Verify legacy SHA-256 passwords verify and transparently upgrade to scrypt in DB."""
    client, test_db = test_env
    
    # Check DB initial hash is SHA-256 (64 hex characters)
    conn = sqlite3.connect(test_db)
    row = conn.execute("SELECT password_hash FROM admins WHERE username='admin'").fetchone()
    conn.close()
    assert len(row[0]) == 64  # SHA-256 hex string

    # Perform login with valid password
    res = client.post("/login", data={"username": "admin", "password": "admin123"})
    assert res.status_code == 303
    assert res.headers["location"] == "/dashboard"

    # Verify password hash in DB was upgraded to scrypt
    conn = sqlite3.connect(test_db)
    row = conn.execute("SELECT password_hash FROM admins WHERE username='admin'").fetchone()
    conn.close()
    assert row[0].startswith("scrypt:")

def test_authenticated_dashboard_and_apis(test_env):
    """Verify dashboard loads and all API contracts match the frontend requirements."""
    client, _ = test_env
    # Login
    login_res = client.post("/login", data={"username": "admin", "password": "admin123"})
    assert login_res.status_code == 303

    # Access dashboard HTML & compiled Preact SPA bundle
    html, bundle = _fetch_spa_bundle(client)
    assert "Homelab" in html
    assert "/static/manifest.json" in html
    assert "Offline Mode" in bundle

    # 1. System API Contract
    sys_res = client.get("/api/system")
    assert sys_res.status_code == 200
    s_data = sys_res.json()
    expected_sys_keys = [
        "cpu_percent", "cpu_count", "cpu_freq_ghz",
        "ram_used_gb", "ram_total_gb", "ram_percent",
        "disk_used_gb", "disk_total_gb", "disk_percent",
        "uptime", "temperatures", "battery", "backup_mounted"
    ]
    for k in expected_sys_keys:
        assert k in s_data, f"Missing key '{k}' in /api/system response"

    # 2. Containers API Contract
    c_res = client.get("/api/containers")
    assert c_res.status_code == 200
    assert isinstance(c_res.json(), list)

    # 3. Users API Contract (CRUD)
    u_res = client.get("/api/users")
    assert u_res.status_code == 200
    assert isinstance(u_res.json(), list)

    # 4. Music API Contract
    m_status = client.get("/api/music/status")
    assert m_status.status_code == 200
    m_data = m_status.json()
    for field in ["navidrome_running", "navidrome_url", "music_dir", "music_dir_exists", "music_file_count", "artists_count", "albums_count", "last_scan"]:
        assert field in m_data, f"Missing required field '{field}' in /api/music/status"
    assert isinstance(m_data["navidrome_running"], bool)
    assert isinstance(m_data["navidrome_url"], str)
    assert isinstance(m_data["music_dir"], str)
    assert isinstance(m_data["music_dir_exists"], bool)
    assert isinstance(m_data["music_file_count"], int)
    assert isinstance(m_data["artists_count"], int)
    assert isinstance(m_data["albums_count"], int)
    assert isinstance(m_data["last_scan"], str)

    m_stats = client.get("/api/music/stats")
    assert m_stats.status_code == 200
    assert "total_plays" in m_stats.json()
    assert "unique_users" in m_stats.json()

    rec_res = client.get("/api/music/recommendations/admin")
    assert rec_res.status_code == 200
    assert "playlist_suggestions" in rec_res.json()

    # 5. Download Queue Contract
    q_res = client.get("/api/music/queue")
    assert q_res.status_code == 200
    assert isinstance(q_res.json(), list)

    add_dl = client.post("/api/music/download", json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "quality": "320k"})
    assert add_dl.status_code == 200
    job_id = add_dl.json()["job_id"]

    cancel_res = client.post(f"/api/music/queue/{job_id}/cancel")
    assert cancel_res.status_code == 200
    retry_res = client.post(f"/api/music/queue/{job_id}/retry")
    assert retry_res.status_code == 200
    del_job_res = client.post(f"/api/music/queue/{job_id}/delete")
    assert del_job_res.status_code == 200

    # 6. Backup API Contract
    bk_res = client.get("/api/backup/status")
    assert bk_res.status_code == 200
    bk_data = bk_res.json()
    assert "mounted" in bk_data
    assert "last_logs" in bk_data

    # 7. Network APIs
    net_live = client.get("/api/network/live")
    assert net_live.status_code == 200
    net_hist = client.get("/api/network/history")
    assert net_hist.status_code == 200
    assert "rows" in net_hist.json()

    net_sum = client.get("/api/network/summary")
    assert net_sum.status_code == 200
    assert "today" in net_sum.json()
    assert "top_containers_24h" in net_sum.json()

    # 8. Logs & Security
    logs_res = client.get("/api/logs")
    assert logs_res.status_code == 200
    assert isinstance(logs_res.json(), list)

    attempts_res = client.get("/api/login-attempts")
    assert attempts_res.status_code == 200
    assert isinstance(attempts_res.json(), list)

    bans_res = client.get("/api/bans")
    assert bans_res.status_code == 200
    assert isinstance(bans_res.json(), list)

def test_change_password_workflow(test_env):
    """Verify password change route enforces validation and updates credentials."""
    client, _ = test_env
    # Try invalid password length (< 8)
    res = client.post("/api/admin/change-password", json={"current": "admin123", "new": "short"})
    assert res.status_code == 400

    # Try wrong current password
    res = client.post("/api/admin/change-password", json={"current": "wrongpassword", "new": "newsecret123"})
    assert res.status_code == 403

    # Successfully update password
    res = client.post("/api/admin/change-password", json={"current": "admin123", "new": "newsecret123"})
    assert res.status_code == 200
    assert res.json().get("ok") is True

    # Test login with old password fails
    client.get("/logout")
    bad_login = client.post("/login", data={"username": "admin", "password": "admin123"})
    assert bad_login.status_code == 200  # returns login.html with error

    # Test login with new password succeeds
    good_login = client.post("/login", data={"username": "admin", "password": "newsecret123"})
    assert good_login.status_code == 303
    assert good_login.headers["location"] == "/dashboard"

def test_navidrome_dynamic_url_resolution(test_env):
    """Verify ZERO HARDCODING dynamic origin resolution for Navidrome URL."""
    client, _ = test_env
    # Login
    client.post("/login", data={"username": "admin", "password": "newsecret123"})

    # 1. Port mapping (e.g. 5001 -> 4533)
    res = client.get("/api/music/status", headers={"x-forwarded-host": "192.168.1.50:5001", "x-forwarded-proto": "http"})
    assert res.status_code == 200
    assert res.json()["navidrome_url"] == "http://192.168.1.50:4533"

    # 2. Alternative dashboard port (e.g. 2081 -> 4533)
    res = client.get("/api/music/status", headers={"x-forwarded-host": "homelab.local:2081", "x-forwarded-proto": "http"})
    assert res.status_code == 200
    assert res.json()["navidrome_url"] == "http://homelab.local:4533"

    # 3. HTTPS and Subdomain mapping (dashboard.domain -> navidrome.domain)
    res = client.get("/api/music/status", headers={"x-forwarded-host": "dashboard.homelab.me", "x-forwarded-proto": "https"})
    assert res.status_code == 200
    assert res.json()["navidrome_url"] in ("https://navidrome.homelab.me", "https://music.homelab.me", "https://dashboard.homelab.me:4533")

    # 4. Fallback to NAVIDROME_PUBLIC_URL when set
    os.environ["NAVIDROME_PUBLIC_URL"] = "https://navidrome.custom-domain.org"
    try:
        res = client.get("/api/music/status", headers={"host": ""})
        assert res.status_code == 200
        # If no host header provided, fallback to NAVIDROME_PUBLIC_URL
        assert res.json()["navidrome_url"] == "https://navidrome.custom-domain.org"
    finally:
        del os.environ["NAVIDROME_PUBLIC_URL"]

def test_music_dashboard_cards_and_no_ai_notices(test_env):
    """Verify outdated setup and remove AI cards are gone, and live library cards are present in Preact SPA."""
    client, _ = test_env
    _, bundle = _fetch_spa_bundle(client)
    # Verify outdated setup / remove AI cards are removed
    assert "Remove AI containers" not in bundle
    assert "docker stop ollama" not in bundle
    assert "Step 1 — Music folder" not in bundle

    # Verify live library cards are present
    assert "Artists" in bundle
    assert "Albums" in bundle
    assert "Total Songs" in bundle
    assert "Last scan:" in bundle or "Last Scan" in bundle
    assert "Launch Web Player" in bundle or "Open Navidrome" in bundle

def test_music_status_directory_scanning(test_env):
    """Verify live music directory scanning estimates artists, albums, songs and last scan timestamp."""
    client, _ = test_env
    orig_music_dir = app_module.MUSIC_DIR
    with tempfile.TemporaryDirectory() as tmp_music:
        # Create test folder structure
        artist1_alb1 = os.path.join(tmp_music, "Radiohead", "OK Computer")
        artist1_alb2 = os.path.join(tmp_music, "Radiohead", "Kid A")
        artist2_alb1 = os.path.join(tmp_music, "Daft Punk", "Discovery")
        os.makedirs(artist1_alb1, exist_ok=True)
        os.makedirs(artist1_alb2, exist_ok=True)
        os.makedirs(artist2_alb1, exist_ok=True)

        # Create audio files
        with open(os.path.join(artist1_alb1, "01_airbag.flac"), "w") as f:
            f.write("mock audio")
        with open(os.path.join(artist1_alb2, "01_everything.mp3"), "w") as f:
            f.write("mock audio")
        with open(os.path.join(artist2_alb1, "01_one_more_time.ogg"), "w") as f:
            f.write("mock audio")

        app_module.MUSIC_DIR = tmp_music
        try:
            res = client.get("/api/music/status")
            assert res.status_code == 200
            data = res.json()
            assert data["music_dir_exists"] is True
            assert data["music_file_count"] == 3
            assert data["artists_count"] == 2
            assert data["albums_count"] == 3
            assert data["last_scan"] != "Never"
            assert "-" in data["last_scan"]  # YYYY-MM-DD format
        finally:
            app_module.MUSIC_DIR = orig_music_dir

def test_download_formats_and_schema_migration(test_env):
    """Verify database schema, safe migrations, format handling, and title cleaning."""
    client, test_db = test_env
    # 1. Verify schema columns in current DB
    conn = sqlite3.connect(test_db)
    cols = [col[1] for col in conn.execute("PRAGMA table_info(download_queue)").fetchall()]
    conn.close()
    assert "pid" in cols
    assert "format" in cols

    # 2. Verify migration logic on a legacy database missing pid and format
    with tempfile.TemporaryDirectory() as tmp_legacy_dir:
        legacy_db = os.path.join(tmp_legacy_dir, "legacy.db")
        l_conn = sqlite3.connect(legacy_db)
        l_conn.execute("""
            CREATE TABLE download_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT NOT NULL,
                title TEXT,
                platform TEXT,
                status TEXT DEFAULT 'queued',
                total_tracks INTEGER DEFAULT 1,
                completed_tracks INTEGER DEFAULT 0,
                current_track TEXT,
                current_track_pct INTEGER DEFAULT 0,
                quality TEXT DEFAULT '320',
                error TEXT,
                requested_by TEXT,
                is_playlist INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now')),
                completed_at TEXT
            )
        """)
        l_conn.commit()
        l_conn.close()

        orig_db = app_module.DB_PATH
        app_module.DB_PATH = legacy_db
        try:
            app_module.init_db()
            migrated_conn = sqlite3.connect(legacy_db)
            migrated_cols = [c[1] for c in migrated_conn.execute("PRAGMA table_info(download_queue)").fetchall()]
            migrated_conn.close()
            assert "pid" in migrated_cols
            assert "format" in migrated_cols
        finally:
            app_module.DB_PATH = orig_db

    # 3. Verify title cleaning function
    assert app_module.clean_track_title("Never Gonna Give You Up (Official Music Video)") == "Never Gonna Give You Up"
    assert app_module.clean_track_title("Rick Astley - Never Gonna Give You Up (Official Video)") == "Rick Astley - Never Gonna Give You Up"
    assert app_module.clean_track_title("Song Name [Official Audio]") == "Song Name"
    assert app_module.clean_track_title("Track [Lyrics]") == "Track"
    assert app_module.clean_track_title("Track (Lyric Video)") == "Track"
    assert app_module.clean_track_title("Track [Visualizer]") == "Track"
    assert app_module.clean_track_title("Track (Audio)") == "Track"
    assert app_module.clean_track_title("Track (Official HD Video)") == "Track"
    assert app_module.clean_track_title("Track (Official 4K Video)") == "Track"
    assert app_module.clean_track_title("Track (Official Video) [Lyrics]") == "Track"

    # 4. Verify queue creation with different formats (flac, opus, mp3_320, wav, m4a, mp3_256)
    test_formats = ["flac", "opus", "mp3_320", "wav", "m4a", "mp3_256"]
    created_jobs = {}
    for fmt in test_formats:
        url = f"https://www.youtube.com/watch?v=mock_{fmt}"
        res = client.post("/api/music/download", json={"url": url, "format": fmt})
        assert res.status_code == 200, f"Failed for format {fmt}: {res.text}"
        data = res.json()
        assert data["ok"] is True
        assert data["format"] == fmt
        created_jobs[data["job_id"]] = fmt

    # Verify queue retrieval includes correct format and pid column
    q_res = client.get("/api/music/queue")
    assert q_res.status_code == 200
    queue_data = q_res.json()
    queue_map = {row["id"]: row for row in queue_data}

    for jid, expected_fmt in created_jobs.items():
        assert jid in queue_map
        assert queue_map[jid]["format"] == expected_fmt
        assert "pid" in queue_map[jid]
        assert isinstance(queue_map[jid]["pid"], int)

def test_download_cancellation_with_pid(test_env):
    """Verify PID tracking and cancellation of downloading / queued items."""
    client, test_db = test_env

    # 1. Spawn a mock long-running process to test process kill
    dummy_proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    pid = dummy_proc.pid

    # Insert a downloading job into the database with this PID
    conn = sqlite3.connect(test_db)
    cur = conn.execute(
        "INSERT INTO download_queue (url, platform, requested_by, status, quality, format, pid) "
        "VALUES (?,?,?,?,?,?,?)",
        ("https://example.com/mock_active_download", "youtube", "admin", "downloading", "flac", "flac", pid)
    )
    job_id = cur.lastrowid
    conn.commit()
    conn.close()

    try:
        # Cancel the download via API
        cancel_res = client.post(f"/api/music/queue/{job_id}/cancel")
        assert cancel_res.status_code == 200
        assert cancel_res.json()["ok"] is True

        # Ensure the process was killed
        try:
            dummy_proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            dummy_proc.kill()
            pytest.fail("Process was not terminated by cancel endpoint")

        assert dummy_proc.poll() is not None

        # Verify DB status is 'cancelled' and completed_at is set
        conn = sqlite3.connect(test_db)
        row = conn.execute("SELECT status, completed_at, pid FROM download_queue WHERE id=?", (job_id,)).fetchone()
        conn.close()
        assert row[0] == "cancelled"
        assert row[1] is not None
        assert row[2] == pid

    finally:
        if dummy_proc.poll() is None:
            dummy_proc.kill()

    # 2. Cancel a queued job without active PID
    conn = sqlite3.connect(test_db)
    cur = conn.execute(
        "INSERT INTO download_queue (url, platform, requested_by, status, quality, format, pid) "
        "VALUES (?,?,?,?,?,?,?)",
        ("https://example.com/mock_queued_job", "youtube", "admin", "queued", "opus", "opus", 0)
    )
    queued_job_id = cur.lastrowid
    conn.commit()
    conn.close()

    cancel_res2 = client.post(f"/api/music/queue/{queued_job_id}/cancel")
    assert cancel_res2.status_code == 200
    assert cancel_res2.json()["ok"] is True

    conn = sqlite3.connect(test_db)
    row2 = conn.execute("SELECT status, completed_at FROM download_queue WHERE id=?", (queued_job_id,)).fetchone()
    conn.close()
    assert row2[0] == "cancelled"
    assert row2[1] is not None

    # 3. Test cancel with non-existent PID (safe exception handling)
    conn = sqlite3.connect(test_db)
    cur = conn.execute(
        "INSERT INTO download_queue (url, platform, requested_by, status, quality, format, pid) "
        "VALUES (?,?,?,?,?,?,?)",
        ("https://example.com/mock_stale_pid_job", "youtube", "admin", "downloading", "mp3_320", "mp3_320", 9999999)
    )
    stale_job_id = cur.lastrowid
    conn.commit()
    conn.close()

    cancel_res3 = client.post(f"/api/music/queue/{stale_job_id}/cancel")
    assert cancel_res3.status_code == 200
    assert cancel_res3.json()["ok"] is True

    conn = sqlite3.connect(test_db)
    row3 = conn.execute("SELECT status, completed_at FROM download_queue WHERE id=?", (stale_job_id,)).fetchone()
    conn.close()
    assert row3[0] == "cancelled"
    assert row3[1] is not None

def test_download_ui_elements(test_env):
    """Verify Preact SPA bundle has all Hi-Res quality options and queue cancel/retry endpoints."""
    client, _ = test_env
    _, bundle = _fetch_spa_bundle(client)

    # Check format options
    assert "FLAC (Hi-Res Lossless)" in bundle
    assert "OPUS (High-Fidelity 160k+)" in bundle
    assert "M4A / AAC (256 kbps)" in bundle
    assert "MP3 (320 kbps Extreme)" in bundle
    assert "MP3 (256 kbps Standard)" in bundle
    assert "WAV (Uncompressed PCM)" in bundle

    # Check queue endpoints and cancel/retry actions
    assert "/api/music/queue" in bundle
    assert "/api/music/download" in bundle
    assert "Cancel" in bundle and "Retry" in bundle

def test_maloja_scrobble_sync_and_data(test_env):
    """Verify MALOJA_DB_PATH synchronization and fallback with mock Maloja sqlite database."""
    client, test_db = test_env
    orig_maloja_path = getattr(app_module, "MALOJA_DB_PATH", "/maloja/malojadb.sqlite")

    with tempfile.TemporaryDirectory() as tmpdir:
        mock_maloja = os.path.join(tmpdir, "malojadb.sqlite")
        m_conn = sqlite3.connect(mock_maloja)
        m_conn.execute("""
            CREATE TABLE artists (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL
            )
        """)
        m_conn.execute("""
            CREATE TABLE albums (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                artist_id INTEGER
            )
        """)
        m_conn.execute("""
            CREATE TABLE tracks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                artist_id INTEGER,
                album_id INTEGER
            )
        """)
        m_conn.execute("""
            CREATE TABLE scrobbles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp INTEGER NOT NULL,
                track_id INTEGER NOT NULL,
                user TEXT
            )
        """)
        # Seed mock data
        m_conn.execute("INSERT INTO artists (id, name) VALUES (1, 'Radiohead'), (2, 'Daft Punk')")
        m_conn.execute("INSERT INTO albums (id, name, artist_id) VALUES (1, 'OK Computer', 1), (2, 'Discovery', 2)")
        m_conn.execute("INSERT INTO tracks (id, title, artist_id, album_id) VALUES (1, 'Karma Police', 1, 1), (2, 'Paranoid Android', 1, 1), (3, 'One More Time', 2, 2)")
        # 4 scrobbles for alice: 2 for Karma Police, 1 for Paranoid Android, 1 for One More Time
        m_conn.execute("INSERT INTO scrobbles (timestamp, track_id, user) VALUES (1700000000, 1, 'alice')")
        m_conn.execute("INSERT INTO scrobbles (timestamp, track_id, user) VALUES (1700003600, 1, 'alice')")
        m_conn.execute("INSERT INTO scrobbles (timestamp, track_id, user) VALUES (1700007200, 2, 'alice')")
        m_conn.execute("INSERT INTO scrobbles (timestamp, track_id, user) VALUES (1700010800, 3, 'alice')")
        m_conn.commit()
        m_conn.close()

        app_module.MALOJA_DB_PATH = mock_maloja
        os.environ["MALOJA_DB_PATH"] = mock_maloja
        try:
            # 1. Sync scrobbles
            synced = app_module.sync_maloja_scrobbles("alice")
            assert synced == 4

            # 2. Query maloja data directly
            data = app_module.get_maloja_data("alice")
            assert data["total_scrobbles"] == 4
            assert data["unique_tracks"] == 3
            assert len(data["top_artists"]) >= 1
            assert data["top_artists"][0]["name"] == "Radiohead"
            assert data["top_artists"][0]["plays"] == 3
            assert data["top_tracks"][0]["title"] == "Karma Police"
            assert data["top_tracks"][0]["plays"] == 2
            assert "suggestions" in data or "playlist_suggestions" in data

            # 3. Test safe fallback when MALOJA_DB_PATH does not exist
            app_module.MALOJA_DB_PATH = os.path.join(tmpdir, "missing.sqlite")
            os.environ["MALOJA_DB_PATH"] = app_module.MALOJA_DB_PATH
            fallback_data = app_module.get_maloja_data("alice")
            assert isinstance(fallback_data, dict)
            assert "top_artists" in fallback_data
            assert "top_tracks" in fallback_data
        finally:
            app_module.MALOJA_DB_PATH = orig_maloja_path
            os.environ["MALOJA_DB_PATH"] = orig_maloja_path

def test_maloja_real_junction_schema(test_env):
    """Verify native Maloja schema with trackartists junction table and timestamp PK."""
    client, test_db = test_env
    orig_maloja_path = getattr(app_module, "MALOJA_DB_PATH", "/maloja/malojadb.sqlite")

    with tempfile.TemporaryDirectory() as tmpdir:
        real_maloja = os.path.join(tmpdir, "real_malojadb.sqlite")
        m_conn = sqlite3.connect(real_maloja)
        m_conn.execute("CREATE TABLE artists (id INTEGER PRIMARY KEY AUTOINCREMENT, name VARCHAR, name_normalized VARCHAR)")
        m_conn.execute("CREATE TABLE albums (id INTEGER PRIMARY KEY AUTOINCREMENT, albtitle VARCHAR, albtitle_normalized VARCHAR)")
        m_conn.execute("CREATE TABLE tracks (id INTEGER PRIMARY KEY AUTOINCREMENT, title VARCHAR, title_normalized VARCHAR, length INTEGER, album_id INTEGER)")
        m_conn.execute("CREATE TABLE trackartists (id INTEGER PRIMARY KEY, artist_id INTEGER, track_id INTEGER)")
        m_conn.execute("CREATE TABLE scrobbles (timestamp INTEGER NOT NULL PRIMARY KEY, rawscrobble VARCHAR, origin VARCHAR, duration INTEGER, track_id INTEGER, extra VARCHAR)")

        m_conn.execute("INSERT INTO artists (id, name) VALUES (1, 'YRF'), (2, 'Arijit Singh')")
        m_conn.execute("INSERT INTO albums (id, albtitle) VALUES (1, 'Ek Tha Tiger')")
        m_conn.execute("INSERT INTO tracks (id, title, album_id) VALUES (1, 'Saiyaara Full Song', 1)")
        m_conn.execute("INSERT INTO trackartists (id, artist_id, track_id) VALUES (1, 1, 1), (2, 2, 1)")
        m_conn.execute("INSERT INTO scrobbles (timestamp, track_id, origin) VALUES (1776904011, 1, 'navidrome')")
        m_conn.commit()
        m_conn.close()

        app_module.MALOJA_DB_PATH = real_maloja
        os.environ["MALOJA_DB_PATH"] = real_maloja
        try:
            synced = app_module.sync_maloja_scrobbles("admin")
            assert synced == 1

            data = app_module.get_maloja_data("admin")
            assert data["total_scrobbles"] == 1
            assert data["unique_tracks"] == 1
            assert len(data["top_artists"]) >= 1
            assert data["top_tracks"][0]["title"] == "Saiyaara Full Song"
            assert "YRF" in data["top_tracks"][0]["artist"]
            assert len(data["recent_plays"]) == 1
        finally:
            app_module.MALOJA_DB_PATH = orig_maloja_path
            os.environ["MALOJA_DB_PATH"] = orig_maloja_path

def test_music_recommendations_and_stats_api_contracts(test_env):
    """Verify /api/music/recommendations/{username} and /api/music/stats return required contracts."""
    client, _ = test_env
    orig_maloja_path = getattr(app_module, "MALOJA_DB_PATH", "/maloja/malojadb.sqlite")

    with tempfile.TemporaryDirectory() as tmpdir:
        mock_maloja = os.path.join(tmpdir, "malojadb.sqlite")
        m_conn = sqlite3.connect(mock_maloja)
        m_conn.execute("CREATE TABLE artists (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL)")
        m_conn.execute("CREATE TABLE albums (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, artist_id INTEGER)")
        m_conn.execute("CREATE TABLE tracks (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, artist_id INTEGER, album_id INTEGER)")
        m_conn.execute("CREATE TABLE scrobbles (id INTEGER PRIMARY KEY AUTOINCREMENT, time INTEGER NOT NULL, track_id INTEGER NOT NULL, user TEXT)")
        m_conn.execute("INSERT INTO artists (id, name) VALUES (1, 'Pink Floyd')")
        m_conn.execute("INSERT INTO albums (id, name, artist_id) VALUES (1, 'The Dark Side of the Moon', 1)")
        m_conn.execute("INSERT INTO tracks (id, title, artist_id, album_id) VALUES (1, 'Time', 1, 1)")
        m_conn.execute("INSERT INTO scrobbles (time, track_id, user) VALUES (1700000000, 1, 'admin')")
        m_conn.commit()
        m_conn.close()

        app_module.MALOJA_DB_PATH = mock_maloja
        os.environ["MALOJA_DB_PATH"] = mock_maloja
        try:
            # Login
            client.post("/login", data={"username": "admin", "password": "newsecret123"})

            # Test recommendations endpoint
            rec_res = client.get("/api/music/recommendations/admin")
            assert rec_res.status_code == 200
            rec_json = rec_res.json()
            assert "top_artists" in rec_json
            assert "top_genres" in rec_json
            assert "top_tracks" in rec_json
            assert "listening_clock" in rec_json or "time_patterns" in rec_json or "time_pattern" in rec_json
            assert "suggestions" in rec_json or "playlist_suggestions" in rec_json

            assert len(rec_json["top_artists"]) >= 1
            top_a = rec_json["top_artists"][0]
            assert "name" in top_a or "artist" in top_a
            assert "plays" in top_a
            assert "completions" in top_a
            assert (top_a.get("name") or top_a.get("artist")) == "Pink Floyd"

            top_t = rec_json["top_tracks"][0]
            assert "title" in top_t or "track_title" in top_t
            assert "artist" in top_t
            assert "plays" in top_t
            assert (top_t.get("title") or top_t.get("track_title")) == "Time"

            # Test music stats endpoint
            stats_res = client.get("/api/music/stats")
            assert stats_res.status_code == 200
            stats_json = stats_res.json()
            assert "total_scrobbles" in stats_json or "total_plays" in stats_json
            assert "unique_tracks" in stats_json
            assert "top_artist" in stats_json
            assert "recent_plays" in stats_json
            assert stats_json["top_artist"] == "Pink Floyd" or stats_json.get("top_artist", {}).get("name") == "Pink Floyd"
        finally:
            app_module.MALOJA_DB_PATH = orig_maloja_path
            os.environ["MALOJA_DB_PATH"] = orig_maloja_path

def test_recommendations_ui_dropdown_and_onboarding(test_env):
    """Verify Preact SPA recommendations view fetches users, recommendations, and renders onboarding."""
    client, _ = test_env
    _, bundle = _fetch_spa_bundle(client)

    assert "/api/music/recommendations/" in bundle
    assert "/api/music/stats" in bundle
    assert "Listening History Onboarding" in bundle
    assert "Connect Navidrome or your Subsonic client to Maloja" in bundle


def test_activity_logs_api_filtering(test_env):
    """Verify /api/logs supports q, category, severity filtering, pagination, and sorting."""
    client, _ = test_env
    # Ensure client is authenticated (try both initial and changed password)
    r = client.post("/login", data={"username": "admin", "password": "newsecret123"})
    if r.status_code != 303:
        client.post("/login", data={"username": "admin", "password": "admin123"})

    db = app_module.get_db()
    db.execute("DELETE FROM activity_log")
    db.commit()
    db.close()
    
    entries = [
        ("admin", "Container started", "containers", "nginx", "Started successfully", "ok", "info"),
        ("system", "Container exited unexpectedly", "containers", "mariadb", "Exit code 137 OOMKilled", "error", "error"),
        ("system", "High memory threshold", "system", "RAM", "RAM usage reached 94%", "warning", "warning"),
        ("admin", "Admin login successful", "auth", "admin", "Session created", "ok", "info"),
        ("system", "Disk threshold warning", "storage", "/mnt/backup", "Disk usage at 91%", "warning", "warning"),
        ("system", "Firewall banned IP", "security", "192.168.1.105", "Brute force attempts", "ok", "info"),
        ("admin", "Music scan completed", "music", "navidrome", "Added 42 tracks", "ok", "info"),
        ("system", "High packet drop on eth0", "network", "eth0", "Packet drop > 5%", "warning", "warning"),
    ]
    for actor, action, cat, target, detail, status, sev in entries:
        app_module.log_action(actor=actor, action=action, category=cat, target=target, detail=detail, status=status, severity=sev)

    # 1. Category: all
    res_all = client.get("/api/logs?category=all")
    assert res_all.status_code == 200
    data_all = res_all.json()
    assert len(data_all) == 8

    # 2. Specific category
    res_cont = client.get("/api/logs?category=containers")
    assert res_cont.status_code == 200
    data_cont = res_cont.json()
    assert len(data_cont) == 2
    for r in data_cont:
        assert r["category"] == "containers"

    res_sys = client.get("/api/logs?category=system")
    assert res_sys.status_code == 200
    assert len(res_sys.json()) == 1
    assert res_sys.json()[0]["category"] == "system"

    # 3. Severity filter
    res_err = client.get("/api/logs?severity=error")
    assert res_err.status_code == 200
    data_err = res_err.json()
    assert len(data_err) == 1
    assert data_err[0]["severity"] == "error"
    assert "mariadb" in data_err[0]["target"]

    res_warn = client.get("/api/logs?severity=warning")
    assert res_warn.status_code == 200
    assert len(res_warn.json()) == 3
    for r in res_warn.json():
        assert r["severity"] == "warning"

    # 4. Search query q
    res_q = client.get("/api/logs?q=OOMKilled")
    assert res_q.status_code == 200
    data_q = res_q.json()
    assert len(data_q) == 1
    assert "OOMKilled" in data_q[0]["detail"]

    # 5. Pagination: limit & offset
    res_p1 = client.get("/api/logs?limit=3&offset=0")
    assert res_p1.status_code == 200
    data_p1 = res_p1.json()
    assert len(data_p1) == 3

    res_p2 = client.get("/api/logs?limit=3&offset=3")
    assert res_p2.status_code == 200
    data_p2 = res_p2.json()
    assert len(data_p2) == 3
    # Check no overlap between page 1 and page 2
    p1_ids = {r["id"] for r in data_p1}
    p2_ids = {r["id"] for r in data_p2}
    assert p1_ids.isdisjoint(p2_ids)

    # 6. Sorting descending
    all_ids = [r["id"] for r in data_all]
    assert all_ids == sorted(all_ids, reverse=True)


def test_activity_logs_stats_schema_and_aggregation(test_env):
    """Verify /api/logs/stats returns total, by_category dict, by_severity dict, and recent_errors count."""
    client, _ = test_env
    res = client.get("/api/logs/stats")
    assert res.status_code == 200
    stats = res.json()

    assert "total" in stats and isinstance(stats["total"], int)
    assert "by_category" in stats and isinstance(stats["by_category"], dict)
    assert "by_severity" in stats and isinstance(stats["by_severity"], dict)
    assert "recent_errors" in stats and isinstance(stats["recent_errors"], int)

    # Check aggregations against seeded test data
    assert stats["total"] >= 8
    assert stats["by_category"].get("containers", 0) >= 2
    assert stats["by_category"].get("system", 0) >= 1
    assert stats["by_severity"].get("error", 0) >= 1
    assert stats["by_severity"].get("warning", 0) >= 3
    assert stats["recent_errors"] >= 1


def test_system_log_harvester_and_deduplication(test_env):
    """Verify background log harvester detects resource alerts and container errors with deduplication."""
    from unittest.mock import MagicMock, patch
    from collections import namedtuple

    # Clear harvester dedup cache if present
    if hasattr(app_module, "_harvester_dedup_cache"):
        app_module._harvester_dedup_cache.clear()

    # 1. Test Resource Alerts: RAM > 90% and Disk > 90%
    MemMock = namedtuple("MemMock", ["percent"])
    DiskMock = namedtuple("DiskMock", ["percent"])

    with patch("psutil.virtual_memory", return_value=MemMock(percent=95.5)), \
         patch("psutil.disk_usage", return_value=DiskMock(percent=93.2)):
        # Call harvest function directly
        assert hasattr(app_module, "harvest_system_and_container_logs")
        app_module.harvest_system_and_container_logs()

        # Check activity_log contains system category warnings
        db = app_module.get_db()
        sys_logs = db.execute("SELECT * FROM activity_log WHERE category='system' AND severity='warning'").fetchall()
        db.close()
        assert len(sys_logs) >= 2  # RAM alert and Disk alert

        # 2. Test Deduplication: Calling harvest again immediately with same state must NOT add duplicate events
        app_module.harvest_system_and_container_logs()
        db = app_module.get_db()
        sys_logs_after = db.execute("SELECT * FROM activity_log WHERE category='system' AND severity='warning'").fetchall()
        db.close()
        assert len(sys_logs_after) == len(sys_logs)

    # 3. Test Container lifecycle event logging and deduplication
    mock_container = MagicMock()
    mock_container.name = "nextcloud"
    mock_container.status = "exited"
    mock_container.attrs = {"State": {"Health": {"Status": "unhealthy"}, "ExitCode": 1}}
    mock_container.logs.return_value = b"FATAL: Database connection failed\nTraceback (most recent call last):\nException: DB error"

    mock_docker = MagicMock()
    mock_docker.containers.list.return_value = [mock_container]

    orig_docker = app_module.docker_client
    app_module.docker_client = mock_docker
    try:
        app_module.harvest_system_and_container_logs()

        db = app_module.get_db()
        c_logs = db.execute("SELECT * FROM activity_log WHERE category='containers' AND target='nextcloud'").fetchall()
        db.close()
        assert len(c_logs) >= 1

        # Second run deduplicates
        prev_count = len(c_logs)
        app_module.harvest_system_and_container_logs()
        db = app_module.get_db()
        c_logs_2 = db.execute("SELECT * FROM activity_log WHERE category='containers' AND target='nextcloud'").fetchall()
        db.close()
        assert len(c_logs_2) == prev_count
    finally:
        app_module.docker_client = orig_docker


def test_activity_logs_ui_elements(test_env):
    """Verify Preact SPA bundle contains category filter pills, auto-refresh toggle, and log endpoints."""
    client, _ = test_env
    _, bundle = _fetch_spa_bundle(client)

    expected_cats = ["containers", "system", "auth", "storage", "network", "music", "security"]
    for cat in expected_cats:
        assert cat in bundle, f"Category filter '{cat}' missing from SPA bundle"

    assert "Auto-refresh (15s)" in bundle
    assert "/api/logs/stats" in bundle
    assert "/api/logs?q=" in bundle


def test_quick_ban_api_contracts(test_env):
    """Verify quick ban API endpoints (/api/bans/add & /api/bans), durations, validation, and unban."""
    client, _ = test_env

    # Ensure admin is logged in (password was updated to newsecret123 in test_change_password_workflow)
    login_res = client.post("/login", data={"username": "admin", "password": "newsecret123"})
    assert login_res.status_code == 303

    # 1. Valid IP with 24 hours duration
    ban_res = client.post("/api/bans/add", json={
        "ip": "192.168.1.150",
        "duration_hours": 24,
        "reason": "SSH brute force attempt"
    })
    assert ban_res.status_code == 200
    ban_data = ban_res.json()
    assert ban_data["ok"] is True
    assert ban_data["ip"] == "192.168.1.150"
    assert ban_data["reason"] == "SSH brute force attempt"
    assert ban_data["expires_at"] is not None
    assert app_module.is_ip_banned("192.168.1.150") is True

    # Verify activity log recorded security warning
    db = app_module.get_db()
    log = db.execute(
        "SELECT * FROM activity_log WHERE category='security' AND target='192.168.1.150' ORDER BY timestamp DESC"
    ).fetchone()
    db.close()
    assert log is not None
    assert log["severity"] == "warning"

    # Also test POST /api/bans alias endpoint
    ban_res_alias = client.post("/api/bans", json={
        "ip": "10.0.0.75",
        "duration_hours": 1
    })
    assert ban_res_alias.status_code == 200
    assert ban_res_alias.json()["ok"] is True
    assert app_module.is_ip_banned("10.0.0.75") is True

    # 2. Valid IP with permanent duration (0 or None)
    ban_perm_res = client.post("/api/bans/add", json={
        "ip": "192.168.1.151",
        "duration_hours": 0,
        "reason": "Permanent ban on malicious scanner"
    })
    assert ban_perm_res.status_code == 200
    perm_data = ban_perm_res.json()
    assert perm_data["ok"] is True
    assert perm_data["ip"] == "192.168.1.151"
    assert perm_data["expires_at"] is None
    assert app_module.is_ip_banned("192.168.1.151") is True

    # Test with duration_hours=None
    ban_none_res = client.post("/api/bans/add", json={
        "ip": "192.168.1.152",
        "duration_hours": None
    })
    assert ban_none_res.status_code == 200
    assert ban_none_res.json()["expires_at"] is None
    assert app_module.is_ip_banned("192.168.1.152") is True

    # 3. Invalid IP format returns 400
    invalid_ips = ["not-an-ip", "999.999.999.999", "123.456.78.90", "abc", ""]
    for inv in invalid_ips:
        err_res = client.post("/api/bans/add", json={"ip": inv, "duration_hours": 24})
        assert err_res.status_code == 400
        assert err_res.json() == {"error": "Invalid IP address format"}

    # 4. Unban removes the ban
    # Get ban list to find ID for 192.168.1.150
    bans_list = client.get("/api/bans").json()
    b150 = next(b for b in bans_list if b["ip"] == "192.168.1.150")
    unban_res = client.post(f"/api/bans/{b150['id']}/unban")
    assert unban_res.status_code == 200
    assert unban_res.json()["ok"] is True
    assert app_module.is_ip_banned("192.168.1.150") is False

    # Test POST /api/bans/unban by IP
    unban_ip_res = client.post("/api/bans/unban", json={"ip": "192.168.1.151"})
    assert unban_ip_res.status_code == 200
    assert app_module.is_ip_banned("192.168.1.151") is False

    # 5. Expired ban returns False in is_ip_banned
    from datetime import datetime, timedelta
    expired_time = (datetime.utcnow() - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")
    db = app_module.get_db()
    db.execute(
        "INSERT OR REPLACE INTO ip_bans (ip, reason, banned_at, expires_at) VALUES (?, ?, datetime('now'), ?)",
        ("192.168.1.199", "Expired test ban", expired_time)
    )
    db.commit()
    db.close()
    assert app_module.is_ip_banned("192.168.1.199") is False


def test_security_ui_elements(test_env):
    """Verify Preact SPA bundle contains Quick-block form, duration options, login attempts, and 1-click ban."""
    client, _ = test_env
    _, bundle = _fetch_spa_bundle(client)

    assert "Quick Block IP" in bundle
    assert "Manual Admin Ban" in bundle
    assert "Block IP Address" in bundle
    assert "1 Hour" in bundle and "24 Hours" in bundle and "7 Days" in bundle and "Permanent" in bundle
    assert "/api/bans/add" in bundle
    assert "/api/login-attempts" in bundle
    assert "Failed login attempt" in bundle
    assert "Banned" in bundle


def test_network_live_dynamic_interfaces_and_rates(test_env):
    """Verify /api/network/live contract, dynamic interface resolution, and rate calculations."""
    client, _ = test_env
    # 1. Test helper format_bytes
    assert app_module.format_bytes(500) == "500 B"
    assert app_module.format_bytes(1024 * 450.5, is_rate=True) == "450.5 KB/s"
    assert app_module.format_bytes(1024 * 1024 * 1.2, is_rate=True) == "1.2 MB/s"
    assert app_module.format_bytes(1024 * 1024 * 1024 * 12.4) == "12.4 GB"

    # 2. Dynamic interface validation (ZERO hardcoding)
    assert app_module.is_valid_interface("lo") is False
    assert app_module.is_valid_interface("docker0") is False
    assert app_module.is_valid_interface("docker1") is False
    assert app_module.is_valid_interface("br-4a5f6e") is False
    assert app_module.is_valid_interface("veth1234a") is False
    assert app_module.is_valid_interface("eth0") is True
    assert app_module.is_valid_interface("enp3s0") is True
    assert app_module.is_valid_interface("wlan0") is True
    assert app_module.is_valid_interface("tailscale0") is True

    # 3. Dynamic candidate path resolution
    with tempfile.TemporaryDirectory() as tmp_proc:
        orig_proc = app_module.PROC_PATH
        try:
            # Candidate path 2: os.path.join(PROC_PATH, "net", "dev")
            net_dir = os.path.join(tmp_proc, "net")
            os.makedirs(net_dir, exist_ok=True)
            dev_file = os.path.join(net_dir, "dev")
            with open(dev_file, "w") as f:
                f.write("Inter-|   Receive                                                |  Transmit\n")
                f.write(" face |bytes    packets errs drop fifo frame compressed multicast|bytes    packets errs drop fifo colls carrier compressed\n")
                f.write("    lo: 50000       0    0    0    0     0          0         0    50000       0    0    0    0     0       0          0\n")
                f.write("docker0: 60000       0    0    0    0     0          0         0    60000       0    0    0    0     0       0          0\n")
                f.write("  br-123: 70000       0    0    0    0     0          0         0    70000       0    0    0    0     0       0          0\n")
                f.write(" vethabc: 80000       0    0    0    0     0          0         0    80000       0    0    0    0     0       0          0\n")
                f.write("  eth0: 10000000     100    0    0    0     0          0         0  5000000      50    0    0    0     0       0          0\n")
                f.write("tailscale0: 20000000 200    0    0    0     0          0         0  8000000      80    0    0    0     0       0          0\n")

            app_module.PROC_PATH = tmp_proc
            assert app_module.get_net_dev_path() == dev_file

            # Reset collector state and collect first snapshot
            app_module._net_prev.clear()
            app_module._collect_net()

            # Second collection with simulated byte increment
            with open(dev_file, "w") as f:
                f.write("Inter-|   Receive                                                |  Transmit\n")
                f.write(" face |bytes    packets errs drop fifo frame compressed multicast|bytes    packets errs drop fifo colls carrier compressed\n")
                f.write("    lo: 60000       0    0    0    0     0          0         0    60000       0    0    0    0     0       0          0\n")
                f.write("  eth0: 12500000     120    0    0    0     0          0         0  6200000      60    0    0    0     0       0          0\n")
                f.write("tailscale0: 21000000 210    0    0    0     0          0         0  8500000      85    0    0    0     0       0          0\n")

            # Simulate small time delay in _net_prev
            for iface in app_module._net_prev:
                rx, tx, ts = app_module._net_prev[iface]
                app_module._net_prev[iface] = (rx, tx, ts - 1.0)

            app_module._collect_net()
        finally:
            app_module.PROC_PATH = orig_proc

    # 4. Verify /api/network/live response contracts
    res = client.get("/api/network/live")
    assert res.status_code == 200
    data = res.json()
    assert "interfaces" in data
    assert "containers" in data
    assert "timestamp" in data

    ifaces = {i["iface"]: i for i in data["interfaces"]}
    # Excluded interfaces
    assert "lo" not in ifaces
    assert "docker0" not in ifaces
    assert "br-123" not in ifaces
    assert "vethabc" not in ifaces

    # Included interfaces
    assert "eth0" in ifaces
    assert "tailscale0" in ifaces

    # Required fields per interface
    for k in ["eth0", "tailscale0"]:
        item = ifaces[k]
        for field in ["iface", "bytes_in_rate", "bytes_out_rate", "rate_in_human", "rate_out_human", "bytes_in", "bytes_out"]:
            assert field in item, f"Missing field {field} in interface {k}"
        assert item["rate_in_human"].endswith("/s")
        assert item["rate_out_human"].endswith("/s")


def test_network_history_periods_and_net_daily(test_env):
    """Verify /api/network/history querying net_daily for 30d, 1y, all."""
    client, _ = test_env
    db = app_module.get_db()
    # Clean previous test entries
    db.execute("DELETE FROM net_daily")
    db.execute("DELETE FROM net_snapshots")
    db.execute("DELETE FROM net_hourly")

    from datetime import datetime, timedelta
    today = datetime.utcnow().strftime("%Y-%m-%d")
    d10 = (datetime.utcnow() - timedelta(days=10)).strftime("%Y-%m-%d")
    d45 = (datetime.utcnow() - timedelta(days=45)).strftime("%Y-%m-%d")
    d200 = (datetime.utcnow() - timedelta(days=200)).strftime("%Y-%m-%d")
    d400 = (datetime.utcnow() - timedelta(days=400)).strftime("%Y-%m-%d")

    records = [
        (today, "eth0", 104857600, 52428800),
        (d10, "eth0", 209715200, 104857600),
        (d45, "eth0", 314572800, 157286400),
        (d200, "eth0", 419430400, 209715200),
        (d400, "eth0", 524288000, 262144000),
    ]
    for r in records:
        db.execute("INSERT INTO net_daily (day, iface, bytes_in, bytes_out) VALUES (?, ?, ?, ?)", r)
    db.commit()
    db.close()

    # 1. 30d period queries net_daily within 30 days (today and d10)
    res_30d = client.get("/api/network/history?period=30d&iface=eth0")
    assert res_30d.status_code == 200
    rows_30d = res_30d.json()["rows"]
    days_30d = [r["ts"] for r in rows_30d]
    assert today in days_30d
    assert d10 in days_30d
    assert d45 not in days_30d
    assert d400 not in days_30d

    # 2. 1y period queries net_daily within 365 days (today, d10, d45, d200)
    res_1y = client.get("/api/network/history?period=1y&iface=eth0")
    assert res_1y.status_code == 200
    rows_1y = res_1y.json()["rows"]
    days_1y = [r["ts"] for r in rows_1y]
    assert today in days_1y
    assert d200 in days_1y
    assert d400 not in days_1y

    # 3. 'all' period queries net_daily including multi-year data (>365 days ago)
    res_all = client.get("/api/network/history?period=all&iface=eth0")
    assert res_all.status_code == 200
    rows_all = res_all.json()["rows"]
    days_all = [r["ts"] for r in rows_all]
    assert today in days_all
    assert d400 in days_all, "Multi-year historical record (>1 year) must be returned for 'all' period"
    for r in rows_all:
        for k in ["ts", "day", "iface", "in_rate", "out_rate", "total_in", "total_out"]:
            assert k in r


def test_network_summary_rollups_multi_year(test_env):
    """Verify /api/network/summary returns rollups for today, this_week, this_month, this_year, all_time."""
    client, _ = test_env
    db = app_module.get_db()
    db.execute("DELETE FROM net_daily")

    from datetime import datetime, timedelta
    today = datetime.utcnow().strftime("%Y-%m-%d")
    d3 = (datetime.utcnow() - timedelta(days=3)).strftime("%Y-%m-%d")
    d15 = (datetime.utcnow() - timedelta(days=15)).strftime("%Y-%m-%d")
    d100 = (datetime.utcnow() - timedelta(days=100)).strftime("%Y-%m-%d")
    d500 = (datetime.utcnow() - timedelta(days=500)).strftime("%Y-%m-%d")

    records = [
        (today, "eth0", 1000, 2000),
        (d3, "eth0", 3000, 4000),
        (d15, "eth0", 5000, 6000),
        (d100, "eth0", 7000, 8000),
        (d500, "eth0", 9000, 10000),
    ]
    for r in records:
        db.execute("INSERT INTO net_daily (day, iface, bytes_in, bytes_out) VALUES (?, ?, ?, ?)", r)
    db.commit()
    db.close()

    res = client.get("/api/network/summary")
    assert res.status_code == 200
    data = res.json()

    for period in ["today", "this_week", "this_month", "this_year", "all_time"]:
        assert period in data, f"Missing required rollup key '{period}' in summary response"
        assert isinstance(data[period], list)
        if data[period]:
            item = data[period][0]
            for f in ["iface", "bytes_in", "bytes_out", "tin", "tout", "human_in", "human_out", "total_human"]:
                assert f in item, f"Missing field '{f}' in summary period '{period}'"

    # Check cumulative totals
    # today: 1000 in, 2000 out
    assert data["today"][0]["bytes_in"] == 1000
    assert data["today"][0]["bytes_out"] == 2000

    # this_week includes today and d3: 1000 + 3000 = 4000
    assert data["this_week"][0]["bytes_in"] == 4000
    assert data["this_week"][0]["bytes_out"] == 6000

    # this_month includes today, d3, d15: 1000 + 3000 + 5000 = 9000
    assert data["this_month"][0]["bytes_in"] == 9000
    assert data["this_month"][0]["bytes_out"] == 12000

    # this_year includes today, d3, d15, d100: 9000 + 7000 = 16000
    assert data["this_year"][0]["bytes_in"] == 16000
    assert data["this_year"][0]["bytes_out"] == 20000

    # all_time includes all 5 records: 16000 + 9000 = 25000
    assert data["all_time"][0]["bytes_in"] == 25000
    assert data["all_time"][0]["bytes_out"] == 30000


def test_network_ui_elements(test_env):
    """Verify Preact SPA bundle has network speed tiles, rollup cards, period options, and API calls."""
    client, _ = test_env
    _, bundle = _fetch_spa_bundle(client)

    assert "Download" in bundle and "Upload" in bundle
    assert "7 Days" in bundle
    assert "30 Days" in bundle
    assert "This Year" in bundle
    assert "All-Time" in bundle
    assert "Last 7 days" in bundle
    assert "Last 30 days" in bundle
    assert "Last 1 year" in bundle
    assert "/api/network/live" in bundle
    assert "/api/network/summary" in bundle
    assert "/api/network/history?period=" in bundle


# ── Phase 7: Dynamic Cloudflare Zero Trust Defense-in-Depth Tests ───────────────
def test_zero_trust_middleware_disabled(test_env):
    """Verify Zero Trust middleware allows requests when disabled."""
    client, _ = test_env
    db = app_module.get_db()
    db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('cloudflare_zero_trust_enabled', 'false')")
    db.commit()
    db.close()

    # Normal request
    res = client.get("/login")
    assert res.status_code == 200

    # Request with CF headers while disabled still passes
    res_cf = client.get("/login", headers={"CF-Connecting-IP": "203.0.113.50"})
    assert res_cf.status_code == 200

    # Request from external IP while disabled still passes
    res_ext = client.get("/login", headers={"X-Forwarded-For": "203.0.113.50"})
    assert res_ext.status_code == 200


def test_zero_trust_middleware_cf_authorized(test_env):
    """Verify authorized Cloudflare Zero Trust email identity is admitted (200)."""
    client, _ = test_env
    db = app_module.get_db()
    db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('cloudflare_zero_trust_enabled', 'true')")
    db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('allowed_zero_trust_emails', 'authorized@example.com, admin@homelab.local')")
    db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('zero_trust_bypass_local', 'true')")
    db.commit()
    db.close()

    try:
        # Exact match email
        headers = {
            "CF-Connecting-IP": "198.51.100.10",
            "Cf-Ray": "ray-12345abc",
            "Cf-Access-Authenticated-User-Email": "authorized@example.com"
        }
        res = client.get("/login", headers=headers)
        assert res.status_code == 200

        # Case-insensitive email normalization
        headers_case = {
            "CF-Connecting-IP": "198.51.100.10",
            "Cf-Access-Authenticated-User-Email": "Authorized@Example.COM"
        }
        res_case = client.get("/login", headers=headers_case)
        assert res_case.status_code == 200

        # Secondary allowed email
        headers_admin = {
            "Cf-Ray": "ray-67890xyz",
            "Cf-Access-Authenticated-User-Email": "admin@homelab.local"
        }
        res_admin = client.get("/login", headers=headers_admin)
        assert res_admin.status_code == 200
    finally:
        db = app_module.get_db()
        db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('cloudflare_zero_trust_enabled', 'false')")
        db.commit()
        db.close()


def test_zero_trust_middleware_cf_unauthorized(test_env):
    """Verify unauthorized email arriving through Cloudflare tunnel is blocked with 403."""
    client, _ = test_env
    db = app_module.get_db()
    db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('cloudflare_zero_trust_enabled', 'true')")
    db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('allowed_zero_trust_emails', 'authorized@example.com')")
    db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('zero_trust_bypass_local', 'true')")
    db.commit()
    db.close()

    try:
        headers = {
            "CF-Connecting-IP": "198.51.100.50",
            "Cf-Ray": "ray-bad-user",
            "Cf-Access-Authenticated-User-Email": "intruder@malicious.com"
        }
        res = client.get("/login", headers=headers)
        assert res.status_code == 403
        data = res.json()
        assert data["detail"] == "Forbidden: Cloudflare Zero Trust authorization failed"

        # Verify security warning logged to activity_log
        db = app_module.get_db()
        log_entry = db.execute(
            "SELECT actor, action, category, detail, status, severity FROM activity_log "
            "WHERE action='Zero Trust Blocked' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        db.close()
        assert log_entry is not None
        assert log_entry["actor"] == "intruder@malicious.com"
        assert log_entry["category"] == "security"
        assert "intruder@malicious.com" in log_entry["detail"]
        assert log_entry["status"] == "blocked"
    finally:
        db = app_module.get_db()
        db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('cloudflare_zero_trust_enabled', 'false')")
        db.commit()
        db.close()


def test_zero_trust_middleware_cf_missing_email(test_env):
    """Verify Cloudflare traffic without authenticated email header is blocked with 403."""
    client, _ = test_env
    db = app_module.get_db()
    db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('cloudflare_zero_trust_enabled', 'true')")
    db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('allowed_zero_trust_emails', 'authorized@example.com')")
    db.commit()
    db.close()

    try:
        # CF headers present (CF-Connecting-IP) but no email header
        res = client.get("/login", headers={"CF-Connecting-IP": "198.51.100.99"})
        assert res.status_code == 403
        assert res.json()["detail"] == "Forbidden: Cloudflare Zero Trust authorization failed"

        # Cf-Ray present with whitespace/empty email
        res_empty = client.get("/login", headers={"Cf-Ray": "ray-empty", "Cf-Access-Authenticated-User-Email": "   "})
        assert res_empty.status_code == 403
        assert res_empty.json()["detail"] == "Forbidden: Cloudflare Zero Trust authorization failed"
    finally:
        db = app_module.get_db()
        db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('cloudflare_zero_trust_enabled', 'false')")
        db.commit()
        db.close()


def test_zero_trust_middleware_local_and_tailscale_bypass(test_env):
    """Verify private LAN and Tailscale mesh IPs bypass Zero Trust to standard session auth."""
    client, _ = test_env
    db = app_module.get_db()
    db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('cloudflare_zero_trust_enabled', 'true')")
    db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('allowed_zero_trust_emails', 'authorized@example.com')")
    db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('zero_trust_bypass_local', 'true')")
    db.commit()
    db.close()

    try:
        # Loopback IPv4
        res_loopback = client.get("/login", headers={"X-Forwarded-For": "127.0.0.1"})
        assert res_loopback.status_code == 200

        # Loopback IPv6
        res_loopback_v6 = client.get("/login", headers={"X-Forwarded-For": "::1"})
        assert res_loopback_v6.status_code == 200

        # Private Class C (192.168.0.0/16)
        res_lan = client.get("/login", headers={"X-Forwarded-For": "192.168.1.100"})
        assert res_lan.status_code == 200

        # Private Class A (10.0.0.0/8)
        res_lan_10 = client.get("/login", headers={"X-Forwarded-For": "10.0.5.20"})
        assert res_lan_10.status_code == 200

        # Tailscale CGNAT Range (100.64.0.0/10)
        res_tailscale = client.get("/login", headers={"X-Forwarded-For": "100.64.0.42"})
        assert res_tailscale.status_code == 200

        # External Public IP without CF headers -> 403 Forbidden
        res_public = client.get("/login", headers={"X-Forwarded-For": "203.0.113.88"})
        assert res_public.status_code == 403
        assert res_public.json()["detail"] == "Forbidden: Direct public access not allowed"

        res_public2 = client.get("/login", headers={"X-Forwarded-For": "8.8.8.8"})
        assert res_public2.status_code == 403
        assert res_public2.json()["detail"] == "Forbidden: Direct public access not allowed"
    finally:
        db = app_module.get_db()
        db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('cloudflare_zero_trust_enabled', 'false')")
        db.commit()
        db.close()


def test_zero_trust_settings_api(test_env):
    """Verify GET and POST /api/settings/zero-trust contracts, validation, and database persistence."""
    client, _ = test_env
    # Authenticate admin session
    client.post("/login", data={"username": "admin", "password": "newsecret123"})
    # Fallback to initial password if not upgraded
    client.post("/login", data={"username": "admin", "password": "admin123"})

    # 1. GET initial settings
    res = client.get("/api/settings/zero-trust")
    assert res.status_code == 200
    cfg = res.json()
    assert "enabled" in cfg
    assert isinstance(cfg["allowed_emails"], list)
    assert "bypass_local" in cfg

    # 2. POST update settings with comma-separated string
    payload = {
        "enabled": True,
        "allowed_emails": "secops@example.com, audit@example.com, SecOps@example.com",
        "bypass_local": True
    }
    res_post = client.post("/api/settings/zero-trust", json=payload)
    assert res_post.status_code == 200
    data = res_post.json()
    assert data["ok"] is True
    assert data["enabled"] is True
    # Verify deduplication and lowercasing
    assert data["allowed_emails"] == ["secops@example.com", "audit@example.com"]
    assert data["bypass_local"] is True

    # Verify database persistence
    db = app_module.get_db()
    rows = dict(db.execute("SELECT key, value FROM settings").fetchall())
    db.close()
    assert rows.get("cloudflare_zero_trust_enabled") == "true"
    assert rows.get("allowed_zero_trust_emails") == "secops@example.com,audit@example.com"
    assert rows.get("zero_trust_bypass_local") == "true"

    # 3. GET verifies updated settings
    res_get2 = client.get("/api/settings/zero-trust")
    assert res_get2.status_code == 200
    cfg2 = res_get2.json()
    assert cfg2["enabled"] is True
    assert cfg2["allowed_emails"] == ["secops@example.com", "audit@example.com"]

    # 4. POST update settings with list of emails
    payload_list = {
        "enabled": False,
        "allowed_emails": ["ops@sub.domain.org", "dev@homelab.local"],
        "bypass_local": False
    }
    res_post2 = client.post("/api/settings/zero-trust", json=payload_list)
    assert res_post2.status_code == 200
    assert res_post2.json()["enabled"] is False
    assert res_post2.json()["allowed_emails"] == ["ops@sub.domain.org", "dev@homelab.local"]
    assert res_post2.json()["bypass_local"] is False

    # 5. POST validation rejects invalid email formats
    bad_payload = {
        "enabled": True,
        "allowed_emails": "valid@example.com, not_a_valid_email"
    }
    res_bad = client.post("/api/settings/zero-trust", json=bad_payload)
    assert res_bad.status_code == 400
    assert "Invalid email format" in res_bad.json()["error"]

    # Cleanup settings
    db = app_module.get_db()
    db.execute("DELETE FROM settings")
    db.commit()
    db.close()


def test_zero_trust_ui_elements(test_env):
    """Verify Preact SPA bundle contains Zero Trust settings card, form elements, and API hooks."""
    client, _ = test_env
    # Authenticate session
    client.post("/login", data={"username": "admin", "password": "newsecret123"})
    client.post("/login", data={"username": "admin", "password": "admin123"})

    _, bundle = _fetch_spa_bundle(client)

    assert "Cloudflare Zero Trust Defense" in bundle
    assert "Enforce Cloudflare Zero Trust Email Authorization" in bundle
    assert "Save Zero Trust Policy" in bundle
    assert "Tailscale" in bundle
    assert "/api/settings/zero-trust" in bundle


def test_spa_json_auth_and_me_endpoint(test_env):
    """Verify JSON login/register flows and /api/auth/me used by the Preact SPA."""
    _, _ = test_env
    fresh = TestClient(app_module.app, follow_redirects=False)

    # Unauthenticated /api/auth/me
    me = fresh.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["authenticated"] is False

    # Public SPA routes return HTML shell
    assert fresh.get("/login").status_code == 200
    assert fresh.get("/register").status_code == 200

    # JSON register
    reg = fresh.post("/register", json={"username": "spa_test_user", "email": "spa_test@example.com"})
    assert reg.status_code == 200
    assert reg.json()["ok"] is True

    # JSON login (supports either initial or updated password from earlier tests)
    res = fresh.post("/login", json={"username": "admin", "password": "newsecret123"})
    if res.status_code != 200:
        res = fresh.post("/login", json={"username": "admin", "password": "admin123"})
    assert res.status_code == 200
    assert res.json()["ok"] is True

    # Authenticated /api/auth/me
    me2 = fresh.get("/api/auth/me")
    assert me2.status_code == 200
    assert me2.json() == {"authenticated": True, "username": "admin"}


def test_harvester_ignores_warnings_and_normalizes_timestamps(test_env):
    """Verify container log harvester ignores warning/transient retry chatter and deduplicates across timestamps."""
    from unittest.mock import MagicMock

    if hasattr(app_module, "_harvester_dedup_cache"):
        app_module._harvester_dedup_cache.clear()

    db = app_module.get_db()
    db.execute("DELETE FROM activity_log WHERE category='containers'")
    db.commit()
    db.close()

    mock_nav = MagicMock()
    mock_nav.name = "navidrome"
    mock_nav.status = "running"
    mock_nav.attrs = {"State": {"ExitCode": 0}}
    mock_nav.logs.return_value = (
        b'time="2026-11-18T10:00:01Z" level=warning msg="ListenBrainz Scrobble returned HTTP error" error="cache error"\n'
        b'time="2026-11-18T10:00:06Z" level=warning msg="Could not send scrobble. Will be retried"\n'
    )

    mock_pi = MagicMock()
    mock_pi.name = "pihole"
    mock_pi.status = "running"
    mock_pi.attrs = {"State": {"ExitCode": 0}}
    mock_pi.logs.return_value = (
        b"2026-11-18 11:56:48.367 IST [47535/F55] WARNING: Connection error (1.0.0.1#53): TCP connection failed\n"
        b"2026-11-18 14:30:02.358 IST [55/T121] ERROR: Cannot receive UDP DNS reply: Timed out after 2000 ms\n"
        b"2026-11-18 16:11:10.543 IST fatal: unable to access 'https://github.com/pi-hole/FTL/': Could not resolve host: github.com\n"
    )

    mock_db_ctr = MagicMock()
    mock_db_ctr.name = "mariadb"
    mock_db_ctr.status = "running"
    mock_db_ctr.attrs = {"State": {"ExitCode": 0}}
    mock_db_ctr.logs.return_value = (
        b"2026-11-18 10:01:01 [101] FATAL: InnoDB corruption detected\n"
        b"2026-11-18 10:01:05 [102] FATAL: InnoDB corruption detected\n"
    )

    mock_docker = MagicMock()
    mock_docker.containers.list.return_value = [mock_nav, mock_pi, mock_db_ctr]

    orig_docker = app_module.docker_client
    app_module.docker_client = mock_docker
    try:
        app_module.harvest_system_and_container_logs()
    finally:
        app_module.docker_client = orig_docker

    db = app_module.get_db()
    rows = db.execute("SELECT target, detail FROM activity_log WHERE category='containers'").fetchall()
    db.close()

    targets = [r["target"] for r in rows]
    assert "navidrome" not in targets
    assert "pihole" not in targets
    assert targets.count("mariadb") == 1


def test_system_events_dedup_and_resolve_endpoints(test_env):
    """Verify _log_sys deduplicates bursts and /api/system-events resolve endpoints work with SPA filter."""
    client, _ = test_env
    # Ensure authenticated
    r = client.post("/login", data={"username": "admin", "password": "newsecret123"})
    if r.status_code != 303:
        client.post("/login", data={"username": "admin", "password": "admin123"})

    app_module._sys_event_dedup.clear()
    db = app_module.get_db()
    db.execute("DELETE FROM system_events")
    db.commit()
    db.close()

    # Rapid duplicate alerts deduplicate to 1 row
    app_module._log_sys("high_cpu", "CPU critical: 98.5%", severity="critical")
    app_module._log_sys("high_cpu", "CPU critical: 99.1%", severity="critical")

    res = client.get("/api/system-events?unresolved=1")
    assert res.status_code == 200
    events = res.json()
    assert len(events) == 1
    eid = events[0]["id"]

    # Resolve single event
    r1 = client.post(f"/api/system-events/{eid}/resolve")
    assert r1.status_code == 200
    assert r1.json()["ok"] is True

    # Add another and resolve-all
    app_module._sys_event_dedup.clear()
    app_module._log_sys("high_ram", "RAM critical: 94.0%", severity="critical")
    r_all = client.post("/api/system-events/resolve-all")
    assert r_all.status_code == 200
    assert r_all.json()["resolved_count"] == 1

    stats = client.get("/api/logs/stats").json()
    assert stats["unresolved_events"] == 0

    # Verify SPA bundle includes System Alerts filter & resolve API
    _, bundle = _fetch_spa_bundle(client)
    assert "System Alerts" in bundle
    assert "/api/system-events/resolve-all" in bundle





