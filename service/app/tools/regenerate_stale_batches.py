"""
regenerate_stale_batches.py — Operator-triggered safe regeneration of stale
PZ batches.

Use:
    python -m service.app.tools.regenerate_stale_batches --dry-run
    python -m service.app.tools.regenerate_stale_batches --apply
    python -m service.app.tools.regenerate_stale_batches --apply --batch SHIPMENT_2824221912_2026-04_319e1197

Behaviour:
    --dry-run  Read-only scan of storage/outputs/*. Reports for each batch
               whether the cached audit.json is stale, what fields are missing,
               and whether source PDFs are available for regeneration.
               Mutates nothing.

    --apply    Regenerate ONLY batches that are both stale AND have all
               required source documents on disk. Before each write a backup
               copy of the entire batch directory is made under
               storage/outputs/<batch_id>/backup_before_regen_YYYYMMDD_HHMMSS/.

Safety rules (enforced in code):
  - The dashboard never auto-regenerates — only this tool, only when invoked
    explicitly by an operator.
  - If --apply is missing, the script never writes.
  - A batch is regenerated only when (stale=True AND source_complete=True).
  - Existing files are never deleted; backups are taken before re-writing.
  - Freight, duty, VAT, NBP/SAD logic is untouched — regeneration just
    re-runs the engine end-to-end against `source/` PDFs.
"""
from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger("regenerate_stale_batches")


# ── Lightweight import shim so this module is runnable both via
# `python -m service.app.tools.regenerate_stale_batches` and as a script
# from the repo root.
def _bootstrap_paths() -> None:
    here = Path(__file__).resolve()
    repo_root = here.parents[3]                       # …/CLI
    service_dir = here.parents[2]                     # …/CLI/service
    for p in (str(repo_root), str(service_dir)):
        if p not in sys.path:
            sys.path.insert(0, p)


_bootstrap_paths()

from app.services.cache_freshness import (    # noqa: E402  (after path bootstrap)
    CURRENT_ROW_SCHEMA_VERSION,
    is_audit_stale,
    stale_field_summary,
)


# ── Result types ──────────────────────────────────────────────────────────────

@dataclass
class BatchScanReport:
    batch_id:                str
    stale:                   bool
    reason:                  str
    row_schema_version:      str
    source_docs_available:   bool
    missing_source_kinds:    List[str] = field(default_factory=list)
    missing_row_fields:      List[Dict[str, Any]] = field(default_factory=list)
    recommended_action:      str = "skip"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "batch_id":              self.batch_id,
            "stale":                 self.stale,
            "reason":                self.reason,
            "row_schema_version":    self.row_schema_version,
            "source_docs_available": self.source_docs_available,
            "missing_source_kinds":  list(self.missing_source_kinds),
            "missing_row_fields":    list(self.missing_row_fields),
            "recommended_action":    self.recommended_action,
        }


@dataclass
class BatchApplyReport:
    batch_id:        str
    regenerated:     bool
    reason:          str = ""
    backup_dir:      Optional[str] = None
    new_audit_path:  Optional[str] = None
    new_pdf_path:    Optional[str] = None
    new_xlsx_path:   Optional[str] = None
    new_row_schema_version: Optional[str] = None
    error:           Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "batch_id":               self.batch_id,
            "regenerated":            self.regenerated,
            "reason":                 self.reason,
            "backup_dir":             self.backup_dir,
            "new_audit_path":         self.new_audit_path,
            "new_pdf_path":           self.new_pdf_path,
            "new_xlsx_path":          self.new_xlsx_path,
            "new_row_schema_version": self.new_row_schema_version,
            "error":                  self.error,
        }


# ── Source-document inspection ────────────────────────────────────────────────

def _list_pdfs(d: Path) -> List[Path]:
    if not d.is_dir():
        return []
    return sorted(p for p in d.iterdir() if p.suffix.lower() == ".pdf" and p.is_file())


def _audit_for_batch(batch_dir: Path) -> Optional[Dict[str, Any]]:
    p = batch_dir / "audit.json"
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        log.warning("[%s] cannot read audit.json: %s", batch_dir.name, exc)
        return None


def _check_source_documents(batch_dir: Path, audit: Dict[str, Any]) -> tuple[bool, List[str]]:
    """Return (all_present, missing_kinds).

    A batch can be regenerated only when at minimum:
      - source/invoices/ contains ≥1 PDF
      - source/sad/      contains ≥1 PDF
    AWB is required only if audit.inputs.awb is non-empty (non-courier batches
    may legitimately lack a tracking PDF).
    """
    src         = batch_dir / "source"
    inv_pdfs    = _list_pdfs(src / "invoices")
    sad_pdfs    = _list_pdfs(src / "sad")
    awb_pdfs    = _list_pdfs(src / "awb")
    awb_filename = (audit.get("inputs") or {}).get("awb") or ""

    missing: List[str] = []
    if not inv_pdfs:
        missing.append("invoices")
    if not sad_pdfs:
        missing.append("sad")
    if awb_filename and not awb_pdfs:
        missing.append("awb")
    return (len(missing) == 0, missing)


# ── Scan (read-only) ──────────────────────────────────────────────────────────

def scan_batch(batch_dir: Path) -> BatchScanReport:
    audit = _audit_for_batch(batch_dir)
    if audit is None:
        return BatchScanReport(
            batch_id              = batch_dir.name,
            stale                 = False,
            reason                = "no audit.json — not a processed batch",
            row_schema_version    = "",
            source_docs_available = False,
            recommended_action    = "skip",
        )

    stale, reason = is_audit_stale(audit)
    summary       = stale_field_summary(audit)
    src_ok, missing_src = _check_source_documents(batch_dir, audit)

    if not stale:
        action = "skip_fresh"
    elif src_ok:
        action = "regenerate"
    else:
        action = "manual_review_missing_sources"

    return BatchScanReport(
        batch_id              = batch_dir.name,
        stale                 = stale,
        reason                = reason,
        row_schema_version    = summary.get("row_schema_version", "") or "",
        source_docs_available = src_ok,
        missing_source_kinds  = missing_src,
        missing_row_fields    = summary.get("rows_missing_fields", []),
        recommended_action    = action,
    )


def scan_outputs(outputs_dir: Path, batch_filter: Optional[str] = None) -> List[BatchScanReport]:
    if not outputs_dir.is_dir():
        return []
    reports: List[BatchScanReport] = []
    for child in sorted(outputs_dir.iterdir()):
        if not child.is_dir():
            continue
        if batch_filter and child.name != batch_filter:
            continue
        reports.append(scan_batch(child))
    return reports


# ── Apply (write — only when explicitly requested) ────────────────────────────

def _backup_batch_dir(batch_dir: Path) -> Path:
    """Create a timestamped backup copy of the entire batch directory."""
    stamp     = time.strftime("%Y%m%d_%H%M%S")
    backup    = batch_dir / f"backup_before_regen_{stamp}"
    backup.mkdir(parents=True, exist_ok=False)
    # Copy every immediate child except previous backups and temp/large dirs we
    # intentionally exclude to keep the backup compact.
    SKIP = {backup.name}
    for child in batch_dir.iterdir():
        if child.name in SKIP or child.name.startswith("backup_before_regen_"):
            continue
        dest = backup / child.name
        if child.is_dir():
            shutil.copytree(child, dest, dirs_exist_ok=False)
        else:
            shutil.copy2(child, dest)
    return backup


def regenerate_batch(
    batch_dir: Path,
    *,
    process_shipment_fn=None,
) -> BatchApplyReport:
    """Regenerate one batch end-to-end from its source/ documents.

    Optional `process_shipment_fn` lets tests inject a fake engine.
    """
    batch_id = batch_dir.name
    audit    = _audit_for_batch(batch_dir)
    if audit is None:
        return BatchApplyReport(batch_id=batch_id, regenerated=False,
                                reason="no audit.json")

    stale, _ = is_audit_stale(audit)
    if not stale:
        return BatchApplyReport(batch_id=batch_id, regenerated=False,
                                reason="audit is already fresh")

    src_ok, missing = _check_source_documents(batch_dir, audit)
    if not src_ok:
        return BatchApplyReport(batch_id=batch_id, regenerated=False,
                                reason=f"missing source kinds: {missing}")

    invoice_dir = batch_dir / "source" / "invoices"
    sad_pdfs    = _list_pdfs(batch_dir / "source" / "sad")
    zc429_path  = sad_pdfs[0]

    # Backup BEFORE writing anything
    try:
        backup_dir = _backup_batch_dir(batch_dir)
    except Exception as exc:
        return BatchApplyReport(batch_id=batch_id, regenerated=False,
                                reason="backup failed", error=str(exc))

    # Resolve engine entry point (lazy import to keep --dry-run lightweight)
    if process_shipment_fn is None:
        from app.services.export_service import process_shipment as process_shipment_fn  # type: ignore

    doc_no          = audit.get("doc_no") or ""
    settlement_mode = audit.get("settlement_mode") or "standard"
    carrier         = audit.get("carrier") or ""
    nbp_rate        = (audit.get("inputs") or {}).get("nbp_rate_usd")

    try:
        result = process_shipment_fn(
            invoice_dir     = invoice_dir,
            zc429_path      = zc429_path,
            output_dir      = batch_dir,
            doc_no          = doc_no,
            settlement_mode = settlement_mode,
            carrier         = carrier,
            nbp_rate        = nbp_rate,
        )
    except Exception as exc:
        return BatchApplyReport(
            batch_id=batch_id, regenerated=False,
            reason="engine raised", backup_dir=str(backup_dir), error=str(exc),
        )

    # Re-read the audit and confirm row_schema_version is now current.
    fresh_audit = _audit_for_batch(batch_dir) or {}
    new_version = fresh_audit.get("row_schema_version", "") or ""

    return BatchApplyReport(
        batch_id               = batch_id,
        regenerated            = new_version == CURRENT_ROW_SCHEMA_VERSION,
        reason                 = "ok" if new_version == CURRENT_ROW_SCHEMA_VERSION
                                 else "regen completed but row_schema_version did not advance",
        backup_dir             = str(backup_dir),
        new_audit_path         = str(batch_dir / "audit.json"),
        new_pdf_path           = str(result.get("pdf_path") or ""),
        new_xlsx_path          = str(result.get("xlsx_path") or ""),
        new_row_schema_version = new_version,
    )


def apply_outputs(
    outputs_dir: Path,
    batch_filter: Optional[str] = None,
    *,
    process_shipment_fn=None,
) -> List[BatchApplyReport]:
    reports: List[BatchApplyReport] = []
    for scan in scan_outputs(outputs_dir, batch_filter=batch_filter):
        if scan.recommended_action != "regenerate":
            reports.append(BatchApplyReport(
                batch_id=scan.batch_id, regenerated=False,
                reason=f"skipped ({scan.recommended_action})",
            ))
            continue
        reports.append(regenerate_batch(
            outputs_dir / scan.batch_id,
            process_shipment_fn=process_shipment_fn,
        ))
    return reports


# ── CLI ───────────────────────────────────────────────────────────────────────

def _format_dry_run(reports: List[BatchScanReport]) -> str:
    lines = []
    lines.append(f"{'BATCH':52s}  {'STALE':6s}  {'SCHEMA':8s}  {'SRC OK':6s}  ACTION")
    lines.append("-" * 110)
    for r in reports:
        lines.append(
            f"{r.batch_id[:52]:52s}  "
            f"{('YES' if r.stale else 'no'):6s}  "
            f"{(r.row_schema_version or '-'):8s}  "
            f"{('YES' if r.source_docs_available else 'NO'):6s}  "
            f"{r.recommended_action}"
        )
    return "\n".join(lines)


def _format_apply(reports: List[BatchApplyReport]) -> str:
    lines = []
    lines.append(f"{'BATCH':52s}  {'REGEN':6s}  REASON")
    lines.append("-" * 100)
    for r in reports:
        lines.append(
            f"{r.batch_id[:52]:52s}  "
            f"{('YES' if r.regenerated else 'no'):6s}  "
            f"{r.reason}"
        )
        if r.backup_dir:
            lines.append(f"    backup: {r.backup_dir}")
        if r.error:
            lines.append(f"    error : {r.error}")
    return "\n".join(lines)


def _resolve_outputs_dir(override: Optional[str]) -> Path:
    if override:
        return Path(override)
    from app.core.config import settings
    return Path(settings.storage_root) / "outputs"


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="regenerate_stale_batches",
                                description="Operator tool: regenerate stale PZ batches from source.")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true",
                   help="Read-only scan; report stale batches.")
    g.add_argument("--apply",   action="store_true",
                   help="Actually regenerate stale batches that have full source docs.")
    p.add_argument("--batch", default=None,
                   help="Limit scope to a single batch_id.")
    p.add_argument("--outputs-dir", default=None,
                   help="Override storage/outputs/ path (defaults to settings.storage_root).")
    p.add_argument("--json", action="store_true",
                   help="Emit machine-readable JSON output.")
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    outputs_dir = _resolve_outputs_dir(args.outputs_dir)
    if not outputs_dir.is_dir():
        log.error("Outputs dir does not exist: %s", outputs_dir)
        return 2

    if args.dry_run:
        reports = scan_outputs(outputs_dir, batch_filter=args.batch)
        if args.json:
            print(json.dumps([r.to_dict() for r in reports], indent=2, default=str))
        else:
            print(_format_dry_run(reports))
            stale_n = sum(1 for r in reports if r.stale)
            ready_n = sum(1 for r in reports if r.recommended_action == "regenerate")
            print()
            print(f"Total: {len(reports)} batches scanned, {stale_n} stale, "
                  f"{ready_n} ready to regenerate.")
        return 0

    # --apply
    apply_reports = apply_outputs(outputs_dir, batch_filter=args.batch)
    if args.json:
        print(json.dumps([r.to_dict() for r in apply_reports], indent=2, default=str))
    else:
        print(_format_apply(apply_reports))
        ok_n   = sum(1 for r in apply_reports if r.regenerated)
        fail_n = sum(1 for r in apply_reports if r.error)
        print()
        print(f"Total: {len(apply_reports)} processed, {ok_n} regenerated, {fail_n} errored.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
