# service/app/services/conversion_persistence.py
"""
Persists wFirma invoice identity into the proforma draft table
after a successful invoices/add call.

This is the ONLY writer for post-conversion draft fields.
Calling this sets draft_state = 'converted' so the UI
hides the Convert button and shows the invoice identity.
"""
import sqlite3
import datetime
from pathlib import Path
from typing import Optional


def persist_invoice_to_draft(
    db_path: Path,
    draft_id: int,
    wfirma_invoice_id: str,
    wfirma_invoice_number: str,
    sale_date: Optional[str] = None,
    payment_due: Optional[str] = None,
    payment_method: Optional[str] = None,
    converted_at: Optional[str] = None,
) -> None:
    """
    Update the proforma draft row with the wFirma invoice identity.
    Sets draft_state = 'converted'.

    Idempotent: re-calling with the same wfirma_invoice_id is safe.
    """
    _converted_at = converted_at or datetime.datetime.utcnow().isoformat()

    conn = sqlite3.connect(str(db_path))
    try:
        # Add columns idempotently for older schema versions
        for col_def in [
            "wfirma_invoice_id TEXT",
            "wfirma_invoice_number TEXT",
            "payment_due TEXT",
            "payment_method TEXT",
            "sale_date TEXT",
            "converted_at TEXT",
        ]:
            try:
                conn.execute(f"ALTER TABLE proforma_drafts ADD COLUMN {col_def}")
            except Exception:
                pass  # column already exists

        conn.execute(
            """
            UPDATE proforma_drafts SET
                draft_state            = 'converted',
                wfirma_invoice_id      = ?,
                wfirma_invoice_number  = ?,
                payment_due            = COALESCE(?, payment_due),
                payment_method         = COALESCE(?, payment_method),
                sale_date              = COALESCE(?, sale_date),
                converted_at           = ?
            WHERE id = ?
            """,
            (
                wfirma_invoice_id,
                wfirma_invoice_number,
                payment_due,
                payment_method,
                sale_date,
                _converted_at,
                draft_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()
