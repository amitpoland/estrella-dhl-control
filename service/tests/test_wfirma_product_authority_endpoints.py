"""test_wfirma_product_authority_endpoints.py — PR 2 of the search-first
wFirma product authority workflow. Tests the 3 operator-choice write
endpoints + the 6 operator-required test scenarios from 2026-05-23.

Endpoints under test:
  POST /api/v1/wfirma/goods/adopt/{product_code}            — No overwrite
  POST /api/v1/wfirma/goods/update-and-adopt/{product_code} — Yes overwrite
  POST /api/v1/wfirma/goods/create-and-adopt/{product_code} — Missing → create

Operator-required test scenarios (all 6 must pass):
  1. existing product_code → adopt without create
  2. existing product_code + No overwrite → wFirma untouched
  3. existing product_code + Yes overwrite → update existing only
  4. missing product_code → create
  5. unmapped product blocks PZ/Proforma
  6. design_code used only as metadata/description input, never as identity

Plus invariants from the [TASK]:
  * no duplicate creation (409 when /create-and-adopt called on existing)
  * no silent overwrite (/adopt never calls edit_product or create_product)
  * no design_code as product identity (source-grep)
  * no PZ/Proforma while product_code unmapped (block source-grep)
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock
from dataclasses import dataclass

import pytest

_svc = Path(__file__).parent.parent
if str(_svc) not in sys.path:
    sys.path.insert(0, str(_svc))

from fastapi.testclient import TestClient

# Import the app after sys.path is set up.
from app.main import app


PRODUCT_CODE = "EJL/26-27/178-1"
DESIGN_CODE  = "JR08007"


@dataclass
class _WFStub:
    """Minimal WFirmaProduct-shaped stub matching the live dataclass."""
    wfirma_id: str = "99001"
    name:      str = "Pierścionek"
    code:      str = PRODUCT_CODE
    unit:      str = "szt."
    count:     float = 0.0
    reserved:  float = 0.0


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def _disable_api_key(monkeypatch):
    """Disable API-key auth for the test app so we can hit endpoints."""
    from app.core.config import settings
    monkeypatch.setattr(settings, "api_key", "", raising=False)


# ── Operator test 1: existing product → adopt without create ───────────────


def test_existing_product_code_adopts_without_create(_disable_api_key, client, monkeypatch):
    """Operator test 1. wFirma already has the product. /adopt mirrors it
    locally and NEVER calls create_product."""
    from app.services import wfirma_client as wc
    from app.services import wfirma_db as wfdb

    existing = _WFStub(wfirma_id="99001", name="Pierścionek", code=PRODUCT_CODE)
    monkeypatch.setattr(wc, "get_product_by_code", lambda code: existing)

    create_calls = []
    edit_calls   = []
    upsert_calls = []
    monkeypatch.setattr(wc, "create_product",
                        lambda **kw: create_calls.append(kw) or _WFStub())
    monkeypatch.setattr(wc, "edit_product",
                        lambda wfid, **kw: edit_calls.append((wfid, kw)) or {})
    monkeypatch.setattr(wfdb, "upsert_product",
                        lambda **kw: upsert_calls.append(kw) or "id-1")

    r = client.post(f"/api/v1/wfirma/goods/adopt/{PRODUCT_CODE}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["action"] == "adopted"
    assert body["wfirma_product_id"] == "99001"
    assert body["wfirma_untouched"] is True

    # Critical assertions per operator [TASK]
    assert create_calls == [], "adopt must NEVER call create_product"
    assert edit_calls == [],   "adopt must NEVER call edit_product"
    assert len(upsert_calls) == 1, "adopt must mirror locally exactly once"
    assert upsert_calls[0]["wfirma_product_id"] == "99001"
    assert upsert_calls[0]["sync_status"] == "matched"


# ── Operator test 2: No overwrite → wFirma untouched ──────────────────────


def test_no_overwrite_wfirma_untouched(_disable_api_key, client, monkeypatch):
    """Operator test 2. Even when the local expectation differs from the
    wFirma side (operator sees the diff in /search-and-compare), if they
    choose /adopt, wFirma is NOT modified. Local mirror still proceeds."""
    from app.services import wfirma_client as wc
    from app.services import wfirma_db as wfdb

    existing = _WFStub(wfirma_id="99001",
                       name="Different name in wFirma",
                       code=PRODUCT_CODE)
    monkeypatch.setattr(wc, "get_product_by_code", lambda code: existing)
    create_calls = []
    edit_calls   = []
    monkeypatch.setattr(wc, "create_product",
                        lambda **kw: create_calls.append(kw) or _WFStub())
    monkeypatch.setattr(wc, "edit_product",
                        lambda wfid, **kw: edit_calls.append((wfid, kw)) or {})
    monkeypatch.setattr(wfdb, "upsert_product", lambda **kw: "id-1")

    # Operator passes a local_expected that DOES differ from wFirma side —
    # the diff would show in the comparison payload, but the operator
    # has chosen No overwrite, so the wFirma side must stay untouched.
    r = client.post(
        f"/api/v1/wfirma/goods/adopt/{PRODUCT_CODE}",
        json={"name_pl": "Different local expectation", "unit": "szt."},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["action"] == "adopted"
    assert body["wfirma_untouched"] is True
    # Comparison payload surfaces the diff for operator transparency
    assert body["comparison"]["wfirma_present"] is True
    assert len(body["comparison"]["differences"]) >= 1
    # CRITICAL: wFirma side was not touched
    assert create_calls == []
    assert edit_calls   == []


# ── Operator test 3: Yes overwrite → update existing only ─────────────────


def test_yes_overwrite_updates_existing_only(_disable_api_key, client, monkeypatch):
    """Operator test 3. /update-and-adopt calls edit_product (NOT
    create_product). Only the operator-supplied name/description are
    sent to wFirma. Identity fields (code/unit/vat) are not in the
    payload by virtue of edit_product's contract."""
    from app.services import wfirma_client as wc
    from app.services import wfirma_db as wfdb
    from app.core.config import settings

    monkeypatch.setattr(settings, "wfirma_edit_product_allowed", True, raising=False)
    existing = _WFStub(wfirma_id="99001", name="Old name", code=PRODUCT_CODE)
    monkeypatch.setattr(wc, "get_product_by_code", lambda code: existing)
    create_calls = []
    edit_calls   = []
    monkeypatch.setattr(wc, "create_product",
                        lambda **kw: create_calls.append(kw) or _WFStub())
    monkeypatch.setattr(
        wc, "edit_product",
        lambda wfid, **kw: edit_calls.append((wfid, kw)) or {
            "wfirma_id": wfid, "name": kw.get("name", "Old name"),
            "code": PRODUCT_CODE, "unit": "szt.",
        },
    )
    monkeypatch.setattr(wfdb, "upsert_product", lambda **kw: "id-1")

    r = client.post(
        f"/api/v1/wfirma/goods/update-and-adopt/{PRODUCT_CODE}",
        json={"name": "Updated name from operator"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["action"] == "updated_and_adopted"
    assert body["wfirma_product_id"] == "99001"
    assert body["updated_fields"] == ["name"]

    # CRITICAL: edit was called with ONLY the operator-supplied field;
    # create was NEVER called.
    assert create_calls == [], "update-and-adopt must NEVER call create_product"
    assert len(edit_calls) == 1
    edit_id, edit_kwargs = edit_calls[0]
    assert edit_id == "99001"
    assert edit_kwargs == {"name": "Updated name from operator"}


def test_yes_overwrite_blocked_when_flag_off(_disable_api_key, client, monkeypatch):
    """Operator gate: /update-and-adopt returns 403 when
    wfirma_edit_product_allowed is False."""
    from app.services import wfirma_client as wc
    from app.core.config import settings

    monkeypatch.setattr(settings, "wfirma_edit_product_allowed", False, raising=False)
    monkeypatch.setattr(wc, "get_product_by_code", lambda code: _WFStub())
    edit_calls = []
    monkeypatch.setattr(wc, "edit_product",
                        lambda wfid, **kw: edit_calls.append((wfid, kw)) or {})

    r = client.post(
        f"/api/v1/wfirma/goods/update-and-adopt/{PRODUCT_CODE}",
        json={"name": "x"},
    )
    assert r.status_code == 403
    assert "wfirma_edit_product_allowed" in r.text
    assert edit_calls == []


# ── Operator test 4: missing → create ─────────────────────────────────────


def test_missing_product_code_creates(_disable_api_key, client, monkeypatch):
    """Operator test 4. /create-and-adopt: when wFirma doesn't have the
    product AND the flag is on, create it and mirror locally."""
    from app.services import wfirma_client as wc
    from app.services import wfirma_db as wfdb
    from app.services import description_engine as deng
    from app.core.config import settings

    monkeypatch.setattr(settings, "wfirma_create_product_allowed", True, raising=False)
    monkeypatch.setattr(wc, "get_product_by_code", lambda code: None)
    monkeypatch.setattr(wc, "find_vat_code_id", lambda rate: "vat-23-id")
    monkeypatch.setattr(deng, "get_description_block",
                        lambda **kw: {
                            "name_pl": "Pierścionek",
                            "description_line": "Pierścionek / Ring",
                            "description_block": "Block text",
                        })
    create_calls = []
    edit_calls   = []
    monkeypatch.setattr(
        wc, "create_product",
        lambda **kw: create_calls.append(kw) or _WFStub(wfirma_id="new-id"),
    )
    monkeypatch.setattr(wc, "edit_product",
                        lambda wfid, **kw: edit_calls.append((wfid, kw)) or {})
    monkeypatch.setattr(wfdb, "upsert_product", lambda **kw: "id-1")

    r = client.post(
        f"/api/v1/wfirma/goods/create-and-adopt/{PRODUCT_CODE}",
        json={"item_type": "RNG", "description_en": "Ring"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["action"] == "created_and_adopted"
    assert body["wfirma_product_id"] == "new-id"

    assert len(create_calls) == 1
    # The product_code is the identity in the create call
    assert create_calls[0]["product_code"] == PRODUCT_CODE
    # edit was NOT called
    assert edit_calls == []


def test_create_blocked_when_flag_off(_disable_api_key, client, monkeypatch):
    """/create-and-adopt returns 403 when wfirma_create_product_allowed is False."""
    from app.core.config import settings
    monkeypatch.setattr(settings, "wfirma_create_product_allowed", False, raising=False)
    r = client.post(
        f"/api/v1/wfirma/goods/create-and-adopt/{PRODUCT_CODE}",
        json={"item_type": "RNG"},
    )
    assert r.status_code == 403
    assert "wfirma_create_product_allowed" in r.text


# ── Duplicate-prevention invariant: /create-and-adopt refuses if exists ────


def test_create_refuses_when_product_already_in_wfirma(_disable_api_key, client, monkeypatch):
    """Operator [TASK] forbidden: no duplicate creation.
    /create-and-adopt must 409 when wFirma already has the product."""
    from app.services import wfirma_client as wc
    from app.core.config import settings

    monkeypatch.setattr(settings, "wfirma_create_product_allowed", True, raising=False)
    monkeypatch.setattr(wc, "get_product_by_code",
                        lambda code: _WFStub(wfirma_id="already-99001"))
    create_calls = []
    monkeypatch.setattr(wc, "create_product",
                        lambda **kw: create_calls.append(kw) or _WFStub())

    r = client.post(
        f"/api/v1/wfirma/goods/create-and-adopt/{PRODUCT_CODE}",
        json={"item_type": "RNG"},
    )
    assert r.status_code == 409
    body = r.json()["detail"]
    assert body["status"] == "already_in_wfirma"
    assert body["wfirma_product_id"] == "already-99001"
    assert "Refusing to create a duplicate" in body["hint"]
    assert create_calls == [], "duplicate creation must be prevented"


# ── /adopt refuses when wFirma doesn't have the product ───────────────────


def test_adopt_refuses_when_product_not_in_wfirma(_disable_api_key, client, monkeypatch):
    """/adopt must 409 when wFirma has no product — operator should
    use /create-and-adopt instead. Prevents accidental empty mappings."""
    from app.services import wfirma_client as wc
    monkeypatch.setattr(wc, "get_product_by_code", lambda code: None)

    r = client.post(f"/api/v1/wfirma/goods/adopt/{PRODUCT_CODE}")
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert detail["status"] == "not_in_wfirma"
    assert "create-and-adopt" in detail["hint"]


# ── Operator test 5: unmapped product blocks PZ/Proforma ──────────────────


def test_unmapped_product_blocks_pz_and_proforma_via_existing_gate():
    """Operator test 5. Verify the existing PZ + Proforma blocking
    mechanism is in place. The actual blocking is done by:
      - routes_proforma._check_preview_prerequisites (line ~130) returns
        'X product_code(s) unresolved in wfirma_products' as blocking reason
      - routes_wfirma::pz_create (line ~2448) returns 422 with
        unresolved_product_codes when preview.ready is False

    This is a SOURCE-GREP test that pins the gates remain in place. Adding
    real HTTP coverage would require a full SHIPMENT batch fixture which
    is out of scope for this PR — the existing proforma test suite covers
    the integration path. This test ensures the regex/contract holds.
    """
    proforma_src = (
        _svc / "app" / "api" / "routes_proforma.py"
    ).read_text(encoding="utf-8")
    # Proforma block on unresolved product codes
    assert "unresolved in wfirma_products" in proforma_src, (
        "proforma preview gate must surface 'unresolved in wfirma_products' "
        "blocker — operator [TASK] requires unmapped products to block proforma"
    )
    # The gate checks sync_status='matched'
    assert 'sync_status") == "matched"' in proforma_src, (
        "proforma gate must require sync_status='matched' for products"
    )

    wfirma_src = (
        _svc / "app" / "api" / "routes_wfirma.py"
    ).read_text(encoding="utf-8")
    # PZ create gate
    assert "unresolved_product_codes" in wfirma_src, (
        "PZ create endpoint must include unresolved_product_codes "
        "in the 422 not_ready response"
    )
    assert "not_ready" in wfirma_src
    # Status code is 422 for unresolved
    assert "status_code=422" in wfirma_src


# ── Operator test 6: design_code is metadata only, never identity ─────────


def test_design_code_never_used_as_product_identity_in_endpoints():
    """Operator test 6. design_code must NEVER appear as the identity
    parameter in any of the search / adopt / update / create endpoint
    handlers. The product_code is the sole identity authority.

    This is a source-grep over the 3 new endpoint handlers + the
    pre-existing capabilities routes. design_code may appear in
    description / metadata input (passed to deng.get_description_block)
    but never as the wFirma lookup key."""
    routes = (
        _svc / "app" / "api" / "routes_wfirma_capabilities.py"
    ).read_text(encoding="utf-8")

    # Find the 3 new endpoint blocks
    for handler_name in (
        "def adopt_existing_product(",
        "def update_and_adopt_product(",
        "def create_and_adopt_product(",
    ):
        i = routes.find(handler_name)
        assert i >= 0, f"{handler_name} not found in routes"
        # Take the function body (until next def or class at column 0)
        j = routes.find("\n@router.post", i + 1)
        if j < 0:
            j = routes.find("\n# ──", i + 1)
        body = routes[i:j if j > 0 else i + 5000]

        # 1. design_code must NOT be the identity passed to get_product_by_code
        assert "get_product_by_code(design" not in body, (
            f"{handler_name}: design_code must NEVER be used as wFirma "
            f"product identity — product_code is the only authority"
        )
        # 2. design_code must NOT be the path parameter
        assert "{design_code" not in body
        # 3. The identity used is product_code (pc) — verify it's in the body
        assert "get_product_by_code(pc)" in body or "get_product_by_code(product_code" in body


def test_design_code_metadata_acceptable_via_description_engine():
    """Negative-space companion: design_code IS acceptable as an input
    to deng.get_description_block (it builds the human-readable name
    from the design family). This test pins that design_code's only
    legitimate use is descriptive, not identity-bearing."""
    routes = (
        _svc / "app" / "api" / "routes_wfirma_capabilities.py"
    ).read_text(encoding="utf-8")
    # The legacy /create-from-product-code endpoint feeds design via
    # item_type / description_en to deng — that's allowed.
    # Just verify design_code doesn't appear ANYWHERE in the file
    # at the top level as an identity field. (We can't catch every
    # misuse via grep, but we can pin the obvious anti-pattern.)
    for forbidden_pattern in (
        "get_product_by_code(design_code",
        "wfirma_products.product_code = design_code",
        '{"design_code": pc}',
    ):
        assert forbidden_pattern not in routes, (
            f"design_code misused as identity: {forbidden_pattern}"
        )


# ── Source-grep invariants ─────────────────────────────────────────────────


def test_adopt_endpoint_never_calls_create_or_edit():
    """Pin the operator [TASK] forbidden: /adopt path source code
    must not contain calls to create_product or edit_product."""
    src = (
        _svc / "app" / "api" / "routes_wfirma_capabilities.py"
    ).read_text(encoding="utf-8")
    i = src.find("def adopt_existing_product(")
    j = src.find("\n@router.post", i + 1)
    body = src[i:j]
    assert "create_product(" not in body, "/adopt must never call create_product"
    assert "edit_product("   not in body, "/adopt must never call edit_product"


def test_update_and_adopt_endpoint_never_calls_create():
    """Pin: /update-and-adopt edits, never creates."""
    src = (
        _svc / "app" / "api" / "routes_wfirma_capabilities.py"
    ).read_text(encoding="utf-8")
    i = src.find("def update_and_adopt_product(")
    j = src.find("\n@router.post", i + 1)
    body = src[i:j]
    assert "create_product(" not in body, "/update-and-adopt must never call create_product"


def test_create_and_adopt_endpoint_never_calls_edit():
    """Pin: /create-and-adopt creates, never edits."""
    src = (
        _svc / "app" / "api" / "routes_wfirma_capabilities.py"
    ).read_text(encoding="utf-8")
    i = src.find("def create_and_adopt_product(")
    j = src.find("\n# ──", i + 1)
    body = src[i:j if j > 0 else i + 5000]
    assert "edit_product(" not in body, "/create-and-adopt must never call edit_product"
