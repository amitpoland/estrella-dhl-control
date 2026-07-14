"""Slice 1 — Customer Master commercial suggestions in Proforma V2.

Pins the read-only advisory projection added to the proforma draft GET:
draft values and Customer Master defaults stay SEPARATE, every field carries an
honest SOURCE label (saved / suggested / conflict / missing), duplicate
contractor identities are surfaced (never auto-merged), and the projection
never mutates the draft, the DB, or the posting payload.

Synthetic fixtures only (no real customer data). The scenario reproduces a
duplicate-identity customer shape:
  • trade-name contractor — EUR, 7 days, transfer, USD-83 freight, ins rate
  • legal-name contractor — same VAT number, different contractor id
  • active draft is USD with 30 payment days → currency + days CONFLICT.
"""
from __future__ import annotations

import copy
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.core.config import settings
from app.services import customer_master_db as cmdb
from app.api import routes_proforma as rp

# Synthetic identifiers — deliberately not any real contractor/VAT number.
CID_TRADE = "70000001"
CID_LEGAL = "70000002"
VAT_NO = "BG000000000"
TRADE_NAME = "Test Jewellery House"
LEGAL_NAME = "TEST JEWELLERY EOOD"


def _seed(db: Path) -> None:
    cmdb.init_db(db)
    now = "2026-07-01T00:00:00Z"
    cols = (
        "bill_to_contractor_id, bill_to_name, country, nip, vat_eu_number, "
        "default_currency, default_language_id, payment_terms_days, "
        "preferred_payment_method, freight_fixed_amount_usd, freight_currency, "
        "freight_mode, insurance_rate, freight_service_id, insurance_service_id, "
        "created_at, updated_at"
    )
    ph = ",".join(["?"] * 17)
    rows = [
        # trade-name row: full commercial defaults, freight/insurance service_id UNSET.
        (CID_TRADE, TRADE_NAME, "BG", VAT_NO, VAT_NO,
         "EUR", "1", 7, "transfer", "83", "USD", "fixed", "0.0035", None, None,
         now, now),
        # legal-name row: same VAT number, different contractor id (duplicate identity).
        (CID_LEGAL, LEGAL_NAME, "BG", VAT_NO, None,
         None, None, None, None, None, None, None, None, "13002743", "13102217",
         now, now),
    ]
    with sqlite3.connect(db) as con:
        con.executemany(
            f"INSERT INTO customer_master ({cols}) VALUES ({ph})", rows
        )
        con.commit()


def _draft(**over):
    base = dict(client_contractor_id=CID_TRADE,
                client_name=TRADE_NAME,
                currency="USD")
    base.update(over)
    return SimpleNamespace(**base)


def _full(**over):
    base = {
        "payment_terms": {"days": 30, "method": "transfer", "invoice_date": "2026-07-10"},
        "service_charges": [
            {"charge_type": "freight", "amount": 83.0, "currency": "USD", "wfirma_service_id": None},
            {"charge_type": "insurance", "amount": 10.0, "currency": "USD", "wfirma_service_id": None},
        ],
        "wfirma_payment_method": None,
        "vat_code": None,
        "vat_context": None,
    }
    base.update(over)
    return base


@pytest.fixture()
def seeded(tmp_path):
    _seed(tmp_path / "customer_master.sqlite")
    with patch.object(settings, "storage_root", tmp_path):
        yield tmp_path


def _by_key(sug, key):
    return next(f for f in sug["fields"] if f["key"] == key)


# ── status + identity ────────────────────────────────────────────────────────

def test_mapped_status_and_identity_conflict(seeded):
    sug = rp._customer_master_suggestions(_draft(), _full())
    assert sug["status"] == "mapped"
    assert sug["mapped_contractor_id"] == CID_TRADE
    conflict = sug["identity_conflict"]
    assert conflict is not None, "duplicate VAT identity must be surfaced"
    assert conflict["vat_number"] == VAT_NO
    ids = {c["contractor_id"] for c in conflict["contractors"]}
    assert ids == {CID_TRADE, CID_LEGAL}
    assert conflict["mapped_contractor_id"] == CID_TRADE


# ── source labels ────────────────────────────────────────────────────────────

def test_source_labels_are_correct(seeded):
    sug = rp._customer_master_suggestions(_draft(), _full())
    expect = {
        "customer_name": "saved",
        "contractor_id": "saved",
        "currency": "conflict",       # USD draft vs EUR CM
        "payment_method": "saved",    # transfer == transfer
        "payment_days": "conflict",   # 30 draft vs 7 CM
        "invoice_language": "suggested",
        "freight_amount": "saved",    # 83 == 83
        "freight_service_id": "missing",
        "insurance_amount": "saved",  # draft 10, CM none
        "insurance_rate": "suggested",
        "insurance_service_id": "missing",
    }
    for key, src in expect.items():
        assert _by_key(sug, key)["source"] == src, f"{key} expected {src}"
    # VAT/WDT: a DERIVED hint (no stored vat_mode) is 'advisory'; an explicit
    # stored vat_mode override is 'suggested'; neither present → 'missing'.
    # Never falsely "saved".
    _vat = _by_key(sug, "vat_wdt")
    assert _vat["source"] in {"suggested", "advisory", "missing"}
    # A derived-only hint must be marked non-applicable (not a selectable default).
    if _vat["source"] == "advisory":
        assert _vat.get("applicable") is False


def test_currency_conflict_keeps_draft_usd_visible(seeded):
    f = _by_key(rp._customer_master_suggestions(_draft(), _full()), "currency")
    assert f["draft"] == "USD"
    assert f["suggestion"] == "EUR"
    assert f["source"] == "conflict"


def test_payment_days_not_overwritten(seeded):
    f = _by_key(rp._customer_master_suggestions(_draft(), _full()), "payment_days")
    assert f["draft"] == 30
    assert f["suggestion"] == 7
    assert f["source"] == "conflict"


def test_missing_renders_honestly(seeded):
    sug = rp._customer_master_suggestions(_draft(), _full())
    for key in ("freight_service_id", "insurance_service_id"):
        f = _by_key(sug, key)
        assert f["draft"] is None and f["suggestion"] is None
        assert f["source"] == "missing"


# ── ID-first resolution ──────────────────────────────────────────────────────

def test_unmapped_when_draft_has_no_contractor_id(seeded):
    sug = rp._customer_master_suggestions(_draft(client_contractor_id=""), _full())
    assert sug["status"] == "unmapped"
    assert sug["reason"] == "draft_has_no_contractor_id"
    assert sug["fields"] == []
    assert sug["identity_conflict"] is None


def test_id_first_never_resolves_by_name(seeded):
    # Correct NAME, but a contractor id that is NOT in Customer Master → must
    # NOT silently fall back to a name lookup.
    sug = rp._customer_master_suggestions(
        _draft(client_contractor_id="99999999"), _full())
    assert sug["status"] == "unmapped"
    assert sug["reason"] == "contractor_not_in_customer_master"
    assert sug["mapped_contractor_id"] == "99999999"


# ── read-only guarantees ─────────────────────────────────────────────────────

def test_helper_does_not_mutate_full_or_db(seeded):
    db = seeded / "customer_master.sqlite"
    before = sqlite3.connect(db).execute(
        "SELECT bill_to_contractor_id, bill_to_name, default_currency, "
        "payment_terms_days FROM customer_master ORDER BY id"
    ).fetchall()
    full = _full()
    snapshot = copy.deepcopy(full)
    rp._customer_master_suggestions(_draft(), full)
    # helper does not add its own key (wiring adds it in _draft_to_full)
    assert "customer_master_suggestions" not in full
    assert full == snapshot, "helper must not mutate the passed draft payload"
    after = sqlite3.connect(db).execute(
        "SELECT bill_to_contractor_id, bill_to_name, default_currency, "
        "payment_terms_days FROM customer_master ORDER BY id"
    ).fetchall()
    assert before == after, "advisory projection must never write the DB"


def test_suggestions_absent_from_posting_summary():
    # _draft_to_summary feeds the posting-relevant view; the advisory block is
    # additive to _draft_to_full ONLY, never to the summary/posting payload.
    src = Path(rp.__file__).read_text(encoding="utf-8-sig")
    # Body of _draft_to_summary only (up to the next top-level def).
    summary = src.split("def _draft_to_summary", 1)[1].split("\ndef ", 1)[0]
    assert "customer_master_suggestions" not in summary


def test_find_by_nip_is_read_only():
    # Guard: the duplicate-identity helper must be a pure SELECT.
    src = Path(cmdb.__file__).read_text(encoding="utf-8-sig")
    body = src.split("def find_customers_by_nip", 1)[1].split("\ndef ", 1)[0]
    lowered = body.lower()
    assert "select" in lowered
    for kw in ("insert", "update ", "delete", "drop", "replace"):
        assert kw not in lowered, f"find_customers_by_nip must not {kw!r}"


# ── frontend wiring (source-grep) ────────────────────────────────────────────

def test_frontend_section_wired():
    jsx = (Path(rp.__file__).parent.parent / "static" / "v2" / "proforma-detail.jsx"
           ).read_text(encoding="utf-8")
    assert "CustomerMasterSuggestions" in jsx
    assert 'data-testid="cm-suggestions-section"' in jsx
    assert "customer_master_suggestions" in jsx
    assert 'data-testid="cm-identity-conflict"' in jsx
    # CM_SRC_BADGE now includes the 'advisory' source (derived VAT/WDT hint).
    badge_block = jsx.split("CM_SRC_BADGE", 1)[1][:800]
    for src in ("saved", "suggested", "conflict", "advisory", "missing"):
        assert f"{src}:" in badge_block
