"""Cross-platform host hardware, network, timezone, and port-conflict probes."""

from __future__ import annotations

import ctypes
import errno
import os
import platform
import shutil
import socket
import subprocess
from dataclasses import dataclass
from typing import Dict, List


@dataclass
class HostProfile:
    os_name: str
    arch: str
    cpu_cores: int
    total_ram_mb: int
    net_iface: str
    lan_ip: str
    tailscale_ip: str
    timezone: str


def _run_out(cmd: List[str], timeout: int = 4) -> str:
    try:
        res = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=timeout,
        )
        return (res.stdout or "").strip() if res.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def get_total_ram_mb(os_name: str | None = None) -> int:
    system = (os_name or platform.system()).lower()
    if system == "darwin":
        out = _run_out(["sysctl", "-n", "hw.memsize"])
        if out.isdigit():
            return int(out) // (1024 * 1024)
    elif system == "linux" and os.path.exists("/proc/meminfo"):
        try:
            with open("/proc/meminfo", "r", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        parts = line.split()
                        if len(parts) >= 2 and parts[1].isdigit():
                            return int(parts[1]) // 1024
        except OSError:
            pass
    elif system == "windows":
        try:
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):  # type: ignore[attr-defined]
                return int(stat.ullTotalPhys // (1024 * 1024))
        except Exception:
            pass
    return 4096


def detect_net_iface(os_name: str | None = None) -> str:
    system = (os_name or platform.system()).lower()
    if system == "darwin":
        out = _run_out(["route", "-n", "get", "default"])
        for line in out.splitlines():
            if "interface:" in line:
                return line.split(":", 1)[1].strip()
        return "en0"
    if system == "linux":
        out = _run_out(["ip", "-4", "route", "show", "default"])
        tokens = out.split()
        for idx, tok in enumerate(tokens):
            if tok == "dev" and idx + 1 < len(tokens):
                return tokens[idx + 1]
        return "eth0"
    return "eth0"


def detect_lan_ip(net_iface: str = "", os_name: str | None = None) -> str:
    system = (os_name or platform.system()).lower()
    if system == "darwin" and net_iface:
        ip = _run_out(["ipconfig", "getifaddr", net_iface])
        if ip:
            return ip
    elif system == "linux":
        if net_iface:
            out = _run_out(["ip", "-4", "addr", "show", net_iface])
            for line in out.splitlines():
                line = line.strip()
                if line.startswith("inet "):
                    return line.split()[1].split("/")[0]
        out = _run_out(["hostname", "-I"])
        if out:
            return out.split()[0]

    # Cross-platform UDP route lookup (works on Windows/macOS/Linux without sending packets)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("1.1.1.1", 80))
        ip = sock.getsockname()[0]
        if ip and not ip.startswith("127."):
            return ip
    except OSError:
        pass
    finally:
        sock.close()
    return ""


def detect_tailscale_ip(os_name: str | None = None) -> str:
    if shutil.which("tailscale"):
        out = _run_out(["tailscale", "ip", "-4"])
        if out:
            return out.splitlines()[0].strip()

    system = (os_name or platform.system()).lower()
    if system == "darwin":
        out = _run_out(["ifconfig"])
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("inet 100."):
                parts = line.split()
                if len(parts) >= 2:
                    return parts[1]
    elif system == "linux":
        out = _run_out(["ip", "-4", "addr", "show", "tailscale0"])
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("inet "):
                return line.split()[1].split("/")[0]
    return ""


def detect_timezone(os_name: str | None = None) -> str:
    system = (os_name or platform.system()).lower()
    if system == "linux":
        if os.path.isfile("/etc/timezone"):
            try:
                with open("/etc/timezone", "r", encoding="utf-8") as f:
                    val = f.read().strip()
                    if val:
                        return val
            except OSError:
                pass
        if shutil.which("timedatectl"):
            val = _run_out(["timedatectl", "show", "-p", "Timezone", "--value"])
            if val:
                return val
    if os.path.islink("/etc/localtime"):
        target = os.readlink("/etc/localtime")
        if "zoneinfo/" in target:
            return target.split("zoneinfo/", 1)[1].strip() or "UTC"
    return "UTC"


def gather_host_profile(iface_override: str = "") -> HostProfile:
    os_name = platform.system()
    arch = platform.machine()
    cpu_cores = os.cpu_count() or 2
    ram_mb = get_total_ram_mb(os_name)
    net_iface = iface_override.strip() or detect_net_iface(os_name)
    lan_ip = detect_lan_ip(net_iface, os_name)
    tailscale_ip = detect_tailscale_ip(os_name)
    timezone = detect_timezone(os_name)
    return HostProfile(
        os_name=os_name,
        arch=arch,
        cpu_cores=cpu_cores,
        total_ram_mb=ram_mb,
        net_iface=net_iface,
        lan_ip=lan_ip,
        tailscale_ip=tailscale_ip,
        timezone=timezone,
    )


def is_port_in_use(port: int, host: str = "0.0.0.0") -> bool:
    # 1. Check active loopback connect first
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.settimeout(0.2)
    try:
        if probe.connect_ex(("127.0.0.1", port)) == 0:
            return True
    except OSError:
        pass
    finally:
        probe.close()

    # 2. Check bind availability on target host (without SO_REUSEADDR to catch listeners)
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        srv.bind((host, port))
        return False
    except OSError as exc:
        if exc.errno in (errno.EADDRINUSE, 10048, 10013):
            return True
        return False
    finally:
        srv.close()


def check_port_conflicts(ports: tuple[int, ...] = (53, 80, 443, 81, 445, 5001, 8080, 8081, 4533, 42010)) -> Dict[int, str]:
    system = platform.system().lower()
    conflicts: Dict[int, str] = {}
    for p in ports:
        if is_port_in_use(p):
            if p == 53 and system == "linux":
                conflicts[p] = (
                    "Port 53 (DNS) is bound (often Ubuntu systemd-resolved). "
                    "Disable DNSStubListener=no in /etc/systemd/resolved.conf if starting Pi-hole."
                )
            elif p == 445:
                if system == "windows":
                    conflicts[p] = (
                        "Port 445 (SMB) is reserved by Windows File Sharing (LanmanServer). "
                        "Use host shares on Windows or omit/stop the samba container."
                    )
                else:
                    conflicts[p] = (
                        "Port 445 (SMB) is already bound (host smbd may be running). "
                        "Stop host smbd or manage Samba outside Docker."
                    )
            else:
                conflicts[p] = f"Port {p} is already in use on this host. Override port in .env if needed."
    return conflicts
