# Homelab OS (HL-OS)

> **Turnkey Personal Cloud, Durable File Sharing & Resilient Media Engine**  
> *Engineered for low-power hardware (2-Core Celeron / 4–8GB RAM) up to modern dedicated servers.*

[![Python 3.11](https://img.shields.io/badge/Python-3.11-3776AB.svg?style=flat&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688.svg?style=flat&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Docker Compose](https://img.shields.io/badge/Docker_Compose-v2+-2496ED.svg?style=flat&logo=docker&logoColor=white)](https://docs.docker.com/compose/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Zero AI Overhead](https://img.shields.io/badge/AI_Overhead-0%25_CPU-success.svg)](#architecture--memory-budget)

---

## 🚀 Key Highlights

- **Ultra-Low Memory Footprint (~2.2GB Total Hard Cap):** Sized specifically to run on older 2015-era dual-core laptops (Intel Celeron / Core i3) with 4–8GB RAM, leaving ~5.8GB free for Linux page caching on an 8GB host.
- **Zero-AI Philosophy:** No LLMs, Ollama, or PyTorch processes consuming CPU cycles or draining RAM. 100% of CPU time is prioritized for core services (Pi-hole DNS, Nextcloud, Samba).
- **One-Command CLI Setup:** `./install.sh -y --start` auto-detects CPU, RAM, primary NIC, timezone, Tailscale VPN IP, and host port conflicts, generates strong cryptographic secrets in `.env`, initializes directories, and launches the entire 9-container stack.
- **Modern FastAPI Control Plane:** Asynchronous, typed control plane with OpenAPI / Swagger UI at `/docs`, Starlette sessions, optional Cloudflare Zero Trust middleware, host/container network telemetry, and dual-hash password auth (`scrypt` with transparent legacy SHA-256 migration).
- **Dual-Layer Samba (SMB3) Resilience:**
  - **Server-Side:** SMB 3.1.1 durable handles, client lease caching, and Apple `fruit` VFS extensions for macOS Finder compatibility.
  - **Client Watchdog:** Zero-dependency reconnect watchdog script ([`scripts/client_smb_watchdog.sh`](scripts/client_smb_watchdog.sh)) for macOS and Linux clients.
- **Progressive Web App (PWA):** Service worker offline caching and Web App Manifest allow installing the Admin Dashboard as a standalone app.
- **Throttled Media Engine:** Single-threaded `yt-dlp` / `ffmpeg` audio downloader (FLAC, Opus, M4A, MP3, WAV) with cancellation support, embedded metadata/thumbnails, Navidrome Subsonic library metrics, and Maloja scrobble analytics.

---

## 🏗️ Architecture & Memory Budget

| Service | CPU Shares | Memory Limit | Port(s) | Purpose |
| :--- | :---: | :---: | :---: | :--- |
| **Pi-hole DNS** | 1024 *(Priority)* | 128 MB | `53`, `8080` | Network-wide ad-blocking & local DNS resolution |
| **Nginx Proxy Manager** | 768 | 128 MB | `80`, `443`, `81` | Reverse proxy & SSL termination |
| **MariaDB** | 512 | 512 MB | internal | Nextcloud database (`256M` InnoDB buffer pool) |
| **Nextcloud** | 512 | 512 MB | `8081` | Personal file sync, documents, and cloud storage |
| **Redis Cache** | 512 | 64 MB | internal | In-memory session & Nextcloud file lock cache (`48mb`) |
| **Samba (SMB3)** | 512 | 128 MB | `139`, `445` | Native LAN / Tailscale SMB3 network drive |
| **Admin Dashboard** | 512 | 180 MB | `5001` | FastAPI async management plane, backups & telemetry |
| **Navidrome** | 256 | 300 MB | `4533` | Subsonic-compatible personal music streaming |
| **Maloja** | 256 | 256 MB | `42010` | Self-hosted music scrobbler & listening analytics |
| **TOTAL** | — | **~2.2 GB** | — | **Leaves ~5.8 GB for OS page cache on 8GB hosts** |

---

## ⚡ Install as a Package (Linux, macOS & Windows)

> **Dependency-First Guarantee:** Before copying any Homelab OS workspace files or generating configuration, `homelab` checks that **Python 3.9+**, **Docker Engine**, **Docker Compose v2**, active **Docker daemon**, **Tailscale**, **curl**, **OpenSSL**, and **git** (plus `cifs-utils` on Linux) are installed and healthy — automatically installing missing dependencies via your OS package manager (`apt`/`dnf`/`pacman`/`get.docker.com` on Linux, `brew` on macOS, `winget`/`scoop` on Windows) and re-verifying them first.

### Option 1 — Python (`pipx` / `pip` / `uv`) *(Linux, macOS, Windows)*
```bash
pipx install homelab-os    # or: pip install --user homelab-os
homelab init -y --start
```

### Option 2 — Node.js (`npm` / `npx`) *(Linux, macOS, Windows)*
```bash
npx homelab-os -y --start
# Or install globally:
npm install -g homelab-os
homelab init -y --start
```

### Option 3 — Homebrew *(macOS & Linux)*
```bash
brew tap beingbrijesh/tap https://github.com/beingbrijesh/homelab-framework
brew install homelab-os
homelab init -y --start
```

### Option 4 — Windows (`Scoop` or PowerShell One-Liner)
```powershell
# Scoop
scoop install https://raw.githubusercontent.com/beingbrijesh/homelab-framework/main/packaging/scoop/homelab-os.json
homelab init -y --start

# Or PowerShell bootstrapper (auto-checks/installs Python, Docker Desktop, Tailscale, Git & OpenSSL first)
irm https://raw.githubusercontent.com/beingbrijesh/homelab-framework/main/scripts/install.ps1 | iex
```

### Option 5 — Linux / macOS Curl Bootstrapper
```bash
curl -fsSL https://raw.githubusercontent.com/beingbrijesh/homelab-framework/main/scripts/get-homelab.sh | bash -s -- -y --start
```

---

### CLI Commands Reference

```bash
homelab doctor                         # Verify/install dependencies, probe hardware & check ports
homelab init [OPTIONS]                 # Provision ~/.homelab (or --dir PATH), generate .env & optional --start
homelab up [--build]                   # Start all containers
homelab down                           # Stop all containers
homelab status                         # Show container health & access URLs
homelab logs [service] [-f]            # Tail container logs
homelab backup                         # Run snapshot backup inside admin-dashboard
homelab upgrade                        # Refresh stack files without touching .env or user data
```

**Customized Zero-Touch Setup Example:**

```bash
homelab init -y \
  --dir /opt/homelab \
  --storage /mnt/storage \
  --domain cloud.example.com \
  --user opsadmin \
  --zero-trust-email "you@example.com" \
  --start
```

### Access Your Control Plane & Services

- **Admin Dashboard & Telemetry:** `http://<server-ip>:5001`
- **Interactive API Docs (Swagger):** `http://<server-ip>:5001/docs`
- **Nextcloud Personal Cloud:** `http://<server-ip>:8081`
- **Pi-hole Admin:** `http://<server-ip>:8080/admin`
- **Nginx Proxy Manager UI:** `http://<server-ip>:81`
- **Navidrome Music Streamer:** `http://<server-ip>:4533`
- **Maloja Scrobbler:** `http://<server-ip>:42010`
- **Samba SMB3 File Share:** `smb://<server-ip>/Storage`

> **Host Service Notes:**
> - **Ubuntu `systemd-resolved` (Port 53):** If Pi-hole fails to bind port `53`, disable the systemd stub listener (`DNSStubListener=no` in `/etc/systemd/resolved.conf`) and restart `systemd-resolved`.
> - **Windows / Linux Host Samba (Port 445):** Only one SMB daemon can bind port `445`. On Linux, stop host `smbd` or omit `samba` in `docker-compose.yml`; on Windows, `LanmanServer` reserves port `445` natively.
> - **Nextcloud Low-Spec Tuning:** After Nextcloud finishes initial setup (`nextcloud/config/config.php` exists), `homelab upgrade --no-start` or `./install.sh -y` automatically applies `nextcloud/low_spec_tuning.config.php`.

### Optional Client SMB Auto-Reconnect Watchdog

```bash
homelab watchdog <SERVER_IP> --share Storage --mount-point /Volumes/Storage --user homelab
```

---

## 📂 Project Structure

```
homelab/
├── pyproject.toml                  # PyPI / PEP 621 package metadata (`homelab-os` -> `homelab` CLI)
├── setup.py / MANIFEST.in          # Build-time stack bundling into wheel & sdist
├── package.json / bin/homelab.js   # Cross-platform npm / npx CLI wrapper
├── docker-compose.yml              # 9-service container topology with CPU/RAM limits
├── .env.example                    # Documented configuration template
├── homelab_os/                     # Zero-dependency stdlib cross-platform CLI engine
│   ├── cli.py                      # Commands: doctor, init, up, down, status, logs, backup, upgrade
│   ├── deps.py                     # Dependency pre-check & OS package auto-installer gate
│   ├── sysinfo.py                  # Linux / macOS / Windows hardware, NIC, IP & port probes
│   └── workspace.py                # Workspace provisioning & .env generation
├── packaging/
│   ├── homebrew/homelab-os.rb      # Homebrew Ruby formula
│   └── scoop/homelab-os.json       # Windows Scoop manifest
├── admin-dashboard/                # FastAPI control plane & PWA
├── config/                         # Maloja API patch & Samba SMB3 reference config
├── nextcloud/                      # Low-memory preview caps for dual-core CPUs
├── scripts/
│   ├── get-homelab.sh              # Linux/macOS dependency-first curl bootstrapper
│   ├── install.ps1                 # Windows dependency-first PowerShell bootstrapper
│   ├── client_smb_watchdog.sh      # Auto-reconnect SMB watchdog for macOS/Linux clients
│   └── transfer_to_server.py       # Selective deployment helper
└── tests/                          # API contract & CLI packaging pytest suites
```

---

## 🧪 Testing & Verification

Run the smoke and contract test suite locally to verify API schemas, authentication, Zero Trust middleware, and PWA assets:

```bash
python3 -m pytest tests/test_api_contracts.py -v
```

---

## 🔒 Security & Defense-in-Depth

- **Dual-Hash Migration:** Legacy SHA-256 hashes are automatically upgraded to salted `scrypt` upon next login without invalidating sessions.
- **Fail2ban Protection:** 3 consecutive failed login attempts trigger an automatic 30-minute IP ban in SQLite, plus 1-click and timed IP banning in the Security tab.
- **Optional Cloudflare Zero Trust Middleware:** Set `CLOUDFLARE_ZERO_TRUST_ENABLED=true` and `ALLOWED_ZERO_TRUST_EMAILS` in `.env` (or manage dynamically in the Security UI) to enforce `Cf-Access-Authenticated-User-Email` validation on proxied traffic while allowing private LAN / Tailscale access.
- **Safe Database Practices:** SQLite runs with `timeout=30` and Write-Ahead Logging (`PRAGMA journal_mode=WAL`) to avoid lock contention on slower disks.

---

## 📄 License

Distributed under the MIT License. See [LICENSE](LICENSE) for more information.
