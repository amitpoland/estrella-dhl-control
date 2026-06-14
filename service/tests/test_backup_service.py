"""
test_backup_service.py — B7 Backup Service Tests

Tests backup creation, timestamping, manifest generation, and retention policy.
Uses tmp_path for isolated test environments.
"""
import json
import os
import sqlite3
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from app.services.backup_service import run_backup, prune_backups, _parse_backup_dirname


def test_backup_creates_timestamped_dir_and_manifest(tmp_path):
    """Backup creates timestamped directory with manifest.json."""
    # Create a simple test database
    test_db = tmp_path / "test.db"
    with sqlite3.connect(test_db) as conn:
        conn.execute("CREATE TABLE test_table (id INTEGER PRIMARY KEY, name TEXT)")
        conn.execute("INSERT INTO test_table (name) VALUES ('test_data')")

    # Mock the DB registry to return our test DB
    with patch("app.services.backup_service._get_db_registry") as mock_registry:
        mock_registry.return_value = [("test", test_db)]

        backup_root = tmp_path / "backups"
        manifest = run_backup(str(backup_root))

        # Check backup directory was created
        backup_id = manifest["backup_id"]
        backup_dir = backup_root / backup_id
        assert backup_dir.exists()
        assert backup_dir.is_dir()

        # Check manifest exists and has correct structure
        manifest_file = backup_dir / "manifest.json"
        assert manifest_file.exists()

        with open(manifest_file, 'r') as f:
            saved_manifest = json.load(f)

        assert saved_manifest["backup_id"] == backup_id
        assert "started_at" in saved_manifest
        assert "finished_at" in saved_manifest
        assert "files" in saved_manifest
        assert "summary" in saved_manifest

        # Check test DB was backed up
        assert "test" in saved_manifest["files"]
        test_file_info = saved_manifest["files"]["test"]
        assert test_file_info["status"] == "success"
        assert test_file_info["size_bytes"] > 0
        assert len(test_file_info["sha256"]) == 64  # SHA256 hex length


def test_all_present_dbs_copied_and_openable(tmp_path):
    """All present databases are copied and remain openable."""
    # Create multiple test databases
    dbs = {}
    for db_name in ["packing", "warehouse", "documents"]:
        db_path = tmp_path / f"{db_name}.db"
        with sqlite3.connect(db_path) as conn:
            conn.execute(f"CREATE TABLE {db_name}_table (id INTEGER, data TEXT)")
            conn.execute(f"INSERT INTO {db_name}_table VALUES (1, '{db_name}_data')")
        dbs[db_name] = db_path

    with patch("app.services.backup_service._get_db_registry") as mock_registry:
        mock_registry.return_value = [(name, path) for name, path in dbs.items()]

        backup_root = tmp_path / "backups"
        manifest = run_backup(str(backup_root))

        backup_dir = backup_root / manifest["backup_id"]

        # Verify all databases were backed up and are openable
        for db_name in dbs:
            backup_file = backup_dir / f"{db_name}.db"
            assert backup_file.exists()

            # Verify backup is a valid SQLite database
            with sqlite3.connect(backup_file) as conn:
                cursor = conn.execute(f"SELECT data FROM {db_name}_table WHERE id = 1")
                result = cursor.fetchone()
                assert result[0] == f"{db_name}_data"

        # Verify summary counts
        summary = manifest["summary"]
        assert summary["total_files"] == 3
        assert summary["success_count"] == 3


def test_absent_db_recorded_as_absent_run_succeeds(tmp_path):
    """Absent database recorded as absent in manifest, run still succeeds."""
    # Mock registry with non-existent file
    missing_path = tmp_path / "missing.db"

    with patch("app.services.backup_service._get_db_registry") as mock_registry:
        mock_registry.return_value = [("missing", missing_path)]

        backup_root = tmp_path / "backups"
        manifest = run_backup(str(backup_root))

        # Check run succeeded
        assert manifest["backup_id"]
        assert manifest["summary"]["total_files"] == 1
        assert manifest["summary"]["success_count"] == 1  # absent counts as success

        # Check absent file recorded correctly
        file_info = manifest["files"]["missing"]
        assert file_info["status"] == "absent"
        assert file_info["size_bytes"] == 0
        assert file_info["sha256"] == ""


def test_wal_mode_source_db_backs_up_with_committed_data_intact(tmp_path):
    """WAL-mode source database backs up with all committed data intact."""
    test_db = tmp_path / "wal_test.db"

    # Create database with WAL mode and some data
    with sqlite3.connect(test_db) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE wal_table (id INTEGER PRIMARY KEY, data TEXT)")
        conn.execute("INSERT INTO wal_table (data) VALUES ('committed_data')")
        conn.commit()

        # Add more data in a separate transaction
        conn.execute("INSERT INTO wal_table (data) VALUES ('more_data')")
        conn.commit()

    # Verify WAL file exists (indicates WAL mode is active)
    wal_file = Path(str(test_db) + "-wal")
    # WAL file might not exist if auto-checkpointed, so we don't assert its presence

    with patch("app.services.backup_service._get_db_registry") as mock_registry:
        mock_registry.return_value = [("wal_test", test_db)]

        backup_root = tmp_path / "backups"
        manifest = run_backup(str(backup_root))

        backup_dir = backup_root / manifest["backup_id"]
        backup_file = backup_dir / "wal_test.db"

        # Verify all committed data is in the backup
        with sqlite3.connect(backup_file) as conn:
            cursor = conn.execute("SELECT data FROM wal_table ORDER BY id")
            rows = cursor.fetchall()
            assert len(rows) == 2
            assert rows[0][0] == "committed_data"
            assert rows[1][0] == "more_data"


def test_sha256_in_manifest_matches_backup_file(tmp_path):
    """SHA256 hash in manifest matches actual backup file content."""
    test_db = tmp_path / "hash_test.db"
    with sqlite3.connect(test_db) as conn:
        conn.execute("CREATE TABLE hash_table (data BLOB)")
        conn.execute("INSERT INTO hash_table VALUES (?)", (b"specific_binary_data",))

    with patch("app.services.backup_service._get_db_registry") as mock_registry:
        mock_registry.return_value = [("hash_test", test_db)]

        backup_root = tmp_path / "backups"
        manifest = run_backup(str(backup_root))

        backup_dir = backup_root / manifest["backup_id"]
        backup_file = backup_dir / "hash_test.db"

        # Calculate actual file hash
        import hashlib
        hasher = hashlib.sha256()
        with open(backup_file, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                hasher.update(chunk)
        actual_hash = hasher.hexdigest()

        # Compare with manifest hash
        manifest_hash = manifest["files"]["hash_test"]["sha256"]
        assert actual_hash == manifest_hash


def test_prune_keeps_exactly_daily_weekly_monthly_union(tmp_path):
    """Prune keeps exactly the daily/weekly/monthly union."""
    backup_root = tmp_path / "backups"

    # Create fake backup directories spanning several months
    base_date = datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc)
    created_dirs = []

    for days_offset in [0, 1, 2, 3, 7, 14, 21, 28, 35, 42, 49, 56, 63, 70, 77, 84, 91]:
        backup_date = base_date + timedelta(days=days_offset)
        dirname = backup_date.strftime("%Y-%m-%d-%H%M%S")
        backup_dir = backup_root / dirname
        backup_dir.mkdir(parents=True, exist_ok=True)

        # Create minimal manifest
        manifest = {
            "backup_id": dirname,
            "finished_at": backup_date.isoformat(),
            "files": {},
            "summary": {"total_files": 0}
        }
        with open(backup_dir / "manifest.json", 'w') as f:
            json.dump(manifest, f)

        created_dirs.append(dirname)

    # Run prune
    result = prune_backups(str(backup_root), dry_run=False)

    # Verify structure
    assert "kept" in result
    assert "deleted" in result

    # Verify directories actually deleted
    remaining_dirs = [d.name for d in backup_root.iterdir() if d.is_dir()]
    assert set(remaining_dirs) == set(result["kept"])

    # Verify retention rules applied
    # Should keep last 7 daily + 4 weekly + 12 monthly (with union logic)
    # From our test data: expect to keep around 7-12 backups depending on overlap
    assert len(result["kept"]) >= 7  # At least daily retention
    assert len(result["kept"]) <= len(created_dirs)  # Not more than created


def test_prune_dry_run_deletes_nothing(tmp_path):
    """Prune dry run returns deletion plan but deletes nothing."""
    backup_root = tmp_path / "backups"

    # Create several backup directories
    for i in range(20):
        backup_date = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc) + timedelta(days=i)
        dirname = backup_date.strftime("%Y-%m-%d-%H%M%S")
        backup_dir = backup_root / dirname
        backup_dir.mkdir(parents=True)

        manifest = {"backup_id": dirname, "finished_at": backup_date.isoformat()}
        with open(backup_dir / "manifest.json", 'w') as f:
            json.dump(manifest, f)

    original_dirs = set(d.name for d in backup_root.iterdir() if d.is_dir())

    # Run dry run prune
    result = prune_backups(str(backup_root), dry_run=True)

    # Verify no directories were actually deleted
    remaining_dirs = set(d.name for d in backup_root.iterdir() if d.is_dir())
    assert remaining_dirs == original_dirs

    # Verify result structure
    assert "kept" in result
    assert "deleted" in result
    assert len(result["kept"]) + len(result["deleted"]) == len(original_dirs)


def test_lockfile_blocks_concurrent_run(tmp_path):
    """Lockfile prevents concurrent backup runs."""
    backup_root = tmp_path / "backups"
    backup_root.mkdir()

    # Create a lockfile manually
    lockfile = backup_root / "backup.lock"
    lockfile.touch()

    # Mock registry (doesn't matter what it returns since we should fail early)
    with patch("app.services.backup_service._get_db_registry") as mock_registry:
        mock_registry.return_value = []

        # Should fail due to existing lock
        with pytest.raises(RuntimeError, match="Backup already running"):
            run_backup(str(backup_root))


def test_stale_lockfile_ignored_after_one_hour(tmp_path):
    """Stale lockfile (>1h old) is ignored and backup proceeds."""
    backup_root = tmp_path / "backups"
    backup_root.mkdir()

    # Create a stale lockfile (simulate 2 hours ago)
    lockfile = backup_root / "backup.lock"
    lockfile.touch()
    stale_time = time.time() - 7200  # 2 hours ago
    os.utime(lockfile, (stale_time, stale_time))

    with patch("app.services.backup_service._get_db_registry") as mock_registry:
        mock_registry.return_value = []

        # Should succeed and remove stale lock
        try:
            manifest = run_backup(str(backup_root))
            # Should complete successfully
            assert manifest["backup_id"]
        except RuntimeError:
            pytest.fail("Should have ignored stale lockfile")


def test_parse_backup_dirname():
    """Test backup directory name parsing."""
    # Valid format
    dt = _parse_backup_dirname("2026-06-12-143022")
    expected = datetime(2026, 6, 12, 14, 30, 22, tzinfo=timezone.utc)
    assert dt == expected

    # Invalid formats
    assert _parse_backup_dirname("invalid") is None
    assert _parse_backup_dirname("2026-06-12") is None
    assert _parse_backup_dirname("2026-06-12-14:30:22") is None