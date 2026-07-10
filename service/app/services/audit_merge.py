"""
audit_merge.py — preserve workflow overlay state across regenerations.

The PZ engine's `_write_audit()` produces a fresh audit dict containing
calculation/output data (rows, totals, verification, customs_declaration,
canonical_filenames, …). On its own that fresh write would clobber the
DHL/agency/Polish-desc/timeline overlay added on top of audit.json by
later workflow steps (clearance pipeline, DHL reply queueing, agency
package build, etc.).

This module provides one helper, ``merge_regenerated_audit()``, that
combines:

    PRESERVED keys  — workflow overlay added post-engine. Always taken from
                      the existing on-disk audit unless the regenerated
                      audit contains a non-empty value (i.e. the engine
                      ran a flow that legitimately resets the field).

    REGENERATED keys — engine outputs. Always taken from the freshly
                      regenerated audit. Existing values are dropped.

If no existing audit is present (first-time generation) the helper just
returns the regenerated dict.

Single point of truth — used by:
  - ``service.app.services.export_service._write_audit()`` (every PZ run)
  - ``service.app.tools.regenerate_stale_batches`` (CLI regenerate)
"""
from __future__ import annotations

from typing import Any, Dict, Iterable

# Workflow overlay fields written *after* the engine ran. These must
# survive regeneration so the DHL/agency timeline is not lost.
PRESERVED_KEYS: tuple = (
    # Polish customs description (DHL workflow)
    "polish_desc_filename",
    "polish_desc_path",
    "polish_desc_file_exists",
    # DSK transfer document (DHL workflow)
    "dsk_filename",
    "dsk_path",
    "dsk_file_exists",
    "dsk_received",
    "dsk_received_at",
    "dsk_source",
    # Clearance routing decision (set by clearance_decision pipeline)
    "clearance_decision",
    # DHL email correspondence + reply
    "dhl_email",
    "dhl_ticket",
    "dhl_reply_package",
    "dhl_reply_queue_id",
    # Agency clearance correspondence + reply
    "agency_reply_package",
    "agency_queue_id",
    # Email evidence layer (Email Evidence V2)
    "email_evidence",
    "email_scan_results",
    "email_ingestion",
    "email_timeline",
    # Operator overlays
    "operator_overrides",       # never clobber; engine does not know about them
    "broker_followup_drafts",   # broker email drafts for blocked-batch reconciliation
    # ── Shipment-scoped customs description corrections (G3, 2026-07-10) ──
    # Written ONLY by the action-proposals approve route (scope="shipment");
    # read by customs_desc_checker.apply_description_corrections and
    # description_engine.resolve_product_description_for_customs (priority (a),
    # above product_descriptions source='manual'). The engine never writes this
    # key, so before this entry EVERY full re-process silently dropped all
    # approved shipment corrections (governance audit gap G3). Deliberately
    # batch-local — durable cross-shipment corrections are a separate authority
    # (scope="global_mapping" → description_mappings table) and must NOT be
    # merged into this overlay.
    "description_corrections",
    "action_proposals",
    "queued_replies",
    "sent_replies",
    "manual_status_flags",
    "tracking_overrides",
    "operator_notes",
    # Tracking & delivery state (set by tracking pipeline)
    "tracking",
    "tracking_terminal",
    "tracking_terminal_reason",
    "delivery_log",
    # Workflow checkpoints
    "pz_confirmed",
    "pz_confirmed_at",
    "recheck",
    # WorkDrive sync state
    "workdrive_synced",
    "workdrive_batch_folder",
    "workdrive_batch_folder_id",
    "workdrive_pdf_resource_id",
    "workdrive_xlsx_resource_id",
    "workdrive_sync_root",
    "workdrive_sync_error",
    "workdrive_upload",
    "workdrive_direct_upload",
    "workdrive_upload_status",
    # ── PZ engine authority sidecar (Bridge Persistence, 2026-05-21) ──
    # PR #269 invoice-position authority feeds the Global PZ engine bridge
    # in pz_import_processor._try_invoice_from_authority_rows. The engine
    # legitimately overwrites `audit.rows` on every /process run with its
    # own per-row pipeline output, but the bridge needs the original
    # invoice-position rows to survive — they're written to dedicated keys
    # here so REGENERATED_KEYS does not erase them.
    "_pz_engine_authority_rows",
    "_pz_engine_authority_meta",
    # ── Advisory image-only invoice proposal (vision_extractor, 2026-06-17) ──
    # run_image_only_invoice_extraction writes an operator-confirmable
    # vision_invoice proposal (supplier / FOB / line items) when the engine
    # could not parse an image-only invoice. The engine never writes this key,
    # so it must be preserved across regeneration — including a sticky
    # operator_confirmed=true once the operator accepts the proposal.
    "vision_invoice",
    # ── wFirma PZ export authority pointer (#570-class fix, 2026-06-18) ──
    # When a PZ is created live in wFirma, global_pz_push writes the booked-PZ
    # reference (wfirma_pz_doc_id, wfirma_pz_fullnumber, pz_source, pz_created_at,
    # pz_mapped_at) into audit.wfirma_export. The engine never writes this key, so
    # without preservation every subsequent Run PZ regeneration wipes the pointer
    # to null — the canonical link to the booked document is lost from audit.json
    # and survives only in the timeline (recoverable via
    # audit_persist.reconcile_from_timeline, but that is a manual one-shot, not an
    # automatic read-path recovery). Observed on AWB 2315714531 / PZ 4/6/2026
    # (doc_id 189364835): four post-correction regenerations left wfirma_export
    # null. Preserve it so a regen can never silently drop accounting authority.
    "wfirma_export",
)

# Engine outputs — always replaced by the fresh regeneration.
# Listed for documentation; merge helper uses PRESERVED_KEYS exclusively
# (anything not preserved comes from the regen).
REGENERATED_KEYS: tuple = (
    "rows",
    "totals",
    "verification",
    "customs_declaration",
    "zc429",
    "nbp",
    "notes",
    "files",                # PZ PDF / XLSX file refs
    "audit_score",
    "audit_status",
    "amendment_flags",
    "failed_checks",
    "corrections_log",
    "correction_report",
    "invoice_totals",
    "settlement_mode",
    "engine_version",
    "row_schema_version",
    "file_metadata",
    "canonical_filenames",
    "structured_checks",
    "exporter_check",
    "invoice_reference_check",
    "cif_reconciliation",
    "blocked_phrase_check",
    "learning_traces",
    "audit_generation_status",
    "audit_generation_error",
    "correction_generation_error",
    "timestamp",
    "status",
)


def _is_meaningful(value: Any) -> bool:
    """Return True when ``value`` is something other than the engine's
    'unset' placeholder (None / empty dict / empty list / empty string).
    The merge prefers the existing overlay UNLESS the engine wrote a
    meaningful value, so that a regen does not silently downgrade state.
    """
    if value is None:
        return False
    if isinstance(value, (dict, list, str)) and len(value) == 0:
        return False
    return True


def merge_regenerated_audit(
    existing:    Dict[str, Any],
    regenerated: Dict[str, Any],
    *,
    preserve_keys: Iterable[str] = PRESERVED_KEYS,
) -> Dict[str, Any]:
    """Merge a freshly-regenerated audit dict with the existing on-disk
    audit, preserving the workflow overlay.

    Rules:
        1. For every key in ``preserve_keys``: if the existing audit has a
           meaningful value AND the regen did NOT write a meaningful one,
           use the existing value. The rule is ASYMMETRIC — the existing
           overlay only wins when the regen value is not meaningful; a
           meaningful regen value always wins (so a flow that legitimately
           resets the field is never blocked). Regen also wins on tie.
        2. The regenerated ``timeline`` is preserved by extension: if the
           regen produced new timeline events, they are appended to the
           existing list (deduplicated by `(ts, event)`).
        3. Every other key — including all engine outputs — comes from
           the regen.
    """
    if not isinstance(existing, dict) or not existing:
        return dict(regenerated)
    if not isinstance(regenerated, dict):
        return dict(existing)

    merged = dict(regenerated)

    # ── Preserved overlay fields ────────────────────────────────────────
    for key in preserve_keys:
        ex_val  = existing.get(key)
        rg_val  = regenerated.get(key)
        if _is_meaningful(ex_val) and not _is_meaningful(rg_val):
            merged[key] = ex_val
        # else: regen value wins (whether None, empty, or meaningful)

    # ── Timeline — append rather than overwrite ─────────────────────────
    ex_tl = existing.get("timeline") or []
    rg_tl = regenerated.get("timeline") or []
    if isinstance(ex_tl, list) and isinstance(rg_tl, list):
        seen = set()
        out  = []
        for ev in list(ex_tl) + list(rg_tl):
            if not isinstance(ev, dict):
                continue
            key = (ev.get("ts") or ev.get("timestamp"), ev.get("event"))
            if key in seen:
                continue
            seen.add(key)
            out.append(ev)
        merged["timeline"] = out

    # ── Inputs sub-dict — preserve AWB filename + non-engine extras ────
    ex_inputs = existing.get("inputs") or {}
    rg_inputs = regenerated.get("inputs") or {}
    if isinstance(ex_inputs, dict) and isinstance(rg_inputs, dict):
        merged_inputs = dict(rg_inputs)
        # Preserve operator-supplied / upload-time keys not produced by the engine
        for k in ("awb", "uploaded_at", "uploaded_by"):
            if k in ex_inputs and not _is_meaningful(rg_inputs.get(k)):
                merged_inputs[k] = ex_inputs[k]
        merged["inputs"] = merged_inputs

    return merged
