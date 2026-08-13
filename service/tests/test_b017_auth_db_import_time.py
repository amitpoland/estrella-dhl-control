"""B-017: auth DB path must not freeze at import app.main.

Importing app.main must be filesystem-silent for users.db. Path resolution
happens at lifespan/call time via resolve_auth_db_path (same authority as #1204).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from app.auth.database import resolve_auth_db_path


def test_resolve_auth_db_path_prefers_explicit():
    assert resolve_auth_db_path("/x/custom.db", Path("/ignored")) == Path("/x/custom.db")


def test_resolve_auth_db_path_defaults_to_storage_root(tmp_path):
    assert resolve_auth_db_path("", tmp_path) == tmp_path / "users.db"


def test_resolve_auth_db_path_requires_storage_when_empty():
    with pytest.raises(ValueError, match="storage_root"):
        resolve_auth_db_path("", None)


def test_main_has_no_import_time_auth_db_binding():
    """Frozen module-level _auth_db is the B-017 defect; must stay gone."""
    import app.main as m

    assert not hasattr(m, "_auth_db"), "import-time _auth_db binding returned"


def test_import_app_main_does_not_create_users_db(tmp_path):
    """Fresh interpreter: import app.main must not mkdir/create users.db."""
    storage = tmp_path / "storage"
    storage.mkdir()
    service_root = Path(__file__).resolve().parents[1].as_posix()
    script = f"""
import os, sys
from pathlib import Path
storage = Path(sys.argv[1])
os.environ["STORAGE_ROOT"] = str(storage)
os.chdir(storage)
sys.path.insert(0, r"{service_root}")
import app.main  # noqa: F401
users = storage / "users.db"
print("USERS_EXISTS", users.exists())
print("NONE_EXISTS", (storage / "None").exists())
print("HAS_AUTH_DB_ATTR", hasattr(app.main, "_auth_db"))
"""
    proc = subprocess.run(
        [sys.executable, "-c", script, str(storage)],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert "USERS_EXISTS False" in proc.stdout
    assert "NONE_EXISTS False" in proc.stdout
    assert "HAS_AUTH_DB_ATTR False" in proc.stdout


def test_lifespan_resolves_current_settings_path(tmp_path, monkeypatch):
    """After import, patching settings must still drive init_db path."""
    import app.auth.database as d
    import app.main as m
    from app.core.config import settings

    monkeypatch.setattr(settings, "auth_db_path", "")
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    monkeypatch.setattr(settings, "environment", "dev")
    monkeypatch.setattr(d, "_db_path", None)

    auth_db = resolve_auth_db_path(settings.auth_db_path, settings.storage_root)
    d.init_db(auth_db)
    assert auth_db == tmp_path / "users.db"
    assert auth_db.exists()
    with d._connect() as con:
        assert con.execute("SELECT 1").fetchone()[0] == 1
    src = Path(m.__file__).read_text(encoding="utf-8")
    assert "resolve_auth_db_path(settings.auth_db_path, settings.storage_root)" in src
    assert "_auth_db =" not in src
