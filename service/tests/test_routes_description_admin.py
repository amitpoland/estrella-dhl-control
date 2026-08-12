"""
test_routes_description_admin.py — description authority admin endpoints.

Tests:
  GET  /api/v1/description-admin/product/{code}           404 / 200 + gate
  POST /api/v1/description-admin/product/{code}/validate  gate PASS / BLOCKED
  POST /api/v1/description-admin/product/{code}/preview   candidate, no write
  POST /api/v1/description-admin/product/{code}/converge-drafts  editable only
  PUT  /api/v1/description-admin/product/{code}           saves manual; first-save OK
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_SVC = Path(__file__).parent.parent
sys.path.insert(0, str(_SVC))

from app.core.config import settings  # noqa: E402


_AUTH = {"X-API-Key": "test-key-secret"}

# Routes use {product_code:path} so slashes in codes are safe — pass them raw.
_PC       = "TEST-001"
_PC_SLASH = "EJL/26-27/292-1"   # real product code pattern with slashes

_VALID_PL = "Pierścionek z 14-karatowego złota (próba 585) z diamentami laboratoryjnymi."
_VALID_EN = "14KT Gold Ring With Laboratory Grown Diamonds. Jewellery."

# EN with "Gold" + "Jewellery" but NO stone word → warning → gate=WARN (not blocked).
_WARN_EN  = "14KT Gold Ring. Jewellery."


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    monkeypatch.setattr(settings, "api_key", "test-key-secret")
    from app.main import app
    with TestClient(app) as c:
        yield c


def _seed(tmp_path: Path, product_code: str = _PC) -> None:
    """Insert a product_descriptions row. Re-inits DB to guarantee correct path."""
    from app.services.document_db import init_document_db, upsert_product_description
    init_document_db(tmp_path / "documents.db")
    upsert_product_description(
        product_code      = product_code,
        item_type         = "RING",
        name_pl           = "Pierścionek",
        description_pl    = _VALID_PL,
        description_en    = "",
        material_pl       = "złoto 14kt",
        purpose_pl        = "Ozdoba.",
        description_block = f"Co to za towar: {_VALID_PL}",
        description_line  = _VALID_PL,
        source            = "auto",
    )


# ── GET ───────────────────────────────────────────────────────────────────────

def test_get_unknown_returns_404(client):
    r = client.get(f"/api/v1/description-admin/product/UNKNOWN-999", headers=_AUTH)
    assert r.status_code == 404


def test_get_known_returns_row_and_gate(client, tmp_path):
    _seed(tmp_path)
    r = client.get(f"/api/v1/description-admin/product/{_PC}", headers=_AUTH)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["product_code"] == _PC
    assert data["description_pl"] == _VALID_PL
    assert data["gate"] in {"PASS", "WARN", "BLOCKED"}
    assert "validation" in data
    assert "rendered_line" in data


# ── POST /validate ────────────────────────────────────────────────────────────

def test_validate_pass(client):
    r = client.post(
        f"/api/v1/description-admin/product/{_PC}/validate",
        headers=_AUTH,
        json={"description_pl": _VALID_PL, "description_en": _VALID_EN},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["gate"] == "PASS"
    assert data["validation"]["ok"] is True
    assert data["validation"]["blocked"] is False
    assert data["rendered_line"] == f"{_VALID_PL} / {_VALID_EN}"


def test_validate_blocked_empty_pl(client):
    r = client.post(
        f"/api/v1/description-admin/product/{_PC}/validate",
        headers=_AUTH,
        json={"description_pl": "", "description_en": ""},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["gate"] == "BLOCKED"
    assert data["validation"]["blocked"] is True


def test_validate_blocked_shorthand(client):
    r = client.post(
        f"/api/v1/description-admin/product/{_PC}/validate",
        headers=_AUTH,
        json={"description_pl": _VALID_PL, "description_en": "LGD Stud Jewell PCS"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["gate"] == "BLOCKED"
    assert data["validation"]["shorthand_detected"] is True


# ── PUT ───────────────────────────────────────────────────────────────────────

def test_put_unknown_pass_creates_canonical_row(client, tmp_path):
    """First-save of a PASS candidate is allowed when no row exists yet."""
    from app.services.document_db import init_document_db
    init_document_db(tmp_path / "documents.db")
    r = client.put(
        f"/api/v1/description-admin/product/{_PC}",
        headers=_AUTH,
        json={"description_pl": _VALID_PL, "description_en": _VALID_EN, "item_type": "RING"},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["source"] == "manual"
    assert data["description_pl"] == _VALID_PL
    assert data["gate"] == "PASS"


def test_put_unknown_blocked_still_422(client, tmp_path):
    from app.services.document_db import init_document_db
    init_document_db(tmp_path / "documents.db")
    r = client.put(
        "/api/v1/description-admin/product/DOES-NOT-EXIST",
        headers=_AUTH,
        json={"description_pl": ""},
    )
    assert r.status_code == 422


def test_put_saves_manual_and_returns_gate_pass(client, tmp_path):
    _seed(tmp_path)
    new_pl = "Pierścionek z 14-karatowego złota próby 585 z diamentami."
    r = client.put(
        f"/api/v1/description-admin/product/{_PC}",
        headers=_AUTH,
        json={"description_pl": new_pl, "description_en": _VALID_EN},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["source"] == "manual"
    assert data["description_pl"] == new_pl
    assert data["description_en"] == _VALID_EN
    assert data["gate"] == "PASS"

    # Verify GET reflects the saved value.
    r2 = client.get(f"/api/v1/description-admin/product/{_PC}", headers=_AUTH)
    assert r2.status_code == 200
    assert r2.json()["source"] == "manual"
    assert r2.json()["description_pl"] == new_pl


def test_put_blocked_returns_422(client, tmp_path):
    _seed(tmp_path)
    r = client.put(
        f"/api/v1/description-admin/product/{_PC}",
        headers=_AUTH,
        json={"description_pl": "", "description_en": ""},
    )
    assert r.status_code == 422, r.text


def test_put_requires_auth(client):
    r = client.put(
        f"/api/v1/description-admin/product/{_PC}",
        json={"description_pl": _VALID_PL},
    )
    assert r.status_code == 401


def test_put_warn_returns_422(client, tmp_path):
    """WARN gate (ok but has warnings) is also rejected — backend mirrors UI canSave=PASS-only."""
    _seed(tmp_path)
    r = client.put(
        f"/api/v1/description-admin/product/{_PC}",
        headers=_AUTH,
        json={"description_pl": _VALID_PL, "description_en": _WARN_EN},
    )
    assert r.status_code == 422, r.text
    data = r.json()
    assert data["detail"]["error"] == "WARN"


def test_slash_product_code_routes(client, tmp_path):
    """Product codes with slashes (EJL/26-27/292-1) work via {product_code:path}."""
    _seed(tmp_path, product_code=_PC_SLASH)

    # GET
    r = client.get(
        f"/api/v1/description-admin/product/{_PC_SLASH}",
        headers=_AUTH,
    )
    assert r.status_code == 200, r.text
    assert r.json()["product_code"] == _PC_SLASH

    # POST /validate
    r = client.post(
        f"/api/v1/description-admin/product/{_PC_SLASH}/validate",
        headers=_AUTH,
        json={"description_pl": _VALID_PL, "description_en": _VALID_EN},
    )
    assert r.status_code == 200
    assert r.json()["gate"] == "PASS"

    # PUT
    r = client.put(
        f"/api/v1/description-admin/product/{_PC_SLASH}",
        headers=_AUTH,
        json={"description_pl": _VALID_PL, "description_en": _VALID_EN},
    )
    assert r.status_code == 200, r.text
    assert r.json()["source"] == "manual"
    assert r.json()["product_code"] == _PC_SLASH


# ── POST /preview (never writes) ──────────────────────────────────────────────

def test_preview_does_not_write_product_descriptions(client, tmp_path):
    from app.services.document_db import init_document_db, get_product_description
    init_document_db(tmp_path / "documents.db")
    r = client.post(
        f"/api/v1/description-admin/product/{_PC}/preview",
        headers=_AUTH,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["wrote"] is False
    assert data["product_code"] == _PC
    assert "candidate" in data
    assert "gate" in data
    assert get_product_description(_PC) is None


def test_preview_does_not_clobber_manual_row(client, tmp_path):
    _seed(tmp_path)
    from app.services.document_db import get_product_description, upsert_product_description
    upsert_product_description(
        product_code=_PC, item_type="RING", name_pl="Pierścionek",
        description_pl=_VALID_PL, description_en=_VALID_EN,
        material_pl="złoto", purpose_pl="Ozdoba.",
        description_block=_VALID_PL, description_line=_VALID_PL,
        source="manual",
    )
    before = get_product_description(_PC)
    r = client.post(
        f"/api/v1/description-admin/product/{_PC}/preview",
        headers=_AUTH,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["wrote"] is False
    assert data["protected_existing"] is True
    after = get_product_description(_PC)
    assert after["description_pl"] == before["description_pl"]
    assert after["source"] == "manual"


def test_converge_drafts_skips_posted_and_fills_editable(client, tmp_path):
    from app.services import document_db as ddb
    from app.services import proforma_invoice_link_db as pildb
    ddb.init_document_db(tmp_path / "documents.db")
    links = tmp_path / "proforma_links.db"
    pildb.init_db(links)
    ddb.upsert_product_description(
        product_code=_PC, item_type="RING", name_pl="Pierścionek",
        description_pl=_VALID_PL, description_en=_VALID_EN,
        material_pl="złoto 14kt", purpose_pl="Ozdoba.",
        description_block=_VALID_PL, description_line=_VALID_PL,
        source="manual",
    )
    editable, _ = pildb.auto_create_draft_from_sales_packing(
        links, batch_id="B1", client_name="Client A", currency="EUR",
        lines=[{"product_code": _PC, "design_no": "D1", "qty": 2,
                "unit_price": 10.0, "currency": "EUR", "name_pl": ""}],
        operator="test",
    )
    posted, _ = pildb.auto_create_draft_from_sales_packing(
        links, batch_id="B1", client_name="Client B", currency="EUR",
        lines=[{"product_code": _PC, "design_no": "D2", "qty": 9,
                "unit_price": 99.0, "currency": "EUR", "name_pl": "KEEP"}],
        operator="test",
    )
    with sqlite3.connect(str(links)) as con:
        con.execute(
            "UPDATE proforma_drafts SET draft_state='posted', status='issued' WHERE id=?",
            (posted.id,),
        )
        con.commit()

    r = client.post(
        f"/api/v1/description-admin/product/{_PC}/converge-drafts",
        headers=_AUTH,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["drafts_enriched"] == 1
    assert body["drafts_skipped_locked"] >= 1

    ed = pildb.get_draft_by_id(links, editable.id)
    elines = json.loads(ed.editable_lines_json)
    assert elines[0]["qty"] == 2
    assert elines[0]["unit_price"] == 10.0
    assert elines[0]["product_code"] == _PC
    assert _VALID_PL[:20] in (elines[0].get("name_pl") or "")

    pd = pildb.get_draft_by_id(links, posted.id)
    plines = json.loads(pd.editable_lines_json)
    assert pd.draft_state == "posted"
    assert plines[0]["qty"] == 9
    assert plines[0]["unit_price"] == 99.0
    assert plines[0]["name_pl"] == "KEEP"

    r2 = client.post(
        f"/api/v1/description-admin/product/{_PC}/converge-drafts",
        headers=_AUTH,
    )
    assert r2.status_code == 200
    assert r2.json()["drafts_enriched"] == 1

