"""
apply_snapshot_profiles_to_master.py — merge invoice-snapshot profiles into
the local customer_master DB without trampling operator-enriched data.

Rules (LOCKED):
  Field                                | Behaviour
  -------------------------------------+------------------------------------------------
  default_currency                     | fill from preferred_currency only if empty
  default_language_id                  | fill from preferred_language_id only if empty
  insurance_min_override               | fill from insurance_min_detected only if empty
  ship_to_*  (Shape A or Shape B)      | NEVER touched
  credit_*  (limit, currency)          | NEVER touched
  kuke_*    (approved, limit, currency,| NEVER touched
            expiry, risk_status)       |
  notes                                | NEVER touched (no append mode in v1)

  --apply  required to write; default is dry-run.
  --force  required to overwrite a non-empty customer_master field with the
           snapshot value. Even with --force, ship_to/credit/Kuke are NEVER
           touched.

Confidence-state policy:
  EMPTY                  → skip entirely
  SINGLE_DOC / STALE_LOW → allow merge, but mark each row with a 'warn' flag
                            so the operator can audit (visible in summary table)
  CONSISTENT_RECENT      → merge cleanly
  VARYING                → still merges per-field, but each fill carries a warn

The CLI prints a per-row table:
   contractor_id | field | old | new | action

  action ∈ {
    'fill'                      — was empty, now filled
    'skip_already_set'          — non-empty + no --force
    'force_overwrite'           — non-empty + --force
    'skip_no_master_record'     — customer_master has no row for this contractor
    'skip_empty_profile'        — profile.confidence_state == EMPTY
    'warn_low_confidence'       — single_doc / stale_low / varying — fill happens too
  }
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field as dc_field, replace
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def _bootstrap() -> None:
    here = Path(__file__).resolve()
    repo_root = here.parents[3]
    service_dir = here.parents[2]
    for p in (str(repo_root), str(service_dir)):
        if p not in sys.path:
            sys.path.insert(0, p)


_bootstrap()

from app.services.customer_master_db import (   # noqa: E402
    CustomerMaster, get_customer, init_db as init_master_db, upsert_customer,
)
from app.services.customer_invoice_snapshot_db import (   # noqa: E402
    ProfileSnapshotRow, list_profiles,
)


# ── Confidence state names — must match snapshot DB ──────────────────────────

CONF_EMPTY              = "EMPTY"
CONF_SINGLE_DOC         = "SINGLE_DOC"
CONF_STALE_LOW          = "STALE_LOW"
CONF_CONSISTENT_RECENT  = "CONSISTENT_RECENT"
CONF_VARYING            = "VARYING"

LOW_CONFIDENCE_STATES = frozenset({CONF_SINGLE_DOC, CONF_STALE_LOW, CONF_VARYING})


# ── Field merge plan ─────────────────────────────────────────────────────────

# Snapshot field name → CustomerMaster field name.
# This list is the contract: the merger will only touch these mappings.
# Operator-only fields (insurance_min_override, ship_to_*, credit_*, kuke_*)
# are intentionally NOT in this list and NEVER auto-filled.
MERGE_FIELDS: List[Tuple[str, str]] = [
    # Commercial defaults
    ("preferred_currency",          "default_currency"),
    ("preferred_language_id",       "default_language_id"),
    ("preferred_invoice_series_id", "preferred_invoice_series_id"),
    ("vat_mode",                    "vat_mode"),
    # Freight intelligence
    ("last_freight_amount",         "freight_last_amount"),
    ("avg_freight_amount",          "freight_avg_amount"),
    ("freight_mode",                "freight_mode"),
    ("preferred_currency",          "freight_currency"),
    # Insurance intelligence
    ("insurance_min_detected",      "insurance_min_amount"),
    ("insurance_mode",              "insurance_mode"),
]

# Fields the merger will NEVER touch even with --force.
NEVER_TOUCH_FIELDS = frozenset({
    "ship_to_use_alternate", "ship_to_name", "ship_to_person",
    "ship_to_street", "ship_to_city", "ship_to_zip",
    "ship_to_country", "ship_to_phone", "ship_to_email",
    "ship_to_contractor_id",
    "credit_limit", "credit_currency",
    "kuke_approved", "kuke_limit", "kuke_currency",
    "kuke_expiry_date", "risk_status",
    "notes",
})


# ── Outcome reporting ────────────────────────────────────────────────────────

ACTIONS = (
    "fill",
    "skip_already_set",
    "force_overwrite",
    "skip_no_master_record",
    "skip_empty_profile",
)


@dataclass
class FieldOutcome:
    contractor_id:  str
    field:          str
    old_value:      Optional[str]
    new_value:      Optional[str]
    action:         str
    warn:           bool = False
    warn_reason:    str  = ""


@dataclass
class ApplySummary:
    profiles_seen:     int = 0
    profiles_applied:  int = 0
    profiles_skipped:  int = 0
    fields_filled:     int = 0
    fields_forced:     int = 0
    fields_skipped:    int = 0
    outcomes:          List[FieldOutcome] = dc_field(default_factory=list)


# ── Pure merge logic ─────────────────────────────────────────────────────────

def _is_empty(field_name: str, value) -> bool:
    """For Decimal-based money fields: 0 doesn't count as empty (operator may
    deliberately set 0). Only None / empty-string treated as missing."""
    return value is None or (isinstance(value, str) and value == "")


def _project(profile_field: str, value) -> object:
    """Map snapshot value into the customer_master type for that field."""
    if value is None:
        return None
    # Decimal-typed snapshot fields → preserve exact value
    if profile_field in ("insurance_min_detected",
                         "last_freight_amount",
                         "avg_freight_amount"):
        return Decimal(str(value))
    # vat_mode → int
    if profile_field == "vat_mode":
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
    return value


def merge_one(profile:  ProfileSnapshotRow,
              master:   Optional[CustomerMaster],
              *,
              force:    bool = False) -> Tuple[Optional[CustomerMaster], List[FieldOutcome]]:
    """Compute (merged_master, per-field outcomes). Pure function."""
    outcomes: List[FieldOutcome] = []

    # Skip if profile is empty
    if profile.confidence_state == CONF_EMPTY:
        outcomes.append(FieldOutcome(
            contractor_id = profile.contractor_id,
            field         = "(profile)",
            old_value     = None, new_value = None,
            action        = "skip_empty_profile",
        ))
        return master, outcomes

    if master is None:
        # No customer_master record exists yet — caller decides whether to insert.
        # Layer 1 seeder owns inserts; this merger only updates existing records.
        outcomes.append(FieldOutcome(
            contractor_id = profile.contractor_id,
            field         = "(master_record)",
            old_value     = None, new_value = None,
            action        = "skip_no_master_record",
        ))
        return master, outcomes

    low_conf = profile.confidence_state in LOW_CONFIDENCE_STATES
    warn_reason = profile.confidence_state if low_conf else ""

    changes: Dict[str, object] = {}
    for snap_field, master_field in MERGE_FIELDS:
        if master_field in NEVER_TOUCH_FIELDS:
            continue   # belt-and-suspenders; should never trigger
        old = getattr(master, master_field)
        snap_value = getattr(profile, snap_field)
        new = _project(snap_field, snap_value)

        if new is None:
            # Profile didn't have a value — nothing to do
            continue

        if _is_empty(master_field, old):
            # Customer master field is empty → fill
            changes[master_field] = new
            outcomes.append(FieldOutcome(
                contractor_id = profile.contractor_id,
                field         = master_field,
                old_value     = None,
                new_value     = str(new),
                action        = "fill",
                warn          = low_conf,
                warn_reason   = warn_reason,
            ))
        else:
            # Already set — only overwrite with --force
            if force and old != new:
                changes[master_field] = new
                outcomes.append(FieldOutcome(
                    contractor_id = profile.contractor_id,
                    field         = master_field,
                    old_value     = str(old),
                    new_value     = str(new),
                    action        = "force_overwrite",
                    warn          = low_conf,
                    warn_reason   = warn_reason,
                ))
            else:
                outcomes.append(FieldOutcome(
                    contractor_id = profile.contractor_id,
                    field         = master_field,
                    old_value     = str(old),
                    new_value     = str(new),
                    action        = "skip_already_set",
                ))

    if not changes:
        return master, outcomes
    return replace(master, **changes), outcomes


# ── Orchestrator ──────────────────────────────────────────────────────────────

def apply(snapshot_db: Path,
          master_db:   Path,
          *,
          dry_run:     bool = True,
          force:       bool = False,
          only_ids:    Optional[List[str]] = None) -> ApplySummary:
    """Read all profiles from snapshot_db; for each, merge into master_db
    according to the rules. Pure dry-run by default.
    """
    init_master_db(master_db)
    profiles = list_profiles(snapshot_db)
    if only_ids:
        profiles = [p for p in profiles if p.contractor_id in only_ids]

    summary = ApplySummary()
    summary.profiles_seen = len(profiles)

    for p in profiles:
        master = get_customer(master_db, p.contractor_id)
        merged, outcomes = merge_one(p, master, force=force)
        summary.outcomes.extend(outcomes)

        for o in outcomes:
            if o.action == "fill":             summary.fields_filled  += 1
            elif o.action == "force_overwrite":summary.fields_forced  += 1
            elif o.action == "skip_already_set":summary.fields_skipped += 1
            # skip_empty_profile / skip_no_master_record don't count as a field event

        applied_changes = (merged is not None and master is not None and merged != master)
        if applied_changes:
            if not dry_run:
                upsert_customer(master_db, merged)
            summary.profiles_applied += 1
        else:
            summary.profiles_skipped += 1

    return summary


# ── CLI ───────────────────────────────────────────────────────────────────────

def _print_summary(s: ApplySummary, *, dry_run: bool, force: bool) -> None:
    width = 120
    print("=" * width)
    label = "DRY-RUN" if dry_run else ("LIVE WRITE — FORCE" if force else "LIVE WRITE")
    print(f" customer_master ← snapshot profile merge — {label}")
    print("=" * width)
    print(f"  profiles seen      : {s.profiles_seen}")
    print(f"  profiles applied   : {s.profiles_applied}")
    print(f"  profiles unchanged : {s.profiles_skipped}")
    print(f"  fields filled      : {s.fields_filled}")
    print(f"  fields forced      : {s.fields_forced}")
    print(f"  fields skipped     : {s.fields_skipped}")
    print()
    if not s.outcomes:
        print("  (no outcomes)")
        return
    print(f"  {'contractor':>11s}  {'field':25s}  {'old':>14s}  {'new':>14s}  {'action':22s}  warn")
    print("  " + "-" * (width - 4))
    for o in s.outcomes:
        old = o.old_value if o.old_value is not None else "—"
        new = o.new_value if o.new_value is not None else "—"
        warn = f"⚠ {o.warn_reason}" if o.warn else ""
        print(f"  {o.contractor_id:>11s}  {o.field:25s}  {old:>14s}  {new:>14s}  {o.action:22s}  {warn}")
    print()


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="apply_snapshot_profiles_to_master")
    p.add_argument("--snapshot-db", default=None,
                   help="Snapshot SQLite. Default: <repo>/storage/customer_invoice_snapshot.sqlite")
    p.add_argument("--master-db", default=None,
                   help="Customer master SQLite. Default: <repo>/storage/customer_master.sqlite")
    p.add_argument("--apply", action="store_true",
                   help="Write changes. Without this flag, dry-run only.")
    p.add_argument("--force", action="store_true",
                   help="Overwrite non-empty customer_master fields with snapshot values. "
                        "Ship-to / credit / Kuke fields are STILL never touched.")
    p.add_argument("--only", default=None,
                   help="Comma-separated contractor ids to merge")
    args = p.parse_args(argv)

    snap = (Path(args.snapshot_db).expanduser() if args.snapshot_db else
            Path(__file__).resolve().parents[3] / "storage" / "customer_invoice_snapshot.sqlite")
    master = (Path(args.master_db).expanduser() if args.master_db else
              Path(__file__).resolve().parents[3] / "storage" / "customer_master.sqlite")

    only_ids = None
    if args.only:
        only_ids = [s.strip() for s in args.only.split(",") if s.strip()]

    s = apply(snap, master,
              dry_run = not args.apply,
              force   = args.force,
              only_ids = only_ids)

    _print_summary(s, dry_run=(not args.apply), force=args.force)
    return 0


if __name__ == "__main__":
    sys.exit(main())
