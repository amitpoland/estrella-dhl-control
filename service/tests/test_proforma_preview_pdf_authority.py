"""Proforma Preview / PDF authority contracts (issue date, origin, payment, print/download).

Source-grep + focused unit pins for the shared Estrella preview experience.
Draft #76 is a regression case pattern only — nothing is hardcoded to draft id 76.
"""

from __future__ import annotations

import pathlib
import re
import sqlite3
import tempfile

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
JSX = ROOT / "app" / "static" / "v2" / "proforma-detail.jsx"
CSS = ROOT / "app" / "static" / "v2" / "estrella-doc-tokens.css"
ROUTES = ROOT / "app" / "api" / "routes_proforma.py"


def _jsx() -> str:
    return JSX.read_text(encoding="utf-8")


def _routes() -> str:
    return ROUTES.read_text(encoding="utf-8")


# ── Issue date — single commercial authority ─────────────────────────────────

class TestCommercialIssueDateAuthority:
    def test_commercial_issue_date_resolver_present(self):
        text = _jsx()
        assert "commercialIssueDate" in text
        assert "payment_terms.invoice_date" in text or "rawPt.invoice_date" in text
        assert "NEVER created_at" in text or "never created_at" in text.lower()

    def test_issued_header_uses_commercial_issue_date_not_created_at(self):
        text = _jsx()
        # previewDocData.date must use commercialIssueDate
        assert re.search(r"date:\s*commercialIssueDate", text), (
            "previewDocData.date must use commercialIssueDate"
        )
        # Forbidden: Issued date fallback to created_at
        assert not re.search(
            r"date:\s*liveDraft\.invoice_date\s*\|\|\s*liveDraft\.created_at",
            text,
        ), "Issued date must not fall back to created_at"

    def test_no_issue_date_warning_uses_commercial_issue_date(self):
        text = _jsx()
        assert "!commercialIssueDate" in text or "if (!commercialIssueDate)" in text
        assert not re.search(
            r"if\s*\(\s*!liveDraft\.invoice_date\s*\)\s*w\.push\(\s*\{\s*code:\s*'NO_ISSUE_DATE'",
            text,
        ), "NO_ISSUE_DATE must not check invoice_date alone"

    def test_due_fallback_base_not_created_at(self):
        text = _jsx()
        # The due-date base near commercialIssueDate must not use created_at
        idx = text.find("const _dueFallback")
        assert idx != -1
        window = text[idx: idx + 800]
        assert "commercialIssueDate" in window
        assert "liveDraft.created_at" not in window

    def test_overview_issue_date_not_raw_created_at(self):
        text = _jsx()
        assert 'label="Issue date"' in text
        assert not re.search(
            r'label="Issue date"\s+value=\{detail\.created_at',
            text,
        ), "Overview Issue date must not bind solely to detail.created_at"

    def test_api_exposes_issue_date_projection(self):
        src = _routes()
        assert 'full["issue_date"]' in src or '"issue_date"' in src
        assert "payment_terms" in src
        assert "wfirma_issue_date" in src


# ── Payment terms — no internal IDs ──────────────────────────────────────────

class TestPaymentTermsCustomerDisplay:
    def test_payment_terms_allowlist_no_catch_all(self):
        text = _jsx()
        # Old catch-all that leaked invoice_language_id
        assert not re.search(
            r"Object\.entries\(rawPt\)\.forEach",
            text,
        ), "paymentTermsDisplay must not dump all payment_terms keys"

    def test_invoice_language_id_not_in_customer_payment_display(self):
        text = _jsx()
        assert "_PAYMENT_METHOD_LABELS" in text
        assert "Bank transfer" in text
        # Allowlist builder: method + days only — no `${k}: ${v}` catch-all dump
        idx = text.find("const paymentTermsDisplay")
        assert idx != -1
        window = text[idx: idx + 900]
        assert "${k}: ${v}" not in window
        assert "Allowlist only" in window
        assert "parts.push(`${rawPt.days} days`)" in window or "days`)" in window

    def test_preview_html_filters_internal_payment_keys(self):
        src = _routes()
        assert "_PT_METHOD_LABELS" in src
        assert "invoice_language_id" in src  # mentioned in comment as excluded
        # Must not dump all terms.items() raw into customer HTML
        start = src.index("def get_proforma_draft_preview_html")
        end = src.index("\ndef ", start + 10)
        body = src[start:end]
        assert "for k, v in terms.items()" not in body, (
            "preview.html must not dump all payment_terms keys to customers"
        )
        assert "_PT_METHOD_LABELS" in body


# ── Origin enrichment ────────────────────────────────────────────────────────

class TestOriginEnrichmentAuthority:
    def test_frontend_does_not_use_phantom_draft_origin_country(self):
        text = _jsx()
        # View-model lines.origin must not fall back to liveDraft.origin_country
        assert not re.search(
            r"origin:\s*ln\.origin\s*\|\|\s*liveDraft\.origin_country",
            text,
        )
        assert not re.search(
            r"origin:\s*l\.origin\s*\|\|\s*liveDraft\.origin_country",
            text,
        )

    def test_backend_origin_lookup_is_casefold_safe(self):
        src = _routes()
        assert "casefold()" in src
        assert "_pl_origin_index.get(pc.casefold())" in src or "pc.casefold()" in src

    def test_origin_enrichment_fills_when_product_local_has_sku(self, tmp_path, monkeypatch):
        """Read-time enrichment fills ln.origin from product_local; absent SKU stays blank."""
        from app.services import master_data_db as mdb
        from app.api import routes_proforma as rp

        db = tmp_path / "master_data.sqlite"
        mdb.init_db(db)
        mdb.upsert_product_local(db, {
            "product_code": "SKU-ORIGIN-1",
            "origin_country": "IN",
            "active": 1,
        })

        monkeypatch.setattr(rp, "_master_db_path", lambda: db)

        # Simulate the index-build + enrich loop from get_proforma_draft
        _pl_origin_index = {}
        with sqlite3.connect(str(db)) as mc:
            mc.row_factory = sqlite3.Row
            for r in mc.execute(
                "SELECT product_code, origin_country FROM product_local"
                " WHERE active = 1 OR active IS NULL"
            ).fetchall():
                pcode = (r["product_code"] or "").strip()
                if pcode:
                    oc = (r["origin_country"] or "").strip() or "IN"
                    _pl_origin_index[pcode] = oc
                    _pl_origin_index[pcode.casefold()] = oc

        lines = [
            {"product_code": "sku-origin-1", "origin": ""},  # case differs
            {"product_code": "MISSING-SKU", "origin": ""},
            {"product_code": "KEEP-ME", "origin": "CN"},  # operator-supplied
        ]
        for ln in lines:
            pc = str(ln.get("product_code") or "").strip()
            if not pc:
                continue
            if not (ln.get("origin") or "").strip():
                oc = _pl_origin_index.get(pc) or _pl_origin_index.get(pc.casefold())
                if oc:
                    ln["origin"] = oc

        assert lines[0]["origin"] == "IN"
        assert lines[1]["origin"] == ""  # absent SKU — not invented
        assert lines[2]["origin"] == "CN"  # not overwritten


# ── Print vs Download ────────────────────────────────────────────────────────

class TestPreviewPrintDownloadSplit:
    def test_distinct_print_and_download_testids(self):
        text = _jsx()
        assert 'data-testid="preview-print"' in text
        assert 'data-testid="preview-download"' in text
        assert "Print / Save as PDF" not in text

    def test_print_calls_window_print(self):
        text = _jsx()
        idx = text.find('data-testid="preview-print"')
        assert idx != -1
        window = text[idx: idx + 600]
        assert "window.print()" in window

    def test_download_uses_sheet_capture_not_print(self):
        text = _jsx()
        assert "_ejDownloadRenderedSheetPdf" in text
        assert "html2canvas" in text
        idx = text.find('data-testid="preview-download"')
        assert idx != -1
        window = text[idx: idx + 900]
        assert "window.print()" not in window
        assert "_ejDownloadRenderedSheetPdf" in window

    def test_download_pagination_is_explicit_not_tall_canvas_slice(self):
        text = _jsx()
        fn = text[text.find("async function _ejDownloadRenderedSheetPdf"):
                  text.find("async function _ejDownloadRenderedSheetPdf") + 6500]
        # Forbidden: one oversized canvas + negative Y slice
        assert "heightLeft -= pageH" not in fn
        assert "position -= pageH" not in fn
        # Required: row-packed page clones with thead retained
        assert "rowStart" in fn and "rowEnd" in fn
        assert "cloneNode(true)" in fn
        assert "table.ej-table" in fn


# ── Pagination / screen readability ──────────────────────────────────────────

class TestA4PaginationScreen:
    def test_ej_a4_screen_grows_with_content(self):
        css = CSS.read_text(encoding="utf-8")
        # Fixed height:1123px + overflow:hidden would clip 33-line drafts
        block = re.search(r"\.ej-a4\s*\{([^}]+)\}", css)
        assert block, ".ej-a4 rule missing"
        body = block.group(1)
        assert "min-height" in body
        assert "overflow: visible" in body or "overflow:visible" in body
        assert "height: 1123px" not in body.replace("min-height: 1123px", "")
