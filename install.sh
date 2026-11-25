#!/usr/bin/env bash
# ==============================================================================
# Homelab OS (HL-OS) — Unified Turnkey Installer & CLI Setup Engine
# Optimized for: Low-Spec Hardware (2-Core Celeron / 4-8GB RAM) to Multi-Core Rigs
# Zero-AI Footprint · 100% Deterministic · Tailscale & SMB3 Durable Handles
# ==============================================================================

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

# ── CLI Defaults ──────────────────────────────────────────────────────────────
NON_INTERACTIVE=0
FORCE_ENV=0
AUTO_START=0
CHECK_ONLY=0
OPT_DOMAIN=""
OPT_USER=""
OPT_PASSWORD=""
OPT_SMB_USER=""
OPT_STORAGE=""
OPT_IFACE=""
OPT_ZT_EMAILS=""
GENERATED_NEW_ENV=0

# Detected / Configured Globals
OS=""
ARCH=""
CPU_CORES=2
TOTAL_RAM_MB=4096
DOCKER_COMPOSE_CMD=""
TAILSCALE_IP=""
LAN_IP=""
NET_IFACE=""
DETECTED_TZ="UTC"
STORAGE_BASE="${SCRIPT_DIR}/storage"
DOMAIN="homelab.local"
ADMIN_USER="admin"
ADMIN_PW=""
SMB_USER="homelab"
AUTO_SMB_PW=""
AUTO_PIHOLE_PW=""
AUTO_MALOJA_PW=""
AUTO_MALOJA_KEY=""
CF_ZT_ENABLED="false"
ZERO_TRUST_EMAILS=""

log_info()    { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[OK]${NC} $1"; }
log_warn()    { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error()   { echo -e "${RED}[ERROR]${NC} $1"; }

usage() {
    cat << EOF
Homelab OS (HL-OS) — Turnkey CLI Installer

Usage:
  ./install.sh [OPTIONS]

Options:
  -y, --yes                     Non-interactive turnkey setup (accept smart defaults)
      --start                   Build and launch the Docker Compose stack after setup
      --force                   Overwrite existing .env cleanly (creates a timestamped backup)
      --check                   Run hardware, Docker, network, and port-conflict checks only
      --storage PATH            Storage path for shares, music & backups (default: ./storage)
      --domain HOSTNAME         Primary domain or hostname (default: homelab.local)
      --user USERNAME           Admin Dashboard & Nextcloud username (default: admin)
      --password PASSWORD       Admin Dashboard & Nextcloud password (auto-generated if omitted)
      --smb-user USERNAME       Samba SMB3 username (default: homelab)
      --iface INTERFACE         Host network interface for telemetry (auto-detected if omitted)
      --zero-trust-email EMAILS Comma-separated emails to enable Cloudflare Zero Trust middleware
  -h, --help                    Show this help message and exit

Examples:
  # Interactive wizard:
  ./install.sh

  # Zero-touch one-command server install and launch:
  ./install.sh -y --storage /mnt/storage --start

  # Custom domain, user, and Cloudflare Zero Trust access:
  ./install.sh -y --domain cloud.example.com --user opsadmin --zero-trust-email "me@example.com" --start
EOF
}

parse_args() {
    while [ $# -gt 0 ]; do
        case "$1" in
            -y|--yes)
                NON_INTERACTIVE=1
                ;;
            --force)
                FORCE_ENV=1
                ;;
            --start)
                AUTO_START=1
                ;;
            --check)
                CHECK_ONLY=1
                ;;
            --storage)
                [ $# -lt 2 ] && { log_error "--storage requires a path argument"; exit 1; }
                OPT_STORAGE="$2"; shift
                ;;
            --storage=*)
                OPT_STORAGE="${1#*=}"
                ;;
            --domain)
                [ $# -lt 2 ] && { log_error "--domain requires a hostname argument"; exit 1; }
                OPT_DOMAIN="$2"; shift
                ;;
            --domain=*)
                OPT_DOMAIN="${1#*=}"
                ;;
            --user)
                [ $# -lt 2 ] && { log_error "--user requires a username argument"; exit 1; }
                OPT_USER="$2"; shift
                ;;
            --user=*)
                OPT_USER="${1#*=}"
                ;;
            --password)
                [ $# -lt 2 ] && { log_error "--password requires a value"; exit 1; }
                OPT_PASSWORD="$2"; shift
                ;;
            --password=*)
                OPT_PASSWORD="${1#*=}"
                ;;
            --smb-user)
                [ $# -lt 2 ] && { log_error "--smb-user requires a username argument"; exit 1; }
                OPT_SMB_USER="$2"; shift
                ;;
            --smb-user=*)
                OPT_SMB_USER="${1#*=}"
                ;;
            --iface)
                [ $# -lt 2 ] && { log_error "--iface requires a network interface name"; exit 1; }
                OPT_IFACE="$2"; shift
                ;;
            --iface=*)
                OPT_IFACE="${1#*=}"
                ;;
            --zero-trust-email)
                [ $# -lt 2 ] && { log_error "--zero-trust-email requires an email or comma-separated list"; exit 1; }
                OPT_ZT_EMAILS="$2"; shift
                ;;
            --zero-trust-email=*)
                OPT_ZT_EMAILS="${1#*=}"
                ;;
            -h|--help)
                usage
                exit 0
                ;;
            *)
                log_error "Unknown option: $1"
                echo ""
                usage
                exit 1
                ;;
        esac
        shift
    done
}

print_banner() {
    if [ -t 1 ] && [ "${NON_INTERACTIVE}" -eq 0 ]; then
        clear 2>/dev/null || true
    fi
    echo -e "${CYAN}${BOLD}"
    cat << "EOF"
  _    _                      _       _        ____   _____ 
 | |  | |                    | |     | |      / __ \ / ____|
 | |__| | ___  _ __ ___   ___| | __ _| |__   | |  | | (___  
 |  __  |/ _ \| '_ ` _ \ / _ \ |/ _` | '_ \  | |  | |\___ \ 
 | |  | | (_) | | | | | |  __/ | (_| | |_) | | |__| |____) |
 |_|  |_|\___/|_| |_| |_|\___|_|\__,_|_.__/   \____/|_____/ 
EOF
    echo -e "${NC}"
    echo -e "${BLUE}${BOLD}  Turnkey Personal Cloud & Resilient Media Engine (FastAPI Edition)${NC}"
    echo -e "${YELLOW}  Ultra-Low Memory Profile: ~2.2GB total container footprint${NC}"
    echo -e "${YELLOW}  Zero-AI: No Ollama/LLM overhead · 100% CPU dedicated to services${NC}"
    echo "=============================================================================="
    echo ""
}

generate_password() {
    if command -v openssl >/dev/null 2>&1; then
        openssl rand -base64 24 | tr -dc 'a-zA-Z0-9' | head -c 16
    elif command -v python3 >/dev/null 2>&1; then
        python3 -c "import secrets, string; chars = string.ascii_letters + string.digits; print(''.join(secrets.choice(chars) for _ in range(16)))"
    else
        LC_ALL=C tr -dc 'a-zA-Z0-9' < /dev/urandom | head -c 16
    fi
}

generate_hex_secret() {
    if command -v openssl >/dev/null 2>&1; then
        openssl rand -hex 32
    elif command -v python3 >/dev/null 2>&1; then
        python3 -c "import secrets; print(secrets.token_hex(32))"
    else
        generate_password
    fi
}

get_env_value() {
    local key="$1"
    local file="${2:-.env}"
    [ -f "$file" ] || return 0
    awk -v k="$key" '
        $0 ~ "^" k "=" {
            val = substr($0, length(k) + 2)
            gsub(/^["'\'']|["'\'']$/, "", val)
            print val
            exit
        }
    ' "$file"
}

detect_network_and_tz() {
    # Primary Network Interface
    if [ -n "${OPT_IFACE}" ]; then
        NET_IFACE="${OPT_IFACE}"
    elif [ "${OS}" = "Darwin" ]; then
        NET_IFACE=$(route -n get default 2>/dev/null | awk '/interface:/ {print $2; exit}' || true)
        NET_IFACE=${NET_IFACE:-en0}
    else
        NET_IFACE=$(ip -4 route show default 2>/dev/null | awk '/default/ {for (i=1; i<=NF; i++) if ($i=="dev") {print $(i+1); exit}}' || true)
        NET_IFACE=${NET_IFACE:-eth0}
    fi

    # LAN IP
    if [ "${OS}" = "Darwin" ]; then
        LAN_IP=$(ipconfig getifaddr "${NET_IFACE}" 2>/dev/null || true)
    else
        LAN_IP=$(ip -4 addr show "${NET_IFACE}" 2>/dev/null | awk '/inet / {sub(/\/.*/, "", $2); print $2; exit}' || true)
        if [ -z "${LAN_IP}" ]; then
            LAN_IP=$(hostname -I 2>/dev/null | awk '{print $1}' || true)
        fi
    fi

    # Tailscale VPN IP (POSIX awk — no GNU grep -P)
    TAILSCALE_IP=""
    if command -v tailscale >/dev/null 2>&1; then
        TAILSCALE_IP=$(tailscale ip -4 2>/dev/null | head -n 1 || true)
    fi
    if [ -z "${TAILSCALE_IP}" ]; then
        if [ "${OS}" = "Darwin" ]; then
            TAILSCALE_IP=$(ifconfig 2>/dev/null | awk '/inet 100\./ {print $2; exit}' || true)
        else
            TAILSCALE_IP=$(ip -4 addr show tailscale0 2>/dev/null | awk '/inet / {sub(/\/.*/, "", $2); print $2; exit}' || true)
        fi
    fi

    # Host Timezone
    if [ -f /etc/timezone ]; then
        DETECTED_TZ=$(tr -d '[:space:]' < /etc/timezone 2>/dev/null || echo "UTC")
    elif command -v timedatectl >/dev/null 2>&1; then
        DETECTED_TZ=$(timedatectl show -p Timezone --value 2>/dev/null || echo "UTC")
    elif [ -L /etc/localtime ]; then
        DETECTED_TZ=$(readlink /etc/localtime 2>/dev/null | sed 's#.*/zoneinfo/##' || echo "UTC")
    else
        DETECTED_TZ="UTC"
    fi
    DETECTED_TZ=${DETECTED_TZ:-UTC}
}

is_port_in_use() {
    local port="$1"
    if command -v ss >/dev/null 2>&1; then
        ss -H -tuln 2>/dev/null | awk '{print $5}' | grep -qE "[:.]${port}$"
        return $?
    elif command -v lsof >/dev/null 2>&1; then
        lsof -nP -iTCP:"${port}" -sTCP:LISTEN >/dev/null 2>&1 || \
        lsof -nP -iUDP:"${port}" >/dev/null 2>&1
        return $?
    fi
    return 1
}

check_port_conflicts() {
    log_info "Checking common host port bindings..."
    local warnings=0

    if is_port_in_use 53; then
        warnings=$((warnings + 1))
        log_warn "Port 53 (DNS) is already in use on this host."
        echo "         → On Ubuntu/Debian, disable systemd-resolved's stub listener before starting Pi-hole:"
        echo "           sudo sed -i 's/^#*DNSStubListener=.*/DNSStubListener=no/' /etc/systemd/resolved.conf && sudo systemctl restart systemd-resolved"
    fi

    if is_port_in_use 445; then
        warnings=$((warnings + 1))
        log_warn "Port 445 (SMB) is already in use (host smbd may be running)."
        echo "         → Either stop host Samba (sudo systemctl disable --now smbd) so the container serves SMB3,"
        echo "           or comment out the 'samba:' service in docker-compose.yml if keeping host Samba."
    fi

    for p in 80 443 81 5001 8080 8081 4533 42010; do
        if is_port_in_use "${p}"; then
            warnings=$((warnings + 1))
            log_warn "Port ${p} is already bound on this host. Adjust port mappings in .env / docker-compose.yml if needed."
        fi
    done

    if [ "${warnings}" -eq 0 ]; then
        log_success "All default service ports (53, 80, 443, 445, 5001, 8080, 8081, 4533, 42010) appear free."
    fi
}

check_prerequisites() {
    log_info "Detecting system hardware and environment..."

    OS="$(uname -s)"
    ARCH="$(uname -m)"
    log_info "OS: ${OS} (${ARCH})"

    if [ "${OS}" = "Darwin" ]; then
        CPU_CORES=$(sysctl -n hw.ncpu 2>/dev/null || echo 2)
        TOTAL_RAM_BYTES=$(sysctl -n hw.memsize 2>/dev/null || echo 4294967296)
        TOTAL_RAM_MB=$(( TOTAL_RAM_BYTES / 1024 / 1024 ))
    elif [ -f /proc/meminfo ]; then
        CPU_CORES=$(nproc 2>/dev/null || echo 2)
        TOTAL_RAM_KB=$(awk '/MemTotal/ {print $2; exit}' /proc/meminfo 2>/dev/null || echo 4194304)
        TOTAL_RAM_MB=$(( TOTAL_RAM_KB / 1024 ))
    fi

    echo -e "  → Detected CPU Cores : ${BOLD}${CPU_CORES}${NC}"
    echo -e "  → Detected Total RAM : ${BOLD}${TOTAL_RAM_MB} MB${NC}"

    if [ "${TOTAL_RAM_MB}" -lt 3800 ]; then
        log_warn "Host RAM is below 4GB (${TOTAL_RAM_MB}MB). Homelab OS low-spec tuning will run in lean mode."
    else
        log_success "Hardware memory profile fits comfortably within Homelab OS ~2.2GB envelope."
    fi

    # Strict Dependency Check & Auto-Install Gate (curl, openssl, git, tailscale, cifs-utils, Docker + Compose v2)
    run_priv_cmd() {
        if [ "$(id -u)" -eq 0 ]; then "$@"; elif command -v sudo >/dev/null 2>&1; then sudo "$@"; else "$@"; fi
    }

    ensure_base_and_service_tools() {
        local missing=()
        for t in curl openssl git; do
            command -v "$t" >/dev/null 2>&1 || missing+=("$t")
        done
        if [ "${OS}" = "Linux" ] && [ ! -x /sbin/mount.cifs ] && [ ! -x /usr/sbin/mount.cifs ] && ! command -v mount.cifs >/dev/null 2>&1; then
            missing+=("cifs-utils")
        fi
        if [ "${#missing[@]}" -gt 0 ]; then
            local confirm_base="Y"
            if [ "${NON_INTERACTIVE}" -eq 0 ] && [ -t 0 ]; then
                read -r -p "Missing host utilities (${missing[*]}). Install automatically now? [Y/n] " confirm_base
                confirm_base=${confirm_base:-Y}
            fi
            [[ "$confirm_base" =~ ^[Yy]$ ]] || { log_error "Missing required utilities: ${missing[*]}"; exit 1; }
            if [ "${OS}" = "Linux" ]; then
                if command -v apt-get >/dev/null 2>&1; then
                    run_priv_cmd apt-get update && run_priv_cmd apt-get install -y ca-certificates "${missing[@]}"
                elif command -v dnf >/dev/null 2>&1; then
                    run_priv_cmd dnf install -y ca-certificates "${missing[@]}"
                elif command -v yum >/dev/null 2>&1; then
                    run_priv_cmd yum install -y ca-certificates "${missing[@]}"
                elif command -v pacman >/dev/null 2>&1; then
                    run_priv_cmd pacman -Sy --noconfirm "${missing[@]}"
                elif command -v apk >/dev/null 2>&1; then
                    run_priv_cmd apk add --no-cache ca-certificates "${missing[@]}"
                fi
            elif [ "${OS}" = "Darwin" ] && command -v brew >/dev/null 2>&1; then
                for t in "${missing[@]}"; do
                    [ "$t" = "openssl" ] && brew install openssl@3 || brew install "$t"
                done
            fi
        fi

        if ! command -v tailscale >/dev/null 2>&1 && [ ! -x "/Applications/Tailscale.app/Contents/MacOS/Tailscale" ]; then
            local confirm_ts="Y"
            if [ "${NON_INTERACTIVE}" -eq 0 ] && [ -t 0 ]; then
                read -r -p "Missing Tailscale mesh VPN client. Install automatically now? [Y/n] " confirm_ts
                confirm_ts=${confirm_ts:-Y}
            fi
            [[ "$confirm_ts" =~ ^[Yy]$ ]] || { log_error "Tailscale is required before Homelab OS setup."; exit 1; }
            if [ "${OS}" = "Linux" ]; then
                run_priv_cmd sh -c "curl -fsSL https://tailscale.com/install.sh | sh"
                command -v systemctl >/dev/null 2>&1 && run_priv_cmd systemctl enable --now tailscaled || true
            elif [ "${OS}" = "Darwin" ] && command -v brew >/dev/null 2>&1; then
                brew install --cask tailscale
                open -a Tailscale >/dev/null 2>&1 || true
            fi
        fi
    }

    ensure_base_and_service_tools

    install_missing_docker_deps() {
        local confirm="Y"
        if [ "${NON_INTERACTIVE}" -eq 0 ] && [ -t 0 ]; then
            read -r -p "Missing Docker / Docker Compose v2. Install automatically now? [Y/n] " confirm
            confirm=${confirm:-Y}
        fi
        if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
            log_error "Docker and Docker Compose v2 are required before Homelab OS setup."
            exit 1
        fi
        if [ "${OS}" = "Linux" ]; then
            if command -v curl >/dev/null 2>&1; then
                run_priv_cmd sh -c "curl -fsSL https://get.docker.com | sh"
            elif command -v apt-get >/dev/null 2>&1; then
                run_priv_cmd apt-get update && run_priv_cmd apt-get install -y docker.io docker-compose-v2
            elif command -v dnf >/dev/null 2>&1; then
                run_priv_cmd dnf install -y docker docker-compose-plugin
            elif command -v pacman >/dev/null 2>&1; then
                run_priv_cmd pacman -S --noconfirm docker docker-compose
            fi
            command -v systemctl >/dev/null 2>&1 && run_priv_cmd systemctl enable --now docker || true
            [ "$(id -u)" -ne 0 ] && command -v usermod >/dev/null 2>&1 && run_priv_cmd usermod -aG docker "${USER}" || true
        elif [ "${OS}" = "Darwin" ] && command -v brew >/dev/null 2>&1; then
            brew install --cask docker
            open -a Docker >/dev/null 2>&1 || true
        else
            log_error "No supported package manager found to auto-install Docker."
            exit 1
        fi
    }

    if ! command -v docker >/dev/null 2>&1 || { ! docker compose version >/dev/null 2>&1 && ! command -v docker-compose >/dev/null 2>&1; }; then
        log_warn "Required dependencies missing (Docker CLI / Docker Compose)."
        install_missing_docker_deps
    fi

    if ! command -v docker >/dev/null 2>&1; then
        log_error "Docker verification failed after installation attempt."
        exit 1
    fi
    log_success "Docker CLI verified: $(docker --version)"

    # Compose v2/v1 detection
    if docker compose version >/dev/null 2>&1; then
        DOCKER_COMPOSE_CMD="docker compose"
    elif command -v docker-compose >/dev/null 2>&1; then
        DOCKER_COMPOSE_CMD="docker-compose"
    else
        log_error "Docker Compose verification failed after installation attempt."
        exit 1
    fi
    log_success "Docker Compose verified: $(${DOCKER_COMPOSE_CMD} version)"

    detect_network_and_tz
    log_success "Primary network interface: ${BOLD}${NET_IFACE}${NC} (Timezone: ${BOLD}${DETECTED_TZ}${NC})"

    if [ -n "${LAN_IP}" ]; then
        log_success "LAN IP detected: ${BOLD}${LAN_IP}${NC}"
    fi
    if [ -n "${TAILSCALE_IP}" ]; then
        log_success "Tailscale VPN IP detected: ${BOLD}${TAILSCALE_IP}${NC}"
    else
        log_info "No active Tailscale IP detected (optional; install Tailscale anytime for mesh VPN access)."
    fi

    check_port_conflicts
}

build_trusted_domains() {
    local items=("localhost" "127.0.0.1")
    local candidate
    for candidate in "${LAN_IP}" "${TAILSCALE_IP}" "${DOMAIN}"; do
        if [ -n "${candidate}" ]; then
            local seen=0
            local existing
            for existing in "${items[@]}"; do
                if [ "${existing}" = "${candidate}" ]; then
                    seen=1
                    break
                fi
            done
            if [ "${seen}" -eq 0 ]; then
                items+=("${candidate}")
            fi
        fi
    done
    printf '%s' "${items[*]}"
}

configure_environment() {
    log_info "Configuring environment and credentials..."

    if [ -f .env ]; then
        if [ "${FORCE_ENV}" -eq 1 ]; then
            local bak_file=".env.bak.$(date +%s)"
            cp .env "${bak_file}"
            chmod 600 "${bak_file}"
            log_info "Backed up existing .env to ${bak_file} (--force)"
        elif [ "${NON_INTERACTIVE}" -eq 1 ]; then
            log_info "Existing .env found and keeping it in non-interactive mode (pass --force to regenerate)."
            STORAGE_BASE="$(get_env_value STORAGE_PATH .env)"
            STORAGE_BASE="${STORAGE_BASE:-./storage}"
            ADMIN_USER="$(get_env_value ADMIN_DEFAULT_USER .env)"
            ADMIN_USER="${ADMIN_USER:-admin}"
            SMB_USER="$(get_env_value SAMBA_USER .env)"
            SMB_USER="${SMB_USER:-homelab}"
            return 0
        else
            log_warn "An existing .env file was found."
            read -r -p "Do you want to keep existing .env? [Y/n] " keep_env
            keep_env=${keep_env:-Y}
            if [[ "$keep_env" =~ ^[Yy]$ ]]; then
                log_info "Keeping existing .env file."
                STORAGE_BASE="$(get_env_value STORAGE_PATH .env)"
                STORAGE_BASE="${STORAGE_BASE:-./storage}"
                ADMIN_USER="$(get_env_value ADMIN_DEFAULT_USER .env)"
                ADMIN_USER="${ADMIN_USER:-admin}"
                SMB_USER="$(get_env_value SAMBA_USER .env)"
                SMB_USER="${SMB_USER:-homelab}"
                return 0
            fi
            local bak_file=".env.bak.$(date +%s)"
            cp .env "${bak_file}"
            chmod 600 "${bak_file}"
            log_info "Backed up old .env to ${bak_file}"
        fi
    fi

    local default_domain="${OPT_DOMAIN:-homelab.local}"
    local default_user="${OPT_USER:-admin}"
    local default_smb_user="${OPT_SMB_USER:-homelab}"
    local default_storage="${OPT_STORAGE:-./storage}"

    local auto_admin_pw="${OPT_PASSWORD:-$(generate_password)}"
    local auto_db_pw="$(generate_password)"
    local auto_root_db_pw="$(generate_password)"
    local auto_redis_pw="$(generate_password)"
    local auto_secret="$(generate_hex_secret)"
    AUTO_PIHOLE_PW="$(generate_password)"
    AUTO_SMB_PW="$(generate_password)"
    AUTO_MALOJA_PW="$(generate_password)"
    AUTO_MALOJA_KEY="$(generate_hex_secret)"

    if [ "${NON_INTERACTIVE}" -eq 1 ]; then
        DOMAIN="${default_domain}"
        ADMIN_USER="${default_user}"
        ADMIN_PW="${auto_admin_pw}"
        SMB_USER="${default_smb_user}"
        STORAGE_BASE="${default_storage}"
    else
        echo ""
        echo -e "${BOLD}Setup Wizard Configuration:${NC}"

        if [ -z "${OPT_DOMAIN}" ]; then
            read -r -p "Domain or Hostname [${default_domain}]: " input_domain
            DOMAIN=${input_domain:-$default_domain}
        else
            DOMAIN="${OPT_DOMAIN}"
        fi

        if [ -z "${OPT_USER}" ]; then
            read -r -p "Admin Username [${default_user}]: " input_user
            ADMIN_USER=${input_user:-$default_user}
        else
            ADMIN_USER="${OPT_USER}"
        fi

        if [ -z "${OPT_PASSWORD}" ]; then
            read -r -p "Admin Password [Enter to auto-generate: ${auto_admin_pw}]: " input_pw
            ADMIN_PW=${input_pw:-$auto_admin_pw}
        else
            ADMIN_PW="${OPT_PASSWORD}"
        fi

        if [ -z "${OPT_SMB_USER}" ]; then
            read -r -p "Samba SMB Username [${default_smb_user}]: " input_smb
            SMB_USER=${input_smb:-$default_smb_user}
        else
            SMB_USER="${OPT_SMB_USER}"
        fi

        if [ -z "${OPT_STORAGE}" ]; then
            read -r -p "Storage Path for Backups, Music & Shares [${default_storage}]: " input_storage
            STORAGE_BASE=${input_storage:-$default_storage}
        else
            STORAGE_BASE="${OPT_STORAGE}"
        fi

        if [ -z "${OPT_ZT_EMAILS}" ]; then
            read -r -p "Cloudflare Zero Trust Allowed Emails (optional, comma-separated) [skip]: " input_zt
            OPT_ZT_EMAILS="${input_zt}"
        fi
    fi

    if [ -n "${OPT_ZT_EMAILS}" ]; then
        CF_ZT_ENABLED="true"
        ZERO_TRUST_EMAILS="${OPT_ZT_EMAILS}"
    else
        CF_ZT_ENABLED="false"
        ZERO_TRUST_EMAILS=""
    fi

    local trusted_domains
    trusted_domains="$(build_trusted_domains)"

    cat > .env << EOF
# ==============================================================================
# Homelab OS (HL-OS) Configuration — Generated on $(date -u)
# ==============================================================================

# ── General Server Settings ──────────────────────────────────────────────────
COMPOSE_PROJECT_NAME=homelab
TZ=${DETECTED_TZ}
STORAGE_PATH=${STORAGE_BASE}
NET_IFACE=${NET_IFACE}

# ── Admin Dashboard (FastAPI) ────────────────────────────────────────────────
DASHBOARD_PORT=5001
DASHBOARD_SECRET=${auto_secret}
ADMIN_DEFAULT_USER=${ADMIN_USER}
ADMIN_DEFAULT_PASSWORD=${ADMIN_PW}
FORCE_HTTPS=false
WAKE_PROXY_ENABLED=true

# ── Pi-hole DNS ──────────────────────────────────────────────────────────────
PIHOLE_PASSWORD=${AUTO_PIHOLE_PW}
PIHOLE_WEB_PORT=8080

# ── Samba File Server (SMB3 over VPN / LAN) ──────────────────────────────────
SAMBA_SHARE_PATH=${STORAGE_BASE}
SAMBA_USER=${SMB_USER}
SAMBA_PASSWORD=${AUTO_SMB_PW}

# ── MariaDB / Nextcloud Database ─────────────────────────────────────────────
MYSQL_ROOT_PASSWORD=${auto_root_db_pw}
MYSQL_DATABASE=nextcloud
MYSQL_USER=nextcloud
MYSQL_PASSWORD=${auto_db_pw}

# ── Redis Cache ──────────────────────────────────────────────────────────────
REDIS_PASSWORD=${auto_redis_pw}

# ── Nextcloud ────────────────────────────────────────────────────────────────
NEXTCLOUD_ADMIN_USER=${ADMIN_USER}
NEXTCLOUD_ADMIN_PASSWORD=${ADMIN_PW}
NEXTCLOUD_PORT=8081
NEXTCLOUD_TRUSTED_DOMAINS="${trusted_domains}"

# ── Navidrome & Maloja Music Stack ───────────────────────────────────────────
NAVIDROME_PORT=4533
MALOJA_PORT=42010
MALOJA_DATA_PATH=./maloja/data
MALOJA_ADMIN_PASSWORD=${AUTO_MALOJA_PW}
MALOJA_API_KEY=${AUTO_MALOJA_KEY}
MALOJA_API_SECRET=bypass

# ── Backup Configuration ─────────────────────────────────────────────────────
BACKUP_RETENTION_DAYS=7

# ── Cloudflare Zero Trust Defense-in-Depth (Optional) ────────────────────────
CLOUDFLARE_ZERO_TRUST_ENABLED=${CF_ZT_ENABLED}
ALLOWED_ZERO_TRUST_EMAILS="${ZERO_TRUST_EMAILS}"
ZERO_TRUST_BYPASS_LOCAL=true
EOF

    chmod 600 .env
    GENERATED_NEW_ENV=1
    log_success ".env generated with strong cryptographic secrets (mode 0600)."
}

create_directories() {
    log_info "Creating required service and storage directories..."

    mkdir -p admin-dashboard/data admin-dashboard/logs
    mkdir -p nextcloud/data nextcloud/config nextcloud/apps
    mkdir -p nginx/data nginx/letsencrypt
    mkdir -p navidrome/data
    mkdir -p maloja/data

    mkdir -p "${STORAGE_BASE}/music/_playlists"
    mkdir -p "${STORAGE_BASE}/snapshots"

    if [ ! -f config/maloja/_base_patched.py ]; then
        log_warn "config/maloja/_base_patched.py not found; ensure repository checkout is complete."
    fi

    # Apply low-spec Nextcloud tuning automatically if Nextcloud is already initialized
    if [ -f nextcloud/config/config.php ] && [ ! -f nextcloud/config/low_spec.config.php ] && [ -f nextcloud/low_spec_tuning.config.php ]; then
        cp nextcloud/low_spec_tuning.config.php nextcloud/config/low_spec.config.php
        log_success "Applied Nextcloud low-spec tuning drop-in config."
    fi

    log_success "Directory structure initialized at ./ and ${STORAGE_BASE}."
}

install_client_tools() {
    log_info "Setting executable permissions on helper scripts..."
    chmod +x install.sh 2>/dev/null || true
    chmod +x scripts/client_smb_watchdog.sh 2>/dev/null || true
    chmod +x admin-dashboard/scripts/backup.sh 2>/dev/null || true
    log_success "Watchdog and backup scripts are ready."
}

start_stack_if_requested() {
    local should_start="${AUTO_START}"
    if [ "${should_start}" -eq 0 ] && [ "${NON_INTERACTIVE}" -eq 0 ]; then
        echo ""
        read -r -p "Build and start all Homelab OS containers now? [y/N] " start_now
        if [[ "${start_now:-N}" =~ ^[Yy]$ ]]; then
            should_start=1
        fi
    fi

    if [ "${should_start}" -eq 1 ]; then
        if ! docker info >/dev/null 2>&1; then
            log_error "Docker daemon is not running or current user lacks socket permissions."
            echo "  Start Docker daemon (or add user to 'docker' group) and run: ${DOCKER_COMPOSE_CMD} up -d --build"
            exit 1
        fi
        log_info "Building & launching Homelab OS stack (${DOCKER_COMPOSE_CMD} up -d --build)..."
        ${DOCKER_COMPOSE_CMD} up -d --build
        log_success "Containers launched! Check health with: ${DOCKER_COMPOSE_CMD} ps"
    fi
}

verify_and_summary() {
    local display_host="${TAILSCALE_IP:-${LAN_IP:-localhost}}"
    local dash_port nc_port pihole_port navi_port maloja_port
    dash_port="$(get_env_value DASHBOARD_PORT .env)"
    nc_port="$(get_env_value NEXTCLOUD_PORT .env)"
    pihole_port="$(get_env_value PIHOLE_WEB_PORT .env)"
    navi_port="$(get_env_value NAVIDROME_PORT .env)"
    maloja_port="$(get_env_value MALOJA_PORT .env)"

    dash_port="${dash_port:-5001}"
    nc_port="${nc_port:-8081}"
    pihole_port="${pihole_port:-8080}"
    navi_port="${navi_port:-4533}"
    maloja_port="${maloja_port:-42010}"

    echo ""
    echo "=============================================================================="
    echo -e "${GREEN}${BOLD}✔ Homelab OS installation & configuration completed!${NC}"
    echo "=============================================================================="
    echo ""
    echo -e "${BOLD}Services Topology & Access Endpoints:${NC}"
    echo -e "  • ${CYAN}Admin Control Plane (FastAPI + PWA):${NC} http://${display_host}:${dash_port}"
    echo -e "  • ${CYAN}OpenAPI / Swagger Documentation:${NC}     http://${display_host}:${dash_port}/docs"
    echo -e "  • ${CYAN}Nextcloud Personal Cloud:${NC}            http://${display_host}:${nc_port}"
    echo -e "  • ${CYAN}Pi-hole Network Ad-Blocker:${NC}          http://${display_host}:${pihole_port}/admin"
    echo -e "  • ${CYAN}Nginx Proxy Manager UI:${NC}              http://${display_host}:81"
    echo -e "  • ${CYAN}Navidrome Hi-Fi Music Streaming:${NC}     http://${display_host}:${navi_port}"
    echo -e "  • ${CYAN}Maloja Scrobbler Analytics:${NC}          http://${display_host}:${maloja_port}"
    echo -e "  • ${CYAN}Samba SMB3 Durable File Share:${NC}       smb://${display_host}/Storage"
    echo ""

    if [ "${GENERATED_NEW_ENV}" -eq 1 ]; then
        echo -e "${BOLD}Generated Initial Credentials (saved in .env):${NC}"
        echo -e "  • ${BOLD}Dashboard / Nextcloud:${NC} user=${CYAN}${ADMIN_USER}${NC}  pass=${CYAN}${ADMIN_PW}${NC}"
        echo -e "  • ${BOLD}Samba SMB3 Share:${NC}      user=${CYAN}${SMB_USER}${NC}  pass=${CYAN}${AUTO_SMB_PW}${NC}"
        echo -e "  • ${BOLD}Pi-hole Admin:${NC}         pass=${CYAN}${AUTO_PIHOLE_PW}${NC}"
        echo -e "  • ${BOLD}Maloja Admin:${NC}          pass=${CYAN}${AUTO_MALOJA_PW}${NC}"
        echo ""
    fi

    if [ "${AUTO_START}" -eq 0 ]; then
        echo -e "${BOLD}Next Steps to Launch Containers:${NC}"
        echo -e "  ${YELLOW}${DOCKER_COMPOSE_CMD} up -d --build${NC}"
        echo ""
    fi

    echo -e "${PURPLE}All secrets are stored in .env (mode 0600).${NC}"
    echo "=============================================================================="
}

main() {
    parse_args "$@"
    print_banner
    check_prerequisites

    if [ "${CHECK_ONLY}" -eq 1 ]; then
        log_success "Prerequisite check complete."
        exit 0
    fi

    configure_environment
    create_directories
    install_client_tools
    start_stack_if_requested
    verify_and_summary
}

main "$@"
