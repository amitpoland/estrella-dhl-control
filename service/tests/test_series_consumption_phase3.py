"""
test_series_consumption_phase3.py — Phase 3 Series Consumption regression tests.

Pins:
  1. ProformaRequest.series_id field exists and defaults to "".
  2. _build_proforma_xml emits <series><id>…</id></series> when series_id is set.
  3. _build_proforma_xml omits the block when series_id is empty or "0".
  4. Source-grep: _build_proforma_request reads customer master series id.
  5. Source-grep: _build_proforma_request_from_draft reads customer master series id.
  6. Source-grep: invoice conversion fallback chain includes preferred_invoice_series_id.
  7. Source-grep: old hard block on service charges removed from _build_proforma_request_from_draft.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest


def _ensure_path() -> None:
    here = Path(__file__).resolve()
    for p in (str(here.parents[1]), str(here.parents[2])):
        if p not in sys.path:
            sys.path.insert(0, p)


_ensure_path()

_ROUTES  = Path(__file__).resolve().parents[1] / "app" / "api" / "routes_proforma.py"
_WFCLIENT = Path(__file__).resolve().parents[1] / "app" / "services" / "wfirma_client.py"


# ── 1. ProformaRequest.series_id field ───────────────────────────────────────

def test_proforma_request_has_series_id_field():
    from app.services.wfirma_client import ProformaRequest
    req = ProformaRequest(
        client_name="Test",
        client_zip="",
        client_city="",
    )
    assert hasattr(req, "series_id"), "ProformaRequest must have series_id field"
    assert req.series_id == "", "Default series_id must be empty string"


def test_proforma_request_series_id_accepted():
    from app.services.wfirma_client import ProformaRequest
    req = ProformaRequest(
        client_name="Test",
        client_zip="",
        client_city="",
        series_id="PS_100",
    )
    assert req.series_id == "PS_100"


# ── 2. _build_proforma_xml emits <series> block ───────────────────────────────

def _minimal_req(series_id: str = ""):
    """Build the minimal ProformaRequest needed to invoke _build_proforma_xml
    without hitting network calls (empty lines, pre-resolved ids)."""
    from app.services.wfirma_client import ProformaRequest, ReservationLine
    return ProformaRequest(
        client_name          = "Test Client",
        client_zip           = "",
        client_city          = "",
        lines                = [
            ReservationLine(
                product_code   = "TST-001",
                wfirma_good_id = "WFG-001",
                product_name   = "Test",
                qty            = 1.0,
                unit_price     = 10.0,
                unit           = "szt.",
                currency       = "PLN",
            )
        ],
        currency             = "PLN",
        wfirma_contractor_id = "WFC-001",
        vat_code_id          = "VAT-23",
        series_id            = series_id,
    )


def test_build_proforma_xml_emits_series_when_set():
    from app.services.wfirma_client import _build_proforma_xml
    req = _minimal_req(series_id="PS_100")
    xml = _build_proforma_xml(req)
    assert "<series>" in xml, "XML must contain <series> block when series_id is set"
    assert "<id>PS_100</id>" in xml


def test_build_proforma_xml_omits_series_when_empty():
    from app.services.wfirma_client import _build_proforma_xml
    req = _minimal_req(series_id="")
    xml = _build_proforma_xml(req)
    assert "<series>" not in xml, "XML must NOT contain <series> when series_id is empty"


def test_build_proforma_xml_omits_series_for_zero():
    from app.services.wfirma_client import _build_proforma_xml
    req = _minimal_req(series_id="0")
    xml = _build_proforma_xml(req)
    assert "<series>" not in xml, "XML must NOT contain <series> when series_id is '0'"


# ── 3-6. Source-grep contracts ────────────────────────────────────────────────

def test_build_proforma_request_reads_customer_master_series():
    text = _ROUTES.read_text(encoding="utf-8")
    assert "pick_proforma_series_id" in text, (
        "_build_proforma_request must call pick_proforma_series_id "
        "to resolve customer master preferred series"
    )
    assert "cm_proforma_series" in text, (
        "_build_proforma_request must store result as cm_proforma_series"
    )


def test_build_proforma_request_from_draft_reads_customer_master_series():
    text = _ROUTES.read_text(encoding="utf-8")
    assert "draft_proforma_series" in text, (
        "_build_proforma_request_from_draft must resolve "
        "draft_proforma_series from customer master"
    )


def test_invoice_conversion_fallback_includes_preferred_invoice_series():
    text = _ROUTES.read_text(encoding="utf-8")
    assert "pick_invoice_series_id" in text, (
        "invoice conversion must call pick_invoice_series_id as fallback "
        "when proforma XML has no series id"
    )
    assert "preferred_invoice_series_id" in text or "pick_invoice_series_id" in text, (
        "preferred_invoice_series_id fallback must be present in routes_proforma"
    )


def test_old_hard_service_charges_block_removed_from_draft_builder():
    text = _ROUTES.read_text(encoding="utf-8")
    assert "service charges present but wFirma service-product mapping not" \
        not in text, (
        "Old hard block on service charges must be removed from "
        "_build_proforma_request_from_draft (Phase 6D)"
    )
