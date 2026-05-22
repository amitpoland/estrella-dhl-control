"""test_wfirma_product_compare.py — search-first product authority
foundation: pure comparison of wFirma product vs local expectation.

This PR (foundation) ships only the comparison helper + a read-only
search-and-compare endpoint. NO write behaviour is changed. Future PRs
will add /adopt, /update-and-adopt, /create endpoints that consume the
same comparison output gated on operator confirmation.

The operator-stated workflow (2026-05-23) is:

    Product required → Search wFirma → Found?
        ├─ Yes → adopt → compare metadata → ask before update
        └─ No  → create

This module implements only the "compare metadata" sub-step.

Tests cover:
  1. wFirma missing → recommendation = create_new
  2. wFirma found, no local context → recommendation = no_local_context
  3. wFirma found, identical metadata → recommendation = adopt_as_is
  4. wFirma found, whitespace-only drift → recommendation = adopt_with_warning
  5. wFirma found, case-only drift on name → recommendation = adopt_with_warning
  6. wFirma found, unit drift "szt." vs "szt" → minor drift (trailing dot)
  7. wFirma found, material name drift → recommendation = operator_review
  8. wFirma found, material code drift → recommendation = operator_review
  9. Stock fields surface as informational (not part of diff)
 10. Production-shape regression: EJL/26-27/178-1 / JR08007 with
     expected master name "Pierścionek z brylantami i kamieniami szlachetnymi"
     vs hypothetical wFirma response — operator_review when material drift
 11. Helper is read-only (source grep — no INSERT/UPDATE/DELETE)
 12. Endpoint wired in routes_wfirma_capabilities.py (source grep)
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

_svc = Path(__file__).parent.parent
if str(_svc) not in sys.path:
    sys.path.insert(0, str(_svc))

from app.services.wfirma_product_compare import compare_product_metadata


# ── fixture: minimal WFirmaProduct-shaped stub for unit tests ───────────────
#
# The real WFirmaProduct dataclass lives in wfirma_client.py and imports the
# full wFirma client at module load. Using a plain dataclass stub keeps the
# unit tests fast + isolated. The comparator's duck-typing helper (`_g`)
# already accepts dicts and SimpleNamespace too, so this is shape-compatible
# with the real production object.


@dataclass
class WFStub:
    wfirma_id: str = ""
    name:      str = ""
    code:      str = ""
    unit:      str = "szt."
    count:     float = 0.0
    reserved:  float = 0.0


PRODUCT_CODE = "EJL/26-27/178-1"
DESIGN       = "JR08007"


# ── 1. wFirma missing → create_new ─────────────────────────────────────────


def test_missing_wfirma_product_recommends_create_new():
    r = compare_product_metadata(
        wfirma_product = None,
        local_expected = {"name_pl": "Pierścionek z brylantami"},
        product_code   = PRODUCT_CODE,
    )
    assert r["wfirma_present"] is False
    assert r["recommendation"] == "create_new"
    assert "no product for code" in r["advisory"]
    assert PRODUCT_CODE in r["advisory"]
    assert "WFIRMA_CREATE_PRODUCT_ALLOWED" in r["advisory"]
    assert r["differences"] == []


# ── 2. wFirma found, no local context → no_local_context ────────────────────


def test_no_local_context_recommends_no_local_context():
    wf = WFStub(wfirma_id="99001", name="Pierścionek", code=PRODUCT_CODE, unit="szt.")
    r = compare_product_metadata(
        wfirma_product = wf,
        local_expected = None,
        product_code   = PRODUCT_CODE,
    )
    assert r["wfirma_present"] is True
    assert r["wfirma_product_id"] == "99001"
    assert r["recommendation"] == "no_local_context"
    assert r["differences"] == []
    assert "nothing to compare" in r["advisory"]


# ── 3. Identical → adopt_as_is ─────────────────────────────────────────────


def test_identical_metadata_recommends_adopt_as_is():
    wf = WFStub(wfirma_id="99001", name="Pierścionek", code=PRODUCT_CODE, unit="szt.")
    r = compare_product_metadata(
        wfirma_product = wf,
        local_expected = {
            "product_code": PRODUCT_CODE,
            "name_pl":      "Pierścionek",
            "unit":         "szt.",
        },
        product_code   = PRODUCT_CODE,
    )
    assert r["identical"] is True
    assert r["recommendation"] == "adopt_as_is"
    assert r["differences"] == []
    assert "Safe to adopt verbatim" in r["advisory"]


# ── 4. Whitespace-only drift → minor → adopt_with_warning ──────────────────


def test_whitespace_only_drift_is_minor():
    wf = WFStub(wfirma_id="99001", name="Pierścionek", code=PRODUCT_CODE)
    r = compare_product_metadata(
        wfirma_product = wf,
        local_expected = {"product_code": PRODUCT_CODE, "name_pl": "  Pierścionek  "},
        product_code   = PRODUCT_CODE,
    )
    assert r["recommendation"] == "adopt_with_warning"
    assert len(r["differences"]) == 1
    d = r["differences"][0]
    assert d["field"] == "name"
    assert d["severity"] == "minor"
    assert d["normalised_match"] is True


# ── 5. Case-only drift on name → minor ─────────────────────────────────────


def test_case_only_name_drift_is_minor():
    wf = WFStub(wfirma_id="99001", name="PIERŚCIONEK", code=PRODUCT_CODE)
    r = compare_product_metadata(
        wfirma_product = wf,
        local_expected = {"product_code": PRODUCT_CODE, "name_pl": "Pierścionek"},
        product_code   = PRODUCT_CODE,
    )
    assert r["recommendation"] == "adopt_with_warning"
    assert all(d["severity"] == "minor" for d in r["differences"])


# ── 6. Unit "szt." vs "szt" → minor (trailing dot stripped) ────────────────


def test_unit_trailing_dot_is_minor_not_material():
    wf = WFStub(wfirma_id="99001", name="Pierścionek", code=PRODUCT_CODE, unit="szt")
    r = compare_product_metadata(
        wfirma_product = wf,
        local_expected = {
            "product_code": PRODUCT_CODE,
            "name_pl":      "Pierścionek",
            "unit":         "szt.",
        },
        product_code   = PRODUCT_CODE,
    )
    # name + code identical; unit differs only by trailing dot → minor
    assert r["recommendation"] == "adopt_with_warning"
    unit_diffs = [d for d in r["differences"] if d["field"] == "unit"]
    assert len(unit_diffs) == 1
    assert unit_diffs[0]["severity"] == "minor"


# ── 7. Material name drift → operator_review ───────────────────────────────


def test_material_name_drift_requires_operator_review():
    wf = WFStub(wfirma_id="99001",
                name="Złoty pierścionek z diamentami próby 750",
                code=PRODUCT_CODE)
    r = compare_product_metadata(
        wfirma_product = wf,
        local_expected = {
            "product_code": PRODUCT_CODE,
            "name_pl":      "Pierścionek z brylantami",
        },
        product_code   = PRODUCT_CODE,
    )
    assert r["recommendation"] == "operator_review"
    assert "differs materially" in r["advisory"]
    assert "name" in r["advisory"]
    assert "WFIRMA_PRODUCT_UPDATE_ALLOWED" in r["advisory"]
    name_diffs = [d for d in r["differences"] if d["field"] == "name"]
    assert len(name_diffs) == 1
    assert name_diffs[0]["severity"] == "material"


# ── 8. Material code drift → operator_review ───────────────────────────────


def test_material_code_drift_requires_operator_review():
    """wFirma returned a product whose code disagrees with what we asked
    for — this is unusual but possible (operator typo, wFirma side-rename).
    Material — operator must review."""
    wf = WFStub(wfirma_id="99001", name="Pierścionek",
                code="EJL/26-27/177-99")  # wrong
    r = compare_product_metadata(
        wfirma_product = wf,
        local_expected = {
            "product_code": PRODUCT_CODE,
            "name_pl":      "Pierścionek",
        },
        product_code   = PRODUCT_CODE,
    )
    assert r["recommendation"] == "operator_review"
    code_diffs = [d for d in r["differences"] if d["field"] == "code"]
    assert len(code_diffs) == 1
    assert code_diffs[0]["severity"] == "material"


# ── 9. Stock fields are informational, not part of diff ────────────────────


def test_stock_fields_surface_as_informational_only():
    wf = WFStub(wfirma_id="99001", name="Pierścionek", code=PRODUCT_CODE,
                unit="szt.", count=5.0, reserved=2.0)
    r = compare_product_metadata(
        wfirma_product = wf,
        local_expected = {
            "product_code": PRODUCT_CODE,
            "name_pl":      "Pierścionek",
            "unit":         "szt.",
        },
        product_code   = PRODUCT_CODE,
    )
    # Stock present + populated
    assert r["wfirma_stock"] == {"count": 5.0, "reserved": 2.0, "available": 3.0}
    # But NO diff entry for count/reserved/available
    for d in r["differences"]:
        assert d["field"] not in ("count", "reserved", "available")


# ── 10. Production-shape regression: EJL/26-27/178-1 / JR08007 ─────────────


def test_production_shape_ejl_178_1_jr08007_operator_review_when_material():
    """The actual missing product from SHIPMENT_4218922912. If wFirma later
    grows a product under this code with a different name, the workflow
    must surface operator_review rather than silently adopting."""
    wf = WFStub(
        wfirma_id = "212121",  # hypothetical wFirma id once registered
        name      = "Different product name set by wFirma operator",
        code      = PRODUCT_CODE,
        unit      = "szt.",
    )
    r = compare_product_metadata(
        wfirma_product = wf,
        local_expected = {
            "product_code": PRODUCT_CODE,
            "name_pl":      "Pierścionek z brylantami i kamieniami szlachetnymi",
            "unit":         "szt.",
        },
        product_code   = PRODUCT_CODE,
    )
    assert r["recommendation"] == "operator_review"
    assert r["wfirma_product_id"] == "212121"
    assert any(d["field"] == "name" and d["severity"] == "material"
               for d in r["differences"])


def test_production_shape_ejl_178_1_jr08007_missing_recommends_create():
    """The current production state — wFirma has no product for
    EJL/26-27/178-1 yet. Compare returns recommendation=create_new
    so the future /create endpoint knows to gate on
    WFIRMA_CREATE_PRODUCT_ALLOWED + operator confirmation."""
    r = compare_product_metadata(
        wfirma_product = None,
        local_expected = {
            "product_code": PRODUCT_CODE,
            "name_pl":      "Pierścionek z brylantami i kamieniami szlachetnymi",
            "unit":         "szt.",
        },
        product_code   = PRODUCT_CODE,
    )
    assert r["recommendation"] == "create_new"


# ── 11. Read-only invariant ────────────────────────────────────────────────


def test_helper_module_is_read_only():
    """compare_product_metadata must never INSERT/UPDATE/DELETE anything."""
    helper = _svc / "app" / "services" / "wfirma_product_compare.py"
    src = helper.read_text(encoding="utf-8")
    for forbidden in ("INSERT", "UPDATE ", "DELETE ", "DROP ", "REPLACE INTO"):
        assert forbidden not in src.upper(), (
            f"wfirma_product_compare must be read-only; found {forbidden!r}"
        )
    # Also: no sqlite import, no requests/http import, no wfirma_client
    # writes. The module is pure logic over input dicts/dataclasses.
    assert "import sqlite3" not in src
    assert "wfdb.upsert" not in src
    assert "wfirma_client.create_product" not in src


# ── 12. Endpoint wired into routes_wfirma_capabilities.py ──────────────────


def test_search_and_compare_endpoint_wired():
    """Pin that the new GET /goods/search-and-compare endpoint exists and
    calls the new helper. Without this wiring the helper is dead code."""
    routes = _svc / "app" / "api" / "routes_wfirma_capabilities.py"
    src = routes.read_text(encoding="utf-8")
    # Endpoint declared
    assert '@router.get("/goods/search-and-compare"' in src
    # Helper imported lazily inside the endpoint body
    assert "from ..services.wfirma_product_compare import compare_product_metadata" in src
    # Calls the helper
    assert "compare_product_metadata(" in src
    # Read-only contract: endpoint must NOT call upsert/create on this path
    # (search before this endpoint may exist; we only check the new path)
    idx_endpoint = src.find('@router.get("/goods/search-and-compare"')
    # take the next 2500 chars as the endpoint body window
    body = src[idx_endpoint:idx_endpoint + 2500]
    for forbidden_call in (
        "wfdb.upsert_product(",
        "wfirma_client.create_product(",
        "wfirma_client.update_product(",
    ):
        assert forbidden_call not in body, (
            f"search-and-compare endpoint must be read-only; "
            f"found {forbidden_call!r}"
        )
