# service/tests/test_conversion_persistence.py
"""
Tests for post-conversion draft state persistence.
After wFirma returns invoice ID, draft must be updated with invoice identity.
These MUST FAIL before Task 8 fix is applied.
Run: cd service && pytest tests/test_conversion_persistence.py -v
"""
import sqlite3
import tempfile
import pytest
from pathlib import Path


def _create_draft_db(tmp_path: Path) -> Path:
    """Create a minimal proforma_drafts.db with one draft row."""
    db_path = tmp_path / "proforma_drafts.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE proforma_drafts (
            id INTEGER PRIMARY KEY,
            draft_state TEXT NOT NULL DEFAULT 'draft',
            wfirma_invoice_id TEXT,
            wfirma_invoice_number TEXT,
            sale_date TEXT,
            payment_due TEXT,
            payment_method TEXT,
            converted_at TEXT,
            batch_id TEXT
        )
    """)
    conn.execute(
        "INSERT INTO proforma_drafts (id, draft_state, batch_id) VALUES (52, 'draft', 'BATCH_TEST')"
    )
    conn.commit()
    conn.close()
    return db_path


def test_draft_updated_after_conversion(tmp_path):
    """
    Given: wFirma returns invoice ID 'INV_123' and number 'FV WDT 1/2026'
    When: persist_invoice_to_draft() is called
    Then: draft.wfirma_invoice_id == 'INV_123'
    And:  draft.wfirma_invoice_number == 'FV WDT 1/2026'
    And:  draft.draft_state == 'converted'
    """
    from app.services.conversion_persistence import persist_invoice_to_draft

    db_path = _create_draft_db(tmp_path)
    persist_invoice_to_draft(
        db_path=db_path,
        draft_id=52,
        wfirma_invoice_id="INV_123",
        wfirma_invoice_number="FV WDT 1/2026",
        sale_date="2026-06-28",
        payment_due="2026-06-28",
        payment_method="transfer",
        converted_at="2026-06-28T12:00:00",
    )
    conn = sqlite3.connect(str(db_path))
    row = conn.execute(
        "SELECT draft_state, wfirma_invoice_id, wfirma_invoice_number, payment_due "
        "FROM proforma_drafts WHERE id=52"
    ).fetchone()
    conn.close()
    assert row[0] == "converted", f"draft_state should be 'converted', got {row[0]!r}"
    assert row[1] == "INV_123", f"wfirma_invoice_id should be 'INV_123', got {row[1]!r}"
    assert row[2] == "FV WDT 1/2026", f"wfirma_invoice_number wrong: {row[2]!r}"
    assert row[3] == "2026-06-28", f"payment_due wrong: {row[3]!r}"


def test_draft_state_becomes_converted(tmp_path):
    """
    Given: draft starts with draft_state='draft'
    When: persist_invoice_to_draft() is called
    Then: draft_state == 'converted' — NOT 'draft'
    This ensures the UI stops showing the Convert button.
    """
    from app.services.conversion_persistence import persist_invoice_to_draft

    db_path = _create_draft_db(tmp_path)
    # Verify starting state
    conn = sqlite3.connect(str(db_path))
    before = conn.execute(
        "SELECT draft_state FROM proforma_drafts WHERE id=52"
    ).fetchone()
    conn.close()
    assert before[0] == "draft"

    persist_invoice_to_draft(
        db_path=db_path,
        draft_id=52,
        wfirma_invoice_id="INV_999",
        wfirma_invoice_number="FV WDT 9/2026",
        converted_at="2026-06-28T12:00:00",
    )

    conn = sqlite3.connect(str(db_path))
    after = conn.execute(
        "SELECT draft_state FROM proforma_drafts WHERE id=52"
    ).fetchone()
    conn.close()
    assert after[0] == "converted"


def test_convert_readiness_blocks_when_invoice_id_present():
    """
    Given: draft already has wfirma_invoice_id
    When: compute_convert_readiness() is called
    Then: convert_available is False
    This prevents double conversion.
    """
    from app.services.proforma_readiness import compute_convert_readiness

    draft = {
        "id": 52,
        "draft_state": "converted",
        "wfirma_invoice_id": "INV_123",
        "wfirma_invoice_number": "FV WDT 1/2026",
    }
    result = compute_convert_readiness(draft)
    assert result["convert_available"] is False
    assert result.get("wfirma_invoice_id") == "INV_123"
