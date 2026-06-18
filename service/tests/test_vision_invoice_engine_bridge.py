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


# ── 13. Image-only landed cost: freight/insurance from confirmed vision ───────
# Regression for the AWB 2315714531 / inv 122/2026-2027 zero-F+I incident.
# The image-only invoice's text layer is empty, so invoice_totals freight /
# insurance are 0. The freight (USD 100) + insurance (USD 25) live ONLY on the
# operator-confirmed vision_invoice. The bridge MUST carry them into the engine
# input dict, or calculate_landed silently drops the entire freight+insurance
# leg and PZ net collapses to FOB + duty.
def _confirmed_audit_with_fi(**overrides):
    """Production-shaped image-only audit whose CONFIRMED vision_invoice carries
    invoice-level freight/insurance/CIF (FOB 607 + F 100 + I 25 = CIF 732)."""
    return _confirmed_audit(
        freight_usd=100.0, insurance_usd=25.0, cif_usd=732.0, **overrides
    )


def test_build_carries_freight_insurance_from_confirmed_vision():
    audit = _confirmed_audit_with_fi()
    rows = p._authority_rows_from_confirmed_vision(audit, "inv_122.pdf", [])
    built = p._build_invoice_from_authority_rows("inv_122.pdf", "inv_122.pdf", audit, rows, [])
    # Pre-fix this returned 0.0 / 0.0 / 607.0 (read only from invoice_totals).
    assert abs(built["freight_usd"] - 100.0) < 0.01
    assert abs(built["insurance_usd"] - 25.0) < 0.01
    assert abs(built["cif_usd"] - 732.0) < 0.01
    # FOB is untouched by the freight/insurance fallback.
    assert abs(built["fob_usd"] - 607.0) < 0.01


def test_build_freight_insurance_zero_when_vision_lacks_them():
    """A confirmed proposal that does NOT carry freight/insurance must NOT have
    them fabricated — this documents the exact production state that produced the
    zero-F+I PZ (vision_invoice had fob only). The fix carries values when
    present; it never invents them."""
    audit = _confirmed_audit()  # no freight/insurance on the proposal
    rows = p._authority_rows_from_confirmed_vision(audit, "inv_122.pdf", [])
    built = p._build_invoice_from_authority_rows("inv_122.pdf", "inv_122.pdf", audit, rows, [])
    assert built["freight_usd"] == 0.0
    assert built["insurance_usd"] == 0.0
    assert abs(built["cif_usd"] - 607.0) < 0.01  # cif == fob when no F+I authority


def test_text_parsed_freight_not_overridden_by_vision():
    """When invoice_totals already carries a (text-parsed) freight/insurance, the
    vision proposal must NOT override it — invoice_totals is the stronger
    authority for a text invoice; the fallback only fills a ZERO."""
    audit = _confirmed_audit_with_fi()
    audit["invoice_totals"] = {
        "total_fob_usd": 0.0,          # FOB still self-computes from rows
        "total_freight_usd": 40.0,     # real text-parsed freight
        "total_insurance_usd": 8.0,
    }
    rows = p._authority_rows_from_confirmed_vision(audit, "inv_122.pdf", [])
    built = p._build_invoice_from_authority_rows("inv_122.pdf", "inv_122.pdf", audit, rows, [])
    assert abs(built["freight_usd"] - 40.0) < 0.01
    assert abs(built["insurance_usd"] - 8.0) < 0.01


def test_image_only_landed_allocates_freight_insurance():
    """End-to-end through calculate_landed: confirmed-vision freight+insurance
    must be allocated proportionally by value (CLAUDE.md financial rule), duty
    must stay exactly the ZC429 A00 figure, and PZ net must exceed the broken
    FOB+duty-only value."""
    audit = _confirmed_audit_with_fi()
    rows = p._authority_rows_from_confirmed_vision(audit, "inv_122.pdf", [])
    inv = p._build_invoice_from_authority_rows("inv_122.pdf", "inv_122.pdf", audit, rows, [])

    zc429 = {"duty_pln": 62.0, "total_cif_usd": 732.0, "lrn": "TEST_LRN",
             "clearance_date": "2026-06-15", "agent": "DHL"}
    nbp = {"usd_rate": 3.6542}
    out_rows, totals = p.calculate_landed([inv], zc429, nbp, corrections_log=[])

    # Allocated freight+insurance totals exactly USD 125 (100 + 25).
    alloc_fi_usd = sum(r["allocated_ship_usd"] for r in out_rows)
    assert abs(alloc_fi_usd - 125.0) < 0.01
    # Per the expected split: row1 (535) ≈ 110.21, row2 (72) ≈ 14.79.
    by_total = {round(r["total_usd"], 2): r["allocated_ship_usd"] for r in out_rows}
    assert abs(by_total[535.0] - 110.21) < 0.05
    assert abs(by_total[72.0] - 14.79) < 0.05
    # Duty stays exactly the ZC429 A00 figure (residual-reconciled).
    alloc_duty_pln = round(sum(r["allocated_duty_pln"] for r in out_rows), 2)
    assert alloc_duty_pln == 62.0
    # PZ net (sum of line netto) now includes the freight+insurance leg, so it
    # exceeds the broken FOB×rate + duty value (607 × 3.6542 + 62 ≈ 2280.10).
    pz_net = round(sum(r["line_netto_pln"] for r in out_rows), 2)
    fob_plus_duty_only = round(607.0 * 3.6542 + 62.0, 2)
    assert pz_net > fob_plus_duty_only + 100.0   # F+I adds 125 USD × 3.6542 ≈ 457 PLN
    # totals echo the carried CIF (fob+freight+insurance).
    assert abs(totals["total_cif_usd"] - 732.0) < 0.01


# ── 14. GATE 1 follow-up (2026-06-18): F+I backfill gate hardening ────────────
# The backfill gate inside _build_invoice_from_authority_rows must mirror the
# WRITER discipline in _merge_vision_invoice exactly: operator-confirmed AND
# EXPLICITLY USD, dropping zero/negative values. These pin the gate in isolation
# (the normal _try_invoice router rejects unconfirmed/non-USD proposals BEFORE
# the builder, so the builder's own guard would otherwise be source-grep-only).

def test_absent_currency_does_not_backfill_fi():
    """A confirmed proposal carrying freight/insurance but NO currency key must
    NOT be backfilled. Pre-hardening the gate defaulted absent currency to USD —
    more permissive than _merge_vision_invoice, which withholds F+I unless the
    currency reads explicitly USD. The gate now treats absent/blank as non-USD."""
    rows_audit = _confirmed_audit_with_fi()
    rows = p._authority_rows_from_confirmed_vision(rows_audit, "inv_122.pdf", [])
    audit = _confirmed_audit_with_fi()
    audit["vision_invoice"].pop("currency")  # currency absent entirely
    built = p._build_invoice_from_authority_rows("inv_122.pdf", "inv_122.pdf", audit, rows, [])
    assert built["freight_usd"] == 0.0
    assert built["insurance_usd"] == 0.0
    assert abs(built["cif_usd"] - 607.0) < 0.01  # cif collapses to fob — no backfill


def test_blank_currency_does_not_backfill_fi():
    """An empty-string currency is also non-USD — must not backfill."""
    rows_audit = _confirmed_audit_with_fi()
    rows = p._authority_rows_from_confirmed_vision(rows_audit, "inv_122.pdf", [])
    audit = _confirmed_audit_with_fi(currency="")
    built = p._build_invoice_from_authority_rows("inv_122.pdf", "inv_122.pdf", audit, rows, [])
    assert built["freight_usd"] == 0.0
    assert built["insurance_usd"] == 0.0


def test_unconfirmed_vision_does_not_backfill_fi():
    """Direct-unit guard: even with valid pre-built rows, an UNCONFIRMED proposal
    carrying freight/insurance must not have them promoted into the engine. The
    operator_confirmed gate lives inside the builder, not only in the router."""
    rows_audit = _confirmed_audit_with_fi()
    rows = p._authority_rows_from_confirmed_vision(rows_audit, "inv_122.pdf", [])
    audit = _confirmed_audit_with_fi(operator_confirmed=False)
    built = p._build_invoice_from_authority_rows("inv_122.pdf", "inv_122.pdf", audit, rows, [])
    assert built["freight_usd"] == 0.0
    assert built["insurance_usd"] == 0.0
    assert abs(built["cif_usd"] - 607.0) < 0.01


def test_non_usd_vision_does_not_backfill_fi():
    """A confirmed EUR proposal must not backfill USD freight/insurance (currency
    mixing). The router rejects EUR before the builder; this pins the builder's
    own gate in isolation."""
    rows_audit = _confirmed_audit_with_fi()
    rows = p._authority_rows_from_confirmed_vision(rows_audit, "inv_122.pdf", [])
    audit = _confirmed_audit_with_fi(currency="EUR")
    built = p._build_invoice_from_authority_rows("inv_122.pdf", "inv_122.pdf", audit, rows, [])
    assert built["freight_usd"] == 0.0
    assert built["insurance_usd"] == 0.0
    assert abs(built["cif_usd"] - 607.0) < 0.01


def test_negative_fi_values_dropped():
    """Negative freight/insurance on the proposal are noise, not authority — they
    must be dropped ("null not 0" discipline), never backfilled."""
    rows_audit = _confirmed_audit_with_fi()
    rows = p._authority_rows_from_confirmed_vision(rows_audit, "inv_122.pdf", [])
    audit = _confirmed_audit(freight_usd=-10.0, insurance_usd=-5.0, cif_usd=732.0)
    built = p._build_invoice_from_authority_rows("inv_122.pdf", "inv_122.pdf", audit, rows, [])
    assert built["freight_usd"] == 0.0
    assert built["insurance_usd"] == 0.0
    assert abs(built["cif_usd"] - 607.0) < 0.01


def test_zero_fi_values_not_backfilled():
    """Explicit zero freight/insurance on the proposal must not be backfilled —
    a zero carries no allocation authority."""
    rows_audit = _confirmed_audit_with_fi()
    rows = p._authority_rows_from_confirmed_vision(rows_audit, "inv_122.pdf", [])
    audit = _confirmed_audit(freight_usd=0.0, insurance_usd=0.0, cif_usd=607.0)
    built = p._build_invoice_from_authority_rows("inv_122.pdf", "inv_122.pdf", audit, rows, [])
    assert built["freight_usd"] == 0.0
    assert built["insurance_usd"] == 0.0


def test_one_leg_insurance_backfilled_freight_text_wins():
    """Asymmetric single-leg: text-parsed freight present (40) but insurance zero.
    Freight must stay text-parsed (40, not overridden); insurance must backfill
    from the confirmed vision proposal (25). The two legs are independent."""
    audit = _confirmed_audit_with_fi()
    audit["invoice_totals"] = {"total_fob_usd": 0.0, "total_freight_usd": 40.0,
                               "total_insurance_usd": 0.0}
    rows = p._authority_rows_from_confirmed_vision(audit, "inv_122.pdf", [])
    built = p._build_invoice_from_authority_rows("inv_122.pdf", "inv_122.pdf", audit, rows, [])
    assert abs(built["freight_usd"] - 40.0) < 0.01    # text-parsed freight preserved
    assert abs(built["insurance_usd"] - 25.0) < 0.01  # insurance backfilled from vision


def test_one_leg_freight_backfilled_insurance_text_wins():
    """Mirror of the above: text-parsed insurance present (8) but freight zero.
    Insurance stays text-parsed (8); freight backfills from vision (100)."""
    audit = _confirmed_audit_with_fi()
    audit["invoice_totals"] = {"total_fob_usd": 0.0, "total_freight_usd": 0.0,
                               "total_insurance_usd": 8.0}
    rows = p._authority_rows_from_confirmed_vision(audit, "inv_122.pdf", [])
    built = p._build_invoice_from_authority_rows("inv_122.pdf", "inv_122.pdf", audit, rows, [])
    assert abs(built["freight_usd"] - 100.0) < 0.01   # freight backfilled from vision
    assert abs(built["insurance_usd"] - 8.0) < 0.01   # text-parsed insurance preserved
