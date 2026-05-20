"""test_c26_reader_contract_enforcement.py — C26.

Pins the Canonical Proforma Setup Reader Contract
(`.claude/contracts/proforma-setup-reader-contract.md`).

Each forbidden / required reader pattern from the contract is enforced
here as a source-grep test against the actual route modules.  These
tests intentionally avoid runtime fixtures so they remain stable
regardless of DB state and run in well under a second.

Origin: C25A incident (2026-05-20).  `/setup-detail` used
`query_sales_to_wfirma` (returned 0 rows) while `/proforma-readiness`
used `get_invoice_lines_for_batch` (returned 12).  Two readers for one
domain question.  This contract bans that pattern and these tests pin
the ban.
"""
from __future__ import annotations

from pathlib import Path

import pytest


_API_DIR = Path(__file__).resolve().parent.parent / "app" / "api"
_CAP_PATH = _API_DIR / "routes_wfirma_capabilities.py"
_DASH_PATH = _API_DIR / "routes_dashboard.py"
_CONTRACT_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / ".claude" / "contracts" / "proforma-setup-reader-contract.md"
)


# ── Helpers ────────────────────────────────────────────────────────────────


def _strip_comments(src: str) -> str:
    """Remove comment-only lines so contract docstrings citing forbidden
    readers (for history) don't fail the call-site assertions."""
    return "\n".join(
        ln for ln in src.split("\n") if not ln.lstrip().startswith("#")
    )


def _slice_function(src: str, name: str) -> str:
    """Return source from `def <name>(` to the next top-level `@router`
    decorator or EOF.  Used to scope assertions to one endpoint body."""
    needle = f"def {name}("
    idx = src.find(needle)
    if idx < 0:
        raise AssertionError(f"function {name!r} not found in source")
    nxt = src.find("\n@router.", idx)
    return src[idx : nxt if nxt > 0 else len(src)]


@pytest.fixture(scope="module")
def cap_src() -> str:
    return _CAP_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def dash_src() -> str:
    return _DASH_PATH.read_text(encoding="utf-8")


# ── Contract document exists & names every canonical reader ───────────────


def test_contract_document_exists():
    assert _CONTRACT_PATH.is_file(), (
        f"contract document missing at {_CONTRACT_PATH} — C26 enforcement "
        "is meaningless without the contract being readable on disk"
    )


def test_contract_lists_every_canonical_reader():
    doc = _CONTRACT_PATH.read_text(encoding="utf-8")
    required_readers = (
        "get_invoice_lines_for_batch",
        "get_packing_lines_for_batch",
        "wfirma_customer_auto_resolve",
        "list_drafts_for_batch",
        "get_customer_by_name",
        "list_customers",
    )
    for r in required_readers:
        assert r in doc, (
            f"contract document must name canonical reader {r!r} in §2"
        )


def test_contract_lists_every_forbidden_pattern():
    doc = _CONTRACT_PATH.read_text(encoding="utf-8")
    required_bans = (
        "query_sales_to_wfirma",
        "v_sales_to_wfirma",
        "packing_lines",  # discussed in §3.2 enrichment-only rule
    )
    for ban in required_bans:
        assert ban in doc, (
            f"contract must explicitly name forbidden pattern {ban!r}"
        )


# ── Rule 3.1 — products must come from get_invoice_lines_for_batch ────────


def test_setup_detail_uses_canonical_product_reader(cap_src):
    body = _slice_function(cap_src, "shipment_setup_detail")
    code = _strip_comments(body)
    assert "get_invoice_lines_for_batch(batch_id)" in code, (
        "shipment_setup_detail MUST consume get_invoice_lines_for_batch — "
        "the canonical product reader per contract §2 row 1"
    )


def test_proforma_readiness_uses_canonical_product_reader(dash_src):
    body = _slice_function(dash_src, "proforma_readiness")
    code = _strip_comments(body)
    assert "get_invoice_lines_for_batch(batch_id)" in code, (
        "proforma_readiness MUST consume get_invoice_lines_for_batch — "
        "the canonical product reader per contract §2 row 1"
    )


def test_setup_detail_does_not_call_query_sales_to_wfirma(cap_src):
    body = _slice_function(cap_src, "shipment_setup_detail")
    code = _strip_comments(body)
    assert "query_sales_to_wfirma(" not in code, (
        "shipment_setup_detail MUST NOT call query_sales_to_wfirma — "
        "C25A divergence pattern (contract §3.1)"
    )


def test_proforma_readiness_does_not_call_query_sales_to_wfirma(dash_src):
    body = _slice_function(dash_src, "proforma_readiness")
    code = _strip_comments(body)
    assert "query_sales_to_wfirma(" not in code, (
        "proforma_readiness MUST NOT call query_sales_to_wfirma — "
        "contract §3.1 bans this reader for setup/readiness domain"
    )


# ── Rule 3.2 — packing_lines is enrichment only ───────────────────────────


def test_setup_detail_does_not_derive_products_from_packing_lines(cap_src):
    """The product list is anchored on invoice_lines; packing_lines is a
    join target for design_no/item_type only.  Verified by ordering:
    get_invoice_lines_for_batch must be called before
    get_packing_lines_for_batch within the endpoint body."""
    body = _slice_function(cap_src, "shipment_setup_detail")
    code = _strip_comments(body)
    i_inv = code.find("get_invoice_lines_for_batch(")
    i_pl  = code.find("get_packing_lines_for_batch(")
    assert i_inv >= 0, "endpoint must call get_invoice_lines_for_batch"
    if i_pl >= 0:
        assert i_inv < i_pl, (
            "get_invoice_lines_for_batch MUST be called before "
            "get_packing_lines_for_batch — products anchor on invoice_lines, "
            "packing_lines is enrichment only (contract §3.2)"
        )


# ── Rule 3.3 — no inline v_sales_to_wfirma-shaped SQL in routes ──────────


def test_no_inline_v_sales_to_wfirma_join_in_capabilities(cap_src):
    """Reimplementing the v_sales_to_wfirma JOIN inline in a route handler
    reintroduces C25A in disguise.  Banned by contract §3.3."""
    code = _strip_comments(cap_src)
    # The specific banned shape: a JOIN that puts sales_packing_lines and
    # packing_lines together inside a single SQL string in this module.
    # We detect via co-occurrence on the same logical SQL fragment.
    forbidden_join_markers = (
        "FROM sales_packing_lines",
        "JOIN packing_lines",
    )
    if all(m in code for m in forbidden_join_markers):
        # Confirm they're close enough to be in the same SQL string
        i_from = code.find("FROM sales_packing_lines")
        i_join = code.find("JOIN packing_lines")
        proximity = abs(i_from - i_join)
        assert proximity > 400, (
            "inline JOIN of sales_packing_lines × packing_lines in "
            "routes_wfirma_capabilities.py reintroduces the v_sales_to_wfirma "
            "shape banned by contract §3.3"
        )


# ── Rule 3.4 — posting-readiness verdict comes from one place ─────────────


def test_setup_detail_does_not_compute_independent_ready_flag(cap_src):
    """`/setup-detail` may surface gate-derived booleans (can_prepare_proforma,
    can_post_to_wfirma) but its `ready` field — if present — must trace back
    to the same blockers structure proforma_readiness uses.  Detected by
    requiring that any `"ready"` key in the response shape sits alongside
    a `"blockers"` list (same pattern as proforma_readiness)."""
    body = _slice_function(cap_src, "shipment_setup_detail")
    if '"ready"' in body:
        assert (
            '"blockers_for_preparation"' in body
            or '"blockers_for_posting"' in body
            or '"blocking_reasons"' in body
        ), (
            "if /setup-detail surfaces a ready flag, it must also surface a "
            "blockers list — independent ready computation is banned by "
            "contract §3.4"
        )


# ── Rule 3.5 — both endpoints share the same product mapping reader ──────


def test_both_endpoints_use_wfdb_get_product_for_mapping(cap_src, dash_src):
    """Per-code wFirma mapping check must use `wfirma_db.get_product`.
    Bulk-joining wfirma_products inside a route is banned (would create a
    second mapping authority)."""
    cap_body  = _slice_function(cap_src, "shipment_setup_detail")
    dash_body = _slice_function(dash_src, "proforma_readiness")
    for label, body in (("setup_detail", cap_body),
                        ("proforma_readiness", dash_body)):
        code = _strip_comments(body)
        # Either calls wfdb.get_product or has no product-mapping logic;
        # what's banned is a raw wfirma_products SELECT inside the route.
        if "wfirma_products" in code:
            assert ("get_product(" in code) or ("get_products_batch(" in code), (
                f"{label} references wfirma_products without using "
                "wfdb.get_product or wfdb.get_products_batch — contract §2 "
                "row 2 mandates the canonical per-code reader (single or bulk)"
            )


# ── Rule 3.5 — V2 / future panel adapter rule (smoke check) ──────────────


def test_no_undeclared_setup_endpoint_invents_a_product_reader():
    """Smoke: no other route file under app/api defines a function with
    'setup' or 'readiness' in its name that calls query_sales_to_wfirma.
    A new endpoint defining its own reader without updating this contract
    is a §3.5 violation."""
    suspects = []
    for py in _API_DIR.glob("routes_*.py"):
        text = _strip_comments(py.read_text(encoding="utf-8"))
        # Look for new endpoints touching the proforma domain
        if "query_sales_to_wfirma(" in text:
            # Check whether it's inside a setup/readiness-named function
            lines = text.split("\n")
            in_setup_fn = False
            for ln in lines:
                stripped = ln.strip()
                if stripped.startswith("def ") and (
                    "setup" in stripped or "readiness" in stripped
                    or "proforma_" in stripped
                ):
                    in_setup_fn = True
                elif stripped.startswith("def "):
                    in_setup_fn = False
                if in_setup_fn and "query_sales_to_wfirma(" in ln:
                    suspects.append(f"{py.name}: {stripped}")
    assert not suspects, (
        "found setup/readiness/proforma_* endpoints calling "
        "query_sales_to_wfirma — contract §3.5 forbids new endpoints from "
        "reintroducing the C25A reader:\n  " + "\n  ".join(suspects)
    )
