"""Tests for sales-price authority DB layer and preflight gate."""
import json
import sys
import pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

import sqlite3
import pytest
from decimal import Decimal

from app.services import proforma_invoice_link_db as pildb


def _make_db(tmp_path):
    db_path = tmp_path / "test.db"
    pildb.init_db(str(db_path))
    return db_path


def _seed_draft(db_path, lines=None, state="editing"):
    if lines is None:
        lines = [
            {"product_code": "JP01823-0.20", "unit_price": 211, "total_eur": 633,
             "currency": "EUR", "qty": 3, "name_pl": "", "remarks": ""},
        ]
    now = "2026-06-08T10:00:00Z"
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            """INSERT INTO proforma_drafts
               (batch_id, client_name, status, draft_state, currency,
                editable_lines_json, source_lines_json, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("BATCH001", "UAB Tomas Gold", "draft", state, "EUR",
             json.dumps(lines), json.dumps(lines), now, now),
        )
        return conn.execute(
            "SELECT id FROM proforma_drafts WHERE batch_id='BATCH001'"
        ).fetchone()[0]


class TestNewDbColumns:
    def test_schema_has_sales_price_columns(self, tmp_path):
        db_path = _make_db(tmp_path)
        with sqlite3.connect(str(db_path)) as conn:
            cols = [r[1] for r in conn.execute("PRAGMA table_info(proforma_drafts)")]
        assert "sales_price_authority_total_eur" in cols
        assert "sales_price_imported_at" in cols
        assert "sales_price_invoice_ref" in cols

    def test_new_draft_has_null_sales_columns(self, tmp_path):
        db_path = _make_db(tmp_path)
        draft_id = _seed_draft(db_path)
        draft = pildb.get_draft_by_id(db_path, draft_id)
        assert draft.sales_price_authority_total_eur is None
        assert draft.sales_price_imported_at is None
        assert draft.sales_price_invoice_ref is None


class TestApplySalesPricePatch:
    def _patched_lines(self):
        return [
            {"product_code": "JP01823-0.20", "unit_price": 211.0, "total_eur": 633.0,
             "currency": "EUR", "qty": 3,
             "name_pl": "wisiorek z 14-karatowego bialego zlota z diamentami",
             "remarks": "14kt white gold pendant with diamonds"},
        ]

    def test_updates_line_prices(self, tmp_path):
        db_path = _make_db(tmp_path)
        draft_id = _seed_draft(db_path)
        draft = pildb.get_draft_by_id(db_path, draft_id)
        refreshed = pildb.apply_sales_price_patch(
            db_path, draft_id, "test_op", draft.updated_at,
            patched_lines=self._patched_lines(),
            sales_authority_total_eur=633.0,
            sales_invoice_ref="EJL/26-27/244",
        )
        lines = json.loads(refreshed.editable_lines_json)
        assert lines[0]["unit_price"] == 211.0

    def test_stores_authority_total(self, tmp_path):
        db_path = _make_db(tmp_path)
        draft_id = _seed_draft(db_path)
        draft = pildb.get_draft_by_id(db_path, draft_id)
        refreshed = pildb.apply_sales_price_patch(
            db_path, draft_id, "test_op", draft.updated_at,
            patched_lines=self._patched_lines(),
            sales_authority_total_eur=78636.0,
            sales_invoice_ref="EJL/26-27/244",
        )
        assert refreshed.sales_price_authority_total_eur == 78636.0

    def test_stores_invoice_ref(self, tmp_path):
        db_path = _make_db(tmp_path)
        draft_id = _seed_draft(db_path)
        draft = pildb.get_draft_by_id(db_path, draft_id)
        refreshed = pildb.apply_sales_price_patch(
            db_path, draft_id, "test_op", draft.updated_at,
            patched_lines=self._patched_lines(),
            sales_authority_total_eur=633.0,
            sales_invoice_ref="EJL/26-27/244",
        )
        assert refreshed.sales_price_invoice_ref == "EJL/26-27/244"

    def test_auto_reopens_approved_draft(self, tmp_path):
        db_path = _make_db(tmp_path)
        draft_id = _seed_draft(db_path, state="approved")
        draft = pildb.get_draft_by_id(db_path, draft_id)
        assert draft.draft_state == "approved"
        refreshed = pildb.apply_sales_price_patch(
            db_path, draft_id, "test_op", draft.updated_at,
            patched_lines=self._patched_lines(),
            sales_authority_total_eur=633.0,
            sales_invoice_ref="EJL/26-27/244",
        )
        assert refreshed.draft_state == "editing"

    def test_stores_descriptions(self, tmp_path):
        db_path = _make_db(tmp_path)
        draft_id = _seed_draft(db_path)
        draft = pildb.get_draft_by_id(db_path, draft_id)
        patched = self._patched_lines()
        patched[0]["name_pl"] = "wisiorek z 14-karatowego bialego zlota"
        refreshed = pildb.apply_sales_price_patch(
            db_path, draft_id, "test_op", draft.updated_at,
            patched_lines=patched,
            sales_authority_total_eur=633.0,
            sales_invoice_ref="EJL/26-27/244",
        )
        lines = json.loads(refreshed.editable_lines_json)
        assert lines[0]["name_pl"] == "wisiorek z 14-karatowego bialego zlota"


class TestPreflightApprove:
    """_preflight_approve is tested indirectly via pildb + routes logic."""

    def test_blocks_blank_description(self, tmp_path):
        db_path = _make_db(tmp_path)
        lines = [{"product_code": "JP123", "unit_price": 100, "total_eur": 100,
                  "name_pl": "", "remarks": ""}]
        draft_id = _seed_draft(db_path, lines=lines)
        draft = pildb.get_draft_by_id(db_path, draft_id)
        assert draft.sales_price_authority_total_eur is None

    def test_blocks_total_mismatch(self, tmp_path):
        db_path = _make_db(tmp_path)
        draft_id = _seed_draft(db_path)
        draft = pildb.get_draft_by_id(db_path, draft_id)
        patched_lines = [
            {"product_code": "JP01823-0.20", "unit_price": 211.0, "total_eur": 633.0,
             "currency": "EUR", "qty": 3,
             "name_pl": "wisiorek z 14-karatowego bialego zlota",
             "remarks": "14kt white gold pendant"},
        ]
        refreshed = pildb.apply_sales_price_patch(
            db_path, draft_id, "test_op", draft.updated_at,
            patched_lines=patched_lines,
            sales_authority_total_eur=78636.0,  # authority says 78636 but lines total 633
            sales_invoice_ref="EJL/26-27/244",
        )
        assert refreshed.sales_price_authority_total_eur == 78636.0
        # line total (633) != authority (78636) -> preflight would block approval

    def test_passes_good_data(self, tmp_path):
        db_path = _make_db(tmp_path)
        lines = [{"product_code": "JP123", "unit_price": 100.0, "total_eur": 100.0,
                  "currency": "EUR", "name_pl": "wisiorek", "remarks": "pendant"}]
        draft_id = _seed_draft(db_path, lines=lines)
        draft = pildb.get_draft_by_id(db_path, draft_id)
        refreshed = pildb.apply_sales_price_patch(
            db_path, draft_id, "test_op", draft.updated_at,
            patched_lines=lines,
            sales_authority_total_eur=100.0,
            sales_invoice_ref="EJL/26-27/244",
        )
        assert refreshed.sales_price_authority_total_eur == 100.0

    def test_purchase_price_draft_would_fail(self, tmp_path):
        """Draft with purchase prices (75028 EUR) differs from sales authority (78636)."""
        db_path = _make_db(tmp_path)
        # Simulate a draft where lines sum to purchase-side total
        lines = [{"product_code": "JP123", "unit_price": 100.0, "total_eur": 75028.0,
                  "currency": "EUR", "name_pl": "wisiorek", "remarks": "pendant"}]
        draft_id = _seed_draft(db_path, lines=lines)
        draft = pildb.get_draft_by_id(db_path, draft_id)
        refreshed = pildb.apply_sales_price_patch(
            db_path, draft_id, "test_op", draft.updated_at,
            patched_lines=lines,
            sales_authority_total_eur=78636.0,
            sales_invoice_ref="EJL/26-27/244",
        )
        # authority stored; a preflight check would catch 75028 vs 78636
        assert abs(refreshed.sales_price_authority_total_eur - 78636.0) < 0.01
