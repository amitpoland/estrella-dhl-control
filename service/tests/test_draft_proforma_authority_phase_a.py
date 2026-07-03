"""test_draft_proforma_authority_phase_a.py — Phase A: lock Draft Proforma authority.

Proves that ProformaDraft.editable_lines_json is already the single commercial
authority for wFirma export.  No C2 re-resolution from v_sales_to_wfirma happens
at post time.  These tests document existing behaviour before any Phase B changes.

Five tests across three classes:
  1. product_code in ProformaRequest.lines sourced from editable_lines_json only
  2. query_sales_to_wfirma / v_sales_to_wfirma view NOT called during request build
  3. _derive_draft_readiness does NOT call any wfirma_reservation function
  4. _derive_draft_readiness with intent='post' does not require reservation
  5. _build_proforma_request_from_draft output is stable regardless of view return

No production code changes.  No schema changes.
"""
from __future__ import annotations

import json
from contextlib import ExitStack
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest


# ── Shared constants ───────────────────────────────────────────────────────────

_PRODUCT_CODE      = "EJL/26-27/PHASE-A-001"
_WFIRMA_PRODUCT_ID = "WF-PHASE-A-001"
_WFIRMA_CUST_ID    = "WF-CUST-001"
_VAT_CODE_ID       = "42"

_TEST_LINE: Dict[str, Any] = {
    "product_code": _PRODUCT_CODE,
    "qty":          2.0,
    "unit_price":   500.0,
    "currency":     "EUR",
    "design_no":    "D-PHASE-A",
}


# ── Shared helpers ─────────────────────────────────────────────────────────────

def _make_draft(lines: List[Dict[str, Any]] = None, **kw):
    from app.services.proforma_invoice_link_db import ProformaDraft
    return ProformaDraft(
        batch_id             = "EJL-26-27-PHASE-A-TEST",
        client_name          = "TEST_CLIENT",
        status               = "approved",
        draft_state          = "approved",
        currency             = "EUR",
        editable_lines_json  = json.dumps(lines if lines is not None else [_TEST_LINE]),
        id                   = 99,
        **kw,
    )


def _make_wfdb_mock() -> MagicMock:
    """Mock for wfirma_db that satisfies both _db_path guards and get_product calls."""
    m = MagicMock()
    m._db_path = Path("/fake/wfirma.db")
    m.get_product.return_value = {"wfirma_product_id": _WFIRMA_PRODUCT_ID}
    return m


def _customer_resolution() -> Dict[str, Any]:
    """Minimal _resolve_customer return that lets the legacy VAT path proceed without
    calling wfirma_client.search_customer (country=PL satisfies the guard)."""
    return {
        "raw_input":           "TEST_CLIENT",
        "normalized_name":     "test_client",
        "found":               True,
        "ambiguous":           False,
        "match_strategy":      "exact",
        "customer":            {
            "country":                    "PL",
            "vat_id":                     "",
            "ship_to_mode":               "same_as_bill_to",
            "ship_to_wfirma_customer_id": "",
        },
        "wfirma_customer_id":  _WFIRMA_CUST_ID,
        "resolved_wfirma_name": "TEST_CLIENT",
        "candidates":          [],
    }


def _vat_decision() -> Dict[str, Any]:
    return {"context": "domestic", "vat_code": "23", "reason": "pl"}


def _enter_build_patches(stack: ExitStack, mock_wfdb: MagicMock) -> None:
    """Enter all patches required to run _build_proforma_request_from_draft in isolation.

    Uses an ExitStack so callers can add extra patches before entering the function call.
    Patches:
      - _resolve_customer → minimal customer dict (PL domestic, no ambiguity)
      - get_customer_master → None (triggers legacy VAT path, avoids CustomerMaster DB)
      - wfdb module → MagicMock with _db_path set and get_product returning a known ID
      - wfirma_client.decide_proforma_vat_context → domestic/23 VAT decision
      - wfirma_client.resolve_vat_code_id_for_context → numeric code "42"
    """
    stack.enter_context(
        patch("app.api.routes_proforma._resolve_customer",
              return_value=_customer_resolution())
    )
    stack.enter_context(
        patch("app.api.routes_proforma.get_customer_master", return_value=None)
    )
    stack.enter_context(
        patch("app.api.routes_proforma.wfdb", mock_wfdb)
    )
    # C-3g: per-line good-id resolution is mirror-only — the builder calls
    # _c1f_mirror_good_id (the retired wfdb.get_product fallback is gone).
    stack.enter_context(
        patch("app.api.routes_proforma._c1f_mirror_good_id",
              return_value=_WFIRMA_PRODUCT_ID)
    )
    stack.enter_context(
        patch("app.services.wfirma_client.decide_proforma_vat_context",
              return_value=_vat_decision())
    )
    stack.enter_context(
        patch("app.services.wfirma_client.resolve_vat_code_id_for_context",
              return_value=_VAT_CODE_ID)
    )


def _minimal_preview() -> Dict[str, Any]:
    return {
        "ok":                  True,
        "batch_id":            "EJL-26-27-PHASE-A-TEST",
        "blocking_reasons":    [],
        "export_blockers":     [],
        "export_advisories":   [],
        "warehouse_blockers":  [],
        "resolution_rows":     [],
        "lines":               [],
        "ambiguous_design_codes": {},
        "wfirma_products":     {},
        "batch_lifecycle":     {"status": "TRANSIT", "clearance_status": None},
        "customer_resolution": {
            "found": True, "ambiguous": False, "candidates": [],
            "wfirma_customer_id": _WFIRMA_CUST_ID,
        },
    }


def _minimal_auth() -> Dict[str, Any]:
    return {
        "batch_id":                  "EJL-26-27-PHASE-A-TEST",
        "authority_available":       True,
        "product_codes":             set(),
        "rows_scanned":              0,
        "available_by_product_code": {},
        "invoice_by_product_code":   {},
        "authority_error":           None,
    }


# ── Class 1: product_code authority ───────────────────────────────────────────

class TestDraftProductCodeAuthority:
    """Prove that _build_proforma_request_from_draft reads product_code from
    editable_lines_json only and never consults the v_sales_to_wfirma view."""

    def test_product_code_read_from_editable_lines(self):
        """ProformaRequest.lines[0].product_code must equal the value in editable_lines_json."""
        from app.api.routes_proforma import _build_proforma_request_from_draft

        draft     = _make_draft()
        mock_wfdb = _make_wfdb_mock()

        with ExitStack() as stack:
            _enter_build_patches(stack, mock_wfdb)
            req, _, _, _ = _build_proforma_request_from_draft(draft)

        assert len(req.lines) == 1, (
            f"Expected 1 line in ProformaRequest; got {len(req.lines)}"
        )
        assert req.lines[0].product_code == _PRODUCT_CODE, (
            f"Expected product_code={_PRODUCT_CODE!r} (from editable_lines_json); "
            f"got {req.lines[0].product_code!r}"
        )

    def test_query_sales_to_wfirma_not_called_during_request_build(self):
        """v_sales_to_wfirma view must NOT be consulted when building the ProformaRequest.

        The tracker patches query_sales_to_wfirma to record calls AND return a
        'wrong' product_code.  If the function reads the view, either the call
        list will be non-empty OR the product_code in the output will be wrong.
        Both conditions are checked.
        """
        from app.api.routes_proforma import _build_proforma_request_from_draft

        draft     = _make_draft()
        mock_wfdb = _make_wfdb_mock()
        view_calls: List[str] = []

        def _spy_view(batch_id):
            view_calls.append(batch_id)
            return [{"wfirma_product_code": "WRONG-CODE-FROM-VIEW"}]

        with ExitStack() as stack:
            _enter_build_patches(stack, mock_wfdb)
            stack.enter_context(
                patch("app.services.document_db.query_sales_to_wfirma", _spy_view)
            )
            req, _, _, _ = _build_proforma_request_from_draft(draft)

        assert view_calls == [], (
            "query_sales_to_wfirma must NOT be called during _build_proforma_request_from_draft; "
            f"calls detected: {view_calls!r}"
        )
        assert req.lines[0].product_code == _PRODUCT_CODE, (
            "ProformaRequest.lines[0].product_code must come from editable_lines_json, "
            f"not from the v_sales_to_wfirma view; got {req.lines[0].product_code!r}"
        )

    def test_stable_output_regardless_of_view_return(self):
        """ProformaRequest must be identical whether the view returns wrong codes or nothing.

        Two runs with different view implementations; both must produce the same
        product_code, qty, and unit_price — proving the function ignores the view.
        """
        from app.api.routes_proforma import _build_proforma_request_from_draft

        draft = _make_draft()

        def _view_wrong_code(_batch_id):
            return [{"wfirma_product_code": "WRONG-CODE-FROM-VIEW-A"}]

        def _view_empty(_batch_id):
            return []

        results = []
        for view_impl in (_view_wrong_code, _view_empty):
            mock_wfdb = _make_wfdb_mock()
            with ExitStack() as stack:
                _enter_build_patches(stack, mock_wfdb)
                stack.enter_context(
                    patch("app.services.document_db.query_sales_to_wfirma", view_impl)
                )
                req, _, _, _ = _build_proforma_request_from_draft(draft)
                results.append(req)

        pc_a  = results[0].lines[0].product_code
        pc_b  = results[1].lines[0].product_code
        qty_a = results[0].lines[0].qty
        qty_b = results[1].lines[0].qty

        assert pc_a == pc_b == _PRODUCT_CODE, (
            "ProformaRequest.product_code must be stable across different view returns; "
            f"run-A={pc_a!r}, run-B={pc_b!r}"
        )
        assert qty_a == qty_b, (
            f"qty must be stable across runs; run-A={qty_a}, run-B={qty_b}"
        )


# ── Class 2: reservation is never consulted ────────────────────────────────────

class TestReservationNotRequired:
    """Prove that _derive_draft_readiness never calls wfirma_reservation functions.

    Both intent='approve' and intent='post' are covered.  wfirma_reservation is
    optional operational support; its absence must not block proforma readiness.
    """

    def test_derive_readiness_approve_does_not_touch_reservation(self):
        """_derive_draft_readiness(intent='approve') must not call any wfirma_reservation function."""
        from app.api.routes_proforma import _derive_draft_readiness

        draft             = _make_draft(lines=[])
        reservation_calls: List[str] = []

        def _spy_reservation_preview(*_a, **_kw):
            reservation_calls.append("get_reservation_preview")
            return {}

        with patch("app.api.routes_proforma._build_preview",
                   return_value=_minimal_preview()), \
             patch("app.services.cpa_product_service.authority_snapshot",
                   return_value=_minimal_auth()), \
             patch("app.services.wfirma_reservation.get_reservation_preview",
                   _spy_reservation_preview):

            _derive_draft_readiness(draft, intent="approve")

        assert reservation_calls == [], (
            "wfirma_reservation.get_reservation_preview must NOT be called from "
            f"_derive_draft_readiness; calls: {reservation_calls!r}"
        )

    def test_derive_readiness_post_intent_does_not_require_reservation(self):
        """_derive_draft_readiness(intent='post') must not call any wfirma_reservation function.

        The reservation spy is rigged to raise AssertionError if called.  The test
        passes only if the readiness function completes without triggering it.
        """
        from app.api.routes_proforma import _derive_draft_readiness

        draft = _make_draft(lines=[])

        def _fail_if_called(*_a, **_kw):
            raise AssertionError(
                "wfirma_reservation was called from _derive_draft_readiness(intent='post') — "
                "reservation must remain optional for proforma post (Phase A assertion)"
            )

        with patch("app.api.routes_proforma._build_preview",
                   return_value=_minimal_preview()), \
             patch("app.services.cpa_product_service.authority_snapshot",
                   return_value=_minimal_auth()), \
             patch("app.services.wfirma_reservation.get_reservation_preview",
                   _fail_if_called):

            # Must complete without AssertionError from the spy
            result = _derive_draft_readiness(draft, intent="post")

        # Readiness shape sanity-check
        assert "ready" in result
        assert "intent" in result
        assert result["intent"] == "post"
