# Cross-Platform Package Distribution & Dependency-First Setup Design

**Date:** 2026-11-12  
**Status:** Approved (Option A + Strict Dependency Pre-Check/Auto-Install Gate)  
**Target Platforms:** Linux (`x86_64` / `arm64`), macOS (`Intel` / `Apple Silicon`), Windows 10/11 (`x64` / `arm64`)

---

## 1. Decision Record

- **Chosen Architecture (Option A):** Pure-Python stdlib CLI (`homelab_os`, console entry point `homelab`) distributed across PyPI (`pip` / `pipx` / `uv`), npm (`npm install -g homelab-os` / `npx homelab-os`), Homebrew (`packaging/homebrew/homelab-os.rb`), Windows Scoop (`packaging/scoop/homelab-os.json`), and OS bootstrappers (`scripts/get-homelab.sh`, `scripts/install.ps1`), plus automated GitHub Actions release workflows.
- **Single Source of Truth:** Stack definitions (`docker-compose.yml`, `admin-dashboard/`, `config/`, `nextcloud/`, `scripts/`, `.env.example`) remain at repository root with zero duplicate copies committed to git. Packaging metadata (`setup.py` / `pyproject.toml` and `package.json`) bundles them at build/publish time.
- **Strict Dependency-First Gate:** Before copying any Homelab OS codebase files into the user workspace, generating `.env`, or launching containers, every entry point (`homelab init`, `bin/homelab.js`, `get-homelab.sh`, `install.ps1`) checks all required host dependencies (`Python 3.9+`, `Docker Engine`, `Docker Compose v2`, active Docker daemon), installs missing dependencies using the host OS package manager (`apt`/`dnf`/`pacman`/`apk`/`get.docker.com` on Linux, `brew` on macOS, `winget`/`scoop` on Windows), re-verifies them, and only then proceeds to Homelab OS setup.

---

## 2. CLI Surface (`homelab`)

| Command | Purpose |
| :--- | :--- |
| `homelab doctor` | Inspect OS, CPU, RAM, Python, Docker, Compose v2, daemon health, NIC, Tailscale IP, and host port bindings (`53`, `80`, `443`, `81`, `445`, `5001`, `8080`, `8081`, `4533`, `42010`); supports `--install-deps` / `-y`. |
| `homelab init` | Runs dependency check & auto-install gate first; then provisions `~/.homelab` (or `--dir PATH`), generates `.env`, creates service/storage directories, and optionally launches containers (`--start`). |
| `homelab up` | Starts stack (`docker compose up -d [--build]`) after verifying workspace + dependencies. |
| `homelab down` | Stops stack cleanly (`docker compose down`). |
| `homelab restart [service]` | Restarts all services or a single named container. |
| `homelab status` | Prints container states and resolved service URLs. |
| `homelab logs [service]` | Tails logs from Docker Compose services. |
| `homelab backup` | Runs `/scripts/backup.sh` inside `admin-dashboard` (or host fallback). |
| `homelab upgrade` | Refreshes framework files from the installed package into `--dir` without overwriting `.env`, databases, or storage, then recreates containers. |

---

## 3. Distribution Channels

1. **PyPI (`pipx install homelab-os` / `pip install homelab-os`):** Stdlib-only Python >= 3.9 wheel (`setup.py` bundles stack files into `homelab_os/bundle/`).
2. **npm (`npm install -g homelab-os` / `npx homelab-os`):** `package.json` + `bin/homelab.js` verifies/auto-installs Python 3.9+ first, then invokes `homelab_os` with stack assets packaged at npm root.
3. **Homebrew (`brew install <owner>/tap/homelab-os`):** Formula using `Language::Python::Virtualenv` and runtime `docker` / `docker-compose` dependencies.
4. **Windows (`scoop` / `install.ps1`):** Scoop manifest + PowerShell bootstrapper verifying/installing `Python.Python.3.12` and `Docker.DockerDesktop` via `winget` before running `homelab init`.
5. **Linux / macOS Bootstrapper (`scripts/get-homelab.sh`) & Local Script (`install.sh`):** Checks/installs dependencies first, sets up isolated CLI venv (`~/.homelab/.cli-venv`), and invokes `homelab init`.
6. **GitHub Actions (`.github/workflows/release.yml`, `.github/workflows/ci.yml`):** Automated `pytest` + packaging + `docker compose config` verification on PRs/pushes and tag-based publishing (`v*`) to PyPI (OIDC), npm, and GitHub Releases.
