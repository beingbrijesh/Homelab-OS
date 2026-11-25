"""Workspace provisioning, template bundling resolution, and .env generation."""

from __future__ import annotations

import os
import secrets
import shutil
import string
import time
from pathlib import Path
from typing import Dict, List, Optional

from .sysinfo import HostProfile

STACK_ITEMS = (
    "docker-compose.yml",
    ".env.example",
    "admin-dashboard",
    "config",
    "nextcloud",
    "scripts",
)

SKIP_DIR_NAMES = {"data", "logs", "__pycache__", ".pytest_cache", ".git", "node_modules"}
SKIP_SUFFIXES = (".db", ".db-wal", ".db-shm", ".sqlite", ".sqlite3", ".log", ".pyc", ".pyo")


def generate_password(length: int = 16) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def generate_hex_secret(nbytes: int = 32) -> str:
    return secrets.token_hex(nbytes)


def resolve_bundle_dir() -> Path:
    candidates: List[Path] = []
    env_src = os.environ.get("HOMELAB_STACK_SRC", "").strip()
    if env_src:
        candidates.append(Path(env_src).expanduser().resolve())

    pkg_dir = Path(__file__).resolve().parent
    candidates.append(pkg_dir / "bundle")
    candidates.append(pkg_dir.parent)

    for candidate in candidates:
        if (candidate / "docker-compose.yml").is_file() and (candidate / "admin-dashboard" / "app.py").is_file():
            return candidate
    raise FileNotFoundError(
        "Could not locate bundled Homelab OS stack files (docker-compose.yml, admin-dashboard/)."
    )


def resolve_workspace_dir(explicit_dir: Optional[str] = None, for_init: bool = False) -> Path:
    if explicit_dir:
        return Path(explicit_dir).expanduser().resolve()
    env_home = os.environ.get("HOMELAB_HOME", "").strip()
    if env_home:
        return Path(env_home).expanduser().resolve()
    if not for_init:
        cwd = Path.cwd()
        if (cwd / "docker-compose.yml").is_file() and (cwd / "admin-dashboard" / "app.py").is_file():
            return cwd.resolve()
    return (Path.home() / ".homelab").resolve()


def _copy_filtered_tree(src: Path, dst: Path) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    for root, dirs, files in os.walk(src):
        rel_root = Path(root).relative_to(src)
        dirs[:] = [d for d in dirs if d not in SKIP_DIR_NAMES]
        target_root = dst / rel_root
        target_root.mkdir(parents=True, exist_ok=True)
        for fname in files:
            if fname in (".env", ".DS_Store") or fname.startswith("._") or fname.endswith(SKIP_SUFFIXES):
                continue
            shutil.copy2(Path(root) / fname, target_root / fname)


def copy_stack_bundle(src_dir: Path, dst_dir: Path, refresh_only: bool = False) -> None:
    dst_dir.mkdir(parents=True, exist_ok=True)
    for item in STACK_ITEMS:
        src_item = src_dir / item
        dst_item = dst_dir / item
        if not src_item.exists():
            continue
        if refresh_only and item == ".env.example" and (dst_dir / ".env").exists():
            # Keep refreshing .env.example as reference while leaving .env intact
            shutil.copy2(src_item, dst_item)
            continue
        if src_item.is_file():
            if src_item.resolve() != dst_item.resolve():
                shutil.copy2(src_item, dst_item)
        else:
            if src_item.resolve() != dst_item.resolve():
                _copy_filtered_tree(src_item, dst_item)

    if os.name != "nt":
        for script_rel in ("admin-dashboard/scripts/backup.sh", "scripts/client_smb_watchdog.sh"):
            sp = dst_dir / script_rel
            if sp.is_file():
                sp.chmod(sp.stat().st_mode | 0o111)


def parse_env_file(env_path: Path) -> Dict[str, str]:
    values: Dict[str, str] = {}
    if not env_path.is_file():
        return values
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        values[k.strip()] = v.strip().strip('"').strip("'")
    return values


def build_trusted_domains(profile: HostProfile, domain: str) -> str:
    items: List[str] = ["localhost", "127.0.0.1"]
    for candidate in (profile.lan_ip, profile.tailscale_ip, domain):
        c = (candidate or "").strip()
        if c and c not in items:
            items.append(c)
    return " ".join(items)


def generate_env_config(
    workspace_dir: Path,
    profile: HostProfile,
    domain: str = "homelab.local",
    admin_user: str = "admin",
    admin_password: str = "",
    smb_user: str = "homelab",
    storage_path: str = "./storage",
    zero_trust_emails: str = "",
    force: bool = False,
) -> tuple[bool, Dict[str, str]]:
    env_path = workspace_dir / ".env"
    if env_path.is_file() and not force:
        return False, parse_env_file(env_path)

    if env_path.is_file() and force:
        backup_path = workspace_dir / f".env.bak.{int(time.time())}"
        shutil.copy2(env_path, backup_path)
        if os.name != "nt":
            backup_path.chmod(0o600)

    admin_pw = admin_password or generate_password()
    smb_pw = generate_password()
    pihole_pw = generate_password()
    maloja_pw = generate_password()
    db_root_pw = generate_password()
    db_pw = generate_password()
    redis_pw = generate_password()
    dash_secret = generate_hex_secret()
    maloja_key = generate_hex_secret()
    trusted_domains = build_trusted_domains(profile, domain)
    zt_enabled = "true" if zero_trust_emails.strip() else "false"

    # Normalize relative storage path cleanly across OSes for Docker Compose
    norm_storage = storage_path.replace("\\", "/")

    content = f"""# ==============================================================================
# Homelab OS (HL-OS) Configuration — Generated by homelab CLI
# ==============================================================================

# ── General Server Settings ──────────────────────────────────────────────────
COMPOSE_PROJECT_NAME=homelab
TZ={profile.timezone}
STORAGE_PATH={norm_storage}
NET_IFACE={profile.net_iface}

# ── Admin Dashboard (FastAPI) ────────────────────────────────────────────────
DASHBOARD_PORT=5001
DASHBOARD_SECRET={dash_secret}
ADMIN_DEFAULT_USER={admin_user}
ADMIN_DEFAULT_PASSWORD={admin_pw}
FORCE_HTTPS=false
WAKE_PROXY_ENABLED=true

# ── Pi-hole DNS ──────────────────────────────────────────────────────────────
PIHOLE_PASSWORD={pihole_pw}
PIHOLE_WEB_PORT=8080

# ── Samba File Server (SMB3 over VPN / LAN) ──────────────────────────────────
SAMBA_SHARE_PATH={norm_storage}
SAMBA_USER={smb_user}
SAMBA_PASSWORD={smb_pw}

# ── MariaDB / Nextcloud Database ─────────────────────────────────────────────
MYSQL_ROOT_PASSWORD={db_root_pw}
MYSQL_DATABASE=nextcloud
MYSQL_USER=nextcloud
MYSQL_PASSWORD={db_pw}

# ── Redis Cache ──────────────────────────────────────────────────────────────
REDIS_PASSWORD={redis_pw}

# ── Nextcloud ────────────────────────────────────────────────────────────────
NEXTCLOUD_ADMIN_USER={admin_user}
NEXTCLOUD_ADMIN_PASSWORD={admin_pw}
NEXTCLOUD_PORT=8081
NEXTCLOUD_TRUSTED_DOMAINS="{trusted_domains}"

# ── Navidrome & Maloja Music Stack ───────────────────────────────────────────
NAVIDROME_PORT=4533
MALOJA_PORT=42010
MALOJA_DATA_PATH=./maloja/data
MALOJA_ADMIN_PASSWORD={maloja_pw}
MALOJA_API_KEY={maloja_key}
MALOJA_API_SECRET=bypass

# ── Backup Configuration ─────────────────────────────────────────────────────
BACKUP_RETENTION_DAYS=7

# ── Cloudflare Zero Trust Defense-in-Depth (Optional) ────────────────────────
CLOUDFLARE_ZERO_TRUST_ENABLED={zt_enabled}
ALLOWED_ZERO_TRUST_EMAILS="{zero_trust_emails.strip()}"
ZERO_TRUST_BYPASS_LOCAL=true
"""
    env_path.write_text(content, encoding="utf-8")
    if os.name != "nt":
        env_path.chmod(0o600)

    return True, parse_env_file(env_path)


def ensure_runtime_directories(workspace_dir: Path, storage_path: str) -> None:
    for rel in (
        "admin-dashboard/data",
        "admin-dashboard/logs",
        "nextcloud/data",
        "nextcloud/config",
        "nextcloud/apps",
        "nginx/data",
        "nginx/letsencrypt",
        "navidrome/data",
        "maloja/data",
    ):
        (workspace_dir / rel).mkdir(parents=True, exist_ok=True)

    storage_dir = Path(storage_path)
    if not storage_dir.is_absolute():
        storage_dir = (workspace_dir / storage_dir).resolve()
    (storage_dir / "music" / "_playlists").mkdir(parents=True, exist_ok=True)
    (storage_dir / "snapshots").mkdir(parents=True, exist_ok=True)

    # Apply low-spec Nextcloud config drop-in safely if Nextcloud is already initialized
    nc_cfg = workspace_dir / "nextcloud" / "config" / "config.php"
    low_spec_src = workspace_dir / "nextcloud" / "low_spec_tuning.config.php"
    low_spec_dst = workspace_dir / "nextcloud" / "config" / "low_spec.config.php"
    if nc_cfg.is_file() and low_spec_src.is_file() and not low_spec_dst.is_file():
        shutil.copy2(low_spec_src, low_spec_dst)
