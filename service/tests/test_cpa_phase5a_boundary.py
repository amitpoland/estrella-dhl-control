"""test_cpa_phase5a_boundary.py — CPA Phase 5A: C6 + C7 boundary tests.

Verifies that after Phase 5A:
  C6: proforma_draft_sync._resolve_product_codes_for_batch reads the
      design→product_code map through cpa_product_service.design_to_product_codes,
      NOT directly from product_authority_resolver.design_to_product_codes.
  C7: sales_packing_matcher._design_to_product_codes_for_batch reads the map
      through cpa_product_service.design_to_product_codes,
      NOT directly from product_authority_resolver.design_to_product_codes.

Each boundary test verifies:
  (a) the CPA path IS called with the right batch_id
  (b) the old direct-import path is NOT called (boundary isolation)
  (c) the output shape/values are unchanged
"""
from __future__ import annotations

from typing import Dict, List
from unittest.mock import patch


# ── C6 boundary tests ──────────────────────────────────────────────────────────

class TestCpaPhase5C6Boundary:
    """C6: _resolve_product_codes_for_batch must read through CPA, not resolver."""

    def test_c6_calls_cpa_not_resolver_directly(self):
        """_resolve_product_codes_for_batch must call cpa.design_to_product_codes."""
        cpa_calls: List[str] = []
        resolver_calls: List[str] = []

        def _cpa_fake(batch_id, **kwargs):
            cpa_calls.append(batch_id)
            return {"PND": ["EJL/26-27/001"]}

        def _resolver_track(batch_id, **kwargs):
            resolver_calls.append(batch_id)
            return {"PND": ["EJL/26-27/001"]}

        with patch("app.services.cpa_product_service.design_to_product_codes", _cpa_fake), \
             patch("app.services.product_authority_resolver.design_to_product_codes",
                   _resolver_track):
            from app.services.proforma_draft_sync import _resolve_product_codes_for_batch
            result = _resolve_product_codes_for_batch("B-C6-BOUNDARY-01")

        assert len(cpa_calls) == 1, (
            f"cpa.design_to_product_codes must be called exactly once; got {cpa_calls!r}"
        )
        assert cpa_calls[0] == "B-C6-BOUNDARY-01", (
            "batch_id must be forwarded to cpa.design_to_product_codes"
        )
        assert len(resolver_calls) == 0, (
            "product_authority_resolver.design_to_product_codes must NOT be called "
            "directly — Phase 5A C6 boundary violated"
        )

    def test_c6_output_shape_unchanged(self):
        """_resolve_product_codes_for_batch returns exactly what CPA returns."""
        expected = {"PND": ["EJL/26-27/001", "EJL/26-27/002"], "RING-01": ["EJL/26-27/003"]}

        with patch("app.services.cpa_product_service.design_to_product_codes",
                   return_value=expected):
            from app.services.proforma_draft_sync import _resolve_product_codes_for_batch
            result = _resolve_product_codes_for_batch("B-C6-SHAPE-01")

        assert result == expected, (
            "_resolve_product_codes_for_batch must return the dict CPA returned unchanged"
        )

    def test_c6_empty_batch_id_short_circuits(self):
        """Empty batch_id returns {} without calling CPA."""
        cpa_calls: List[str] = []

        with patch("app.services.cpa_product_service.design_to_product_codes",
                   side_effect=lambda bid, **kw: cpa_calls.append(bid) or {}):
            from app.services.proforma_draft_sync import _resolve_product_codes_for_batch
            result = _resolve_product_codes_for_batch("")

        assert result == {}, "Empty batch_id must return empty dict"
        assert len(cpa_calls) == 0, "CPA must not be called for empty batch_id"

    def test_c6_cpa_exception_returns_empty(self):
        """If CPA raises, _resolve_product_codes_for_batch returns {} (non-fatal)."""
        with patch("app.services.cpa_product_service.design_to_product_codes",
                   side_effect=RuntimeError("packing_db unavailable")):
            from app.services.proforma_draft_sync import _resolve_product_codes_for_batch
            result = _resolve_product_codes_for_batch("B-C6-ERR-01")

        assert result == {}, "CPA exception must be swallowed and {} returned"


# ── C7 boundary tests ──────────────────────────────────────────────────────────

class TestCpaPhase5C7Boundary:
    """C7: _design_to_product_codes_for_batch must read through CPA, not resolver."""

    def test_c7_calls_cpa_not_resolver_directly(self):
        """_design_to_product_codes_for_batch must call cpa.design_to_product_codes."""
        cpa_calls: List[str] = []
        resolver_calls: List[str] = []

        def _cpa_fake(batch_id, **kwargs):
            cpa_calls.append(batch_id)
            return {"pnd": ["EJL/26-27/001"]}

        def _resolver_track(batch_id, **kwargs):
            resolver_calls.append(batch_id)
            return {"pnd": ["EJL/26-27/001"]}

        with patch("app.services.cpa_product_service.design_to_product_codes", _cpa_fake), \
             patch("app.services.product_authority_resolver.design_to_product_codes",
                   _resolver_track):
            from app.services.sales_packing_matcher import _design_to_product_codes_for_batch
            _design_to_product_codes_for_batch("B-C7-BOUNDARY-01")

        assert len(cpa_calls) == 1, (
            f"cpa.design_to_product_codes must be called exactly once; got {cpa_calls!r}"
        )
        assert cpa_calls[0] == "B-C7-BOUNDARY-01", (
            "batch_id must be forwarded to cpa.design_to_product_codes"
        )
        assert len(resolver_calls) == 0, (
            "product_authority_resolver.design_to_product_codes must NOT be called "
            "directly — Phase 5A C7 boundary violated"
        )

    def test_c7_output_normalises_keys(self):
        """_design_to_product_codes_for_batch normalises design_no keys (upper/trim)."""
        raw_from_cpa = {
            " Pnd ":  ["EJL/26-27/001"],
            "RING-01": ["EJL/26-27/003"],
        }
        with patch("app.services.cpa_product_service.design_to_product_codes",
                   return_value=raw_from_cpa):
            from app.services.sales_packing_matcher import _design_to_product_codes_for_batch
            result = _design_to_product_codes_for_batch("B-C7-SHAPE-01")

        # C7 normalises keys: uppercase + trim + collapse whitespace
        assert "PND" in result, (
            "design_no must be normalised to uppercase/trimmed key; got keys: "
            + str(list(result.keys()))
        )
        assert result["PND"] == ["EJL/26-27/001"]
        assert "RING-01" in result

    def test_c7_empty_batch_id_short_circuits(self):
        """Empty batch_id returns {} without calling CPA."""
        cpa_calls: List[str] = []

        with patch("app.services.cpa_product_service.design_to_product_codes",
                   side_effect=lambda bid, **kw: cpa_calls.append(bid) or {}):
            from app.services.sales_packing_matcher import _design_to_product_codes_for_batch
            result = _design_to_product_codes_for_batch("")

        assert result == {}
        assert len(cpa_calls) == 0

    def test_c7_cpa_exception_returns_empty(self):
        """If CPA raises, _design_to_product_codes_for_batch returns {} (non-fatal)."""
        with patch("app.services.cpa_product_service.design_to_product_codes",
                   side_effect=RuntimeError("packing_db unavailable")):
            from app.services.sales_packing_matcher import _design_to_product_codes_for_batch
            result = _design_to_product_codes_for_batch("B-C7-ERR-01")

        assert result == {}


# ── CPA wrapper delegation test ───────────────────────────────────────────────

class TestCpaDesignToProductCodesDelegation:
    """cpa.design_to_product_codes() delegates to product_authority_resolver."""

    def test_delegates_to_resolver(self):
        """cpa.design_to_product_codes calls resolver and returns its result."""
        expected = {"PND": ["EJL/26-27/001"], "RING-X": ["EJL/26-27/099"]}

        with patch("app.services.product_authority_resolver.design_to_product_codes",
                   return_value=expected):
            from app.services.cpa_product_service import design_to_product_codes
            result = design_to_product_codes("B-DELG-01")

        assert result == expected

    def test_empty_batch_delegates_and_returns_empty(self):
        """Empty batch_id is forwarded to resolver; result is returned as-is."""
        with patch("app.services.product_authority_resolver.design_to_product_codes",
                   return_value={}):
            from app.services.cpa_product_service import design_to_product_codes
            result = design_to_product_codes("B-EMPTY")

        assert result == {}

    def test_packing_rows_kwarg_forwarded(self):
        """packing_rows kwarg is forwarded to the resolver."""
        received_kwargs: dict = {}

        def _capture(batch_id, **kwargs):
            received_kwargs.update(kwargs)
            return {}

        rows = [{"product_code": "EJL/26-27/001", "design_no": "PND"}]
        with patch("app.services.product_authority_resolver.design_to_product_codes",
                   side_effect=_capture):
            from app.services.cpa_product_service import design_to_product_codes
            design_to_product_codes("B-KW-01", packing_rows=rows)

        assert received_kwargs.get("packing_rows") == rows, (
            "packing_rows kwarg must be forwarded to the resolver"
        )
