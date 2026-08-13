#!/usr/bin/env python3
"""Install / verify EstrellaDBBackup Windows scheduled task (B-019).

Copies ``run_estrella_db_backup.py`` to ``C:\\PZ\\scripts\\`` and registers a
daily schtask with a short ``/TR`` (schtasks limit: 261 chars).

Does NOT mutate live databases — only writes under settings.backup_root.
Creating/updating the schtask requires Administrator.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

TASK_NAME = "EstrellaDBBackup"
PROD_ROOT = Path(r"C:\PZ")
SCRIPTS_DIR = PROD_ROOT / "scripts"
RUNNER_NAME = "run_estrella_db_backup.py"
PYTHON = Path(r"C:\Users\Super Fashion\AppData\Local\Programs\Python\Python39\python.exe")


def _repo_runner() -> Path:
    # Prefer sibling of this installer (service/scripts/), else PZ-main path.
    here = Path(__file__).resolve().parent / RUNNER_NAME
    if here.exists():
        return here
    alt = Path(r"C:\PZ-main\service\scripts") / RUNNER_NAME
    if alt.exists():
        return alt
    raise FileNotFoundError(f"Cannot locate {RUNNER_NAME}")


def _ensure_runner_on_disk() -> Path:
    SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    dest = SCRIPTS_DIR / RUNNER_NAME
    src = _repo_runner()
    shutil.copy2(src, dest)
    return dest


def _query_task() -> int:
    return subprocess.call(
        ["schtasks", "/Query", "/TN", TASK_NAME],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def install(hour: int = 2, minute: int = 15) -> int:
    if not PYTHON.exists():
        print(f"ERROR: python not found: {PYTHON}", file=sys.stderr)
        return 1
    if not (PROD_ROOT / "app").is_dir():
        print(f"ERROR: production app missing: {PROD_ROOT / 'app'}", file=sys.stderr)
        return 1

    runner = _ensure_runner_on_disk()
    tr = f'"{PYTHON}" -X utf8 "{runner}"'
    if len(tr) > 261:
        print(f"ERROR: /TR length {len(tr)} exceeds 261", file=sys.stderr)
        return 1

    subprocess.call(
        ["schtasks", "/Delete", "/TN", TASK_NAME, "/F"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    cmd = [
        "schtasks", "/Create", "/TN", TASK_NAME,
        "/SC", "DAILY",
        "/ST", f"{hour:02d}:{minute:02d}",
        "/RU", "SYSTEM",
        "/RL", "HIGHEST",
        "/F",
        "/TR", tr,
    ]
    print("Creating", TASK_NAME, "TR=", tr, "len=", len(tr))
    rc = subprocess.call(cmd)
    if rc != 0:
        print("ERROR: schtasks /Create failed", rc, file=sys.stderr)
        return rc
    print("OK: task created. Query:")
    subprocess.call(["schtasks", "/Query", "/TN", TASK_NAME, "/V", "/FO", "LIST"])
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="B-019 EstrellaDBBackup schtask installer")
    p.add_argument("--install", action="store_true", help="Create/replace the daily schtask")
    p.add_argument("--query", action="store_true", help="Query task presence (exit 0 if present)")
    p.add_argument("--hour", type=int, default=2)
    p.add_argument("--minute", type=int, default=15)
    args = p.parse_args()
    if args.query:
        rc = _query_task()
        print("PRESENT" if rc == 0 else "ABSENT")
        return 0 if rc == 0 else 2
    if args.install:
        return install(args.hour, args.minute)
    p.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
