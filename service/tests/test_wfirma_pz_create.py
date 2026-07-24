"""
test_wfirma_pz_create.py — unit tests for POST .../wfirma/pz_create

Covers:
  1. WFIRMA_CREATE_PZ_ALLOWED=false → 403 before any wFirma call
  2. Existing wfirma_pz_doc_id in audit → status=already_created, no wFirma call
  3. Unresolved product_codes → status=not_ready, no wFirma call
  4. Price conflicts → status=not_ready, no wFirma call
  5. Ready preview → create_warehouse_pz called exactly once
  6. Success → wfirma_pz_doc_id written to audit via _patch_pz_doc_id
  7. wFirma failure → _patch_pz_doc_id NOT called, status=failed
  8. Duplicate rerun (already_created guard) → create_warehouse_pz not called
  9. Success response includes planned_lines
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

_svc = Path(__file__).parent.parent
if str(_svc) not in sys.path:
    sys.path.insert(0, str(_svc))


# ── Shared fixtures ────────────────────────────────────────────────────────────

_BATCH = "TEST_PZ_CREATE_001"
_MRN   = "26PL321000E0CREATE01"

_AUDIT_BASE = {
    "batch_id": _BATCH,
    "status":   "processed",
    "customs_declaration": {
        "mrn":            _MRN,
        "clearance_date": "2026-05-01",
    },
    "inputs":        {},
    "wfirma_export": {},
}

_AUDIT_WITH_DOC_ID = {
    **_AUDIT_BASE,
    "wfirma_export": {"wfirma_pz_doc_id": "PZ_EXISTING_999"},
}

def _make_row(product_code: str, qty: float = 2.0, price: float = 173.00) -> dict:
    return {
        "product_code":    product_code,
        "item_type":       "wisiorek",
        "description_en":  "Silver Pendant",
        "pl_desc":         "Wisiorek",
        "quantity":        qty,
        "unit_netto_pln":  price,
        "invoice_no":      "EJL/26-27/013",
    }

_MAPPED_PRODUCTS = [
    {"product_code": "EJL/26-27/013-1", "wfirma_product_id": "48611875"},
    {"product_code": "EJL/26-27/013-2", "wfirma_product_id": "48612067"},
]

def _settings(gate: bool = True):
    m = MagicMock()
    m.wfirma_create_pz_allowed       = gate
    m.wfirma_supplier_contractor_id  = "38142296"
    m.wfirma_warehouse_id            = "347088"
    return m

def _pz_success():
    from app.services.wfirma_client import PZResult
    return PZResult(ok=True, wfirma_pz_doc_id="PZ_NEW_12345")

def _pz_failure():
    from app.services.wfirma_client import PZResult
    return PZResult(ok=False, error="wFirma API timeout")


def _run(batch_id=_BATCH, x_operator=None):
    import asyncio
    from app.api.routes_wfirma import wfirma_pz_create
    # Call the route function directly: FastAPI Header() defaults are not
    # resolved off-server, so pass x_operator explicitly (the route signature
    # gained the X-Operator attribution header).
    return asyncio.get_event_loop().run_until_complete(
        wfirma_pz_create(batch_id, x_operator=x_operator))


# ── Test 1: gate off → 403 before any wFirma call ────────────────────────────

def test_gate_off_returns_403():
    with (
        patch("app.api.routes_wfirma.settings", _settings(gate=False)),
        patch("app.api.routes_wfirma.wfirma_client.create_warehouse_pz") as mock_create,
    ):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            _run()
        assert exc_info.value.status_code == 403
        assert exc_info.value.detail["code"] == "PZ_CREATE_GATE_OFF"
        mock_create.assert_not_called()


# ── Test 2: existing wfirma_pz_doc_id → already_created, no wFirma call ──────

def test_existing_doc_id_returns_already_created():
    rows = [_make_row("EJL/26-27/013-1")]

    with (
        patch("app.api.routes_wfirma.settings", _settings()),
        patch("app.api.routes_wfirma.get_output_dir"),
        patch("app.api.routes_wfirma._read_audit", return_value=_AUDIT_WITH_DOC_ID),
        patch("app.api.routes_wfirma._guard_wfirma_export"),
        patch("app.api.routes_wfirma._build_rows", return_value=rows),
        patch("app.api.routes_wfirma.wfirma_client.create_warehouse_pz") as mock_create,
    ):
        result = _run()
        body = json.loads(result.body)

    assert body["status"] == "already_created"
    assert body["wfirma_pz_doc_id"] == "PZ_EXISTING_999"
    mock_create.assert_not_called()


# ── Test 3: unresolved product_codes → not_ready, no wFirma call ─────────────

def test_unresolved_products_block_pz_create():
    rows = [_make_row("EJL/26-27/013-UNKNOWN")]

    with (
        patch("app.api.routes_wfirma.settings", _settings()),
        patch("app.api.routes_wfirma.get_output_dir"),
        patch("app.api.routes_wfirma._read_audit", return_value=_AUDIT_BASE),
        patch("app.api.routes_wfirma._guard_wfirma_export"),
        patch("app.api.routes_wfirma._build_rows", return_value=rows),
        patch("app.api.routes_wfirma._mirror_product_map", return_value={}),
        patch("app.api.routes_wfirma.wfirma_client.create_warehouse_pz") as mock_create,
    ):
        result = _run()
        body = json.loads(result.body)

    assert result.status_code == 422
    assert body["status"] == "not_ready"
    assert "EJL/26-27/013-UNKNOWN" in body["unresolved_product_codes"]
    mock_create.assert_not_called()


# ── Test 4: price conflicts → not_ready, no wFirma call ──────────────────────

def test_price_conflicts_block_pz_create():
    rows = [
        _make_row("EJL/26-27/013-1", qty=1.0, price=173.00),
        _make_row("EJL/26-27/013-1", qty=1.0, price=999.00),  # same code, different price
    ]
    products = [{"product_code": "EJL/26-27/013-1", "wfirma_product_id": "48611875"}]

    with (
        patch("app.api.routes_wfirma.settings", _settings()),
        patch("app.api.routes_wfirma.get_output_dir"),
        patch("app.api.routes_wfirma._read_audit", return_value=_AUDIT_BASE),
        patch("app.api.routes_wfirma._guard_wfirma_export"),
        patch("app.api.routes_wfirma._build_rows", return_value=rows),
        patch("app.api.routes_wfirma._mirror_product_map", return_value={p["product_code"]: p["wfirma_product_id"] for p in products}),
        patch("app.api.routes_wfirma.wfirma_client.create_warehouse_pz") as mock_create,
    ):
        result = _run()
        body = json.loads(result.body)

    assert result.status_code == 422
    assert body["status"] == "not_ready"
    assert len(body["price_conflicts"]) > 0
    mock_create.assert_not_called()


# ── Test 5: ready preview → create_warehouse_pz called exactly once ──────────

def test_ready_preview_calls_create_once():
    rows = [
        _make_row("EJL/26-27/013-1", qty=3.0, price=173.00),
        _make_row("EJL/26-27/013-2", qty=2.0, price=176.50),
    ]

    with (
        patch("app.api.routes_wfirma.settings", _settings()),
        patch("app.api.routes_wfirma.get_output_dir"),
        patch("app.api.routes_wfirma._read_audit", return_value=_AUDIT_BASE),
        patch("app.api.routes_wfirma._guard_wfirma_export"),
        patch("app.api.routes_wfirma._build_rows", return_value=rows),
        patch("app.api.routes_wfirma._mirror_product_map", return_value={p["product_code"]: p["wfirma_product_id"] for p in _MAPPED_PRODUCTS}),
        patch("app.api.routes_wfirma.wfirma_client.create_warehouse_pz",
              return_value=_pz_success()) as mock_create,
        patch("app.api.routes_wfirma._patch_pz_doc_id", return_value=None),
        patch("app.api.routes_wfirma.tl.log_event"),
    ):
        result = _run()

    mock_create.assert_called_once()


# ── Test 6: success → _patch_pz_doc_id called with returned doc id ────────────

def test_success_writes_pz_doc_id_to_audit():
    rows = [_make_row("EJL/26-27/013-1", qty=3.0, price=173.00)]
    products = [{"product_code": "EJL/26-27/013-1", "wfirma_product_id": "48611875"}]
    patched: list = []

    def fake_patch(output_dir, doc_id):
        patched.append(doc_id)

    with (
        patch("app.api.routes_wfirma.settings", _settings()),
        patch("app.api.routes_wfirma.get_output_dir"),
        patch("app.api.routes_wfirma._read_audit", return_value=_AUDIT_BASE),
        patch("app.api.routes_wfirma._guard_wfirma_export"),
        patch("app.api.routes_wfirma._build_rows", return_value=rows),
        patch("app.api.routes_wfirma._mirror_product_map", return_value={p["product_code"]: p["wfirma_product_id"] for p in products}),
        patch("app.api.routes_wfirma.wfirma_client.create_warehouse_pz",
              return_value=_pz_success()),
        patch("app.api.routes_wfirma._patch_pz_doc_id", side_effect=fake_patch),
        patch("app.api.routes_wfirma.tl.log_event"),
    ):
        result = _run()
        body = json.loads(result.body)

    assert body["status"] == "created"
    assert body["wfirma_pz_doc_id"] == "PZ_NEW_12345"
    assert patched == ["PZ_NEW_12345"]


# ── Test 7: wFirma failure → _patch_pz_doc_id NOT called, status=failed ───────

def test_wfirma_failure_writes_nothing():
    rows = [_make_row("EJL/26-27/013-1", qty=3.0, price=173.00)]
    products = [{"product_code": "EJL/26-27/013-1", "wfirma_product_id": "48611875"}]
    patched: list = []

    with (
        patch("app.api.routes_wfirma.settings", _settings()),
        patch("app.api.routes_wfirma.get_output_dir"),
        patch("app.api.routes_wfirma._read_audit", return_value=_AUDIT_BASE),
        patch("app.api.routes_wfirma._guard_wfirma_export"),
        patch("app.api.routes_wfirma._build_rows", return_value=rows),
        patch("app.api.routes_wfirma._mirror_product_map", return_value={p["product_code"]: p["wfirma_product_id"] for p in products}),
        patch("app.api.routes_wfirma.wfirma_client.create_warehouse_pz",
              return_value=_pz_failure()),
        patch("app.api.routes_wfirma._patch_pz_doc_id",
              side_effect=lambda *a: patched.append(a)),
        patch("app.api.routes_wfirma.tl.log_event"),
    ):
        result = _run()
        body = json.loads(result.body)

    assert result.status_code == 502
    assert body["status"] == "failed"
    assert "timeout" in body["error"]
    assert patched == []


# ── Test 8: duplicate rerun (already_created guard) → no wFirma call ─────────

def test_duplicate_rerun_does_not_call_wfirma():
    """
    After a successful pz_create, the audit holds wfirma_pz_doc_id.
    A second call must short-circuit at guard 5 without touching wFirma.
    """
    with (
        patch("app.api.routes_wfirma.settings", _settings()),
        patch("app.api.routes_wfirma.get_output_dir"),
        patch("app.api.routes_wfirma._read_audit", return_value=_AUDIT_WITH_DOC_ID),
        patch("app.api.routes_wfirma._guard_wfirma_export"),
        patch("app.api.routes_wfirma.wfirma_client.create_warehouse_pz") as mock_create,
    ):
        result = _run()
        body = json.loads(result.body)

    assert body["status"] == "already_created"
    mock_create.assert_not_called()


# ── Test 9: success response includes planned_lines ───────────────────────────

def test_success_response_includes_planned_lines():
    rows = [
        _make_row("EJL/26-27/013-1", qty=3.0, price=173.00),
        _make_row("EJL/26-27/013-2", qty=2.0, price=176.50),
    ]

    with (
        patch("app.api.routes_wfirma.settings", _settings()),
        patch("app.api.routes_wfirma.get_output_dir"),
        patch("app.api.routes_wfirma._read_audit", return_value=_AUDIT_BASE),
        patch("app.api.routes_wfirma._guard_wfirma_export"),
        patch("app.api.routes_wfirma._build_rows", return_value=rows),
        patch("app.api.routes_wfirma._mirror_product_map", return_value={p["product_code"]: p["wfirma_product_id"] for p in _MAPPED_PRODUCTS}),
        patch("app.api.routes_wfirma.wfirma_client.create_warehouse_pz",
              return_value=_pz_success()),
        patch("app.api.routes_wfirma._patch_pz_doc_id", return_value=None),
        patch("app.api.routes_wfirma.tl.log_event"),
    ):
        result = _run()
        body = json.loads(result.body)

    assert body["status"] == "created"
    assert body["line_count"] == 2
    assert len(body["planned_lines"]) == 2
    codes = {pl["product_code"] for pl in body["planned_lines"]}
    assert "EJL/26-27/013-1" in codes
    assert "EJL/26-27/013-2" in codes
    for pl in body["planned_lines"]:
        assert "good_id" in pl
        assert "price_pln" in pl
        assert "count" in pl
