"""
backfill_sad_import_state.py — One-time backfill of SAD import state for existing batches.

Problem:
  The _stamp_sad_imported bridge (added to routes_upload.py) only runs on future
  PZ pipeline executions. Existing batches that already have a SAD file in
  source/sad/ still have sad_imported_ts=null, so dhl_readiness remains stuck
  and proposal_engine keeps proposing agency_followup.

Scope:
  One-time operator tool. Dry-run by default; requires --apply to write.

Eligibility rules (ALL must hold):
  1. source/sad/ contains at least one .pdf file
  2. audit["sad_imported_ts"] is null / absent
  3. audit["status"] is NOT "blocked"

Fields written on apply:
  sad_imported:    True
  sad_imported_ts: file mtime (UTC ISO) if available, else current UTC ISO

Timeline event appended (deduped):
  zc429_received  — if SAD filename contains "ZC429" (case-insensitive)
  sad_uploaded    — otherwise

Idempotent:
  - Rerun will skip batches where sad_imported_ts is already set
  - Rerun will not duplicate an existing timeline event

Usage:
  python -m app.tools.backfill_sad_import_state --dry-run
  python -m app.tools.backfill_sad_import_state --dry-run --batch SHIPMENT_XYZ
  python -m app.tools.backfill_sad_import_state --apply
  python -m app.tools.backfill_sad_import_state --apply --batch SHIPMENT_XYZ
  python -m app.tools.backfill_sad_import_state --apply --outputs-dir /path/to/outputs
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

log = logging.getLogger("backfill_sad_import_state")


# ── Path bootstrap ────────────────────────────────────────────────────────────

def _bootstrap_paths() -> None:
    here     = Path(__file__).resolve()
    repo_root    = here.parents[3]   # …/CLI
    service_dir  = here.parents[2]   # …/CLI/service
    for p in (str(repo_root), str(service_dir)):
        if p not in sys.path:
            sys.path.insert(0, p)


_bootstrap_paths()


# ── Result dataclass ──────────────────────────────────────────────────────────

@dataclass
class BackfillResult:
    batch_id:    str
    action:      str          # "eligible" | "skipped" | "stamped" | "error"
    skip_reason: str = ""     # why skipped
    sad_file:    str = ""     # SAD filename found
    event_emitted: str = ""   # timeline event that was / would be emitted
    sad_imported_ts: str = "" # ts that was / would be written
    error:       str = ""

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


# ── Core helpers ──────────────────────────────────────────────────────────────

def _find_sad_file(batch_dir: Path) -> Optional[Path]:
    """Return the first .pdf in source/sad/, or None."""
    sad_dir = batch_dir / "source" / "sad"
    if not sad_dir.is_dir():
        return None
    pdfs = sorted(sad_dir.glob("*.pdf"))
    return pdfs[0] if pdfs else None


def _file_mtime_iso(path: Path) -> str:
    """Return file mtime as UTC ISO string, or current UTC ISO on any error."""
    try:
        mtime = path.stat().st_mtime
        return datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
    except Exception:
        return datetime.now(timezone.utc).isoformat()


def _pick_event(sad_name: str) -> str:
    """Return the readiness timeline event name based on SAD filename."""
    from app.core import timeline as tl
    if "ZC429" in sad_name.upper():
        return tl.EV_ZC429_RECEIVED
    return tl.EV_SAD_UPLOADED


def _inspect_batch(batch_dir: Path) -> BackfillResult:
    """
    Classify a single batch directory — does not write anything.

    Returns a BackfillResult with action="eligible" if the batch should be
    stamped, or action="skipped" with a skip_reason explaining why.
    """
    batch_id  = batch_dir.name
    audit_path = batch_dir / "audit.json"

    if not audit_path.exists():
        return BackfillResult(batch_id=batch_id, action="skipped",
                              skip_reason="no_audit_json")

    try:
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return BackfillResult(batch_id=batch_id, action="skipped",
                              skip_reason=f"corrupt_audit:{exc}")

    # Rule 3: status must not be blocked
    status = audit.get("status", "")
    if status == "blocked":
        sad_file = _find_sad_file(batch_dir)
        return BackfillResult(batch_id=batch_id, action="skipped",
                              skip_reason="status_blocked",
                              sad_file=sad_file.name if sad_file else "")

    # Rule 2: sad_imported_ts must be absent/null
    if audit.get("sad_imported_ts"):
        return BackfillResult(batch_id=batch_id, action="skipped",
                              skip_reason="already_stamped",
                              sad_imported_ts=audit["sad_imported_ts"])

    # Rule 1: must have a SAD file
    sad_path = _find_sad_file(batch_dir)
    if sad_path is None:
        return BackfillResult(batch_id=batch_id, action="skipped",
                              skip_reason="no_sad_file")

    ts     = _file_mtime_iso(sad_path)
    ev     = _pick_event(sad_path.name)
    return BackfillResult(
        batch_id=batch_id,
        action="eligible",
        sad_file=sad_path.name,
        event_emitted=ev,
        sad_imported_ts=ts,
    )


def _stamp_batch(batch_dir: Path, dry_run: bool) -> BackfillResult:
    """
    Inspect + optionally stamp a single batch.

    dry_run=True  → classify only, never write
    dry_run=False → classify and write if eligible
    """
    result = _inspect_batch(batch_dir)

    if result.action != "eligible":
        return result

    if dry_run:
        # Mark as eligible but don't touch the filesystem
        return result

    # ── Apply ─────────────────────────────────────────────────────────────────
    audit_path = batch_dir / "audit.json"
    try:
        from app.utils.io import write_json_atomic
        from app.core    import timeline as tl

        # Re-read to apply on freshest version
        audit = json.loads(audit_path.read_text(encoding="utf-8"))

        # Idempotent guard (in case concurrent run stamped it between inspect + apply)
        if audit.get("sad_imported_ts"):
            return BackfillResult(batch_id=batch_dir.name, action="skipped",
                                  skip_reason="already_stamped_concurrent",
                                  sad_imported_ts=audit["sad_imported_ts"])

        audit["sad_imported"]    = True
        audit["sad_imported_ts"] = result.sad_imported_ts
        write_json_atomic(audit_path, audit)

        # Emit timeline event only if not already present
        existing = {e.get("event") for e in (audit.get("timeline") or [])}
        if result.event_emitted not in existing:
            tl.log_event(audit_path, result.event_emitted,
                         "system", "backfill_sad_import_state",
                         detail={"sad_name": result.sad_file,
                                 "trigger": "backfill"})

        log.info("[%s] stamped sad_imported_ts=%s event=%s",
                 batch_dir.name, result.sad_imported_ts, result.event_emitted)
        result.action = "stamped"
        return result

    except Exception as exc:
        log.error("[%s] backfill error: %s", batch_dir.name, exc)
        result.action = "error"
        result.error  = str(exc)
        return result


# ── Public API (used by tests and CLI) ────────────────────────────────────────

def scan_batches(
    outputs_dir: Path,
    batch_filter: Optional[str] = None,
) -> List[BackfillResult]:
    """
    Dry-run scan of outputs_dir. Returns classification for every batch found.
    Never writes.
    """
    results = []
    for d in sorted(outputs_dir.iterdir()):
        if not d.is_dir():
            continue
        if batch_filter and d.name != batch_filter:
            continue
        results.append(_stamp_batch(d, dry_run=True))
    return results


def apply_backfill(
    outputs_dir: Path,
    batch_filter: Optional[str] = None,
) -> List[BackfillResult]:
    """
    Apply backfill to all eligible batches in outputs_dir.
    Writes sad_imported, sad_imported_ts, and appends a timeline event.
    """
    results = []
    for d in sorted(outputs_dir.iterdir()):
        if not d.is_dir():
            continue
        if batch_filter and d.name != batch_filter:
            continue
        results.append(_stamp_batch(d, dry_run=False))
    return results


# ── CLI ───────────────────────────────────────────────────────────────────────

def _resolve_outputs_dir(override: Optional[str]) -> Path:
    if override:
        return Path(override)
    from app.core.config import settings
    return Path(settings.storage_root) / "outputs"


def _format_results(results: List[BackfillResult], dry_run: bool) -> str:
    lines: List[str] = []
    mode = "DRY-RUN" if dry_run else "APPLY"
    lines.append(f"── backfill_sad_import_state [{mode}] ───────────────────")
    for r in results:
        if r.action in ("eligible", "stamped"):
            verb = "would stamp" if dry_run else "stamped"
            lines.append(
                f"  {verb:12} {r.batch_id}  sad={r.sad_file}  "
                f"event={r.event_emitted}  ts={r.sad_imported_ts[:19]}"
            )
        else:
            lines.append(
                f"  {'skipped':12} {r.batch_id}  reason={r.skip_reason}"
                + (f"  error={r.error}" if r.error else "")
            )
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        prog="backfill_sad_import_state",
        description="Backfill sad_imported_ts for batches that already have a SAD file.",
    )
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true",
                   help="Classify batches without writing (default safe mode).")
    g.add_argument("--apply",   action="store_true",
                   help="Actually stamp eligible batches.")
    p.add_argument("--batch", default=None,
                   help="Limit to a single batch_id.")
    p.add_argument("--outputs-dir", default=None,
                   help="Override outputs directory (default: settings.storage_root/outputs).")
    p.add_argument("--json", action="store_true",
                   help="Emit JSON output.")
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    outputs_dir = _resolve_outputs_dir(args.outputs_dir)
    if not outputs_dir.is_dir():
        log.error("Outputs directory not found: %s", outputs_dir)
        return 2

    if args.dry_run:
        results = scan_batches(outputs_dir, batch_filter=args.batch)
    else:
        results = apply_backfill(outputs_dir, batch_filter=args.batch)

    if args.json:
        print(json.dumps([r.to_dict() for r in results], indent=2, default=str))
    else:
        print(_format_results(results, dry_run=args.dry_run))
        eligible = sum(1 for r in results if r.action in ("eligible", "stamped"))
        skipped  = sum(1 for r in results if r.action == "skipped")
        errors   = sum(1 for r in results if r.action == "error")
        verb     = "would stamp" if args.dry_run else "stamped"
        print()
        print(f"Total: {len(results)} batches — {verb}: {eligible}, "
              f"skipped: {skipped}, errors: {errors}")

    return 0 if not any(r.action == "error" for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
