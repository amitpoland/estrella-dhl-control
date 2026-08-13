#!/usr/bin/env python3
"""Production DB backup job entrypoint (B-019).

Intended invocation (cwd irrelevant; forces C:\\PZ on sys.path):

    python -X utf8 C:\\PZ\\scripts\\run_estrella_db_backup.py

Writes only under settings.backup_root (default C:\\PZ-backups).
Never overwrites live databases.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROD_ROOT = Path(r"C:\PZ")
if str(PROD_ROOT) not in sys.path:
    sys.path.insert(0, str(PROD_ROOT))

from app.core.config import settings  # noqa: E402
from app.services.backup_service import prune_backups, run_backup  # noqa: E402


def main() -> int:
    manifest = run_backup()
    print("BACKUP_OK", manifest.get("backup_id"), manifest.get("summary"))
    print("PRUNE", prune_backups(settings.backup_root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
