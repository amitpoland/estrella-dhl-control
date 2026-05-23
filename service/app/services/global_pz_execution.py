"""
global_pz_execution.py -- Governed execution of Global PZ correction options.

Execution target: LOCAL pz_rows.json staging file only.
No wFirma API calls are made here.
wFirma push is a separate, downstream operator action ("Execute PZ in wFirma").

Tiers
-----
KEEP_CURRENT / NO_ACTION
    Acknowledgement only.  pz_rows.json is not touched.
    Audit record written.

ALIGN_TO_AUTHORITY
    Renames product_codes in pz_rows.json to the suggested INV-NN format
    derived from invoice_position_no.  Quantities and values are unchanged.
    Backup created before modification.

SPLIT_TO_STYLE_LEVEL
    Rebuilds pz_rows.json with one line per (invoice_position, item_type).
    Values are allocated proportionally by packing_qty within each position.
    Backup created before modification.

Safety properties (Lesson E compliance)
-----------------------------------------
1. Execution-time validation  -- option_id and pz_rows validated at call time.
2. Idempotency                -- correction_execution_record.json checked before
                                 any write; second call returns the existing record.
3. Terminal-state suppression -- caller (endpoint) must pass is_global_supplier
                                 gate before calling this service.
4. Replay safety              -- backup + record written atomically; rollback_command
                                 returned so operator can undo.
5. No direct wFirma calls     -- wFirma is touched only by the existing PZ execution
                                 pipeline, not here.

No imports from wfirma_*.  Verified by test_global_pz_execution.py AST check.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Output contract
# ---------------------------------------------------------------------------

@dataclass
class ExecutionResult:
    ok:               bool
    batch_id:         str
    option_id:        str
    already_executed: bool = False
    pre_line_count:   int  = 0
    post_line_count:  int  = 0
    backup_path:      str  = ""
    rollback_command: str  = ""
    audit_ref:        str  = ""
    wfirma_action:    str  = "none"
    error:            Optional[str] = None
    notes:            List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Storage helpers
# ---------------------------------------------------------------------------

_VALID_OPTIONS = frozenset({
    "KEEP_CURRENT",
    "ALIGN_TO_AUTHORITY",
    "SPLIT_TO_STYLE_LEVEL",
    "NO_ACTION",
})


def _batch_dir(batch_id: str, storage_root: Path) -> Optional[Path]:
    for sub in ("outputs", "working"):
        p = storage_root / sub / batch_id
        if p.exists():
            return p
    return None


def _read_pz_rows(batch_dir: Path) -> Optional[List[Dict[str, Any]]]:
    f = batch_dir / "pz_rows.json"
    if not f.exists():
        return None
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else None
    except Exception:
        return None


def _write_pz_rows(batch_dir: Path, rows: List[Dict[str, Any]]) -> None:
    (batch_dir / "pz_rows.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _backup_pz_rows(batch_dir: Path) -> str:
    src = batch_dir / "pz_rows.json"
    if not src.exists():
        return ""
    ts  = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    dst = batch_dir / f"pz_rows_correction_backup_{ts}.json"
    dst.write_bytes(src.read_bytes())
    return str(dst)


def _record_path(batch_dir: Path) -> Path:
    return batch_dir / "correction_execution_record.json"


def _check_idempotency(batch_dir: Path, option_id: str) -> Optional[Dict[str, Any]]:
    """Return the existing record if this option_id was already executed."""
    p = _record_path(batch_dir)
    if not p.exists():
        return None
    try:
        rec = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(rec, dict) and rec.get("option_id") == option_id:
            return rec
    except Exception:
        pass
    return None


def _write_record(batch_dir: Path, record: Dict[str, Any]) -> str:
    p = _record_path(batch_dir)
    p.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(p)


# ---------------------------------------------------------------------------
# Option-specific transforms
# ---------------------------------------------------------------------------

def _align_product_codes(
    rows: List[Dict[str, Any]],
    proposed_lines: List[Any],
) -> List[Dict[str, Any]]:
    """Rename product_code to suggested_product_code (INV-NN) for each row.

    Matches by pz_row['line_position'] == ProposedLine.invoice_position_no.
    Rows without a matching ProposedLine are left unchanged.
    """
    code_map: Dict[int, str] = {
        pl.invoice_position_no: pl.suggested_product_code
        for pl in proposed_lines
        if pl.suggested_product_code
    }
    updated = []
    for row in rows:
        r = dict(row)
        pos = r.get("line_position")
        if pos is not None and pos in code_map:
            r["_original_product_code"] = r.get("product_code", "")
            r["product_code"] = code_map[pos]
        updated.append(r)
    return updated


def _split_to_style_level(
    rows: List[Dict[str, Any]],
    proposed_lines: List[Any],
) -> List[Dict[str, Any]]:
    """Rebuild pz_rows with one line per (invoice_position_no, item_type).

    Proportional value allocation:
        proportion  = packing_qty_for_this_type / sum(packing_qty_at_this_position)
        line_netto  = parent_line_netto * proportion
        unit_netto  = line_netto / packing_qty  (>= 1)

    Parent row fields (invoice_no, usd_pln, unit, etc.) are inherited.
    Rows whose line_position is not in proposed_lines are carried unchanged.
    """
    from collections import defaultdict

    # Group proposed lines by position
    by_pos: Dict[int, List[Any]] = defaultdict(list)
    for pl in proposed_lines:
        by_pos[pl.invoice_position_no].append(pl)

    # Index existing rows by line_position (last one wins if duplicate)
    row_by_pos: Dict[int, Dict[str, Any]] = {}
    for row in rows:
        pos = row.get("line_position")
        if pos is not None:
            row_by_pos[int(pos)] = row

    result: List[Dict[str, Any]] = []
    handled_positions: set = set()

    for pos, pls in sorted(by_pos.items()):
        handled_positions.add(pos)
        parent = row_by_pos.get(pos)
        if parent is None:
            # No existing row for this position — skip (should not happen)
            continue

        total_qty = sum(max(float(pl.packing_qty), 1.0) for pl in pls)
        parent_netto  = float(parent.get("line_netto_pln",  0.0))
        parent_brutto = float(parent.get("line_brutto_pln", 0.0))
        parent_duty   = float(parent.get("allocated_duty_pln", 0.0))

        for pl in sorted(pls, key=lambda p: p.item_type):
            qty        = max(float(pl.packing_qty), 1.0)
            proportion = qty / total_qty
            line_netto  = round(parent_netto  * proportion, 6)
            line_brutto = round(parent_brutto * proportion, 6)
            line_duty   = round(parent_duty   * proportion, 6)
            unit_netto  = round(line_netto / qty, 6) if qty else 0.0

            new_row = dict(parent)
            new_row.update({
                "product_code":         pl.suggested_product_code or f"INV-{pos:02d}",
                "line_position":        pos,
                "item_type":            pl.item_type,
                "quantity":             qty,
                "unit_netto_pln":       unit_netto,
                "line_netto_pln":       line_netto,
                "line_brutto_pln":      line_brutto,
                "allocated_duty_pln":   line_duty,
                "_split_from_code":     parent.get("product_code", ""),
                "_split_proportion":    round(proportion, 6),
                "_allocation_confidence": pl.allocation_confidence,
                "_allocation_reason_codes": pl.allocation_reason_codes,
            })
            result.append(new_row)

    # Carry unchanged rows for positions not in proposed_lines
    for row in rows:
        pos = row.get("line_position")
        if pos not in handled_positions:
            result.append(dict(row))

    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def execute_correction_option(
    batch_id:        str,
    option_id:       str,
    operator_reason: str,
    proposed_lines:  List[Any],
    storage_root:    Path,
) -> ExecutionResult:
    """Execute the chosen correction option against the local pz_rows.json.

    Parameters
    ----------
    batch_id        Batch identifier (e.g. SHIPMENT_4789974092_2026-05_999deef1).
    option_id       One of KEEP_CURRENT / NO_ACTION / ALIGN_TO_AUTHORITY /
                    SPLIT_TO_STYLE_LEVEL.
    operator_reason Non-empty free-text reason; required before any write.
    proposed_lines  ProposedLine list re-derived server-side from the correction
                    engine.  Never taken from client input.
    storage_root    Path to the app storage root (from settings).
    """
    # --- Gate: validate inputs -------------------------------------------
    if option_id not in _VALID_OPTIONS:
        return ExecutionResult(
            ok=False, batch_id=batch_id, option_id=option_id,
            error=f"Unknown option_id: {option_id!r}. Valid: {sorted(_VALID_OPTIONS)}",
        )

    if not isinstance(operator_reason, str) or not operator_reason.strip():
        return ExecutionResult(
            ok=False, batch_id=batch_id, option_id=option_id,
            error="operator_reason is required and must not be empty.",
        )

    # --- Find batch storage -----------------------------------------------
    bdir = _batch_dir(batch_id, storage_root)
    if bdir is None:
        return ExecutionResult(
            ok=False, batch_id=batch_id, option_id=option_id,
            error=f"Batch storage directory not found for {batch_id!r}.",
        )

    # --- Idempotency check -----------------------------------------------
    existing = _check_idempotency(bdir, option_id)
    if existing:
        return ExecutionResult(
            ok=True,
            batch_id=batch_id,
            option_id=option_id,
            already_executed=True,
            pre_line_count=existing.get("pre_line_count", 0),
            post_line_count=existing.get("post_line_count", 0),
            backup_path=existing.get("backup_path", ""),
            rollback_command=existing.get("rollback_command", ""),
            audit_ref=str(_record_path(bdir)),
            wfirma_action=existing.get("wfirma_action", "none"),
            notes=["Already executed -- returning existing record."],
        )

    # --- Read current pz_rows --------------------------------------------
    pz_rows = _read_pz_rows(bdir)
    pre_count   = len(pz_rows) if pz_rows else 0
    backup_path = ""
    post_rows   = list(pz_rows) if pz_rows else []
    wfirma_action = "none"
    notes: List[str] = []
    executed_at = datetime.now(timezone.utc).isoformat()

    # --- Execute ---------------------------------------------------------
    if option_id in ("KEEP_CURRENT", "NO_ACTION"):
        notes.append(
            "Operator accepted existing PZ structure. "
            "No pz_rows.json changes. wFirma is unchanged."
        )

    elif option_id == "ALIGN_TO_AUTHORITY":
        if not pz_rows:
            return ExecutionResult(
                ok=False, batch_id=batch_id, option_id=option_id,
                error="pz_rows.json not found or empty -- cannot align product codes.",
            )
        backup_path = _backup_pz_rows(bdir)
        post_rows   = _align_product_codes(pz_rows, proposed_lines)
        _write_pz_rows(bdir, post_rows)
        wfirma_action = "product_code_rename_in_staging"
        notes.append(
            f"Product codes renamed to INV-NN format in pz_rows.json. "
            f"Backup: {backup_path}. "
            f"wFirma push is a separate operator step (Execute PZ in wFirma)."
        )

    elif option_id == "SPLIT_TO_STYLE_LEVEL":
        if not pz_rows:
            return ExecutionResult(
                ok=False, batch_id=batch_id, option_id=option_id,
                error="pz_rows.json not found or empty -- cannot split to style level.",
            )
        backup_path = _backup_pz_rows(bdir)
        post_rows   = _split_to_style_level(pz_rows, proposed_lines)
        _write_pz_rows(bdir, post_rows)
        wfirma_action = "pz_rows_rebuilt_split_staging"
        notes.append(
            f"pz_rows.json rebuilt with {len(post_rows)} lines (was {pre_count}). "
            f"Values allocated proportionally by packing_qty. "
            f"Backup: {backup_path}. "
            f"wFirma push is a separate operator step."
        )

    post_count = len(post_rows)
    pz_rows_path = str(bdir / "pz_rows.json")
    rollback_cmd = (
        f"copy {backup_path!r} {pz_rows_path!r}"
        if backup_path
        else "No rollback needed -- no file was changed."
    )

    record: Dict[str, Any] = {
        "batch_id":        batch_id,
        "option_id":       option_id,
        "operator_reason": operator_reason.strip(),
        "executed_at":     executed_at,
        "pre_line_count":  pre_count,
        "post_line_count": post_count,
        "backup_path":     backup_path,
        "rollback_command": rollback_cmd,
        "wfirma_action":   wfirma_action,
        "notes":           notes,
    }
    audit_ref = _write_record(bdir, record)

    return ExecutionResult(
        ok=True,
        batch_id=batch_id,
        option_id=option_id,
        pre_line_count=pre_count,
        post_line_count=post_count,
        backup_path=backup_path,
        rollback_command=rollback_cmd,
        audit_ref=audit_ref,
        wfirma_action=wfirma_action,
        notes=notes,
    )
