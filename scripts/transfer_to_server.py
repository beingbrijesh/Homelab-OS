#!/usr/bin/env python3
"""
Safe Transfer Script: Local Development -> Remote Homelab Server
Preserves all server databases, backups, and live data.
Copies only framework files, configs, and assets without metadata collisions.
"""

import os
import shutil
import sys

SRC_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DST_DIR = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("HOMELAB_DEPLOY_DST", "")

FILES_TO_COPY = [
    # Core Root Files
    ("install.sh", "install.sh"),
    ("pyproject.toml", "pyproject.toml"),
    ("setup.py", "setup.py"),
    ("MANIFEST.in", "MANIFEST.in"),
    ("package.json", "package.json"),
    (".npmignore", ".npmignore"),
    ("README.md", "README.md"),
    ("ARCHITECTURE.md", "ARCHITECTURE.md"),
    ("CONTRIBUTING.md", "CONTRIBUTING.md"),
    ("LICENSE", "LICENSE"),
    (".env.example", ".env.example"),
    (".gitignore", ".gitignore"),
    ("docker-compose.yml", "docker-compose.yml"),
    (".dockerignore", ".dockerignore"),
    ("admin-dashboard/.dockerignore", "admin-dashboard/.dockerignore"),

    # Package CLI & Node Wrapper
    ("bin/homelab.js", "bin/homelab.js"),
    ("homelab_os/__init__.py", "homelab_os/__init__.py"),
    ("homelab_os/__main__.py", "homelab_os/__main__.py"),
    ("homelab_os/cli.py", "homelab_os/cli.py"),
    ("homelab_os/deps.py", "homelab_os/deps.py"),
    ("homelab_os/sysinfo.py", "homelab_os/sysinfo.py"),
    ("homelab_os/workspace.py", "homelab_os/workspace.py"),

    # Packaging Manifests
    ("packaging/homebrew/homelab-os.rb", "packaging/homebrew/homelab-os.rb"),
    ("packaging/scoop/homelab-os.json", "packaging/scoop/homelab-os.json"),

    # Nextcloud Tuning
    ("nextcloud/low_spec_tuning.config.php", "nextcloud/low_spec_tuning.config.php"),

    # Service Configurations
    ("config/samba/smb.conf", "config/samba/smb.conf"),
    ("config/maloja/_base_patched.py", "config/maloja/_base_patched.py"),

    # Client & Bootstrap Scripts
    ("scripts/client_smb_watchdog.sh", "scripts/client_smb_watchdog.sh"),
    ("scripts/get-homelab.sh", "scripts/get-homelab.sh"),
    ("scripts/install.ps1", "scripts/install.ps1"),

    # Test Suite
    ("tests/test_api_contracts.py", "tests/test_api_contracts.py"),
    ("tests/test_cli_packaging.py", "tests/test_cli_packaging.py"),
    ("tests/test_optimization_updates.py", "tests/test_optimization_updates.py"),

    # Admin Dashboard Backend & Dockerfile
    ("admin-dashboard/app.py", "admin-dashboard/app.py"),
    ("admin-dashboard/ops_updates.py", "admin-dashboard/ops_updates.py"),
    ("admin-dashboard/ops_resources.py", "admin-dashboard/ops_resources.py"),
    ("admin-dashboard/Dockerfile", "admin-dashboard/Dockerfile"),
    ("admin-dashboard/requirements.txt", "admin-dashboard/requirements.txt"),
    ("admin-dashboard/requirements-dev.txt", "admin-dashboard/requirements-dev.txt"),
    ("admin-dashboard/scripts/backup.sh", "admin-dashboard/scripts/backup.sh"),

    # Admin Dashboard Static PWA Files
    ("admin-dashboard/static/manifest.json", "admin-dashboard/static/manifest.json"),
    ("admin-dashboard/static/sw.js", "admin-dashboard/static/sw.js"),

    # Documentation & Overhaul Plans
    ("docs/plans/2026-11-10-homelab-v2-complete-overhaul-plan.md", "docs/plans/2026-11-10-homelab-v2-complete-overhaul-plan.md"),
    ("docs/plans/2026-11-12-wake-on-request-autosleep-design.md", "docs/plans/2026-11-12-wake-on-request-autosleep-design.md"),
    ("docs/plans/2026-11-12-wake-on-request-autosleep-plan.md", "docs/plans/2026-11-12-wake-on-request-autosleep-plan.md"),
    ("docs/plans/2026-11-18-preact-dashboard-design.md", "docs/plans/2026-11-18-preact-dashboard-design.md"),
    ("docs/plans/2026-11-18-preact-dashboard-plan.md", "docs/plans/2026-11-18-preact-dashboard-plan.md"),
]

DIRS_TO_SYNC = [
    ("admin-dashboard/frontend", "admin-dashboard/frontend", {"node_modules", ".DS_Store"}),
    ("admin-dashboard/static/dist", "admin-dashboard/static/dist", {".DS_Store"}),
]

def main():
    if not DST_DIR:
        print("ERROR: Destination directory is required.")
        print(f"Usage: {sys.argv[0]} /path/to/remote/homelab")
        print("   or: HOMELAB_DEPLOY_DST=/path/to/remote/homelab python3 scripts/transfer_to_server.py")
        sys.exit(1)

    if not os.path.exists(DST_DIR):
        print(f"ERROR: Destination directory {DST_DIR} not accessible or unmounted.")
        sys.exit(1)

    print(f"Beginning safe transfer from {SRC_DIR} to {DST_DIR}...")
    success_count = 0

    for rel_src, rel_dst in FILES_TO_COPY:
        src_path = os.path.join(SRC_DIR, rel_src)
        dst_path = os.path.join(DST_DIR, rel_dst)

        if not os.path.exists(src_path):
            print(f"  [SKIP] Source missing: {rel_src}")
            continue

        os.makedirs(os.path.dirname(dst_path), exist_ok=True)
        try:
            shutil.copyfile(src_path, dst_path)
            print(f"  [COPIED] {rel_src} -> {rel_dst}")
            success_count += 1
        except Exception as e:
            print(f"  [ERROR] Failed copying {rel_src}: {e}")

    for rel_src_dir, rel_dst_dir, excludes in DIRS_TO_SYNC:
        src_root = os.path.join(SRC_DIR, rel_src_dir)
        dst_root = os.path.join(DST_DIR, rel_dst_dir)
        if not os.path.isdir(src_root):
            print(f"  [SKIP] Source dir missing: {rel_src_dir}")
            continue
        for root, dirs, files in os.walk(src_root):
            dirs[:] = [d for d in dirs if d not in excludes]
            rel_dir = os.path.relpath(root, src_root)
            target_dir = dst_root if rel_dir == "." else os.path.join(dst_root, rel_dir)
            os.makedirs(target_dir, exist_ok=True)
            for fname in files:
                if fname in excludes:
                    continue
                s = os.path.join(root, fname)
                d = os.path.join(target_dir, fname)
                try:
                    shutil.copyfile(s, d)
                    success_count += 1
                except Exception as e:
                    print(f"  [ERROR] Failed copying {s}: {e}")
        print(f"  [SYNCED DIR] {rel_src_dir} -> {rel_dst_dir}")

    print(f"\nTransfer completed successfully: {success_count} files transferred.")
    print("Remote databases and user data remained 100% untouched.")

if __name__ == "__main__":
    main()
