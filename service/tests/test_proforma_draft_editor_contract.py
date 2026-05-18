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


# ── 15. buyer_override saves dict (never "[object Object]") ─────────────

def _patch_fields(cli: TestClient, draft_id: int, expected: str, patch: dict):
    return cli.patch(
        f"/api/v1/proforma/draft/{draft_id}",
        json={"expected_updated_at": expected, "patch": patch},
        headers={"X-Operator": "tester@local"},
    )


def test_patch_buyer_override_saves_object_never_object_object(client):
    cli, tmp = client
    draft_id = _seed_draft_with_line(tmp, batch_id="B-BUY",
                                       client_name="ACME")
    d = _get_draft(cli, draft_id)
    buyer = {"type": "company", "name": "ACME Sp. z o.o.",
             "vat_id": "PL1234567890", "country": "PL",
             "city": "Warszawa", "street": "ul. Główna 1"}
    r = _patch_fields(cli, draft_id, d["updated_at"],
                      {"buyer_override": buyer})
    assert r.status_code == 200, r.text
    d2 = _get_draft(cli, draft_id)
    bo = d2.get("buyer_override")
    assert isinstance(bo, dict), \
        f"buyer_override must round-trip as dict; got {type(bo).__name__}"
    assert bo.get("type") == "company"
    assert bo.get("name") == "ACME Sp. z o.o."
    assert bo.get("vat_id") == "PL1234567890"
    # JSON-string serialisation must not regress to "[object Object]"
    assert "[object Object]" not in json.dumps(bo)


def test_patch_ship_to_override_saves_object_never_object_object(client):
    cli, tmp = client
    draft_id = _seed_draft_with_line(tmp, batch_id="B-SHIP",
                                       client_name="ACME")
    d = _get_draft(cli, draft_id)
    ship = {"type": "individual", "name": "Jan Kowalski",
            "country": "PL", "city": "Kraków",
            "street": "ul. Krakowska 5", "zip": "30-001"}
    r = _patch_fields(cli, draft_id, d["updated_at"],
                      {"ship_to_override": ship})
    assert r.status_code == 200, r.text
    d2 = _get_draft(cli, draft_id)
    so = d2.get("ship_to_override")
    assert isinstance(so, dict)
    assert so.get("type") == "individual"
    assert so.get("name") == "Jan Kowalski"
    assert "[object Object]" not in json.dumps(so)


def test_payment_terms_saves_days_method_note(client):
    cli, tmp = client
    draft_id = _seed_draft_with_line(tmp, batch_id="B-PT",
                                       client_name="ACME")
    d = _get_draft(cli, draft_id)
    terms = {"days": "30", "method": "transfer",
             "note": "Net 30, bank transfer EUR account"}
    r = _patch_fields(cli, draft_id, d["updated_at"],
                      {"payment_terms": terms})
    assert r.status_code == 200, r.text
    d2 = _get_draft(cli, draft_id)
    pt = d2.get("payment_terms")
    assert isinstance(pt, dict)
    assert pt.get("days")   == "30"
    assert pt.get("method") == "transfer"
    assert pt.get("note")   == "Net 30, bank transfer EUR account"


# ── 16. /product-options endpoint shape + local-only behaviour ──────────

def test_product_options_endpoint_returns_local_master_codes(client):
    cli, tmp = client
    # Seed document_db with a couple of product_descriptions rows.
    from app.services import document_db as ddb
    ddb.init_document_db(tmp / "documents.db")
    ddb.upsert_product_description(
        product_code="EJL/PO-1", item_type="RING",
        name_pl="pierścionek złoty",
        description_pl="", material_pl="złoto 14k",
        purpose_pl="", description_block="", source="auto",
    )
    ddb.upsert_product_description(
        product_code="EJL/PO-2", item_type="EARRING",
        name_pl="kolczyki srebrne",
        description_pl="", material_pl="srebro",
        purpose_pl="", description_block="", source="auto",
    )
    r = cli.get("/api/v1/proforma/product-options")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("ok") is True
    opts = body.get("options") or []
    codes = [o.get("product_code") for o in opts]
    assert "EJL/PO-1" in codes
    assert "EJL/PO-2" in codes
    by_pc = {o["product_code"]: o for o in opts}
    assert by_pc["EJL/PO-1"]["item_type"] == "RING"
    assert by_pc["EJL/PO-1"]["name_pl"]   == "pierścionek złoty"
    # design_no slot always present (may be empty when no product_master row)
    assert "design_no" in by_pc["EJL/PO-1"]


def test_product_options_endpoint_is_read_only(client):
    cli, tmp = client
    from app.services import document_db as ddb
    ddb.init_document_db(tmp / "documents.db")
    ddb.upsert_product_description(
        product_code="EJL/RO-1", item_type="RING", name_pl="ring",
        description_pl="", material_pl="", purpose_pl="",
        description_block="", source="auto",
    )

    def _snap():
        out = {}
        for fname, tables in (
            ("documents.db",      ["product_descriptions"]),
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
    for _ in range(3):
        cli.get("/api/v1/proforma/product-options")
    after = _snap()
    assert before == after, (
        f"/product-options must be read-only; row counts changed: "
        f"{before} → {after}"
    )


def test_product_options_endpoint_source_has_no_external_calls():
    src = (Path(__file__).resolve().parents[1] / "app" / "api"
           / "routes_proforma.py").read_text(encoding="utf-8")
    start = src.index("def list_proforma_product_options(")
    end   = src.index("@router.", start + 50)
    body  = src[start:end]
    for forbidden in (
        "requests.", "httpx.", "wfirma_client",
        "create_product", "create_customer", "send_email",
    ):
        assert forbidden not in body, (
            f"list_proforma_product_options must not reference {forbidden!r}"
        )


# ── 17. GET /draft enrichment from product_descriptions (no writes) ─────

def test_draft_get_enriches_blank_item_type_and_name_pl(client):
    cli, tmp = client
    from app.services import document_db as ddb
    ddb.init_document_db(tmp / "documents.db")
    ddb.upsert_product_description(
        product_code="EJL/EN-1", item_type="BRACELET",
        name_pl="bransoletka złota",
        description_pl="", material_pl="", purpose_pl="",
        description_block="", source="auto",
    )
    draft_id = _seed_draft_with_line(tmp, batch_id="B-EN",
                                       client_name="ACME",
                                       product_code="EJL/EN-1")
    # Clear blank-out item_type/name_pl on the seeded row to force enrichment.
    db = tmp / "proforma_links.db"
    with _s.connect(str(db)) as con:
        row = con.execute(
            "SELECT editable_lines_json FROM proforma_drafts WHERE id=?",
            (draft_id,)).fetchone()
        lines = json.loads(row[0])
        for ln in lines:
            ln["item_type"] = ""
            ln["name_pl"]   = ""
        con.execute(
            "UPDATE proforma_drafts SET editable_lines_json=? WHERE id=?",
            (json.dumps(lines, sort_keys=True), draft_id))
        con.commit()

    d = _get_draft(cli, draft_id)
    ln0 = d["editable_lines"][0]
    assert ln0["item_type"] == "BRACELET", \
        f"GET draft should enrich blank item_type from product_descriptions; " \
        f"got {ln0!r}"
    assert ln0["name_pl"] == "bransoletka złota"


def test_draft_get_does_not_overwrite_existing_item_type(client):
    cli, tmp = client
    from app.services import document_db as ddb
    ddb.init_document_db(tmp / "documents.db")
    ddb.upsert_product_description(
        product_code="EJL/OV-1", item_type="RING_CANONICAL",
        name_pl="canonical_name",
        description_pl="", material_pl="", purpose_pl="",
        description_block="", source="auto",
    )
    draft_id = _seed_draft_with_line(tmp, batch_id="B-OV",
                                       client_name="ACME",
                                       product_code="EJL/OV-1")
    # Operator already set item_type — must be preserved on GET.
    d = _get_draft(cli, draft_id)
    _patch_line(cli, draft_id, 1, d["updated_at"],
                {"item_type": "OPERATOR_OVERRIDE",
                 "name_pl":   "operator name"})
    d2 = _get_draft(cli, draft_id)
    ln0 = d2["editable_lines"][0]
    assert ln0["item_type"] == "OPERATOR_OVERRIDE", \
        "Enrichment must not overwrite operator-supplied item_type"
    assert ln0["name_pl"]   == "operator name", \
        "Enrichment must not overwrite operator-supplied name_pl"


def test_draft_get_enrichment_does_not_write_back(client):
    cli, tmp = client
    from app.services import document_db as ddb
    ddb.init_document_db(tmp / "documents.db")
    ddb.upsert_product_description(
        product_code="EJL/RB-1", item_type="NECKLACE",
        name_pl="naszyjnik",
        description_pl="", material_pl="", purpose_pl="",
        description_block="", source="auto",
    )
    draft_id = _seed_draft_with_line(tmp, batch_id="B-RB",
                                       client_name="ACME",
                                       product_code="EJL/RB-1")
    # Blank the columns
    db = tmp / "proforma_links.db"
    with _s.connect(str(db)) as con:
        row = con.execute(
            "SELECT editable_lines_json FROM proforma_drafts WHERE id=?",
            (draft_id,)).fetchone()
        lines = json.loads(row[0])
        for ln in lines:
            ln["item_type"] = ""
            ln["name_pl"]   = ""
        con.execute(
            "UPDATE proforma_drafts SET editable_lines_json=? WHERE id=?",
            (json.dumps(lines, sort_keys=True), draft_id))
        con.commit()
    # GET multiple times
    for _ in range(3):
        cli.get(f"/api/v1/proforma/draft/{draft_id}")
    # Stored row must still be blank — enrichment is projection only.
    with _s.connect(str(db)) as con:
        row = con.execute(
            "SELECT editable_lines_json FROM proforma_drafts WHERE id=?",
            (draft_id,)).fetchone()
        lines = json.loads(row[0])
    assert lines[0]["item_type"] == "", \
        "GET enrichment must not write back to editable_lines_json"
    assert lines[0]["name_pl"]   == ""


# ── 18. Service-charge add: freight + insurance ─────────────────────────

def test_freight_charge_add_works(client):
    cli, tmp = client
    draft_id = _seed_draft_with_line(tmp, batch_id="B-FR",
                                       client_name="ACME")
    d = _get_draft(cli, draft_id)
    r = cli.post(
        f"/api/v1/proforma/draft/{draft_id}/service-charges",
        json={"expected_updated_at": d["updated_at"],
              "charge": {"charge_type": "freight", "amount": 75.0,
                         "currency": "USD", "label": "DHL Express"}},
        headers={"X-Operator": "tester@local"},
    )
    assert r.status_code == 200, r.text
    d2 = _get_draft(cli, draft_id)
    charges = d2.get("service_charges") or []
    types   = [c.get("charge_type") for c in charges]
    assert "freight" in types


def test_insurance_charge_add_works(client):
    cli, tmp = client
    draft_id = _seed_draft_with_line(tmp, batch_id="B-INS",
                                       client_name="ACME")
    d = _get_draft(cli, draft_id)
    r = cli.post(
        f"/api/v1/proforma/draft/{draft_id}/service-charges",
        json={"expected_updated_at": d["updated_at"],
              "charge": {"charge_type": "insurance", "amount": 25.0,
                         "currency": "USD", "label": "Cargo insurance"}},
        headers={"X-Operator": "tester@local"},
    )
    assert r.status_code == 200, r.text
    d2 = _get_draft(cli, draft_id)
    charges = d2.get("service_charges") or []
    types   = [c.get("charge_type") for c in charges]
    assert "insurance" in types


# ── 19. HTML preview includes buyer / ship-to / payment terms / charges ─

def test_html_preview_includes_buyer_ship_to_payment_terms_charges(client):
    cli, tmp = client
    draft_id = _seed_draft_with_line(tmp, batch_id="B-HTML-FULL",
                                       client_name="Verhoeven Joaillier",
                                       product_code="EJL/HT-1")
    d = _get_draft(cli, draft_id)
    # Fill buyer, ship-to, payment-terms.
    _patch_fields(cli, draft_id, d["updated_at"], {
        "buyer_override":   {"type": "company",
                              "name": "ACME Buyer",
                              "vat_id": "PL9999999999",
                              "city": "Warszawa"},
    })
    d = _get_draft(cli, draft_id)
    _patch_fields(cli, draft_id, d["updated_at"], {
        "ship_to_override": {"type": "individual",
                              "name": "Jan Recipient",
                              "city": "Kraków"},
    })
    d = _get_draft(cli, draft_id)
    _patch_fields(cli, draft_id, d["updated_at"], {
        "payment_terms":    {"days": "14", "method": "transfer",
                              "note": "Net 14"},
    })
    d = _get_draft(cli, draft_id)
    cli.post(
        f"/api/v1/proforma/draft/{draft_id}/service-charges",
        json={"expected_updated_at": d["updated_at"],
              "charge": {"charge_type": "freight", "amount": 99.0,
                         "currency": "USD", "label": "Courier"}},
        headers={"X-Operator": "tester@local"},
    )

    r = cli.get(f"/api/v1/proforma/draft/{draft_id}/preview.html")
    assert r.status_code == 200, r.text
    body = r.text
    for marker in ("ACME Buyer", "Jan Recipient",
                   "Courier"):
        assert marker in body, (
            f"preview.html must contain operator-readable marker {marker!r}"
        )


# ── 20. UI surfaces — customer picker + type radio + product datalist ──

def test_ui_source_includes_customer_picker_and_type_selectors():
    src = (Path(__file__).resolve().parents[1] / "app" / "static"
           / "shipment-detail.html").read_text(encoding="utf-8")
    for marker in (
        "draft-buyer-customer-picker",
        "draft-ship-to-customer-picker",
        "proforma-add-line-product-codes",   # datalist for Add-line
        "ProformaCustomerPicker",
        "ProformaAddLineForm",
    ):
        assert marker in src, (
            f"shipment-detail.html missing {marker!r} — customer/product "
            f"selector wiring not present"
        )


def test_ui_source_does_not_invoke_wfirma_or_pz_post_from_editor():
    """Source-grep: the proforma draft editor section must not call any
    write/post path against wFirma / PZ / DHL / customs."""
    src = (Path(__file__).resolve().parents[1] / "app" / "static"
           / "shipment-detail.html").read_text(encoding="utf-8")
    # Look at the slice from ProformaDraftPanel to the closing of the file
    # for forbidden client-side write paths.  These tokens never appear in
    # legit editor code; presence means a regression.
    start = src.index("function ProformaDraftPanel(")
    panel = src[start:]
    forbidden = (
        "/api/v1/proforma/post",
        "/api/v1/proforma/create",
        "/api/v1/pz/process",
        "/api/v1/dhl/",
    )
    for bad in forbidden:
        assert bad not in panel, (
            f"Proforma draft editor must not invoke {bad!r}"
        )


# ── 21. ProformaDraftAddChargeForm uses e.target.value extraction ───────
#       (companion fix to PR #200 — service-charge add form was the one
#       remaining SyntheticEvent surface in the editor).

def test_charge_form_source_uses_event_target_value_extraction():
    """The service-charge add form (ProformaDraftAddChargeForm) must
    extract e.target.value from every onChange handler.  Passing the
    React setter directly stores a SyntheticEvent in state — which
    JSON-stringifies to the literal '[object Object]'.  This is a
    source-grep guard over the function body."""
    src = (Path(__file__).resolve().parents[1] / "app" / "static"
           / "shipment-detail.html").read_text(encoding="utf-8")
    start = src.index("function ProformaDraftAddChargeForm(")
    end   = src.index("\n}\n", start) + 2
    body  = src[start:end]
    for bad in (
        "onChange={setType}",
        "onChange={setAmount}",
        "onChange={setCcy}",
        "onChange={setLabel}",
    ):
        assert bad not in body, (
            f"ProformaDraftAddChargeForm contains broken handler {bad!r}; "
            f"must use (e) => setter(e.target.value)"
        )
    for required in (
        "setType(e.target.value)",
        "setAmount(e.target.value)",
        "setCcy(",                        # accepts toUpperCase wrapper
        "setLabel(e.target.value)",
    ):
        assert required in body, (
            f"ProformaDraftAddChargeForm missing {required!r} — "
            f"event extraction not wired correctly"
        )


def test_charge_form_ccy_handler_uppercases_value_not_event():
    """The currency input wrapper must read e.target.value before
    .toUpperCase() — calling toUpperCase() on a SyntheticEvent crashes
    at runtime."""
    src = (Path(__file__).resolve().parents[1] / "app" / "static"
           / "shipment-detail.html").read_text(encoding="utf-8")
    start = src.index("function ProformaDraftAddChargeForm(")
    end   = src.index("\n}\n", start) + 2
    body  = src[start:end]
    assert "(v) => setCcy(v.toUpperCase())" not in body, (
        "Broken ccy handler '(v) => setCcy(v.toUpperCase())' still present"
    )
    assert "e.target.value" in body and "toUpperCase" in body, (
        "ccy handler must extract e.target.value before toUpperCase()"
    )


def test_freight_charge_endpoint_stores_clean_strings_and_numbers(client):
    """Round-trip a freight charge through POST → GET and assert clean
    types + no '[object Object]' literal in serialised charges JSON."""
    cli, tmp = client
    draft_id = _seed_draft_with_line(tmp, batch_id="B-CHG-FR",
                                       client_name="ACME")
    d = _get_draft(cli, draft_id)
    r = cli.post(
        f"/api/v1/proforma/draft/{draft_id}/service-charges",
        json={"expected_updated_at": d["updated_at"],
              "charge": {"charge_type": "freight",
                         "amount": 100.0,
                         "currency": "USD",
                         "label": "DHL Express"}},
        headers={"X-Operator": "tester@local"},
    )
    assert r.status_code == 200, r.text
    d2 = _get_draft(cli, draft_id)
    charges = d2.get("service_charges") or []
    fr = next((c for c in charges if c.get("charge_type") == "freight"),
                None)
    assert fr is not None, f"freight row missing: {charges!r}"
    assert fr.get("currency") == "USD"
    assert isinstance(fr.get("amount"), (int, float))
    assert float(fr.get("amount")) == 100.0
    assert fr.get("label") == "DHL Express"
    assert "[object Object]" not in json.dumps(charges), \
        f"service-charges round-trip emitted [object Object]: {charges!r}"


def test_insurance_charge_endpoint_stores_clean_strings_and_numbers(client):
    cli, tmp = client
    draft_id = _seed_draft_with_line(tmp, batch_id="B-CHG-INS",
                                       client_name="ACME")
    d = _get_draft(cli, draft_id)
    r = cli.post(
        f"/api/v1/proforma/draft/{draft_id}/service-charges",
        json={"expected_updated_at": d["updated_at"],
              "charge": {"charge_type": "insurance",
                         "amount": 25.5,
                         "currency": "USD",
                         "label": "Cargo insurance"}},
        headers={"X-Operator": "tester@local"},
    )
    assert r.status_code == 200, r.text
    d2 = _get_draft(cli, draft_id)
    charges = d2.get("service_charges") or []
    ins = next((c for c in charges if c.get("charge_type") == "insurance"),
                None)
    assert ins is not None, f"insurance row missing: {charges!r}"
    assert ins.get("currency") == "USD"
    assert float(ins.get("amount")) == 25.5
    assert ins.get("label") == "Cargo insurance"
    assert "[object Object]" not in json.dumps(charges)


def test_service_charges_json_never_contains_object_object_literal(client):
    """Source-of-truth guard: the proforma_drafts.service_charges_json
    column on disk must never carry the broken '[object Object]'
    literal that SyntheticEvent serialisation used to emit."""
    cli, tmp = client
    draft_id = _seed_draft_with_line(tmp, batch_id="B-NOJ",
                                       client_name="ACME")
    d = _get_draft(cli, draft_id)
    for ct, amt, ccy, lab in (
        ("freight",   75.0, "USD", "Courier"),
        ("insurance", 12.5, "USD", "Insure"),
    ):
        r = cli.post(
            f"/api/v1/proforma/draft/{draft_id}/service-charges",
            json={"expected_updated_at": d["updated_at"],
                  "charge": {"charge_type": ct, "amount": amt,
                             "currency": ccy, "label": lab}},
            headers={"X-Operator": "tester@local"},
        )
        assert r.status_code == 200, r.text
        d = _get_draft(cli, draft_id)
    db = tmp / "proforma_links.db"
    with _s.connect(str(db)) as con:
        row = con.execute(
            "SELECT service_charges_json FROM proforma_drafts WHERE id=?",
            (draft_id,)).fetchone()
    assert row is not None, "draft row missing"
    raw = row[0] or "[]"
    assert "[object Object]" not in raw, (
        f"service_charges_json contains broken literal: {raw!r}"
    )
    persisted = json.loads(raw)
    assert isinstance(persisted, list) and len(persisted) >= 2, (
        f"expected ≥2 charges persisted, got {persisted!r}"
    )
    for c in persisted:
        for k, v in c.items():
            assert "[object Object]" not in str(v), (
                f"service_charges_json {k}={v!r} contains broken literal"
            )
