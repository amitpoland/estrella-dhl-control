"""B-004 — draft birth and created_from_sales_packing are one transaction."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from app.services import proforma_invoice_link_db as pildb


@pytest.fixture()
def db_path(tmp_path) -> Path:
    p = tmp_path / "proforma_links.db"
    pildb.init_db(p)
    return p


def _lines():
    return [{
        "product_code": "RNG-100",
        "design_no": "D100",
        "quantity": 1,
        "unit_price": 10.0,
        "currency": "EUR",
        "price_source": "packing_list",
        "client_ref": "R1",
    }]


def _counts(db: Path, *, batch_id: str = "B1", client_name: str = "ACME"):
    with sqlite3.connect(str(db)) as con:
        drafts = con.execute(
            "SELECT COUNT(*) FROM proforma_drafts "
            "WHERE batch_id=? AND client_name=?",
            (batch_id, client_name),
        ).fetchone()[0]
        events = con.execute(
            "SELECT COUNT(*) FROM proforma_draft_events e "
            "JOIN proforma_drafts d ON d.id=e.draft_id "
            "WHERE d.batch_id=? AND d.client_name=? "
            "AND e.event='created_from_sales_packing'",
            (batch_id, client_name),
        ).fetchone()[0]
        all_events = con.execute(
            "SELECT COUNT(*) FROM proforma_draft_events"
        ).fetchone()[0]
    return drafts, events, all_events


def test_normal_birth_one_draft_one_birth_event(db_path):
    draft, created = pildb.auto_create_draft_from_sales_packing(
        db_path, batch_id="B1", client_name="ACME",
        currency="EUR", lines=_lines(), operator="op",
    )
    assert created is True
    d, e, _ = _counts(db_path)
    assert (d, e) == (1, 1)
    ev = pildb.list_draft_events(db_path, draft.id)
    assert len(ev) == 1
    assert ev[0]["event"] == "created_from_sales_packing"
    detail = json.loads(ev[0]["detail_json"])
    assert detail["batch_id"] == "B1"
    assert detail["client_name"] == "ACME"
    assert detail["currency"] == "EUR"
    assert detail["line_count"] == 1
    assert "birth_unresolved" in detail
    assert ev[0]["operator"] == "op"


def test_event_insert_failure_rolls_back_draft(db_path, monkeypatch):
    real = pildb._record_draft_event_conn

    def boom(conn, **kwargs):
        raise sqlite3.OperationalError("injected birth-event failure")

    monkeypatch.setattr(pildb, "_record_draft_event_conn", boom)
    with pytest.raises(sqlite3.OperationalError, match="injected"):
        pildb.auto_create_draft_from_sales_packing(
            db_path, batch_id="B1", client_name="ACME",
            currency="EUR", lines=_lines(),
        )
    d, e, all_e = _counts(db_path)
    assert (d, e, all_e) == (0, 0, 0)

    # Restore and retry → clean successful birth
    monkeypatch.setattr(pildb, "_record_draft_event_conn", real)
    draft, created = pildb.auto_create_draft_from_sales_packing(
        db_path, batch_id="B1", client_name="ACME",
        currency="EUR", lines=_lines(),
    )
    assert created is True
    assert draft.id > 0
    assert _counts(db_path)[:2] == (1, 1)


def test_idempotent_retry_no_duplicate_birth_event(db_path):
    d1, c1 = pildb.auto_create_draft_from_sales_packing(
        db_path, batch_id="B1", client_name="ACME",
        currency="EUR", lines=_lines(),
    )
    d2, c2 = pildb.auto_create_draft_from_sales_packing(
        db_path, batch_id="B1", client_name="ACME",
        currency="EUR", lines=_lines(),
    )
    assert c1 is True and c2 is False
    assert d1.id == d2.id
    assert _counts(db_path)[:2] == (1, 1)


def test_post_birth_record_draft_event_still_works(db_path):
    draft, _ = pildb.auto_create_draft_from_sales_packing(
        db_path, batch_id="B1", client_name="ACME",
        currency="EUR", lines=_lines(),
    )
    eid = pildb._record_draft_event(
        db_path, draft_id=draft.id, event="manual_test",
        detail_json='{"k":"v"}', operator="op1",
    )
    assert eid > 0
    events = pildb.list_draft_events(db_path, draft.id)
    assert [e["event"] for e in events] == [
        "created_from_sales_packing", "manual_test",
    ]


def test_source_birth_uses_conn_helper_not_public_wrapper():
    src = Path(pildb.__file__).read_text(encoding="utf-8")
    start = src.index("def auto_create_draft_from_sales_packing")
    end = src.index("# ── Phase 3 — editable draft mutation API", start)
    body = src[start:end]
    assert "_record_draft_event_conn(" in body
    assert "created_from_sales_packing" in body
    # Strip the conn helper name so a lone public wrapper call would remain.
    stripped = body.replace("_record_draft_event_conn", "")
    assert "_record_draft_event(" not in stripped
