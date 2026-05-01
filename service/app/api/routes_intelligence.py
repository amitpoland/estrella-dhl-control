"""
routes_intelligence.py — Intelligence Layer API
================================================
Endpoints for the Cowork Intelligence Engine.

GET  /api/v1/intelligence/suggestions   — current trigger suggestions + risks
GET  /api/v1/intelligence/config        — view suggested intelligence config
POST /api/v1/intelligence/refresh       — re-parse docs + rebuild config
GET  /api/v1/intelligence/actors        — full actor registry
GET  /api/v1/intelligence/classify      — classify a sample email (test endpoint)
GET  /api/v1/intelligence/status        — intelligence engine status summary
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..core.config import settings
from ..core.security import require_api_key

log    = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/intelligence", tags=["intelligence"])
_auth  = Depends(require_api_key)

_OUTPUTS     = settings.storage_root / "outputs"
_CONFIG_PATH = settings.storage_root / "intelligence_config.json"
_MASTER_PATH = settings.storage_root / "intelligence_master.json"


# ── Request / Response models ─────────────────────────────────────────────────

class ClassifyEmailRequest(BaseModel):
    sender:      str
    subject:     str = ""
    body:        str = ""
    attachments: List[str] = []


# ── Helpers ────────────────────────────────────────────────────────────────────

def _read_audit(batch_dir: Path) -> Optional[Dict[str, Any]]:
    p = batch_dir / "audit.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_all_active_batches() -> List[Dict[str, Any]]:
    batches = []
    if not _OUTPUTS.is_dir():
        return batches
    for batch_dir in _OUTPUTS.iterdir():
        if not batch_dir.is_dir():
            continue
        audit = _read_audit(batch_dir)
        if audit and not audit.get("archived"):
            audit["_batch_id"] = batch_dir.name
            batches.append(audit)
    return batches


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/suggestions")
async def get_intelligence_suggestions(
    include_low: bool = Query(False, description="Include LOW severity suggestions"),
    _: Any = _auth,
) -> JSONResponse:
    """
    Return all current intelligence suggestions across active batches.

    Combines:
    - cowork detect_triggers() suggestions (existing)
    - intelligence risk_detector warnings (new)
    - SLA breach analysis

    Read-only. No audit modifications. No emails sent.
    """
    try:
        from ..agents.cowork_coordinator import detect_triggers, load_audit, get_active_batches
        from ..services.risk_detector import detect_all_risks
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Import error: {exc}")

    all_suggestions: List[Dict[str, Any]] = []
    all_warnings:    List[Dict[str, Any]] = []
    batch_summary:   List[Dict[str, Any]] = []
    errors:          List[str] = []

    active_batches = get_active_batches()

    for batch_id in active_batches:
        try:
            audit = load_audit(batch_id)
            if not audit:
                continue

            awb = audit.get("awb") or audit.get("tracking_no") or ""

            # Cowork triggers (suggest-only)
            sug = detect_triggers(audit, batch_id)
            all_suggestions.extend(sug)

            # Risk detector warnings
            risks = detect_all_risks(audit)
            if not include_low:
                risks = [r for r in risks if r.get("severity") != "LOW"]
            all_warnings.extend(risks)

            batch_summary.append({
                "batch_id":        batch_id,
                "awb":             awb,
                "trigger_count":   len(sug),
                "warning_count":   len(risks),
                "status":          audit.get("status") or audit.get("clearance_status"),
                "carrier":         audit.get("carrier"),
            })

        except Exception as exc:
            errors.append(f"{batch_id}: {exc}")
            log.error("[intelligence] Batch error %s: %s", batch_id, exc)

    # Deduplicate suggestions by trigger+batch
    seen: set = set()
    unique_suggestions = []
    for s in all_suggestions:
        key = f"{s.get('trigger')}:{s.get('batch_id')}"
        if key not in seen:
            seen.add(key)
            unique_suggestions.append(s)

    # Count by severity/trigger
    trigger_counts: Dict[str, int] = {}
    for s in unique_suggestions:
        t = s.get("trigger", "UNKNOWN")
        trigger_counts[t] = trigger_counts.get(t, 0) + 1

    warning_counts: Dict[str, int] = {}
    for w in all_warnings:
        c = w.get("code", "UNKNOWN")
        warning_counts[c] = warning_counts.get(c, 0) + 1

    return JSONResponse({
        "generated_at":    datetime.now(timezone.utc).isoformat(),
        "batches_checked": len(active_batches),
        "suggestions": {
            "count":          len(unique_suggestions),
            "by_trigger":     trigger_counts,
            "items":          unique_suggestions,
        },
        "warnings": {
            "count":          len(all_warnings),
            "by_code":        warning_counts,
            "items":          all_warnings,
        },
        "batch_summary":   batch_summary,
        "errors":          errors,
        "mode":            "suggest_only",
        "note":            "Read-only. No audit modifications. No emails sent.",
    })


@router.get("/suggestions/{batch_id}")
async def get_batch_intelligence_suggestions(
    batch_id: str,
    _: Any = _auth,
) -> JSONResponse:
    """
    Return intelligence suggestions and SLA warnings for a single batch.

    Used by the dashboard "Live Intelligence" tab to show:
      - Active trigger suggestions for this shipment
      - SLA warnings derived from the timeline
      - Last detected clearance event
      - Next expected step

    Read-only. No audit modifications. No emails sent.
    """
    batch_dir  = _OUTPUTS / batch_id
    audit_path = batch_dir / "audit.json"
    if not batch_dir.is_dir() or not audit_path.exists():
        raise HTTPException(status_code=404, detail=f"Batch {batch_id!r} not found")

    try:
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Could not read audit: {exc}")

    try:
        from ..agents.cowork_coordinator import detect_triggers
        from ..services.sla_engine import check_sla, get_sla_summary
        from ..services.risk_detector import detect_all_risks
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Import error: {exc}")

    carrier   = audit.get("carrier") or "DHL"
    awb       = audit.get("awb") or audit.get("tracking_no") or ""
    timeline  = audit.get("timeline") or []

    # Cowork trigger suggestions (suggest-only)
    suggestions = detect_triggers(audit, batch_id)

    # Risk warnings
    risks = detect_all_risks(audit)

    # SLA summary from timeline
    sla_summary = {}
    sla_warnings: List[Dict[str, Any]] = []
    if timeline:
        try:
            sla_summary  = get_sla_summary(timeline, carrier=carrier)
            sla_warnings = check_sla(timeline, carrier=carrier, awb=awb, batch_id=batch_id)
        except Exception as exc:
            log.warning("[intelligence] SLA check failed for %s: %s", batch_id, exc)

    # Last detected clearance event (most recent email_classifier event on timeline)
    last_event: Optional[Dict[str, Any]] = None
    for ev in reversed(timeline):
        if (ev.get("trigger_source") == "email_classifier"
                or ev.get("event") in {
                    "carrier_arrived", "cesja_received", "zc429_received",
                    "pzc_received", "duty_note_received", "payment_confirmed",
                    "ganther_pzc_sent", "dsk_received", "cesja_submitted",
                }):
            last_event = ev
            break

    # Next expected step — inferred from current state
    def _next_step() -> str:
        ev_names = {e.get("event") for e in timeline}
        if "payment_confirmed" in ev_names:
            return "Await Ganther service invoice (ganther_invoice_received)"
        if "duty_note_received" in ev_names:
            return "Confirm duty payment with account@estrellajewels.eu"
        if "pzc_received" in ev_names or "ganther_pzc_sent" in ev_names:
            return "Await Ganther duty notice (duty_note_received)"
        if "zc429_received" in ev_names or "sad_uploaded" in ev_names:
            return "Await ACS PZC + duty notice (pzc_received)"
        if "cesja_received" in ev_names or "cesja_submitted" in ev_names:
            return "Await ZC429 / SAD clearance confirmation (zc429_received)"
        if "carrier_arrived" in ev_names:
            return "Await cesja / ACS clearance initiation (cesja_received)"
        if carrier == "FEDEX" and not audit.get("cesja_submitted_at"):
            return "Submit cesja to pl-import@fedex.com (manual step required)"
        return "Await carrier arrival confirmation (carrier_arrived)"

    return JSONResponse({
        "batch_id":       batch_id,
        "awb":            awb,
        "carrier":        carrier,
        "generated_at":   datetime.now(timezone.utc).isoformat(),
        "last_event":     last_event,
        "next_step":      _next_step(),
        "sla_summary":    sla_summary,
        "sla_warnings":   sla_warnings,
        "suggestions":    suggestions,
        "risk_warnings":  risks,
        "timeline_depth": len(timeline),
        "mode":           "suggest_only",
    })


@router.get("/config")
async def get_intelligence_config(
    _: Any = _auth,
) -> JSONResponse:
    """
    Return the current intelligence config (suggested, not yet activated).
    """
    if not _CONFIG_PATH.exists():
        return JSONResponse({
            "status":  "not_generated",
            "message": "Intelligence config not yet generated. POST /api/v1/intelligence/refresh to generate.",
        }, status_code=404)
    try:
        raw = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
        # Return safe summary (not full actor index — too large)
        cfg = raw.get("suggested_config") or raw.get("activated_config") or {}
        return JSONResponse({
            "version":          raw.get("version"),
            "generated_at":     raw.get("generated_at"),
            "docs_parsed":      raw.get("docs_parsed", []),
            "docs_missing":     raw.get("docs_missing", []),
            "approval_status":  raw.get("approval_status"),
            "summary": {
                "trusted_clearance_count":    len(cfg.get("TRUSTED_CLEARANCE_SENDERS", [])),
                "do_not_trigger_count":       len(cfg.get("DO_NOT_TRIGGER", [])),
                "attachment_patterns_count":  len(cfg.get("ATTACHMENT_PATTERNS", [])),
                "trigger_rules_count":        len(cfg.get("TRIGGER_RULES", [])),
                "risk_items_count":           len(cfg.get("RISK_ITEMS", [])),
                "unknown_emails_for_review":  cfg.get("_unknown_emails_for_review", []),
            },
            "trusted_clearance_senders": cfg.get("TRUSTED_CLEARANCE_SENDERS", []),
            "do_not_trigger":            cfg.get("DO_NOT_TRIGGER", []),
            "sla_thresholds":            cfg.get("SLA_THRESHOLDS", {}),
            "carrier_rules": {
                "DHL":   {k: v for k, v in (cfg.get("CARRIER_RULES", {}).get("DHL", {})).items()
                          if k not in ("payment_phrases",)},
                "FEDEX": cfg.get("CARRIER_RULES", {}).get("FEDEX", {}),
            },
        })
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Config read error: {exc}")


@router.post("/refresh")
async def refresh_intelligence_config(
    _: Any = _auth,
) -> JSONResponse:
    """
    Re-parse all research docs and rebuild intelligence config.

    Updates storage/intelligence_config.json as suggested_config.
    Does NOT activate config automatically — admin approval required.
    """
    try:
        from ..services.intelligence_config_builder import generate_and_save
        saved_path = generate_and_save()
        raw = json.loads(saved_path.read_text(encoding="utf-8"))
        cfg = raw.get("suggested_config") or {}
        return JSONResponse({
            "status":       "refreshed",
            "saved_to":     str(saved_path),
            "generated_at": raw.get("generated_at"),
            "docs_parsed":  raw.get("docs_parsed", []),
            "docs_missing": raw.get("docs_missing", []),
            "summary": {
                "actors":              len(cfg.get("ACTOR_INDEX", {})),
                "trusted_clearance":   len(cfg.get("TRUSTED_CLEARANCE_SENDERS", [])),
                "do_not_trigger":      len(cfg.get("DO_NOT_TRIGGER", [])),
                "triggers":            len(cfg.get("TRIGGER_RULES", [])),
                "risks":               len(cfg.get("RISK_ITEMS", [])),
                "unknown_for_review":  len(cfg.get("_unknown_emails_for_review", [])),
            },
            "note": "Config stored as suggested_config. Requires admin approval to activate.",
        })
    except Exception as exc:
        log.error("[intelligence] Refresh error: %s", exc)
        raise HTTPException(status_code=500, detail=f"Refresh failed: {exc}")


@router.get("/actors")
async def get_actor_registry(
    trust_level: Optional[str] = Query(None, description="Filter by trust_level"),
    carrier: Optional[str] = Query(None, description="Filter by carrier"),
    _: Any = _auth,
) -> JSONResponse:
    """
    Return the full actor registry with optional filtering.
    """
    try:
        from ..services.intelligence_parser import _ACTORS
        actors = [vars(a) for a in _ACTORS]
        if trust_level:
            actors = [a for a in actors if a.get("trust_level") == trust_level.upper()]
        if carrier:
            actors = [a for a in actors if a.get("carrier") == carrier.upper()]
        return JSONResponse({
            "count":  len(actors),
            "actors": actors,
        })
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/classify")
async def classify_email_endpoint(
    req: ClassifyEmailRequest,
    _: Any = _auth,
) -> JSONResponse:
    """
    Classify a sample email using the intelligence email classifier.

    Test endpoint for verifying classification rules.
    """
    try:
        from ..services.email_classifier import classify_email
        from ..services.timeline_mapper import map_email_to_events
        from ..services.risk_detector import detect_unknown_sender, detect_vat_deferment, detect_fca_complication

        classification = classify_email(
            sender=req.sender,
            subject=req.subject,
            body=req.body,
            attachments=req.attachments,
        )

        # Also compute timeline mapping
        mapping = map_email_to_events(classification)

        # Risk signals
        risks: List[Dict] = []
        risks.extend(detect_unknown_sender(req.sender))
        if req.body:
            risks.extend(detect_vat_deferment(req.body))
            risks.extend(detect_fca_complication(req.body))

        return JSONResponse({
            "classification": classification,
            "timeline_mapping": mapping.to_dict() if mapping else None,
            "risks": risks,
        })
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/status")
async def get_intelligence_status(
    _: Any = _auth,
) -> JSONResponse:
    """
    Return intelligence engine status summary.

    Shows: config status, doc availability, trigger counts, known risks.
    """
    from ..services.intelligence_parser import parse_research_docs, RESEARCH_DOCS

    # Check config file
    config_exists = _CONFIG_PATH.exists()
    config_age_h  = None
    if config_exists:
        try:
            raw = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
            gen_at = raw.get("generated_at", "")
            if gen_at:
                ts = datetime.fromisoformat(gen_at)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                config_age_h = round((datetime.now(timezone.utc) - ts).total_seconds() / 3600, 1)
        except Exception:
            pass

    # Check which docs exist
    doc_status = []
    for doc_path in RESEARCH_DOCS:
        doc_status.append({
            "name":   doc_path.name,
            "exists": doc_path.exists(),
            "size_kb": round(doc_path.stat().st_size / 1024, 1) if doc_path.exists() else None,
        })

    docs_found   = sum(1 for d in doc_status if d["exists"])
    docs_missing = sum(1 for d in doc_status if not d["exists"])

    return JSONResponse({
        "status": "active",
        "config": {
            "exists":        config_exists,
            "age_hours":     config_age_h,
            "path":          str(_CONFIG_PATH),
        },
        "research_docs": {
            "total":   len(RESEARCH_DOCS),
            "found":   docs_found,
            "missing": docs_missing,
            "details": doc_status,
        },
        "intelligence": {
            "actors_registered":    len([]),   # populated below
            "triggers_defined":     14,        # T0-T14 from blueprint
            "risks_tracked":        8,         # R1-R8 from analysis
            "carriers_supported":   ["DHL", "FEDEX"],
        },
        "capabilities": [
            "email_classification (dhl_arrival/zc429/fedex_cesja/duty/payment)",
            "risk_detection (routing_gap/sla_breach/vat_deferment/unknown_sender)",
            "timeline_mapping (email_type → timeline_event)",
            "carrier_aware_clearance_decision (DHL/FedEx unified)",
            "intelligence_config_generation (suggest_only)",
        ],
        "note": "Suggest-only mode. All outputs are advisory. No writes or sends.",
    })


@router.post("/build")
async def build_intelligence_master(
    _: Any = _auth,
) -> JSONResponse:
    """
    Build (or rebuild) intelligence_master.json from all 14 Task F documents.

    Parses research docs → extracts SLA benchmarks, automation opportunities,
    system gaps, actor discoveries, risk patterns → writes master JSON.

    Does NOT activate any automation. Does NOT modify audit.json.
    """
    try:
        from ..services.intelligence_engine import build_knowledge_base, load_master, TASK_F_DOCS
        saved = build_knowledge_base()
        master = load_master(force_reload=True)
        return JSONResponse({
            "status":      "built",
            "saved_to":    str(saved),
            "generated_at": master.get("generated_at") if master else None,
            "docs_parsed": master.get("docs_parsed", []) if master else [],
            "docs_missing": master.get("docs_missing", []) if master else [],
            "summary": {
                "automation_opportunities": len((master or {}).get("automation_opportunities", [])),
                "system_gaps":              len((master or {}).get("system_gaps", [])),
                "risk_patterns":            len((master or {}).get("risk_patterns", [])),
                "known_delay_incidents":    len((master or {}).get("known_delay_incidents", [])),
                "actor_discoveries":        len((master or {}).get("actor_discoveries", [])),
                "total_awbs_in_docs":       (master or {}).get("awb_stats", {}).get("total_awb_count", 0),
            },
            "note": "Read-only extraction. No audit.json modified. No automation enabled.",
        })
    except Exception as exc:
        log.error("[intelligence] Build error: %s", exc)
        raise HTTPException(status_code=500, detail=f"Build failed: {exc}")


@router.get("/insights")
async def get_intelligence_insights(
    phase: Optional[str] = Query(None, description="Filter automation opps by phase (P1, P2)"),
    include_gaps: bool = Query(True, description="Include system gap analysis"),
    _: Any = _auth,
) -> JSONResponse:
    """
    Return intelligence insights from intelligence_master.json.

    Different from /suggestions (which scans live batches):
      - /suggestions → live batch scan for current trigger + risk events
      - /insights    → knowledge base: automation opportunities, system gaps,
                       historical delay patterns, actor discoveries, SLA stats

    Requires intelligence_master.json to exist (POST /api/v1/intelligence/build first).
    """
    try:
        from ..services.intelligence_engine import (
            load_master,
            get_automation_opportunities,
            MASTER_PATH,
        )
        from ..services.intelligence_parser import _ACTORS

        master = load_master()

        if master is None:
            return JSONResponse({
                "status":  "not_built",
                "message": "Intelligence master not generated. POST /api/v1/intelligence/build to generate.",
                "master_path": str(MASTER_PATH),
            }, status_code=404)

        # Filter automation opportunities
        opps = get_automation_opportunities(phase=phase)
        high_impact_opps = [o for o in opps if o.get("impact") == "HIGH"]
        not_implemented  = [o for o in opps if "not_implemented" in (o.get("status") or "")]

        # System gaps
        gaps = master.get("system_gaps", []) if include_gaps else []
        high_gaps    = [g for g in gaps if g.get("severity") == "HIGH"]
        open_gaps    = [g for g in gaps if g.get("severity") in ("HIGH", "MEDIUM")]

        # Actor discoveries (emails found in docs not in known list)
        new_actors = master.get("actor_discoveries", [])

        # Known delays
        known_delays = master.get("known_delay_incidents", [])

        # SLA stats
        sla = master.get("sla_benchmarks", {})
        awb_stats = master.get("awb_stats", {})

        # Risk patterns
        risks = master.get("risk_patterns", [])

        # Current actor registry size
        actor_count = len(_ACTORS)

        return JSONResponse({
            "generated_at":       master.get("generated_at"),
            "master_version":     master.get("version"),
            "docs_coverage": {
                "parsed":  len(master.get("docs_parsed", [])),
                "missing": len(master.get("docs_missing", [])),
            },
            "shipment_stats": {
                "period":                  awb_stats.get("period"),
                "confirmed_dhl_shipments": awb_stats.get("confirmed_dhl_shipments"),
                "confirmed_fedex_inbound": awb_stats.get("confirmed_fedex_inbound"),
                "confirmed_total_duty_pln": awb_stats.get("confirmed_total_duty_pln"),
            },
            "automation_opportunities": {
                "total":           len(opps),
                "high_impact":     len(high_impact_opps),
                "not_implemented": len(not_implemented),
                "items":           opps,
            },
            "system_gaps": {
                "total":     len(gaps),
                "high":      len(high_gaps),
                "open":      len(open_gaps),
                "items":     gaps,
            } if include_gaps else {"note": "gaps excluded (include_gaps=false)"},
            "known_delay_incidents": {
                "count": len(known_delays),
                "items": known_delays,
            },
            "sla_benchmarks": {
                "DHL_days":   f"{sla.get('DHL', {}).get('total_days_min', 3)}–{sla.get('DHL', {}).get('total_days_max', 5)}",
                "FEDEX_days": f"{sla.get('FEDEX', {}).get('total_days_min', 6)}–{sla.get('FEDEX', {}).get('total_days_max', 9)}",
                "duty_payment_warning_h":  sla.get("thresholds", {}).get("duty_payment_warning_h", 72),
                "duty_payment_critical_h": sla.get("thresholds", {}).get("duty_payment_critical_h", 168),
                "fedex_cesja_warning_h":   sla.get("thresholds", {}).get("fedex_cesja_warning_h", 24),
            },
            "actor_discoveries": {
                "new_in_docs":     len(new_actors),
                "known_actors":    actor_count,
                "items":           new_actors[:20],   # cap to avoid large response
                "note":            f"{len(new_actors)} email addresses found in docs not in actor registry",
            },
            "risk_patterns": {
                "count": len(risks),
                "items": risks,
            },
            "mode": "knowledge_base",
            "note": "Static knowledge extracted from 14 Task F research documents. Not real-time.",
        })
    except Exception as exc:
        log.error("[intelligence] Insights error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))
