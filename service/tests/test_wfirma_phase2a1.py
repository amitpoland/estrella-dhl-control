"""
Tests for wFirma webhook Phase 2A.1 — Snapshot foundation.

Coverage:
  - wfirma_processing_db: schema init, processing rows, snapshot rows, stats
  - wfirma_snapshot_processor: XML parsing, object_id extraction, InvoiceSnapshotProcessor
  - wfirma_webhook_scheduler: _run_processing_tick state machine (events DB + proc DB)

Design: all tests use tmp_path (pytest built-in) — no live DB, no live wFirma API.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

from app.services.wfirma_processing_db import (
    MAX_RETRIES,
    ensure_processing_row,
    get_processable_events,
    get_processing_stats,
    get_snapshot_by_event,
    get_snapshots_by_object,
    increment_retry,
    init_db,
    insert_snapshot,
    mark_dead_letter,
    mark_retry_pending,
    set_state,
)
from app.services.wfirma_snapshot_processor import (
    InvoiceSnapshotProcessor,
    _extract_object_id,
    _parse_invoice_xml,
)

_NOW = "2026-06-29T15:00:00+00:00"


# ── Fixtures ───────────────────────────────────────────────────────────────────


@pytest.fixture
def proc_db(tmp_path: Path) -> Path:
    db = tmp_path / "wfirma_processing.db"
    init_db(db)
    return db


@pytest.fixture
def events_db(tmp_path: Path) -> Path:
    """Minimal wfirma_webhook_events DB matching Phase 1 schema."""
    db = tmp_path / "wfirma_webhook_events.db"
    with sqlite3.connect(str(db)) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS wfirma_webhook_events (
                event_id     TEXT PRIMARY KEY,
                event_type   TEXT,
                payload_json TEXT NOT NULL,
                received_at  TEXT NOT NULL
            )
            """
        )
    return db


def _insert_event(events_db: Path, event_id: str, invoice_id: str = "INV-001") -> None:
    payload = json.dumps({"invoice_id": invoice_id, "event_type": "Faktury.Dodanie"})
    with sqlite3.connect(str(events_db)) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO wfirma_webhook_events VALUES (?, ?, ?, ?)",
            (event_id, "Faktury.Dodanie", payload, _NOW),
        )


_SAMPLE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<api>
  <status><code>OK</code></status>
  <invoices>
    <invoice>
      <fullnumber>PROF 42/2026</fullnumber>
      <type>proforma</type>
      <currency>EUR</currency>
      <netto>1000.00</netto>
      <brutto>1230.00</brutto>
      <vat_sum>230.00</vat_sum>
      <date>2026-06-01</date>
      <saledate>2026-06-01</saledate>
      <paymentdate>2026-06-15</paymentdate>
      <paymentmethod>transfer</paymentmethod>
      <status>issued</status>
    </invoice>
  </invoices>
</api>"""


# ── init_db ────────────────────────────────────────────────────────────────────


def test_init_db_creates_processing_table(proc_db: Path) -> None:
    with sqlite3.connect(str(proc_db)) as conn:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='wfirma_webhook_processing'"
        ).fetchone()
    assert row is not None


def test_init_db_creates_snapshot_table(proc_db: Path) -> None:
    with sqlite3.connect(str(proc_db)) as conn:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='wfirma_invoice_snapshots'"
        ).fetchone()
    assert row is not None


def test_init_db_idempotent(tmp_path: Path) -> None:
    """Calling init_db twice must not raise."""
    db = tmp_path / "proc.db"
    init_db(db)
    init_db(db)


# ── ensure_processing_row ──────────────────────────────────────────────────────


def test_ensure_processing_row_inserts_new(proc_db: Path) -> None:
    inserted = ensure_processing_row(proc_db, "evt-001", "INV-001", _NOW)
    assert inserted is True


def test_ensure_processing_row_sets_received_state(proc_db: Path) -> None:
    ensure_processing_row(proc_db, "evt-001", "INV-001", _NOW)
    with sqlite3.connect(str(proc_db)) as conn:
        row = conn.execute(
            "SELECT processing_state FROM wfirma_webhook_processing WHERE event_id='evt-001'"
        ).fetchone()
    assert row[0] == "RECEIVED"


def test_ensure_processing_row_idempotent(proc_db: Path) -> None:
    ensure_processing_row(proc_db, "evt-001", "INV-001", _NOW)
    inserted_again = ensure_processing_row(proc_db, "evt-001", "INV-001", _NOW)
    assert inserted_again is False

    with sqlite3.connect(str(proc_db)) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM wfirma_webhook_processing WHERE event_id='evt-001'"
        ).fetchone()[0]
    assert count == 1


# ── get_processable_events ─────────────────────────────────────────────────────


def test_get_processable_events_returns_received(proc_db: Path) -> None:
    ensure_processing_row(proc_db, "evt-001", "INV-001", _NOW)
    rows = get_processable_events(proc_db)
    assert any(r["event_id"] == "evt-001" for r in rows)


def test_get_processable_events_returns_retry_pending(proc_db: Path) -> None:
    ensure_processing_row(proc_db, "evt-002", "INV-002", _NOW)
    mark_retry_pending(proc_db, "evt-002")
    rows = get_processable_events(proc_db)
    assert any(r["event_id"] == "evt-002" for r in rows)


def test_get_processable_events_skips_snapshotted(proc_db: Path) -> None:
    ensure_processing_row(proc_db, "evt-done", "INV-003", _NOW)
    set_state(proc_db, "evt-done", "SNAPSHOTTED", extra={"snapshotted_at": _NOW})
    rows = get_processable_events(proc_db)
    assert not any(r["event_id"] == "evt-done" for r in rows)


def test_get_processable_events_skips_dead_letter(proc_db: Path) -> None:
    ensure_processing_row(proc_db, "evt-dead", "INV-004", _NOW)
    mark_dead_letter(proc_db, "evt-dead", _NOW)
    rows = get_processable_events(proc_db)
    assert not any(r["event_id"] == "evt-dead" for r in rows)


def test_get_processable_events_skips_max_retries(proc_db: Path) -> None:
    ensure_processing_row(proc_db, "evt-max", "INV-005", _NOW)
    for _ in range(MAX_RETRIES):
        increment_retry(proc_db, "evt-max", "some error", _NOW)
    rows = get_processable_events(proc_db)
    assert not any(r["event_id"] == "evt-max" for r in rows)


# ── set_state / increment_retry / mark_* ──────────────────────────────────────


def test_set_state_updates_processing_state(proc_db: Path) -> None:
    ensure_processing_row(proc_db, "evt-001", "INV-001", _NOW)
    set_state(proc_db, "evt-001", "FETCHING", extra={"fetching_at": _NOW})
    with sqlite3.connect(str(proc_db)) as conn:
        row = conn.execute(
            "SELECT processing_state, fetching_at FROM wfirma_webhook_processing WHERE event_id='evt-001'"
        ).fetchone()
    assert row[0] == "FETCHING"
    assert row[1] == _NOW


def test_increment_retry_sets_failed_state(proc_db: Path) -> None:
    ensure_processing_row(proc_db, "evt-001", "INV-001", _NOW)
    count = increment_retry(proc_db, "evt-001", "timeout", _NOW)
    assert count == 1
    with sqlite3.connect(str(proc_db)) as conn:
        row = conn.execute(
            "SELECT processing_state, retry_count, last_error FROM wfirma_webhook_processing WHERE event_id='evt-001'"
        ).fetchone()
    assert row[0] == "FAILED"
    assert row[1] == 1
    assert "timeout" in row[2]


def test_increment_retry_accumulates(proc_db: Path) -> None:
    ensure_processing_row(proc_db, "evt-001", "INV-001", _NOW)
    increment_retry(proc_db, "evt-001", "err1", _NOW)
    count = increment_retry(proc_db, "evt-001", "err2", _NOW)
    assert count == 2


def test_mark_dead_letter_sets_state(proc_db: Path) -> None:
    ensure_processing_row(proc_db, "evt-001", "INV-001", _NOW)
    mark_dead_letter(proc_db, "evt-001", _NOW)
    with sqlite3.connect(str(proc_db)) as conn:
        row = conn.execute(
            "SELECT processing_state, dead_letter_at FROM wfirma_webhook_processing WHERE event_id='evt-001'"
        ).fetchone()
    assert row[0] == "DEAD_LETTER"
    assert row[1] == _NOW


# ── insert_snapshot ────────────────────────────────────────────────────────────


def test_insert_snapshot_stores_data(proc_db: Path) -> None:
    parsed = {"invoice_number": "PROF 42/2026", "currency": "EUR", "net_amount": "1000.00"}
    inserted = insert_snapshot(
        db_path=proc_db,
        snapshot_id="snap-001",
        event_id="evt-001",
        object_id="INV-001",
        fetched_at=_NOW,
        raw_xml="<xml/>",
        parsed=parsed,
        raw_payload='{"invoice_id":"INV-001"}',
    )
    assert inserted is True

    snap = get_snapshot_by_event(proc_db, "evt-001")
    assert snap is not None
    assert snap["snapshot_id"] == "snap-001"
    assert snap["invoice_number"] == "PROF 42/2026"
    assert snap["currency"] == "EUR"
    assert snap["object_id"] == "INV-001"
    assert snap["version"] == 1


def test_insert_snapshot_idempotent_on_event_id(proc_db: Path) -> None:
    """Two calls with the same event_id: second returns False and stores no extra row."""
    parsed = {"invoice_number": "PROF 42/2026"}
    insert_snapshot(
        db_path=proc_db, snapshot_id="snap-001", event_id="evt-001",
        object_id="INV-001", fetched_at=_NOW, raw_xml="<xml/>",
        parsed=parsed, raw_payload="{}",
    )
    inserted_again = insert_snapshot(
        db_path=proc_db, snapshot_id="snap-002", event_id="evt-001",
        object_id="INV-001", fetched_at=_NOW, raw_xml="<xml/>",
        parsed=parsed, raw_payload="{}",
    )
    assert inserted_again is False

    snaps = get_snapshots_by_object(proc_db, "INV-001")
    assert len(snaps) == 1


def test_snapshot_version_increments_per_object_id(proc_db: Path) -> None:
    """Different event_ids for the same object_id produce version 1 then version 2."""
    parsed = {}
    insert_snapshot(
        db_path=proc_db, snapshot_id="snap-001", event_id="evt-001",
        object_id="INV-001", fetched_at=_NOW, raw_xml="<xml/>",
        parsed=parsed, raw_payload="{}",
    )
    insert_snapshot(
        db_path=proc_db, snapshot_id="snap-002", event_id="evt-002",
        object_id="INV-001", fetched_at=_NOW, raw_xml="<xml2/>",
        parsed=parsed, raw_payload="{}",
    )
    snaps = get_snapshots_by_object(proc_db, "INV-001")
    assert len(snaps) == 2
    assert snaps[0]["version"] == 1
    assert snaps[1]["version"] == 2


# ── get_processing_stats ───────────────────────────────────────────────────────


def test_processing_stats_counts_states(proc_db: Path) -> None:
    ensure_processing_row(proc_db, "evt-001", "INV-001", _NOW)
    ensure_processing_row(proc_db, "evt-002", "INV-002", _NOW)
    mark_dead_letter(proc_db, "evt-002", _NOW)
    insert_snapshot(
        db_path=proc_db, snapshot_id="snap-001", event_id="evt-001",
        object_id="INV-001", fetched_at=_NOW, raw_xml="<xml/>",
        parsed={}, raw_payload="{}",
    )
    stats = get_processing_stats(proc_db)
    assert stats["by_state"].get("RECEIVED", 0) == 1
    assert stats["by_state"].get("DEAD_LETTER", 0) == 1
    assert stats["total_snapshots"] == 1


# ── _extract_object_id ────────────────────────────────────────────────────────


def test_extract_object_id_from_object_id_field() -> None:
    payload = json.dumps({"object_id": "99999", "event_type": "Faktury.Dodanie"})
    assert _extract_object_id(payload) == "99999"


def test_extract_object_id_from_invoice_id_field() -> None:
    payload = json.dumps({"invoice_id": "482638499", "event_type": "Faktury.Dodanie"})
    assert _extract_object_id(payload) == "482638499"


def test_extract_object_id_priority_object_id_over_invoice_id() -> None:
    """object_id is canonical — must win when both fields are present."""
    payload = json.dumps({"object_id": "111", "invoice_id": "222"})
    assert _extract_object_id(payload) == "111"


def test_extract_object_id_from_faktury_id_field() -> None:
    payload = json.dumps({"faktury_id": "12345"})
    assert _extract_object_id(payload) == "12345"


def test_extract_object_id_returns_none_when_missing() -> None:
    payload = json.dumps({"webhook_key": "abc", "event_type": "Faktury.Dodanie"})
    assert _extract_object_id(payload) is None


def test_extract_object_id_handles_invalid_json() -> None:
    assert _extract_object_id("not-json") is None


# ── _parse_invoice_xml ────────────────────────────────────────────────────────


def test_parse_invoice_xml_extracts_all_fields() -> None:
    result = _parse_invoice_xml(_SAMPLE_XML)
    assert result["invoice_number"] == "PROF 42/2026"
    assert result["document_type"] == "proforma"
    assert result["currency"] == "EUR"
    assert result["net_amount"] == "1000.00"
    assert result["gross_amount"] == "1230.00"
    assert result["vat_amount"] == "230.00"
    assert result["issue_date"] == "2026-06-01"
    assert result["sale_date"] == "2026-06-01"
    assert result["payment_due"] == "2026-06-15"
    assert result["payment_method"] == "transfer"
    assert result["status"] == "issued"


def test_parse_invoice_xml_handles_missing_elements() -> None:
    xml = '<?xml version="1.0"?><api><invoices><invoice><fullnumber>X/1</fullnumber></invoice></invoices></api>'
    result = _parse_invoice_xml(xml)
    assert result["invoice_number"] == "X/1"
    assert result["currency"] == ""
    assert result["payment_method"] == ""


def test_parse_invoice_xml_handles_malformed() -> None:
    result = _parse_invoice_xml("not xml at all<<<")
    assert result == {}


# ── InvoiceSnapshotProcessor ──────────────────────────────────────────────────


def test_processor_stores_snapshot_on_success(proc_db: Path) -> None:
    """Processor fetches XML (mocked) and stores a snapshot in proc_db."""
    ensure_processing_row(proc_db, "evt-001", "INV-001", _NOW)

    with patch(
        "app.services.wfirma_client.fetch_invoice_xml",
        return_value=_SAMPLE_XML,
    ):
        proc = InvoiceSnapshotProcessor(proc_db)
        proc.process("evt-001", "INV-001", '{"invoice_id":"INV-001"}', _NOW)

    snap = get_snapshot_by_event(proc_db, "evt-001")
    assert snap is not None
    assert snap["object_id"] == "INV-001"
    assert snap["invoice_number"] == "PROF 42/2026"
    assert snap["raw_xml"] == _SAMPLE_XML
    assert snap["version"] == 1


def test_processor_idempotent_on_duplicate_call(proc_db: Path) -> None:
    """Calling process() twice for the same event_id stores only one snapshot."""
    ensure_processing_row(proc_db, "evt-001", "INV-001", _NOW)

    with patch(
        "app.services.wfirma_client.fetch_invoice_xml",
        return_value=_SAMPLE_XML,
    ):
        proc = InvoiceSnapshotProcessor(proc_db)
        proc.process("evt-001", "INV-001", '{"invoice_id":"INV-001"}', _NOW)
        proc.process("evt-001", "INV-001", '{"invoice_id":"INV-001"}', _NOW)

    snaps = get_snapshots_by_object(proc_db, "INV-001")
    assert len(snaps) == 1


def test_processor_raises_on_fetch_error(proc_db: Path) -> None:
    """fetch_invoice_xml raising RuntimeError must propagate to caller."""
    ensure_processing_row(proc_db, "evt-err", "INV-BAD", _NOW)

    with patch(
        "app.services.wfirma_client.fetch_invoice_xml",
        side_effect=RuntimeError("wFirma 404"),
    ):
        proc = InvoiceSnapshotProcessor(proc_db)
        with pytest.raises(RuntimeError, match="wFirma 404"):
            proc.process("evt-err", "INV-BAD", "{}", _NOW)


def test_processor_does_not_write_business_tables(proc_db: Path) -> None:
    """After processing, only wfirma_processing.db is written — no proforma_drafts etc."""
    ensure_processing_row(proc_db, "evt-001", "INV-001", _NOW)

    with patch(
        "app.services.wfirma_client.fetch_invoice_xml",
        return_value=_SAMPLE_XML,
    ):
        proc = InvoiceSnapshotProcessor(proc_db)
        proc.process("evt-001", "INV-001", "{}", _NOW)

    with sqlite3.connect(str(proc_db)) as conn:
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    # Only the wfirma_processing.db tables — no business tables
    assert tables == {
        "wfirma_webhook_processing",
        "wfirma_invoice_snapshots",
        "wfirma_customer_snapshots",  # Phase 3 — same DB, still no business tables
    }


# ── Scheduler tick (state machine) ────────────────────────────────────────────


def _setup_tick(tmp_path: Path, invoice_id: str = "INV-001") -> tuple:
    """Helper: create events + proc DBs and seed one event."""
    events_db = tmp_path / "wfirma_webhook_events.db"
    proc_db = tmp_path / "wfirma_processing.db"
    with sqlite3.connect(str(events_db)) as conn:
        conn.execute(
            "CREATE TABLE wfirma_webhook_events (event_id TEXT PRIMARY KEY, event_type TEXT, payload_json TEXT NOT NULL, received_at TEXT NOT NULL)"
        )
        payload = json.dumps({"invoice_id": invoice_id})
        conn.execute(
            "INSERT INTO wfirma_webhook_events VALUES ('evt-001', 'Faktury.Dodanie', ?, ?)",
            (payload, _NOW),
        )
    init_db(proc_db)
    return events_db, proc_db


def test_scheduler_tick_creates_processing_row(tmp_path: Path) -> None:
    events_db, proc_db = _setup_tick(tmp_path)

    import app.services.wfirma_webhook_scheduler as sched
    sched._events_db_path = events_db
    sched._proc_db_path = proc_db

    with patch("app.services.wfirma_client.fetch_invoice_xml", return_value=_SAMPLE_XML):
        sched._run_processing_tick()

    rows = get_processable_events(proc_db)
    # Should be empty — event is SNAPSHOTTED, not re-processable by Phase 2A.1
    assert not any(r["event_id"] == "evt-001" for r in rows)

    with sqlite3.connect(str(proc_db)) as conn:
        row = conn.execute(
            "SELECT processing_state FROM wfirma_webhook_processing WHERE event_id='evt-001'"
        ).fetchone()
    assert row is not None
    assert row[0] == "SNAPSHOTTED"


def test_scheduler_tick_marks_snapshotted_on_success(tmp_path: Path) -> None:
    events_db, proc_db = _setup_tick(tmp_path)

    import app.services.wfirma_webhook_scheduler as sched
    sched._events_db_path = events_db
    sched._proc_db_path = proc_db

    with patch("app.services.wfirma_client.fetch_invoice_xml", return_value=_SAMPLE_XML):
        sched._run_processing_tick()

    snap = get_snapshot_by_event(proc_db, "evt-001")
    assert snap is not None
    assert snap["invoice_number"] == "PROF 42/2026"


def test_scheduler_tick_increments_retry_on_fetch_failure(tmp_path: Path) -> None:
    events_db, proc_db = _setup_tick(tmp_path)

    import app.services.wfirma_webhook_scheduler as sched
    sched._events_db_path = events_db
    sched._proc_db_path = proc_db

    with patch(
        "app.services.wfirma_client.fetch_invoice_xml",
        side_effect=RuntimeError("network error"),
    ):
        sched._run_processing_tick()

    with sqlite3.connect(str(proc_db)) as conn:
        row = conn.execute(
            "SELECT processing_state, retry_count FROM wfirma_webhook_processing WHERE event_id='evt-001'"
        ).fetchone()
    assert row[0] == "RETRY_PENDING"
    assert row[1] == 1


def test_scheduler_tick_dead_letters_after_max_retries(tmp_path: Path) -> None:
    events_db, proc_db = _setup_tick(tmp_path)

    import app.services.wfirma_webhook_scheduler as sched
    sched._events_db_path = events_db
    sched._proc_db_path = proc_db

    with patch(
        "app.services.wfirma_client.fetch_invoice_xml",
        side_effect=RuntimeError("persistent error"),
    ):
        for _ in range(MAX_RETRIES):
            sched._run_processing_tick()

    with sqlite3.connect(str(proc_db)) as conn:
        row = conn.execute(
            "SELECT processing_state, retry_count FROM wfirma_webhook_processing WHERE event_id='evt-001'"
        ).fetchone()
    assert row[0] == "DEAD_LETTER"
    assert row[1] == MAX_RETRIES


def test_scheduler_tick_dead_letters_event_with_no_object_id(tmp_path: Path) -> None:
    """Events whose payload has no recognisable invoice-id field → DEAD_LETTER after retries."""
    events_db = tmp_path / "wfirma_webhook_events.db"
    proc_db = tmp_path / "wfirma_processing.db"
    with sqlite3.connect(str(events_db)) as conn:
        conn.execute(
            "CREATE TABLE wfirma_webhook_events (event_id TEXT PRIMARY KEY, event_type TEXT, payload_json TEXT NOT NULL, received_at TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO wfirma_webhook_events VALUES ('evt-noid', 'ping', ?, ?)",
            (json.dumps({"no_id_here": True}), _NOW),
        )
    init_db(proc_db)

    import app.services.wfirma_webhook_scheduler as sched
    sched._events_db_path = events_db
    sched._proc_db_path = proc_db

    for _ in range(MAX_RETRIES):
        sched._run_processing_tick()

    with sqlite3.connect(str(proc_db)) as conn:
        row = conn.execute(
            "SELECT processing_state FROM wfirma_webhook_processing WHERE event_id='evt-noid'"
        ).fetchone()
    assert row[0] == "DEAD_LETTER"
