# Homelab OS Admin Dashboard — Ultra-Lightweight Preact Migration Design

Date: 2026-11-18
Status: Approved

## 1. Goal

Migrate `/admin-dashboard` from monolithic server-rendered Jinja2 templates (`dashboard.html` + CDN Tailwind + CDN Chart.js + inline JS) to an ultra-lightweight **Preact + Vite + TypeScript + Tailwind CSS v4** Single Page Application (SPA), styled after a high-contrast monochrome Bento UI (`iDraft` inspiration) with:
- 1-click **Light Monochrome** (default) and **Dark Monochrome** theme toggle
- Subtle health/warning accent colors strictly for status indicators
- Full-window edge-to-edge layout with floating `rounded-3xl` sidebar
- 100% functional parity across all 13 dashboard sections + Login + Register + PWA offline support
- Minimum-size multi-stage Docker image (`node:20-alpine` frontend build + `python:3.11-alpine` runtime, stripping dev tools, test packages, pip/setuptools, and unneeded uvicorn extras)

## 2. Architecture & Tech Stack

- **Frontend Framework**: Preact 10 + `@preact/preset-vite` (~3.5 kB gzipped React-compatible runtime)
- **Language**: TypeScript (zero runtime overhead)
- **Bundler**: Vite 6 (tree-shaking, hashed immutable assets, minification)
- **Styling**: Tailwind CSS v4 (`@tailwindcss/vite`, pure compiled static CSS)
- **Icons**: `lucide-preact` (tree-shaken SVG components)
- **Charts**: Zero-dependency custom SVG micro-charts (smooth monochrome bezier curves for rolling resource telemetry & network history, concentric SVG radial progress rings for SSD/HDD/RAM, clean 24-hour monochrome bar chart for listening clock) — eliminates ~220 kB Chart.js dependency completely!
- **HTTP & Polling**: Native `fetch` + typed API client with `X-Background-Poll: 1` support for Eco-Sleep idle tracking.
- **Backend**: Existing FastAPI (`app.py`, `ops_resources.py`, `ops_updates.py`) retaining all 50+ `/api/*` JSON contracts, plus `/api/auth/me` and JSON support on `/login` & `/register` alongside form-data compatibility.

## 3. Minimal Docker Image Strategy

1. **Stage 1 (`node:20-alpine`)**: Builds `frontend/` into static `dist/` (~35–55 kB gzipped total). Zero Node.js in runtime image.
2. **Stage 2 (`python:3.11-alpine`)**: Installs `gcc musl-dev linux-headers` solely to build `/opt/venv` from production-only `requirements.txt` (excluding `pytest`, `httpx`, `watchfiles`, `websockets`, `jinja2` if unused). Purges `pip`, `setuptools`, `wheel`, `__pycache__`, `*.pyc`, `tests/` inside venv.
3. **Stage 3 (`python:3.11-alpine`)**: Copies `/opt/venv`, built `static/dist/`, `static/manifest.json`, `static/sw.js`, `app.py`, `ops_resources.py`, `ops_updates.py`, `scripts/backup.sh`. Installs only `ffmpeg`, `curl`, `bash` via `apk add --no-cache`. Drops Debian's ~300 MB `ffmpeg` X11/PulseAudio dependency bloat.

## 4. UI Sections (1:1 Parity)

1. Overview (`overview`): Dark hero telemetry card + nested CPU/RAM/Disk sub-cards, smooth rolling resource SVG chart, concentric SSD/HDD storage rings, battery/AC tile, thermal sensor grid, quick managed services status.
2. Containers (`containers`): Bento service cards, online/offline status, CPU/RAM metrics, Start/Stop/Restart actions, 3-dot context menu, floating Container Logs modal.
3. Network (`network`): Live ↓/↑ speed pills, period selector (`24h`/`7d`/`30d`/`1y`), dual-curve traffic SVG chart, per-container traffic table, Today/7D/30D/1Y/All-Time summary cards.
4. Users (`users`): Sync from Nextcloud button, pending approval queue (Approve/Reject), all users table (Block/Unblock/Delete).
5. Backup (`backup`): Run Backup Now trigger, SSD/HDD storage rings, syntax-highlighted backup log stream.
6. Navidrome (`music`): Server status, Artists/Albums/Songs/Last Scan metrics, dynamic endpoint URL & Launch Player.
7. Download (`download`): yt-dlp submission form (URL, quality/format, embed thumbnail, archive skip, rate limit) + queue cards with single-track and playlist progress bars, Retry/Cancel/Remove, adaptive 4s/20s polling.
8. Recommendations (`recommend`): Scrobble stats, user picker, onboarding prompt, Top Artists & Top Tracks, 24-hour listening pattern SVG bar chart, Collaborative Recommendations (1-click Queue), Smart Mix Bento cards (Export .m3u / Save).
9. Updates (`updates`): Check Updates + scheduler settings, Nextcloud core/apps card, managed service update Bento cards, live active job progress/log/cancel card, job history table.
10. Power & Resources (`power`): RAM/Cache/Swap/CPU/Thermal stats, 1-click Compact RAM, Eco/Balanced/Performance power profile pills, Resource Guard thresholds, per-container Docker limits editor table, Auto-Sleep & WakeProxy config + per-service Sleep/Wake + S3 Host Sleep.
11. Activity Log (`logs`): 5 metric cards, category filter pills, search/severity controls, 15s auto-refresh toggle, full audit table.
12. Security (`security`): Quick-Ban IP form, active IP bans table (Unban), login attempts table (1-click Quick Ban), Cloudflare Zero Trust policy settings.
13. Settings (`settings`): Admin password update form.
14. Auth (`login`, `register`): Monochrome Bento login & account request pages.
