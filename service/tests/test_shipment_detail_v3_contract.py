"""
test_shipment_detail_v3_contract.py — Sprint 03 contract tests.

Asserts (static source-grep; no server required):

  A. Anti-duplication (1)
     1. shipment-v2.html does NOT exist — single shipment authority rule.

  B. File & script integrity (2–4)
     2. shipment-detail-v3.html exists.
     3. pz-design-v2.js is loaded (Sprint 25 supplementary layer).
     4. dashboard-shared.js is NOT loaded as a script src.

  C. Six API endpoint paths (5–10)
     5. /api/v1/dashboard/batches/ path present (batch header + documents).
     6. /api/v1/batch/ + /readiness path present (readiness domains).
     7. /api/v1/agents/decision/ path present (AI decision signals).
     8. /api/v1/tracking/shipment/ + /timeline path present (timeline events).
     9. /api/v1/sales/linkage/ path present (sales linkage preview).
    10. /api/v1/action-proposals/ path present (inbox proposals).

  D. Tab structure (11–13)
    11. Seven canonical tab labels declared in TABS constant.
    12. data-testid="tabs" container present.
    13. tab-btn- prefix used for tab button testids.

  E. Workflow stepper (14–15)
    14. Seven canonical stage labels declared in STAGES constant.
    15. data-testid="workflow-strip" present.

  F. Page anatomy testids (16–21)
    16. data-testid="shipment-header" present.
    17. data-testid="header-awb" present.
    18. data-testid="back-to-dashboard" present.
    19. data-testid="no-batch" guard present.
    20. data-testid="skeleton" loading state present.
    21. data-testid="next-action" callout present.

  G. Per-tab content testids (22–28)
    22. data-testid="tab-control" (Overview / Control Center)
    23. data-testid="tab-timeline"
    24. data-testid="tab-intelligence"
    25. data-testid="tab-proposals"
    26. data-testid="tab-pz" (PZ / Accounting)
    27. data-testid="tab-sales"
    28. data-testid="tab-documents"

  H. No-write policy (29–30)
    29. No POST/PATCH/DELETE fetch methods anywhere in the inline script.
    30. No forbidden write endpoint patterns (wFirma create/post, DHL label,
        PZ create, customs mutation).
"""
from __future__ import annotations

import re
from pathlib import Path

_ROOT   = Path(__file__).resolve().parents[2]
_STATIC = _ROOT / "service" / "app" / "static"
_V3     = _STATIC / "shipment-detail-v3.html"


def _src() -> str:
    return _V3.read_text(encoding="utf-8", errors="replace")


# ══════════════════════════════════════════════════════════════════════════════
# A — Anti-duplication
# ══════════════════════════════════════════════════════════════════════════════

def test_shipment_v2_does_not_exist():
    """shipment-v2.html must never be created — single shipment visual authority."""
    assert not (_STATIC / "shipment-v2.html").exists(), (
        "shipment-v2.html was found in service/app/static/. "
        "shipment-detail-v3.html is the sole shipment visual authority. "
        "Creating a second shipment page violates the single-authority rule."
    )


# ══════════════════════════════════════════════════════════════════════════════
# B — File & script integrity
# ══════════════════════════════════════════════════════════════════════════════

def test_shipment_detail_v3_exists():
    assert _V3.exists(), "shipment-detail-v3.html must exist in service/app/static/"


def test_pz_design_v2_script_loaded():
    src = _src()
    assert "pz-design-v2.js" in src, (
        "shipment-detail-v3.html must load pz-design-v2.js (Sprint 25 shared layer)"
    )


def test_dashboard_shared_not_loaded():
    src = _src()
    assert 'src="/dashboard/dashboard-shared.js"' not in src, (
        "dashboard-shared.js must NOT appear as a script src — "
        "page is self-contained with inline transport and pz-design-v2.js"
    )


# ══════════════════════════════════════════════════════════════════════════════
# C — Six API endpoint paths
# ══════════════════════════════════════════════════════════════════════════════

def test_api_batch_header_path():
    """GET /api/v1/dashboard/batches/{enc} — batch header, financials, documents."""
    src = _src()
    assert "/api/v1/dashboard/batches/" in src, (
        "batchState endpoint /api/v1/dashboard/batches/ not found in source"
    )


def test_api_readiness_path():
    """GET /api/v1/batch/{enc}/readiness — per-domain readiness gates."""
    src = _src()
    assert "/api/v1/batch/" in src and "/readiness" in src, (
        "readyState endpoint /api/v1/batch/.../readiness not found in source"
    )


def test_api_decision_path():
    """GET /api/v1/agents/decision/{enc} — AI decision signals and next action."""
    src = _src()
    assert "/api/v1/agents/decision/" in src, (
        "decisionState endpoint /api/v1/agents/decision/ not found in source"
    )


def test_api_timeline_path():
    """GET /api/v1/tracking/shipment/{enc}/timeline — DHL + workflow events."""
    src = _src()
    assert "/api/v1/tracking/shipment/" in src and "/timeline" in src, (
        "timelineState endpoint /api/v1/tracking/shipment/.../timeline not found in source"
    )


def test_api_sales_linkage_path():
    """GET /api/v1/sales/linkage/{enc}?mode=preview — packing→sales linkage."""
    src = _src()
    assert "/api/v1/sales/linkage/" in src, (
        "salesState endpoint /api/v1/sales/linkage/ not found in source"
    )


def test_api_action_proposals_path():
    """GET /api/v1/action-proposals/{enc} — system-generated proposals."""
    src = _src()
    assert "/api/v1/action-proposals/" in src, (
        "proposalsState endpoint /api/v1/action-proposals/ not found in source"
    )


# ══════════════════════════════════════════════════════════════════════════════
# D — Tab structure
# ══════════════════════════════════════════════════════════════════════════════

_EXPECTED_TABS = [
    "Overview", "Timeline", "Intelligence", "Proposals",
    "PZ / Accounting", "Sales", "Documents",
]


def test_seven_tabs_declared():
    src = _src()
    for tab in _EXPECTED_TABS:
        assert f"'{tab}'" in src or f'"{tab}"' in src, (
            f"Tab '{tab}' not found in TABS declaration"
        )


def test_tabs_container_testid():
    assert 'data-testid="tabs"' in _src(), "data-testid=\"tabs\" must be present"


def test_tab_btn_prefix_used():
    src = _src()
    assert "tab-btn-" in src, (
        "tab button testids must use 'tab-btn-' prefix "
        "(e.g. data-testid={\"tab-btn-\" + ...})"
    )


# ══════════════════════════════════════════════════════════════════════════════
# E — Workflow stepper
# ══════════════════════════════════════════════════════════════════════════════

_EXPECTED_STAGES = [
    "Intake", "Pre-check", "DHL Reply", "SAD / ZC429",
    "Verified", "PZ Generated", "wFirma Booked",
]


def test_seven_stages_declared():
    src = _src()
    for stage in _EXPECTED_STAGES:
        assert f"'{stage}'" in src or f'"{stage}"' in src, (
            f"Stage '{stage}' not found in STAGES declaration"
        )


def test_workflow_strip_testid():
    assert 'data-testid="workflow-strip"' in _src(), \
        "data-testid=\"workflow-strip\" must be present"


# ══════════════════════════════════════════════════════════════════════════════
# F — Page anatomy testids
# ══════════════════════════════════════════════════════════════════════════════

def test_shipment_header_testid():
    assert 'data-testid="shipment-header"' in _src()


def test_header_awb_testid():
    assert 'data-testid="header-awb"' in _src()


def test_back_to_dashboard_testid():
    assert 'data-testid="back-to-dashboard"' in _src()


def test_no_batch_guard_testid():
    assert 'data-testid="no-batch"' in _src(), \
        "data-testid=\"no-batch\" guard must be present (renders when ?batch_id= absent)"


def test_skeleton_testid():
    assert 'data-testid="skeleton"' in _src(), \
        "data-testid=\"skeleton\" must be present for loading states"


def test_next_action_callout_testid():
    assert 'data-testid="next-action"' in _src(), \
        "data-testid=\"next-action\" callout must be present"


# ══════════════════════════════════════════════════════════════════════════════
# G — Per-tab content testids
# ══════════════════════════════════════════════════════════════════════════════

_TAB_TESTIDS = [
    "tab-control",
    "tab-timeline",
    "tab-intelligence",
    "tab-proposals",
    "tab-pz",
    "tab-sales",
    "tab-documents",
]


def test_all_tab_content_testids_present():
    src = _src()
    for tid in _TAB_TESTIDS:
        assert f'testid="{tid}"' in src or f"testid=\"{tid}\"" in src, (
            f"data-testid=\"{tid}\" must be present in shipment-detail-v3.html"
        )


# ══════════════════════════════════════════════════════════════════════════════
# H — No-write policy
# ══════════════════════════════════════════════════════════════════════════════

def test_no_post_patch_delete_methods():
    """The page is strictly read-only — inline apiFetch uses GET only."""
    src = _src()
    # Only check within the inline <script> block, not the comment text
    script_start = src.find("<script")
    script_content = src[script_start:] if script_start != -1 else src

    forbidden_method_patterns = [
        "method: 'POST'",
        'method: "POST"',
        "method: 'PATCH'",
        'method: "PATCH"',
        "method: 'DELETE'",
        'method: "DELETE"',
        "method: 'PUT'",
        'method: "PUT"',
    ]
    for pattern in forbidden_method_patterns:
        assert pattern not in script_content, (
            f"Write method '{pattern}' found in shipment-detail-v3.html — "
            "page must be strictly read-only (GET only via inline apiFetch)"
        )


def test_no_forbidden_write_endpoints():
    """No wFirma create, PZ create, DHL write, or customs mutation endpoints."""
    src = _src()
    forbidden_patterns = [
        "/wfirma/pz/create",
        "/wfirma/create",
        "/wfirma/proforma/create",
        "/wfirma/invoice",
        "/dhl/label",
        "/dhl/create",
        "/pz/process",
        "/pz/create",
        "/customs/mutation",
        "approve_proforma",
        "post_proforma",
    ]
    for pattern in forbidden_patterns:
        assert pattern not in src, (
            f"Forbidden write endpoint '{pattern}' found in shipment-detail-v3.html"
        )
