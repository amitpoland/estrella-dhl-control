"""Compact wFirma PZ description notes (2026-05-22).

Pins the public contract of `wfirma_pz_notes.build_wfirma_pz_notes`:

- Fixed line order, no placeholders for missing fields, ASCII safety,
  length cap, supplier normalisation, AWB / invoice fallbacks,
  customs-agent routing (DHL self-clearance vs agency).
- Pure function — no I/O, no external state.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from service.app.services.wfirma_pz_notes import (
    LINE_KEYS,
    MAX_NOTE_LEN,
    build_wfirma_pz_notes,
    _supplier_short,
)


# ── Fixture: operator's exact spec — DHL self-clearance ────────────────

def _spec_audit():
    """Synthetic audit that produces the operator's exact example."""
    return {
        "awb": "4789974092",
        "carrier": "DHL",
        "customs_declaration": {
            "mrn": "26PL44302D00C2M4R4",
            "lrn": "26S00SV10S",
            "art33a": True,
            "nbp_table": "096/A/NBP/2026",
            "nbp_rate": 3.6709,
        },
        "verification": {"invoice_exporter_name": "Global Jewellery"},
        "clearance_decision": {"clearance_path": "self_clearance"},
        "_pz_engine_authority_rows": [{"invoice_number": "088/2026-2027"}],
    }


def test_spec_output_exact_match():
    out = build_wfirma_pz_notes(
        _spec_audit(), "SHIPMENT_4789974092_2026-05_999deef1"
    )
    expected = (
        "INV:088/2026-2027\n"
        "AWB:4789974092\n"
        "MRN:26PL44302D00C2M4R4\n"
        "SAD:26S00SV10S\n"
        "VAT:Art33a\n"
        "NBP:096/A/NBP/2026 USD=3.6709\n"
        "SUP:Global Jewellery\n"
        "CA:DHL Express PL"
    )
    assert out == expected


def test_fixed_line_order():
    out = build_wfirma_pz_notes(_spec_audit(), "SHIPMENT_4789974092_2026-05_X")
    lines = out.split("\n")
    keys = [ln.split(":", 1)[0] for ln in lines]
    assert keys == list(LINE_KEYS)


# ── Missing-field omission ─────────────────────────────────────────────

def test_missing_fields_omitted_not_rendered_as_unknown():
    a = _spec_audit()
    a["customs_declaration"].pop("lrn", None)           # no SAD
    a["customs_declaration"].pop("nbp_table", None)     # no NBP
    a["clearance_decision"]["clearance_path"] = ""       # no CA route
    a["carrier"] = ""
    out = build_wfirma_pz_notes(a, "SHIPMENT_4789974092_2026-05_X")
    assert "SAD:" not in out
    assert "NBP:" not in out
    assert "CA:" not in out
    # Forbidden placeholders MUST NOT appear anywhere
    for placeholder in ("UNKNOWN", "None", "null", "<", "n/a", "N/A"):
        assert placeholder not in out


def test_art33a_line_only_when_evidenced():
    a = _spec_audit()
    a["customs_declaration"].pop("art33a", None)
    a["customs_declaration"].pop("vat_mode", None)
    a.pop("settlement_mode", None)
    out = build_wfirma_pz_notes(a, "BID")
    assert "VAT:" not in out


# ── Supplier normalisation ─────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("Global Jewellery Pvt. Ltd.", "Global Jewellery"),
    ("Global Jewellery Pvt Ltd", "Global Jewellery"),
    ("ESTRELLA JEWELS SP. Z O.O. SP. K.", "Estrella Jewels"),
    ("ESTRELLA JEWELS LLP.", "Estrella Jewels"),
    ("Foo Bar Inc.", "Foo Bar"),
    ("Foo Bar GmbH", "Foo Bar"),
    ("Already Short", "Already Short"),
    ("Mixed Case Co. Ltd.", "Mixed Case Co"),
])
def test_supplier_short(raw, expected):
    assert _supplier_short(raw) == expected


# ── AWB fallback chain ─────────────────────────────────────────────────

def test_awb_fallback_to_batch_id():
    a = _spec_audit()
    a.pop("awb", None)
    a.pop("tracking_no", None)
    out = build_wfirma_pz_notes(a, "SHIPMENT_4789974092_2026-05_abc12345")
    assert "AWB:4789974092" in out


def test_awb_skipped_when_no_source():
    a = _spec_audit()
    a.pop("awb", None)
    a.pop("tracking_no", None)
    out = build_wfirma_pz_notes(a, "SHIPMENT_AUTO_2026-05_abc")
    assert "AWB:" not in out


# ── Invoice number fallback ────────────────────────────────────────────

def test_invoice_from_sidecar_when_top_level_missing():
    a = _spec_audit()
    a.pop("invoice_no", None)
    out = build_wfirma_pz_notes(a, "BID")
    assert "INV:088/2026-2027" in out


def test_invoice_from_invoice_names_when_sidecar_missing():
    a = _spec_audit()
    a.pop("_pz_engine_authority_rows", None)
    a["invoice_names"] = ["GLOBAL Invoice 088.pdf"]
    out = build_wfirma_pz_notes(a, "BID")
    assert "INV:GLOBAL Invoice 088" in out


# ── Customs-agent routing ──────────────────────────────────────────────

def test_ca_dhl_self_clearance_default():
    a = _spec_audit()
    a["carrier"] = "DHL"
    a["clearance_decision"]["clearance_path"] = "self_clearance"
    out = build_wfirma_pz_notes(a, "BID")
    assert "CA:DHL Express PL" in out


def test_ca_agency_clearance_uses_agency_name():
    a = _spec_audit()
    a["clearance_decision"] = {
        "clearance_path": "agency_clearance",
        "agency": "Agencja Celna Spedycja",
    }
    a["customs_declaration"]["customs_agent"] = "AGENCJA CELNA SPEDYCJA KUŹMICZ K."
    out = build_wfirma_pz_notes(a, "BID")
    assert "CA:Agencja Celna Spedycja" in out


def test_ca_omitted_when_no_evidence():
    a = _spec_audit()
    a["carrier"] = ""
    a["clearance_decision"] = {}
    a["customs_declaration"].pop("customs_agent", None)
    out = build_wfirma_pz_notes(a, "BID")
    assert "CA:" not in out


# ── Dummy-data + length + purity guards ────────────────────────────────

def test_no_dummy_invoice_no_in_output():
    """Regression pin: a historical-fixture invoice number must not
    appear in the output when the current audit's invoice differs."""
    a = _spec_audit()
    out = build_wfirma_pz_notes(a, "BID")
    assert "EJL/25-26/1217-1219" not in out
    assert "EJL/25-26/1217" not in out


def test_output_under_max_length():
    a = _spec_audit()
    out = build_wfirma_pz_notes(a, "SHIPMENT_4789974092_2026-05_999deef1")
    assert len(out) <= MAX_NOTE_LEN


def test_truncation_at_line_boundary_for_oversize_input():
    a = _spec_audit()
    # Force a giant supplier name; the helper still truncates cleanly.
    a["verification"]["invoice_exporter_name"] = "X" * (MAX_NOTE_LEN + 50)
    out = build_wfirma_pz_notes(a, "BID")
    assert len(out) <= MAX_NOTE_LEN
    # No partial line — every line must contain ":" (key:value).
    for ln in out.split("\n"):
        if ln:
            assert ":" in ln


def test_empty_audit_returns_empty_string():
    assert build_wfirma_pz_notes({}, "") == ""
    assert build_wfirma_pz_notes(None, "") == ""  # type: ignore[arg-type]


def test_pure_function_repeated_calls_identical():
    a = _spec_audit()
    out1 = build_wfirma_pz_notes(a, "BID")
    out2 = build_wfirma_pz_notes(a, "BID")
    assert out1 == out2


# ── Live audit smoke (read-only) ───────────────────────────────────────

LIVE_AUDIT = Path(
    "C:/PZ/storage/outputs/SHIPMENT_4789974092_2026-05_999deef1/audit.json"
)


@pytest.mark.skipif(not LIVE_AUDIT.exists(), reason="live audit not present")
def test_live_audit_renders_all_expected_keys():
    a = json.loads(LIVE_AUDIT.read_text(encoding="utf-8"))
    out = build_wfirma_pz_notes(a, "SHIPMENT_4789974092_2026-05_999deef1")
    # The Global batch in production has the canonical values verified
    # in prior diagnostic rounds:
    assert "INV:088/2026-2027" in out
    assert "AWB:4789974092" in out
    assert "MRN:26PL44302D00C2M4R4" in out
    assert "SAD:26S00SV10S" in out
    assert "VAT:Art33a" in out
    assert "NBP:096/A/NBP/2026 USD=3.6709" in out
    assert "SUP:Global Jewellery" in out
    # Production batch went via agency_clearance — CA reflects the agency
    assert "CA:Agencja Celna Spedycja" in out
