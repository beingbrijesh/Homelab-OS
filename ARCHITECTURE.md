# Homelab OS Architecture & Engineering Specification

## 1. High-Level Architecture

Homelab OS is organized into three decoupled layers:

```
+-------------------------------------------------------------------------+
|                              CLIENT LAYER                               |
|   macOS / iOS / Linux / Windows / Android (via Tailscale Mesh VPN)      |
|  - Native SMB3 Client (Finder / File Explorer)                          |
|  - Progressive Web App Dashboard (Service Worker + Offline Pill)        |
|  - Subsonic Music Client (Symfonium / DSub / Web Player)                |
+-------------------------------------------------------------------------+
                                     │
                                     ▼
+-------------------------------------------------------------------------+
|                        SERVICES & GATEWAY LAYER                         |
|   - Nginx Reverse Proxy (SSL termination, routing, gzip compression)     |
|   - Pi-hole DNS (port 53, priority CPU shares: 1024)                    |
|   - Samba SMB 3.1.1 (Ports 445/139, durable handles & leases)           |
|   - Admin Dashboard (FastAPI, Port 5001, OpenAPI /docs)                 |
|   - Nextcloud (Port 8081, PHP-FPM low-spec tuning)                      |
|   - Navidrome (Port 4533, Go Subsonic server)                           |
|   - Maloja (Port 42010, Self-hosted scrobbler)                          |
+-------------------------------------------------------------------------+
                                     │
                                     ▼
+-------------------------------------------------------------------------+
|                      DATA PERSISTENCE & STORAGE                         |
|   - MariaDB 10.11 (InnoDB buffer pool capped at 256MB)                  |
|   - Redis Cache (maxmemory 48mb, allkeys-lru)                           |
|   - SQLite3 with WAL Mode (Admin DB + Maloja scrobble DB)               |
|   - Host Storage Mounts (${STORAGE_PATH}: music, shares & snapshots)    |
+-------------------------------------------------------------------------+
```

---

## 2. Low-Spec Optimization Principles (Dual-Core Celeron & 8GB RAM)

### 2.1 Memory Envelope
- Total System RAM: 8,192 MB (~8.0 GB)
- Container Hard Memory Limits: ~2,240 MB (~2.2 GB)
- Container Soft Memory Limits (Reservations): ~1,200 MB (~1.2 GB)
- **Available Host Page Cache:** **~5,952 MB (~5.8 GB)**
- **Result:** Linux page cache remains plentiful for high-throughput disk I/O, preventing swapping to slower mechanical drives or budget SSDs.

### 2.2 CPU Share Scheduling
Docker assigns standard containers 1024 CPU shares by default. In Homelab OS, CPU shares are tuned to protect low-latency services:
1. **Pi-hole (1024 shares):** DNS resolution never drops a single packet during heavy I/O.
2. **Nginx Proxy (768 shares):** Reverse proxy and TLS routing remain responsive under load.
3. **MariaDB, Redis, Nextcloud, Samba & Admin Dashboard (512 shares):** File transfers, database queries, and management plane receive balanced priority.
4. **Navidrome & Maloja (256 shares):** Music streaming and scrobble analytics.
5. **Background Workers (`nice -n 15` / `-n 19`):** Audio conversion (`yt-dlp` / `ffmpeg`) and backup snapshots (`mysqldump`) run at reduced CPU/I/O priority, eliminating system stutters.

---

## 3. Resilient File Sharing: Dual-Layer Samba Architecture

### 3.1 Server-Side Durability (`smb.conf`)
Standard Samba deployments drop open handles and crash mounted network shares when transient packet loss occurs over mobile or VPN networks.

Homelab OS configures SMB 3.1.1 with:
- **`durable handles = yes` & `smb2 leases = yes`:** Permits clients to reconnect to suspended file sessions without invalidating open file descriptors.
- **`deadtime = 15`:** Periodically tests client connection liveness.
- **`vfs objects = catia fruit streams_xattr`:** Full compatibility with macOS Finder, preventing `.DS_Store` file locks and metadata corruption.

### 3.2 Client-Side Watchdog (`scripts/client_smb_watchdog.sh`)
Runs on client machines as a lightweight cron or launchd agent. It pings the server SMB port (445) and checks if the volume mount has gone stale, automatically unmounting and remounting cleanly without requiring manual Finder restarts.

---

## 4. Control Plane Migration: Flask to FastAPI

### 4.1 Why FastAPI?
- **Asynchronous Execution:** Handles concurrent telemetry gathering, Docker polling, and UI interactions without blocking the Python GIL.
- **Interactive Documentation:** Automatic OpenAPI generation at `/docs` simplifies community integrations and API scripting.
- **Pydantic Validation:** Type safety prevents runtime crashes from malformed client payloads.

### 4.2 Seamless Password Upgrade Flow
```
User Enters Credentials
       │
       ▼
Check SQLite DB for stored hash
       │
       ├─ Starts with "scrypt:" or "pbkdf2:"? ──► Verify with check_password_hash()
       │
       └─ 64-char Hex String (Legacy SHA-256)?
             │
             ├─ Hash match? ──► Generate new scrypt hash
             │                       │
             │                       ▼
             │                 UPDATE admins SET password_hash = new_scrypt
             │                       │
             │                       ▼
             │                 Grant Session (admin_logged_in = True)
             │
             └─ Hash mismatch? ──► Record failed attempt, check Fail2ban
```
