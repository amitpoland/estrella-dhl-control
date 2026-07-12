"""
timeline_milestones.py — Canonical workflow-milestone read-model (Wave 4).

PURE PROJECTION. Given a batch ``audit`` dict, compute each workflow milestone's
``{key, label, done, ts, source}``. This is the single authoritative mapping the
V2 Shipment Detail Timeline consumes — it reconciles the wireframe-era frontend
milestone keys against the REAL emitted timeline events (core/timeline.py EV_*
strings, appended to ``audit["timeline"]`` as ``{"ts","event",...}``) and, for
the milestones whose completion truth lives in an AUDIT FIELD rather than a
timeline event (verification, PZ unlocked, PZ confirmed), the authoritative
field.

No new database, no duplicate audit store, no frontend inference: this is a
read-time projection over the existing ``audit.timeline`` + ``audit`` fields,
injected into the batch-detail response by routes_dashboard.

Reconciliation evidence (Wave-4 authority trace) — every accepted event string
below is a REAL emitter (verified against core/timeline.py EV_* + literal
``tl.log_event`` call sites). Milestones whose truth is a field carry an
audit-field predicate; strings with zero emitters were removed so the read-model
never advertises coverage it does not have.

  * batch/invoice/awb  → events ``batch_created`` / ``invoice_uploaded`` /
                   ``awb_uploaded`` (routes_upload.py); field fallback on the
                   ``inputs`` block so the first milestones survive the 200-event
                   timeline truncation (core/timeline.py _MAX_EVENTS).
  * polish desc  → event ``description_ready`` (EV_DESCRIPTION_READY).
  * reply pkg    → ``dsk_generated`` / ``dhl_reply_package_auto_built`` /
                   ``dhl_self_clearance_reply_auto_built`` / ``agency_package_auto_built``.
  * reply sent   → ``reply_approved`` (EV_REPLY_APPROVED) / ``dsk_transfer_sent``
                   (DHL path) / ``agency_email_sent`` (EV_AGENCY_EMAIL_SENT — the
                   agency/ACS path peer; dhl_readiness maps it to agency_forwarded).
  * sad imported → ``sad_uploaded`` (EV_SAD_UPLOADED) / ``zc429_received`` /
                   ``customs_docs_imported`` (import received, PRE-parse), or the
                   ``audit.sad_imported`` field / mrn / inputs.zc429.
  * customs      → parse-only: event ``agency_sad_parsed`` OR the parsed fields
                   ``audit.customs_declaration.mrn`` / ``duty_a00_pln``.
                   ``customs_docs_imported`` is deliberately NOT accepted here —
                   it fires when a SAD PDF lands on disk, BEFORE any MRN/duty is
                   extracted (sad_importer.py), so it would falsely mark "values
                   parsed" done on an un-parsed upload.
  * verification → NO event; the agency decision is the final gate when present
                   (``audit.agency_sad_decision.safe_to_run_pz``); otherwise
                   ``audit.verification.cif_match``. A recorded BLOCK
                   (safe_to_run_pz is False) is NOT "verified".
  * pz unlocked  → NO reliable event (``agency_sad_decision`` fires for a BLOCK
                   too). Truth is ``agency_sad_decision.safe_to_run_pz is True``
                   (agency path) OR ``clearance_status == "pz_unlocked"`` (the
                   self-clearance / state-engine path never sets an agency
                   decision — dhl_clearance_state_engine.STATE_PZ_UNLOCKED).
  * pz generated → event ``pz_generated`` (EV_PZ_GENERATED).
  * pz confirmed → ``wfirma_pz_created`` / ``wfirma_pz_adopted`` events, or
                   ``audit.pz_confirmed`` / ``audit.doc_no`` (the /confirm-pz
                   endpoint sets the fields but emits no event).
  * pz exported  → event ``wfirma_pz_created`` (EV_WFIRMA_PZ_CREATED).
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple


def _cd(audit: Dict[str, Any]) -> Dict[str, Any]:
    return audit.get("customs_declaration") or {}


def _f_batch_created(a: Dict[str, Any]) -> bool:
    # Any persisted audit means the shipment was created; survives event truncation.
    return bool(a.get("batch_id"))


def _f_invoice_uploaded(a: Dict[str, Any]) -> bool:
    return bool((a.get("inputs") or {}).get("invoices"))


def _f_awb_uploaded(a: Dict[str, Any]) -> bool:
    return bool((a.get("inputs") or {}).get("awb")) or bool(a.get("awb"))


def _f_sad_present(a: Dict[str, Any]) -> bool:
    return (
        bool(_cd(a).get("mrn"))
        or bool((a.get("inputs") or {}).get("zc429"))
        or bool(a.get("zc429"))
        or bool(a.get("sad_imported"))
    )


def _f_customs_parsed(a: Dict[str, Any]) -> bool:
    cd = _cd(a)
    return bool(cd.get("mrn")) or cd.get("duty_a00_pln") is not None


def _f_verification_passed(a: Dict[str, Any]) -> bool:
    # The agency SAD decision is the FINAL gate whenever it has been recorded:
    # a BLOCK (safe_to_run_pz is False) must not read as "verified", even if the
    # CIF numbers happened to match. Only fall through to cif_match when no
    # agency decision exists (e.g. the self-clearance path).
    dec = a.get("agency_sad_decision") or {}
    if dec.get("safe_to_run_pz") is not None:
        return dec.get("safe_to_run_pz") is True
    return (a.get("verification") or {}).get("cif_match") is True


def _f_pz_unlocked(a: Dict[str, Any]) -> bool:
    if (a.get("agency_sad_decision") or {}).get("safe_to_run_pz") is True:
        return True
    # Self-clearance / state-engine path never records an agency decision.
    return str(a.get("clearance_status") or "") == "pz_unlocked"


def _f_pz_confirmed(a: Dict[str, Any]) -> bool:
    return bool(a.get("pz_confirmed")) or bool(a.get("doc_no"))


# (key, label, accepted event strings, optional audit-field predicate)
# ``key`` is the STABLE milestone identity the frontend renders; it stays the
# same even though the emitted event string differs. Every event string here is
# a verified emitter — no defensive dead stubs.
_MILESTONES: List[Tuple[str, str, Tuple[str, ...], Optional[Callable[[Dict[str, Any]], bool]]]] = [
    ("batch_created",                "Shipment created",                ("batch_created",), _f_batch_created),
    ("invoice_uploaded",             "Invoice uploaded",                ("invoice_uploaded",), _f_invoice_uploaded),
    ("awb_uploaded",                 "AWB uploaded",                    ("awb_uploaded",), _f_awb_uploaded),
    ("dhl_precheck_completed",       "DHL pre-check completed",         ("dhl_precheck_completed",), None),
    ("dhl_email_received",           "DHL clearance email received",    ("dhl_email_received",), None),
    ("polish_description_generated", "Polish description generated",    ("description_ready",), None),
    ("dsk_generated",                "DSK generated",                   ("dsk_generated",), None),
    ("reply_package_generated",      "Reply package prepared",          ("dsk_generated", "dhl_reply_package_auto_built", "dhl_self_clearance_reply_auto_built", "agency_package_auto_built"), None),
    ("reply_sent",                   "Reply sent to DHL / agency",      ("reply_approved", "dsk_transfer_sent", "agency_email_sent"), None),
    ("sad_imported",                 "SAD / ZC429 uploaded",            ("sad_uploaded", "zc429_received", "customs_docs_imported"), _f_sad_present),
    ("customs_parsed",               "Customs values parsed",           ("agency_sad_parsed",), _f_customs_parsed),
    ("verification_checks_passed",   "Verification checks passed",      (), _f_verification_passed),
    ("pz_unlocked",                  "PZ unlocked",                     (), _f_pz_unlocked),
    ("pz_created",                   "PZ generated",                    ("pz_generated",), None),
    ("pz_confirmed",                 "PZ number confirmed",             ("wfirma_pz_created", "wfirma_pz_adopted"), _f_pz_confirmed),
    ("wfirma_pz_created",            "PZ exported to wFirma",           ("wfirma_pz_created",), None),
]


def _earliest_event_ts(events_by_name: Dict[str, List[dict]], names: Tuple[str, ...]) -> Optional[str]:
    """The earliest ISO ``ts`` among any accepted event, or None if none present.

    Timeline ``ts`` values are ISO-8601 strings (core/timeline.log_event writes
    ``_now_iso()``), so a lexicographic ``<`` gives true chronological order.
    Non-string / malformed ts values are ignored rather than trusted.
    """
    best: Optional[str] = None
    for n in names:
        for e in events_by_name.get(n, []):
            raw = e.get("ts")
            if not isinstance(raw, str) or not raw:
                continue
            if best is None or raw < best:
                best = raw
    return best


def build_milestones(audit: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return the ordered canonical milestone list for a batch audit.

    Each entry: ``{key, label, done, ts, source}``. ``done`` is True if any
    accepted event is present OR the audit-field predicate holds. ``ts`` is the
    earliest matching event timestamp (None when completion is field-derived
    only). ``source`` ∈ {'event', 'audit_field', None}.
    """
    audit = audit or {}
    timeline = audit.get("timeline") or []
    by_name: Dict[str, List[dict]] = {}
    for e in timeline:
        if isinstance(e, dict):
            by_name.setdefault(str(e.get("event") or ""), []).append(e)

    out: List[Dict[str, Any]] = []
    for key, label, names, pred in _MILESTONES:
        ev_ts = _earliest_event_ts(by_name, names)
        field_done = bool(pred(audit)) if pred else False
        if ev_ts is not None:
            source = "event"
        elif field_done:
            source = "audit_field"
        else:
            source = None
        out.append({
            "key":    key,
            "label":  label,
            "done":   (ev_ts is not None) or field_done,
            "ts":     ev_ts,
            "source": source,
        })
    return out
