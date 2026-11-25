# Homelab OS Ultra-Lightweight Preact Dashboard Implementation Plan

> **For Antigravity:** REQUIRED SUB-SKILL: Load executing-plans to implement this plan task-by-task.

**Goal:** Migrate `/admin-dashboard` to an ultra-lightweight Preact + Vite + TypeScript + Tailwind CSS v4 SPA with an `iDraft`-inspired monochrome Bento aesthetic (Light/Dark toggle, subtle health accents, full-window layout) and a minimal-size multi-stage Alpine Docker image.

**Architecture:** Preact 10 SPA built in `admin-dashboard/frontend/` via Vite into `admin-dashboard/static/dist/`, served directly by the existing FastAPI backend (`app.py`) with 100% preserved API JSON contracts and auth redirects, packaged in a 3-stage `node:20-alpine` + `python:3.11-alpine` Dockerfile.

**Tech Stack:** Preact 10, TypeScript, Vite 6, Tailwind CSS v4, `lucide-preact`, custom zero-dependency SVG charts, FastAPI, Docker multi-stage Alpine build.

---

### Task 1: Scaffold Ultra-Lightweight Preact + Vite + Tailwind v4 Frontend
- Create `admin-dashboard/frontend/package.json`, `tsconfig.json`, `vite.config.ts`, `index.html`, `src/index.css`
- Configure Vite to output directly into `../static/dist` with clean asset hashing and dev proxy to `http://127.0.0.1:5001`
- Install dependencies and verify empty shell compiles cleanly

### Task 2: Core Types, API Client, Theme & Polling Hooks
- Create `src/types/api.ts` covering all 50+ FastAPI JSON contracts
- Create `src/api/client.ts` (typed fetch wrapper supporting `X-Background-Poll: 1`, JSON/Form auth, clean error handling)
- Create `src/hooks/useTheme.ts` (Light/Dark monochrome toggle persisted in `localStorage`)
- Create `src/hooks/useInterval.ts` & `src/utils/format.ts` (byte formatting, thermal sensor names, format badges)

### Task 3: Design System Primitives & Zero-Dependency SVG Charts
- Create `src/components/ui.tsx` (BentoCard, HeroCard, StatusBadge, PillButton, Modal, ConfirmDialog/Toast, ServiceIcon)
- Create `src/components/Charts.tsx`:
  - `SmoothLineChart` (monochrome bezier curve SVG chart with hover tooltip & legends — used for Overview telemetry & Network history)
  - `ConcentricRingGauge` (reference-inspired concentric circular SVG rings with center metric — used for SSD/HDD/RAM)
  - `HourlyBarChart` (monochrome 24-hour bar chart — used for Music Listening Clock)

### Task 4: Layout Shell & Authentication Views
- Create `src/components/Sidebar.tsx` (floating `rounded-3xl` monochrome pill sidebar with Monitor/Manage/Music/System groups, badge dots, mobile icon rail collapse)
- Create `src/components/TopBar.tsx` (greeting, live clock, context quick action pill, Refresh, Light/Dark theme toggle, Offline status pill, Admin avatar)
- Create `src/views/LoginView.tsx` & `src/views/RegisterView.tsx` (minimalist monochrome auth cards)

### Task 5: Monitor Views (Overview, Containers, Network)
- Create `src/views/OverviewView.tsx`
- Create `src/views/ContainersView.tsx` (with floating Container Logs modal & 3-dot action menus)
- Create `src/views/NetworkView.tsx`

### Task 6: Manage & Media Views (Users, Backup, Music, Download, Recommendations)
- Create `src/views/UsersView.tsx`
- Create `src/views/BackupView.tsx`
- Create `src/views/MusicView.tsx`
- Create `src/views/DownloadView.tsx`
- Create `src/views/RecommendationsView.tsx`

### Task 7: System Views (Updates, Power & Resources, Activity Log, Security, Settings)
- Create `src/views/UpdatesView.tsx`
- Create `src/views/PowerView.tsx`
- Create `src/views/LogsView.tsx`
- Create `src/views/SecurityView.tsx`
- Create `src/views/SettingsView.tsx`

### Task 8: Root App Wiring, Build & Bundle Size Verification
- Wire `src/App.tsx` and `src/main.tsx` with route matching (`/dashboard`, `/login`, `/register`), 8s background polling loop, PWA service worker registration, and online/offline listeners
- Build production bundle and verify bundle size (< 60 kB gzipped) and zero TypeScript errors

### Task 9: Backend FastAPI Integration & PWA Update
- Update `admin-dashboard/app.py`:
  - Serve built SPA `static/dist/index.html` on `/dashboard`, `/login`, `/register` (keeping exact auth redirects and form POST compatibility + adding `/api/auth/me` and JSON support on `/login` & `/register`)
  - Mount `/assets` from `static/dist/assets`
  - Remove Jinja2 runtime dependency from serving hot path
- Update `admin-dashboard/static/sw.js` and `static/manifest.json` (zero external CDN URLs, offline cache for compiled SPA)

### Task 10: Ultra-Minimal Multi-Stage Docker Image
- Split dev/test requirements (`requirements-dev.txt`) from production `requirements.txt` (remove `pytest`, `httpx`, `watchfiles`, `websockets`, `jinja2`)
- Rewrite `admin-dashboard/Dockerfile` to 3-stage `node:20-alpine` + `python:3.11-alpine` build with aggressive venv stripping (`pip`, `setuptools`, `wheel`, `__pycache__`, `*.pyc`, `tests`)
- Tighten `admin-dashboard/.dockerignore`

### Task 11: Testing & Visual Verification
- Update legacy raw-HTML assertions in `tests/test_api_contracts.py` and `tests/test_optimization_updates.py` for the new SPA while keeping all API/security tests intact
- Run full `pytest tests/ -v` and verify 100% pass
- Run frontend build & verify Docker build / image size (if Docker daemon is running) and inspect rendered UI in both Light and Dark modes
