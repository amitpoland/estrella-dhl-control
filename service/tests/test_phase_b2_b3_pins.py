"""
test_phase_b2_b3_pins.py — Phase B slices B2 + B3
(PROJECT_STATE DECISIONS "Phase B slices B2+B3", 2026-07-03).

B2 — Promotion Notes panel: the BE-2 v1 document viewer as a sixth InvPanel
on the EXISTING Inventory page (no new page/route/tab — GOVERNANCE
authority-first rule). Transports in pz-api.js; note_no is slash-bearing
(SPN/NNN/YYYY) and MUST be encoded per segment, never whole-id.

B3 — proforma-detail :2542 prefers the persisted client_po (494c4665);
the invoice_no||client_ref expression survives ONLY as the legacy fallback
for pre-fix rows ('' column).
"""
from __future__ import annotations

from pathlib import Path

import pytest

_V2 = Path(__file__).resolve().parent.parent / "app" / "static" / "v2"


def _read(name: str) -> str:
    return (_V2 / name).read_text(encoding="utf-8", errors="replace")


# ── B2: transports ────────────────────────────────────────────────────────────

def test_pz_api_has_both_note_transports():
    src = _read("pz-api.js")
    assert "getPromotionNotes:" in src
    assert "getPromotionNote:" in src
    assert "/inventory/promotion-notes/${encodeURIComponent(batchId)}" in src


def test_note_no_encoded_per_segment_never_whole():
    """note_no contains slashes; the :path route needs literal separators.
    Whole-id encodeURIComponent would send %2F — pinned out."""
    src = _read("pz-api.js")
    assert ".split('/').map(encodeURIComponent).join('/')" in src, \
        "getPromotionNote must encode per segment (slash-bearing note_no)"
    k = src.index("getPromotionNote:")
    block = src[k:k + 400]
    assert "encodeURIComponent(noteNo)" not in block, \
        "whole-id encoding would break the :path route (%2F)"


def test_slashed_note_no_routes_end_to_end(tmp_path, monkeypatch):
    """Round-trip with SPN/001/2026 through the REAL route: the exact URL
    shape the JS transport builds (literal slashes) must match the :path
    converter — 200 for an existing note, and the 404 for a missing one
    must be the route's own NOTE_NOT_FOUND (not the framework default,
    which would mean the path never matched)."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.core.config import settings as _settings
    from app.services import warehouse_db as wdb
    from app.services import stock_promotion_note_db as ndb

    monkeypatch.setattr(_settings, "api_key", "", raising=False)
    monkeypatch.setattr(_settings, "environment", "dev", raising=False)
    wdb.init_warehouse_db(tmp_path / "warehouse.db")

    note_no = ndb.write_promotion_note(
        batch_id="B_B2", trigger="pz_created", source="wfirma_pz_create",
        moved=[{"scan_code": "SC-1", "state_before": "PURCHASE_TRANSIT",
                "state_after": "WAREHOUSE_STOCK"}],
        now_iso="2026-01-01T00:00:00+00:00",
    )
    assert note_no == "SPN/001/2026"

    client = TestClient(app)
    ok = client.get(f"/api/v1/inventory/promotion-note/{note_no}")
    assert ok.status_code == 200
    assert ok.json()["note_no"] == "SPN/001/2026"

    missing = client.get("/api/v1/inventory/promotion-note/SPN/999/2099")
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "NOTE_NOT_FOUND", \
        "slashed path must reach the route (framework default 404 = no match)"


# ── B2: panel pins on the EXISTING Inventory page ────────────────────────────

def test_panel_present_with_house_testids():
    src = _read("inventory-page.jsx")
    for tid in ("panel-promotion-notes", "input-notes-batch-id",
                "btn-notes-fetch", "notes-table", "notes-row",
                "notes-lines", "notes-empty", "btn-note-expand"):
        assert tid in src, f"testid '{tid}' missing from the Promotion Notes panel"


def test_panel_is_sixth_invpanel_on_existing_page_no_new_page():
    src = _read("inventory-page.jsx")
    assert "<PromotionNotesPanel />" in src, "panel must mount inside InventoryPage"
    assert src.count("function PromotionNotesPanel") == 1
    # authority rule: no new page/route — the shell must NOT gain a slug
    index = _read("index.html")
    assert "promotion_notes" not in index, \
        "no new page slug — the panel lives on the existing Inventory authority"


def test_panel_uses_pzapi_transports_and_reads_only():
    src = _read("inventory-page.jsx")
    assert "window.PzApi.getPromotionNotes" in src
    assert "window.PzApi.getPromotionNote" in src
    # Slice ONLY the PromotionNotesPanel body. The Move Stock modal (Phase B
    # FOLD) now sits between this panel and InventoryPage and legitimately
    # calls movePieceLocation — end the read-only slice at MoveStockModal.
    k = src.index("function PromotionNotesPanel")
    end_marker = src.find("const MS_ERROR_HINTS", k)
    if end_marker == -1:
        end_marker = src.index("function InventoryPage")
    body = src[k:end_marker]
    for forbidden in ("method: 'POST'", 'method: "POST"', "_post", "movePieceLocation"):
        assert forbidden not in body, f"read-only panel must not contain {forbidden!r}"
    assert "Read-only. No write calls are made from this panel." in body


def test_panel_honest_empty_state():
    src = _read("inventory-page.jsx")
    assert "No promotion notes for this batch" in src
    assert "honest empty" in src


# ── Babel global-helper collision immunity (found by the B2 render check) ────

def test_inventory_page_has_no_spread_rest_components():
    """Babel-standalone hoists compiled destructure helpers' `_excluded`
    prop-lists to GLOBAL vars outside each file's IIFE; a later-loaded
    script overwrites them, leaking excluded props (onChange!) into JSX
    spreads — typing then stores the event object into state and the tree
    unmounts (pre-existing: untouched AuditPanel crashed identically;
    live-page proof 2026-07-03, window._excluded held another file's
    Button prop-list). This file is immune ONLY while it contains no
    spread-rest destructuring."""
    src = _read("inventory-page.jsx")
    assert "...rest" not in src, \
        "spread-rest returned to inventory-page.jsx — the global _excluded " \
        "helper collision re-opens (see PROJECT_STATE DECISIONS)"
    assert "'data-testid': testid" in src, \
        "the explicit data-testid destructure must remain"


# ── B3: real client_po preferred, legacy fallback preserved ──────────────────

def test_proforma_detail_client_po_never_bleeds_purchase_invoice():
    """2026-07-16 authority repair: client_po is the CLIENT PO only. It must NEVER
    fall back to pk.invoice_no (the SUPPLIER purchase invoice) — that mix put the
    purchase invoice into the Client PO column. The purchase invoice is now its
    own typed field (purchase_invoice_no)."""
    src = _read("proforma-detail.jsx")
    assert "client_po:    pk.client_po || ''," in src, \
        "client_po must resolve to pk.client_po only (honest-missing else)"
    assert "purchase_invoice_no: pk.invoice_no || ''," in src, \
        "supplier purchase invoice must be its own typed field, separate from client_po"
    # the old cross-authority fallback must be gone
    assert "pk.client_po || pk.invoice_no || ln.client_ref" not in src


def test_packing_renderer_never_renders_supplier_purchase_invoice():
    """PROJECT_STATE DECISIONS 2026-07-18: purchase_invoice_no is a typed-separation
    guard — DEFERRED / intentionally NOT rendered. The supplier purchase invoice is
    IMPORT_PZ authority and must never appear on the customer-facing packing list,
    which carries invoice_ref (the wFirma SALES invoice) as its only invoice identity.
    The presence pin above keeps the builder field alive so pk.invoice_no can never
    bleed into client_po; this absence pin keeps that field OFF the document. A future
    `{r.purchase_invoice_no}` added to the renderer must fail here, not ship silently."""
    packing_src = _read("estrella-doc-packing.jsx")
    assert ".purchase_invoice_no" not in packing_src, \
        "estrella-doc-packing.jsx must not read purchase_invoice_no — the supplier " \
        "purchase invoice is IMPORT_PZ authority and must not appear on a customer " \
        "sales/transport document (PROJECT_STATE DECISIONS 2026-07-18)"


def test_b3_client_po_typed_separation_semantics():
    """client_po draws ONLY from the client PO column; it never adopts the
    supplier purchase invoice. Pure-expression check mirroring the JSX."""
    def client_po(pk_client_po):
        return pk_client_po or ""
    assert client_po("PO-2026-7") == "PO-2026-7"
    assert client_po("") == ""            # missing → honest blank, NOT invoice_no
