"""test_awb9158478722_product_adoption.py

Unblock AWB 9158478722 product adoption: pending-product modal actions + batch
adopt for products already found in wFirma.

Covers:
  1. wfirma_db.adopt_pending_product — local-only flip of found+pending rows to
     matched; skips matched / unlinked / missing; idempotent (real temp DB).
  2. /shipment/{batch}/adopt-pending-found endpoint classification — adopts only
     found-pending rows, skips others with reasons, returns counts; performs NO
     wFirma write (mocked deps).
  3. Source guards: modal sends a request body + surfaces errors; batch-adopt
     button + handler wired; Register button no longer a dead disabled stub;
     batch endpoint is local-authority only (no wfirma_client / create).
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_SVC = Path(__file__).resolve().parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

_CAP_SRC    = _SVC / "app" / "api" / "routes_wfirma_capabilities.py"
_DB_SRC     = _SVC / "app" / "services" / "wfirma_db.py"
_DETAIL_HTML = _SVC / "app" / "static" / "shipment-detail.html"


# ── 1. DB helper: adopt_pending_product (real temp DB) ──────────────────────

@pytest.fixture()
def wfdb(tmp_path):
    from app.services import wfirma_db as _wfdb
    _wfdb.init_wfirma_db(tmp_path / "wfirma.db")
    # found in wFirma, awaiting operator decision
    _wfdb.upsert_product(product_code="P-PENDING", wfirma_product_id="111",
                         product_name_pl="Pierscionek", sync_status="pending_adoption")
    # already adopted
    _wfdb.upsert_product(product_code="P-MATCHED", wfirma_product_id="222",
                         product_name_pl="Kolczyki", sync_status="matched")
    # pending but NOT linked to a wFirma product (no wfirma_product_id)
    _wfdb.upsert_product(product_code="P-NOWFID", wfirma_product_id=None,
                         sync_status="pending_adoption")
    return _wfdb


def test_adopt_flips_found_pending_to_matched(wfdb):
    assert wfdb.adopt_pending_product("P-PENDING") is True
    row = wfdb.get_product("P-PENDING")
    assert row["sync_status"] == "matched"
    assert row["wfirma_product_id"] == "111"          # preserved, not recreated


def test_adopt_skips_already_matched(wfdb):
    assert wfdb.adopt_pending_product("P-MATCHED") is False
    assert wfdb.get_product("P-MATCHED")["sync_status"] == "matched"


def test_adopt_skips_unlinked_pending(wfdb):
    # pending_adoption but no wfirma_product_id → not a found product → no flip
    assert wfdb.adopt_pending_product("P-NOWFID") is False
    assert wfdb.get_product("P-NOWFID")["sync_status"] == "pending_adoption"


def test_adopt_skips_missing_code(wfdb):
    assert wfdb.adopt_pending_product("P-DOES-NOT-EXIST") is False


def test_adopt_is_idempotent(wfdb):
    assert wfdb.adopt_pending_product("P-PENDING") is True
    assert wfdb.adopt_pending_product("P-PENDING") is False   # already matched now


# ── 2. Endpoint classification (mocked deps, no wFirma write) ────────────────

def _invoice_rows(*codes):
    return [{"product_code": c} for c in codes]


def test_batch_adopt_classifies_and_adopts_only_found_pending():
    from app.api import routes_wfirma_capabilities as cap

    products = {
        "PENDING1": {"sync_status": "pending_adoption", "wfirma_product_id": "1"},
        "PENDING2": {"sync_status": "pending_adoption", "wfirma_product_id": "2"},
        "MATCHED1": {"sync_status": "matched",          "wfirma_product_id": "3"},
        "NOWFID1":  {"sync_status": "pending_adoption", "wfirma_product_id": ""},
        # MISSING1 deliberately absent from the products map
    }
    adopted_calls = []

    def _fake_adopt(pc):
        adopted_calls.append(pc)
        return products.get(pc, {}).get("sync_status") == "pending_adoption" \
            and bool(products.get(pc, {}).get("wfirma_product_id"))

    with patch("app.services.document_db.get_invoice_lines_for_batch",
               return_value=_invoice_rows("PENDING1", "PENDING2", "MATCHED1",
                                          "NOWFID1", "MISSING1")), \
         patch("app.services.wfirma_db.get_products_batch", return_value=products), \
         patch("app.services.wfirma_db.adopt_pending_product", side_effect=_fake_adopt):
        resp = cap.adopt_pending_found_for_batch("BATCH_X", x_operator=None)

    data = json.loads(resp.body)
    assert data["ok"] is True
    assert data["wfirma_untouched"] is True
    assert data["considered"] == 5
    assert data["adopted_count"] == 2
    assert sorted(data["adopted"]) == ["PENDING1", "PENDING2"]

    # adopt_pending_product is called ONLY for the found-pending rows
    assert sorted(adopted_calls) == ["PENDING1", "PENDING2"]

    reasons = {s["product_code"]: s["reason"] for s in data["skipped"]}
    assert reasons["MATCHED1"] == "already_matched"
    assert reasons["NOWFID1"]  == "missing_in_wfirma"
    assert reasons["MISSING1"] == "not_resolved_yet"


def test_batch_adopt_empty_batch_is_safe():
    from app.api import routes_wfirma_capabilities as cap
    with patch("app.services.document_db.get_invoice_lines_for_batch", return_value=[]), \
         patch("app.services.wfirma_db.get_products_batch", return_value={}), \
         patch("app.services.wfirma_db.adopt_pending_product", return_value=False) as m:
        resp = cap.adopt_pending_found_for_batch("BATCH_EMPTY", x_operator=None)
    data = json.loads(resp.body)
    assert data["adopted_count"] == 0 and data["considered"] == 0
    m.assert_not_called()


# ── 3. Source guards ────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def cap_src() -> str:
    return _CAP_SRC.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def html_src() -> str:
    return _DETAIL_HTML.read_text(encoding="utf-8")


def test_batch_endpoint_registered_and_local_only(cap_src):
    assert '/shipment/{batch_id:path}/adopt-pending-found' in cap_src
    assert 'def adopt_pending_found_for_batch(' in cap_src
    # Parse the endpoint's EXECUTABLE source (comments stripped via ast.unparse)
    # and prove it makes NO wFirma write call. A raw text slice would
    # false-positive on the trailing section comment that mentions "goods/add".
    tree = ast.parse(cap_src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
              and n.name == "adopt_pending_found_for_batch")
    # Drop the docstring too — it legitimately names WFIRMA_CREATE_PRODUCT_ALLOWED
    # (which contains the substring "create_product").
    if (fn.body and isinstance(fn.body[0], ast.Expr)
            and isinstance(getattr(fn.body[0], "value", None), ast.Constant)
            and isinstance(fn.body[0].value.value, str)):
        fn.body = fn.body[1:]
    body = ast.unparse(fn).lower()
    assert "adopt_pending_product" in body
    for forbidden in ("wfirma_client", "create_product", "create_warehouse_pz"):
        assert forbidden not in body, (
            f"batch adopt must be local-only — found wFirma-write token {forbidden!r}"
        )


def test_db_helper_present_and_scoped(cap_src):
    src = _DB_SRC.read_text(encoding="utf-8")
    assert "def adopt_pending_product(" in src
    idx = src.index("def adopt_pending_product(")
    body = src[idx:src.find("\ndef ", idx + 1)]
    assert "sync_status='pending_adoption'" in body   # only flips pending
    assert "sync_status='matched'" in body            # to matched
    assert "wfirma_product_id IS NOT NULL" in body     # only linked rows


def test_modal_sends_body_and_surfaces_errors(html_src):
    # _postPendingAction now takes a body param and attaches it as JSON.
    assert "const _postPendingAction = React.useCallback(async (productCode, endpoint, actionLabel, body)" in html_src
    assert "opts.body = JSON.stringify(body)" in html_src
    # Error formatter renders strings, 422 arrays, and structured dicts.
    assert "_fmtApiError" in html_src
    # Update/Create handlers pass the required payloads.
    assert "{ name, description }" in html_src
    assert "{ item_type, description_en }" in html_src


def test_batch_adopt_button_wired(html_src):
    assert 'data-testid="pending-batch-adopt-btn"' in html_src
    assert "handleBatchAdopt" in html_src
    assert "/adopt-pending-found" in html_src
    assert "pending-input-item-type-" in html_src   # per-row create input (JSX template testid)


def test_register_button_no_longer_dead(html_src):
    assert "handleRegisterMissing" in html_src
    # Register now has an onClick and a conditional (not hard-coded) disabled.
    assert "onClick={() => handleRegisterMissing(row)}" in html_src
    # The PRODUCT register button's dead-stub title is gone. (The customer
    # create-contractor stub is a separate sales-side button, out of scope for
    # this product-adoption task, and may remain.)
    idx = html_src.index("btn-setup-product-register-")
    window = html_src[idx - 200: idx + 700]
    assert "Handler wired in follow-up PR" not in window
    assert "Create this product in wFirma and adopt it" in window
