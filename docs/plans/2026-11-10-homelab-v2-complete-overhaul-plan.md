# Homelab OS v2: Comprehensive Control Plane Overhaul Plan

> **For Antigravity:** Subagent-Driven Execution Plan (Fast Mode).
> **Guiding Principle:** **ZERO HARDCODING** — No email addresses, domain names, usernames, or specific network interface names hardcoded anywhere in the codebase. All configuration is strictly driven by dynamic environment variables, runtime database settings, and dynamic HTTP request header resolution.

**Goal:** Resolve all 7 identified operational issues on the Homelab Admin Dashboard: Navidrome information, download engine (cancellation, Hi-Res FLAC/Opus audio, rich metadata tagging), recommendations and Maloja scrobble sync, system-wide activity logging, 1-click IP blocking in the Security tab, true host network speed monitoring with multi-year data persistence, and dynamic Cloudflare Zero Trust Defense-in-Depth authorization across all endpoints.

**Architecture:** 
1. **Dynamic Zero Trust Defense-in-Depth:** ASGI middleware inspecting `Cf-Access-Authenticated-User-Email` and `Cf-Access-Jwt-Assertion` against dynamic lists loaded from `ALLOWED_ZERO_TRUST_EMAILS` (env var) and runtime database settings. Private LAN/Tailscale IP ranges bypass Zero Trust checks into standard session auth.
2. **Navidrome & Music Engine:** Dynamic client origin resolution using `X-Forwarded-Host` / `request.url.hostname` + Subsonic API integration; yt-dlp process manager with PID tracking for immediate cancellation, multi-format audio conversion (FLAC, Opus, M4A, MP3, WAV), and ID3/Vorbis metadata embedding with clean title parsing.
3. **Recommendations & Analytics:** Bidirectional sync between Maloja's `malojadb.sqlite` (configured via `MALOJA_DB_PATH`) and dashboard SQLite layer, fixing frontend user select filtering and generating accurate genre/artist recommendations.
4. **Unified Logging & Security:** Background Docker event/log tailer and system alert harvester feeding a categorized `activity_log` stream; instant 1-click IP ban in `dashboard.html` and manual IP block modal.
5. **Network Telemetry & Data Storage:** Auto-detects physical host network interfaces via `/host_proc/1/net/dev` with `net_daily` multi-year archival; displays live transfer rates in KB/s and MB/s.

**Tech Stack:** FastAPI, Starlette, SQLite (WAL mode), yt-dlp, FFmpeg, Docker Engine API, Maloja SQLite, Cloudflare Access headers, Tailwind CSS, Chart.js.

---

## Detailed Task Breakdown

### Phase 1: Navidrome Dynamic URL & Live Subsonic Metrics
- **Files:**
  - Modify: `admin-dashboard/app.py`
  - Modify: `admin-dashboard/templates/dashboard.html`
  - Test: `tests/test_api_contracts.py`
- **Dynamic / Zero-Hardcoding Rules:**
  - Dynamically derive Navidrome external URL from incoming `request.headers.get("x-forwarded-host")` or `request.url.hostname` with fallback to `os.environ.get("NAVIDROME_PUBLIC_URL", "")`.
  - Zero hardcoded domains.
- **Tasks:**
  - Update `/api/music/status` in `admin-dashboard/app.py` to inspect Navidrome container state, query Subsonic/Navidrome stats, and dynamically return the external accessible URL based on the request host/headers.
  - Update `admin-dashboard/templates/dashboard.html` in the `#s-music` section to replace outdated setup cards and AI removal notices with live library cards (Total Artists, Total Albums, Total Songs, Last Scan Time, and a working "Open Navidrome" button).
  - Add pytest test in `tests/test_api_contracts.py` verifying dynamic URL calculation and music status contract.

### Phase 2: Download Engine Overhaul (Cancellation, Hi-Res Formats & Rich Metadata)
- **Files:**
  - Modify: `admin-dashboard/app.py`
  - Modify: `admin-dashboard/templates/dashboard.html`
  - Test: `tests/test_api_contracts.py`
- **Tasks:**
  - In `init_db()` in `app.py`: add `pid INTEGER DEFAULT 0` and `format TEXT DEFAULT 'mp3'` to `download_queue` table (with safe `ALTER TABLE` migration for existing databases).
  - Update `_run_download` in `app.py`: store `proc.pid` in `download_queue`.
  - Update `/api/music/queue/{id}/cancel` to lookup `pid` and send `os.kill(pid, signal.SIGTERM)` (falling back to `SIGKILL` if still alive after timeout), updating status to `cancelled`.
  - Support high-fidelity audio formats:
    - `flac`: Hi-Res Studio Lossless (`--audio-format flac`)
    - `opus`: High Fidelity 160kbps+ VBR (`--audio-format opus`)
    - `m4a`: AAC 256kbps (`--audio-format m4a`)
    - `mp3_320`: 320 kbps CBR MP3
    - `mp3_256`: 256 kbps MP3
    - `wav`: Uncompressed PCM (`--audio-format wav`)
  - Metadata enrichment in yt-dlp arguments:
    - `--add-metadata`, `--embed-metadata`, `--embed-thumbnail`
    - `--parse-metadata "%(artist,creator,uploader,channel)s:%(meta_artist)s"`
    - Strip video clutter regex: remove `(Official Music Video)`, `[Lyrics]`, `4K`, `Official Audio`, etc.
  - Update `dashboard.html` download UI:
    - Quality dropdown with FLAC, OPUS, M4A, MP3 320k, MP3 256k, WAV.
    - Show red **Cancel** button on both `queued` AND `downloading` items.
  - Add unit tests in `tests/test_api_contracts.py` for queue cancellation and format parameter validation.

### Phase 3: Recommendations & Maloja Scrobble Sync
- **Files:**
  - Modify: `docker-compose.yml`
  - Modify: `admin-dashboard/app.py`
  - Modify: `admin-dashboard/templates/dashboard.html`
  - Test: `tests/test_api_contracts.py`
- **Dynamic / Zero-Hardcoding Rules:**
  - Mount path configured via `MALOJA_DB_PATH` (defaults to `/maloja/malojadb.sqlite`, with graceful fallback if file does not exist).
  - Active user filtering detects whatever active users exist in `dashboard.db` without hardcoded user IDs or names.
- **Tasks:**
  - In `docker-compose.yml`, mount `${MALOJA_DATA_PATH:-./maloja/data}/malojadb.sqlite:/maloja/malojadb.sqlite:ro` into `admin-dashboard`.
  - In `app.py`, implement `sync_maloja_scrobbles()` to read real listening history, top artists, top tracks, and play counts from Maloja and populate dashboard tables.
  - Fix user dropdown in `templates/dashboard.html` line 883: support both `u.status === 'active'` and `u.active === 1`, auto-selecting the current user on tab open.
  - Add pytest test verifying recommendations endpoint returns rich play stats and suggested playlists.

### Phase 4: System-Wide Unified Activity Logging
- **Files:**
  - Modify: `admin-dashboard/app.py`
  - Modify: `admin-dashboard/templates/dashboard.html`
  - Test: `tests/test_api_contracts.py`
- **Tasks:**
  - In `app.py`, expand `_log_sys` and add background container log harvester capturing:
    - Docker container stop/restart/unhealthy events
    - Nextcloud, MariaDB, and Pi-hole error logs
    - Samba file session disconnect / reconnect events
    - High CPU / memory / disk usage alerts
  - Update `/api/logs` to support category filtering (`all`, `containers`, `system`, `auth`, `storage`, `network`).
  - Update `templates/dashboard.html` Activity Log tab with category filter pills and live auto-refresh.
  - Add pytest test verifying log categories and filtering.

### Phase 5: Security Tab 1-Click Blocking & Quick-Ban Modal
- **Files:**
  - Modify: `admin-dashboard/app.py`
  - Modify: `admin-dashboard/templates/dashboard.html`
  - Test: `tests/test_api_contracts.py`
- **Tasks:**
  - In `app.py`, implement `POST /api/bans/add` accepting `ip`, `reason`, and `duration_hours` (1h, 24h, 168h, permanent).
  - In `templates/dashboard.html`, add a **Quick-Block Form** at the top of the Security section.
  - In `templates/dashboard.html`, add a **🚫 Block IP** button directly on every row in the Recent Login Attempts table with 1-click ban action.
  - Add pytest test verifying ban creation, expiration, and unban.

### Phase 6: True Host Network Speed & Multi-Year Data Storage
- **Files:**
  - Modify: `admin-dashboard/app.py`
  - Modify: `admin-dashboard/templates/dashboard.html`
  - Test: `tests/test_api_contracts.py`
- **Dynamic / Zero-Hardcoding Rules:**
  - Automatically parse `/host_proc/1/net/dev` (or `/proc/net/dev`), filtering out `lo` and docker veth interfaces, and dynamically aggregating all physical NICs (`eth*`, `en*`, `wl*`) and overlay NICs (`tailscale*`).
  - No interface names hardcoded.
- **Tasks:**
  - In `app.py`, update `_collect_net()` to read `/host_proc/1/net/dev` (host PID 1 network namespace).
  - Create `net_daily` and `container_net_daily` tables in SQLite to store aggregated transfer volume indefinitely without deletion.
  - Update `/api/network/summary` and `/api/network/history` to return multi-month and multi-year data rollups.
  - Update `dashboard.html` Network section to show real-time live download/upload speeds in KB/s and MB/s.
  - Add pytest test verifying network rate calculations and daily persistence.

### Phase 7: Dynamic Cloudflare Zero Trust Defense-in-Depth Middleware (ZERO HARDCODING)
- **Files:**
  - Modify: `admin-dashboard/app.py`
  - Modify: `.env.example`
  - Modify: `admin-dashboard/templates/dashboard.html`
  - Test: `tests/test_api_contracts.py`
- **Dynamic / Zero-Hardcoding Architecture:**
  - **No Hardcoded Emails:** Allowed emails are read dynamically from:
    1. Runtime SQLite database `settings` table (`key='allowed_zero_trust_emails'`)
    2. Environment variable `ALLOWED_ZERO_TRUST_EMAILS` (comma-separated, case-insensitive)
  - **No Hardcoded Domains / Tunnels:** Cloudflare request detection checks for presence of standard Cloudflare headers (`CF-Connecting-IP`, `Cf-Ray`, `Cf-Access-Authenticated-User-Email`).
  - **Dynamic Bypass for Private / LAN Traffic:** Requests originating from private LAN (RFC 1918) or Tailscale (`100.64.0.0/10`) without Cloudflare proxy headers bypass Zero Trust email enforcement and use standard session auth.
  - **Security Tab UI Integration:** Authenticated admins can view and update `ALLOWED_ZERO_TRUST_EMAILS` directly from the dashboard Security tab at runtime.
- **Tasks:**
  - In `app.py`, implement `CloudflareZeroTrustMiddleware` (Starlette ASGI middleware):
    - Configured via:
      - `CLOUDFLARE_ZERO_TRUST_ENABLED` (boolean, default: `False`)
      - `ALLOWED_ZERO_TRUST_EMAILS` (comma-separated string, default: `""`)
      - `ZERO_TRUST_BYPASS_PRIVATE_NETS` (boolean, default: `True`)
    - When enabled and request arrives via Cloudflare:
      - Reads `Cf-Access-Authenticated-User-Email`.
      - Checks if email matches the dynamically configured set.
      - If no match or missing header, returns HTTP `403 Forbidden` (`{"detail": "Forbidden: Cloudflare Zero Trust authorization failed"}`).
      - If matched, logs authorized access and attaches `request.state.cf_email`.
  - Add `GET /api/settings/zero-trust` and `POST /api/settings/zero-trust` to allow changing allowed emails dynamically from the UI.
  - In `dashboard.html`, add Zero Trust configuration card under Security tab with toggle status and allowed email management.
  - In `.env.example`, document all Zero Trust options clearly with placeholder examples.
  - In `tests/test_api_contracts.py`, add comprehensive unit tests:
    - Disabled by default -> allows all requests.
    - Enabled + Cloudflare header + unauthorized email -> returns 403.
    - Enabled + Cloudflare header + authorized email -> returns 200.
    - Enabled + local/Tailscale request without CF headers -> bypasses to standard auth.

---

## Verification, Safe Sync & Deployment
1. Run all pytest unit and contract tests locally in the repository root.
2. Build optimized multi-stage Docker image locally to verify clean compile.
3. Sync files to the target server directory preserving existing databases and secrets.
4. On server, build and update `admin-dashboard` (`docker compose up -d --no-deps admin-dashboard`).
5. Live test:
   - Port 5001 local access
   - Port 2081 Caddy reverse proxy access
   - Zero Trust header simulation (authorized vs unauthorized email)
   - Tailscale access
6. Verify all other 8 containers remain healthy and undisturbed.
