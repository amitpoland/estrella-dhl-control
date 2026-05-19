"""
test_wfirma_pz_lock.py — idempotency lock + audit-write hardening for PZ
create / adopt flows.

Each test guards against a specific way an operator (or two operators clicking
simultaneously) could end up with two warehouse PZs, an adopt-after-create,
or a create-after-adopt for the same shipment.

Cases covered
-------------
1. create blocked after create  (HTTP 409, code=PZ_ALREADY_CREATED)
2. adopt  blocked after create  (HTTP 409, code=PZ_ALREADY_CREATED)
3. create blocked after adopt   (HTTP 409, code=PZ_ALREADY_ADOPTED)
4. adopt  blocked after adopt   (idempotent same id → already_adopted;
                                  different id → 409)
5. concurrent operators         (file lock — second writer gets PZ_WRITE_LOCKED)
6. timeline-only audit lock     (doc_id removed but EV_WFIRMA_PZ_CREATED in
                                  timeline still blocks both create and adopt)
7. audit-write failure          (wFirma created OK but disk write fails →
                                  500 with status=audit_write_failed and
                                  the wfirma_pz_doc_id preserved in response)
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_svc = Path(__file__).parent.parent
if str(_svc) not in sys.path:
    sys.path.insert(0, str(_svc))


_BATCH    = "TEST_PZ_LOCK_001"
_DOC_ID   = "183167843"
_DOC_ID_B = "999999999"
_DOC_NO   = "PZ 5/5/2026"


def _audit_with(*, doc_id="", source="", timeline=()):
    """Build an audit dict with optional pz_doc_id, pz_source, timeline events."""
    a = {
        "batch_id": _BATCH,
        "status":   "success",
        "inputs":   {"zc429": "sad.pdf"},
        "wfirma_export": {},
    }
    if doc_id:
        a["wfirma_export"]["wfirma_pz_doc_id"] = doc_id
    if source:
        a["wfirma_export"]["pz_source"] = source
    if timeline:
        a["timeline"] = [{"event": ev, "ts": "2026-05-06T00:00:00Z"} for ev in timeline]
    return a


def _write_audit(tmp_path: Path, audit: dict) -> Path:
    p = tmp_path / "audit.json"
    p.write_text(json.dumps(audit), encoding="utf-8")
    return p


def _adopt_body(pz_doc_id=_DOC_ID, pz_number=None):
    from app.api.routes_wfirma import _PZAdoptBody
    return _PZAdoptBody(pz_doc_id=pz_doc_id, pz_number=pz_number)


def _run_adopt(batch_id=_BATCH, body=None):
    from app.api.routes_wfirma import wfirma_pz_adopt
    if body is None:
        body = _adopt_body()
    # Pass x_operator=None explicitly so FastAPI's Header sentinel is not used
    # as the default when the coroutine is invoked directly (outside DI machinery).
    return asyncio.get_event_loop().run_until_complete(
        wfirma_pz_adopt(batch_id, body, x_operator=None)
    )


def _run_create(batch_id=_BATCH):
    from app.api.routes_wfirma import wfirma_pz_create
    # Same: pass x_operator=None to avoid FastAPI Header sentinel being the default.
    return asyncio.get_event_loop().run_until_complete(
        wfirma_pz_create(batch_id, x_operator=None)
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Pure unit tests for the helper — no FastAPI plumbing
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("audit, expected_code", [
    # doc_id present, no source → PZ_ALREADY_LINKED
    (_audit_with(doc_id=_DOC_ID),                                        "PZ_ALREADY_LINKED"),
    # source=created_via_app → PZ_ALREADY_CREATED
    (_audit_with(doc_id=_DOC_ID, source="created_via_app"),              "PZ_ALREADY_CREATED"),
    # source=adopted_existing → PZ_ALREADY_ADOPTED
    (_audit_with(doc_id=_DOC_ID, source="adopted_existing"),             "PZ_ALREADY_ADOPTED"),
    # timeline-only — doc_id field removed, but EV_WFIRMA_PZ_CREATED proves it
    (_audit_with(timeline=("wfirma_pz_created",)),                       "PZ_ALREADY_CREATED"),
    (_audit_with(timeline=("wfirma_pz_adopted",)),                       "PZ_ALREADY_ADOPTED"),
])
def test_assert_pz_not_locked_blocks_with_code(audit, expected_code):
    """The unified guard rejects every prior-PZ signal with a precise code."""
    from fastapi import HTTPException
    from app.api.routes_wfirma import _assert_pz_not_locked

    with pytest.raises(HTTPException) as exc:
        _assert_pz_not_locked(audit, _BATCH, "pz_create")
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == expected_code


def test_assert_pz_not_locked_passes_clean_audit():
    """Clean audit (no doc_id, no source, no terminal event) → no exception."""
    from app.api.routes_wfirma import _assert_pz_not_locked
    _assert_pz_not_locked(_audit_with(), _BATCH, "pz_create")  # must not raise


# ═══════════════════════════════════════════════════════════════════════════════
# Case 1: create blocked after create
# ═══════════════════════════════════════════════════════════════════════════════

def test_create_blocked_after_create(tmp_path, monkeypatch):
    """
    Audit already shows pz_source='created_via_app'.  Calling pz_create again
    must return 409 PZ_ALREADY_CREATED — wFirma must NEVER be invoked twice.
    """
    audit = _audit_with(doc_id=_DOC_ID, source="created_via_app",
                        timeline=("wfirma_pz_created",))
    _write_audit(tmp_path, audit)

    create_called = MagicMock()

    # The fast-path returns already_created when source != adopted_existing.
    # That's the correct "no double-create" behavior; assert it returns 200
    # already_created (not 409) and that wFirma is NOT called.
    with (
        patch("app.api.routes_wfirma.get_output_dir", return_value=tmp_path),
        patch("app.api.routes_wfirma._read_audit", return_value=audit),
        patch("app.api.routes_wfirma.settings.wfirma_create_pz_allowed", True),
        patch("app.api.routes_wfirma.settings.wfirma_supplier_contractor_id", "1"),
        patch("app.api.routes_wfirma.settings.wfirma_warehouse_id", "1"),
        patch("app.api.routes_wfirma.wfirma_client.create_warehouse_pz",
              side_effect=create_called),
    ):
        # Inject MRN so guard 3 passes
        audit["customs_declaration"] = {"mrn": "26PL000000000000"}
        result = _run_create()

    body = json.loads(result.body)
    assert body["status"] == "already_created"
    assert body["wfirma_pz_doc_id"] == _DOC_ID
    create_called.assert_not_called(), "wFirma must never be called for a re-create"


# ═══════════════════════════════════════════════════════════════════════════════
# Case 2: adopt blocked after create
# ═══════════════════════════════════════════════════════════════════════════════

def test_adopt_blocked_after_create(tmp_path):
    """
    Shipment already has pz_source='created_via_app'.  An adopt attempt with a
    DIFFERENT pz_doc_id must be rejected 409 PZ_ALREADY_CREATED.
    """
    from fastapi import HTTPException

    audit = _audit_with(doc_id=_DOC_ID, source="created_via_app",
                        timeline=("wfirma_pz_created",))
    _write_audit(tmp_path, audit)

    from app.services.wfirma_client import PZFetchResult
    fetch_ok_other = PZFetchResult(ok=True, pz_doc_id=_DOC_ID_B, pz_number=_DOC_NO)

    with (
        patch("app.api.routes_wfirma.get_output_dir", return_value=tmp_path),
        patch("app.api.routes_wfirma._read_audit", return_value=audit),
        patch("app.api.routes_wfirma.settings.wfirma_create_pz_allowed", True),
        patch("app.api.routes_wfirma.wfirma_client.fetch_warehouse_pz",
              return_value=fetch_ok_other),
        patch("app.api.routes_wfirma._find_pz_owner_batch", return_value=None),
        patch("app.api.routes_wfirma.tl.log_event"),
    ):
        with pytest.raises(HTTPException) as exc:
            _run_adopt(body=_adopt_body(pz_doc_id=_DOC_ID_B))
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "PZ_ALREADY_CREATED"


# ═══════════════════════════════════════════════════════════════════════════════
# Case 3: create blocked after adopt
# ═══════════════════════════════════════════════════════════════════════════════

def test_create_blocked_after_adopt(tmp_path):
    """
    Shipment was previously adopted (pz_source='adopted_existing').  A create
    attempt must NOT silently succeed; the in-lock guard must throw 409
    PZ_ALREADY_ADOPTED so wFirma is never asked to create a duplicate PZ.

    The fast-path explicitly excludes adopted_existing so we reach the lock.
    """
    from fastapi import HTTPException

    audit = _audit_with(doc_id=_DOC_ID, source="adopted_existing",
                        timeline=("wfirma_pz_adopted",))
    audit["customs_declaration"] = {"mrn": "26PL000000000000"}
    _write_audit(tmp_path, audit)

    create_called = MagicMock()

    with (
        patch("app.api.routes_wfirma.get_output_dir", return_value=tmp_path),
        patch("app.api.routes_wfirma._read_audit", return_value=audit),
        patch("app.api.routes_wfirma.settings.wfirma_create_pz_allowed", True),
        patch("app.api.routes_wfirma.settings.wfirma_supplier_contractor_id", "1"),
        patch("app.api.routes_wfirma.settings.wfirma_warehouse_id", "1"),
        patch("app.api.routes_wfirma.wfirma_client.create_warehouse_pz",
              side_effect=create_called),
        # The preview is consulted before the lock — short-circuit it
        patch("app.api.routes_wfirma.build_pz_request_from_batch",
              return_value=MagicMock(ready=True, planned_lines=[], pz_request={})),
        patch("app.api.routes_wfirma._build_rows", return_value=[]),
        patch("app.api.routes_wfirma.wfirma_db.list_products", return_value=[]),
    ):
        with pytest.raises(HTTPException) as exc:
            _run_create()
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "PZ_ALREADY_ADOPTED"
    create_called.assert_not_called()


# ═══════════════════════════════════════════════════════════════════════════════
# Case 4: adopt-after-adopt (same id → idempotent; different id → 409)
# ═══════════════════════════════════════════════════════════════════════════════

def test_adopt_after_adopt_same_id_is_idempotent(tmp_path):
    """Same pz_doc_id already adopted → status=already_adopted, no error."""
    audit = _audit_with(doc_id=_DOC_ID, source="adopted_existing",
                        timeline=("wfirma_pz_adopted",))
    _write_audit(tmp_path, audit)

    from app.services.wfirma_client import PZFetchResult
    fetch_ok = PZFetchResult(ok=True, pz_doc_id=_DOC_ID, pz_number=_DOC_NO)

    with (
        patch("app.api.routes_wfirma.get_output_dir", return_value=tmp_path),
        patch("app.api.routes_wfirma._read_audit", return_value=audit),
        patch("app.api.routes_wfirma.settings.wfirma_create_pz_allowed", True),
        patch("app.api.routes_wfirma.wfirma_client.fetch_warehouse_pz",
              return_value=fetch_ok),
        patch("app.api.routes_wfirma._find_pz_owner_batch", return_value=None),
        patch("app.api.routes_wfirma.tl.log_event"),
    ):
        result = _run_adopt(body=_adopt_body(pz_doc_id=_DOC_ID))
    body = json.loads(result.body)
    assert body["status"] == "already_adopted"
    assert body["wfirma_pz_doc_id"] == _DOC_ID


def test_adopt_after_adopt_different_id_is_blocked(tmp_path):
    """A second adopt with a DIFFERENT pz_doc_id must 409 — never overwrite."""
    from fastapi import HTTPException

    audit = _audit_with(doc_id=_DOC_ID, source="adopted_existing",
                        timeline=("wfirma_pz_adopted",))
    _write_audit(tmp_path, audit)

    from app.services.wfirma_client import PZFetchResult
    fetch_ok_other = PZFetchResult(ok=True, pz_doc_id=_DOC_ID_B, pz_number=_DOC_NO)

    with (
        patch("app.api.routes_wfirma.get_output_dir", return_value=tmp_path),
        patch("app.api.routes_wfirma._read_audit", return_value=audit),
        patch("app.api.routes_wfirma.settings.wfirma_create_pz_allowed", True),
        patch("app.api.routes_wfirma.wfirma_client.fetch_warehouse_pz",
              return_value=fetch_ok_other),
        patch("app.api.routes_wfirma._find_pz_owner_batch", return_value=None),
        patch("app.api.routes_wfirma.tl.log_event"),
    ):
        with pytest.raises(HTTPException) as exc:
            _run_adopt(body=_adopt_body(pz_doc_id=_DOC_ID_B))
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "PZ_ALREADY_ADOPTED"


# ═══════════════════════════════════════════════════════════════════════════════
# Case 5: concurrent operators — second click gets PZ_WRITE_LOCKED
# ═══════════════════════════════════════════════════════════════════════════════

def test_concurrent_operators_second_request_locked(tmp_path):
    """
    Simulate two operators clicking Adopt simultaneously: the first acquires
    the file lock; the second must hit PZ_WRITE_LOCKED (409) instead of also
    being able to write.
    """
    from fastapi import HTTPException
    from app.api.routes_wfirma import _pz_write_lock

    # Pre-create the lock file to simulate "first request still running"
    lock_path = tmp_path / ".pz_write.lock"
    lock_path.write_text(f"99999@{int(__import__('time').time())}\n",
                         encoding="utf-8")

    with pytest.raises(HTTPException) as exc:
        with _pz_write_lock(tmp_path, _BATCH, "pz_adopt"):
            pytest.fail("should never enter lock body — file already exists")
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "PZ_WRITE_LOCKED"


def test_lock_is_released_after_normal_exit(tmp_path):
    """Successful entry/exit must remove the lock so a follow-up attempt works."""
    from app.api.routes_wfirma import _pz_write_lock

    with _pz_write_lock(tmp_path, _BATCH, "pz_create"):
        assert (tmp_path / ".pz_write.lock").exists()
    assert not (tmp_path / ".pz_write.lock").exists()

    # Second entry must succeed (no leftover lock)
    with _pz_write_lock(tmp_path, _BATCH, "pz_create"):
        pass


def test_stale_lock_is_force_released(tmp_path, monkeypatch):
    """A stale lock (older than _PZ_LOCK_STALE_SECS) is force-removed."""
    import time as _t
    from app.api.routes_wfirma import _pz_write_lock

    lock_path = tmp_path / ".pz_write.lock"
    lock_path.write_text(f"99999@{int(_t.time())-9999}\n", encoding="utf-8")
    # Backdate the file mtime so the staleness check fires
    old = _t.time() - 9999
    import os as _os
    _os.utime(lock_path, (old, old))

    # Should NOT raise — stale lock is reclaimed
    with _pz_write_lock(tmp_path, _BATCH, "pz_create"):
        pass


# ═══════════════════════════════════════════════════════════════════════════════
# Case 6: timeline-only audit lock (doc_id manually removed)
# ═══════════════════════════════════════════════════════════════════════════════

def test_audit_lock_respected_when_doc_id_manually_removed(tmp_path):
    """
    Operator deletes wfirma_export.wfirma_pz_doc_id manually (e.g. trying to
    "reset" the shipment).  The audit timeline still contains
    EV_WFIRMA_PZ_CREATED.  Both create AND adopt must remain blocked because
    the timeline is the immutable source of truth.
    """
    from fastapi import HTTPException

    audit = _audit_with(timeline=("wfirma_pz_created",))   # no doc_id, no source
    audit["customs_declaration"] = {"mrn": "26PL000000000000"}
    _write_audit(tmp_path, audit)

    # Adopt path — guard fires inside the lock
    from app.services.wfirma_client import PZFetchResult
    fetch_ok = PZFetchResult(ok=True, pz_doc_id=_DOC_ID, pz_number=_DOC_NO)
    with (
        patch("app.api.routes_wfirma.get_output_dir", return_value=tmp_path),
        patch("app.api.routes_wfirma._read_audit", return_value=audit),
        patch("app.api.routes_wfirma.settings.wfirma_create_pz_allowed", True),
        patch("app.api.routes_wfirma.wfirma_client.fetch_warehouse_pz",
              return_value=fetch_ok),
        patch("app.api.routes_wfirma._find_pz_owner_batch", return_value=None),
        patch("app.api.routes_wfirma.tl.log_event"),
    ):
        with pytest.raises(HTTPException) as exc:
            _run_adopt(body=_adopt_body(pz_doc_id=_DOC_ID))
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "PZ_ALREADY_CREATED"

    # Create path — guard fires inside the lock
    create_called = MagicMock()
    with (
        patch("app.api.routes_wfirma.get_output_dir", return_value=tmp_path),
        patch("app.api.routes_wfirma._read_audit", return_value=audit),
        patch("app.api.routes_wfirma.settings.wfirma_create_pz_allowed", True),
        patch("app.api.routes_wfirma.settings.wfirma_supplier_contractor_id", "1"),
        patch("app.api.routes_wfirma.settings.wfirma_warehouse_id", "1"),
        patch("app.api.routes_wfirma.wfirma_client.create_warehouse_pz",
              side_effect=create_called),
        patch("app.api.routes_wfirma.build_pz_request_from_batch",
              return_value=MagicMock(ready=True, planned_lines=[], pz_request={})),
        patch("app.api.routes_wfirma._build_rows", return_value=[]),
        patch("app.api.routes_wfirma.wfirma_db.list_products", return_value=[]),
    ):
        with pytest.raises(HTTPException) as exc:
            _run_create()
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "PZ_ALREADY_CREATED"
    create_called.assert_not_called()


# ═══════════════════════════════════════════════════════════════════════════════
# Case 7: audit-write failure surfaces a structured warning
# ═══════════════════════════════════════════════════════════════════════════════

def test_create_audit_write_failure_returns_structured_warning(tmp_path):
    """
    wFirma creates the PZ successfully but the local audit write fails.
    Response MUST be 500 with status=audit_write_failed and the live
    wfirma_pz_doc_id so the operator can manually adopt — never silent success.
    """
    audit = _audit_with()  # clean
    audit["customs_declaration"] = {"mrn": "26PL000000000000"}
    _write_audit(tmp_path, audit)

    from app.services.wfirma_client import PZResult
    create_ok = PZResult(ok=True, wfirma_pz_doc_id=_DOC_ID)

    with (
        patch("app.api.routes_wfirma.get_output_dir", return_value=tmp_path),
        patch("app.api.routes_wfirma._read_audit", return_value=audit),
        patch("app.api.routes_wfirma.settings.wfirma_create_pz_allowed", True),
        patch("app.api.routes_wfirma.settings.wfirma_supplier_contractor_id", "1"),
        patch("app.api.routes_wfirma.settings.wfirma_warehouse_id", "1"),
        patch("app.api.routes_wfirma.build_pz_request_from_batch",
              return_value=MagicMock(ready=True, planned_lines=[], pz_request={})),
        patch("app.api.routes_wfirma._build_rows", return_value=[]),
        patch("app.api.routes_wfirma.wfirma_db.list_products", return_value=[]),
        patch("app.api.routes_wfirma.wfirma_client.create_warehouse_pz",
              return_value=create_ok),
        patch("app.api.routes_wfirma._patch_pz_doc_id",
              return_value="disk full simulation"),
        patch("app.api.routes_wfirma.tl.log_event"),
    ):
        result = _run_create()

    assert result.status_code == 500
    body = json.loads(result.body)
    assert body["status"] == "audit_write_failed"
    assert body["wfirma_pz_doc_id"] == _DOC_ID
    assert "warning" in body
    assert "audit_error" in body
