"""test_finance_postings_db.py — Phase 6F.1 schema + CRUD tests.

Pure unit tests against the additive finance_postings.sqlite schema.
No service touch, no production DB, no wFirma, no proforma, no PZ.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest


def _ensure_path() -> None:
    here = Path(__file__).resolve()
    for p in (str(here.parents[1]), str(here.parents[2])):
        if p not in sys.path:
            sys.path.insert(0, p)


_ensure_path()

from app.services import finance_postings_db as fpdb


# ── Init / schema ───────────────────────────────────────────────────────────

def test_init_db_creates_file(tmp_path):
    db = tmp_path / "fp.sqlite"
    fpdb.init_db(db)
    assert db.is_file()


def test_init_db_idempotent(tmp_path):
    db = tmp_path / "fp.sqlite"
    fpdb.init_db(db)
    v1 = fpdb.current_schema_version(db)
    fpdb.init_db(db)
    v2 = fpdb.current_schema_version(db)
    assert v1 == v2 == 1


def test_init_db_creates_all_five_tables_plus_schema(tmp_path):
    db = tmp_path / "fp.sqlite"
    fpdb.init_db(db)
    with sqlite3.connect(str(db)) as c:
        names = {r[0] for r in c.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
    expected = {"schema_version", "charges", "postings", "payments",
                "payment_allocations", "settlements"}
    assert expected.issubset(names), f"Missing tables: {expected - names}"


def test_schema_version_table_records_v1(tmp_path):
    db = tmp_path / "fp.sqlite"
    fpdb.init_db(db)
    assert fpdb.current_schema_version(db) == 1


def test_current_schema_version_none_when_missing(tmp_path):
    assert fpdb.current_schema_version(tmp_path / "nope.sqlite") is None


# ── Allow-lists are exactly the architecture-approved set ──────────────────

def test_charge_types_allow_list_locked():
    assert fpdb.CHARGE_TYPES == frozenset({
        "net_goods", "freight", "insurance", "customs_duty",
        "vat_eu", "vat_pl", "rounding_adjustment", "fx_delta_at_settlement",
    })


def test_charge_sources_locked():
    assert fpdb.CHARGE_SOURCES == frozenset({
        "operator", "derived", "wfirma", "legacy_backfill"})


def test_posting_kinds_locked():
    assert fpdb.POSTING_KINDS == frozenset({"proforma", "invoice", "correction"})


def test_payment_sources_locked():
    assert fpdb.PAYMENT_SOURCES == frozenset({"wfirma", "bank_recon", "operator"})


def test_allocation_methods_locked():
    assert fpdb.ALLOCATION_METHODS == frozenset({"proportional", "operator_directed"})


# ── Charges validation ─────────────────────────────────────────────────────

def test_validate_charge_requires_all_fields():
    errs = fpdb.validate_charge({})
    for f in ("batch_id", "client_name", "charge_type", "amount_minor",
              "currency", "source"):
        assert any(f in e for e in errs), f"Missing required field error: {f}"


def test_validate_charge_rejects_unknown_type():
    errs = fpdb.validate_charge({
        "batch_id": "B1", "client_name": "C", "charge_type": "made_up",
        "amount_minor": 100, "currency": "EUR", "source": "operator",
    })
    assert any("charge_type" in e for e in errs)


def test_validate_charge_rejects_non_int_amount():
    errs = fpdb.validate_charge({
        "batch_id": "B1", "client_name": "C", "charge_type": "freight",
        "amount_minor": 12.50, "currency": "EUR", "source": "operator",  # float
    })
    assert any("amount_minor" in e and "int" in e for e in errs)


def test_validate_charge_rejects_non_iso_currency():
    errs = fpdb.validate_charge({
        "batch_id": "B1", "client_name": "C", "charge_type": "freight",
        "amount_minor": 100, "currency": "EUROPE", "source": "operator",
    })
    assert any("currency" in e for e in errs)


def test_validate_charge_rejects_unknown_source():
    errs = fpdb.validate_charge({
        "batch_id": "B1", "client_name": "C", "charge_type": "freight",
        "amount_minor": 100, "currency": "EUR", "source": "magic",
    })
    assert any("source" in e for e in errs)


def test_validate_charge_accepts_minimal_valid_row():
    assert fpdb.validate_charge({
        "batch_id": "B1", "client_name": "C", "charge_type": "freight",
        "amount_minor": 100, "currency": "EUR", "source": "operator",
    }) == []


# ── Charges CRUD ───────────────────────────────────────────────────────────

def test_create_charge_round_trip(tmp_path):
    db = tmp_path / "fp.sqlite"
    rec = fpdb.create_charge(db, {
        "batch_id": "B1", "client_name": "Acme",
        "charge_type": "freight", "amount_minor": 3500,
        "currency": "eur", "source": "operator", "notes": "test",
    })
    assert rec.id is not None
    assert rec.currency == "EUR"
    assert rec.amount_minor == 3500
    again = fpdb.get_charge(db, rec.id)
    assert again is not None
    assert again.charge_type == "freight"


def test_list_charges_filters(tmp_path):
    db = tmp_path / "fp.sqlite"
    fpdb.create_charge(db, {"batch_id": "B1", "client_name": "A",
                             "charge_type": "freight", "amount_minor": 100,
                             "currency": "EUR", "source": "operator"})
    fpdb.create_charge(db, {"batch_id": "B1", "client_name": "B",
                             "charge_type": "insurance", "amount_minor": 50,
                             "currency": "EUR", "source": "operator"})
    fpdb.create_charge(db, {"batch_id": "B2", "client_name": "A",
                             "charge_type": "freight", "amount_minor": 200,
                             "currency": "EUR", "source": "operator"})
    by_batch = fpdb.list_charges(db, batch_id="B1")
    by_client = fpdb.list_charges(db, client_name="A")
    by_type   = fpdb.list_charges(db, charge_type="insurance")
    assert len(by_batch) == 2
    assert len(by_client) == 2
    assert len(by_type) == 1


def test_link_charge_to_posting(tmp_path):
    db = tmp_path / "fp.sqlite"
    ch = fpdb.create_charge(db, {"batch_id": "B1", "client_name": "A",
                                  "charge_type": "freight", "amount_minor": 100,
                                  "currency": "EUR", "source": "operator"})
    p = fpdb.create_posting(db, {"batch_id": "B1", "client_name": "A",
                                  "posting_kind": "proforma",
                                  "issued_total_minor": 100, "currency": "EUR"})
    out = fpdb.link_charge_to_posting(db, ch.id, p.id)
    assert out is not None and out.posting_id == p.id


def test_link_unknown_charge_returns_none(tmp_path):
    db = tmp_path / "fp.sqlite"
    fpdb.init_db(db)
    assert fpdb.link_charge_to_posting(db, 9999, 1) is None


# ── Postings ───────────────────────────────────────────────────────────────

def test_validate_posting_rejects_unknown_kind():
    errs = fpdb.validate_posting({"batch_id": "B1", "client_name": "C",
                                   "posting_kind": "weird",
                                   "issued_total_minor": 100, "currency": "EUR"})
    assert any("posting_kind" in e for e in errs)


def test_create_posting_round_trip(tmp_path):
    db = tmp_path / "fp.sqlite"
    p = fpdb.create_posting(db, {"batch_id": "B1", "client_name": "A",
                                  "posting_kind": "invoice",
                                  "issued_total_minor": 5000, "currency": "EUR",
                                  "wfirma_invoice_id": "WF-001"})
    assert p.id is not None
    assert fpdb.get_posting(db, p.id).wfirma_invoice_id == "WF-001"


def test_list_postings_filters(tmp_path):
    db = tmp_path / "fp.sqlite"
    fpdb.create_posting(db, {"batch_id": "B1", "client_name": "A",
                              "posting_kind": "proforma",
                              "issued_total_minor": 1, "currency": "EUR"})
    fpdb.create_posting(db, {"batch_id": "B2", "client_name": "A",
                              "posting_kind": "proforma",
                              "issued_total_minor": 1, "currency": "EUR"})
    fpdb.create_posting(db, {"batch_id": "B1", "client_name": "B",
                              "posting_kind": "proforma",
                              "issued_total_minor": 1, "currency": "EUR"})
    by_batch = fpdb.list_postings(db, batch_id="B1")
    by_client = fpdb.list_postings(db, client_name="A")
    assert len(by_batch) == 2
    assert len(by_client) == 2


# ── Payments ───────────────────────────────────────────────────────────────

def test_validate_payment_rejects_missing_posting_id():
    errs = fpdb.validate_payment({"paid_at": "2026-05-16",
                                   "amount_minor": 1000, "currency": "EUR",
                                   "source": "operator"})
    assert any("posting_id" in e for e in errs)


def test_validate_payment_rejects_bad_date():
    errs = fpdb.validate_payment({"posting_id": 1, "paid_at": "16/05/2026",
                                   "amount_minor": 1, "currency": "EUR",
                                   "source": "operator"})
    assert any("paid_at" in e for e in errs)


def test_create_payment_round_trip(tmp_path):
    db = tmp_path / "fp.sqlite"
    p = fpdb.create_posting(db, {"batch_id": "B1", "client_name": "A",
                                  "posting_kind": "invoice",
                                  "issued_total_minor": 5000, "currency": "EUR"})
    pay = fpdb.create_payment(db, {"posting_id": p.id, "paid_at": "2026-05-16",
                                    "amount_minor": 5000, "currency": "EUR",
                                    "source": "operator"})
    assert pay.id is not None
    assert fpdb.get_payment(db, pay.id).amount_minor == 5000


def test_payment_uniqueness_by_wfirma_payment_id(tmp_path):
    db = tmp_path / "fp.sqlite"
    p = fpdb.create_posting(db, {"batch_id": "B1", "client_name": "A",
                                  "posting_kind": "invoice",
                                  "issued_total_minor": 5000, "currency": "EUR"})
    fpdb.create_payment(db, {"posting_id": p.id, "paid_at": "2026-05-16",
                              "amount_minor": 100, "currency": "EUR",
                              "wfirma_payment_id": "WFP-1", "source": "wfirma"})
    with pytest.raises(ValueError, match="DUPLICATE_PAYMENT"):
        fpdb.create_payment(db, {"posting_id": p.id, "paid_at": "2026-05-17",
                                  "amount_minor": 50, "currency": "EUR",
                                  "wfirma_payment_id": "WFP-1", "source": "wfirma"})


def test_payment_without_wfirma_id_is_not_unique_constrained(tmp_path):
    """Operator-recorded payments (no wfirma_payment_id) must not collide.
    Partial UNIQUE INDEX WHERE wfirma_payment_id IS NOT NULL takes care of this."""
    db = tmp_path / "fp.sqlite"
    p = fpdb.create_posting(db, {"batch_id": "B1", "client_name": "A",
                                  "posting_kind": "invoice",
                                  "issued_total_minor": 1, "currency": "EUR"})
    fpdb.create_payment(db, {"posting_id": p.id, "paid_at": "2026-05-16",
                              "amount_minor": 100, "currency": "EUR",
                              "source": "operator"})
    # Second payment same posting, no wfirma id — should NOT collide
    fpdb.create_payment(db, {"posting_id": p.id, "paid_at": "2026-05-17",
                              "amount_minor": 50, "currency": "EUR",
                              "source": "operator"})
    assert len(fpdb.list_payments(db, posting_id=p.id)) == 2


# ── Allocations ────────────────────────────────────────────────────────────

def test_validate_allocation_requires_ints():
    errs = fpdb.validate_allocation({"payment_id": "x", "charge_id": 1,
                                      "applied_minor": 1,
                                      "allocation_method": "proportional"})
    assert any("payment_id" in e for e in errs)


def test_validate_allocation_rejects_negative_applied():
    errs = fpdb.validate_allocation({"payment_id": 1, "charge_id": 1,
                                      "applied_minor": -10,
                                      "allocation_method": "proportional"})
    assert any("applied_minor" in e for e in errs)


def test_create_allocation_round_trip(tmp_path):
    db = tmp_path / "fp.sqlite"
    p = fpdb.create_posting(db, {"batch_id": "B1", "client_name": "A",
                                  "posting_kind": "invoice",
                                  "issued_total_minor": 100, "currency": "EUR"})
    ch = fpdb.create_charge(db, {"batch_id": "B1", "client_name": "A",
                                  "charge_type": "freight", "amount_minor": 100,
                                  "currency": "EUR", "source": "operator",
                                  "posting_id": p.id})
    pay = fpdb.create_payment(db, {"posting_id": p.id, "paid_at": "2026-05-16",
                                    "amount_minor": 100, "currency": "EUR",
                                    "source": "operator"})
    a = fpdb.create_allocation(db, {"payment_id": pay.id, "charge_id": ch.id,
                                     "applied_minor": 100,
                                     "allocation_method": "proportional"})
    assert a.id is not None
    assert fpdb.get_allocation(db, a.id).applied_minor == 100


def test_list_allocations_filters(tmp_path):
    db = tmp_path / "fp.sqlite"
    p = fpdb.create_posting(db, {"batch_id": "B1", "client_name": "A",
                                  "posting_kind": "invoice",
                                  "issued_total_minor": 200, "currency": "EUR"})
    ch1 = fpdb.create_charge(db, {"batch_id": "B1", "client_name": "A",
                                   "charge_type": "freight", "amount_minor": 100,
                                   "currency": "EUR", "source": "operator",
                                   "posting_id": p.id})
    ch2 = fpdb.create_charge(db, {"batch_id": "B1", "client_name": "A",
                                   "charge_type": "insurance", "amount_minor": 100,
                                   "currency": "EUR", "source": "operator",
                                   "posting_id": p.id})
    pay = fpdb.create_payment(db, {"posting_id": p.id, "paid_at": "2026-05-16",
                                    "amount_minor": 200, "currency": "EUR",
                                    "source": "operator"})
    fpdb.create_allocation(db, {"payment_id": pay.id, "charge_id": ch1.id,
                                 "applied_minor": 100,
                                 "allocation_method": "proportional"})
    fpdb.create_allocation(db, {"payment_id": pay.id, "charge_id": ch2.id,
                                 "applied_minor": 100,
                                 "allocation_method": "proportional"})
    assert len(fpdb.list_allocations(db, payment_id=pay.id)) == 2
    assert len(fpdb.list_allocations(db, charge_id=ch1.id)) == 1


# ── Settlements ────────────────────────────────────────────────────────────

def test_record_settlement_round_trip(tmp_path):
    db = tmp_path / "fp.sqlite"
    p = fpdb.create_posting(db, {"batch_id": "B1", "client_name": "A",
                                  "posting_kind": "invoice",
                                  "issued_total_minor": 100, "currency": "EUR"})
    s = fpdb.record_settlement(db, {"posting_id": p.id,
                                     "fx_delta_total_minor": 5,
                                     "rounding_diff_minor": 1})
    assert s.id is not None
    assert fpdb.get_settlement_for_posting(db, p.id).fx_delta_total_minor == 5


def test_settlement_unique_per_posting(tmp_path):
    db = tmp_path / "fp.sqlite"
    p = fpdb.create_posting(db, {"batch_id": "B1", "client_name": "A",
                                  "posting_kind": "invoice",
                                  "issued_total_minor": 100, "currency": "EUR"})
    fpdb.record_settlement(db, {"posting_id": p.id})
    with pytest.raises(ValueError, match="SETTLEMENT_EXISTS"):
        fpdb.record_settlement(db, {"posting_id": p.id})


# ── Pure helpers ───────────────────────────────────────────────────────────

def test_compute_sums_and_fully_paid(tmp_path):
    db = tmp_path / "fp.sqlite"
    p = fpdb.create_posting(db, {"batch_id": "B1", "client_name": "A",
                                  "posting_kind": "invoice",
                                  "issued_total_minor": 200, "currency": "EUR"})
    fpdb.create_charge(db, {"batch_id": "B1", "client_name": "A",
                             "charge_type": "freight", "amount_minor": 200,
                             "currency": "EUR", "source": "operator",
                             "posting_id": p.id})
    assert fpdb.compute_sum_charges_minor(db, p.id) == 200
    assert fpdb.compute_sum_payments_minor(db, p.id) == 0
    assert fpdb.is_fully_paid(db, p.id) is False

    fpdb.create_payment(db, {"posting_id": p.id, "paid_at": "2026-05-16",
                              "amount_minor": 199, "currency": "EUR",
                              "source": "operator"})
    # Within 1-cent tolerance
    assert fpdb.is_fully_paid(db, p.id) is True


def test_empty_db_helpers_return_safe_defaults(tmp_path):
    db = tmp_path / "missing.sqlite"
    assert fpdb.compute_sum_charges_minor(db, 1) == 0
    assert fpdb.compute_sum_payments_minor(db, 1) == 0
    assert fpdb.is_fully_paid(db, 1) is True  # 0 == 0


# ── Behaviour-isolation tests (Phase 6F.1 must NOT couple to anything) ─────

def test_module_does_not_import_wfirma_or_pz_engine():
    """The new module must NOT import wFirma, proforma, or PZ engine modules."""
    src = Path(fpdb.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "from ..api.routes_wfirma",
        "from ..api.routes_proforma",
        "from ..services.wfirma_client",
        "from ..services.proforma_pz",
        "from ..services.ledger_aggregator",
        "from ..services.proforma_service_charges_db",
        "import pz_import_processor",
    ):
        assert forbidden not in src, \
            f"finance_postings_db must not import: {forbidden}"


def test_module_does_not_open_existing_dbs():
    """The new module must only touch finance_postings.sqlite. No reads/writes
    against customer_master.sqlite, suppliers.sqlite, master_data.sqlite,
    packing.db, warehouse.db, etc."""
    src = Path(fpdb.__file__).read_text(encoding="utf-8")
    for forbidden in ("customer_master.sqlite", "suppliers.sqlite",
                      "master_data.sqlite", "packing.db",
                      "warehouse.db", "wfirma.db", "documents.db",
                      "proforma_links.db"):
        assert forbidden not in src, \
            f"finance_postings_db must not reference: {forbidden}"
