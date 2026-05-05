"""
seed_customer_master_from_wfirma.py — bootstrap customer_master from wFirma.

Reads active wFirma contractors and creates/updates local customer_master
records with the BASIC fields wFirma owns. Never overwrites operator-enriched
fields (currency, language, freight profile, insurance override, credit/Kuke).

Read-only on wFirma. Writes only to the local customer_master SQLite DB.

  Basic fields  (sourced from wFirma; safe to refresh)
    - bill_to_contractor_id, bill_to_name, country, nip
    - ship_to_use_alternate, ship_to_name, ship_to_person,
      ship_to_street, ship_to_city, ship_to_zip, ship_to_country

  Enriched fields  (NEVER touched by this tool)
    - vat_eu_number, vat_eu_valid, vat_eu_validated_at
    - ship_to_contractor_id (Shape B receiver — operator-decided)
    - default_currency, default_language_id, insurance_min_override
    - credit_limit, credit_currency
    - kuke_*, risk_status, notes

Behaviour:
  Default     : insert new customers with basic fields. For existing rows,
                update basic fields ONLY if the DB value is empty.
  --force-basic: always overwrite basic fields with wFirma values, even if
                the operator changed them. Enriched fields still preserved.
  --dry-run   : don't write anything; print what would happen.
  --only X,Y  : restrict to the given contractor ids.

Usage:
    python3 -m app.tools.seed_customer_master_from_wfirma --dry-run
    python3 -m app.tools.seed_customer_master_from_wfirma
    python3 -m app.tools.seed_customer_master_from_wfirma --only 38582303
    python3 -m app.tools.seed_customer_master_from_wfirma --force-basic
"""
from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple


def _bootstrap() -> None:
    here = Path(__file__).resolve()
    repo_root = here.parents[3]
    service_dir = here.parents[2]
    for p in (str(repo_root), str(service_dir)):
        if p not in sys.path:
            sys.path.insert(0, p)


_bootstrap()

from app.services.customer_master_db import (   # noqa: E402
    CustomerMaster, get_customer, init_db, upsert_customer, validate,
)


# ── Field categories (locked) ────────────────────────────────────────────────

# Fields the seeder is allowed to read FROM wFirma and write to customer_master.
# Anything not in this list is "enriched" and NEVER touched.
BASIC_FIELDS = (
    "bill_to_name",
    "country",
    "nip",
    "ship_to_use_alternate",
    "ship_to_name",
    "ship_to_person",
    "ship_to_street",
    "ship_to_city",
    "ship_to_zip",
    "ship_to_country",
)

# Empty-ness check per field — strings are blank when None or empty;
# booleans count as "empty" only when False (== default).
def _is_empty(field_name: str, value) -> bool:
    if field_name == "ship_to_use_alternate":
        return value is False or value is None
    return value is None or value == ""


# ── Outcome reporting ────────────────────────────────────────────────────────

@dataclass
class SeedOutcome:
    contractor_id:     str
    name:              str
    country:           str
    action:            str   # inserted | updated | skipped_unchanged | skipped_missing_country
    fields_updated:    List[str] = field(default_factory=list)
    note:              str = ""


@dataclass
class SeedSummary:
    inserted:                int = 0
    updated:                 int = 0
    skipped_unchanged:       int = 0
    skipped_missing_country: int = 0
    errors:                  int = 0
    outcomes:                List[SeedOutcome] = field(default_factory=list)


# ── wFirma fetcher (live; injectable for tests) ──────────────────────────────

def fetch_wfirma_contractors(only_ids: Optional[List[str]] = None,
                              limit:    int = 500) -> List[Dict[str, str]]:
    """Read contractor records from wFirma. Returns a list of dicts with the
    fields the seeder needs. Never writes."""
    from app.services import wfirma_client as wfc

    conditions = ""
    if only_ids:
        # Use 'in' operator if available; fall back to one-by-one
        ids_xml = "".join(
            f"<condition><field>id</field><operator>eq</operator><value>{cid}</value></condition>"
            for cid in only_ids
        )
        conditions = f"<conditions>{ids_xml}</conditions>" if ids_xml else ""

    body = f"""<?xml version="1.0" encoding="UTF-8"?>
<api>
  <contractors>
    <parameters>
      {conditions}
      <page><start>0</start><limit>{int(limit)}</limit></page>
    </parameters>
  </contractors>
</api>"""
    http_status, response = wfc._http_request("GET", "contractors", "find", body)
    if http_status >= 400:
        raise ConnectionError(f"contractors/find HTTP {http_status}")

    try:
        root = ET.fromstring(response)
    except ET.ParseError as exc:
        raise ValueError(f"contractors/find returned non-XML: {exc}") from exc

    out: List[Dict[str, str]] = []
    for c in root.findall("contractors/contractor"):
        out.append(_parse_contractor(c))
    # If only_ids was supplied with multiple entries, wFirma's `eq` repeated
    # may behave like AND (returning none). Fallback: one-by-one.
    if only_ids and not out and len(only_ids) > 1:
        for cid in only_ids:
            for r in fetch_wfirma_contractors(only_ids=[cid], limit=1):
                out.append(r)
    return out


def _t(parent: ET.Element, tag: str) -> str:
    el = parent.find(tag)
    return (el.text or "").strip() if el is not None and el.text else ""


def _parse_contractor(c: ET.Element) -> Dict[str, str]:
    """Map wFirma contractor XML to a normalised dict."""
    return {
        "contractor_id":             _t(c, "id"),
        "name":                      _t(c, "name"),
        "altname":                   _t(c, "altname"),
        "country":                   _t(c, "country"),
        "nip":                       _t(c, "nip"),
        "different_contact_address": _t(c, "different_contact_address"),
        "contact_name":              _t(c, "contact_name"),
        "contact_person":            _t(c, "contact_person"),
        "contact_street":            _t(c, "contact_street"),
        "contact_city":              _t(c, "contact_city"),
        "contact_zip":               _t(c, "contact_zip"),
        "contact_country":           _t(c, "contact_country"),
    }


# ── Mapping ──────────────────────────────────────────────────────────────────

def map_contractor_to_basic_master(raw: Dict[str, str]) -> CustomerMaster:
    """Project a wFirma contractor dict onto a CustomerMaster with ONLY basic
    fields populated. Enriched fields are left unset.

    Raises ValueError if the required fields (id, name, country) are missing.
    """
    cid = (raw.get("contractor_id") or "").strip()
    name = (raw.get("name") or raw.get("altname") or "").strip()
    country = (raw.get("country") or "").strip().upper()
    if not cid:
        raise ValueError("contractor_id missing in wFirma payload")
    if not name:
        raise ValueError(f"contractor name missing for id={cid}")
    if not country or len(country) != 2:
        raise ValueError(f"contractor country invalid for id={cid}: {country!r}")

    use_alt = (raw.get("different_contact_address", "0").strip() == "1")
    return CustomerMaster(
        bill_to_contractor_id = cid,
        bill_to_name          = name,
        country               = country,
        nip                   = raw.get("nip") or None,
        ship_to_use_alternate = use_alt,
        ship_to_name          = (raw.get("contact_name")    or None) if use_alt else None,
        ship_to_person        = (raw.get("contact_person")  or None) if use_alt else None,
        ship_to_street        = (raw.get("contact_street")  or None) if use_alt else None,
        ship_to_city          = (raw.get("contact_city")    or None) if use_alt else None,
        ship_to_zip           = (raw.get("contact_zip")     or None) if use_alt else None,
        ship_to_country       = ((raw.get("contact_country") or "").upper() or None) if use_alt else None,
    )


# ── Merge logic ──────────────────────────────────────────────────────────────

def merge_basic_into_existing(existing: CustomerMaster,
                              from_wfirma: CustomerMaster,
                              *,
                              force_basic: bool) -> Tuple[CustomerMaster, List[str]]:
    """Apply wFirma-sourced basic fields onto an existing customer_master.

    Returns (merged, fields_changed). Enriched fields on `existing` are
    always preserved untouched.

    Default behaviour: only fill basic fields that are CURRENTLY empty.
    With force_basic: always overwrite basic fields with wFirma values
    (still preserves enriched).
    """
    changes: Dict[str, object] = {}
    for f in BASIC_FIELDS:
        new_val = getattr(from_wfirma, f)
        old_val = getattr(existing, f)
        if force_basic:
            if new_val != old_val:
                changes[f] = new_val
        else:
            # Only set if old is empty
            if _is_empty(f, old_val) and not _is_empty(f, new_val):
                changes[f] = new_val
    if not changes:
        return existing, []
    merged = replace(existing, **changes)
    return merged, sorted(changes.keys())


# ── Seeder ───────────────────────────────────────────────────────────────────

def seed(db_path: Path,
         *,
         only_ids:   Optional[List[str]] = None,
         dry_run:    bool = False,
         force_basic: bool = False,
         fetcher:    Optional[Callable] = None) -> SeedSummary:
    """Walk wFirma contractors and update customer_master.

    `fetcher` is the injectable wFirma reader, signature:
        fetcher(only_ids: list[str]|None) -> list[dict]
    Defaults to live fetch_wfirma_contractors. Tests pass a stub.
    """
    init_db(db_path)
    do_fetch = fetcher or (lambda only: fetch_wfirma_contractors(only_ids=only))
    raws = do_fetch(only_ids)

    summary = SeedSummary()
    for raw in raws:
        try:
            new = map_contractor_to_basic_master(raw)
        except ValueError as exc:
            # Currently the only ValueError reason from the mapper is
            # "country invalid" — count it as missing_country and continue.
            cid = (raw.get("contractor_id") or "?")
            summary.skipped_missing_country += 1
            summary.outcomes.append(SeedOutcome(
                contractor_id = cid,
                name          = raw.get("name") or "",
                country       = raw.get("country") or "",
                action        = "skipped_missing_country",
                note          = str(exc),
            ))
            continue

        existing = get_customer(db_path, new.bill_to_contractor_id)
        if existing is None:
            # INSERT
            if not dry_run:
                upsert_customer(db_path, new)
            summary.inserted += 1
            summary.outcomes.append(SeedOutcome(
                contractor_id = new.bill_to_contractor_id,
                name          = new.bill_to_name,
                country       = new.country,
                action        = "inserted",
                fields_updated = list(BASIC_FIELDS),
            ))
            continue

        merged, changed = merge_basic_into_existing(existing, new, force_basic=force_basic)
        if not changed:
            summary.skipped_unchanged += 1
            summary.outcomes.append(SeedOutcome(
                contractor_id = new.bill_to_contractor_id,
                name          = new.bill_to_name,
                country       = new.country,
                action        = "skipped_unchanged",
            ))
            continue

        if not dry_run:
            upsert_customer(db_path, merged)
        summary.updated += 1
        summary.outcomes.append(SeedOutcome(
            contractor_id  = new.bill_to_contractor_id,
            name           = new.bill_to_name,
            country        = new.country,
            action         = "updated",
            fields_updated = changed,
        ))

    return summary


# ── CLI ───────────────────────────────────────────────────────────────────────

def _print_summary(summary: SeedSummary, *, dry_run: bool) -> None:
    width = 80
    print("=" * width)
    print(f" customer_master seed — {'DRY-RUN' if dry_run else 'LIVE WRITE'}")
    print("=" * width)
    print(f"  inserted              : {summary.inserted}")
    print(f"  updated               : {summary.updated}")
    print(f"  skipped (no change)   : {summary.skipped_unchanged}")
    print(f"  skipped (missing country): {summary.skipped_missing_country}")
    print(f"  errors                : {summary.errors}")
    print()
    if summary.outcomes:
        print(f"  {'action':25s}  {'id':>10s}  {'country':>3s}  fields  /  name")
        print("  " + "-" * (width - 4))
        for o in summary.outcomes[:50]:
            extra = ", ".join(o.fields_updated) if o.fields_updated else ""
            line = f"  {o.action:25s}  {o.contractor_id:>10s}  {o.country:>3s}"
            if extra:
                line += f"  {extra}"
            line += f"  /  {o.name[:50]}"
            if o.note:
                line += f"   ({o.note})"
            print(line)
        if len(summary.outcomes) > 50:
            print(f"  ... and {len(summary.outcomes) - 50} more")
    print()


def main(argv: Optional[List[str]] = None,
         fetcher:  Optional[Callable] = None) -> int:
    p = argparse.ArgumentParser(prog="seed_customer_master_from_wfirma")
    p.add_argument("--db", default=None,
                   help="Path to customer_master SQLite. Default: <repo>/storage/customer_master.sqlite")
    p.add_argument("--only", default=None,
                   help="Comma-separated wFirma contractor ids to seed (skip the rest)")
    p.add_argument("--dry-run", action="store_true",
                   help="Don't write to DB; print what would happen")
    p.add_argument("--force-basic", action="store_true",
                   help="Overwrite basic fields with wFirma values even if operator changed them. "
                        "Enriched fields (currency/language/Kuke/credit) are still preserved.")
    args = p.parse_args(argv)

    if args.db:
        db_path = Path(args.db).expanduser()
    else:
        db_path = Path(__file__).resolve().parents[3] / "storage" / "customer_master.sqlite"

    only_ids = None
    if args.only:
        only_ids = [s.strip() for s in args.only.split(",") if s.strip()]

    try:
        summary = seed(db_path,
                       only_ids    = only_ids,
                       dry_run     = args.dry_run,
                       force_basic = args.force_basic,
                       fetcher     = fetcher)
    except (ConnectionError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 5

    _print_summary(summary, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
