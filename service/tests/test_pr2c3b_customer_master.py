"""
test_pr2c3b_customer_master.py — PR 2C.3b: freight/insurance suggestions
+ draft service-charge integration.

Tests
-----
Freight (1-8)
  1.  pick_freight EUR fixed: returns freight_fixed_amount_eur.
  2.  pick_freight USD fixed: returns freight_fixed_amount_usd.
  3.  pick_freight EUR blocked when no EUR amount and no legacy fallback.
  4.  pick_freight EUR backward-compat: missing fixed_eur + freight_last_amount
      + mode=fixed → legacy fallback dict (ok=True, legacy_fallback=True).
  5.  pick_freight USD blocked when no USD amount.
  6.  pick_freight blocked when service_id is missing.
  7.  pick_freight operator_override always wins (new signature).
  8.  pick_freight no cross-currency: EUR draft with only USD amount → blocked.

Insurance (9-15)
  9.  insurance_enabled=False → blocked.
  10. insurance_service_id missing → blocked.
  11. compute_insurance_suggestion EUR fixed mode.
  12. compute_insurance_suggestion USD fixed mode.
  13. compute_insurance_suggestion EUR formula mode (rate + min_eur).
  14. compute_insurance_suggestion USD formula mode (rate + min_usd).
  15. compute_insurance_suggestion blocked when no amount and no rate.

Service charge (16-20)
  16. One-per-type: adding a second "freight" charge raises ValueError.
  17. wfirma_service_id stored and retrieved in charge dict.
  18. formula_basis stored and retrieved.
  19. formula_basis with forbidden key raises ValueError.
  20. wfirma_service_id blank string raises ValueError.
"""
from __future__ import annotations

import json
import sqlite3
import sys
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

from app.services.customer_master_db import (   # noqa: E402
    CustomerMaster,
    init_db,
    upsert_customer,
)
from app.services.customer_master import (       # noqa: E402
    pick_freight,
    compute_insurance_suggestion,
)
from app.services.proforma_invoice_link_db import (  # noqa: E402
    add_draft_service_charge,
    get_draft_by_id,
    init_db as pildb_init_db,
    upsert_pending_draft,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _cm(**overrides) -> CustomerMaster:
    """CustomerMaster with all 2C.3a fields populated for EUR + USD."""
    base = dict(
        bill_to_contractor_id      = "TEST001",
        bill_to_name               = "Test Customer",
        country                    = "NO",
        freight_service_id         = "13002743",
        freight_fixed_amount_eur   = Decimal("120.00"),
        freight_fixed_amount_usd   = Decimal("130.00"),
        freight_label_pl           = "Transport",
        freight_label_en           = "Courier",
        insurance_service_id       = "13102217",
        insurance_fixed_amount_eur = Decimal("35.00"),
        insurance_fixed_amount_usd = Decimal("38.00"),
        insurance_min_eur          = Decimal("10.00"),
        insurance_min_usd          = Decimal("11.00"),
        insurance_label_pl         = "Ubezpieczenie",
        insurance_label_en         = "Insurance",
        insurance_enabled          = True,
        insurance_rate             = Decimal("0.0035"),
    )
    base.update(overrides)
    return CustomerMaster(**base)


def _draft_db(tmp_path: Path) -> Path:
    """Initialised proforma_links.db in tmp_path."""
    db = tmp_path / "proforma_links.db"
    pildb_init_db(db)
    return db


_draft_counter = 0


def _make_draft(db: Path, *, currency: str = "EUR",
                lines: list | None = None) -> int:
    """Create a minimal draft in editable 'draft' state and return its id.

    Inserts with status='draft' so the _row_to_draft legacy shim maps to
    draft_state='draft', which is in EDITABLE_STATES.
    """
    global _draft_counter
    _draft_counter += 1
    batch_id = f"BATCH-2C3B-{_draft_counter}"
    pildb_init_db(db)
    now = "2026-05-15T00:00:00+00:00"
    with sqlite3.connect(str(db), isolation_level=None) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("""
            INSERT INTO proforma_drafts
                (batch_id, client_name, status, currency, exchange_rate,
                 source_lines_json, wfirma_proforma_id, notes,
                 draft_state, created_at, updated_at)
            VALUES (?, ?, 'draft', ?, ?, '[]', NULL, NULL, 'draft', ?, ?)
            ON CONFLICT(batch_id, client_name) DO NOTHING
        """, (batch_id, "Test Customer", currency, 1.0, now, now))
        row = conn.execute(
            "SELECT id FROM proforma_drafts WHERE batch_id=? AND client_name=?",
            (batch_id, "Test Customer"),
        ).fetchone()
        draft_id = row["id"]
        if lines:
            conn.execute(
                "UPDATE proforma_drafts SET editable_lines_json=? WHERE id=?",
                (json.dumps(lines), draft_id),
            )
    return draft_id


def _add_charge(db: Path, draft_id: int, charge: dict, *, operator: str = "tester") -> None:
    """Helper: load the draft's updated_at and call add_draft_service_charge."""
    d = get_draft_by_id(db, draft_id)
    add_draft_service_charge(db, draft_id, charge, operator, d.updated_at)


# ── Freight tests (1-8) ───────────────────────────────────────────────────────

def test_pick_freight_eur_returns_fixed_eur():
    """Test 1: EUR draft → freight_fixed_amount_eur."""
    c = _cm()
    r = pick_freight(c, "EUR")
    assert r["ok"] is True
    assert r["amount"] == Decimal("120.00")
    assert r["wfirma_service_id"] == "13002743"
    assert r.get("label") == "Courier"


def test_pick_freight_usd_returns_fixed_usd():
    """Test 2: USD draft → freight_fixed_amount_usd."""
    c = _cm()
    r = pick_freight(c, "USD")
    assert r["ok"] is True
    assert r["amount"] == Decimal("130.00")
    assert r["wfirma_service_id"] == "13002743"


def test_pick_freight_eur_blocked_when_no_eur_and_no_legacy():
    """Test 3: EUR draft, no fixed EUR amount, no freight_last_amount → blocked."""
    c = _cm(
        freight_fixed_amount_eur=None,
        freight_last_amount=None,
        freight_mode=None,
    )
    r = pick_freight(c, "EUR")
    assert r["ok"] is False
    assert r["blocked"] is True
    assert "EUR" in r["reason"]


def test_pick_freight_eur_legacy_fallback_when_fixed_eur_missing():
    """Test 4: EUR draft, no fixed EUR, but freight_last_amount + mode=fixed →
    legacy fallback ok=True with legacy_fallback flag."""
    c = _cm(
        freight_fixed_amount_eur=None,
        freight_last_amount=Decimal("95.00"),
        freight_mode="fixed",
    )
    r = pick_freight(c, "EUR")
    assert r["ok"] is True
    assert r["amount"] == Decimal("95.00")
    assert r.get("legacy_fallback") is True


def test_pick_freight_usd_blocked_when_no_usd_amount():
    """Test 5: USD draft, no fixed USD amount → blocked."""
    c = _cm(freight_fixed_amount_usd=None)
    r = pick_freight(c, "USD")
    assert r["ok"] is False
    assert r["blocked"] is True
    assert "USD" in r["reason"]


def test_pick_freight_blocked_when_no_service_id():
    """Test 6: service_id missing → blocked regardless of currency."""
    c = _cm(freight_service_id=None)
    r = pick_freight(c, "EUR")
    assert r["ok"] is False
    assert "freight_service_id" in r["reason"]


def test_pick_freight_operator_override_always_wins():
    """Test 7: operator_override beats fixed amounts."""
    c = _cm()
    r = pick_freight(c, "EUR", operator_override=Decimal("999.00"))
    assert r["ok"] is True
    assert r["amount"] == Decimal("999.00")


def test_pick_freight_no_cross_currency_fallback():
    """Test 8: EUR draft with only USD amount (no EUR amount) → blocked.
    No cross-currency fallback allowed."""
    c = _cm(freight_fixed_amount_eur=None, freight_last_amount=None, freight_mode=None)
    r = pick_freight(c, "EUR")
    assert r["ok"] is False
    assert r["blocked"] is True
    # Must NOT silently return the USD amount
    assert r.get("amount") is None


# ── Insurance tests (9-15) ────────────────────────────────────────────────────

def test_insurance_disabled_blocks_suggestion():
    """Test 9: insurance_enabled=False → blocked."""
    c = _cm(insurance_enabled=False)
    r = compute_insurance_suggestion(c, "EUR", Decimal("1000"))
    assert r["ok"] is False
    assert "disabled" in r["reason"]


def test_insurance_no_service_id_blocks_suggestion():
    """Test 10: insurance_service_id missing → blocked."""
    c = _cm(insurance_service_id=None)
    r = compute_insurance_suggestion(c, "EUR", Decimal("1000"))
    assert r["ok"] is False
    assert "service_id" in r["reason"]


def test_insurance_eur_fixed_mode():
    """Test 11: EUR fixed mode → insurance_fixed_amount_eur."""
    c = _cm()
    r = compute_insurance_suggestion(c, "EUR", Decimal("10000"))
    assert r["ok"] is True
    assert r["amount"] == Decimal("35.00")
    assert r["wfirma_service_id"] == "13102217"
    assert r["formula_basis"] is None


def test_insurance_usd_fixed_mode():
    """Test 12: USD fixed mode → insurance_fixed_amount_usd."""
    c = _cm()
    r = compute_insurance_suggestion(c, "USD", Decimal("10000"))
    assert r["ok"] is True
    assert r["amount"] == Decimal("38.00")
    assert r["formula_basis"] is None


def test_insurance_eur_formula_mode_uses_rate_and_min():
    """Test 13: EUR formula mode — max(sales * rate, min_eur)."""
    c = _cm(
        insurance_fixed_amount_eur=None,
        insurance_rate=Decimal("0.0035"),
        insurance_min_eur=Decimal("10.00"),
    )
    # sales_total = 5000 → 5000 × 0.0035 = 17.50 → max(17.50, 10.00) = 17.50
    r = compute_insurance_suggestion(c, "EUR", Decimal("5000"))
    assert r["ok"] is True
    assert r["amount"] == Decimal("17.50")
    assert r["formula_basis"] is not None
    assert "sales_total" in r["formula_basis"]
    assert "rate_pct" in r["formula_basis"]
    assert "minimum_eur" in r["formula_basis"]
    # Minimum wins when computed < minimum
    c2 = _cm(
        insurance_fixed_amount_eur=None,
        insurance_rate=Decimal("0.0035"),
        insurance_min_eur=Decimal("10.00"),
    )
    r2 = compute_insurance_suggestion(c2, "EUR", Decimal("100"))  # 0.35 < 10 → 10
    assert r2["amount"] == Decimal("10.00")


def test_insurance_usd_formula_mode_uses_rate_and_min_usd():
    """Test 14: USD formula mode — max(sales * rate, min_usd)."""
    c = _cm(
        insurance_fixed_amount_usd=None,
        insurance_rate=Decimal("0.0035"),
        insurance_min_usd=Decimal("11.00"),
    )
    r = compute_insurance_suggestion(c, "USD", Decimal("5000"))
    assert r["ok"] is True
    assert r["amount"] == Decimal("17.50")
    assert "minimum_usd" in r["formula_basis"]
    assert "minimum_eur" not in r["formula_basis"]


def test_insurance_blocked_when_no_amount_and_no_rate():
    """Test 15: no fixed amount, no rate → blocked."""
    c = _cm(
        insurance_fixed_amount_eur=None,
        insurance_fixed_amount_usd=None,
        insurance_rate=None,
    )
    r = compute_insurance_suggestion(c, "EUR", Decimal("1000"))
    assert r["ok"] is False
    assert r["blocked"] is True


# ── Service charge tests (16-20) ──────────────────────────────────────────────

def test_one_per_type_blocks_duplicate_freight(tmp_path: Path):
    """Test 16: adding a second freight charge raises ValueError."""
    db = _draft_db(tmp_path)
    did = _make_draft(db, currency="EUR")
    _add_charge(db, did, {
        "charge_type": "freight",
        "amount": 100,
        "currency": "EUR",
        "label": "first",
    })
    d = get_draft_by_id(db, did)
    with pytest.raises(ValueError, match="already exists"):
        add_draft_service_charge(
            db, did,
            {"charge_type": "freight", "amount": 120, "currency": "EUR"},
            "tester",
            d.updated_at,
        )


def test_wfirma_service_id_stored_and_retrieved(tmp_path: Path):
    """Test 17: wfirma_service_id is stored in the charge JSON."""
    db = _draft_db(tmp_path)
    did = _make_draft(db, currency="EUR")
    _add_charge(db, did, {
        "charge_type":      "freight",
        "amount":           100,
        "currency":         "EUR",
        "label":            "Freight",
        "wfirma_service_id": "13002743",
    })
    d = get_draft_by_id(db, did)
    charges = json.loads(d.service_charges_json)
    assert len(charges) == 1
    assert charges[0]["wfirma_service_id"] == "13002743"


def test_formula_basis_stored_and_retrieved(tmp_path: Path):
    """Test 18: formula_basis is stored in the charge JSON."""
    db = _draft_db(tmp_path)
    did = _make_draft(db, currency="EUR")
    basis = {"sales_total": "5000", "rate_pct": "0.35", "minimum_eur": "10"}
    _add_charge(db, did, {
        "charge_type":   "insurance",
        "amount":        17.50,
        "currency":      "EUR",
        "formula_basis": basis,
    })
    d = get_draft_by_id(db, did)
    charges = json.loads(d.service_charges_json)
    assert charges[0]["formula_basis"] == basis


def test_formula_basis_with_forbidden_key_raises(tmp_path: Path):
    """Test 19: formula_basis containing a forbidden key (cif, customs, etc.) is rejected."""
    db = _draft_db(tmp_path)
    did = _make_draft(db, currency="EUR")
    d = get_draft_by_id(db, did)
    for forbidden_key in ("cif", "customs", "import_cost", "pz_amount", "sad_total", "zc429_duty"):
        with pytest.raises(ValueError, match="formula_basis"):
            add_draft_service_charge(
                db, did,
                {
                    "charge_type":   "insurance",
                    "amount":        10,
                    "currency":      "EUR",
                    "formula_basis": {forbidden_key: "123"},
                },
                "tester",
                d.updated_at,
            )


def test_wfirma_service_id_blank_string_raises(tmp_path: Path):
    """Test 20: wfirma_service_id set to empty/whitespace string raises ValueError."""
    db = _draft_db(tmp_path)
    did = _make_draft(db, currency="EUR")
    d = get_draft_by_id(db, did)
    with pytest.raises(ValueError, match="wfirma_service_id"):
        add_draft_service_charge(
            db, did,
            {
                "charge_type":       "freight",
                "amount":            50,
                "currency":          "EUR",
                "wfirma_service_id": "   ",
            },
            "tester",
            d.updated_at,
        )
