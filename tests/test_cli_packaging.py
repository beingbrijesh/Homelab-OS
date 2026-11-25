import os
import sys
import subprocess
from pathlib import Path
import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))


def test_deps_gate_blocks_when_missing_and_no_auto_install():
    from homelab_os.deps import DependencyStatus, ensure_dependencies

    missing = [
        DependencyStatus(name="python", required=True, ok=True, detail="3.11.9"),
        DependencyStatus(name="docker", required=True, ok=False, detail="not found", remediation="Install Docker"),
        DependencyStatus(name="docker_compose", required=True, ok=False, detail="not found", remediation="Install Compose"),
    ]
    ok, statuses = ensure_dependencies(
        auto_install=False,
        interactive=False,
        check_fn=lambda skip_daemon=False: missing,
    )
    assert ok is False
    assert any(not s.ok and s.name == "docker" for s in statuses)


def test_deps_gate_installs_missing_and_re_verifies():
    from homelab_os.deps import DependencyStatus, ensure_dependencies

    state = {"installed": False}
    executed = []

    def fake_check(skip_daemon=False):
        if not state["installed"]:
            return [
                DependencyStatus(name="python", required=True, ok=True, detail="3.11.9"),
                DependencyStatus(name="docker", required=True, ok=False, detail="not found"),
                DependencyStatus(name="docker_compose", required=True, ok=False, detail="not found"),
                DependencyStatus(name="docker_daemon", required=True, ok=False, detail="stopped"),
            ]
        return [
            DependencyStatus(name="python", required=True, ok=True, detail="3.11.9"),
            DependencyStatus(name="docker", required=True, ok=True, detail="Docker 29.0"),
            DependencyStatus(name="docker_compose", required=True, ok=True, detail="Compose v2"),
            DependencyStatus(name="docker_daemon", required=True, ok=True, detail="running"),
        ]

    def fake_runner(cmd):
        executed.append(cmd)
        state["installed"] = True
        return 0

    ok, statuses = ensure_dependencies(
        auto_install=True,
        interactive=False,
        check_fn=fake_check,
        runner=fake_runner,
        os_name="Linux",
        which_fn=lambda name: "/usr/bin/apt-get" if name == "apt-get" else None,
        is_root=True,
        sleep_fn=lambda _: None,
    )
    assert ok is True
    assert len(executed) >= 1
    assert all(s.ok for s in statuses if s.required)


def test_deps_gate_fails_if_post_install_verification_still_fails():
    from homelab_os.deps import DependencyStatus, ensure_dependencies

    always_missing = [
        DependencyStatus(name="python", required=True, ok=True, detail="3.11.9"),
        DependencyStatus(name="docker", required=True, ok=False, detail="not found"),
    ]
    ok, _ = ensure_dependencies(
        auto_install=True,
        interactive=False,
        check_fn=lambda skip_daemon=False: always_missing,
        runner=lambda cmd: 0,
        os_name="Linux",
        which_fn=lambda name: "/usr/bin/apt-get" if name == "apt-get" else None,
        is_root=True,
        sleep_fn=lambda _: None,
    )
    assert ok is False


def test_install_plan_per_platform():
    from homelab_os.deps import get_install_plan

    linux_cmds = get_install_plan(
        ["curl", "openssl", "git", "cifs_utils", "docker", "docker_daemon", "tailscale"],
        os_name="Linux",
        pkg_mgr="apt-get",
        is_root=False,
        which_fn=lambda x: "/usr/bin/sudo" if x == "sudo" else None,
    )
    joined = [" ".join(c) for c in linux_cmds]
    # curl/base packages must be ordered BEFORE get.docker.com and tailscale.com scripts
    curl_idx = next(i for i, s in enumerate(joined) if "apt-get install" in s and "curl" in s)
    docker_idx = next(i for i, s in enumerate(joined) if "get.docker.com" in s)
    ts_idx = next(i for i, s in enumerate(joined) if "tailscale.com/install.sh" in s)
    assert curl_idx < docker_idx < ts_idx
    assert any("cifs-utils" in s for s in joined)
    assert any("tailscaled" in s for s in joined)

    mac_cmds = get_install_plan(
        ["docker", "tailscale"],
        os_name="Darwin",
        pkg_mgr="brew",
        is_root=False,
        which_fn=lambda x: "/opt/homebrew/bin/brew" if x == "brew" else None,
    )
    assert any("brew" in c and "--cask" in c and "docker" in c for c in mac_cmds)
    assert any("brew" in c and "--cask" in c and "tailscale" in c for c in mac_cmds)

    win_cmds = get_install_plan(
        ["git", "docker", "tailscale"],
        os_name="Windows",
        pkg_mgr="winget",
        is_root=False,
        which_fn=lambda x: "winget" if x == "winget" else None,
    )
    assert any("winget" in c and "Git.Git" in c for c in win_cmds)
    assert any("winget" in c and "Docker.DockerDesktop" in c for c in win_cmds)
    assert any("winget" in c and "Tailscale.Tailscale" in c for c in win_cmds)


def test_sysinfo_port_probe_detects_bound_port():
    import socket
    from homelab_os.sysinfo import is_port_in_use

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    try:
        assert is_port_in_use(port, host="127.0.0.1") is True
    finally:
        srv.close()


def test_init_aborts_before_creating_workspace_when_deps_fail(tmp_path, monkeypatch):
    from homelab_os import cli
    from homelab_os.deps import DependencyStatus

    target_dir = tmp_path / "should-not-exist"
    monkeypatch.setattr(
        "homelab_os.deps.check_dependencies",
        lambda skip_daemon=False, which_fn=None, os_name=None: [
            DependencyStatus(name="python", required=True, ok=True, detail="3.11"),
            DependencyStatus(name="docker", required=True, ok=False, detail="missing"),
        ],
    )
    rc = cli.main(["init", "-y", "--no-install-deps", "--dir", str(target_dir)])
    assert rc != 0
    assert not (target_dir / "docker-compose.yml").exists()
    assert not (target_dir / ".env").exists()


def test_init_provisions_workspace_and_env_with_valid_deps(tmp_path, monkeypatch):
    import re
    from homelab_os import cli
    from homelab_os.deps import DependencyStatus

    target_dir = tmp_path / "hl-ws"
    monkeypatch.setattr(
        "homelab_os.deps.check_dependencies",
        lambda skip_daemon=False, which_fn=None, os_name=None: [
            DependencyStatus(name="python", required=True, ok=True, detail="3.11"),
            DependencyStatus(name="curl", required=True, ok=True, detail="/usr/bin/curl"),
            DependencyStatus(name="openssl", required=True, ok=True, detail="/usr/bin/openssl"),
            DependencyStatus(name="git", required=True, ok=True, detail="/usr/bin/git"),
            DependencyStatus(name="tailscale", required=True, ok=True, detail="/usr/local/bin/tailscale"),
            DependencyStatus(name="docker", required=True, ok=True, detail="29.0"),
            DependencyStatus(name="docker_compose", required=True, ok=True, detail="v2"),
            DependencyStatus(name="docker_daemon", required=True, ok=True, detail="running"),
        ],
    )
    rc = cli.main([
        "init", "-y",
        "--dir", str(target_dir),
        "--domain", "cloud.test.local",
        "--user", "cliadmin",
        "--password", "CliPass123",
        "--zero-trust-email", "alice@example.com",
    ])
    assert rc == 0
    assert (target_dir / "docker-compose.yml").is_file()
    assert (target_dir / "admin-dashboard" / "app.py").is_file()
    assert (target_dir / "config" / "maloja" / "_base_patched.py").is_file()
    assert (target_dir / "storage" / "music" / "_playlists").is_dir()
    assert (target_dir / "storage" / "snapshots").is_dir()
    env_file = target_dir / ".env"
    assert env_file.is_file()

    env_text = env_file.read_text()
    compose_text = (target_dir / "docker-compose.yml").read_text()
    env_map = {}
    for line in env_text.splitlines():
        if line.strip() and not line.strip().startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env_map[k.strip()] = v.strip().strip('"').strip("'")
    vars_in_compose = set(re.findall(r"\$\{([A-Z0-9_]+)(?::-[^}]*)?\}", compose_text))
    assert not [v for v in vars_in_compose if v not in env_map]
    assert env_map["ADMIN_DEFAULT_USER"] == "cliadmin"
    assert env_map["ADMIN_DEFAULT_PASSWORD"] == "CliPass123"
    assert env_map["CLOUDFLARE_ZERO_TRUST_ENABLED"] == "true"
    assert env_map["ALLOWED_ZERO_TRUST_EMAILS"] == "alice@example.com"


def test_init_preserves_env_and_upgrade_keeps_env(tmp_path, monkeypatch):
    from homelab_os import cli
    from homelab_os.deps import DependencyStatus

    target_dir = tmp_path / "hl-upgrade"
    monkeypatch.setattr(
        "homelab_os.deps.check_dependencies",
        lambda skip_daemon=False, which_fn=None, os_name=None: [
            DependencyStatus(name="python", required=True, ok=True, detail="3.11"),
            DependencyStatus(name="curl", required=True, ok=True, detail="/usr/bin/curl"),
            DependencyStatus(name="openssl", required=True, ok=True, detail="/usr/bin/openssl"),
            DependencyStatus(name="git", required=True, ok=True, detail="/usr/bin/git"),
            DependencyStatus(name="tailscale", required=True, ok=True, detail="/usr/local/bin/tailscale"),
            DependencyStatus(name="docker", required=True, ok=True, detail="29.0"),
            DependencyStatus(name="docker_compose", required=True, ok=True, detail="v2"),
            DependencyStatus(name="docker_daemon", required=True, ok=True, detail="running"),
        ],
    )
    assert cli.main(["init", "-y", "--dir", str(target_dir), "--password", "KeepSecret99"]) == 0
    original_env = (target_dir / ".env").read_text()
    # Second init without --force preserves .env
    assert cli.main(["init", "-y", "--dir", str(target_dir), "--password", "Other99"]) == 0
    assert (target_dir / ".env").read_text() == original_env

    # Corrupt a template file, run upgrade without starting containers, confirm template restored & .env untouched
    (target_dir / "docker-compose.yml").write_text("# modified")
    assert cli.main(["upgrade", "--dir", str(target_dir), "--no-start"]) == 0
    assert "services:" in (target_dir / "docker-compose.yml").read_text()
    assert (target_dir / ".env").read_text() == original_env


def test_npm_wrapper_cli_entrypoint():
    import shutil
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    res = subprocess.run(
        [node, str(ROOT_DIR / "bin" / "homelab.js"), "--version"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert res.returncode == 0
    assert "homelab-os" in res.stdout
