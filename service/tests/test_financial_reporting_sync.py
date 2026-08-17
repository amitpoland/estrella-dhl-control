"""AP financial-reporting incremental sync (scheduled automation).

Pins the lag class that left five 2026-08-10 Estrella LLP expenses absent
until a manual CLI sync: freshness tracked last sync time but nothing
triggered AP ingestion.

Authority under test
--------------------
``app.services.financial_reporting_sync.run_ap_incremental_tick`` → existing
``sync_ap`` upsert path. Scheduler tick is a thin wrapper.

Safety pins
-----------
  * Idempotent duplicate ticks do not duplicate expense rows.
  * Overlap window catches late-created docs with earlier issue dates.
  * Transient wFirma failures stamp error + retry after backoff (not every 30s).
  * Restart recovery reads watermark from SQLite (not process memory).
  * Normal CFO/payables request paths do not call the sync entry.
"""
from __future__ import annotations

import inspect
import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone

import pytest

from app.services import financial_reporting_sync as aps
from app.services.financial_reporting_db import (
    count_ap,
    get_sync_state,
    reporting_db_path,
    set_sync_state,
)


def _expense_xml(
    expense_id: str,
    *,
    supplier_id: str = "9001",
    date_: str = "2026-08-10",
    number: str = "EJL/26-27/519",
    currency: str = "USD",
    brutto: str = "1399.00",
) -> ET.Element:
    return ET.fromstring(
        f"<expense>"
        f"<id>{expense_id}</id>"
        f"<contractor><id>{supplier_id}</id></contractor>"
        f"<contractor_detail><name>Estrella LLP</name></contractor_detail>"
        f"<fullnumber>{number}</fullnumber>"
        f"<date>{date_}</date>"
        f"<paymentdate>{date_}</paymentdate>"
        f"<currency>{currency}</currency>"
        f"<netto>{brutto}</netto>"
        f"<brutto>{brutto}</brutto>"
        f"<type>normal</type>"
        f"<paymentstate>unpaid</paymentstate>"
        f"</expense>"
    )


@pytest.fixture
def storage(tmp_path, monkeypatch):
    root = tmp_path / "storage"
    root.mkdir()
    from app.core import config as cfg

    monkeypatch.setattr(cfg.settings, "storage_root", str(root), raising=False)
    return root


@pytest.fixture
def db(storage):
    return reporting_db_path(storage)


def test_resolve_window_uses_watermark_minus_overlap():
    df, dt = aps.resolve_incremental_window(
        watermark="2026-08-17",
        today=date(2026, 8, 17),
        overlap_days=14,
    )
    assert df == "2026-08-03"
    assert dt == "2026-08-17"


def test_resolve_window_lookback_when_no_watermark():
    df, dt = aps.resolve_incremental_window(
        watermark=None,
        today=date(2026, 8, 17),
        lookback_days=30,
    )
    assert df == "2026-07-18"
    assert dt == "2026-08-17"


def test_duplicate_tick_is_idempotent(storage, db, monkeypatch):
    nodes = [_expense_xml("205591651")]
    calls = {"n": 0}

    def _fetch(date_from, date_to, **_kw):
        calls["n"] += 1
        return list(nodes)

    monkeypatch.setattr(
        "app.services.wfirma_client.fetch_expenses_for_period", _fetch
    )

    now = datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc)
    s1 = aps.run_ap_incremental_tick(storage, force=True, now=now)
    assert s1 is not None and s1["ok"] is True
    assert s1["upserted"] == 1
    assert count_ap(db) == 1

    # Immediate second forced tick upserts same id — still one row.
    s2 = aps.run_ap_incremental_tick(
        storage,
        force=True,
        now=datetime(2026, 8, 17, 12, 5, tzinfo=timezone.utc),
    )
    assert s2 is not None and s2["ok"] is True
    assert count_ap(db) == 1
    assert calls["n"] == 2


def test_cooldown_skips_second_run(storage, db, monkeypatch):
    monkeypatch.setattr(
        "app.services.wfirma_client.fetch_expenses_for_period",
        lambda *a, **k: [_expense_xml("1")],
    )
    t0 = datetime(2026, 8, 17, 10, 0, tzinfo=timezone.utc)
    assert aps.run_ap_incremental_tick(storage, force=True, now=t0)["ok"]
    # 10 minutes later — still inside 1h cooldown
    skipped = aps.run_ap_incremental_tick(
        storage,
        now=datetime(2026, 8, 17, 10, 10, tzinfo=timezone.utc),
        cooldown_seconds=3600,
    )
    assert skipped is None


def test_missed_window_caught_by_overlap(storage, db, monkeypatch):
    """Expense issue-dated before watermark but inside overlap must upsert."""
    set_sync_state(
        db,
        "ap_expenses",
        last_incremental_at="2026-08-17T01:04:00+00:00",
        last_source_watermark="2026-08-17",
        status="ok",
        row_count=0,
    )
    seen = {}

    def _fetch(date_from, date_to, **_kw):
        seen["from"] = date_from
        seen["to"] = date_to
        # Late-created Aug-10 expense — only present if overlap reached it.
        if date_from <= "2026-08-10" <= date_to:
            return [_expense_xml("205591651", date_="2026-08-10")]
        return []

    monkeypatch.setattr(
        "app.services.wfirma_client.fetch_expenses_for_period", _fetch
    )
    # Force due by aging past cooldown
    summary = aps.run_ap_incremental_tick(
        storage,
        force=True,
        now=datetime(2026, 8, 17, 16, 0, tzinfo=timezone.utc),
        overlap_days=14,
    )
    assert seen["from"] == "2026-08-03"
    assert summary["upserted"] == 1
    assert count_ap(db) == 1


def test_transient_failure_retries_after_backoff_not_immediately(
    storage, db, monkeypatch
):
    monkeypatch.setattr(
        "app.services.wfirma_client.fetch_expenses_for_period",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("wfirma down")),
    )
    t0 = datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc)
    fail = aps.run_ap_incremental_tick(storage, force=True, now=t0)
    assert fail["ok"] is False
    st = get_sync_state(db, "ap_expenses")
    assert st["status"] == "error"
    # Watermark must NOT advance on total failure
    assert not st.get("last_source_watermark")

    # Immediate follow-up without force — still within error_retry window
    assert (
        aps.run_ap_incremental_tick(
            storage,
            now=datetime(2026, 8, 17, 12, 1, tzinfo=timezone.utc),
            error_retry_seconds=300,
        )
        is None
    )

    # After error_retry_seconds — due again
    assert aps.is_ap_sync_due(
        db,
        error_retry_seconds=300,
        now=datetime(2026, 8, 17, 12, 6, tzinfo=timezone.utc),
    )


def test_restart_recovery_reads_watermark_from_db(storage, db, monkeypatch):
    set_sync_state(
        db,
        "ap_expenses",
        last_incremental_at="2026-08-16T12:00:00+00:00",
        last_source_watermark="2026-08-16",
        status="ok",
        row_count=0,
    )
    seen = {}

    def _fetch(date_from, date_to, **_kw):
        seen["from"] = date_from
        return []

    monkeypatch.setattr(
        "app.services.wfirma_client.fetch_expenses_for_period", _fetch
    )
    # Simulate process restart: call with force using only DB state
    aps.run_ap_incremental_tick(
        storage,
        force=True,
        now=datetime(2026, 8, 17, 18, 0, tzinfo=timezone.utc),
        overlap_days=14,
    )
    assert seen["from"] == "2026-08-02"  # 2026-08-16 - 14d


def test_status_exposes_lag_and_watchdog(storage, db):
    set_sync_state(
        db,
        "ap_expenses",
        last_incremental_at="2026-08-16T00:00:00+00:00",
        last_source_watermark="2026-08-16",
        status="ok",
        row_count=10,
    )
    st = aps.get_ap_sync_status(
        storage,
        now=datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc),
    )
    assert st["last_success"] == "2026-08-16T00:00:00+00:00"
    assert st["lag_hours"] == 36.0
    assert st["stale_watchdog"] is True  # > FRESHNESS_MAX_AGE_HOURS (24)


def test_scheduler_tick_wrapper_calls_shared_entry(monkeypatch):
    from app.services import wfirma_webhook_scheduler as sched

    called = {"n": 0}

    def _tick(**_kw):
        called["n"] += 1
        return {"ok": True, "date_from": "a", "date_to": "b", "fetched": 0, "upserted": 0, "errors": []}

    monkeypatch.setattr(
        "app.services.financial_reporting_sync.run_ap_incremental_tick", _tick
    )
    sched._run_ap_reporting_sync_tick()
    assert called["n"] == 1


def test_cfo_payables_route_does_not_import_ap_incremental_sync():
    """Normal CFO request path must not trigger upstream AP projection sync."""
    from app.api import routes_ledgers

    src = inspect.getsource(routes_ledgers)
    assert "run_ap_incremental_tick" not in src
    assert "financial_reporting_sync" not in src
    assert "sync_financial_reporting" not in src


def test_processing_tick_invokes_ap_reporting_before_events_guard():
    src = inspect.getsource(
        __import__(
            "app.services.wfirma_webhook_scheduler", fromlist=["_run_processing_tick"]
        )._run_processing_tick
    )
    assert "_run_ap_reporting_sync_tick()" in src
    # Placement: before the early return on missing events DB
    ap_pos = src.index("_run_ap_reporting_sync_tick()")
    guard_pos = src.index("_events_db_path is None")
    assert ap_pos < guard_pos
