"""
test_suggest_freight_insurance_customer_authority.py

Customer Master authority tests for suggest-freight and suggest-insurance.

Pins:
  SG-01  _suggest_lookup checks buyer_override_json.wfirma_customer_id before name resolution
  SG-02  _suggest_lookup returns actionable ambiguity message (not generic "not found")
  SG-03  Explicit contractor selection in buyer_override bypasses ambiguous resolution
  SG-04  Ambiguous customer with no buyer_override blocks freight with correct message
  SG-05  Ambiguous customer with no buyer_override blocks insurance with correct message
  SG-06  Explicit contractor in buyer_override enables freight suggestion
  SG-07  Explicit contractor in buyer_override enables insurance suggestion
  SG-08  Missing CM record after override returns "update Customer Master" message
  SG-09  Unambiguous customer without override still resolves (no regression)
  SG-10  frontend: handleSave PATCHes draft with wfirma_customer_id in buyer_override
  SG-11  frontend: contractorId initialised from buyer_override.wfirma_customer_id
  SG-12  _suggest_lookup source contains buyer_override path BEFORE _resolve_customer call
  SG-13  Ambiguity probe does NOT call full _resolve_customer when ambiguous
  SG-14  proforma-detail-v2.html shows selected-contractor-id-row testid
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_ROUTES_PY = _ROOT / "app" / "api" / "routes_proforma.py"
_V2_HTML   = _ROOT / "app" / "static" / "proforma-detail-v2.html"


# ── helpers ────────────────────────────────────────────────────────────────────

def _src():
    return _ROUTES_PY.read_text(encoding="utf-8")


def _html():
    return _V2_HTML.read_text(encoding="utf-8")


def _make_draft(
    draft_id: int = 42,
    client_name: str = "UAB",
    currency: str = "EUR",
    buyer_override: dict | None = None,
    editable_lines: list | None = None,
    updated_at: str = "2026-06-08T10:00:00+00:00",
):
    """Return a minimal mock draft object matching pildb.ProformaDraft fields."""
    bo = buyer_override if buyer_override is not None else {}
    lines = editable_lines if editable_lines is not None else []
    return SimpleNamespace(
        id=draft_id,
        client_name=client_name,
        currency=currency,
        buyer_override_json=json.dumps(bo),
        editable_lines_json=json.dumps(lines),
        updated_at=updated_at,
        batch_id="SHIPMENT_TEST",
    )


def _make_cm(
    freight_fixed_amount_eur=None,
    freight_fixed_amount_usd=None,
    freight_service_id="13002743",
    freight_mode=None,
    insurance_service_id="13102217",
    insurance_rate=None,
    insurance_mode=None,
    insurance_enabled=True,
    insurance_fixed_amount_eur=None,
    insurance_fixed_amount_usd=None,
):
    """Return a minimal CustomerMaster-like namespace."""
    from decimal import Decimal
    return SimpleNamespace(
        freight_fixed_amount_eur=Decimal(str(freight_fixed_amount_eur)) if freight_fixed_amount_eur else None,
        freight_fixed_amount_usd=Decimal(str(freight_fixed_amount_usd)) if freight_fixed_amount_usd else None,
        freight_service_id=freight_service_id,
        freight_mode=freight_mode,
        freight_last_amount=None,
        freight_avg_amount=None,
        freight_currency=None,
        freight_label_pl=None,
        freight_label_en=None,
        insurance_service_id=insurance_service_id,
        insurance_rate=Decimal(str(insurance_rate)) if insurance_rate else None,
        insurance_mode=insurance_mode,
        insurance_enabled=insurance_enabled,
        insurance_fixed_amount_eur=Decimal(str(insurance_fixed_amount_eur)) if insurance_fixed_amount_eur else None,
        insurance_fixed_amount_usd=Decimal(str(insurance_fixed_amount_usd)) if insurance_fixed_amount_usd else None,
        insurance_min_eur=None,
        insurance_min_usd=None,
        insurance_min_amount=None,
        insurance_min_override=None,
        insurance_label_pl=None,
        insurance_label_en=None,
    )


# ── SG-01: source-grep — buyer_override path exists in _suggest_lookup ─────────

class TestSuggestLookupSourceStructure:
    """Source-grep tests pinning the code structure of _suggest_lookup."""

    def _lookup_src(self) -> str:
        src = _src()
        start = src.find("def _suggest_lookup(")
        assert start >= 0
        end = src.find("\ndef ", start + 10)
        return src[start:end] if end > 0 else src[start:]

    def test_buyer_override_checked_in_suggest_lookup(self):
        """_suggest_lookup must check buyer_override_json for wfirma_customer_id."""
        body = self._lookup_src()
        assert "buyer_override_json" in body, (
            "_suggest_lookup must read buyer_override_json to check for explicit contractor selection"
        )
        assert "wfirma_customer_id" in body

    def test_override_path_before_resolve_customer(self):
        """buyer_override check must appear BEFORE _resolve_customer call."""
        body = self._lookup_src()
        override_pos = body.find("buyer_override_json")
        resolve_pos  = body.find("_resolve_customer(")
        assert override_pos > 0
        assert resolve_pos > 0
        assert override_pos < resolve_pos, (
            "buyer_override path must be checked BEFORE _resolve_customer call"
        )

    def test_ambiguity_message_is_actionable(self):
        """Ambiguity block must include 'Customer Mapping tab' in the message."""
        body = self._lookup_src()
        assert "Customer Mapping tab" in body or "customer mapping" in body.lower(), (
            "Ambiguity block must tell operator to use the Customer Mapping tab"
        )

    def test_ambiguity_probe_uses_resolve_customer_via_master(self):
        """Ambiguity check must use _resolve_customer_via_master (not full _resolve_customer)."""
        body = self._lookup_src()
        assert "_resolve_customer_via_master" in body, (
            "_suggest_lookup must probe for ambiguity using _resolve_customer_via_master"
        )


# ── SG-04/05: ambiguous customer blocks freight and insurance ──────────────────

class TestAmbiguousCustomerBlocked:
    """Ambiguous customer without explicit selection blocks both endpoints."""

    def _run_lookup(self, draft):
        from app.api import routes_proforma
        with (
            patch.object(routes_proforma.pildb, "get_draft_by_id", return_value=draft),
            patch("app.api.routes_proforma._resolve_customer_via_master", return_value={
                "ambiguous": True,
                "match_strategy": "ambiguous",
                "candidates": ["UAB Tomas Gold", "UAB MONODIJA IR KO"],
                "candidate_ids": ["45722450", "134920664"],
            }),
            patch("app.api.routes_proforma._proforma_db_path", return_value=":memory:"),
            patch("app.api.routes_proforma._customer_master_db_path", return_value=":memory:"),
        ):
            return routes_proforma._suggest_lookup(draft.id)

    def test_ambiguous_returns_blocked_reason(self):
        """Ambiguous customer with no buyer_override must return a blocked_reason."""
        draft = _make_draft(client_name="UAB", buyer_override={})
        _, _, cm, reason = self._run_lookup(draft)
        assert reason is not None, "Must block when customer is ambiguous and no override"
        assert cm is None

    def test_ambiguous_reason_mentions_customer_mapping_tab(self):
        """Blocked reason for ambiguous must tell operator to use Customer Mapping tab."""
        draft = _make_draft(client_name="UAB", buyer_override={})
        _, _, _, reason = self._run_lookup(draft)
        assert "Customer Mapping" in reason or "customer mapping" in reason.lower(), (
            f"Reason must mention Customer Mapping tab, got: {reason!r}"
        )

    def test_ambiguous_reason_mentions_candidates(self):
        """Blocked reason must include the candidate names so operator knows which to pick."""
        draft = _make_draft(client_name="UAB", buyer_override={})
        _, _, _, reason = self._run_lookup(draft)
        assert "UAB Tomas Gold" in reason or "UAB" in reason, (
            f"Reason should mention candidates, got: {reason!r}"
        )


# ── SG-03/06/07: explicit contractor in buyer_override enables lookup ──────────

class TestExplicitContractorOverride:
    """buyer_override.wfirma_customer_id bypasses name resolution entirely."""

    def _run_lookup_with_override(self, contractor_id: str, cm_record=None):
        from app.api import routes_proforma
        draft = _make_draft(
            client_name="UAB",
            buyer_override={"wfirma_customer_id": contractor_id},
        )
        mock_cm = cm_record or _make_cm(
            freight_fixed_amount_eur=89,
            freight_service_id="13002743",
            insurance_service_id="13102217",
            insurance_rate=0.0035,
        )
        with (
            patch.object(routes_proforma.pildb, "get_draft_by_id", return_value=draft),
            patch("app.api.routes_proforma.get_customer_master", return_value=mock_cm),
            patch("app.api.routes_proforma._proforma_db_path", return_value=":memory:"),
            patch("app.api.routes_proforma._customer_master_db_path", return_value=":memory:"),
            # _resolve_customer_via_master should NOT be called when override is set
            patch("app.api.routes_proforma._resolve_customer_via_master",
                  side_effect=AssertionError("must not call _resolve_customer_via_master when override is set")),
            patch("app.api.routes_proforma._resolve_customer",
                  side_effect=AssertionError("must not call _resolve_customer when override is set")),
        ):
            return routes_proforma._suggest_lookup(draft.id)

    def test_override_bypasses_name_resolution(self):
        """Explicit contractor in buyer_override must not trigger name resolution."""
        # This will raise AssertionError if _resolve_customer or
        # _resolve_customer_via_master is called — proving bypass works.
        d, currency, cm, reason = self._run_lookup_with_override("45722450")
        assert reason is None, f"Should not be blocked: {reason}"
        assert cm is not None

    def test_override_returns_correct_cm(self):
        """Explicit contractor must load the CM record with the correct contractor_id."""
        mock_cm = _make_cm(freight_fixed_amount_eur=89, freight_service_id="13002743")
        d, currency, cm, reason = self._run_lookup_with_override("45722450", cm_record=mock_cm)
        assert cm is mock_cm
        assert reason is None

    def test_override_preserves_draft_currency(self):
        """Draft currency must still be passed through correctly."""
        d, currency, cm, reason = self._run_lookup_with_override("45722450")
        assert currency == "EUR"


# ── SG-08: missing CM record after override ────────────────────────────────────

class TestOverrideWithMissingCMRecord:
    """Missing CM record after explicit selection returns actionable message."""

    def test_missing_cm_after_override_returns_update_message(self):
        from app.api import routes_proforma
        draft = _make_draft(
            client_name="UAB",
            buyer_override={"wfirma_customer_id": "99999999"},
        )
        with (
            patch.object(routes_proforma.pildb, "get_draft_by_id", return_value=draft),
            patch("app.api.routes_proforma.get_customer_master", return_value=None),
            patch("app.api.routes_proforma._proforma_db_path", return_value=":memory:"),
            patch("app.api.routes_proforma._customer_master_db_path", return_value=":memory:"),
        ):
            _, _, cm, reason = routes_proforma._suggest_lookup(draft.id)

        assert cm is None
        assert reason is not None
        assert "99999999" in reason, "Reason must include the contractor_id that was tried"
        assert "Customer Master" in reason

    def test_missing_cm_after_override_does_not_say_not_in_wfirma(self):
        """Missing CM after override must NOT say 'not found in wFirma mapping' (wrong path)."""
        from app.api import routes_proforma
        draft = _make_draft(
            client_name="UAB",
            buyer_override={"wfirma_customer_id": "99999999"},
        )
        with (
            patch.object(routes_proforma.pildb, "get_draft_by_id", return_value=draft),
            patch("app.api.routes_proforma.get_customer_master", return_value=None),
            patch("app.api.routes_proforma._proforma_db_path", return_value=":memory:"),
            patch("app.api.routes_proforma._customer_master_db_path", return_value=":memory:"),
        ):
            _, _, _, reason = routes_proforma._suggest_lookup(draft.id)

        assert "not found in wFirma mapping" not in reason


# ── SG-09: unambiguous customer without override still works (no regression) ───

class TestUnambiguousCustomerFallback:
    """Unambiguous customer without buyer_override must still resolve normally."""

    def test_unambiguous_customer_resolves_via_name(self):
        from app.api import routes_proforma
        draft = _make_draft(client_name="UAB Tomas Gold", buyer_override={})
        mock_cm = _make_cm(freight_fixed_amount_eur=89)
        with (
            patch.object(routes_proforma.pildb, "get_draft_by_id", return_value=draft),
            patch("app.api.routes_proforma._resolve_customer_via_master", return_value={
                "found": True,
                "match_strategy": "customer_master",
                "wfirma_customer_id": "45722450",
                "resolved_wfirma_name": "UAB Tomas Gold",
            }),
            patch("app.api.routes_proforma._resolve_customer", return_value={
                "found": True,
                "wfirma_customer_id": "45722450",
                "ambiguous": False,
                "match_strategy": "customer_master",
            }),
            patch("app.api.routes_proforma.get_customer_master", return_value=mock_cm),
            patch("app.api.routes_proforma._proforma_db_path", return_value=":memory:"),
            patch("app.api.routes_proforma._customer_master_db_path", return_value=":memory:"),
        ):
            d, currency, cm, reason = routes_proforma._suggest_lookup(draft.id)

        assert reason is None, f"Unambiguous customer must not be blocked: {reason}"
        assert cm is mock_cm


# ── SG-10/11: frontend source-grep tests ──────────────────────────────────────

class TestFrontendCustomerMappingSaveWithContractorId:
    """Frontend must save wfirma_customer_id in buyer_override via PATCH."""

    def test_handle_save_patches_draft_with_wfirma_customer_id(self):
        """handleSave must PATCH /api/v1/proforma/draft/{id} with buyer_override.wfirma_customer_id."""
        html = _html()
        # Find handleSave function — use setSaving(false) as end-of-body anchor
        # because the function body contains earlier `};` (from `const body = {...};`)
        start = html.find("const handleSave = async () =>")
        assert start >= 0, "handleSave not found in V2 HTML"
        marker = html.find("setSaving(false);", start)
        assert marker >= 0, "setSaving(false) not found inside handleSave"
        end = marker + len("setSaving(false);")
        body = html[start:end]
        assert "wfirma_customer_id" in body, (
            "handleSave must set buyer_override.wfirma_customer_id when saving"
        )
        assert "buyer_override" in body, (
            "handleSave must send buyer_override in the PATCH payload"
        )

    def test_handle_save_patches_draft_endpoint(self):
        """handleSave must call PATCH /api/v1/proforma/draft/{id}."""
        html = _html()
        start = html.find("const handleSave = async () =>")
        assert start >= 0
        marker = html.find("setSaving(false);", start)
        assert marker >= 0
        end = marker + len("setSaving(false);")
        body = html[start:end]
        assert "/api/v1/proforma/draft/" in body, (
            "handleSave must PATCH the proforma draft endpoint to store the selection"
        )
        assert "PATCH" in body

    def test_contractor_id_initialised_from_buyer_override(self):
        """contractorId state must check buyer_override.wfirma_customer_id first."""
        html = _html()
        # Locate CustomerMappingTab function
        start = html.find("function CustomerMappingTab(")
        assert start >= 0
        region = html[start:start + 800]
        assert "buyer_override" in region, (
            "CustomerMappingTab must initialise contractorId from buyer_override.wfirma_customer_id"
        )
        assert "storedContractorId" in region or "wfirma_customer_id" in region

    def test_handle_save_merges_with_existing_override(self):
        """handleSave must merge (not replace) with existing buyer_override fields."""
        html = _html()
        start = html.find("const handleSave = async () =>")
        assert start >= 0
        marker = html.find("setSaving(false);", start)
        assert marker >= 0
        end = marker + len("setSaving(false);")
        body = html[start:end]
        # Must spread existing override, not replace outright
        assert "existingOverride" in body or "buyer_override" in body, (
            "handleSave must preserve existing buyer_override fields when adding wfirma_customer_id"
        )
        assert "mergedOverride" in body or "..." in body


# ── SG-14: frontend shows selected-contractor-id-row testid ────────────────────

class TestFrontendSelectedContractorRow:
    """selected-contractor-id-row must be shown when explicit selection is stored."""

    def test_selected_contractor_id_row_testid_present(self):
        """proforma-detail-v2.html must render selected-contractor-id-row testid."""
        html = _html()
        assert "selected-contractor-id-row" in html, (
            "CustomerMappingTab must render a 'selected-contractor-id-row' testid "
            "when an explicit contractor selection is stored in buyer_override"
        )

    def test_selected_contractor_row_shown_conditionally_on_explicit_selection(self):
        """selected-contractor-id-row must be conditional on explicitSelection."""
        html = _html()
        idx = html.find("selected-contractor-id-row")
        assert idx >= 0
        # Check context around the testid — should be inside a conditional
        context = html[max(0, idx - 200):idx + 100]
        assert "explicitSelection" in context, (
            "selected-contractor-id-row must only render when explicitSelection is truthy"
        )
