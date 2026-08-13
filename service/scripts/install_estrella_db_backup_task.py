#!/usr/bin/env python3
"""Install / verify EstrellaDBBackup Windows scheduled task (B-019).

Invokes production ``app.services.backup_service.run_backup`` + prune with
cwd semantics equivalent to NSSM AppDirectory (``C:\\PZ`` so ``import app``
resolves to ``C:\\PZ\\app``).

Does NOT mutate live databases — only writes under settings.backup_root
(default ``C:\\PZ-backups``). Creating/updating the schtask requires
Administrator.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

TASK_NAME = "EstrellaDBBackup"
PROD_ROOT = Path(r"C:\PZ")
PYTHON = Path(r"C:\Users\Super Fashion\AppData\Local\Programs\Python\Python39\python.exe")

# Double-quote safe /TR payload for schtasks.
_TR = (
    f'"{PYTHON}" -X utf8 -c '
    "\"import sys; "
    "sys.path.insert(0, r'C:\\\\PZ'); "
    "from app.services.backup_service import run_backup, prune_backups; "
    "from app.core.config import settings; "
    "m = run_backup(); "
    "print('BACKUP_OK', m.get('backup_id'), m.get('summary')); "
    "print('PRUNE', prune_backups(settings.backup_root))\""
)


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
        "/TR", _TR,
    ]
    print("Creating", TASK_NAME, "…")
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
