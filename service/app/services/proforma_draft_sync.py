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
from . import master_data_db as mdb
from . import packing_db as _pdb
from . import proforma_invoice_link_db as pildb
from . import preamble_signals as _ps
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


# ── HS code resolution (Phase 4) ─────────────────────────────────────────────
#
# Priority chain (per product_code):
#   1. product_local.hs_code_override   (master_data.sqlite, operator-curated)
#   2. invoice_lines.hs_code / hsn_code (documents.db, parsed from invoices)
#   3. None — caller leaves existing value unchanged
#
# All lookups are best-effort: any exception or None result falls through
# to the next level. Never raises.

def _resolve_hs_code(
    product_code:   str,
    master_db_path: Optional[Path],
) -> Optional[str]:
    """Return the best-available HS code for *product_code*, or None.

    Level 1 — product_local.hs_code_override (master_data.sqlite).
    Level 2 — invoice_lines.hs_code / hsn_code from documents.db.
    Returns None if neither source has a non-empty value.
    """
    if not (product_code or "").strip():
        return None

    # ── Level 1: product_local override ──────────────────────────────────────
    if master_db_path is not None:
        try:
            pl = mdb.get_product_local(master_db_path, product_code.strip())
            # Phase 4B Wave 4: an INACTIVE overlay means "stop applying overlay"
            # — treat it as a Level-1 miss and fall through to invoice lines.
            if (pl and getattr(pl, "active", True)
                    and (pl.hs_code_override or "").strip()):
                return pl.hs_code_override.strip()
        except Exception as _exc:
            log.debug(
                "_resolve_hs_code: product_local lookup failed for %r: %s",
                product_code, _exc,
            )

    # ── Level 2: invoice_lines in documents.db ────────────────────────────────
    docs_db = getattr(ddb, "_db_path", None)
    if docs_db is not None:
        try:
            with sqlite3.connect(str(docs_db)) as con:
                con.row_factory = sqlite3.Row
                row = con.execute(
                    """
                    SELECT hs_code, hsn_code
                      FROM invoice_lines
                     WHERE UPPER(TRIM(product_code)) = UPPER(TRIM(?))
                       AND (
                             (hs_code  IS NOT NULL AND hs_code  <> '')
                             OR
                             (hsn_code IS NOT NULL AND hsn_code <> '')
                           )
                     ORDER BY rowid DESC
                     LIMIT 1
                    """,
                    (product_code.strip(),),
                ).fetchone()
                if row:
                    hs = (row["hs_code"] or row["hsn_code"] or "").strip()
                    if hs:
                        return hs
        except Exception as _exc:
            log.debug(
                "_resolve_hs_code: invoice_lines lookup failed for %r: %s",
                product_code, _exc,
            )

    return None


def _enrich_lines_with_hs(
    lines:          List[Dict[str, Any]],
    master_db_path: Optional[Path],
) -> List[Dict[str, Any]]:
    """Return a copy of *lines* with ``hs_code`` filled from the resolution chain.

    Lines that already carry a non-empty ``hs_code`` are left unchanged
    (operator-entered values take precedence). Lines whose resolved value is
    None are left unchanged. Never mutates the input list.
    """
    if not master_db_path and getattr(ddb, "_db_path", None) is None:
        return lines  # no resolution source available — fast exit

    result: List[Dict[str, Any]] = []
    for ln in lines:
        existing = str(ln.get("hs_code") or "").strip()
        if existing:
            result.append(ln)
            continue
        pc = str(ln.get("product_code") or "").strip()
        resolved = _resolve_hs_code(pc, master_db_path) if pc else None
        if resolved:
            clone = dict(ln)
            clone["hs_code"] = resolved
            result.append(clone)
        else:
            result.append(ln)
    return result


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


# ── Draft-birth skip-visibility helpers (PR 1) ────────────────────────────────
#
# When sync_draft_from_packing_upload() drops a sales_document because every
# one of its lines has empty client_name, the existing code emits NO timeline
# event. That silent-drop class forced operators into manual forensic work
# (e.g. SHIPMENT_7123231135_2026-06_f255bbb5 missing drafts for EJL-26-27/258
# and /260). These helpers emit ONE event per dropped sales_document with
# read-only identity-signal observations (VAT, heading candidate) so the
# audit shows exactly what evidence existed at the moment of failure.
#
# CRITICAL: These helpers are observation only. They do NOT change which
# drafts get created. Pre-PR draft count == post-PR draft count for every
# input.


def _lookup_sales_doc_source_path(
    batch_id: str,
    sales_document_id: str,
) -> Tuple[str, str]:
    """Return (source_file_path, sales_doc_no) for a sales_document_id.

    Reads from ``documents.db`` via ``ddb.get_sales_documents`` (NOT from
    ``proforma_links.db`` — sales_documents is owned by the documents
    registry). Both fields are best-effort; either may be '' if the row
    is missing or the lookup fails. Never raises.
    """
    if not sales_document_id:
        return "", ""
    try:
        for sd in (ddb.get_sales_documents(batch_id) or []):
            if str(sd.get("id") or "") == str(sales_document_id):
                return (
                    str(sd.get("source_file_path") or ""),
                    str(sd.get("sales_doc_no") or ""),
                )
        return "", ""
    except Exception as exc:
        log.debug(
            "_lookup_sales_doc_source_path: id=%s failed (non-fatal): %s",
            sales_document_id, exc,
        )
        return "", ""


def _emit_draft_birth_skip_events(
    resolved_lines: List[Dict[str, Any]],
    by_client:      Dict[str, List[Dict[str, Any]]],
    audit_path:     Optional[Path],
    operator:       str,
    batch_id:       str,
) -> Tuple[int, int]:
    """Emit ONE timeline event per sales_document whose lines were all dropped
    due to empty client_name. Returns (pending_count, skipped_count).

    pending_count  = docs that emitted EV_PROFORMA_DRAFT_CREATION_PENDING_RESOLUTION
                     (at least one identity signal — VAT or heading candidate — found)
    skipped_count  = docs that emitted EV_PROFORMA_DRAFT_CREATION_SKIPPED
                     (no identity signals found)

    Behaviour-invariant: this function does not mutate `by_client`,
    `resolved_lines`, or any database. It only appends events to audit.json.
    """
    if audit_path is None:
        return 0, 0

    # Aggregate per sales_document_id: lines_count, value_sum, currency, has_client.
    per_doc: Dict[str, Dict[str, Any]] = {}
    for ln in resolved_lines:
        sd_id = str(ln.get("sales_document_id") or "")
        if not sd_id:
            continue
        info = per_doc.setdefault(sd_id, {
            "lines_count":  0,
            "value":        0.0,
            "currency":     "",
            "has_client":   False,
        })
        info["lines_count"] += 1
        try:
            info["value"] += float(ln.get("total_value") or 0)
        except (TypeError, ValueError):
            pass
        if not info["currency"]:
            info["currency"] = str(ln.get("currency") or "")
        if str(ln.get("client_name") or "").strip():
            info["has_client"] = True

    # Only docs that contributed ZERO lines to by_client are dropped.
    dropped = {sd: info for sd, info in per_doc.items() if not info["has_client"]}
    if not dropped:
        return 0, 0

    pending = 0
    skipped = 0
    for sd_id, info in dropped.items():
        source_file_path, sales_doc_no = _lookup_sales_doc_source_path(batch_id, sd_id)

        signals: Dict[str, Optional[str]] = {"vat": None, "heading_candidate": None}
        if source_file_path:
            try:
                signals = _ps.extract_all_signals(source_file_path)
            except Exception as _sig_exc:
                log.debug(
                    "_emit_draft_birth_skip_events: signal extract failed "
                    "(sales_doc=%s): %s", sd_id, _sig_exc,
                )

        has_signal = bool(signals.get("vat") or signals.get("heading_candidate"))
        event_name = (
            tl.EV_PROFORMA_DRAFT_CREATION_PENDING_RESOLUTION if has_signal
            else tl.EV_PROFORMA_DRAFT_CREATION_SKIPPED
        )
        next_action = (
            "vat_resolver_will_auto_bind_post_pr2" if signals.get("vat")
            else "heading_candidate_requires_corroboration" if signals.get("heading_candidate")
            else "operator_bind_client_name_manually"
        )

        try:
            tl.log_event(
                audit_path,
                event_name,
                trigger_source="proforma_draft_sync",
                actor=operator or "system",
                detail={
                    "batch_id":         batch_id,
                    "sales_doc_id":     sd_id,
                    "sales_doc_no":     sales_doc_no,
                    "source_file_path": source_file_path,
                    "reason":           "client_name_unresolved",
                    "lines_count":      info["lines_count"],
                    "value":            round(info["value"], 2),
                    "currency":         info["currency"],
                    "resolver_signals_seen": signals,
                    "resolver_passes_attempted": [
                        "packing_row",
                        "sales_doc",
                        "shipment_doc_contractor",
                        "filename",
                        "preamble",
                    ],
                    "next_action":      next_action,
                },
            )
            if has_signal:
                pending += 1
            else:
                skipped += 1
        except Exception as _emit_exc:
            log.debug(
                "_emit_draft_birth_skip_events: log_event failed (sales_doc=%s): %s",
                sd_id, _emit_exc,
            )

    return pending, skipped


# ── Main entry point ──────────────────────────────────────────────────────────

def sync_draft_from_packing_upload(
    batch_id:       str,
    operator:       str,
    db_path:        Path,
    audit_path:     Optional[Path] = None,
    master_db_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Auto-create/sync proforma drafts from packing upload.

    ``master_db_path`` — path to master_data.sqlite.  When provided, HS code
    resolution is attempted for every line (priority: product_local.hs_code_override
    → invoice_lines.hs_code).  Omitting it disables HS enrichment (no error).

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

    # ── 1.6 Enrich lines with HS codes (best-effort, Phase 4) ────────────────
    # Priority: product_local.hs_code_override → invoice_lines.hs_code.
    # Lines that already carry hs_code are left unchanged.
    resolved_lines = _enrich_lines_with_hs(resolved_lines, master_db_path)

    # ── 2. Group by client_name ───────────────────────────────────────────────
    by_client: Dict[str, List[Dict[str, Any]]] = {}
    for ln in resolved_lines:
        cn = str(ln.get("client_name") or "").strip()
        if not cn:
            continue
        by_client.setdefault(cn, []).append(ln)

    # ── 2.5 Skip-visibility emit (PR 1 — observation only, no behaviour change) ───
    # For every sales_document_id whose lines were dropped above (empty
    # client_name on EVERY line), emit ONE timeline event so the silent-drop
    # class becomes auditable. Read-only preamble signals (VAT, heading
    # candidate) are recorded to enable future deterministic resolution.
    pending_count, skipped_count = _emit_draft_birth_skip_events(
        resolved_lines=resolved_lines,
        by_client=by_client,
        audit_path=audit_path,
        operator=operator,
        batch_id=batch_id,
    )

    result: Dict[str, Any] = {
        "batch_id":              batch_id,
        "clients_processed":     0,
        "created":               0,
        "synced":                0,
        "blocked":               0,
        "pending_resolution":    pending_count,
        "skipped_no_signal":     skipped_count,
        "designs_resolved":      resolution_summary["designs_resolved"],
        "designs_ambiguous":     resolution_summary["designs_ambiguous"],
        "designs_unresolved":    resolution_summary["designs_unresolved"],
    }

    # Birth/reset name_pl fallback + mapping advisory callables. Lazy imports
    # keep the service layer free of route/parser import cycles; both are
    # read-only (never write wFirma, never fabricate).
    from ..api.sales_packing_parser import generate_name_pl_if_sufficient
    from . import wfirma_db as _wfdb

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
                name_pl_lookup=ddb.get_product_description,
                desc_generate=generate_name_pl_if_sufficient,
                product_mapping_lookup=_wfdb.get_product,
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
                # Annotate lines with product descriptions (item_type, name_pl, etc.).
                # Best-effort: failures do NOT abort the sync.
                try:
                    pildb.enrich_draft_lines(
                        db_path, draft.id, operator, draft.updated_at,
                        lambda pc: ddb.get_product_description(pc),
                    )
                except Exception as _enrich_exc:
                    log.debug(
                        "[%s] proforma_draft_sync: enrich after create skipped: %s",
                        batch_id, _enrich_exc,
                    )

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
                        name_pl_lookup=ddb.get_product_description,
                        desc_generate=generate_name_pl_if_sufficient,
                        product_mapping_lookup=_wfdb.get_product,
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
                    # Annotate lines with product descriptions after reset.
                    try:
                        pildb.enrich_draft_lines(
                            db_path, updated.id, operator, updated.updated_at,
                            lambda pc: ddb.get_product_description(pc),
                        )
                    except Exception as _enrich_exc:
                        log.debug(
                            "[%s] proforma_draft_sync: enrich after sync skipped: %s",
                            batch_id, _enrich_exc,
                        )

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
