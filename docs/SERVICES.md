# Homelab OS: Service Catalog & Configuration Reference

This catalog documents the 9 integrated container services comprising **Homelab OS**, detailing their ports, resource limits, volume bindings, environment keys, and low-spec tuning strategies.

---

## 📋 Services Overview Matrix

| Container Name | Image Source | Port(s) | Memory (Hard / Soft) | CPU Shares | Primary Role |
| :--- | :--- | :--- | :---: | :---: | :--- |
| **`pihole`** | `pihole/pihole:latest` | `53/tcp`, `53/udp`, `8080/tcp` | 128 MB / 64 MB | 1024 *(High)* | Network-wide DNS sinkhole & local ad-blocking |
| **`nginx-proxy`** | `jc21/nginx-proxy-manager:latest` | `80/tcp`, `443/tcp`, `81/tcp` | 128 MB / 64 MB | 768 | Reverse proxy, TLS termination, Let's Encrypt |
| **`mariadb`** | `mariadb:10.11` | *(Internal)* | 512 MB / 256 MB | 512 | Nextcloud transactional database store |
| **`redis`** | `redis:7-alpine` | *(Internal)* | 64 MB / 32 MB | 512 | In-memory session & Nextcloud transactional file lock cache |
| **`nextcloud`** | `nextcloud:33-apache` | `8081/tcp` | 512 MB / 256 MB | 512 | Self-hosted files, calendar, contacts, photos |
| **`samba`** | `dperson/samba:latest` | `139/tcp`, `445/tcp` | 128 MB / 64 MB | 512 | Native SMB 3.1.1 multi-client network shares |
| **`admin-dashboard`**| Local 3-Stage Alpine Build | `5001/tcp` | 180 MB / 64 MB | 512 | FastAPI management plane & Preact Bento UI |
| **`navidrome`** | `deluan/navidrome:latest` | `4533/tcp` | 300 MB / 128 MB | 256 | High-performance Go Subsonic music streamer |
| **`maloja`** | `krateng/maloja:latest` | `42010/tcp` | 256 MB / 96 MB | 256 | Self-hosted listening analytics & scrobbler |

---

## 1. Pi-hole DNS (`pihole`)

* **Role:** Resolves local network DNS queries, routes private domains (`homelab.local`), and filters ads and telemetry trackers before they reach client devices.
* **Ports:**
  - `53/tcp`, `53/udp`: DNS resolution protocol.
  - `8080/tcp`: Pi-hole web administration interface (`http://<HOST_IP>:8080/admin`).
* **Persistent Volumes:**
  - `pihole/etc-pihole/:/etc/pihole/`: Adlists, audit queries, and local DNS records.
  - `pihole/etc-dnsmasq.d/:/etc/dnsmasq.d/`: Underlying dnsmasq network configurations.
* **Resource Tuning:**
  - Assigned **1024 CPU Shares** (highest in the stack) to guarantee sub-millisecond DNS responses even during 100% host disk I/O.
  - Memory capped at **128 MB**.

---

## 2. Nginx Proxy Manager (`nginx-proxy`)

* **Role:** Unified ingress gateway providing automatic Let's Encrypt SSL/TLS certificates, domain routing, and HTTP-to-HTTPS redirection.
* **Ports:**
  - `80/tcp`: Public HTTP traffic.
  - `443/tcp`: Public HTTPS traffic.
  - `81/tcp`: Web configuration dashboard.
* **Persistent Volumes:**
  - `nginx/data/:/data`: SSL certificates, proxy hosts, and access lists.
  - `nginx/letsencrypt/:/etc/letsencrypt`: ACME challenge tokens and keys.
* **Resource Tuning:**
  - Capped at **128 MB RAM** and **768 CPU Shares**, preventing buffer bloat while maintaining responsive request forwarding.

---

## 3. MariaDB (`mariadb`)

* **Role:** ACID-compliant relational backend specifically dedicated to Nextcloud application state, file indexes, user metadata, and sync journals.
* **Network:** Connected strictly to internal Docker bridge network (no external host ports exposed).
* **Persistent Volumes:**
  - `mariadb/:/var/lib/mysql`: MySQL database tablespaces.
* **Low-Spec Optimization Settings:**
  - `innodb_buffer_pool_size = 256M`: Prevents MariaDB from ballooning past 512 MB.
  - `innodb_log_file_size = 64M`: Fast recovery checkpointing.
  - `max_connections = 64`: Throttles connection overhead for home-scale concurrency.

---

## 4. Redis Cache (`redis`)

* **Role:** High-speed in-memory store for Nextcloud transactional file locking (`filelocking.enabled = true`) and memory caching.
* **Network:** Internal Docker network only.
* **Resource Tuning:**
  - `maxmemory 48mb`: Hard ceiling on Redis memory usage.
  - `maxmemory-policy allkeys-lru`: Evicts least-recently-used cache objects automatically when memory threshold is reached, preventing out-of-memory container crashes.

---

## 5. Nextcloud (`nextcloud`)

* **Role:** Multi-user private cloud storage supporting desktop folder sync, mobile camera auto-uploads, document collaboration, and webDAV.
* **Ports:**
  - `8081/tcp`: Nextcloud web interface and WebDAV endpoint.
* **Persistent Volumes:**
  - `nextcloud/data/:/var/www/html/data`: Primary user files and directories.
  - `nextcloud/config/:/var/www/html/config`: Dynamic Nextcloud PHP configuration.
  - `nextcloud/apps/:/var/www/html/custom_apps`: Installed Nextcloud plugins.
* **Low-Spec Tuning ([`nextcloud/low_spec_tuning.config.php`](file:///Users/beingbrijesh/homelab-framework/nextcloud/low_spec_tuning.config.php)):**
  - Preview generator dimensions capped at `1024x1024` pixels to eliminate CPU spikes during photo uploads.
  - Background cron execution shifted from AJAX to system-level cron.

---

## 6. Samba SMB 3.1.1 (`samba`)

* **Role:** Native LAN and Tailscale network file sharing for Windows File Explorer, macOS Finder, and Linux desktop clients.
* **Ports:**
  - `445/tcp`, `139/tcp`: SMB/CIFS durable protocol ports.
* **Persistent Volumes:**
  - `${STORAGE_PATH}:/share/Storage`: Primary shared host directory.
  - `config/samba/smb.conf:/etc/samba/smb.conf`: Tailored configuration.
* **Configuration Highlights ([`config/samba/smb.conf`](file:///Users/beingbrijesh/homelab-framework/config/samba/smb.conf)):**
  - `server min protocol = SMB3_00`: Disables insecure legacy SMB1/SMB2.
  - `smb2 leases = yes`: Enables client lease caching.
  - `vfs objects = catia fruit streams_xattr`: Full macOS Finder metadata and extended attribute support without `.DS_Store` corruption.

---

## 7. Admin Dashboard (`admin-dashboard`)

* **Role:** Centralized control plane, real-time hardware telemetry, container lifecycle updater, system event resolver, and high-fidelity YouTube audio downloader.
* **Ports:**
  - `5001/tcp`: FastAPI control plane and Preact Bento UI.
* **Persistent Volumes:**
  - `admin-dashboard/data/:/app/data`: Local SQLite database (`dashboard.db`).
  - `/var/run/docker.sock:/var/run/docker.sock`: Read/write Docker API communication.
  - `/proc:/host/proc:ro`, `/sys:/host/sys:ro`: Real-time hardware thermals and CPU telemetry.
* **Engineering Highlights:**
  - **Docker Image:** 3-stage minimal Alpine build reduced from **642 MB down to 236 MB (-63.2%)**.
  - **Frontend:** Preact 10 + Vite 6 + Tailwind CSS v4 (~47 kB gzipped production bundle).
  - **Database:** SQLite with Write-Ahead Logging (`WAL`), `scrypt` password hashing, and token-based session management.

---

## 8. Navidrome (`navidrome`)

* **Role:** Ultra-lightweight Subsonic-compatible personal music streaming server written in Go.
* **Ports:**
  - `4533/tcp`: Subsonic API and web streaming UI.
* **Persistent Volumes:**
  - `${STORAGE_PATH}/music:/music:ro`: Lossless audio files (`flac`, `opus`, `mp3`, `m4a`).
  - `navidrome/data/:/data`: Music library index and Subsonic user database.
* **Tuning:**
  - Memory capped at **300 MB**.
  - Read-only music volume mount ensures client devices cannot accidentally delete source media.

---

## 9. Maloja (`maloja`)

* **Role:** Independent, self-hosted music scrobbler and listening statistics engine.
* **Ports:**
  - `42010/tcp`: Scrobbler web interface and native API.
* **Persistent Volumes:**
  - `maloja/data/:/var/lib/maloja`: Scrobble database and user listening logs.
* **Subsonic Integration:**
  - Connects to Navidrome to automatically record track plays, artist leaderboards, and hourly listening analytics.
