#!/usr/bin/env python3
"""
Homelab OS (HL-OS) — Core Control Plane Engine (FastAPI Edition)
Provides:
  - Resilient asynchronous control plane
  - Auto-generated OpenAPI / Swagger docs at /docs
  - Dual-hash authentication (seamless SHA-256 -> scrypt upgrade)
  - Non-blocking telemetry cache (optimized for 2-core Celeron)
  - Throttled single-threaded background audio conversion
  - 100% frozen frontend API contracts (zero JavaScript regressions)
"""

import os
import sys
import json
import sqlite3
import subprocess
import threading
import asyncio
import time
import signal
import hashlib
import math
import secrets
import shutil
import re
import ipaddress
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("homelab")

import psutil
try:
    import docker
except ImportError:
    docker = None
from fastapi import FastAPI, Request, Response, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from werkzeug.security import generate_password_hash, check_password_hash

import ops_updates
import ops_resources

# ── Configuration & Paths ─────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "data", "dashboard.db")
BACKUP_SCRIPT = os.environ.get("BACKUP_SCRIPT", "/scripts/backup.sh")
BACKUP_LOG = os.environ.get("BACKUP_LOG", "/logs/backup.log")
BACKUP_MOUNT = os.environ.get("BACKUP_MOUNT", "/mnt/backup")
MUSIC_DIR = os.environ.get("MUSIC_DIR", "/mnt/backup/music")
PLAYLIST_DIR = os.environ.get("PLAYLIST_DIR", os.path.join(MUSIC_DIR, "_playlists"))
NAVIDROME_URL = os.environ.get("NAVIDROME_URL", "http://navidrome:4533")
MALOJA_DB_PATH = os.environ.get("MALOJA_DB_PATH", "/maloja/malojadb.sqlite")
PROC_PATH = os.environ.get("PROCFS_PATH", "/proc")
DASHBOARD_SECRET = os.environ.get("DASHBOARD_SECRET", secrets.token_hex(32))

MANAGED = [
    "nextcloud", "mariadb", "redis", "nginx-proxy", "pihole",
    "navidrome", "maloja", "samba", "admin-dashboard"
]

docker_client = None
if docker:
    try:
        docker_client = docker.from_env(timeout=180)
    except Exception:
        pass

# ── App Initialization ────────────────────────────────────────────────────────
app = FastAPI(
    title="Homelab OS Control Plane",
    description="Unified self-hosted server dashboard, container manager, and resilient media engine",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

app.add_middleware(
    SessionMiddleware,
    secret_key=DASHBOARD_SECRET,
    max_age=86400 * 7,
    same_site="lax",
    https_only=(os.environ.get("FORCE_HTTPS", "false").lower() == "true")
)

STATIC_DIR = os.path.join(BASE_DIR, "static")
DIST_DIR = os.path.join(STATIC_DIR, "dist")
DIST_ASSETS_DIR = os.path.join(DIST_DIR, "assets")
SPA_INDEX_PATH = os.path.join(DIST_DIR, "index.html")
os.makedirs(STATIC_DIR, exist_ok=True)
os.makedirs(DIST_ASSETS_DIR, exist_ok=True)

app.mount("/assets", StaticFiles(directory=DIST_ASSETS_DIR), name="assets")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

def serve_spa(status_code: int = 200) -> HTMLResponse:
    if os.path.isfile(SPA_INDEX_PATH):
        with open(SPA_INDEX_PATH, "r", encoding="utf-8") as f:
            return HTMLResponse(
                content=f.read(),
                status_code=status_code,
                headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
            )
    return HTMLResponse(
        content="<!DOCTYPE html><html><body><h1>Homelab OS UI bundle not built</h1><p>Run npm run build in admin-dashboard/frontend.</p></body></html>",
        status_code=503,
    )

# ── Database Layer ────────────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    db = get_db()
    db.executescript("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS admins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            status TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT (datetime('now')),
            nextcloud_uid TEXT
        );
        CREATE TABLE IF NOT EXISTS activity_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT DEFAULT (datetime('now')),
            actor TEXT NOT NULL,
            action TEXT NOT NULL,
            category TEXT DEFAULT 'general',
            target TEXT,
            detail TEXT,
            status TEXT DEFAULT 'ok',
            ip TEXT,
            duration_ms INTEGER,
            severity TEXT DEFAULT 'info'
        );
        CREATE TABLE IF NOT EXISTS login_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ip TEXT NOT NULL,
            username TEXT,
            attempted_at TEXT DEFAULT (datetime('now')),
            success INTEGER DEFAULT 0,
            user_agent TEXT
        );
        CREATE TABLE IF NOT EXISTS ip_bans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ip TEXT UNIQUE NOT NULL,
            reason TEXT,
            banned_at TEXT DEFAULT (datetime('now')),
            expires_at TEXT
        );
        CREATE TABLE IF NOT EXISTS system_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT DEFAULT (datetime('now')),
            event_type TEXT NOT NULL,
            source TEXT,
            message TEXT NOT NULL,
            severity TEXT DEFAULT 'info',
            resolved INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS download_queue (
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
            format TEXT DEFAULT 'mp3',
            pid INTEGER DEFAULT 0,
            error TEXT,
            requested_by TEXT,
            is_playlist INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            completed_at TEXT
        );
        CREATE TABLE IF NOT EXISTS listen_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            track_path TEXT NOT NULL,
            track_title TEXT,
            artist TEXT,
            genre TEXT,
            duration_sec INTEGER,
            listened_sec INTEGER,
            completed INTEGER DEFAULT 0,
            hour_of_day INTEGER,
            day_of_week INTEGER,
            device TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS user_playlists (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            name TEXT NOT NULL,
            tracks TEXT DEFAULT '[]',
            auto_generated INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS net_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT DEFAULT (datetime('now')),
            iface TEXT NOT NULL,
            bytes_in INTEGER DEFAULT 0,
            bytes_out INTEGER DEFAULT 0,
            bytes_in_rate INTEGER DEFAULT 0,
            bytes_out_rate INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS container_net (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT DEFAULT (datetime('now')),
            container TEXT NOT NULL,
            bytes_in INTEGER DEFAULT 0,
            bytes_out INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS net_hourly (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            hour TEXT NOT NULL,
            iface TEXT NOT NULL,
            avg_in_rate INTEGER DEFAULT 0,
            avg_out_rate INTEGER DEFAULT 0,
            total_in INTEGER DEFAULT 0,
            total_out INTEGER DEFAULT 0,
            UNIQUE(hour, iface)
        );
        CREATE TABLE IF NOT EXISTS net_daily (
            day TEXT,
            iface TEXT,
            bytes_in INTEGER DEFAULT 0,
            bytes_out INTEGER DEFAULT 0,
            PRIMARY KEY (day, iface)
        );
        CREATE TABLE IF NOT EXISTS container_net_daily (
            day TEXT,
            container TEXT,
            bytes_in INTEGER DEFAULT 0,
            bytes_out INTEGER DEFAULT 0,
            PRIMARY KEY (day, container)
        );
        CREATE TABLE IF NOT EXISTS update_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            target TEXT NOT NULL,
            status TEXT DEFAULT 'queued',
            progress_pct INTEGER DEFAULT 0,
            current_step TEXT DEFAULT '',
            log TEXT DEFAULT '',
            cancel_requested INTEGER DEFAULT 0,
            triggered_by TEXT DEFAULT 'manual',
            error TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            started_at TEXT,
            completed_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_net_ts ON net_snapshots(ts);
        CREATE INDEX IF NOT EXISTS idx_cnet_ts ON container_net(ts);
        CREATE INDEX IF NOT EXISTS idx_net_daily_day ON net_daily(day);
        CREATE INDEX IF NOT EXISTS idx_container_net_daily_day ON container_net_daily(day);
        CREATE INDEX IF NOT EXISTS idx_listen_user ON listen_events(username);
    """)

    # Safe migration check for download_queue columns
    dq_cols = [col[1] for col in db.execute("PRAGMA table_info(download_queue)").fetchall()]
    if "pid" not in dq_cols:
        db.execute("ALTER TABLE download_queue ADD COLUMN pid INTEGER DEFAULT 0")
    if "format" not in dq_cols:
        db.execute("ALTER TABLE download_queue ADD COLUMN format TEXT DEFAULT 'mp3'")
    if "embed_thumbnail" not in dq_cols:
        db.execute("ALTER TABLE download_queue ADD COLUMN embed_thumbnail INTEGER DEFAULT 1")
    if "rate_limit" not in dq_cols:
        db.execute("ALTER TABLE download_queue ADD COLUMN rate_limit TEXT DEFAULT ''")
    if "archive_skip" not in dq_cols:
        db.execute("ALTER TABLE download_queue ADD COLUMN archive_skip INTEGER DEFAULT 1")

    # Safe migration check for activity_log columns & indexes
    al_cols = [col[1] for col in db.execute("PRAGMA table_info(activity_log)").fetchall()]
    al_required = {
        "timestamp": "TEXT DEFAULT (datetime('now'))",
        "actor": "TEXT NOT NULL DEFAULT 'system'",
        "action": "TEXT NOT NULL DEFAULT 'event'",
        "category": "TEXT DEFAULT 'general'",
        "target": "TEXT",
        "detail": "TEXT",
        "status": "TEXT DEFAULT 'ok'",
        "ip": "TEXT",
        "duration_ms": "INTEGER",
        "severity": "TEXT DEFAULT 'info'"
    }
    for col_name, col_def in al_required.items():
        if col_name not in al_cols:
            db.execute(f"ALTER TABLE activity_log ADD COLUMN {col_name} {col_def}")
    db.execute("CREATE INDEX IF NOT EXISTS idx_activity_ts ON activity_log(timestamp)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_activity_cat ON activity_log(category)")

    # Seed initial admin with secure scrypt hash if empty
    if not db.execute("SELECT id FROM admins LIMIT 1").fetchone():
        default_user = os.environ.get("ADMIN_DEFAULT_USER", "").strip() or "admin"
        default_pw = os.environ.get("ADMIN_DEFAULT_PASSWORD", "").strip() or "admin123"
        db.execute(
            "INSERT INTO admins (username, password_hash) VALUES (?, ?)",
            (default_user, generate_password_hash(default_pw, method="scrypt"))
        )
    db.commit()
    db.close()

# ── Dual-Hash Password Migration ──────────────────────────────────────────────
def hash_password(pw: str) -> str:
    return generate_password_hash(pw, method="scrypt")

def verify_and_migrate_password(input_password: str, stored_hash: str) -> tuple:
    """
    Verifies input password against stored hash.
    If stored hash is legacy SHA-256, upgrades transparently to scrypt.
    Returns: (is_valid, upgraded_hash_or_same, was_upgraded)
    """
    if stored_hash.startswith(("scrypt:", "pbkdf2:")):
        return check_password_hash(stored_hash, input_password), stored_hash, False
    
    # Check legacy SHA-256
    legacy = hashlib.sha256(input_password.encode()).hexdigest()
    if legacy == stored_hash:
        new_hash = generate_password_hash(input_password, method="scrypt")
        return True, new_hash, True
    
    return False, stored_hash, False

def log_action(actor: str, action: str, category: str = "general", target: str = None,
               detail: str = None, status: str = "ok", severity: str = "info",
               ms: int = None, ip: str = None):
    db = None
    try:
        db = get_db()
        db.execute(
            "INSERT INTO activity_log "
            "(actor, action, category, target, detail, status, ip, duration_ms, severity) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (actor, action, category, target, detail, status, ip or "system", ms, severity)
        )
        db.commit()
    except Exception:
        pass
    finally:
        if db:
            try:
                db.close()
            except Exception:
                pass

_sys_event_dedup: Dict[str, float] = {}
_sys_event_dedup_lock = threading.Lock()

def _log_sys(etype: str, msg: str, severity: str = "info", dedup_seconds: int = 600):
    now = time.time()
    with _sys_event_dedup_lock:
        last = _sys_event_dedup.get(etype, 0.0)
        if dedup_seconds > 0 and (now - last) < dedup_seconds:
            return
        _sys_event_dedup[etype] = now
    db = None
    try:
        db = get_db()
        db.execute(
            "INSERT INTO system_events (event_type, source, message, severity) VALUES (?,?,?,?)",
            (etype, "system", msg, severity)
        )
        db.commit()
    except Exception:
        pass
    finally:
        if db:
            try:
                db.close()
            except Exception:
                pass

# ── Cloudflare Zero Trust Defense-in-Depth ────────────────────────────────────
LOCAL_PRIVATE_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]

def is_local_or_private_ip(ip_str: str) -> bool:
    if not ip_str:
        return False
    ip_clean = ip_str.strip().lower()
    if ip_clean in ("testclient", "localhost"):
        return True
    try:
        ip = ipaddress.ip_address(ip_clean)
        if getattr(ip, "ipv4_mapped", None):
            ip = ip.ipv4_mapped
        return any(ip in net for net in LOCAL_PRIVATE_NETWORKS)
    except ValueError:
        return False

# ── Authentication & Security Guard ───────────────────────────────────────────
def get_client_ip(request: Request) -> str:
    cf_connecting = request.headers.get("CF-Connecting-IP")
    if cf_connecting:
        return cf_connecting.strip()
    direct_host = request.client.host if request.client else "127.0.0.1"
    forwarded = request.headers.get("X-Forwarded-For")
    # Only trust X-Forwarded-For if request comes from local/private reverse proxy
    if forwarded and is_local_or_private_ip(direct_host):
        return forwarded.split(",")[0].strip()
    return direct_host

def get_zero_trust_config() -> dict:
    enabled = None
    allowed_emails_raw = None
    bypass_local = None

    try:
        db = get_db()
        rows = db.execute(
            "SELECT key, value FROM settings WHERE key IN "
            "('cloudflare_zero_trust_enabled', 'allowed_zero_trust_emails', 'zero_trust_bypass_local')"
        ).fetchall()
        db.close()
        settings_map = {r["key"]: r["value"] for r in rows}
        if "cloudflare_zero_trust_enabled" in settings_map:
            val = settings_map["cloudflare_zero_trust_enabled"]
            if val is not None:
                enabled = str(val).strip().lower() in ("true", "1", "yes")
        if "allowed_zero_trust_emails" in settings_map:
            allowed_emails_raw = settings_map["allowed_zero_trust_emails"]
        if "zero_trust_bypass_local" in settings_map:
            val = settings_map["zero_trust_bypass_local"]
            if val is not None:
                bypass_local = str(val).strip().lower() in ("true", "1", "yes")
    except Exception:
        pass

    if enabled is None:
        enabled = os.environ.get("CLOUDFLARE_ZERO_TRUST_ENABLED", "false").strip().lower() in ("true", "1", "yes")

    if allowed_emails_raw is None:
        allowed_emails_raw = os.environ.get("ALLOWED_ZERO_TRUST_EMAILS", "")

    if bypass_local is None:
        bypass_local = os.environ.get("ZERO_TRUST_BYPASS_LOCAL", "true").strip().lower() in ("true", "1", "yes")

    if isinstance(allowed_emails_raw, list):
        items = allowed_emails_raw
    else:
        items = str(allowed_emails_raw or "").split(",")

    allowed_emails = []
    for em in items:
        clean = str(em).strip().lower()
        if clean and clean not in allowed_emails:
            allowed_emails.append(clean)

    return {
        "enabled": bool(enabled),
        "allowed_emails": allowed_emails,
        "bypass_local": bool(bypass_local)
    }

class CloudflareZeroTrustMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        cfg = get_zero_trust_config()
        if not cfg["enabled"]:
            return await call_next(request)

        # Detect Cloudflare presence headers
        is_cf = any(
            h in request.headers
            for h in ("cf-connecting-ip", "cf-ray", "cf-access-authenticated-user-email")
        )

        if is_cf:
            cf_email = request.headers.get("cf-access-authenticated-user-email", "").strip().lower()
            if cf_email and cf_email in cfg["allowed_emails"]:
                request.state.cf_email = cf_email
                return await call_next(request)
            else:
                log_action(
                    actor=cf_email or "anonymous",
                    action="Zero Trust Blocked",
                    category="security",
                    detail=f"Unauthorized email: {cf_email or 'none'}",
                    status="blocked",
                    severity="warning",
                    ip=get_client_ip(request)
                )
                return JSONResponse(
                    {"detail": "Forbidden: Cloudflare Zero Trust authorization failed"},
                    status_code=403
                )

        # Cloudflare headers are NOT present
        if cfg["bypass_local"]:
            client_ip = get_client_ip(request)
            if is_local_or_private_ip(client_ip):
                return await call_next(request)
            else:
                log_action(
                    actor="anonymous",
                    action="Zero Trust Blocked",
                    category="security",
                    detail=f"Direct public access blocked from IP: {client_ip}",
                    status="blocked",
                    severity="warning",
                    ip=client_ip
                )
                return JSONResponse(
                    {"detail": "Forbidden: Direct public access not allowed"},
                    status_code=403
                )
        else:
            return JSONResponse(
                {"detail": "Forbidden: Direct public access not allowed"},
                status_code=403
            )

app.add_middleware(CloudflareZeroTrustMiddleware)

@app.middleware("http")
async def _track_server_activity_middleware(request: Request, call_next):
    is_bg = request.headers.get("x-background-poll") == "1"
    path = request.url.path or ""
    if not is_bg and not path.startswith("/static/") and path != "/health":
        touch_activity()
        ops_resources.touch_server_request()
    return await call_next(request)

def resolve_navidrome_url(request: Request = None) -> str:
    """
    Dynamically resolve external Navidrome URL based on request headers/hostname,
    with zero hardcoding and fallback to NAVIDROME_PUBLIC_URL or NAVIDROME_URL.
    """
    nav_port = os.environ.get("NAVIDROME_PORT", "4533").strip()
    public_url_env = os.environ.get("NAVIDROME_PUBLIC_URL", "").strip()

    if not request:
        return public_url_env or os.environ.get("NAVIDROME_URL", f"http://localhost:{nav_port}")

    # Inspect x-forwarded-host, host header, or request hostname
    forwarded_host = request.headers.get("x-forwarded-host", "").strip()
    host_hdr = forwarded_host or request.headers.get("host", "").strip()

    # If host header is explicitly empty or missing, fallback to public_url_env if present
    if not host_hdr:
        if public_url_env:
            return public_url_env
        host_hdr = (request.url.hostname or "").strip()
        if not host_hdr:
            return public_url_env or os.environ.get("NAVIDROME_URL", f"http://localhost:{nav_port}")

    proto = request.headers.get("x-forwarded-proto", "").strip() or request.url.scheme or "http"

    # Separate host and port
    if ":" in host_hdr:
        hostname, _, port = host_hdr.partition(":")
    else:
        hostname = host_hdr
        port = str(request.url.port or "") if request.url.port else ""

    # Port mapping: If dashboard is accessed on port 5001, 2081, or any non-standard web port
    if port and port not in ("80", "443"):
        parts = hostname.split(".")
        if len(parts) > 1 and parts[0].lower() in ("dashboard", "admin", "dash"):
            sub_mapped = "navidrome." + ".".join(parts[1:])
            return f"{proto}://{sub_mapped}:{nav_port}"
        return f"{proto}://{hostname}:{nav_port}"

    # If accessed on standard port (80/443) or no port:
    parts = hostname.split(".")
    # Subdomain mapping (e.g. dashboard.domain.com -> navidrome.domain.com)
    if len(parts) > 1 and parts[0].lower() in ("dashboard", "admin", "dash"):
        sub_mapped = "navidrome." + ".".join(parts[1:])
        port_suffix = f":{port}" if port and port not in ("80", "443") else ""
        return f"{proto}://{sub_mapped}{port_suffix}"

    # If accessing directly on IP or root host on standard ports without subdomain mapping
    if port in ("80", "443"):
        if public_url_env:
            return public_url_env
        return f"{proto}://{hostname}:{nav_port}"

    return f"{proto}://{hostname}:{nav_port}"

def login_required(request: Request):
    if not request.session.get("admin_logged_in"):
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": "/login"}
        )
    if request.headers.get("x-background-poll") != "1":
        touch_activity()
        ops_resources.touch_server_request()
    return request.session.get("admin_username", "admin")

def is_ip_banned(ip: str) -> bool:
    db = get_db()
    r = db.execute(
        "SELECT id FROM ip_bans WHERE ip=? AND (expires_at IS NULL OR datetime(expires_at) > datetime('now'))",
        (ip,)
    ).fetchone()
    db.close()
    return r is not None

def fail_count(ip: str, mins: int = 15) -> int:
    db = get_db()
    since = (datetime.utcnow() - timedelta(minutes=mins)).isoformat()
    r = db.execute(
        "SELECT COUNT(*) as c FROM login_attempts WHERE ip=? AND success=0 AND attempted_at>?",
        (ip, since)
    ).fetchone()
    db.close()
    return r["c"] if r else 0

# ── Non-Blocking Container Telemetry Cache (2-Core Celeron Tuning) ─────────────
_container_cache = []
_container_lock = threading.Lock()
_last_activity_ts = time.time()

def touch_activity():
    global _last_activity_ts
    _last_activity_ts = time.time()

def _refresh_container_stats():
    global _container_cache
    if not docker_client:
        return
    results = []
    try:
        for c in docker_client.containers.list(all=True):
            cpu_pct = 0.0
            mem_mb = 0.0
            if c.status == "running":
                try:
                    raw = c.stats(stream=False)
                    cd = raw["cpu_stats"]["cpu_usage"]["total_usage"] - raw["precpu_stats"]["cpu_usage"]["total_usage"]
                    sd = raw["cpu_stats"]["system_cpu_usage"] - raw["precpu_stats"]["system_cpu_usage"]
                    ncpu = raw["cpu_stats"].get("online_cpus", 1)
                    if sd > 0:
                        cpu_pct = round((cd / sd) * ncpu * 100, 1)
                    mem_mb = round(raw["memory_stats"].get("usage", 0) / 1e6, 1)
                except Exception:
                    pass
            results.append({
                "name": c.name,
                "image": c.image.tags[0] if c.image.tags else c.image.short_id,
                "status": c.status,
                "cpu_percent": cpu_pct,
                "mem_mb": mem_mb,
                "managed": c.name in MANAGED
            })
    except Exception:
        pass
    results.sort(key=lambda x: (x["name"] not in MANAGED, x["name"]))
    with _container_lock:
        _container_cache = results

def start_container_collector():
    def loop():
        while True:
            _refresh_container_stats()
            time.sleep(30)  # Polled every 30s instead of 10s to keep Celeron idle CPU < 2%
    threading.Thread(target=loop, daemon=True).start()

# ── Network Collector Loop ────────────────────────────────────────────────────
_net_prev = {}
_cnet_prev = {}

def get_net_dev_path() -> Optional[str]:
    """Resolve /proc/net/dev candidate paths in order (Zero hardcoding)."""
    candidate_paths = [
        os.path.join(PROC_PATH, "1", "net", "dev"),
        os.path.join(PROC_PATH, "net", "dev"),
        "/host_proc/1/net/dev",
        "/host_proc/net/dev",
        "/proc/net/dev"
    ]
    for p in candidate_paths:
        if os.path.exists(p):
            return p
    return None

def is_valid_interface(iface: str) -> bool:
    """Filter out lo, virtual docker bridges (br-*, docker0), and veth pairs (veth*)."""
    if not iface:
        return False
    iface = iface.strip()
    if iface == "lo":
        return False
    if iface == "docker0" or iface.startswith("docker"):
        return False
    if iface.startswith("br-"):
        return False
    if iface.startswith("veth"):
        return False
    return True

def format_bytes(bytes_val, is_rate: bool = False, rate: bool = False) -> str:
    """Format byte values into human-readable strings (e.g., 1.2 MB/s, 450.5 KB/s, 12.4 GB)."""
    use_rate = is_rate or rate
    try:
        val = float(bytes_val or 0)
    except (ValueError, TypeError):
        val = 0.0

    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    unit_idx = 0
    while abs(val) >= 1024.0 and unit_idx < len(units) - 1:
        val /= 1024.0
        unit_idx += 1

    unit = units[unit_idx]
    if unit == "B":
        s = f"{int(val)} {unit}"
    else:
        s = f"{val:.1f} {unit}"

    return f"{s}/s" if use_rate else s

def _collect_net():
    now_ts = datetime.utcnow().isoformat()
    db = None
    try:
        db = get_db()
        dev_path = get_net_dev_path()
        if dev_path and os.path.exists(dev_path):
            with open(dev_path) as f:
                lines = f.readlines()[2:]
            now_time = time.time()
            for line in lines:
                line_str = line.strip()
                if not line_str or ":" not in line_str:
                    continue
                iface_part, stats_part = line_str.split(":", 1)
                iface = iface_part.strip()
                if not is_valid_interface(iface):
                    continue
                stats = stats_part.split()
                if len(stats) < 9:
                    continue
                rx = int(stats[0])
                tx = int(stats[8])
                prev = _net_prev.get(iface)
                rate_in = rate_out = 0
                if prev:
                    el = now_time - prev[2]
                    if el > 0:
                        rate_in = max(0, int((rx - prev[0]) / el))
                        rate_out = max(0, int((tx - prev[1]) / el))
                _net_prev[iface] = (rx, tx, now_time)
                db.execute(
                    "INSERT INTO net_snapshots (ts,iface,bytes_in,bytes_out,bytes_in_rate,bytes_out_rate) "
                    "VALUES (?,?,?,?,?,?)",
                    (now_ts, iface, rx, tx, rate_in, rate_out)
                )

        # Container stats
        if docker_client:
            try:
                for c in docker_client.containers.list():
                    try:
                        s = c.stats(stream=False)
                        nets = s.get("networks", {})
                        rx2 = sum(v.get("rx_bytes", 0) for v in nets.values())
                        tx2 = sum(v.get("tx_bytes", 0) for v in nets.values())
                        tot2 = rx2 + tx2
                        prev_tot = _cnet_prev.get(c.name)
                        if prev_tot is not None and (tot2 - prev_tot) > 512:
                            ops_resources.touch_container_request(c.name)
                        _cnet_prev[c.name] = tot2
                        db.execute(
                            "INSERT INTO container_net (ts,container,bytes_in,bytes_out) VALUES (?,?,?,?)",
                            (now_ts, c.name, rx2, tx2)
                        )
                    except Exception:
                        pass
            except Exception:
                pass

        # Pruning snapshots older than 7 days
        cutoff = (datetime.utcnow() - timedelta(days=7)).isoformat()
        db.execute("DELETE FROM net_snapshots WHERE ts<?", (cutoff,))
        db.execute("DELETE FROM container_net WHERE ts<?", (cutoff,))

        # Roll up hourly stats
        last_hour = datetime.utcnow().replace(minute=0, second=0, microsecond=0).isoformat()
        db.execute(
            "INSERT OR REPLACE INTO net_hourly "
            "(hour,iface,avg_in_rate,avg_out_rate,total_in,total_out) "
            "SELECT strftime('%Y-%m-%dT%H:00:00',ts) as hour, iface, "
            "AVG(bytes_in_rate), AVG(bytes_out_rate), "
            "MAX(bytes_in)-MIN(bytes_in), MAX(bytes_out)-MIN(bytes_out) "
            "FROM net_snapshots WHERE strftime('%Y-%m-%dT%H:00:00',ts)=? "
            "GROUP BY iface",
            (last_hour,)
        )
        cutoff_y = (datetime.utcnow() - timedelta(days=365)).isoformat()
        db.execute("DELETE FROM net_hourly WHERE hour<?", (cutoff_y,))

        # Roll up daily snapshots into net_daily (scoped to today for minimal Celeron CPU)
        today_str = datetime.utcnow().strftime("%Y-%m-%d")
        db.execute(
            "INSERT OR REPLACE INTO net_daily (day, iface, bytes_in, bytes_out) "
            "SELECT strftime('%Y-%m-%d', hour) as day, iface, SUM(total_in), SUM(total_out) "
            "FROM net_hourly WHERE hour >= ? GROUP BY day, iface",
            (today_str,)
        )

        # Roll up container daily into container_net_daily (scoped to today for minimal Celeron CPU)
        db.execute(
            "INSERT OR REPLACE INTO container_net_daily (day, container, bytes_in, bytes_out) "
            "SELECT strftime('%Y-%m-%d', ts) as day, container, "
            "MAX(bytes_in) - MIN(bytes_in), MAX(bytes_out) - MIN(bytes_out) "
            "FROM container_net WHERE ts >= ? GROUP BY day, container",
            (today_str,)
        )

        db.commit()
    except Exception:
        pass
    finally:
        if db:
            try:
                db.close()
            except Exception:
                pass

def start_net_collector():
    def loop():
        while True:
            _collect_net()
            time.sleep(30)
    threading.Thread(target=loop, daemon=True).start()

# ── Background System & Container Log Harvester (2-Core Celeron Tuned) ─────────
_harvester_dedup_cache = {}
_harvester_last_since = {}

def _is_deduped(key: str, ttl_seconds: float = 300.0) -> bool:
    now = time.time()
    if len(_harvester_dedup_cache) > 1000:
        cutoff = now - 3600
        keys_to_del = [k for k, ts in _harvester_dedup_cache.items() if ts < cutoff]
        for k in keys_to_del:
            del _harvester_dedup_cache[k]
    if key in _harvester_dedup_cache:
        if (now - _harvester_dedup_cache[key]) < ttl_seconds:
            return True
    _harvester_dedup_cache[key] = now
    return False

def harvest_system_and_container_logs():
    """
    Lightweight harvester:
      1. Inspects system RAM and root disk thresholds (>90% -> warning log).
      2. Inspects Docker container lifecycle states (exited, dead, unhealthy -> warning/error).
      3. Tails recent logs for key service containers searching for fatal errors / exceptions.
      4. Deduplicates recent alerts to prevent repetitive spam.
    """
    # 1. System resource alerts
    try:
        mem = psutil.virtual_memory()
        if mem.percent > 90:
            if not _is_deduped("sys_alert:ram_high", 300):
                log_action(
                    actor="system",
                    action="High memory threshold",
                    category="system",
                    target="RAM",
                    detail=f"RAM usage reached {round(mem.percent, 1)}% (threshold 90%)",
                    status="warning",
                    severity="warning"
                )
    except Exception:
        pass

    try:
        disk = psutil.disk_usage("/")
        if disk.percent > 90:
            if not _is_deduped("sys_alert:disk_high", 300):
                log_action(
                    actor="system",
                    action="Disk threshold warning",
                    category="system",
                    target="disk",
                    detail=f"Disk usage at {round(disk.percent, 1)}% on / (threshold 90%)",
                    status="warning",
                    severity="warning"
                )
    except Exception:
        pass

    # 2. Docker container lifecycle & error tailing
    if docker_client:
        try:
            containers = docker_client.containers.list(all=True)
            KEY_LOG_CONTAINERS = {"nextcloud", "mariadb", "pihole", "navidrome", "samba"}
            error_pattern = re.compile(
                r'\b(fatal|panic|exception|critical|traceback|oomkilled)\b|\[error\]|\berror\b',
                re.IGNORECASE
            )
            # Ignore non-fatal warning/info lines and benign transient upstream retry chatter
            ignore_pattern = re.compile(
                r'level=(warning|warn|info|debug)\b|\bWARNING:|'
                r'Will be retried|ListenBrainz Scrobble|Connection error \(|'
                r'Cannot receive UDP DNS reply:\s*Timed out|'
                r'Could not resolve host:\s*github\.com',
                re.IGNORECASE
            )
            norm_pattern = re.compile(
                r'time="[^"]+"|\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:\s*[A-Z]{2,4})?|'
                r'\[\d+(?:/[A-Za-z0-9_-]+)?\]|\b\d{1,3}(?:\.\d{1,3}){3}(?:#\d+|:\d+)?\b|\b\d+\b'
            )
            now_epoch = int(time.time())
            eco_sleep_targets = set()
            try:
                _sdb = get_db()
                try:
                    eco_sleep_targets = set(ops_resources.get_sleep_settings(_sdb).get("sleep_targets") or [])
                finally:
                    _sdb.close()
            except Exception:
                pass

            for c in containers:
                c_name = getattr(c, "name", "unknown")
                status = getattr(c, "status", "unknown")
                health = ""
                exit_code = None
                attrs = getattr(c, "attrs", {})
                if isinstance(attrs, dict):
                    state_dict = attrs.get("State", {})
                    if isinstance(state_dict, dict):
                        exit_code = state_dict.get("ExitCode")
                        health_dict = state_dict.get("Health", {})
                        if isinstance(health_dict, dict):
                            health = health_dict.get("Status", "")

                # Container lifecycle state checks (suppress expected Eco-Sleep stops/pauses)
                is_unhealthy = (health == "unhealthy" or status == "unhealthy")
                is_exited_or_dead = status in ("exited", "dead")
                is_eco_sleeping = (
                    c_name in eco_sleep_targets
                    and status in ("exited", "paused")
                    and (exit_code is None or exit_code in (0, 143))
                )

                if (is_exited_or_dead or is_unhealthy) and not is_eco_sleeping:
                    problem_type = "unhealthy" if is_unhealthy else status
                    sev = "error" if (problem_type in ("dead", "unhealthy") or (exit_code and exit_code != 0)) else "warning"
                    dedup_key = f"container_status:{c_name}:{problem_type}:{exit_code}"
                    if not _is_deduped(dedup_key, 300):
                        detail = f"Container {c_name} in {problem_type} state"
                        if exit_code is not None:
                            detail += f" (exit code {exit_code})"
                        log_action(
                            actor="system",
                            action=f"Container {c_name} {problem_type}",
                            category="containers",
                            target=c_name,
                            detail=detail,
                            status="error" if sev == "error" else "warning",
                            severity=sev
                        )

                # Error log tailing for key containers
                is_key_container = any(k in c_name.lower() for k in KEY_LOG_CONTAINERS)
                if is_key_container and hasattr(c, "logs"):
                    try:
                        since_ts = _harvester_last_since.get(c_name, now_epoch - 60)
                        try:
                            raw_logs = c.logs(tail=20, since=since_ts)
                        except TypeError:
                            raw_logs = c.logs(tail=20)
                        _harvester_last_since[c_name] = now_epoch

                        if isinstance(raw_logs, bytes):
                            text_logs = raw_logs.decode("utf-8", errors="replace")
                        else:
                            text_logs = str(raw_logs)

                        err_count = 0
                        for line in text_logs.splitlines():
                            line_clean = line.strip()
                            if not line_clean:
                                continue
                            if ignore_pattern.search(line_clean):
                                continue
                            if error_pattern.search(line_clean):
                                normalized = norm_pattern.sub("", line_clean).strip().lower()
                                line_hash = hashlib.sha256((normalized or line_clean).encode("utf-8", errors="ignore")).hexdigest()[:16]
                                log_dedup_key = f"container_log_err:{c_name}:{line_hash}"
                                if not _is_deduped(log_dedup_key, 1800):
                                    log_action(
                                        actor="system",
                                        action=f"Container error in {c_name}",
                                        category="containers",
                                        target=c_name,
                                        detail=line_clean[:400],
                                        status="error",
                                        severity="error"
                                    )
                                    err_count += 1
                                    if err_count >= 5:
                                        break
                    except Exception:
                        pass
        except Exception:
            pass

def start_system_log_harvester():
    def loop():
        while True:
            try:
                harvest_system_and_container_logs()
            except Exception:
                pass
            time.sleep(35)  # Runs every 35s (low CPU impact on Celeron)
    threading.Thread(target=loop, daemon=True).start()

# ── Audio Download Worker (Throttled for Dual-Core CPU) ────────────────────────
PLATFORM_MAP = {
    "spotify.com": "spotify",
    "youtu.be": "youtube",
    "youtube.com": "youtube",
    "soundcloud.com": "soundcloud",
    "bandcamp.com": "bandcamp",
}

def detect_platform(url: str) -> str:
    for k, v in PLATFORM_MAP.items():
        if k in url:
            return v
    return "unknown"

def is_playlist_url(url: str) -> bool:
    return ("playlist" in url.lower() or "list=" in url or "/sets/" in url or "/album/" in url)

CLEAN_TITLE_RE = re.compile(
    r'(?i)\s*[\(\[](?:official\s*(?:video|audio|music\s*video|lyric\s*video|hd(?:\s*video)?|4k(?:\s*video)?|hd|4k)?|lyrics?(?:\s*video)?|visualizer|audio)[\)\]]'
)

def clean_track_title(title: str) -> str:
    if not title:
        return ""
    t = title
    prev = None
    while t != prev:
        prev = t
        t = CLEAN_TITLE_RE.sub("", t).strip()
    return t

def resolve_audio_format(val: str = None) -> tuple:
    """
    Resolves input quality/format to (format_name, ytdlp_args_list).
    Supported formats:
      - flac: Hi-Res Studio Lossless (--audio-format flac)
      - opus: High Fidelity 160kbps+ VBR (--audio-format opus)
      - m4a: AAC 256kbps (--audio-format m4a)
      - mp3_320: 320 kbps CBR MP3 (--audio-format mp3, --audio-quality 320k)
      - mp3_256: 256 kbps MP3 (--audio-format mp3, --audio-quality 256k)
      - wav: Uncompressed PCM (--audio-format wav)
      - default: mp3_320
    """
    v = (val or "").strip().lower()
    if v in ("flac",):
        return "flac", ["--audio-format", "flac"]
    if v in ("opus",):
        return "opus", ["--audio-format", "opus"]
    if v in ("m4a", "aac"):
        return "m4a", ["--audio-format", "m4a"]
    if v in ("mp3_256", "256", "256k"):
        return "mp3_256", ["--audio-format", "mp3", "--audio-quality", "256k"]
    if v in ("wav",):
        return "wav", ["--audio-format", "wav"]
    # Default to mp3_320
    return "mp3_320", ["--audio-format", "mp3", "--audio-quality", "320k"]

RATE_LIMIT_RE = re.compile(r'^\d+(?:\.\d+)?[KMGkmg]?$')

def sanitize_rate_limit(val: Optional[str]) -> str:
    s = (val or "").strip()
    if not s or s.lower() in ("unlimited", "none", "0"):
        return ""
    return s if RATE_LIMIT_RE.match(s) else ""

def _effective_download_tuning() -> tuple:
    """Returns (nice_level, global_rate_limit) respecting power profile and thermal guard."""
    nice_level = 15
    global_rate = ""
    try:
        db = get_db()
        rows = db.execute(
            "SELECT key, value FROM settings WHERE key IN ('power_profile', 'download_rate_limit', 'cpu_throttle_pct', 'cpu_throttle_temp_c')"
        ).fetchall()
        db.close()
        smap = {r["key"]: (r["value"] or "") for r in rows}
        prof = smap.get("power_profile", "balanced").lower()
        if prof == "eco":
            nice_level = 19
        elif prof == "performance":
            nice_level = 5
        global_rate = sanitize_rate_limit(smap.get("download_rate_limit", ""))

        # Adaptive CPU/Thermal safety guard
        max_cpu = float(smap.get("cpu_throttle_pct") or 85)
        max_temp = float(smap.get("cpu_throttle_temp_c") or 80)
        cpu_now = psutil.cpu_percent(interval=None)
        temp_now = 0.0
        try:
            raw_t = psutil.sensors_temperatures() or {}
            vals = [e.current for entries in raw_t.values() for e in entries if getattr(e, "current", None)]
            if vals:
                temp_now = max(vals)
        except Exception:
            pass
        if cpu_now > max_cpu or temp_now > max_temp:
            nice_level = 19
            if not global_rate:
                global_rate = "512K"
    except Exception:
        pass
    return nice_level, global_rate

def build_ytdlp_command(
    url: str,
    music_dir: str,
    quality: str = "mp3_320",
    is_playlist: bool = False,
    nice_level: int = 15,
    rate_limit: str = "",
    embed_thumbnail: bool = True,
    archive_skip: bool = True,
) -> List[str]:
    """Builds a minimal-CPU/RAM/IO yt-dlp command (audio-only, 1 fragment, single-thread ffmpeg)."""
    _, fmt_args = resolve_audio_format(quality)
    out_tpl = os.path.join(music_dir, "%(artist,uploader)s - %(title)s.%(ext)s")

    cmd: List[str] = []
    if shutil.which("ionice"):
        cmd.extend(["ionice", "-c", "3"])
    cmd.extend(["nice", "-n", str(int(nice_level)), "yt-dlp"])
    cmd.extend([
        "--format", "bestaudio[abr<=320]/bestaudio/best",
        "--extract-audio",
        *fmt_args,
        "--concurrent-fragments", "1",
        "--postprocessor-args", "ffmpeg:-threads 1",
        "--no-overwrites",
        "--embed-metadata",
    ])
    if embed_thumbnail:
        cmd.append("--embed-thumbnail")
    if archive_skip:
        cmd.extend(["--download-archive", os.path.join(music_dir, ".download_archive.txt")])
    clean_rate = sanitize_rate_limit(rate_limit)
    if clean_rate:
        cmd.extend(["--limit-rate", clean_rate])
    cmd.extend([
        "--parse-metadata", "%(artist,creator,uploader,channel)s:%(meta_artist)s",
        "--replace-in-metadata", "title", r"(?i)\s*[\(\[](?:official\s*(?:video|audio|music\s*video|lyric\s*video|hd(?:\s*video)?|4k(?:\s*video)?|hd|4k)?|lyrics?(?:\s*video)?|visualizer|audio)[\)\]]", "",
        "--newline",
        "--progress",
        "--no-mtime",
        "--output", out_tpl,
    ])
    if not is_playlist:
        cmd.append("--no-playlist")
    cmd.append(url)
    return cmd

def _trigger_navidrome_scan() -> bool:
    """Lightweight non-fatal Navidrome library scan trigger on download completion."""
    if docker_client:
        try:
            nav = docker_client.containers.get("navidrome")
            if getattr(nav, "status", "") == "running":
                res = nav.exec_run("/app/navidrome scan", detach=True)
                if res is not None:
                    return True
        except Exception:
            try:
                nav = docker_client.containers.get("navidrome")
                if getattr(nav, "status", "") == "running":
                    nav.exec_run("navidrome scan", detach=True)
                    return True
            except Exception:
                pass
    return False

def _run_download(
    job_id: int,
    url: str,
    music_dir: str,
    quality: str = "mp3_320",
    embed_thumbnail: bool = True,
    rate_limit: str = "",
    archive_skip: bool = True,
):
    def upd(**kw):
        try:
            db = get_db()
            row = db.execute("SELECT status FROM download_queue WHERE id=?", (job_id,)).fetchone()
            if row and row["status"] == "cancelled" and kw.get("status") != "cancelled":
                db.close()
                return
            fields = [f"{k}=?" for k in kw]
            vals = list(kw.values())
            if kw.get("status") in ("completed", "failed", "cancelled"):
                fields.append("completed_at=?")
                vals.append(datetime.utcnow().isoformat())
            if fields:
                db.execute(f"UPDATE download_queue SET {','.join(fields)} WHERE id=?", (*vals, job_id))
                db.commit()
            db.close()
        except Exception:
            pass

    # Quick check if cancelled or removed before running
    db = get_db()
    row = db.execute("SELECT status FROM download_queue WHERE id=?", (job_id,)).fetchone()
    db.close()
    if not row or row["status"] == "cancelled":
        return

    audio_fmt, _ = resolve_audio_format(quality)
    upd(status="downloading", format=audio_fmt, current_track_pct=0)
    try:
        os.makedirs(music_dir, exist_ok=True)
    except Exception as e:
        upd(status="failed", current_track=f"Directory error: {str(e)[:100]}")
        return
    is_pl = is_playlist_url(url)

    if is_pl:
        try:
            flat = subprocess.run(
                ["yt-dlp", "--flat-playlist", "--print", "%(id)s", url],
                capture_output=True, text=True, timeout=60
            )
            total = len([l for l in flat.stdout.strip().splitlines() if l.strip()])
            if total > 0:
                upd(total_tracks=total, is_playlist=1)
        except Exception:
            pass

    nice_level, global_rate = _effective_download_tuning()
    eff_rate = sanitize_rate_limit(rate_limit) or global_rate

    cmd = build_ytdlp_command(
        url=url,
        music_dir=music_dir,
        quality=audio_fmt,
        is_playlist=is_pl,
        nice_level=nice_level,
        rate_limit=eff_rate,
        embed_thumbnail=bool(embed_thumbnail),
        archive_skip=bool(archive_skip),
    )

    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        upd(pid=proc.pid)
        done_tracks = 0
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            m = re.search(r'\[(?:download|ExtractAudio|Merger)\] Destination: (.+)', line)
            if m:
                fname = os.path.splitext(os.path.basename(m.group(1)))[0]
                fname = clean_track_title(fname)
                upd(current_track=fname[:80], title=fname[:80], current_track_pct=0, completed_tracks=max(0, done_tracks))
            m2 = re.search(r'\[download\]\s+([\d.]+)%', line)
            if m2:
                upd(current_track_pct=int(float(m2.group(1))))
            if "[Merger]" in line or "has already been downloaded" in line or "has already been recorded in the archive" in line:
                done_tracks += 1
                upd(completed_tracks=done_tracks, current_track_pct=100)
            
            # Check cancellation
            db = get_db()
            row = db.execute("SELECT status FROM download_queue WHERE id=?", (job_id,)).fetchone()
            db.close()
            if not row or row["status"] == "cancelled":
                try:
                    proc.terminate()
                except (ProcessLookupError, PermissionError):
                    pass
                return
        proc.wait()
        db = get_db()
        row = db.execute("SELECT status, total_tracks FROM download_queue WHERE id=?", (job_id,)).fetchone()
        db.close()
        if not row or row["status"] == "cancelled":
            return
        if proc.returncode == 0:
            total = row["total_tracks"] if row else 1
            upd(status="completed", current_track_pct=100, completed_tracks=total)
            _trigger_navidrome_scan()
        else:
            upd(status="failed", current_track_pct=0)
    except FileNotFoundError:
        upd(status="failed", current_track="yt-dlp not found")
    except Exception as e:
        db = get_db()
        row = db.execute("SELECT status FROM download_queue WHERE id=?", (job_id,)).fetchone()
        db.close()
        if row and row["status"] != "cancelled":
            upd(status="failed", current_track=str(e)[:120])

# Strict single-worker sequential download queue dispatcher (max 1 concurrent yt-dlp/ffmpeg)
_download_wake = threading.Event()
_download_worker_started = False
_download_worker_start_lock = threading.Lock()

def _process_next_queued_download() -> bool:
    """Claims and processes a single queued download job sequentially. Returns True if a job ran."""
    db = None
    row = None
    try:
        db = get_db()
        row = db.execute(
            "SELECT id, url, quality, format, embed_thumbnail, rate_limit, archive_skip "
            "FROM download_queue WHERE status='queued' ORDER BY id ASC LIMIT 1"
        ).fetchone()
    except Exception:
        row = None
    finally:
        if db:
            try:
                db.close()
            except Exception:
                pass
    if not row:
        return False

    fmt = row["format"] or row["quality"] or "mp3_320"
    emb = True if row["embed_thumbnail"] is None else bool(row["embed_thumbnail"])
    arch = True if row["archive_skip"] is None else bool(row["archive_skip"])
    rlim = row["rate_limit"] or ""
    _run_download(
        row["id"],
        row["url"],
        MUSIC_DIR,
        fmt,
        embed_thumbnail=emb,
        rate_limit=rlim,
        archive_skip=arch,
    )
    return True

def _download_worker_loop():
    while True:
        _download_wake.wait(timeout=30.0)
        _download_wake.clear()
        try:
            while _process_next_queued_download():
                pass
        except Exception:
            pass

def ensure_download_worker_started():
    global _download_worker_started
    if _download_worker_started:
        return
    with _download_worker_start_lock:
        if not _download_worker_started:
            threading.Thread(target=_download_worker_loop, daemon=True, name="dl-single-worker").start()
            _download_worker_started = True

def _notify_download_worker():
    ensure_download_worker_started()
    _download_wake.set()

# ── ROUTES: Web UI Pages (Ultra-Lightweight Preact SPA) ───────────────────────
@app.get("/", response_class=RedirectResponse)
async def index(request: Request):
    if request.session.get("admin_logged_in"):
        return RedirectResponse(url="/dashboard", status_code=303)
    return RedirectResponse(url="/login", status_code=303)

@app.get("/api/auth/me")
async def auth_me(request: Request):
    if request.session.get("admin_logged_in"):
        return {"authenticated": True, "username": request.session.get("admin_username", "admin")}
    return {"authenticated": False, "username": None}

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return serve_spa()

@app.post("/login")
async def login_submit(request: Request):
    ct = (request.headers.get("content-type") or "").lower()
    wants_json = "application/json" in ct or "application/json" in (request.headers.get("accept") or "").lower()
    if "application/json" in ct:
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        username = str(payload.get("username", ""))
        password = str(payload.get("password", ""))
    else:
        form = await request.form()
        username = str(form.get("username", ""))
        password = str(form.get("password", ""))

    ip = get_client_ip(request)
    ua = request.headers.get("User-Agent", "")[:200]
    u = username.strip()

    if is_ip_banned(ip):
        if wants_json:
            return JSONResponse({"ok": False, "error": "Your IP is temporarily banned."}, status_code=403)
        return serve_spa()

    db = get_db()
    admin = db.execute("SELECT * FROM admins WHERE username=?", (u,)).fetchone()

    if admin:
        stored_hash = admin["password_hash"]
        is_valid, upgraded_hash, was_upgraded = verify_and_migrate_password(password, stored_hash)

        if is_valid:
            if was_upgraded:
                db.execute("UPDATE admins SET password_hash=? WHERE id=?", (upgraded_hash, admin["id"]))
            db.execute("INSERT INTO login_attempts (ip, username, success, user_agent) VALUES (?,?,1,?)", (ip, u, ua))
            db.commit()
            db.close()

            request.session["admin_logged_in"] = True
            request.session["admin_username"] = u
            log_action(u, "Admin login", "auth", detail=f"IP {ip}", ip=ip)
            if wants_json:
                return JSONResponse({"ok": True, "username": u})
            return RedirectResponse(url="/dashboard", status_code=303)

    db.execute("INSERT INTO login_attempts (ip, username, success, user_agent) VALUES (?,?,0,?)", (ip, u or "unknown", ua))
    db.commit()
    db.close()

    fails = fail_count(ip)
    log_action("system", "Failed login", "auth", target=u, detail=f"IP {ip} attempt {fails}/3", status="warning", severity="warning", ip=ip)

    if fails >= 3:
        exp = (datetime.utcnow() + timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
        db = get_db()
        db.execute("INSERT OR REPLACE INTO ip_bans (ip, reason, expires_at) VALUES (?,?,?)", (ip, f"3 failed logins ('{u}')", exp))
        db.commit()
        db.close()
        log_action("system", "IP banned", "security", target=ip, detail=f"Expires {exp}", severity="critical", ip=ip)
        if wants_json:
            return JSONResponse({"ok": False, "error": "Too many attempts. IP banned 30 min."}, status_code=429)
        return serve_spa()

    if wants_json:
        return JSONResponse({"ok": False, "error": f"Invalid credentials. ({fails}/3 attempts)"}, status_code=401)
    return serve_spa()

@app.get("/logout")
async def logout(request: Request):
    u = request.session.get("admin_username", "unknown")
    log_action(u, "Admin logout", "auth")
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, admin: str = Depends(login_required)):
    return serve_spa()

@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    return serve_spa()

@app.post("/register")
async def register_submit(request: Request):
    ct = (request.headers.get("content-type") or "").lower()
    wants_json = "application/json" in ct or "application/json" in (request.headers.get("accept") or "").lower()
    if "application/json" in ct:
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        u = str(payload.get("username", "")).strip()
        e = str(payload.get("email", "")).strip()
    else:
        form = await request.form()
        u = str(form.get("username", "")).strip()
        e = str(form.get("email", "")).strip()

    if not u or not e:
        if wants_json:
            return JSONResponse({"ok": False, "error": "All fields required."}, status_code=400)
        return serve_spa()
    db = get_db()
    try:
        db.execute("INSERT INTO users (username, email) VALUES (?,?)", (u, e))
        db.commit()
        log_action("public", "New signup", "users", target=u, detail=f"Email: {e}", ip=get_client_ip(request))
        if wants_json:
            return JSONResponse({"ok": True})
        return serve_spa()
    except sqlite3.IntegrityError:
        if wants_json:
            return JSONResponse({"ok": False, "error": "Username or email exists."}, status_code=409)
        return serve_spa()
    finally:
        db.close()

# ── API: System Telemetry ─────────────────────────────────────────────────────
@app.get("/api/system")
async def api_system(admin: str = Depends(login_required)):
    cpu = psutil.cpu_percent(interval=0.2)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    temps = {}
    try:
        raw = psutil.sensors_temperatures()
        if raw:
            for name, entries in raw.items():
                if entries:
                    temps[name] = round(entries[0].current, 1)
    except Exception:
        pass

    battery = None
    try:
        bat = psutil.sensors_battery()
        if bat:
            battery = {
                "percent": round(bat.percent, 1),
                "charging": bat.power_plugged,
                "time_left": int(bat.secsleft) if bat.secsleft and bat.secsleft > 0 else None
            }
    except Exception:
        pass

    bk = os.path.ismount(BACKUP_MOUNT)
    bkd = None
    music_count = 0
    if bk:
        try:
            bu = psutil.disk_usage(BACKUP_MOUNT)
            bkd = {
                "total_gb": round(bu.total / 1e9, 1),
                "used_gb": round(bu.used / 1e9, 1),
                "free_gb": round(bu.free / 1e9, 1),
                "percent": bu.percent
            }
        except Exception:
            pass
        try:
            for _, _, files in os.walk(MUSIC_DIR):
                music_count += sum(1 for f in files if f.lower().endswith(('.mp3', '.flac', '.ogg', '.m4a', '.wav', '.aac')))
        except Exception:
            pass

    if cpu > 95:
        _log_sys("high_cpu", f"CPU critical: {cpu}%", severity="critical")
    if mem.percent > 90:
        _log_sys("high_ram", f"RAM critical: {mem.percent}%", severity="critical")
    if disk.percent > 90:
        _log_sys("low_disk", f"Root disk {disk.percent}% full", severity="critical")

    h, r = divmod(int(psutil.time.time() - psutil.boot_time()), 3600)
    m2, _ = divmod(r, 60)
    freq = None
    try:
        f = psutil.cpu_freq()
        freq = round(f.current / 1000, 2) if f else None
    except Exception:
        pass

    return {
        "cpu_percent": cpu,
        "cpu_count": psutil.cpu_count(),
        "cpu_freq_ghz": freq,
        "ram_used_gb": round(mem.used / 1e9, 1),
        "ram_total_gb": round(mem.total / 1e9, 1),
        "ram_percent": mem.percent,
        "disk_used_gb": round(disk.used / 1e9, 1),
        "disk_total_gb": round(disk.total / 1e9, 1),
        "disk_percent": disk.percent,
        "temperatures": temps,
        "battery": battery,
        "backup_mounted": bk,
        "disk_backup": bkd,
        "music_file_count": music_count,
        "uptime": f"{h}h {m2}m"
    }

@app.get("/api/system-events")
async def api_system_events(unresolved: int = 0, limit: int = 100, admin: str = Depends(login_required)):
    limit = max(1, min(int(limit or 100), 200))
    db = get_db()
    if unresolved:
        rows = db.execute(
            "SELECT * FROM system_events WHERE resolved=0 ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT * FROM system_events ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    db.close()
    return [dict(r) for r in rows]

@app.post("/api/system-events/{eid}/resolve")
async def api_resolve_system_event(eid: int, admin: str = Depends(login_required)):
    db = get_db()
    db.execute("UPDATE system_events SET resolved=1 WHERE id=?", (eid,))
    db.commit()
    db.close()
    log_action(admin, "System alert resolved", "system", target=f"event#{eid}")
    return {"ok": True, "id": eid}

@app.post("/api/system-events/resolve-all")
async def api_resolve_all_system_events(admin: str = Depends(login_required)):
    db = get_db()
    cur = db.execute("UPDATE system_events SET resolved=1 WHERE resolved=0")
    count = cur.rowcount
    db.commit()
    db.close()
    log_action(admin, "All system alerts resolved", "system", detail=f"Resolved {count} alert(s)")
    return {"ok": True, "resolved_count": count}

# ── API: Containers ───────────────────────────────────────────────────────────
@app.get("/api/containers")
async def api_containers(admin: str = Depends(login_required)):
    with _container_lock:
        if _container_cache:
            return _container_cache
    _refresh_container_stats()
    with _container_lock:
        return _container_cache

@app.post("/api/container/{name}/{action}")
async def api_container_action(name: str, action: str, request: Request, admin: str = Depends(login_required)):
    if action not in ("start", "stop", "restart"):
        return JSONResponse({"error": "Invalid action"}, status_code=400)
    if not docker_client:
        return JSONResponse({"error": "Docker unavailable"}, status_code=503)
    t0 = datetime.utcnow()
    try:
        c = docker_client.containers.get(name)
        prev = c.status
        getattr(c, action)()
        ms = int((datetime.utcnow() - t0).total_seconds() * 1000)
        log_action(admin, f"Container {action}", "containers", target=name, detail=f"Was: {prev}. Took {ms}ms.", ms=ms, ip=get_client_ip(request))
        _refresh_container_stats()
        return {"ok": True}
    except Exception as e:
        log_action(admin, f"Container {action} failed", "containers", target=name, detail=str(e), status="error", severity="error", ip=get_client_ip(request))
        return JSONResponse({"error": str(e)}, status_code=500)

@app.get("/api/container/{name}/logs")
async def api_container_logs(name: str, lines: int = 100, admin: str = Depends(login_required)):
    if not docker_client:
        return JSONResponse({"error": "Docker unavailable"}, status_code=503)
    try:
        c = docker_client.containers.get(name)
        logs = c.logs(tail=lines, timestamps=True).decode("utf-8", errors="replace")
        return {"logs": logs, "container": name, "status": c.status}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

# ── API: Users ────────────────────────────────────────────────────────────────
@app.get("/api/users")
async def api_users(admin: str = Depends(login_required)):
    db = get_db()
    rows = db.execute("SELECT * FROM users ORDER BY created_at DESC").fetchall()
    db.close()
    return [dict(r) for r in rows]

@app.get("/api/users/pending-count")
async def api_pending_count(admin: str = Depends(login_required)):
    db = get_db()
    r = db.execute("SELECT COUNT(*) as c FROM users WHERE status='pending'").fetchone()
    db.close()
    return {"count": r["c"] if r else 0}

@app.post("/api/users/{uid}/{action}")
async def api_user_action(uid: int, action: str, request: Request, admin: str = Depends(login_required)):
    if action not in ("approve", "block", "unblock", "delete"):
        return JSONResponse({"error": "Invalid action"}, status_code=400)
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not user:
        db.close()
        return JSONResponse({"error": "Not found"}, status_code=404)
    
    if action == "delete":
        db.execute("DELETE FROM users WHERE id=?", (uid,))
        detail = f"Deleted '{user['username']}'"
        sev = "warning"
    else:
        ns = {"approve": "active", "block": "blocked", "unblock": "active"}[action]
        db.execute("UPDATE users SET status=? WHERE id=?", (ns, uid))
        detail = f"'{user['username']}' -> {ns}"
        sev = "warning" if action in ("block", "delete") else "info"
    
    db.commit()
    db.close()
    log_action(admin, f"User {action}d", "users", target=user["username"], detail=detail, severity=sev, ip=get_client_ip(request))
    return {"ok": True}

@app.post("/api/users/sync-nextcloud")
async def api_sync_nextcloud(request: Request, admin: str = Depends(login_required)):
    if not docker_client:
        return JSONResponse({"error": "Docker unavailable"}, status_code=503)
    try:
        result = docker_client.containers.get("nextcloud").exec_run("php /var/www/html/occ user:list --output=json", user="www-data")
        ud = json.loads(result.output.decode("utf-8", errors="replace").strip())
        db = get_db()
        synced = 0
        for uid_str in ud.keys():
            if not db.execute("SELECT id FROM users WHERE username=?", (uid_str,)).fetchone():
                db.execute(
                    "INSERT INTO users (username, email, status, nextcloud_uid) VALUES (?,?,?,?)",
                    (uid_str, f"{uid_str}@nextcloud.local", "active", uid_str)
                )
                synced += 1
            else:
                db.execute("UPDATE users SET status='active', nextcloud_uid=? WHERE username=?", (uid_str, uid_str))
        db.commit()
        db.close()
        log_action(admin, "Nextcloud sync", "users", detail=f"{len(ud)} users synced ({synced} new)", ip=get_client_ip(request))
        return {"ok": True, "synced": synced, "total": len(ud)}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

# ── API: Backup ───────────────────────────────────────────────────────────────
@app.get("/api/backup/status")
async def api_backup_status(admin: str = Depends(login_required)):
    mounted = os.path.ismount(BACKUP_MOUNT)
    last_logs = []
    if os.path.exists(BACKUP_LOG):
        with open(BACKUP_LOG) as f:
            last_logs = [l.strip() for l in f.readlines()[-5:] if l.strip()]
    return {"mounted": mounted, "last_logs": last_logs}

@app.post("/api/backup/run")
async def api_backup_run(request: Request, admin: str = Depends(login_required)):
    if not os.path.exists(BACKUP_SCRIPT):
        log_action(admin, "Backup failed", "backup", detail=f"Script not found: {BACKUP_SCRIPT}", status="error", severity="error", ip=get_client_ip(request))
        return JSONResponse({"error": f"Script not found at {BACKUP_SCRIPT}"}, status_code=404)
    try:
        proc = subprocess.Popen(["bash", BACKUP_SCRIPT], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        log_action(admin, "Manual backup triggered", "backup", detail=f"PID {proc.pid}", ip=get_client_ip(request))
        return {"ok": True, "pid": proc.pid, "message": "Backup started"}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

# ── API: Music & Downloads ────────────────────────────────────────────────────
@app.get("/api/music/status")
async def api_music_status(request: Request, admin: str = Depends(login_required)):
    running = False
    if docker_client:
        try:
            running = (docker_client.containers.get("navidrome").status == "running")
        except Exception:
            pass

    resolved_url = resolve_navidrome_url(request)
    music_ok = os.path.isdir(MUSIC_DIR)

    audio_count = 0
    artists_count = 0
    albums_count = 0
    last_scan = "Never"

    # 1. Attempt reading Navidrome DB directly if accessible
    nav_db_paths = [
        os.environ.get("NAVIDROME_DB_PATH", ""),
        "/data/navidrome.db",
        "/navidrome/data/navidrome.db",
        os.path.join(BASE_DIR, "navidrome", "data", "navidrome.db"),
        os.path.join(os.path.dirname(BASE_DIR), "navidrome", "data", "navidrome.db"),
    ]
    db_found = False
    for p in nav_db_paths:
        if p and os.path.isfile(p):
            try:
                conn = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
                cur = conn.cursor()
                cur.execute("SELECT COUNT(*) FROM media_file")
                audio_count = int(cur.fetchone()[0])
                cur.execute("SELECT COUNT(*) FROM artist")
                artists_count = int(cur.fetchone()[0])
                cur.execute("SELECT COUNT(*) FROM album")
                albums_count = int(cur.fetchone()[0])
                cur.execute("SELECT value FROM property WHERE id IN ('lastScan', 'last_scan', 'lastScanTime') LIMIT 1")
                row = cur.fetchone()
                if row and row[0]:
                    last_scan = str(row[0])
                conn.close()
                db_found = True
                break
            except Exception:
                pass

    # 2. Directory structure estimation if DB not available or empty
    if not db_found and music_ok:
        try:
            artists_set = set()
            albums_set = set()
            latest_mtime = 0.0
            AUDIO_EXTS = ('.mp3', '.flac', '.ogg', '.m4a', '.wav', '.aac', '.opus', '.wma')

            for root, dirs, files in os.walk(MUSIC_DIR):
                dirs[:] = [d for d in dirs if not d.startswith(('.', '_'))]
                rel_path = os.path.relpath(root, MUSIC_DIR)
                audio_files = [f for f in files if f.lower().endswith(AUDIO_EXTS)]
                if audio_files:
                    audio_count += len(audio_files)
                    for f in audio_files:
                        try:
                            m = os.path.getmtime(os.path.join(root, f))
                            if m > latest_mtime:
                                latest_mtime = m
                        except Exception:
                            pass
                    if rel_path != ".":
                        parts = rel_path.split(os.sep)
                        artists_set.add(parts[0])
                        if len(parts) >= 2:
                            albums_set.add(f"{parts[0]}/{parts[1]}")
                        else:
                            albums_set.add(parts[0])

            artists_count = len(artists_set)
            albums_count = len(albums_set)
            if audio_count > 0 and artists_count == 0:
                artists_count = 1
                albums_count = 1

            if latest_mtime > 0:
                last_scan = datetime.fromtimestamp(latest_mtime).strftime("%Y-%m-%d %H:%M")
        except Exception:
            pass

    return {
        "navidrome_running": running,
        "navidrome_url": resolved_url,
        "music_dir": MUSIC_DIR,
        "music_dir_exists": music_ok,
        "music_file_count": audio_count,
        "artists_count": artists_count,
        "albums_count": albums_count,
        "last_scan": last_scan
    }

@app.post("/api/music/download")
async def api_music_download(request: Request, admin: str = Depends(login_required)):
    data = await request.json() or {}
    url = (data.get("url") or "").strip()
    raw_fmt = data.get("format") or data.get("quality")
    audio_fmt, _ = resolve_audio_format(raw_fmt)
    if not url or not url.startswith("http"):
        return JSONResponse({"error": "Please provide a valid URL"}, status_code=400)

    raw_emb = data.get("embed_thumbnail", True)
    embed_thumb = raw_emb if isinstance(raw_emb, bool) else str(raw_emb).strip().lower() not in ("false", "0", "no")
    raw_arch = data.get("archive_skip", True)
    archive_skip = raw_arch if isinstance(raw_arch, bool) else str(raw_arch).strip().lower() not in ("false", "0", "no")
    rate_limit = sanitize_rate_limit(str(data.get("rate_limit") or ""))

    platform = detect_platform(url)
    is_pl = is_playlist_url(url)
    db = get_db()
    existing = db.execute(
        "SELECT id, status FROM download_queue WHERE url=? AND status IN ('queued','downloading')",
        (url,)
    ).fetchone()
    if existing:
        db.close()
        return JSONResponse({"error": f"Already in queue (job #{existing['id']})"}, status_code=409)
    
    cur = db.execute(
        "INSERT INTO download_queue "
        "(url, platform, requested_by, is_playlist, quality, format, pid, embed_thumbnail, rate_limit, archive_skip) "
        "VALUES (?,?,?,?,?,?,0,?,?,?)",
        (url, platform, admin, 1 if is_pl else 0, audio_fmt, audio_fmt, 1 if embed_thumb else 0, rate_limit, 1 if archive_skip else 0)
    )
    job_id = cur.lastrowid
    db.commit()
    db.close()

    log_action(admin, "Download queued", "music", target=url[:80], detail=f"Platform: {platform}, Format: {audio_fmt}", ip=get_client_ip(request))
    _notify_download_worker()

    return {
        "ok": True,
        "job_id": job_id,
        "platform": platform,
        "is_playlist": is_pl,
        "format": audio_fmt,
        "embed_thumbnail": embed_thumb,
        "rate_limit": rate_limit,
        "archive_skip": archive_skip,
        "message": f"Download queued (sequential eco worker) — job #{job_id}"
    }

@app.get("/api/music/queue")
async def api_music_queue(admin: str = Depends(login_required)):
    db = get_db()
    rows = db.execute("SELECT * FROM download_queue ORDER BY created_at DESC LIMIT 60").fetchall()
    db.close()
    return [dict(r) for r in rows]

@app.post("/api/music/queue/{jid}/cancel")
async def api_cancel_download(jid: int, admin: str = Depends(login_required)):
    db = get_db()
    row = db.execute("SELECT id, pid, status FROM download_queue WHERE id=?", (jid,)).fetchone()
    if not row:
        db.close()
        return JSONResponse({"error": "Job not found"}, status_code=404)

    pid = row["pid"] or 0
    status_val = row["status"]
    
    if status_val in ("queued", "downloading"):
        if pid > 0:
            try:
                os.kill(pid, signal.SIGTERM)
                time.sleep(0.1)
                try:
                    os.kill(pid, 0)
                    sig_kill = getattr(signal, "SIGKILL", signal.SIGTERM)
                    os.kill(pid, sig_kill)
                except (ProcessLookupError, PermissionError):
                    pass
            except (ProcessLookupError, PermissionError):
                pass
        
        now = datetime.utcnow().isoformat()
        db.execute("UPDATE download_queue SET status='cancelled', completed_at=? WHERE id=?", (now, jid))
        db.commit()
    
    db.close()
    return {"ok": True}

@app.post("/api/music/queue/{jid}/retry")
async def api_retry_download(jid: int, admin: str = Depends(login_required)):
    db = get_db()
    row = db.execute("SELECT * FROM download_queue WHERE id=?", (jid,)).fetchone()
    if not row or row["status"] not in ("failed", "cancelled"):
        db.close()
        return JSONResponse({"error": "Not retryable"}, status_code=400)
    db.execute(
        "UPDATE download_queue SET status='queued', current_track_pct=0, completed_tracks=0, current_track=NULL, error=NULL, pid=0 WHERE id=?",
        (jid,)
    )
    db.commit()
    db.close()
    _notify_download_worker()
    return {"ok": True}

@app.post("/api/music/queue/{jid}/delete")
async def api_delete_download(jid: int, admin: str = Depends(login_required)):
    db = get_db()
    db.execute("DELETE FROM download_queue WHERE id=? AND status NOT IN ('downloading')", (jid,))
    db.commit()
    db.close()
    return {"ok": True}

@app.post("/api/music/listen")
async def api_log_listen(request: Request, admin: str = Depends(login_required)):
    d = await request.json() or {}
    now = datetime.utcnow()
    db = get_db()
    db.execute(
        "INSERT INTO listen_events "
        "(username, track_path, track_title, artist, genre, duration_sec, listened_sec, completed, hour_of_day, day_of_week, device) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (
            d.get("username", admin),
            d.get("track_path", ""),
            d.get("title", "Unknown"),
            d.get("artist", "Unknown"),
            d.get("genre", ""),
            d.get("duration_sec", 0),
            d.get("listened_sec", 0),
            1 if d.get("listened_sec", 0) >= d.get("duration_sec", 1) * 0.8 else 0,
            now.hour,
            now.weekday(),
            d.get("device", "web")
        )
    )
    db.commit()
    db.close()
    return {"ok": True}

def _get_maloja_conn():
    path = getattr(sys.modules.get(__name__), "MALOJA_DB_PATH", os.environ.get("MALOJA_DB_PATH", MALOJA_DB_PATH))
    if not path or not os.path.isfile(path):
        return None
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return conn
    except Exception:
        try:
            conn = sqlite3.connect(path)
            conn.row_factory = sqlite3.Row
            return conn
        except Exception:
            return None

def _is_valid_maloja_db(conn):
    if not conn:
        return False
    try:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        required = {"scrobbles", "tracks", "artists", "albums"}
        return required.issubset(set(tables))
    except Exception:
        return False

def _inspect_maloja_columns(conn):
    cols = {}
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    for tbl in ["scrobbles", "tracks", "artists", "albums", "trackartists"]:
        if tbl in tables:
            try:
                cols[tbl] = [r[1] for r in conn.execute(f"PRAGMA table_info({tbl})").fetchall()]
            except Exception:
                cols[tbl] = []
        else:
            cols[tbl] = []
    return cols, set(tables)

def _build_maloja_join_clauses(cols, tables):
    scrobble_time = "timestamp" if "timestamp" in cols["scrobbles"] else "time"
    scrobble_id_col = "id" if "id" in cols["scrobbles"] else scrobble_time
    scrobble_track = "track_id" if "track_id" in cols["scrobbles"] else "track"
    scrobble_user = "user" if "user" in cols["scrobbles"] else ("username" if "username" in cols["scrobbles"] else None)
    track_title = "title" if "title" in cols["tracks"] else "name"
    artist_name = "name" if "name" in cols["artists"] else "artist"

    has_direct_artist = "artist_id" in cols["tracks"] or "artist" in cols["tracks"]
    if "trackartists" in tables and not has_direct_artist:
        artist_join = "LEFT JOIN trackartists ta ON t.id = ta.track_id LEFT JOIN artists a ON ta.artist_id = a.id"
    else:
        track_artist_id = "artist_id" if "artist_id" in cols["tracks"] else "artist"
        artist_join = f"LEFT JOIN artists a ON t.{track_artist_id} = a.id"

    return {
        "scrobble_time": scrobble_time,
        "scrobble_id_col": scrobble_id_col,
        "scrobble_track": scrobble_track,
        "scrobble_user": scrobble_user,
        "track_title": track_title,
        "artist_name": artist_name,
        "artist_join": artist_join
    }

def sync_maloja_scrobbles(username: str = None) -> int:
    """Synchronize scrobbles from Maloja DB into local dashboard.db listen_events table."""
    m_conn = _get_maloja_conn()
    if not m_conn or not _is_valid_maloja_db(m_conn):
        if m_conn:
            m_conn.close()
        return 0

    try:
        cols, tables = _inspect_maloja_columns(m_conn)
        mc = _build_maloja_join_clauses(cols, tables)
        scrobble_user = mc["scrobble_user"]

        query = f"""
            SELECT s.{mc['scrobble_id_col']} as scrobble_id,
                   s.{mc['scrobble_time']} as scrobble_time,
                   t.{mc['track_title']} as title,
                   GROUP_CONCAT(DISTINCT a.{mc['artist_name']}) as artist
                   {f", s.{scrobble_user} as scrobble_user" if scrobble_user else ""}
            FROM scrobbles s
            LEFT JOIN tracks t ON s.{mc['scrobble_track']} = t.id
            {mc['artist_join']}
        """
        params = []
        if username and scrobble_user:
            query += f" WHERE LOWER(s.{scrobble_user}) = LOWER(?)"
            params.append(username)
        query += f" GROUP BY s.{mc['scrobble_id_col']}"

        rows = m_conn.execute(query, params).fetchall()

        db = get_db()
        existing_ids = set(
            r[0] for r in db.execute(
                "SELECT track_path FROM listen_events WHERE track_path LIKE 'maloja:%'"
            ).fetchall()
        )

        inserted_count = 0
        for r in rows:
            scrobble_id = r["scrobble_id"]
            ref_path = f"maloja:{scrobble_id}"
            if ref_path in existing_ids:
                continue

            raw_time = r["scrobble_time"]
            hour_of_day = 12
            day_of_week = 0
            created_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
            if raw_time is not None:
                try:
                    if isinstance(raw_time, (int, float)):
                        ts = float(raw_time)
                        if ts > 1e11:
                            ts /= 1000.0
                        dt = datetime.utcfromtimestamp(ts)
                    else:
                        dt = datetime.fromisoformat(str(raw_time).replace("Z", "+00:00"))
                    hour_of_day = dt.hour
                    day_of_week = dt.weekday()
                    created_at = dt.strftime("%Y-%m-%d %H:%M:%S")
                except Exception:
                    pass

            target_user = username or (r["scrobble_user"] if scrobble_user and r["scrobble_user"] else "admin")
            db.execute(
                """
                INSERT INTO listen_events 
                (username, track_path, track_title, artist, genre, duration_sec, listened_sec, completed, hour_of_day, day_of_week, device, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, 'maloja', ?)
                """,
                (
                    target_user,
                    ref_path,
                    r["title"] or "Unknown Track",
                    r["artist"] or "Unknown Artist",
                    "",
                    180,
                    180,
                    hour_of_day,
                    day_of_week,
                    created_at
                )
            )
            inserted_count += 1
            existing_ids.add(ref_path)

        db.commit()
        db.close()
        return inserted_count
    except Exception as e:
        logger.error(f"Error syncing Maloja scrobbles: {e}")
        return 0
    finally:
        m_conn.close()

def _compute_weighted_tracks_and_mixes(db, username: str = None, top_artists=None, top_tracks=None, top_genres=None, listening_clock=None) -> tuple:
    """
    Zero-AI deterministic scoring:
      - Recency decay: exp(-age_days / 30)
      - Completion weighting: 1.25 for completed plays vs 0.35 for skipped plays
      - Concrete Smart Mixes (Deep Cuts, Skip-Free Favorites, Current Hour Mood, Genre Mix)
    """
    now_dt = datetime.utcnow()
    user_where = "WHERE username=? " if username else "WHERE 1=1 "
    user_param = (username,) if username else ()

    rows = db.execute(
        f"SELECT track_path, track_title, artist, genre, completed, hour_of_day, created_at "
        f"FROM listen_events {user_where} ORDER BY id DESC LIMIT 2500",
        user_param,
    ).fetchall()

    track_stats: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        t_title = (r["track_title"] or "").strip() or "Unknown Track"
        t_artist = (r["artist"] or "").strip() or "Unknown Artist"
        t_path = (r["track_path"] or "").strip()
        key = f"{t_artist.lower()}::{t_title.lower()}"

        age_days = 0.0
        raw_ts = r["created_at"]
        if raw_ts:
            try:
                dt = datetime.fromisoformat(str(raw_ts).replace("Z", "+00:00").replace("+00:00", ""))
                age_days = max(0.0, (now_dt - dt).total_seconds() / 86400.0)
            except Exception:
                age_days = 0.0

        decay = math.exp(-age_days / 30.0)
        comp = 1 if r["completed"] else 0
        event_score = decay * (1.25 if comp else 0.35)

        entry = track_stats.get(key)
        if not entry:
            entry = {
                "title": t_title,
                "track_title": t_title,
                "artist": t_artist,
                "track_path": t_path,
                "genre": (r["genre"] or "").strip(),
                "plays": 0,
                "completions": 0,
                "weighted_score": 0.0,
                "min_age_days": age_days,
                "hours": set(),
            }
            track_stats[key] = entry

        entry["plays"] += 1
        entry["completions"] += comp
        entry["weighted_score"] += event_score
        if age_days < entry["min_age_days"]:
            entry["min_age_days"] = age_days
        if t_path and not t_path.startswith("maloja:") and (not entry["track_path"] or entry["track_path"].startswith("maloja:")):
            entry["track_path"] = t_path
        if r["hour_of_day"] is not None:
            entry["hours"].add(int(r["hour_of_day"]))

    scored_list = list(track_stats.values())
    for item in scored_list:
        item["weighted_score"] = round(item["weighted_score"], 2)
        item["completion_rate"] = round(item["completions"] / max(1, item["plays"]), 2)

    score_lookup = {f"{x['artist'].lower()}::{x['title'].lower()}": x["weighted_score"] for x in scored_list}
    if top_tracks:
        for tt in top_tracks:
            k = f"{(tt.get('artist') or 'Unknown Artist').strip().lower()}::{(tt.get('title') or tt.get('track_title') or '').strip().lower()}"
            if k in score_lookup:
                tt["weighted_score"] = score_lookup[k]
            else:
                tt["weighted_score"] = round(float(tt.get("plays") or 0), 2)

    def _pack(items, limit=15):
        return [
            {
                "title": x["title"],
                "artist": x["artist"],
                "track_path": x["track_path"],
                "plays": x["plays"],
                "weighted_score": x["weighted_score"],
            }
            for x in items[:limit]
        ]

    mixes = []
    # 1. Rediscover Deep Cuts: played >= 2 times, untouched for > 21 days
    deep_cuts = sorted(
        [x for x in scored_list if x["plays"] >= 2 and x["min_age_days"] >= 21.0],
        key=lambda x: (x["completions"], x["plays"]),
        reverse=True,
    )
    if deep_cuts:
        mixes.append({
            "name": "Rediscover Deep Cuts",
            "reason": f"{len(deep_cuts)} favorites not played in 3+ weeks",
            "based_on": "deep_cuts",
            "tracks": _pack(deep_cuts),
        })

    # 2. Skip-Free Favorites: >= 80% completion rate, ranked by weighted_score
    skip_free = sorted(
        [x for x in scored_list if x["completion_rate"] >= 0.8 and x["completions"] >= 1],
        key=lambda x: x["weighted_score"],
        reverse=True,
    )
    if skip_free:
        mixes.append({
            "name": "Skip-Free Favorites",
            "reason": f"Highest completion tracks ({len(skip_free)} matches)",
            "based_on": "skip_free",
            "tracks": _pack(skip_free),
        })

    # 3. Current Hour Mood Mix
    cur_h = now_dt.hour
    if 6 <= cur_h < 12:
        mood_name, h_set = "Morning Energy Mix", set(range(6, 12))
    elif 12 <= cur_h < 17:
        mood_name, h_set = "Afternoon Focus Mix", set(range(12, 17))
    elif 17 <= cur_h < 21:
        mood_name, h_set = "Evening Wind-Down Mix", set(range(17, 21))
    else:
        mood_name, h_set = "Late Night Session", {21, 22, 23, 0, 1, 2, 3, 4, 5}

    mood_tracks = sorted(
        [x for x in scored_list if x["hours"].intersection(h_set)],
        key=lambda x: x["weighted_score"],
        reverse=True,
    )
    if mood_tracks:
        mixes.append({
            "name": mood_name,
            "reason": f"Matched to your {cur_h:02d}:00 listening window",
            "based_on": "mood_hour",
            "tracks": _pack(mood_tracks),
        })

    # 4. Top Genre Discovery Mix
    if top_genres:
        g_name = top_genres[0]["genre"]
        g_tracks = sorted(
            [x for x in scored_list if x["genre"].lower() == g_name.lower()],
            key=lambda x: x["weighted_score"],
            reverse=True,
        )
        if g_tracks:
            mixes.append({
                "name": f"{g_name} Mix",
                "reason": f"Weighted by recency & completion in {g_name}",
                "based_on": "top_genre",
                "tracks": _pack(g_tracks),
            })

    return scored_list, mixes

def get_maloja_data(username: str = None) -> dict:
    """Fetch analytics either directly from Maloja's SQLite tables or fallback to dashboard.db listen_events."""
    m_conn = _get_maloja_conn()
    if m_conn and _is_valid_maloja_db(m_conn):
        try:
            cols, tables = _inspect_maloja_columns(m_conn)
            mc = _build_maloja_join_clauses(cols, tables)
            scrobble_user = mc["scrobble_user"]
            has_genre = "genre" in cols["tracks"] or "genre" in cols["artists"] or "genre" in cols["albums"]
            genre_col = "t.genre" if "genre" in cols["tracks"] else ("a.genre" if "genre" in cols["artists"] else ("alb.genre" if "genre" in cols["albums"] else "''"))

            user_clause = ""
            params = []
            if username and scrobble_user:
                user_clause = f" WHERE LOWER(s.{scrobble_user}) = LOWER(?)"
                params.append(username)

            total_row = m_conn.execute(f"SELECT COUNT(*) as c FROM scrobbles s{user_clause}", params).fetchone()
            total_scrobbles = total_row["c"] if total_row else 0

            uniq_row = m_conn.execute(f"SELECT COUNT(DISTINCT s.{mc['scrobble_track']}) as c FROM scrobbles s{user_clause}", params).fetchone()
            unique_tracks = uniq_row["c"] if uniq_row else 0

            top_artists_rows = m_conn.execute(f"""
                SELECT a.{mc['artist_name']} as name, COUNT(DISTINCT s.{mc['scrobble_id_col']}) as plays, COUNT(DISTINCT s.{mc['scrobble_id_col']}) as completions
                FROM scrobbles s
                JOIN tracks t ON s.{mc['scrobble_track']} = t.id
                {mc['artist_join']}
                {user_clause} {"AND" if user_clause else "WHERE"} a.{mc['artist_name']} IS NOT NULL AND a.{mc['artist_name']} != ''
                GROUP BY a.{mc['artist_name']}
                ORDER BY plays DESC, completions DESC
                LIMIT 10
            """, params).fetchall()
            top_artists = [
                {"name": r["name"], "artist": r["name"], "plays": r["plays"], "completions": r["completions"]}
                for r in top_artists_rows
            ]

            top_tracks_rows = m_conn.execute(f"""
                SELECT t.{mc['track_title']} as title, COALESCE(GROUP_CONCAT(DISTINCT a.{mc['artist_name']}), 'Unknown Artist') as artist,
                       COUNT(DISTINCT s.{mc['scrobble_id_col']}) as plays, COUNT(DISTINCT s.{mc['scrobble_id_col']}) as completions
                FROM scrobbles s
                JOIN tracks t ON s.{mc['scrobble_track']} = t.id
                {mc['artist_join']}
                {user_clause}
                GROUP BY s.{mc['scrobble_track']}
                ORDER BY plays DESC, completions DESC
                LIMIT 20
            """, params).fetchall()
            top_tracks = [
                {"title": r["title"], "track_title": r["title"], "artist": r["artist"], "plays": r["plays"], "completions": r["completions"]}
                for r in top_tracks_rows
            ]

            top_genres = []
            if has_genre:
                try:
                    genre_rows = m_conn.execute(f"""
                        SELECT {genre_col} as genre, COUNT(DISTINCT s.{mc['scrobble_id_col']}) as plays
                        FROM scrobbles s
                        JOIN tracks t ON s.{mc['scrobble_track']} = t.id
                        {mc['artist_join']}
                        LEFT JOIN albums alb ON t.album_id = alb.id
                        {user_clause} {"AND" if user_clause else "WHERE"} {genre_col} != ''
                        GROUP BY genre
                        ORDER BY plays DESC
                        LIMIT 5
                    """, params).fetchall()
                    top_genres = [{"genre": r["genre"], "plays": r["plays"]} for r in genre_rows]
                except Exception:
                    top_genres = []

            # Listening clock / time patterns
            time_rows = m_conn.execute(f"""
                SELECT s.{mc['scrobble_time']} as scrobble_time
                FROM scrobbles s
                {user_clause}
            """, params).fetchall()

            hour_counts = [0] * 24
            for r in time_rows:
                raw_time = r["scrobble_time"]
                if raw_time is not None:
                    try:
                        if isinstance(raw_time, (int, float)):
                            ts = float(raw_time)
                            if ts > 1e11:
                                ts /= 1000.0
                            h = datetime.utcfromtimestamp(ts).hour
                        else:
                            h = datetime.fromisoformat(str(raw_time).replace("Z", "+00:00")).hour
                        hour_counts[h] += 1
                    except Exception:
                        pass

            time_patterns = [{"hour_of_day": h, "hour": h, "plays": hour_counts[h]} for h in range(24)]
            listening_clock = sorted([p for p in time_patterns if p["plays"] > 0], key=lambda x: x["plays"], reverse=True)

            recent_rows = m_conn.execute(f"""
                SELECT t.{mc['track_title']} as title, COALESCE(GROUP_CONCAT(DISTINCT a.{mc['artist_name']}), 'Unknown Artist') as artist, s.{mc['scrobble_time']} as time
                FROM scrobbles s
                JOIN tracks t ON s.{mc['scrobble_track']} = t.id
                {mc['artist_join']}
                {user_clause}
                GROUP BY s.{mc['scrobble_id_col']}
                ORDER BY s.{mc['scrobble_time']} DESC
                LIMIT 10
            """, params).fetchall()
            recent_plays = [
                {"title": r["title"], "track_title": r["title"], "artist": r["artist"], "time": str(r["time"])}
                for r in recent_rows
            ]

            suggestions = []
            if top_artists:
                suggestions.append({
                    "name": f"More from {top_artists[0]['name']}",
                    "reason": f"{top_artists[0]['plays']} plays recorded",
                    "based_on": "top_artist"
                })
            if listening_clock:
                ph = listening_clock[0]["hour_of_day"]
                mood = ("Morning energy" if 6 <= ph < 12 else
                        "Afternoon focus" if 12 <= ph < 17 else
                        "Evening wind-down" if 17 <= ph < 21 else "Late night session")
                suggestions.append({
                    "name": mood,
                    "reason": f"You listen most around {ph:02d}:00",
                    "based_on": "time_pattern"
                })
            if top_tracks:
                suggestions.append({
                    "name": f"Heavy Rotation: {top_tracks[0]['title']}",
                    "reason": f"Your top track with {top_tracks[0]['plays']} plays",
                    "based_on": "top_track"
                })
            if top_genres:
                suggestions.append({
                    "name": f"{top_genres[0]['genre']} Mix",
                    "reason": f"{top_genres[0]['plays']} plays in this genre",
                    "based_on": "top_genre"
                })

            top_artist_name = top_artists[0]["name"] if top_artists else ""
            smart_mixes = []
            try:
                ldb = get_db()
                _, smart_mixes = _compute_weighted_tracks_and_mixes(ldb, username, top_artists, top_tracks, top_genres, listening_clock)
                ldb.close()
            except Exception:
                smart_mixes = []

            return {
                "total_scrobbles": total_scrobbles,
                "unique_tracks": unique_tracks,
                "top_artist": top_artist_name,
                "top_artists": top_artists,
                "top_genres": top_genres,
                "top_tracks": top_tracks,
                "listening_clock": listening_clock,
                "time_patterns": time_patterns,
                "recent_plays": recent_plays,
                "suggestions": suggestions,
                "smart_mixes": smart_mixes or suggestions,
                "collaborative": []
            }
        except Exception as e:
            logger.error(f"Error querying Maloja database: {e}")
        finally:
            m_conn.close()

    # Graceful fallback to dashboard.db listen_events
    db = get_db()
    user_param = (username,) if username else ()
    user_where = "WHERE username=? " if username else "WHERE 1=1 "

    tot_r = db.execute(f"SELECT COUNT(*) as c FROM listen_events {user_where}", user_param).fetchone()
    total_scrobbles = tot_r["c"] if tot_r else 0

    uniq_r = db.execute(f"SELECT COUNT(DISTINCT track_path) as c FROM listen_events {user_where}", user_param).fetchone()
    unique_tracks = uniq_r["c"] if uniq_r else 0

    top_artists_rows = db.execute(
        f"SELECT artist, COUNT(*) as plays, SUM(completed) as completions "
        f"FROM listen_events {user_where} AND artist!='' "
        f"GROUP BY artist ORDER BY completions DESC, plays DESC LIMIT 10",
        user_param
    ).fetchall()
    top_artists = [
        {"name": r["artist"], "artist": r["artist"], "plays": r["plays"], "completions": r["completions"] or 0}
        for r in top_artists_rows
    ]

    top_genres_rows = db.execute(
        f"SELECT genre, COUNT(*) as plays FROM listen_events {user_where} AND genre!='' "
        f"GROUP BY genre ORDER BY plays DESC LIMIT 5",
        user_param
    ).fetchall()
    top_genres = [{"genre": r["genre"], "plays": r["plays"]} for r in top_genres_rows]

    time_patt_rows = db.execute(
        f"SELECT hour_of_day, COUNT(*) as plays FROM listen_events {user_where} "
        f"GROUP BY hour_of_day ORDER BY plays DESC LIMIT 24",
        user_param
    ).fetchall()
    hour_map = {r["hour_of_day"]: r["plays"] for r in time_patt_rows}
    time_patterns = [{"hour_of_day": h, "hour": h, "plays": hour_map.get(h, 0)} for h in range(24)]
    listening_clock = sorted([p for p in time_patterns if p["plays"] > 0], key=lambda x: x["plays"], reverse=True)

    top_tracks_rows = db.execute(
        f"SELECT track_title, artist, COUNT(*) as plays, SUM(completed) as completions "
        f"FROM listen_events {user_where} "
        f"GROUP BY track_path ORDER BY completions DESC, plays DESC LIMIT 20",
        user_param
    ).fetchall()
    top_tracks = [
        {"title": r["track_title"], "track_title": r["track_title"], "artist": r["artist"], "plays": r["plays"], "completions": r["completions"] or 0}
        for r in top_tracks_rows
    ]

    recent_rows = db.execute(
        f"SELECT track_title as title, artist, created_at as time FROM listen_events {user_where} ORDER BY id DESC LIMIT 10",
        user_param
    ).fetchall()
    recent_plays = [dict(r) for r in recent_rows]

    collab = []
    if top_artists and username:
        al = [r["name"] for r in top_artists[:3]]
        ph = ",".join("?" * len(al))
        similar = db.execute(
            f"SELECT username, COUNT(*) as shared FROM listen_events "
            f"WHERE artist IN ({ph}) AND username!=? "
            f"GROUP BY username ORDER BY shared DESC LIMIT 5",
            (*al, username)
        ).fetchall()
        our = set(r["track_path"] for r in db.execute("SELECT DISTINCT track_path FROM listen_events WHERE username=?", (username,)).fetchall())
        for su in similar:
            faves = db.execute(
                "SELECT track_title, artist, track_path, COUNT(*) as plays FROM listen_events "
                "WHERE username=? AND completed=1 GROUP BY track_path ORDER BY plays DESC LIMIT 10",
                (su["username"],)
            ).fetchall()
            collab.extend([dict(r) for r in faves if r["track_path"] not in our][:3])

    suggestions = []
    if top_artists:
        suggestions.append({
            "name": f"More from {top_artists[0]['name']}",
            "reason": f"{top_artists[0]['completions']} completed plays",
            "based_on": "top_artist"
        })
    if listening_clock:
        ph = listening_clock[0]["hour_of_day"]
        mood = ("Morning energy" if 6 <= ph < 12 else
                "Afternoon focus" if 12 <= ph < 17 else
                "Evening wind-down" if 17 <= ph < 21 else "Late night session")
        suggestions.append({
            "name": mood,
            "reason": f"You listen most around {ph:02d}:00",
            "based_on": "time_pattern"
        })
    if top_genres:
        suggestions.append({
            "name": f"{top_genres[0]['genre']} Mix",
            "reason": f"{top_genres[0]['plays']} plays in this genre",
            "based_on": "top_genre"
        })

    _, smart_mixes = _compute_weighted_tracks_and_mixes(db, username, top_artists, top_tracks, top_genres, listening_clock)
    db.close()

    top_artist_name = top_artists[0]["name"] if top_artists else ""

    return {
        "total_scrobbles": total_scrobbles,
        "unique_tracks": unique_tracks,
        "top_artist": top_artist_name,
        "top_artists": top_artists,
        "top_genres": top_genres,
        "top_tracks": top_tracks,
        "listening_clock": listening_clock,
        "time_patterns": time_patterns,
        "recent_plays": recent_plays,
        "suggestions": suggestions,
        "smart_mixes": smart_mixes or suggestions,
        "collaborative": collab[:6]
    }

@app.get("/api/music/recommendations/{username}")
async def api_recommendations(username: str, admin: str = Depends(login_required)):
    try:
        sync_maloja_scrobbles(username)
    except Exception:
        pass

    data = get_maloja_data(username)
    return {
        "username": username,
        "total_scrobbles": data.get("total_scrobbles", 0),
        "top_artists": data.get("top_artists", []),
        "top_genres": data.get("top_genres", []),
        "top_tracks": data.get("top_tracks", []),
        "listening_clock": data.get("listening_clock", []),
        "time_pattern": data.get("time_patterns", []),
        "time_patterns": data.get("time_patterns", []),
        "collaborative": data.get("collaborative", []),
        "suggestions": data.get("suggestions", []),
        "playlist_suggestions": data.get("suggestions", []),
        "smart_mixes": data.get("smart_mixes", data.get("suggestions", [])),
    }

def _resolve_m3u_track_entry(track: dict, music_dir: str, playlist_dir: str) -> str:
    """Resolves a track dict to a safe relative audio path in MUSIC_DIR if available."""
    raw_path = str(track.get("track_path") or "").strip()
    title = str(track.get("title") or track.get("track_title") or "").strip()
    artist = str(track.get("artist") or "").strip()

    if raw_path and not raw_path.startswith("maloja:"):
        cand = raw_path if os.path.isabs(raw_path) else os.path.join(music_dir, raw_path)
        if os.path.isfile(cand):
            try:
                return os.path.relpath(cand, playlist_dir)
            except Exception:
                return cand

    # Best-effort scan of MUSIC_DIR filenames matching title/artist
    if os.path.isdir(music_dir) and (title or artist):
        AUDIO_EXTS = (".mp3", ".flac", ".opus", ".m4a", ".wav", ".ogg", ".aac")
        t_low = title.lower()
        a_low = artist.lower()
        for root, dirs, files in os.walk(music_dir):
            dirs[:] = [d for d in dirs if not d.startswith(("_", "."))]
            for fn in files:
                if not fn.lower().endswith(AUDIO_EXTS):
                    continue
                f_low = fn.lower()
                if t_low and t_low in f_low and (not a_low or a_low in f_low or a_low == "unknown artist"):
                    full = os.path.join(root, fn)
                    try:
                        return os.path.relpath(full, playlist_dir)
                    except Exception:
                        return full
    return raw_path or f"{artist} - {title}".strip(" -")

@app.post("/api/music/playlists/export-m3u")
async def api_export_m3u_playlist(request: Request, admin: str = Depends(login_required)):
    d = await request.json() or {}
    raw_name = str(d.get("name") or "Smart Mix").strip()
    safe_name = re.sub(r"[^a-zA-Z0-9._ -]+", "_", raw_name).strip(" .") or "Smart_Mix"
    safe_name = safe_name.replace("..", "_")[:80]
    tracks = d.get("tracks") or []
    username = str(d.get("username") or admin).strip()

    pl_dir = os.path.abspath(PLAYLIST_DIR or os.path.join(MUSIC_DIR, "_playlists"))
    os.makedirs(pl_dir, exist_ok=True)
    out_file = os.path.abspath(os.path.join(pl_dir, f"{safe_name}.m3u"))
    if os.path.dirname(out_file) != pl_dir:
        return JSONResponse({"error": "Invalid playlist path"}, status_code=400)

    lines = ["#EXTM3U", f"#PLAYLIST:{raw_name}"]
    count = 0
    for tr in tracks:
        if not isinstance(tr, dict):
            continue
        title = str(tr.get("title") or tr.get("track_title") or "Unknown").strip()
        artist = str(tr.get("artist") or "Unknown").strip()
        entry = _resolve_m3u_track_entry(tr, MUSIC_DIR, pl_dir)
        if entry:
            lines.append(f"#EXTINF:-1,{artist} - {title}")
            lines.append(entry)
            count += 1

    with open(out_file, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    db = get_db()
    db.execute(
        "INSERT INTO user_playlists (username, name, tracks, auto_generated) VALUES (?,?,?,1)",
        (username, raw_name, json.dumps(tracks)),
    )
    db.commit()
    db.close()

    log_action(admin, "Exported M3U playlist", "music", target=safe_name, detail=f"{count} tracks -> {out_file}", ip=get_client_ip(request))
    return {"ok": True, "filename": f"{safe_name}.m3u", "path": out_file, "track_count": count}

@app.post("/api/music/recommendations/queue-track")
async def api_queue_recommended_track(request: Request, admin: str = Depends(login_required)):
    d = await request.json() or {}
    title = str(d.get("title") or "").strip()
    artist = str(d.get("artist") or "").strip()
    if not title:
        return JSONResponse({"error": "Track title is required"}, status_code=400)

    raw_fmt = d.get("format") or d.get("quality") or "mp3_320"
    audio_fmt, _ = resolve_audio_format(raw_fmt)
    query = f"{artist} - {title}".strip(" -")
    search_url = f"ytsearch1:{query} audio"

    db = get_db()
    existing = db.execute(
        "SELECT id FROM download_queue WHERE url=? AND status IN ('queued','downloading')",
        (search_url,),
    ).fetchone()
    if existing:
        db.close()
        return JSONResponse({"error": f"Already in queue (job #{existing['id']})"}, status_code=409)

    cur = db.execute(
        "INSERT INTO download_queue (url, title, platform, requested_by, is_playlist, quality, format, pid, embed_thumbnail, archive_skip) "
        "VALUES (?, ?, 'youtube_search', ?, 0, ?, ?, 0, 1, 1)",
        (search_url, query[:80], admin, audio_fmt, audio_fmt),
    )
    job_id = cur.lastrowid
    db.commit()
    db.close()

    log_action(admin, "Recommended track queued", "music", target=query[:80], detail=f"Format: {audio_fmt}", ip=get_client_ip(request))
    _notify_download_worker()
    return {"ok": True, "job_id": job_id, "url": search_url, "title": query, "format": audio_fmt}

@app.post("/api/music/playlists")
async def api_create_playlist(request: Request, admin: str = Depends(login_required)):
    d = await request.json() or {}
    db = get_db()
    cur = db.execute(
        "INSERT INTO user_playlists (username, name, tracks, auto_generated) VALUES (?,?,?,?)",
        (
            d.get("username", admin),
            d.get("name", "New Playlist"),
            json.dumps(d.get("tracks", [])),
            1 if d.get("auto_generated") else 0
        )
    )
    pid = cur.lastrowid
    db.commit()
    db.close()
    return {"ok": True, "playlist_id": pid}

@app.get("/api/music/stats")
async def api_music_stats(admin: str = Depends(login_required)):
    try:
        sync_maloja_scrobbles()
    except Exception as e:
        logger.debug(f"Maloja scrobble sync skipped: {e}")

    try:
        data = get_maloja_data()
    except Exception as e:
        logger.error(f"Error fetching maloja data: {e}")
        data = {}

    db = get_db()
    try:
        unique_users = db.execute("SELECT COUNT(DISTINCT username) as c FROM listen_events").fetchone()["c"]
        active_today = db.execute("SELECT COUNT(DISTINCT username) as c FROM listen_events WHERE date(created_at)=date('now')").fetchone()["c"]
    finally:
        db.close()

    total = data.get("total_scrobbles", 0)
    top_artists = data.get("top_artists", [])
    top_artist = data.get("top_artist", "")
    top_tracks = data.get("top_tracks", [])
    recent_plays = data.get("recent_plays", [])

    return {
        "total_plays": total,
        "total_scrobbles": total,
        "unique_tracks": data.get("unique_tracks", 0),
        "unique_users": max(unique_users, 1 if total > 0 else 0),
        "active_today": max(active_today, 1 if total > 0 else 0),
        "top_artist": top_artist,
        "top_artists": top_artists,
        "top_tracks": top_tracks,
        "recent_plays": recent_plays
    }

# ── API: Activity Logs ────────────────────────────────────────────────────────
@app.get("/api/logs")
async def api_logs(
    q: str = "",
    category: str = "",
    severity: str = "",
    limit: int = 100,
    offset: int = 0,
    admin: str = Depends(login_required)
):
    db = get_db()
    sql = "SELECT * FROM activity_log WHERE 1=1"
    params = []
    if q and q.strip():
        sql += " AND (actor LIKE ? OR action LIKE ? OR target LIKE ? OR detail LIKE ?)"
        params += [f"%{q.strip()}%"] * 4
    if category and category.strip() and category.strip().lower() != "all":
        sql += " AND lower(category)=lower(?)"
        params.append(category.strip())
    if severity and severity.strip() and severity.strip().lower() != "all":
        sql += " AND lower(severity)=lower(?)"
        params.append(severity.strip())
    sql += " ORDER BY timestamp DESC, id DESC LIMIT ? OFFSET ?"
    params.extend([max(1, limit), max(0, offset)])
    rows = db.execute(sql, params).fetchall()
    db.close()
    return [dict(r) for r in rows]

@app.get("/api/logs/stats")
async def api_log_stats(admin: str = Depends(login_required)):
    db = get_db()
    total_row = db.execute("SELECT COUNT(*) as c FROM activity_log").fetchone()
    total = total_row["c"] if total_row else 0

    by_cat_rows = db.execute("SELECT category, COUNT(*) as c FROM activity_log GROUP BY category").fetchall()
    by_category = {r["category"]: r["c"] for r in by_cat_rows}

    by_sev_rows = db.execute("SELECT severity, COUNT(*) as c FROM activity_log GROUP BY severity").fetchall()
    by_severity = {r["severity"]: r["c"] for r in by_sev_rows}

    err_row = db.execute(
        "SELECT COUNT(*) as c FROM activity_log WHERE severity IN ('error', 'critical') AND (timestamp >= datetime('now', '-24 hours') OR timestamp IS NULL)"
    ).fetchone()
    recent_errors = err_row["c"] if err_row else 0

    warnings = by_severity.get("warning", 0)
    errors = by_severity.get("error", 0) + by_severity.get("critical", 0)
    today_row = db.execute("SELECT COUNT(*) as c FROM activity_log WHERE date(timestamp)=date('now')").fetchone()
    today = today_row["c"] if today_row else 0
    unresolved_row = db.execute("SELECT COUNT(*) as c FROM system_events WHERE resolved=0").fetchone()
    unresolved = unresolved_row["c"] if unresolved_row else 0
    db.close()

    return {
        "total": total,
        "by_category": by_category,
        "by_severity": by_severity,
        "recent_errors": recent_errors,
        "errors": errors,
        "warnings": warnings,
        "today": today,
        "unresolved_events": unresolved
    }

# ── API: Security & Bans ──────────────────────────────────────────────────────
@app.get("/api/bans")
async def api_bans(admin: str = Depends(login_required)):
    db = get_db()
    rows = db.execute("SELECT * FROM ip_bans ORDER BY banned_at DESC").fetchall()
    db.close()
    return [dict(r) for r in rows]

@app.post("/api/bans/add")
@app.post("/api/bans")
async def api_bans_add(request: Request, admin: str = Depends(login_required)):
    data = {}
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            data = await request.json() or {}
        except Exception:
            data = {}
    elif "application/x-www-form-urlencoded" in content_type or "multipart/form-data" in content_type:
        try:
            form = await request.form()
            data = dict(form)
        except Exception:
            data = {}
    else:
        try:
            data = await request.json() or {}
        except Exception:
            try:
                form = await request.form()
                data = dict(form)
            except Exception:
                data = {}

    ip = str(data.get("ip") or "").strip()
    if not ip:
        return JSONResponse({"error": "Invalid IP address format"}, status_code=400)

    try:
        ipaddress.ip_address(ip)
    except ValueError:
        return JSONResponse({"error": "Invalid IP address format"}, status_code=400)

    raw_reason = data.get("reason")
    if raw_reason is not None and str(raw_reason).strip():
        reason = str(raw_reason).strip()
    else:
        reason = "Manual admin ban"

    if "duration_hours" in data and data["duration_hours"] is None:
        duration_hours = 0
    elif "duration_hours" in data and str(data["duration_hours"]).strip() != "":
        try:
            duration_hours = int(data["duration_hours"])
        except (ValueError, TypeError):
            duration_hours = 24
    else:
        duration_hours = 24

    if duration_hours <= 0:
        expires_at = None
    else:
        expires_dt = datetime.utcnow() + timedelta(hours=duration_hours)
        expires_at = expires_dt.strftime("%Y-%m-%d %H:%M:%S")

    db = get_db()
    db.execute(
        "INSERT INTO ip_bans (ip, reason, banned_at, expires_at) VALUES (?, ?, datetime('now'), ?) "
        "ON CONFLICT(ip) DO UPDATE SET reason=excluded.reason, banned_at=datetime('now'), expires_at=excluded.expires_at",
        (ip, reason, expires_at)
    )
    db.commit()
    db.close()

    log_action(
        actor=admin,
        action="IP banned",
        category="security",
        target=ip,
        detail=f"Reason: {reason}, Expires: {expires_at or 'Permanent'}",
        severity="warning",
        ip=get_client_ip(request)
    )

    return {"ok": True, "ip": ip, "reason": reason, "expires_at": expires_at}

@app.post("/api/bans/{bid}/unban")
async def api_unban(bid: int, request: Request, admin: str = Depends(login_required)):
    db = get_db()
    row = db.execute("SELECT ip FROM ip_bans WHERE id=?", (bid,)).fetchone()
    if row:
        db.execute("DELETE FROM ip_bans WHERE id=?", (bid,))
        db.commit()
        log_action(admin, "IP unbanned", "security", target=row["ip"], ip=get_client_ip(request))
    db.close()
    return {"ok": True}

@app.post("/api/bans/unban")
async def api_unban_post(request: Request, admin: str = Depends(login_required)):
    data = {}
    try:
        data = await request.json() or {}
    except Exception:
        try:
            data = dict(await request.form())
        except Exception:
            data = {}
    ip = str(data.get("ip") or "").strip()
    bid = data.get("id") or data.get("bid")
    db = get_db()
    target_ip = None
    if ip:
        target_ip = ip
        db.execute("DELETE FROM ip_bans WHERE ip=?", (ip,))
        db.commit()
    elif bid:
        row = db.execute("SELECT ip FROM ip_bans WHERE id=?", (bid,)).fetchone()
        if row:
            target_ip = row["ip"]
            db.execute("DELETE FROM ip_bans WHERE id=?", (bid,))
            db.commit()
    if target_ip:
        log_action(admin, "IP unbanned", "security", target=target_ip, ip=get_client_ip(request))
    db.close()
    return {"ok": True}

@app.get("/api/login-attempts")
async def api_login_attempts(admin: str = Depends(login_required)):
    db = get_db()
    rows = db.execute("SELECT * FROM login_attempts ORDER BY attempted_at DESC LIMIT 50").fetchall()
    db.close()
    return [dict(r) for r in rows]

# ── API: Network Telemetry ────────────────────────────────────────────────────
@app.get("/api/network/live")
async def api_net_live(admin: str = Depends(login_required)):
    db = get_db()
    rows = db.execute(
        "SELECT iface, bytes_in_rate, bytes_out_rate, bytes_in, bytes_out, ts "
        "FROM net_snapshots WHERE ts=(SELECT MAX(ts) FROM net_snapshots)"
    ).fetchall()
    crows = db.execute(
        "SELECT n1.container, "
        "n1.bytes_in  - IFNULL(n2.bytes_in, 0)  as delta_in, "
        "n1.bytes_out - IFNULL(n2.bytes_out, 0) as delta_out, "
        "n1.bytes_in as total_in, n1.bytes_out as total_out "
        "FROM container_net n1 "
        "LEFT JOIN container_net n2 ON n2.container=n1.container "
        "AND n2.ts=(SELECT MAX(ts) FROM container_net WHERE ts<n1.ts AND container=n1.container) "
        "WHERE n1.ts=(SELECT MAX(ts) FROM container_net) "
        "ORDER BY (n1.bytes_in + n1.bytes_out) DESC"
    ).fetchall()
    db.close()

    interfaces = []
    for r in rows:
        item = dict(r)
        in_rate = int(item.get("bytes_in_rate") or 0)
        out_rate = int(item.get("bytes_out_rate") or 0)
        item["bytes_in_rate"] = in_rate
        item["bytes_out_rate"] = out_rate
        item["rate_in_human"] = format_bytes(in_rate, is_rate=True)
        item["rate_out_human"] = format_bytes(out_rate, is_rate=True)
        interfaces.append(item)

    return {
        "interfaces": interfaces,
        "containers": [dict(r) for r in crows],
        "timestamp": datetime.utcnow().isoformat()
    }

@app.get("/api/network/history")
async def api_net_history(period: str = "24h", iface: str = "", admin: str = Depends(login_required)):
    # Period options: 1h, 24h, 7d, 30d, 1y, all
    # For 30d, 1y, all, query net_daily directly.
    db = get_db()
    params = []

    if period in ("30d", "90d", "1y", "all"):
        if period == "all":
            sql = (
                "SELECT day as ts, day, iface, "
                "CAST(bytes_in / 86400 AS INTEGER) as in_rate, "
                "CAST(bytes_out / 86400 AS INTEGER) as out_rate, "
                "bytes_in as total_in, bytes_out as total_out, "
                "bytes_in, bytes_out "
                "FROM net_daily WHERE 1=1"
            )
        else:
            days_map = {"30d": 30, "90d": 90, "1y": 365}
            d_count = days_map.get(period, 30)
            since = (datetime.utcnow() - timedelta(days=d_count)).strftime("%Y-%m-%d")
            sql = (
                "SELECT day as ts, day, iface, "
                "CAST(bytes_in / 86400 AS INTEGER) as in_rate, "
                "CAST(bytes_out / 86400 AS INTEGER) as out_rate, "
                "bytes_in as total_in, bytes_out as total_out, "
                "bytes_in, bytes_out "
                "FROM net_daily WHERE day>=?"
            )
            params.append(since)
        if iface:
            sql += " AND iface=?"
            params.append(iface)
        sql += " ORDER BY day ASC"
    elif period == "7d":
        since = (datetime.utcnow() - timedelta(days=7)).isoformat()
        sql = (
            "SELECT hour as ts, hour, iface, "
            "avg_in_rate as in_rate, avg_out_rate as out_rate, "
            "total_in, total_out, total_in as bytes_in, total_out as bytes_out "
            "FROM net_hourly WHERE hour>?"
        )
        params.append(since)
        if iface:
            sql += " AND iface=?"
            params.append(iface)
        sql += " ORDER BY hour ASC"
    else:
        hours = 1 if period == "1h" else 24
        since = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
        sql = (
            "SELECT ts, iface, "
            "bytes_in_rate as in_rate, bytes_out_rate as out_rate, "
            "bytes_in as total_in, bytes_out as total_out, "
            "bytes_in, bytes_out "
            "FROM net_snapshots WHERE ts>?"
        )
        params.append(since)
        if iface:
            sql += " AND iface=?"
            params.append(iface)
        sql += " ORDER BY ts ASC"

    rows = db.execute(sql, params).fetchall()
    db.close()
    return {"period": period, "rows": [dict(r) for r in rows]}

@app.get("/api/network/summary")
async def api_net_summary(admin: str = Depends(login_required)):
    db = get_db()
    try:
        def _query_period(day_filter=None, hour_filter=None):
            if day_filter:
                rows = db.execute(
                    f"SELECT iface, SUM(bytes_in) as bytes_in, SUM(bytes_out) as bytes_out "
                    f"FROM net_daily WHERE {day_filter} GROUP BY iface"
                ).fetchall()
                if rows and any((r["bytes_in"] or 0) > 0 or (r["bytes_out"] or 0) > 0 for r in rows):
                    return rows
            elif day_filter is None and hour_filter is None:
                rows = db.execute(
                    "SELECT iface, SUM(bytes_in) as bytes_in, SUM(bytes_out) as bytes_out "
                    "FROM net_daily GROUP BY iface"
                ).fetchall()
                if rows and any((r["bytes_in"] or 0) > 0 or (r["bytes_out"] or 0) > 0 for r in rows):
                    return rows

            if hour_filter:
                rows = db.execute(
                    f"SELECT iface, SUM(total_in) as bytes_in, SUM(total_out) as bytes_out "
                    f"FROM net_hourly WHERE {hour_filter} GROUP BY iface"
                ).fetchall()
                if rows and any((r["bytes_in"] or 0) > 0 or (r["bytes_out"] or 0) > 0 for r in rows):
                    return rows
            elif day_filter is None and hour_filter is None:
                rows = db.execute(
                    "SELECT iface, SUM(total_in) as bytes_in, SUM(total_out) as bytes_out "
                    "FROM net_hourly GROUP BY iface"
                ).fetchall()
                if rows and any((r["bytes_in"] or 0) > 0 or (r["bytes_out"] or 0) > 0 for r in rows):
                    return rows

            snap_clause = "1=1"
            if hour_filter:
                snap_clause = hour_filter.replace("hour", "ts")
            elif day_filter:
                snap_clause = day_filter.replace("day", "date(ts)")
            rows = db.execute(
                f"SELECT iface, MAX(bytes_in)-MIN(bytes_in) as bytes_in, MAX(bytes_out)-MIN(bytes_out) as bytes_out "
                f"FROM net_snapshots WHERE {snap_clause} GROUP BY iface"
            ).fetchall()
            return rows

        def _format_rows(rows):
            res = []
            for r in rows:
                b_in = int(r["bytes_in"] or 0)
                b_out = int(r["bytes_out"] or 0)
                res.append({
                    "iface": r["iface"],
                    "bytes_in": b_in,
                    "bytes_out": b_out,
                    "tin": b_in,
                    "tout": b_out,
                    "human_in": format_bytes(b_in),
                    "human_out": format_bytes(b_out),
                    "total_human": format_bytes(b_in + b_out)
                })
            return res

        today_rows = _format_rows(_query_period("day=date('now')", "hour>=date('now')"))
        week_rows = _format_rows(_query_period("day>=date('now','-7 days')", "hour>=date('now','-7 days')"))
        month_rows = _format_rows(_query_period("day>=date('now','-30 days')", "hour>=date('now','-30 days')"))
        year_rows = _format_rows(_query_period("day>=date('now','-365 days')", "hour>=date('now','-365 days')"))
        all_time_rows = _format_rows(_query_period(None, None))

        top_c = db.execute(
            "SELECT container, MAX(bytes_in)-MIN(bytes_in) as total_in, MAX(bytes_out)-MIN(bytes_out) as total_out "
            "FROM container_net WHERE ts>=datetime('now','-24 hours') "
            "GROUP BY container ORDER BY (MAX(bytes_in)+MAX(bytes_out)) DESC LIMIT 10"
        ).fetchall()
    finally:
        db.close()

    def _calc_total(r_list):
        tot_in = sum(x["bytes_in"] for x in r_list)
        tot_out = sum(x["bytes_out"] for x in r_list)
        return {
            "bytes_in": tot_in,
            "bytes_out": tot_out,
            "tin": tot_in,
            "tout": tot_out,
            "human_in": format_bytes(tot_in),
            "human_out": format_bytes(tot_out),
            "total_human": format_bytes(tot_in + tot_out)
        }

    return {
        "today": today_rows,
        "this_week": week_rows,
        "week": week_rows,
        "this_month": month_rows,
        "month": month_rows,
        "this_year": year_rows,
        "year": year_rows,
        "all_time": all_time_rows,
        "totals": {
            "today": _calc_total(today_rows),
            "this_week": _calc_total(week_rows),
            "this_month": _calc_total(month_rows),
            "this_year": _calc_total(year_rows),
            "all_time": _calc_total(all_time_rows)
        },
        "top_containers_24h": [dict(r) for r in top_c]
    }

# ── API: Admin Password Change ────────────────────────────────────────────────
@app.post("/api/admin/change-password")
async def api_change_password(request: Request, admin: str = Depends(login_required)):
    data = await request.json() or {}
    cur = data.get("current", "")
    nw = data.get("new", "")
    if len(nw) < 8:
        return JSONResponse({"error": "Minimum 8 characters required"}, status_code=400)
    
    db = get_db()
    row = db.execute("SELECT id, password_hash FROM admins WHERE username=?", (admin,)).fetchone()
    if not row:
        db.close()
        return JSONResponse({"error": "Admin not found"}, status_code=404)
    
    is_valid, _, _ = verify_and_migrate_password(cur, row["password_hash"])
    if not is_valid:
        db.close()
        return JSONResponse({"error": "Current password incorrect"}, status_code=403)
    
    db.execute("UPDATE admins SET password_hash=? WHERE username=?", (hash_password(nw), admin))
    db.commit()
    db.close()
    log_action(admin, "Password changed", "auth", ip=get_client_ip(request))
    return {"ok": True}

# ── API: Cloudflare Zero Trust Defense-in-Depth Settings ────────────────────────
@app.get("/api/settings/zero-trust")
async def api_get_zero_trust_settings(request: Request, admin: str = Depends(login_required)):
    cfg = get_zero_trust_config()
    return {
        "enabled": cfg["enabled"],
        "allowed_emails": cfg["allowed_emails"],
        "bypass_local": cfg["bypass_local"]
    }

@app.post("/api/settings/zero-trust")
async def api_set_zero_trust_settings(request: Request, admin: str = Depends(login_required)):
    try:
        data = await request.json()
    except Exception:
        data = {}
    
    if not isinstance(data, dict):
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    raw_enabled = data.get("enabled", False)
    if isinstance(raw_enabled, str):
        enabled = raw_enabled.strip().lower() in ("true", "1", "yes")
    else:
        enabled = bool(raw_enabled)

    raw_bypass = data.get("bypass_local", True)
    if isinstance(raw_bypass, str):
        bypass_local = raw_bypass.strip().lower() in ("true", "1", "yes")
    else:
        bypass_local = bool(raw_bypass)

    raw_emails = data.get("allowed_emails", "")
    if isinstance(raw_emails, str):
        email_items = re.split(r'[,;\n]', raw_emails)
    elif isinstance(raw_emails, (list, tuple, set)):
        email_items = raw_emails
    else:
        return JSONResponse({"error": "allowed_emails must be a list or comma-separated string"}, status_code=400)

    email_regex = re.compile(r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$')
    sanitized_emails = []
    for item in email_items:
        clean = str(item).strip().lower()
        if not clean:
            continue
        if not email_regex.match(clean):
            return JSONResponse({"error": f"Invalid email format: '{clean}'"}, status_code=400)
        if clean not in sanitized_emails:
            sanitized_emails.append(clean)

    emails_str = ",".join(sanitized_emails)
    db = None
    try:
        db = get_db()
        db.execute(
            "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, datetime('now')) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=datetime('now')",
            ("cloudflare_zero_trust_enabled", "true" if enabled else "false")
        )
        db.execute(
            "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, datetime('now')) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=datetime('now')",
            ("allowed_zero_trust_emails", emails_str)
        )
        db.execute(
            "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, datetime('now')) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=datetime('now')",
            ("zero_trust_bypass_local", "true" if bypass_local else "false")
        )
        db.commit()
    except Exception as e:
        return JSONResponse({"error": f"Database error saving settings: {str(e)}"}, status_code=500)
    finally:
        if db:
            try:
                db.close()
            except Exception:
                pass

    log_action(
        actor=admin,
        action="Zero Trust Settings Updated",
        category="security",
        detail=f"Enabled={enabled}, BypassLocal={bypass_local}, Emails={len(sanitized_emails)}",
        ip=get_client_ip(request)
    )

    return {
        "ok": True,
        "enabled": enabled,
        "allowed_emails": sanitized_emails,
        "bypass_local": bypass_local
    }

# ── API: App-Store Auto Update Engine ─────────────────────────────────────────
_update_wake = threading.Event()
_update_worker_started = False
_update_worker_lock = threading.Lock()

def _process_next_update_job() -> bool:
    db = None
    row = None
    try:
        db = get_db()
        row = db.execute(
            "SELECT id FROM update_jobs WHERE status='queued' ORDER BY id ASC LIMIT 1"
        ).fetchone()
    except Exception:
        row = None
    finally:
        if db:
            try:
                db.close()
            except Exception:
                pass
    if not row:
        return False
    ops_updates.run_update_job(
        job_id=row["id"],
        db_factory=get_db,
        docker_client=docker_client,
        managed_services=MANAGED,
        backup_script=BACKUP_SCRIPT,
    )
    return True

def _update_worker_loop():
    while True:
        _update_wake.wait(timeout=60.0)
        _update_wake.clear()
        try:
            while _process_next_update_job():
                pass
        except Exception:
            pass

def ensure_update_worker_started():
    global _update_worker_started
    if _update_worker_started:
        return
    with _update_worker_lock:
        if not _update_worker_started:
            threading.Thread(target=_update_worker_loop, daemon=True, name="update-worker").start()
            _update_worker_started = True

def enqueue_update_job(target: str, actor: str = "admin", ip: str = "system") -> int:
    db = get_db()
    cur = db.execute(
        "INSERT INTO update_jobs (target, status, current_step, triggered_by) VALUES (?, 'queued', 'Queued', ?)",
        (target, actor),
    )
    jid = cur.lastrowid
    db.commit()
    db.close()
    log_action(actor, "Update queued", "system", target=target, detail=f"Job #{jid}", ip=ip)
    ensure_update_worker_started()
    _update_wake.set()
    return jid

@app.get("/api/updates/status")
async def api_updates_status(admin: str = Depends(login_required)):
    db = get_db()
    try:
        cfg = ops_updates.get_update_settings(db)
        cached = ops_updates.get_cached_updates(db)
        active = db.execute(
            "SELECT * FROM update_jobs WHERE status IN ('queued','running') ORDER BY id DESC LIMIT 1"
        ).fetchone()
        active_job = dict(active) if active else None
    finally:
        db.close()

    if not cached:
        cached = {
            "services": [
                {"name": s, "status": "unknown", "image": "", "current_version": "—", "latest_version": "—", "update_available": False, "source": "docker", "note": "Click Check Updates"}
                for s in MANAGED
            ],
            "nextcloud_info": {"running": False, "version": "", "maintenance": False, "core_update_available": False, "available_version": "", "app_updates": []},
            "ytdlp_info": {"current_version": "unknown", "latest_version": "unknown", "update_available": False},
            "updates_available_count": 0,
            "last_checked": cfg.get("last_checked") or "",
        }
    return {
        **cached,
        "active_job": active_job,
        "settings": cfg,
    }

@app.post("/api/updates/check")
async def api_updates_check(request: Request, admin: str = Depends(login_required)):
    db = get_db()
    try:
        res = ops_updates.check_all_updates(docker_client, MANAGED, db=db)
        cfg = ops_updates.get_update_settings(db)
    finally:
        db.close()
    log_action(admin, "Checked for updates", "system", detail=f"{res['updates_available_count']} update(s) available", ip=get_client_ip(request))
    return {**res, "settings": cfg}

@app.get("/api/updates/settings")
async def api_get_update_settings(admin: str = Depends(login_required)):
    db = get_db()
    try:
        return ops_updates.get_update_settings(db)
    finally:
        db.close()

@app.post("/api/updates/settings")
async def api_save_update_settings(request: Request, admin: str = Depends(login_required)):
    data = await request.json() or {}
    db = get_db()
    try:
        saved = ops_updates.save_update_settings(db, data)
    finally:
        db.close()
    log_action(admin, "Update schedule saved", "system", detail=f"Auto={saved['auto_update_enabled']}, {saved['schedule_freq']}@{saved['schedule_time']}", ip=get_client_ip(request))
    return saved

@app.post("/api/updates/apply")
async def api_updates_apply(request: Request, admin: str = Depends(login_required)):
    data = await request.json() or {}
    target = str(data.get("target") or "all").strip()
    valid_targets = set(MANAGED) | {"all", "nextcloud_core", "yt-dlp"}
    if target not in valid_targets:
        return JSONResponse({"error": f"Invalid update target '{target}'"}, status_code=400)
    jid = enqueue_update_job(target=target, actor=admin, ip=get_client_ip(request))
    return {"ok": True, "job_id": jid, "target": target, "status": "queued"}

@app.post("/api/updates/{job_id}/cancel")
async def api_updates_cancel(job_id: int, request: Request, admin: str = Depends(login_required)):
    db = get_db()
    try:
        row = db.execute("SELECT id, status, target, cancel_requested FROM update_jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            return JSONResponse({"error": "Update job not found"}, status_code=404)
        st = row["status"]
        if st == "queued":
            db.execute(
                "UPDATE update_jobs SET status='cancelled', cancel_requested=1, current_step='Cancelled by user', completed_at=datetime('now') WHERE id=?",
                (job_id,),
            )
            new_st = "cancelled"
        elif st == "running" and row["cancel_requested"] == 1:
            db.execute(
                "UPDATE update_jobs SET status='cancelled', current_step='Cancelled by user', error='Force-cancelled while stalled', completed_at=datetime('now') WHERE id=?",
                (job_id,),
            )
            new_st = "cancelled"
        elif st == "running":
            db.execute(
                "UPDATE update_jobs SET cancel_requested=1, current_step='Cancelling cleanly...' WHERE id=?",
                (job_id,),
            )
            new_st = "cancelling"
        else:
            new_st = st
        db.commit()
    finally:
        db.close()
    log_action(admin, "Update cancelled", "system", target=row["target"], detail=f"Job #{job_id} ({new_st})", ip=get_client_ip(request))
    return {"ok": True, "job_id": job_id, "status": new_st}

@app.get("/api/updates/jobs")
async def api_updates_jobs(admin: str = Depends(login_required)):
    db = get_db()
    try:
        rows = db.execute("SELECT * FROM update_jobs ORDER BY id DESC LIMIT 30").fetchall()
        return [dict(r) for r in rows]
    finally:
        db.close()

# ── API: Memory, CPU Profiles & Auto Sleep Mode ───────────────────────────────
@app.get("/api/resources/status")
async def api_resources_status(admin: str = Depends(login_required)):
    db = get_db()
    try:
        with _container_lock:
            cache_copy = list(_container_cache)
        return ops_resources.collect_resource_status(db, docker_client, cache_copy, MANAGED)
    finally:
        db.close()

@app.get("/api/resources/settings")
async def api_get_resource_settings(admin: str = Depends(login_required)):
    db = get_db()
    try:
        return ops_resources.get_resource_settings(db)
    finally:
        db.close()

@app.post("/api/resources/settings")
async def api_save_resource_settings(request: Request, admin: str = Depends(login_required)):
    data = await request.json() or {}
    db = get_db()
    try:
        saved = ops_resources.save_resource_settings(db, data)
    finally:
        db.close()
    log_action(admin, "Resource policy updated", "system", detail=f"Profile={saved['power_profile']}, Reclaim={saved['mem_auto_reclaim_pct']}%", ip=get_client_ip(request))
    return saved

@app.post("/api/resources/memory/compact")
async def api_memory_compact(request: Request, admin: str = Depends(login_required)):
    res = ops_resources.compact_memory(docker_client=docker_client)
    log_action(admin, "RAM compacted", "system", detail=f"Freed {res['freed_mb']} MB ({', '.join(res['actions'])})", ip=get_client_ip(request))
    return res

@app.post("/api/resources/profile")
async def api_set_power_profile(request: Request, admin: str = Depends(login_required)):
    data = await request.json() or {}
    profile = str(data.get("profile") or "").strip().lower()
    db = get_db()
    try:
        ok, msg, updated = ops_resources.apply_power_profile(db, docker_client, profile)
    finally:
        db.close()
    if not ok:
        return JSONResponse({"error": msg}, status_code=400)
    log_action(admin, "Power profile switched", "system", target=profile, detail=f"Updated {len(updated)} containers", ip=get_client_ip(request))
    return {"ok": True, "profile": profile, "message": msg, "updated_containers": updated}

@app.post("/api/resources/container/{name}/limits")
async def api_container_limits(name: str, request: Request, admin: str = Depends(login_required)):
    if name not in MANAGED:
        return JSONResponse({"error": f"Unknown managed container '{name}'"}, status_code=400)
    data = await request.json() or {}
    ok, msg, out = ops_resources.update_container_limits(
        docker_client=docker_client,
        name=name,
        mem_limit_mb=data.get("mem_limit_mb"),
        cpu_shares=data.get("cpu_shares"),
        cpu_quota_pct=data.get("cpu_quota_pct"),
    )
    if not ok:
        code = 503 if "unavailable" in msg.lower() else 400
        return JSONResponse({"error": msg}, status_code=code)
    _refresh_container_stats()
    log_action(admin, "Container limits updated", "containers", target=name, detail=msg, ip=get_client_ip(request))
    return {"ok": True, "message": msg, **out}

# ── Ultralight Async TCP & HTTP Wake-Proxy (Zero-Container Scale-to-Zero) ─────
class WakeProxyManager:
    """Binds service ports inside admin-dashboard to auto-wake sleeping containers on incoming traffic."""

    @staticmethod
    def default_routes():
        routes = [
            ("nextcloud", int(os.environ.get("NEXTCLOUD_PORT", "8081") or 8081), "nextcloud", 80),
            ("navidrome", int(os.environ.get("NAVIDROME_PORT", "4533") or 4533), "navidrome", 4533),
            ("maloja", int(os.environ.get("MALOJA_PORT", "42010") or 42010), "maloja", 42010),
        ]
        smb_port = int(os.environ.get("SAMBA_WAKE_PORT", "0") or 0)
        if smb_port > 0:
            routes.append(("samba", smb_port, "samba", 445))
        return routes

    def __init__(self, routes=None, host: str = "0.0.0.0"):
        self.routes = list(routes) if routes is not None else self.default_routes()
        self.host = host
        self.servers = []
        self.bound_ports: Dict[str, int] = {}
        self.active = False

    async def _ensure_awake(self, service: str, target_host: str, target_port: int, force_probe: bool = False):
        if not docker_client:
            return
        needs_wake = force_probe
        if not needs_wake:
            to_check = ops_resources.SERVICE_DEPENDENCIES.get(service, []) + [service]
            for name in to_check:
                try:
                    c = docker_client.containers.get(name)
                    if getattr(c, "status", "") != "running":
                        needs_wake = True
                        break
                except Exception:
                    pass
        if needs_wake:
            await asyncio.to_thread(
                ops_resources.wake_service_and_wait,
                get_db,
                docker_client,
                service,
                target_host,
                int(target_port),
            )

    async def _handle_client(
        self,
        service: str,
        target_host: str,
        target_port: int,
        client_reader: asyncio.StreamReader,
        client_writer: asyncio.StreamWriter,
    ):
        ops_resources.touch_container_request(service)
        backend_writer = None
        try:
            await self._ensure_awake(service, target_host, target_port)
            try:
                backend_reader, backend_writer = await asyncio.open_connection(target_host, int(target_port))
            except OSError:
                await self._ensure_awake(service, target_host, target_port, force_probe=True)
                backend_reader, backend_writer = await asyncio.open_connection(target_host, int(target_port))

            async def _pipe(src: asyncio.StreamReader, dst: asyncio.StreamWriter):
                try:
                    while True:
                        chunk = await src.read(32768)
                        if not chunk:
                            break
                        ops_resources.touch_container_request(service)
                        dst.write(chunk)
                        await dst.drain()
                except (asyncio.CancelledError, OSError):
                    pass
                finally:
                    try:
                        if dst.can_write_eof():
                            dst.write_eof()
                    except Exception:
                        pass

            await asyncio.gather(
                _pipe(client_reader, backend_writer),
                _pipe(backend_reader, client_writer),
            )
        except Exception as e:
            logger.debug(f"Wake-proxy connection closed for {service}: {e}")
        finally:
            for w in (backend_writer, client_writer):
                if w is not None:
                    try:
                        w.close()
                    except Exception:
                        pass

    async def start(self):
        if self.servers:
            return
        for service, listen_port, target_host, target_port in self.routes:
            if not listen_port and listen_port != 0:
                continue
            try:
                def _make_cb(svc=service, th=target_host, tp=target_port):
                    return lambda r, w: self._handle_client(svc, th, tp, r, w)

                srv = await asyncio.start_server(_make_cb(), self.host, int(listen_port))
                self.servers.append(srv)
                if srv.sockets:
                    self.bound_ports[service] = int(srv.sockets[0].getsockname()[1])
            except OSError as e:
                logger.warning(f"WakeProxy could not bind {self.host}:{listen_port} for {service}: {e}")
        self.active = bool(self.servers)

    async def stop(self):
        for srv in self.servers:
            try:
                srv.close()
                await srv.wait_closed()
            except Exception:
                pass
        self.servers.clear()
        self.bound_ports.clear()
        self.active = False

_wake_proxy_manager = WakeProxyManager()

SERVICE_HTTP_TARGETS = {
    "nextcloud": ("nextcloud", 80),
    "navidrome": ("navidrome", 4533),
    "maloja": ("maloja", 42010),
}

@app.api_route("/svc/{service}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
@app.api_route("/svc/{service}/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
async def wake_http_proxy(service: str, request: Request, path: str = ""):
    import httpx
    svc = (service or "").strip().lower()
    if svc not in SERVICE_HTTP_TARGETS:
        return JSONResponse({"error": f"Unsupported wake-proxy service '{svc}'"}, status_code=404)

    target_host, target_port = SERVICE_HTTP_TARGETS[svc]
    ops_resources.touch_container_request(svc)

    # Wake service + dependencies if asleep
    needs_wake = False
    if docker_client:
        for dep_name in ops_resources.SERVICE_DEPENDENCIES.get(svc, []) + [svc]:
            try:
                c = docker_client.containers.get(dep_name)
                if getattr(c, "status", "") != "running":
                    needs_wake = True
                    break
            except Exception:
                pass
    if needs_wake and docker_client:
        ok, msg, _ = await asyncio.to_thread(
            ops_resources.wake_service_and_wait,
            get_db,
            docker_client,
            svc,
            target_host,
            target_port,
        )
        if not ok:
            return JSONResponse({"error": msg}, status_code=503)

    clean_path = f"/{path.lstrip('/')}" if path else "/"
    qs = request.url.query
    upstream_url = f"http://{target_host}:{target_port}{clean_path}" + (f"?{qs}" if qs else "")
    skip_req_headers = {"host", "content-length", "connection", "transfer-encoding"}
    fwd_headers = {k: v for k, v in request.headers.items() if k.lower() not in skip_req_headers}
    body = await request.body()

    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=False) as client:
            resp = await client.request(
                method=request.method,
                url=upstream_url,
                headers=fwd_headers,
                content=body,
            )
    except Exception as e:
        return JSONResponse({"error": f"Upstream '{svc}' unreachable: {e}"}, status_code=502)

    skip_resp_headers = {"content-encoding", "transfer-encoding", "connection", "content-length"}
    resp_headers = {k: v for k, v in resp.headers.items() if k.lower() not in skip_resp_headers}
    return Response(content=resp.content, status_code=resp.status_code, headers=resp_headers)

@app.get("/api/sleep/status")
async def api_sleep_status(admin: str = Depends(login_required)):
    db = get_db()
    try:
        cfg = ops_resources.get_sleep_settings(db)
        with _container_lock:
            cache_copy = list(_container_cache)
        sleeping_containers = [
            c["name"] for c in cache_copy
            if c.get("status") in ("paused", "exited") and c.get("name") in cfg["sleep_targets"]
        ]
        idle_telemetry = ops_resources.get_idle_telemetry(
            MANAGED,
            docker_client=docker_client,
            sleep_targets=cfg["sleep_targets"],
        )
        idle_elapsed_min = idle_telemetry["server_idle_minutes"]
        return {
            **cfg,
            "sleeping_containers": sleeping_containers,
            "idle_elapsed_minutes": idle_elapsed_min,
            "server_idle_seconds": idle_telemetry["server_idle_seconds"],
            "server_last_request_iso": idle_telemetry["server_last_request_iso"],
            "containers_idle": idle_telemetry["containers"],
            "wake_proxy_active": _wake_proxy_manager.active,
            "wake_proxy_routes": [
                {"service": s, "listen_port": lp, "target": f"{th}:{tp}", "bound_port": _wake_proxy_manager.bound_ports.get(s, 0)}
                for s, lp, th, tp in _wake_proxy_manager.routes
            ],
            "protected_containers": sorted(ops_resources.PROTECTED_SLEEP_CONTAINERS),
        }
    finally:
        db.close()

@app.get("/api/sleep/settings")
async def api_get_sleep_settings(admin: str = Depends(login_required)):
    db = get_db()
    try:
        return ops_resources.get_sleep_settings(db)
    finally:
        db.close()

@app.post("/api/sleep/settings")
async def api_save_sleep_settings(request: Request, admin: str = Depends(login_required)):
    data = await request.json() or {}
    db = get_db()
    try:
        saved = ops_resources.save_sleep_settings(db, data, MANAGED)
    finally:
        db.close()
    log_action(admin, "Auto Sleep policy updated", "system", detail=f"Mode={saved['sleep_mode']}, CtrIdle={saved['container_idle_minutes']}m, SrvIdle={saved['server_idle_minutes']}m", ip=get_client_ip(request))
    return saved

@app.post("/api/sleep/now")
async def api_sleep_now(request: Request, admin: str = Depends(login_required)):
    try:
        data = await request.json() or {}
    except Exception:
        data = {}
    db = get_db()
    try:
        ok, msg, affected = ops_resources.apply_container_sleep(
            db,
            docker_client,
            mode=data.get("mode"),
            targets=data.get("targets"),
        )
    finally:
        db.close()
    if not ok:
        return JSONResponse({"error": msg}, status_code=503)
    _refresh_container_stats()
    log_action(admin, "Container Eco-Sleep activated", "system", detail=", ".join(affected) or "none", ip=get_client_ip(request))
    return {"ok": True, "message": msg, "affected": affected}

@app.post("/api/sleep/wake")
async def api_sleep_wake(request: Request, admin: str = Depends(login_required)):
    try:
        data = await request.json() or {}
    except Exception:
        data = {}
    touch_activity()
    ops_resources.touch_server_request()
    db = get_db()
    try:
        service = str(data.get("service") or "").strip()
        if service:
            deps = ops_resources.SERVICE_DEPENDENCIES.get(service, [])
            ok, msg, woken = ops_resources.wake_sleeping_containers(
                db,
                docker_client,
                targets=deps + [service],
            )
        else:
            ok, msg, woken = ops_resources.wake_sleeping_containers(
                db,
                docker_client,
                targets=data.get("targets"),
            )
    finally:
        db.close()
    if not ok:
        return JSONResponse({"error": msg}, status_code=503)
    _refresh_container_stats()
    log_action(admin, "Services woken from Eco-Sleep", "system", detail=", ".join(woken) or "none", ip=get_client_ip(request))
    return {"ok": True, "message": msg, "woken": woken}

@app.post("/api/sleep/host")
async def api_sleep_host(request: Request, admin: str = Depends(login_required)):
    try:
        data = await request.json() or {}
    except Exception:
        data = {}
    db = get_db()
    try:
        cfg = ops_resources.get_sleep_settings(db)
    finally:
        db.close()
    if not cfg.get("host_sleep_enabled"):
        return JSONResponse({"ok": False, "supported": False, "error": "Host sleep is disabled in Sleep settings."}, status_code=400)
    wake_mins = int(data.get("wake_minutes") or 0)
    ok, supported, msg = ops_resources.trigger_host_sleep(wake_minutes=wake_mins)
    if not ok:
        return JSONResponse({"ok": False, "supported": supported, "error": msg}, status_code=400)
    log_action(admin, "Host suspend initiated", "system", detail=msg, ip=get_client_ip(request))
    return {"ok": True, "supported": True, "message": msg}

# ── Lightweight 60s Background Ops Supervisor (Scheduler + Auto-Sleep + RAM) ─
_last_auto_reclaim_ts = 0.0
_ops_supervisor_started = False
_ops_supervisor_lock = threading.Lock()

def run_ops_supervisor_tick():
    """Single lightweight 60s check: RAM auto-reclaim, scheduled updates, and Two-Tier Auto-Sleep."""
    global _last_auto_reclaim_ts
    db = None
    try:
        db = get_db()
        res_cfg = ops_resources.get_resource_settings(db)
        upd_cfg = ops_updates.get_update_settings(db)
        sleep_cfg = ops_resources.get_sleep_settings(db)

        # 1. Auto RAM compaction when above threshold (5-min cooldown)
        mem = psutil.virtual_memory()
        if mem.percent >= res_cfg["mem_auto_reclaim_pct"] and (time.time() - _last_auto_reclaim_ts) >= 300:
            _last_auto_reclaim_ts = time.time()
            comp = ops_resources.compact_memory(docker_client=docker_client)
            log_action("system", "Auto RAM reclaim", "system", detail=f"RAM {mem.percent}% -> freed {comp['freed_mb']} MB")

        # 2. Scheduled Auto-Update check
        if ops_updates.is_schedule_due(upd_cfg):
            active_upd = db.execute("SELECT id FROM update_jobs WHERE status IN ('queued','running') LIMIT 1").fetchone()
            if not active_upd:
                chk = ops_updates.check_all_updates(docker_client, MANAGED, db=db)
                db.execute(
                    "INSERT INTO settings (key, value, updated_at) VALUES ('auto_update_last_run', ?, datetime('now')) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=datetime('now')",
                    (datetime.utcnow().isoformat(),),
                )
                db.commit()
                if chk.get("updates_available_count", 0) > 0:
                    enqueue_update_job("all", actor="scheduler", ip="scheduler")

        # 3. Two-Tier Auto-Sleep (per-container idle + server-wide idle + schedule window)
        if sleep_cfg.get("eco_sleep_enabled") and docker_client:
            busy_dl = db.execute("SELECT id FROM download_queue WHERE status IN ('queued','downloading') LIMIT 1").fetchone()
            busy_up = db.execute("SELECT id FROM update_jobs WHERE status IN ('queued','running') LIMIT 1").fetchone()
            res = ops_resources.evaluate_idle_sleep(db, docker_client, busy=bool(busy_dl or busy_up))
            if res.get("slept"):
                log_action("system", "Auto Eco-Sleep", "system", detail=f"{res['reason']}: {', '.join(res['slept'])}")
                if res.get("server_idle_sleep"):
                    ops_resources.compact_memory(docker_client=docker_client)
            if res.get("woken"):
                log_action("system", "Auto Eco-Wake", "system", detail=f"{res['reason']}: {', '.join(res['woken'])}")
    except Exception:
        pass
    finally:
        if db:
            try:
                db.close()
            except Exception:
                pass

def start_ops_supervisor():
    global _ops_supervisor_started
    if _ops_supervisor_started:
        return
    with _ops_supervisor_lock:
        if not _ops_supervisor_started:
            def loop():
                while True:
                    time.sleep(60)
                    run_ops_supervisor_tick()
            threading.Thread(target=loop, daemon=True, name="ops-supervisor").start()
            _ops_supervisor_started = True

# ── Lifespan & Background Task Initialization ──────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    try:
        _rdb = get_db()
        try:
            ops_updates.recover_stale_running_jobs(_rdb)
            if docker_client:
                ops_resources.recover_untargeted_sleeping_containers(_rdb, docker_client)
        finally:
            _rdb.close()
    except Exception:
        pass
    ops_resources.reset_idle_trackers()
    start_container_collector()
    start_net_collector()
    start_system_log_harvester()
    ensure_download_worker_started()
    ensure_update_worker_started()
    start_ops_supervisor()
    wake_enabled = os.environ.get("WAKE_PROXY_ENABLED", "true").lower() in ("true", "1", "yes")
    if wake_enabled and not os.environ.get("PYTEST_CURRENT_TEST"):
        await _wake_proxy_manager.start()
    try:
        yield
    finally:
        await _wake_proxy_manager.stop()

app.router.lifespan_context = lifespan

if __name__ == "__main__":
    import uvicorn
    init_db()
    start_container_collector()
    start_net_collector()
    start_system_log_harvester()
    ensure_download_worker_started()
    ensure_update_worker_started()
    start_ops_supervisor()
    port = int(os.environ.get("DASHBOARD_PORT", 5001))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=False)
