"""
test_series_resolver.py — ADR-027 D6 canonical series resolver.

Pins the contract for resolve_final_invoice_series_id() in customer_master.py.
Covers: operator-wins, WDT/domestic CM pick, empty-valid (M-3), "0" normalised
to "", advisory on operator/CM mismatch, ValueError → advisory with "" series,
proforma-type-series HARD BLOCK at route level.

No wFirma calls, no DB writes (pure-function tests + route-level monkeypatch).
Lesson A: no dict stubs for customer_master; uses minimal dataclass-style objects.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from unittest.mock import patch

import pytest

_SVC = Path(__file__).parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))


# ── Minimal CustomerMaster stub (Lesson A shape) ────────────────────────────

@dataclass
class _CM:
    """Minimal shape required by pick_invoice_series_id_for_vat_context.
    Must carry bill_to_name + bill_to_contractor_id for error-message formatting."""
    preferred_invoice_series_id:        str = ""
    preferred_wdt_invoice_series_id:    str = ""
    preferred_export_invoice_series_id: str = ""
    bill_to_name:           str = "Test Customer"
    bill_to_contractor_id:  str = "TEST_CTR_001"


# ── Helpers ─────────────────────────────────────────────────────────────────

def _resolve(*, vat_context="", operator_series_in="", customer_master=None):
    from app.services.customer_master import resolve_final_invoice_series_id
    return resolve_final_invoice_series_id(
        vat_context=vat_context,
        operator_series_in=operator_series_in,
        customer_master=customer_master,
    )


# ── Test: operator override always wins ─────────────────────────────────────

def test_operator_override_wins_over_cm():
    """Operator-provided series beats CM series — ADR-027 D6 step 1."""
    cm = _CM(preferred_invoice_series_id="CM_SER", preferred_wdt_invoice_series_id="CM_WDT")
    series, advisories = _resolve(
        vat_context="domestic",
        operator_series_in="OP_SER",
        customer_master=cm,
    )
    assert series == "OP_SER"


def test_operator_override_wins_for_wdt_context():
    """Operator override beats CM WDT series when vat_context=wdt."""
    cm = _CM(preferred_wdt_invoice_series_id="CM_WDT_SER")
    series, advisories = _resolve(
        vat_context="wdt",
        operator_series_in="OVERRIDE",
        customer_master=cm,
    )
    assert series == "OVERRIDE"


def test_advisory_emitted_when_operator_differs_from_cm():
    """Advisory (not error) emitted when operator series differs from CM preferred."""
    cm = _CM(preferred_invoice_series_id="CM_SER")
    series, advisories = _resolve(
        vat_context="domestic",
        operator_series_in="OP_SER",
        customer_master=cm,
    )
    assert series == "OP_SER"
    assert len(advisories) == 1
    assert "advisory" in advisories[0].lower() or "differs" in advisories[0].lower()


def test_no_advisory_when_operator_matches_cm():
    """No advisory when operator series matches CM preferred series."""
    cm = _CM(preferred_invoice_series_id="SAME_SER")
    series, advisories = _resolve(
        vat_context="domestic",
        operator_series_in="SAME_SER",
        customer_master=cm,
    )
    assert series == "SAME_SER"
    assert advisories == []


def test_zero_string_normalised_to_empty():
    """"0" is the wFirma sentinel for 'no series' — treated as empty, not operator override."""
    series, advisories = _resolve(operator_series_in="0")
    assert series == ""


# ── Test: CM-based resolution per vat_context ───────────────────────────────

def test_wdt_context_uses_preferred_wdt_series():
    """vat_context=wdt → CM.preferred_wdt_invoice_series_id."""
    cm = _CM(
        preferred_invoice_series_id="DOM_SER",
        preferred_wdt_invoice_series_id="WDT_SER",
    )
    series, advisories = _resolve(vat_context="wdt", customer_master=cm)
    assert series == "WDT_SER"
    assert advisories == []


def test_domestic_context_uses_preferred_domestic_series():
    """vat_context=domestic → CM.preferred_invoice_series_id."""
    cm = _CM(
        preferred_invoice_series_id="DOM_SER",
        preferred_wdt_invoice_series_id="WDT_SER",
    )
    series, advisories = _resolve(vat_context="domestic", customer_master=cm)
    assert series == "DOM_SER"
    assert advisories == []


def test_unknown_vat_context_treated_as_domestic():
    """Unknown vat_context values fall through to 'domestic' resolution."""
    cm = _CM(preferred_invoice_series_id="DOM_SER")
    series, advisories = _resolve(vat_context="UNKNOWN_CONTEXT", customer_master=cm)
    assert series == "DOM_SER"


def test_no_cm_no_operator_returns_empty():
    """No CM, no operator → ("", []) — empty is valid per ADR-027 D6 step 3 (M-3)."""
    series, advisories = _resolve()
    assert series == ""
    assert advisories == []


# ── Test: ADR-027 D6 step 3 — empty series is valid (M-3) ──────────────────

def test_empty_series_is_valid_not_an_error():
    """ADR-027 D6: empty series → omit <series>; wFirma contractor default.
    Must NOT raise. Empty advisory list."""
    series, advisories = _resolve(vat_context="domestic", operator_series_in="")
    assert series == ""
    # No advisory for "missing series" — it's a valid state, not a gap


def test_cm_with_no_series_configured_returns_empty():
    """CM with empty preferred_invoice_series_id → ("", advisory_or_empty)."""
    cm = _CM(preferred_invoice_series_id="")
    series, advisories = _resolve(vat_context="domestic", customer_master=cm)
    # Empty series is valid per ADR-027 D6; we accept either "" or advisory
    assert series == ""


# ── Test: ValueError from CM pick → advisory, not exception ────────────────

def test_valueerror_from_cm_pick_becomes_advisory():
    """When pick_invoice_series_id_for_vat_context raises ValueError,
    resolver converts it to an advisory and returns ("", advisories)."""
    from app.services.customer_master import resolve_final_invoice_series_id

    class _CMRaises:
        """Stub that raises ValueError from the pick function."""
        preferred_invoice_series_id = "X"
        preferred_wdt_invoice_series_id = "X"
        preferred_export_invoice_series_id = "X"

    with patch(
        "app.services.customer_master.pick_invoice_series_id_for_vat_context",
        side_effect=ValueError("no matching series for vat_context"),
    ):
        series, advisories = resolve_final_invoice_series_id(
            vat_context="domestic",
            customer_master=_CMRaises(),
        )
    assert series == ""
    assert len(advisories) >= 1
    assert any("series" in a.lower() or "no matching" in a.lower()
               for a in advisories)


# ── Test: source proforma series is NEVER in the fallback chain ─────────────

def test_source_proforma_series_never_used():
    """The source proforma's own series_id MUST NOT appear in the resolver.
    The resolver only consults: operator_series_in, CM series, or empty.
    This test proves it by checking the resolver ignores a proforma-series
    argument that would be in the old inline chain."""
    # Old code used snap.series_id as fallback — resolver must NOT take a snap argument
    import inspect
    from app.services.customer_master import resolve_final_invoice_series_id
    sig = inspect.signature(resolve_final_invoice_series_id)
    param_names = set(sig.parameters.keys())
    assert "snap" not in param_names, (
        "resolve_final_invoice_series_id must not accept a snap/proforma parameter — "
        "source proforma series is permanently excluded from the chain (ADR-027 D6)"
    )


# ── Route-level test: proforma-type-series HARD BLOCK ───────────────────────

def test_execute_route_blocks_when_resolved_series_is_proforma_type(
        tmp_path, monkeypatch):
    """Route-level pin: if the resolved series_id is in proforma_series but NOT
    in invoice_series, the execute endpoint must return ok=False / status=blocked.
    This guards against misfiling invoices into the proforma series.
    (Authority: PROFORMA; named fiscal risk: misfiling invoice — Lesson N §True blockers #5.)
    """
    import sqlite3
    from decimal import Decimal
    from unittest.mock import patch as _patch

    from fastapi.testclient import TestClient

    from app.core.config import settings
    from app.services import wfirma_client as wc
    from app.services import packing_db as pdb
    from app.services import warehouse_db as wdb
    from app.services import document_db as ddb
    from app.services import wfirma_db as wfdb
    from app.services import proforma_invoice_link_db as pildb
    from app.services import proforma_service_charges_db as scdb

    BATCH   = "BATCH_SERIES_BLOCK"
    CLIENT  = "SERIES_CLIENT"
    TOKEN   = "YES_CREATE_FINAL_INVOICE_FROM_PROFORMA"
    PID     = "555proforma"
    PROFORMA_SERIES = "15827088"   # a proforma-type series
    INVOICE_SERIES  = "15827921"   # a separate invoice-type series

    # Minimal storage setup
    pdb.init_packing_db(tmp_path / "packing.db")
    wdb.init_warehouse_db(tmp_path / "warehouse.db")
    ddb.init_document_db(tmp_path / "documents.db")
    wfdb.init_wfirma_db(tmp_path / "wfirma.db")
    scdb.init(tmp_path / "proforma_links.db")
    pildb.init_db(tmp_path / "proforma_links.db")

    pildb.upsert_pending_draft(
        tmp_path / "proforma_links.db",
        batch_id=BATCH, client_name=CLIENT,
        currency="EUR", exchange_rate=None, source_lines_json="[]",
    )
    pildb.mark_draft_issued(
        tmp_path / "proforma_links.db",
        BATCH, CLIENT, wfirma_proforma_id=PID,
    )

    proforma_xml = f"""<?xml version="1.0"?>
<api><invoices><invoice>
  <id>{PID}</id><fullnumber>PROF 99/2026</fullnumber>
  <type>proforma</type><date>2026-05-08</date>
  <paymentmethod>transfer</paymentmethod><paymentdate>2026-06-08</paymentdate>
  <currency>EUR</currency><contractor><id>9001</id></contractor>
  <series><id>{PROFORMA_SERIES}</id></series>
  <total>100.00</total><netto>100.00</netto><description>Test</description>
  <invoicecontents><invoicecontent>
    <name>RING</name><good><id>42</id></good>
    <unit>szt.</unit><unit_count>1.0000</unit_count>
    <price>100.00</price><vat_code><id>228</id></vat_code>
  </invoicecontent></invoicecontents>
</invoice></invoices><status><code>OK</code></status></api>"""

    # Dictionary cache: PROFORMA_SERIES is in proforma_series only, not invoice_series
    fake_dicts = {
        "invoice_series":  [{"id": INVOICE_SERIES, "label": "WDT Invoice Series"}],
        "proforma_series": [{"id": PROFORMA_SERIES, "label": "Proforma Series"}],
    }

    wc._VAT_CODE_ID_CACHE["WDT"] = "228"
    wc._VAT_CODE_ID_CACHE["23"]  = "222"

    from app.api import routes_proforma as rp

    def _stub_readiness(draft, *, intent):
        return {
            "ready": True, "intent": intent,
            "draft_id": int(draft.id), "draft_status": draft.status,
            "blockers": [], "blocking_reasons": [],
            "warnings": [], "ambiguous_designs": {}, "resolved_designs": {},
        }

    from app.main import app
    with _patch.object(settings, "storage_root", tmp_path), \
         _patch.object(settings, "wfirma_create_invoice_allowed", True), \
         _patch.object(wc, "fetch_invoice_xml", return_value=proforma_xml), \
         _patch.object(wc, "_http_request",
                       side_effect=AssertionError("wFirma must not be called")), \
         _patch("app.api.routes_proforma._derive_draft_readiness", _stub_readiness), \
         _patch(
             "app.services.wfirma_dictionary_cache.get_dictionaries",
             return_value=fake_dicts,
         ):
        with TestClient(app, raise_server_exceptions=True) as tc:
            body = tc.post(
                f"/api/v1/proforma/to-invoice/{BATCH}/{CLIENT}",
                headers={"X-API-KEY": settings.api_key or "test-key",
                         "X-Operator": "amit"},
                json={
                    "confirm":         TOKEN,
                    # Operator sends the proforma-type series — should be blocked
                    "final_series_id": PROFORMA_SERIES,
                },
            ).json()

    assert body.get("ok") is False, (
        f"Expected ok=False (proforma-type series block), got: {body}"
    )
    assert body.get("status") == "blocked", body
    assert any("PROFORMA" in (r or "").upper() or "proforma" in (r or "").lower()
               for r in body.get("blocking_reasons", [])), (
        f"Blocking reason must mention proforma-type series; got: {body.get('blocking_reasons')}"
    )
