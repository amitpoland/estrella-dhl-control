"""test_global_jewellery_supplier_profile.py

Tests the permanent Global Jewellery Pvt. Ltd. supplier profile:
detector, type/metal/stone normalisers, bilingual PL/EN description
rules engine, per-line extractor from invoice raw text, and the
row-builder entry point used by routes_dhl_clearance.

Invoice 088/2026-2027 (AWB 4789974092) drives the fixture-based
end-to-end test:
  - 14 product rows distributed across 5 jewellery types
  - sum of line_total_usd = 3172.00 (matches engine-parsed FOB)
  - 183 PCS + 62 PRS = 245 units total

Estrella protection: this module is isolated. Estrella regression
test files are not affected; the dispatcher in
_synthesize_rows_from_invoice_aggregates falls through for any
non-Global supplier.
"""
from __future__ import annotations

from pathlib import Path

import pytest


# ── Operator-fixed Rule A–E test cases ────────────────────────────────────


@pytest.mark.parametrize("type_,metal,stone,want_pl,want_en", [
    # Rule A
    ("Ring", "925 Purity Silver", "Plain",
     "Pierścionek ze srebra próby 925",
     "925 Silver Plain Jewellery RING"),
    # Rule B
    ("Ring", "925 Purity Silver", "CZ",
     "Pierścionek ze srebra próby 925 wysadzany cyrkoniami",
     "925 Silver CZ Stud Jewellery RING"),
    # Rule C — CZ + Colour Stone combination
    ("Pendant", "925 Purity Silver", "Studed Jewellery CZ, CLS",
     "Wisiorek ze srebra próby 925 wysadzany cyrkoniami i kamieniami kolorowymi",
     "925 Silver CZ & Colour Stone Jewellery PENDANT"),
    # Rule D — LGD
    ("Earrings", "14KT Gold", "LGD Gold Stud Jewell",
     "Kolczyki ze złota próby 585 z diamentami laboratoryjnymi",
     "14KT Gold Lab Grown Diamond Jewellery EARRINGS"),
    # Rule E — 09KT Gold LGD Bracelet
    ("Bracelet", "09KT Gold", "LGD Gold Stud Jewell",
     "Bransoletka ze złota próby 375 z diamentami laboratoryjnymi",
     "09KT Gold Lab Grown Diamond Jewellery BRACELET"),
])
def test_render_description_locked_rules(type_, metal, stone, want_pl, want_en):
    from app.services.global_jewellery_supplier_profile import render_description
    out = render_description(type_, metal, stone)
    assert out["pl"] == want_pl, f"PL mismatch: {out['pl']!r} != {want_pl!r}"
    assert out["en"] == want_en, f"EN mismatch: {out['en']!r} != {want_en!r}"
    assert out["item_type"], "item_type must be set so engine grouping works"
    assert out["item_type_pl"], "item_type_pl must be set so engine PL render works"


# ── Type normalisation ────────────────────────────────────────────────────


@pytest.mark.parametrize("raw,want", [
    ("Ring", "RING"),
    ("ring", "RING"),
    ("Earring", "EARRING"),     # singular form preserved as canonical key
    ("Earrings", "EARRINGS"),
    ("Bracelet", "BRACELET"),
    ("Bangle", "BANGLE"),
    ("Pendant", "PENDANT"),
])
def test_normalize_type(raw, want):
    from app.services.global_jewellery_supplier_profile import normalize_type
    assert normalize_type(raw) == want


def test_normalize_type_returns_none_for_unknown():
    """Operator spec: NEVER emit placeholder for unknown jewellery
    type. Detector returns None so the caller can fall back."""
    from app.services.global_jewellery_supplier_profile import normalize_type
    assert normalize_type("Cufflink") is not None  # this one IS in the table
    assert normalize_type("Unobtainium") is None
    assert normalize_type("") is None
    assert normalize_type(None) is None  # type: ignore[arg-type]


# ── Metal normalisation ───────────────────────────────────────────────────


@pytest.mark.parametrize("raw,want_pl,want_en", [
    ("925 Purity Silver", "ze srebra próby 925", "925 Silver"),
    ("925 Silver",        "ze srebra próby 925", "925 Silver"),
    ("14KT Gold",         "ze złota próby 585",  "14KT Gold"),
    ("14 KT Gold",        "ze złota próby 585",  "14KT Gold"),
    ("09KT Gold",         "ze złota próby 375",  "09KT Gold"),
    ("9KT Gold",          "ze złota próby 375",  "09KT Gold"),
    ("18KT Gold",         "ze złota próby 750",  "18KT Gold"),
    ("22KT Gold",         "ze złota próby 916",  "22KT Gold"),
    ("PT950",             "z platyny próby 950", "PT950 Platinum"),
])
def test_normalize_metal(raw, want_pl, want_en):
    from app.services.global_jewellery_supplier_profile import normalize_metal
    out = normalize_metal(raw)
    assert out is not None, f"metal {raw!r} not recognised"
    assert out["pl"] == want_pl
    assert out["en"] == want_en


def test_normalize_metal_returns_none_for_unknown():
    """No 'metal szlachetny' fallback — caller must decide."""
    from app.services.global_jewellery_supplier_profile import normalize_metal
    assert normalize_metal("Tin") is None
    assert normalize_metal("") is None


# ── Stone normalisation ───────────────────────────────────────────────────


def test_stone_plain_when_no_match():
    """No-stone case maps to plain (caller composes 'Plain Jewellery')."""
    from app.services.global_jewellery_supplier_profile import normalize_stone
    out = normalize_stone("Plain Jewellery")
    assert out["pl"] == ""
    assert out["en"] == "Plain Jewellery"


def test_stone_cz_alone():
    from app.services.global_jewellery_supplier_profile import normalize_stone
    out = normalize_stone("CZ Stud Jewellery")
    assert "cyrkoniami" in out["pl"]
    assert "CZ" in out["en"]


def test_stone_cz_plus_colour_stone():
    from app.services.global_jewellery_supplier_profile import normalize_stone
    out = normalize_stone("Studed Jewellery CZ, CLS")
    assert "cyrkoniami i kamieniami kolorowymi" in out["pl"]
    assert "Colour Stone" in out["en"]


def test_stone_lgd_lab_grown_diamond():
    from app.services.global_jewellery_supplier_profile import normalize_stone
    out = normalize_stone("LGD Gold Stud Jewell")
    assert "diamentami laboratoryjnymi" in out["pl"]
    assert "Lab Grown Diamond" in out["en"]


# ── Detector ──────────────────────────────────────────────────────────────


def test_is_global_jewellery_invoice_via_format_field():
    from app.services.global_jewellery_supplier_profile import is_global_jewellery_invoice
    assert is_global_jewellery_invoice({"invoice_format": "global_jewellery"})
    assert is_global_jewellery_invoice({"invoice_format": "GLOBAL_JEWELLERY"})


def test_is_global_jewellery_invoice_via_raw_text():
    """Fallback path when invoice_format wasn't set by upstream parsers."""
    from app.services.global_jewellery_supplier_profile import is_global_jewellery_invoice
    assert is_global_jewellery_invoice({
        "_raw_text": "Some content\nGlobal Jewellery Pvt. Ltd. INVOICE\n…",
    })


def test_is_global_jewellery_invoice_false_for_estrella():
    """Estrella protection: detector MUST be False for EJL invoices."""
    from app.services.global_jewellery_supplier_profile import is_global_jewellery_invoice
    estrella_inv = {
        "invoice_format": "ejl",
        "invoice_no": "EJL/26-27/180",
        "_raw_text": "Estrella Jewels Sp. z o.o…  EJL/26-27/180  ",
    }
    assert is_global_jewellery_invoice(estrella_inv) is False


def test_is_global_jewellery_invoice_false_for_empty_input():
    from app.services.global_jewellery_supplier_profile import is_global_jewellery_invoice
    assert is_global_jewellery_invoice(None) is False
    assert is_global_jewellery_invoice({}) is False


# ── Per-line extractor (the heart of the parser) ──────────────────────────


# Excerpt of the real Global-088 invoice raw text, exactly as pdfplumber
# returns it (verified against C:\PZ\storage\outputs\…\source\invoices\
# GLOBAL Invoice.pdf during this PR).
_GLOBAL_088_RAW = """\
Marks & Nos./ No. & Kind of Pkgs Description of Goods NetWt GrossWt Quantity Rate AmountUS$
Container No. (Gms) (Gms)
As Add One Tin Box 71131149
CZ, Colour Stone, Diamond, LGD Studded / Plain / Comb SL925/14KT, 09KT / 14KT Gold / 925 Silver Jewellery
PCS, 09KT Gold, LGD Gold Stud Jewell
Bracelet 8.982 9.860 2.0 302.00 604.00 09KT Gold, LGD Gold Stud Jewellery Bracelet 2.0 0.005 302.00
PCS, 925 Purity Silver, Studed Jewellery CZ, CLS
Pendant 7.668 9.300 8.0 6.63 53.00 925 Purity Silver, Studed Jewellery CZ, CLS Pendant 8.0 0.001 6.63
Ring 33.362 36.220 15.0 7.27 109.00 925 Purity Silver, Studed Jewellery CZ, CLS Ring 15.0 0.002 7.27
PCS, 925 Purity Silver, Stud Jewelry DIA&CZ
Ring 6.584 7.914 2.0 23.00 46.00 925 Purity Silver, Stud Jewelry DIA&CZ Ring 2.0 0.004 23.00
PCS, 925 Purity Silver, CZ Stud Silver Jew.
Bangle 11.806 12.080 2.0 11.50 23.00 925 Purity Silver, CZ Stud Silver Jewellery Bangle 2.0 0.006 11.50
Bracelet 8.780 11.720 1.0 23.00 23.00 925 Purity Silver, CZ Stud Silver Jewellery Bracelet 1.0 0.012 23.00
Pendant 60.637 63.972 49.0 5.80 284.00 925 Purity Silver, CZ Stud Silver Jewellery Pendant 49.0 0.001 5.80
Ring 223.087 256.097 101.0 7.28 735.00 925 Purity Silver, CZ Stud Silver Jewellery Ring 101.0 0.003 7.28
PCS, 925 Purity Silver, Silver CZ Stud 14k Com Jew
Ring 2.260 2.530 2.0 80.50 161.00 925 Purity Silver, Silver CZ Stud 14k Com Jew Ring 2.0 0.001 80.50
PCS, 925 Purity Silver, Plain Jewellery
Ring 8.810 8.810 1.0 12.00 12.00 925 Purity Silver, Plain Jewellery Ring 1.0 0.009 12.00
PRS, 14KT Gold, LGD Gold Stud Jewell
Earrings 7.282 7.660 1.0 659.00 659.00 14KT Gold, LGD Gold Stud Jewellery Earring 1.0 0.008 659.00
PRS, 925 Purity Silver, Studed Jewellery CLS, CZ
Earrings 8.217 9.020 4.0 14.50 58.00 925 Purity Silver, CZ Stud Silver Jewellery Earring 4.0 0.002 14.50
PRS, 925 Purity Silver, CZ Stud Silver Jew.
Earrings 64.617 68.800 56.0 7.14 400.00 925 Purity Silver, CZ Stud Silver Jewellery Earring 56.0 0.001 7.14
PRS, 925 Purity Silver, Plain Jewellery
Earrings 1.120 1.120 1.0 5.00 5.00 925 Purity Silver, Plain Jewellery Earring 1.0 0.001 5.00
"""


def test_extract_lines_count():
    """The Global 088 invoice has 14 product rows."""
    from app.services.global_jewellery_supplier_profile import extract_lines_from_text
    rows = extract_lines_from_text(_GLOBAL_088_RAW)
    assert len(rows) == 14, f"expected 14 rows, got {len(rows)}: {[r['type'] for r in rows]}"


def test_extract_lines_amount_sums_to_3172():
    """Per-line amount column must sum exactly to declared FOB."""
    from app.services.global_jewellery_supplier_profile import extract_lines_from_text
    rows = extract_lines_from_text(_GLOBAL_088_RAW)
    total = round(sum(r["line_total_usd"] for r in rows), 2)
    assert total == 3172.00, f"row sum {total} != 3172.00"


def test_extract_lines_qty_split_pcs_prs():
    """183 PCS + 62 PRS = 245 total."""
    from app.services.global_jewellery_supplier_profile import extract_lines_from_text
    rows = extract_lines_from_text(_GLOBAL_088_RAW)
    pcs = int(round(sum(r["quantity"] for r in rows if r["unit"] == "PCS")))
    prs = int(round(sum(r["quantity"] for r in rows if r["unit"] == "PRS")))
    assert pcs == 183, f"PCS sum {pcs} != 183"
    assert prs == 62,  f"PRS sum {prs} != 62"


def test_extract_lines_inherit_metal_and_stone():
    """Each item row inherits metal + stone from its preceding PCS,/PRS,
    category header until a new header appears."""
    from app.services.global_jewellery_supplier_profile import extract_lines_from_text
    rows = extract_lines_from_text(_GLOBAL_088_RAW)
    # First row: PCS Bracelet 09KT Gold LGD
    r0 = rows[0]
    assert r0["unit"] == "PCS"
    assert r0["type"] == "BRACELET"
    assert "09KT Gold" in r0["metal_raw"] or "9KT Gold" in r0["metal_raw"].replace("09KT", "9KT")
    assert "LGD" in r0["stone_raw"]
    # First PRS row: Earrings 14KT Gold LGD
    prs_rows = [r for r in rows if r["unit"] == "PRS"]
    assert prs_rows, "no PRS rows extracted"
    assert "14KT Gold" in prs_rows[0]["metal_raw"]


# ── Row builder: end-to-end with reconciliation ──────────────────────────


def test_build_global_invoice_rows_full_088():
    """End-to-end against the 088 fixture: every row should render with
    a non-empty PL + EN description, and the sum reconciles to 3172."""
    from app.services.global_jewellery_supplier_profile import build_global_invoice_rows
    rows = build_global_invoice_rows(
        invoice_no="088/2026-2027",
        raw_text=_GLOBAL_088_RAW,
        declared_fob=3172.00,
    )
    assert len(rows) == 14, f"expected 14 rows, got {len(rows)}"
    # Every row must have non-empty bilingual descriptions
    for r in rows:
        assert r["polish_customs_description"], (
            f"row {r['product_code']} has empty PL description"
        )
        assert r["description_en"], (
            f"row {r['product_code']} has empty EN description"
        )
        assert r["item_type"], (
            f"row {r['product_code']} has empty item_type"
        )
        assert r["uom"] in ("PCS", "PRS"), (
            f"row {r['product_code']} uom {r['uom']!r} not in PCS/PRS"
        )
    total = round(sum(r["line_total"] for r in rows), 2)
    assert total == 3172.00


def test_build_global_invoice_rows_product_codes_sequential():
    """Product codes follow rule: <invoice_no>-<seq>."""
    from app.services.global_jewellery_supplier_profile import build_global_invoice_rows
    rows = build_global_invoice_rows(
        invoice_no="088/2026-2027",
        raw_text=_GLOBAL_088_RAW,
        declared_fob=3172.00,
    )
    codes = [r["product_code"] for r in rows]
    expected = [f"088/2026-2027-{i}" for i in range(1, 15)]
    assert codes == expected


def test_build_global_invoice_rows_no_unknown_strings():
    """Operator spec: NEVER emit UNKNOWN / metal szlachetny / generic
    placeholder text."""
    from app.services.global_jewellery_supplier_profile import build_global_invoice_rows
    rows = build_global_invoice_rows(
        invoice_no="088/2026-2027",
        raw_text=_GLOBAL_088_RAW,
        declared_fob=3172.00,
    )
    forbidden = ("UNKNOWN", "metal szlachetny", "Wyrób jubilerski",
                 "grouped invoice aggregate")
    for r in rows:
        for tok in forbidden:
            assert tok not in r["polish_customs_description"], (
                f"row {r['product_code']} PL desc contains forbidden {tok!r}"
            )
            assert tok not in r["description_en"], (
                f"row {r['product_code']} EN desc contains forbidden {tok!r}"
            )


def test_build_global_invoice_rows_returns_empty_when_no_text():
    from app.services.global_jewellery_supplier_profile import build_global_invoice_rows
    assert build_global_invoice_rows("088/2026-2027", "", 3172.0) == []


def test_build_global_invoice_rows_returns_empty_when_sum_doesnt_reconcile():
    """Reconciliation safety: if extracted rows don't sum to declared
    FOB, return empty so caller falls back. We must never emit rows
    the downstream reconciler would reject anyway."""
    from app.services.global_jewellery_supplier_profile import build_global_invoice_rows
    # Tell builder the FOB is 9999 — extracted sum is 3172, off by 6827
    rows = build_global_invoice_rows(
        invoice_no="088/2026-2027",
        raw_text=_GLOBAL_088_RAW,
        declared_fob=9999.00,
    )
    assert rows == []


def test_build_global_invoice_rows_supplier_profile_marker():
    """Every emitted row carries the _supplier_profile marker so
    downstream code can identify the source."""
    from app.services.global_jewellery_supplier_profile import build_global_invoice_rows
    rows = build_global_invoice_rows(
        invoice_no="088/2026-2027",
        raw_text=_GLOBAL_088_RAW,
        declared_fob=3172.00,
    )
    for r in rows:
        assert r["_supplier_profile"] == "global_jewellery"


# ── Item-type grouping (operator's customs-description output spec) ──────


def test_full_088_groups_into_expected_jewellery_types():
    """Operator spec: customs description should show Rings / Pendants /
    Earrings / Bracelets / Bangles. The item_type values on rows must
    match this set."""
    from app.services.global_jewellery_supplier_profile import build_global_invoice_rows
    rows = build_global_invoice_rows(
        invoice_no="088/2026-2027",
        raw_text=_GLOBAL_088_RAW,
        declared_fob=3172.00,
    )
    types = {r["item_type"] for r in rows}
    assert "RING"      in types
    assert "PENDANT"   in types
    assert "EARRINGS"  in types
    assert "BRACELET"  in types
    assert "BANGLE"    in types


# ── Exporter's Ref invoice number extraction ─────────────────────────────


def test_extract_invoice_number_from_text_finds_global_ref():
    """The Global Exporter's Ref pattern ``NNN/YYYY-YYYY`` (e.g.
    088/2026-2027) is the canonical invoice number for product_code
    generation."""
    from app.services.global_jewellery_supplier_profile import extract_invoice_number_from_text
    sample = (
        "Global Jewellery Pvt. Ltd. INVOICE\n"
        "Exporter's Ref :\n"
        "088/2026-2027 RBI Code: BG-003730\n"
    )
    assert extract_invoice_number_from_text(sample) == "088/2026-2027"


def test_extract_invoice_number_handles_various_widths():
    from app.services.global_jewellery_supplier_profile import extract_invoice_number_from_text
    assert extract_invoice_number_from_text("Ref: 7/2025-2026") == "7/2025-2026"
    assert extract_invoice_number_from_text("Ref: 1234/2025-2026") == "1234/2025-2026"


def test_extract_invoice_number_returns_none_when_absent():
    from app.services.global_jewellery_supplier_profile import extract_invoice_number_from_text
    assert extract_invoice_number_from_text("no number here") is None
    assert extract_invoice_number_from_text("") is None


# ── Estrella protection ───────────────────────────────────────────────────


def test_supplier_profile_isolated_from_estrella_paths():
    """The supplier-profile module must NOT import or modify any
    Estrella supplier code (invoice_intake_parser, customs_description_engine,
    product_identity_engine, description_engine)."""
    src = Path(__file__).resolve().parent.parent / "app" / "services" \
          / "global_jewellery_supplier_profile.py"
    body = src.read_text(encoding="utf-8")
    forbidden_imports = (
        "from ..services.invoice_intake_parser",
        "from ..services.customs_description_engine",
        "from ..services.product_identity_engine",
        "from ..services.description_engine",
        "import customs_description_engine",
    )
    for tok in forbidden_imports:
        assert tok not in body, (
            f"supplier profile module must not import Estrella code: {tok!r}"
        )


def test_no_cif_or_threshold_logic_in_supplier_profile():
    """Profile must consume engine output, never re-derive CIF / freight /
    insurance / customs threshold."""
    src = Path(__file__).resolve().parent.parent / "app" / "services" \
          / "global_jewellery_supplier_profile.py"
    body = src.read_text(encoding="utf-8")
    forbidden = (
        "DHL_BROKER_THRESHOLD", "_customs_threshold", "compute_cif",
        "WFIRMA_CREATE_", "create_invoice", "create_pz",
        "_guard_wfirma_export",
    )
    for tok in forbidden:
        assert tok not in body, f"supplier profile must not reference {tok!r}"


# ── Synthesizer integration (route layer wiring) ─────────────────────────


def test_synthesizer_imports_global_supplier_profile():
    """The route-layer synthesizer must import and dispatch to the
    Global Jewellery profile before falling through to the generic
    aggregate path."""
    p = (Path(__file__).resolve().parent.parent
         / "app" / "api" / "routes_dhl_clearance.py")
    body = p.read_text(encoding="utf-8")
    assert "global_jewellery_supplier_profile" in body, (
        "_synthesize_rows_from_invoice_aggregates must import the profile"
    )
    # And the dispatch must happen INSIDE the synthesizer loop BEFORE
    # the aggregate fallback (groups list construction).
    idx_syn  = body.find("def _synthesize_rows_from_invoice_aggregates(")
    idx_call = body.find("is_global_jewellery_invoice(", idx_syn)
    idx_grp  = body.find("groups: list[tuple[str, int]]", idx_syn)
    assert 0 < idx_call < idx_grp, (
        "Global profile dispatch must run before aggregate fallback"
    )
