#!/usr/bin/env bash
# ==============================================================================
# Homelab OS (HL-OS) — Hardened & Portable Backup Script
# Runs inside the admin-dashboard container (or on host)
# ==============================================================================

set -o pipefail

# Inside admin-dashboard container (no docker CLI binary), delegate cleanly to Python Docker SDK snapshot engine
if ! command -v docker >/dev/null 2>&1 && [ -f /app/ops_updates.py ]; then
    PY_BIN="${PYTHON_BIN:-/opt/venv/bin/python3}"
    [ -x "$PY_BIN" ] || PY_BIN="python3"
    exec "$PY_BIN" -c "import os, docker, sys; sys.path.insert(0, '/app'); import ops_updates; ok, snap, msg = ops_updates.run_backup_snapshot(docker_client=docker.from_env()); print(msg); sys.exit(0 if ok else 1)"
fi

# ── Dynamic Path Resolution (Zero Hardcoded Usernames) ───────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOMELAB_DIR="${HOMELAB_DIR:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
BACKUP_ROOT="${BACKUP_MOUNT:-/mnt/backup}/snapshots"
LOG_FILE="${BACKUP_LOG:-$HOMELAB_DIR/admin-dashboard/logs/backup.log}"
DATE=$(date +%Y%m%d_%H%M%S)
SNAPSHOT_DIR="$BACKUP_ROOT/$DATE"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-7}"
FAILED=0

mkdir -p "$(dirname "$LOG_FILE")"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

ok() {
    if [ $? -eq 0 ]; then
        log "  ✓ $1"
    else
        log "  ✗ $1 FAILED"
        FAILED=1
    fi
}

mkdir -p "$SNAPSHOT_DIR"
log "══════════════════════════════════════════════"
log "  Homelab Automated Backup Started — $DATE"
log "══════════════════════════════════════════════"
log "  Destination: $SNAPSHOT_DIR"

# ── 1. Docker Compose & Configs ──────────────────────────────────────────────
log ""
log "── [1/6] Backing up Compose & Configuration files..."
if [ -f "$HOMELAB_DIR/docker-compose.yml" ]; then
    cp "$HOMELAB_DIR/docker-compose.yml" "$SNAPSHOT_DIR/docker-compose.yml"
    ok "docker-compose.yml"
fi

if [ -f "$HOMELAB_DIR/.env" ]; then
    cp "$HOMELAB_DIR/.env" "$SNAPSHOT_DIR/env.bak"
    chmod 600 "$SNAPSHOT_DIR/env.bak"
    ok ".env configuration"
fi

# ── 2. MariaDB Database (Secure execution without ps aux leak) ───────────────
log ""
log "── [2/6] Backing up MariaDB databases..."
if docker ps --format '{{.Names}}' | grep -q "^mariadb$"; then
    docker exec mariadb sh -c 'MYSQL_PWD="${MYSQL_ROOT_PASSWORD}" exec mysqldump -u root --single-transaction --quick nextcloud' \
        > "$SNAPSHOT_DIR/nextcloud_db.sql" 2>/dev/null
    ok "Nextcloud database"

    docker exec mariadb sh -c 'MYSQL_PWD="${MYSQL_ROOT_PASSWORD}" exec mysqldump -u root --single-transaction --quick --all-databases' \
        > "$SNAPSHOT_DIR/all_databases.sql" 2>/dev/null
    ok "All databases backup"
else
    log "  ⚠ MariaDB container is not running, skipping database dump"
fi

# ── 3. Nextcloud Config & Apps ───────────────────────────────────────────────
log ""
log "── [3/6] Backing up Nextcloud configuration..."
if docker ps --format '{{.Names}}' | grep -q "^nextcloud$"; then
    docker exec -u 33 nextcloud cat /var/www/html/config/config.php > "$SNAPSHOT_DIR/nextcloud_config.php" 2>/dev/null
    ok "Nextcloud config.php"
    docker exec -u 33 nextcloud php -d memory_limit=512M /var/www/html/occ app:list > "$SNAPSHOT_DIR/nextcloud_apps.txt" 2>/dev/null
    ok "Nextcloud apps list"
fi

# ── 4. Navidrome & Maloja Databases ──────────────────────────────────────────
log ""
log "── [4/6] Backing up Media Databases..."
mkdir -p "$SNAPSHOT_DIR/navidrome" "$SNAPSHOT_DIR/maloja"
if [ -f "$HOMELAB_DIR/navidrome/data/navidrome.db" ]; then
    cp "$HOMELAB_DIR/navidrome/data/navidrome.db" "$SNAPSHOT_DIR/navidrome/navidrome.db" 2>/dev/null
    ok "Navidrome database"
fi

if [ -d "$HOMELAB_DIR/maloja/data" ]; then
    cp "$HOMELAB_DIR/maloja/data/malojadb.sqlite" "$SNAPSHOT_DIR/maloja/" 2>/dev/null || true
    cp "$HOMELAB_DIR/maloja/data/settings.ini" "$SNAPSHOT_DIR/maloja/" 2>/dev/null || true
    ok "Maloja scrobbler database"
fi

# ── 5. Admin Dashboard Database ──────────────────────────────────────────────
log ""
log "── [5/6] Backing up Dashboard state..."
mkdir -p "$SNAPSHOT_DIR/dashboard"
if [ -f "$HOMELAB_DIR/admin-dashboard/data/dashboard.db" ]; then
    cp "$HOMELAB_DIR/admin-dashboard/data/dashboard.db" "$SNAPSHOT_DIR/dashboard/dashboard.db" 2>/dev/null
    ok "Dashboard SQLite database"
fi

# ── 6. Cleanup Expired Snapshots ─────────────────────────────────────────────
log ""
log "── [6/6] Cleaning up snapshots older than $RETENTION_DAYS days..."
find "$BACKUP_ROOT" -maxdepth 1 -type d -mtime +"$RETENTION_DAYS" -not -path "$BACKUP_ROOT" -exec rm -rf {} + 2>/dev/null
ok "Retention cleanup"

log ""
log "══════════════════════════════════════════════"
if [ $FAILED -eq 0 ]; then
    log "  ✓ Backup completed successfully"
else
    log "  ✗ Backup completed with non-fatal warnings"
fi
log "  Snapshot archive: $SNAPSHOT_DIR"
log "══════════════════════════════════════════════"

exit $FAILED
