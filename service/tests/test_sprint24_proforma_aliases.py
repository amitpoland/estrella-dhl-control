"""
test_sprint24_proforma_aliases.py — Contract tests for Sprint-24 Screen-B read-only aliases.

Tests:
  1. GET /api/v1/proforma/draft/{draft_id}/to-invoice-preview
     alias resolver: draft_id → (batch_id, client_name) → delegates to preview function
  2. GET /api/v1/proforma/draft/{draft_id}/invoice-link
     read-only join on proforma_invoice_links by wfirma_proforma_id

Both are read-only. No financial mutations tested here.
"""
from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.auth.dependencies import get_current_user


# ── Auth bypass ───────────────────────────────────────────────────────────────

_TEST_USER = {"id": "test", "email": "test@local", "role": "admin"}


@pytest.fixture(autouse=True)
def bypass_auth():
    app.dependency_overrides[get_current_user] = lambda: _TEST_USER
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=True)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_draft_db(tmp: Path, *, batch_id="BATCH_TEST", client_name="Test Client",
                   draft_state="editing", wfirma_proforma_id=None):
    """Create a minimal proforma_links.db with one proforma_draft row."""
    conn = sqlite3.connect(str(tmp))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS proforma_drafts (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_id            TEXT NOT NULL,
            client_name         TEXT NOT NULL,
            status              TEXT NOT NULL DEFAULT 'draft',
            currency            TEXT NOT NULL DEFAULT 'EUR',
            exchange_rate       REAL,
            source_lines_json   TEXT NOT NULL DEFAULT '[]',
            wfirma_proforma_id  TEXT,
            notes               TEXT,
            created_at          TEXT NOT NULL DEFAULT '2026-01-01T00:00:00',
            updated_at          TEXT NOT NULL DEFAULT '2026-01-01T00:00:00',
            draft_state         TEXT NOT NULL DEFAULT 'editing',
            draft_version       INTEGER NOT NULL DEFAULT 1,
            editable_lines_json TEXT NOT NULL DEFAULT '[]',
            service_charges_json TEXT NOT NULL DEFAULT '[]',
            buyer_override_json TEXT NOT NULL DEFAULT '{}',
            ship_to_override_json TEXT NOT NULL DEFAULT '{}',
            payment_terms_json  TEXT NOT NULL DEFAULT '{}',
            remarks             TEXT NOT NULL DEFAULT '',
            wfirma_proforma_fullnumber TEXT NOT NULL DEFAULT '',
            fx_rate_source      TEXT NOT NULL DEFAULT 'NBP'
        )
    """)
    conn.execute(
        "INSERT INTO proforma_drafts (batch_id, client_name, status, draft_state, wfirma_proforma_id)"
        " VALUES (?,?,?,?,?)",
        (batch_id, client_name, "draft", draft_state, wfirma_proforma_id),
    )
    conn.commit()
    conn.close()
    return tmp


def _make_link_db(tmp: Path, *, proforma_id: str, status="issued",
                  invoice_id="INV123", invoice_number="FV 99/2026"):
    """Create a minimal proforma_links.db with one proforma_invoice_links row."""
    conn = sqlite3.connect(str(tmp))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS proforma_invoice_links (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            proforma_id      TEXT NOT NULL UNIQUE,
            proforma_number  TEXT NOT NULL DEFAULT '',
            converted_at     TEXT NOT NULL DEFAULT '2026-01-01T00:00:00',
            operator         TEXT NOT NULL DEFAULT 'test',
            source_total     REAL NOT NULL DEFAULT 0.0,
            currency         TEXT NOT NULL DEFAULT 'EUR',
            status           TEXT NOT NULL,
            invoice_id       TEXT,
            invoice_number   TEXT,
            invoice_total    REAL,
            notes            TEXT,
            wfirma_pz_doc_id TEXT
        )
    """)
    conn.execute(
        "INSERT INTO proforma_invoice_links (proforma_id, status, invoice_id, invoice_number)"
        " VALUES (?,?,?,?)",
        (proforma_id, status, invoice_id, invoice_number),
    )
    conn.commit()
    conn.close()


# ── Tests: GET .../to-invoice-preview alias ───────────────────────────────────

class TestDraftToInvoicePreviewAlias:

    def test_404_for_unknown_draft_id(self, client, tmp_path):
        db = tmp_path / "proforma_links.db"
        _make_draft_db(db)
        with patch("app.api.routes_proforma._proforma_db_path", return_value=db):
            r = client.get("/api/v1/proforma/draft/999/to-invoice-preview")
        assert r.status_code == 404, f"expected 404, got {r.status_code}"
        assert "not found" in r.json()["detail"].lower()

    def test_resolves_draft_id_to_batch_client(self, client, tmp_path):
        """Alias resolves draft_id → (batch_id, client_name) and calls preview."""
        db = tmp_path / "proforma_links.db"
        _make_draft_db(db, batch_id="BATCH_XYZ", client_name="Acme Corp",
                       wfirma_proforma_id="PROF999")

        # Mock the delegated preview function so we verify the resolution
        with patch("app.api.routes_proforma._proforma_db_path", return_value=db), \
             patch("app.api.routes_proforma.proforma_to_invoice_preview") as mock_preview:
            mock_preview.return_value = MagicMock(status_code=200)
            client.get("/api/v1/proforma/draft/1/to-invoice-preview")

        # Verify the alias called the preview with the resolved (batch_id, client_name)
        mock_preview.assert_called_once_with("BATCH_XYZ", "Acme Corp")

    def test_no_draft_id_in_db_returns_404(self, client, tmp_path):
        db = tmp_path / "proforma_links.db"
        _make_draft_db(db)  # creates draft with id=1
        with patch("app.api.routes_proforma._proforma_db_path", return_value=db):
            r = client.get("/api/v1/proforma/draft/2/to-invoice-preview")
        assert r.status_code == 404


# ── Tests: GET .../invoice-link ───────────────────────────────────────────────

class TestDraftInvoiceLink:

    def test_404_for_unknown_draft_id(self, client, tmp_path):
        db = tmp_path / "proforma_links.db"
        _make_draft_db(db)
        with patch("app.api.routes_proforma._proforma_db_path", return_value=db):
            r = client.get("/api/v1/proforma/draft/999/invoice-link")
        assert r.status_code == 404

    def test_not_converted_when_no_wfirma_proforma_id(self, client, tmp_path):
        """Draft with no wfirma_proforma_id → not_converted."""
        db = tmp_path / "proforma_links.db"
        _make_draft_db(db, wfirma_proforma_id=None)
        with patch("app.api.routes_proforma._proforma_db_path", return_value=db):
            r = client.get("/api/v1/proforma/draft/1/invoice-link")
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is False
        assert body["status"] == "not_converted"
        assert "wfirma_proforma_id" not in body or body.get("wfirma_proforma_id") is None

    def test_not_converted_when_no_link_row(self, client, tmp_path):
        """Draft with wfirma_proforma_id but no link row → not_converted."""
        db = tmp_path / "proforma_links.db"
        _make_draft_db(db, wfirma_proforma_id="PROF777")
        # Link DB exists but no link row for PROF777
        _make_link_db(db, proforma_id="OTHER_PROF", status="issued",
                      invoice_id="INV_OTHER", invoice_number="FV 1/2026")
        # Patch settings on the routes module so the link_db path resolves to tmp_path
        with patch("app.api.routes_proforma._proforma_db_path", return_value=db), \
             patch("app.api.routes_proforma.settings") as mock_settings:
            mock_settings.storage_root = tmp_path
            r = client.get("/api/v1/proforma/draft/1/invoice-link")
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is False
        assert body["status"] == "not_converted"

    def test_issued_link_returns_invoice_data(self, client, tmp_path):
        """Draft with issued conversion link returns invoice_id + invoice_number."""
        db = tmp_path / "proforma_links.db"
        _make_draft_db(db, wfirma_proforma_id="PROF42")
        _make_link_db(db, proforma_id="PROF42", status="issued",
                      invoice_id="WDT_999", invoice_number="FV WDT 99/2026")
        with patch("app.api.routes_proforma._proforma_db_path", return_value=db), \
             patch("app.api.routes_proforma.settings") as mock_settings:
            mock_settings.storage_root = tmp_path
            r = client.get("/api/v1/proforma/draft/1/invoice-link")
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["status"] == "issued"
        assert body["invoice_id"] == "WDT_999"
        assert body["invoice_number"] == "FV WDT 99/2026"
        assert body["wfirma_proforma_id"] == "PROF42"

    def test_failed_link_returns_failed_status(self, client, tmp_path):
        """Failed conversion link returns status=failed."""
        db = tmp_path / "proforma_links.db"
        _make_draft_db(db, wfirma_proforma_id="PROF43")
        _make_link_db(db, proforma_id="PROF43", status="failed",
                      invoice_id=None, invoice_number=None)
        with patch("app.api.routes_proforma._proforma_db_path", return_value=db), \
             patch("app.api.routes_proforma.settings") as mock_settings:
            mock_settings.storage_root = tmp_path
            r = client.get("/api/v1/proforma/draft/1/invoice-link")
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["status"] == "failed"
        assert body["invoice_id"] is None


# ── Sprint-24 §4.1 Phantom row filter ────────────────────────────────────────

class TestPhantomRowFilter:
    """Verifies that the wfirma_reservation.get_reservation_preview filters
    empty-name + empty-doc_number stub rows from the documents list."""

    def test_filter_empty_name_no_docno_stub(self):
        """A sales_doc with empty client_name and no doc_number must be filtered."""
        from app.services.wfirma_reservation import _filter_stub_doc

        # Stub: empty name, no doc_number
        assert _filter_stub_doc({"client_name": "", "sales_doc_no": None}) is True
        assert _filter_stub_doc({"client_name": "   ", "sales_doc_no": ""}) is True
        # Real unassigned draft: empty name but HAS a doc_number → keep
        assert _filter_stub_doc({"client_name": "", "sales_doc_no": "DOC-001"}) is False
        # Normal row: has client name → keep
        assert _filter_stub_doc({"client_name": "Diamond Point", "sales_doc_no": "DOC-002"}) is False
        assert _filter_stub_doc({"client_name": "Acme", "sales_doc_no": None}) is False
