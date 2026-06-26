"""test_cpa_phase5b_boundary.py — CPA Phase 5B: C4 boundary tests.

Verifies that after Phase 5B:
  C4: routes_proforma._reconcile_billed_ambiguity and
      routes_proforma._analyze_product_code_billing are re-exported through
      cpa_product_service, NOT directly from product_authority_resolver.

Each boundary test verifies:
  (a) the module-level name in routes_proforma IS the CPA wrapper object
  (b) it is NOT the resolver function directly
  (c) CPA wrappers delegate to the resolver with arguments forwarded unchanged
  (d) return shape is identical (pure delegation)

Note: routes_proforma re-exports at module level (not a lazy import), so the
boundary is tested via object identity rather than mock-based call tracking.
"""
from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import patch


# ── C4 boundary: identity checks ─────────────────────────────────────────────

class TestCpaPhase5C4Boundary:
    """C4: routes_proforma private names must resolve through CPA, not resolver."""

    def test_c4_rba_bound_to_cpa_not_resolver(self):
        """_reconcile_billed_ambiguity in routes_proforma must be cpa's wrapper."""
        from app.api.routes_proforma import _reconcile_billed_ambiguity
        from app.services import cpa_product_service as cpa
        from app.services import product_authority_resolver as par

        assert _reconcile_billed_ambiguity is cpa.reconcile_billed_ambiguity, (
            "routes_proforma._reconcile_billed_ambiguity must be bound to "
            "cpa_product_service.reconcile_billed_ambiguity — C4 boundary violated"
        )
        assert _reconcile_billed_ambiguity is not par.reconcile_billed_ambiguity, (
            "routes_proforma._reconcile_billed_ambiguity must NOT be bound directly "
            "to product_authority_resolver.reconcile_billed_ambiguity"
        )

    def test_c4_apbc_bound_to_cpa_not_resolver(self):
        """_analyze_product_code_billing in routes_proforma must be cpa's wrapper."""
        from app.api.routes_proforma import _analyze_product_code_billing
        from app.services import cpa_product_service as cpa
        from app.services import product_authority_resolver as par

        assert _analyze_product_code_billing is cpa.analyze_product_code_billing, (
            "routes_proforma._analyze_product_code_billing must be bound to "
            "cpa_product_service.analyze_product_code_billing — C4 boundary violated"
        )
        assert _analyze_product_code_billing is not par.analyze_product_code_billing, (
            "routes_proforma._analyze_product_code_billing must NOT be bound directly "
            "to product_authority_resolver.analyze_product_code_billing"
        )


# ── CPA wrapper: delegation tests ────────────────────────────────────────────

class TestCpaReconcileBilledAmbiguityDelegation:
    """cpa.reconcile_billed_ambiguity() delegates to product_authority_resolver."""

    def test_delegates_with_correct_args(self):
        """Arguments forwarded exactly; return value returned unchanged."""
        received: List[tuple] = []

        def _track(ambig, lines):
            received.append((ambig, lines))
            return {"genuinely_ambiguous": {}, "resolved": {"PND": ["EJL/1"]}, "not_billed": []}

        ambig = {"PND": ["EJL/1", "EJL/2"]}
        lines = [{"design_no": "PND", "product_code": "EJL/1"}]

        with patch("app.services.product_authority_resolver.reconcile_billed_ambiguity", _track):
            from app.services.cpa_product_service import reconcile_billed_ambiguity
            result = reconcile_billed_ambiguity(ambig, lines)

        assert len(received) == 1, "resolver must be called exactly once"
        assert received[0][0] is ambig, "ambiguous_design_codes forwarded by reference"
        assert received[0][1] is lines, "draft_lines forwarded by reference"
        assert result == {"genuinely_ambiguous": {}, "resolved": {"PND": ["EJL/1"]}, "not_billed": []}

    def test_empty_inputs_forwarded(self):
        """Empty inputs are forwarded; resolver's result returned as-is."""
        with patch("app.services.product_authority_resolver.reconcile_billed_ambiguity",
                   return_value={"genuinely_ambiguous": {}, "resolved": {}, "not_billed": []}):
            from app.services.cpa_product_service import reconcile_billed_ambiguity
            result = reconcile_billed_ambiguity({}, [])

        assert result == {"genuinely_ambiguous": {}, "resolved": {}, "not_billed": []}

    def test_output_shape_matches_resolver_contract(self):
        """Return value has the three required keys."""
        with patch("app.services.product_authority_resolver.reconcile_billed_ambiguity",
                   return_value={"genuinely_ambiguous": {"X": ["A"]}, "resolved": {}, "not_billed": ["Y"]}):
            from app.services.cpa_product_service import reconcile_billed_ambiguity
            result = reconcile_billed_ambiguity({"X": ["A"], "Y": ["B"]}, [{"design_no": "X", "product_code": "Z"}])

        assert "genuinely_ambiguous" in result
        assert "resolved" in result
        assert "not_billed" in result


class TestCpaAnalyzeProductCodeBillingDelegation:
    """cpa.analyze_product_code_billing() delegates to product_authority_resolver."""

    def test_delegates_with_correct_positional_args(self):
        """draft_lines and available_by_pc forwarded positionally."""
        received: List[tuple] = []

        def _track(lines, avail, inv_by_pc=None):
            received.append((lines, avail, inv_by_pc))
            return []

        lines = [{"product_code": "EJL/1", "design_no": "PND", "qty": 2}]
        avail = {"EJL/1": 5.0}

        with patch("app.services.product_authority_resolver.analyze_product_code_billing", _track):
            from app.services.cpa_product_service import analyze_product_code_billing
            result = analyze_product_code_billing(lines, avail)

        assert len(received) == 1
        assert received[0][0] is lines
        assert received[0][1] is avail
        assert received[0][2] is None  # invoice_by_pc defaults to None
        assert result == []

    def test_invoice_by_pc_kwarg_forwarded(self):
        """Optional invoice_by_pc is forwarded to the resolver."""
        received: List[Any] = []

        def _track(lines, avail, inv_by_pc=None):
            received.append(inv_by_pc)
            return []

        inv = {"EJL/1": "EJL/26-27/299"}
        with patch("app.services.product_authority_resolver.analyze_product_code_billing", _track):
            from app.services.cpa_product_service import analyze_product_code_billing
            analyze_product_code_billing([], {}, inv)

        assert received[0] is inv, "invoice_by_pc must be forwarded to the resolver"

    def test_output_list_returned_unchanged(self):
        """Return value from resolver is returned as-is."""
        expected = [{"product_code": "EJL/1", "over_billed": True, "billed_qty": 3, "available_qty": 1}]
        with patch("app.services.product_authority_resolver.analyze_product_code_billing",
                   return_value=expected):
            from app.services.cpa_product_service import analyze_product_code_billing
            result = analyze_product_code_billing([], {})

        assert result is expected


# ── Backward-compatibility: existing consumer tests still work ────────────────

class TestC4BackwardCompatibility:
    """Ensure existing tests that import from routes_proforma still work."""

    def test_rba_via_routes_proforma_still_callable(self):
        """_reconcile_billed_ambiguity imported from routes_proforma is callable."""
        from app.api.routes_proforma import _reconcile_billed_ambiguity
        result = _reconcile_billed_ambiguity(
            {"PND": ["EJL/26-27/001", "EJL/26-27/002"]},
            [{"design_no": "PND", "product_code": "EJL/26-27/001"}],
        )
        assert "genuinely_ambiguous" in result
        assert "resolved" in result
        assert "not_billed" in result

    def test_apbc_via_routes_proforma_still_callable(self):
        """_analyze_product_code_billing imported from routes_proforma is callable."""
        from app.api.routes_proforma import _analyze_product_code_billing
        result = _analyze_product_code_billing(
            [{"product_code": "EJL/1", "design_no": "PND", "qty": 3}],
            {"EJL/1": 2.0},
        )
        assert isinstance(result, list)
        assert result[0]["over_billed"] is True
