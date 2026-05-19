"""
test_authority_graph_commercial_draft.py
Campaign 4 — Commercial Draft Single-Source-of-Truth Refactor

Authority-graph contract tests.  These tests pin the relationships described in
service/docs/authority-graph-commercial-draft.md so any future change that
accidentally creates a new authority layer or bypasses the canonical one will
fail CI immediately.

Pins:
  AG-01  freight_resolver has PRODUCTION_ROUTE_EXCLUSION comment
  AG-02  freight_resolver is not imported by any production API route
  AG-03  pick_freight is the canonical production freight path (imported by routes_proforma)
  AG-04  compute_insurance_suggestion is the canonical production insurance path
  AG-05  suggest-freight endpoint reads from CustomerMaster (not freight_resolver)
  AG-06  suggest-insurance endpoint reads from CustomerMaster (not freight_resolver)
  AG-07  _build_preview ship_to response includes cm_conflict key
  AG-08  ship_to authority is wfirma_customers in _build_proforma_request, not CustomerMaster
  AG-09  no production API route imports resolve_freight
  AG-10  cross-validation warning is non-blocking (no blocking_reasons entry)
"""
from __future__ import annotations

import ast
import pathlib
import re

SERVICE_ROOT = pathlib.Path(__file__).resolve().parents[1]
API_DIR      = SERVICE_ROOT / "app" / "api"
SERVICES_DIR = SERVICE_ROOT / "app" / "services"
STATIC_DIR   = SERVICE_ROOT / "app" / "static"


# ── AG-01 ─────────────────────────────────────────────────────────────────────

def test_freight_resolver_has_production_exclusion_comment():
    """freight_resolver.py must carry the PRODUCTION ROUTE EXCLUSION header."""
    src = (SERVICES_DIR / "freight_resolver.py").read_text(encoding="utf-8")
    assert "PRODUCTION ROUTE EXCLUSION" in src, (
        "freight_resolver.py must carry a PRODUCTION ROUTE EXCLUSION comment "
        "to prevent accidental import in production routes. "
        "See service/docs/authority-graph-commercial-draft.md — Layer E."
    )


# ── AG-02 ─────────────────────────────────────────────────────────────────────

def test_no_production_api_route_imports_freight_resolver():
    """No file in app/api/ may import freight_resolver or resolve_freight."""
    violations = []
    for path in API_DIR.glob("*.py"):
        src = path.read_text(encoding="utf-8")
        if "freight_resolver" in src or "resolve_freight" in src:
            violations.append(path.name)
    assert not violations, (
        f"Production API routes must not import freight_resolver. "
        f"Violations: {violations}. "
        "Use pick_freight(cm, draft_currency) from app.services.customer_master instead."
    )


# ── AG-03 ─────────────────────────────────────────────────────────────────────

def test_routes_proforma_imports_pick_freight():
    """routes_proforma.py must import pick_freight from customer_master."""
    src = (API_DIR / "routes_proforma.py").read_text(encoding="utf-8")
    assert "pick_freight" in src, (
        "routes_proforma.py must import/use pick_freight from customer_master "
        "as the canonical production freight path."
    )


# ── AG-04 ─────────────────────────────────────────────────────────────────────

def test_routes_proforma_imports_compute_insurance_suggestion():
    """routes_proforma.py must import compute_insurance_suggestion."""
    src = (API_DIR / "routes_proforma.py").read_text(encoding="utf-8")
    assert "compute_insurance_suggestion" in src, (
        "routes_proforma.py must import/use compute_insurance_suggestion "
        "from customer_master as the canonical production insurance path."
    )


# ── AG-05 ─────────────────────────────────────────────────────────────────────

def test_suggest_freight_endpoint_uses_pick_freight_not_resolver():
    """suggest-freight endpoint must call pick_freight, never resolve_freight."""
    src = (API_DIR / "routes_proforma.py").read_text(encoding="utf-8")
    # Locate the suggest_freight_endpoint function
    start = src.find("def suggest_freight_endpoint(")
    assert start >= 0, "suggest_freight_endpoint not found"
    # Find next top-level def to bound the function body
    next_def = src.find("\ndef ", start + 10)
    body = src[start:next_def] if next_def > 0 else src[start:]
    assert "pick_freight" in body, (
        "suggest_freight_endpoint must call pick_freight(cm, draft_currency)"
    )
    assert "resolve_freight" not in body, (
        "suggest_freight_endpoint must NOT call resolve_freight — "
        "freight_resolver is tool-only (Layer E in authority graph)"
    )


# ── AG-06 ─────────────────────────────────────────────────────────────────────

def test_suggest_insurance_endpoint_uses_compute_insurance_not_resolver():
    """suggest-insurance endpoint must call compute_insurance_suggestion."""
    src = (API_DIR / "routes_proforma.py").read_text(encoding="utf-8")
    start = src.find("def suggest_insurance_endpoint(")
    assert start >= 0, "suggest_insurance_endpoint not found"
    next_def = src.find("\ndef ", start + 10)
    body = src[start:next_def] if next_def > 0 else src[start:]
    assert "compute_insurance_suggestion" in body, (
        "suggest_insurance_endpoint must call compute_insurance_suggestion"
    )
    assert "resolve_freight" not in body, (
        "suggest_insurance_endpoint must NOT call resolve_freight"
    )


# ── AG-07 ─────────────────────────────────────────────────────────────────────

def test_build_preview_ship_to_response_includes_cm_conflict_key():
    """_build_preview ship_to response dict must include 'cm_conflict' key."""
    src = (API_DIR / "routes_proforma.py").read_text(encoding="utf-8")
    # Find the ship_to dict in the return value of _build_preview
    start = src.find('"ship_to": {')
    assert start >= 0, "ship_to response block not found in routes_proforma.py"
    end = src.find("},", start)
    block = src[start:end]
    assert "cm_conflict" in block, (
        "'ship_to' response block must include 'cm_conflict' key "
        "(non-blocking warning for authority divergence). "
        "See authority-graph-commercial-draft.md — Conflict 1."
    )


# ── AG-08 ─────────────────────────────────────────────────────────────────────

def test_build_proforma_request_reads_ship_to_from_wfirma_customers():
    """_build_proforma_request must read ship_to_mode from wfirma_customers (cust dict),
    never from CustomerMaster directly for receiver ID routing."""
    src = (API_DIR / "routes_proforma.py").read_text(encoding="utf-8")
    start = src.find("def _build_proforma_request(")
    assert start >= 0, "_build_proforma_request not found"
    next_def = src.find("\ndef ", start + 10)
    body = src[start:next_def] if next_def > 0 else src[start:]
    # Must read ship_to_mode from the cust dict (wfirma_customers row)
    assert 'cust' in body and 'ship_to_mode' in body, (
        "_build_proforma_request must read ship_to_mode from wfirma_customers cust dict"
    )
    # Must NOT call ship_to_shape from customer_master
    assert "ship_to_shape" not in body, (
        "_build_proforma_request must NOT call ship_to_shape(cm) "
        "(that reads CustomerMaster.ship_to_contractor_id — a legacy field). "
        "Use wfirma_customers.ship_to_mode instead."
    )


# ── AG-09 ─────────────────────────────────────────────────────────────────────

def test_no_production_service_imports_freight_resolver():
    """No service in app/services/ may import freight_resolver EXCEPT
    freight_history_db (which is its own storage module) and freight_resolver itself."""
    allowed = {"freight_resolver.py", "freight_history_db.py"}
    violations = []
    for path in SERVICES_DIR.glob("*.py"):
        if path.name in allowed:
            continue
        src = path.read_text(encoding="utf-8")
        if "freight_resolver" in src and "PRODUCTION ROUTE EXCLUSION" not in src:
            violations.append(path.name)
    assert not violations, (
        f"Production services must not import freight_resolver: {violations}. "
        "Use pick_freight(cm, draft_currency) from customer_master."
    )


# ── AG-10 ─────────────────────────────────────────────────────────────────────

def test_ship_to_cm_conflict_is_non_blocking():
    """The ship_to cm_conflict warning must be assigned to ship_to_cm_conflict,
    not appended to blocking_reasons. Cross-validation must never block the preview."""
    src = (API_DIR / "routes_proforma.py").read_text(encoding="utf-8")
    assert "ship_to_cm_conflict" in src, (
        "ship_to_cm_conflict variable must exist in _build_preview"
    )
    # Verify ship_to_cm_conflict is never passed to blocking_reasons.append.
    # If it were, that would make the cross-validation a hard block.
    lines = src.splitlines()
    violations = [
        ln.strip() for ln in lines
        if "blocking_reasons.append" in ln and "ship_to_cm_conflict" in ln
    ]
    assert not violations, (
        "ship_to_cm_conflict must NOT be appended to blocking_reasons. "
        f"Found: {violations}. "
        "Cross-validation is a non-blocking advisory warning only."
    )
    # Also verify cm_conflict key is in the ship_to return dict
    assert '"cm_conflict": ' in src or '"cm_conflict":' in src, (
        "'cm_conflict' key must appear in the 'ship_to' response dict"
    )
