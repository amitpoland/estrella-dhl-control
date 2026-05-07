"""Sweep email_evidence/by_awb/*.json for messages misclassified
as event_type='other' that carry DHL ticket markers in the subject.

Read-only. Reports candidates for manual remediation via
email_evidence_store.update_message. Does not mutate any record.

Sibling of audit_email_evidence.py. Run after the email_thread_mapper
classifier fix has landed to identify pre-fix data debt.

Markers are imported from email_thread_mapper to avoid drift; if
the import fails the script aborts rather than duplicating
constants.

Usage:
    python scripts/audit_stale_event_types.py [--storage PATH] [--json]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

_SVC = Path(__file__).resolve().parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))


# ── Marker import (C5: import live constants; do not duplicate) ──────────────

try:
    from app.services.email_thread_mapper import (
        _DHL_TICKET_PATTERN,
        _DHL_TICKET_THREAD_PHRASES,
    )
except (ImportError, AttributeError) as exc:  # pragma: no cover - defended
    sys.stderr.write(
        "FATAL: could not import DHL ticket markers from "
        "app.services.email_thread_mapper "
        f"({type(exc).__name__}: {exc}). "
        "The sweep refuses to fall back to duplicated constants without "
        "explicit authorization (C5). Aborting.\n"
    )
    sys.exit(2)


# ── Storage resolution (mirror audit_email_evidence._resolve_storage) ────────

def _resolve_storage(override: Optional[str]) -> Path:
    if override:
        return Path(override)
    try:
        from app.core.config import settings
        return Path(settings.storage_root)
    except Exception:
        default = (
            Path.home() / "Library" / "Application Support"
            / "estrellajewels" / "storage"
        )
        return default


def _safe_load(p: Path) -> Dict[str, Any]:
    if not p.exists():
        return {}
    try:
        text = p.read_text(encoding="utf-8")
        return json.loads(text) if text.strip() else {}
    except Exception:
        return {}


# ── Marker detection ─────────────────────────────────────────────────────────

def _matched_markers(subject: str) -> List[str]:
    """Return the list of marker labels matched by *subject*. Empty list
    means no DHL ticket signature in the subject."""
    out: List[str] = []
    if not subject:
        return out
    s = subject.lower()
    if _DHL_TICKET_PATTERN.search(subject):
        out.append("ticket_token")
    for phrase in _DHL_TICKET_THREAD_PHRASES:
        if phrase.lower() in s:
            out.append(phrase)
    return out


# ── Sweep core (read-only) ───────────────────────────────────────────────────

def sweep(storage_root: Path) -> Dict[str, Any]:
    """
    Read every email_evidence/by_awb/*.json under *storage_root* and return
    a result dict containing scanned counts + suspect records.

    A suspect is a message where event_type == "other" AND the subject
    matches at least one DHL ticket marker.

    Read-only: no mutation, no network. Does not echo monetary fields
    even if present in the source data (customs-value-freeze).
    """
    evidence_dir = storage_root / "email_evidence" / "by_awb"
    if not evidence_dir.is_dir():
        raise FileNotFoundError(
            f"evidence directory not found: {evidence_dir}"
        )

    awb_files_scanned = 0
    messages_scanned  = 0
    suspects: List[Dict[str, Any]] = []

    for path in sorted(evidence_dir.glob("*.json")):
        doc = _safe_load(path)
        if not doc:
            continue
        awb_files_scanned += 1
        awb_label = doc.get("awb") or path.stem
        for thread in doc.get("threads", []) or []:
            for msg in thread.get("messages", []) or []:
                messages_scanned += 1
                if (msg.get("event_type") or "") != "other":
                    continue
                markers = _matched_markers(msg.get("subject") or "")
                if not markers:
                    continue
                # customs-value-freeze: enumerate ONLY the fields we report.
                # Even if monetary keys are present in the source dict, we
                # do not echo them.
                suspects.append({
                    "awb":             str(awb_label),
                    "message_id":      str(msg.get("message_id") or ""),
                    "subject":         msg.get("subject") or "",
                    "sender":          msg.get("sender") or "",
                    "direction":       msg.get("direction") or "",
                    "matched_markers": markers,
                })

    return {
        "scanned": {
            "awb_files": awb_files_scanned,
            "messages":  messages_scanned,
        },
        "suspects": suspects,
    }


# ── Output renderers ─────────────────────────────────────────────────────────

def _render_human(report: Dict[str, Any], out=sys.stdout) -> None:
    awb_files = report["scanned"]["awb_files"]
    messages  = report["scanned"]["messages"]
    suspects  = report["suspects"]
    awbs_with_suspects = len({s["awb"] for s in suspects})
    out.write("Counts:\n")
    out.write(f"  total_awb_files_scanned: {awb_files}\n")
    out.write(f"  total_messages_scanned:  {messages}\n")
    out.write(f"  suspect_messages_found:  {len(suspects)}\n")
    out.write(f"  awbs_with_suspects:      {awbs_with_suspects}\n")
    if not suspects:
        return
    out.write("\nSuspect records:\n")
    for s in suspects:
        subj_disp = (s["subject"] or "")[:120]
        out.write("\n")
        out.write(f"  AWB:        {s['awb']}\n")
        out.write(f"  Message ID: {s['message_id']}\n")
        out.write(f"  Subject:    {subj_disp}\n")
        out.write(f"  Sender:     {s['sender']}\n")
        out.write(f"  Direction:  {s['direction']}\n")
        out.write(f"  Marker(s):  {', '.join(s['matched_markers'])}\n")


def _render_json(report: Dict[str, Any], out=sys.stdout) -> None:
    json.dump(report, out, ensure_ascii=False, indent=2)
    out.write("\n")


# ── CLI ──────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--storage", help="Override storage root path")
    ap.add_argument("--json", action="store_true",
                    help="Output JSON instead of human-readable text")
    args = ap.parse_args()

    storage_root = _resolve_storage(args.storage)
    try:
        report = sweep(storage_root)
    except FileNotFoundError as exc:
        sys.stderr.write(f"ERROR: {exc}\n")
        return 1

    if args.json:
        _render_json(report)
    else:
        _render_human(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
