"""
dhl_thread_tracker.py — RFC822 References-aware thread tracking for DHL
self-clearance emails (P0).

Replaces subject-keyed thread_id derivation for DHL self-clearance threads
*only*. Other email types continue using the existing
`email_thread_mapper.normalise_subject` logic (untouched).

Why
===
DHL templated subjects collide across distinct shipments (e.g. every
"Clearance Information Required" subject normalises to the same string),
so subject-keyed thread_id fragments evidence. RFC822 References / In-Reply-To
chains give a stable per-thread identity that DHL's mail server propagates.

Fallback (gap-hunter requirement)
=================================
If neither References nor In-Reply-To is present (DHL sometimes starts a
fresh thread server-side — Risk R1), fall back to AWB-keyed search via
`email_evidence_store.get_by_awb`. When a fresh thread on a known AWB is
detected, the resolver appends the new thread_id to the manifest's
`thread_id_aliases[]` list and returns the *primary* thread_id (the first
known one) to keep evidence continuous.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, List, Optional, Tuple

from . import dhl_clearance_manifest as manifest
from . import email_evidence_store as evidence

# RFC822 References can be either angle-bracketed Message-IDs separated by
# whitespace or a single In-Reply-To value. We split on whitespace and pull
# anything between < and >.
_MSGID_RE = re.compile(r"<([^>\s]+)>")


# ── Header parsers ───────────────────────────────────────────────────────────

def parse_message_ids(header_value: Optional[str]) -> List[str]:
    """Extract all angle-bracketed message-ids from a header value. []  if none."""
    if not header_value:
        return []
    return _MSGID_RE.findall(header_value)


def derive_root_message_id(
    headers: Dict[str, Any],
) -> Optional[str]:
    """
    Return the *root* message-id of the thread, by precedence:
        1. First entry in References:    (oldest ancestor)
        2. In-Reply-To:                  (immediate parent)
        3. Message-ID:                   (this email is the root)
    Returns None when no usable header is present.
    """
    refs = parse_message_ids(headers.get("References") or headers.get("references"))
    if refs:
        return refs[0]
    in_reply_to = parse_message_ids(
        headers.get("In-Reply-To") or headers.get("in_reply_to")
    )
    if in_reply_to:
        return in_reply_to[0]
    msgid = parse_message_ids(headers.get("Message-ID") or headers.get("message_id"))
    if msgid:
        return msgid[0]
    return None


def _hash_thread_id(root_message_id: str) -> str:
    """Stable, opaque thread_id derived from the root Message-ID."""
    h = hashlib.sha1(root_message_id.encode("utf-8")).hexdigest()[:16]
    return f"thr:{h}"


# ── Resolver ─────────────────────────────────────────────────────────────────

def resolve_thread_id(
    message_headers: Dict[str, Any],
    awb:             str,
) -> Tuple[str, str]:
    """
    Resolve a stable thread_id for an inbound DHL self-clearance email.

    Returns (thread_id, resolution_source):
        ("thr:<hash>", "references")     — derived from References / In-Reply-To
        ("thr:<hash>", "message_id")     — first message in a new thread
        ("<existing>", "awb_fallback")   — RFC822 unavailable; resolved via AWB
        ("",           "no_evidence")    — no headers and no AWB record found
    """
    root = derive_root_message_id(message_headers or {})
    if root:
        # Distinguish first-message (Message-ID only) vs continuation
        refs = parse_message_ids(
            (message_headers or {}).get("References")
            or (message_headers or {}).get("references")
        )
        in_reply_to = parse_message_ids(
            (message_headers or {}).get("In-Reply-To")
            or (message_headers or {}).get("in_reply_to")
        )
        source = "references" if (refs or in_reply_to) else "message_id"
        return _hash_thread_id(root), source

    # Fallback — look up by AWB in email_evidence_store.
    if awb:
        doc = evidence.get_by_awb(awb)
        threads: List[Dict[str, Any]] = doc.get("threads") or []
        if threads:
            primary = threads[0].get("thread_id") or ""
            if primary:
                return primary, "awb_fallback"

    return "", "no_evidence"


# ── Alias maintenance (Risk R1) ─────────────────────────────────────────────

def record_alias_if_new(
    audit:         Dict[str, Any],
    new_thread_id: str,
) -> bool:
    """
    If *new_thread_id* differs from the manifest's primary thread_id, record
    it on `thread_id_aliases[]`. Returns True iff an alias was newly added.
    """
    if not new_thread_id:
        return False
    manifest.init_manifest(audit)
    block = audit[manifest.MANIFEST_KEY]
    primary = block.get("thread_id") or ""
    if not primary:
        # First thread seen — establish it as primary.
        block["thread_id"] = new_thread_id
        return False
    if new_thread_id == primary:
        return False
    aliases: List[str] = block.setdefault("thread_id_aliases", [])
    if new_thread_id in aliases:
        return False
    aliases.append(new_thread_id)
    return True
