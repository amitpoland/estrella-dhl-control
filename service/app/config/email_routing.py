"""
email_routing.py — Centralized email recipient configuration.

Single source of truth for all outgoing and expected-incoming addresses.
Import from here; never hardcode addresses elsewhere.

Usage:
    from ..config.email_routing import AGENCY_TO, AGENCY_CC, DHL_TO, INTERNAL_CC
    from ..config.email_routing import format_to, format_cc
"""
from __future__ import annotations

import re
from typing import List, Tuple

from ..core.config import settings

# Automatic B2 reply may only target a @dhl.com address from the inbound
# message (Reply-To preferred, else From). Hardcoded DHL_TO must not silently
# satisfy automatic eligibility.
_B2_DHL_ADDR_RE = re.compile(r"^[a-z0-9._%+\-]+@dhl\.com$", re.IGNORECASE)
_ANGLE_ADDR_RE = re.compile(r"<([^>]+@[^>]+)>")
_BARE_ADDR_RE = re.compile(r"[\w.+-]+@[\w.-]+\.\w+")

# ── Agency (external customs broker) ─────────────────────────────────────────

AGENCY_TO: List[str] = [
    # Spec v3 (docs/dhl_clearance_paths.md hard rule 7): TO is identical
    # for B1 (agency notification at upload) and B4 (forward complete
    # package after DHL DSK). Piotr is the AC Spedycja primary contact;
    # Grzegorz Ciągarlak (Ganther) is the forwarder/intermediary and
    # must receive both stages on TO alongside Piotr.
    "piotr@acspedycja.pl",
    "ciagarlak@ganther.com.pl",
]

AGENCY_CC: List[str] = [
    # Spec v3: agency CC is biuro + roman, plus the three Estrella
    # internal addresses (added separately at call sites). Ganther moved
    # to AGENCY_TO above per hard rule 7.
    "biuro@acspedycja.pl",
    "roman@acspedycja.pl",
]

# ── DHL ───────────────────────────────────────────────────────────────────────

DHL_TO: List[str] = [
    "odprawacelna@dhl.com",
]

# Known senders from which DHL forwards DSK (broker notification) documents.
# Incoming emails from these addresses trigger dsk_received tracking in audit.
DHL_DSK_SOURCE: List[str] = [
    "odprawacelna@dhl.com",
]

# ── Internal (Estrella Jewels) ────────────────────────────────────────────────

INTERNAL_CC: List[str] = [
    "info@estrellajewels.eu",
    "import@estrellajewels.eu",
    "account@estrellajewels.eu",
]

# ── Helpers ───────────────────────────────────────────────────────────────────

def format_to(recipients: List[str]) -> str:
    """
    Collapse a list of recipients to a comma-separated string for queue_email(to=…).
    Primary recipient is first; extras appear as a comma list.
    """
    return ", ".join(r.strip() for r in recipients if r.strip())


def format_cc(recipients: List[str]) -> str:
    """Collapse a CC list to a comma-separated string."""
    return ", ".join(r.strip() for r in recipients if r.strip())


def primary(recipients: List[str]) -> str:
    """Return the primary (first) recipient, or empty string if list is empty."""
    return recipients[0] if recipients else ""


def resolve_dhl_to() -> str:
    """Resolve the DHL TO recipient with the canonical fallback chain.

    Priority:
      1. ``DHL_TO`` constant (this module) — when non-empty and contains
         at least one non-blank address.
      2. ``settings.dhl_customs_email`` env var — fallback for non-prod
         environments where the constant may be intentionally empty.
      3. Empty string.

    Returns a comma-joined string suitable for ``queue_email(to=…)``.
    """
    if DHL_TO and any(addr for addr in DHL_TO):
        return format_to(DHL_TO)
    return (settings.dhl_customs_email or "").strip()


def resolve_dhl_cc() -> str:
    """Resolve the DHL CC recipient with the canonical fallback chain.

    Priority:
      1. ``INTERNAL_CC`` constant (this module) — when non-empty and
         contains at least one non-blank address.
      2. ``settings.dhl_customs_cc`` env var — fallback for non-prod
         environments where the constant may be intentionally empty.
      3. Empty string.

    Returns a comma-joined string suitable for ``queue_email(cc=…)``.
    """
    if INTERNAL_CC and any(addr for addr in INTERNAL_CC):
        return format_cc(INTERNAL_CC)
    return (settings.dhl_customs_cc or "").strip()


def is_dsk_source(sender: str) -> bool:
    """
    Return True if `sender` matches one of the known DHL DSK source addresses.
    Case-insensitive, strips whitespace.
    """
    sender_norm = sender.strip().lower()
    return sender_norm in {s.lower() for s in DHL_DSK_SOURCE}


def extract_mailbox_address(raw: str) -> str:
    """Return bare addr@domain from 'Name <addr@domain>' or a bare address."""
    if not raw:
        return ""
    m = _ANGLE_ADDR_RE.search(raw)
    if m:
        return m.group(1).strip().lower()
    m = _BARE_ADDR_RE.search(raw)
    return m.group(0).strip().lower() if m else ""


def is_allowed_dhl_reply_address(addr: str) -> bool:
    """True when addr is a bare @dhl.com mailbox (automatic B2 allowlist)."""
    return bool(addr) and bool(_B2_DHL_ADDR_RE.match(addr.strip()))


def resolve_b2_auto_reply_recipient(
    reply_to: str = "",
    from_header: str = "",
    sender: str = "",
) -> Tuple[str, str]:
    """
    Resolve automatic B2 TO from the authoritative inbound DHL message.

    Priority:
      1. Reply-To (if present and valid @dhl.com)
      2. From header / sender (if valid @dhl.com)
      3. empty — caller must HOLD (no hardcoded DHL_TO fallback)

    Returns ``(address, source)`` where source is
    ``reply_to`` | ``from`` | ``missing`` | ``invalid``.
    """
    saw_invalid = False
    for raw, source in (
        (reply_to, "reply_to"),
        (from_header or sender, "from"),
    ):
        addr = extract_mailbox_address(raw or "")
        if not addr:
            continue
        if is_allowed_dhl_reply_address(addr):
            return addr, source
        saw_invalid = True
    return "", "invalid" if saw_invalid else "missing"
