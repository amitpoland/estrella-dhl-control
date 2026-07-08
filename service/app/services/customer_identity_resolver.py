"""customer_identity_resolver.py — WF-3 canonical customer identity authority.

ONE function answers "who is this customer?" and it is keyed on the wFirma
**contractor.id** — never a customer name. This consolidates the previously
scattered customer lookups into a single id-first authority so the rest of the
app resolves identity through one place instead of re-matching by name.

RESOLUTION ORDER (all id-keyed):
    1. Customer Master   — customer_master.bill_to_contractor_id  (CANONICAL)
    2. wFirma mirror     — wfirma_customer_mirror.contractor_id    (sync layer)
    3. legacy cache      — wfirma_customers.wfirma_customer_id      (deprecating)

NAME IS NEVER AN IDENTITY KEY. A name may be offered as an ADVISORY suggestion
(migration/validation only, `suggest_id_for_name`) but it is never authoritative
and never used as a write key. Renames therefore never break resolution: the
id resolves regardless of the current display name.

NON-DESTRUCTIVE MIGRATION (old -> new -> validate -> [retire later]):
    `backfill_legacy_contractor_ids()` (dry-run by default)
      * populates the id-keyed mirror from the legacy caches (reuses the existing
        reservation_db.backfill_customer_authority — no duplicate authority), and
      * fills the EMPTY wfirma_customers.wfirma_customer_id where the legacy row's
        name maps UNAMBIGUOUSLY to exactly one Customer Master contractor.id.
    Ambiguous / unmatched / already-linked legacy rows are left untouched and
    readable. The fill never overwrites an existing id (rollback-safe) and a
    second run fills nothing (idempotent).

AUTHORITY / SAFETY: read-only against every business authority. The only writes
are the two id-keyed, non-destructive migration writes above (mirror upsert +
legacy id-fill). It NEVER writes Product Master, inventory, accounting, carrier,
proforma, invoice, or any name key. It calls no wFirma customer API.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from . import customer_master_db
from . import reservation_db
from . import wfirma_db
from . import name_normalization


# ── path resolution ─────────────────────────────────────────────────────────

def _cm_path(explicit: Optional[Path] = None) -> Path:
    if explicit is not None:
        return Path(explicit)
    from ..core.config import settings
    return Path(settings.storage_root) / "customer_master.db"


def _res_path(explicit: Optional[Path] = None) -> Path:
    if explicit is not None:
        return Path(explicit)
    from ..core.config import settings
    return Path(settings.storage_root) / "reservation_queue.db"


def _norm(s: Optional[str]) -> str:
    return name_normalization.customer_resolution_normalize_name(s)


def _attr(obj: Any, key: str, default: str = "") -> str:
    """CustomerMaster is a dataclass; tolerate dict too. Return a stripped str."""
    if obj is None:
        return default
    v = getattr(obj, key, None)
    if v is None and isinstance(obj, dict):
        v = obj.get(key)
    return (str(v).strip() if v is not None else default)


# ── id-first resolution (the authority) ─────────────────────────────────────

def resolve_by_contractor_id(
    contractor_id: str,
    *,
    cm_path: Optional[Path] = None,
    res_path: Optional[Path] = None,
) -> Optional[Dict[str, Any]]:
    """Resolve a customer identity by wFirma contractor.id across the id-keyed
    stores, canonical-first. Returns a normalized record or None.

    Result shape::
        {"contractor_id", "name", "nip", "country", "source"}
    where source ∈ {customer_master, wfirma_customer_mirror, legacy_wfirma_customers}.
    """
    cid = (contractor_id or "").strip()
    if not cid:
        return None

    # 1. Customer Master — canonical.
    try:
        cm = customer_master_db.get_customer(_cm_path(cm_path), cid)
    except Exception:
        cm = None
    if cm is not None:
        return {
            "contractor_id": cid,
            "name": _attr(cm, "bill_to_name"),
            "nip": _attr(cm, "nip"),
            "country": _attr(cm, "country"),
            "source": "customer_master",
        }

    # 2. wFirma customer mirror — sync layer, id-keyed.
    try:
        mir = reservation_db.get_customer_mirror(_res_path(res_path), cid)
    except Exception:
        mir = None
    if mir:
        return {
            "contractor_id": cid,
            "name": (mir.get("client_name") or "").strip(),
            "nip": "",
            "country": "",
            "source": "wfirma_customer_mirror",
        }

    # 3. Legacy cache — by wfirma_customer_id (never by name).
    try:
        leg = wfirma_db.get_customer_by_wfirma_id(cid)
    except Exception:
        leg = None
    if leg:
        return {
            "contractor_id": cid,
            "name": (leg.get("client_name") or "").strip(),
            "nip": (leg.get("vat_id") or "").strip(),
            "country": (leg.get("country") or "").strip(),
            "source": "legacy_wfirma_customers",
        }

    return None


# ── name → id suggestion (ADVISORY ONLY — never an identity key) ─────────────

def suggest_id_for_name(
    name: str,
    *,
    cm_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Advisory-only: suggest the contractor.id for a display name by matching
    against Customer Master (normalized). This is used for MIGRATION/VALIDATION
    and operator advisories — NEVER as an authoritative identity or a write key.

    Returns {"suggested_contractor_id": str|None, "ambiguous": bool,
             "candidates": [contractor_id, …]}.
    A name that maps to two different contractor.ids is AMBIGUOUS → no suggestion.
    """
    norm = _norm(name)
    out: Dict[str, Any] = {"suggested_contractor_id": None, "ambiguous": False, "candidates": []}
    if not norm:
        return out
    try:
        masters = customer_master_db.list_customers(_cm_path(cm_path))
    except Exception:
        masters = []
    ids: List[str] = []
    for m in masters or []:
        if _norm(_attr(m, "bill_to_name")) == norm:
            cid = _attr(m, "bill_to_contractor_id")
            if cid and cid not in ids:
                ids.append(cid)
    out["candidates"] = ids
    if len(ids) == 1:
        out["suggested_contractor_id"] = ids[0]
    elif len(ids) > 1:
        out["ambiguous"] = True
    return out


def resolve(
    *,
    contractor_id: Optional[str] = None,
    name: Optional[str] = None,
    cm_path: Optional[Path] = None,
    res_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Single caller-agnostic entry point. Id-first; name is advisory only.

    Returns::
        {"resolved": bool, "contractor_id": str|None, "record": dict|None,
         "match_strategy": "contractor_id" | "name_advisory" | "unresolved",
         "advisory": str}
    A name is NEVER returned as an identity key. When only a name is supplied,
    the result is an advisory suggestion the caller may act on — it does not
    assert authority.
    """
    cid = (contractor_id or "").strip()
    if cid:
        rec = resolve_by_contractor_id(cid, cm_path=cm_path, res_path=res_path)
        if rec is not None:
            advisory = ""
            if name and _norm(name) and _norm(name) != _norm(rec["name"]):
                advisory = (
                    f"Supplied name {name!r} differs from the identity record "
                    f"{rec['name']!r} for contractor {cid}; contractor.id is "
                    f"authoritative (display-name drift only)."
                )
            return {"resolved": True, "contractor_id": cid, "record": rec,
                    "match_strategy": "contractor_id", "advisory": advisory}
        return {"resolved": False, "contractor_id": cid, "record": None,
                "match_strategy": "unresolved",
                "advisory": f"contractor.id {cid} not found in any identity store."}

    # No id — name is advisory only, never authoritative.
    if name and _norm(name):
        sug = suggest_id_for_name(name, cm_path=cm_path)
        if sug["suggested_contractor_id"]:
            rec = resolve_by_contractor_id(sug["suggested_contractor_id"],
                                           cm_path=cm_path, res_path=res_path)
            return {"resolved": False, "contractor_id": None, "record": rec,
                    "match_strategy": "name_advisory",
                    "advisory": (f"Name {name!r} suggests contractor "
                                 f"{sug['suggested_contractor_id']} — advisory only; "
                                 f"confirm the contractor.id before use.")}
        if sug["ambiguous"]:
            return {"resolved": False, "contractor_id": None, "record": None,
                    "match_strategy": "name_advisory",
                    "advisory": (f"Name {name!r} is ambiguous across "
                                 f"{len(sug['candidates'])} contractors — "
                                 f"cannot resolve by name; supply contractor.id.")}
    return {"resolved": False, "contractor_id": None, "record": None,
            "match_strategy": "unresolved", "advisory": "no contractor.id supplied."}


# ── non-destructive migration ───────────────────────────────────────────────

def backfill_legacy_contractor_ids(
    *,
    dry_run: bool = True,
    cm_path: Optional[Path] = None,
    res_path: Optional[Path] = None,
    wfirma_db_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Non-destructive migration (old -> new -> validate).

    Step 1 (only when not dry_run): populate the id-keyed mirror from the legacy
    caches via the existing reservation_db.backfill_customer_authority.
    Step 2: for each legacy wfirma_customers row with an EMPTY wfirma_customer_id,
    map its name to a Customer Master contractor.id; fill ONLY when exactly one
    match exists. Ambiguous / unmatched / already-linked rows are untouched.

    Returns a report with counts + per-row disposition. Idempotent and
    rollback-safe (never overwrites an existing id).
    """
    report: Dict[str, Any] = {
        "dry_run": dry_run,
        "mirror": None,
        "scanned": 0,
        "already_linked": 0,
        "filled": 0,
        "ambiguous": 0,
        "unmatched": 0,
        "entries": [],
    }

    # Step 1 — mirror population (id-keyed; reuse existing authority).
    if not dry_run:
        try:
            report["mirror"] = reservation_db.backfill_customer_authority(
                _res_path(res_path),
                wfirma_db_path=(wfirma_db_path or _wfirma_path()),
            )
        except Exception as exc:  # never break the report
            report["mirror"] = {"error": str(exc)}

    # Build normalized-name -> {contractor_id} index from Customer Master.
    try:
        masters = customer_master_db.list_customers(_cm_path(cm_path))
    except Exception:
        masters = []
    name_to_ids: Dict[str, List[str]] = {}
    for m in masters or []:
        nm = _norm(_attr(m, "bill_to_name"))
        cid = _attr(m, "bill_to_contractor_id")
        if nm and cid:
            name_to_ids.setdefault(nm, [])
            if cid not in name_to_ids[nm]:
                name_to_ids[nm].append(cid)

    # Step 2 — legacy id-fill.
    try:
        legacy_rows = wfirma_db.list_customers()
    except Exception:
        legacy_rows = []

    for row in legacy_rows or []:
        report["scanned"] += 1
        row_id = (row.get("id") or "").strip()
        cur_id = (row.get("wfirma_customer_id") or "").strip()
        cname = (row.get("client_name") or "").strip()
        if cur_id:
            report["already_linked"] += 1
            continue
        cands = name_to_ids.get(_norm(cname), [])
        if len(cands) == 1:
            target = cands[0]
            filled = False
            if not dry_run:
                filled = wfirma_db.backfill_contractor_id(row_id, target)
            report["filled"] += 1
            report["entries"].append(
                {"client_name": cname, "contractor_id": target,
                 "disposition": ("filled" if filled or dry_run else "fill_noop")})
        elif len(cands) > 1:
            report["ambiguous"] += 1
            report["entries"].append(
                {"client_name": cname, "contractor_id": None, "disposition": "ambiguous"})
        else:
            report["unmatched"] += 1
            report["entries"].append(
                {"client_name": cname, "contractor_id": None, "disposition": "unmatched"})

    return report


def _wfirma_path() -> Path:
    from ..core.config import settings
    return Path(settings.storage_root) / "wfirma.db"


__all__ = [
    "resolve_by_contractor_id",
    "suggest_id_for_name",
    "resolve",
    "backfill_legacy_contractor_ids",
]
