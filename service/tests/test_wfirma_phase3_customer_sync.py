"""
Phase 3 — webhook-triggered customer sync processor tests.

Covers:
  1. Happy path: contractor fetched → snapshot inserted → CM row inserted.
  2. Happy path: CM row exists → name overwritten, operator email preserved.
  3. Skip: no contractor_id in invoice XML (<contractor> node absent).
  4. Skip: contractor_id is "0" (wFirma null sentinel).
  5. Fail + retry counter: fetch_contractor_by_id returns ok=False.
  6. Fail + retry counter: upsert_identity_only raises.
  7. Exhausted attempts: event excluded from pending query after MAX retries.
  8. Idempotency: already-synced event is excluded from pending query.
  9. Phase 3 migration: columns added to existing processing table.
 10. get_customer_sync_pending_events: only terminal states with snapshots qualify.
 11. get_customer_sync_pending_events: events without invoice snapshots excluded.
"""
from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest


# ── Constants & XML fixtures ──────────────────────────────────────────────────

_NOW          = "2026-06-30T10:00:00+00:00"
_EVENT_ID     = "EVT-P3-001"
_OBJECT_ID    = "484110947"
_CONTRACTOR_ID = "173845539"

_INVOICE_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<api>
  <invoices>
    <invoice>
      <id>{_OBJECT_ID}</id>
      <fullnumber>FV 1/2026</fullnumber>
      <currency>EUR</currency>
      <date>2026-06-28</date>
      <paymentdate>2026-07-12</paymentdate>
      <paymentmethod>transfer</paymentmethod>
      <contractor>
        <id>{_CONTRACTOR_ID}</id>
        <altname>OMARA s.r.o</altname>
        <email>info@omara.sk</email>
      </contractor>
      <contractor_receiver><id>0</id></contractor_receiver>
    </invoice>
  </invoices>
</api>"""

_XML_NO_CONTRACTOR = """<?xml version="1.0" encoding="UTF-8"?>
<api><invoices><invoice><id>9</id><fullnumber>FV 2/2026</fullnumber></invoice></invoices></api>"""

_XML_ZERO_CONTRACTOR = """<?xml version="1.0" encoding="UTF-8"?>
<api><invoices><invoice><id>10</id><contractor><id>0</id></contractor></invoice></invoices></api>"""


def _make_result(ok=True, **overrides):
    defaults = dict(
        ok=ok, contractor_id=_CONTRACTOR_ID,
        name="OMARA s.r.o", nip="SK2020371878",
        country="SK", street="Nám. SNP 1",
        city="Bratislava", zip="811 01",
        email="info@omara.sk", phone="421949432014",
        mobile="", regon="",
        account_number="SK1234",
        payment_days="14",
        translation_language_id="",
        skype="", fax="", url="", description="",
        discount_percent="", buyer="", seller="",
        receiver="", tags="",
        different_contact_address=False,
        contact_name="", contact_person="",
        contact_street="", contact_city="",
        contact_zip="", contact_country="",
        raw_response="<xml/>", error=None,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


# ── DB fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture()
def proc_db(tmp_path):
    from app.services.wfirma_processing_db import init_db
    db = tmp_path / "proc.db"
    init_db(db)
    return db


@pytest.fixture()
def cm_db(tmp_path):
    from app.services.customer_master_db import init_db as cm_init
    db = tmp_path / "customer_master.sqlite"
    cm_init(db)
    return db


def _seed(proc_db: Path, *, state="COMPLETED", xml=_INVOICE_XML,
          event_id=_EVENT_ID, object_id=_OBJECT_ID):
    """Insert a processing row + invoice snapshot."""
    from app.services.wfirma_processing_db import (
        ensure_processing_row, insert_snapshot, set_state,
    )
    ensure_processing_row(proc_db, event_id, object_id, _NOW)
    insert_snapshot(
        proc_db,
        snapshot_id=str(uuid.uuid4()),
        event_id=event_id,
        object_id=object_id,
        fetched_at=_NOW,
        raw_xml=xml,
        parsed={"invoice_number": "FV 1/2026", "currency": "EUR"},
        raw_payload="{}",
    )
    set_state(proc_db, event_id, state)


# ── _extract_contractor_id_from_xml ──────────────────────────────────────────


def test_extract_happy():
    from app.services.wfirma_customer_sync_processor import _extract_contractor_id_from_xml
    assert _extract_contractor_id_from_xml(_INVOICE_XML) == _CONTRACTOR_ID


def test_extract_no_contractor_node():
    from app.services.wfirma_customer_sync_processor import _extract_contractor_id_from_xml
    assert _extract_contractor_id_from_xml(_XML_NO_CONTRACTOR) is None


def test_extract_zero_sentinel():
    from app.services.wfirma_customer_sync_processor import _extract_contractor_id_from_xml
    assert _extract_contractor_id_from_xml(_XML_ZERO_CONTRACTOR) is None


def test_extract_malformed_xml():
    from app.services.wfirma_customer_sync_processor import _extract_contractor_id_from_xml
    assert _extract_contractor_id_from_xml("<<<bad") is None


# ── sync_customer_from_snapshot happy path ────────────────────────────────────


def test_happy_path_inserts_cm_row(proc_db, cm_db):
    _seed(proc_db)
    with patch(
        "app.services.wfirma_client.fetch_contractor_by_id",
        return_value=_make_result(),
    ):
        from app.services.wfirma_customer_sync_processor import sync_customer_from_snapshot
        result = sync_customer_from_snapshot(
            event_id=_EVENT_ID, proc_db=proc_db, cm_db=cm_db, now=_NOW,
        )

    assert result == "CUSTOMER_SYNCED"

    # immutable customer snapshot stored
    with sqlite3.connect(str(proc_db)) as conn:
        row = conn.execute(
            "SELECT contractor_id, name, email FROM wfirma_customer_snapshots WHERE event_id = ?",
            (_EVENT_ID,),
        ).fetchone()
    assert row is not None
    assert row[0] == _CONTRACTOR_ID
    assert row[1] == "OMARA s.r.o"
    assert row[2] == "info@omara.sk"

    # processing row marked synced
    with sqlite3.connect(str(proc_db)) as conn:
        row = conn.execute(
            "SELECT customer_synced_at FROM wfirma_webhook_processing WHERE event_id = ?",
            (_EVENT_ID,),
        ).fetchone()
    assert row[0] == _NOW

    # customer_master row created
    with sqlite3.connect(str(cm_db)) as conn:
        row = conn.execute(
            "SELECT bill_to_name, country, bill_to_email "
            "FROM customer_master WHERE bill_to_contractor_id = ?",
            (_CONTRACTOR_ID,),
        ).fetchone()
    assert row is not None
    assert row[0] == "OMARA s.r.o"
    assert row[1] == "SK"
    assert row[2] == "info@omara.sk"


def test_happy_path_preserves_operator_email(proc_db, cm_db):
    """Existing CM row with operator-entered email — wFirma must not overwrite it."""
    from app.services.customer_master_db import upsert_identity_only
    upsert_identity_only(
        cm_db,
        bill_to_contractor_id=_CONTRACTOR_ID,
        bill_to_name="Old Name",
        country="SK",
        bill_to_email="operator@existing.com",
        sync_source="operator",
    )

    _seed(proc_db)
    with patch(
        "app.services.wfirma_client.fetch_contractor_by_id",
        return_value=_make_result(),
    ):
        from app.services.wfirma_customer_sync_processor import sync_customer_from_snapshot
        sync_customer_from_snapshot(
            event_id=_EVENT_ID, proc_db=proc_db, cm_db=cm_db, now=_NOW,
        )

    with sqlite3.connect(str(cm_db)) as conn:
        row = conn.execute(
            "SELECT bill_to_name, bill_to_email FROM customer_master WHERE bill_to_contractor_id = ?",
            (_CONTRACTOR_ID,),
        ).fetchone()
    assert row[0] == "OMARA s.r.o"       # name always overwritten
    assert row[1] == "operator@existing.com"  # email preserved


# ── Skip cases ────────────────────────────────────────────────────────────────


def test_skip_no_contractor_id_in_xml(proc_db, cm_db):
    _seed(proc_db, xml=_XML_NO_CONTRACTOR)

    with patch(
        "app.services.wfirma_client.fetch_contractor_by_id",
    ) as mock_fetch:
        from app.services.wfirma_customer_sync_processor import sync_customer_from_snapshot
        result = sync_customer_from_snapshot(
            event_id=_EVENT_ID, proc_db=proc_db, cm_db=cm_db, now=_NOW,
        )

    assert result == "CUSTOMER_SYNC_SKIPPED"
    mock_fetch.assert_not_called()

    with sqlite3.connect(str(proc_db)) as conn:
        row = conn.execute(
            "SELECT customer_synced_at FROM wfirma_webhook_processing WHERE event_id = ?",
            (_EVENT_ID,),
        ).fetchone()
    assert row[0] is not None and row[0].startswith("SKIPPED:")


def test_skip_zero_contractor_id(proc_db, cm_db):
    _seed(proc_db, xml=_XML_ZERO_CONTRACTOR)
    with patch("app.services.wfirma_client.fetch_contractor_by_id") as mock_fetch:
        from app.services.wfirma_customer_sync_processor import sync_customer_from_snapshot
        result = sync_customer_from_snapshot(
            event_id=_EVENT_ID, proc_db=proc_db, cm_db=cm_db, now=_NOW,
        )
    assert result == "CUSTOMER_SYNC_SKIPPED"
    mock_fetch.assert_not_called()


# ── Failure cases ─────────────────────────────────────────────────────────────


def test_fail_fetch_not_ok(proc_db, cm_db):
    _seed(proc_db)
    with patch(
        "app.services.wfirma_client.fetch_contractor_by_id",
        return_value=_make_result(ok=False, error="contractor not found"),
    ):
        from app.services.wfirma_customer_sync_processor import sync_customer_from_snapshot
        result = sync_customer_from_snapshot(
            event_id=_EVENT_ID, proc_db=proc_db, cm_db=cm_db, now=_NOW,
        )

    assert result == "CUSTOMER_SYNC_FAILED"
    with sqlite3.connect(str(proc_db)) as conn:
        row = conn.execute(
            "SELECT customer_synced_at, customer_sync_attempts, customer_sync_error "
            "FROM wfirma_webhook_processing WHERE event_id = ?",
            (_EVENT_ID,),
        ).fetchone()
    assert row[0] is None
    assert row[1] == 1
    assert "contractor not found" in (row[2] or "")


def test_fail_upsert_raises(proc_db, cm_db):
    _seed(proc_db)
    with (
        patch(
            "app.services.wfirma_client.fetch_contractor_by_id",
            return_value=_make_result(),
        ),
        patch(
            "app.services.customer_master_db.upsert_identity_only",
            side_effect=RuntimeError("DB locked"),
        ),
    ):
        from app.services.wfirma_customer_sync_processor import sync_customer_from_snapshot
        result = sync_customer_from_snapshot(
            event_id=_EVENT_ID, proc_db=proc_db, cm_db=cm_db, now=_NOW,
        )

    assert result == "CUSTOMER_SYNC_FAILED"
    with sqlite3.connect(str(proc_db)) as conn:
        row = conn.execute(
            "SELECT customer_sync_attempts FROM wfirma_webhook_processing WHERE event_id = ?",
            (_EVENT_ID,),
        ).fetchone()
    assert row[0] == 1


# ── Pending query invariants ──────────────────────────────────────────────────


def test_pending_excludes_already_synced(proc_db):
    from app.services.wfirma_processing_db import (
        get_customer_sync_pending_events,
        set_customer_sync_success,
    )
    _seed(proc_db)
    set_customer_sync_success(proc_db, _EVENT_ID, _NOW)
    pending = get_customer_sync_pending_events(proc_db)
    assert not any(r["event_id"] == _EVENT_ID for r in pending)


def test_pending_excludes_exhausted_attempts(proc_db):
    from app.services.wfirma_processing_db import (
        MAX_CUSTOMER_SYNC_ATTEMPTS,
        get_customer_sync_pending_events,
        increment_customer_sync_attempts,
    )
    _seed(proc_db)
    for _ in range(MAX_CUSTOMER_SYNC_ATTEMPTS):
        increment_customer_sync_attempts(proc_db, _EVENT_ID, "err", _NOW)
    pending = get_customer_sync_pending_events(proc_db)
    assert not any(r["event_id"] == _EVENT_ID for r in pending)


def test_pending_only_terminal_states(proc_db):
    """RECEIVED and SNAPSHOTTED must never appear; COMPLETED / UNMATCHED / ENRICHMENT_FAILED must."""
    from app.services.wfirma_processing_db import (
        ensure_processing_row,
        get_customer_sync_pending_events,
        insert_snapshot,
        set_state,
    )

    cases = [
        ("EVT-RCV",  "RECEIVED"),
        ("EVT-SNAP", "SNAPSHOTTED"),
        ("EVT-COMP", "COMPLETED"),
        ("EVT-UNMA", "UNMATCHED"),
        ("EVT-ENFL", "ENRICHMENT_FAILED"),
        ("EVT-DEAD", "DEAD_LETTER"),
    ]
    for eid, state in cases:
        ensure_processing_row(proc_db, eid, "99", _NOW)
        insert_snapshot(
            proc_db, snapshot_id=str(uuid.uuid4()),
            event_id=eid, object_id="99", fetched_at=_NOW,
            raw_xml=_INVOICE_XML, parsed={}, raw_payload="{}",
        )
        set_state(proc_db, eid, state)

    ids = {r["event_id"] for r in get_customer_sync_pending_events(proc_db)}
    assert "EVT-COMP" in ids
    assert "EVT-UNMA" in ids
    assert "EVT-ENFL" in ids
    assert "EVT-RCV"  not in ids
    assert "EVT-SNAP" not in ids
    assert "EVT-DEAD" not in ids


def test_pending_requires_invoice_snapshot(proc_db):
    """Event with no invoice snapshot must never appear in pending."""
    from app.services.wfirma_processing_db import (
        ensure_processing_row,
        get_customer_sync_pending_events,
        set_state,
    )
    ensure_processing_row(proc_db, "EVT-NO-SNAP", "98", _NOW)
    set_state(proc_db, "EVT-NO-SNAP", "COMPLETED")
    ids = {r["event_id"] for r in get_customer_sync_pending_events(proc_db)}
    assert "EVT-NO-SNAP" not in ids


# ── Phase 3 DB migration ──────────────────────────────────────────────────────


def test_phase3_migration_idempotent(tmp_path):
    from app.services.wfirma_processing_db import init_db
    db = tmp_path / "mig.db"
    init_db(db)
    init_db(db)  # must not raise

    with sqlite3.connect(str(db)) as conn:
        cols = {
            row[1]
            for row in conn.execute(
                "PRAGMA table_info(wfirma_webhook_processing)"
            ).fetchall()
        }
    assert "customer_synced_at" in cols
    assert "customer_sync_error" in cols
    assert "customer_sync_attempts" in cols


def test_customer_snapshots_table_created(tmp_path):
    from app.services.wfirma_processing_db import init_db
    db = tmp_path / "snap.db"
    init_db(db)

    with sqlite3.connect(str(db)) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    assert "wfirma_customer_snapshots" in tables
