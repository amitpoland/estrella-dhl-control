"""B-006: importing App modules must stay filesystem-silent outside test roots.

B-017 already moved auth DB path resolution to lifespan/call time
(``resolve_auth_db_path``). This pin covers the broader B-006 claim:
a fresh interpreter that imports ``app.main`` must not create persistent
DB/files under the default storage root, cwd, or production storage.
TestClient / lifespan must resolve only to an explicit temporary root.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.auth.database import resolve_auth_db_path


_SERVICE_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_STORAGE = _SERVICE_ROOT / "app" / "storage"
_PROD_STORAGE = Path(r"C:\PZ\app\storage")
_PROD_NONE = Path(r"C:\PZ\None")


def _fresh_import_probe(storage: Path, cwd: Path) -> dict:
    """Run import app.main in a brand-new interpreter; return JSON report."""
    script = r"""
import json, os, sys
from pathlib import Path

storage = Path(sys.argv[1])
cwd = Path(sys.argv[2])
service_root = Path(sys.argv[3])
os.environ["STORAGE_ROOT"] = str(storage)
os.chdir(cwd)
sys.path.insert(0, str(service_root))

def tree_files(p: Path):
    if not p.exists():
        return []
    return sorted(str(f.relative_to(p)).replace("\\", "/") for f in p.rglob("*") if f.is_file())

before = {
    "storage_files": tree_files(storage),
    "cwd_users": (cwd / "users.db").exists(),
    "cwd_none": (cwd / "None").exists(),
    "cwd_dbs": sorted(p.name for p in cwd.glob("*.db")),
}
import app.main  # noqa: F401
after = {
    "storage_files": tree_files(storage),
    "cwd_users": (cwd / "users.db").exists(),
    "cwd_none": (cwd / "None").exists(),
    "cwd_dbs": sorted(p.name for p in cwd.glob("*.db")),
    "has_auth_db_attr": hasattr(app.main, "_auth_db"),
    "storage_root": str(__import__("app.core.config", fromlist=["settings"]).settings.storage_root),
}
print(json.dumps({"before": before, "after": after}))
"""
    proc = subprocess.run(
        [sys.executable, "-c", script, str(storage), str(cwd), str(_SERVICE_ROOT)],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=120,
        env={**os.environ, "STORAGE_ROOT": str(storage)},
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip().startswith("{")]
    assert lines, proc.stdout + proc.stderr
    return json.loads(lines[-1])


def test_fresh_process_import_creates_no_persistent_db_twice(tmp_path):
    """Two clean interpreters: import app.main must not create persistent files."""
    storage = tmp_path / "storage"
    storage.mkdir()
    cwd = tmp_path / "cwd"
    cwd.mkdir()

    prod_before = {}
    if _PROD_STORAGE.exists():
        for f in _PROD_STORAGE.glob("*.db"):
            st = f.stat()
            prod_before[f.name] = (st.st_size, st.st_mtime_ns)
    none_before = _PROD_NONE.exists() if _PROD_NONE.parent.exists() else None

    for _ in range(2):
        report = _fresh_import_probe(storage, cwd)
        assert report["before"]["storage_files"] == []
        assert report["after"]["storage_files"] == []
        assert report["after"]["cwd_users"] is False
        assert report["after"]["cwd_none"] is False
        assert report["after"]["cwd_dbs"] == []
        assert report["after"]["has_auth_db_attr"] is False
        assert Path(report["after"]["storage_root"]) == storage

    if prod_before:
        for name, before in prod_before.items():
            f = _PROD_STORAGE / name
            assert f.exists(), name
            st = f.stat()
            assert (st.st_size, st.st_mtime_ns) == before, f"production {name} mutated by import probe"
    if none_before is not None:
        assert _PROD_NONE.exists() == none_before


def test_testclient_uses_explicit_temporary_storage_root(tmp_path, monkeypatch):
    """Lifespan/TestClient must initialise DBs only under the patched root."""
    import app.auth.database as adb
    import app.main as m
    from app.core.config import settings
    from fastapi.testclient import TestClient

    live_users = _DEFAULT_STORAGE / "users.db"
    live_before = live_users.stat().st_mtime_ns if live_users.exists() else None

    monkeypatch.setattr(settings, "storage_root", tmp_path)
    monkeypatch.setattr(settings, "auth_db_path", "")
    monkeypatch.setattr(settings, "environment", "dev")
    monkeypatch.setattr(adb, "_db_path", None)

    with TestClient(m.app, raise_server_exceptions=True) as client:
        r = client.get("/api/v1/health")
        assert r.status_code == 200

    assert (tmp_path / "users.db").exists()
    assert resolve_auth_db_path(settings.auth_db_path, settings.storage_root) == tmp_path / "users.db"
    if live_before is None:
        assert not live_users.exists()
    else:
        assert live_users.stat().st_mtime_ns == live_before



def test_explicit_runtime_auth_init_still_succeeds(tmp_path, monkeypatch):
    """Normal call-time init_db via resolve_auth_db_path remains the authority."""
    import app.auth.database as adb
    from app.core.config import settings

    monkeypatch.setattr(settings, "storage_root", tmp_path)
    monkeypatch.setattr(settings, "auth_db_path", "")
    monkeypatch.setattr(adb, "_db_path", None)

    auth_db = resolve_auth_db_path(settings.auth_db_path, settings.storage_root)
    adb.init_db(auth_db)
    assert auth_db == tmp_path / "users.db"
    assert auth_db.exists()
    with adb._connect() as con:
        assert con.execute("SELECT 1").fetchone()[0] == 1
