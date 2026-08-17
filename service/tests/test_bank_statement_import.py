"""Tests for bank statement import adapter (preview → confirm)."""
from __future__ import annotations

from pathlib import Path

from app.services.bank_statement_import import (
    confirm_import_batch,
    parse_csv_balances,
    save_preview_batch,
)
from app.services.treasury_db import latest_balances_as_of


def test_csv_preview_and_confirm(tmp_path: Path):
    db = tmp_path / "treasury.sqlite"
    csv = (
        b"effective_date,account_location,currency,closing_balance,note\n"
        b"2026-08-15,mBank PLN,PLN,1000.50,closing\n"
        b"2026-08-16,mBank PLN,PLN,1100.00,closing\n"
    )
    preview = parse_csv_balances(csv, filename="mbank.csv")
    assert preview.valid
    assert len(preview.rows) == 2
    save_preview_batch(db, preview, uploaded_by="tester")
    result = confirm_import_batch(db, preview.batch_id, operator="tester")
    assert result["inserted"] == 2
    rows = latest_balances_as_of(db, "2026-08-16")
    assert len(rows) == 1
    assert rows[0]["closing_balance"] == "1100.00"
    assert rows[0]["source"] == "BANK_IMPORT"


def test_confirm_refuses_second_confirm(tmp_path: Path):
    db = tmp_path / "treasury.sqlite"
    csv = (
        b"effective_date,account_location,currency,closing_balance,note\n"
        b"2026-08-15,Cash PLN,PLN,50.00,x\n"
    )
    preview = parse_csv_balances(csv, filename="cash.csv")
    save_preview_batch(db, preview, uploaded_by="tester")
    confirm_import_batch(db, preview.batch_id, operator="tester")
    try:
        confirm_import_batch(db, preview.batch_id, operator="tester")
        raised = False
    except ValueError as exc:
        raised = True
        assert "already confirmed" in str(exc).lower() or "race" in str(exc).lower()
    assert raised
    rows = latest_balances_as_of(db, "2026-08-15")
    assert len(rows) == 1
    assert rows[0]["closing_balance"] == "50.00"
