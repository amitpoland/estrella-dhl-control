"""
test_freight_authority_blocker_repair.py

Freight suggestion authority + blocker repair path (campaign 2026-06-21).

Customer Master is the SINGLE freight authority. When the RESOLVED customer
record is missing a freight field, a blocked freight suggestion must carry the
exact record (contractor_id + name), the missing field, and a deep-link to edit
THAT record — so the operator repairs the authority in Customer Master and
retries, with NO draft-level override and NO guessed fallback. A resolution
FAILURE (no record, or ambiguous) must NOT synthesise a record identity — the
wrong/owner-less record is never silently used.

Pins:
  FA-01  pick_freight reports the exact missing field key (usd / eur / service_id)
  FA-02  pick_freight VALID path returns ok + amount (no regression)
  FA-03  _freight_authority_block: resolved cm → identity + missing_field + deep-link
  FA-04  _freight_authority_block: cm is None → resolved=False, no identity
  FA-05  /suggest-freight blocked (missing USD amount) → freight_authority + deep-link
  FA-06  /suggest-freight blocked (missing service_id) → missing_field=freight_service_id
  FA-07  /suggest-freight valid → ok=True, no block (no regression)
  FA-08  /suggest-freight resolution failure (cm None) → NO resolved identity (not silently used)
  FA-09  /suggest-combined blocked freight → freight entry carries the deep-link block
  FA-10  edit_url deep-links the EXACT contractor_id (V2 Customer Master authority)
  FA-11  V1 shipment-detail.html blocker deep-links contractor_id + names only missing field
  FA-12  V2 proforma-detail.jsx blocker has edit deep-link + retry; read-only otherwise
  FA-13  V2 SPA (master-page.jsx) deep-link entry point honours ?entity/?contractor_id=
  FA-14  no hardcoded customer name in the freight authority repair path

Wave 8 (frontend-authority-inspector RISK-1): the freight-edit deep-link was
repointed from the DEPRECATED /dashboard/customer-master-v2.html (retired
2026-06-30) to the V2 Customer Master AUTHORITY — /v2/master?entity=clients&
contractor_id=<id>, which opens the record in ClientDetailModal.
"""
from __future__ import annotations

import json
import sys
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_ROUTES_PY  = _ROOT / "app" / "api" / "routes_proforma.py"
_V1_HTML    = _ROOT / "app" / "static" / "shipment-detail.html"
_V2_JSX     = _ROOT / "app" / "static" / "v2" / "proforma-detail.jsx"
_MASTER_JSX = _ROOT / "app" / "static" / "v2" / "master-page.jsx"

# The V2 Customer Master authority deep-link (replaces the deprecated
# /dashboard/customer-master-v2.html target — Wave 8 RISK-1 repoint).
def _expect_edit_url(cid: str) -> str:
    return f"/v2/master?entity=clients&contractor_id={cid}"


# ── helpers ─────────────────────────────────────────────────────────────────

def _cm(usd=None, eur=None, service_id="13002743",
        contractor_id="91254191", name="Acme Diamonds"):
    """A CustomerMaster-like record. Defaults mirror the real-world failure:
    freight_service_id SET, freight_fixed_amount_usd MISSING."""
    return SimpleNamespace(
        bill_to_contractor_id=contractor_id,
        bill_to_name=name,
        freight_service_id=service_id,
        freight_fixed_amount_usd=Decimal(str(usd)) if usd is not None else None,
        freight_fixed_amount_eur=Decimal(str(eur)) if eur is not None else None,
        freight_last_amount=None,
        freight_mode=None,
        freight_label_en=None,
        freight_label_pl=None,
        # insurance attrs so the combined endpoint can short-circuit cleanly
        insurance_enabled=False,
        insurance_service_id="13102217",
    )


def _draft(draft_id=42, currency="USD"):
    return SimpleNamespace(
        id=draft_id, currency=currency,
        service_charges_json="[]", editable_lines_json="[]",
    )


def _call(fn, draft_id, *, draft, currency, cm, reason):
    """Invoke an endpoint with _suggest_lookup patched, return parsed JSON."""
    from app.api import routes_proforma
    with patch.object(routes_proforma, "_suggest_lookup",
                      return_value=(draft, currency, cm, reason)):
        resp = fn(draft_id)
    return json.loads(resp.body)


# ── FA-01/02: pick_freight reports the missing field ─────────────────────────

class TestPickFreightFieldKey:
    def test_missing_usd_amount_reports_field(self):
        from app.services.customer_master import pick_freight
        r = pick_freight(_cm(usd=None), "USD")
        assert r["ok"] is False and r["blocked"] is True
        assert r["field"] == "freight_fixed_amount_usd"

    def test_missing_eur_amount_reports_field(self):
        from app.services.customer_master import pick_freight
        r = pick_freight(_cm(eur=None), "EUR")
        assert r["field"] == "freight_fixed_amount_eur"

    def test_missing_service_id_reports_field(self):
        from app.services.customer_master import pick_freight
        r = pick_freight(_cm(usd=120, service_id=None), "USD")
        assert r["field"] == "freight_service_id"

    def test_valid_usd_freight_suggests(self):
        from app.services.customer_master import pick_freight
        r = pick_freight(_cm(usd=83), "USD")
        assert r["ok"] is True
        assert r["amount"] == Decimal("83")
        assert r["wfirma_service_id"] == "13002743"
        assert "field" not in r  # field only present on the blocked path


# ── FA-03/04: _freight_authority_block structure ─────────────────────────────

class TestFreightAuthorityBlock:
    def test_resolved_record_carries_identity_and_deeplink(self):
        from app.api.routes_proforma import _freight_authority_block, pick_freight
        cm = _cm(usd=None, contractor_id="91254191", name="Acme Diamonds")
        block = _freight_authority_block(cm, pick_freight(cm, "USD"))
        assert block["resolved"] is True
        assert block["contractor_id"] == "91254191"
        assert block["bill_to_name"] == "Acme Diamonds"
        assert block["missing_field"] == "freight_fixed_amount_usd"
        assert block["edit_url"] == _expect_edit_url("91254191")

    def test_unresolved_record_has_no_identity(self):
        from app.api.routes_proforma import _freight_authority_block
        block = _freight_authority_block(None, {"field": "freight_fixed_amount_usd"})
        assert block == {"resolved": False}
        assert "contractor_id" not in block
        assert "edit_url" not in block

    def test_edit_url_url_encodes_contractor_id(self):
        # contractor ids are numeric in practice; guard against odd ids regardless
        from app.api.routes_proforma import _freight_authority_block
        cm = _cm(usd=None, contractor_id="ab/cd 12")
        block = _freight_authority_block(cm, {"field": "freight_fixed_amount_usd"})
        assert "ab%2Fcd%2012" in block["edit_url"]


# ── FA-05..08: /suggest-freight endpoint ─────────────────────────────────────

class TestSuggestFreightEndpoint:
    def test_missing_usd_amount_blocks_with_deeplink(self):
        from app.api.routes_proforma import suggest_freight_endpoint
        body = _call(suggest_freight_endpoint, 42,
                     draft=_draft(), currency="USD",
                     cm=_cm(usd=None, contractor_id="91254191", name="Acme Diamonds"),
                     reason=None)
        assert body["ok"] is False and body["blocked"] is True
        assert "freight_fixed_amount_usd is not set" in body["reason"]
        fa = body["freight_authority"]
        assert fa["resolved"] is True
        assert fa["contractor_id"] == "91254191"
        assert fa["missing_field"] == "freight_fixed_amount_usd"
        assert fa["edit_url"] == _expect_edit_url("91254191")

    def test_missing_service_id_blocks_with_field(self):
        from app.api.routes_proforma import suggest_freight_endpoint
        body = _call(suggest_freight_endpoint, 42,
                     draft=_draft(), currency="USD",
                     cm=_cm(usd=120, service_id=None), reason=None)
        assert body["ok"] is False
        assert body["freight_authority"]["missing_field"] == "freight_service_id"

    def test_missing_eur_amount_blocks_with_deeplink(self):
        """EUR draft path is functionally distinct from USD — pin it at the
        endpoint level (not just the pick_freight unit)."""
        from app.api.routes_proforma import suggest_freight_endpoint
        body = _call(suggest_freight_endpoint, 42,
                     draft=_draft(currency="EUR"), currency="EUR",
                     cm=_cm(eur=None, contractor_id="55"), reason=None)
        assert body["ok"] is False
        assert "freight_fixed_amount_eur is not set" in body["reason"]
        fa = body["freight_authority"]
        assert fa["resolved"] is True
        assert fa["missing_field"] == "freight_fixed_amount_eur"
        assert fa["edit_url"] == _expect_edit_url("55")

    def test_valid_freight_suggests_no_block(self):
        from app.api.routes_proforma import suggest_freight_endpoint
        body = _call(suggest_freight_endpoint, 42,
                     draft=_draft(), currency="USD",
                     cm=_cm(usd=83), reason=None)
        assert body["ok"] is True
        assert body["suggestion"]["amount"] == "83"
        assert "freight_authority" not in body  # no repair block on success

    def test_resolution_failure_does_not_synthesise_identity(self):
        """When no record resolves (cm None), the blocker must NOT claim a
        resolved record — the wrong/owner-less record is never silently used."""
        from app.api.routes_proforma import suggest_freight_endpoint
        body = _call(suggest_freight_endpoint, 42,
                     draft=_draft(), currency="USD", cm=None,
                     reason="customer 'X' not found in wFirma mapping — "
                            "cannot look up customer master")
        assert body["ok"] is False and body["blocked"] is True
        # no resolved identity / deep-link on the resolution-failure path
        assert not body.get("freight_authority", {}).get("resolved")
        assert "contractor_id" not in body.get("freight_authority", {})


# ── FA-09: combined endpoint carries the freight repair block ────────────────

class TestSuggestCombinedEndpoint:
    def test_blocked_freight_entry_carries_authority_block(self):
        from app.api.routes_proforma import suggest_service_charges
        body = _call(suggest_service_charges, 42,
                     draft=_draft(), currency="USD",
                     cm=_cm(usd=None, contractor_id="91254191"), reason=None)
        freight = body["freight"]
        assert freight["available"] is False
        assert "freight_fixed_amount_usd is not set" in freight["blocked_reason"]
        fa = freight["freight_authority"]
        assert fa["resolved"] is True and fa["contractor_id"] == "91254191"
        assert fa["edit_url"] == _expect_edit_url("91254191")

    def test_blocked_freight_missing_service_id_carries_field(self):
        from app.api.routes_proforma import suggest_service_charges
        body = _call(suggest_service_charges, 42,
                     draft=_draft(), currency="USD",
                     cm=_cm(usd=120, service_id=None, contractor_id="55"), reason=None)
        freight = body["freight"]
        assert freight["available"] is False
        fa = freight["freight_authority"]
        assert fa["missing_field"] == "freight_service_id"
        assert fa["edit_url"] == _expect_edit_url("55")

    def test_resolution_failure_blocks_without_identity(self):
        from app.api.routes_proforma import suggest_service_charges
        body = _call(suggest_service_charges, 42,
                     draft=_draft(), currency="USD", cm=None,
                     reason="multiple Customer Master records — open the Customer "
                            "Mapping tab and select")
        assert body["freight"]["available"] is False
        # combined resolution-block path returns no per-entry freight_authority
        assert "freight_authority" not in body["freight"]


# ── FA-11: V1 shipment-detail.html blocker UX (source-grep) ──────────────────

class TestV1FreightBlockerDeepLink:
    def _html(self):
        return _V1_HTML.read_text(encoding="utf-8")

    def test_blocker_threads_resolved_identity(self):
        html = self._html()
        assert "r.freight_authority" in html, (
            "onSuggestFreight must read freight_authority from the response")
        # freight-specific property accesses (avoid matching unrelated tokens
        # like `rows_missing_fields` elsewhere in the page).
        assert "freightBlock.cm_contractor_id" in html
        assert "freightBlock.missing_field" in html

    def test_blocker_deeplinks_exact_record(self):
        html = self._html()
        idx = html.find("freight-block-cm-link")
        assert idx >= 0
        region = html[idx:idx + 500]
        # Deep-links the exact CM record on the V2 Customer Master authority
        # (repointed from the deprecated /dashboard/customer-master-v2.html).
        assert "/v2/master?entity=clients&contractor_id=" in region, (
            "V1 freight blocker link must deep-link the exact CM record on the "
            "V2 authority")
        assert "encodeURIComponent(freightBlock.cm_contractor_id)" in region
        assert "customer-master-v2.html" not in region, (
            "V1 freight blocker must not reference the deprecated CM page")

    def test_blocker_names_only_missing_field(self):
        html = self._html()
        # The misleading hardcoded "(and freight_service_id)" must be gone
        assert "(and <code>freight_service_id</code>)" not in html
        assert "freightBlock.missing_field" in html


# ── FA-12: V2 proforma-detail.jsx blocker UX (source-grep) ───────────────────

class TestV2FreightBlockerRepair:
    def _jsx(self):
        return _V2_JSX.read_text(encoding="utf-8")

    def test_blocker_has_edit_deeplink_and_retry(self):
        jsx = self._jsx()
        assert "freight-authority-edit-" in jsx, "V2 blocker needs a CM edit deep-link"
        assert "freight-authority-retry-" in jsx, "V2 blocker needs a Retry control"
        assert "fa.edit_url" in jsx, "edit link must use the backend-provided edit_url"

    def test_retry_is_readonly_refetch_not_a_write(self):
        """Retry re-runs the read-only suggestion fetch — it must NOT write the
        draft or apply a charge (governance: no silent fallback / override)."""
        jsx = self._jsx()
        idx = jsx.find("freight-authority-retry-")
        assert idx >= 0
        region = jsx[idx:idx + 400]
        assert "onFetchSuggestions" in region, "Retry must re-fetch suggestions"
        assert "onApplyCharge" not in region, (
            "the blocked branch must not apply a charge (read-only except CM edit)")

    def test_repair_block_gated_on_resolved_authority(self):
        jsx = self._jsx()
        assert "fa.resolved" in jsx, (
            "the repair deep-link must be gated on freight_authority.resolved "
            "so an unresolved record never shows a (wrong) edit link")


# ── FA-13: V2 SPA deep-link entry point (the repointed authority target) ─────

class TestV2MasterDeepLinkEntryPoint:
    """The backend + V1/legacy links now deep-link to the V2 Customer Master
    authority (/v2/master?entity=clients&contractor_id=). Pin that master-page.jsx
    actually honours those params — otherwise the repointed link opens a page that
    ignores the record and the operator is back to hunting the customer list."""

    def _jsx(self):
        return _MASTER_JSX.read_text(encoding="utf-8")

    def test_master_reads_deep_link_params(self):
        jsx = self._jsx()
        assert "URLSearchParams(window.location.search" in jsx, (
            "master-page.jsx must read the deep-link query params on load")
        assert "sp.get('contractor_id')" in jsx, (
            "master-page.jsx must honour ?contractor_id= (open that CM record)")
        assert "sp.get('entity')" in jsx, (
            "master-page.jsx must honour ?entity= (select the tab)")

    def test_contractor_id_opens_client_editor(self):
        jsx = self._jsx()
        # contractor_id forces the Clients tab and opens the ClientDetailModal
        # (which exposes freight_fixed_amount_usd/eur — the freight repair target).
        assert "setEntity('clients')" in jsx
        assert "setEditRecord({ bill_to_contractor_id: cid })" in jsx
        assert "ClientDetailModal" in jsx

    def test_client_editor_exposes_freight_amount_fields(self):
        # The deep-link is only useful if its target can edit the missing freight
        # field. ClientDetailModal renders both freight amount inputs.
        cd = (_ROOT / "app" / "static" / "v2" / "client-detail.jsx").read_text(encoding="utf-8")
        assert "freight_fixed_amount_usd" in cd
        assert "freight_fixed_amount_eur" in cd


# ── FA-14: no hardcoded customer name in the repair path ─────────────────────

def test_no_hardcoded_customer_name_in_freight_authority():
    src = _ROUTES_PY.read_text(encoding="utf-8")
    start = src.find("def _freight_authority_block(")
    end = src.find("\ndef ", start + 10)
    body = src[start:end]
    for needle in ("Clear-Diamonds", "Clear Diamonds", "91254191"):
        assert needle not in body, f"freight authority path must not hardcode {needle!r}"
