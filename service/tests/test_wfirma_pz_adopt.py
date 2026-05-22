"""
test_wfirma_pz_adopt.py — POST .../wfirma/pz_adopt route tests.

Drives the route through ``fastapi.testclient.TestClient`` so FastAPI's
dependency machinery (notably the ``X-Operator`` ``Header(...)`` default
on the route signature) resolves correctly. The previous shape called
the coroutine directly and tripped on the unbound ``Header`` sentinel.

Coverage (preserved from the original suite):
  1. adopt success — wFirma confirms PZ, no prior link → status=adopted,
     audit patched with pz_source='adopted_existing'
  2. already_adopted — same wfirma_pz_doc_id already in audit → idempotent
  3. reject different existing id — audit holds a different PZ → 409
  4. reject duplicate adoption across shipments → blocked
  5. reject missing wFirma document → blocked
  6. missing body identifiers → blocked before wFirma call
  7. pz_number supplied → routes to find_warehouse_pz_by_number
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

_svc = Path(__file__).parent.parent
if str(_svc) not in sys.path:
    sys.path.insert(0, str(_svc))


# ── Shared constants ───────────────────────────────────────────────────────────

_BATCH       = "TEST_PZ_ADOPT_001"
_OTHER_BATCH = "TEST_PZ_ADOPT_OTHER"
_DOC_ID      = "183167843"
_DOC_NO      = "PZ 3/5/2026"
_OPERATOR    = "amit"

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


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture()
def storage(tmp_path):
    """Minimal storage init so the FastAPI app can boot through TestClient.
    The adopt route mocks every internal helper, but app startup still
    initialises the operational DBs."""
    from app.services import packing_db   as pdb
    from app.services import warehouse_db as wdb
    from app.services import document_db  as ddb
    from app.services import wfirma_db    as wfdb
    from app.services import proforma_service_charges_db as scdb
    pdb.init_packing_db(tmp_path / "packing.db")
    wdb.init_warehouse_db(tmp_path / "warehouse.db")
    ddb.init_document_db(tmp_path / "documents.db")
    wfdb.init_wfirma_db(tmp_path / "wfirma.db")
    scdb.init(tmp_path / "proforma_links.db")
    return tmp_path


@pytest.fixture()
def client(storage):
    from app.core.config import settings
    from app.main import app
    # pz_adopt now checks wfirma_create_pz_allowed (same kill-switch as pz_create).
    # Tests explicitly enable the flag so they exercise the adopt-specific logic
    # rather than the governance gate (the gate itself is covered in test_wfirma_pz_guard_normalization.py).
    with patch.object(settings, "storage_root", storage), \
         patch.object(settings, "wfirma_create_pz_allowed", True):
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


def _auth():
    from app.core.config import settings
    return {"X-API-KEY": settings.api_key or "test-key"}


def _post(client_obj, *, batch_id=_BATCH, body_json=None,
           operator=_OPERATOR):
    """POST adopt request via TestClient with X-Operator header.
    ``body_json`` may be ``None`` (no key) — sends an empty {} which the
    route's pydantic body parser accepts, mirroring the old _body() helper.
    """
    payload = body_json if body_json is not None else {}
    headers = {**_auth(), "X-Operator": operator}
    return client_obj.post(
        f"/api/v1/upload/shipment/{batch_id}/wfirma/pz_adopt",
        headers=headers, json=payload,
    )


def _make_fetch_ok(pz_doc_id=_DOC_ID, pz_number=_DOC_NO):
    from app.services.wfirma_client import PZFetchResult
    return PZFetchResult(ok=True, pz_doc_id=pz_doc_id, pz_number=pz_number)


def _make_fetch_fail(error="document not found"):
    from app.services.wfirma_client import PZFetchResult
    return PZFetchResult(ok=False, error=error)


# ── Test 1: adopt success ─────────────────────────────────────────────────────

def test_adopt_success_writes_audit_and_returns_adopted(client, tmp_path):
    """Fresh batch, no existing PZ. wFirma fetch succeeds.
    Expect: status=adopted, audit written with pz_source=adopted_existing."""
    audit_dir  = tmp_path / "adopt_success"; audit_dir.mkdir()
    audit_path = audit_dir / "audit.json"
    audit_path.write_text(json.dumps(_AUDIT_CLEAN))

    with (
        patch("app.api.routes_wfirma.get_output_dir", return_value=audit_dir),
        patch("app.api.routes_wfirma._read_audit", return_value=_AUDIT_CLEAN),
        patch("app.api.routes_wfirma.wfirma_client.fetch_warehouse_pz",
              return_value=_make_fetch_ok()),
        patch("app.api.routes_wfirma._find_pz_owner_batch", return_value=None),
        patch("app.api.routes_wfirma.tl.log_event"),
    ):
        r = _post(client, body_json={"pz_doc_id": _DOC_ID})

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"]            == "adopted", body
    assert body["wfirma_pz_doc_id"]  == _DOC_ID
    assert body["pz_number"]         == _DOC_NO
    assert body["pz_source"]         == "adopted_existing"

    saved = json.loads(audit_path.read_text())
    assert saved["wfirma_export"]["wfirma_pz_doc_id"] == _DOC_ID
    assert saved["wfirma_export"]["pz_source"]        == "adopted_existing"


# ── Test 2: already adopted (same id) → idempotent ───────────────────────────

def test_already_adopted_same_id_returns_idempotent(client):
    """Audit already contains the same pz_doc_id.
    Expect: status=already_adopted, no second write."""
    with (
        patch("app.api.routes_wfirma.get_output_dir"),
        patch("app.api.routes_wfirma._read_audit", return_value=_AUDIT_WITH_SAME),
        patch("app.api.routes_wfirma.wfirma_client.fetch_warehouse_pz",
              return_value=_make_fetch_ok()),
        patch("app.api.routes_wfirma._find_pz_owner_batch", return_value=None),
        patch("app.api.routes_wfirma._patch_pz_adopted") as mock_patch,
    ):
        r = _post(client, body_json={"pz_doc_id": _DOC_ID})

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"]           == "already_adopted", body
    assert body["wfirma_pz_doc_id"] == _DOC_ID
    mock_patch.assert_not_called()


# ── Test 3: different existing PZ → 409 ───────────────────────────────────────

def test_different_existing_pz_blocks_adopt(client):
    """Audit already contains a DIFFERENT wfirma_pz_doc_id.
    Idempotency hardening: route raises HTTPException(409,
    code=PZ_ALREADY_LINKED) so wFirma audit can never be silently
    overwritten. TestClient surfaces this as HTTP 409."""
    with (
        patch("app.api.routes_wfirma.get_output_dir"),
        patch("app.api.routes_wfirma._read_audit", return_value=_AUDIT_WITH_DIFFERENT),
        patch("app.api.routes_wfirma.wfirma_client.fetch_warehouse_pz",
              return_value=_make_fetch_ok()),
        patch("app.api.routes_wfirma._find_pz_owner_batch", return_value=None),
        patch("app.api.routes_wfirma._patch_pz_adopted") as mock_patch,
    ):
        r = _post(client, body_json={"pz_doc_id": _DOC_ID})

    assert r.status_code == 409, r.text
    detail = r.json().get("detail") or {}
    code = detail.get("code") if isinstance(detail, dict) else ""
    assert code in ("PZ_ALREADY_LINKED",
                     "PZ_ALREADY_CREATED",
                     "PZ_ALREADY_ADOPTED"), detail
    mock_patch.assert_not_called()


# ── Test 4: duplicate adoption across shipments → blocked ─────────────────────

def test_cross_shipment_duplicate_blocks_adopt(client):
    """``_find_pz_owner_batch`` returns a different batch that already
    owns the PZ. Expect: status=blocked, blocking_reasons names the
    owning batch."""
    with (
        patch("app.api.routes_wfirma.get_output_dir"),
        patch("app.api.routes_wfirma._read_audit", return_value=_AUDIT_CLEAN),
        patch("app.api.routes_wfirma.wfirma_client.fetch_warehouse_pz",
              return_value=_make_fetch_ok()),
        patch("app.api.routes_wfirma._find_pz_owner_batch",
              return_value=_OTHER_BATCH),
        patch("app.api.routes_wfirma._patch_pz_adopted") as mock_patch,
    ):
        r = _post(client, body_json={"pz_doc_id": _DOC_ID})

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "blocked", body
    reasons = body.get("blocking_reasons", [])
    assert any(_OTHER_BATCH in str(reason) for reason in reasons), reasons
    mock_patch.assert_not_called()


# ── Test 5: wFirma document not found → blocked ───────────────────────────────

def test_missing_wfirma_document_blocks_adopt(client):
    """wFirma lookup returns ok=False (document does not exist).
    Expect: status=blocked, blocking_reasons names 'not found or unreachable'."""
    with (
        patch("app.api.routes_wfirma.get_output_dir"),
        patch("app.api.routes_wfirma._read_audit", return_value=_AUDIT_CLEAN),
        patch("app.api.routes_wfirma.wfirma_client.fetch_warehouse_pz",
              return_value=_make_fetch_fail("PZ document '999' not found")),
        patch("app.api.routes_wfirma._patch_pz_adopted") as mock_patch,
    ):
        r = _post(client, body_json={"pz_doc_id": _DOC_ID})

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "blocked", body
    reasons = body.get("blocking_reasons", [])
    assert any("not found or unreachable" in str(reason) for reason in reasons), reasons
    mock_patch.assert_not_called()


# ── Test 6: missing identifiers → 422 from model_validator ───────────────────
#
# Previously expected 200+blocked from Guard 1. After _PZAdoptBody gained a
# model_validator (2026-05-22), Pydantic rejects the empty body at the schema
# level and returns 422 before Guard 1 is reached. The error message is
# machine-readable and contains the same human text as before.

def test_missing_body_identifiers_returns_422(client):
    """Neither pz_doc_id nor pz_number supplied.

    Expect: 422 Unprocessable Entity from _PZAdoptBody.model_validator with
    a clear, machine-readable reason. No wFirma call is made.
    """
    with (
        patch("app.api.routes_wfirma.wfirma_client.fetch_warehouse_pz") as mock_fetch,
        patch("app.api.routes_wfirma.wfirma_client.find_warehouse_pz_by_number") as mock_find,
    ):
        r = _post(client, body_json={})

    assert r.status_code == 422, r.text
    detail = r.json().get("detail", [])
    # Pydantic v2 returns a list of validation error objects; the message is
    # in detail[0]["msg"].
    assert any(
        "pz_doc_id or pz_number is required" in str(item)
        for item in detail
    ), detail
    mock_fetch.assert_not_called()
    mock_find.assert_not_called()


# ── Test 7: pz_number supplied → find_warehouse_pz_by_number called ──────────

def test_pz_number_routes_to_find_function(client, tmp_path):
    """When only pz_number is given (no pz_doc_id), the endpoint must
    call find_warehouse_pz_by_number, not fetch_warehouse_pz."""
    audit_dir  = tmp_path / "adopt_via_number"; audit_dir.mkdir()
    audit_path = audit_dir / "audit.json"
    audit_path.write_text(json.dumps(_AUDIT_CLEAN))

    with (
        patch("app.api.routes_wfirma.get_output_dir", return_value=audit_dir),
        patch("app.api.routes_wfirma._read_audit", return_value=_AUDIT_CLEAN),
        patch("app.api.routes_wfirma.wfirma_client.fetch_warehouse_pz") as mock_fetch,
        patch("app.api.routes_wfirma.wfirma_client.find_warehouse_pz_by_number",
              return_value=_make_fetch_ok()) as mock_find,
        patch("app.api.routes_wfirma._find_pz_owner_batch", return_value=None),
        patch("app.api.routes_wfirma.tl.log_event"),
    ):
        r = _post(client, body_json={"pz_number": _DOC_NO})

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "adopted", body
    mock_find.assert_called_once_with(_DOC_NO)
    mock_fetch.assert_not_called()


# ── Test 8: X-Operator header threads through to the route ──────────────────

def test_x_operator_header_threaded_through(client, tmp_path):
    """Defence-in-depth: confirm the TestClient request actually carries
    X-Operator into the route. The audit timeline emit (mocked here) is
    invoked with detail.operator = the supplied value, so we capture
    that arg."""
    audit_dir  = tmp_path / "adopt_op"; audit_dir.mkdir()
    (audit_dir / "audit.json").write_text(json.dumps(_AUDIT_CLEAN))

    log_calls = []
    def _log(*a, **kw):
        log_calls.append({"args": a, "kw": kw})

    with (
        patch("app.api.routes_wfirma.get_output_dir", return_value=audit_dir),
        patch("app.api.routes_wfirma._read_audit", return_value=_AUDIT_CLEAN),
        patch("app.api.routes_wfirma.wfirma_client.fetch_warehouse_pz",
              return_value=_make_fetch_ok()),
        patch("app.api.routes_wfirma._find_pz_owner_batch", return_value=None),
        patch("app.api.routes_wfirma.tl.log_event", side_effect=_log),
    ):
        r = _post(client, body_json={"pz_doc_id": _DOC_ID},
                   operator="amit")

    assert r.status_code == 200, r.text
    # Find the adopted-event call and verify the operator made it through.
    operator_seen = None
    for c in log_calls:
        detail = (c.get("kw") or {}).get("detail") or {}
        if "operator" in detail:
            operator_seen = detail["operator"]
            break
    assert operator_seen == "amit", log_calls
