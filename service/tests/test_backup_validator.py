"""
test_backup_validator.py — B7 Backup Validator Tests

Tests backup integrity validation including restore simulation, SQLite checks,
and SHA256 verification.
"""
import json
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from app.services.backup_validator import validate_backup


def test_validator_pass_on_good_backup(tmp_path):
    """Validator returns PASS on good backup with valid manifest and files."""
    # Create backup directory structure
    backup_dir = tmp_path / "2026-06-12-143022"
    backup_dir.mkdir()

    # Create test database backup
    test_db_backup = backup_dir / "test.db"
    with sqlite3.connect(test_db_backup) as conn:
        conn.execute("CREATE TABLE test_table (id INTEGER PRIMARY KEY, data TEXT)")
        conn.execute("INSERT INTO test_table VALUES (1, 'test_data')")

    # Calculate SHA256 for manifest
    import hashlib
    hasher = hashlib.sha256()
    with open(test_db_backup, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            hasher.update(chunk)
    sha256_hex = hasher.hexdigest()

    # Create manifest
    manifest = {
        "backup_id": "2026-06-12-143022",
        "started_at": "2026-06-12T14:30:22+00:00",
        "finished_at": "2026-06-12T14:30:25+00:00",
        "files": {
            "test": {
                "status": "success",
                "size_bytes": test_db_backup.stat().st_size,
                "sha256": sha256_hex
            }
        },
        "summary": {"total_files": 1, "success_count": 1}
    }

    with open(backup_dir / "manifest.json", 'w') as f:
        json.dump(manifest, f)

    # Validate backup
    result = validate_backup(str(backup_dir))

    assert result["overall_verdict"] == "PASS"
    assert result["backup_id"] == "2026-06-12-143022"
    assert "test" in result["files"]

    test_result = result["files"]["test"]
    assert test_result["status"] == "PASS"
    assert test_result["integrity_check"] == "PASS"
    assert test_result["sentinel_query"] == "PASS"
    assert test_result["sha256_check"] == "PASS"
    assert test_result["sentinel_count"] >= 1  # At least one table


def test_validator_fail_on_corrupted_file_and_sha_mismatch(tmp_path):
    """Validator returns FAIL on corrupted backup file and SHA mismatch."""
    backup_dir = tmp_path / "2026-06-12-143022"
    backup_dir.mkdir()

    # Create corrupted backup file (garbage bytes)
    corrupted_file = backup_dir / "test.db"
    with open(corrupted_file, 'wb') as f:
        f.write(b"this is not a valid sqlite database")

    # Manifest with wrong SHA256
    manifest = {
        "backup_id": "2026-06-12-143022",
        "files": {
            "test": {
                "status": "success",
                "size_bytes": corrupted_file.stat().st_size,
                "sha256": "wrong_hash_value"
            }
        }
    }

    with open(backup_dir / "manifest.json", 'w') as f:
        json.dump(manifest, f)

    # Validate backup
    result = validate_backup(str(backup_dir))

    assert result["overall_verdict"] == "FAIL"
    assert "test" in result["files"]

    test_result = result["files"]["test"]
    assert test_result["status"] == "FAIL"
    assert test_result["integrity_check"] == "FAIL"
    assert test_result["sha256_check"] == "FAIL"


def test_validator_handles_absent_files_correctly(tmp_path):
    """Validator handles absent files (marked as absent in manifest) correctly."""
    backup_dir = tmp_path / "2026-06-12-143022"
    backup_dir.mkdir()

    # Manifest with absent file
    manifest = {
        "backup_id": "2026-06-12-143022",
        "files": {
            "absent_db": {
                "status": "absent",
                "size_bytes": 0,
                "sha256": ""
            }
        }
    }

    with open(backup_dir / "manifest.json", 'w') as f:
        json.dump(manifest, f)

    # Validate backup
    result = validate_backup(str(backup_dir))

    assert result["overall_verdict"] == "PASS"
    assert "absent_db" in result["files"]

    absent_result = result["files"]["absent_db"]
    assert absent_result["status"] == "PASS"
    assert "was absent during backup" in absent_result["message"]


def test_validator_fail_missing_backup_directory(tmp_path):
    """Validator returns FAIL when backup directory doesn't exist."""
    missing_dir = tmp_path / "nonexistent"

    result = validate_backup(str(missing_dir))

    assert result["overall_verdict"] == "FAIL"
    assert "does not exist" in result["error"]
    assert result["files"] == {}


def test_validator_fail_missing_manifest(tmp_path):
    """Validator returns FAIL when manifest.json is missing."""
    backup_dir = tmp_path / "2026-06-12-143022"
    backup_dir.mkdir()
    # No manifest.json created

    result = validate_backup(str(backup_dir))

    assert result["overall_verdict"] == "FAIL"
    assert "manifest.json not found" in result["error"]
    assert result["files"] == {}


def test_validator_fail_corrupted_manifest(tmp_path):
    """Validator returns FAIL when manifest.json is corrupted."""
    backup_dir = tmp_path / "2026-06-12-143022"
    backup_dir.mkdir()

    # Create invalid JSON manifest
    with open(backup_dir / "manifest.json", 'w') as f:
        f.write("this is not valid json {")

    result = validate_backup(str(backup_dir))

    assert result["overall_verdict"] == "FAIL"
    assert "Failed to read manifest" in result["error"]
    assert result["files"] == {}


def test_validator_cleans_up_temp_dirs_on_success_and_failure(tmp_path):
    """Validator always cleans up temporary directories."""
    backup_dir = tmp_path / "2026-06-12-143022"
    backup_dir.mkdir()

    # Create good database backup
    test_db_backup = backup_dir / "test.db"
    with sqlite3.connect(test_db_backup) as conn:
        conn.execute("CREATE TABLE test_table (id INTEGER)")

    # Calculate SHA256
    import hashlib
    hasher = hashlib.sha256()
    with open(test_db_backup, 'rb') as f:
        hasher.update(f.read())
    sha256_hex = hasher.hexdigest()

    manifest = {
        "backup_id": "2026-06-12-143022",
        "files": {
            "test": {
                "status": "success",
                "size_bytes": test_db_backup.stat().st_size,
                "sha256": sha256_hex
            }
        }
    }

    with open(backup_dir / "manifest.json", 'w') as f:
        json.dump(manifest, f)

    # Track temp directories created during validation
    original_mkdtemp = tempfile.mkdtemp
    created_temps = []

    def tracking_mkdtemp():
        temp_dir = original_mkdtemp()
        created_temps.append(temp_dir)
        return temp_dir

    with patch('tempfile.mkdtemp', side_effect=tracking_mkdtemp):
        result = validate_backup(str(backup_dir))

    # Verify validation succeeded
    assert result["overall_verdict"] == "PASS"

    # Verify all temp directories were cleaned up
    for temp_dir in created_temps:
        assert not Path(temp_dir).exists(), f"Temp directory not cleaned up: {temp_dir}"


def test_validator_summary_counts_correct(tmp_path):
    """Validator returns correct summary counts for mixed pass/fail results."""
    backup_dir = tmp_path / "2026-06-12-143022"
    backup_dir.mkdir()

    # Create one good backup file
    good_db = backup_dir / "good.db"
    with sqlite3.connect(good_db) as conn:
        conn.execute("CREATE TABLE good_table (id INTEGER)")

    # Create one corrupted backup file
    bad_db = backup_dir / "bad.db"
    with open(bad_db, 'wb') as f:
        f.write(b"corrupted data")

    # Calculate SHA256 for good file
    import hashlib
    hasher = hashlib.sha256()
    with open(good_db, 'rb') as f:
        hasher.update(f.read())
    good_sha256 = hasher.hexdigest()

    manifest = {
        "backup_id": "2026-06-12-143022",
        "files": {
            "good": {
                "status": "success",
                "size_bytes": good_db.stat().st_size,
                "sha256": good_sha256
            },
            "bad": {
                "status": "success",
                "size_bytes": bad_db.stat().st_size,
                "sha256": "wrong_hash"
            },
            "absent": {
                "status": "absent",
                "size_bytes": 0,
                "sha256": ""
            }
        }
    }

    with open(backup_dir / "manifest.json", 'w') as f:
        json.dump(manifest, f)

    result = validate_backup(str(backup_dir))

    # Overall should fail due to bad file
    assert result["overall_verdict"] == "FAIL"

    # Check summary counts
    summary = result["summary"]
    assert summary["total_files"] == 3
    assert summary["passed_files"] == 2  # good + absent
    assert summary["failed_files"] == 1  # bad

    # Check individual results
    assert result["files"]["good"]["status"] == "PASS"
    assert result["files"]["bad"]["status"] == "FAIL"
    assert result["files"]["absent"]["status"] == "PASS"


def test_validator_integrity_check_sentinel_query_details(tmp_path):
    """Validator provides detailed integrity check and sentinel query results."""
    backup_dir = tmp_path / "2026-06-12-143022"
    backup_dir.mkdir()

    # Create database with multiple tables
    test_db = backup_dir / "test.db"
    with sqlite3.connect(test_db) as conn:
        conn.execute("CREATE TABLE table1 (id INTEGER)")
        conn.execute("CREATE TABLE table2 (name TEXT)")
        conn.execute("CREATE INDEX idx_table1 ON table1(id)")

    # Calculate SHA256
    import hashlib
    hasher = hashlib.sha256()
    with open(test_db, 'rb') as f:
        hasher.update(f.read())
    sha256_hex = hasher.hexdigest()

    manifest = {
        "backup_id": "2026-06-12-143022",
        "files": {
            "test": {
                "status": "success",
                "size_bytes": test_db.stat().st_size,
                "sha256": sha256_hex
            }
        }
    }

    with open(backup_dir / "manifest.json", 'w') as f:
        json.dump(manifest, f)

    result = validate_backup(str(backup_dir))

    assert result["overall_verdict"] == "PASS"

    test_result = result["files"]["test"]
    assert test_result["sentinel_count"] >= 3  # 2 tables + 1 index (minimum)
    assert "All checks passed" in test_result["message"]
    assert test_result["integrity_check"] == "PASS"
    assert test_result["sentinel_query"] == "PASS"
    assert test_result["sha256_check"] == "PASS"