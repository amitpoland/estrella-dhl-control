"""test_global_invoice_position_parser.py

Pins the customs authority replacement: ONE row per commercial invoice
line (parsed directly from the GLOBAL Invoice PDF). The previous
packing-row aggregator collapsed distinct invoice positions into
artificial groups; this PR replaces that path with direct invoice-line
parsing.

Authority contract (operator-locked):
  - Customs row count = invoice commercial-line count
  - Per-position quantity / amount = sum of that position's product rows
  - Polish grammar uses "z" prefix:
        "z cyrkoniami"
        "z kamieniami kolorowymi"
        "z diamentami laboratoryjnymi"
        "ze srebra próby 925"
        "ze złota próby 375" / "ze złota próby 585"
  - No "wysadzany" prefix anywhere in customs descriptions
  - No artificial single-type labels like "PENDANT 242 PCS" when the
    position actually contains multiple jewellery types

Estrella protection: non-Global suppliers continue through the existing
chain (db invoice_lines → XLSX → synthesizer). The invoice-position
parser fires only when _detect_global_supplier_for_batch returns True.
"""
from __future__ import annotations

from pathlib import Path

import pytest


# ── Module API ───────────────────────────────────────────────────────────


def test_module_exposes_public_api():
    from app.services.global_invoice_position_parser import (
        parse_invoice_positions_from_text,
        parse_invoice_positions_from_pdf,
        positions_to_audit_rows,
        position_count,
    )
    for f in (parse_invoice_positions_from_text,
              parse_invoice_positions_from_pdf,
              positions_to_audit_rows,
              position_count):
        assert callable(f)


# ── Position header parsing ──────────────────────────────────────────────


def test_parser_recognises_pcs_header():
    from app.services.global_invoice_position_parser import (
        parse_invoice_positions_from_text,
    )
    text = (
        "PCS, 09KT Gold, LGD Gold Stud Jewell\n"
        "Bracelet 8.982 9.860 2.0 302.00 604.00 ext\n"
    )
    out = parse_invoice_positions_from_text(text)
    assert len(out) == 1
    p = out[0]
    assert p["unit"] == "PCS"
    assert p["metal_pl"] == "ze złota próby 375"
    assert p["stone_pl"] == "z diamentami laboratoryjnymi"
    assert p["quantity"] == 2.0
    assert p["amount"] == 604.00


def test_parser_recognises_prs_header():
    from app.services.global_invoice_position_parser import (
        parse_invoice_positions_from_text,
    )
    text = (
        "PRS, 14KT Gold, LGD Gold Stud Jewell\n"
        "Earrings 7.282 7.660 1.0 659.00 659.00 ext\n"
    )
    out = parse_invoice_positions_from_text(text)
    assert len(out) == 1
    assert out[0]["unit"] == "PRS"
    assert out[0]["metal_pl"] == "ze złota próby 585"


def test_parser_skips_unrecognised_header():
    from app.services.global_invoice_position_parser import (
        parse_invoice_positions_from_text,
    )
    # Header with no PCS/PRS prefix isn't a position
    text = (
        "Some unrelated header\n"
        "Bracelet 8.982 9.860 2.0 302.00 604.00\n"
    )
    out = parse_invoice_positions_from_text(text)
    assert out == []


# ── Operator-locked Polish grammar ───────────────────────────────────────


@pytest.mark.parametrize("metal_token,expected_pl", [
    ("09KT Gold",          "ze złota próby 375"),
    ("9KT Gold",           "ze złota próby 375"),
    ("14KT Gold",          "ze złota próby 585"),
    ("18KT Gold",          "ze złota próby 750"),
    ("22KT Gold",          "ze złota próby 916"),
    ("925 Purity Silver",  "ze srebra próby 925"),
    ("925 Silver",         "ze srebra próby 925"),
    ("PT950",              "z platyny próby 950"),
])
def test_metal_grammar_pl(metal_token, expected_pl):
    from app.services.global_invoice_position_parser import _normalize_metal
    _, pl, _ = _normalize_metal(metal_token)
    assert pl == expected_pl


@pytest.mark.parametrize("stones_text,expected_pl", [
    ("LGD Gold Stud Jewell",        "z diamentami laboratoryjnymi"),
    ("Lab Grown Diamond",           "z diamentami laboratoryjnymi"),
    ("Studed Jewellery CZ, CLS",    "z cyrkoniami i kamieniami kolorowymi"),
    ("Studed Jewellery CLS, CZ",    "z cyrkoniami i kamieniami kolorowymi"),
    ("Stud Jewelry DIA&CZ",         "z diamentami i cyrkoniami"),
    ("CZ Stud Silver Jew.",         "z cyrkoniami"),
    ("Plain Jewellery",             ""),
])
def test_stone_grammar_pl(stones_text, expected_pl):
    from app.services.global_invoice_position_parser import _normalize_stone
    pl, _ = _normalize_stone(stones_text)
    assert pl == expected_pl, (
        f"stone token {stones_text!r} expected {expected_pl!r}, got {pl!r}"
    )


def test_no_wysadzany_prefix_in_pl_grammar():
    """Operator spec: replace 'wysadzany' with 'z'. The new vocabulary
    must contain NO 'wysadzany' phrases anywhere in the stone table."""
    from app.services.global_invoice_position_parser import _STONE_RULES
    for _, pl, _ in _STONE_RULES:
        assert "wysadzany" not in pl, (
            f"stone vocabulary still contains 'wysadzany': {pl!r}"
        )


# ── Multi-row position aggregation ────────────────────────────────────────


def test_position_aggregates_multiple_product_rows():
    """A single PCS/PRS header followed by multiple product rows
    produces ONE position with summed qty + amount."""
    from app.services.global_invoice_position_parser import (
        parse_invoice_positions_from_text,
    )
    text = (
        "PCS, 925 Purity Silver, Studed Jewellery CZ, CLS\n"
        "Pendant 7.668 9.300 8.0 6.63 53.00 ext\n"
        "Ring 33.362 36.220 15.0 7.27 109.00 ext\n"
    )
    out = parse_invoice_positions_from_text(text)
    assert len(out) == 1
    p = out[0]
    assert p["quantity"] == 23.0  # 8 + 15
    assert p["amount"]   == 162.0  # 53 + 109
    assert len(p["rows"]) == 2
    types = {r["type"] for r in p["rows"]}
    assert types == {"PENDANT", "RING"}


def test_position_separates_different_headers():
    """Two distinct PCS headers produce TWO positions even when they
    share metal — different stones = different invoice lines."""
    from app.services.global_invoice_position_parser import (
        parse_invoice_positions_from_text,
    )
    text = (
        "PCS, 925 Purity Silver, Studed Jewellery CZ, CLS\n"
        "Pendant 7.668 9.300 8.0 6.63 53.00 ext\n"
        "PCS, 925 Purity Silver, Stud Jewelry DIA&CZ\n"
        "Ring 6.584 7.914 2.0 23.00 46.00 ext\n"
    )
    out = parse_invoice_positions_from_text(text)
    assert len(out) == 2
    assert "z cyrkoniami i kamieniami kolorowymi" in out[0]["stone_pl"]
    assert "z diamentami i cyrkoniami"             in out[1]["stone_pl"]


# ── Audit-row shape from positions ────────────────────────────────────────


def test_positions_to_audit_rows_shape():
    from app.services.global_invoice_position_parser import (
        parse_invoice_positions_from_text, positions_to_audit_rows,
    )
    text = (
        "PCS, 925 Purity Silver, Studed Jewellery CZ, CLS\n"
        "Pendant 7.668 9.300 8.0 6.63 53.00 ext\n"
        "Ring 33.362 36.220 15.0 7.27 109.00 ext\n"
    )
    positions = parse_invoice_positions_from_text(text)
    rows = positions_to_audit_rows(positions, invoice_no="088/2026-2027")
    assert len(rows) == 1
    r = rows[0]
    # Required reconciler fields
    assert r["invoice_number"]            == "088/2026-2027"
    assert r["line_position"]             == 1
    assert r["product_code"]              == "088/2026-2027-INV-01"
    assert r["quantity"]                  == 23.0
    assert r["line_total"]                == 162.00
    assert r["uom"]                       == "PCS"
    # Operator-locked PL grammar
    assert r["polish_customs_description"] == (
        "Wisiorki, Pierścionki ze srebra próby 925 "
        "z cyrkoniami i kamieniami kolorowymi"
    )
    # EN
    assert "925 Silver CZ & Colour Stone Jewellery" in r["description_en"]
    assert "PENDANTS, RINGS" in r["description_en"]
    # Source markers
    assert r["_rows_source"] == "invoice_positions_authority"
    assert r["_supplier_profile"] == "global_jewellery"


def test_audit_rows_contain_no_forbidden_tokens():
    from app.services.global_invoice_position_parser import (
        parse_invoice_positions_from_text, positions_to_audit_rows,
    )
    text = (
        "PCS, 09KT Gold, LGD Gold Stud Jewell\n"
        "Bracelet 8.982 9.860 2.0 302.00 604.00 ext\n"
        "PCS, 925 Purity Silver, Plain Jewellery\n"
        "Ring 8.810 8.810 1.0 12.00 12.00 ext\n"
    )
    rows = positions_to_audit_rows(
        parse_invoice_positions_from_text(text),
        invoice_no="088/2026-2027",
    )
    for r in rows:
        text_blob = (r["polish_customs_description"] + " " + r["description_en"])
        for tok in ("UNKNOWN", "metal szlachetny", "Wyrób jubilerski",
                    "grouped invoice aggregate", "wysadzany"):
            assert tok not in text_blob, (
                f"row {r['product_code']} contains forbidden {tok!r}"
            )


# ── Production fixture end-to-end (skipped when file missing) ────────────


_FIXTURE_PDF = Path(
    r"C:\PZ\storage\outputs\SHIPMENT_4789974092_2026-05_999deef1"
    r"\source\invoices\GLOBAL Invoice.pdf"
)


def test_production_invoice_parses_to_10_positions():
    """The Global 088 invoice must produce exactly 10 commercial-line
    positions (PCS x 6 + PRS x 4) — one per "PCS,/PRS, <metal>, <stones>"
    header in the invoice."""
    if not _FIXTURE_PDF.exists():
        pytest.skip("production fixture missing")
    from app.services.global_invoice_position_parser import (
        parse_invoice_positions_from_pdf,
    )
    positions = parse_invoice_positions_from_pdf(_FIXTURE_PDF)
    assert len(positions) == 10, (
        f"expected 10 invoice positions, got {len(positions)}: "
        + ", ".join(f"{p['unit']}+{p['metal_pl']}+{p['stone_pl']}" for p in positions)
    )
    units = [p["unit"] for p in positions]
    assert units.count("PCS") == 6
    assert units.count("PRS") == 4


def test_production_invoice_qty_totals_reconcile_to_245():
    if not _FIXTURE_PDF.exists():
        pytest.skip("production fixture missing")
    from app.services.global_invoice_position_parser import (
        parse_invoice_positions_from_pdf,
    )
    positions = parse_invoice_positions_from_pdf(_FIXTURE_PDF)
    pcs = sum(p["quantity"] for p in positions if p["unit"] == "PCS")
    prs = sum(p["quantity"] for p in positions if p["unit"] == "PRS")
    assert int(pcs) == 183
    assert int(prs) == 62
    assert int(pcs + prs) == 245


def test_production_invoice_fob_sum_reconciles_to_3172():
    if not _FIXTURE_PDF.exists():
        pytest.skip("production fixture missing")
    from app.services.global_invoice_position_parser import (
        parse_invoice_positions_from_pdf,
    )
    positions = parse_invoice_positions_from_pdf(_FIXTURE_PDF)
    total = round(sum(p["amount"] for p in positions), 2)
    assert total == 3172.00, f"FOB sum {total} != 3172.00"


def test_production_audit_rows_count_matches_positions():
    if not _FIXTURE_PDF.exists():
        pytest.skip("production fixture missing")
    from app.services.global_invoice_position_parser import (
        parse_invoice_positions_from_pdf, positions_to_audit_rows,
    )
    positions = parse_invoice_positions_from_pdf(_FIXTURE_PDF)
    rows = positions_to_audit_rows(positions, "088/2026-2027")
    assert len(rows) == len(positions) == 10, (
        "1-to-1 mapping required: customs row count must equal "
        "invoice position count"
    )


# ── Chain wiring at the route layer ──────────────────────────────────────


_ROUTES = (
    Path(__file__).resolve().parent.parent
    / "app" / "api" / "routes_dhl_clearance.py"
)


def test_inject_chain_invokes_invoice_position_parser_for_global():
    src = _ROUTES.read_text(encoding="utf-8")
    assert "_try_inject_invoice_positions_for_global" in src
    # The chain must call the helper BEFORE the packing path so that
    # invoice-position rows win when the supplier is Global.
    idx_chain = src.find("def _inject_rows_from_sources(")
    body = src[idx_chain : idx_chain + 4000]
    i_inv  = body.find("_try_inject_invoice_positions_for_global")
    i_pack = body.find("_inject_rows_from_packing_lines(")
    assert 0 < i_inv < i_pack, (
        "invoice-position parser must run BEFORE packing path"
    )


def test_inject_chain_gates_on_global_supplier():
    """The invoice-position step must check _detect_global_supplier_for_batch
    so Estrella batches are not affected."""
    src = _ROUTES.read_text(encoding="utf-8")
    idx_chain = src.find("def _inject_rows_from_sources(")
    body = src[idx_chain : idx_chain + 4000]
    assert "_detect_global_supplier_for_batch" in body
    assert "customs_view == \"invoice_positions\"" in body


# ── Out-of-scope guard ────────────────────────────────────────────────────


def test_parser_does_not_compute_fiscal_or_customs_values():
    """Module must consume invoice text; never compute CIF/duty/VAT."""
    path = (Path(__file__).resolve().parent.parent
            / "app" / "services" / "global_invoice_position_parser.py")
    body = path.read_text(encoding="utf-8")
    forbidden = (
        "compute_cif", "DHL_BROKER_THRESHOLD", "duty_pln", "vat_pln",
        "WFIRMA_CREATE_", "create_invoice", "create_pz",
        "_guard_wfirma_export",
    )
    for tok in forbidden:
        assert tok not in body, f"parser must not reference {tok!r}"


def test_parser_does_not_import_estrella_modules():
    path = (Path(__file__).resolve().parent.parent
            / "app" / "services" / "global_invoice_position_parser.py")
    body = path.read_text(encoding="utf-8")
    forbidden_imports = (
        "invoice_intake_parser", "customs_description_engine",
        "product_identity_engine", "description_engine",
        "global_invoice_parser", "global_packing_parser",
    )
    for tok in forbidden_imports:
        assert tok not in body, (
            f"parser must not import {tok!r}"
        )
