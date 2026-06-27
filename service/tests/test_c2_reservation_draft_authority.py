"""test_c2_reservation_draft_authority.py — Phase B: C2 draft-first resolution.

Verifies that get_reservation_preview() reads product_code from
ProformaDraft.editable_lines_json first, falling back to v_sales_to_wfirma only
when no Draft exists (or when a sales SKU is absent from the Draft's lines).

Three behavioural tests + one regression (existing view fallback unchanged):
  1. Draft present → product_code comes from Draft, not from view
  2. No Draft → product_code comes from view (unchanged fallback behaviour)
  3. Draft present but SKU missing from Draft lines → falls back to view for that SKU
  4. Draft lookup exception is non-fatal; preview still returns via view fallback

No routes touched.  No schema changes.
"""
from __future__ import annotations

import json
from contextlib import ExitStack
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest


# ── Minimal fixture helpers ────────────────────────────────────────────────────

_BATCH   = "EJL-26-27-C2-TEST"
_CLIENT  = "TEST CLIENT"
_SKU     = "CSTR07596"          # sales.product_code / packing.design_no
_DRAFT_PC = "EJL/26-27/C2-D"   # product_code from Draft
_VIEW_PC  = "EJL/26-27/C2-V"   # product_code from v_sales_to_wfirma (should be overridden)
_DOC_ID   = "DOC-C2-001"


def _minimal_capabilities() -> Dict[str, Any]:
    return {
        "api_configured":        True,
        "reservation_supported": True,
        "create_product_allowed":  False,
        "create_customer_allowed": False,
    }


def _sales_doc() -> Dict[str, Any]:
    return {
        "id":                   _DOC_ID,
        "sales_document_id":    _DOC_ID,
        "client_name":          _CLIENT,
        "client_ref":           "C2-REF-001",
        "sales_doc_no":         "C2/2026/001",
        "client_contractor_id": "",
    }


def _spl_row() -> Dict[str, Any]:
    """One sales packing line row referencing the design SKU."""
    return {
        "sales_document_id": _DOC_ID,
        "product_code":      _SKU,   # SKU = sales design code
        "design_no":         _SKU,
        "quantity":          3.0,
    }


def _view_row() -> Dict[str, Any]:
    """One row from v_sales_to_wfirma — the view fallback."""
    return {
        "sales_document_id": _DOC_ID,
        "sales_design_no":   _SKU,
        "wfirma_product_code": _VIEW_PC,
    }


def _make_draft(design_no: str = _SKU, product_code: str = _DRAFT_PC):
    from app.services.proforma_invoice_link_db import ProformaDraft
    return ProformaDraft(
        batch_id            = _BATCH,
        client_name         = _CLIENT,
        status              = "approved",
        draft_state         = "approved",
        currency            = "EUR",
        editable_lines_json = json.dumps([{
            "design_no":    design_no,
            "product_code": product_code,
            "qty":          3.0,
            "unit_price":   100.0,
            "currency":     "EUR",
        }]),
        id = 10,
    )


def _enter_reservation_patches(
    stack: ExitStack,
    *,
    list_drafts_return: list,
    view_rows: Optional[list] = None,
) -> None:
    """Enter all patches required to run get_reservation_preview in isolation."""
    mock_wfdb = MagicMock()
    mock_wfdb._db_path = Path("/fake/wfirma.db")
    mock_wfdb.list_reservation_drafts.return_value = []
    mock_wfdb.get_customer.return_value = None
    mock_wfdb.get_product.return_value = None
    mock_wfdb.upsert_reservation_draft.return_value = 1
    mock_wfdb.upsert_reservation_line.return_value = None

    # Fake warehouse DB connection (inventory query returns empty)
    mock_con = MagicMock()
    mock_con.__enter__ = lambda s: s
    mock_con.__exit__ = MagicMock(return_value=False)
    mock_con.execute.return_value.fetchall.return_value = []

    stack.enter_context(
        patch("app.services.wfirma_reservation.wfdb", mock_wfdb)
    )
    # _ready() checks ddb._db_path / pdb._db_path / wdb._db_path which are None
    # in tests — bypass the guard entirely.
    stack.enter_context(
        patch("app.services.wfirma_reservation._ready", return_value=True)
    )
    stack.enter_context(
        patch("app.services.wfirma_capabilities.get_capabilities",
              return_value=_minimal_capabilities())
    )
    stack.enter_context(
        patch("app.services.document_db.get_sales_documents",
              return_value=[_sales_doc()])
    )
    stack.enter_context(
        patch("app.services.document_db.get_sales_packing_lines",
              return_value=[_spl_row()])
    )
    stack.enter_context(
        patch("app.services.document_db.query_sales_to_wfirma",
              return_value=view_rows if view_rows is not None else [_view_row()])
    )
    stack.enter_context(
        patch("app.services.packing_db.get_packing_lines_for_batch",
              return_value=[])
    )
    stack.enter_context(
        patch("app.services.document_db.get_invoice_lines_for_batch",
              return_value=[])
    )
    stack.enter_context(
        patch("app.services.wfirma_reservation._wcon",
              return_value=mock_con)
    )
    stack.enter_context(
        patch("app.services.warehouse_audit.get_missing_scans", return_value=[])
    )
    stack.enter_context(
        patch("app.services.warehouse_audit.get_invalid_flows", return_value=[])
    )
    stack.enter_context(
        patch("app.services.warehouse_audit.get_orphan_inventory", return_value=[])
    )
    stack.enter_context(
        patch("app.services.proforma_invoice_link_db.list_drafts_for_batch",
              return_value=list_drafts_return)
    )


# ── Tests ──────────────────────────────────────────────────────────────────────

class TestC2DraftAuthority:
    """get_reservation_preview reads product_code from Draft first, view second."""

    def test_draft_present_uses_draft_product_code(self):
        """When a Draft exists with design_no → product_code, the reservation row
        uses the Draft's product_code, not the view's value."""
        from app.services.wfirma_reservation import get_reservation_preview

        draft = _make_draft(design_no=_SKU, product_code=_DRAFT_PC)

        with ExitStack() as stack:
            _enter_reservation_patches(
                stack,
                list_drafts_return=[draft],
                view_rows=[_view_row()],   # view says VIEW_PC — should be ignored
            )
            result = get_reservation_preview(_BATCH)

        docs = result.get("documents", [])
        assert len(docs) == 1, f"Expected 1 document; got {len(docs)}"
        rows = docs[0].get("rows", [])
        assert len(rows) == 1, f"Expected 1 row; got {len(rows)}"
        got_pc = rows[0]["product_code"]
        assert got_pc == _DRAFT_PC, (
            f"Expected Draft product_code={_DRAFT_PC!r}; "
            f"got {got_pc!r} — view value should be overridden by Draft"
        )

    def test_no_draft_falls_back_to_view(self):
        """When no Draft exists, the reservation row uses the view's product_code
        (pre-existing behaviour unchanged)."""
        from app.services.wfirma_reservation import get_reservation_preview

        with ExitStack() as stack:
            _enter_reservation_patches(
                stack,
                list_drafts_return=[],     # no Draft
                view_rows=[_view_row()],
            )
            result = get_reservation_preview(_BATCH)

        docs = result.get("documents", [])
        assert len(docs) == 1
        rows = docs[0].get("rows", [])
        assert len(rows) == 1
        got_pc = rows[0]["product_code"]
        assert got_pc == _VIEW_PC, (
            f"Expected view product_code={_VIEW_PC!r} when no Draft; "
            f"got {got_pc!r}"
        )

    def test_draft_missing_sku_falls_back_to_view_for_that_sku(self):
        """When a Draft exists but does NOT have a line for a particular SKU,
        the view provides the product_code for that SKU."""
        from app.services.wfirma_reservation import get_reservation_preview

        _OTHER_SKU = "OTHER-SKU-999"
        # Draft has a line for _OTHER_SKU only, not for the test SKU
        draft = _make_draft(design_no=_OTHER_SKU, product_code="EJL/26-27/OTHER")

        with ExitStack() as stack:
            _enter_reservation_patches(
                stack,
                list_drafts_return=[draft],
                view_rows=[_view_row()],   # view covers _SKU → _VIEW_PC
            )
            result = get_reservation_preview(_BATCH)

        docs = result.get("documents", [])
        assert len(docs) == 1
        rows = docs[0].get("rows", [])
        assert len(rows) == 1
        got_pc = rows[0]["product_code"]
        assert got_pc == _VIEW_PC, (
            f"When Draft doesn't cover the SKU, expected view fallback {_VIEW_PC!r}; "
            f"got {got_pc!r}"
        )

    def test_draft_lookup_exception_is_non_fatal(self):
        """If list_drafts_for_batch raises, get_reservation_preview must still complete
        using the view fallback.  The Draft path is non-fatal by design."""
        from app.services.wfirma_reservation import get_reservation_preview

        def _raise(*_a, **_kw):
            raise RuntimeError("simulated draft DB error")

        with ExitStack() as stack:
            _enter_reservation_patches(
                stack,
                list_drafts_return=[],   # will be replaced by the raise below
                view_rows=[_view_row()],
            )
            # Override the list_drafts patch to raise instead
            stack.enter_context(
                patch("app.services.proforma_invoice_link_db.list_drafts_for_batch",
                      _raise)
            )
            result = get_reservation_preview(_BATCH)

        # Must complete without raising and still return the view-based result
        assert "documents" in result, "Non-fatal Draft error must not abort preview"
        docs = result["documents"]
        assert len(docs) == 1
        rows = docs[0].get("rows", [])
        assert len(rows) == 1
        got_pc = rows[0]["product_code"]
        assert got_pc == _VIEW_PC, (
            f"After Draft lookup error, view fallback {_VIEW_PC!r} must still work; "
            f"got {got_pc!r}"
        )
