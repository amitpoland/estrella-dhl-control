"""test_proforma_draft_editor_contract.py — proforma draft editor
backend-contract tests.

Verifies that the line PATCH endpoint accepts the fields the editable
UI exposes (product_code, design_no, currency, qty, unit_price), that
the manual product_code override survives a round-trip, and that the
preview endpoint stays read-only and does not call wFirma write paths.
"""
from __future__ import annotations

import json
import sqlite3 as _s
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def fresh(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    monkeypatch.setenv("PZ_STORAGE_ROOT", str(tmp_path))
    from app.core.config import settings
    monkeypatch.setattr(settings, "storage_root", tmp_path, raising=False)
    monkeypatch.setattr(settings, "api_key", "", raising=False)
    from app.services import wfirma_db as wfdb
    from app.services import proforma_invoice_link_db as pildb
    from app.services import proforma_service_charges_db as scdb
    wfdb.init_wfirma_db(tmp_path / "wfirma.db")
    pildb.init_db(tmp_path / "proforma_links.db")
    scdb.init(tmp_path / "proforma_links.db")
    return tmp_path


@pytest.fixture()
def client(fresh):
    tmp = fresh
    from app.main import app
    from app.auth.dependencies import get_current_user
    app.dependency_overrides[get_current_user] = lambda: {
        "id": "t", "email": "t@local",
    }
    yield TestClient(app), tmp
    app.dependency_overrides.clear()


def _seed_draft_with_line(tmp: Path, *, batch_id: str, client_name: str,
                          product_code: str = "EJL/SEED-1",
                          design_no: str = "D-SEED",
                          currency: str = "USD") -> int:
    from app.services import proforma_invoice_link_db as pildb
    db = tmp / "proforma_links.db"
    pildb.init_db(db)
    lines = [{"line_id": 1, "product_code": product_code,
              "design_no": design_no, "qty": 1.0,
              "unit_price": 100.0, "currency": currency,
              "client_ref": ""}]
    source_lines = list(lines)  # snapshot for override-detection
    with _s.connect(str(db)) as conn:
        pildb._ensure_drafts_table(conn)
        now = pildb._now_utc_iso()
        cur = conn.execute(
            "INSERT INTO proforma_drafts (batch_id, client_name, status, "
            "currency, draft_state, draft_version, source_lines_json, "
            "editable_lines_json, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (batch_id, client_name, "draft", currency, "editing", 1,
             json.dumps(source_lines, sort_keys=True),
             json.dumps(lines, sort_keys=True), now, now),
        )
        return int(cur.lastrowid)


def _get_draft(cli: TestClient, draft_id: int) -> dict:
    r = cli.get(f"/api/v1/proforma/draft/{draft_id}")
    assert r.status_code == 200, r.text
    return r.json()["draft"]


def _patch_line(cli: TestClient, draft_id: int, line_id: int,
                expected: str, patch: dict):
    return cli.patch(
        f"/api/v1/proforma/draft/{draft_id}/lines/{line_id}",
        json={"expected_updated_at": expected, "patch": patch},
        headers={"X-Operator": "tester@local"},
    )


# ── 1. PATCH line accepts product_code ───────────────────────────────────

def test_patch_line_accepts_product_code(client):
    cli, tmp = client
    draft_id = _seed_draft_with_line(tmp, batch_id="B-PC",
                                       client_name="ACME")
    d = _get_draft(cli, draft_id)
    r = _patch_line(cli, draft_id, 1, d["updated_at"],
                     {"product_code": "EJL/MANUAL-OVERRIDE-1"})
    assert r.status_code == 200, r.text

    d2 = _get_draft(cli, draft_id)
    line = d2["editable_lines"][0]
    assert line["product_code"] == "EJL/MANUAL-OVERRIDE-1"


# ── 2. PATCH line accepts design_no ──────────────────────────────────────

def test_patch_line_accepts_design_no(client):
    cli, tmp = client
    draft_id = _seed_draft_with_line(tmp, batch_id="B-DN",
                                       client_name="ACME")
    d = _get_draft(cli, draft_id)
    r = _patch_line(cli, draft_id, 1, d["updated_at"],
                     {"design_no": "D-NEW"})
    assert r.status_code == 200, r.text
    d2 = _get_draft(cli, draft_id)
    assert d2["editable_lines"][0]["design_no"] == "D-NEW"


# ── 3. PATCH line accepts currency ───────────────────────────────────────

def test_patch_line_accepts_currency(client):
    cli, tmp = client
    draft_id = _seed_draft_with_line(tmp, batch_id="B-CCY",
                                       client_name="ACME")
    d = _get_draft(cli, draft_id)
    r = _patch_line(cli, draft_id, 1, d["updated_at"],
                     {"currency": "EUR"})
    assert r.status_code == 200, r.text
    d2 = _get_draft(cli, draft_id)
    assert d2["editable_lines"][0]["currency"] == "EUR"


# ── 4. Manual product_code override survives round-trip ──────────────────

def test_manual_product_code_override_survives_get(client):
    cli, tmp = client
    draft_id = _seed_draft_with_line(tmp, batch_id="B-OVR",
                                       client_name="ACME",
                                       product_code="EJL/ORIG-1")
    d = _get_draft(cli, draft_id)
    _patch_line(cli, draft_id, 1, d["updated_at"],
                 {"product_code": "EJL/OVERRIDDEN-1"})
    d2 = _get_draft(cli, draft_id)
    line = d2["editable_lines"][0]
    assert line["product_code"] == "EJL/OVERRIDDEN-1"
    # source_lines retains the original — UI uses this for the
    # "MANUAL OVERRIDE" badge.
    src = d2.get("source_lines") or []
    assert src, "source_lines should be preserved for override detection"
    src_pc = next((s.get("product_code") for s in src
                   if int(s.get("line_id") or 0) == 1), None)
    assert src_pc == "EJL/ORIG-1", (
        f"source_lines product_code should remain the original "
        f"value, got {src_pc!r}"
    )


# ── 5. Add-line POST works through existing endpoint ─────────────────────

def test_add_line_endpoint_accepts_full_payload(client):
    cli, tmp = client
    draft_id = _seed_draft_with_line(tmp, batch_id="B-ADD",
                                       client_name="ACME")
    d = _get_draft(cli, draft_id)
    r = cli.post(
        f"/api/v1/proforma/draft/{draft_id}/lines",
        json={"expected_updated_at": d["updated_at"],
              "line": {"product_code": "EJL/ADD-1",
                       "design_no": "D-ADD",
                       "qty": 2.0, "unit_price": 55.5,
                       "currency": "USD"}},
        headers={"X-Operator": "tester@local"},
    )
    assert r.status_code == 200, r.text
    d2 = _get_draft(cli, draft_id)
    pcs = [ln["product_code"] for ln in d2["editable_lines"]]
    assert "EJL/ADD-1" in pcs


# ── 6. Preview endpoint is read-only (DB row counts unchanged) ───────────

def test_preview_endpoint_is_read_only(client):
    cli, tmp = client
    draft_id = _seed_draft_with_line(tmp, batch_id="B-PV",
                                       client_name="ACME")

    def _snap():
        out = {}
        for fname, tables in (
            ("proforma_links.db", ["proforma_drafts"]),
            ("wfirma.db",         ["wfirma_customers", "wfirma_products"]),
        ):
            p = tmp / fname
            if not p.exists():
                continue
            with _s.connect(str(p)) as c:
                for t in tables:
                    try:
                        out[t] = c.execute(
                            f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                    except Exception:
                        pass
        return out

    before = _snap()
    # Preview is POST /preview/{batch_id}/{client_name}. May 200 or
    # 4xx depending on data completeness — both are fine, we only care
    # that DB rows don't change.
    cli.post("/api/v1/proforma/preview/B-PV/ACME")
    cli.post("/api/v1/proforma/preview/B-PV/ACME")
    after = _snap()
    assert before == after, f"preview must be read-only; rows changed: {before} → {after}"


# ── 7. Preview endpoint does not invoke wFirma write paths ──────────────

def test_preview_endpoint_does_not_invoke_wfirma_write(client, monkeypatch):
    """Source-grep + monkeypatch guard: the preview endpoint must never
    call wfirma_client.create_proforma / create_product / create_customer."""
    cli, tmp = client
    _seed_draft_with_line(tmp, batch_id="B-NO-WRITE", client_name="ACME")

    from app.services import wfirma_client as wfc
    write_calls = {"create_proforma": 0, "create_product": 0,
                    "create_customer": 0, "create_invoice": 0}

    def _spy(fn_name):
        def _wrapped(*a, **kw):
            write_calls[fn_name] += 1
            raise RuntimeError(f"preview must not call {fn_name}")
        return _wrapped

    for fn in list(write_calls.keys()):
        if hasattr(wfc, fn):
            monkeypatch.setattr(wfc, fn, _spy(fn))

    # Preview may return 4xx for blocked state (missing customer / product
    # mapping) — that's fine; we only assert no write was called.
    cli.post("/api/v1/proforma/preview/B-NO-WRITE/ACME")
    assert sum(write_calls.values()) == 0, (
        f"preview triggered wfirma_client writes: {write_calls}"
    )


# ── 8. Source-grep: edit endpoints don't introduce wFirma write surfaces

def test_edit_endpoints_have_no_wfirma_write_surface():
    """The patch-line / add-line / delete-line / patch-fields endpoints
    must NOT reference wfirma_client.create_*, post to wFirma, or write
    via the wfirma module.  This is a source-grep guard over the
    relevant route functions in routes_proforma.py."""
    src = (Path(__file__).resolve().parents[1] / "app" / "api"
           / "routes_proforma.py").read_text(encoding="utf-8")

    # Slice each editor function and check.
    edit_function_markers = [
        "def patch_proforma_draft(",
        "def patch_proforma_draft_line(",
        "def add_proforma_draft_line(",
        "def delete_proforma_draft_line(",
    ]
    forbidden = (
        "wfirma_client.create_proforma",
        "wfirma_client.create_product",
        "wfirma_client.create_customer",
        "wfirma_client.create_invoice",
    )
    for marker in edit_function_markers:
        if marker not in src:
            # Endpoint may not exist (e.g. delete) — skip
            continue
        start = src.index(marker)
        # bound at next @router decorator
        end = src.index("@router.", start + 50)
        body = src[start:end]
        for bad in forbidden:
            assert bad not in body, (
                f"{marker} body must not reference {bad!r}"
            )


# ── 9. customer_resolution still read-only (regression guard) ────────────

def test_customer_resolution_block_still_present_and_read_only(client):
    cli, tmp = client
    draft_id = _seed_draft_with_line(tmp, batch_id="B-CR",
                                       client_name="ACME")
    r = cli.get(f"/api/v1/proforma/draft/{draft_id}")
    body = r.json()["draft"]
    assert "customer_resolution" in body
    cr = body["customer_resolution"]
    for k in ("wfirma_customer_id", "found", "match_strategy"):
        assert k in cr, f"customer_resolution missing key {k!r}"


# ── 10. PATCH line accepts item_type and name_pl (PR-continuation) ───────

def test_patch_line_accepts_item_type_and_name_pl(client):
    cli, tmp = client
    draft_id = _seed_draft_with_line(tmp, batch_id="B-IT-NP",
                                       client_name="ACME")
    d = _get_draft(cli, draft_id)
    # First PATCH: item_type alone
    r = _patch_line(cli, draft_id, 1, d["updated_at"],
                     {"item_type": "RING"})
    assert r.status_code == 200, r.text
    d2 = _get_draft(cli, draft_id)
    assert d2["editable_lines"][0]["item_type"] == "RING"
    # Then PATCH: name_pl
    r2 = _patch_line(cli, draft_id, 1, d2["updated_at"],
                      {"name_pl":
                       "pierścionek ze złota próby 14 karatów"})
    assert r2.status_code == 200, r2.text
    d3 = _get_draft(cli, draft_id)
    assert d3["editable_lines"][0]["name_pl"] == \
        "pierścionek ze złota próby 14 karatów"


# ── 11. editable_line_fields whitelist includes item_type, name_pl ───────

def test_editable_line_fields_whitelist_includes_new_keys():
    from app.services import proforma_invoice_link_db as pildb
    assert "item_type" in pildb.EDITABLE_LINE_FIELDS
    assert "name_pl"   in pildb.EDITABLE_LINE_FIELDS


# ── 12. UI source includes inline inputs for item_type and name_pl ───────

def test_ui_source_includes_editable_item_type_and_name_pl_inputs():
    src = (Path(__file__).resolve().parents[1] / "app" / "static"
           / "shipment-detail.html").read_text(encoding="utf-8")
    # data-testids on the inline inputs (template-style names with ${line_id})
    for marker in ("draft-line-item-type-input-",
                   "draft-line-name-pl-input-"):
        assert marker in src, (
            f"shipment-detail.html missing {marker!r} — "
            f"item_type / name_pl inline inputs not unlocked"
        )


# ── 13. Readable HTML preview is read-only and never calls wFirma ────────

def test_draft_html_preview_is_read_only(client):
    cli, tmp = client
    draft_id = _seed_draft_with_line(tmp, batch_id="B-HTML",
                                       client_name="ACME")

    def _snap():
        out = {}
        for fname, tables in (
            ("proforma_links.db", ["proforma_drafts"]),
            ("wfirma.db",         ["wfirma_customers", "wfirma_products"]),
        ):
            p = tmp / fname
            if not p.exists():
                continue
            with _s.connect(str(p)) as c:
                for t in tables:
                    try:
                        out[t] = c.execute(
                            f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                    except Exception:
                        pass
        return out

    before = _snap()
    r = cli.get(f"/api/v1/proforma/draft/{draft_id}/preview.html")
    assert r.status_code == 200, r.text
    assert "text/html" in r.headers.get("content-type", "")
    after = _snap()
    assert before == after, (
        f"preview.html must be read-only; row counts changed: "
        f"{before} → {after}"
    )


def test_draft_html_preview_contains_human_readable_markers(client):
    cli, tmp = client
    draft_id = _seed_draft_with_line(tmp, batch_id="B-HTML-CONTENT",
                                       client_name="Verhoeven Joaillier",
                                       product_code="EJL/26-27/177-3",
                                       design_no="J4502R01415-PE")
    r = cli.get(f"/api/v1/proforma/draft/{draft_id}/preview.html")
    assert r.status_code == 200
    body = r.text
    # Document is HTML, not raw JSON.
    assert body.lstrip().lower().startswith("<!doctype html>")
    # Carries operator-readable headings + the seeded data.
    for marker in ("Proforma DRAFT", "Verhoeven Joaillier",
                   "EJL/26-27/177-3", "J4502R01415-PE",
                   "Customer mapping", "Lines", "Grand total"):
        assert marker in body, (
            f"preview.html missing human-readable marker {marker!r}"
        )


def test_draft_html_preview_does_not_invoke_wfirma_writes(client, monkeypatch):
    cli, tmp = client
    draft_id = _seed_draft_with_line(tmp, batch_id="B-NW",
                                       client_name="ACME")
    from app.services import wfirma_client as wfc
    write_calls = {"create_proforma": 0, "create_product": 0,
                   "create_customer": 0, "create_invoice": 0}
    def _spy(fn_name):
        def _wrapped(*a, **kw):
            write_calls[fn_name] += 1
            raise RuntimeError(f"preview.html must not call {fn_name}")
        return _wrapped
    for fn in list(write_calls.keys()):
        if hasattr(wfc, fn):
            monkeypatch.setattr(wfc, fn, _spy(fn))

    r = cli.get(f"/api/v1/proforma/draft/{draft_id}/preview.html")
    assert r.status_code == 200, r.text
    assert sum(write_calls.values()) == 0, (
        f"preview.html invoked wFirma writes: {write_calls}"
    )


# ── 14. HTML preview body has no wFirma write surface (source-grep) ─────

def test_draft_html_preview_route_source_has_no_wfirma_writes():
    src = (Path(__file__).resolve().parents[1] / "app" / "api"
           / "routes_proforma.py").read_text(encoding="utf-8")
    start = src.index("def get_proforma_draft_preview_html(")
    end   = src.index("@router.", start + 50)
    body  = src[start:end]
    # Strict guard: no live HTTP client invocations and no wFirma
    # write surfaces. (Plain "POST"/"PATCH"/"DELETE" tokens are allowed
    # in comments — only actual call surfaces matter.)
    for forbidden in (
        "wfirma_client.create_proforma",
        "wfirma_client.create_product",
        "wfirma_client.create_customer",
        "wfirma_client.create_invoice",
        "requests.post", "requests.patch", "requests.delete",
        "httpx.post", "httpx.patch", "httpx.delete",
    ):
        assert forbidden not in body, (
            f"preview.html handler body must not reference {forbidden!r}"
        )
