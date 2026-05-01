"""
email_routing.py — Centralized email recipient configuration.

Single source of truth for all outgoing and expected-incoming addresses.
Import from here; never hardcode addresses elsewhere.

Usage:
    from ..config.email_routing import AGENCY_TO, AGENCY_CC, DHL_TO, INTERNAL_CC
    from ..config.email_routing import format_to, format_cc
"""
from __future__ import annotations

from typing import List

# ── Agency (external customs broker) ─────────────────────────────────────────

AGENCY_TO: List[str] = [
    "piotr@acspedycja.pl",
]

AGENCY_CC: List[str] = [
    "biuro@acspedycja.pl",
    "roman@acspedycja.pl",
    "ciagarlak@ganther.com.pl",
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


def is_dsk_source(sender: str) -> bool:
    """
    Return True if `sender` matches one of the known DHL DSK source addresses.
    Case-insensitive, strips whitespace.
    """
    sender_norm = sender.strip().lower()
    return sender_norm in {s.lower() for s in DHL_DSK_SOURCE}
