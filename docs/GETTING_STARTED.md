# Homelab OS: Getting Started Guide

Welcome to **Homelab OS (HL-OS)** — a turnkey, multi-platform personal cloud, resilient SMB3 file server, local DNS ad-blocker, and high-fidelity media engine designed to operate reliably on everything from 2015-era dual-core laptops to dedicated home-lab servers.

---

## 📋 Table of Contents

1. [Hardware Requirements & Sizing](#1-hardware-requirements--sizing)
2. [Operating System Prerequisites](#2-operating-system-prerequisites)
3. [Installation Methods](#3-installation-methods)
   - [Method 1: Python Package (Recommended)](#method-1-python-package-pipx--pip)
   - [Method 2: Node.js Wrapper (npm / npx)](#method-2-nodejs-wrapper-npm--npx)
   - [Method 3: Direct Git Clone & Installer](#method-3-direct-git-clone--installer)
4. [First-Time Initialization & Credentials](#4-first-time-initialization--credentials)
5. [Connecting Client Devices](#5-connecting-client-devices)
   - [Admin Dashboard & PWA](#admin-dashboard--pwa)
   - [Nextcloud Personal Cloud](#nextcloud-personal-cloud)
   - [Samba (SMB3) Network Drive](#samba-smb3-network-drive)
   - [Navidrome & Subsonic Music Players](#navidrome--subsonic-music-players)
   - [Tailscale Mesh VPN (Access from Anywhere)](#tailscale-mesh-vpn-access-from-anywhere)
6. [Post-Install Health Verification](#6-post-install-health-verification)

---

## 1. Hardware Requirements & Sizing

Homelab OS is engineered with a strict **~2.2 GB RAM total memory cap** across all 9 containers, ensuring the operating system retains ample page cache for smooth disk operations even on low-power hardware.

| Hardware Tier | CPU | Memory (RAM) | Storage | Recommended Use Case |
| :--- | :--- | :--- | :--- | :--- |
| **Minimum (Low-Spec)** | 2-Core Intel Celeron / Core i3 (2015+) or ARM64 (Raspberry Pi 4/5) | 4 GB | 32 GB SSD / High-Speed Flash | Personal file sync, ad-blocking, single-user audio streaming. |
| **Standard (Sweet Spot)** | 4-Core Intel/AMD or Apple Silicon | 8 GB | 120 GB+ SSD / NVMe | Family cloud, continuous Nextcloud photo sync, multi-room Subsonic playback. |
| **Power User / Lab** | 6+ Cores | 16 GB+ | Multi-TB HDD / ZFS pool + NVMe cache | High-throughput SMB multi-channel, extensive lossless FLAC libraries. |

> [!NOTE]
> **Zero-AI Guarantee:** Homelab OS explicitly excludes large language models (LLMs), PyTorch, or Ollama daemons, reserving 100% of CPU and RAM for file transfers, networking, and core services.

---

## 2. Operating System Prerequisites

Before launching Homelab OS, ensure your host operating system is up to date:

* **Linux (Recommended):** Ubuntu 22.04/24.04 LTS, Debian 12 (Bookworm), Fedora, Arch Linux, or Alpine Linux.
* **macOS:** macOS 12 (Monterey) or higher (Apple Silicon M1/M2/M3/M4 or Intel).
* **Windows:** Windows 10/11 Pro or Enterprise with WSL2 (Ubuntu) or Windows Containers.

### Dependency Checklist

Homelab OS automatically detects and can install missing dependencies, but the following packages form the core stack:
* **Docker Engine** (24.0+) & **Docker Compose v2** (2.20+)
* **Python** (3.9+)
* **Git**, **cURL**, and **OpenSSL**
* **Tailscale** (optional, for secure remote mesh access)
* `cifs-utils` (Linux hosts only, for SMB mount points)

---

## 3. Installation Methods

Choose the method that best matches your administration workflow:

### Method 1: Python Package (`pipx` / `pip`)

The easiest way to install the Homelab OS management CLI globally on any platform:

```bash
# Install via pipx (isolated global environment)
pipx install homelab-os

# Or install via user-level pip
pip install --user homelab-os

# Initialize and immediately start containers
homelab init -y --start
```

### Method 2: Node.js Wrapper (`npm` / `npx`)

Run turnkey setup directly without permanent global installation:

```bash
# One-liner execution using npx
npx homelab-os init -y --start

# Or install globally via npm
npm install -g homelab-os
homelab init -y --start
```

### Method 3: Direct Git Clone & Installer

If you prefer inspecting the source code and configuration manifests directly:

```bash
git clone https://github.com/beingbrijesh/Homelab-OS.git
cd Homelab-OS

# Run the automated installer with start flag
./install.sh -y --start
```

---

## 4. First-Time Initialization & Credentials

During initialization, Homelab OS:
1. Probes host CPU cores, memory limits, primary network interface, and active IP addresses.
2. Checks for host port conflicts (e.g. systemd-resolved on port 53 or smbd on port 445).
3. Creates persistent storage folders:
   - `storage/music/` (lossless audio library & playlists)
   - `storage/shares/` (Samba shared folders)
   - `storage/snapshots/` (atomic backup snapshots)
4. Generates an encrypted `.env` configuration file with cryptographically secure random passwords.

### Default Port Allocations

| Service | Protocol / Port | Initial URL | Default Username | Default Password |
| :--- | :--- | :--- | :--- | :--- |
| **Admin Dashboard** | HTTP `5001` | `http://<HOST_IP>:5001` | `admin` | *(Auto-generated in `.env`)* |
| **API Documentation** | HTTP `5001` | `http://<HOST_IP>:5001/docs` | *(Same as Admin)* | *(Same as Admin)* |
| **Nextcloud** | HTTP `8081` | `http://<HOST_IP>:8081` | `admin` | *(Auto-generated in `.env`)* |
| **Pi-hole DNS** | HTTP `8080` / UDP `53` | `http://<HOST_IP>:8080/admin` | — | *(Auto-generated in `.env`)* |
| **Nginx Proxy Manager** | HTTP `81` / `80` / `443` | `http://<HOST_IP>:81` | `admin@example.com` | `changeme` *(Prompted on first login)* |
| **Navidrome** | HTTP `4533` | `http://<HOST_IP>:4533` | *(Created on first visit)* | *(Created on first visit)* |
| **Maloja Scrobbler** | HTTP `42010` | `http://<HOST_IP>:42010` | `admin` | *(Auto-generated in `.env`)* |
| **Samba SMB3** | TCP `445`, `139` | `smb://<HOST_IP>/Storage` | `homelab` | *(Auto-generated in `.env`)* |

> [!TIP]
> Retrieve all generated credentials at any time by viewing the `.env` file in your workspace:
> ```bash
> grep -E "PASSWORD|USER" .env
> ```

---

## 5. Connecting Client Devices

### Admin Dashboard & PWA
Open `http://<HOST_IP>:5001` in Chrome, Safari, or Edge.
* **Install as PWA:** Click the **Install** or **Add to Home Screen** button in your browser's address bar. The dashboard will run as an isolated, native desktop or mobile application with offline telemetry indicators.
* **Theme Preference:** Toggle between Monochrome Dark and Light themes from the top bar.

### Nextcloud Personal Cloud
1. Download the official Nextcloud client for iOS, Android, macOS, or Windows from [nextcloud.com/install](https://nextcloud.com/install).
2. Enter your server address: `http://<HOST_IP>:8081`.
3. Sign in with the credentials from your `.env` (`ADMIN_DEFAULT_USER` and `ADMIN_DEFAULT_PASSWORD`).
4. Enable auto-upload for photos and camera roll.

### Samba (SMB3) Network Drive
Homelab OS enables durable handles and client leasing for rock-solid network drive connectivity:

* **macOS (Finder):**
  1. Open Finder, press `Cmd + K` (Connect to Server).
  2. Enter: `smb://<HOST_IP>/Storage`.
  3. Enter username `homelab` and your `SAMBA_PASSWORD`.
* **Windows (File Explorer):**
  1. Open File Explorer, press `Win + E`.
  2. In the address bar, type: `\\<HOST_IP>\Storage`.
  3. Enter credentials: `homelab` and your `SAMBA_PASSWORD`.
* **Linux (Auto-Reconnect Mount):**
  ```bash
  sudo mkdir -p /mnt/homelab
  sudo mount -t cifs //<HOST_IP>/Storage /mnt/homelab -o user=homelab,password=<PASSWORD>,uid=1000,gid=1000
  ```

### Navidrome & Subsonic Music Players
Your audio library in `storage/music/` is automatically scanned:
1. Open `http://<HOST_IP>:4533` in a browser and create your personal user account.
2. In Subsonic mobile clients (such as **Symfonium** on Android or **Amperfy** on iOS):
   - Server URL: `http://<HOST_IP>:4533`
   - Enter your Navidrome username and password.
3. Enjoy offline cached playback, gapless transitions, and real-time scrobbling.

### Tailscale Mesh VPN (Access from Anywhere)
Access your entire homelab securely from coffee shops, mobile networks, or foreign connections without port forwarding:
```bash
# Connect host machine to Tailscale mesh
sudo tailscale up

# Retrieve your Tailscale IP
tailscale ip -4
```
Use the assigned `100.x.y.z` IP address to access all dashboards, Nextcloud, and SMB shares securely from any device authorized on your Tailscale tailnet.

---

## 6. Post-Install Health Verification

Run built-in diagnostic commands to verify all containers and sockets are operating normally:

```bash
# Run the diagnostic health check
homelab doctor

# Check running container status
homelab status

# View live container logs
homelab logs -f
```

All 9 containers should show `healthy` or `running`. You are now ready to use your private Homelab OS cloud!
