"""test_awb9158478722_import_pz_sales_authority.py

Regression: IMPORT PZ / wFirma goods-receipt readiness must NOT depend on
SALES packing list or sales linkage.

Origin: AWB 9158478722 was shown as "Can post to wFirma: ✗" with sales-side
prerequisites (proforma drafts, customer mapping) folded into the posting
blockers via ``post_blockers.extend(prep_blockers)`` in
``shipment_setup_detail``. Import authority (mapped products, warehouse
receipt, WFIRMA_CREATE_PZ_ALLOWED) is the only correct gate for the import PZ;
sales linkage is downstream and advisory. Imported goods may sit in inventory
before being sold.

Authority contract under test (``split_import_vs_sales_blockers``):
  - missing sales packing list / proforma drafts → NOT a posting blocker
  - unmapped customers → NOT a posting blocker
  - unmapped products → REMAINS a posting blocker (fiscal gate)
  - warehouse transit (PRE_IMPORT / DHL_TRANSIT) → REMAINS a posting blocker
  - WFIRMA_CREATE_PZ_ALLOWED off → REMAINS a posting blocker

Plus source guards proving the import PZ preview/guard/create paths
(``_collect_pz_preview_blockers``, ``_guard_wfirma_export``,
``wfirma_pz_create``) carry no sales dependency.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.api.routes_wfirma_capabilities import split_import_vs_sales_blockers


_REPO = Path(__file__).resolve().parent.parent
_CAP_SRC  = _REPO / "app" / "api" / "routes_wfirma_capabilities.py"
_WFIRMA_SRC = _REPO / "app" / "api" / "routes_wfirma.py"

_ONE_UNMAPPED = [{"client_name": "Diamond Point"}]
_SALES_TOKENS = ("sales_packing", "sales_documents", "proforma", "client_name")


# ── Authority contract (pure helper) ────────────────────────────────────────

def test_missing_sales_does_not_block_import_pz():
    """No proforma drafts AND an unmapped customer, but import prerequisites all
    satisfied → import PZ posting is NOT blocked."""
    r = split_import_vs_sales_blockers(
        client_names=[],                       # no proforma drafts (sales)
        unresolved_customers=_ONE_UNMAPPED,    # customer unmapped (sales)
        products_missing_count=0,              # import OK
        wfirma_create_pz_allowed=True,         # import OK
        batch_lifecycle="WAREHOUSE_STOCK",     # import OK (received)
    )
    assert r["can_post_to_wfirma"] is True
    assert r["blockers_for_posting"] == []
    # Sales prerequisites are still surfaced — visible but advisory.
    assert r["can_prepare_proforma"] is False
    assert r["sales_linkage_advisory"] == r["blockers_for_preparation"]
    assert len(r["sales_linkage_advisory"]) == 2


def test_sales_strings_never_appear_in_posting_blockers():
    r = split_import_vs_sales_blockers(
        client_names=[],
        unresolved_customers=_ONE_UNMAPPED,
        products_missing_count=31,
        wfirma_create_pz_allowed=True,
        batch_lifecycle="PRE_IMPORT",
    )
    joined = " ".join(r["blockers_for_posting"]).lower()
    assert "proforma" not in joined
    assert "customer" not in joined
    assert "sales" not in joined


def test_unmapped_products_remain_a_real_posting_blocker():
    r = split_import_vs_sales_blockers(
        client_names=["Diamond Point"],
        unresolved_customers=[],
        products_missing_count=31,
        wfirma_create_pz_allowed=True,
        batch_lifecycle="WAREHOUSE_STOCK",
    )
    assert r["can_post_to_wfirma"] is False
    assert any("product code(s) unmapped" in b for b in r["blockers_for_posting"])


def test_warehouse_transit_remains_a_real_posting_blocker():
    for lifecycle in ("PRE_IMPORT", "DHL_TRANSIT"):
        r = split_import_vs_sales_blockers(
            client_names=["Diamond Point"],
            unresolved_customers=[],
            products_missing_count=0,
            wfirma_create_pz_allowed=True,
            batch_lifecycle=lifecycle,
        )
        assert r["can_post_to_wfirma"] is False, lifecycle
        assert any(
            "warehouse scan-in not yet performed" in b
            for b in r["blockers_for_posting"]
        ), lifecycle


def test_create_pz_flag_off_remains_a_real_posting_blocker():
    r = split_import_vs_sales_blockers(
        client_names=["Diamond Point"],
        unresolved_customers=[],
        products_missing_count=0,
        wfirma_create_pz_allowed=False,
        batch_lifecycle="WAREHOUSE_STOCK",
    )
    assert r["can_post_to_wfirma"] is False
    assert any("WFIRMA_CREATE_PZ_ALLOWED" in b for b in r["blockers_for_posting"])


def test_fully_ready_import_with_sales_present():
    r = split_import_vs_sales_blockers(
        client_names=["Diamond Point"],
        unresolved_customers=[],
        products_missing_count=0,
        wfirma_create_pz_allowed=True,
        batch_lifecycle="WAREHOUSE_STOCK",
    )
    assert r["can_post_to_wfirma"] is True
    assert r["can_prepare_proforma"] is True
    assert r["blockers_for_posting"] == []
    assert r["sales_linkage_advisory"] == []


# ── Source guards: the fold is gone; advisory is wired ──────────────────────

@pytest.fixture(scope="module")
def cap_src() -> str:
    return _CAP_SRC.read_text(encoding="utf-8")


def test_sales_prep_is_no_longer_folded_into_posting(cap_src):
    assert "post_blockers.extend(prep_blockers)" not in cap_src, (
        "Sales prep blockers must NOT be folded into import PZ posting blockers"
    )


def test_setup_detail_exposes_sales_linkage_advisory(cap_src):
    assert '"sales_linkage_advisory"' in cap_src
    assert "split_import_vs_sales_blockers(" in cap_src


# ── Source guards: import PZ preview/guard/create carry no sales dependency ──

@pytest.fixture(scope="module")
def wfirma_src() -> str:
    return _WFIRMA_SRC.read_text(encoding="utf-8")


def _executable_src(src: str, name: str) -> str:
    """Return the function's EXECUTABLE source (docstring + comments stripped).

    Source-grep over a raw body false-positives on negative docstring mentions
    (e.g. pz_create's "does NOT call ...proforma..."). We parse the function,
    drop its docstring, and ``ast.unparse`` it — comments vanish and the
    docstring is gone, but real string literals (e.g. SQL "...sales_packing...")
    are preserved, so a genuine sales data dependency would still be caught.
    """
    tree = ast.parse(src)
    target = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            target = node
            break
    assert target is not None, f"function {name!r} not found"
    if (target.body and isinstance(target.body[0], ast.Expr)
            and isinstance(getattr(target.body[0], "value", None), ast.Constant)
            and isinstance(target.body[0].value.value, str)):
        target.body = target.body[1:]
    return ast.unparse(target).lower()


@pytest.mark.parametrize("name", [
    "_collect_pz_preview_blockers",
    "_guard_wfirma_export",
    "wfirma_pz_create",
])
def test_import_pz_paths_have_no_sales_dependency(wfirma_src, name):
    """The import PZ preview/guard/create executable code must not read sales
    packing list, sales documents, proforma, or client/customer identity."""
    body = _executable_src(wfirma_src, name)
    for tok in _SALES_TOKENS:
        assert tok not in body, (
            f"{name} references sales token {tok!r} in executable code — import "
            "PZ readiness/creation must not depend on sales linkage"
        )
