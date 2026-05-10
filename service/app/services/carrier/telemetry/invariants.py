"""
Carrier subsystem invariant guards.

Each guard function either returns None (invariant holds) or raises
InvariantViolation. There are no silent failures.

Eight invariants:
  1. assert_no_label_bytes        — no binary label data in a payload dict
  2. assert_no_pdf_header         — string value must not start with %PDF-
  3. assert_no_large_base64       — string value must not be a large base64 blob
  4. assert_no_real_awb_in_shadow — shadow results must carry SIM- refs only
  5. assert_shadow_result_is_simulated — shadow ShipmentResult.simulated must be True
  6. assert_webhook_signature_verified — must not process unverified webhook
  7. assert_plt_path_contained    — PLT path must resolve under storage_root/carrier/plt/
  8. assert_valid_carrier_gate_status — status must be pending / shadow / live

Safety contract:
  Exception messages never echo sensitive content:
    - No payload field values.
    - No tracking reference values.
    - No signature or secret values.
    - No large binary blobs.

No HTTP, no DB, no file writes, no side effects.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


class InvariantViolation(Exception):
    """Raised when a carrier subsystem invariant is violated."""


# ── detection constants (mirrors redactor thresholds) ─────────────────────────

_MIN_SUSPICIOUS_LEN: int = 512
_BASE64_RATIO_THRESHOLD: float = 0.95
_BASE64_ALPHABET: frozenset = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=_-"
)
_PDF_HEADER: str = "%PDF-"
_VALID_GATE_STATUSES: frozenset = frozenset({"pending", "shadow", "live"})
_SHADOW_SIM_PREFIX: str = "SIM-"


# ── guard 2: PDF magic header ─────────────────────────────────────────────────


def assert_no_pdf_header(value: str) -> None:
    """Guard 2 — string value must not start with the PDF magic header."""
    if value.startswith(_PDF_HEADER):
        raise InvariantViolation(
            "Invariant violated: string value begins with PDF magic header (%PDF-). "
            "Possible unredacted label binary."
        )


# ── guard 3: large base64 blob ────────────────────────────────────────────────


def assert_no_large_base64(value: str) -> None:
    """Guard 3 — string value must not be a suspiciously large base64 blob."""
    if len(value) < _MIN_SUSPICIOUS_LEN:
        return
    b64_count = sum(1 for c in value if c in _BASE64_ALPHABET)
    ratio = b64_count / len(value)
    if ratio >= _BASE64_RATIO_THRESHOLD:
        raise InvariantViolation(
            f"Invariant violated: string value (length={len(value)}, "
            f"base64_ratio={ratio:.2f}) exceeds binary-detection threshold. "
            "Possible unredacted binary data."
        )


# ── guard 1: no label bytes in payload dict ───────────────────────────────────


def _scan_node(node: Any, path: str) -> None:
    """Recursively scan a payload node for binary-like values."""
    if isinstance(node, dict):
        for k, v in node.items():
            _scan_node(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, item in enumerate(node):
            _scan_node(item, f"{path}[{i}]")
    elif isinstance(node, str):
        if node.startswith(_PDF_HEADER):
            raise InvariantViolation(
                f"Invariant violated: payload field at {path!r} begins with "
                "PDF magic header. Possible unredacted label binary."
            )
        if len(node) >= _MIN_SUSPICIOUS_LEN:
            b64_count = sum(1 for c in node if c in _BASE64_ALPHABET)
            if (b64_count / len(node)) >= _BASE64_RATIO_THRESHOLD:
                raise InvariantViolation(
                    f"Invariant violated: payload field at {path!r} "
                    f"(length={len(node)}) has suspiciously high base64 ratio. "
                    "Possible unredacted binary data."
                )


def assert_no_label_bytes(payload: dict) -> None:
    """
    Guard 1 — payload dict must contain no binary label data.

    Scans all string values recursively. Raises on PDF header or
    suspiciously large base64 content. Does not echo field values.
    """
    _scan_node(payload, "$")


# ── guard 4: no real AWB in shadow mode ───────────────────────────────────────


def assert_no_real_awb_in_shadow(result: Any) -> None:
    """
    Guard 4 — shadow mode results must not carry real DHL AWB tracking refs.

    Shadow tracking refs must start with 'SIM-'. Any other non-None ref in
    shadow mode indicates a real AWB has leaked into a simulated result.
    Exception does not echo the tracking ref value.
    """
    from ..models.shipment import ShipmentMode

    if result.mode != ShipmentMode.SHADOW:
        return
    if result.tracking_ref is None:
        return
    if not result.tracking_ref.startswith(_SHADOW_SIM_PREFIX):
        raise InvariantViolation(
            "Invariant violated: shadow mode result carries a tracking ref "
            f"without the required '{_SHADOW_SIM_PREFIX}' prefix. "
            "Real DHL AWBs must not appear in shadow mode results."
        )


# ── guard 5: shadow result must be marked simulated ──────────────────────────


def assert_shadow_result_is_simulated(result: Any) -> None:
    """
    Guard 5 — shadow mode ShipmentResult.simulated must be True.

    A shadow result with simulated=False would indicate the result was
    produced by a live adapter call, which violates the shadow isolation
    invariant.
    """
    from ..models.shipment import ShipmentMode

    if result.mode != ShipmentMode.SHADOW:
        return
    if not result.simulated:
        raise InvariantViolation(
            "Invariant violated: shadow mode ShipmentResult has simulated=False. "
            "Shadow results must always be produced by the simulated adapter."
        )


# ── guard 6: webhook signature must be verified ───────────────────────────────


def assert_webhook_signature_verified(verified: bool) -> None:
    """
    Guard 6 — a webhook event must not be processed unless its HMAC
    signature has been successfully verified.

    Takes a boolean flag; does not accept or echo any signature value.
    """
    if not verified:
        raise InvariantViolation(
            "Invariant violated: attempting to process a webhook event whose "
            "HMAC signature has not been verified or has failed verification."
        )


# ── guard 7: PLT path must be inside storage_root ────────────────────────────


def assert_plt_path_contained(path: Path, storage_root: Path) -> None:
    """
    Guard 7 — PLT file path must resolve inside storage_root/carrier/plt/.

    Uses resolve() + relative_to() — identical containment logic to
    PltStorage.write(). Catches symlink escapes and path traversal.
    Path need not exist; strict=False resolve is used.
    """
    plt_root = (Path(storage_root) / "carrier" / "plt").resolve()
    resolved = Path(path).resolve()
    try:
        resolved.relative_to(plt_root)
    except ValueError:
        raise InvariantViolation(
            f"Invariant violated: PLT path resolves to {str(resolved)!r}, "
            f"which is outside the PLT storage root {str(plt_root)!r}."
        )


# ── guard 8: carrier gate status must be known ───────────────────────────────


def assert_valid_carrier_gate_status(status: str) -> None:
    """
    Guard 8 — carrier gate status must be one of the defined values.

    Unknown status strings indicate misconfiguration or a code path that
    bypassed the factory gate validation.
    """
    if status not in _VALID_GATE_STATUSES:
        raise InvariantViolation(
            f"Invariant violated: unknown carrier gate status {status!r}. "
            f"Valid values: {sorted(_VALID_GATE_STATUSES)}."
        )
