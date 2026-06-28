"""
test_phase_c_converted_state.py — Phase C Fix 1 regression tests.

Guards the 'converted' draft_state against the _ensure_drafts_table() backfill.

C1 — 'converted' is a recognized lifecycle state in DRAFT_LIFECYCLE_STATES
C2 — draft_state='converted' is NOT overwritten to 'posted' by _ensure_drafts_table()
     even when the legacy status column is 'issued'
C3 — draft_state='posted' (non-converted) is still backfilled correctly for 'issued'
C4 — persist_invoice_to_draft() writes draft_state='converted' and the field
     survives a subsequent _ensure_drafts_table() call on the same connection
"""
from __future__ import annotations

import pathlib
import sqlite3
import tempfile

import pytest


# ── C1 ────────────────────────────────────────────────────────────────────────

def test_converted_in_lifecycle_states():
    from app.services.proforma_invoice_link_db import DRAFT_LIFECYCLE_STATES
    assert "converted" in DRAFT_LIFECYCLE_STATES, (
        "'converted' must be in DRAFT_LIFECYCLE_STATES — Phase C Fix 1"
    )


# ── C2 ────────────────────────────────────────────────────────────────────────

def test_converted_state_survives_ensure_drafts_table(tmp_path):
    """
    _ensure_drafts_table() backfill must NOT overwrite draft_state='converted'
    back to 'posted' when status='issued'.
    """
    from app.services.proforma_invoice_link_db import _ensure_drafts_table

    db_path = tmp_path / "test_converted.db"
    conn = sqlite3.connect(str(db_path))

    # Bootstrap the schema (first call creates tables + adds additive columns)
    _ensure_drafts_table(conn)

    # Insert a row that simulates a draft after conversion:
    # status='issued' (legacy) and draft_state='converted' (Phase C).
    conn.execute(
        """
        INSERT INTO proforma_drafts
            (batch_id, client_name, status, currency, created_at, updated_at,
             draft_state, clone_generation)
        VALUES
            ('B001', 'Client A', 'issued', 'EUR', '2026-01-01T00:00:00', '2026-01-01T00:00:00',
             'converted', 0)
        """
    )
    conn.commit()

    # Simulate a subsequent call that would previously have triggered the backfill.
    _ensure_drafts_table(conn)
    conn.commit()

    row = conn.execute(
        "SELECT draft_state FROM proforma_drafts WHERE batch_id='B001'"
    ).fetchone()
    conn.close()

    assert row is not None, "Row must exist"
    assert row[0] == "converted", (
        f"draft_state should remain 'converted' after _ensure_drafts_table(), got '{row[0]}'"
    )


# ── C3 ────────────────────────────────────────────────────────────────────────

def test_posted_backfill_still_works(tmp_path):
    """
    Ensure the Fix 1 guard doesn't break the normal backfill:
    status='issued' + draft_state='draft' → must still backfill to 'posted'.
    """
    from app.services.proforma_invoice_link_db import _ensure_drafts_table

    db_path = tmp_path / "test_backfill.db"
    conn = sqlite3.connect(str(db_path))
    _ensure_drafts_table(conn)

    # Insert a row with draft_state='draft' (not 'converted', not 'posted').
    # After the backfill, status='issued' rows not in 'converted' state
    # should be remapped to 'posted'.
    conn.execute(
        """
        INSERT INTO proforma_drafts
            (batch_id, client_name, status, currency, created_at, updated_at,
             draft_state, clone_generation)
        VALUES
            ('B002', 'Client B', 'issued', 'EUR', '2026-01-01T00:00:00', '2026-01-01T00:00:00',
             'draft', 0)
        """
    )
    conn.commit()

    _ensure_drafts_table(conn)
    conn.commit()

    row = conn.execute(
        "SELECT draft_state FROM proforma_drafts WHERE batch_id='B002'"
    ).fetchone()
    conn.close()

    assert row is not None
    assert row[0] == "posted", (
        f"draft_state='issued' row with draft_state='draft' should be backfilled to 'posted', got '{row[0]}'"
    )


# ── C4 ────────────────────────────────────────────────────────────────────────

def test_persist_invoice_to_draft_converted_survives_subsequent_read(tmp_path):
    """
    End-to-end: persist_invoice_to_draft() writes draft_state='converted'.
    A subsequent get_draft() call (which calls _ensure_drafts_table) must
    return a draft with draft_state='converted', not 'posted'.
    """
    import sqlite3 as _sq
    from app.services.proforma_invoice_link_db import (
        _ensure_drafts_table,
        get_draft,
    )
    from app.services.conversion_persistence import persist_invoice_to_draft

    db_path = tmp_path / "c4_test.db"
    conn = _sq.connect(str(db_path))
    _ensure_drafts_table(conn)

    # Insert a row in 'issued' state (the state just before conversion)
    conn.execute(
        """
        INSERT INTO proforma_drafts
            (batch_id, client_name, status, currency, created_at, updated_at,
             draft_state, wfirma_proforma_id, clone_generation)
        VALUES
            ('B003', 'Client C', 'issued', 'EUR',
             '2026-01-01T00:00:00', '2026-01-01T00:00:00',
             'posted', '999', 0)
        """
    )
    conn.commit()
    row_id = conn.execute(
        "SELECT id FROM proforma_drafts WHERE batch_id='B003'"
    ).fetchone()[0]
    conn.close()

    # Simulate conversion: write draft_state='converted' + invoice identity
    persist_invoice_to_draft(
        db_path=db_path,
        draft_id=row_id,
        wfirma_invoice_id="84110947",
        wfirma_invoice_number="FV 1/2026",
    )

    # get_draft() calls _ensure_drafts_table internally; the backfill guard
    # must not overwrite the 'converted' state.
    result = get_draft(db_path, "B003", "Client C")
    assert result is not None, "Draft must be found after persist"
    assert result.draft_state == "converted", (
        f"get_draft() must return draft_state='converted', got '{result.draft_state}'"
    )
    assert result.wfirma_invoice_id == "84110947"
    assert result.wfirma_invoice_number == "FV 1/2026"
