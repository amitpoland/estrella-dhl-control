"""
test_wfirma_pz_adopt.py — unit tests for POST .../wfirma/pz_adopt

Covers:
  1. adopt success — wFirma confirms PZ, no prior link → status=adopted,
     audit patched with pz_source='adopted_existing'
  2. already_adopted — same wfirma_pz_doc_id already in audit → idempotent
  3. reject different existing id — audit holds a different PZ → blocked
  4. reject duplicate adoption across shipments — another batch owns same id → blocked
  5. reject missing document — wFirma returns not-found → blocked
  6. missing body identifiers — both pz_doc_id and pz_number absent → blocked
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_svc = Path(__file__).parent.parent
if str(_svc) not in sys.path:
    sys.path.insert(0, str(_svc))


# ── Shared fixtures ────────────────────────────────────────────────────────────

_BATCH       = "TEST_PZ_ADOPT_001"
_OTHER_BATCH = "TEST_PZ_ADOPT_OTHER"
_DOC_ID      = "183167843"
_DOC_NO      = "PZ 3/5/2026"

_AUDIT_CLEAN = {
    "batch_id":      _BATCH,
    "status":        "processed",
    "inputs":        {"zc429": "sad.pdf"},
    "wfirma_export": {},
}

_AUDIT_WITH_SAME = {
    **_AUDIT_CLEAN,
    "wfirma_export": {"wfirma_pz_doc_id": _DOC_ID},
}

_AUDIT_WITH_DIFFERENT = {
    **_AUDIT_CLEAN,
    "wfirma_export": {"wfirma_pz_doc_id": "999999999"},
}


def _make_fetch_ok(pz_doc_id=_DOC_ID, pz_number=_DOC_NO):
    from app.services.wfirma_client import PZFetchResult
    return PZFetchResult(ok=True, pz_doc_id=pz_doc_id, pz_number=pz_number)


def _make_fetch_fail(error="document not found"):
    from app.services.wfirma_client import PZFetchResult
    return PZFetchResult(ok=False, error=error)


def _body(pz_doc_id=None, pz_number=None):
    from app.api.routes_wfirma import _PZAdoptBody
    return _PZAdoptBody(pz_doc_id=pz_doc_id, pz_number=pz_number)


def _run(batch_id=_BATCH, body=None):
    import asyncio
    from app.api.routes_wfirma import wfirma_pz_adopt
    if body is None:
        body = _body(pz_doc_id=_DOC_ID)
    return asyncio.get_event_loop().run_until_complete(wfirma_pz_adopt(batch_id, body))


# ── Test 1: adopt success ─────────────────────────────────────────────────────

def test_adopt_success_writes_audit_and_returns_adopted(tmp_path):
    """
    Fresh batch, no existing PZ. wFirma fetch succeeds.
    Expect: status=adopted, audit written with pz_source=adopted_existing.
    """
    audit_path = tmp_path / "audit.json"
    audit_path.write_text(json.dumps(_AUDIT_CLEAN))

    with (
        patch("app.api.routes_wfirma.get_output_dir", return_value=tmp_path),
        patch("app.api.routes_wfirma._read_audit", return_value=_AUDIT_CLEAN),
        patch("app.api.routes_wfirma.wfirma_client.fetch_warehouse_pz",
              return_value=_make_fetch_ok()),
        patch("app.api.routes_wfirma._find_pz_owner_batch", return_value=None),
        patch("app.api.routes_wfirma.tl.log_event"),
    ):
        result = _run()
        body = json.loads(result.body)

    assert body["status"] == "adopted", body
    assert body["wfirma_pz_doc_id"] == _DOC_ID
    assert body["pz_number"] == _DOC_NO
    assert body["pz_source"] == "adopted_existing"

    # Verify audit was patched
    saved = json.loads(audit_path.read_text())
    assert saved["wfirma_export"]["wfirma_pz_doc_id"] == _DOC_ID
    assert saved["wfirma_export"]["pz_source"] == "adopted_existing"


# ── Test 2: already adopted (same id) → idempotent ───────────────────────────

def test_already_adopted_same_id_returns_idempotent():
    """
    Audit already contains the same pz_doc_id.
    Expect: status=already_adopted, no second write.
    """
    with (
        patch("app.api.routes_wfirma.get_output_dir"),
        patch("app.api.routes_wfirma._read_audit", return_value=_AUDIT_WITH_SAME),
        patch("app.api.routes_wfirma.wfirma_client.fetch_warehouse_pz",
              return_value=_make_fetch_ok()),
        patch("app.api.routes_wfirma._find_pz_owner_batch", return_value=None),
        patch("app.api.routes_wfirma._patch_pz_adopted") as mock_patch,
    ):
        result = _run()
        body = json.loads(result.body)

    assert body["status"] == "already_adopted", body
    assert body["wfirma_pz_doc_id"] == _DOC_ID
    mock_patch.assert_not_called()


# ── Test 3: different existing PZ → blocked ───────────────────────────────────

def test_different_existing_pz_blocks_adopt():
    """
    Audit already contains a DIFFERENT wfirma_pz_doc_id.
    Expect: status=blocked, blocking_reasons mentions the conflict.
    """
    with (
        patch("app.api.routes_wfirma.get_output_dir"),
        patch("app.api.routes_wfirma._read_audit", return_value=_AUDIT_WITH_DIFFERENT),
        patch("app.api.routes_wfirma.wfirma_client.fetch_warehouse_pz",
              return_value=_make_fetch_ok()),
        patch("app.api.routes_wfirma._find_pz_owner_batch", return_value=None),
        patch("app.api.routes_wfirma._patch_pz_adopted") as mock_patch,
    ):
        result = _run()
        body = json.loads(result.body)

    assert body["status"] == "blocked", body
    reasons = body.get("blocking_reasons", [])
    assert any("already has" in r for r in reasons), reasons
    mock_patch.assert_not_called()


# ── Test 4: duplicate adoption across shipments → blocked ─────────────────────

def test_cross_shipment_duplicate_blocks_adopt():
    """
    _find_pz_owner_batch returns a different batch that already owns the PZ.
    Expect: status=blocked, blocking_reasons mentions the owning batch.
    """
    with (
        patch("app.api.routes_wfirma.get_output_dir"),
        patch("app.api.routes_wfirma._read_audit", return_value=_AUDIT_CLEAN),
        patch("app.api.routes_wfirma.wfirma_client.fetch_warehouse_pz",
              return_value=_make_fetch_ok()),
        patch("app.api.routes_wfirma._find_pz_owner_batch",
              return_value=_OTHER_BATCH),
        patch("app.api.routes_wfirma._patch_pz_adopted") as mock_patch,
    ):
        result = _run()
        body = json.loads(result.body)

    assert body["status"] == "blocked", body
    reasons = body.get("blocking_reasons", [])
    assert any(_OTHER_BATCH in r for r in reasons), reasons
    mock_patch.assert_not_called()


# ── Test 5: wFirma document not found → blocked ───────────────────────────────

def test_missing_wfirma_document_blocks_adopt():
    """
    wFirma lookup returns ok=False (document does not exist).
    Expect: status=blocked, blocking_reasons mentions 'not found or unreachable'.
    """
    with (
        patch("app.api.routes_wfirma.get_output_dir"),
        patch("app.api.routes_wfirma._read_audit", return_value=_AUDIT_CLEAN),
        patch("app.api.routes_wfirma.wfirma_client.fetch_warehouse_pz",
              return_value=_make_fetch_fail("PZ document '999' not found")),
        patch("app.api.routes_wfirma._patch_pz_adopted") as mock_patch,
    ):
        result = _run()
        body = json.loads(result.body)

    assert body["status"] == "blocked", body
    reasons = body.get("blocking_reasons", [])
    assert any("not found or unreachable" in r for r in reasons), reasons
    mock_patch.assert_not_called()


# ── Test 6: missing identifiers → blocked before wFirma call ─────────────────

def test_missing_body_identifiers_blocks_before_wfirma():
    """
    Neither pz_doc_id nor pz_number supplied.
    Expect: status=blocked immediately, no wFirma call.
    """
    with (
        patch("app.api.routes_wfirma.wfirma_client.fetch_warehouse_pz") as mock_fetch,
        patch("app.api.routes_wfirma.wfirma_client.find_warehouse_pz_by_number") as mock_find,
    ):
        result = _run(body=_body())   # both None
        body = json.loads(result.body)

    assert body["status"] == "blocked", body
    reasons = body.get("blocking_reasons", [])
    assert any("pz_doc_id or pz_number is required" in r for r in reasons), reasons
    mock_fetch.assert_not_called()
    mock_find.assert_not_called()


# ── Test 7: pz_number supplied → find_warehouse_pz_by_number called ──────────

def test_pz_number_routes_to_find_function(tmp_path):
    """
    When only pz_number is given (no pz_doc_id), the endpoint must call
    find_warehouse_pz_by_number, not fetch_warehouse_pz.
    """
    audit_path = tmp_path / "audit.json"
    audit_path.write_text(json.dumps(_AUDIT_CLEAN))

    with (
        patch("app.api.routes_wfirma.get_output_dir", return_value=tmp_path),
        patch("app.api.routes_wfirma._read_audit", return_value=_AUDIT_CLEAN),
        patch("app.api.routes_wfirma.wfirma_client.fetch_warehouse_pz") as mock_fetch,
        patch("app.api.routes_wfirma.wfirma_client.find_warehouse_pz_by_number",
              return_value=_make_fetch_ok()) as mock_find,
        patch("app.api.routes_wfirma._find_pz_owner_batch", return_value=None),
        patch("app.api.routes_wfirma.tl.log_event"),
    ):
        result = _run(body=_body(pz_number=_DOC_NO))
        body = json.loads(result.body)

    assert body["status"] == "adopted", body
    mock_find.assert_called_once_with(_DOC_NO)
    mock_fetch.assert_not_called()
