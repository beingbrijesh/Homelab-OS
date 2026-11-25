# Cross-Platform Package Distribution Implementation Plan

> **For Antigravity:** Load executing-plans (or execute step-by-step with verification) to build Option A cleanly with strict dependency-first setup gating.

**Goal:** Package Homelab OS as `homelab-os` (`homelab` CLI) installable via PyPI (`pip`/`pipx`), npm (`npm`/`npx`), Homebrew, Scoop, and Linux/macOS/Windows one-liners, with a mandatory dependency check & auto-install gate running before any Homelab OS workspace setup.

**Architecture:** Stdlib-only Python >= 3.9 package (`homelab_os/`) built via `setuptools` (`pyproject.toml` + `setup.py` `build_py` hook bundling root stack assets cleanly at build time), paired with a Node `bin/homelab.js` launcher, Homebrew Ruby formula, Scoop JSON manifest, `get-homelab.sh` / `install.ps1` bootstrappers, and GitHub Actions CI/release workflows.

**Tech Stack:** Python 3.9+ stdlib, setuptools/wheel, Node.js (`bin/homelab.js`), POSIX Shell / PowerShell, Homebrew Ruby DSL, Scoop JSON, GitHub Actions, pytest.

---

### Task 1: Dependency Checker & Auto-Installer Module (`homelab_os/deps.py`) + Tests
- **Files:**
  - Create: `homelab_os/__init__.py`
  - Create: `homelab_os/deps.py`
  - Create: `tests/test_cli_packaging.py`
- **Behavior:**
  - `check_dependencies()` probes Python version, `docker`, `docker compose` v2, active Docker daemon (`docker info`), and optional tools (`git`, `openssl`, `tailscale`).
  - `detect_package_manager(os_name)` selects OS package manager (`apt-get`, `dnf`, `yum`, `pacman`, `apk`, `get.docker.com` on Linux; `brew` on macOS; `winget`, `scoop`, `choco` on Windows).
  - `ensure_dependencies(auto_install=False, interactive=True, skip_daemon=False, runner=...)` refuses to proceed if any required dependency is missing when `auto_install=False` (or user declines), runs OS install commands when approved/auto, re-verifies every dependency, and returns pass/fail cleanly.
- **Verification:** `pytest tests/test_cli_packaging.py -v`

### Task 2: Cross-Platform System Probe, Workspace Provisioner & CLI (`homelab_os/sysinfo.py`, `homelab_os/workspace.py`, `homelab_os/cli.py`, `homelab_os/__main__.py`)
- **Files:**
  - Create: `homelab_os/sysinfo.py`
  - Create: `homelab_os/workspace.py`
  - Create: `homelab_os/cli.py`
  - Create: `homelab_os/__main__.py`
  - Modify: `tests/test_cli_packaging.py`
- **Behavior:**
  - Cross-platform CPU, RAM (`sysctl` / `/proc/meminfo` / Windows `GlobalMemoryStatusEx`), default NIC, LAN IP, Tailscale IP, timezone, and socket bind port-conflict checks (`53`, `80`, `443`, `81`, `445`, `5001`, `8080`, `8081`, `4533`, `42010`, including Windows `LanmanServer` / Ubuntu `systemd-resolved` hints).
  - `init` runs `ensure_dependencies()` **first**; aborts cleanly before creating `--dir` or `.env` if dependency gate fails.
  - Copies bundled stack assets into `--dir` (default `~/.homelab`), writes `.env` (`0o600`), creates directories (`admin-dashboard/{data,logs}`, `nextcloud/{data,config,apps}`, `nginx/{data,letsencrypt}`, `navidrome/data`, `maloja/data`, `${STORAGE_PATH}/{music/_playlists,snapshots}`), and supports `--start`, `--yes`, `--force`, `--no-install-deps`, `--skip-daemon-check`.
  - Implements `doctor`, `up`, `down`, `restart`, `status`, `logs`, `backup`, `upgrade`.
- **Verification:** `pytest tests/test_cli_packaging.py -v`

### Task 3: Python Package Metadata (`pyproject.toml`, `setup.py`, `MANIFEST.in`)
- **Files:**
  - Create: `pyproject.toml`
  - Create: `setup.py`
  - Create: `MANIFEST.in`
- **Behavior:**
  - `setup.py` `build_py` copies canonical stack directories/files from repo root into `homelab_os/bundle/` inside build artifacts (skipping runtime `.env`, `*.db`, logs, `__pycache__/`) without duplicating files in git.
  - Verify wheel build & isolated venv install (`python3 -m venv` + `pip install --no-build-isolation --no-deps .` + `homelab --help` + `homelab init` end-to-end in `/tmp`).

### Task 4: npm Wrapper (`package.json`, `.npmignore`, `bin/homelab.js`)
- **Files:**
  - Create: `package.json`
  - Create: `.npmignore`
  - Create: `bin/homelab.js`
  - Modify: `tests/test_cli_packaging.py`
- **Behavior:**
  - `bin/homelab.js` checks Python >= 3.9 BEFORE running `homelab_os`; if missing, installs Python via OS package manager (`apt`/`dnf`/`pacman`/`apk`/`brew`/`winget`) on confirmation or `-y`, re-verifies, and delegates all CLI args to `homelab_os` with `HOMELAB_STACK_SRC` pointing to package root.
  - Verify `npm pack --dry-run` and execute `node bin/homelab.js --help` & `doctor` cleanly.

### Task 5: Homebrew Formula, Windows Scoop Manifest, OS Bootstrappers & Unified `install.sh`
- **Files:**
  - Create: `packaging/homebrew/homelab-os.rb`
  - Create: `packaging/scoop/homelab-os.json`
  - Create: `scripts/get-homelab.sh`
  - Create: `scripts/install.ps1`
  - Modify: `install.sh` (ensure dependency check/auto-install gate runs before setup when used standalone)
- **Behavior:**
  - All bootstrappers enforce dependency check + auto-install first before installing `homelab-os` and setting up Homelab OS.
  - Syntax check (`bash -n`, `ruby -c` if available, `python3 -m json.tool`).

### Task 6: GitHub Actions CI/Release Workflows & Documentation Updates
- **Files:**
  - Create: `.github/workflows/ci.yml`
  - Create: `.github/workflows/release.yml`
  - Modify: `.gitignore` (add `dist/`, `build/`, `*.egg-info/`, `node_modules/`, `homelab_os/bundle/`)
  - Modify: `README.md`, `CONTRIBUTING.md`, `scripts/transfer_to_server.py`
- **Verification:** Full test suite (`tests/test_api_contracts.py` + `tests/test_cli_packaging.py`), `grep` personal-data leak scan, `npm pack --dry-run`, Python isolated venv build+install+init test, `docker compose config --quiet`.
