"""test_cpa_phase4_boundary.py — CPA Phase 4: consumer migration boundary tests.

Verifies that after Phase 4:
  C1: _build_preview reads sales resolution through cpa_product_service.query_sales_resolution,
      NOT directly from document_db.query_sales_to_wfirma.
  C3: _derive_draft_readiness reads product authority through cpa_product_service.authority_snapshot,
      NOT directly from product_authority_resolver.resolve_batch_product_authority.

Each boundary test verifies:
  (a) the CPA path IS called with the right arguments
  (b) the old direct-import path is NOT called (boundary isolation)
  (c) the output dict still carries the required top-level keys (shape unchanged)
"""
from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import patch

import pytest


# ── Shared helpers ─────────────────────────────────────────────────────────────

def _minimal_draft(batch_id: str = "B-P4-C3-01", client_name: str = "TestClient",
                   editable_lines_json: str = "[]"):
    from app.services.proforma_invoice_link_db import ProformaDraft
    return ProformaDraft(
        batch_id=batch_id,
        client_name=client_name,
        status="draft",
        editable_lines_json=editable_lines_json,
        id=1,  # required: _derive_draft_readiness does int(draft.id) in its return
    )


def _minimal_preview() -> Dict[str, Any]:
    return {
        "blocking_reasons": [],
        "export_blockers": [],
        "export_advisories": [],
        "warehouse_blockers": [],
        "resolution_rows": [],
        "lines": [],
        "ambiguous_design_codes": {},
        "wfirma_products": {},
        "batch_lifecycle": {},
        "customer_resolution": {"found": False, "ambiguous": False, "candidates": []},
    }


def _minimal_auth() -> Dict[str, Any]:
    return {
        "batch_id": "B-P4-C3-01",
        "authority_available": True,
        "product_codes": set(),
        "rows_scanned": 0,
        "available_by_product_code": {},
        "invoice_by_product_code": {},
        "authority_error": None,
    }


def _minimal_customer_resolution() -> Dict[str, Any]:
    return {
        "found": False,
        "contractor_id": None,
        "ambiguous": False,
        "candidates": [],
        # Fields accessed in the early-exit path (lines 760-764 of routes_proforma)
        "normalized_name": "testclient",
        "resolved_wfirma_name": None,
        "wfirma_customer_id": None,
        "match_strategy": "none",
    }


# ── C1 boundary tests ──────────────────────────────────────────────────────────

class TestCpaPhase4C1Boundary:
    """C1: _build_preview must read sales rows through CPA, not directly from ddb."""

    # Patches that allow _build_preview to reach the CPA call without
    # exploding on missing batch data or customer master.
    _COMMON_PATCHES = [
        ("app.api.routes_proforma._check_proforma_export_prerequisites", [], True),
        ("app.api.routes_proforma._check_warehouse_readiness",           [], True),
        ("app.api.routes_proforma._derive_batch_lifecycle",
         {"status": "TRANSIT", "clearance_status": None}, True),
        ("app.services.design_product_bridge.populate_from_packing",
         {"ambiguous_design_codes": {}}, True),
    ]

    def _apply_common(self, patches):
        ctx = []
        for (target, retval, _) in self._COMMON_PATCHES:
            ctx.append(patch(target, return_value=retval))
        return ctx

    def test_c1_calls_cpa_not_ddb_directly(self):
        """_build_preview must call cpa.query_sales_resolution, not ddb.query_sales_to_wfirma."""
        cpa_calls: List[str] = []
        ddb_calls: List[str] = []

        def _cpa_fake(batch_id):
            cpa_calls.append(batch_id)
            return []  # empty → early exit, fine for this boundary check

        def _ddb_track(batch_id):
            ddb_calls.append(batch_id)
            return []  # track, don't raise — presence itself is the violation

        with patch("app.services.cpa_product_service.query_sales_resolution", _cpa_fake), \
             patch("app.services.document_db.query_sales_to_wfirma", _ddb_track), \
             patch("app.api.routes_proforma._check_proforma_export_prerequisites",
                   return_value=[]), \
             patch("app.api.routes_proforma._check_warehouse_readiness", return_value=[]), \
             patch("app.api.routes_proforma._derive_batch_lifecycle",
                   return_value={"status": "TRANSIT", "clearance_status": None}), \
             patch("app.services.design_product_bridge.populate_from_packing",
                   return_value={"ambiguous_design_codes": {}}), \
             patch("app.api.routes_proforma._resolve_customer",
                   return_value=_minimal_customer_resolution()):

            from app.api.routes_proforma import _build_preview
            _build_preview("B-P4-C1-01", "TestClient")

        assert len(cpa_calls) == 1, (
            f"cpa.query_sales_resolution must be called exactly once; got {cpa_calls!r}"
        )
        assert cpa_calls[0] == "B-P4-C1-01", (
            "batch_id must be forwarded to cpa.query_sales_resolution"
        )
        assert len(ddb_calls) == 0, (
            "ddb.query_sales_to_wfirma must NOT be called directly — "
            "Phase 4 CPA boundary violated"
        )

    def test_c1_output_shape_unchanged(self):
        """_build_preview returns the expected top-level keys when routed through CPA."""
        with patch("app.services.cpa_product_service.query_sales_resolution",
                   return_value=[]), \
             patch("app.api.routes_proforma._check_proforma_export_prerequisites",
                   return_value=[]), \
             patch("app.api.routes_proforma._check_warehouse_readiness", return_value=[]), \
             patch("app.api.routes_proforma._derive_batch_lifecycle",
                   return_value={"status": "TRANSIT", "clearance_status": None}), \
             patch("app.services.design_product_bridge.populate_from_packing",
                   return_value={"ambiguous_design_codes": {}}), \
             patch("app.api.routes_proforma._resolve_customer",
                   return_value=_minimal_customer_resolution()):

            from app.api.routes_proforma import _build_preview
            result = _build_preview("B-P4-SHAPE-01", "TestClient")

        # The early-exit path (no sales rows) still returns the canonical shape.
        # Note: `resolution_rows` only appears on the full path; `lines` and
        # `blocking_reasons` are present on both paths.
        for key in ("ok", "batch_id", "blocking_reasons", "lines", "batch_lifecycle"):
            assert key in result, (
                f"_build_preview result missing key {key!r} — output shape changed"
            )


# ── C3 boundary tests ──────────────────────────────────────────────────────────

class TestCpaPhase4C3Boundary:
    """C3: _derive_draft_readiness must read product authority through CPA."""

    def test_c3_calls_cpa_not_resolver_directly(self):
        """_derive_draft_readiness must call cpa.authority_snapshot, not resolver directly."""
        cpa_auth_calls: List[str] = []
        resolver_calls: List[str] = []

        def _cpa_auth_fake(batch_id, **kwargs):
            cpa_auth_calls.append(batch_id)
            return _minimal_auth()

        def _resolver_track(batch_id, **kwargs):
            resolver_calls.append(batch_id)
            return _minimal_auth()

        draft = _minimal_draft()

        # _derive_draft_readiness calls _build_preview internally (step 1).
        # Patch _build_preview so the C3 test focuses purely on step 5.
        with patch("app.services.cpa_product_service.authority_snapshot", _cpa_auth_fake), \
             patch("app.services.product_authority_resolver.resolve_batch_product_authority",
                   _resolver_track), \
             patch("app.api.routes_proforma._build_preview",
                   return_value=_minimal_preview()):
            try:
                from app.api.routes_proforma import _derive_draft_readiness
                _derive_draft_readiness(draft, intent="approve")
            except Exception:
                pass  # we only care that the boundary calls happened, not completion

        assert len(cpa_auth_calls) >= 1, (
            "cpa.authority_snapshot must be called by _derive_draft_readiness"
        )
        assert cpa_auth_calls[0] == draft.batch_id, (
            "batch_id must be forwarded to cpa.authority_snapshot"
        )
        assert len(resolver_calls) == 0, (
            "product_authority_resolver.resolve_batch_product_authority must NOT be called "
            "directly from _derive_draft_readiness — Phase 4 C3 boundary violated"
        )

    def test_c3_output_shape_unchanged(self):
        """_derive_draft_readiness returns the standard readiness dict through the CPA path."""
        draft = _minimal_draft()

        with patch("app.services.cpa_product_service.authority_snapshot",
                   return_value=_minimal_auth()), \
             patch("app.services.product_authority_resolver.resolve_batch_product_authority",
                   side_effect=AssertionError("direct resolver call — boundary violated")), \
             patch("app.api.routes_proforma._build_preview",
                   return_value=_minimal_preview()):

            from app.api.routes_proforma import _derive_draft_readiness
            result = _derive_draft_readiness(draft, intent="approve")

        for key in ("ready", "intent", "blockers", "blocking_reasons", "warnings"):
            assert key in result, (
                f"_derive_draft_readiness result missing key {key!r} — output shape changed"
            )
        assert result["intent"] == "approve"


# ── Delegation chain test ──────────────────────────────────────────────────────

class TestCpaQuerySalesResolutionDelegation:
    """query_sales_resolution() delegates to document_db.query_sales_to_wfirma."""

    def test_delegates_to_ddb(self):
        """cpa.query_sales_resolution calls ddb.query_sales_to_wfirma and returns its result."""
        rows = [{"batch_id": "B1", "client_name": "X", "wfirma_product_code": "EJL/001"}]

        with patch("app.services.document_db.query_sales_to_wfirma", return_value=rows):
            from app.services.cpa_product_service import query_sales_resolution
            result = query_sales_resolution("B1")

        assert result == rows

    def test_empty_batch_returns_empty_list(self):
        with patch("app.services.document_db.query_sales_to_wfirma", return_value=[]):
            from app.services.cpa_product_service import query_sales_resolution
            result = query_sales_resolution("B-EMPTY")

        assert result == []
