"""
backup_service.py — B7 Automated Backup Program

SQLite backup service using online backup API. Creates timestamped backups
of all operational databases with integrity verification and retention management.

Architecture:
- `run_backup()` — creates timestamped backup with manifest
- `prune_backups()` — retention policy: 7 daily, 4 weekly, 12 monthly
- Lockfile prevents concurrent runs
- WAL checkpoint before backup ensures consistent state
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from ..core.config import settings
from ..core.audit import audit_db_path


def _get_db_registry() -> List[Tuple[str, Path]]:
    """
    Return list of (name, path) for all registered databases.

    Derives from storage modules at call time for test compatibility.
    Non-existent files are included (marked as "absent" in manifest).
    """
    storage_root = Path(settings.storage_root)

    # Auth database (from main.py line 125/153)
    auth_db = (
        Path(settings.auth_db_path) if settings.auth_db_path
        else storage_root / "users.db"
    )

    return [
        ("packing", storage_root / "packing.db"),
        ("warehouse", storage_root / "warehouse.db"),
        ("documents", storage_root / "documents.db"),
        ("wfirma", storage_root / "wfirma.db"),
        ("correction_registry", storage_root / "correction_registry.db"),
        ("intake_lineage", storage_root / "intake_lineage.db"),
        ("proforma_links", storage_root / "proforma_links.db"),
        ("tracking_events", storage_root / "tracking_events.db"),
        ("reservation_queue", storage_root / "reservation_queue.db"),
        ("customer_master", storage_root / "customer_master.sqlite"),
        ("master_audit", audit_db_path()),
        ("master_data", storage_root / "master_data.sqlite"),
        ("suppliers", storage_root / "suppliers.sqlite"),
        ("users", auth_db),
        ("packing_resolutions", storage_root / "packing_resolutions.sqlite"),
    ]


def _create_lockfile(backup_root: Path) -> Path:
    """Create lockfile, checking for stale locks (>1h old)."""
    lockfile = backup_root / "backup.lock"

    if lockfile.exists():
        try:
            stat = lockfile.stat()
            age_seconds = time.time() - stat.st_mtime
            if age_seconds > 3600:  # 1 hour
                lockfile.unlink()  # Remove stale lock
            else:
                raise RuntimeError(f"Backup already running (lock age: {age_seconds:.0f}s)")
        except OSError:
            pass  # Lock file disappeared, continue

    lockfile.touch()
    return lockfile


def _wal_checkpoint_and_backup(source_path: Path, dest_path: Path) -> Tuple[bool, str, int, str]:
    """
    Perform WAL checkpoint then SQLite online backup.

    Returns: (success, status, size_bytes, sha256_hex)
    """
    if not source_path.exists():
        return True, "absent", 0, ""

    try:
        # WAL checkpoint to ensure consistent state, then online backup.
        # NOTE: sqlite3's context manager only manages the transaction, NOT the
        # connection — close explicitly or the handles stay open (Windows file locks).
        src_conn = sqlite3.connect(str(source_path))
        try:
            src_conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")

            dest_conn = sqlite3.connect(str(dest_path))
            try:
                src_conn.backup(dest_conn)
            finally:
                dest_conn.close()
        finally:
            src_conn.close()

        # Verify backup was created and get metadata
        if not dest_path.exists():
            return False, "backup_failed", 0, ""

        size_bytes = dest_path.stat().st_size

        # Calculate SHA256
        hasher = hashlib.sha256()
        with open(dest_path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                hasher.update(chunk)
        sha256_hex = hasher.hexdigest()

        return True, "success", size_bytes, sha256_hex

    except Exception as e:
        return False, f"error: {e}", 0, ""


def run_backup(backup_root: Optional[str] = None) -> dict:
    """
    Create timestamped backup of all registered databases.

    Args:
        backup_root: Override default backup location

    Returns:
        dict: Backup manifest with per-file status and overall summary
    """
    if backup_root is None:
        backup_root = settings.backup_root

    backup_root_path = Path(backup_root)
    backup_root_path.mkdir(parents=True, exist_ok=True)

    # Create lockfile
    lockfile = _create_lockfile(backup_root_path)

    try:
        # Create timestamped backup directory
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H%M%S")
        backup_dir = backup_root_path / timestamp
        backup_dir.mkdir(parents=True, exist_ok=True)

        # Track overall timing
        started_at = datetime.now(timezone.utc).isoformat()

        # Get app SHA if available (cheaply)
        app_sha = None
        try:
            from subprocess import check_output
            app_sha = check_output(["git", "rev-parse", "--short", "HEAD"],
                                 cwd=Path(__file__).parent.parent.parent.parent,
                                 text=True).strip()
        except Exception:
            pass

        # Process each database
        db_registry = _get_db_registry()
        files_status = {}

        for db_name, source_path in db_registry:
            start_time = time.time()
            dest_path = backup_dir / f"{db_name}.db"

            success, status, size_bytes, sha256_hex = _wal_checkpoint_and_backup(source_path, dest_path)
            duration_ms = int((time.time() - start_time) * 1000)

            files_status[db_name] = {
                "source_path": str(source_path),
                "status": status,
                "size_bytes": size_bytes,
                "sha256": sha256_hex,
                "duration_ms": duration_ms,
            }

        finished_at = datetime.now(timezone.utc).isoformat()

        # Create manifest
        manifest = {
            "backup_id": timestamp,
            "started_at": started_at,
            "finished_at": finished_at,
            "app_sha": app_sha,
            "files": files_status,
            "summary": {
                "total_files": len(db_registry),
                "success_count": sum(1 for f in files_status.values() if f["status"] in ("success", "absent")),
                "total_size_bytes": sum(f["size_bytes"] for f in files_status.values()),
            }
        }

        # Write manifest
        manifest_path = backup_dir / "manifest.json"
        with open(manifest_path, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, indent=2)

        return manifest

    finally:
        # Always remove lockfile
        try:
            lockfile.unlink()
        except OSError:
            pass


def _parse_backup_dirname(dirname: str) -> Optional[datetime]:
    """Parse backup directory name to datetime, return None if invalid format."""
    try:
        return datetime.strptime(dirname, "%Y-%m-%d-%H%M%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def prune_backups(backup_root: str, dry_run: bool = False) -> dict:
    """
    Apply retention policy: keep last 7 daily, 4 weekly, 12 monthly.

    Args:
        backup_root: Backup root directory
        dry_run: If True, return what would be deleted without deleting

    Returns:
        dict: {"kept": [...], "deleted": [...]}
    """
    backup_root_path = Path(backup_root)
    if not backup_root_path.exists():
        return {"kept": [], "deleted": []}

    # Find all backup directories with valid timestamps
    all_backups = []
    for item in backup_root_path.iterdir():
        if item.is_dir():
            parsed_dt = _parse_backup_dirname(item.name)
            if parsed_dt:
                all_backups.append((item.name, parsed_dt))

    # Sort by date (newest first)
    all_backups.sort(key=lambda x: x[1], reverse=True)

    # Calculate keep sets
    keep_set: Set[str] = set()

    # Daily: keep last 7
    daily_dates = {}
    for dirname, dt in all_backups:
        date_key = dt.date()
        if date_key not in daily_dates:
            daily_dates[date_key] = dirname
        if len(daily_dates) >= 7:
            break
    keep_set.update(daily_dates.values())

    # Weekly: keep latest per ISO week for last 4 weeks
    weekly_dates = {}
    for dirname, dt in all_backups:
        # ISO week: year and week number
        iso_year, iso_week, _ = dt.isocalendar()
        week_key = (iso_year, iso_week)
        if week_key not in weekly_dates:
            weekly_dates[week_key] = dirname
        if len(weekly_dates) >= 4:
            break
    keep_set.update(weekly_dates.values())

    # Monthly: keep latest per month for last 12 months
    monthly_dates = {}
    for dirname, dt in all_backups:
        month_key = (dt.year, dt.month)
        if month_key not in monthly_dates:
            monthly_dates[month_key] = dirname
        if len(monthly_dates) >= 12:
            break
    keep_set.update(monthly_dates.values())

    # Split into kept and to-delete
    kept = []
    deleted = []

    for dirname, _ in all_backups:
        if dirname in keep_set:
            kept.append(dirname)
        else:
            deleted.append(dirname)
            if not dry_run:
                try:
                    import shutil
                    shutil.rmtree(backup_root_path / dirname)
                except Exception:
                    pass  # Continue with other deletions

    return {"kept": kept, "deleted": deleted}