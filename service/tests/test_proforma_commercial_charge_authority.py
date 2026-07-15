"""test_proforma_commercial_charge_authority.py — PR-6.

The ONE CommercialChargeAuthority: freight + insurance subtotal resolved from the
proforma draft snapshot (``service_charges_json``), same-currency-only, one premium
formula frozen at write time. Customs CIF is a SEPARATE authority and must not be
touched by this slice.

Test matrix (12 required):
  CCA-01  one premium formula: max(sales_total × rate, minimum), cents-quantised
  CCA-02  resolve sums same-currency freight + insurance into the subtotal
  CCA-03  cross-currency charge is surfaced, NEVER converted or summed
  CCA-04  frozen insurance amount>0 is consumed verbatim (no recompute)
  CCA-05  legacy amount==0 recomputed ONLY from frozen formula_basis inputs
  CCA-06  amount==0 with incomplete frozen inputs → incomplete_charges, no invention
  CCA-07  write-time freeze persists amount + formula evidence (existing charge)
  CCA-08  write-time freeze persists amount + formula evidence (new charge)
  CCA-09  compute_insurance_suggestion reuses the ONE shared formula (not a copy)
  CCA-10  customs / cif files are NOT modified by this slice (source-grep)
  CCA-11  no second premium formula anywhere in production services (source-grep)
  CCA-12  UI financial paths read the authority, not an independent charge re-sum
"""
from __future__ import annotations

import pathlib
import re
from decimal import Decimal

import pytest

from app.services import commercial_charge_authority as cca
from app.services import customer_master as cm
from app.services import proforma_invoice_link_db as pildb

SERVICE_ROOT = pathlib.Path(__file__).resolve().parents[1]
SERVICES_DIR = SERVICE_ROOT / "app" / "services"
API_DIR = SERVICE_ROOT / "app" / "api"
STATIC_V2 = SERVICE_ROOT / "app" / "static" / "v2"


# ── CCA-01 ──────────────────────────────────────────────────────────────────
def test_one_premium_formula():
    # rate as a fraction; below the floor → floor wins.
    assert cca.insurance_premium(1000, "0.0035", 5) == Decimal("5.00")
    # above the floor → computed wins, cents-quantised.
    assert cca.insurance_premium(2000, "0.0035", 5) == Decimal("7.00")
    # no minimum → pure product.
    assert cca.insurance_premium(1000, "0.0035") == Decimal("3.50")


# ── CCA-02 ──────────────────────────────────────────────────────────────────
def test_resolve_sums_same_currency():
    r = cca.resolve_commercial_charges("USD", [
        {"charge_type": "freight", "amount": 100, "currency": "USD"},
        {"charge_type": "insurance", "amount": 18.79, "currency": "USD"},
    ])
    assert r["freight_total"] == 100.0
    assert r["insurance_total"] == 18.79
    assert r["service_charge_subtotal"] == 118.79
    assert r["cross_currency_charges"] == []
    assert r["incomplete_charges"] == []
    assert r["provenance"]["currency_rule"] == "same_currency_only"


# ── CCA-03 ──────────────────────────────────────────────────────────────────
def test_cross_currency_surfaced_not_summed():
    r = cca.resolve_commercial_charges("USD", [
        {"charge_type": "freight", "amount": 100, "currency": "USD"},
        {"charge_type": "freight", "amount": 50, "currency": "PLN"},
    ])
    assert r["freight_total"] == 100.0          # PLN NOT summed
    assert r["service_charge_subtotal"] == 100.0
    assert len(r["cross_currency_charges"]) == 1
    assert r["cross_currency_charges"][0]["currency"] == "PLN"


# ── CCA-04 ──────────────────────────────────────────────────────────────────
def test_frozen_amount_consumed_verbatim():
    # frozen amount present → used as-is even if formula_basis would differ.
    r = cca.resolve_commercial_charges("EUR", [
        {"charge_type": "insurance", "amount": 42.00, "currency": "EUR",
         "formula_basis": {"sales_total": "1000", "rate_pct": "0.35"}},
    ])
    assert r["insurance_total"] == 42.00
    assert r["incomplete_charges"] == []


# ── CCA-05 ──────────────────────────────────────────────────────────────────
def test_legacy_zero_recomputed_from_frozen_basis():
    # amount==0 but the snapshot carries the frozen inputs → recompute from THEM.
    r = cca.resolve_commercial_charges("EUR", [
        {"charge_type": "insurance", "amount": 0, "currency": "EUR",
         "formula_basis": {"sales_total": "2000", "rate_pct": "0.5",
                           "minimum_eur": "8"}},
    ])
    # 2000 × 0.005 = 10.00 ≥ 8 floor → 10.00
    assert r["insurance_total"] == 10.00
    assert r["incomplete_charges"] == []


# ── CCA-06 ──────────────────────────────────────────────────────────────────
def test_zero_with_incomplete_inputs_is_incomplete_not_invented():
    r = cca.resolve_commercial_charges("EUR", [
        {"charge_type": "insurance", "amount": 0, "currency": "EUR",
         "formula_basis": {"rate_pct": "0.5"}},  # no sales_total
    ])
    assert r["insurance_total"] == 0.0            # nothing invented
    assert len(r["incomplete_charges"]) == 1
    assert r["incomplete_charges"][0]["charge_type"] == "insurance"


# ── write-freeze fixtures ────────────────────────────────────────────────────
def _make_draft(tmp_path, currency="EUR", charges_json="[]"):
    import sqlite3
    db = tmp_path / "proforma_links.sqlite3"
    draft, created = pildb.upsert_pending_draft(
        db,
        batch_id="SHIP_CCA_TEST",
        client_name="Test Client",
        currency=currency,
        exchange_rate=4.30,
        source_lines_json="[]",
        service_charges_json=charges_json,
    )
    assert created
    # Fresh upserts land in the 'posting' lifecycle state; move to the editable
    # 'draft' state so the commercial-apply write path is exercised.
    with sqlite3.connect(str(db)) as conn:
        conn.execute(
            "UPDATE proforma_drafts SET draft_state='draft', status='draft' WHERE id=?",
            (draft.id,),
        )
        conn.commit()
    fresh = pildb.get_draft_by_id(db, draft.id)
    assert fresh.draft_state == "draft", f"fixture state = {fresh.draft_state!r}"
    return db, fresh


# ── CCA-07 ──────────────────────────────────────────────────────────────────
def test_write_freeze_existing_charge(tmp_path):
    charges = '[{"charge_id":1,"charge_type":"insurance","amount":0.0,' \
              '"currency":"EUR","formula_basis":null}]'
    db, draft = _make_draft(tmp_path, "EUR", charges)
    out = pildb.apply_customer_commercial_to_draft(
        db, draft.id, "Test Client", "C123",
        {"insurance_amount": 12.34,
         "insurance_formula_basis": {"sales_total": "1000", "rate_pct": "0.35",
                                     "minimum_eur": "5"}},
        operator="tester", expected_updated_at=draft.updated_at,
    )
    r = cca.resolve_commercial_charges("EUR", _charges_of(out))
    assert r["insurance_total"] == 12.34         # frozen premium persisted
    ins = [c for c in _charges_of(out) if c["charge_type"] == "insurance"][0]
    assert ins["amount"] == 12.34
    assert ins["formula_basis"]["sales_total"] == "1000"


# ── CCA-08 ──────────────────────────────────────────────────────────────────
def test_write_freeze_new_charge(tmp_path):
    db, draft = _make_draft(tmp_path, "EUR", "[]")
    out = pildb.apply_customer_commercial_to_draft(
        db, draft.id, "Test Client", "C123",
        {"insurance_amount": 7.50,
         "insurance_formula_basis": {"sales_total": "1000", "rate_pct": "0.75"}},
        operator="tester", expected_updated_at=draft.updated_at,
    )
    ins = [c for c in _charges_of(out) if c["charge_type"] == "insurance"][0]
    assert ins["amount"] == 7.50
    assert ins["formula_basis"]["rate_pct"] == "0.75"
    # And the authority resolves that same frozen premium.
    assert cca.resolve_commercial_charges("EUR", _charges_of(out))["insurance_total"] == 7.50


def _charges_of(draft):
    import json
    return json.loads(draft.service_charges_json or "[]")


# ── CCA-09 ──────────────────────────────────────────────────────────────────
def test_compute_insurance_suggestion_reuses_shared_formula():
    src = (SERVICES_DIR / "customer_master.py").read_text(encoding="utf-8")
    # must import + call the ONE shared helper; must NOT re-implement max(x*rate,..)
    assert "from .commercial_charge_authority import insurance_premium" in src
    assert "insurance_premium(" in src
    # the old inline formula literal must be gone from the suggest path.
    assert "max(computed, Decimal(str(minimum)))" not in src


# ── CCA-10 ──────────────────────────────────────────────────────────────────
def test_customs_cif_files_not_touched_by_authority():
    """The commercial authority must not import or call customs valuation.

    The module docstring may *name* cif_resolver to state the separation; what is
    forbidden is actual code coupling (an import or an attribute call).
    """
    src = (SERVICES_DIR / "commercial_charge_authority.py").read_text(encoding="utf-8")
    # strip the module docstring so its prose reference to cif_resolver is ignored.
    body = re.sub(r'^"""».*?»"""', "", src, count=1, flags=re.DOTALL)
    body = re.sub(r'^""".*?"""', "", src, count=1, flags=re.DOTALL)
    forbidden = (
        "import cif_resolver", "from .cif_resolver", "cif_resolver.",
        "customs_valuation", "import cif_", "cif_resolver(",
    )
    for f in forbidden:
        assert f not in body, (
            f"commercial_charge_authority must stay decoupled from customs; "
            f"found code coupling {f!r}"
        )


# ── CCA-11 ──────────────────────────────────────────────────────────────────
def test_no_second_premium_formula_in_services():
    """Only commercial_charge_authority.py may define the premium arithmetic.

    A ``max(<sales> * <rate>, <minimum>)`` shape anywhere else is a second formula.
    """
    pat = re.compile(r"max\(\s*[\w.]*sales[\w.]*\s*\*\s*[\w.]*rate", re.IGNORECASE)
    offenders = []
    for path in SERVICES_DIR.glob("*.py"):
        if path.name == "commercial_charge_authority.py":
            continue
        if pat.search(path.read_text(encoding="utf-8")):
            offenders.append(path.name)
    assert not offenders, f"second premium formula found in: {offenders}"


# ── CCA-12 ──────────────────────────────────────────────────────────────────
def test_ui_reads_authority_not_independent_resum():
    """proforma-detail.jsx financial paths must read commercial_charges (the
    authority) and must not re-sum service_charges amounts for the subtotal."""
    src = (STATIC_V2 / "proforma-detail.jsx").read_text(encoding="utf-8")
    assert "commercial_charges" in src, "UI must consume the resolved authority"
    # the AWB declared-value inline reduce over service_charges must be gone.
    assert "liveDraft.service_charges || []).reduce" not in src, (
        "AWB declared value must read commercial_charges.service_charge_subtotal, "
        "not re-sum service_charges in the UI"
    )
    # the doc renderer must be able to prefer the authority subtotal.
    doc = (STATIC_V2 / "estrella-doc-proforma.jsx").read_text(encoding="utf-8")
    assert "charges_total" in doc, "doc renderer must prefer docData.charges_total"
