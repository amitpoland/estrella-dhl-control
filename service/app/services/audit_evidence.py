"""
audit_evidence.py — Read-time effective PZ/customs evidence helper.

Why
---
``audit.json`` on disk often lags behind the operator's actual progress.
Examples we hit in production:

  • ``status="failed"`` from a verification block, but the operator later
    cleared the failure via /cn-decision/accept-sad (existing
    ``routes_wfirma._compute_effective_pz_status`` already handles this).
  • wFirma PZ created live (doc id known), but ``wfirma_export``
    write back never landed in audit.json — only the timeline event
    ``wfirma_pz_created`` carries the proof.
  • Customs cleared via DHL self-clearance or DSK, but the corresponding
    ``audit.dsk_received`` flag was not stamped.

Without normalization, downstream gates (mark-direct-dispatch,
seed-batch auto-target) report false negatives: "no PZ evidence" even
though the wFirma document exists and is verified.

What
----
``effective_pz_evidence(audit)`` walks every reliable signal a PZ-complete
shipment can leave and returns a structured result. Callers decide what
to do with it; this module never mutates audit.json.

Reliable signals (any one is sufficient — they're all hard to fake)
-------------------------------------------------------------------
  PZ-side:
    1. ``audit.wfirma_export.wfirma_pz_doc_id`` non-empty
    2. timeline event ``wfirma_pz_created`` with ``detail.wfirma_pz_doc_id``
    3. ``_compute_effective_pz_status`` returns a PZ-done state
       (operator-cleared verification path)
  Customs-side:
    4. ``audit.customs_declaration.mrn`` non-empty
    5. ``audit.inputs.zc429`` present (SAD file uploaded)
    6. existing post-DHL flags: ``dhl_email.received``,
       ``dsk_received``, ``sad_received``, ``agency_sad_received``,
       ``clearance_status`` ∈ cleared-set.

If none fire, the helper reports ``has_evidence=False`` and lists which
signals were checked. Strict rejection is preserved.
"""
from __future__ import annotations

from typing import Any, Dict, List


_CLEARANCE_STATUSES_OK = frozenset({
    "dhl_email_received", "dsk_generated", "agency_sad_received",
    "agency_pzc_received", "customs_cleared",
})

# Signals listed in the order operators expect them to appear in the audit;
# UI surfaces this list verbatim so the operator can see *why* the route
# accepted (or rejected) the batch.
_ALL_SIGNAL_KEYS = [
    "wfirma_export.wfirma_pz_doc_id",
    "timeline:wfirma_pz_created",
    "effective_pz_status_done",
    "customs_declaration.mrn",
    "inputs.zc429",
    "dhl_email.received",
    "dsk_received",
    "sad_received",
    "agency_sad_received",
    "clearance_status",
]


def _wfirma_pz_doc_id_from_export(audit: Dict[str, Any]) -> str:
    return ((audit.get("wfirma_export") or {}).get("wfirma_pz_doc_id") or "").strip()


def _wfirma_pz_doc_id_from_timeline(audit: Dict[str, Any]) -> str:
    """Walk audit.timeline for a wfirma_pz_created event with a doc id.

    Timeline shape (see app.core.timeline.log_event):
        {ts, event, trigger_source, actor, detail}
    """
    timeline = audit.get("timeline") or []
    if not isinstance(timeline, list):
        return ""
    for entry in timeline:
        if not isinstance(entry, dict):
            continue
        if entry.get("event") != "wfirma_pz_created":
            continue
        detail = entry.get("detail") or {}
        if not isinstance(detail, dict):
            continue
        doc_id = (detail.get("wfirma_pz_doc_id") or "").strip()
        if doc_id:
            return doc_id
    return ""


def _effective_pz_status_done(audit: Dict[str, Any]) -> bool:
    """Re-use the existing operator-cleared normalization. Imported lazily
    to avoid a circular import (routes_wfirma imports services modules)."""
    try:
        from ..api.routes_wfirma import _compute_effective_pz_status, _PZ_DONE
    except Exception:
        return False
    try:
        eff, _ = _compute_effective_pz_status(audit)
    except Exception:
        return False
    return eff in _PZ_DONE


def effective_pz_evidence(audit: Dict[str, Any]) -> Dict[str, Any]:
    """
    Return an evidence summary computed read-time from the *audit* dict.

    Result shape::

        {
          "has_evidence":     bool,
          "wfirma_pz_doc_id": str,    # canonical doc id if any signal carried one, else ""
          "signals":          [str],  # ordered list of signal keys that fired
          "missing":          [str],  # signal keys that did not fire (informational)
        }

    The function is pure — it does not write to disk and does not touch
    any database.
    """
    if not isinstance(audit, dict):
        return {"has_evidence": False, "wfirma_pz_doc_id": "",
                "signals": [], "missing": list(_ALL_SIGNAL_KEYS)}

    signals: List[str] = []

    # ── PZ-side signals ────────────────────────────────────────────────
    doc_export   = _wfirma_pz_doc_id_from_export(audit)
    if doc_export:
        signals.append("wfirma_export.wfirma_pz_doc_id")

    doc_timeline = _wfirma_pz_doc_id_from_timeline(audit)
    if doc_timeline:
        signals.append("timeline:wfirma_pz_created")

    if _effective_pz_status_done(audit):
        signals.append("effective_pz_status_done")

    # ── Customs-side signals ───────────────────────────────────────────
    mrn = ((audit.get("customs_declaration") or {}).get("mrn") or "").strip()
    if mrn:
        signals.append("customs_declaration.mrn")

    zc429 = (audit.get("inputs") or {}).get("zc429")
    if zc429:
        signals.append("inputs.zc429")

    if bool((audit.get("dhl_email") or {}).get("received")):
        signals.append("dhl_email.received")
    if audit.get("dsk_received"):
        signals.append("dsk_received")
    if audit.get("sad_received"):
        signals.append("sad_received")
    if audit.get("agency_sad_received"):
        signals.append("agency_sad_received")
    cs = (audit.get("clearance_status") or "").strip()
    if cs in _CLEARANCE_STATUSES_OK:
        signals.append("clearance_status")

    canonical_doc_id = doc_export or doc_timeline
    return {
        "has_evidence":      bool(signals),
        "wfirma_pz_doc_id":  canonical_doc_id,
        "signals":           signals,
        "missing":           [s for s in _ALL_SIGNAL_KEYS if s not in signals],
    }
