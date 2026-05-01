#!/usr/bin/env python3
"""
backfill_awb_and_timeline.py
============================
One-time backfill of existing audit.json batches that pre-date the
canonical audit.awb field and timeline logging.

What it does
------------
For each batch in outputs/:
  1. Extract AWB from (priority order):
       a. audit["awb"]               — already set, skip
       b. audit["tracking_no"]       — stored on dashboard-upload batches
       c. audit["batch_meta"]["awb"] — legacy cowork batches
       d. audit["dhl_awb"]           — legacy DHL handler field
       e. SHIPMENT_{AWB}_* batch_id  — parsed from batch_id itself
       f. ZC429 filename             — ZC429_<MRN>_... (MRN not AWB, skip)
       g. null                       — write warning

  2. Write audit["awb"] (normalised digits, no spaces)
     Write audit["warnings"] += ["awb_missing"] if null
     Remove "awb_missing" from warnings if AWB is now resolved

  3. If audit["timeline"] is missing or empty, reconstruct a minimal timeline:
       batch_created    ← audit["timestamp"]
       invoices_uploaded ← audit["timestamp"] (if invoices present)
       sad_uploaded     ← audit["timestamp"] (if zc429 present)
       pz_generated     ← audit["timestamp"] (if files.pdf present)

     All backfilled events use ts = audit["timestamp"] and actor = "backfill_script".

What it NEVER touches
---------------------
  - audit["totals"]
  - audit["verification"]
  - audit["corrections_log"]
  - audit["amendment_flags"]
  - audit["files"]
  - Any PZ, CIF, or customs calculation field

Usage
-----
  python3 scripts/backfill_awb_and_timeline.py [--dry-run] [--verbose]

Exit codes
----------
  0 — all batches processed
  1 — one or more batches could not be processed (details printed)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

# ── Storage root ──────────────────────────────────────────────────────────────
_HERE    = Path(__file__).resolve().parent
_ROOT    = _HERE.parent
_OUTPUTS = _ROOT / "service" / "app" / "storage" / "outputs"

# ── AWB pattern (10–12 digit DHL AWB) ────────────────────────────────────────
_AWB_RE = re.compile(r"\b(\d{10,12})\b")


def _normalise_awb(raw: str) -> str | None:
    """Strip whitespace and validate AWB-like digit string. Return None if invalid."""
    if not raw:
        return None
    clean = raw.strip().replace(" ", "")
    if re.fullmatch(r"\d{10,12}", clean):
        return clean
    return None


def _extract_awb_from_batch_id(batch_id: str) -> str | None:
    """SHIPMENT_{AWB}_{YYYY-MM}_{uid} → AWB digits."""
    m = re.match(r"^SHIPMENT_(\d{10,12})_", batch_id)
    return m.group(1) if m else None


def _extract_awb(audit: dict, batch_id: str) -> str | None:
    """Return canonical AWB from any available source. None if not extractable."""
    candidates = [
        audit.get("awb"),
        audit.get("tracking_no"),
        (audit.get("batch_meta") or {}).get("awb"),
        audit.get("dhl_awb"),
        _extract_awb_from_batch_id(batch_id),
    ]
    for c in candidates:
        awb = _normalise_awb(str(c)) if c else None
        if awb:
            return awb
    return None


def _make_event(ts: str, event: str, detail: dict | None = None) -> dict:
    return {
        "ts":             ts,
        "event":          event,
        "trigger_source": "backfill_script",
        "actor":          "backfill_script",
        "detail":         detail,
    }


def _reconstruct_timeline(audit: dict) -> list:
    """Build a minimal timeline from what we can infer from the stored audit."""
    events: list = []
    ts = audit.get("timestamp", datetime.now(timezone.utc).isoformat())

    # batch_created — always
    events.append(_make_event(ts, "batch_created", {
        "backfilled": True,
        "source":     audit.get("source", "unknown"),
        "carrier":    audit.get("carrier"),
    }))

    # invoices_uploaded — if invoice list present
    invoices = (audit.get("inputs") or {}).get("invoices") or []
    for inv in invoices:
        events.append(_make_event(ts, "invoice_uploaded", {"file": inv, "backfilled": True}))

    # sad_uploaded — if ZC429 present
    zc429 = (audit.get("inputs") or {}).get("zc429")
    if zc429:
        events.append(_make_event(ts, "sad_uploaded", {"file": zc429, "backfilled": True}))

    # pz_generated — if output PDF was produced
    pdf_info = (audit.get("files") or {}).get("pdf")
    if pdf_info:
        status = audit.get("status", "")
        ev = "pz_generated" if status in ("success", "partial") else "pz_blocked"
        events.append(_make_event(ts, ev, {"status": status, "backfilled": True}))

    return events


def _write_atomic(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)


def backfill_batch(
    batch_dir: Path,
    dry_run: bool = False,
    verbose: bool = False,
) -> dict:
    """
    Process one batch. Returns a result dict with keys:
      batch_id, awb_before, awb_after, timeline_before, timeline_after, changed, error
    """
    batch_id   = batch_dir.name
    audit_path = batch_dir / "audit.json"
    result     = {
        "batch_id":       batch_id,
        "awb_before":     None,
        "awb_after":      None,
        "timeline_before": 0,
        "timeline_after":  0,
        "changed":        False,
        "error":          None,
    }

    if not audit_path.exists():
        result["error"] = "audit.json not found"
        return result

    try:
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
    except Exception as exc:
        result["error"] = f"JSON parse error: {exc}"
        return result

    original_audit = json.dumps(audit, sort_keys=True)
    result["awb_before"] = audit.get("awb")
    result["timeline_before"] = len(audit.get("timeline") or [])

    # ── 1. AWB extraction ─────────────────────────────────────────────────────
    awb = _extract_awb(audit, batch_id)
    if awb:
        audit["awb"] = awb
        # Remove warning if it was set
        warnings = audit.get("warnings") or []
        if "awb_missing" in warnings:
            warnings.remove("awb_missing")
            audit["warnings"] = warnings
    else:
        # AWB could not be determined
        audit["awb"] = None
        warnings = audit.get("warnings") or []
        if "awb_missing" not in warnings:
            warnings.append("awb_missing")
        audit["warnings"] = warnings

    result["awb_after"] = audit.get("awb")

    # ── 2. Timeline reconstruction ────────────────────────────────────────────
    existing_timeline = audit.get("timeline") or []
    if not existing_timeline:
        audit["timeline"] = _reconstruct_timeline(audit)
    # If timeline already exists, don't touch it

    result["timeline_after"] = len(audit.get("timeline") or [])

    # ── 3. Write (unless dry-run or unchanged) ────────────────────────────────
    new_audit = json.dumps(audit, sort_keys=True)
    if new_audit != original_audit:
        result["changed"] = True
        if not dry_run:
            _write_atomic(audit_path, audit)
        if verbose:
            awb_msg = f"AWB: {result['awb_before'] or 'null'} → {result['awb_after'] or 'null'}"
            tl_msg  = f"timeline: {result['timeline_before']} → {result['timeline_after']} events"
            print(f"  {'[DRY] ' if dry_run else ''}UPDATED {batch_id[:16]}: {awb_msg} | {tl_msg}")
    else:
        if verbose:
            print(f"  OK (no change): {batch_id[:16]}")

    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Backfill AWB + timeline in existing audit.json files")
    parser.add_argument("--dry-run",  action="store_true", help="Show what would change without writing")
    parser.add_argument("--verbose",  action="store_true", help="Print per-batch detail")
    parser.add_argument("--outputs",  default=str(_OUTPUTS), help="Path to outputs/ directory")
    args = parser.parse_args(argv)

    outputs_dir = Path(args.outputs)
    if not outputs_dir.is_dir():
        print(f"ERROR: outputs directory not found: {outputs_dir}", file=sys.stderr)
        return 1

    batch_dirs = [d for d in outputs_dir.iterdir() if d.is_dir() and (d / "audit.json").exists()]
    if not batch_dirs:
        print("No batches found.", file=sys.stderr)
        return 0

    print(f"Backfill: {len(batch_dirs)} batch(es) in {outputs_dir}")
    if args.dry_run:
        print("DRY RUN — no files will be written")

    results   = []
    errors    = 0
    changed   = 0
    awb_found = 0
    awb_miss  = 0

    for batch_dir in sorted(batch_dirs):
        r = backfill_batch(batch_dir, dry_run=args.dry_run, verbose=args.verbose)
        results.append(r)
        if r["error"]:
            errors += 1
            print(f"  ERROR {r['batch_id'][:16]}: {r['error']}", file=sys.stderr)
        if r["changed"]:
            changed += 1
        if r["awb_after"]:
            awb_found += 1
        else:
            awb_miss  += 1

    print()
    print("── Summary ──────────────────────────────")
    print(f"  Batches processed:  {len(results)}")
    print(f"  Updated:            {changed}")
    print(f"  Errors:             {errors}")
    print(f"  AWB resolved:       {awb_found}")
    print(f"  AWB still missing:  {awb_miss}")

    if awb_miss:
        print()
        print("Batches without AWB (will block automation):")
        for r in results:
            if not r["awb_after"]:
                print(f"  {r['batch_id'][:32]}  status=missing")

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
