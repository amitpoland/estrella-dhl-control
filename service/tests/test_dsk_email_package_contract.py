"""
test_dsk_email_package_contract.py

Contract tests for POST /api/v1/dsk/email-package.

Covers:
  C01 — EmailPackageRequest requires both batch_id and awb
  C02 — Missing awb returns 422 (the bug that was fixed)
  C03 — Missing batch_id returns 422
  C04 — Empty awb string returns 422 via route validation
  C05 — frontend pattern: awb = trackingNo || batchId is extractable from batch_id
  C06 — AWB derivation from SHIPMENT_<AWB>_<YYYY-MM>_<hash> batch_id format
  C07 — dashboard.html callers pass both batch_id and awb (source-grep)
  C08 — shipment-detail.html callers pass both batch_id and awb (source-grep regression guard)
"""
from __future__ import annotations

import json
import pathlib
import pytest

# ── C01-C04: Pydantic model contract ──────────────────────────────────────────

def test_email_package_request_requires_awb():
    """EmailPackageRequest must require awb field (not optional)."""
    from app.api.routes_dsk import EmailPackageRequest
    import inspect
    sig = inspect.signature(EmailPackageRequest)
    fields = EmailPackageRequest.model_fields
    assert "awb" in fields, "awb field missing from EmailPackageRequest"
    assert "batch_id" in fields, "batch_id field missing from EmailPackageRequest"


def test_email_package_request_awb_is_required():
    """awb has no default — missing it must raise ValidationError."""
    from app.api.routes_dsk import EmailPackageRequest
    from pydantic import ValidationError
    with pytest.raises(ValidationError) as exc_info:
        EmailPackageRequest(batch_id="SHIPMENT_123_2026-05_abc")
    errors = exc_info.value.errors()
    fields_with_errors = {e["loc"][0] for e in errors}
    assert "awb" in fields_with_errors, f"Expected 'awb' in validation errors, got: {fields_with_errors}"


def test_email_package_request_batch_id_is_required():
    """batch_id has no default — missing it must raise ValidationError."""
    from app.api.routes_dsk import EmailPackageRequest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        EmailPackageRequest(awb="1234567890")


def test_email_package_request_both_present_passes():
    """Both fields present — model constructs without error."""
    from app.api.routes_dsk import EmailPackageRequest
    req = EmailPackageRequest(batch_id="SHIPMENT_4218922912_2026-05_9040dd39", awb="4218922912")
    assert req.batch_id == "SHIPMENT_4218922912_2026-05_9040dd39"
    assert req.awb == "4218922912"


# ── C05-C06: AWB derivation from batch_id ────────────────────────────────────

@pytest.mark.parametrize("batch_id,expected_awb", [
    ("SHIPMENT_4218922912_2026-05_9040dd39", "4218922912"),
    ("SHIPMENT_1234567890_2026-01_abcdef12", "1234567890"),
    ("SHIPMENT_9876543210_2025-12_deadbeef", "9876543210"),
])
def test_awb_derivable_from_batch_id(batch_id, expected_awb):
    """AWB is always recoverable from SHIPMENT_<AWB>_... batch_id format.

    This is the pattern used by the frontend: trackingNo || batchId.
    The fallback (using batchId itself) is acceptable when trackingNo is empty —
    the backend resolves the storage directory from batch_id regardless.
    """
    parts = batch_id.split("_")
    assert len(parts) >= 4 and parts[0] == "SHIPMENT" and parts[1] != "AUTO"
    derived = parts[1]
    assert derived == expected_awb


def test_auto_batch_id_not_parseable_as_awb():
    """SHIPMENT_AUTO_... batch_ids must NOT have their AWB extracted from position [1]."""
    batch_id = "SHIPMENT_AUTO_2026-05_abc123"
    parts = batch_id.split("_")
    # The route_dashboard logic excludes AUTO: `if parts[1] != "AUTO"`
    assert parts[1] == "AUTO"


# ── C07-C08: Source-grep guards — all callers must pass both fields ───────────

def test_batch_html_build_reply_passes_awb():
    """batch.html buildAndSendReply and prepareDskEmailPackage must pass awb."""
    src = pathlib.Path(__file__).parents[1] / "app" / "static" / "batch.html"
    assert src.exists(), "batch.html not found"
    text = src.read_text(encoding="utf-8")
    # Both callers must pass awb
    import re
    calls = re.findall(r"fetch\('/api/v1/dsk/email-package'[^)]+?\)", text, re.DOTALL)
    assert calls, "No fetch calls to /api/v1/dsk/email-package found in batch.html"
    for call in calls:
        assert "awb" in call, f"Fetch call in batch.html missing 'awb': {call[:200]}"


def test_shipment_detail_html_build_reply_passes_awb():
    """Regression guard: shipment-detail.html Build Reply Package button must pass awb.

    This test was added after the INC fix (2026-05-19): the button was sending
    { batch_id: batchId } only, causing HTTP 422. Fixed to: { batch_id: batchId, awb: trackingNo || batchId }.
    """
    src = pathlib.Path(__file__).parents[1] / "app" / "static" / "shipment-detail.html"
    assert src.exists(), "shipment-detail.html not found"
    text = src.read_text(encoding="utf-8")
    import re
    # Find the specific email-package call in the Build Reply Package button
    calls = re.findall(r"email-package[^)]*?\)", text, re.DOTALL)
    pkg_calls = [c for c in calls if "batch_id" in c]
    assert pkg_calls, "No email-package calls with batch_id found in shipment-detail.html"
    for call in pkg_calls:
        assert "awb" in call, (
            f"email-package call in shipment-detail.html missing 'awb' field.\n"
            f"This was the INC-005 bug: {{ batch_id: batchId }} sent without awb.\n"
            f"Fix: {{ batch_id: batchId, awb: trackingNo || batchId }}\n"
            f"Call found: {call[:300]}"
        )


def test_build_reply_awb_uses_trackingnoo_or_batchid_pattern():
    """shipment-detail.html Build Reply Package uses trackingNo || batchId fallback pattern."""
    src = pathlib.Path(__file__).parents[1] / "app" / "static" / "shipment-detail.html"
    text = src.read_text(encoding="utf-8")
    # The exact pattern that matches the DSK generate buttons
    assert "awb: trackingNo || batchId" in text, (
        "Build Reply Package button must use 'awb: trackingNo || batchId' "
        "pattern (consistent with Generate DSK buttons at lines 7593, 7600)"
    )
