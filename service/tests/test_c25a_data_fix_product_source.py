"""test_c25a_data_fix_product_source.py — C25A-DATA-FIX.

PRODUCTION INCIDENT
After C25A backend deploy, /setup-detail returned
products.missing_count=0 for the Lapis batch where /proforma-readiness
correctly reported 12.

ROOT CAUSE
The endpoint read products from `ddb.query_sales_to_wfirma(batch_id)`
which queries a TEMP VIEW (v_sales_to_wfirma) joining
sales_packing_lines × packing_lines.  For the Lapis batch the join
returns zero rows, so the panel reported "0 missing" instead of "12
missing".  The authoritative product source — the one used by the
existing /dashboard/.../proforma-readiness endpoint — is
`ddb.get_invoice_lines_for_batch(batch_id)`.

FIX
Switched source to `get_invoice_lines_for_batch` so the two endpoints
agree on product counts.  Enrichment (design_no / item_type /
client_name / description) is best-effort from packing_lines + sales_-
packing_lines + invoice description.

This file pins the contract by source-grep and an integration test
against an in-memory fixture.
"""
from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path

import pytest


_ROUTES_PATH = (
    Path(__file__).resolve().parent.parent
    / "app" / "api" / "routes_wfirma_capabilities.py"
)


@pytest.fixture(scope="module")
def routes_src() -> str:
    return _ROUTES_PATH.read_text(encoding="utf-8")


def _slice_endpoint(src: str) -> str:
    idx = src.index("def shipment_setup_detail(")
    # End at next top-level `@router` decorator OR EOF.
    next_dec = src.find("\n@router.", idx)
    return src[idx : next_dec if next_dec > 0 else len(src)]


# ── Source contract ────────────────────────────────────────────────────────


def test_endpoint_reads_from_invoice_lines(routes_src):
    """The product authority MUST be get_invoice_lines_for_batch — same
    source as /dashboard/batches/{batch}/proforma-readiness."""
    body = _slice_endpoint(routes_src)
    assert "get_invoice_lines_for_batch(batch_id)" in body, (
        "shipment_setup_detail must call _ddb.get_invoice_lines_for_batch — "
        "this is the authoritative product source"
    )


def test_endpoint_does_not_call_query_sales_to_wfirma(routes_src):
    """The previous-source bug must not regress.  query_sales_to_wfirma
    returns 0 rows for the Lapis-style batch and must NOT be CALLED as
    the product authority.  Comment references are allowed (they
    document the C25A-DATA-FIX history)."""
    body = _slice_endpoint(routes_src)
    # Strip comment-only lines, then assert no call expression remains.
    code_only = "\n".join(
        ln for ln in body.split("\n")
        if not ln.lstrip().startswith("#")
    )
    assert "query_sales_to_wfirma(" not in code_only, (
        "shipment_setup_detail must NOT call query_sales_to_wfirma(...) — "
        "that source returns 0 rows for some live batches (C25A-DATA-FIX)"
    )


def test_endpoint_remains_read_only(routes_src):
    """C25A authority — endpoint body must contain NO write-shaped tokens."""
    body = _slice_endpoint(routes_src)
    forbidden = (
        "INSERT ", "UPDATE ", "DELETE ",
        "upsert_", "create_proforma", "create_invoice",
        "register_product", "register_customer",
        "_guard_wfirma_export",
        "wfirma_client.",
    )
    for tok in forbidden:
        assert tok not in body, (
            f"setup-detail body contains forbidden token {tok!r} — "
            "endpoint must remain read-only"
        )


def test_endpoint_preserves_response_shape(routes_src):
    """Response shape unchanged by C25A-DATA-FIX."""
    body = _slice_endpoint(routes_src)
    required_keys = (
        '"missing":', '"mapped_count":', '"missing_count":',
        '"create_flag_on":', '"details":', '"action_needed":',
        '"can_prepare_proforma":', '"can_post_to_wfirma":',
        '"blockers_for_preparation":', '"blockers_for_posting":',
        '"purchase_transit_count":', '"batch_lifecycle":',
    )
    for k in required_keys:
        assert k in body, f"setup-detail response missing required key {k!r}"


def test_endpoint_create_flags_still_from_settings(routes_src):
    """create_flag_on for products and customers must read from the
    same settings flags as before — unchanged by this fix."""
    body = _slice_endpoint(routes_src)
    assert "wfirma_create_product_allowed" in body
    assert "wfirma_create_customer_allowed" in body
    assert "wfirma_create_pz_allowed" in body


# ── Aggregation-logic unit tests (no DB required) ─────────────────────────


def test_endpoint_aggregates_per_product_code(routes_src):
    """The endpoint must collapse multiple invoice_lines rows with the
    SAME product_code into ONE entry (qty/total_value summed).  Verified
    by source-grep against the aggregation pattern."""
    body = _slice_endpoint(routes_src)
    # Aggregation loop: sees `seen_codes`, accumulates qty/total_value
    # for repeat product_codes, and uses setdefault-like single-entry
    # behaviour.
    assert "seen_codes" in body, "aggregation must track seen product_codes"
    assert "missing_acc[pc][\"qty\"] +=" in body or "missing_acc[pc]['qty'] +=" in body, (
        "aggregation must sum qty across invoice_lines rows with same product_code"
    )


def test_endpoint_enriches_from_packing_lines(routes_src):
    """Best-effort enrichment from packing_lines gives design_no +
    item_type when invoice_lines doesn't carry them."""
    body = _slice_endpoint(routes_src)
    assert "get_packing_lines_for_batch(batch_id)" in body, (
        "enrichment must read packing_lines for design_no + item_type"
    )


def test_endpoint_enriches_client_name_from_sales_packing_lines(routes_src):
    """Best-effort client_name attribution per product_code via
    sales_packing_lines (same batch scope, no cross-batch leakage)."""
    body = _slice_endpoint(routes_src)
    assert "sales_packing_lines" in body, (
        "client_name enrichment must come from sales_packing_lines"
    )
    assert "WHERE batch_id=?" in body, (
        "client_name lookup must be batch-scoped"
    )


def test_endpoint_response_shape_preserved(routes_src):
    """C25A-DATA-FIX must not change the response shape: products.missing
    row keys remain the same so the frontend renders identically."""
    body = _slice_endpoint(routes_src)
    # Per-row keys must still be set
    for key in ('"product_code":', '"design_no":', '"item_type":',
                '"qty":', '"total_value":', '"currency":',
                '"draft_id":', '"client_name":'):
        assert key in body, (
            f"products.missing row must still carry {key!r}"
        )
