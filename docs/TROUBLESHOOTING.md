# Homelab OS: Diagnostic & Troubleshooting Guide

This guide provides systematic diagnostic procedures, decision trees, and resolutions for common issues encountered during Homelab OS operations.

---

## ⚡ 1. Rapid Triage Commands

Before diving into specific issues, run these standard diagnostic commands to inspect the cluster state:

```bash
# 1. Run the system dependency and hardware audit
homelab doctor

# 2. Check container runtime status and health checks
docker compose ps

# 3. View live, interleaved logs across all services
homelab logs -f

# 4. View logs for a specific container (e.g. Nextcloud or Pi-hole)
docker compose logs --tail=100 -f nextcloud
```

---

## 🔍 2. Diagnostic Decision Matrix

| Symptom | Probable Cause | Quick Resolution |
| :--- | :--- | :--- |
| **Pi-hole fails to start (`port 53 already in use`)** | Host OS `systemd-resolved` is binding to port 53. | [Disable DNSStubListener](#issue-1-port-53-conflict-systemd-resolved) |
| **Samba fails to start (`port 445 already in use`)** | Host OS `smbd` or Windows native file sharing is running. | [Stop host Samba daemon](#issue-2-port-445-conflict-host-smbd) |
| **Admin Dashboard graphs look flat / zero traffic** | Incorrect active network interface selected in UI. | [Select active interface & switch scale](#issue-3-network-graph-appears-flat) |
| **Nextcloud displays "Internal Server Error"** | MariaDB container is still initializing or permissions need repair. | [Verify MariaDB readiness & file permissions](#issue-4-nextcloud-internal-server-error) |
| **Samba share disconnects after laptop sleep** | Client lease dropped during OS standby. | [Run client SMB watchdog script](#issue-5-smb3-network-share-drops-on-client-sleep) |
| **Forgotten Admin Dashboard password** | Lost credentials from `.env`. | [Reset password via SQLite](#issue-6-reset-admin-password) |

---

## 🛠️ 3. Issue Resolutions

### Issue 1: Port 53 Conflict (`systemd-resolved`)
On modern Ubuntu and Debian distributions, `systemd-resolved` runs a local caching stub listener on `127.0.0.53:53`, preventing Pi-hole from binding to port 53.

**Resolution:**
1. Edit the resolved configuration:
   ```bash
   sudo nano /etc/systemd/resolved.conf
   ```
2. Set `DNSStubListener=no`:
   ```ini
   [Resolve]
   DNS=127.0.0.1
   DNSStubListener=no
   ```
3. Update symlink for resolv.conf and restart the daemon:
   ```bash
   sudo ln -sf /run/systemd/resolve/resolv.conf /etc/resolv.conf
   sudo systemctl restart systemd-resolved
   ```
4. Restart Homelab OS:
   ```bash
   homelab up
   ```

---

### Issue 2: Port 445 Conflict (Host `smbd`)
If your host machine already had Samba installed prior to running Homelab OS, the host service binds to port 445.

**Resolution:**
```bash
# Check what is listening on port 445
sudo lsof -i :445  # or: sudo ss -tulpn | grep 445

# Stop and disable the host service
sudo systemctl stop smbd nmbd
sudo systemctl disable smbd nmbd

# Restart the Homelab OS Samba container
docker compose restart samba
```

---

### Issue 3: Network Graph Appears Flat
If the Network view in the Admin Dashboard displays a flat baseline despite active downloads:
1. **Interface Selection:** Modern laptops and home servers often have multiple network adapters (e.g., `wlp2s0` Wi-Fi, `enp4s0` Ethernet, and `tailscale0`). Open the **Network** tab in the dashboard and ensure the dropdown is set to your **primary active adapter** (not an idle disconnected Ethernet port).
2. **Perceptual Log Scale:** In low-traffic scenarios (1–30 KB/s idle chatter) alongside multi-megabyte spikes, linear scaling renders small numbers at sub-pixel levels. Click the **Logarithmic Scale** button on the chart to visualize minute traffic bursts clearly.

---

### Issue 4: Nextcloud "Internal Server Error"
If Nextcloud fails during startup or displays database connection errors:
1. Ensure MariaDB is running and healthy:
   ```bash
   docker compose ps mariadb
   ```
2. Verify Nextcloud file ownership:
   ```bash
   # Files must be readable and writable by www-data (UID 33 in Debian/Apache, 1000 in Homelab OS)
   sudo chown -R 1000:1000 nextcloud/
   ```
3. Run Nextcloud maintenance repairs:
   ```bash
   docker compose exec -u www-data nextcloud php occ maintenance:repair
   ```

---

### Issue 5: SMB3 Network Share Drops on Client Sleep
Laptops that enter sleep mode lose active TCP sockets with the Samba daemon.

**Resolution:**
Run the included zero-dependency client watchdog script on your macOS or Linux client laptop:
```bash
# Download and make executable
curl -fsSL https://raw.githubusercontent.com/beingbrijesh/Homelab-OS/main/scripts/client_smb_watchdog.sh -o client_smb_watchdog.sh
chmod +x client_smb_watchdog.sh

# Start the auto-reconnect watchdog daemon in background
./client_smb_watchdog.sh --host <HOST_IP> --share Storage --mount /Volumes/Storage &
```
The watchdog polls the mount every 15 seconds; if the connection drops, it re-mounts the share silently without interrupting user workflows.

---

### Issue 6: Reset Admin Password
If you lost access to your admin account and cannot find the credentials in `.env`:

```bash
# Generate a new scrypt hash for password 'MyNewSecretPassword'
python3 -c "
import hashlib, os, base64
salt = os.urandom(16)
dk = hashlib.scrypt('MyNewSecretPassword'.encode(), salt=salt, n=16384, r=8, p=1)
stored = f'scrypt${base64.b64encode(salt).decode()}\${base64.b64encode(dk).decode()}'
print(stored)
"
```
Copy the printed hash and update SQLite:
```bash
sqlite3 admin-dashboard/data/dashboard.db "UPDATE admins SET password_hash='<COPIED_HASH>' WHERE username='admin';"
```
You can now sign in immediately at `http://<HOST_IP>:5001` with your new password.

---

## 🛟 4. Still Having Issues?

* **Diagnostic Report:** Run `homelab doctor` to generate a self-contained health report.
* **Community Issues:** Submit an issue on the [Homelab OS GitHub Tracker](https://github.com/beingbrijesh/Homelab-OS/issues) with the output of `homelab doctor` (sensitive tokens and passwords are auto-sanitized).
