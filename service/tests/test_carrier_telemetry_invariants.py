"""
Phase I tests — carrier telemetry invariant guards.

One positive test (invariant holds → no exception) and one negative
fail-loud test (invariant violated → InvariantViolation raised) per guard,
plus exception-message safety assertions.

No DB, no HTTP, no production storage, no side effects.
"""
from __future__ import annotations

import base64
import os
from pathlib import Path

import pytest

from app.services.carrier.telemetry.invariants import (
    InvariantViolation,
    assert_no_label_bytes,
    assert_no_large_base64,
    assert_no_pdf_header,
    assert_no_real_awb_in_shadow,
    assert_plt_path_contained,
    assert_shadow_result_is_simulated,
    assert_valid_carrier_gate_status,
    assert_webhook_signature_verified,
)
from app.services.carrier.models.shipment import (
    ShipmentMode,
    ShipmentResult,
    ShipmentState,
)


# ── helpers ───────────────────────────────────────────────────────────────────


def _large_b64(byte_count: int = 1024) -> str:
    return base64.b64encode(os.urandom(byte_count)).decode()


def _shadow_result(tracking_ref: str | None = "SIM-ABCD1234", simulated: bool = True) -> ShipmentResult:
    return ShipmentResult(
        idempotency_key="a" * 64,
        mode=ShipmentMode.SHADOW,
        state=ShipmentState.COMPLETE,
        tracking_ref=tracking_ref,
        simulated=simulated,
    )


def _live_result(tracking_ref: str = "1234567890") -> ShipmentResult:
    return ShipmentResult(
        idempotency_key="b" * 64,
        mode=ShipmentMode.LIVE,
        state=ShipmentState.COMPLETE,
        tracking_ref=tracking_ref,
        simulated=False,
    )


# ══════════════════════════════════════════════════════════════════════════════
# Guard 1: assert_no_label_bytes (dict payload scan)
# ══════════════════════════════════════════════════════════════════════════════


def test_no_label_bytes_clean_payload_passes():
    payload = {"status": "ok", "mode": "shadow", "tracking_ref": "SIM-ABCD1234"}
    assert_no_label_bytes(payload)  # must not raise


def test_no_label_bytes_nested_clean_passes():
    payload = {"outer": {"inner": {"value": "normal text"}}, "count": 3}
    assert_no_label_bytes(payload)  # must not raise


def test_no_label_bytes_pdf_header_raises():
    payload = {"document": "%PDF-1.4 binary content"}
    with pytest.raises(InvariantViolation):
        assert_no_label_bytes(payload)


def test_no_label_bytes_large_b64_raises():
    payload = {"someField": _large_b64(1024)}
    with pytest.raises(InvariantViolation):
        assert_no_label_bytes(payload)


def test_no_label_bytes_nested_large_b64_raises():
    payload = {"data": {"label": _large_b64(1024)}}
    with pytest.raises(InvariantViolation):
        assert_no_label_bytes(payload)


def test_no_label_bytes_list_value_raises():
    payload = {"pieces": [{"label": _large_b64(512)}]}
    with pytest.raises(InvariantViolation):
        assert_no_label_bytes(payload)


def test_no_label_bytes_exception_does_not_echo_value():
    """Exception message must never contain the binary blob."""
    blob = _large_b64(512)
    payload = {"secret_field": blob}
    with pytest.raises(InvariantViolation) as exc:
        assert_no_label_bytes(payload)
    assert blob not in str(exc.value)


# ══════════════════════════════════════════════════════════════════════════════
# Guard 2: assert_no_pdf_header (single string)
# ══════════════════════════════════════════════════════════════════════════════


def test_no_pdf_header_normal_string_passes():
    assert_no_pdf_header("This is normal text, not a PDF.")


def test_no_pdf_header_empty_string_passes():
    assert_no_pdf_header("")


def test_no_pdf_header_pdf_magic_raises():
    with pytest.raises(InvariantViolation):
        assert_no_pdf_header("%PDF-1.4 ...")


def test_no_pdf_header_exact_prefix_raises():
    with pytest.raises(InvariantViolation):
        assert_no_pdf_header("%PDF-")


def test_no_pdf_header_pdf_embedded_but_not_prefix_passes():
    """String containing %PDF- not at position 0 should pass."""
    assert_no_pdf_header("Some prefix %PDF-1.4 content")


def test_no_pdf_header_exception_message_is_safe():
    """Exception must not echo the value."""
    value = "%PDF-1.4" + "x" * 200
    with pytest.raises(InvariantViolation) as exc:
        assert_no_pdf_header(value)
    assert value not in str(exc.value)


# ══════════════════════════════════════════════════════════════════════════════
# Guard 3: assert_no_large_base64 (single string)
# ══════════════════════════════════════════════════════════════════════════════


def test_no_large_base64_short_string_passes():
    assert_no_large_base64("abc123==")


def test_no_large_base64_long_text_with_spaces_passes():
    text = "The quick brown fox jumps over the lazy dog. " * 20
    assert_no_large_base64(text)


def test_no_large_base64_url_passes():
    url = "https://express.api.dhl.com/shipments?awb=1234567890&locale=en" * 3
    assert_no_large_base64(url)


def test_no_large_base64_exactly_512_chars_raises():
    # 512 chars of base64 alphabet = at threshold
    value = "A" * 512
    with pytest.raises(InvariantViolation):
        assert_no_large_base64(value)


def test_no_large_base64_random_bytes_encoded_raises():
    with pytest.raises(InvariantViolation):
        assert_no_large_base64(_large_b64(1024))


def test_no_large_base64_511_chars_passes():
    # One under the length threshold
    assert_no_large_base64("A" * 511)


def test_no_large_base64_exception_does_not_echo_value():
    """Exception must not echo the base64 blob."""
    blob = _large_b64(512)
    with pytest.raises(InvariantViolation) as exc:
        assert_no_large_base64(blob)
    assert blob not in str(exc.value)


def test_no_large_base64_exception_contains_length():
    """Exception should state the length for diagnosability."""
    value = "A" * 600
    with pytest.raises(InvariantViolation) as exc:
        assert_no_large_base64(value)
    assert "600" in str(exc.value)


# ══════════════════════════════════════════════════════════════════════════════
# Guard 4: assert_no_real_awb_in_shadow
# ══════════════════════════════════════════════════════════════════════════════


def test_no_real_awb_shadow_sim_prefix_passes():
    assert_no_real_awb_in_shadow(_shadow_result("SIM-ABCD1234"))


def test_no_real_awb_shadow_none_ref_passes():
    assert_no_real_awb_in_shadow(_shadow_result(tracking_ref=None))


def test_no_real_awb_live_mode_not_checked():
    """Live mode is out of scope for this guard — must not raise."""
    assert_no_real_awb_in_shadow(_live_result("1234567890"))


def test_no_real_awb_shadow_real_awb_raises():
    result = _shadow_result(tracking_ref="1234567890")
    with pytest.raises(InvariantViolation):
        assert_no_real_awb_in_shadow(result)


def test_no_real_awb_shadow_non_sim_prefix_raises():
    result = _shadow_result(tracking_ref="DHL-REAL-AWB")
    with pytest.raises(InvariantViolation):
        assert_no_real_awb_in_shadow(result)


def test_no_real_awb_exception_does_not_echo_ref():
    """Exception must not reveal the actual tracking ref value."""
    real_awb = "9876543210-REAL"
    result = _shadow_result(tracking_ref=real_awb)
    with pytest.raises(InvariantViolation) as exc:
        assert_no_real_awb_in_shadow(result)
    assert real_awb not in str(exc.value)


# ══════════════════════════════════════════════════════════════════════════════
# Guard 5: assert_shadow_result_is_simulated
# ══════════════════════════════════════════════════════════════════════════════


def test_shadow_simulated_true_passes():
    assert_shadow_result_is_simulated(_shadow_result(simulated=True))


def test_live_result_not_checked_by_guard():
    """Live results are not constrained by this guard."""
    assert_shadow_result_is_simulated(_live_result())


def test_shadow_simulated_false_raises():
    result = _shadow_result(simulated=False)
    with pytest.raises(InvariantViolation):
        assert_shadow_result_is_simulated(result)


def test_shadow_simulated_false_exception_is_clear():
    result = _shadow_result(simulated=False)
    with pytest.raises(InvariantViolation) as exc:
        assert_shadow_result_is_simulated(result)
    assert "shadow" in str(exc.value).lower()
    assert "simulated" in str(exc.value).lower()


# ══════════════════════════════════════════════════════════════════════════════
# Guard 6: assert_webhook_signature_verified
# ══════════════════════════════════════════════════════════════════════════════


def test_webhook_verified_true_passes():
    assert_webhook_signature_verified(True)


def test_webhook_verified_false_raises():
    with pytest.raises(InvariantViolation):
        assert_webhook_signature_verified(False)


def test_webhook_exception_does_not_echo_any_signature():
    """Exception must contain no signature-like content — just a descriptive message."""
    with pytest.raises(InvariantViolation) as exc:
        assert_webhook_signature_verified(False)
    msg = str(exc.value)
    # Message should mention signature/verification, not any value
    assert "signature" in msg.lower() or "verified" in msg.lower()
    # Must not contain any hex-like long string (which could be a leaked sig)
    import re
    assert not re.search(r"[0-9a-f]{32,}", msg)


# ══════════════════════════════════════════════════════════════════════════════
# Guard 7: assert_plt_path_contained
# ══════════════════════════════════════════════════════════════════════════════


def test_plt_path_inside_root_passes(tmp_path):
    plt_root = tmp_path / "carrier" / "plt"
    plt_root.mkdir(parents=True)
    target = plt_root / "BATCH-001" / "label.pdf"
    assert_plt_path_contained(target, tmp_path)


def test_plt_path_directly_in_plt_root_passes(tmp_path):
    plt_root = tmp_path / "carrier" / "plt"
    plt_root.mkdir(parents=True)
    target = plt_root / "some_file.pdf"
    assert_plt_path_contained(target, tmp_path)


def test_plt_path_outside_storage_root_raises(tmp_path):
    outside = tmp_path.parent / "escaped" / "label.pdf"
    with pytest.raises(InvariantViolation):
        assert_plt_path_contained(outside, tmp_path)


def test_plt_path_traversal_raises(tmp_path):
    plt_root = tmp_path / "carrier" / "plt"
    plt_root.mkdir(parents=True)
    escape = plt_root / ".." / ".." / ".." / "etc" / "passwd"
    with pytest.raises(InvariantViolation):
        assert_plt_path_contained(escape, tmp_path)


def test_plt_path_under_carrier_but_not_plt_raises(tmp_path):
    carrier_root = tmp_path / "carrier"
    carrier_root.mkdir(parents=True)
    wrong = carrier_root / "not_plt" / "label.pdf"
    with pytest.raises(InvariantViolation):
        assert_plt_path_contained(wrong, tmp_path)


def test_plt_path_exception_contains_path_info(tmp_path):
    outside = tmp_path.parent / "somewhere_else" / "label.pdf"
    with pytest.raises(InvariantViolation) as exc:
        assert_plt_path_contained(outside, tmp_path)
    # Path info is not sensitive — safe to include in message
    assert str(tmp_path) in str(exc.value) or "outside" in str(exc.value).lower() or "PLT" in str(exc.value)


# ══════════════════════════════════════════════════════════════════════════════
# Guard 8: assert_valid_carrier_gate_status
# ══════════════════════════════════════════════════════════════════════════════


def test_gate_status_pending_passes():
    assert_valid_carrier_gate_status("pending")


def test_gate_status_shadow_passes():
    assert_valid_carrier_gate_status("shadow")


def test_gate_status_live_passes():
    assert_valid_carrier_gate_status("live")


def test_gate_status_unknown_raises():
    with pytest.raises(InvariantViolation):
        assert_valid_carrier_gate_status("unknown")


def test_gate_status_empty_raises():
    with pytest.raises(InvariantViolation):
        assert_valid_carrier_gate_status("")


def test_gate_status_mixed_case_raises():
    """Status values are case-sensitive."""
    with pytest.raises(InvariantViolation):
        assert_valid_carrier_gate_status("Shadow")


def test_gate_status_exception_contains_bad_value():
    """Status string is not sensitive — safe to echo in message."""
    with pytest.raises(InvariantViolation) as exc:
        assert_valid_carrier_gate_status("rogue_status")
    assert "rogue_status" in str(exc.value)


def test_gate_status_exception_lists_valid_values():
    with pytest.raises(InvariantViolation) as exc:
        assert_valid_carrier_gate_status("bad")
    msg = str(exc.value)
    assert "pending" in msg
    assert "shadow" in msg
    assert "live" in msg


# ══════════════════════════════════════════════════════════════════════════════
# Cross-guard: InvariantViolation is always raised, never False
# ══════════════════════════════════════════════════════════════════════════════


def test_all_guards_raise_invariant_violation_not_assertion_error():
    """Every guard must raise InvariantViolation specifically, not generic exceptions."""
    cases = [
        lambda: assert_no_pdf_header("%PDF-1.4 content"),
        lambda: assert_no_large_base64("A" * 600),
        lambda: assert_no_label_bytes({"x": _large_b64()}),
        lambda: assert_no_real_awb_in_shadow(_shadow_result("REAL-AWB-9999")),
        lambda: assert_shadow_result_is_simulated(_shadow_result(simulated=False)),
        lambda: assert_webhook_signature_verified(False),
        lambda: assert_valid_carrier_gate_status("bad"),
    ]
    for fn in cases:
        with pytest.raises(InvariantViolation):
            fn()


def test_invariant_violation_is_exception_subclass():
    assert issubclass(InvariantViolation, Exception)
