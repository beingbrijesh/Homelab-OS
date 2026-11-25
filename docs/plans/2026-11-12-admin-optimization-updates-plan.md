# Admin Optimization & Auto-Update Features Implementation Plan

> **For Antigravity:** REQUIRED SUB-SKILL: Load executing-plans to implement this plan task-by-task.

**Goal:** Implement 6 ultra-low-resource enhancements in Homelab OS Admin Panel — Auto Update (with App-Store UX & Nextcloud automation), Memory Management, CPU Management, Auto Sleep Mode, Deterministic Music Recommendation Enhancements, and Low-Resource Song Download Queue — with zero regressions to unrelated features.

**Architecture:** Extract Self-Contained Update (`admin-dashboard/ops_updates.py`) and Resource/Power/Sleep (`admin-dashboard/ops_resources.py`) engines imported cleanly into FastAPI (`admin-dashboard/app.py`), backed by SQLite (`settings`, `update_jobs`, migrated `download_queue`), a single lightweight 60s background supervisor loop + single-worker download dispatcher, and new `#s-updates` / `#s-power` views plus minimal controls inside `#s-download` / `#s-recommend` in `admin-dashboard/templates/dashboard.html`.

**Tech Stack:** Python 3.11 (stdlib `threading`, `math`, `gc`, `shutil`, `subprocess`, `sqlite3`, `urllib`), FastAPI, Docker SDK (`docker`), `psutil`, Vanilla JS + Chart.js. Zero new pip/Docker dependencies.

---

### Task 1: Schema Migrations & Feature 6 — Single-Worker Low-Resource Download Engine

**Files:**
- Modify: `admin-dashboard/app.py` (`init_db`, `_run_download`, `api_music_download`, `api_retry_download`, `lifespan`)
- Test: `tests/test_optimization_updates.py`

**Step 1: Write failing tests for download queue concurrency, command builder (`ionice`, `bestaudio`, `limit-rate`, `--download-archive`, optional thumbnail), and DB columns.**

**Step 2: Run pytest on the new test to verify failure (`PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/test_optimization_updates.py -v`).**

**Step 3: Implement in `admin-dashboard/app.py`:**
- Add `download_queue` safe `ALTER TABLE` migrations (`embed_thumbnail INTEGER DEFAULT 1`, `rate_limit TEXT DEFAULT ''`, `archive_skip INTEGER DEFAULT 1`).
- Extract `build_ytdlp_command(...)` helper and `_trigger_navidrome_scan()` helper.
- Replace direct per-request thread spawn with single-worker dispatcher (`start_download_worker()`, `_download_wake` `threading.Event`, `_download_lock`) so `MAX_CONCURRENT_DOWNLOADS == 1`.

**Step 4: Run pytest to verify Task 1 tests pass and existing `test_api_contracts.py` still passes.**

---

### Task 2: Feature 1 — App-Store Auto Update Engine (`ops_updates.py` + API + Scheduler)

**Files:**
- Create: `admin-dashboard/ops_updates.py`
- Modify: `admin-dashboard/app.py` (`init_db` `update_jobs` table, `/api/updates/*` endpoints, 60s scheduler hook)
- Test: `tests/test_optimization_updates.py`

**Step 1: Write failing tests covering:**
- Unauthenticated redirect protection (`303`) on `/api/updates/*`.
- `POST /api/updates/check` & `GET /api/updates/status` with mocked Docker images/Nextcloud `occ`/yt-dlp.
- `GET/POST /api/updates/settings` persistence (`auto_update_enabled`, `freq`, `day`, `time`, `backup_before`, `update_nextcloud_apps`).
- `POST /api/updates/apply` + `POST /api/updates/{job_id}/cancel` cooperative cancellation.
- Nextcloud automated update workflow (`maintenance:mode --on` -> `occ upgrade --no-interaction` -> `occ app:update --all` -> `occ db:add-missing-indices` -> `maintenance:mode --off` ALWAYS executed even on failure/cancel).
- `is_schedule_due()` deterministic verification.

**Step 2: Run pytest to verify failure.**

**Step 3: Implement `admin-dashboard/ops_updates.py` and wire `/api/updates/*` routes + background single-worker update runner & schedule evaluator in `admin-dashboard/app.py`.**

**Step 4: Run pytest to verify pass.**

---

### Task 3: Features 2, 3 & 4 — Memory Management, CPU Power Profiles & Auto Sleep Mode (`ops_resources.py` + API + Supervisor)

**Files:**
- Create: `admin-dashboard/ops_resources.py`
- Modify: `admin-dashboard/app.py` (`/api/resources/*` & `/api/sleep/*` endpoints + 60s supervisor loop in `lifespan`)
- Test: `tests/test_optimization_updates.py`

**Step 1: Write failing tests covering:**
- Unauthenticated redirect (`303`) on `/api/resources/*` and `/api/sleep/*`.
- `GET /api/resources/status` returning host memory/swap breakdown, CPU/temps, container limits, active profile, and sleep state.
- `POST /api/resources/memory/compact` running GC + best-effort Redis purge and returning `freed_mb`.
- `POST /api/resources/profile` (`eco`, `balanced`, `performance`) updating container CPU shares via Docker SDK & persisting setting.
- `POST /api/resources/container/{name}/limits` updating container memory & CPU quota limits cleanly (with validation).
- `GET/POST /api/sleep/settings`, `POST /api/sleep/now` & `POST /api/sleep/wake` (pausing/stopping non-critical containers while keeping `pihole` and `admin-dashboard` awake), scheduled window helper (including overnight ranges), idle auto-sleep check, and `POST /api/sleep/host` graceful unprivileged container response.

**Step 2: Run pytest to verify failure.**

**Step 3: Implement `admin-dashboard/ops_resources.py` and wire `/api/resources/*`, `/api/sleep/*`, and 60s background supervisor into `admin-dashboard/app.py`.**

**Step 4: Run pytest to verify pass.**

---

### Task 4: Feature 5 — Deterministic Zero-AI Music Recommendation Enhancement & `.m3u` Export

**Files:**
- Modify: `admin-dashboard/app.py` (`get_maloja_data`, `api_recommendations`, add `/api/music/playlists/export-m3u`, `/api/music/recommendations/queue-track`)
- Test: `tests/test_optimization_updates.py`

**Step 1: Write failing tests covering:**
- Existing keys in `/api/music/recommendations/{username}` remain intact.
- Time-decay + completion weighting ranks recent fully-played tracks higher than stale skipped tracks.
- `smart_mixes` returned (Rediscover Deep Cuts, Skip-Free Favorites, Current Hour Vibe).
- `POST /api/music/playlists/export-m3u` writes valid `#EXTM3U` file inside `PLAYLIST_DIR` with path traversal protection and DB record.
- `POST /api/music/recommendations/queue-track` enqueues into `download_queue`.

**Step 2: Run pytest to verify failure.**

**Step 3: Implement recommendation enhancements & endpoints cleanly in `admin-dashboard/app.py`.**

**Step 4: Run pytest to verify pass.**

---

### Task 5: Admin Dashboard Frontend UI (`admin-dashboard/templates/dashboard.html`) & Manifest Sync

**Files:**
- Modify: `admin-dashboard/templates/dashboard.html`
- Modify: `scripts/transfer_to_server.py` (include new files `ops_updates.py`, `ops_resources.py`, `test_optimization_updates.py`, plan doc)
- Modify: `tests/test_optimization_updates.py` (HTML section/tab/element presence & JS syntax verification)

**Step 1: Update `admin-dashboard/templates/dashboard.html`:**
- Add `Updates` and `Power & Resources` entries under sidebar `System` section without altering existing nav items.
- Add `#s-updates` App-Store UI section (Check Updates card, Schedule/Auto-Update settings toggle, active Update Job progress + Cancel button, service & Nextcloud app update cards with 1-click Update / Update All).
- Add `#s-power` Power & Resources UI section (Host RAM/CPU/Thermal tiles, 1-Click Compact RAM button, Eco/Balanced/Performance switcher, Auto-Reclaim & Thermal Guard settings, Per-container live CPU/RAM limit editor, Smart Container Eco-Sleep controls + schedule/idle settings + optional Host S3 Sleep trigger).
- Enhance `#s-download` in place (embed thumbnail checkbox, speed/rate-limit selector, resource throttle status badge).
- Enhance `#s-recommend` in place (Smart Mixes cards with 1-click Export `.m3u` to Navidrome + Queue Missing Track button in recommendations).
- Wire `updates` and `power` hooks in `nav()` and background refresh polling cleanly.

**Step 2: Update `scripts/transfer_to_server.py` with new files.**

**Step 3: Verify HTML/JS inline script syntax with Node (`node --check`) and add UI contract assertions in `tests/test_optimization_updates.py`.**

---

### Task 6: Full Verification & Artifact Cleanup (`verification-before-completion`)

**Step 1:** Run full pytest suite across ALL tests:
`PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/ -v`
Expected: All existing 41+ tests AND all new tests PASS.

**Step 2:** Run Python bytecode compilation (`python3 -m py_compile admin-dashboard/*.py homelab_os/*.py tests/*.py`), Node syntax check on extracted dashboard JS, `docker compose config --quiet` (if Docker CLI present), and personal data/leak grep scan.

**Step 3:** Clean up any temporary `__pycache__`, `.pytest_cache`, `*.pyc`, or test `*.db` files in the repository root.
