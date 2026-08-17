"""
WH-001 / WH-005 — webhook scheduler event-domain routing tests.

Proves the main processing tick routes by event_type:
  - invoice events → InvoiceSnapshotProcessor (fetch path)
  - stock events → ROUTED_STOCK, no invoice fetch
  - unknown events → QUARANTINED, no invoice fetch
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from unittest.mock import MagicMock, patch

import pytest

from app.services.wfirma_processing_db import (
    MAX_RETRIES,
    get_snapshot_by_event,
    init_db,
)
from app.services.wfirma_webhook_event_router import (
    DOMAIN_CONTRACTOR,
    DOMAIN_INVOICE,
    DOMAIN_STOCK,
    DOMAIN_UNKNOWN,
    classify_event_domain,
)

_NOW = "2026-06-29T15:00:00+00:00"
_SAMPLE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<api><status><code>OK</code></status><invoices><invoice>
<fullnumber>PROF 42/2026</fullnumber><type>proforma</type>
</invoice></invoices></api>"""


def _create_events_db(path: Path) -> None:
    with sqlite3.connect(str(path)) as conn:
        conn.execute(
            """
            CREATE TABLE wfirma_webhook_events (
                event_id     TEXT PRIMARY KEY,
                event_type   TEXT,
                payload_json TEXT NOT NULL,
                received_at  TEXT NOT NULL
            )
            """
        )


def _insert_event(
    events_db: Path,
    event_id: str,
    event_type: str,
    payload: dict,
) -> None:
    with sqlite3.connect(str(events_db)) as conn:
        conn.execute(
            "INSERT INTO wfirma_webhook_events VALUES (?, ?, ?, ?)",
            (event_id, event_type, json.dumps(payload), _NOW),
        )


@contextmanager
def _scheduler_ctx(events_db: Path, proc_db: Path) -> Iterator:
    import app.services.wfirma_webhook_scheduler as sched

    saved = {
        "_events_db_path": sched._events_db_path,
        "_proc_db_path": sched._proc_db_path,
        "_links_db_path": sched._links_db_path,
        "_cm_db_path": sched._cm_db_path,
        "_payment_db_path": sched._payment_db_path,
        "_contractor_poll_db_path": sched._contractor_poll_db_path,
    }
    sched._events_db_path = events_db
    sched._proc_db_path = proc_db
    sched._links_db_path = None
    sched._cm_db_path = None
    sched._payment_db_path = None
    sched._contractor_poll_db_path = None
    try:
        yield sched
    finally:
        for k, v in saved.items():
            setattr(sched, k, v)


@pytest.mark.parametrize(
    "event_type,expected",
    [
        ("Faktury.Dodanie", DOMAIN_INVOICE),
        ("invoice.created", DOMAIN_INVOICE),
        ("Towary.Zmiana", DOMAIN_STOCK),
        ("Produkty.ZmianaIlosci", DOMAIN_STOCK),
        ("Kontrahenci.Edycja", DOMAIN_CONTRACTOR),
        ("ping", DOMAIN_UNKNOWN),
        (None, DOMAIN_UNKNOWN),
        ("", DOMAIN_UNKNOWN),
    ],
)
def test_classify_event_domain(event_type, expected):
    assert classify_event_domain(event_type) == expected


def test_invoice_event_still_snapshotted(tmp_path: Path) -> None:
    events_db = tmp_path / "wfirma_webhook_events.db"
    proc_db = tmp_path / "wfirma_processing.db"
    _create_events_db(events_db)
    _insert_event(
        events_db,
        "evt-inv",
        "Faktury.Dodanie",
        {"invoice_id": "INV-001"},
    )
    init_db(proc_db)

    fetch_mock = MagicMock(return_value=_SAMPLE_XML)
    with _scheduler_ctx(events_db, proc_db) as sched, patch(
        "app.services.wfirma_client.fetch_invoice_xml", fetch_mock
    ):
        sched._run_processing_tick()

    fetch_mock.assert_called_once()
    snap = get_snapshot_by_event(proc_db, "evt-inv")
    assert snap is not None

    with sqlite3.connect(str(proc_db)) as conn:
        row = conn.execute(
            "SELECT processing_state FROM wfirma_webhook_processing WHERE event_id='evt-inv'"
        ).fetchone()
    assert row[0] == "SNAPSHOTTED"


def test_unknown_event_quarantined_without_invoice_fetch(tmp_path: Path) -> None:
    events_db = tmp_path / "wfirma_webhook_events.db"
    proc_db = tmp_path / "wfirma_processing.db"
    _create_events_db(events_db)
    _insert_event(events_db, "evt-ping", "ping", {"no_id_here": True})
    init_db(proc_db)

    fetch_mock = MagicMock(side_effect=AssertionError("invoice fetch must not run"))
    with _scheduler_ctx(events_db, proc_db) as sched, patch(
        "app.services.wfirma_client.fetch_invoice_xml", fetch_mock
    ):
        sched._run_processing_tick()

    fetch_mock.assert_not_called()
    with sqlite3.connect(str(proc_db)) as conn:
        row = conn.execute(
            "SELECT processing_state, last_error FROM wfirma_webhook_processing "
            "WHERE event_id='evt-ping'"
        ).fetchone()
    assert row[0] == "QUARANTINED"
    assert "quarantined_unknown_event_type" in row[1]
    assert get_snapshot_by_event(proc_db, "evt-ping") is None


def test_stock_event_not_handled_by_invoice_processor(tmp_path: Path) -> None:
    events_db = tmp_path / "wfirma_webhook_events.db"
    proc_db = tmp_path / "wfirma_processing.db"
    _create_events_db(events_db)
    _insert_event(
        events_db,
        "evt-stock",
        "Towary.Zmiana",
        {"good_id": "G-1", "object_id": "G-1"},
    )
    init_db(proc_db)

    fetch_mock = MagicMock(side_effect=AssertionError("invoice fetch must not run"))
    with _scheduler_ctx(events_db, proc_db) as sched, patch(
        "app.services.wfirma_client.fetch_invoice_xml", fetch_mock
    ):
        sched._run_processing_tick()

    fetch_mock.assert_not_called()
    with sqlite3.connect(str(proc_db)) as conn:
        row = conn.execute(
            "SELECT processing_state, last_error FROM wfirma_webhook_processing "
            "WHERE event_id='evt-stock'"
        ).fetchone()
    assert row[0] == "ROUTED_STOCK"
    assert "routed_stock" in row[1]
    assert get_snapshot_by_event(proc_db, "evt-stock") is None


def test_contractor_event_not_handled_by_invoice_processor(tmp_path: Path) -> None:
    events_db = tmp_path / "wfirma_webhook_events.db"
    proc_db = tmp_path / "wfirma_processing.db"
    _create_events_db(events_db)
    _insert_event(
        events_db,
        "evt-cm",
        "Kontrahenci.Dodanie",
        {"contractor_id": "C-99", "object_id": "C-99"},
    )
    init_db(proc_db)

    fetch_mock = MagicMock(side_effect=AssertionError("invoice fetch must not run"))
    with _scheduler_ctx(events_db, proc_db) as sched, patch(
        "app.services.wfirma_client.fetch_invoice_xml", fetch_mock
    ):
        sched._run_processing_tick()

    fetch_mock.assert_not_called()
    with sqlite3.connect(str(proc_db)) as conn:
        row = conn.execute(
            "SELECT processing_state FROM wfirma_webhook_processing "
            "WHERE event_id='evt-cm'"
        ).fetchone()
    assert row[0] == "ROUTED_CONTRACTOR"
    assert get_snapshot_by_event(proc_db, "evt-cm") is None


def test_invoice_without_object_id_still_retries_not_quarantine(tmp_path: Path) -> None:
    """Invoice-domain events with a missing object_id keep the retry/dead-letter path."""
    events_db = tmp_path / "wfirma_webhook_events.db"
    proc_db = tmp_path / "wfirma_processing.db"
    _create_events_db(events_db)
    _insert_event(
        events_db,
        "evt-noid",
        "Faktury.Dodanie",
        {"no_id_here": True},
    )
    init_db(proc_db)

    fetch_mock = MagicMock(side_effect=AssertionError("fetch before object_id resolved"))
    with _scheduler_ctx(events_db, proc_db) as sched, patch(
        "app.services.wfirma_client.fetch_invoice_xml", fetch_mock
    ):
        for _ in range(MAX_RETRIES):
            sched._run_processing_tick()

    fetch_mock.assert_not_called()
    with sqlite3.connect(str(proc_db)) as conn:
        row = conn.execute(
            "SELECT processing_state FROM wfirma_webhook_processing WHERE event_id='evt-noid'"
        ).fetchone()
    assert row[0] == "DEAD_LETTER"


@pytest.mark.parametrize(
    "event_type,domain",
    [
        ("Faktury.Dodanie", DOMAIN_INVOICE),
        ("Faktury.Usunięcie", "INVOICE_DELETE"),
        ("invoice.delete", "INVOICE_DELETE"),
        ("Płatności.Dodanie", "PAYMENT"),
        ("Platnosci.Dodanie", "PAYMENT"),
        ("payment.add", "PAYMENT"),
        ("Towary.Zmiana", DOMAIN_STOCK),
        ("Kontrahenci.Dodanie", DOMAIN_CONTRACTOR),
        ("ping", DOMAIN_UNKNOWN),
    ],
)
def test_classify_event_domain_table(event_type: str, domain: str) -> None:
    from app.services.wfirma_webhook_event_router import (
        DOMAIN_INVOICE_DELETE,
        DOMAIN_PAYMENT,
        classify_event_domain,
    )

    expected = {
        "INVOICE_DELETE": DOMAIN_INVOICE_DELETE,
        "PAYMENT": DOMAIN_PAYMENT,
    }.get(domain, domain)
    assert classify_event_domain(event_type) == expected


def test_payment_event_routed_without_invoice_fetch(tmp_path: Path) -> None:
    events_db = tmp_path / "wfirma_webhook_events.db"
    proc_db = tmp_path / "wfirma_processing.db"
    _create_events_db(events_db)
    _insert_event(
        events_db,
        "evt-pay",
        "Płatności.Dodanie",
        {"object_id": "P-1", "payment_id": "P-1"},
    )
    init_db(proc_db)

    fetch_mock = MagicMock(side_effect=AssertionError("invoice fetch must not run"))
    with _scheduler_ctx(events_db, proc_db) as sched, patch(
        "app.services.wfirma_client.fetch_invoice_xml", fetch_mock
    ):
        sched._run_processing_tick()

    fetch_mock.assert_not_called()
    with sqlite3.connect(str(proc_db)) as conn:
        row = conn.execute(
            "SELECT processing_state, last_error FROM wfirma_webhook_processing "
            "WHERE event_id='evt-pay'"
        ).fetchone()
    assert row[0] == "ROUTED_PAYMENT"
    assert "routed_payment_pending_consumer" in row[1]
    assert get_snapshot_by_event(proc_db, "evt-pay") is None


def test_invoice_delete_routed_without_fetch(tmp_path: Path) -> None:
    events_db = tmp_path / "wfirma_webhook_events.db"
    proc_db = tmp_path / "wfirma_processing.db"
    _create_events_db(events_db)
    _insert_event(
        events_db,
        "evt-del",
        "Faktury.Usunięcie",
        {"object_id": "INV-9", "invoice_id": "INV-9"},
    )
    init_db(proc_db)

    fetch_mock = MagicMock(side_effect=AssertionError("delete must not fetch"))
    with _scheduler_ctx(events_db, proc_db) as sched, patch(
        "app.services.wfirma_client.fetch_invoice_xml", fetch_mock
    ):
        sched._run_processing_tick()

    fetch_mock.assert_not_called()
    with sqlite3.connect(str(proc_db)) as conn:
        row = conn.execute(
            "SELECT processing_state, last_error FROM wfirma_webhook_processing "
            "WHERE event_id='evt-del'"
        ).fetchone()
    assert row[0] == "ROUTED_INVOICE_DELETE"
    assert "tombstone_pending" in row[1]
    assert get_snapshot_by_event(proc_db, "evt-del") is None
