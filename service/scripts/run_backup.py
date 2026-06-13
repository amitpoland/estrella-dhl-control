#!/usr/bin/env python3
"""
run_backup.py — B7 CLI entry point for Windows Task Scheduler

Usage:
    python run_backup.py           # Run backup only
    python run_backup.py --prune   # Run backup + prune old backups
    python run_backup.py --validate backup_id  # Validate specific backup

Exit codes:
    0 — Success
    1 — Backup failed
    2 — Validation failed
    3 — Prune failed
"""
import argparse
import sys
from pathlib import Path

# Add the service app to Python path
SERVICE_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(SERVICE_ROOT))

from app.services.backup_service import run_backup, prune_backups
from app.services.backup_validator import validate_backup
from app.core.config import settings


def main():
    parser = argparse.ArgumentParser(
        description="B7 Backup System CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--prune", action="store_true",
                        help="Run prune after backup (applies retention policy)")
    parser.add_argument("--validate", metavar="BACKUP_ID", type=str,
                        help="Validate specific backup by ID (skip backup)")
    parser.add_argument("--backup-root", metavar="PATH", type=str,
                        help="Override backup root directory")

    args = parser.parse_args()

    backup_root = args.backup_root or settings.backup_root

    try:
        if args.validate:
            # Validation mode
            print(f"Validating backup: {args.validate}")
            backup_dir = Path(backup_root) / args.validate

            if not backup_dir.exists():
                print(f"ERROR: Backup directory not found: {backup_dir}", file=sys.stderr)
                return 2

            result = validate_backup(str(backup_dir))

            print(f"Validation result: {result['overall_verdict']}")
            if result['overall_verdict'] == 'PASS':
                summary = result.get('summary', {})
                print(f"Files validated: {summary.get('total_files', 0)}")
                print(f"Passed: {summary.get('passed_files', 0)}")
                print(f"Failed: {summary.get('failed_files', 0)}")
                return 0
            else:
                print(f"Validation failed: {result.get('error', 'Unknown error')}", file=sys.stderr)
                for file_name, file_result in result.get('files', {}).items():
                    if file_result['status'] == 'FAIL':
                        print(f"  {file_name}: {file_result.get('message', 'Failed')}", file=sys.stderr)
                return 2

        else:
            # Backup mode
            print(f"Starting backup to: {backup_root}")
            manifest = run_backup(backup_root)

            backup_id = manifest['backup_id']
            summary = manifest['summary']

            print(f"Backup completed: {backup_id}")
            print(f"Total files: {summary['total_files']}")
            print(f"Successful: {summary['success_count']}")
            print(f"Total size: {summary['total_size_bytes']:,} bytes")

            if summary['success_count'] < summary['total_files']:
                failed_count = summary['total_files'] - summary['success_count']
                print(f"WARNING: {failed_count} files failed", file=sys.stderr)

                # Show failed files
                for file_name, file_info in manifest['files'].items():
                    if file_info['status'] not in ('success', 'absent'):
                        print(f"  {file_name}: {file_info['status']}", file=sys.stderr)

            # Run prune if requested
            if args.prune:
                print("Running retention policy...")
                prune_result = prune_backups(backup_root, dry_run=False)

                kept_count = len(prune_result['kept'])
                deleted_count = len(prune_result['deleted'])

                print(f"Retention: kept {kept_count}, deleted {deleted_count}")
                if deleted_count > 0:
                    print(f"Deleted backups: {', '.join(prune_result['deleted'])}")

            return 0

    except KeyboardInterrupt:
        print("\nBackup interrupted", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())