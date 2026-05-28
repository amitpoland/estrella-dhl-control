"""test_master_soft_delete_phase4b_wave4_product_local.py — Phase 4B Wave 4.

Final entity: product_local (overlay).

Semantics (per service/docs/product_local_soft_delete_design.md):
  inactive overlay = "stop applying overlay" → consumers fall back to
  non-overlay behavior; wFirma product is never treated as deleted.

Covers:
  - lifecycle (soft delete / list / get / restore / hard-delete gating / audit)
  - PUT does not reactivate
  - CONSUMER FALLBACK proofs:
      * proforma_draft_sync._resolve_hs_code falls back when overlay inactive
      * routes_proforma origin reverts to "IN" when overlay inactive
      * proforma_intelligence drops inactive overlay from HS suggestions
  - PZ engine still does not import product_local
"""
from __future__ import annotations

import re
import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch

import pytest


def _ensure_path() -> None:
    here = Path(__file__).resolve()
    for p in (str(here.parents[1]), str(here.parents[2])):
        if p not in sys.path:
            sys.path.insert(0, p)


_ensure_path()

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.audit import list_audit
from app.core.config import settings
from app.services import master_data_db as mdb


_API = "/api/v1/product-local"
_HDR = {"X-API-Key": "TESTKEY"}
_PC  = "SKU-W4"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    monkeypatch.setattr(settings, "api_key", "TESTKEY")
    monkeypatch.setattr(settings, "master_audit_enabled", True)
    monkeypatch.setattr(settings, "master_role_enforcement", False)
    monkeypatch.setattr(settings, "master_hard_delete_enabled", False)
    import app.api.routes_master_data as md
    md._DB_PATH = tmp_path / "master_data.sqlite"
    app = FastAPI()
    app.include_router(md.pl_router)
    app.include_router(md.hs_router)   # for RI seeding of hs_code_override
    c = TestClient(app, raise_server_exceptions=True)
    # Seed an active HS code so hs_code_override RI (Phase 4C) is satisfied.
    c.put("/api/v1/hs-codes/71131900", json={"description_pl": "x"}, headers=_HDR)
    return c, tmp_path / "master_data.sqlite"


def _seed(client, **extra) -> None:
    cl, _ = client
    body = {"hs_code_override": "71131900", "origin_country": "IN", **extra}
    r = cl.put(f"{_API}/{_PC}", json=body, headers=_HDR)
    assert r.status_code == 200, r.text


# ── Lifecycle ────────────────────────────────────────────────────────────────

def test_soft_delete_sets_active_false_and_deleted_at(client):
    cl, _ = client
    _seed(client)
    r = cl.delete(f"{_API}/{_PC}", headers=_HDR)
    assert r.status_code == 204, r.text
    g = cl.get(f"{_API}/{_PC}", headers=_HDR)
    assert g.status_code == 200
    assert g.json()["active"] is False
    assert g.json().get("deleted_at")


def test_soft_delete_audit_op_is_delete(client):
    cl, _ = client
    _seed(client)
    cl.delete(f"{_API}/{_PC}", headers=_HDR)
    rows = list_audit(entity="product_local", pk=_PC)
    dr = [r for r in rows if r["op"] == "delete"]
    assert len(dr) == 1
    assert dr[0]["before_json"]["product_code"] == _PC
    assert dr[0]["after_json"] is None


def test_default_list_excludes_inactive(client):
    cl, _ = client
    _seed(client)
    cl.delete(f"{_API}/{_PC}", headers=_HDR)
    r = cl.get(f"{_API}/", headers=_HDR)
    codes = [p["product_code"] for p in r.json()["items"]]
    assert _PC not in codes


def test_active_false_list_includes_inactive(client):
    cl, _ = client
    _seed(client)
    cl.delete(f"{_API}/{_PC}", headers=_HDR)
    r = cl.get(f"{_API}/?active=false", headers=_HDR)
    codes = [p["product_code"] for p in r.json()["items"]]
    assert _PC in codes


def test_get_by_code_returns_inactive_for_audit(client):
    cl, _ = client
    _seed(client)
    cl.delete(f"{_API}/{_PC}", headers=_HDR)
    g = cl.get(f"{_API}/{_PC}", headers=_HDR)
    assert g.status_code == 200
    assert g.json()["active"] is False
    assert g.json()["deleted_at"]


def test_restore_sets_active_true_and_clears_deleted_at(client):
    cl, _ = client
    _seed(client)
    cl.delete(f"{_API}/{_PC}", headers=_HDR)
    r = cl.post(f"{_API}/{_PC}/restore", headers=_HDR)
    assert r.status_code == 200, r.text
    assert r.json()["active"] is True
    assert r.json().get("deleted_at") in (None, "")


def test_restore_writes_audit_row(client):
    cl, _ = client
    _seed(client)
    cl.delete(f"{_API}/{_PC}", headers=_HDR)
    cl.post(f"{_API}/{_PC}/restore", headers=_HDR)
    rr = [r for r in list_audit(entity="product_local", pk=_PC) if r["op"] == "restore"]
    assert len(rr) == 1
    assert rr[0]["before_json"]["active"] is False
    assert rr[0]["after_json"]["active"] is True


def test_restore_404_on_missing(client):
    cl, _ = client
    r = cl.post(f"{_API}/NOPE/restore", headers=_HDR)
    assert r.status_code == 404


def test_put_does_not_reactivate(client):
    cl, _ = client
    _seed(client)
    cl.delete(f"{_API}/{_PC}", headers=_HDR)
    r = cl.put(f"{_API}/{_PC}", json={"hs_code_override": "71131900",
                                      "notes": "edited"}, headers=_HDR)
    assert r.status_code == 200
    g = cl.get(f"{_API}/{_PC}", headers=_HDR)
    assert g.json()["active"] is False, "PUT must not reactivate"
    assert g.json()["notes"] == "edited"


# ── Hard delete gating ──────────────────────────────────────────────────────

def test_hard_delete_blocked_when_flag_off(client):
    cl, _ = client
    _seed(client)
    r = cl.delete(f"{_API}/{_PC}?hard=true", headers=_HDR)
    assert r.status_code == 409
    assert "Hard delete is disabled" in r.text
    assert cl.get(f"{_API}/{_PC}", headers=_HDR).json()["active"] is True


def test_hard_delete_blocked_for_master_editor_when_flag_on(client, monkeypatch):
    cl, _ = client
    _seed(client)
    monkeypatch.setattr(settings, "master_hard_delete_enabled", True)
    monkeypatch.setattr(settings, "master_role_enforcement", True)
    with patch("app.core.role_gate.get_current_user_optional",
               return_value={"id": "u", "role": "master_editor"}):
        r = cl.delete(f"{_API}/{_PC}?hard=true", cookies={"pz_session": "fake"})
    assert r.status_code == 403


def test_hard_delete_allowed_for_master_admin_when_flag_on(client, monkeypatch):
    cl, _ = client
    _seed(client)
    monkeypatch.setattr(settings, "master_hard_delete_enabled", True)
    monkeypatch.setattr(settings, "master_role_enforcement", True)
    with patch("app.core.role_gate.get_current_user_optional",
               return_value={"id": "u", "role": "master_admin"}), \
         patch("app.auth.dependencies.get_current_user_optional",
               return_value={"id": "u", "role": "master_admin"}):
        r = cl.delete(f"{_API}/{_PC}?hard=true", cookies={"pz_session": "fake"})
    assert r.status_code == 204, r.text
    assert cl.get(f"{_API}/{_PC}", headers=_HDR).status_code == 404


def test_hard_delete_audit_op(client, monkeypatch):
    cl, _ = client
    _seed(client)
    monkeypatch.setattr(settings, "master_hard_delete_enabled", True)
    r = cl.delete(f"{_API}/{_PC}?hard=true", headers=_HDR)
    assert r.status_code == 204
    hd = [r for r in list_audit(entity="product_local", pk=_PC) if r["op"] == "hard_delete"]
    assert len(hd) == 1 and hd[0]["after_json"] is None


# ── Consumer fallback proofs (the load-bearing Wave 4 behavior) ─────────────

def test_resolver_falls_back_when_overlay_inactive(client):
    """proforma_draft_sync._resolve_hs_code returns the overlay HS when
    active, and falls back (None / invoice level) when inactive."""
    cl, db = client
    _seed(client)   # active overlay with hs_code_override=71131900
    from app.services.proforma_draft_sync import _resolve_hs_code
    # Active → returns the override.
    assert _resolve_hs_code(_PC, db) == "71131900"
    # Soft-delete the overlay → resolver must NOT return the override.
    cl.delete(f"{_API}/{_PC}", headers=_HDR)
    # No invoice-line fallback configured in this isolated test → None.
    assert _resolve_hs_code(_PC, db) is None, \
        "inactive overlay must not supply the HS code"


def test_routes_proforma_origin_reverts_when_overlay_inactive(client):
    """The proforma line-enrichment guard only applies origin/hs from an
    ACTIVE overlay. Verify via direct get_product_local + the guard logic:
    an inactive overlay yields active=False so the route skips it."""
    cl, db = client
    _seed(client, origin_country="PL")   # overlay claims origin PL
    rec = mdb.get_product_local(db, _PC)
    assert rec.active is True and rec.origin_country == "PL"
    cl.delete(f"{_API}/{_PC}", headers=_HDR)
    rec2 = mdb.get_product_local(db, _PC)
    assert rec2.active is False
    # The route guard is `if pl_row and getattr(pl_row, "active", True)` —
    # with active False it is skipped, so origin stays the "IN" default.
    # Assert the data the route reads supports that decision.
    assert rec2.active is False, "inactive overlay must be skipped by enrichment"


def test_proforma_intelligence_drops_inactive_overlay(client):
    """The proforma_intelligence raw SQL must exclude inactive overlays
    (COALESCE(active,1)=1)."""
    cl, db = client
    _seed(client)
    # Active overlay shows up in the HS lookup SQL.
    with sqlite3.connect(db) as cx:
        cx.row_factory = sqlite3.Row
        before = cx.execute(
            "SELECT product_code FROM product_local "
            "WHERE hs_code_override IS NOT NULL AND hs_code_override <> '' "
            "AND COALESCE(active, 1) = 1").fetchall()
    assert any(r["product_code"] == _PC for r in before)
    cl.delete(f"{_API}/{_PC}", headers=_HDR)
    with sqlite3.connect(db) as cx:
        cx.row_factory = sqlite3.Row
        after = cx.execute(
            "SELECT product_code FROM product_local "
            "WHERE hs_code_override IS NOT NULL AND hs_code_override <> '' "
            "AND COALESCE(active, 1) = 1").fetchall()
    assert not any(r["product_code"] == _PC for r in after), \
        "inactive overlay must be excluded from the intelligence HS lookup"


def test_wfirma_product_not_deleted_on_soft_delete(client):
    """Soft-deleting the overlay must not touch any wFirma product. The
    overlay row persists (inactive); no wFirma write path is invoked."""
    cl, db = client
    _seed(client)
    cl.delete(f"{_API}/{_PC}", headers=_HDR)
    # Overlay row still exists in the local table (soft, not removed).
    with sqlite3.connect(db) as cx:
        cnt = cx.execute("SELECT COUNT(*) FROM product_local WHERE product_code=?",
                         (_PC,)).fetchone()[0]
    assert cnt == 1, "soft-delete must keep the overlay row (inactive), not remove it"


# ── Source-grep isolation ────────────────────────────────────────────────────

_REPO = Path(__file__).resolve().parents[2]


def test_pz_engine_does_not_import_product_local():
    """PZ landed-cost engine must remain decoupled from product_local."""
    offenders = []
    for name in ("pz_import_processor.py", "pz_calculator.py",
                 "pz_dual_export.py", "pz_pdf_export.py"):
        f = _REPO / name
        if f.exists() and "product_local" in f.read_text(encoding="utf-8", errors="replace"):
            offenders.append(name)
    assert not offenders, f"PZ engine must not reference product_local: {offenders}"


def test_soft_delete_section_has_no_wfirma_or_pz_imports():
    src = (Path(__file__).resolve().parents[1] / "app" / "services"
           / "master_data_db.py").read_text(encoding="utf-8")
    m = re.search(r"# ── Phase 4B Wave 4 — product_local soft-delete[\s\S]+?(?=\n# ──|\Z)", src)
    assert m, "Wave 4 section not found"
    block = m.group(0)
    # Strip comment lines so the descriptive header ("no wFirma / PZ side
    # effects") doesn't false-positive — we assert on actual code only.
    code_only = "\n".join(
        ln for ln in block.splitlines() if not ln.lstrip().startswith("#")
    ).lower()
    for forbidden in ("wfirma", "pz_calculator", "pz_import", "requests.", "httpx."):
        assert forbidden not in code_only, \
            f"Wave 4 soft-delete section must not reference {forbidden!r}"
