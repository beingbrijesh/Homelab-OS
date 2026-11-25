"""Unified cross-platform CLI for Homelab OS (`homelab`)."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

from . import __version__
from .deps import detect_compose_cmd, ensure_dependencies
from .sysinfo import HostProfile, check_port_conflicts, gather_host_profile
from .workspace import (
    copy_stack_bundle,
    ensure_runtime_directories,
    generate_env_config,
    parse_env_file,
    resolve_bundle_dir,
    resolve_workspace_dir,
)


def _run_compose(workspace: Path, args: List[str]) -> int:
    compose_cmd = detect_compose_cmd()
    if not compose_cmd:
        print("[ERROR] Docker Compose v2 is not available. Run 'homelab doctor' first.", file=sys.stderr)
        return 1
    cmd = compose_cmd + args
    print(f"[INFO] Running ({workspace}): {' '.join(cmd)}")
    return subprocess.run(cmd, cwd=str(workspace)).returncode


def _print_endpoints(workspace: Path, profile: HostProfile, env_map: dict, generated_new: bool = False) -> None:
    host = profile.tailscale_ip or profile.lan_ip or "localhost"
    dash_port = env_map.get("DASHBOARD_PORT", "5001")
    nc_port = env_map.get("NEXTCLOUD_PORT", "8081")
    pihole_port = env_map.get("PIHOLE_WEB_PORT", "8080")
    navi_port = env_map.get("NAVIDROME_PORT", "4533")
    maloja_port = env_map.get("MALOJA_PORT", "42010")

    print("\n" + "=" * 78)
    print(f"Homelab OS Workspace Ready: {workspace}")
    print("=" * 78)
    print("Service Endpoints:")
    print(f"  * Admin Dashboard (FastAPI + PWA): http://{host}:{dash_port}")
    print(f"  * OpenAPI / Swagger Docs:          http://{host}:{dash_port}/docs")
    print(f"  * Nextcloud Personal Cloud:        http://{host}:{nc_port}")
    print(f"  * Pi-hole DNS Admin:               http://{host}:{pihole_port}/admin")
    print(f"  * Nginx Proxy Manager UI:          http://{host}:81")
    print(f"  * Navidrome Music Streamer:        http://{host}:{navi_port}")
    print(f"  * Maloja Scrobbler:                http://{host}:{maloja_port}")
    print(f"  * Samba SMB3 Share:                smb://{host}/Storage")

    if generated_new:
        print("\nGenerated Initial Credentials (saved in .env):")
        print(f"  * Dashboard / Nextcloud: user={env_map.get('ADMIN_DEFAULT_USER')}  pass={env_map.get('ADMIN_DEFAULT_PASSWORD')}")
        print(f"  * Samba SMB3 Share:      user={env_map.get('SAMBA_USER')}  pass={env_map.get('SAMBA_PASSWORD')}")
        print(f"  * Pi-hole Admin:         pass={env_map.get('PIHOLE_PASSWORD')}")
        print(f"  * Maloja Admin:          pass={env_map.get('MALOJA_ADMIN_PASSWORD')}")
    print("=" * 78)


def cmd_doctor(args: argparse.Namespace) -> int:
    ok, _ = ensure_dependencies(
        auto_install=args.install_deps,
        interactive=(not args.yes and args.install_deps),
        skip_daemon=args.skip_daemon_check,
    )
    profile = gather_host_profile(iface_override=args.iface or "")
    print("\nHost Profile:")
    print(f"  OS / Arch     : {profile.os_name} ({profile.arch})")
    print(f"  CPU / RAM     : {profile.cpu_cores} cores / {profile.total_ram_mb} MB")
    print(f"  Primary NIC   : {profile.net_iface} (LAN IP: {profile.lan_ip or 'none'})")
    print(f"  Tailscale IP  : {profile.tailscale_ip or 'not active'}")
    print(f"  Timezone      : {profile.timezone}")

    conflicts = check_port_conflicts()
    if conflicts:
        print("\nHost Port Notices:")
        for port, msg in sorted(conflicts.items()):
            print(f"  [WARN] Port {port}: {msg}")
    else:
        print("\nHost Port Check: All default ports appear free.")

    return 0 if ok else 1


def cmd_init(args: argparse.Namespace) -> int:
    # MANDATORY GATE: Verify & auto-install all required dependencies BEFORE codebase setup!
    ok, _ = ensure_dependencies(
        auto_install=(not args.no_install_deps),
        interactive=(not args.yes),
        skip_daemon=args.skip_daemon_check,
    )
    if not ok:
        print(
            "\n[ABORTED] Homelab OS workspace/codebase setup blocked until all required dependencies are installed and running.",
            file=sys.stderr,
        )
        return 1

    workspace = resolve_workspace_dir(args.dir, for_init=True)
    bundle_dir = resolve_bundle_dir()

    if getattr(args, "tailscale_authkey", ""):
        ts_cmd = ["tailscale", "up", f"--authkey={args.tailscale_authkey}"]
        if os.name != "nt" and hasattr(os, "geteuid") and os.geteuid() != 0:
            ts_cmd = ["sudo"] + ts_cmd
        print("[INFO] Connecting Tailscale mesh VPN using --tailscale-authkey...")
        subprocess.run(ts_cmd)

    profile = gather_host_profile(iface_override=args.iface or "")
    if not profile.tailscale_ip:
        print("[INFO] Tailscale is installed but not signed in yet. Run 'tailscale up' anytime for private VPN access.")

    print(f"\n[INFO] Host: {profile.os_name} ({profile.arch}) | {profile.cpu_cores} CPU | {profile.total_ram_mb} MB RAM")
    conflicts = check_port_conflicts()
    for port, msg in sorted(conflicts.items()):
        print(f"[WARN] Port {port}: {msg}")

    domain = args.domain
    admin_user = args.user
    admin_pw = args.password
    smb_user = args.smb_user
    storage = args.storage
    zt_emails = args.zero_trust_email

    env_exists = (workspace / ".env").is_file()
    if not args.yes and not env_exists and sys.stdin.isatty():
        domain = input(f"Domain or Hostname [{domain}]: ").strip() or domain
        admin_user = input(f"Admin Username [{admin_user}]: ").strip() or admin_user
        if not admin_pw:
            admin_pw = input("Admin Password [Enter to auto-generate]: ").strip()
        smb_user = input(f"Samba Username [{smb_user}]: ").strip() or smb_user
        storage = input(f"Storage Path [{storage}]: ").strip() or storage
        if not zt_emails:
            zt_emails = input("Cloudflare Zero Trust Emails (comma-separated, optional) [skip]: ").strip()

    print(f"[INFO] Installing Homelab OS stack files into: {workspace}")
    copy_stack_bundle(bundle_dir, workspace, refresh_only=False)

    generated_new, env_map = generate_env_config(
        workspace_dir=workspace,
        profile=profile,
        domain=domain,
        admin_user=admin_user,
        admin_password=admin_pw,
        smb_user=smb_user,
        storage_path=storage,
        zero_trust_emails=zt_emails,
        force=args.force,
    )
    if generated_new:
        print("[OK] Generated .env with strong cryptographic secrets.")
    else:
        print("[INFO] Kept existing .env (pass --force to regenerate).")

    ensure_runtime_directories(workspace, env_map.get("STORAGE_PATH", "./storage"))
    print("[OK] Initialized persistent storage and service directories.")

    _print_endpoints(workspace, profile, env_map, generated_new=generated_new)

    should_start = args.start
    if not should_start and not args.yes and sys.stdin.isatty():
        ans = input("Build and start all Homelab OS containers now? [y/N] ").strip().lower()
        should_start = ans in ("y", "yes")

    if should_start:
        return _run_compose(workspace, ["up", "-d", "--build"])

    print(f"\nNext step: homelab up --dir \"{workspace}\"")
    return 0


def _require_initialized_workspace(explicit_dir: Optional[str]) -> Optional[Path]:
    ws = resolve_workspace_dir(explicit_dir, for_init=False)
    if not (ws / "docker-compose.yml").is_file():
        print(f"[ERROR] No Homelab OS workspace found at {ws}. Run 'homelab init' first.", file=sys.stderr)
        return None
    return ws


def cmd_up(args: argparse.Namespace) -> int:
    ok, _ = ensure_dependencies(
        auto_install=args.install_deps,
        interactive=False,
        skip_daemon=False,
    )
    if not ok:
        return 1
    ws = _require_initialized_workspace(args.dir)
    if not ws:
        return 1
    compose_args = ["up", "-d"]
    if args.build:
        compose_args.append("--build")
    return _run_compose(ws, compose_args)


def cmd_down(args: argparse.Namespace) -> int:
    ws = _require_initialized_workspace(args.dir)
    if not ws:
        return 1
    return _run_compose(ws, ["down"])


def cmd_restart(args: argparse.Namespace) -> int:
    ws = _require_initialized_workspace(args.dir)
    if not ws:
        return 1
    c_args = ["restart"]
    if args.service:
        c_args.append(args.service)
    return _run_compose(ws, c_args)


def cmd_status(args: argparse.Namespace) -> int:
    ws = _require_initialized_workspace(args.dir)
    if not ws:
        return 1
    rc = _run_compose(ws, ["ps"])
    env_map = parse_env_file(ws / ".env")
    profile = gather_host_profile()
    _print_endpoints(ws, profile, env_map, generated_new=False)
    return rc


def cmd_logs(args: argparse.Namespace) -> int:
    ws = _require_initialized_workspace(args.dir)
    if not ws:
        return 1
    c_args = ["logs", "--tail", str(args.tail)]
    if args.follow:
        c_args.append("-f")
    if args.service:
        c_args.append(args.service)
    return _run_compose(ws, c_args)


def cmd_backup(args: argparse.Namespace) -> int:
    ws = _require_initialized_workspace(args.dir)
    if not ws:
        return 1
    return _run_compose(ws, ["exec", "admin-dashboard", "bash", "/scripts/backup.sh"])


def cmd_upgrade(args: argparse.Namespace) -> int:
    ws = _require_initialized_workspace(args.dir)
    if not ws:
        return 1
    bundle_dir = resolve_bundle_dir()
    copy_stack_bundle(bundle_dir, ws, refresh_only=True)
    env_map = parse_env_file(ws / ".env")
    ensure_runtime_directories(ws, env_map.get("STORAGE_PATH", "./storage"))
    print(f"[OK] Refreshed framework files in {ws} (.env and data untouched).")
    if args.no_start:
        return 0
    return _run_compose(ws, ["up", "-d", "--build"])


def cmd_watchdog(args: argparse.Namespace) -> int:
    if os.name == "nt":
        print("On Windows, map the SMB share directly with:")
        print(f"  net use Z: \\\\{args.server_ip}\\{args.share} /user:{args.user} /persistent:yes")
        return 0
    ws = resolve_workspace_dir(args.dir, for_init=False)
    script = ws / "scripts" / "client_smb_watchdog.sh"
    if not script.is_file():
        script = resolve_bundle_dir() / "scripts" / "client_smb_watchdog.sh"
    return subprocess.run(
        ["bash", str(script), args.server_ip, args.share, args.mount_point, args.user]
    ).returncode


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="homelab",
        description="Homelab OS (HL-OS) — Cross-platform self-hosted server CLI",
    )
    parser.add_argument("--version", action="version", version=f"homelab-os {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_doc = sub.add_parser("doctor", help="Check host dependencies, hardware & port conflicts")
    p_doc.add_argument("-y", "--yes", action="store_true", help="Non-interactive confirmation")
    p_doc.add_argument("--install-deps", action="store_true", help="Automatically install missing dependencies")
    p_doc.add_argument("--skip-daemon-check", action="store_true", help="Skip active Docker daemon check")
    p_doc.add_argument("--iface", default="", help="Override detected primary NIC")
    p_doc.set_defaults(func=cmd_doctor)

    p_init = sub.add_parser("init", help="Verify/install dependencies, then provision & configure Homelab OS")
    p_init.add_argument("-y", "--yes", action="store_true", help="Non-interactive mode (accept defaults & auto-install deps)")
    p_init.add_argument("--dir", default=None, help="Target workspace directory (default: ~/.homelab)")
    p_init.add_argument("--start", action="store_true", help="Build and start all containers after setup")
    p_init.add_argument("--force", action="store_true", help="Overwrite existing .env cleanly (creates backup)")
    p_init.add_argument("--no-install-deps", action="store_true", help="Fail instead of auto-installing missing dependencies")
    p_init.add_argument("--skip-daemon-check", action="store_true", help="Check CLI presence without requiring running Docker daemon")
    p_init.add_argument("--storage", default="./storage", help="Storage directory for music, shares & snapshots")
    p_init.add_argument("--domain", default="homelab.local", help="Primary domain or hostname")
    p_init.add_argument("--user", default="admin", help="Admin Dashboard & Nextcloud username")
    p_init.add_argument("--password", default="", help="Admin password (auto-generated if omitted)")
    p_init.add_argument("--smb-user", default="homelab", help="Samba share username")
    p_init.add_argument("--iface", default="", help="Host network interface for telemetry")
    p_init.add_argument("--zero-trust-email", default="", help="Comma-separated Cloudflare Zero Trust allowed emails")
    p_init.add_argument("--tailscale-authkey", default="", help="Optional Tailscale auth key to run `tailscale up` non-interactively")
    p_init.set_defaults(func=cmd_init)

    p_up = sub.add_parser("up", help="Start all Homelab OS containers")
    p_up.add_argument("--dir", default=None, help="Workspace directory")
    p_up.add_argument("--build", action="store_true", help="Rebuild Admin Dashboard image before starting")
    p_up.add_argument("--install-deps", action="store_true", help="Auto-install/start Docker if missing")
    p_up.set_defaults(func=cmd_up)

    p_down = sub.add_parser("down", help="Stop all Homelab OS containers")
    p_down.add_argument("--dir", default=None, help="Workspace directory")
    p_down.set_defaults(func=cmd_down)

    p_rst = sub.add_parser("restart", help="Restart all services or a single container")
    p_rst.add_argument("service", nargs="?", default="", help="Optional container service name")
    p_rst.add_argument("--dir", default=None, help="Workspace directory")
    p_rst.set_defaults(func=cmd_restart)

    p_st = sub.add_parser("status", help="Show container status and service URLs")
    p_st.add_argument("--dir", default=None, help="Workspace directory")
    p_st.set_defaults(func=cmd_status)

    p_logs = sub.add_parser("logs", help="View container logs")
    p_logs.add_argument("service", nargs="?", default="", help="Optional service name")
    p_logs.add_argument("-f", "--follow", action="store_true", help="Follow log output")
    p_logs.add_argument("--tail", type=int, default=100, help="Lines to show from end")
    p_logs.add_argument("--dir", default=None, help="Workspace directory")
    p_logs.set_defaults(func=cmd_logs)

    p_bak = sub.add_parser("backup", help="Trigger snapshot backup inside admin-dashboard")
    p_bak.add_argument("--dir", default=None, help="Workspace directory")
    p_bak.set_defaults(func=cmd_backup)

    p_upg = sub.add_parser("upgrade", help="Update stack files in workspace without touching .env/data")
    p_upg.add_argument("--dir", default=None, help="Workspace directory")
    p_upg.add_argument("--no-start", action="store_true", help="Refresh files without recreating containers")
    p_upg.set_defaults(func=cmd_upgrade)

    p_wd = sub.add_parser("watchdog", help="Run SMB auto-reconnect client watchdog (macOS/Linux)")
    p_wd.add_argument("server_ip", help="Server VPN / LAN IP")
    p_wd.add_argument("--share", default="Storage", help="SMB share name")
    p_wd.add_argument("--mount-point", default="/Volumes/Storage", help="Local mount point")
    p_wd.add_argument("--user", default="homelab", help="SMB username")
    p_wd.add_argument("--dir", default=None, help="Workspace directory")
    p_wd.set_defaults(func=cmd_watchdog)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    if not raw or (raw[0].startswith("-") and raw[0] not in ("-h", "--help", "--version")):
        raw = ["init"] + raw
    parser = build_parser()
    args = parser.parse_args(raw)
    return int(args.func(args))
