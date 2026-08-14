"""
Customer Communication Recipients — ONE resolver for customer To/CC.

Authority: Customer Master (child table + legacy bill_to/ship_to fallback).
Consumed by: customer document send, delivery confirmation, delivery reminder.

Does NOT own SMTP or the email queue. Does NOT invent emails from Proforma UI.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

# RFC-lite: local@domain with no whitespace / control / angle brackets.
_EMAIL_RE = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$")
_CTRL_OR_CRLF = re.compile(r"[\r\n\x00-\x1f\x7f]")


class RecipientValidationError(ValueError):
    """Invalid email syntax or header-injection attempt."""


def validate_email_address(raw: Any) -> str:
    """Return normalised address or raise RecipientValidationError."""
    if raw is None:
        raise RecipientValidationError("email is required")
    s = str(raw).strip()
    if not s:
        raise RecipientValidationError("email is required")
    if _CTRL_OR_CRLF.search(s):
        raise RecipientValidationError("email contains forbidden control characters")
    if "," in s or ";" in s or "<" in s or ">" in s:
        raise RecipientValidationError("email must be a single bare address")
    if len(s) > 254:
        raise RecipientValidationError("email exceeds maximum length")
    if not _EMAIL_RE.match(s):
        raise RecipientValidationError(f"invalid email syntax: {s!r}")
    return s


def _dedupe_preserve(addrs: Sequence[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for a in addrs:
        key = a.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(a)
    return out


def compose_recipient_lists(
    *,
    to: Sequence[str],
    cc: Sequence[str],
) -> Tuple[List[str], List[str]]:
    """Dedupe case-insensitively; drop CC entries that already appear in To."""
    to_clean = _dedupe_preserve([validate_email_address(a) for a in to if str(a).strip()])
    to_keys = {a.lower() for a in to_clean}
    cc_clean: List[str] = []
    seen_cc = set()
    for raw in cc:
        if not str(raw).strip():
            continue
        addr = validate_email_address(raw)
        key = addr.lower()
        if key in to_keys or key in seen_cc:
            continue
        seen_cc.add(key)
        cc_clean.append(addr)
    return to_clean, cc_clean


def format_address_list(addrs: Sequence[str]) -> str:
    """Comma-separated string for email_service.queue_email."""
    return ", ".join(a.strip() for a in addrs if a and str(a).strip())


def merge_cc_layers(
    *,
    customer_cc: Sequence[str],
    mandatory_internal_cc: Sequence[str],
    to: Sequence[str],
) -> List[str]:
    """Customer CC + mandatory internal CC; never promote internal into To."""
    to_keys = {a.strip().lower() for a in to if a and str(a).strip()}
    out: List[str] = []
    seen = set()
    for raw in list(customer_cc) + list(mandatory_internal_cc):
        if not str(raw).strip():
            continue
        try:
            addr = validate_email_address(raw)
        except RecipientValidationError:
            continue
        key = addr.lower()
        if key in to_keys or key in seen:
            continue
        seen.add(key)
        out.append(addr)
    return out


def resolve_customer_communication_recipients(
    *,
    db_path: Path,
    contractor_id: Optional[str] = None,
    customer: Any = None,
    to_override: Optional[Sequence[str]] = None,
    cc_override: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """Resolve To/CC for customer communications.

    Override lists (one-off send) replace the corresponding CM defaults for
    this call only — they are never persisted here.

    Legacy fallback when no active communication-recipient rows:
      bill_to_email, else ship_to_email (same as pick_email).
    """
    from . import customer_master as cm_mod
    from . import customer_master_db as cmdb

    db_path = Path(db_path)
    cmdb.init_db(db_path)

    if customer is None:
        if not contractor_id:
            return {
                "to": [],
                "cc": [],
                "source": "none",
                "primary": None,
            }
        customer = cmdb.get_customer(db_path, str(contractor_id).strip())
        if customer is None:
            return {
                "to": [],
                "cc": [],
                "source": "none",
                "primary": None,
            }

    cid = (getattr(customer, "bill_to_contractor_id", None) or contractor_id or "").strip()
    rows = cmdb.list_communication_recipients(db_path, cid) if cid else []

    stored_to = [
        r["email"] for r in rows
        if r.get("is_active") and (r.get("role") or "") == "to"
    ]
    stored_cc = [
        r["email"] for r in rows
        if r.get("is_active") and (r.get("role") or "") == "cc"
    ]
    # Deterministic: primary first among To, then sort_order / email.
    primary_emails = [
        r["email"] for r in rows
        if r.get("is_active") and (r.get("role") or "") == "to" and r.get("is_primary")
    ]

    source = "customer_master"
    if to_override is not None:
        to_list = [str(x).strip() for x in to_override if str(x).strip()]
        source = "send_override"
    elif stored_to:
        # Primary first, then remaining stored To in DB order.
        ordered: List[str] = []
        if primary_emails:
            ordered.append(primary_emails[0])
        for e in stored_to:
            if e.lower() not in {x.lower() for x in ordered}:
                ordered.append(e)
        to_list = ordered
        source = "customer_master"
    else:
        legacy = cm_mod.pick_email(customer)
        to_list = [legacy] if legacy else []
        source = "legacy_bill_to_ship_to" if legacy else "none"

    if cc_override is not None:
        cc_list = [str(x).strip() for x in cc_override if str(x).strip()]
        if source != "send_override":
            source = "send_override"
    else:
        cc_list = list(stored_cc)

    to_clean, cc_clean = compose_recipient_lists(to=to_list, cc=cc_list)
    primary = to_clean[0] if to_clean else None
    return {
        "to": to_clean,
        "cc": cc_clean,
        "source": source,
        "primary": primary,
        "contractor_id": cid or None,
    }


def replace_communication_recipients(
    *,
    db_path: Path,
    contractor_id: str,
    to: Sequence[Dict[str, Any]],
    cc: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    """Replace Customer Master communication recipients (atomic replace).

    Each entry: ``{"email": "...", "label": optional, "is_primary": bool}`` for To;
    CC entries omit is_primary.
    """
    from . import customer_master_db as cmdb

    db_path = Path(db_path)
    cid = (contractor_id or "").strip()
    if not cid:
        raise RecipientValidationError("contractor_id is required")

    cmdb.init_db(db_path)
    if cmdb.get_customer(db_path, cid) is None:
        raise LookupError(f"Customer not found: {cid}")

    to_rows: List[Dict[str, Any]] = []
    for i, item in enumerate(to or []):
        if not isinstance(item, dict):
            raise RecipientValidationError("to entries must be objects")
        email = validate_email_address(item.get("email"))
        to_rows.append({
            "email": email,
            "role": "to",
            "label": (str(item.get("label") or "").strip() or None),
            "is_primary": bool(item.get("is_primary")) if i == 0 or item.get("is_primary") else False,
            "is_active": True,
            "sort_order": i,
        })
    if to_rows and not any(r["is_primary"] for r in to_rows):
        to_rows[0]["is_primary"] = True
    # Exactly one primary.
    saw_primary = False
    for r in to_rows:
        if r["is_primary"] and not saw_primary:
            saw_primary = True
        else:
            r["is_primary"] = False

    cc_rows: List[Dict[str, Any]] = []
    for i, item in enumerate(cc or []):
        if not isinstance(item, dict):
            raise RecipientValidationError("cc entries must be objects")
        email = validate_email_address(item.get("email"))
        cc_rows.append({
            "email": email,
            "role": "cc",
            "label": (str(item.get("label") or "").strip() or None),
            "is_primary": False,
            "is_active": True,
            "sort_order": i,
        })

    # Cross-role: drop CC entries that collide with To (deterministic).
    to_keys = {r["email"].lower() for r in to_rows}
    cc_rows = [r for r in cc_rows if r["email"].lower() not in to_keys]

    # Within-role unique email (case-insensitive).
    for role_rows in (to_rows, cc_rows):
        keys = [r["email"].lower() for r in role_rows]
        if len(keys) != len(set(keys)):
            raise RecipientValidationError("duplicate email within role")

    cmdb.replace_communication_recipients(db_path, cid, to_rows + cc_rows)
    return resolve_customer_communication_recipients(
        db_path=db_path, contractor_id=cid,
    )
