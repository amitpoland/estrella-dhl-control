"""
proforma_draft_sync.py — Auto-create and sync proforma drafts from packing upload.
====================================================================================

Called non-blocking from routes_packing.upload_packing_list() after
seed_purchase_transit() completes. Any exception raised here is caught by the
caller and logged — the packing upload response is NEVER affected.

Sync logic per client found in sales_packing_lines:

  1. auto_create_draft_from_sales_packing() — idempotent create.
     a. was_created=True  → EV_PROFORMA_DRAFT_AUTO_CREATED
     b. was_created=False → inspect draft_state:
        - state in EDITABLE_STATES → reset_draft_from_sales_packing()
                                     + EV_PROFORMA_DRAFT_SYNCED
          NOTE: if the draft was in "draft" state, reset advances it to
          "editing" (via _next_state_after_edit). This is intentional and
          documented; operators can observe this in the draft panel.
          Any operator edits made since the draft was created will be
          overwritten — packing upload is the source of truth for line data.
        - finalized state (approved/posting/posted/cancelled/superseded)
          → EV_PROFORMA_SYNC_BLOCKED_FINALIZED, no write.
        - DraftConflict from TOCTOU race → treated as blocked (non-fatal).

Currency: modal (most-common) currency per client group from sales_packing_lines.
"""
from __future__ import annotations

import logging
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import document_db as ddb
from . import packing_db as _pdb
from . import proforma_invoice_link_db as pildb
from ..core import timeline as tl

log = logging.getLogger(__name__)


# ── Batch-scoped design → product_code resolver ──────────────────────────────
#
# Operational draft sync MUST use batch-scoped evidence only. The global
# design_product_mapping registry (design_product_bridge) is advisory and
# would leak cross-batch design collisions if used here.  We query
# packing_db.packing_lines directly with WHERE batch_id=? so resolution is
# strictly scoped to the same shipment.

def _resolve_product_codes_for_batch(
    batch_id: str,
) -> Dict[str, List[str]]:
    """Return ``{design_no: sorted([product_code, ...])}`` for *batch_id*.

    Local SELECT against ``packing_db.packing_lines``.  Batch-scoped by
    construction — design collisions across batches cannot leak into
    sales draft resolution.  Returns ``{}`` when packing_db is not
    initialised or the batch has no purchase packing_lines.
    """
    out: Dict[str, set] = {}
    if not (batch_id or "").strip():
        return {}
    db_path = getattr(_pdb, "_db_path", None)
    if db_path is None:
        return {}
    try:
        with sqlite3.connect(str(db_path)) as con:
            con.row_factory = sqlite3.Row
            rows = con.execute(
                "SELECT DISTINCT design_no, product_code FROM packing_lines "
                "WHERE batch_id=? "
                "AND product_code IS NOT NULL AND product_code<>''",
                (str(batch_id),),
            ).fetchall()
    except Exception as exc:
        log.warning(
            "[%s] batch-scoped design lookup failed (non-fatal): %s",
            batch_id, exc,
        )
        return {}
    for r in rows:
        d = (r["design_no"] or "").strip()
        p = (r["product_code"] or "").strip()
        if not d or not p:
            continue
        out.setdefault(d, set()).add(p)
    return {d: sorted(ps) for d, ps in out.items()}


def resolve_sales_lines_for_batch(
    batch_id:    str,
    sales_lines: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Resolve missing ``product_code`` on *sales_lines* using batch-scoped
    purchase packing_lines evidence only.

    Resolution order, per row:
      1. row already has non-empty ``product_code`` → keep unchanged.
      2. row has ``design_no`` and the batch lookup returns exactly ONE
         product_code → clone the row with the resolved ``product_code``
         and ``resolution_source="batch_packing_lines"`` (observability
         only; consumers must not depend on this field).
      3. batch lookup returns multiple candidates → leave row unchanged
         (empty ``product_code``); record under ``designs_ambiguous``.
      4. batch lookup returns zero candidates → leave row unchanged;
         record under ``designs_unresolved``.

    The DB-layer invariant in proforma_invoice_link_db.py — rows with
    empty ``product_code`` are skipped at create/reset time — is
    preserved.  This resolver only fills in product_code earlier, from
    same-batch local evidence.  It NEVER invents codes, NEVER uses
    design_no as a fallback product_code, and NEVER consults the global
    design_product_mapping registry.

    Returns (resolved_lines, summary). ``summary`` shape::

        {
          "designs_resolved":   {design_no: product_code, ...},
          "designs_ambiguous":  {design_no: [product_code, ...], ...},
          "designs_unresolved": [design_no, ...],
        }
    """
    lookup = _resolve_product_codes_for_batch(batch_id)
    resolved: List[Dict[str, Any]] = []
    designs_resolved:   Dict[str, str]       = {}
    designs_ambiguous:  Dict[str, List[str]] = {}
    designs_unresolved: set                  = set()

    for ln in (sales_lines or []):
        pc = str(ln.get("product_code") or "").strip()
        if pc:
            resolved.append(ln)
            continue
        dn = str(ln.get("design_no") or "").strip()
        if not dn:
            resolved.append(ln)
            continue
        cands = lookup.get(dn, [])
        if len(cands) == 1:
            clone = dict(ln)
            clone["product_code"]      = cands[0]
            clone["resolution_source"] = "batch_packing_lines"
            resolved.append(clone)
            designs_resolved[dn] = cands[0]
        elif len(cands) > 1:
            designs_ambiguous[dn] = list(cands)
            resolved.append(ln)
            log.warning(
                "[%s] sales draft sync: design %r ambiguous in batch "
                "packing_lines -> %s — skipping (no product_code set)",
                batch_id, dn, cands,
            )
        else:
            designs_unresolved.add(dn)
            resolved.append(ln)
            log.info(
                "[%s] sales draft sync: design %r unresolvable in batch "
                "packing_lines — skipping",
                batch_id, dn,
            )

    summary = {
        "designs_resolved":   designs_resolved,
        "designs_ambiguous":  designs_ambiguous,
        "designs_unresolved": sorted(designs_unresolved),
    }
    return resolved, summary


# ── Helpers ───────────────────────────────────────────────────────────────────

def _modal_currency(lines: List[Dict[str, Any]], fallback: str = "EUR") -> str:
    """Return the most-common non-empty currency from a list of sales lines."""
    counts: Counter = Counter()
    for ln in lines:
        c = str(ln.get("currency") or "").strip().upper()
        if c:
            counts[c] += 1
    return counts.most_common(1)[0][0] if counts else fallback


def _write_sync_metadata(
    db_path:  Path,
    draft_id: int,
    warning:  Optional[str],
) -> None:
    """Persist last_packing_sync_at and packing_sync_warning.

    Intentionally does NOT bump updated_at — this is audit metadata,
    not a content change, and OCC tokens held by concurrent operators
    should remain valid.
    """
    now = datetime.now(timezone.utc).isoformat()
    try:
        with sqlite3.connect(str(db_path), isolation_level="DEFERRED") as conn:
            conn.execute(
                """
                UPDATE proforma_drafts
                   SET last_packing_sync_at = ?,
                       packing_sync_warning  = ?
                 WHERE id = ?
                """,
                (now, warning, draft_id),
            )
    except Exception as exc:
        log.warning(
            "_write_sync_metadata: draft_id=%s failed (non-fatal): %s", draft_id, exc
        )


# ── Main entry point ──────────────────────────────────────────────────────────

def sync_draft_from_packing_upload(
    batch_id:   str,
    operator:   str,
    db_path:    Path,
    audit_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Auto-create/sync proforma drafts from packing upload.

    Returns a summary dict suitable for log.info(). Never raises.
    """
    # ── 1. Load sales packing lines (carries client_name + pricing) ──────────
    sales_lines: List[Dict[str, Any]] = []
    try:
        sales_lines = ddb.get_sales_packing_lines(batch_id)
    except Exception as exc:
        log.warning(
            "[%s] proforma_draft_sync: get_sales_packing_lines failed: %s",
            batch_id, exc,
        )

    if not sales_lines:
        return {
            "batch_id":          batch_id,
            "clients_processed": 0,
            "created":           0,
            "synced":            0,
            "blocked":           0,
            "no_sales_lines":    True,
            "designs_resolved":   {},
            "designs_ambiguous":  {},
            "designs_unresolved": [],
        }

    # ── 1.5 Resolve missing product_code via batch-scoped lookup ─────────────
    resolved_lines, resolution_summary = resolve_sales_lines_for_batch(
        batch_id, sales_lines,
    )

    # ── 2. Group by client_name ───────────────────────────────────────────────
    by_client: Dict[str, List[Dict[str, Any]]] = {}
    for ln in resolved_lines:
        cn = str(ln.get("client_name") or "").strip()
        if not cn:
            continue
        by_client.setdefault(cn, []).append(ln)

    result: Dict[str, Any] = {
        "batch_id":          batch_id,
        "clients_processed": 0,
        "created":           0,
        "synced":            0,
        "blocked":           0,
        "designs_resolved":   resolution_summary["designs_resolved"],
        "designs_ambiguous":  resolution_summary["designs_ambiguous"],
        "designs_unresolved": resolution_summary["designs_unresolved"],
    }

    # ── 3. Per-client sync ────────────────────────────────────────────────────
    for client_name, lines in by_client.items():
        currency = _modal_currency(lines)
        action   = "skipped"
        warning  = None

        try:
            draft, was_created = pildb.auto_create_draft_from_sales_packing(
                db_path,
                batch_id=batch_id,
                client_name=client_name,
                currency=currency,
                lines=lines,
                operator=operator,
            )

            if was_created:
                # ── 3a. Fresh draft created ───────────────────────────────
                action = "created"
                _write_sync_metadata(db_path, draft.id, warning=None)
                if audit_path:
                    tl.log_event(
                        audit_path,
                        tl.EV_PROFORMA_DRAFT_AUTO_CREATED,
                        "packing_upload",
                        actor=operator,
                        detail={
                            "batch_id":    batch_id,
                            "client_name": client_name,
                            "draft_id":    draft.id,
                            "lines":       len(lines),
                            "currency":    currency,
                        },
                    )
                result["created"] += 1

            elif draft.draft_state in pildb.EDITABLE_STATES:
                # ── 3b. Existing editable draft — reset lines ─────────────
                # Gate-side check performed above (pre-call).
                # DraftConflict (TOCTOU) and DraftNotEditable (defensive) are
                # both caught and treated as blocked.
                try:
                    updated = pildb.reset_draft_from_sales_packing(
                        db_path,
                        draft.id,
                        operator,
                        draft.updated_at,   # OCC token
                        sales_lines=lines,
                    )
                    action = "synced"
                    _write_sync_metadata(db_path, updated.id, warning=None)
                    if audit_path:
                        tl.log_event(
                            audit_path,
                            tl.EV_PROFORMA_DRAFT_SYNCED,
                            "packing_upload",
                            actor=operator,
                            detail={
                                "batch_id":    batch_id,
                                "client_name": client_name,
                                "draft_id":    updated.id,
                                "state_before": draft.draft_state,
                                "state_after":  updated.draft_state,
                                "lines":        len(lines),
                            },
                        )
                    result["synced"] += 1

                except (pildb.DraftNotEditable, pildb.DraftConflict) as exc:
                    # TOCTOU race: another writer changed the draft between
                    # auto_create (above) and reset (now). Treat as blocked.
                    action  = "blocked"
                    warning = f"sync_race:{type(exc).__name__}"
                    log.info(
                        "[%s] proforma_draft_sync: %s on draft %s — treating as blocked",
                        batch_id, type(exc).__name__, draft.id,
                    )
                    _write_sync_metadata(db_path, draft.id, warning=warning)
                    if audit_path:
                        tl.log_event(
                            audit_path,
                            tl.EV_PROFORMA_SYNC_BLOCKED_FINALIZED,
                            "packing_upload",
                            actor=operator,
                            detail={
                                "batch_id":    batch_id,
                                "client_name": client_name,
                                "draft_id":    draft.id,
                                "state":       draft.draft_state,
                                "reason":      type(exc).__name__,
                            },
                        )
                    result["blocked"] += 1

            else:
                # ── 3c. Finalized state — protected, skip ─────────────────
                action  = "blocked"
                warning = f"finalized:{draft.draft_state}"
                log.info(
                    "[%s] proforma_draft_sync: draft %s is %s — sync blocked",
                    batch_id, draft.id, draft.draft_state,
                )
                _write_sync_metadata(db_path, draft.id, warning=warning)
                if audit_path:
                    tl.log_event(
                        audit_path,
                        tl.EV_PROFORMA_SYNC_BLOCKED_FINALIZED,
                        "packing_upload",
                        actor=operator,
                        detail={
                            "batch_id":    batch_id,
                            "client_name": client_name,
                            "draft_id":    draft.id,
                            "state":       draft.draft_state,
                            "reason":      "finalized_state_protected",
                        },
                    )
                result["blocked"] += 1

        except Exception as exc:
            log.warning(
                "[%s] proforma_draft_sync: client=%s unexpected error (non-fatal): %s",
                batch_id, client_name, exc,
            )
            action = "error"

        result["clients_processed"] += 1
        log.debug(
            "[%s] proforma_draft_sync: client=%s action=%s warning=%s",
            batch_id, client_name, action, warning,
        )

    return result
