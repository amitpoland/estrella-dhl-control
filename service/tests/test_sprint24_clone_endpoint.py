"""
test_sprint24_clone_endpoint.py — Clone endpoint contract tests.

Covers POST /api/v1/proforma/draft/{draft_id}/clone:
  1. Creates a NEW draft row (source is untouched)
  2. Clone gets draft_state='draft', no wfirma_proforma_id
  3. Clone carries source_ref_id pointing to source
  4. Clone copies all editable fields (lines, currency, overrides)
  5. 404 for unknown source_id
  6. No proforma_invoice_link created for the clone
  7. Source draft edits are intact after clone
"""
from __future__ import annotations

import sqlite3
import json
from datetime import datetime
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.auth.dependencies import get_current_user

# ── Auth bypass ───────────────────────────────────────────────────────────────

_TEST_USER = {
    "id": "test-id", "email": "test@local",
    "full_name": "Test Operator", "role": "admin",
    "is_active": True, "is_approved": True,
}

@pytest.fixture(autouse=True)
def bypass_auth():
    app.dependency_overrides[get_current_user] = lambda: _TEST_USER
    yield
    app.dependency_overrides.clear()

@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=True)

# ── DB helper ─────────────────────────────────────────────────────────────────

def _make_draft_db(path, *, batch_id="BATCH_CLONE_TEST",
                   client_name="Clone Test Client",
                   draft_state="editing",
                   wfirma_proforma_id=None,
                   lines=None,
                   currency="EUR"):
    """Use real init_db() then insert one draft row."""
    from app.services import proforma_invoice_link_db as pildb
    from pathlib import Path as _P
    pildb.init_db(_P(str(path)))
    now = datetime.utcnow().isoformat()
    lines_json = json.dumps(lines or [
        {"line_id": 1, "product_code": "TST001", "name_en": "Widget",
         "qty": 3, "unit_price": 150.0, "currency": currency}
    ])
    conn = sqlite3.connect(str(path))
    conn.execute(
        "INSERT INTO proforma_drafts"
        " (batch_id, client_name, status, draft_state, currency,"
        "  wfirma_proforma_id, editable_lines_json, source_lines_json,"
        "  buyer_override_json, ship_to_override_json, payment_terms_json,"
        "  remarks, fx_rate_source, created_at, updated_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (batch_id, client_name, "draft", draft_state, currency,
         wfirma_proforma_id, lines_json, "[]",
         '{"name":"Buyer Co"}', '{}', '{"paymentmethod":"transfer"}',
         "Test remarks", "NBP", now, now),
    )
    conn.commit()
    conn.close()


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestCloneEndpoint:

    def test_404_for_unknown_draft(self, client, tmp_path):
        db = tmp_path / "proforma_links.db"
        _make_draft_db(db)
        with patch("app.api.routes_proforma._proforma_db_path", return_value=db):
            r = client.post("/api/v1/proforma/draft/999/clone")
        assert r.status_code == 404, f"Expected 404, got {r.status_code}: {r.text}"

    def test_clone_creates_new_row(self, client, tmp_path):
        """Clone must return a NEW draft id — not the same as the source."""
        db = tmp_path / "proforma_links.db"
        _make_draft_db(db)
        with patch("app.api.routes_proforma._proforma_db_path", return_value=db):
            r = client.post("/api/v1/proforma/draft/1/clone")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["draft_id"] != 1, "Clone must have a different id from source"
        assert body["source_id"] == 1

    def test_source_draft_unchanged_after_clone(self, client, tmp_path):
        """The source draft MUST NOT be modified by the clone operation."""
        db = tmp_path / "proforma_links.db"
        _make_draft_db(db, draft_state="editing",
                       lines=[{"line_id": 99, "product_code": "ORIG", "qty": 7}])

        with patch("app.api.routes_proforma._proforma_db_path", return_value=db):
            client.post("/api/v1/proforma/draft/1/clone")

        # Re-read source from DB
        conn = sqlite3.connect(str(db))
        row = conn.execute(
            "SELECT draft_state, editable_lines_json FROM proforma_drafts WHERE id=1"
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[0] == "editing", "Source draft_state must be unchanged"
        lines = json.loads(row[1] or "[]")
        assert any(l.get("product_code") == "ORIG" for l in lines), (
            "Source lines must be intact after clone"
        )

    def test_clone_properties(self, client, tmp_path):
        """Clone must have: draft_state='draft', no wfirma_proforma_id, source_ref_id set."""
        db = tmp_path / "proforma_links.db"
        _make_draft_db(db, wfirma_proforma_id="PROF_12345")
        with patch("app.api.routes_proforma._proforma_db_path", return_value=db):
            r = client.post("/api/v1/proforma/draft/1/clone")
        assert r.status_code == 200
        body = r.json()
        new_id = body["draft_id"]

        # Verify clone row in DB
        conn = sqlite3.connect(str(db))
        row = conn.execute(
            "SELECT draft_state, wfirma_proforma_id, source_ref_id, clone_generation"
            " FROM proforma_drafts WHERE id=?", (new_id,)
        ).fetchone()
        conn.close()
        assert row is not None, "Clone row must exist in DB"
        assert row[0] == "draft",   "Clone must have draft_state='draft'"
        assert row[1] is None,      "Clone must NOT have wfirma_proforma_id"
        assert row[2] == 1,         "Clone source_ref_id must point to source"
        assert row[3] >= 1,         "Clone generation must be >= 1"

    def test_clone_copies_lines_and_overrides(self, client, tmp_path):
        """Clone must carry all editable_lines_json, currency, and override JSON."""
        db = tmp_path / "proforma_links.db"
        src_lines = [{"line_id": 5, "product_code": "XYZ", "qty": 2, "unit_price": 99.0}]
        _make_draft_db(db, currency="USD", lines=src_lines)
        with patch("app.api.routes_proforma._proforma_db_path", return_value=db):
            r = client.post("/api/v1/proforma/draft/1/clone")
        assert r.status_code == 200
        new_id = r.json()["draft_id"]

        conn = sqlite3.connect(str(db))
        row = conn.execute(
            "SELECT currency, editable_lines_json, buyer_override_json"
            " FROM proforma_drafts WHERE id=?", (new_id,)
        ).fetchone()
        conn.close()
        assert row[0] == "USD", "Clone must copy currency"
        clone_lines = json.loads(row[1] or "[]")
        assert any(l.get("product_code") == "XYZ" for l in clone_lines), (
            "Clone must copy editable_lines_json"
        )
        buyer = json.loads(row[2] or "{}")
        assert buyer.get("name") == "Buyer Co", "Clone must copy buyer_override_json"

    def test_clone_has_no_invoice_link(self, client, tmp_path):
        """A clone is unposted — it must NOT have any proforma_invoice_links row."""
        db = tmp_path / "proforma_links.db"
        _make_draft_db(db)
        with patch("app.api.routes_proforma._proforma_db_path", return_value=db):
            r = client.post("/api/v1/proforma/draft/1/clone")
        assert r.status_code == 200
        new_id = r.json()["draft_id"]

        conn = sqlite3.connect(str(db))
        # wfirma_proforma_id of clone should be None — no link row possible
        row = conn.execute(
            "SELECT wfirma_proforma_id FROM proforma_drafts WHERE id=?", (new_id,)
        ).fetchone()
        assert row[0] is None, "Clone must have NULL wfirma_proforma_id (no invoice link possible)"
        # No link row should exist with a null proforma_id
        link_count = conn.execute(
            "SELECT COUNT(*) FROM proforma_invoice_links"
        ).fetchone()[0]
        assert link_count == 0, "Clone must not create any invoice link"
        conn.close()

    def test_response_shape(self, client, tmp_path):
        """Response must include ok, draft_id, source_id, clone_generation, draft."""
        db = tmp_path / "proforma_links.db"
        _make_draft_db(db)
        with patch("app.api.routes_proforma._proforma_db_path", return_value=db):
            r = client.post("/api/v1/proforma/draft/1/clone")
        assert r.status_code == 200
        body = r.json()
        for key in ("ok", "draft_id", "source_id", "clone_generation", "draft"):
            assert key in body, f"Response missing key: {key!r}"
        assert isinstance(body["draft"], dict), "draft field must be a dict"
        assert body["draft"].get("draft_state") == "draft"
