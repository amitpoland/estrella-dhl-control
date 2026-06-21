"""
operational_authority.py — Single backend authority for operational truth.

ATLAS P1 (WRONG-AUTHORITY) fix. Before this module, PZ status was derived in
three backend places (routes_dashboard._derive_pz_status,
routes_wfirma._compute_effective_pz_status) plus the frontend, and blocking
reasons were built in four places (batch_readiness, sales_linkage,
proforma-preview, dashboard wfirma-readiness) — so chips and buttons could
disagree about the same batch.

This module is the ONE place those are derived. It is a LEAF module: it imports
only settings + (lazily) warehouse_audit. It MUST NOT import batch_readiness,
sales_linkage, or routes_* (batch_readiness already imports sales_linkage, so a
higher home would create an import cycle).

Invariant: this consolidation changes WHERE truth is derived, never the truth
itself. The PZ-status value set (`complete | ready | locked | failed`) and every
readiness/blocking boolean are preserved byte-for-byte; only the reason TEXT is
unified. Parity is pinned by test_derive_pz_status.py +
test_closure_gate_boolean_parity.py + test_blocking_reason_authority_parity.py.
"""
from __future__ import annotations

from typing import Any, Dict, List

from ..core.config import settings

# Storage root for the on-disk SAD-presence fallback (mirrors routes_dashboard).
_OUTPUTS = settings.storage_root / "outputs"

# PZ statuses that indicate a completed engine run (shared with routes_wfirma._PZ_DONE).
PZ_DONE = {"success", "partial"}


# ── Status derivations (moved verbatim from routes_dashboard; canonical home) ──
# routes_dashboard re-imports these under their old private names, so its call
# sites are unchanged. Behaviour is identical — this is a relocation, not a
# rewrite. Do not "improve" the logic here without updating the parity tests.

def derive_status(a: Dict[str, Any]) -> str:
    """
    Derive status for old audit files that pre-date the `status` field.
    Priority: explicit field → infer from verification → infer from corrections_log.
    New business statuses: draft, ready, processing are passed through as-is.
    """
    stored = a.get("status")
    if stored == "failed":
        fc = a.get("failed_checks") or []
        pz_files_exist = bool(
            a.get("pz_output", {}).get("generated_at")
            or (a.get("files", {}).get("pdf") or {}).get("sha256")
        )
        if not fc and pz_files_exist:
            v = a.get("verification", {})
            hard_fails = [k for k, val in v.items() if not isinstance(val, list) and val is False]
            if hard_fails:
                return "blocked"
            corrections = a.get("corrections_log", [])
            has_gaps = any(c.startswith("[VERIFY-GAP]") for c in corrections)
            if has_gaps:
                return "partial"
            if v:
                return "success"
            return "partial"
    if stored in ("draft", "ready", "processing", "in_preparation",
                  "success", "partial", "blocked", "failed"):
        return stored
    if stored and stored != "unknown":
        return stored
    v = a.get("verification", {})
    hard_fails = [k for k, val in v.items() if not isinstance(val, list) and val is False]
    if hard_fails:
        return "blocked"
    corrections = a.get("corrections_log", [])
    has_gaps = any(c.startswith("[VERIFY-GAP]") for c in corrections)
    if has_gaps:
        return "partial"
    if v:
        return "success"
    return "unknown"


def derive_sad_status(a: Dict[str, Any]) -> str:
    """Derive SAD pipeline status for list column. 'uploaded_parsed'|'uploaded'|'missing'."""
    inp = a.get("inputs", {})
    fd  = a.get("files_detail", {})
    sf  = (fd or {}).get("source_files", {})

    has_sad = bool(
        (sf.get("sad") or [])
        or inp.get("zc429_file") or inp.get("sad_file") or inp.get("zc429")
        or a.get("zc429", {}).get("mrn")
        or a.get("customs_declaration", {}).get("mrn")
    )
    if not has_sad:
        batch_id = a.get("batch_id", "")
        if batch_id:
            sad_dir = _OUTPUTS / batch_id / "source" / "sad"
            if sad_dir.exists() and any(sad_dir.iterdir()):
                has_sad = True

    if not has_sad:
        return "missing"

    cd = a.get("customs_declaration", {})
    if cd and (cd.get("mrn") or cd.get("duty_a00_pln") is not None):
        return "uploaded_parsed"
    if inp.get("zc429_mrn"):
        return "uploaded_parsed"
    if a.get("zc429", {}).get("mrn"):
        return "uploaded_parsed"
    return "uploaded"


def derive_pz_status(a: Dict[str, Any]) -> str:
    """
    CANONICAL PZ accounting pipeline status. Returns: 'complete'|'ready'|'locked'|'failed'.

    Precedence (highest first):
      0. complete — wfirma_export.wfirma_pz_doc_id set (PZ actually created in wFirma;
                    highest authority, overrides a stale engine_error).
      1. failed   — audit.status=='failed' OR audit.engine_error truthy.
      2. complete — derive_status returns success/partial.
      3. locked   — SAD missing.
      4. ready    — default.
    """
    wfirma_export = a.get("wfirma_export") or {}
    if wfirma_export.get("wfirma_pz_doc_id"):
        return "complete"

    stored = (a.get("status") or "").strip().lower()
    if stored == "failed" or (a.get("engine_error") or "").strip():
        return "failed"

    status = derive_status(a)
    if status in ("success", "partial"):
        return "complete"
    sad_status = derive_sad_status(a)
    if sad_status == "missing":
        return "locked"
    return "ready"


def is_pz_done(a: Dict[str, Any]) -> bool:
    """Canonical 'PZ is complete' predicate — the single source both the dashboard
    column and the wFirma guard must agree on. True iff derive_pz_status == 'complete'."""
    return derive_pz_status(a) == "complete"


def compute_effective_pz_status(a: Dict[str, Any]) -> tuple:
    """Return ``(effective_status, normalized_flag)`` — the EFFECTIVE / creatability
    PZ-status authority.

    Campaign A1, Stage 1: an ADDITIVE, behaviour-identical extraction of
    ``routes_wfirma._compute_effective_pz_status`` into its canonical leaf home.
    Pinned byte-for-byte against the live fork by
    ``test_compute_effective_pz_status_extraction_parity.py``. Stage 1 is additive
    only — no caller is repointed and the fork is NOT retired (that happens later,
    behind a default-OFF flag, after shadow validation).

    This is a SEPARATE concern from ``derive_pz_status`` (the DISPLAY authority —
    the ``complete|ready|locked|failed`` enum). ``is_pz_done`` / ``derive_pz_status``
    MUST NOT call this, and Path B (below) MUST NOT be folded into them: the
    effective-status authority and the display authority are intentionally
    different (Path B has no display equivalent). Reuses the shared ``PZ_DONE`` set.

    Normalizes a stale ``status`` back to ``'partial'`` when the shipment is in fact
    PZ-complete but the persisted status string lags operator decisions:

    Path A — MRN present: ``failed_checks`` empty, ``customs_declaration.mrn``
      populated, ``verification.cn_match`` True OR ``cn_decision.approved`` True.
    Path B — PZ output exists (MRN unparseable but engine ran successfully):
      ``failed_checks`` empty, ``pz_output.pdf`` set, ``pz_output.generated_at`` set,
      and CN ok.

    Hard blocks (returns the stored status unchanged): ``failed_checks`` non-empty,
    MRN missing AND no ``pz_output`` evidence, or CN unresolved. Like the fork it
    checks only ``failed_checks`` (NOT ``engine_error``) and NEVER mutates the audit.
    """
    stored = (a.get("status") or "").strip()
    if stored in PZ_DONE:
        return stored, False

    failed = a.get("failed_checks") or []
    if failed:
        return stored, False

    # CN check is shared by both paths — resolve it once here.
    ver    = a.get("verification") or {}
    cn_dec = a.get("cn_decision")  or {}
    cn_ok  = bool(ver.get("cn_match")) or bool(cn_dec.get("approved"))
    if not cn_ok:
        return stored, False

    # ── Path A: MRN present ────────────────────────────────────────────────────
    cd  = a.get("customs_declaration") or {}
    mrn = (cd.get("mrn") or "").strip()
    if mrn:
        return "partial", True

    # ── Path B: PZ output exists (MRN not parsed but engine ran successfully) ──
    pz_output = a.get("pz_output") or {}
    pz_pdf_set  = bool((pz_output.get("pdf") or "").strip())
    pz_ts_set   = bool((pz_output.get("generated_at") or "").strip())
    if pz_pdf_set and pz_ts_set:
        return "partial", True

    return stored, False


__all__ = [
    "derive_status", "derive_sad_status", "derive_pz_status", "is_pz_done",
    "compute_effective_pz_status", "PZ_DONE", "_OUTPUTS",
]
