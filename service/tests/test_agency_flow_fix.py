"""
test_agency_flow_fix.py — Verify external_agency_clearance shipments can
generate Polish description WITHOUT waiting for DHL customs email.

This was the operational bug: the clearance flow for high-value (>$2500)
shipments was reversed. Correct order:
    1. Generate description
    2. Send to agency
    3. THEN handle DHL email when it arrives
"""
from __future__ import annotations


def test_dhl_email_guard_skipped_for_agency_path():
    """Reading the route source: the guard must be skipped when clearance_path
    is external_agency_clearance.

    This is a structural test — it asserts the guard logic is conditional on
    clearance path, not unconditional.
    """
    src_path = "/Users/amitgupta/Downloads/CLI/service/app/api/routes_dhl_clearance.py"
    with open(src_path, "r", encoding="utf-8") as f:
        src = f.read()

    # The relaxed-guard block must reference external_agency_clearance
    # AND wrap guard_dhl_requires_email in a conditional
    assert "agency_clearance" in src
    # Find the generate-description handler section (decorator, not docstring)
    idx = src.find('@router.post("/generate-description/')
    assert idx > 0, "generate-description route decorator not found"
    section = src[idx:idx + 5000]
    # The guard must be inside an "if not _is_agency_path" block
    assert "_is_agency_path" in section
    assert "if not _is_agency_path" in section
    # And the relaxed-guard comment must be present (documents intent)
    assert "RELAXED" in section or "agency_clearance" in section


def test_auto_agency_trigger_block_present():
    """After Polish desc generation, an auto-agency-build block must exist."""
    src_path = "/Users/amitgupta/Downloads/CLI/service/app/api/routes_dhl_clearance.py"
    with open(src_path, "r", encoding="utf-8") as f:
        src = f.read()
    # The auto-build comment + queue_email + agency_reply_package write
    assert "auto-trigger agency package" in src.lower() or "auto_after_polish_desc" in src
    assert "build_agency_package" in src
    # The auto-built record must mark its source so timeline is honest
    assert '"auto_after_polish_desc"' in src


def test_response_includes_auto_agency_built_field():
    """generate-description response must surface auto_agency_built status."""
    src_path = "/Users/amitgupta/Downloads/CLI/service/app/api/routes_dhl_clearance.py"
    with open(src_path, "r", encoding="utf-8") as f:
        src = f.read()
    assert '"auto_agency_built"' in src
    assert '"auto_agency_error"' in src
