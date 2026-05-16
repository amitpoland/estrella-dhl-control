"""Phase 6F.5 — Legacy table isolation.

The dual-write must NEVER mutate ``proforma_service_charges`` (the legacy
table). We enforce this two ways:

1. Source-grep: the helper file does not reference the legacy module name.
2. Runtime: when a legacy DB file exists alongside the finance DB, running
   the dual-write does not change a single byte of the legacy file.
"""
from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

from app.services import finance_dual_write as fdw


def _make_legacy_db(p: Path) -> bytes:
    """Create a minimal legacy proforma_service_charges DB and return its bytes."""
    with sqlite3.connect(str(p)) as c:
        c.execute(
            "CREATE TABLE proforma_service_charges ("
            "batch_id TEXT, client_name TEXT, charge_type TEXT, amount REAL, "
            "currency TEXT, note TEXT, created_by TEXT, created_at TEXT, updated_at TEXT)"
        )
        c.execute(
            "INSERT INTO proforma_service_charges VALUES "
            "('B/old', 'Legacy Ltd', 'freight', 5.55, 'EUR', 'legacy', "
            "'tester', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')"
        )
        c.commit()
    return p.read_bytes()


def test_legacy_db_byte_identical_before_and_after(tmp_path: Path):
    legacy = tmp_path / "proforma_links.db"
    finance = tmp_path / "finance_postings.sqlite"
    before_bytes = _make_legacy_db(legacy)

    res = fdw.dual_write_proforma_post(
        db_path=finance,
        batch_id="B/new",
        client_name="New Co",
        currency="EUR",
        full_number="FV/1/2026",
        service_charges_json='[{"charge_type":"freight","amount":1.00,"currency":"EUR"}]',
        enabled=True,
        shadow=False,
    )
    assert res["ok"] is True
    # Dual-write succeeded against the finance DB.
    assert finance.exists()
    # Legacy DB is byte-identical (no mtime check — SQLite WAL might touch it
    # if we'd opened it; we never did).
    after_bytes = legacy.read_bytes()
    assert after_bytes == before_bytes, (
        "Legacy proforma_service_charges DB was mutated by dual-write"
    )


def test_source_grep_no_legacy_table_writes():
    """Helper file must not contain any write SQL against the legacy table."""
    import re
    src = Path(__file__).resolve().parents[1] / "app" / "services" / "finance_dual_write.py"
    text = src.read_text(encoding="utf-8")
    forbidden_patterns = [
        r"INSERT\s+INTO\s+proforma_service_charges",
        r"UPDATE\s+proforma_service_charges",
        r"DELETE\s+FROM\s+proforma_service_charges",
        r"from\s+\.\s*proforma_service_charges_db",
        r"import\s+proforma_service_charges_db",
    ]
    for pat in forbidden_patterns:
        hits = re.findall(pat, text, flags=re.IGNORECASE)
        assert hits == [], f"Forbidden legacy-table reference: {pat!r} in finance_dual_write.py"
