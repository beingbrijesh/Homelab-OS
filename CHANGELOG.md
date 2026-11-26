# Changelog

All notable changes to **Homelab OS** are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [2.0.0] - 2026-11-25

### 🚀 Major Architectural Overhaul & Modernization

#### Added
* **Ultra-Lightweight Preact Bento Frontend:**
  - Complete frontend rewrite in Preact 10, Vite 6, TypeScript, and Tailwind CSS v4.
  - Total production client bundle reduced to **~47 kB gzipped** (~208 kB raw).
  - Zero-dependency custom SVG charting engine (`SmoothLineChart`, `ConcentricRingGauge`, `HourlyBarChart`) with perceptual logarithmic and linear scale toggle.
  - 13 high-density Bento dashboard views: Overview, Containers, Storage, Network, Hardware, Power, Security, Logs, Updates, Backups, Recommendations, Settings, and Music Downloads.
  - Full PWA support (`homelab-pwa-v4`) with cache-first asset delivery and offline network indicator.
* **Turnkey Multi-Platform CLI & Package Distribution:**
  - Global npm package executable via `npx homelab-os` or `npm install -g homelab-os`.
  - Python package distribution with entry point `homelab` on PyPI (`pipx install homelab-os`).
  - Homebrew formula (`packaging/homebrew/homelab-os.rb`) and Windows Scoop manifest (`packaging/scoop/homelab-os.json`).
  - Headless `--skip-deps` flag for CI pipeline testing and automated verification.
* **System Logging & Event Deduplication Engine:**
  - Automated container log harvester normalizing timestamps, PIDs, and message hashes.
  - In-memory 10-minute deduplication window suppressing transient retry chatter (e.g., Navidrome scrobble notices, Pi-hole DNS retries).
  - System event management endpoints: `POST /api/system-events/{eid}/resolve` and `POST /api/system-events/resolve-all`.
* **Zero-Downtime Updates & Disaster Recovery:**
  - Container updater with automatic pre-update snapshots, health check verification, and automatic rollback upon container failure.
  - Hands-free Nextcloud upgrade engine preventing skipped major version tags.
  - Online SQLite `VACUUM INTO` atomic snapshot creation.
* **Cross-Platform Process Management:**
  - Integrated `psutil` process termination for download cancellation, replacing POSIX `signal.SIGKILL` with seamless compatibility across Linux, macOS, and Windows.
* **Comprehensive Test & CI Suite:**
  - 76 regression tests covering API schemas, password migration, PWA assets, and CLI packaging.
  - GitHub Actions matrix testing automated builds on `ubuntu-latest`, `macos-latest`, and `windows-latest`.

#### Changed
* **Container Optimization & Alpine Multi-Stage Build:**
  - Replaced monolithic Debian container with 3-stage Alpine build (`node:20-alpine` -> `python:3.11-alpine` stripped builder -> runtime).
  - Production Docker image shrunk from **642 MB down to 236 MB (-63.2%)**.
  - Runtime memory footprint optimized to **~53 MiB** (~29% of 180 MB memory cap).
* **Enhanced Password Security:**
  - Upgraded authentication to salted `scrypt` ($N=16384, r=8, p=1$).
  - Transparent in-flight migration for legacy SHA-256 hashes without user disruption.
* **Database Concurrency:**
  - Enforced SQLite Write-Ahead Logging (`PRAGMA journal_mode=WAL`) and `busy_timeout=30000` to prevent database lock contention.

#### Removed
* Legacy Jinja2 server-rendered HTML templates (`admin-dashboard/templates/`).
* Heavy runtime build utilities (pip, setuptools, wheel, C compiler headers) from the production container image.

---

## [1.0.0] - 2026-10-15

### Initial Release
* Baseline multi-container compose architecture with Pi-hole, Nextcloud, MariaDB, Redis, Samba, Navidrome, and Maloja.
* Initial FastAPI admin dashboard using server-rendered Jinja2 HTML templates.
* Shell-based installer (`install.sh`) for Debian and Ubuntu servers.
