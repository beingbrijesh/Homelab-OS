# Homelab OS: Operations & Disaster Recovery Runbooks

This guide covers day-2 operations for **Homelab OS**, including automated atomic backups, disaster recovery drills, zero-downtime container updates, storage expansion, and power management.

---

## 📋 Table of Contents

1. [Backup & Snapshot Architecture](#1-backup--snapshot-architecture)
2. [Disaster Recovery Drill (Step-by-Step)](#2-disaster-recovery-drill-step-by-step)
3. [Zero-Downtime Container Upgrades](#3-zero-downtime-container-upgrades)
4. [Storage Volume Management & Expansion](#4-storage-volume-management--expansion)
5. [Eco-Sleep Power Management](#5-eco-sleep-power-management)
6. [Routine Maintenance Schedule](#6-routine-maintenance-schedule)

---

## 1. Backup & Snapshot Architecture

Homelab OS features an integrated, container-aware backup engine ([`ops_updates.py`](file:///Users/beingbrijesh/homelab-framework/admin-dashboard/ops_updates.py) and [`backup.sh`](file:///Users/beingbrijesh/homelab-framework/admin-dashboard/scripts/backup.sh)). It creates self-contained snapshot archives without requiring the host to stop running services.

### Anatomy of a Snapshot Archive

Each snapshot is saved to `storage/snapshots/<TIMESTAMP>/` (e.g., `20261126_130000/`):

```text
storage/snapshots/20261126_130000/
├── nextcloud_db.sql           # Complete MariaDB database dump
├── nextcloud_config.php       # Nextcloud cryptographic keys and salt
├── nextcloud_apps.txt         # List of installed Nextcloud plugins and versions
├── dashboard/
│   └── dashboard.db           # Online SQLite backup of control plane
└── maloja/
    └── malojadb.sqlite        # SQLite copy of listening history
```

### Triggering a Snapshot

#### Method A: Command-Line Interface
```bash
homelab backup
```

#### Method B: Admin Dashboard UI
1. Navigate to the **Backups** tab in the Admin Dashboard (`http://<HOST_IP>:5001`).
2. Click **Create Snapshot Now**.
3. Observe live progress; the snapshot appears in the archives list upon completion.

#### Method C: REST API
```bash
curl -X POST http://localhost:5001/api/backups/create \
  -H "Cookie: session=<YOUR_SESSION_TOKEN>"
```

### Automated Retention Cleanup

Snapshots older than **7 days** (configurable via `BACKUP_RETENTION_DAYS` in `.env`) are purged automatically during the next snapshot cycle to preserve host disk space.

---

## 2. Disaster Recovery Drill (Step-by-Step)

If your host machine suffers storage corruption, complete disk failure, or accidental file deletion, follow this procedure to restore Homelab OS:

### Step 1: Re-provision Host Environment
Install Docker and Homelab OS on the new or formatted system:
```bash
git clone https://github.com/beingbrijesh/Homelab-OS.git
cd Homelab-OS
./install.sh -y
```

### Step 2: Restore Configuration Secrets
Copy your backed-up `.env` file into the root directory. This restores cryptographic keys, session secrets, and MariaDB passwords.

### Step 3: Restore Databases and Nextcloud Configuration
Locate your snapshot directory (e.g., `/mnt/usb/snapshots/20261126_130000/`):

```bash
# 1. Start core database containers first
docker compose up -d mariadb redis

# 2. Wait 10 seconds for MariaDB to initialize, then restore database dump
docker compose exec -T mariadb mysql -u root -p"${MYSQL_ROOT_PASSWORD}" nextcloud < nextcloud_db.sql

# 3. Restore Nextcloud configuration file
docker cp nextcloud_config.php $(docker compose ps -q nextcloud):/var/www/html/config/config.php

# 4. Restore Admin Dashboard SQLite database
mkdir -p admin-dashboard/data
cp dashboard/dashboard.db admin-dashboard/data/dashboard.db
```

### Step 4: Restore File Storage & Fix Permissions
Copy your user files and media into `storage/`:
```bash
# Ensure correct ownership (UID 1000 for standard Linux container permissions)
sudo chown -R 1000:1000 storage/ nextcloud/
```

### Step 5: Launch Stack & Verify
```bash
docker compose up -d
docker compose ps
```
All services will resume in their exact pre-disaster state.

---

## 3. Zero-Downtime Container Upgrades

Updating containers in Homelab OS is managed through the companion engine with automated rollback safety:

```
[Trigger Update]
       │
       ▼
[Automated Pre-Update Backup] ──► Fails? ──► Abort & Retain Running State
       │ (Succeeds)
       ▼
[Pull New Image Digest]
       │
       ▼
[Recreate Container & Attach Volumes]
       │
       ▼
[Poll Container Health (60s)] ──► Unhealthy? ──► Auto-Rollback to Previous Image
       │ (Healthy)
       ▼
[Prune Stale Orphan Image]
```

### Nextcloud Hands-Free Upgrade Safety

Nextcloud core forbids skipping major versions (e.g., jumping from Nextcloud 32 directly to 34 causes data corruption). The Homelab OS update engine inspects Nextcloud's `occ status` and enforces:
* **Step-by-Step Major Bumps:** Upgrades `32 -> 33` before allowing `33 -> 34`.
* **Port Verification:** Waits for internal Apache port 80 to become active after entrypoint rsync before declaring the service healthy.

---

## 4. Storage Volume Management & Expansion

### Adding an External Hard Drive or NAS Mount
To store large media collections or Nextcloud files on a dedicated drive:

1. Format and mount the external disk (e.g., at `/mnt/data`).
2. Add the mount point to `/etc/fstab` for persistence across reboots.
3. Update your `.env` file:
   ```env
   STORAGE_PATH=/mnt/data/homelab/storage
   ```
4. Restart containers to apply the mount path:
   ```bash
   homelab down && homelab up
   ```

### Fixing File Permission Issues
If files copied via SMB or Nextcloud show `Permission Denied`:
```bash
# Set appropriate read/write permissions
sudo chmod -R 775 storage/
sudo chown -R 1000:1000 storage/
```

---

## 5. Eco-Sleep Power Management

On low-power hosts (such as fanless mini-PCs or older laptops running on battery backup), Homelab OS includes an intelligent **Eco-Sleep Engine** ([`ops_resources.py`](file:///Users/beingbrijesh/homelab-framework/admin-dashboard/ops_resources.py)):

* **Idle Detection:** If no SMB file transfers, Subsonic streams, or Nextcloud syncs occur for 30 minutes (configurable via `ECO_SLEEP_TIMEOUT_MINUTES=30` in `.env`), non-essential background containers are paused.
* **Instant Wake-on-Request:** Ingress proxy requests or DNS lookups immediately wake paused services in under 1.5 seconds.
* **Power Savings:** Reduces host CPU idle power draw by up to **35%** on dual-core hardware.

---

## 6. Routine Maintenance Schedule

| Frequency | Task | Recommended Command |
| :--- | :--- | :--- |
| **Daily** | Verify container health & review unresolved system events | `homelab doctor` or check Dashboard alerts |
| **Weekly** | Automated backup snapshot rotation | Handled automatically by backup scheduler |
| **Monthly** | Container registry check & security updates | Click **Update All** in Updates UI |
| **Quarterly** | Docker unused build cache prune | `docker builder prune -f` |
