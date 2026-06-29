"""
Phase 2B regression tests — wFirma snapshot enrichment.

Validates:
  1. Happy path — SNAPSHOTTED → MATCHED → ENRICHED → COMPLETED
  2. UNMATCHED — no draft found, state terminal, no proforma write
  3. Only the three approved columns change
  4. Duplicate processing is idempotent (replay-safe)
  5. ENRICHMENT_FAILED when write_postposting_enrichment raises
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path

import pytest

from app.services.wfirma_enrichment_processor import enrich_snapshot
from app.services.wfirma_processing_db import (
    init_db,
    insert_snapshot,
    set_state,
    ensure_processing_row,
)


# ── fixtures ───────────────────────────────────────────────────────────────────

NOW = "2026-06-29T12:00:00+00:00"


def _make_proc_db(tmp_path: Path) -> Path:
    db = tmp_path / "wfirma_processing.db"
    init_db(db)
    return db


def _make_links_db(tmp_path: Path) -> Path:
    """Create proforma_links.db using the production table DDL (via _ensure_drafts_table)."""
    db = tmp_path / "proforma_links.db"
    from app.services.proforma_invoice_link_db import _ensure_drafts_table
    with sqlite3.connect(str(db)) as conn:
        _ensure_drafts_table(conn)
    return db


def _insert_draft(links_db: Path, wfirma_proforma_id: str) -> int:
    with sqlite3.connect(str(links_db)) as conn:
        cur = conn.execute(
            "INSERT INTO proforma_drafts "
            "(batch_id, client_name, status, currency, source_lines_json, "
            " created_at, updated_at, wfirma_proforma_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("BATCH_TEST", "TEST_CLIENT", "draft", "EUR", "[]", NOW, NOW, wfirma_proforma_id),
        )
        return cur.lastrowid


def _get_draft(links_db: Path, draft_id: int) -> dict:
    with sqlite3.connect(str(links_db)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM proforma_drafts WHERE id = ?", (draft_id,)
        ).fetchone()
    return dict(row) if row else {}


def _get_all_draft_fields(links_db: Path, draft_id: int) -> dict:
    return _get_draft(links_db, draft_id)


def _insert_event(proc_db: Path, event_id: str, object_id: str) -> None:
    ensure_processing_row(proc_db, event_id, object_id, NOW)


def _insert_snapshot_row(
    proc_db: Path,
    event_id: str,
    object_id: str,
    issue_date: str = "2026-06-01",
    payment_due: str = "2026-07-01",
    payment_method: str = "transfer",
) -> None:
    insert_snapshot(
        proc_db,
        snapshot_id=str(uuid.uuid4()),
        event_id=event_id,
        object_id=object_id,
        fetched_at=NOW,
        raw_xml="<invoice/>",
        parsed={
            "issue_date":     issue_date,
            "payment_due":    payment_due,
            "payment_method": payment_method,
            "invoice_number": "PROF 1/2026",
        },
        raw_payload="{}",
    )
    set_state(proc_db, event_id, "SNAPSHOTTED", extra={"snapshotted_at": NOW})


def _get_proc_state(proc_db: Path, event_id: str) -> str:
    with sqlite3.connect(str(proc_db)) as conn:
        row = conn.execute(
            "SELECT processing_state FROM wfirma_webhook_processing WHERE event_id = ?",
            (event_id,),
        ).fetchone()
    return row[0] if row else "MISSING"


# ── test 1: happy path ─────────────────────────────────────────────────────────


def test_happy_path_completed(tmp_path):
    proc_db  = _make_proc_db(tmp_path)
    links_db = _make_links_db(tmp_path)

    object_id = "482638627"
    draft_id  = _insert_draft(links_db, object_id)
    event_id  = str(uuid.uuid4())

    _insert_event(proc_db, event_id, object_id)
    _insert_snapshot_row(proc_db, event_id, object_id)

    result = enrich_snapshot(
        event_id=event_id,
        object_id=object_id,
        proc_db=proc_db,
        links_db=links_db,
        now=NOW,
    )

    assert result == "COMPLETED"
    assert _get_proc_state(proc_db, event_id) == "COMPLETED"

    draft = _get_draft(links_db, draft_id)
    assert draft["wfirma_issue_date"]    == "2026-06-01"
    assert draft["wfirma_payment_due"]   == "2026-07-01"
    assert draft["wfirma_payment_method"] == "transfer"


# ── test 2: UNMATCHED — no draft, no write ─────────────────────────────────────


def test_unmatched_when_no_draft(tmp_path):
    proc_db  = _make_proc_db(tmp_path)
    links_db = _make_links_db(tmp_path)

    object_id = "999999999"   # no matching draft
    event_id  = str(uuid.uuid4())

    _insert_event(proc_db, event_id, object_id)
    _insert_snapshot_row(proc_db, event_id, object_id)

    result = enrich_snapshot(
        event_id=event_id,
        object_id=object_id,
        proc_db=proc_db,
        links_db=links_db,
        now=NOW,
    )

    assert result == "UNMATCHED"
    assert _get_proc_state(proc_db, event_id) == "UNMATCHED"

    # confirm no row written to proforma_drafts
    with sqlite3.connect(str(links_db)) as conn:
        count = conn.execute("SELECT COUNT(*) FROM proforma_drafts").fetchone()[0]
    assert count == 0


# ── test 3: only the three approved columns change ─────────────────────────────


def test_only_three_columns_written(tmp_path):
    proc_db  = _make_proc_db(tmp_path)
    links_db = _make_links_db(tmp_path)

    object_id = "482638628"
    draft_id  = _insert_draft(links_db, object_id)

    # record all draft fields before enrichment
    before = _get_all_draft_fields(links_db, draft_id)

    event_id = str(uuid.uuid4())
    _insert_event(proc_db, event_id, object_id)
    _insert_snapshot_row(proc_db, event_id, object_id,
                         issue_date="2026-06-15",
                         payment_due="2026-07-15",
                         payment_method="cash")

    enrich_snapshot(
        event_id=event_id,
        object_id=object_id,
        proc_db=proc_db,
        links_db=links_db,
        now=NOW,
    )

    after = _get_all_draft_fields(links_db, draft_id)

    changed = {k for k in before if before[k] != after[k]}
    # updated_at also changes (set by write_postposting_enrichment)
    allowed_changes = {"wfirma_issue_date", "wfirma_payment_due", "wfirma_payment_method", "updated_at"}
    assert changed <= allowed_changes, f"Unexpected columns changed: {changed - allowed_changes}"

    # the three approved fields must have the new values
    assert after["wfirma_issue_date"]     == "2026-06-15"
    assert after["wfirma_payment_due"]    == "2026-07-15"
    assert after["wfirma_payment_method"] == "cash"

    # all other fields must be unchanged
    for col in before:
        if col not in allowed_changes:
            assert before[col] == after[col], f"Column {col!r} must not change"


# ── test 4: duplicate processing is idempotent ────────────────────────────────


def test_idempotent_second_run(tmp_path):
    """
    Running enrich_snapshot twice on the same event must produce
    identical field values and COMPLETED state.
    """
    proc_db  = _make_proc_db(tmp_path)
    links_db = _make_links_db(tmp_path)

    object_id = "482638629"
    draft_id  = _insert_draft(links_db, object_id)
    event_id  = str(uuid.uuid4())

    _insert_event(proc_db, event_id, object_id)
    _insert_snapshot_row(proc_db, event_id, object_id,
                         issue_date="2026-06-20",
                         payment_due="2026-07-20",
                         payment_method="transfer")

    # first run
    r1 = enrich_snapshot(
        event_id=event_id, object_id=object_id,
        proc_db=proc_db, links_db=links_db, now=NOW,
    )
    draft_after_first = _get_draft(links_db, draft_id)

    # reset processing state to SNAPSHOTTED to simulate replay
    set_state(proc_db, event_id, "SNAPSHOTTED", extra={"snapshotted_at": NOW})

    # second run (replay)
    r2 = enrich_snapshot(
        event_id=event_id, object_id=object_id,
        proc_db=proc_db, links_db=links_db, now=NOW,
    )
    draft_after_second = _get_draft(links_db, draft_id)

    assert r1 == "COMPLETED"
    assert r2 == "COMPLETED"

    # field values must be identical after both runs
    assert draft_after_first["wfirma_issue_date"]     == draft_after_second["wfirma_issue_date"]
    assert draft_after_first["wfirma_payment_due"]    == draft_after_second["wfirma_payment_due"]
    assert draft_after_first["wfirma_payment_method"] == draft_after_second["wfirma_payment_method"]


# ── test 5: ENRICHMENT_FAILED when write raises ────────────────────────────────


def test_enrichment_failed_on_write_error(tmp_path, monkeypatch):
    """
    If write_postposting_enrichment raises, state must be ENRICHMENT_FAILED
    and the draft must not be modified.
    """
    proc_db  = _make_proc_db(tmp_path)
    links_db = _make_links_db(tmp_path)

    object_id = "482638630"
    draft_id  = _insert_draft(links_db, object_id)
    before    = _get_all_draft_fields(links_db, draft_id)

    event_id = str(uuid.uuid4())
    _insert_event(proc_db, event_id, object_id)
    _insert_snapshot_row(proc_db, event_id, object_id)

    # patch the write function to raise
    import app.services.wfirma_enrichment_processor as mod
    monkeypatch.setattr(
        mod,
        "_read_snapshot_fields",
        lambda proc_db, event_id: {"wfirma_issue_date": "x", "wfirma_payment_due": "x", "wfirma_payment_method": "x"},
    )

    def _raise(*a, **kw):
        raise RuntimeError("simulated write failure")

    import app.services.proforma_invoice_link_db as link_mod
    monkeypatch.setattr(link_mod, "write_postposting_enrichment", _raise)

    result = enrich_snapshot(
        event_id=event_id, object_id=object_id,
        proc_db=proc_db, links_db=links_db, now=NOW,
    )

    assert result == "ENRICHMENT_FAILED"
    assert _get_proc_state(proc_db, event_id) == "ENRICHMENT_FAILED"

    after = _get_all_draft_fields(links_db, draft_id)
    for col in before:
        assert before[col] == after[col], f"Column {col!r} must not change on failure"
