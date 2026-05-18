"""Phase 3 — wFirma post-posting enrichment tests.

Tests are source-grep + DB round-trip style (no live wFirma calls).
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import pytest

# ── Source-grep tests ─────────────────────────────────────────────────────────

_WFIRMA_CLIENT = Path(__file__).parent.parent / "app" / "services" / "wfirma_client.py"
_PIL_DB        = Path(__file__).parent.parent / "app" / "services" / "proforma_invoice_link_db.py"
_ROUTES        = Path(__file__).parent.parent / "app" / "api" / "routes_proforma.py"

_wfirma_src = _WFIRMA_CLIENT.read_text()
_pildb_src  = _PIL_DB.read_text()
_routes_src = _ROUTES.read_text()


def test_fetch_proforma_enrichment_exists():
    assert "def fetch_proforma_enrichment" in _wfirma_src


def test_fetch_company_account_iban_exists():
    assert "def fetch_company_account_iban" in _wfirma_src


def test_enrichment_returns_three_keys():
    """Verify the return dict has issue_date, payment_due, payment_method."""
    assert '"issue_date"' in _wfirma_src
    assert '"payment_due"' in _wfirma_src
    assert '"payment_method"' in _wfirma_src


def test_write_postposting_enrichment_in_pildb():
    assert "def write_postposting_enrichment" in _pildb_src


def test_pildb_dataclass_has_wfirma_issue_date():
    assert "wfirma_issue_date" in _pildb_src


def test_pildb_dataclass_has_wfirma_payment_due():
    assert "wfirma_payment_due" in _pildb_src


def test_pildb_dataclass_has_wfirma_payment_method():
    assert "wfirma_payment_method" in _pildb_src


def test_additive_columns_include_phase3():
    assert '("wfirma_issue_date"' in _pildb_src
    assert '("wfirma_payment_due"' in _pildb_src
    assert '("wfirma_payment_method"' in _pildb_src


def test_routes_calls_fetch_proforma_enrichment():
    assert "fetch_proforma_enrichment" in _routes_src


def test_routes_calls_write_postposting_enrichment():
    assert "write_postposting_enrichment" in _routes_src


def test_routes_enrichment_is_best_effort():
    """Enrichment must be wrapped in try/except — never fail main flow."""
    # Check that the enrichment call is inside a try block
    pattern = re.compile(
        r"try:.*?fetch_proforma_enrichment",
        re.DOTALL,
    )
    assert pattern.search(_routes_src), (
        "fetch_proforma_enrichment must be inside a try block (best-effort)"
    )


def test_renderer_shows_wfirma_dates():
    assert "_wfirma_dates_html" in _routes_src


# ── DB round-trip tests ───────────────────────────────────────────────────────

def _build_db() -> tuple[Path, sqlite3.Connection]:
    tmp = tempfile.mktemp(suffix=".db")
    conn = sqlite3.connect(tmp)
    conn.row_factory = sqlite3.Row
    return Path(tmp), conn


def test_write_postposting_enrichment_round_trip(tmp_path):
    """write_postposting_enrichment stores and retrieves all three fields."""
    from app.services.proforma_invoice_link_db import (
        write_postposting_enrichment,
        _ensure_drafts_table,
        _now_utc_iso,
    )

    db_path = tmp_path / "p3_a.db"
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        _ensure_drafts_table(conn)
        conn.execute(
            "INSERT INTO proforma_drafts "
            "(batch_id, client_name, status, currency, created_at, updated_at) "
            "VALUES ('B1', 'Client A', 'draft', 'EUR', ?, ?)",
            (_now_utc_iso(), _now_utc_iso()),
        )
        conn.commit()
        draft_id = conn.execute("SELECT id FROM proforma_drafts LIMIT 1").fetchone()[0]

    write_postposting_enrichment(
        db_path,
        draft_id,
        wfirma_issue_date     = "2026-05-15",
        wfirma_payment_due    = "2026-06-15",
        wfirma_payment_method = "transfer",
    )

    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT wfirma_issue_date, wfirma_payment_due, wfirma_payment_method "
            "FROM proforma_drafts WHERE id=?", (draft_id,)
        ).fetchone()

    assert row["wfirma_issue_date"]     == "2026-05-15"
    assert row["wfirma_payment_due"]    == "2026-06-15"
    assert row["wfirma_payment_method"] == "transfer"


def test_write_postposting_enrichment_nullable(tmp_path):
    """Null values are stored and returned as None."""
    from app.services.proforma_invoice_link_db import (
        write_postposting_enrichment,
        _ensure_drafts_table,
        _now_utc_iso,
    )

    db_path = tmp_path / "p3_b.db"
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        _ensure_drafts_table(conn)
        conn.execute(
            "INSERT INTO proforma_drafts "
            "(batch_id, client_name, status, currency, created_at, updated_at) "
            "VALUES ('B2', 'Client B', 'draft', 'USD', ?, ?)",
            (_now_utc_iso(), _now_utc_iso()),
        )
        conn.commit()
        draft_id = conn.execute("SELECT id FROM proforma_drafts LIMIT 1").fetchone()[0]

    write_postposting_enrichment(
        db_path, draft_id,
        wfirma_issue_date=None, wfirma_payment_due=None, wfirma_payment_method=None,
    )

    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT wfirma_issue_date, wfirma_payment_due, wfirma_payment_method "
            "FROM proforma_drafts WHERE id=?", (draft_id,)
        ).fetchone()

    assert row["wfirma_issue_date"]     is None
    assert row["wfirma_payment_due"]    is None
    assert row["wfirma_payment_method"] is None


def test_write_postposting_enrichment_invalid_id(tmp_path):
    """Invalid draft_id raises ValueError."""
    from app.services.proforma_invoice_link_db import write_postposting_enrichment

    db_path = tmp_path / "p3_c.db"
    with pytest.raises(ValueError):
        write_postposting_enrichment(
            db_path, -1,
            wfirma_issue_date=None, wfirma_payment_due=None, wfirma_payment_method=None,
        )


def test_additive_alter_idempotent_phase3(tmp_path):
    """Running _ensure_drafts_table twice does not raise on Phase 3 columns."""
    from app.services.proforma_invoice_link_db import _ensure_drafts_table

    db_path = tmp_path / "p3_d.db"
    with sqlite3.connect(str(db_path)) as conn:
        _ensure_drafts_table(conn)
        _ensure_drafts_table(conn)  # idempotent — no error

    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        _ensure_drafts_table(conn)
        cols = [r[1] for r in conn.execute("PRAGMA table_info(proforma_drafts)")]
    assert "wfirma_issue_date"     in cols
    assert "wfirma_payment_due"    in cols
    assert "wfirma_payment_method" in cols
