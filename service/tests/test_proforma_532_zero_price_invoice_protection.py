"""test_proforma_532_zero_price_invoice_protection.py

Campaign 04 — PR2 (#532): zero-price invoice protection.

Defect class: a proforma line priced at zero must never reach the final
wFirma invoice. By construction at ``routes_packing.py`` line 2327 —

    price_source = "packing_xlsx_value" if unit_price > 0 else "packing_promote"

— a zero unit_price is EXACTLY the ``packing_promote`` cost-less promotion.
So at the invoice boundary the two #532 rules collapse to one price test:

  • Rule A — exclude ``price_source == "packing_promote"``
  • Rule B — exclude ``unit_price <= 0``
  • Rule C — if NOTHING is billable, BLOCK invoice generation.

``price_source`` does not survive the wFirma proforma XML round-trip
(``LineItem`` carries only ``price``), so ``price`` is the authority at this
boundary and rule A ≡ rule B ≡ exclude ``price <= 0``.

These tests exercise the REAL builders (Lesson A — no stubs):
``parse_proforma_xml`` (which intentionally ALLOWS ``<price>0</price>`` — that
is the gap #529's draft gate covers at approve/post and that this convert-time
guard backstops) and ``build_final_invoice_plan`` (which performs the A/B/C
filter + zero-billable block).

Frozen-valuation invariant: excluding a zero-price line removes no revenue and
changes no monetary total — landed-cost / FX math is untouched.
"""
from __future__ import annotations

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest


def _ensure_path() -> None:
    here = Path(__file__).resolve()
    service_dir = here.parents[1]
    repo_root   = here.parents[2]
    for p in (str(service_dir), str(repo_root)):
        if p not in sys.path:
            sys.path.insert(0, p)


_ensure_path()

from app.services.proforma_to_invoice import (         # noqa: E402
    LineItem, ProformaSnapshot, ZeroBillableInvoice,
    build_final_invoice_plan, build_final_invoice_xml,
    is_billable_line, partition_billable, parse_proforma_xml,
)


# ── helpers: real LineItem / ProformaSnapshot, real wFirma-shape XML ─────────

def _li(name: str, price: str, good_id: str = "10000001",
        vat: str = "229") -> LineItem:
    return LineItem(name=name, good_id=good_id, unit="szt.",
                    unit_count="1.0000", price=price, vat_code_id=vat)


def _snap(lines, *, total: str = "0.00") -> ProformaSnapshot:
    """A minimal but real ProformaSnapshot carrying the given line items."""
    return ProformaSnapshot(
        proforma_id="98700532",
        proforma_number="PROF 532/2026",
        type="proforma",
        contractor_id="38582303",
        currency="EUR",
        price_currency_exchange=None,
        paymentmethod="transfer",
        paymentdate="2026-06-20",
        date="2026-06-13",
        description="Campaign 04 PR2 fixture",
        series_id="15827088",
        company_account_id="169589",
        translation_language_id="1",
        contractor_receiver_id=None,
        total=Decimal(total),
        netto=Decimal(total),
        contents=list(lines),
    )


def _line_xml(name: str, good_id: str, price: str) -> str:
    return (
        "<invoicecontent>"
        f"<name>{name}</name>"
        f"<good><id>{good_id}</id></good>"
        "<unit>szt.</unit>"
        "<unit_count>1.0000</unit_count>"
        f"<price>{price}</price>"
        "<vat_code><id>229</id></vat_code>"
        "</invoicecontent>"
    )


def _proforma_xml(line_specs, *, total: str) -> str:
    """Real wFirma-shape proforma XML with arbitrary (name, good_id, price)
    line specs. Mirrors what ``fetch_invoice_xml`` returns for a proforma."""
    rows = "".join(_line_xml(n, g, p) for (n, g, p) in line_specs)
    return f"""<?xml version="1.0"?>
<api><invoices><invoice>
  <id>98700532</id>
  <fullnumber>PROF 532/2026</fullnumber>
  <type>proforma</type>
  <date>2026-06-13</date>
  <paymentdate>2026-06-20</paymentdate>
  <paymentmethod>transfer</paymentmethod>
  <currency>EUR</currency>
  <total>{total}</total>
  <netto>{total}</netto>
  <description>Campaign 04 PR2 fixture</description>
  <contractor><id>38582303</id></contractor>
  <series><id>15827088</id></series>
  <invoicecontents>{rows}</invoicecontents>
</invoice></invoices><status><code>OK</code></status></api>"""


# ── parse intentionally allows price 0 (the gap this guard backstops) ────────

def test_parse_allows_zero_price_line():
    """``parse_proforma_xml`` does NOT reject a zero-price line — it requires
    only that ``<price>`` be present. This documents the drift surface that the
    convert-time guard exists to catch."""
    xml = _proforma_xml(
        [("Priced", "10000001", "100.00"),
         ("Promo",  "10000002", "0.00")],
        total="100.00",
    )
    snap = parse_proforma_xml(xml)
    assert len(snap.contents) == 2
    assert snap.contents[1].price == "0.00"   # parse let it through


# ── Case 1 — priced + packing_promote (zero) ⇒ invoice contains priced only ──

def test_case1_mixed_priced_and_promote_keeps_only_priced():
    xml = _proforma_xml(
        [("Gold ring",   "10000001", "211.00"),
         ("Free sample", "10000002", "0.00"),     # packing_promote ≡ price 0
         ("Silver pin",  "10000003", "55.00")],
        total="266.00",
    )
    snap = parse_proforma_xml(xml)
    plan = build_final_invoice_plan(snap, final_series_id="15827921")

    kept = [l.name for l in plan.contents]
    assert kept == ["Gold ring", "Silver pin"], kept
    # The dropped zero-price line is disclosed, never silently swallowed.
    assert [l.name for l in plan.excluded_lines] == ["Free sample"]
    # Emitted XML contains only the priced lines.
    xml_out = build_final_invoice_xml(plan)
    assert "Gold ring" in xml_out and "Silver pin" in xml_out
    assert "Free sample" not in xml_out
    # Monetary total is unchanged — a zero line carried no value.
    assert plan.expected_total == Decimal("266.00")


# ── Case 2 — all packing_promote (all zero) ⇒ BLOCK ──────────────────────────

def test_case2_all_packing_promote_blocks():
    # Every line is a zero-price promotion (packing_promote by construction).
    snap = _snap([_li("Promo A", "0.00"), _li("Promo B", "0")], total="0.00")
    with pytest.raises(ZeroBillableInvoice) as ei:
        build_final_invoice_plan(snap, final_series_id="15827921")
    assert "no billable lines" in str(ei.value)
    assert "PROF 532/2026" in str(ei.value)


# ── Case 3 — all zero-price ⇒ BLOCK ──────────────────────────────────────────

def test_case3_all_zero_price_blocks():
    # Single zero-price line (rule B path) — same block as the all-promote set.
    snap = _snap([_li("Zero line", "0.00")], total="0.00")
    with pytest.raises(ZeroBillableInvoice):
        build_final_invoice_plan(snap, final_series_id="15827921")


# ── Case 4 — normal priced invoice ⇒ unchanged ───────────────────────────────

def test_case4_all_priced_unchanged():
    xml = _proforma_xml(
        [("Pendant", "10000001", "25.00"),
         ("Courier", "10000002", "75.00"),
         ("Insurance", "10000003", "20.00")],
        total="120.00",
    )
    snap = parse_proforma_xml(xml)
    plan = build_final_invoice_plan(snap, final_series_id="15827921")

    # No exclusions, every line preserved verbatim and in order.
    assert plan.excluded_lines == []
    assert [l.name for l in plan.contents] == ["Pendant", "Courier", "Insurance"]
    assert [l.price for l in plan.contents] == ["25.00", "75.00", "20.00"]
    assert plan.expected_total == Decimal("120.00")
    xml_out = build_final_invoice_xml(plan)
    for n in ("Pendant", "Courier", "Insurance"):
        assert n in xml_out


# ── partition helpers (pure) ─────────────────────────────────────────────────

@pytest.mark.parametrize("price,expected", [
    ("100.00", True),
    ("0.01",   True),
    ("0.00",   False),
    ("0",      False),
    ("-5.00",  False),     # negative is non-billable
    ("",       False),     # blank → treated as 0 → non-billable
    ("garbage", False),    # unparseable → 0 → non-billable, never raises
])
def test_is_billable_line(price, expected):
    assert is_billable_line(_li("X", price)) is expected


def test_partition_preserves_order_and_splits():
    lines = [_li("a", "10"), _li("b", "0"), _li("c", "5"), _li("d", "0.00")]
    billable, excluded = partition_billable(lines)
    assert [l.name for l in billable] == ["a", "c"]
    assert [l.name for l in excluded] == ["b", "d"]
    # Inputs are not mutated.
    assert [l.name for l in lines] == ["a", "b", "c", "d"]


def test_partition_empty_input():
    billable, excluded = partition_billable([])
    assert billable == [] and excluded == []


# ── guard ties to routes_packing.py:2327 invariant (documentation test) ──────

def test_zero_price_is_the_packing_promote_set():
    """Document the equivalence this guard relies on: at the invoice boundary,
    excluding ``price <= 0`` is the faithful proxy for excluding
    ``price_source == "packing_promote"`` because routes_packing.py:2327 sets
    ``packing_promote`` IFF ``unit_price <= 0``. A priced line is always kept;
    a zero line is always dropped."""
    assert is_billable_line(_li("priced", "0.01")) is True
    assert is_billable_line(_li("promote", "0.00")) is False
