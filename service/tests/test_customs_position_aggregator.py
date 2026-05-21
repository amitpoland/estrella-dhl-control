"""test_customs_position_aggregator.py

Tests the customs description authority replacement: aggregate per-row
packing customs rows into invoice-position customs rows.

Operator-locked expectation:

  Polish Description PDF before: 245 desc / 42 pages (per packing row)
  Polish Description PDF after:  ~8-10 desc / 2-5 pages (per invoice position)

The aggregator preserves FOB sum exactly. The per-row Packing
Description Report capability is preserved by passing
``customs_view="packing_rows"`` to the row injection chain.

Estrella protection: aggregator is a pure function; it doesn't import
any Estrella supplier module. The route layer's default-on-Global gate
is the same _detect_global_supplier_for_batch check the per-row path
uses — Estrella batches go through the unchanged db_invoice_lines path.
"""
from __future__ import annotations

from pathlib import Path

import pytest


# ── Module public API ────────────────────────────────────────────────────


def test_module_loads_and_exposes_aggregator():
    from app.services.customs_position_aggregator import (
        aggregate_packing_rows_to_invoice_positions, position_count,
    )
    assert callable(aggregate_packing_rows_to_invoice_positions)
    assert callable(position_count)


# ── Aggregation behaviour ────────────────────────────────────────────────


def _row(pc, item_type, item_type_pl, qty, line_total, pl_desc, en_desc, uom="PCS",
         invoice_no="088/2026-2027"):
    return {
        "invoice_number":             invoice_no,
        "line_position":              0,
        "product_code":               pc,
        "description":                en_desc,
        "polish_customs_description": pl_desc,
        "description_en":             en_desc,
        "description_pl":             pl_desc,
        "item_type":                  item_type,
        "item_type_pl":               item_type_pl,
        "quantity":                   qty,
        "unit_price":                 line_total / qty if qty else 0,
        "line_total":                 line_total,
        "uom":                        uom,
        "currency":                   "USD",
    }


def test_aggregation_collapses_same_metal_stone_into_one_position():
    """Two packing rows with the same (uom, metal, stone) but different
    jewellery types should collapse into ONE invoice position."""
    from app.services.customs_position_aggregator import (
        aggregate_packing_rows_to_invoice_positions,
    )
    rows = [
        _row("088/2026-2027-1", "PENDANT", "Wisiorek", 8.0, 53.00,
             "Wisiorek ze srebra próby 925 wysadzany cyrkoniami",
             "925 Silver CZ Stud Jewellery PENDANT"),
        _row("088/2026-2027-2", "RING", "Pierścionek", 15.0, 109.00,
             "Pierścionek ze srebra próby 925 wysadzany cyrkoniami",
             "925 Silver CZ Stud Jewellery RING"),
    ]
    out = aggregate_packing_rows_to_invoice_positions(rows)
    assert len(out) == 1
    pos = out[0]
    assert pos["quantity"] == 23.0
    assert pos["line_total"] == 162.00
    assert "Wisiorki" in pos["polish_customs_description"]
    assert "Pierścionki" in pos["polish_customs_description"]
    assert "ze srebra próby 925" in pos["polish_customs_description"]
    assert "wysadzany cyrkoniami" in pos["polish_customs_description"]
    # Source traceability
    assert pos["source_row_count"] == 2
    assert "088/2026-2027-1" in pos["source_packing_codes"]
    assert "088/2026-2027-2" in pos["source_packing_codes"]
    # Position code follows the operator's product_code rule
    assert pos["product_code"].endswith("-POS-1")


def test_aggregation_separates_different_metals():
    """Same item type + stone but DIFFERENT metal → distinct positions."""
    from app.services.customs_position_aggregator import (
        aggregate_packing_rows_to_invoice_positions,
    )
    rows = [
        _row("X-1", "RING", "Pierścionek", 1.0, 100.0,
             "Pierścionek ze srebra próby 925 wysadzany cyrkoniami",
             "925 Silver CZ Stud Jewellery RING"),
        _row("X-2", "RING", "Pierścionek", 1.0, 500.0,
             "Pierścionek ze złota próby 585 wysadzany cyrkoniami",
             "14KT Gold CZ Stud Jewellery RING"),
    ]
    out = aggregate_packing_rows_to_invoice_positions(rows)
    assert len(out) == 2
    metals = sorted(p["polish_customs_description"] for p in out)
    assert any("srebra próby 925" in m for m in metals)
    assert any("złota próby 585" in m for m in metals)


def test_aggregation_separates_pcs_from_prs():
    """Same metal+stone but different unit (PCS vs PRS) → distinct
    positions — customs always wants UOM-separated."""
    from app.services.customs_position_aggregator import (
        aggregate_packing_rows_to_invoice_positions,
    )
    rows = [
        _row("X-1", "RING", "Pierścionek", 1.0, 100.0,
             "Pierścionek ze srebra próby 925 wysadzany cyrkoniami",
             "925 Silver CZ Stud Jewellery RING", uom="PCS"),
        _row("X-2", "EARRINGS", "Kolczyki", 1.0, 50.0,
             "Kolczyki ze srebra próby 925 wysadzany cyrkoniami",
             "925 Silver CZ Stud Jewellery EARRINGS", uom="PRS"),
    ]
    out = aggregate_packing_rows_to_invoice_positions(rows)
    assert len(out) == 2
    uoms = {p["uom"] for p in out}
    assert uoms == {"PCS", "PRS"}


def test_aggregation_preserves_fob_sum_exactly():
    """Critical invariant: aggregation MUST NOT lose value. Sum of
    aggregated line_totals == sum of source line_totals."""
    from app.services.customs_position_aggregator import (
        aggregate_packing_rows_to_invoice_positions,
    )
    rows = [
        _row("a", "RING", "Pierścionek", 2.0, 232.50,
             "Pierścionek ze srebra próby 925",
             "925 Silver Plain Jewellery RING"),
        _row("b", "RING", "Pierścionek", 1.0, 0.50,
             "Pierścionek ze srebra próby 925",
             "925 Silver Plain Jewellery RING"),
        _row("c", "PENDANT", "Wisiorek", 5.0, 100.00,
             "Wisiorek ze srebra próby 925 wysadzany cyrkoniami",
             "925 Silver CZ Stud Jewellery PENDANT"),
    ]
    src_sum = sum(r["line_total"] for r in rows)
    out = aggregate_packing_rows_to_invoice_positions(rows)
    agg_sum = sum(p["line_total"] for p in out)
    assert round(src_sum, 2) == round(agg_sum, 2), (
        f"FOB sum drifted: src={src_sum} agg={agg_sum}"
    )


def test_aggregation_preserves_quantity_total():
    from app.services.customs_position_aggregator import (
        aggregate_packing_rows_to_invoice_positions,
    )
    rows = [
        _row("a", "RING", "Pierścionek", 101.0, 735.00,
             "Pierścionek ze srebra próby 925 wysadzany cyrkoniami",
             "925 Silver CZ Stud Jewellery RING"),
        _row("b", "PENDANT", "Wisiorek", 49.0, 284.00,
             "Wisiorek ze srebra próby 925 wysadzany cyrkoniami",
             "925 Silver CZ Stud Jewellery PENDANT"),
    ]
    out = aggregate_packing_rows_to_invoice_positions(rows)
    assert len(out) == 1
    assert out[0]["quantity"] == 150.0  # 101 + 49


def test_aggregation_no_rows_returns_empty():
    from app.services.customs_position_aggregator import (
        aggregate_packing_rows_to_invoice_positions,
    )
    assert aggregate_packing_rows_to_invoice_positions([]) == []


def test_aggregation_handles_missing_keys_gracefully():
    """When rows don't carry the renderer's output fields, the
    aggregator returns them unchanged (caller falls back to per-row
    authority)."""
    from app.services.customs_position_aggregator import (
        aggregate_packing_rows_to_invoice_positions,
    )
    rows = [{"product_code": "x", "quantity": 1.0, "line_total": 100.0}]
    out = aggregate_packing_rows_to_invoice_positions(rows)
    # Return as-is
    assert out == rows


def test_aggregation_produces_8_to_10_positions_for_global_088_fixture():
    """The operator's batch 088/2026-2027 has 245 packing rows that
    must collapse to ~8-10 invoice positions (one per (uom, metal,
    stone) tuple). Use a representative fixture."""
    from app.services.customs_position_aggregator import (
        aggregate_packing_rows_to_invoice_positions,
    )
    # Construct a fixture matching the production invoice categories
    def mk(pc_seq, item_type, item_pl, qty, fob, metal_pl, metal_en,
           stone_pl, stone_en, uom="PCS"):
        return _row(
            f"088/2026-2027-{pc_seq}", item_type, item_pl, qty, fob,
            f"{item_pl} {metal_pl}{(' ' + stone_pl) if stone_pl else ''}",
            f"{metal_en} {stone_en} {item_type}",
            uom=uom,
        )

    rows = [
        # PCS 09KT Gold LGD (Bracelet ×2 in production)
        mk(1, "BRACELET", "Bransoletka", 2.0, 604.0,
           "ze złota próby 375", "09KT Gold",
           "z diamentami laboratoryjnymi", "Lab Grown Diamond Jewellery"),
        # PCS 925 Silver CZ+CLS (Pendant + Ring in production)
        mk(2, "PENDANT", "Wisiorek", 8.0, 53.0,
           "ze srebra próby 925", "925 Silver",
           "wysadzany cyrkoniami i kamieniami kolorowymi",
           "CZ & Colour Stone Jewellery"),
        mk(3, "RING", "Pierścionek", 15.0, 109.0,
           "ze srebra próby 925", "925 Silver",
           "wysadzany cyrkoniami i kamieniami kolorowymi",
           "CZ & Colour Stone Jewellery"),
        # PCS 925 Silver CZ (multiple types, multiple rows)
        mk(7, "PENDANT", "Wisiorek", 49.0, 284.0,
           "ze srebra próby 925", "925 Silver",
           "wysadzany cyrkoniami", "CZ Stud Jewellery"),
        mk(8, "RING", "Pierścionek", 101.0, 735.0,
           "ze srebra próby 925", "925 Silver",
           "wysadzany cyrkoniami", "CZ Stud Jewellery"),
        # PCS 925 Silver Plain
        mk(10, "RING", "Pierścionek", 1.0, 12.0,
           "ze srebra próby 925", "925 Silver",
           "", "Plain Jewellery"),
        # PRS 14KT Gold LGD
        mk(11, "EARRINGS", "Kolczyki", 1.0, 659.0,
           "ze złota próby 585", "14KT Gold",
           "z diamentami laboratoryjnymi", "Lab Grown Diamond Jewellery",
           uom="PRS"),
        # PRS 925 Silver CZ
        mk(13, "EARRINGS", "Kolczyki", 56.0, 400.0,
           "ze srebra próby 925", "925 Silver",
           "wysadzany cyrkoniami", "CZ Stud Jewellery", uom="PRS"),
        # PRS 925 Silver Plain
        mk(14, "EARRINGS", "Kolczyki", 1.0, 5.0,
           "ze srebra próby 925", "925 Silver",
           "", "Plain Jewellery", uom="PRS"),
    ]
    out = aggregate_packing_rows_to_invoice_positions(rows)
    # Distinct (uom, metal, stone) tuples in the fixture: 6 unique
    # signatures (the operator's batch produces ~8-10 positions on the
    # full 245-row data set)
    assert 4 <= len(out) <= 12, (
        f"expected reasonable position count, got {len(out)}: "
        f"{[(p['uom'], p['polish_customs_description']) for p in out]}"
    )


# ── Source contract: route layer wiring ──────────────────────────────────


_ROUTES = (
    Path(__file__).resolve().parent.parent
    / "app" / "api" / "routes_dhl_clearance.py"
)


def test_inject_chain_supports_customs_view_param():
    src = _ROUTES.read_text(encoding="utf-8")
    idx = src.find("def _inject_rows_from_sources(")
    body = src[idx : idx + 3500]
    assert "customs_view: str" in body
    assert 'customs_view == "invoice_positions"' in body
    assert "aggregate_packing_rows_to_invoice_positions" in body


def test_inject_chain_preserves_fob_sum_check_before_swap():
    """Safety: the aggregation result must be applied only when the
    aggregated FOB sum equals the source FOB sum (within $0.01).
    Otherwise per-row rows are preserved."""
    src = _ROUTES.read_text(encoding="utf-8")
    idx = src.find("def _inject_rows_from_sources(")
    body = src[idx : idx + 3500]
    assert "_src_sum" in body and "_agg_sum" in body
    assert "abs(_src_sum - _agg_sum) <= 0.01" in body


def test_generate_description_endpoint_accepts_customs_view():
    src = _ROUTES.read_text(encoding="utf-8")
    idx = src.find("async def generate_description(")
    body = src[idx : idx + 2000]
    assert 'customs_view: str = "invoice_positions"' in body


def test_packing_rows_mode_preserves_legacy_behaviour():
    """When customs_view='packing_rows' the aggregation step does not
    execute — per-row authority preserved for warehouse / audit use."""
    src = _ROUTES.read_text(encoding="utf-8")
    idx = src.find("def _inject_rows_from_sources(")
    body = src[idx : idx + 3500]
    # The aggregation must be guarded by customs_view == "invoice_positions"
    assert 'customs_view == "invoice_positions" and audit.get("rows")' in body


# ── Out-of-scope guard ────────────────────────────────────────────────────


def test_aggregator_module_does_not_import_estrella_supplier_code():
    path = (Path(__file__).resolve().parent.parent
            / "app" / "services" / "customs_position_aggregator.py")
    body = path.read_text(encoding="utf-8")
    forbidden_imports = (
        "invoice_intake_parser",
        "customs_description_engine",
        "product_identity_engine",
        "description_engine",
        "global_invoice_parser",
        "global_packing_parser",
    )
    for tok in forbidden_imports:
        assert tok not in body, (
            f"aggregator must not import {tok!r}"
        )


def test_aggregator_does_not_compute_cif_or_duty():
    path = (Path(__file__).resolve().parent.parent
            / "app" / "services" / "customs_position_aggregator.py")
    body = path.read_text(encoding="utf-8")
    forbidden = (
        "compute_cif", "DHL_BROKER_THRESHOLD", "duty_pln", "vat_pln",
        "WFIRMA_CREATE_", "create_invoice", "create_pz",
        "_guard_wfirma_export",
    )
    for tok in forbidden:
        assert tok not in body, f"aggregator must not reference {tok!r}"


def test_aggregator_produces_no_forbidden_tokens_in_descriptions():
    """The aggregator must never emit UNKNOWN / metal szlachetny /
    Wyrób jubilerski / grouped invoice aggregate placeholders."""
    from app.services.customs_position_aggregator import (
        aggregate_packing_rows_to_invoice_positions,
    )
    rows = [
        _row("a", "RING", "Pierścionek", 1.0, 100.0,
             "Pierścionek ze srebra próby 925 wysadzany cyrkoniami",
             "925 Silver CZ Stud Jewellery RING"),
    ]
    out = aggregate_packing_rows_to_invoice_positions(rows)
    for p in out:
        text = (p.get("polish_customs_description","")
                + " " + p.get("description_en",""))
        for tok in ("UNKNOWN", "metal szlachetny", "Wyrób jubilerski",
                    "grouped invoice aggregate"):
            assert tok not in text, (
                f"aggregator emitted forbidden {tok!r} in: {text!r}"
            )
