"""
backup_validator.py — B7 Backup Validation Service

Validates backup integrity by restore simulation and SQLite consistency checks.

Features:
- Restore simulation to temp directory
- SQLite integrity check
- SHA256 verification against manifest
- Clean temp directories on success or failure
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import shutil
from pathlib import Path
from typing import Dict, List


def validate_backup(backup_dir: str) -> dict:
    """
    Validate backup integrity through restore simulation.

    Steps for each DB file:
    1. Copy to temp directory (restore simulation)
    2. Open read-only and run PRAGMA integrity_check
    3. Run sentinel query (SELECT count(*) FROM sqlite_master)
    4. Verify SHA256 against manifest
    5. Clean up temp files

    Args:
        backup_dir: Path to backup directory containing manifest.json

    Returns:
        dict: Validation results with per-file status and overall verdict
    """
    backup_path = Path(backup_dir)
    manifest_path = backup_path / "manifest.json"

    if not backup_path.exists() or not backup_path.is_dir():
        return {
            "overall_verdict": "FAIL",
            "error": "Backup directory does not exist",
            "files": {}
        }

    if not manifest_path.exists():
        return {
            "overall_verdict": "FAIL",
            "error": "manifest.json not found",
            "files": {}
        }

    # Load manifest
    try:
        with open(manifest_path, 'r', encoding='utf-8') as f:
            manifest = json.load(f)
    except Exception as e:
        return {
            "overall_verdict": "FAIL",
            "error": f"Failed to read manifest: {e}",
            "files": {}
        }

    files_status = {}
    overall_success = True
    temp_dirs = []

    try:
        # Validate each file
        for file_name, file_info in manifest.get("files", {}).items():
            if file_info.get("status") == "absent":
                files_status[file_name] = {
                    "status": "PASS",
                    "message": "File was absent during backup"
                }
                continue

            # Find corresponding backup file
            backup_file = backup_path / f"{file_name}.db"
            if not backup_file.exists():
                files_status[file_name] = {
                    "status": "FAIL",
                    "message": "Backup file not found"
                }
                overall_success = False
                continue

            # Create temp directory for this validation
            temp_dir = Path(tempfile.mkdtemp())
            temp_dirs.append(temp_dir)
            temp_file = temp_dir / f"{file_name}_restored.db"

            try:
                # Step 1: Copy to temp (restore simulation)
                shutil.copy2(backup_file, temp_file)

                # Step 2 & 3: SQLite integrity check and sentinel query
                integrity_ok = True
                sentinel_ok = True
                integrity_msg = ""
                sentinel_count = 0

                # NOTE: sqlite3's context manager only manages the transaction,
                # NOT the connection. The connection must be closed explicitly,
                # otherwise the open file handle blocks temp-dir deletion on Windows.
                conn = None
                try:
                    conn = sqlite3.connect(f"file:{temp_file}?mode=ro", uri=True)
                    # Integrity check
                    cursor = conn.execute("PRAGMA integrity_check")
                    integrity_result = cursor.fetchall()
                    if integrity_result != [("ok",)]:
                        integrity_ok = False
                        integrity_msg = f"Integrity check failed: {integrity_result}"

                    # Sentinel query
                    cursor = conn.execute("SELECT count(*) FROM sqlite_master")
                    sentinel_count = cursor.fetchone()[0]

                except Exception as e:
                    integrity_ok = False
                    sentinel_ok = False
                    integrity_msg = f"Database access failed: {e}"
                finally:
                    if conn is not None:
                        try:
                            conn.close()
                        except Exception:
                            pass

                # Step 4: SHA256 verification
                sha256_ok = True
                sha256_msg = ""
                expected_sha256 = file_info.get("sha256", "")

                if expected_sha256:
                    try:
                        hasher = hashlib.sha256()
                        with open(backup_file, 'rb') as f:
                            for chunk in iter(lambda: f.read(8192), b''):
                                hasher.update(chunk)
                        actual_sha256 = hasher.hexdigest()

                        if actual_sha256 != expected_sha256:
                            sha256_ok = False
                            sha256_msg = f"SHA256 mismatch: expected {expected_sha256}, got {actual_sha256}"
                    except Exception as e:
                        sha256_ok = False
                        sha256_msg = f"SHA256 calculation failed: {e}"

                # Overall file status
                file_success = integrity_ok and sentinel_ok and sha256_ok
                if not file_success:
                    overall_success = False

                status_msg_parts = []
                if not integrity_ok:
                    status_msg_parts.append(integrity_msg)
                if not sentinel_ok:
                    status_msg_parts.append("Sentinel query failed")
                if not sha256_ok:
                    status_msg_parts.append(sha256_msg)

                files_status[file_name] = {
                    "status": "PASS" if file_success else "FAIL",
                    "message": "; ".join(status_msg_parts) if status_msg_parts else f"All checks passed (sentinel: {sentinel_count} objects)",
                    "integrity_check": "PASS" if integrity_ok else "FAIL",
                    "sentinel_query": "PASS" if sentinel_ok else "FAIL",
                    "sha256_check": "PASS" if sha256_ok else "FAIL",
                    "sentinel_count": sentinel_count if sentinel_ok else 0,
                }

            except Exception as e:
                files_status[file_name] = {
                    "status": "FAIL",
                    "message": f"Validation failed: {e}",
                    "integrity_check": "FAIL",
                    "sentinel_query": "FAIL",
                    "sha256_check": "FAIL",
                }
                overall_success = False

    finally:
        # Step 5: Always clean up temp directories
        for temp_dir in temp_dirs:
            try:
                # On Windows, we need to handle readonly files and retry
                def handle_remove_readonly(func, path, exc):
                    import os
                    import stat
                    if os.path.exists(path):
                        os.chmod(path, stat.S_IWRITE)
                        func(path)

                shutil.rmtree(temp_dir, onerror=handle_remove_readonly)
            except Exception:
                pass  # Continue cleanup

    return {
        "overall_verdict": "PASS" if overall_success else "FAIL",
        "backup_id": manifest.get("backup_id", "unknown"),
        "files": files_status,
        "summary": {
            "total_files": len(files_status),
            "passed_files": sum(1 for f in files_status.values() if f["status"] == "PASS"),
            "failed_files": sum(1 for f in files_status.values() if f["status"] == "FAIL"),
        }
    }