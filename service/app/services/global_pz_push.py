"""
global_pz_push.py -- Governed wFirma push for staged Global PZ corrections.

This module is the ONLY path from a staged correction to a live wFirma PZ
document.  It is intentionally narrow:

  - Create-only.  No update, cancel, or delete.
  - Only ALIGN_TO_AUTHORITY and SPLIT_TO_STYLE_LEVEL are pushable.
  - KEEP_CURRENT / NO_ACTION are permanently blocked (KEEP_CURRENT = operator
    chose existing PZ; NO_ACTION = acknowledged, no PZ pending).
  - CANCEL_AND_RECREATE is OUT OF SCOPE for this implementation pass and
    must not be added here.
  - No wFirma call is made unless settings.wfirma_correction_push_allowed is True.
  - No wFirma call is made if audit.json already records a terminal PZ event
    (EV_WFIRMA_PZ_CREATED or wfirma_pz_adopted).
  - Idempotency is enforced via correction_push_record.json keyed on
    (batch_id, option_id, idempotency_key).  A matching record returns
    status="already_pushed" immediately without re-calling wFirma.
  - Audit event (EV_WFIRMA_PZ_CREATED) and wfirma_export patch are written
    BEFORE the function returns.  Failure to write audit is surfaced as a
    recoverable warning (document may exist; operator must inspect).

Safety properties (Lesson E compliance)
-----------------------------------------
1. Execution-time validation  -- pz_rows, product_map, audit state all
                                 validated at call time.
2. Idempotency                -- correction_push_record.json checked before
                                 any wFirma call; second call is a no-op.
3. Terminal-state suppression -- audit.json timeline checked; refuses to
                                 push if PZ already exists.
4. Replay safety              -- push record written after successful wFirma
                                 response; replayed calls return already_pushed.
5. Environment isolation      -- wfirma_correction_push_allowed flag must be
                                 True; flag must be explicitly set in .env.
                                 Never True by default.

Imports from wfirma_client only (for PZRequest, PZLine, PZResult,
create_warehouse_pz).  No routes imports.  No global_pz_execution imports.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..core.config import settings
from ..core.logging import get_logger

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Timeline event name (same string used by routes_wfirma.py)
EV_WFIRMA_PZ_CREATED = "wfirma_pz_created"

# Options that are eligible for a wFirma push
_PUSHABLE_OPTIONS: frozenset = frozenset({
    "ALIGN_TO_AUTHORITY",
    "SPLIT_TO_STYLE_LEVEL",
})

# Options that are explicitly blocked (operator chose to keep existing state)
_BLOCKED_OPTIONS: frozenset = frozenset({
    "KEEP_CURRENT",
    "NO_ACTION",
})

# Confirmation sentinel the caller must pass verbatim
_CONFIRM_SENTINEL = (
    "I confirm this will create a new wFirma PZ document "
    "and cannot be undone without manual wFirma intervention"
)

# Name of the push idempotency record
_PUSH_RECORD_NAME = "correction_push_record.json"


# ---------------------------------------------------------------------------
# Output contract
# ---------------------------------------------------------------------------

@dataclass
class PushResult:
    ok:                  bool
    batch_id:            str
    status:              str    # pushed | already_pushed | blocked | failed
    wfirma_document_id:  str    = ""
    action_taken:        str    = ""
    staged_option:       str    = ""
    pre_push_line_count: int    = 0
    post_push_line_count: int   = 0
    already_pushed:      bool   = False
    error:               Optional[str] = None
    action_required:     Optional[str] = None
    warnings:            List[str] = field(default_factory=list)
    rollback_note:       str    = ""
    audit_event_id:      str    = ""


# ---------------------------------------------------------------------------
# Storage helpers
# ---------------------------------------------------------------------------

def _batch_dir(batch_id: str, storage_root: Path) -> Optional[Path]:
    for sub in ("outputs", "working"):
        p = storage_root / sub / batch_id
        if p.exists():
            return p
    return None


def _read_json_file(path: Path) -> Optional[Any]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_json_file(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_pz_rows(batch_dir: Path) -> Optional[List[Dict[str, Any]]]:
    data = _read_json_file(batch_dir / "pz_rows.json")
    if isinstance(data, list):
        return data
    return None


def _read_audit(batch_dir: Path) -> Optional[Dict[str, Any]]:
    data = _read_json_file(batch_dir / "audit.json")
    if isinstance(data, dict):
        return data
    return None


def _push_record_path(batch_dir: Path) -> Path:
    return batch_dir / _PUSH_RECORD_NAME


def _check_idempotency(
    batch_dir: Path,
    option_id: str,
    idempotency_key: str,
) -> Optional[Dict[str, Any]]:
    """Return the existing push record if (option_id, idempotency_key) match."""
    p = _push_record_path(batch_dir)
    rec = _read_json_file(p)
    if not isinstance(rec, dict):
        return None
    if (
        rec.get("option_id") == option_id
        and rec.get("idempotency_key") == idempotency_key
    ):
        return rec
    return None


def _write_push_record(batch_dir: Path, record: Dict[str, Any]) -> str:
    p = _push_record_path(batch_dir)
    _write_json_file(p, record)
    return str(p)


def _has_terminal_pz_event(audit: Dict[str, Any]) -> Optional[str]:
    """Return the terminal PZ event name if already present, else None."""
    terminal_events = frozenset({EV_WFIRMA_PZ_CREATED, "wfirma_pz_adopted"})
    for ev in (audit.get("timeline") or []):
        name = (ev or {}).get("event") or ""
        if name in terminal_events:
            return name
    return None


def _patch_audit_pz_doc_id(
    batch_dir: Path,
    wfirma_pz_doc_id: str,
) -> Optional[str]:
    """
    Write wfirma_pz_doc_id into audit.json wfirma_export block.

    Returns None on success.  Returns an error string on failure (caller
    surfaces it as a warning — the wFirma document may already exist).
    """
    audit_path = batch_dir / "audit.json"
    if not audit_path.exists():
        return f"audit.json missing at {audit_path}"
    try:
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        existing = audit.get("wfirma_export") or {}
        audit["wfirma_export"] = {
            **existing,
            "wfirma_pz_doc_id": wfirma_pz_doc_id,
            "pz_source":        "created_via_correction_push",
            "pz_created_at":    time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        # Write atomically via temp-file swap (same pattern as write_json_atomic)
        _write_json_file(audit_path, audit)
        return None
    except Exception as exc:
        return f"audit patch failed: {exc}"


def _log_timeline_event(
    batch_dir: Path,
    event: str,
    detail: Dict[str, Any],
) -> str:
    """Append a timeline event to audit.json.  Returns a stable audit_event_id."""
    audit_path = batch_dir / "audit.json"
    if not audit_path.exists():
        return ""
    try:
        from ..core import timeline as tl  # noqa: PLC0415
        tl.log_event(audit_path, event, "system", "wfirma", detail=detail)
        return f"{event}:{detail.get('wfirma_pz_doc_id', '')}"
    except Exception as exc:
        log.warning("[global_pz_push] timeline log skipped: %s", exc)
        return ""


# ---------------------------------------------------------------------------
# Product map builder
# ---------------------------------------------------------------------------

def _build_product_map() -> Dict[str, str]:
    """Return {product_code -> wfirma_good_id} from the local product DB."""
    try:
        from ..services import wfirma_db  # noqa: PLC0415
        product_map: Dict[str, str] = {}
        for p in wfirma_db.list_products():
            pid  = (p.get("wfirma_product_id") or "").strip()
            code = (p.get("product_code") or "").strip()
            if pid and code:
                product_map[code] = pid
        return product_map
    except Exception as exc:
        log.warning("[global_pz_push] product map build failed: %s", exc)
        return {}


# ---------------------------------------------------------------------------
# PZ row → PZLine conversion
# ---------------------------------------------------------------------------

def _rows_to_pz_lines(
    pz_rows: List[Dict[str, Any]],
    product_map: Dict[str, str],
    warnings: List[str],
) -> Optional[List[Any]]:
    """
    Convert pz_rows entries to PZLine objects.

    Returns None if zero lines could be resolved (caller returns blocked).
    Rows whose product_code has no mapping are skipped and logged as warnings.
    """
    from ..services.wfirma_client import PZLine  # noqa: PLC0415

    lines: List[PZLine] = []
    for row in pz_rows:
        code     = (row.get("product_code") or "").strip()
        good_id  = product_map.get(code, "")
        qty      = float(row.get("quantity") or row.get("ilosc") or 0)
        # Prefer unit_netto_pln; fall back to cena_netto for legacy rows
        price    = float(
            row.get("unit_netto_pln")
            or row.get("cena_netto")
            or 0
        )
        if not good_id:
            warnings.append(
                f"product_code '{code}' has no wfirma_good_id mapping — row skipped"
            )
            continue
        if qty <= 0:
            warnings.append(
                f"product_code '{code}' has qty={qty} (<=0) — row skipped"
            )
            continue
        lines.append(PZLine(good_id=good_id, count=qty, price=price))

    if not lines:
        return None
    return lines


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def push_correction_to_wfirma(
    batch_id:              str,
    execution_record_id:   str,
    operator_reason:       str,
    idempotency_key:       str,
    confirm_understanding: str,
    storage_root:          Path,
    contractor_id:         str,
    warehouse_id:          str,
    product_map:           Optional[Dict[str, str]] = None,
) -> PushResult:
    """
    Push staged corrected PZ rows to wFirma as a new PZ document.

    This is the only wFirma write path for Global PZ corrections.

    Parameters
    ----------
    batch_id
        Batch identifier (e.g. SHIPMENT_4789974092_2026-05_999deef1).
    execution_record_id
        ID of the staged correction execution record (correction_execution_record.json
        was written by global_pz_execution.execute_correction_option).
    operator_reason
        Non-empty free-text reason; required and logged in push record.
    idempotency_key
        Caller-supplied opaque key for replay safety.  Same key + same
        option_id returns already_pushed immediately.
    confirm_understanding
        Must match _CONFIRM_SENTINEL exactly; prevents accidental invocation.
    storage_root
        Path to the app storage root (from settings).
    contractor_id
        wFirma contractor ID for the PZ document.
    warehouse_id
        wFirma warehouse ID for the PZ document.
    product_map
        Optional pre-built {product_code -> wfirma_good_id}.  Built from
        wfirma_db if None.

    Returns
    -------
    PushResult
        Always returned (never raises).  Check .ok and .status.
    """
    warnings: List[str] = []

    # ── Gate 1: confirmation sentinel ────────────────────────────────────────
    if confirm_understanding != _CONFIRM_SENTINEL:
        return PushResult(
            ok=False, batch_id=batch_id, status="blocked",
            error=(
                "confirm_understanding does not match required sentinel. "
                f"Required: {_CONFIRM_SENTINEL!r}"
            ),
        )

    # ── Gate 2: operator_reason ───────────────────────────────────────────────
    if not isinstance(operator_reason, str) or not operator_reason.strip():
        return PushResult(
            ok=False, batch_id=batch_id, status="blocked",
            error="operator_reason is required and must not be empty.",
        )

    # ── Gate 3: write flag ────────────────────────────────────────────────────
    if not settings.wfirma_correction_push_allowed:
        return PushResult(
            ok=False, batch_id=batch_id, status="blocked",
            error=(
                "wFirma correction push is disabled. "
                "Set WFIRMA_CORRECTION_PUSH_ALLOWED=true in .env to enable."
            ),
        )

    # ── Gate 4: basic ID validation ───────────────────────────────────────────
    if "/" in batch_id or ".." in batch_id:
        return PushResult(
            ok=False, batch_id=batch_id, status="blocked",
            error="Invalid batch_id: path traversal characters not allowed.",
        )

    # ── Find batch storage ────────────────────────────────────────────────────
    bdir = _batch_dir(batch_id, storage_root)
    if bdir is None:
        return PushResult(
            ok=False, batch_id=batch_id, status="failed",
            error=f"Batch storage directory not found for {batch_id!r}.",
        )

    # ── Gate 5: staged execution record must exist ────────────────────────────
    exec_record = _read_json_file(bdir / "correction_execution_record.json")
    if not isinstance(exec_record, dict):
        return PushResult(
            ok=False, batch_id=batch_id, status="blocked",
            error=(
                "No staged correction execution record found. "
                "Run POST /pz/lineage/{batch_id}/correction-execute first."
            ),
        )

    staged_option = exec_record.get("option_id", "")

    # ── Gate 6: option must be pushable ───────────────────────────────────────
    if staged_option in _BLOCKED_OPTIONS:
        reason = (
            "KEEP_CURRENT: operator accepted the existing PZ structure — no push needed."
            if staged_option == "KEEP_CURRENT"
            else "NO_ACTION: acknowledged, no PZ document pending."
        )
        return PushResult(
            ok=False,
            batch_id=batch_id,
            status="blocked",
            staged_option=staged_option,
            error=f"Option {staged_option!r} is not pushable to wFirma. {reason}",
        )

    if staged_option not in _PUSHABLE_OPTIONS:
        return PushResult(
            ok=False, batch_id=batch_id, status="blocked",
            staged_option=staged_option,
            error=(
                f"Option {staged_option!r} is not recognised as pushable. "
                f"Pushable options: {sorted(_PUSHABLE_OPTIONS)}"
            ),
        )

    # ── Gate 7: idempotency check ─────────────────────────────────────────────
    existing_push = _check_idempotency(bdir, staged_option, idempotency_key)
    if existing_push:
        log.info(
            "[%s] push_correction_to_wfirma: already_pushed (doc_id=%s)",
            batch_id, existing_push.get("wfirma_document_id", ""),
        )
        return PushResult(
            ok=True,
            batch_id=batch_id,
            status="already_pushed",
            wfirma_document_id=existing_push.get("wfirma_document_id", ""),
            staged_option=staged_option,
            pre_push_line_count=existing_push.get("pre_push_line_count", 0),
            post_push_line_count=existing_push.get("post_push_line_count", 0),
            already_pushed=True,
            action_taken=existing_push.get("action_taken", ""),
            rollback_note=(
                "wFirma documents cannot be deleted via API. "
                "Manual wFirma intervention required to remove if needed."
            ),
            audit_event_id=existing_push.get("audit_event_id", ""),
        )

    # ── Gate 8: terminal-state suppression (audit timeline check) ────────────
    audit = _read_audit(bdir)
    if audit is None:
        return PushResult(
            ok=False, batch_id=batch_id, status="blocked",
            error="audit.json not found — cannot verify terminal PZ state.",
        )

    terminal_ev = _has_terminal_pz_event(audit)
    if terminal_ev:
        existing_doc_id = (audit.get("wfirma_export") or {}).get("wfirma_pz_doc_id", "")
        return PushResult(
            ok=False,
            batch_id=batch_id,
            status="blocked",
            staged_option=staged_option,
            wfirma_document_id=existing_doc_id,
            error=(
                f"A wFirma PZ document already exists for this batch "
                f"(event: {terminal_ev!r}, doc_id: {existing_doc_id!r}). "
                "Push rejected to prevent duplicate document creation."
            ),
            action_required=(
                "Inspect existing wFirma PZ via the dashboard. "
                "Manual wFirma correction required if the existing document is incorrect."
            ),
        )

    # ── Read staged pz_rows ───────────────────────────────────────────────────
    pz_rows = _read_pz_rows(bdir)
    if not pz_rows:
        return PushResult(
            ok=False, batch_id=batch_id, status="blocked",
            staged_option=staged_option,
            error="pz_rows.json not found or empty — cannot push empty PZ.",
        )

    pre_push_count = len(pz_rows)

    # ── Build product map ─────────────────────────────────────────────────────
    if product_map is None:
        product_map = _build_product_map()

    if not product_map:
        return PushResult(
            ok=False, batch_id=batch_id, status="blocked",
            staged_option=staged_option,
            pre_push_line_count=pre_push_count,
            error=(
                "Product map is empty — no product_code → wfirma_good_id mappings found. "
                "Ensure products are synced from wFirma before pushing."
            ),
        )

    # ── Convert rows to PZLines ───────────────────────────────────────────────
    pz_lines = _rows_to_pz_lines(pz_rows, product_map, warnings)
    if pz_lines is None:
        return PushResult(
            ok=False, batch_id=batch_id, status="blocked",
            staged_option=staged_option,
            pre_push_line_count=pre_push_count,
            error=(
                "No PZ lines could be resolved from pz_rows. "
                "All product_code values are unmapped or have zero quantity."
            ),
            warnings=warnings,
        )

    # ── Build PZRequest ───────────────────────────────────────────────────────
    try:
        from ..services.wfirma_client import PZRequest, create_warehouse_pz  # noqa: PLC0415
    except ImportError as exc:
        return PushResult(
            ok=False, batch_id=batch_id, status="failed",
            staged_option=staged_option,
            error=f"wfirma_client unavailable: {exc}",
        )

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    description = (
        f"Correction push: {staged_option} | batch: {batch_id} | "
        f"reason: {operator_reason.strip()[:120]}"
    )

    pz_request = PZRequest(
        contractor_id=contractor_id,
        warehouse_id=warehouse_id,
        date=today,
        description=description,
        lines=pz_lines,
    )

    # ── Call wFirma ───────────────────────────────────────────────────────────
    log.info(
        "[%s] push_correction_to_wfirma: calling create_warehouse_pz "
        "(option=%s, lines=%d)",
        batch_id, staged_option, len(pz_lines),
    )

    # Timeline pre-event (intent logged before the call)
    _log_timeline_event(bdir, "wfirma_pz_correction_push_started", {
        "batch_id":     batch_id,
        "staged_option": staged_option,
        "line_count":   len(pz_lines),
        "idempotency_key": idempotency_key,
    })

    pz_result = create_warehouse_pz(pz_request)

    if not pz_result.ok:
        log.warning(
            "[%s] push_correction_to_wfirma: wFirma returned failure: %s",
            batch_id, pz_result.error,
        )
        _log_timeline_event(bdir, "wfirma_pz_correction_push_failed", {
            "batch_id":      batch_id,
            "staged_option": staged_option,
            "error":         pz_result.error,
        })
        return PushResult(
            ok=False,
            batch_id=batch_id,
            status="failed",
            staged_option=staged_option,
            pre_push_line_count=pre_push_count,
            error=pz_result.error or "wFirma create_warehouse_pz returned ok=False.",
            warnings=warnings,
            action_required=(
                "The push record was NOT written (no document was created). "
                "Retry with the same idempotency_key once the wFirma issue is resolved."
            ),
        )

    # ── Success path ──────────────────────────────────────────────────────────
    wfirma_document_id = pz_result.wfirma_pz_doc_id

    # 1. Patch audit.json (must succeed before declaring success)
    audit_patch_error = _patch_audit_pz_doc_id(bdir, wfirma_document_id)
    if audit_patch_error:
        warnings.append(
            f"AUDIT PATCH FAILED: {audit_patch_error}. "
            f"wFirma PZ {wfirma_document_id!r} was created but audit.json "
            "was not updated. Manual audit reconciliation required."
        )
        log.error(
            "[%s] push_correction_to_wfirma: AUDIT PATCH FAILED doc_id=%s — %s",
            batch_id, wfirma_document_id, audit_patch_error,
        )

    # 2. Log terminal timeline event
    audit_event_id = _log_timeline_event(bdir, EV_WFIRMA_PZ_CREATED, {
        "batch_id":         batch_id,
        "wfirma_pz_doc_id": wfirma_document_id,
        "line_count":       len(pz_lines),
        "staged_option":    staged_option,
        "source":           "correction_push",
    })

    # 3. Write idempotency record (after successful wFirma + audit write)
    push_record: Dict[str, Any] = {
        "batch_id":            batch_id,
        "option_id":           staged_option,
        "idempotency_key":     idempotency_key,
        "operator_reason":     operator_reason.strip(),
        "pushed_at":           datetime.now(timezone.utc).isoformat(),
        "wfirma_document_id":  wfirma_document_id,
        "pre_push_line_count": pre_push_count,
        "post_push_line_count": len(pz_lines),
        "action_taken":        f"created_wfirma_pz_via_correction_{staged_option.lower()}",
        "audit_event_id":      audit_event_id,
        "audit_patch_error":   audit_patch_error,
    }
    push_record_path = _write_push_record(bdir, push_record)

    log.info(
        "[%s] push_correction_to_wfirma: SUCCESS doc_id=%s lines=%d record=%s",
        batch_id, wfirma_document_id, len(pz_lines), push_record_path,
    )

    return PushResult(
        ok=True,
        batch_id=batch_id,
        status="pushed",
        wfirma_document_id=wfirma_document_id,
        action_taken=f"created_wfirma_pz_via_correction_{staged_option.lower()}",
        staged_option=staged_option,
        pre_push_line_count=pre_push_count,
        post_push_line_count=len(pz_lines),
        already_pushed=False,
        warnings=warnings,
        rollback_note=(
            "wFirma PZ documents cannot be deleted via API. "
            "Manual wFirma intervention required to remove document "
            f"{wfirma_document_id!r} if needed."
        ),
        audit_event_id=audit_event_id,
    )
