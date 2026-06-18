"""Stage C — confirmed-vision → PZ engine authority bridge (2026-06-18).

Validates the Priority-3 path in `pz_import_processor`:
`_authority_rows_from_confirmed_vision` + its wiring inside
`_try_invoice_from_authority_rows`.

Context: image-only / scanned invoices have no text layer, so the text parser
yields FOB $0 and the engine fails at "FOB USD = 0.00 — cannot compute freight
share". The vision/OCR fallback writes an advisory `vision_invoice` proposal.
Once an operator CONFIRMS that proposal (`operator_confirmed == True`, written
only by the confirm endpoint / manual unblock tool — ADR-031 isolation), the
engine bridge promotes its line items into authority rows so PZ generates.

Every failure mode must fall through cleanly (return None) — an unconfirmed,
drifting, or non-USD proposal must NEVER reach the engine.
"""
from __future__ import annotations

import json
from pathlib import Path

import pz_import_processor as p


# ── Fixture helpers ──────────────────────────────────────────────────────────

def _vision_items():
    """Mirrors production fixture SHIPMENT_2315714531 (Global Jewellery
    invoice 122/2026-2027): qty 70, FOB $607."""
    return [
        {"description": "SL925 925 Silver Jewellery Studded with CZ (Ring-66 PCS)",
         "hsn": "71131149", "quantity": 66, "unit_price_usd": 8.11, "total_usd": 535.0},
        {"description": "SL925 Silver Jewellery Studded with Diamond & Colour Stone (Ring-4 PCS)",
         "hsn": "71131149", "quantity": 4, "unit_price_usd": 18.0, "total_usd": 72.0},
    ]


def _confirmed_audit(items=None, **vi_overrides):
    vi = {
        "supplier": "Global Jewellery Pvt. Ltd.",
        "invoice_no": "122/2026-2027",
        "currency": "USD",
        "fob_usd": 607.0,
        "operator_confirmed": True,
        "line_items": _vision_items() if items is None else items,
    }
    vi.update(vi_overrides)
    return {
        # image-only: text parser produced FOB 0, no customs aggregation.
        "invoice_totals": {"total_fob_usd": 0.0, "total_freight_usd": 0.0,
                           "total_insurance_usd": 0.0},
        "vision_invoice": vi,
    }


def _layout(tmp_path: Path, audit: dict):
    batch = tmp_path / "SHIPMENT_X"
    inv_dir = batch / "source" / "invoices"
    inv_dir.mkdir(parents=True)
    pdf = inv_dir / "inv_122.pdf"
    pdf.write_bytes(b"%PDF-1.4 stub")
    (batch / "audit.json").write_text(json.dumps(audit), encoding="utf-8")
    return pdf


# ── 1. Confirmed vision builds reconciled authority rows ─────────────────────
def test_helper_builds_rows_from_confirmed_vision():
    log = []
    rows = p._authority_rows_from_confirmed_vision(_confirmed_audit(), "inv_122.pdf", log)
    assert rows is not None
    assert len(rows) == 2
    assert rows[0]["item_type"] == "RING"
    assert rows[0]["invoice_number"] == "122/2026-2027"
    assert rows[0]["uom"] == "PCS"
    assert abs(sum(r["line_total_usd"] for r in rows) - 607.0) < 0.01
    assert sum(r["quantity"] for r in rows) == 70


# ── 2. Built rows pass the shared authority validator ────────────────────────
def test_built_rows_pass_validation():
    audit = _confirmed_audit()
    rows = p._authority_rows_from_confirmed_vision(audit, "inv_122.pdf", [])
    ok, why = p._validate_authority_rows(rows, audit)
    assert ok, why


# ── 3. Full bridge end-to-end: FOB self-computed from rows ───────────────────
def test_bridge_end_to_end_unblocks_fob(tmp_path):
    pdf = _layout(tmp_path, _confirmed_audit())
    parsed = p._try_invoice_from_authority_rows(str(pdf), "inv_122.pdf", [])
    assert parsed is not None
    assert abs(parsed["fob_usd"] - 607.0) < 0.01
    assert len(parsed["items"]) == 2
    assert parsed["_authority_source"] == "invoice_positions_authority"


# ── 4. NEGATIVE: unconfirmed proposal is ignored (no operator gate) ──────────
def test_unconfirmed_proposal_ignored(tmp_path):
    pdf = _layout(tmp_path, _confirmed_audit(operator_confirmed=False))
    assert p._try_invoice_from_authority_rows(str(pdf), "inv_122.pdf", []) is None


def test_missing_confirmed_flag_ignored():
    audit = _confirmed_audit()
    audit["vision_invoice"].pop("operator_confirmed")
    assert p._authority_rows_from_confirmed_vision(audit, "x", []) is None


# ── 5. NEGATIVE: FOB drift > $1 between rows and proposal is rejected ─────────
def test_fob_drift_rejected():
    audit = _confirmed_audit(fob_usd=999.0)
    log = []
    assert p._authority_rows_from_confirmed_vision(audit, "x", log) is None
    assert any("vision_fob_drift" in m for m in log)


# ── 6. NEGATIVE: non-USD proposal rejected (engine is USD-based) ─────────────
def test_non_usd_rejected():
    audit = _confirmed_audit(currency="EUR")
    log = []
    assert p._authority_rows_from_confirmed_vision(audit, "x", log) is None
    assert any("vision_currency_not_usd" in m for m in log)


# ── 7. NEGATIVE: zero/negative qty or total rejected ─────────────────────────
def test_zero_qty_rejected():
    bad = [{"description": "RING", "hsn": "7113", "quantity": 0, "total_usd": 10.0}]
    audit = _confirmed_audit(items=bad, fob_usd=0.0)
    assert p._authority_rows_from_confirmed_vision(audit, "x", []) is None


def test_zero_total_rejected():
    bad = [{"description": "RING", "hsn": "7113", "quantity": 5, "total_usd": 0.0}]
    audit = _confirmed_audit(items=bad, fob_usd=0.0)
    assert p._authority_rows_from_confirmed_vision(audit, "x", []) is None


# ── 8. NEGATIVE: empty / missing line_items rejected ─────────────────────────
def test_empty_line_items_rejected():
    audit = _confirmed_audit(items=[], fob_usd=0.0)
    assert p._authority_rows_from_confirmed_vision(audit, "x", []) is None


# ── 9. ADR-031: bridge never mutates operator_confirmed ──────────────────────
def test_bridge_does_not_set_confirmed_flag(tmp_path):
    audit = _confirmed_audit(operator_confirmed=False)
    pdf = _layout(tmp_path, audit)
    p._try_invoice_from_authority_rows(str(pdf), "inv_122.pdf", [])
    on_disk = json.loads((Path(pdf).parent.parent.parent / "audit.json").read_text(encoding="utf-8"))
    assert on_disk["vision_invoice"]["operator_confirmed"] is False


# ── 10. NEGATIVE: absent/zero fob_usd rejected even with valid rows ───────────
# Review finding (3 reviewers converged): for an image-only invoice the audit has
# NO independent FOB anchor, so fob_usd is the ONLY cross-check on the LLM row sum.
# A confirmed proposal that omits or zeroes fob_usd must be rejected, not allowed
# to self-set its FOB from the (unverified) row sum.
def test_fob_absent_rejected():
    audit = _confirmed_audit(fob_usd=None)
    log = []
    assert p._authority_rows_from_confirmed_vision(audit, "x", log) is None
    assert any("vision_fob_absent_or_zero" in m for m in log)


def test_fob_zero_rejected_even_with_valid_rows():
    audit = _confirmed_audit(fob_usd=0.0)  # rows still sum to 607
    log = []
    assert p._authority_rows_from_confirmed_vision(audit, "x", log) is None
    assert any("vision_fob_absent_or_zero" in m for m in log)


# ── 11. Image-only invoice routes to the GENERIC parser, and the bridge fires ─
# The real failure: an image-only PDF has no text layer, so detect_invoice_format
# returns "generic" (no template marker) and the text-blind generic parser would
# yield FOB $0. The bridge must intercept the generic branch so a confirmed
# vision_invoice still generates a PZ. Without the Stage-C generic-branch wiring
# the confirmed rows would never reach the engine.
def test_image_only_routes_generic_and_bridge_fires(tmp_path, monkeypatch):
    pdf = _layout(tmp_path, _confirmed_audit())

    class _Pg:
        def extract_text(self):
            return ""  # image-only: no extractable text

    class _Doc:
        pages = [_Pg()]
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    monkeypatch.setattr(p.pdfplumber, "open", lambda *_a, **_k: _Doc())

    # Detection genuinely falls through to generic on empty text.
    assert p.detect_invoice_format("", []) == "generic"

    result = p.parse_invoice(str(pdf), [])
    assert result["_authority_source"] == "invoice_positions_authority"
    assert abs(result["fob_usd"] - 607.0) < 0.01
    assert len(result["items"]) == 2


# ── 12. Exporter identity comes from the confirmed vision supplier ────────────
# Once the bridge can reach non-Global-Jewellery image invoices (generic branch),
# the historical hardcoded "Global Jewellery" exporter would be a customs error.
# The built invoice must carry the supplier named on the confirmed proposal.
def test_exporter_name_from_vision_supplier(tmp_path):
    audit = _confirmed_audit(supplier="Acme Scanned Imports Ltd.")
    rows = p._authority_rows_from_confirmed_vision(audit, "inv_122.pdf", [])
    built = p._build_invoice_from_authority_rows("inv_122.pdf", "inv_122.pdf", audit, rows, [])
    assert built["exporter_name"] == "Acme Scanned Imports Ltd."
    assert built["seller_name"] == "Acme Scanned Imports Ltd."


def test_exporter_name_defaults_when_no_vision_supplier():
    # PR #269 sidecar/text path carries no vision_invoice → historical default.
    audit = {
        "invoice_totals": {"total_fob_usd": 607.0},
        "_pz_engine_authority_meta": {"fob_sum_preserved": 607.0},
    }
    rows = p._authority_rows_from_confirmed_vision(_confirmed_audit(), "x", [])
    built = p._build_invoice_from_authority_rows("x", "x", audit, rows, [])
    assert built["exporter_name"] == "Global Jewellery"
