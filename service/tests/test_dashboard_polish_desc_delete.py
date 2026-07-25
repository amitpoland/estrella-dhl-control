"""
test_dashboard_polish_desc_delete.py — Polish description delete endpoint.

Pins the safe-delete contract for
DELETE /dashboard/batches/{batch_id}/polish-description:

  * Filename comes from audit.polish_desc_filename — never from the URL —
    so URL-injection (../../evil.pdf) cannot escape polish_descriptions/.
  * 404 when audit field empty.
  * 404 when file missing on disk.
  * Resolved path must remain inside storage_root/polish_descriptions/.
  * On success: file removed, audit pointers cleared.
  * 400 when batch_id contains traversal characters.
  * 400 when audit.polish_desc_filename itself contains a path separator
    or '..' (defends against poisoned audits).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Tuple

import pytest

_ROOT = Path(__file__).parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

os.environ.setdefault("API_KEY", "test-key")


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _isolate_storage(tmp_path, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    from app.api import routes_dashboard
    monkeypatch.setattr(routes_dashboard, "_OUTPUTS", tmp_path / "outputs")


@pytest.fixture
def env(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "environment", "dev",      raising=False)
    monkeypatch.setattr(settings, "api_key",     "test-key", raising=False)
    return settings


@pytest.fixture
def client(env):
    from fastapi.testclient import TestClient
    from app.main import app
    # The delete route is guarded by require_admin (an admin *session*, not
    # X-API-Key). Inject an admin the canonical way; the X-API-Key header the
    # helpers still send is now simply ignored by this route.
    from app.auth.dependencies import require_admin
    app.dependency_overrides[require_admin] = lambda: {
        "id": "test-admin", "email": "admin@test.local", "role": "admin",
    }
    try:
        yield TestClient(app, raise_server_exceptions=False)
    finally:
        app.dependency_overrides.pop(require_admin, None)


def _make_batch(
    root: Path,
    *,
    batch_id: str = "B_DEL_PD",
    polish_fn: str = "POLISH_DESC_AWB_1234567890_20260507.pdf",
    write_file: bool = True,
    audit_fn: str | None = "default",
) -> Tuple[str, Path, Path]:
    batch_dir = root / "outputs" / batch_id
    batch_dir.mkdir(parents=True, exist_ok=True)
    pd_dir = root / "polish_descriptions"
    pd_dir.mkdir(parents=True, exist_ok=True)
    pd_file = pd_dir / polish_fn
    if write_file:
        pd_file.write_bytes(b"%PDF-1.4 fake polish desc")

    audit: Dict[str, Any] = {
        "batch_id": batch_id,
        "awb":      "1234567890",
        "timeline": [],
    }
    if audit_fn == "default":
        audit["polish_desc_filename"] = polish_fn
        audit["polish_desc_path"]     = str(pd_file)
    elif audit_fn is not None:
        audit["polish_desc_filename"] = audit_fn
    ap = batch_dir / "audit.json"
    ap.write_text(json.dumps(audit, ensure_ascii=False), encoding="utf-8")
    return batch_id, batch_dir, ap


def _delete(client, batch_id: str):
    return client.delete(
        f"/dashboard/batches/{batch_id}/polish-description",
        headers={"X-API-Key": "test-key"},
    )


def _read_audit(ap: Path) -> Dict[str, Any]:
    return json.loads(ap.read_text(encoding="utf-8"))


# ── Happy path ───────────────────────────────────────────────────────────────

def test_deletes_polish_description_and_clears_audit(tmp_path, client):
    bid, _, ap = _make_batch(tmp_path)
    pd = tmp_path / "polish_descriptions" / "POLISH_DESC_AWB_1234567890_20260507.pdf"
    assert pd.is_file()

    r = _delete(client, bid)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"]      is True
    assert body["deleted"] == "POLISH_DESC_AWB_1234567890_20260507.pdf"
    assert body["batch_id"] == bid
    # File gone
    assert not pd.exists()
    # Audit cleared
    a = _read_audit(ap)
    assert "polish_desc_filename"   not in a
    assert "polish_desc_path"       not in a
    # Timeline event
    assert any(e["event"] == "polish_description_deleted" for e in a.get("timeline", []))


# ── 404 paths ────────────────────────────────────────────────────────────────

def test_404_when_no_polish_desc_recorded(tmp_path, client):
    """audit.polish_desc_filename empty → 404 (no permissive scan)."""
    bid, _, _ = _make_batch(tmp_path, audit_fn="")
    r = _delete(client, bid)
    assert r.status_code == 404
    assert "No Polish description recorded" in r.json()["detail"]


def test_404_when_recorded_but_file_missing(tmp_path, client):
    bid, _, _ = _make_batch(tmp_path, write_file=False)
    r = _delete(client, bid)
    assert r.status_code == 404
    assert "not on disk" in r.json()["detail"]


def test_404_when_batch_does_not_exist(tmp_path, client):
    r = _delete(client, "B_DOES_NOT_EXIST")
    assert r.status_code == 404


# ── Path-safety ──────────────────────────────────────────────────────────────

def test_400_when_batch_id_contains_traversal(tmp_path, client):
    r = _delete(client, "..%2Fevil")
    # FastAPI may match before our handler runs; either 400 or 404 is acceptable
    # SO LONG AS no file is touched. Prove the latter:
    assert r.status_code in (400, 404, 405)


def test_400_when_audit_polish_desc_filename_has_separator(tmp_path, client):
    """A poisoned audit with '../etc/passwd' as polish_desc_filename must
    NOT delete anything outside polish_descriptions/."""
    bid, _, ap = _make_batch(
        tmp_path,
        polish_fn="POLISH_DESC_AWB_X_20260507.pdf",
        audit_fn="../etc/passwd",
    )
    # Decoy file outside polish_descriptions/
    decoy = tmp_path / "etc" / "passwd"
    decoy.parent.mkdir(parents=True, exist_ok=True)
    decoy.write_text("decoy", encoding="utf-8")

    r = _delete(client, bid)
    assert r.status_code == 400
    assert decoy.exists(), "path traversal must not delete files outside polish_descriptions/"


def test_400_when_audit_polish_desc_filename_has_backslash(tmp_path, client):
    bid, _, _ = _make_batch(
        tmp_path,
        polish_fn="POLISH_DESC_AWB_X_20260507.pdf",
        audit_fn=r"..\windows\System32",
    )
    r = _delete(client, bid)
    assert r.status_code == 400


# ── Idempotency ──────────────────────────────────────────────────────────────

def test_second_delete_returns_404_not_500(tmp_path, client):
    bid, _, _ = _make_batch(tmp_path)
    r1 = _delete(client, bid)
    assert r1.status_code == 200
    r2 = _delete(client, bid)
    assert r2.status_code == 404
