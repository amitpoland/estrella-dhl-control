"""compliance_resolver.py — secondary compliance authority (read-time).

Mirrors the sad_invoice_authority pattern. Produces a parallel structured
authority object that the dashboard consumes ALONGSIDE audit.verification.

Contract
--------
- Pure function. No I/O. No mutation of the input audit dict.
- Read-time only. Result is injected on dashboard detail read; never persisted.
- Operates on three target checks for v1: importer_match, exporter_match,
  qty_match_by_type. The deterministic engine already populates each as
  True/False/None plus rich provenance fields (nip_source, exporter_source,
  qty_status, master-NIP master fallback, etc.).
- Does NOT change True/False outcomes. Only upgrades None ("verify manually")
  into "verified" or "review" when the available evidence chain supports it
  with at least high confidence. Medium/low confidence keeps the manual
  warning intact (rules from task brief).
- Never rewrites SAD/invoice values. Never touches financial fields. Never
  emits an override entry.

Output shape
------------
{
  "<check_key>": {
     "resolver":     "intelligence" | "manual_required",
     "status":       "verified" | "review",
     "confidence":   "exact" | "high" | "medium" | "low",
     "evidence":     [{"source": "...", "value": "...", "doc_ref": "..."}],
     "resolved_by":  "compliance_resolver.v1",
     "resolved_at":  "<iso8601 utc>",
     "reason":       "<operator-facing short reason>"
  },
  ...
}

Checks that are already True or False in verification are skipped — the
deterministic authority stands; we do not annotate it.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

RESOLVER_VERSION = "compliance_resolver.v1"

TARGET_CHECKS = ("importer_match", "exporter_match", "qty_match_by_type")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _intelligence(status: str, confidence: str, reason: str,
                  evidence: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "resolver":    "intelligence",
        "status":      status,
        "confidence":  confidence,
        "evidence":    evidence,
        "resolved_by": RESOLVER_VERSION,
        "resolved_at": _now_iso(),
        "reason":      reason,
    }


def _manual(reason: str, evidence: Optional[List[Dict[str, Any]]] = None,
            confidence: str = "low") -> Dict[str, Any]:
    return {
        "resolver":    "manual_required",
        "status":      "review",
        "confidence":  confidence,
        "evidence":    evidence or [],
        "resolved_by": RESOLVER_VERSION,
        "resolved_at": _now_iso(),
        "reason":      reason,
    }


# ── per-check resolvers ──────────────────────────────────────────────────────

def _resolve_importer(ver: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Upgrade null importer_match using the NIP/master-fallback chain.

    The engine already attempts a name-overlap match, falls back to NIP, and
    further falls back to the known Estrella master NIP (RECIPIENT). When
    those upper layers leave the field null, the supporting fields tell us
    whether evidence is sufficient.
    """
    nip_match  = ver.get("nip_match")
    nip_source = ver.get("nip_source")
    sad_imp    = ver.get("sad_importer_name") or ""
    inv_imp    = ver.get("invoice_importer_name") or ""
    inv_vat    = ver.get("invoice_vat") or ""

    # Master-NIP fallback: invoice missing NIP, SAD declared the known master.
    if nip_match is True and nip_source == "sad_and_master":
        return _intelligence(
            status="verified",
            confidence="high",
            reason="Importer confirmed via master contractor NIP "
                   "(invoice omitted VAT; SAD declares the registered "
                   "Estrella NIP).",
            evidence=[
                {"source": "verification.nip_source", "value": nip_source},
                {"source": "verification.nip_match",  "value": True},
                {"source": "verification.sad_importer_name",
                 "value": sad_imp},
            ],
        )

    # NIP matches on both sides but engine name-overlap heuristic returned
    # None (e.g. one side missing parsed name string). NIP equality is a
    # stronger identity proof than name overlap.
    if nip_match is True and nip_source == "invoice_and_sad":
        return _intelligence(
            status="verified",
            confidence="high",
            reason="Importer VAT/NIP matches between invoice and SAD.",
            evidence=[
                {"source": "verification.nip_match",  "value": True},
                {"source": "verification.nip_source", "value": nip_source},
                {"source": "verification.invoice_vat", "value": inv_vat},
            ],
        )

    # Insufficient evidence — keep the manual warning.
    return _manual(
        reason="Importer identity could not be confirmed from available "
               "evidence. Manual review required.",
        evidence=[
            {"source": "verification.nip_source",
             "value": nip_source or "unknown"},
            {"source": "verification.sad_importer_name", "value": sad_imp},
            {"source": "verification.invoice_importer_name", "value": inv_imp},
        ],
        confidence="low",
    )


def _resolve_exporter(ver: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Upgrade null exporter_match using parsed exporter source provenance.

    Engine sets exporter_source to one of:
      invoice_and_sad / invoice_only / sad_only / neither
    SAD truncation of a known legal entity is the canonical reason
    exporter_match is null while invoice carries the full name.
    """
    src         = ver.get("exporter_source")
    sad_exp     = ver.get("sad_exporter_name") or ver.get("zc429_exporter_name") or ""
    # The engine writes invoice_exporter only into the invoice record, but it
    # populates _exporter_label, exporter_source — those are sufficient signal.
    label       = ver.get("exporter_label") or ver.get("_exporter_label") or ""

    if src == "invoice_only":
        return _intelligence(
            status="verified",
            confidence="high",
            reason="Exporter parsed from invoice; SAD omits the exporter "
                   "block (common SAD truncation pattern).",
            evidence=[
                {"source": "verification.exporter_source", "value": src},
                {"source": "verification.exporter_label",  "value": label},
            ],
        )

    if src == "sad_only":
        # Lower confidence — only SAD parsed exporter; invoice side empty.
        # Operator must confirm against the invoice document.
        return _manual(
            reason="Exporter present only in SAD; invoice exporter not "
                   "parsed. Cross-check against the invoice document.",
            evidence=[
                {"source": "verification.exporter_source", "value": src},
                {"source": "verification.sad_exporter_name", "value": sad_exp},
            ],
            confidence="medium",
        )

    # invoice_and_sad here implies engine already returned True/False — we
    # would not be called. neither / unknown → low signal.
    return _manual(
        reason="Exporter identity unverified — neither invoice nor SAD "
               "exporter block parsed cleanly.",
        evidence=[
            {"source": "verification.exporter_source",
             "value": src or "unknown"},
        ],
        confidence="low",
    )


def _resolve_qty_by_type(ver: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Upgrade null qty_match_by_type when SAD uses an aggregated combined
    line AND the cif reconciliation independently confirms the total.

    qty_status == "partial_aggregated_sad" means SAD declares a single
    aggregated description (engine could not slice per-type), but the SAD
    is internally consistent. When the CIF totals also match between
    invoice and SAD, the qty-per-type gap is a SAD formatting artifact,
    not a discrepancy. That is enough for an intelligence upgrade.
    """
    qty_status = ver.get("qty_status")
    cif_match  = ver.get("cif_match")

    if qty_status == "partial_aggregated_sad" and cif_match is True:
        return _intelligence(
            status="verified",
            confidence="high",
            reason="SAD uses an aggregated combined-description line and "
                   "the CIF total reconciles against the invoices. Per-type "
                   "qty cannot be sliced from SAD, but the aggregate is "
                   "consistent.",
            evidence=[
                {"source": "verification.qty_status",  "value": qty_status},
                {"source": "verification.cif_match",   "value": True},
            ],
        )

    if qty_status == "partial_aggregated_sad":
        # SAD aggregated but CIF not independently verified — medium signal.
        return _manual(
            reason="SAD uses combined description; CIF reconciliation not "
                   "available to corroborate the aggregate.",
            evidence=[
                {"source": "verification.qty_status", "value": qty_status},
                {"source": "verification.cif_match",
                 "value": cif_match if cif_match is not None else "unknown"},
            ],
            confidence="medium",
        )

    return _manual(
        reason="Quantity-by-type could not be reconciled from available "
               "evidence.",
        evidence=[
            {"source": "verification.qty_status",
             "value": qty_status or "unknown"},
        ],
        confidence="low",
    )


_DISPATCH = {
    "importer_match":    _resolve_importer,
    "exporter_match":    _resolve_exporter,
    "qty_match_by_type": _resolve_qty_by_type,
}


# ── public entry point ───────────────────────────────────────────────────────

def resolve_compliance(audit: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Derive compliance_resolution for an audit dict.

    Pure function. Does NOT mutate the input. Returns a dict keyed by the
    verification check name. Only checks that are currently null in
    audit.verification are evaluated — True/False outcomes from the
    deterministic engine are left untouched and are not present in the
    returned dict.
    """
    ver = (audit or {}).get("verification") or {}
    out: Dict[str, Dict[str, Any]] = {}

    for key in TARGET_CHECKS:
        # Only upgrade null states. Never re-decide True/False engine output.
        if key not in ver:
            continue
        current = ver.get(key)
        if current is True or current is False:
            continue
        resolver_fn = _DISPATCH.get(key)
        if resolver_fn is None:
            continue
        try:
            out[key] = resolver_fn(ver)
        except Exception as exc:  # noqa: BLE001
            # Degrade safely — never raise out of the resolver.
            out[key] = {
                "resolver":    "manual_required",
                "status":      "review",
                "confidence":  "low",
                "evidence":    [],
                "resolved_by": RESOLVER_VERSION,
                "resolved_at": _now_iso(),
                "reason":      f"Resolver error (degraded to manual): "
                               f"{type(exc).__name__}",
            }

    return out
