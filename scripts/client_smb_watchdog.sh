#!/usr/bin/env bash
# ==============================================================================
# Homelab OS (HL-OS) — Client-Side Samba / SMB Auto-Reconnect Watchdog
# Automatically re-establishes SMB share mounts when private VPN reconnects
# ==============================================================================

SERVER_IP="${1:-${HOMELAB_SERVER_IP:-}}"              # Your server VPN / Tailscale / LAN IP
SHARE_NAME="${2:-${HOMELAB_SHARE_NAME:-Storage}}"          # SMB Share name
MOUNT_POINT="${3:-${HOMELAB_MOUNT_POINT:-/Volumes/Storage}}" # Local mount destination
SMB_USER="${4:-${HOMELAB_SMB_USER:-homelab}}"               # Samba username
CHECK_INTERVAL="${5:-${HOMELAB_CHECK_INTERVAL:-10}}"        # Check every 10 seconds

if [ -z "$SERVER_IP" ]; then
    echo "ERROR: Server IP is required." >&2
    echo "Usage: $0 <SERVER_IP> [SHARE_NAME] [MOUNT_POINT] [SMB_USER] [CHECK_INTERVAL]" >&2
    echo "   or: HOMELAB_SERVER_IP=100.x.x.x $0" >&2
    exit 1
fi

echo "════════════════════════════════════════════════════════════════"
echo "  Homelab Samba Reconnect Watchdog Active"
echo "  Monitoring server at: $SERVER_IP (Share: $SHARE_NAME)"
echo "  Target Mount: $MOUNT_POINT (User: $SMB_USER)"
echo "  Check interval: ${CHECK_INTERVAL}s"
echo "════════════════════════════════════════════════════════════════"

offline_count=0

check_reachable() {
    if [[ "$OSTYPE" == "darwin"* ]]; then
        # macOS BSD ping: -W is milliseconds, -t is overall timeout in seconds
        ping -c 2 -W 2000 -t 4 "$SERVER_IP" >/dev/null 2>&1
    else
        # Linux iputils ping: -W is seconds
        ping -c 2 -W 2 "$SERVER_IP" >/dev/null 2>&1
    fi
}

is_mounted() {
    mount | grep -Fq " on ${MOUNT_POINT} "
}

force_unmount() {
    if [[ "$OSTYPE" == "darwin"* ]]; then
        /sbin/umount -f "$MOUNT_POINT" >/dev/null 2>&1 || \
        /usr/sbin/diskutil unmount force "$MOUNT_POINT" >/dev/null 2>&1 || true
    else
        umount -l "$MOUNT_POINT" >/dev/null 2>&1 || umount -f "$MOUNT_POINT" >/dev/null 2>&1 || true
    fi
}

while true; do
    # 1. Check if server is reachable over VPN / network
    if check_reachable; then
        offline_count=0
        needs_mount=0

        # Check if already mounted
        if ! is_mounted; then
            needs_mount=1
        else
            # Verify mount is responsive and not stale/hung
            if ! /bin/df "$MOUNT_POINT" >/dev/null 2>&1; then
                echo "[$(date '+%Y-%m-%d %H:%M:%S')] ⚠️ Mount $MOUNT_POINT appears stale or unresponsive. Unmounting..."
                force_unmount
                if ! is_mounted; then
                    needs_mount=1
                fi
            fi
        fi

        # Reconnect if unmounted
        if [ "$needs_mount" -eq 1 ]; then
            echo "[$(date '+%Y-%m-%d %H:%M:%S')] 🔄 Server reachable ($SERVER_IP). Re-establishing SMB mount..."
            
            if [[ "$OSTYPE" == "darwin"* ]]; then
                # macOS native AppleScript mount using Keychain credentials
                osascript -e "mount volume \"smb://${SMB_USER}@${SERVER_IP}/${SHARE_NAME}\"" >/dev/null 2>&1 || \
                mount -t smbfs "//${SMB_USER}@${SERVER_IP}/${SHARE_NAME}" "$MOUNT_POINT" 2>/dev/null
            else
                # Linux CIFS mount
                mkdir -p "$MOUNT_POINT"
                mount -t cifs "//${SERVER_IP}/${SHARE_NAME}" "$MOUNT_POINT" -o "username=${SMB_USER}" 2>/dev/null
            fi

            if is_mounted; then
                echo "[$(date '+%Y-%m-%d %H:%M:%S')] ✓ Successfully connected $SHARE_NAME at $MOUNT_POINT"
            else
                echo "[$(date '+%Y-%m-%d %H:%M:%S')] ❌ Mount attempt failed. Will retry in ${CHECK_INTERVAL}s."
            fi
        fi
    else
        # Server unreachable / network dropped:
        offline_count=$((offline_count + 1))
        # If offline for 2 checks (~24-28s across 4 ICMP probes), cleanly unmount before Finder modal dialog
        if [ "$offline_count" -ge 2 ] && is_mounted; then
            echo "[$(date '+%Y-%m-%d %H:%M:%S')] ⚠️ Network disconnected ($SERVER_IP unreachable). Cleanly unmounting to prevent modal dialog..."
            force_unmount
            if ! is_mounted; then
                echo "[$(date '+%Y-%m-%d %H:%M:%S')] ✓ Cleanly unmounted $MOUNT_POINT"
            fi
        fi
    fi
    sleep "$CHECK_INTERVAL"
done
