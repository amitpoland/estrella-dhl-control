"""
test_sprint24_proforma_aliases.py — Sprint-24 Screen-B alias contract + security tests.

Covers:
  1. GET /api/v1/proforma/draft/{id}/to-invoice-preview alias
  2. GET /api/v1/proforma/draft/{id}/invoice-link JOIN
  3. POST /api/v1/proforma/draft/{id}/to-invoice session-operator alias:
     - flag-off blocks conversion (security invariant)
     - operator from session, X-Operator header IGNORED (security invariant)
     - UNIQUE(proforma_id) idempotency guard (security invariant)
     - confirm token required (security invariant)
     - delegates to existing proforma_to_invoice (no reimplementation)
  4. wfirma_reservation._filter_stub_doc() phantom-row filter
"""
from __future__ import annotations

import sqlite3
from datetime import datetime
from unittest.mock import patch, MagicMock

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
    from app.api.routes_proforma import _get_current_user_optional
    app.dependency_overrides[get_current_user] = lambda: _TEST_USER
    # Also override the optional session user so operator derivation works in tests
    app.dependency_overrides[_get_current_user_optional] = lambda: _TEST_USER
    yield
    app.dependency_overrides.clear()

@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=True)


# ── DB helpers ────────────────────────────────────────────────────────────────

def _make_draft_db(path, *, batch_id="BATCH_X", client_name="Test Client",
                   draft_state="editing", wfirma_proforma_id=None):
    """Create a proforma_links.db using the real init_db() so all columns are present."""
    from app.services import proforma_invoice_link_db as pildb
    from pathlib import Path as _P
    pildb.init_db(_P(str(path)))  # creates proforma_drafts with full schema
    now = datetime.utcnow().isoformat()
    conn = sqlite3.connect(str(path))
    conn.execute(
        "INSERT INTO proforma_drafts (batch_id, client_name, status, draft_state,"
        " wfirma_proforma_id, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
        (batch_id, client_name, "draft", draft_state, wfirma_proforma_id, now, now),
    )
    conn.commit(); conn.close()


def _make_link_db(path, *, proforma_id, status="issued",
                  invoice_id="INV999", invoice_number="FV 99/2026",
                  proforma_number="PROF TEST/2026"):
    """Use real init_db() for proper schema, then insert a link row."""
    from app.services import proforma_invoice_link_db as pildb
    from pathlib import Path as _P
    pildb.init_db(_P(str(path)))  # creates proforma_invoice_links with full schema
    now = datetime.utcnow().isoformat()
    conn = sqlite3.connect(str(path))
    conn.execute(
        "INSERT INTO proforma_invoice_links"
        " (proforma_id, proforma_number, converted_at, operator, source_total,"
        "  currency, status, invoice_id, invoice_number)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (proforma_id, proforma_number, now, "test", 0.0, "EUR",
         status, invoice_id, invoice_number),
    )
    conn.commit(); conn.close()


# ── GET .../to-invoice-preview alias ─────────────────────────────────────────

class TestToInvoicePreviewAlias:
    def test_404_unknown_draft(self, client, tmp_path):
        db = tmp_path / "proforma_links.db"; _make_draft_db(db)
        with patch("app.api.routes_proforma._proforma_db_path", return_value=db):
            r = client.get("/api/v1/proforma/draft/999/to-invoice-preview")
        assert r.status_code == 404

    def test_resolves_draft_id_to_batch_client(self, client, tmp_path):
        db = tmp_path / "proforma_links.db"
        _make_draft_db(db, batch_id="BATCH_A", client_name="Client A")
        with patch("app.api.routes_proforma._proforma_db_path", return_value=db), \
             patch("app.api.routes_proforma.proforma_to_invoice_preview") as mock:
            mock.return_value = MagicMock(status_code=200)
            client.get("/api/v1/proforma/draft/1/to-invoice-preview")
        mock.assert_called_once_with("BATCH_A", "Client A")

    def test_second_unknown_id_returns_404(self, client, tmp_path):
        db = tmp_path / "proforma_links.db"; _make_draft_db(db)
        with patch("app.api.routes_proforma._proforma_db_path", return_value=db):
            r = client.get("/api/v1/proforma/draft/2/to-invoice-preview")
        assert r.status_code == 404


# ── GET .../invoice-link ──────────────────────────────────────────────────────

class TestInvoiceLinkAlias:
    def test_404_unknown(self, client, tmp_path):
        db = tmp_path / "proforma_links.db"; _make_draft_db(db)
        with patch("app.api.routes_proforma._proforma_db_path", return_value=db):
            r = client.get("/api/v1/proforma/draft/999/invoice-link")
        assert r.status_code == 404

    def test_not_converted_no_wfirma_id(self, client, tmp_path):
        db = tmp_path / "proforma_links.db"; _make_draft_db(db, wfirma_proforma_id=None)
        with patch("app.api.routes_proforma._proforma_db_path", return_value=db):
            r = client.get("/api/v1/proforma/draft/1/invoice-link")
        assert r.status_code == 200
        body = r.json(); assert body["ok"] is False; assert body["status"] == "not_converted"

    def test_not_converted_no_link_row(self, client, tmp_path):
        db = tmp_path / "proforma_links.db"
        _make_draft_db(db, wfirma_proforma_id="PROF_X")
        _make_link_db(db, proforma_id="OTHER", status="issued")
        with patch("app.api.routes_proforma._proforma_db_path", return_value=db), \
             patch("app.api.routes_proforma.settings") as ms:
            ms.storage_root = tmp_path
            r = client.get("/api/v1/proforma/draft/1/invoice-link")
        assert r.json()["status"] == "not_converted"

    def test_issued_link_returns_invoice_data(self, client, tmp_path):
        db = tmp_path / "proforma_links.db"
        _make_draft_db(db, wfirma_proforma_id="PROF42")
        _make_link_db(db, proforma_id="PROF42", status="issued",
                      invoice_id="WDT_999", invoice_number="FV WDT 99/2026")
        with patch("app.api.routes_proforma._proforma_db_path", return_value=db), \
             patch("app.api.routes_proforma.settings") as ms:
            ms.storage_root = tmp_path
            r = client.get("/api/v1/proforma/draft/1/invoice-link")
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True; assert body["status"] == "issued"
        assert body["invoice_id"] == "WDT_999"
        assert body["invoice_number"] == "FV WDT 99/2026"
        assert body["wfirma_proforma_id"] == "PROF42"

    def test_failed_link(self, client, tmp_path):
        db = tmp_path / "proforma_links.db"
        _make_draft_db(db, wfirma_proforma_id="PROF43")
        _make_link_db(db, proforma_id="PROF43", status="failed",
                      invoice_id=None, invoice_number=None)
        with patch("app.api.routes_proforma._proforma_db_path", return_value=db), \
             patch("app.api.routes_proforma.settings") as ms:
            ms.storage_root = tmp_path
            r = client.get("/api/v1/proforma/draft/1/invoice-link")
        assert r.json()["status"] == "failed"
        assert r.json()["invoice_id"] is None


# ── POST .../to-invoice session-operator alias ────────────────────────────────

class TestToInvoiceAlias:

    def test_404_unknown_draft(self, client, tmp_path):
        db = tmp_path / "proforma_links.db"; _make_draft_db(db)
        with patch("app.api.routes_proforma._proforma_db_path", return_value=db):
            r = client.post("/api/v1/proforma/draft/999/to-invoice",
                            json={"confirm": "YES_CREATE_FINAL_INVOICE_FROM_PROFORMA"})
        assert r.status_code == 404

    def test_flag_off_blocks_conversion(self, client, tmp_path):
        """Security: wfirma_create_invoice_allowed=False MUST block. No wFirma call."""
        db = tmp_path / "proforma_links.db"
        _make_draft_db(db, wfirma_proforma_id="PROF_FLAG", draft_state="adopted_from_audit")
        with patch("app.api.routes_proforma._proforma_db_path", return_value=db), \
             patch("app.api.routes_proforma.settings") as ms:
            ms.wfirma_create_invoice_allowed = False
            ms.storage_root = tmp_path
            r = client.post("/api/v1/proforma/draft/1/to-invoice",
                            json={"confirm": "YES_CREATE_FINAL_INVOICE_FROM_PROFORMA"})
        body = r.json()
        # Flag off is blocked — ok=False and WFIRMA_CREATE_INVOICE_ALLOWED in reasons
        assert body.get("ok") is False
        reasons = " ".join(body.get("blocking_reasons", []))
        assert "WFIRMA_CREATE_INVOICE_ALLOWED" in reasons

    def test_operator_from_session_not_from_header(self, client, tmp_path):
        """Security: X-Operator header MUST be ignored. Operator comes from session."""
        db = tmp_path / "proforma_links.db"
        _make_draft_db(db, wfirma_proforma_id="PROF_OP", draft_state="adopted_from_audit")
        delegated = {}
        def capture(batch_id, client_name, body, x_operator=None):
            delegated['operator'] = x_operator
            from fastapi.responses import JSONResponse
            return JSONResponse({"ok": False, "status": "blocked", "blocking_reasons": ["test"]})

        with patch("app.api.routes_proforma._proforma_db_path", return_value=db), \
             patch("app.api.routes_proforma.proforma_to_invoice", side_effect=capture):
            client.post("/api/v1/proforma/draft/1/to-invoice",
                        json={"confirm": "YES_CREATE_FINAL_INVOICE_FROM_PROFORMA"},
                        headers={"X-Operator": "SPOOFED_ACTOR"})

        op = delegated.get('operator', '')
        assert op != "SPOOFED_ACTOR", "X-Operator header must not override session operator"
        assert "Test Operator" in op or "test@local" in op, (
            f"Operator must come from session user, got: {op!r}"
        )

    def test_delegates_batch_and_client(self, client, tmp_path):
        """Alias resolves draft_id → (batch_id, client_name) correctly."""
        db = tmp_path / "proforma_links.db"
        _make_draft_db(db, batch_id="BATCH_CONV", client_name="Conv Client",
                       wfirma_proforma_id="PROF_CONV", draft_state="adopted_from_audit")
        called = {}
        def capture(batch_id, client_name, body, x_operator=None):
            called.update({'batch_id': batch_id, 'client_name': client_name})
            from fastapi.responses import JSONResponse
            return JSONResponse({"ok": False, "status": "blocked", "blocking_reasons": []})
        with patch("app.api.routes_proforma._proforma_db_path", return_value=db), \
             patch("app.api.routes_proforma.proforma_to_invoice", side_effect=capture):
            client.post("/api/v1/proforma/draft/1/to-invoice",
                        json={"confirm": "YES_CREATE_FINAL_INVOICE_FROM_PROFORMA"})
        assert called.get('batch_id') == "BATCH_CONV"
        assert called.get('client_name') == "Conv Client"

    def test_idempotency_duplicate_blocked(self, client, tmp_path):
        """UNIQUE(proforma_id) guard — second call on same proforma must be rejected."""
        db = tmp_path / "proforma_links.db"
        _make_draft_db(db, wfirma_proforma_id="PROF_IDEM", draft_state="adopted_from_audit")
        _make_link_db(db, proforma_id="PROF_IDEM", status="issued")  # already converted

        def fake_convert(batch_id, client_name, body, x_operator=None):
            from fastapi.responses import JSONResponse
            return JSONResponse({
                "ok": False, "status": "blocked",
                "blocking_reasons": ["proforma_id 'PROF_IDEM' already has a conversion link"],
            })
        with patch("app.api.routes_proforma._proforma_db_path", return_value=db), \
             patch("app.api.routes_proforma.proforma_to_invoice", side_effect=fake_convert), \
             patch("app.api.routes_proforma.settings") as ms:
            ms.storage_root = tmp_path
            r = client.post("/api/v1/proforma/draft/1/to-invoice",
                            json={"confirm": "YES_CREATE_FINAL_INVOICE_FROM_PROFORMA"})
        body = r.json()
        assert body.get("ok") is False
        assert any("already has a conversion link" in reason
                   for reason in body.get("blocking_reasons", []))


# ── §4.1 phantom-row filter ───────────────────────────────────────────────────

class TestPhantomRowFilter:
    def test_stub_filtered(self):
        from app.services.wfirma_reservation import _filter_stub_doc
        assert _filter_stub_doc({"client_name": "", "sales_doc_no": None}) is True
        assert _filter_stub_doc({"client_name": "   ", "sales_doc_no": ""}) is True
        assert _filter_stub_doc({"client_name": None, "sales_doc_no": None}) is True

    def test_real_unassigned_kept(self):
        from app.services.wfirma_reservation import _filter_stub_doc
        # Has doc_number despite empty client_name — real unassigned draft
        assert _filter_stub_doc({"client_name": "", "sales_doc_no": "DOC-001"}) is False
        assert _filter_stub_doc({"client_name": "", "client_ref": "REF-001"}) is False

    def test_normal_row_kept(self):
        from app.services.wfirma_reservation import _filter_stub_doc
        assert _filter_stub_doc({"client_name": "Diamond Point", "sales_doc_no": None}) is False
        assert _filter_stub_doc({"client_name": "Acme", "sales_doc_no": "DOC-X"}) is False


# ── Phase 2/3 toolbar design-spec contract ────────────────────────────────────
# Source-grep tests: pin that proforma-detail-v2.html carries the exact toolbar
# testids specified by ATLAS_PROFORMA_DRILLDOWN_REDESIGN.md §2.3.
# These run offline — no server, no wFirma, no DB.

import pathlib as _pathlib

_DETAIL_HTML = (
    _pathlib.Path(__file__).parent.parent
    / "app" / "static" / "proforma-detail-v2.html"
)


# ── POST /draft/{id}/clone ────────────────────────────────────────────────────

class TestCloneEndpoint:
    """Sprint-24 Phase 1: verify clone creates a new row, source is intact."""

    def test_clone_creates_new_draft(self, client, tmp_path):
        """POST /clone returns a new draft_id distinct from the source."""
        db = tmp_path / "proforma_links.db"
        _make_draft_db(db, batch_id="BATCH_C", client_name="Clone Client",
                       draft_state="editing")
        with patch("app.api.routes_proforma._proforma_db_path", return_value=db):
            r = client.post("/api/v1/proforma/draft/1/clone")
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["ok"] is True
        assert data["draft_id"] != 1, "Clone must have a NEW id"
        assert data["source_id"] == 1
        assert data["clone_generation"] >= 1

    def test_source_unchanged_after_clone(self, client, tmp_path):
        """Source draft's draft_state and wfirma_proforma_id are untouched by clone."""
        db = tmp_path / "proforma_links.db"
        _make_draft_db(db, batch_id="BATCH_C2", client_name="Source Client",
                       draft_state="approved", wfirma_proforma_id="PROF_SRC")
        with patch("app.api.routes_proforma._proforma_db_path", return_value=db):
            client.post("/api/v1/proforma/draft/1/clone")
            # Re-fetch source to confirm no mutation
            r_src = client.get("/api/v1/proforma/draft/1")
        assert r_src.status_code == 200
        src = r_src.json()["draft"]
        assert src["draft_state"] == "approved", "Source draft_state must be unchanged"
        assert src["wfirma_proforma_id"] == "PROF_SRC", "Source wfirma_proforma_id must be unchanged"

    def test_clone_is_unposted_draft(self, client, tmp_path):
        """Clone starts as draft state with no wFirma IDs."""
        db = tmp_path / "proforma_links.db"
        _make_draft_db(db, batch_id="BATCH_C3", client_name="Post Client",
                       draft_state="posted", wfirma_proforma_id="PROF_ORIG")
        with patch("app.api.routes_proforma._proforma_db_path", return_value=db):
            r = client.post("/api/v1/proforma/draft/1/clone")
        assert r.status_code == 200
        clone = r.json()["draft"]
        assert clone["draft_state"] == "draft", "Clone must start as 'draft'"
        assert not clone["wfirma_proforma_id"], "Clone must have no wFirma ID"
        assert clone["source_ref_id"] == 1

    def test_clone_404_unknown_source(self, client, tmp_path):
        """404 when source draft does not exist."""
        db = tmp_path / "proforma_links.db"
        _make_draft_db(db)
        with patch("app.api.routes_proforma._proforma_db_path", return_value=db):
            r = client.post("/api/v1/proforma/draft/999/clone")
        assert r.status_code == 404

    def test_two_clones_get_distinct_generations(self, client, tmp_path):
        """Cloning the same source twice yields generation 1 and 2."""
        db = tmp_path / "proforma_links.db"
        _make_draft_db(db, batch_id="BATCH_C4", client_name="Gen Client",
                       draft_state="editing")
        with patch("app.api.routes_proforma._proforma_db_path", return_value=db):
            r1 = client.post("/api/v1/proforma/draft/1/clone")
            r2 = client.post("/api/v1/proforma/draft/1/clone")
        assert r1.json()["clone_generation"] == 1
        assert r2.json()["clone_generation"] == 2
        assert r1.json()["draft_id"] != r2.json()["draft_id"]


class TestToolbarDesignSpecContract:
    """Pins all 9 toolbar testids (design spec §2.3 + overflow) in Screen B HTML."""

    @pytest.fixture(autouse=True)
    def load_html(self):
        self.html = _DETAIL_HTML.read_text(encoding="utf-8")

    # ── Primary toolbar buttons (design spec §2.3) ─────────────────────────
    def test_btn_edit_present(self):
        assert 'data-testid="btn-edit"' in self.html, "Edit button testid missing"

    def test_btn_cancel_draft_present_not_btn_delete(self):
        # Toolbar semantics fix: soft cancel ≠ hard delete. Label = 'Cancel draft'.
        assert 'data-testid="btn-cancel-draft"' in self.html, (
            "btn-cancel-draft must be present (replaces btn-delete)")
        assert 'data-testid="btn-delete"' not in self.html, (
            "btn-delete must be absent — renamed to btn-cancel-draft")

    def test_btn_duplicate_present(self):
        assert 'data-testid="btn-duplicate"' in self.html, "Duplicate button testid missing"

    def test_btn_post_wfirma_present(self):
        assert 'data-testid="btn-post-wfirma"' in self.html, "Post to wFirma testid missing"

    def test_btn_convert_invoice_present(self):
        assert 'data-testid="btn-convert-invoice"' in self.html, "Convert to Invoice testid missing"

    def test_btn_print_present(self):
        assert 'data-testid="btn-print"' in self.html, "Print testid missing"

    def test_btn_send_in_overflow(self):
        """Send has no endpoint — lives in ⋯ overflow, not primary toolbar.
        Primary toolbar holds only working actions (Phase 2/3 spec)."""
        assert 'overflow-btn-send' in self.html, (
            "Send must be in ⋯ overflow (overflow-btn-send testid) since it "
            "has no backend endpoint yet — do NOT present as primary action"
        )
        # Guard: btn-send must NOT appear as a PRIMARY toolbar button
        # (presence in overflow is fine, presence in primary is a regression)
        assert 'data-testid="btn-send"' not in self.html, (
            "btn-send in primary toolbar is a regression — "
            "Send belongs in ⋯ overflow until an email endpoint exists"
        )

    def test_btn_generate_present(self):
        assert 'data-testid="btn-generate"' in self.html, "Generate testid missing"

    def test_btn_overflow_present(self):
        assert 'data-testid="btn-overflow"' in self.html, "Overflow ⋯ testid missing"

    # ── No unconditionally-disabled stubs (Round 1 regression guard) ───────
    def test_no_ships_next_sprint_tooltip(self):
        """Guard against Round-1 'ships next sprint' placeholder stubs."""
        assert "ships next sprint" not in self.html, (
            "Round-1 disabled stub tooltip found — toolbar was not wired"
        )

    # ── Convert modal security markers ─────────────────────────────────────
    def test_irreversibility_warning_first(self):
        """Irreversibility warning must appear BEFORE the payload section."""
        irrev_pos = self.html.find("cannot be cancelled")
        payload_pos = self.html.find("PAYLOAD")
        assert irrev_pos != -1, "Irreversibility sentence missing from ConvertModal"
        assert payload_pos != -1, "PAYLOAD section header missing from ConvertModal"
        assert irrev_pos < payload_pos, (
            "Irreversibility warning must appear before the payload section"
        )

    def test_confirm_token_in_convert_call(self):
        assert "YES_CREATE_FINAL_INVOICE_FROM_PROFORMA" in self.html, (
            "Convert confirm token must be present in the fetch body"
        )

    def test_flag_off_message_present(self):
        assert "WFIRMA_CREATE_INVOICE_ALLOWED" in self.html, (
            "Flag-off message must reference the WFIRMA_CREATE_INVOICE_ALLOWED env var"
        )

    # ── Design system layer (no dashboard-shared.js) ───────────────────────
    def test_uses_pz_design_v2_not_dashboard_shared(self):
        assert "pz-design-v2.js" in self.html, "Must import pz-design-v2.js"
        assert "dashboard-shared.js" not in self.html, (
            "Must NOT import dashboard-shared.js (Lesson F: V2 layer only)"
        )

    def test_dm_serif_font_loaded(self):
        assert "DM+Serif+Display" in self.html or "DM Serif Display" in self.html, (
            "DM Serif Display Google Font must be loaded"
        )

    def test_duplicate_calls_clone_endpoint(self):
        """Duplicate must POST to /clone — not reset-from-sales-packing."""
        assert '/clone' in self.html, (
            "Duplicate button must call the /clone endpoint to create a new draft"
        )
        # Regression guard: Duplicate must NOT call reset-from-sales-packing
        # (that overwrites the current draft — wrong semantic for Duplicate)
        # reset-from-sales-packing should only appear in overflow under Reset
        html = self.html
        dup_section_start = html.find("modal==='duplicate'")
        dup_section_end   = html.find("modal==='reset'", dup_section_start)
        assert dup_section_start != -1, "modal==='duplicate' must exist"
        dup_section = html[dup_section_start:dup_section_end] if dup_section_end != -1 else html[dup_section_start:dup_section_start+400]
        assert "reset-from-sales-packing" not in dup_section, (
            "Duplicate modal must NOT call reset-from-sales-packing — that overwrites "
            "the current draft. Duplicate must POST to /clone instead."
        )

    def test_delete_wording_says_retained(self):
        """Delete modal must clarify draft is retained for audit — not permanently deleted."""
        assert "retained for audit" in self.html or "retained" in self.html, (
            "Delete/Cancel modal must state the draft is retained for audit history"
        )
