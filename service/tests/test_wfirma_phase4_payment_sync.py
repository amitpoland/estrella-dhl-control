"""
Phase 4A — Payment Sync tests.

Coverage:
  - init_payment_db: creates both tables
  - insert_payment_snapshot: idempotency (INSERT OR IGNORE)
  - get_contractors_due_for_sync: first-sync / cooldown / stale
  - mark_contractor_synced: accumulates count
  - get_snapshot_count / get_sync_state diagnostics
  - sync_payments_for_contractor: happy path, fetch error, missing id nodes
  - _run_payment_sync_tick: no-op without db paths, no contractors, respects cooldown
  - Phase 4A does NOT touch wfirma_processing.db or customer_master.sqlite
"""
from __future__ import annotations

import json
import sqlite3
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List
from unittest.mock import MagicMock, patch

import pytest


# ── helpers ───────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hours_ago(h: int) -> str:
    dt = datetime.now(timezone.utc) - timedelta(hours=h)
    return dt.isoformat()


def _make_payment_node(payment_id: str, contractor_id: str, invoice_id: str = "99") -> ET.Element:
    xml = (
        f"<payment>"
        f"  <id>{payment_id}</id>"
        f"  <date>2026-01-15</date>"
        f"  <value>1000.00</value>"
        f"  <value_pln>4200.00</value_pln>"
        f"  <currency_label>EUR</currency_label>"
        f"  <payment_method>transfer</payment_method>"
        f"  <payment_type>normal</payment_type>"
        f"  <type>income</type>"
        f"  <notes>test</notes>"
        f"  <contractor><id>{contractor_id}</id></contractor>"
        f"  <invoice><id>{invoice_id}</id></invoice>"
        f"</payment>"
    )
    return ET.fromstring(xml)


# ── wfirma_payment_db ─────────────────────────────────────────────────────────

class TestInitPaymentDb:
    def test_creates_both_tables(self, tmp_path):
        from service.app.services.wfirma_payment_db import init_payment_db
        db = tmp_path / "payment_state.db"
        init_payment_db(db)
        with sqlite3.connect(str(db)) as conn:
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()}
        assert "wfirma_payment_snapshots" in tables
        assert "payment_sync_state" in tables

    def test_idempotent_init(self, tmp_path):
        from service.app.services.wfirma_payment_db import init_payment_db
        db = tmp_path / "payment_state.db"
        init_payment_db(db)
        init_payment_db(db)  # second call must not raise


class TestInsertPaymentSnapshot:
    def _db(self, tmp_path):
        from service.app.services.wfirma_payment_db import init_payment_db
        db = tmp_path / "payment_state.db"
        init_payment_db(db)
        return db

    def _insert(self, db, payment_id="P001", contractor_id="C001"):
        from service.app.services.wfirma_payment_db import insert_payment_snapshot
        return insert_payment_snapshot(
            db,
            payment_id=payment_id,
            contractor_id=contractor_id,
            invoice_id="INV1",
            payment_date="2026-01-15",
            value="1000.00",
            value_pln="4200.00",
            currency_label="EUR",
            payment_method="transfer",
            payment_type="normal",
            type_="income",
            notes=None,
            fetched_at=_now(),
            raw_json=json.dumps({"payment_id": payment_id}),
        )

    def test_new_row_returns_true(self, tmp_path):
        db = self._db(tmp_path)
        assert self._insert(db) is True

    def test_duplicate_returns_false(self, tmp_path):
        db = self._db(tmp_path)
        self._insert(db, "P001")
        assert self._insert(db, "P001") is False

    def test_different_ids_both_inserted(self, tmp_path):
        db = self._db(tmp_path)
        assert self._insert(db, "P001") is True
        assert self._insert(db, "P002") is True
        from service.app.services.wfirma_payment_db import get_snapshot_count
        assert get_snapshot_count(db) == 2

    def test_idempotent_no_update_on_dup(self, tmp_path):
        db = self._db(tmp_path)
        self._insert(db, "P001")
        from service.app.services.wfirma_payment_db import insert_payment_snapshot, get_snapshot_count
        insert_payment_snapshot(
            db,
            payment_id="P001",
            contractor_id="C999",   # different contractor — still ignored
            invoice_id=None,
            payment_date=None,
            value=None,
            value_pln=None,
            currency_label=None,
            payment_method=None,
            payment_type=None,
            type_=None,
            notes=None,
            fetched_at=_now(),
            raw_json="{}",
        )
        with sqlite3.connect(str(db)) as conn:
            row = conn.execute(
                "SELECT contractor_id FROM wfirma_payment_snapshots WHERE payment_id='P001'"
            ).fetchone()
        assert row[0] == "C001"  # original preserved


class TestGetContractorsDueForSync:
    def _db(self, tmp_path):
        from service.app.services.wfirma_payment_db import init_payment_db
        db = tmp_path / "payment_state.db"
        init_payment_db(db)
        return db

    def test_all_due_when_no_state(self, tmp_path):
        db = self._db(tmp_path)
        from service.app.services.wfirma_payment_db import get_contractors_due_for_sync
        due = get_contractors_due_for_sync(db, ["C001", "C002"], _now())
        assert set(due) == {"C001", "C002"}

    def test_empty_input_returns_empty(self, tmp_path):
        db = self._db(tmp_path)
        from service.app.services.wfirma_payment_db import get_contractors_due_for_sync
        assert get_contractors_due_for_sync(db, [], _now()) == []

    def test_within_cooldown_not_due(self, tmp_path):
        db = self._db(tmp_path)
        from service.app.services.wfirma_payment_db import (
            get_contractors_due_for_sync, mark_contractor_synced
        )
        mark_contractor_synced(db, "C001", _now(), 5)
        due = get_contractors_due_for_sync(db, ["C001"], _now(), cooldown_seconds=3600)
        assert due == []

    def test_past_cooldown_is_due(self, tmp_path):
        db = self._db(tmp_path)
        from service.app.services.wfirma_payment_db import (
            get_contractors_due_for_sync, mark_contractor_synced
        )
        mark_contractor_synced(db, "C001", _hours_ago(2), 5)
        due = get_contractors_due_for_sync(db, ["C001"], _now(), cooldown_seconds=3600)
        assert "C001" in due

    def test_malformed_timestamp_treated_as_due(self, tmp_path):
        db = self._db(tmp_path)
        with sqlite3.connect(str(db)) as conn:
            conn.execute(
                "INSERT INTO payment_sync_state (contractor_id, last_synced_at, snapshot_count) "
                "VALUES ('C001', 'not-a-date', 0)"
            )
            conn.commit()
        from service.app.services.wfirma_payment_db import get_contractors_due_for_sync
        due = get_contractors_due_for_sync(db, ["C001"], _now())
        assert "C001" in due


class TestMarkContractorSynced:
    def _db(self, tmp_path):
        from service.app.services.wfirma_payment_db import init_payment_db
        db = tmp_path / "payment_state.db"
        init_payment_db(db)
        return db

    def test_first_insert(self, tmp_path):
        db = self._db(tmp_path)
        from service.app.services.wfirma_payment_db import mark_contractor_synced, get_sync_state
        mark_contractor_synced(db, "C001", _now(), 10)
        state = get_sync_state(db)
        assert len(state) == 1
        assert state[0]["contractor_id"] == "C001"
        assert state[0]["snapshot_count"] == 10

    def test_accumulates_count(self, tmp_path):
        db = self._db(tmp_path)
        from service.app.services.wfirma_payment_db import mark_contractor_synced, get_sync_state
        mark_contractor_synced(db, "C001", _now(), 10)
        mark_contractor_synced(db, "C001", _now(), 3)
        state = get_sync_state(db)
        assert state[0]["snapshot_count"] == 13

    def test_updates_last_synced_at(self, tmp_path):
        db = self._db(tmp_path)
        from service.app.services.wfirma_payment_db import mark_contractor_synced, get_sync_state
        t1 = _hours_ago(2)
        t2 = _now()
        mark_contractor_synced(db, "C001", t1, 0)
        mark_contractor_synced(db, "C001", t2, 0)
        state = get_sync_state(db)
        assert state[0]["last_synced_at"] == t2


# ── wfirma_payment_sync_processor ─────────────────────────────────────────────

class TestSyncPaymentsForContractor:
    def _db(self, tmp_path):
        from service.app.services.wfirma_payment_db import init_payment_db
        db = tmp_path / "payment_state.db"
        init_payment_db(db)
        return db

    def test_happy_path_inserts_new(self, tmp_path):
        db = self._db(tmp_path)
        nodes = [
            _make_payment_node("P1", "173845539"),
            _make_payment_node("P2", "173845539"),
        ]
        with patch(
            "service.app.services.wfirma_client.fetch_payments_for_contractor",
            return_value=nodes,
        ):
            from service.app.services.wfirma_payment_sync_processor import sync_payments_for_contractor
            new, existing, error = sync_payments_for_contractor(
                contractor_id="173845539",
                payment_db=db,
                now=_now(),
            )
        assert new == 2
        assert existing == 0
        assert error is None

    def test_idempotent_second_run(self, tmp_path):
        db = self._db(tmp_path)
        nodes = [_make_payment_node("P1", "C001")]
        with patch(
            "service.app.services.wfirma_client.fetch_payments_for_contractor",
            return_value=nodes,
        ):
            from service.app.services.wfirma_payment_sync_processor import sync_payments_for_contractor
            sync_payments_for_contractor(contractor_id="C001", payment_db=db, now=_now())
            new2, existing2, err2 = sync_payments_for_contractor(
                contractor_id="C001", payment_db=db, now=_now()
            )
        assert new2 == 0
        assert existing2 == 1
        assert err2 is None

    def test_fetch_error_returns_zero_counts(self, tmp_path):
        db = self._db(tmp_path)
        with patch(
            "service.app.services.wfirma_client.fetch_payments_for_contractor",
            side_effect=RuntimeError("wFirma down"),
        ):
            from service.app.services.wfirma_payment_sync_processor import sync_payments_for_contractor
            new, existing, error = sync_payments_for_contractor(
                contractor_id="C001", payment_db=db, now=_now()
            )
        assert new == 0
        assert existing == 0
        assert error is not None
        assert "wFirma down" in error

    def test_node_without_id_skipped(self, tmp_path):
        db = self._db(tmp_path)
        bad_node = ET.fromstring("<payment><date>2026-01-01</date></payment>")
        with patch(
            "service.app.services.wfirma_client.fetch_payments_for_contractor",
            return_value=[bad_node],
        ):
            from service.app.services.wfirma_payment_sync_processor import sync_payments_for_contractor
            new, existing, error = sync_payments_for_contractor(
                contractor_id="C001", payment_db=db, now=_now()
            )
        assert new == 0
        assert existing == 0
        assert error is None
        from service.app.services.wfirma_payment_db import get_snapshot_count
        assert get_snapshot_count(db) == 0

    def test_invoice_id_extracted(self, tmp_path):
        db = self._db(tmp_path)
        node = _make_payment_node("P1", "C001", invoice_id="42")
        with patch(
            "service.app.services.wfirma_client.fetch_payments_for_contractor",
            return_value=[node],
        ):
            from service.app.services.wfirma_payment_sync_processor import sync_payments_for_contractor
            sync_payments_for_contractor(contractor_id="C001", payment_db=db, now=_now())
        with sqlite3.connect(str(db)) as conn:
            row = conn.execute(
                "SELECT invoice_id FROM wfirma_payment_snapshots WHERE payment_id='P1'"
            ).fetchone()
        assert row[0] == "42"

    def test_does_not_touch_wfirma_processing_db(self, tmp_path):
        proc_db = tmp_path / "wfirma_processing.db"
        pay_db = tmp_path / "payment_state.db"
        from service.app.services.wfirma_payment_db import init_payment_db
        init_payment_db(pay_db)

        with patch(
            "service.app.services.wfirma_client.fetch_payments_for_contractor",
            return_value=[_make_payment_node("P1", "C001")],
        ):
            from service.app.services.wfirma_payment_sync_processor import sync_payments_for_contractor
            sync_payments_for_contractor(contractor_id="C001", payment_db=pay_db, now=_now())

        # wfirma_processing.db must not have been created
        assert not proc_db.exists()


# ── scheduler tick integration ─────────────────────────────────────────────────

class TestRunPaymentSyncTick:
    def _reset_scheduler_globals(self):
        import service.app.services.wfirma_webhook_scheduler as s
        s._payment_db_path = None
        s._cm_db_path = None

    def test_noop_when_payment_db_path_is_none(self):
        import service.app.services.wfirma_webhook_scheduler as s
        s._payment_db_path = None
        s._cm_db_path = Path("/fake/cm.sqlite")
        s._run_payment_sync_tick()  # must not raise

    def test_noop_when_cm_db_path_is_none(self):
        import service.app.services.wfirma_webhook_scheduler as s
        s._payment_db_path = Path("/fake/pay.db")
        s._cm_db_path = None
        s._run_payment_sync_tick()  # must not raise

    def test_noop_when_customer_master_has_no_contractors(self, tmp_path):
        from service.app.services.wfirma_payment_db import init_payment_db
        pay_db = tmp_path / "payment_state.db"
        init_payment_db(pay_db)
        cm_db = tmp_path / "customer_master.sqlite"
        with sqlite3.connect(str(cm_db)) as conn:
            conn.execute(
                "CREATE TABLE customer_master "
                "(bill_to_contractor_id TEXT)"
            )
            conn.commit()

        import service.app.services.wfirma_webhook_scheduler as s
        s._payment_db_path = pay_db
        s._cm_db_path = cm_db
        s._run_payment_sync_tick()  # must not raise; 0 contractors

        from service.app.services.wfirma_payment_db import get_snapshot_count
        assert get_snapshot_count(pay_db) == 0

    def test_syncs_known_contractors(self, tmp_path):
        from service.app.services.wfirma_payment_db import init_payment_db
        pay_db = tmp_path / "payment_state.db"
        init_payment_db(pay_db)
        cm_db = tmp_path / "customer_master.sqlite"
        with sqlite3.connect(str(cm_db)) as conn:
            conn.execute(
                "CREATE TABLE customer_master (bill_to_contractor_id TEXT)"
            )
            conn.execute(
                "INSERT INTO customer_master VALUES ('C001')"
            )
            conn.commit()

        nodes = [_make_payment_node("P1", "C001")]
        with patch(
            "service.app.services.wfirma_client.fetch_payments_for_contractor",
            return_value=nodes,
        ):
            import service.app.services.wfirma_webhook_scheduler as s
            s._payment_db_path = pay_db
            s._cm_db_path = cm_db
            s._run_payment_sync_tick()

        from service.app.services.wfirma_payment_db import get_snapshot_count
        assert get_snapshot_count(pay_db) == 1

    def test_respects_cooldown(self, tmp_path):
        from service.app.services.wfirma_payment_db import (
            init_payment_db, mark_contractor_synced, get_snapshot_count
        )
        pay_db = tmp_path / "payment_state.db"
        init_payment_db(pay_db)
        # Mark C001 as recently synced
        mark_contractor_synced(pay_db, "C001", _now(), 0)

        cm_db = tmp_path / "customer_master.sqlite"
        with sqlite3.connect(str(cm_db)) as conn:
            conn.execute(
                "CREATE TABLE customer_master (bill_to_contractor_id TEXT)"
            )
            conn.execute("INSERT INTO customer_master VALUES ('C001')")
            conn.commit()

        with patch(
            "service.app.services.wfirma_client.fetch_payments_for_contractor",
        ) as mock_fetch:
            import service.app.services.wfirma_webhook_scheduler as s
            s._payment_db_path = pay_db
            s._cm_db_path = cm_db
            s._run_payment_sync_tick()
            mock_fetch.assert_not_called()  # within cooldown

        assert get_snapshot_count(pay_db) == 0
