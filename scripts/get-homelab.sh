#!/usr/bin/env bash
# ==============================================================================
# Homelab OS (HL-OS) — Cross-Distro Linux & macOS Dependency-First Bootstrapper
# Checks & installs ALL host/service dependencies FIRST (curl, openssl, git,
# python3, docker, docker compose, tailscale, cifs-utils), then installs the
# `homelab-os` CLI in an isolated venv and runs setup.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/beingbrijesh/homelab-framework/main/scripts/get-homelab.sh | bash
#   curl -fsSL https://raw.githubusercontent.com/beingbrijesh/homelab-framework/main/scripts/get-homelab.sh | bash -s -- -y --start
# ==============================================================================

set -euo pipefail

AUTO_YES=0
for arg in "$@"; do
    case "$arg" in
        -y|--yes) AUTO_YES=1 ;;
    esac
done

OS="$(uname -s)"
HOMELAB_CLI_VENV="${HOME}/.homelab/.cli-venv"
HOMELAB_PKG="${HOMELAB_PKG_SPEC:-homelab-os}"

log_info()  { echo "[INFO] $1"; }
log_ok()    { echo "[OK]   $1"; }
log_warn()  { echo "[WARN] $1"; }
log_err()   { echo "[ERR]  $1" >&2; }

run_priv() {
    if [ "$(id -u)" -eq 0 ]; then
        "$@"
    elif command -v sudo >/dev/null 2>&1; then
        sudo "$@"
    else
        "$@"
    fi
}

confirm_install() {
    local prompt="$1"
    if [ "$AUTO_YES" -eq 1 ]; then
        return 0
    fi
    if [ -t 0 ]; then
        read -r -p "${prompt} [Y/n] " ans
        ans=${ans:-Y}
        [[ "$ans" =~ ^[Yy]$ ]]
        return $?
    fi
    return 1
}

install_base_tools() {
    local missing=()
    for t in curl openssl git; do
        command -v "$t" >/dev/null 2>&1 || missing+=("$t")
    done
    if [ "$OS" = "Linux" ] && [ ! -x /sbin/mount.cifs ] && [ ! -x /usr/sbin/mount.cifs ] && ! command -v mount.cifs >/dev/null 2>&1; then
        missing+=("cifs-utils")
    fi

    if [ "${#missing[@]}" -eq 0 ]; then
        return 0
    fi

    log_warn "Missing base utilities: ${missing[*]}"
    confirm_install "Install missing base tools (${missing[*]}) now?" || { log_err "Required base tools missing."; exit 1; }

    if [ "$OS" = "Linux" ]; then
        if command -v apt-get >/dev/null 2>&1; then
            run_priv apt-get update && run_priv apt-get install -y ca-certificates "${missing[@]}"
        elif command -v dnf >/dev/null 2>&1; then
            run_priv dnf install -y ca-certificates "${missing[@]}"
        elif command -v yum >/dev/null 2>&1; then
            run_priv yum install -y ca-certificates "${missing[@]}"
        elif command -v pacman >/dev/null 2>&1; then
            run_priv pacman -Sy --noconfirm "${missing[@]}"
        elif command -v apk >/dev/null 2>&1; then
            run_priv apk add --no-cache ca-certificates "${missing[@]}"
        else
            log_err "No supported Linux package manager found to install: ${missing[*]}"
            exit 1
        fi
    elif [ "$OS" = "Darwin" ]; then
        command -v brew >/dev/null 2>&1 || { log_err "Homebrew is required on macOS: https://brew.sh"; exit 1; }
        for t in "${missing[@]}"; do
            [ "$t" = "openssl" ] && brew install openssl@3 || brew install "$t"
        done
    fi
}

check_python_ready() {
    command -v python3 >/dev/null 2>&1 && \
    python3 -c "import sys, venv; sys.exit(0 if sys.version_info >= (3, 9) else 1)" >/dev/null 2>&1
}

install_python() {
    log_warn "Python 3.9+ with venv support is missing."
    confirm_install "Install Python 3 now?" || { log_err "Python 3.9+ is required before installing Homelab OS."; exit 1; }

    if [ "$OS" = "Linux" ]; then
        if command -v apt-get >/dev/null 2>&1; then
            run_priv apt-get update && run_priv apt-get install -y python3 python3-venv python3-pip
        elif command -v dnf >/dev/null 2>&1; then
            run_priv dnf install -y python3 python3-pip
        elif command -v yum >/dev/null 2>&1; then
            run_priv yum install -y python3
        elif command -v pacman >/dev/null 2>&1; then
            run_priv pacman -S --noconfirm python
        elif command -v apk >/dev/null 2>&1; then
            run_priv apk add --no-cache python3 py3-pip
        else
            log_err "No supported Linux package manager found to install Python 3."
            exit 1
        fi
    elif [ "$OS" = "Darwin" ]; then
        command -v brew >/dev/null 2>&1 || { log_err "Homebrew is required on macOS: https://brew.sh"; exit 1; }
        brew install python@3.12
    else
        log_err "Unsupported OS for get-homelab.sh: $OS"
        exit 1
    fi
}

check_docker_ready() {
    command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1
}

install_docker() {
    log_warn "Docker Engine / Docker Compose v2 is missing."
    confirm_install "Install Docker & Docker Compose v2 now?" || { log_err "Docker & Compose v2 are required before Homelab OS setup."; exit 1; }

    if [ "$OS" = "Linux" ]; then
        if command -v curl >/dev/null 2>&1; then
            run_priv sh -c "curl -fsSL https://get.docker.com | sh"
        elif command -v apt-get >/dev/null 2>&1; then
            run_priv apt-get update && run_priv apt-get install -y docker.io docker-compose-v2
        elif command -v dnf >/dev/null 2>&1; then
            run_priv dnf install -y docker docker-compose-plugin
        elif command -v pacman >/dev/null 2>&1; then
            run_priv pacman -S --noconfirm docker docker-compose
        fi
        command -v systemctl >/dev/null 2>&1 && run_priv systemctl enable --now docker || true
        [ "$(id -u)" -ne 0 ] && command -v usermod >/dev/null 2>&1 && run_priv usermod -aG docker "${USER}" || true
    elif [ "$OS" = "Darwin" ]; then
        command -v brew >/dev/null 2>&1 || { log_err "Install Homebrew or Docker Desktop manually."; exit 1; }
        brew install --cask docker
        open -a Docker || true
    fi
}

check_tailscale_ready() {
    command -v tailscale >/dev/null 2>&1 || [ -x "/Applications/Tailscale.app/Contents/MacOS/Tailscale" ]
}

install_tailscale() {
    log_warn "Tailscale mesh VPN client is missing."
    confirm_install "Install Tailscale now?" || { log_err "Tailscale is required before Homelab OS setup."; exit 1; }

    if [ "$OS" = "Linux" ]; then
        run_priv sh -c "curl -fsSL https://tailscale.com/install.sh | sh"
        command -v systemctl >/dev/null 2>&1 && run_priv systemctl enable --now tailscaled || true
    elif [ "$OS" = "Darwin" ]; then
        command -v brew >/dev/null 2>&1 || { log_err "Install Homebrew or Tailscale manually."; exit 1; }
        brew install --cask tailscale
        open -a Tailscale || true
    fi
}

echo "=== Step 1/3: Checking & Installing All Host & Service Dependencies First ==="

install_base_tools
log_ok "Base utilities verified (curl, openssl, git)"

if ! check_python_ready; then
    install_python
fi
check_python_ready || { log_err "Python 3.9+ verification failed after installation."; exit 1; }
log_ok "Python ready: $(python3 --version)"

if ! check_docker_ready; then
    install_docker
fi
check_docker_ready || { log_err "Docker / Docker Compose verification failed after installation."; exit 1; }
log_ok "Docker ready: $(docker --version) | $(docker compose version)"

if ! docker info >/dev/null 2>&1; then
    if [ "$OS" = "Linux" ] && command -v systemctl >/dev/null 2>&1; then
        run_priv systemctl enable --now docker || true
    elif [ "$OS" = "Darwin" ]; then
        open -a Docker >/dev/null 2>&1 || true
        sleep 5
    fi
fi

if ! check_tailscale_ready; then
    install_tailscale
fi
check_tailscale_ready || { log_err "Tailscale verification failed after installation."; exit 1; }
log_ok "Tailscale installed"

echo "=== Step 2/3: Installing homelab-os CLI Package ==="
if command -v pipx >/dev/null 2>&1; then
    pipx install --force "${HOMELAB_PKG}"
    HOMELAB_BIN="$(command -v homelab || echo "${HOME}/.local/bin/homelab")"
else
    mkdir -p "$(dirname "${HOMELAB_CLI_VENV}")" "${HOME}/.local/bin"
    python3 -m venv "${HOMELAB_CLI_VENV}"
    "${HOMELAB_CLI_VENV}/bin/pip" install --upgrade pip >/dev/null
    "${HOMELAB_CLI_VENV}/bin/pip" install --upgrade "${HOMELAB_PKG}"
    ln -sf "${HOMELAB_CLI_VENV}/bin/homelab" "${HOME}/.local/bin/homelab"
    HOMELAB_BIN="${HOME}/.local/bin/homelab"
fi
log_ok "Installed CLI: ${HOMELAB_BIN}"

echo "=== Step 3/3: Running Homelab OS Setup ==="
exec "${HOMELAB_BIN}" init "$@"
