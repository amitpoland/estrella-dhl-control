"""
test_routes_description_admin.py — description authority admin endpoints.

Tests:
  GET  /api/v1/description-admin/product/{code}           404 / 200 + gate
  POST /api/v1/description-admin/product/{code}/validate  gate PASS / BLOCKED
  PUT  /api/v1/description-admin/product/{code}           saves manual; audit
"""
from __future__ import annotations

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

def test_put_unknown_returns_404(client):
    r = client.put(
        "/api/v1/description-admin/product/DOES-NOT-EXIST",
        headers=_AUTH,
        json={"description_pl": _VALID_PL},
    )
    assert r.status_code == 404


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
