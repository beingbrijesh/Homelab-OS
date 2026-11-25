"""Cross-platform host dependency verification and auto-installation gate."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple


@dataclass
class DependencyStatus:
    name: str
    required: bool
    ok: bool
    detail: str
    remediation: str = ""


def _run_capture(cmd: List[str], timeout: int = 10) -> Tuple[int, str]:
    try:
        res = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
        )
        return res.returncode, (res.stdout or "").strip()
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, str(exc)


def _default_runner(cmd: List[str]) -> int:
    print(f"  -> Running: {' '.join(cmd)}")
    try:
        return subprocess.run(cmd).returncode
    except OSError as exc:
        print(f"  [ERROR] Failed to run {cmd[0]}: {exc}")
        return 1


def _find_tool(
    name: str,
    which_fn: Callable[[str], Optional[str]] = shutil.which,
    os_name: Optional[str] = None,
) -> Optional[str]:
    found = which_fn(name)
    if found:
        return found
    system = (os_name or platform.system()).lower()
    if system == "darwin" and name == "tailscale":
        mac_app = "/Applications/Tailscale.app/Contents/MacOS/Tailscale"
        if os.path.exists(mac_app):
            return mac_app
    if system == "windows":
        if name == "tailscale":
            win_ts = os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "Tailscale", "tailscale.exe")
            if os.path.exists(win_ts):
                return win_ts
        if name == "openssl":
            git_ssl = os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "Git", "usr", "bin", "openssl.exe")
            if os.path.exists(git_ssl):
                return git_ssl
    if system == "linux" and name == "mount.cifs":
        for p in ("/sbin/mount.cifs", "/usr/sbin/mount.cifs"):
            if os.path.exists(p):
                return p
    return None


def detect_compose_cmd(which_fn: Callable[[str], Optional[str]] = shutil.which) -> Optional[List[str]]:
    if which_fn("docker"):
        rc, _ = _run_capture(["docker", "compose", "version"])
        if rc == 0:
            return ["docker", "compose"]
    if which_fn("docker-compose"):
        rc, _ = _run_capture(["docker-compose", "--version"])
        if rc == 0:
            return ["docker-compose"]
    return None


def detect_package_manager(
    os_name: Optional[str] = None,
    which_fn: Callable[[str], Optional[str]] = shutil.which,
) -> Optional[str]:
    system = (os_name or platform.system()).lower()
    if system == "linux":
        for mgr in ("apt-get", "dnf", "yum", "pacman", "apk"):
            if which_fn(mgr):
                return mgr
        return None
    if system == "darwin":
        return "brew" if which_fn("brew") else None
    if system == "windows":
        for mgr in ("winget", "scoop", "choco"):
            if which_fn(mgr):
                return mgr
        return None
    return None


def check_dependencies(
    skip_daemon: bool = False,
    which_fn: Callable[[str], Optional[str]] = shutil.which,
    os_name: Optional[str] = None,
) -> List[DependencyStatus]:
    system = (os_name or platform.system()).lower()
    statuses: List[DependencyStatus] = []

    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    statuses.append(
        DependencyStatus(
            name="python",
            required=True,
            ok=(sys.version_info >= (3, 9)),
            detail=f"Python {py_ver}",
            remediation="Install Python 3.9 or higher.",
        )
    )

    for tool, hint in (
        ("curl", "Install curl via your OS package manager."),
        ("openssl", "Install openssl via your OS package manager."),
        ("git", "Install git via your OS package manager."),
    ):
        found = _find_tool(tool, which_fn=which_fn, os_name=system)
        statuses.append(
            DependencyStatus(
                name=tool,
                required=True,
                ok=bool(found),
                detail=found or f"{tool} not found in PATH",
                remediation=hint,
            )
        )

    ts_bin = _find_tool("tailscale", which_fn=which_fn, os_name=system)
    statuses.append(
        DependencyStatus(
            name="tailscale",
            required=True,
            ok=bool(ts_bin),
            detail=ts_bin or "tailscale not installed",
            remediation="Install Tailscale (Linux: curl -fsSL https://tailscale.com/install.sh | sh; macOS: brew install --cask tailscale; Windows: winget install Tailscale.Tailscale).",
        )
    )

    if system == "linux":
        cifs = _find_tool("mount.cifs", which_fn=which_fn, os_name=system)
        statuses.append(
            DependencyStatus(
                name="cifs_utils",
                required=True,
                ok=bool(cifs),
                detail=cifs or "mount.cifs not installed",
                remediation="Install cifs-utils (needed for SMB watchdog client mounts on Linux).",
            )
        )

    docker_path = _find_tool("docker", which_fn=which_fn, os_name=system)
    if docker_path:
        rc, out = _run_capture(["docker", "--version"])
        statuses.append(
            DependencyStatus(
                name="docker",
                required=True,
                ok=(rc == 0),
                detail=out.splitlines()[0] if out else docker_path,
                remediation="Install Docker Engine / Docker Desktop.",
            )
        )
    else:
        statuses.append(
            DependencyStatus(
                name="docker",
                required=True,
                ok=False,
                detail="docker CLI not found in PATH",
                remediation="Install Docker Engine (Linux) or Docker Desktop (macOS/Windows).",
            )
        )

    compose_cmd = detect_compose_cmd(which_fn=which_fn)
    if compose_cmd:
        rc, out = _run_capture(compose_cmd + ["version"])
        statuses.append(
            DependencyStatus(
                name="docker_compose",
                required=True,
                ok=(rc == 0),
                detail=out.splitlines()[0] if out else " ".join(compose_cmd),
                remediation="Install Docker Compose v2 plugin.",
            )
        )
    else:
        statuses.append(
            DependencyStatus(
                name="docker_compose",
                required=True,
                ok=False,
                detail="docker compose v2 plugin not found",
                remediation="Install Docker Compose v2 (included with Docker Desktop / docker-compose-plugin).",
            )
        )

    if not skip_daemon:
        if docker_path:
            rc, out = _run_capture(["docker", "info", "--format", "{{.ServerVersion}}"])
            statuses.append(
                DependencyStatus(
                    name="docker_daemon",
                    required=True,
                    ok=(rc == 0),
                    detail=f"Engine {out}" if rc == 0 and out else "daemon not reachable",
                    remediation="Start the Docker service (Linux: sudo systemctl enable --now docker; macOS/Windows: start Docker Desktop).",
                )
            )
        else:
            statuses.append(
                DependencyStatus(
                    name="docker_daemon",
                    required=True,
                    ok=False,
                    detail="docker CLI missing",
                    remediation="Install and start Docker first.",
                )
            )

    return statuses


def _with_sudo(cmd: List[str], is_root: bool, which_fn: Callable[[str], Optional[str]]) -> List[str]:
    if is_root:
        return cmd
    if which_fn("sudo"):
        return ["sudo"] + cmd
    return cmd


def get_install_plan(
    missing_names: List[str],
    os_name: Optional[str] = None,
    pkg_mgr: Optional[str] = None,
    is_root: Optional[bool] = None,
    which_fn: Callable[[str], Optional[str]] = shutil.which,
) -> List[List[str]]:
    system = (os_name or platform.system()).lower()
    mgr = pkg_mgr or detect_package_manager(os_name=system, which_fn=which_fn)
    if is_root is None:
        is_root = hasattr(os, "geteuid") and os.geteuid() == 0

    missing = set(missing_names)
    need_docker = bool(missing & {"docker", "docker_compose"})
    need_daemon = "docker_daemon" in missing
    need_tailscale = "tailscale" in missing
    cmds: List[List[str]] = []

    if system == "linux":
        # 1. Base CLI & SMB utilities first (guarantees curl/ca-certificates/openssl/git/cifs-utils before Docker/Tailscale scripts)
        linux_base_pkgs: List[str] = []
        if "curl" in missing or need_docker or need_tailscale:
            linux_base_pkgs.extend(["curl", "ca-certificates"])
        if "openssl" in missing:
            linux_base_pkgs.append("openssl")
        if "git" in missing:
            linux_base_pkgs.append("git")
        if "cifs_utils" in missing:
            linux_base_pkgs.append("cifs-utils")
        # Deduplicate while preserving order
        linux_base_pkgs = list(dict.fromkeys(linux_base_pkgs))

        # Only install base packages if any base tool is actually missing
        if bool(missing & {"curl", "openssl", "git", "cifs_utils"}) or (
            (need_docker or need_tailscale) and not which_fn("curl")
        ):
            if mgr == "apt-get":
                cmds.append(_with_sudo(["apt-get", "update"], is_root, which_fn))
                cmds.append(_with_sudo(["apt-get", "install", "-y"] + linux_base_pkgs, is_root, which_fn))
            elif mgr in ("dnf", "yum"):
                cmds.append(_with_sudo([mgr, "install", "-y"] + linux_base_pkgs, is_root, which_fn))
            elif mgr == "pacman":
                cmds.append(_with_sudo(["pacman", "-Sy", "--noconfirm"] + linux_base_pkgs, is_root, which_fn))
            elif mgr == "apk":
                cmds.append(_with_sudo(["apk", "add", "--no-cache"] + linux_base_pkgs, is_root, which_fn))

        # 2. Docker Engine + Compose v2
        if need_docker:
            if which_fn("curl") or "curl" in linux_base_pkgs:
                cmds.append(_with_sudo(["sh", "-c", "curl -fsSL https://get.docker.com | sh"], is_root, which_fn))
            elif mgr == "apt-get":
                cmds.append(_with_sudo(["apt-get", "install", "-y", "docker.io", "docker-compose-v2"], is_root, which_fn))
            elif mgr in ("dnf", "yum"):
                cmds.append(_with_sudo([mgr, "install", "-y", "docker", "docker-compose-plugin"], is_root, which_fn))
            elif mgr == "pacman":
                cmds.append(_with_sudo(["pacman", "-S", "--noconfirm", "docker", "docker-compose"], is_root, which_fn))
            elif mgr == "apk":
                cmds.append(_with_sudo(["apk", "add", "--no-cache", "docker", "docker-cli-compose"], is_root, which_fn))

        if need_docker or need_daemon:
            if which_fn("systemctl") or mgr in ("apt-get", "dnf", "yum", "pacman"):
                cmds.append(_with_sudo(["systemctl", "enable", "--now", "docker"], is_root, which_fn))
            user = os.environ.get("USER") or os.environ.get("LOGNAME")
            if user and not is_root and which_fn("usermod"):
                cmds.append(_with_sudo(["usermod", "-aG", "docker", user], is_root, which_fn))

        # 3. Tailscale mesh VPN
        if need_tailscale:
            cmds.append(_with_sudo(["sh", "-c", "curl -fsSL https://tailscale.com/install.sh | sh"], is_root, which_fn))
            if which_fn("systemctl") or mgr in ("apt-get", "dnf", "yum", "pacman"):
                cmds.append(_with_sudo(["systemctl", "enable", "--now", "tailscaled"], is_root, which_fn))

    elif system == "darwin":
        if mgr == "brew":
            for tool, pkg in (("curl", "curl"), ("openssl", "openssl@3"), ("git", "git")):
                if tool in missing:
                    cmds.append(["brew", "install", pkg])
            if need_docker:
                cmds.append(["brew", "install", "--cask", "docker"])
            if need_tailscale:
                cmds.append(["brew", "install", "--cask", "tailscale"])
                cmds.append(["open", "-a", "Tailscale"])
        if need_docker or need_daemon:
            cmds.append(["open", "-a", "Docker"])

    elif system == "windows":
        if mgr == "winget":
            if bool(missing & {"git", "openssl"}):
                cmds.append([
                    "winget", "install", "--id", "Git.Git", "-e",
                    "--accept-source-agreements", "--accept-package-agreements",
                ])
            if "curl" in missing:
                cmds.append([
                    "winget", "install", "--id", "cURL.cURL", "-e",
                    "--accept-source-agreements", "--accept-package-agreements",
                ])
            if need_docker:
                cmds.append([
                    "winget", "install", "--id", "Docker.DockerDesktop", "-e",
                    "--accept-source-agreements", "--accept-package-agreements",
                ])
            if need_tailscale:
                cmds.append([
                    "winget", "install", "--id", "Tailscale.Tailscale", "-e",
                    "--accept-source-agreements", "--accept-package-agreements",
                ])
        elif mgr == "choco":
            if bool(missing & {"git", "openssl"}):
                cmds.append(["choco", "install", "git", "openssl", "-y"])
            if need_docker:
                cmds.append(["choco", "install", "docker-desktop", "-y"])
            if need_tailscale:
                cmds.append(["choco", "install", "tailscale", "-y"])
        elif mgr == "scoop":
            scoop_pkgs = []
            if "git" in missing:
                scoop_pkgs.append("git")
            if "openssl" in missing:
                scoop_pkgs.append("openssl")
            if "curl" in missing:
                scoop_pkgs.append("curl")
            if need_docker:
                scoop_pkgs.extend(["docker", "docker-compose"])
            if need_tailscale:
                scoop_pkgs.append("tailscale")
            if scoop_pkgs:
                cmds.append(["scoop", "install"] + scoop_pkgs)

        if need_docker or need_daemon:
            desktop_exe = os.path.join(
                os.environ.get("ProgramFiles", r"C:\Program Files"),
                "Docker", "Docker", "Docker Desktop.exe",
            )
            if os.path.exists(desktop_exe):
                cmds.append([desktop_exe])

    return cmds


def _default_confirm(prompt: str) -> bool:
    if not sys.stdin.isatty():
        return False
    ans = input(f"{prompt} [Y/n] ").strip().lower()
    return ans in ("", "y", "yes")


def print_dependency_report(statuses: List[DependencyStatus]) -> None:
    print("Host Dependency Verification:")
    for st in statuses:
        tag = "[OK]" if st.ok else ("[MISSING]" if st.required else "[OPT]")
        req = "required" if st.required else "optional"
        print(f"  {tag:10s} {st.name:15s} ({req}) — {st.detail}")


def ensure_dependencies(
    auto_install: bool = True,
    interactive: bool = False,
    skip_daemon: bool = False,
    confirm_fn: Optional[Callable[[str], bool]] = None,
    runner: Optional[Callable[[List[str]], int]] = None,
    check_fn: Optional[Callable[..., List[DependencyStatus]]] = None,
    os_name: Optional[str] = None,
    which_fn: Callable[[str], Optional[str]] = shutil.which,
    is_root: Optional[bool] = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> Tuple[bool, List[DependencyStatus]]:
    if check_fn is not None:
        check = check_fn
    elif os_name is not None:
        check = lambda skip_daemon=False: check_dependencies(skip_daemon=skip_daemon, which_fn=which_fn, os_name=os_name)
    else:
        check = lambda skip_daemon=False: check_dependencies(skip_daemon=skip_daemon, which_fn=which_fn)
    run_cmd = runner or _default_runner
    ask = confirm_fn or _default_confirm
    system = os_name or platform.system()

    statuses = check(skip_daemon=skip_daemon)
    print_dependency_report(statuses)
    missing = [s for s in statuses if s.required and not s.ok]
    if not missing:
        return True, statuses

    print("\nMissing required dependencies detected before Homelab OS setup:")
    for item in missing:
        print(f"  - {item.name}: {item.remediation or item.detail}")

    if not auto_install:
        print("\nDependency installation skipped (--no-install-deps). Install the items above and re-run.")
        return False, statuses

    if interactive and not ask("\nInstall missing required dependencies now before continuing?"):
        print("Aborted: all required dependencies must be installed before Homelab OS setup.")
        return False, statuses

    pkg_mgr = detect_package_manager(os_name=system, which_fn=which_fn)
    plan = get_install_plan(
        [m.name for m in missing],
        os_name=system,
        pkg_mgr=pkg_mgr,
        is_root=is_root,
        which_fn=which_fn,
    )
    if not plan:
        print("\nCould not find an automated package manager to install missing dependencies on this host.")
        return False, statuses

    print("\nInstalling missing dependencies first...")
    for cmd in plan:
        rc = run_cmd(cmd)
        if rc != 0:
            print(f"  [WARN] Command exited with code {rc}: {' '.join(cmd)}")

    for attempt in range(10):
        final_statuses = check(skip_daemon=skip_daemon)
        still_missing = [s for s in final_statuses if s.required and not s.ok]
        if not still_missing:
            print("\nAll required dependencies verified!")
            print_dependency_report(final_statuses)
            return True, final_statuses
        if len(still_missing) == 1 and still_missing[0].name == "docker_daemon" and attempt < 9:
            sleep_fn(2.0)
            continue
        break

    print("\nDependency verification still failed after installation attempt:")
    for item in still_missing:
        print(f"  - {item.name}: {item.remediation or item.detail}")
    print("Homelab OS setup cannot proceed until all required dependencies are working.")
    return False, final_statuses
