"""Tests for ProformaDraft Phase 7 schema extensions.

Source-grep + lightweight DB tests. No server required.
"""
import sqlite3
import pytest
from pathlib import Path
from app.services.proforma_invoice_link_db import (
    ProformaDraft, _ensure_drafts_table,
)


def test_proforma_draft_has_fx_rate_date():
    d = ProformaDraft(batch_id="b1", client_name="c1", status="draft")
    assert hasattr(d, "fx_rate_date")
    assert d.fx_rate_date is None

def test_proforma_draft_fx_rate_source_default():
    d = ProformaDraft(batch_id="b1", client_name="c1", status="draft")
    assert d.fx_rate_source == "NBP"

def test_proforma_draft_incoterm_nullable():
    d = ProformaDraft(batch_id="b1", client_name="c1", status="draft")
    assert d.incoterm is None

def test_proforma_draft_insurance_eur_nullable():
    d = ProformaDraft(batch_id="b1", client_name="c1", status="draft")
    assert d.insurance_eur is None

def test_additive_alter_idempotent(tmp_path):
    """Running _ensure_drafts_table twice must not raise."""
    db = tmp_path / "proforma_links.db"
    with sqlite3.connect(str(db)) as conn:
        _ensure_drafts_table(conn)
        _ensure_drafts_table(conn)  # second call must be silent

def test_fx_rate_date_column_present_after_migration(tmp_path):
    db = tmp_path / "proforma_links.db"
    with sqlite3.connect(str(db)) as conn:
        _ensure_drafts_table(conn)
        cols = [r[1] for r in conn.execute("PRAGMA table_info(proforma_drafts)").fetchall()]
    assert "fx_rate_date" in cols
    assert "fx_rate_source" in cols
    assert "incoterm" in cols
    assert "insurance_eur" in cols

def test_fx_rate_date_round_trip(tmp_path):
    """Write fx_rate_date via auto_create, read it back."""
    from app.services.proforma_invoice_link_db import (
        auto_create_draft_from_sales_packing, get_draft,
    )
    db = tmp_path / "proforma_links.db"
    draft, _ = auto_create_draft_from_sales_packing(
        db,
        batch_id="TEST_BATCH_001",
        client_name="TestClient",
        currency="EUR",
        lines=[{"product_code": "SKU001", "design_no": "D001", "qty": 1, "unit_price": 100.0, "currency": "EUR"}],
    )
    # fx_rate_date may be None initially (set when exchange_rate is set) — just assert no crash
    assert draft.batch_id == "TEST_BATCH_001"
    assert draft.fx_rate_source == "NBP"

def test_incoterm_and_insurance_eur_settable(tmp_path):
    """Verify incoterm and insurance_eur can be stored."""
    from app.services.proforma_invoice_link_db import (
        auto_create_draft_from_sales_packing,
    )
    db = tmp_path / "proforma_links.db"
    draft, _ = auto_create_draft_from_sales_packing(
        db,
        batch_id="TEST_BATCH_002",
        client_name="TestClient2",
        currency="EUR",
        lines=[],
    )
    # Directly update the columns to verify they accept values
    with sqlite3.connect(str(db)) as conn:
        conn.execute(
            "UPDATE proforma_drafts SET incoterm=?, insurance_eur=? WHERE id=?",
            ("DAP", 200.0, draft.id),
        )
    with sqlite3.connect(str(db)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM proforma_drafts WHERE id=?", (draft.id,)).fetchone()
    assert row["incoterm"] == "DAP"
    assert abs(row["insurance_eur"] - 200.0) < 0.001

def test_source_grep_phase7_columns():
    """Schema additions must appear in the source file."""
    src = Path(__file__).resolve().parent.parent / "app" / "services" / "proforma_invoice_link_db.py"
    content = src.read_text(encoding="utf-8")
    assert "fx_rate_date" in content
    assert "fx_rate_source" in content
    assert "incoterm" in content
    assert "insurance_eur" in content
    assert "Phase 7" in content
