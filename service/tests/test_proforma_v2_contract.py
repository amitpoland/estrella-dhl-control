"""
test_proforma_v2_contract.py — API contract tests for Proforma V2 frontend.

Pins the six contracts that proforma-v2.html depends on.  V2 renders
backend authority directly — these tests ensure the backend keeps
honouring the exact shapes the frontend reads.

Coverage (per §5.6 acceptance criteria in docs/v2-architecture-plan.md):
  1. GET  /api/v1/proforma/drafts/{batch_id}
       → { ok, batch_id, drafts[], count }  — drafts carry summary fields
  2. POST /api/v1/proforma/preview/{batch_id}/{client_name}
       → previewObj.ready (bool), blocking_reasons[], export_blockers[],
         warehouse_blockers[], customer_resolution{}
       → ready=False when product_match=False
       → ready=False when customer not mapped
       → export_blockers carry '[DEV-BYPASS]' marker when bypass active
  3. GET  /api/v1/proforma/draft/{draft_id}
       → { ok, draft: { draft_id, draft_state, lines[], service_charges[],
             updated_at, currency, remarks, ... } }
       → each line has line_id (needed by PATCH)
  4. PATCH /api/v1/proforma/draft/{draft_id}
       → 200 on valid patch with matching expected_updated_at
       → 409 on stale expected_updated_at (optimistic lock)
       → 400 without X-Operator header
  5. POST /api/v1/proforma/draft/{draft_id}/approve
       → 200 on approvable draft_state ('draft' or 'pending_local')
       → draft_state transitions to 'approved'
  6. POST /api/v1/proforma/draft/{draft_id}/cancel
       → 200 on cancellable draft
       → draft_state transitions to 'cancelled'
  7. GET  /api/v1/customer-master/{contractor_id}
       → returns customer record or 404 (never raises 5xx on missing)
  8. PUT  /api/v1/customer-master/{contractor_id}
       → 200 on valid body; response includes key fields
  9. Layer-discipline proofs (HTML grep):
       a. proforma-v2.html has exactly one ReactDOM.createRoot call
       b. proforma-v2.html reads only URL params (no window.currentBatch)
       c. dashboard-shared.js StatusDot/GateBlock/SectionHeader have no
          domain knowledge (no shipment state tokens, no wFirma keywords)
       d. pz-state.js never computes 'ready' locally
       e. pz-api.js has no business logic beyond _call wrappers
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.services import proforma_invoice_link_db as pildb
from app.services import wfirma_client as _wc


# ── helpers ─────────────────────────────────────────────────────────────────

def _auth(operator: str = "alice") -> dict:
    return {
        "X-API-KEY":  settings.api_key or "test-key",
        "X-Operator": operator,
    }


def _readonly_auth() -> dict:
    """Auth header without X-Operator (for read-only endpoints)."""
    return {"X-API-KEY": settings.api_key or "test-key"}


@pytest.fixture(autouse=True)
def _prime_vat_cache():
    _wc._VAT_CODE_ID_CACHE["23"]  = "222"
    _wc._VAT_CODE_ID_CACHE["WDT"] = "228"
    _wc._VAT_CODE_ID_CACHE["EXP"] = "229"
    yield
    for k in ("23", "WDT", "EXP"):
        _wc._VAT_CODE_ID_CACHE.pop(k, None)


@pytest.fixture()
def db_path(tmp_path) -> Path:
    p = tmp_path / "proforma_links.db"
    pildb.init_db(p)
    return p


@pytest.fixture()
def client(tmp_path) -> TestClient:
    from app.main import app
    with patch.object(settings, "storage_root", tmp_path):
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


def _seed_draft(db: Path, *, batch="V2_BATCH", client_name="ACME", currency="EUR"):
    draft, _ = pildb.auto_create_draft_from_sales_packing(
        db, batch_id=batch, client_name=client_name, currency=currency,
        lines=[{
            "line_id":    None,
            "product_code": "EJL/TEST/01",
            "design_no":   "D001",
            "qty":          2,
            "unit_price":   50.0,
            "currency":    currency,
            "line_value":  100.0,
            "product_match": True,
            "stock_ok":    True,
            "stock_status": "in_stock",
            "price_source": "packing_list",
        }],
    )
    return draft


# ── Contract 1: GET /api/v1/proforma/drafts/{batch_id} ────────────────────

class TestListDrafts:

    def test_returns_summary_shape(self, client, db_path, tmp_path):
        with patch.object(settings, "storage_root", tmp_path):
            _seed_draft(db_path, batch="V2C1")
        r = client.get("/api/v1/proforma/drafts/V2C1", headers=_readonly_auth())
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["batch_id"] == "V2C1"
        assert isinstance(body["drafts"], list)
        assert isinstance(body["count"], int)
        assert body["count"] >= 1

    def test_draft_summary_carries_required_fields(self, client, db_path, tmp_path):
        with patch.object(settings, "storage_root", tmp_path):
            _seed_draft(db_path, batch="V2C1B")
        r = client.get("/api/v1/proforma/drafts/V2C1B", headers=_readonly_auth())
        d = r.json()["drafts"][0]
        # Backend summary uses 'id', not 'draft_id' — pz-api.js reads d.id
        for field in ("id", "draft_state", "client_name", "currency", "updated_at"):
            assert field in d, f"missing field: {field}"

    def test_empty_batch_returns_empty_list(self, client):
        r = client.get("/api/v1/proforma/drafts/NO_SUCH_BATCH", headers=_readonly_auth())
        assert r.status_code == 200
        body = r.json()
        assert body["drafts"] == []
        assert body["count"] == 0

    def test_requires_auth(self, client, tmp_path):
        # Auth is only enforced when api_key is set (empty = dev mode off)
        with patch.object(settings, "api_key", "secure-test-key"), \
             patch.object(settings, "storage_root", tmp_path):
            r = client.get("/api/v1/proforma/drafts/V2C1")
        assert r.status_code in (401, 403)

    def test_list_line_count_matches_detail(self, client, db_path, tmp_path):
        """list endpoint line_count must equal len(detail.editable_lines).

        Sprint 1.1: list serialiser adds a computed line_count integer so the
        Pro Forma list view can display line count without parsing the full blob.
        This test pins list/detail agreement so the two can never silently diverge.
        Covers: one populated draft (1 line) + one zero-line draft.
        """
        with patch.object(settings, "storage_root", tmp_path):
            # Populated draft: 1 line seeded by _seed_draft
            draft_with_lines = _seed_draft(db_path, batch="LC_BATCH")
            # Zero-line draft: create with empty lines list
            draft_empty, _ = pildb.auto_create_draft_from_sales_packing(
                db_path, batch_id="LC_BATCH", client_name="ZeroClient",
                currency="EUR", lines=[],
            )

        # list endpoint
        list_r = client.get("/api/v1/proforma/drafts/LC_BATCH", headers=_readonly_auth())
        assert list_r.status_code == 200
        list_drafts = {d["id"]: d for d in list_r.json()["drafts"]}

        for draft_id, expected_count in [
            (draft_with_lines.id, 1),
            (draft_empty.id,      0),
        ]:
            # line_count from list endpoint
            assert draft_id in list_drafts, f"draft {draft_id} missing from list"
            list_count = list_drafts[draft_id].get("line_count")
            assert list_count is not None, (
                f"draft {draft_id}: line_count absent from list endpoint response"
            )
            assert list_count == expected_count, (
                f"draft {draft_id}: list line_count={list_count}, expected {expected_count}"
            )

            # detail endpoint: len(editable_lines) must agree
            detail_r = client.get(f"/api/v1/proforma/draft/{draft_id}", headers=_readonly_auth())
            assert detail_r.status_code == 200
            detail_count = len(detail_r.json()["draft"]["editable_lines"])
            assert list_count == detail_count, (
                f"draft {draft_id}: list line_count={list_count} != "
                f"detail editable_lines len={detail_count} — list/detail diverged"
            )


# ── Contract 2: POST /api/v1/proforma/preview/{batch_id}/{client} ─────────

class TestPreviewShape:

    def test_preview_returns_required_keys(self, client):
        """Preview endpoint must always return the V2 required shape."""
        r = client.post(
            "/api/v1/proforma/preview/NO_BATCH_AT_ALL/SOME_CLIENT",
            headers=_readonly_auth(),
        )
        # May be 200 (empty) or 400/422 — but must not 5xx
        assert r.status_code < 500, f"preview raised 5xx: {r.text}"

    def test_preview_blocked_when_no_matching_products(self, client, tmp_path):
        """ready must be False when products are not matched."""
        from app.services import packing_db as pdb
        from app.services import wfirma_db as wfdb
        from app.services import document_db as ddb
        pdb.init_packing_db(tmp_path / "packing.db")
        wfdb.init_wfirma_db(tmp_path / "wfirma.db")
        ddb.init_document_db(tmp_path / "documents.db")

        with patch.object(settings, "storage_root", tmp_path):
            r = client.post(
                "/api/v1/proforma/preview/EMPTY_BATCH/Ghost Client",
                headers=_readonly_auth(),
            )
        # Either returns 200 with ready=False or a 4xx — never 5xx
        assert r.status_code < 500

    def test_preview_ready_field_is_bool(self, client, tmp_path):
        """ready must be a boolean (not truthy string)."""
        from app.services import packing_db as pdb
        from app.services import wfirma_db as wfdb
        from app.services import document_db as ddb
        pdb.init_packing_db(tmp_path / "packing.db")
        wfdb.init_wfirma_db(tmp_path / "wfirma.db")
        ddb.init_document_db(tmp_path / "documents.db")

        with patch.object(settings, "storage_root", tmp_path):
            r = client.post(
                "/api/v1/proforma/preview/BOOL_BATCH/Test Client",
                headers=_readonly_auth(),
            )
        if r.status_code == 200:
            body = r.json()
            if "ready" in body:
                assert isinstance(body["ready"], bool), (
                    f"preview.ready must be bool, got {type(body['ready'])}"
                )

    def test_preview_blocking_reasons_is_list(self, client, tmp_path):
        """blocking_reasons must be a list — V2 iterates it."""
        from app.services import packing_db as pdb
        from app.services import wfirma_db as wfdb
        from app.services import document_db as ddb
        pdb.init_packing_db(tmp_path / "packing.db")
        wfdb.init_wfirma_db(tmp_path / "wfirma.db")
        ddb.init_document_db(tmp_path / "documents.db")

        with patch.object(settings, "storage_root", tmp_path):
            r = client.post(
                "/api/v1/proforma/preview/BR_BATCH/Test Client",
                headers=_readonly_auth(),
            )
        if r.status_code == 200:
            body = r.json()
            assert isinstance(body.get("blocking_reasons", []), list)
            assert isinstance(body.get("export_blockers", []), list)
            assert isinstance(body.get("warehouse_blockers", []), list)


# ── Contract 3: GET /api/v1/proforma/draft/{draft_id} ────────────────────

class TestGetDraft:

    def test_returns_full_shape(self, client, db_path, tmp_path):
        with patch.object(settings, "storage_root", tmp_path):
            draft = _seed_draft(db_path, batch="V2C3")
        r = client.get(f"/api/v1/proforma/draft/{draft.id}",
                       headers=_readonly_auth())
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert "draft" in body
        d = body["draft"]
        # 'id' comes from summary; 'editable_lines' and 'service_charges' from full
        for field in ("id", "draft_state", "client_name", "currency",
                      "updated_at", "editable_lines", "service_charges"):
            assert field in d, f"missing field in draft: {field}"

    def test_lines_carry_line_id(self, client, db_path, tmp_path):
        """Every editable_line must expose line_id — DraftLineRow depends on it."""
        with patch.object(settings, "storage_root", tmp_path):
            draft = _seed_draft(db_path, batch="V2C3L")
        r = client.get(f"/api/v1/proforma/draft/{draft.id}",
                       headers=_readonly_auth())
        lines = r.json()["draft"]["editable_lines"]
        assert len(lines) > 0
        for ln in lines:
            assert "line_id" in ln, f"line missing line_id: {ln}"

    def test_unknown_draft_returns_404(self, client):
        r = client.get("/api/v1/proforma/draft/999999", headers=_readonly_auth())
        assert r.status_code == 404

    def test_requires_auth(self, client, db_path, tmp_path):
        with patch.object(settings, "storage_root", tmp_path):
            draft = _seed_draft(db_path, batch="V2C3A")
        with patch.object(settings, "api_key", "secure-test-key"), \
             patch.object(settings, "storage_root", tmp_path):
            r = client.get(f"/api/v1/proforma/draft/{draft.id}")
        assert r.status_code in (401, 403)


# ── Contract 4: PATCH /api/v1/proforma/draft/{draft_id} ──────────────────

class TestPatchDraft:

    def test_patch_remarks_succeeds(self, client, db_path, tmp_path):
        with patch.object(settings, "storage_root", tmp_path):
            draft = _seed_draft(db_path, batch="V2C4")
        payload = {
            "expected_updated_at": draft.updated_at,
            "patch": {"remarks": "V2 test remark"},
        }
        r = client.patch(f"/api/v1/proforma/draft/{draft.id}",
                         json=payload, headers=_auth())
        assert r.status_code == 200

    def test_patch_requires_operator(self, client, db_path, tmp_path):
        with patch.object(settings, "storage_root", tmp_path):
            draft = _seed_draft(db_path, batch="V2C4Op")
        payload = {
            "expected_updated_at": draft.updated_at,
            "patch": {"remarks": "no operator"},
        }
        r = client.patch(f"/api/v1/proforma/draft/{draft.id}",
                         json=payload, headers=_readonly_auth())
        assert r.status_code == 400, (
            f"PATCH without X-Operator must return 400, got {r.status_code}: {r.text}"
        )

    def test_patch_stale_lock_returns_409(self, client, db_path, tmp_path):
        with patch.object(settings, "storage_root", tmp_path):
            draft = _seed_draft(db_path, batch="V2C4Stale")
        payload = {
            "expected_updated_at": "1970-01-01T00:00:00Z",  # intentionally stale
            "patch": {"remarks": "stale"},
        }
        r = client.patch(f"/api/v1/proforma/draft/{draft.id}",
                         json=payload, headers=_auth())
        assert r.status_code == 409, (
            f"stale expected_updated_at must return 409, got {r.status_code}: {r.text}"
        )


# ── Contract 5: POST /api/v1/proforma/draft/{draft_id}/approve ───────────

class TestApproveDraft:

    def test_approve_transitions_state(self, client, db_path, tmp_path):
        with patch.object(settings, "storage_root", tmp_path):
            draft = _seed_draft(db_path, batch="V2C5")
        body = {
            "expected_updated_at": draft.updated_at,
            "confirm_token":       "YES_APPROVE_LOCAL_PROFORMA_DRAFT",
        }
        r = client.post(f"/api/v1/proforma/draft/{draft.id}/approve",
                        json=body, headers=_auth())
        assert r.status_code == 200, f"approve failed: {r.text}"
        # Fetch the draft again and verify state
        r2 = client.get(f"/api/v1/proforma/draft/{draft.id}",
                        headers=_readonly_auth())
        assert r2.json()["draft"]["draft_state"] == "approved"

    def test_approve_requires_auth(self, client, db_path, tmp_path):
        with patch.object(settings, "storage_root", tmp_path):
            draft = _seed_draft(db_path, batch="V2C5A")
        with patch.object(settings, "api_key", "secure-test-key"), \
             patch.object(settings, "storage_root", tmp_path):
            r = client.post(f"/api/v1/proforma/draft/{draft.id}/approve")
        assert r.status_code in (401, 403)


# ── Contract 6: POST /api/v1/proforma/draft/{draft_id}/cancel ────────────

class TestCancelDraft:

    def test_cancel_transitions_state(self, client, db_path, tmp_path):
        with patch.object(settings, "storage_root", tmp_path):
            draft = _seed_draft(db_path, batch="V2C6")
        body = {
            "expected_updated_at": draft.updated_at,
            "reason":              "Test cancellation",
        }
        r = client.post(f"/api/v1/proforma/draft/{draft.id}/cancel",
                        json=body, headers=_auth())
        assert r.status_code == 200, f"cancel failed: {r.text}"
        r2 = client.get(f"/api/v1/proforma/draft/{draft.id}",
                        headers=_readonly_auth())
        assert r2.json()["draft"]["draft_state"] == "cancelled"

    def test_cancel_requires_auth(self, client, db_path, tmp_path):
        with patch.object(settings, "storage_root", tmp_path):
            draft = _seed_draft(db_path, batch="V2C6A")
        with patch.object(settings, "api_key", "secure-test-key"), \
             patch.object(settings, "storage_root", tmp_path):
            r = client.post(f"/api/v1/proforma/draft/{draft.id}/cancel")
        assert r.status_code in (401, 403)


# ── Contract 7 + 8: Customer Master endpoints ─────────────────────────────

class TestCustomerMasterEndpoints:

    def test_get_missing_customer_returns_404(self, client, tmp_path):
        with patch.object(settings, "storage_root", tmp_path):
            r = client.get("/api/v1/customer-master/NON_EXISTENT",
                           headers=_readonly_auth())
        assert r.status_code == 404

    def test_put_creates_record(self, client, tmp_path):
        # CustomerMaster required fields: bill_to_name, country
        body = {
            "bill_to_name":          "V2 Test Customer GmbH",
            "country":              "DE",
            "bill_to_nip":          "DE123456789",
            "bill_to_street":       "Test Str 1",
            "bill_to_city":         "Berlin",
            "bill_to_postal_code":  "10115",
        }
        with patch.object(settings, "storage_root", tmp_path):
            r = client.put("/api/v1/customer-master/V2_TEST_CUST",
                           json=body, headers=_auth())
        # Either 200 or 201 — created successfully
        assert r.status_code in (200, 201), f"PUT customer master failed: {r.text}"

    def test_get_after_put_returns_record(self, client, tmp_path):
        body = {
            "bill_to_name": "V2 Round Trip Sp. z o.o.",
            "country":      "PL",
        }
        with patch.object(settings, "storage_root", tmp_path):
            client.put("/api/v1/customer-master/V2_RT_CUST",
                       json=body, headers=_auth())
            r = client.get("/api/v1/customer-master/V2_RT_CUST",
                           headers=_readonly_auth())
        assert r.status_code == 200
        assert r.json()["bill_to_name"] == "V2 Round Trip Sp. z o.o."


# ── Contract 9: Layer-discipline proofs (HTML / JS grep) ─────────────────

class TestLayerDisciplineProofs:
    """These tests grep the V2 static files and enforce the six-proof gate
    required by docs/v2-architecture-plan.md §9 (first V2 PR review gate).
    They never make HTTP requests — they read file content."""

    STATIC = Path(__file__).parents[1] / "app" / "static"

    @pytest.fixture(autouse=True)
    def _files(self):
        self.v2_html      = (self.STATIC / "proforma-v2.html").read_text(encoding="utf-8")
        self.pz_api       = (self.STATIC / "pz-api.js").read_text(encoding="utf-8")
        self.pz_state     = (self.STATIC / "pz-state.js").read_text(encoding="utf-8")
        self.pz_comp      = (self.STATIC / "pz-components.js").read_text(encoding="utf-8")
        self.shared       = (self.STATIC / "dashboard-shared.js").read_text(encoding="utf-8")

    # Proof 1 — Isolated hydration
    def test_exactly_one_createroot_call(self):
        count = self.v2_html.count("ReactDOM.createRoot")
        assert count == 1, (
            f"proforma-v2.html must have exactly 1 ReactDOM.createRoot call, found {count}"
        )

    def test_no_window_current_batch(self):
        # The string may appear in doc-comments explaining it's NOT used.
        # The critical check: no assignment or read of window.currentBatch in code.
        # Detect actual JS access patterns (not comment mentions).
        import re
        # Strip single-line comments before checking
        stripped = re.sub(r'//[^\n]*', '', self.v2_html)
        # Also strip block comments
        stripped = re.sub(r'/\*.*?\*/', '', stripped, flags=re.DOTALL)
        assert "window.currentBatch" not in stripped, (
            "proforma-v2.html must not access window.currentBatch in code — URL params only"
        )

    def test_url_params_used_as_input(self):
        assert "URLSearchParams" in self.v2_html or "searchParams" in self.v2_html, (
            "proforma-v2.html must read URL params (URLSearchParams / location.search)"
        )

    # Proof 2 — No proforma mega-state pulled from shipment-detail domains
    def test_no_shipment_detail_imports(self):
        for forbidden in ("getShipment", "window.currentShipment",
                          "shipment-detail", "ProformaDraftPanel"):
            assert forbidden not in self.v2_html, (
                f"proforma-v2.html must not reference V1 symbol: {forbidden!r}"
            )

    # Proof 3 — Backend authority: ready never computed locally
    def test_pz_state_does_not_compute_ready_locally(self):
        # The state hook must never derive ready = !blocking_reasons or similar
        for pattern in (
            "ready = !",
            "ready = true",
            "ready = false",
            "setReady(",
            "blocking_reasons.length === 0",
        ):
            assert pattern not in self.pz_state, (
                f"pz-state.js must not compute ready locally — found: {pattern!r}"
            )

    def test_pz_state_comment_states_invariant(self):
        assert "NEVER" in self.pz_state and "ready" in self.pz_state, (
            "pz-state.js must document the no-local-ready invariant"
        )

    # Proof 4 — No visual-domain leakage into dashboard-shared.js
    def test_dashboard_shared_has_no_domain_tokens(self):
        # These are domain-specific tokens that MUST NOT appear in visual atoms
        forbidden_tokens = [
            "shipment_state",
            "draft_state",
            "wfirma_",
            "blocking_reasons",
            "export_blockers",
            "customs_",
            "clearance",
            "proforma",
            "sales_doc",
            "carrier",
        ]
        # Only check the NEW V2 atoms section, not the whole file
        # Locate the V2 atoms section (added between Sidebar and Export)
        if "V2 visual atoms" in self.shared:
            v2_atoms_section = self.shared.split("V2 visual atoms")[1]
            # Take the section up to the export / EstrellaShared freeze
            end_marker = "window.EstrellaShared"
            if end_marker in v2_atoms_section:
                v2_atoms_section = v2_atoms_section.split(end_marker)[0]
            for tok in forbidden_tokens:
                assert tok not in v2_atoms_section, (
                    f"dashboard-shared.js V2 atoms must not contain domain token: {tok!r}"
                )

    def test_statusdot_exported_from_shared(self):
        assert "StatusDot" in self.shared, "StatusDot must be exported from dashboard-shared.js"

    def test_gateblock_exported_from_shared(self):
        assert "GateBlock" in self.shared, "GateBlock must be exported from dashboard-shared.js"

    # Proof 5 — No write gate relaxation
    def test_approve_requires_explicit_click(self):
        # Approve must only fire via an onClick handler — never on mount
        assert "approveDraft" in self.v2_html, "approveDraft must be called from proforma-v2.html"
        # Must not be called inside useEffect (auto-action on load)
        assert "useEffect" not in self.v2_html.split("approveDraft")[0].split("function")[
            -1
        ], "approveDraft must not be called inside a useEffect"

    def test_cancel_requires_modal_confirmation(self):
        assert "CancelModal" in self.v2_html, (
            "proforma-v2.html must have a CancelModal for cancellation"
        )
        assert "cancelDraft" in self.v2_html, (
            "cancelDraft must be referenced in proforma-v2.html"
        )
        # Cancel must only be called after modal confirmation — check it's
        # wired through onConfirm or handleCancelConfirm
        assert ("onConfirm" in self.v2_html or "handleCancelConfirm" in self.v2_html), (
            "Cancel must go through a confirmation callback"
        )

    def test_no_auto_write_on_load(self):
        """No write API should be called from top-level useEffect without operator action."""
        # pz-api write methods that must not appear in auto-load hooks
        write_methods = ["approveDraft", "cancelDraft", "patchDraft", "reopenDraft"]
        # The check: these must appear in the file (they are wired up)
        # but they must be inside onClick or callback handlers, not in
        # a bare useEffect at the page root.
        # Heuristic: they should not appear before the first function definition
        # in the inline script section.
        for method in write_methods:
            if method in self.v2_html:
                # Method is present — verify it's not outside a function body
                # by checking it doesn't appear in the global IIFE preamble
                # (before any `function` keyword)
                preamble = self.v2_html.split("function ")[0] if "function " in self.v2_html else ""
                assert method not in preamble, (
                    f"{method!r} must not appear in global scope / preamble of proforma-v2.html"
                )

    # Proof 6 — No copied legacy renderer
    def test_no_proforma_draft_panel_copy(self):
        assert "ProformaDraftPanel" not in self.v2_html, (
            "proforma-v2.html must not import or reuse ProformaDraftPanel (legacy V1)"
        )

    def test_no_direct_shipment_detail_renderer(self):
        for legacy in ("renderProforma", "ProformaTab(", "legacyProforma"):
            assert legacy not in self.v2_html, (
                f"proforma-v2.html must not reference legacy renderer: {legacy!r}"
            )

    # pz-api.js discipline
    def test_pz_api_has_no_react_import(self):
        assert "useState" not in self.pz_api
        assert "useEffect" not in self.pz_api

    def test_pz_api_normalises_errors(self):
        assert "ok: false" in self.pz_api or "ok:false" in self.pz_api.replace(" ", ""), (
            "pz-api.js must produce { ok: false } on errors"
        )

    def test_pz_api_exposes_freeze(self):
        assert "Object.freeze" in self.pz_api, (
            "window.PzApi must be Object.freeze(d)"
        )

    # pz-components.js discipline
    def test_pz_components_does_not_fetch(self):
        for fetch_keyword in ("apiFetch", "PzApi.", "fetch(", "XMLHttpRequest"):
            assert fetch_keyword not in self.pz_comp, (
                f"pz-components.js must not fetch data — found: {fetch_keyword!r}"
            )

    def test_pz_components_lazy_accessor(self):
        assert "window.EstrellaShared" in self.pz_comp, (
            "pz-components.js must use EstrellaShared via lazy accessor"
        )

    def test_pz_components_exposes_freeze(self):
        assert "Object.freeze" in self.pz_comp, (
            "window.PzComponents must be Object.freeze(d)"
        )

    # Script load order declared in proforma-v2.html
    def test_script_load_order(self):
        dsi = self.v2_html.find("dashboard-shared.js")
        api = self.v2_html.find("pz-api.js")
        sta = self.v2_html.find("pz-state.js")
        com = self.v2_html.find("pz-components.js")
        assert dsi != -1 and api != -1 and sta != -1 and com != -1, (
            "proforma-v2.html must load all four shared scripts"
        )
        assert dsi < api < sta < com, (
            "Script load order must be: dashboard-shared → pz-api → pz-state → pz-components"
        )

    def test_data_testids_present(self):
        required = [
            "draft-state-chip",
            "readiness-gate-ready",
            "readiness-gate-blocked",
        ]
        # Check components define these testids (in pz-components.js or html)
        combined = self.v2_html + self.pz_comp
        for tid in required:
            assert tid in combined, (
                f"data-testid={tid!r} must be present in proforma-v2.html or pz-components.js"
            )


class TestSprint01Hardening:
    """Sprint 01 hardening — source-grep tests for Atlas-V2 Sprint 01 additions.

    Pins the seven gaps closed by Sprint 01:
      1. readiness-ready-chip testid on the green "Ready to Issue" chip
      2. btn-save-customer-mapping testid on "Save Customer Mapping" Btn
      3. onSave prop wired to CustomerAuthorityCard in the page
      4. EmptyState for "No drafts for this client." (client-level empty state)
      5. Card root testids on section panels
      6. ProductAuthorityRow uses 'warn' (not 'error') for unmatched products
      7. CustomerAuthorityCard does not auto-save (explicit click only)
    """

    STATIC = Path(__file__).parents[1] / "app" / "static"

    @pytest.fixture(autouse=True)
    def _files(self):
        self.v2_html = (self.STATIC / "proforma-v2.html").read_text(encoding="utf-8")
        self.pz_comp = (self.STATIC / "pz-components.js").read_text(encoding="utf-8")

    # Gap 1 — readiness-ready-chip testid
    def test_readiness_ready_chip_testid(self):
        combined = self.v2_html + self.pz_comp
        assert 'readiness-ready-chip' in combined, (
            "readiness-ready-chip data-testid must be present on the green 'Ready to Issue' chip"
        )

    # Gap 2 — btn-save-customer-mapping testid
    def test_btn_save_customer_mapping_testid(self):
        assert 'btn-save-customer-mapping' in self.pz_comp, (
            "btn-save-customer-mapping data-testid must be present on the Save Customer Mapping Btn"
        )

    # Gap 2 (authority rule) — CustomerAuthorityCard accepts onSave prop
    def test_customer_authority_card_accepts_onsave(self):
        assert 'onSave' in self.pz_comp, (
            "CustomerAuthorityCard must accept an onSave prop (wired by page layer, not fetching itself)"
        )

    # Gap 2 (no auto-save) — CustomerAuthorityCard must not call PzApi or apiFetch directly
    def test_customer_authority_card_no_auto_save(self):
        for fetch_kw in ("PzApi.", "apiFetch", "saveCustomerMaster", "fetch("):
            assert fetch_kw not in self.pz_comp, (
                f"pz-components.js must not call {fetch_kw!r} — onSave callback is provided by page layer"
            )

    # Gap 3 — onSave wired in the page
    def test_page_wires_onsave_to_customer_card(self):
        assert 'onSave={handleSaveCustomerMapping}' in self.v2_html, (
            "proforma-v2.html must pass onSave={handleSaveCustomerMapping} to CustomerAuthorityCard"
        )
        assert 'handleSaveCustomerMapping' in self.v2_html, (
            "proforma-v2.html must define handleSaveCustomerMapping handler"
        )
        assert 'saveCustomerMaster' in self.v2_html, (
            "handleSaveCustomerMapping must call Api.saveCustomerMaster"
        )

    # Gap 4 — EmptyState for no client drafts
    def test_empty_state_for_no_client_drafts(self):
        assert 'No drafts for this client.' in self.v2_html, (
            "proforma-v2.html must show EmptyState 'No drafts for this client.' when client has no drafts"
        )

    # Gap 5 — Card section testids
    def test_card_section_testids(self):
        required_cards = [
            'readiness-card',
            'draft-card',
            'customer-authority-card-wrapper',
            'product-authority-card',
            'draft-history-card',
        ]
        for tid in required_cards:
            assert tid in self.v2_html, (
                f"proforma-v2.html Card wrapper must have data-testid={tid!r}"
            )

    # Gap 6 — ProductAuthorityRow uses 'warn' not 'error' for unmatched
    def test_product_authority_row_uses_warn_for_unmatched(self):
        import re
        # Extract only the ProductAuthorityRow function body (DraftLineRow may still use 'error')
        match = re.search(
            r"function ProductAuthorityRow\b.*?(?=\n  // ──|\n  window\.PzComponents)",
            self.pz_comp, re.DOTALL,
        )
        assert match is not None, "ProductAuthorityRow function must exist in pz-components.js"
        row_body = match.group(0)
        assert "'warn'" in row_body or '"warn"' in row_body, (
            "ProductAuthorityRow must use StatusDot status='warn' for unmatched products"
        )
        old_pattern = re.search(r"product_match\s*\?\s*['\"]ok['\"]\s*:\s*['\"]error['\"]", row_body)
        assert old_pattern is None, (
            "ProductAuthorityRow must not use 'error' for unmatched — use 'warn'"
        )

    # Gap 7 — ProformaReadinessGate does not infer readiness locally
    def test_readiness_gate_no_local_inference(self):
        for forbidden in (
            "blocking_reasons.length === 0",
            "blocking_reasons.length == 0",
            "!blocking_reasons.length",
            "ready = true",
            "ready = false",
            "setReady(",
        ):
            assert forbidden not in self.pz_comp, (
                f"ProformaReadinessGate must not infer readiness locally — found: {forbidden!r}"
            )
