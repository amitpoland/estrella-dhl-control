"""
Phase 3B -- wFirma Contractor Master Sync tests.

Coverage:
  - init_contractor_poll_db: creates table
  - is_scan_due: first run / within cooldown / stale / malformed timestamp
  - mark_scan_started / mark_scan_completed: round-trip
  - get_scan_state: diagnostics
  - scan_contractors_into_master: happy path, empty result, page error, skip
    contractors with missing name/country, payment_term int parse
  - _run_contractor_poll_tick: no-op without paths, no-op within cooldown,
    full path writes customer_master and updates poll state
  - Phase 3B does NOT touch wfirma_processing.db or payment_state.db
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List
from unittest.mock import MagicMock, patch

import pytest


# ── helpers ───────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hours_ago(h: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=h)).isoformat()


def _make_contractor(
    wfirma_id: str = "100",
    name: str = "Test Co",
    country: str = "PL",
    nip: str = "1234567890",
    city: str = "Warsaw",
    zip: str = "00-001",
    payment_term: str = "14",
):
    from service.app.services.wfirma_client import WFirmaContractor
    return WFirmaContractor(
        wfirma_id=wfirma_id,
        name=name,
        nip=nip,
        country=country,
        zip=zip,
        city=city,
        email="test@test.com",
        phone="+48111222333",
        mobile="",
        street="ul. Testowa 1",
        account_payments="PL12345678901234567890123456",
        payment_method="transfer",
        payment_term=payment_term,
    )


def _poll_db(tmp_path: Path) -> Path:
    from service.app.services.wfirma_contractor_poll_db import init_contractor_poll_db
    db = tmp_path / "contractor_poll.db"
    init_contractor_poll_db(db)
    return db


def _cm_db(tmp_path: Path) -> Path:
    from service.app.services.customer_master_db import init_db
    db = tmp_path / "customer_master.sqlite"
    init_db(db)
    return db


def _cm_count(db: Path) -> int:
    with sqlite3.connect(str(db)) as conn:
        return conn.execute("SELECT COUNT(*) FROM customer_master").fetchone()[0]


def _cm_row(db: Path, contractor_id: str) -> dict:
    with sqlite3.connect(str(db)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM customer_master WHERE bill_to_contractor_id = ?",
            (contractor_id,),
        ).fetchone()
    return dict(row) if row else {}


# ── init_contractor_poll_db ───────────────────────────────────────────────────

class TestInitContractorPollDb:
    def test_creates_table(self, tmp_path):
        db = _poll_db(tmp_path)
        with sqlite3.connect(str(db)) as conn:
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()}
        assert "contractor_poll_state" in tables

    def test_idempotent(self, tmp_path):
        db = _poll_db(tmp_path)
        _poll_db(tmp_path)  # second call must not raise


# ── is_scan_due ───────────────────────────────────────────────────────────────

class TestIsScanDue:
    def test_due_when_never_scanned(self, tmp_path):
        from service.app.services.wfirma_contractor_poll_db import is_scan_due
        db = _poll_db(tmp_path)
        assert is_scan_due(db, _now()) is True

    def test_not_due_within_cooldown(self, tmp_path):
        from service.app.services.wfirma_contractor_poll_db import (
            is_scan_due, mark_scan_completed
        )
        db = _poll_db(tmp_path)
        mark_scan_completed(db, _now(), 10, 2, 8)
        assert is_scan_due(db, _now(), cooldown_seconds=21600) is False

    def test_due_after_cooldown(self, tmp_path):
        from service.app.services.wfirma_contractor_poll_db import (
            is_scan_due, mark_scan_completed
        )
        db = _poll_db(tmp_path)
        mark_scan_completed(db, _hours_ago(7), 10, 2, 8)
        assert is_scan_due(db, _now(), cooldown_seconds=21600) is True

    def test_due_when_timestamp_malformed(self, tmp_path):
        from service.app.services.wfirma_contractor_poll_db import is_scan_due
        db = _poll_db(tmp_path)
        with sqlite3.connect(str(db)) as conn:
            conn.execute(
                "INSERT INTO contractor_poll_state "
                "(id, last_scan_completed_at) VALUES (1, 'bad-date')"
            )
            conn.commit()
        assert is_scan_due(db, _now()) is True


# ── mark_scan_started / mark_scan_completed ───────────────────────────────────

class TestScanStateRoundtrip:
    def test_started_then_completed(self, tmp_path):
        from service.app.services.wfirma_contractor_poll_db import (
            mark_scan_started, mark_scan_completed, get_scan_state
        )
        db = _poll_db(tmp_path)
        t1 = _hours_ago(1)
        mark_scan_started(db, t1)
        state = get_scan_state(db)
        assert state["last_scan_started_at"] == t1
        assert state["last_scan_completed_at"] is None

        t2 = _now()
        mark_scan_completed(db, t2, contractor_count=20, new_count=5, updated_count=15)
        state = get_scan_state(db)
        assert state["last_scan_completed_at"] == t2
        assert state["last_scan_contractor_count"] == 20
        assert state["last_scan_new_count"] == 5
        assert state["last_scan_updated_count"] == 15
        assert state["last_scan_error"] is None

    def test_completed_with_error(self, tmp_path):
        from service.app.services.wfirma_contractor_poll_db import (
            mark_scan_completed, get_scan_state
        )
        db = _poll_db(tmp_path)
        mark_scan_completed(db, _now(), 5, 0, 0, error="wFirma down")
        assert get_scan_state(db)["last_scan_error"] == "wFirma down"

    def test_second_start_clears_error(self, tmp_path):
        from service.app.services.wfirma_contractor_poll_db import (
            mark_scan_completed, mark_scan_started, get_scan_state
        )
        db = _poll_db(tmp_path)
        mark_scan_completed(db, _hours_ago(7), 5, 0, 0, error="wFirma down")
        mark_scan_started(db, _now())
        assert get_scan_state(db)["last_scan_error"] is None


# ── scan_contractors_into_master ──────────────────────────────────────────────

class TestScanContractorsIntoMaster:
    def test_happy_path_inserts_new(self, tmp_path):
        cm = _cm_db(tmp_path)
        contractors = [_make_contractor("C1", "Alpha Ltd", "DE"),
                       _make_contractor("C2", "Beta GmbH", "PL")]
        with patch(
            "service.app.services.wfirma_client.list_contractors_page",
            side_effect=[contractors, []],
        ):
            from service.app.services.wfirma_contractor_poll_processor import scan_contractors_into_master
            total, new, updated, err = scan_contractors_into_master(cm, _now())
        assert total == 2
        assert new == 2
        assert updated == 0
        assert err is None
        assert _cm_count(cm) == 2

    def test_idempotent_second_scan(self, tmp_path):
        cm = _cm_db(tmp_path)
        contractors = [_make_contractor("C1", "Alpha Ltd", "DE")]
        with patch(
            "service.app.services.wfirma_client.list_contractors_page",
            side_effect=[contractors, [], contractors, []],
        ):
            from service.app.services.wfirma_contractor_poll_processor import scan_contractors_into_master
            scan_contractors_into_master(cm, _now())
            total2, new2, updated2, err2 = scan_contractors_into_master(cm, _now())
        assert new2 == 0
        assert updated2 == 1
        assert err2 is None
        assert _cm_count(cm) == 1

    def test_skip_contractor_without_country(self, tmp_path):
        cm = _cm_db(tmp_path)
        bad = _make_contractor("C1", "No Country Corp", country="")
        good = _make_contractor("C2", "Good Corp", country="PL")
        with patch(
            "service.app.services.wfirma_client.list_contractors_page",
            side_effect=[[bad, good], []],
        ):
            from service.app.services.wfirma_contractor_poll_processor import scan_contractors_into_master
            total, new, updated, err = scan_contractors_into_master(cm, _now())
        assert total == 2
        assert new == 1    # only Good Corp
        assert _cm_count(cm) == 1

    def test_skip_contractor_with_invalid_country(self, tmp_path):
        cm = _cm_db(tmp_path)
        bad = _make_contractor("C1", "Bad Country", country="POLAND")
        with patch(
            "service.app.services.wfirma_client.list_contractors_page",
            side_effect=[[bad], []],
        ):
            from service.app.services.wfirma_contractor_poll_processor import scan_contractors_into_master
            total, new, updated, err = scan_contractors_into_master(cm, _now())
        assert new == 0
        assert _cm_count(cm) == 0

    def test_empty_page_stops_scan(self, tmp_path):
        cm = _cm_db(tmp_path)
        with patch(
            "service.app.services.wfirma_client.list_contractors_page",
            return_value=[],
        ):
            from service.app.services.wfirma_contractor_poll_processor import scan_contractors_into_master
            total, new, updated, err = scan_contractors_into_master(cm, _now())
        assert total == 0
        assert new == 0
        assert err is None

    def test_page_error_returns_partial_with_error(self, tmp_path):
        cm = _cm_db(tmp_path)
        page1 = [_make_contractor("C1", "Alpha", "PL")]
        with patch(
            "service.app.services.wfirma_client.list_contractors_page",
            side_effect=[page1, RuntimeError("wFirma 500")],
        ):
            from service.app.services.wfirma_contractor_poll_processor import scan_contractors_into_master
            total, new, updated, err = scan_contractors_into_master(cm, _now())
        assert total == 1   # page 1 was processed
        assert new == 1
        assert err is not None
        assert "500" in err

    def test_payment_term_parsed_as_int(self, tmp_path):
        cm = _cm_db(tmp_path)
        c = _make_contractor("C1", "NetTerms Co", "SK", payment_term="30")
        with patch(
            "service.app.services.wfirma_client.list_contractors_page",
            side_effect=[[c], []],
        ):
            from service.app.services.wfirma_contractor_poll_processor import scan_contractors_into_master
            scan_contractors_into_master(cm, _now())
        row = _cm_row(cm, "C1")
        assert row.get("payment_terms_days") == 30

    def test_invalid_payment_term_silently_skipped(self, tmp_path):
        cm = _cm_db(tmp_path)
        c = _make_contractor("C1", "BadTerm Co", "SK", payment_term="n/a")
        with patch(
            "service.app.services.wfirma_client.list_contractors_page",
            side_effect=[[c], []],
        ):
            from service.app.services.wfirma_contractor_poll_processor import scan_contractors_into_master
            total, new, updated, err = scan_contractors_into_master(cm, _now())
        assert new == 1   # contractor still inserted, just without payment_terms_days
        assert err is None

    def test_sync_source_is_wfirma_poll(self, tmp_path):
        cm = _cm_db(tmp_path)
        c = _make_contractor("C1", "Source Check Co", "PL")
        with patch(
            "service.app.services.wfirma_client.list_contractors_page",
            side_effect=[[c], []],
        ):
            from service.app.services.wfirma_contractor_poll_processor import scan_contractors_into_master
            scan_contractors_into_master(cm, _now())
        row = _cm_row(cm, "C1")
        assert row.get("wfirma_sync_source") == "wfirma_poll"

    def test_does_not_touch_wfirma_processing_db(self, tmp_path):
        proc_db = tmp_path / "wfirma_processing.db"
        cm = _cm_db(tmp_path)
        with patch(
            "service.app.services.wfirma_client.list_contractors_page",
            return_value=[],
        ):
            from service.app.services.wfirma_contractor_poll_processor import scan_contractors_into_master
            scan_contractors_into_master(cm, _now())
        assert not proc_db.exists()


# ── _run_contractor_poll_tick ─────────────────────────────────────────────────

class TestRunContractorPollTick:
    def test_noop_when_poll_db_is_none(self):
        import service.app.services.wfirma_webhook_scheduler as s
        s._contractor_poll_db_path = None
        s._cm_db_path = Path("/fake/cm.sqlite")
        s._run_contractor_poll_tick()   # must not raise

    def test_noop_when_cm_db_is_none(self):
        import service.app.services.wfirma_webhook_scheduler as s
        s._contractor_poll_db_path = Path("/fake/poll.db")
        s._cm_db_path = None
        s._run_contractor_poll_tick()   # must not raise

    def test_respects_cooldown(self, tmp_path):
        poll_db = _poll_db(tmp_path)
        cm = _cm_db(tmp_path)
        from service.app.services.wfirma_contractor_poll_db import mark_scan_completed
        # Mark scan as completed just now
        mark_scan_completed(poll_db, _now(), 5, 1, 4)

        import service.app.services.wfirma_webhook_scheduler as s
        s._contractor_poll_db_path = poll_db
        s._cm_db_path = cm

        with patch(
            "service.app.services.wfirma_client.list_contractors_page",
        ) as mock_list:
            s._run_contractor_poll_tick()
            mock_list.assert_not_called()   # within 6-hour cooldown

    def test_runs_scan_when_due(self, tmp_path):
        poll_db = _poll_db(tmp_path)
        cm = _cm_db(tmp_path)

        import service.app.services.wfirma_webhook_scheduler as s
        s._contractor_poll_db_path = poll_db
        s._cm_db_path = cm

        contractors = [_make_contractor("C1", "Fresh Co", "DE")]
        with patch(
            "service.app.services.wfirma_client.list_contractors_page",
            side_effect=[contractors, []],
        ):
            s._run_contractor_poll_tick()

        # customer_master populated
        assert _cm_count(cm) == 1
        # poll state updated
        from service.app.services.wfirma_contractor_poll_db import get_scan_state
        state = get_scan_state(poll_db)
        assert state["last_scan_completed_at"] is not None
        assert state["last_scan_new_count"] == 1

    def test_scan_state_records_error(self, tmp_path):
        poll_db = _poll_db(tmp_path)
        cm = _cm_db(tmp_path)

        import service.app.services.wfirma_webhook_scheduler as s
        s._contractor_poll_db_path = poll_db
        s._cm_db_path = cm

        with patch(
            "service.app.services.wfirma_client.list_contractors_page",
            side_effect=RuntimeError("API down"),
        ):
            s._run_contractor_poll_tick()

        from service.app.services.wfirma_contractor_poll_db import get_scan_state
        state = get_scan_state(poll_db)
        assert state["last_scan_error"] is not None
        assert "API down" in state["last_scan_error"]
