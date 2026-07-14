"""
timeline_milestones.py — Canonical workflow-milestone read-model (Wave 4; Slice 2A 7-state).

PURE PROJECTION. Given a batch ``audit`` dict, compute each workflow milestone's
``{key, label, done, state, ts, source}`` (``blocked_reason`` when blocked). This
is the single authoritative mapping the V2 Shipment Detail Timeline consumes — it
reconciles the wireframe-era frontend milestone keys against the REAL emitted
timeline events (core/timeline.py EV_* strings, appended to ``audit["timeline"]``
as ``{"ts","event",...}``) and, for milestones whose completion truth lives in an
AUDIT FIELD rather than a timeline event, the authoritative field.

No new database, no duplicate audit store, no frontend inference: this is a
read-time projection over the existing ``audit.timeline`` + ``audit`` fields,
injected into the batch-detail response by routes_dashboard.

STATE MODEL (Slice 2A) — every milestone carries a ``state`` ∈:
  * ``completed``      — an accepted event is present OR the audit-field predicate
                         holds. ``done`` remains ``True`` iff state == completed
                         (back-compat with the V2 canonical render + counter).
  * ``not_applicable`` — the milestone belongs to the OTHER clearance lane
                         (``clearance_decision.clearance_path`` is definitively
                         self vs agency and this milestone's lane excludes it).
                         The ONLY source of not_applicable — never guessed. A
                         routing_pending / unknown path is treated as applicable.
  * ``available``      — the single frontier milestone (first applicable,
                         not-completed, not-skipped) whose precondition gate holds.
  * ``blocked``        — the frontier milestone whose real precondition gate fails;
                         ``blocked_reason`` carries the operator-readable cause.
                         Advisory display only (Lesson N) — never a fiscal gate.
  * ``skipped``        — an OPTIONAL, applicable, not-completed milestone that a
                         LATER applicable milestone has already passed (positive
                         bypass evidence). Absent that evidence → not_started.
  * ``failed``         — a recorded failure for this milestone key
                         (``audit["milestone_failures"]``). Evidence-only; inert
                         without evidence — never fabricated.
  * ``not_started``    — genuinely waiting, no evidence either way (safe default).

Reconciliation evidence (Wave-4 authority trace) — every accepted event string
below is a REAL emitter (verified against core/timeline.py EV_* + literal
``tl.log_event`` call sites). Milestones whose truth is a field carry an
audit-field predicate; strings with zero emitters were removed so the read-model
never advertises coverage it does not have.

  * batch/invoice/awb  → events ``batch_created`` / ``invoice_uploaded`` /
                   ``awb_uploaded`` (routes_upload.py); field fallback on the
                   ``inputs`` block so the first milestones survive the 200-event
                   timeline truncation (core/timeline.py _MAX_EVENTS).
  * dhl precheck → event ``dhl_precheck_completed`` (EV_DHL_PRECHECK_COMPLETED),
                   field fallback ``audit.dhl_precheck`` (routes_upload.py stores
                   the precheck result durably before the event is logged).
  * dhl email    → event ``dhl_email_received`` (EV_DHL_EMAIL_RECEIVED), field
                   fallback ``audit.dhl_email.received`` (scan-inbox and
                   /mark-email-received set the field alongside the event).
  * polish desc  → event ``description_ready`` (EV_DESCRIPTION_READY), field
                   fallback ``audit.polish_desc_filename`` (set by BOTH
                   /generate-description and /generate-customs-package). The field
                   fallback backfills historical shipments generated before the
                   combined endpoint learned to emit the event (Slice 2A.1).
  * reply pkg    → events ``dhl_reply_package_auto_built`` /
                   ``dhl_self_clearance_reply_auto_built`` /
                   ``agency_package_auto_built``, field fallback
                   ``audit.reply_package`` / ``audit.agency_reply_package.status``.
                   ``dsk_generated`` is NOT accepted here — a DSK existing does not
                   prove a reply package was built (that would infer an earlier /
                   parallel milestone from a later one). Real evidence is the
                   ``reply_package`` field written by /dsk/email-package.
  * dsk          → event ``dsk_generated`` (EV_DSK_GENERATED), field fallback
                   ``audit.dsk_filename``. Lane: DHL self-clearance only (the
                   agency lane builds an agency package instead) — but a genuinely
                   generated DSK always reads ``completed`` regardless of lane,
                   since completion is evaluated before applicability.
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

from typing import Any, Callable, Dict, FrozenSet, List, Optional, Tuple

from .clearance_path_alias import (
    normalize_path,
    PATH_AGENCY_CLEARANCE,
    PATH_DHL_SELF_CLEARANCE,
)

# ── Milestone state vocabulary ───────────────────────────────────────────────
ST_COMPLETED      = "completed"
ST_AVAILABLE      = "available"
ST_BLOCKED        = "blocked"
ST_NOT_STARTED    = "not_started"
ST_SKIPPED        = "skipped"
ST_NOT_APPLICABLE = "not_applicable"
ST_FAILED         = "failed"

ALL_STATES: FrozenSet[str] = frozenset({
    ST_COMPLETED, ST_AVAILABLE, ST_BLOCKED, ST_NOT_STARTED,
    ST_SKIPPED, ST_NOT_APPLICABLE, ST_FAILED,
})

# Lane sets — a milestone is not_applicable only when the path is DEFINITIVELY
# self or agency and the path is not in the milestone's lanes.
_ALL_LANES: FrozenSet[str] = frozenset({PATH_DHL_SELF_CLEARANCE, PATH_AGENCY_CLEARANCE})
_SELF_ONLY: FrozenSet[str] = frozenset({PATH_DHL_SELF_CLEARANCE})


def _cd(audit: Dict[str, Any]) -> Dict[str, Any]:
    return audit.get("customs_declaration") or {}


def _f_batch_created(a: Dict[str, Any]) -> bool:
    # Any persisted audit means the shipment was created; survives event truncation.
    return bool(a.get("batch_id"))


def _f_invoice_uploaded(a: Dict[str, Any]) -> bool:
    return bool((a.get("inputs") or {}).get("invoices"))


def _f_awb_uploaded(a: Dict[str, Any]) -> bool:
    return bool((a.get("inputs") or {}).get("awb")) or bool(a.get("awb"))


def _f_precheck_completed(a: Dict[str, Any]) -> bool:
    # routes_upload._run_dhl_precheck writes audit["dhl_precheck"] durably before
    # the EV_DHL_PRECHECK_COMPLETED event — the field backfills the milestone when
    # the event has been truncated or the precheck ran on an older code path.
    return bool(a.get("dhl_precheck"))


def _f_dhl_email_received(a: Dict[str, Any]) -> bool:
    # scan-inbox and /mark-email-received both set dhl_email.received=True (and
    # emit dhl_email_received); the field backfills the milestone honestly when
    # the event has been truncated or set on an older path.
    return bool((a.get("dhl_email") or {}).get("received"))


def _f_polish_desc(a: Dict[str, Any]) -> bool:
    # Both /generate-description and /generate-customs-package set this field.
    return bool(a.get("polish_desc_filename"))


def _f_reply_package(a: Dict[str, Any]) -> bool:
    # /dsk/email-package writes reply_package; the agency auto-build writes
    # agency_reply_package.status. A DSK existing is deliberately NOT evidence.
    return bool(a.get("reply_package")) or bool((a.get("agency_reply_package") or {}).get("status"))


def _f_dsk(a: Dict[str, Any]) -> bool:
    return bool(a.get("dsk_filename"))


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


# ── Precondition gates ───────────────────────────────────────────────────────
# A gate is consulted ONLY for the frontier milestone (the next actionable step).
# It returns (ok, reason): ok=True → available; ok=False → blocked with reason.
# Gates mirror the REAL backend guards so the timeline's advisory hint matches
# what the command would actually enforce (Lesson N — advisory, never a fiscal gate).

def _email_received(a: Dict[str, Any], done: Dict[str, bool]) -> bool:
    return bool(done.get("dhl_email_received")) or bool((a.get("dhl_email") or {}).get("received"))


def _gate_email_required(a: Dict[str, Any], done: Dict[str, bool]) -> Tuple[bool, str]:
    if _email_received(a, done):
        return True, ""
    return False, "DHL clearance email has not been received yet."


def _gate_description(a: Dict[str, Any], done: Dict[str, bool]) -> Tuple[bool, str]:
    # On the agency path the DHL-email guard is advisory (generate_description
    # runs in advisory mode) — do not block. On self-clearance the email is the
    # real precondition.
    if normalize_path((a.get("clearance_decision") or {}).get("clearance_path")) == PATH_AGENCY_CLEARANCE:
        return True, ""
    return _gate_email_required(a, done)


def _gate_reply_package(a: Dict[str, Any], done: Dict[str, bool]) -> Tuple[bool, str]:
    if a.get("polish_desc_filename") or a.get("dsk_filename") \
       or done.get("polish_description_generated") or done.get("dsk_generated"):
        return True, ""
    return False, "Generate the Polish description or DSK before building the reply package."


def _gate_reply_sent(a: Dict[str, Any], done: Dict[str, bool]) -> Tuple[bool, str]:
    if _f_reply_package(a) or done.get("reply_package_generated"):
        return True, ""
    return False, "Build the reply package before sending the reply."


_GATES: Dict[str, Callable[[Dict[str, Any], Dict[str, bool]], Tuple[bool, str]]] = {
    "polish_description_generated": _gate_description,
    "dsk_generated":                _gate_email_required,
    "reply_package_generated":      _gate_reply_package,
    "reply_sent":                   _gate_reply_sent,
}


def _failed(a: Dict[str, Any], key: str) -> bool:
    """Evidence-only failure detection. Inert unless audit records a failure for
    ``key`` under ``milestone_failures`` (dict keyed by milestone, or a list of
    keys). Never fabricated from the absence of a success event."""
    errs = a.get("milestone_failures")
    if isinstance(errs, dict):
        return bool(errs.get(key))
    if isinstance(errs, (list, tuple, set)):
        return key in errs
    return False


# (key, label, accepted event strings, optional audit-field predicate, lanes, optional)
# ``key`` is the STABLE milestone identity the frontend renders; it stays the
# same even though the emitted event string differs. Every event string here is
# a verified emitter — no defensive dead stubs. ``lanes`` gates not_applicable;
# ``optional`` gates skipped.
_MILESTONES: List[Tuple[str, str, Tuple[str, ...], Optional[Callable[[Dict[str, Any]], bool]], FrozenSet[str], bool]] = [
    ("batch_created",                "Shipment created",                ("batch_created",), _f_batch_created, _ALL_LANES, False),
    ("invoice_uploaded",             "Invoice uploaded",                ("invoice_uploaded",), _f_invoice_uploaded, _ALL_LANES, False),
    ("awb_uploaded",                 "AWB uploaded",                    ("awb_uploaded",), _f_awb_uploaded, _ALL_LANES, False),
    ("dhl_precheck_completed",       "DHL pre-check completed",         ("dhl_precheck_completed",), _f_precheck_completed, _ALL_LANES, True),
    ("dhl_email_received",           "DHL clearance email received",    ("dhl_email_received",), _f_dhl_email_received, _ALL_LANES, False),
    ("polish_description_generated", "Polish description generated",    ("description_ready",), _f_polish_desc, _ALL_LANES, False),
    ("dsk_generated",                "DSK generated",                   ("dsk_generated",), _f_dsk, _SELF_ONLY, False),
    ("reply_package_generated",      "Reply package prepared",          ("dhl_reply_package_auto_built", "dhl_self_clearance_reply_auto_built", "agency_package_auto_built"), _f_reply_package, _ALL_LANES, False),
    ("reply_sent",                   "Reply sent to DHL / agency",      ("reply_approved", "dsk_transfer_sent", "agency_email_sent"), None, _ALL_LANES, False),
    ("sad_imported",                 "SAD / ZC429 uploaded",            ("sad_uploaded", "zc429_received", "customs_docs_imported"), _f_sad_present, _ALL_LANES, False),
    ("customs_parsed",               "Customs values parsed",           ("agency_sad_parsed",), _f_customs_parsed, _ALL_LANES, False),
    ("verification_checks_passed",   "Verification checks passed",      (), _f_verification_passed, _ALL_LANES, False),
    ("pz_unlocked",                  "PZ unlocked",                     (), _f_pz_unlocked, _ALL_LANES, False),
    ("pz_created",                   "PZ generated",                    ("pz_generated",), None, _ALL_LANES, False),
    ("pz_confirmed",                 "PZ number confirmed",             ("wfirma_pz_created", "wfirma_pz_adopted"), _f_pz_confirmed, _ALL_LANES, False),
    ("wfirma_pz_created",            "PZ exported to wFirma",           ("wfirma_pz_created",), None, _ALL_LANES, False),
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

    Each entry: ``{key, label, done, state, ts, source}`` (plus ``blocked_reason``
    when ``state == "blocked"``). ``done`` is True iff ``state == "completed"``.
    ``ts`` is the earliest matching event timestamp (None when completion is
    field-derived only). ``source`` ∈ {'event', 'audit_field', None}. Pure
    projection over ``audit.timeline`` + ``audit`` fields — no I/O, no DB.
    """
    audit = audit or {}
    timeline = audit.get("timeline") or []
    by_name: Dict[str, List[dict]] = {}
    for e in timeline:
        if isinstance(e, dict):
            by_name.setdefault(str(e.get("event") or ""), []).append(e)

    path = normalize_path((audit.get("clearance_decision") or {}).get("clearance_path"))
    path_known = path in (PATH_DHL_SELF_CLEARANCE, PATH_AGENCY_CLEARANCE)

    n = len(_MILESTONES)
    completed: List[bool] = [False] * n
    ts_list: List[Optional[str]] = [None] * n
    src_list: List[Optional[str]] = [None] * n
    applicable: List[bool] = [True] * n

    # Pass 1 — completion + timestamp + applicability.
    for i, (key, label, names, pred, lanes, optional) in enumerate(_MILESTONES):
        ev_ts = _earliest_event_ts(by_name, names)
        field_done = bool(pred(audit)) if pred else False
        done_i = (ev_ts is not None) or field_done
        completed[i] = done_i
        ts_list[i] = ev_ts
        src_list[i] = "event" if ev_ts is not None else ("audit_field" if field_done else None)
        # Applicability: exclude ONLY when the path is definitively self/agency and
        # this milestone's lane excludes it. Completion is evaluated first below,
        # so a genuinely-completed milestone never reads not_applicable.
        if path_known and path not in lanes:
            applicable[i] = False

    done_by_key: Dict[str, bool] = {m[0]: completed[i] for i, m in enumerate(_MILESTONES)}

    # Pass 2 — skipped: an optional, applicable, not-completed milestone that a
    # LATER applicable milestone has already passed (positive bypass evidence).
    skipped: List[bool] = [False] * n
    for i in range(n):
        if completed[i] or not applicable[i]:
            continue
        if _MILESTONES[i][5] and any(applicable[j] and completed[j] for j in range(i + 1, n)):
            skipped[i] = True

    # Pass 3 — frontier: first applicable, not-completed, not-skipped milestone.
    frontier: Optional[int] = None
    for i in range(n):
        if applicable[i] and not completed[i] and not skipped[i]:
            frontier = i
            break

    # Pass 4 — assign a single truthful state per milestone.
    out: List[Dict[str, Any]] = []
    for i, (key, label, names, pred, lanes, optional) in enumerate(_MILESTONES):
        blocked_reason: Optional[str] = None
        if completed[i]:
            state = ST_COMPLETED
        elif not applicable[i]:
            state = ST_NOT_APPLICABLE
        elif _failed(audit, key):
            state = ST_FAILED
        elif skipped[i]:
            state = ST_SKIPPED
        elif i == frontier:
            gate = _GATES.get(key)
            if gate is None:
                state = ST_AVAILABLE
            else:
                ok, reason = gate(audit, done_by_key)
                if ok:
                    state = ST_AVAILABLE
                else:
                    state = ST_BLOCKED
                    blocked_reason = reason
        else:
            state = ST_NOT_STARTED

        entry: Dict[str, Any] = {
            "key":    key,
            "label":  label,
            "done":   state == ST_COMPLETED,
            "state":  state,
            "ts":     ts_list[i],
            "source": src_list[i],
        }
        if blocked_reason:
            entry["blocked_reason"] = blocked_reason
        out.append(entry)
    return out
