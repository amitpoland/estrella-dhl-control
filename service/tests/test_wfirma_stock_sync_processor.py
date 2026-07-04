"""
C-8a — deterministic-plumbing tests for the goods stock-change webhook processor.

Covers only the parts that ARE implemented: the OI-10 inert state, event-type
routing, non-stock skip, the wired scheduler tick as a safe no-op, and the
guarantee that no wFirma read/write fires (payload/parse/stock-update are
BLOCKED BY OI-10 and must not run).
"""
from unittest.mock import MagicMock

from app.services import wfirma_stock_sync_processor as ssp
from app.services import wfirma_webhook_scheduler as sched
from app.services import wfirma_webhook_db


def test_stock_change_event_type_is_blocked_by_oi10():
    # The wire event_type string is undocumented — left None (no guessing).
    assert ssp.STOCK_CHANGE_EVENT_TYPE is None


def test_is_stock_change_event_inert_until_oi10():
    # With the type unset, nothing is recognized as a stock-change event.
    assert ssp.is_stock_change_event("Towary.Zmiana") is False
    assert ssp.is_stock_change_event("Faktury.Dodanie") is False
    assert ssp.is_stock_change_event(None) is False


def test_sync_skips_non_stock_event():
    result = ssp.sync_stock_from_event(
        event_id="e1", event_type="Faktury.Dodanie",
        payload_json="{}", now="2026-07-04T00:00:00Z",
    )
    assert result == "skipped_not_stock_change"


def test_routing_reaches_deferred_branch_once_type_known(monkeypatch):
    # Simulate OI-10 supplying the event-type string: routing must reach the
    # deferred branch (still a no-op — the three blocked steps are not run).
    monkeypatch.setattr(ssp, "STOCK_CHANGE_EVENT_TYPE", "Towary.Zmiana")
    assert ssp.is_stock_change_event("Towary.Zmiana") is True
    result = ssp.sync_stock_from_event(
        event_id="e2", event_type="Towary.Zmiana",
        payload_json='{"id": 1}', now="2026-07-04T00:00:00Z",
    )
    assert result == "blocked_oi10"


def test_sync_never_calls_get_stock(monkeypatch):
    # No wFirma read/write may fire — parse/map/update are BLOCKED BY OI-10.
    import app.services.wfirma_client as wc
    spy = MagicMock(side_effect=AssertionError("get_stock must not be called"))
    monkeypatch.setattr(wc, "get_stock", spy)
    # inert path
    ssp.sync_stock_from_event(event_id="e3", event_type="Towary.Zmiana",
                              payload_json='{"id": 1}', now="now")
    # deferred path
    monkeypatch.setattr(ssp, "STOCK_CHANGE_EVENT_TYPE", "Towary.Zmiana")
    ssp.sync_stock_from_event(event_id="e4", event_type="Towary.Zmiana",
                              payload_json='{"id": 1}', now="now")
    spy.assert_not_called()


def test_stock_sync_tick_none_db_returns(monkeypatch):
    monkeypatch.setattr(sched, "_events_db_path", None)
    # Must not raise.
    sched._run_stock_sync_tick()


def test_stock_sync_tick_safe_noop_over_events(tmp_path, monkeypatch):
    db = tmp_path / "wfirma_webhook_events.db"
    wfirma_webhook_db.init_db(db)
    wfirma_webhook_db.insert_event(db, "ev1", "Faktury.Dodanie", {"id": 1}, "2026-07-04T00:00:00Z")
    wfirma_webhook_db.insert_event(db, "ev2", "Towary.Zmiana", {"id": 2}, "2026-07-04T00:00:00Z")
    monkeypatch.setattr(sched, "_events_db_path", db)
    # Read-only no-op: iterates events, recognizes none (OI-10 inert), no raise.
    sched._run_stock_sync_tick()
    # Events store is untouched (no processing/state writes by this tick).
    import sqlite3
    with sqlite3.connect(str(db)) as conn:
        n = conn.execute("SELECT COUNT(*) FROM wfirma_webhook_events").fetchone()[0]
    assert n == 2
