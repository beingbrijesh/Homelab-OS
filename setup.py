"""Custom setuptools build hook to bundle root stack templates inside homelab_os/bundle without git duplication."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from setuptools import setup
from setuptools.command.build_py import build_py as _build_py

STACK_ITEMS = (
    "docker-compose.yml",
    ".env.example",
    "admin-dashboard",
    "config",
    "nextcloud",
    "scripts",
)
SKIP_DIRS = {"data", "logs", "__pycache__", ".pytest_cache", ".git", "node_modules", "bundle"}
SKIP_SUFFIXES = (".db", ".db-wal", ".db-shm", ".sqlite", ".sqlite3", ".log", ".pyc", ".pyo")


def _copy_clean_tree(src: Path, dst: Path) -> None:
    for root, dirs, files in os.walk(src):
        rel = Path(root).relative_to(src)
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        out_dir = dst / rel
        out_dir.mkdir(parents=True, exist_ok=True)
        for fname in files:
            if fname in (".env", ".DS_Store") or fname.startswith("._") or fname.endswith(SKIP_SUFFIXES):
                continue
            shutil.copy2(Path(root) / fname, out_dir / fname)


class build_py(_build_py):
    def run(self) -> None:
        super().run()
        repo_root = Path(__file__).resolve().parent
        bundle_dst = Path(self.build_lib) / "homelab_os" / "bundle"
        if bundle_dst.exists():
            shutil.rmtree(bundle_dst)
        bundle_dst.mkdir(parents=True, exist_ok=True)

        for item in STACK_ITEMS:
            src = repo_root / item
            dst = bundle_dst / item
            if not src.exists():
                continue
            if src.is_file():
                shutil.copy2(src, dst)
            else:
                _copy_clean_tree(src, dst)


setup(
    packages=["homelab_os"],
    cmdclass={"build_py": build_py},
)
