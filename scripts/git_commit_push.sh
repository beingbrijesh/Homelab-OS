#!/usr/bin/env bash
# ==============================================================================
# Homelab-OS: 5-Stage Semantic Commit & GitHub Push Automation Script
# Remote: https://github.com/beingbrijesh/Homelab-OS.git
# Branch: main
# ==============================================================================

set -euo pipefail

# ANSI color codes
BOLD='\033[1m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
RED='\033[0;31m'
NC='\033[0m'

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo -e "${BOLD}${CYAN}======================================================${NC}"
echo -e "${BOLD}${CYAN}      Homelab-OS 5-Stage Commit & Push Automation      ${NC}"
echo -e "${BOLD}${CYAN}======================================================${NC}"
echo -e "Workspace: ${ROOT_DIR}\n"

# 1. Initialize Git repository if needed
if [ ! -d ".git" ]; then
    echo -e "${YELLOW}[1/7] Initializing Git repository...${NC}"
    git init -b main
else
    echo -e "${GREEN}[1/7] Git repository initialized.${NC}"
fi

# Ensure branch is main
git checkout -B main

# 2. Configure user identity if not already present
if [ -z "$(git config --get user.name 2>/dev/null || true)" ]; then
    git config user.name "Brijesh Yadav"
fi
if [ -z "$(git config --get user.email 2>/dev/null || true)" ]; then
    git config user.email "brijeshy9653@gmail.com"
fi

# Configure gh auth for git operations if gh CLI is available
if command -v gh >/dev/null 2>&1; then
    echo -e "${BLUE}[2/7] Ensuring GitHub CLI authentication for git...${NC}"
    gh auth setup-git 2>/dev/null || true
fi

# Helper function to stage and commit
commit_step() {
    local step_num="$1"
    local commit_title="$2"
    local commit_body="$3"
    shift 3
    local files=("$@")

    echo -e "\n${BOLD}${BLUE}--> [Commit ${step_num}/5] ${commit_title}${NC}"
    for file in "${files[@]}"; do
        if [ -e "$file" ] || [ -d "$file" ]; then
            git add "$file"
        fi
    done

    # Check if there are staged changes
    if git diff --cached --quiet; then
        echo -e "${YELLOW}    No new changes to commit for stage ${step_num}.${NC}"
    else
        git commit -m "${commit_title}" -m "${commit_body}"
        echo -e "${GREEN}    ✓ Successfully committed stage ${step_num}.${NC}"
    fi
}

# ==============================================================================
# Commit 1: Core Framework, Multi-Platform CLI & Service Manifests
# ==============================================================================
commit_step 1 \
"feat(core): initialize homelab-os v2 framework, CLI packaging, and service configurations" \
"Establish the foundational Homelab-OS architecture:
- Core manifests: package.json, pyproject.toml, setup.py, MANIFEST.in, .env.example, docker-compose.yml
- Turnkey CLI engine: bin/homelab.js wrapper and homelab_os Python package (sysinfo, workspace, deps, cli)
- Cross-platform distribution manifests: Homebrew formula and Scoop bucket manifest
- Service tuning: SMB3 durable shares, Nextcloud low-spec PHP tuning, Maloja patch
- Host installer scripts: install.sh, install.ps1, client_smb_watchdog.sh, transfer_to_server.py
- Continuous integration workflows: GitHub Actions CI and release automation" \
    ".dockerignore" \
    ".env.example" \
    ".github" \
    ".gitignore" \
    ".npmignore" \
    "bin" \
    "config" \
    "docker-compose.yml" \
    "homelab_os" \
    "install.sh" \
    "nextcloud" \
    "package.json" \
    "packaging" \
    "pyproject.toml" \
    "setup.py" \
    "MANIFEST.in" \
    "LICENSE" \
    "CONTRIBUTING.md" \
    "scripts/client_smb_watchdog.sh" \
    "scripts/get-homelab.sh" \
    "scripts/install.ps1" \
    "scripts/transfer_to_server.py"

# ==============================================================================
# Commit 2: Dashboard Backend & Control Plane Engines
# ==============================================================================
commit_step 2 \
"feat(dashboard-backend): modernize FastAPI control plane with WAL SQLite, eco-sleep, and telemetry engine" \
"Implement high-performance homelab control plane:
- app.py: FastAPI REST engine, dual-hash transparent authentication (SHA-256 to scrypt), session tokens
- System activity and event logger with deduplication, normalized event hashing, and resolution endpoints
- ops_resources.py: Hardware thermals polling, RAM/Disk metrics, and Wake-on-Request eco-sleep engine
- ops_updates.py: Zero-downtime container updating, registry version checking, and atomic rollbacks
- scripts/backup.sh: Atomic SQLite VACUUM INTO backup and snapshot rotation" \
    "admin-dashboard/app.py" \
    "admin-dashboard/ops_resources.py" \
    "admin-dashboard/ops_updates.py" \
    "admin-dashboard/scripts/backup.sh"

# ==============================================================================
# Commit 3: Ultra-Lightweight Preact Bento SPA & Static Assets
# ==============================================================================
commit_step 3 \
"feat(dashboard-ui): build ultra-lightweight Preact + Vite + Tailwind v4 monochrome Bento dashboard" \
"Migrate admin frontend from monolithic Jinja2 templates to high-contrast monochrome Bento SPA:
- Preact 10 + Vite 6 + Tailwind CSS v4 reactive client (~47 kB gzipped production bundle)
- Zero-dependency SVG charts: SmoothLineChart (dual-mode log/linear), ConcentricRingGauge, HourlyBarChart
- 13 comprehensive views: Overview, Containers, Storage, Network, Hardware, Power, Security, Logs, etc.
- System alert filter pills, resolved badges, and instant dismiss controls
- Responsive layout with scrollable power/memory/network panes and clean typography
- PWA manifest and service worker (homelab-pwa-v4) with cache-first asset delivery" \
    "admin-dashboard/frontend" \
    "admin-dashboard/static"

# ==============================================================================
# Commit 4: 3-Stage Alpine Docker Build & Runtime Dependencies
# ==============================================================================
commit_step 4 \
"build(docker): implement 3-stage minimal Alpine Dockerfile reducing image from 642MB to 236MB" \
"Optimize container build pipeline and reduce disk/memory footprint:
- 3-stage Alpine Dockerfile: node:20-alpine builder -> python:3.11-alpine stripped venv -> python:3.11-alpine runtime
- Strip pip, setuptools, wheel, bytecode, and C debug symbols from runtime virtualenv
- Alpine ffmpeg integration without X11/PulseAudio dependencies (-63.2% size reduction: 642MB -> 236MB)
- Split requirements.txt (production runtime: 6 packages) and requirements-dev.txt (test runner)
- admin-dashboard/.dockerignore to isolate build contexts" \
    "admin-dashboard/Dockerfile" \
    "admin-dashboard/.dockerignore" \
    "admin-dashboard/requirements.txt" \
    "admin-dashboard/requirements-dev.txt"

# ==============================================================================
# Commit 5: Test Suite, Architectural Specs & Verification Documentation
# ==============================================================================
commit_step 5 \
"test(contracts): add comprehensive regression suite and documentation for v2 control plane" \
"Ensure long-term reliability, architectural clarity, and verifiable deployments:
- 75 automated pytest regression tests covering auth migration, API contracts, JSON schemas, and SPA bundle
- Architectural specifications and implementation plans in docs/plans/
- ARCHITECTURE.md: Multi-tier defense-in-depth, storage topology, and update safety guarantees
- README.md: Comprehensive user manual, quickstart guides, and feature breakdown
- scripts/git_commit_push.sh: Automated 5-stage semantic commit pipeline" \
    "tests" \
    "docs" \
    "ARCHITECTURE.md" \
    "README.md" \
    "scripts/git_commit_push.sh"

# ==============================================================================
# Remote Configuration & Push
# ==============================================================================
echo -e "\n${BOLD}${CYAN}=== Configuring Remote and Pushing to GitHub ===${NC}"
REMOTE_URL="https://github.com/beingbrijesh/Homelab-OS.git"

if git remote get-url origin >/dev/null 2>&1; then
    echo -e "${YELLOW}Updating origin remote to ${REMOTE_URL}...${NC}"
    git remote set-url origin "$REMOTE_URL"
else
    echo -e "${GREEN}Adding origin remote ${REMOTE_URL}...${NC}"
    git remote add origin "$REMOTE_URL"
fi

echo -e "${BOLD}${BLUE}Pushing main branch to origin...${NC}"
git push -u origin main

echo -e "\n${BOLD}${GREEN}✔ Successfully committed 5 stages and pushed to https://github.com/beingbrijesh/Homelab-OS.git (main)${NC}\n"
git log --oneline -n 5
