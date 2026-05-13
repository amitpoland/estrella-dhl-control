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
from typing import Any, Dict, List, Optional

from . import document_db as ddb
from . import proforma_invoice_link_db as pildb
from ..core import timeline as tl

log = logging.getLogger(__name__)


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
        }

    # ── 2. Group by client_name ───────────────────────────────────────────────
    by_client: Dict[str, List[Dict[str, Any]]] = {}
    for ln in sales_lines:
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
