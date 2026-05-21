"""test_global_packing_first_authority.py

Pins the source-priority fix for Global Jewellery customs description
generation:

  packing_lines  (NEW step 0) → first authority for Global supplier
       ↓
  db invoice_lines (step 1)   → only when packing didn't produce rows
       ↓
  XLSX rows sheet (step 2)
       ↓
  aggregate synthesizer (step 3) — FALLBACK ONLY; never reached for
       Global when packing rows exist; explicitly blocked with 422 when
       a Global packing file is present on disk but produced 0 rows.

The operator's hard requirement: a regenerated Polish Description for a
Global batch with packing rows MUST NOT contain the strings "UNKNOWN",
"metal szlachetny", "Wyrób jubilerski", or "grouped invoice aggregate".

Estrella protection: non-Global suppliers MUST pass through
_inject_rows_from_packing_lines as a no-op. The Estrella EJL chain is
unchanged.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


_ROUTES = Path(__file__).resolve().parent.parent / "app" / "api" / "routes_dhl_clearance.py"


# ── Source contract: injection chain + helpers present ────────────────────


def test_packing_injection_helper_exists():
    src = _ROUTES.read_text(encoding="utf-8")
    assert "def _inject_rows_from_packing_lines(" in src, (
        "_inject_rows_from_packing_lines missing from routes_dhl_clearance.py"
    )


def test_chain_order_packing_first():
    """Step 0 (packing_lines) must run BEFORE invoice_lines / XLSX /
    aggregate synthesizer."""
    src = _ROUTES.read_text(encoding="utf-8")
    idx_chain = src.find("def _inject_rows_from_sources(")
    body = src[idx_chain : idx_chain + 2000]
    i_packing = body.find("_inject_rows_from_packing_lines(")
    i_invoice = body.find("_inject_rows_from_db_invoice_lines(")
    i_xlsx    = body.find("_inject_rows_from_xlsx(")
    i_synth   = body.find("_synthesize_rows_from_invoice_aggregates(")
    assert 0 < i_packing < i_invoice < i_xlsx < i_synth, (
        "chain order must be: packing → invoice_lines → xlsx → synthesize"
    )


def test_global_packing_empty_guard_present_at_route_layer():
    """Operator spec: if Global packing file exists on disk but parser
    produced 0 rows, route MUST 422 with global_packing_present_but_empty
    rather than fall through to UNKNOWN aggregate synthesis."""
    src = _ROUTES.read_text(encoding="utf-8")
    assert "_global_packing_present_but_empty" in src, (
        "global_packing_present_but_empty flag missing"
    )
    assert '"global_packing_present_but_empty"' in src, (
        "422 guard code 'global_packing_present_but_empty' missing"
    )


def test_packing_injection_imports_supplier_detect():
    """The packing injection must dispatch only when supplier is Global
    Jewellery — non-Global suppliers (EJL) MUST be no-op'd here."""
    src = _ROUTES.read_text(encoding="utf-8")
    assert "supplier_detect" in src, (
        "supplier_detect import missing — Global gate would not exist"
    )
    assert "_detect_global_supplier_for_batch" in src, (
        "Global-supplier-batch detector missing"
    )


# ── Global PL/EN renderer (operator-locked vocabulary) ───────────────────


@pytest.mark.parametrize("item_type,metal,stone,want_pl_starts,want_en_contains", [
    ("Ring",     "925 SILVER", "Plain Jewellery",
     "Pierścionek ze srebra próby 925",
     "925 Silver Plain Jewellery RING"),
    ("Ring",     "925 SILVER", "CZ Round Shape",
     "Pierścionek ze srebra próby 925 wysadzany cyrkoniami",
     "925 Silver CZ Stud Jewellery RING"),
    ("Pendant",  "925 SILVER", "Oval Shape Sapphire CZ Round Shape",
     "Wisiorek ze srebra próby 925 wysadzany cyrkoniami i kamieniami kolorowymi",
     "925 Silver CZ & Colour Stone Jewellery PENDANT"),
    ("Bracelet", "9KT GOLD",   "LAB ROUND DIA",
     "Bransoletka ze złota próby 375 z diamentami laboratoryjnymi",
     "09KT Gold Lab Grown Diamond Jewellery BRACELET"),
    ("Earrings", "14KT GOLD",  "LAB ROUND DIA",
     "Kolczyki ze złota próby 585 z diamentami laboratoryjnymi",
     "14KT Gold Lab Grown Diamond Jewellery EARRINGS"),
    ("Bangle",   "925 SILVER", "Oval shape CZ",
     "Bransoletka sztywna ze srebra próby 925 wysadzany cyrkoniami",
     "925 Silver CZ Stud Jewellery BANGLE"),
])
def test_global_render_pl_en_locked_rules(
    item_type, metal, stone, want_pl_starts, want_en_contains,
):
    from app.api.routes_dhl_clearance import _global_render_pl_en
    out = _global_render_pl_en(item_type, metal, stone)
    assert out["pl"] == want_pl_starts, (
        f"PL: got {out['pl']!r} expected {want_pl_starts!r}"
    )
    assert want_en_contains in out["en"], (
        f"EN: got {out['en']!r} expected to contain {want_en_contains!r}"
    )


def test_global_render_returns_empty_for_unmapped_type():
    """Unknown jewellery type must NOT produce a row — operator spec:
    never emit UNKNOWN. Caller skips."""
    from app.api.routes_dhl_clearance import _global_render_pl_en
    out = _global_render_pl_en("Unobtainium", "925 SILVER", "CZ")
    assert out["pl"] == ""
    assert out["en"] == ""


def test_global_render_returns_empty_for_unmapped_metal():
    """Unknown metal must NOT produce a row — operator spec:
    never emit metal szlachetny."""
    from app.api.routes_dhl_clearance import _global_render_pl_en
    out = _global_render_pl_en("Ring", "Tin", "CZ")
    assert out["pl"] == ""
    assert out["en"] == ""


# ── PDF parser robustness (regression for OCR-quirky rows) ────────────────


_FIXTURE_PDF = Path(
    r"C:\PZ\storage\outputs\SHIPMENT_4789974092_2026-05_999deef1"
    r"\source\packing\Global-inv-088 sggd.pdf"
)


def test_pdf_parser_handles_ocr_quirky_metal_columns():
    """Some rows have OCR-mangled style/metal blobs:
       "CSTR04794-J-HA9F25SL 1 ..."  — trailing "25SL" instead of "925SL"
       "JR08296 925SL/ 14KT CO 1M"   — multi-metal alloy + qty OCR 1M
    Both must still parse with metal=925 SILVER (canonical)."""
    if not _FIXTURE_PDF.exists():
        pytest.skip("production fixture missing")
    from app.services.global_packing_parser import parse_global_packing_pdf
    rows, _, _, diag = parse_global_packing_pdf(_FIXTURE_PDF)
    assert len(rows) == 245, f"expected 245 rows, got {len(rows)}"
    by_sr = {r["serial_no"]: r for r in rows}
    for sr in (93, 106, 181, 182):
        r = by_sr[sr]
        assert r["metal"] == "925 SILVER", (
            f"row sr={sr} expected metal=925 SILVER got {r['metal']!r}"
        )
        assert r["quantity"] == 1.0, (
            f"row sr={sr} expected qty=1 got {r['quantity']}"
        )


def test_pdf_parser_totals_reconcile_after_lenient_split():
    """After the lenient split for OCR-quirky rows, totals MUST still
    reconcile to the operator-locked values."""
    if not _FIXTURE_PDF.exists():
        pytest.skip("production fixture missing")
    from app.services.global_packing_parser import parse_global_packing_pdf
    _, _, _, diag = parse_global_packing_pdf(_FIXTURE_PDF)
    assert diag["total_qty"] == 245.0
    assert diag["total_fob_usd"] == pytest.approx(3172.00, abs=0.02)


# ── End-to-end: customs row injection from real packing_lines DB ─────────


def test_end_to_end_packing_lines_become_audit_rows(monkeypatch):
    """When packing.db has rows for a Global batch, _inject_rows_from_sources
    must use them as audit['rows'] — NOT the aggregate synthesizer."""
    import sys
    sys.path.insert(0, r"C:\Users\Super Fashion\PZ APP\engine")
    sys.path.insert(0, r"C:\Users\Super Fashion\PZ APP")

    audit_path = Path(
        r"C:\PZ\storage\outputs\SHIPMENT_4789974092_2026-05_999deef1\audit.json"
    )
    if not audit_path.exists():
        pytest.skip("production audit missing")

    # Point settings.storage_root at the production storage so the
    # supplier-detect helper can find GLOBAL Invoice.pdf in source/invoices.
    from app.core.config import settings as _s
    monkeypatch.setattr(_s, "storage_root",
                        Path(r"C:\PZ\storage"), raising=False)

    # Initialise packing_db pointing at production
    from app.services import packing_db
    packing_db.init_packing_db(Path(r"C:\PZ\storage\packing.db"))

    pkg = packing_db.get_packing_lines_for_batch(
        "SHIPMENT_4789974092_2026-05_999deef1"
    )
    if not pkg:
        pytest.skip("no packing_lines in production for this batch")

    from app.api.routes_dhl_clearance import _inject_rows_from_sources
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    audit.pop("rows", None)
    audit.pop("invoices", None)
    audit["invoice_names"] = ["GLOBAL Invoice.pdf"]
    audit2 = _inject_rows_from_sources(
        "SHIPMENT_4789974092_2026-05_999deef1", audit,
    )
    assert audit2.get("_rows_source") == "packing_lines", (
        f"expected source=packing_lines got {audit2.get('_rows_source')!r}"
    )
    assert audit2.get("rows"), "no rows produced"
    forbidden = ("UNKNOWN", "metal szlachetny", "Wyrób jubilerski",
                 "grouped invoice aggregate")
    for r in audit2["rows"]:
        text = (r.get("polish_customs_description","")
                + " " + r.get("description_en",""))
        for tok in forbidden:
            assert tok not in text, (
                f"row {r['product_code']} contains forbidden {tok!r}: {text!r}"
            )


# ── Estrella protection ──────────────────────────────────────────────────


def test_packing_injection_noop_when_no_global_supplier(tmp_path, monkeypatch):
    """Non-Global suppliers MUST pass through _inject_rows_from_packing_lines
    as a no-op. Verified by running with a batch that has no Global
    marker in any source file."""
    from app.core.config import settings as _s
    monkeypatch.setattr(_s, "storage_root", tmp_path, raising=False)
    batch_id = "ESTRELLA_TEST_BATCH"
    batch_dir = tmp_path / "outputs" / batch_id / "source"
    (batch_dir / "invoices").mkdir(parents=True)
    # Write a non-Global "invoice" PDF — minimal %PDF- header
    (batch_dir / "invoices" / "EJL-26-27-180.pdf").write_bytes(
        b"%PDF-1.7\n%Estrella EJL invoice content\n"
    )

    from app.api.routes_dhl_clearance import _inject_rows_from_packing_lines
    audit = {"batch_id": batch_id}
    out = _inject_rows_from_packing_lines(batch_id, audit)
    # Must NOT have populated rows and must NOT have set the empty-packing flag
    assert "rows" not in out
    assert "_global_packing_present_but_empty" not in out
