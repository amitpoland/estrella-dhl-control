"""test_proforma_authority_ui.py — Proforma draft operator-readiness (V1).

Pins the V1 `shipment-detail.html` proforma-draft operator-readiness fixes:

  A. Customer-authority summary renders BEFORE the product lines.
  B. Each line shows the CANONICAL product description (product_descriptions /
     description_engine — the same authority PZ uses) with a source badge,
     labelled display-only (the wFirma line name posts from design_no /
     product_code, NOT this — so the change cannot alter the posted line).
  C. Contractor-projection blocked draft-birth records are fetched + rendered
     (no hidden blocked records); the GET /blocks endpoint is enriched with
     ``source_file_name`` so the operator can name the source document.

Also pins the safety invariants: the wFirma proforma post line-name authority
is UNCHANGED (design_no / product_code), and the description change is display
only (no valuation / PZ / customs / accounting / wFirma-booking change).

Run: python -m pytest tests/test_proforma_authority_ui.py -q
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from app.core.config import settings
from app.services import document_db as ddb
from app.services import proforma_invoice_link_db as pildb

_HTML = Path(__file__).resolve().parents[1] / "app" / "static" / "shipment-detail.html"
_SRC = _HTML.read_text(encoding="utf-8")
_ROUTES_PROFORMA = (Path(__file__).resolve().parents[1] / "app" / "api"
                    / "routes_proforma.py").read_text(encoding="utf-8")


# ── A. Customer authority before lines ────────────────────────────────────────

class TestCustomerAuthorityBeforeLines:
    def test_summary_present(self):
        assert 'data-testid="draft-customer-authority-summary"' in _SRC

    def test_summary_renders_before_lines_table(self):
        i_sum = _SRC.index('data-testid="draft-customer-authority-summary"')
        i_lines = _SRC.index('data-testid="draft-lines-table"')
        assert i_sum < i_lines, "customer authority summary must render before the lines table"

    def test_summary_shows_buyer_shipto_payment_and_state(self):
        # the summary block references the authority fields + override/sync state.
        # Start the segment at the summary comment (the const reads sit above the
        # data-testid inside the IIFE).
        seg = _SRC[_SRC.index('Customer authority summary (read-only)'):
                   _SRC.index('data-testid="draft-lines-table"')]
        assert "buyer_override" in seg and "ship_to_override" in seg and "payment_terms" in seg
        assert "override active" in seg and "packing synced" in seg


# ── B. Canonical description + display-only labelling ─────────────────────────

class TestCanonicalDescription:
    def test_canonical_desc_rendered_per_line(self):
        assert "draft-line-canon-desc-" in _SRC
        assert "draft-line-desc-source-" in _SRC

    def test_uses_canonical_product_descriptions_fields(self):
        # reuses the fields enrich already stamps — no separate mapping invented
        assert "description_bilingual" in _SRC
        assert "description_pl" in _SRC and "description_en" in _SRC
        assert "name_pl_source" in _SRC

    def test_labelled_display_only_not_wfirma_line_name(self):
        # the operator must not mistake the display description for the wFirma
        # line name — the title says so explicitly.
        assert "Display only" in _SRC
        assert "design_no / product_code" in _SRC

    def test_wfirma_post_line_name_authority_unchanged(self):
        # SAFETY: the wFirma proforma line name posts from design_no / product_code,
        # NOT name_pl / description — so the display change cannot alter the post.
        assert 'ln.get("design_no")' in _ROUTES_PROFORMA
        # the posted wFirma line name reads design_no / product_code (both post
        # sites: preview + create), never name_pl.
        assert 'design_no") or pc' in _ROUTES_PROFORMA


# ── C. Blocked records visible (HTML) ─────────────────────────────────────────

class TestBlockedRecordsVisible:
    def test_panel_present_and_fetches_blocks(self):
        assert 'data-testid="proforma-blocked-records-panel"' in _SRC
        assert "/api/v1/admin/contractor-projection/blocks/" in _SRC
        assert "birthBlocks" in _SRC

    def test_renders_required_fields_and_action(self):
        seg = _SRC[_SRC.index('proforma-blocked-records-panel'):
                   _SRC.index('proforma-draft-list')]
        for token in ("source_file_name", "client_name", "client_contractor_id",
                      "code", "reason", "Action"):
            assert token in seg, f"blocked panel must render {token}"

    def test_cm_link_only_when_contractor_id(self):
        seg = _SRC[_SRC.index('proforma-blocked-records-panel'):
                   _SRC.index('proforma-draft-list')]
        # the link is guarded by a non-empty contractor id (F5)
        assert "cid &&" in seg and "customer-master" in seg


# ── C-backend. /blocks endpoint enriches source_file_name ─────────────────────

class TestBlocksEndpointSourceFile:
    @pytest.fixture()
    def storage(self, tmp_path):
        ddb.init_document_db(tmp_path / "documents.db")
        pildb.init_db(tmp_path / "proforma_links.db")
        with patch.object(settings, "storage_root", tmp_path):
            yield tmp_path

    @pytest.fixture()
    def client(self, storage):
        from fastapi.testclient import TestClient
        from app.main import app
        from app.core.security import require_api_key
        app.dependency_overrides[require_api_key] = lambda: {"id": "op"}
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c
        app.dependency_overrides.clear()

    def test_block_carries_source_file_name(self, client, storage):
        b = "B-BLK-1"
        ship = ddb.register_document(batch_id=b, document_type="sales_packing_list",
                                     file_name="EJL-299.xlsx", source="intake")
        sd = ddb.store_sales_document(
            batch_id=b, document_id=ship,
            data={"client_name": "", "document_type": "sales_packing_list",
                  "source_file_path": r"C:\\PZ\\storage\\incoming\\B-BLK-1\\EJL-299.xlsx"})
        pildb.record_draft_birth_block(
            storage / "proforma_links.db", b, sd,
            code="contractor_missing", reason="No client name and no contractor.",
            client_contractor_id="", client_name="", lines_count=3)
        r = client.get(f"/api/v1/admin/contractor-projection/blocks/{b}")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["count"] == 1
        assert body["blocks"][0]["source_file_name"] == "EJL-299.xlsx"
        assert body["blocks"][0]["code"] == "contractor_missing"


# ── No-financial-change guard (this PR is display + read-only enrichment) ──────

class TestNoFinancialChange:
    def test_html_change_does_not_touch_pricing_or_booking(self):
        # the canonical-description block and summary are display-only; they must
        # not introduce price math or a wFirma write call.
        seg = _SRC[_SRC.index('draft-customer-authority-summary'):
                   _SRC.index('data-testid="draft-charges-table"')]
        for forbidden in ("process_batch", "/wfirma/", "landed_cost", "duty",
                          "reservations/create"):
            assert forbidden not in seg
