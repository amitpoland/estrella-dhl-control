"""Phase 6F.5 — Lesson A real-builder regression test.

Stub-based tests can mask production bugs by mismatching real return
shapes. This test drives the dual-write through the REAL
``dual_write_proforma_post`` against the REAL ``finance_postings_db``
module (no mocks), with a payload constructed in exactly the same
shape that ``routes_proforma.py`` produces after ``mark_post_succeeded``
returns.

It also asserts the actual JSONResponse-input data flowing into the
helper would be type-correct.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services import finance_dual_write as fdw
from app.services import finance_postings_db as fpdb


# Mirrors the keys that routes_proforma reads from ``posted`` after
# ``pildb.mark_post_succeeded`` returns. We do NOT stub these — instead we
# build the call exactly as the route does.
def _route_invocation_kwargs(*, posted_attrs: dict, full_number: str, db_path: Path) -> dict:
    return dict(
        db_path              = db_path,
        batch_id             = posted_attrs["batch_id"] or "",
        client_name          = posted_attrs["client_name"] or "",
        currency             = posted_attrs["currency"] or "",
        full_number          = full_number,
        service_charges_json = posted_attrs["service_charges_json"],
        enabled              = True,
        shadow               = False,
    )


def test_real_builder_end_to_end_no_charges(tmp_path: Path):
    """Real-builder path: empty service_charges_json → 1 posting, 0 charges."""
    db = tmp_path / "finance_postings.sqlite"
    posted = {
        "batch_id":             "B/RB/001",
        "client_name":          "Real Builder Co",
        "currency":             "EUR",
        "service_charges_json": "[]",
    }
    kwargs = _route_invocation_kwargs(
        posted_attrs=posted, full_number="FV/RB/1/2026", db_path=db,
    )
    res = fdw.dual_write_proforma_post(**kwargs)

    assert isinstance(res, dict)
    assert res["ok"] is True
    assert res["mode"] == "live"
    assert res["created_posting"] is True
    assert res["created_charges"] == 0
    # Real-DB verification
    postings = fpdb.list_postings(db, batch_id="B/RB/001")
    charges  = fpdb.list_charges(db,  batch_id="B/RB/001")
    assert len(postings) == 1
    assert len(charges) == 0
    p = postings[0]
    assert p.wfirma_invoice_id.startswith("LIVE-")
    assert p.posting_kind == "proforma"
    assert p.currency == "EUR"
    assert p.issued_total_minor == 0


def test_real_builder_end_to_end_with_charges(tmp_path: Path):
    """Real-builder path: 2 charges → 1 posting, 2 charges, totals match."""
    db = tmp_path / "finance_postings.sqlite"
    posted = {
        "batch_id":    "B/RB/002",
        "client_name": "Real Builder Co",
        "currency":    "EUR",
        "service_charges_json": json.dumps([
            {"charge_type": "freight",   "amount": 12.34, "currency": "EUR"},
            {"charge_type": "insurance", "amount":  2.50, "currency": "EUR"},
        ]),
    }
    kwargs = _route_invocation_kwargs(
        posted_attrs=posted, full_number="FV/RB/2/2026", db_path=db,
    )
    res = fdw.dual_write_proforma_post(**kwargs)
    assert res["ok"] is True
    assert res["created_charges"] == 2
    postings = fpdb.list_postings(db, batch_id="B/RB/002")
    assert len(postings) == 1
    assert postings[0].issued_total_minor == 1234 + 250
    charges = fpdb.list_charges(db, batch_id="B/RB/002")
    minors = sorted(c.amount_minor for c in charges)
    assert minors == [250, 1234]
    # Every charge is linked to the synthetic posting.
    assert all(c.posting_id == postings[0].id for c in charges)
    # Sources are "operator" — not "legacy_backfill"
    assert {c.source for c in charges} == {"operator"}


def test_real_builder_breakdown_endpoint_path_is_compatible(tmp_path: Path):
    """The dual-write must produce rows that the 6F.3 breakdown endpoint can read.

    We invoke the breakdown query helpers directly (no HTTP), since the
    route just packages those into JSON. This proves the integration
    contract: dual-write writes data the read endpoint can consume.
    """
    db = tmp_path / "finance_postings.sqlite"
    fdw.dual_write_proforma_post(
        db_path=db,
        batch_id="B/RB/BREAKDOWN",
        client_name="BD Co",
        currency="EUR",
        full_number="FV/BD/1/2026",
        service_charges_json='[{"charge_type":"freight","amount":1.00,"currency":"EUR"}]',
        enabled=True, shadow=False,
    )
    postings = fpdb.list_postings(db, batch_id="B/RB/BREAKDOWN")
    assert len(postings) == 1
    posting_id = postings[0].id

    # Exercise the exact helpers routes_finance_postings.get_breakdown calls.
    posting = fpdb.get_posting(db, posting_id)
    charges = fpdb.list_charges(db, posting_id=posting_id)
    assert posting is not None
    assert posting.wfirma_invoice_id.startswith("LIVE-")
    assert len(charges) == 1
    assert charges[0].amount_minor == 100
    assert charges[0].source == "operator"


def test_real_builder_currency_normalisation(tmp_path: Path):
    """Lower-case currency in source → upper-case after persistence."""
    db = tmp_path / "finance_postings.sqlite"
    res = fdw.dual_write_proforma_post(
        db_path=db,
        batch_id="B/RB/CCY",
        client_name="Currency Co",
        currency="eur",
        full_number="FV/CCY/1/2026",
        service_charges_json='[{"charge_type":"freight","amount":1.00,"currency":"eur"}]',
        enabled=True, shadow=False,
    )
    assert res["ok"] is True
    postings = fpdb.list_postings(db, batch_id="B/RB/CCY")
    assert postings[0].currency == "EUR"
    charges = fpdb.list_charges(db, batch_id="B/RB/CCY")
    assert charges[0].currency == "EUR"
