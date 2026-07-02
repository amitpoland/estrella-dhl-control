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
    k = src.index("function PromotionNotesPanel")
    body = src[k:src.index("function InventoryPage")]
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

def test_proforma_detail_prefers_persisted_client_po():
    src = _read("proforma-detail.jsx")
    assert "pk.client_po || pk.invoice_no || ln.client_ref" in src, \
        "B3: the persisted column must be preferred; legacy expression is the fallback"
    assert "494c4665" in src, "the fix must cite the persistence commit"


def test_b3_fallback_semantics():
    """'' (legacy backfill default) is falsy → pre-fix rows keep the legacy
    display; a persisted value wins. Pure-expression check mirroring the JSX."""
    def js_expr(pk_client_po, pk_invoice_no, ln_client_ref):
        return pk_client_po or pk_invoice_no or ln_client_ref or ""
    assert js_expr("PO-2026-7", "EJL/26-27/300", "VER") == "PO-2026-7"
    assert js_expr("", "EJL/26-27/300", "VER") == "EJL/26-27/300"
    assert js_expr("", "", "VER") == "VER"
    assert js_expr("", "", "") == ""
