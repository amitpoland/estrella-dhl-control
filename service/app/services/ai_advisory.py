"""
ai_advisory.py — Read-only AI advisory service (Phase 2: LLM-augmented).

Class: R (read-only AI). See docs/ai-governance/ai-capability-map.md.

Phase 1 delivered a deterministic "why is this workflow blocked?" explanation
from batch_readiness output. Phase 2 wires an opt-in LLM call inside
synthesise_explanation() via ai_gateway.call(). All Phase 1 contracts carry
forward unchanged: no writes, no execute calls, no authority redefinition.

Feature flags (config.py, all default False / disabled):
    ai_advisory_llm_enabled        -- master switch; must be True to use LLM
    ai_advisory_model              -- model id (default: haiku for cost control)
    ai_advisory_max_tokens_per_call
    ai_advisory_budget_usd_per_day -- advisory-specific daily ceiling
    ai_advisory_cache_ttl_seconds  -- TTL for in-memory result cache

When ai_advisory_llm_enabled=False (the default) the behaviour is identical
to Phase 1: deterministic, zero LLM calls, llm_used=False.

Response shape (Phase 2, backward-compatible with Phase 1):
    {
        "batch_id":          str,
        "ready_for_closure": bool,
        "blocked_domains":   list[str],
        "next_step":         str,
        "blockers":          list[Blocker],
        "summary":           str,               -- plain-English explanation
        "advisory_class":    "R",               -- read-only by contract
        "source":            str,               -- "batch_readiness" or "batch_readiness+llm"
        "llm_used":          bool,              -- True iff LLM call succeeded this response
        "model_used":        str | None,        -- model id if llm_used, else None
        "generated_at":      str,               -- ISO-8601 UTC
    }

Blocker:
    {
        "domain":           str,
        "status":           str,
        "message":          str,
        "why":              str,                -- deterministic plain-English expansion
        "what_unblocks_it": str,               -- deterministic next-action hint
    }

Forbidden (binding, not relaxed in Phase 2):
    * wfirma_writer / wfirma_create_*
    * email_service.queue_email / send / smtplib
    * execute_action(...)
    * database writes (INSERT INTO / UPDATE / DELETE FROM / CREATE TABLE / DROP TABLE)
    * mutation of audit.json / timeline.json
    * HTTP calls to wFirma / DHL / carrier endpoints
    * re-derivation of financial truth or readiness
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from .batch_readiness import get_batch_readiness

# Module-level import so tests can patch app.services.ai_advisory.ai_gateway.
# The gateway may not be installed in minimal test environments; failures are
# handled gracefully inside _synthesise_via_llm (returns None on any error).
try:
    from . import ai_gateway  # noqa: F401
except Exception:  # pragma: no cover
    ai_gateway = None  # type: ignore[assignment]


# ── Public contract ───────────────────────────────────────────────────────────

class AdvisoryError(Exception):
    """Raised when readiness cannot be loaded. The route maps this to 503."""


# ── In-memory TTL cache ───────────────────────────────────────────────────────

_CACHE_LOCK = threading.Lock()
_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}


def _cache_get(key: str, ttl_s: int) -> Optional[Dict[str, Any]]:
    if ttl_s <= 0:
        return None
    with _CACHE_LOCK:
        entry = _cache.get(key)
        if entry and (time.monotonic() - entry[0]) < ttl_s:
            return dict(entry[1])  # return a copy
    return None


def _cache_set(key: str, value: Dict[str, Any]) -> None:
    with _CACHE_LOCK:
        _cache[key] = (time.monotonic(), dict(value))


def cache_clear() -> None:
    """Flush all cached advisory results. Test use only."""
    with _CACHE_LOCK:
        _cache.clear()


# ── Advisory budget guard ─────────────────────────────────────────────────────

def _advisory_budget_ok() -> bool:
    """Return True iff advisory-specific daily budget is not exhausted.

    Uses the ai_advisory_budget_usd_per_day setting against today's total
    actual cost in ai_call_ledger.db. Fails closed on any error.
    """
    try:
        from ..core.config import settings  # noqa: PLC0415
        budget = float(getattr(settings, "ai_advisory_budget_usd_per_day", 1.0))
        if budget <= 0:
            return True  # unlimited
        from . import ai_call_ledger as ledger  # noqa: PLC0415
        spent = ledger.get_daily_cost_usd()
        return spent < budget
    except Exception:
        return False  # fail closed


# ── LLM system prompt ─────────────────────────────────────────────────────────

_SYSTEM_PROMPT = (
    "You are an operations analyst for a B2B jewellery import workflow platform. "
    "You will receive structured information about why a batch is blocked in the "
    "customs/inventory workflow. Produce a concise, plain-English explanation for "
    "a logistics operator. "
    "Rules: no markdown headers, no bullet lists -- use short prose paragraphs. "
    "Maximum 3 sentences. Be concrete about what needs to happen next. "
    "Do not invent facts not present in the input."
)


def _build_user_prompt(
    *,
    batch_id: str,
    ready_for_closure: bool,
    blockers: List[Dict[str, Any]],
    next_step: str,
) -> str:
    """Build a safe, structured user prompt from authority output only.

    IMPORTANT: this function receives only structured fields produced from
    batch_readiness authority output -- never raw email text, supplier
    documents, or free-form operator input. Prompt-injection risk is minimal
    because the input surface is closed (enum-like domain names, status codes,
    short message strings from deterministic service output).
    """
    if ready_for_closure:
        return (
            f"Batch {batch_id} is ready for closure. "
            "All workflow domains (warehouse, sales, wFirma, DHL) are satisfied. "
            "Provide a one-sentence confirmation for the operator."
        )

    blocker_lines = "\n".join(
        f"  domain={b['domain']} status={b['status']} message={b['message']!r} "
        f"next_action={b['what_unblocks_it']!r}"
        for b in blockers
    )
    prompt = (
        f"Batch {batch_id} is blocked.\n"
        f"Blocked domains ({len(blockers)}):\n{blocker_lines}\n"
    )
    if next_step:
        prompt += f"Suggested next step: {next_step!r}\n"
    prompt += (
        "\nExplain to the operator what is blocking this batch and "
        "what specific action will unblock it."
    )
    return prompt


# ── LLM synthesis ─────────────────────────────────────────────────────────────

def _synthesise_via_llm(
    *,
    batch_id: str,
    ready_for_closure: bool,
    blockers: List[Dict[str, Any]],
    next_step: str,
    selected_model: str,
    max_tokens: int,
) -> Optional[str]:
    """Route through ai_gateway for an LLM-synthesised explanation.

    Returns the model's text response, or None when:
    - ai_gateway.call() returns None (flag off, key missing, CB open, budget, etc.)
    - Any exception occurs

    Never raises. The caller always falls back to synthesise_explanation().
    """
    try:
        # Reference module-level ai_gateway (imported above) so test patches work.
        gw = ai_gateway
        if gw is None:
            return None

        user_text = _build_user_prompt(
            batch_id=batch_id,
            ready_for_closure=ready_for_closure,
            blockers=blockers,
            next_step=next_step,
        )

        raw = gw.call(
            system=_SYSTEM_PROMPT,
            user=user_text,
            task_type="advisory_explanation",
            service_name="ai_advisory",
            object_id=batch_id,
            complexity="simple",
            risk_level="low",
            confidence_score=1.0,
            max_tokens=max_tokens,
            operator_override_model=selected_model,
        )
        if raw and raw.strip():
            return raw.strip()
        return None
    except Exception:
        return None


# ── Main entry point ──────────────────────────────────────────────────────────

def explain_workflow_blockers(batch_id: str) -> Dict[str, Any]:
    """Return a read-only explanation of why a batch's workflow is blocked.

    Phase 2: attempts LLM synthesis when ai_advisory_llm_enabled=True and
    budget/circuit-breaker/api-key conditions are satisfied. Falls back to
    deterministic path in all other cases.

    Caches results for ai_advisory_cache_ttl_seconds (default 300s).
    Never raises (only AdvisoryError on readiness load failure).
    """
    if not batch_id or not isinstance(batch_id, str):
        raise AdvisoryError("batch_id must be a non-empty string")

    # ── Feature flag + config snapshot ────────────────────────────────────────
    # Default model string intentionally left empty here: model IDs live only
    # in ai_gateway.py and config.py (gateway-violation rule). If settings fail
    # to load, llm_enabled stays False and selected_model is never used.
    llm_enabled = False
    selected_model = ""
    max_tokens = 1000
    cache_ttl = 300
    try:
        from ..core.config import settings  # noqa: PLC0415
        llm_enabled = bool(getattr(settings, "ai_advisory_llm_enabled", False))
        selected_model = str(getattr(settings, "ai_advisory_model", ""))
        max_tokens = int(getattr(settings, "ai_advisory_max_tokens_per_call", 1000))
        cache_ttl = int(getattr(settings, "ai_advisory_cache_ttl_seconds", 300))
    except Exception:
        llm_enabled = False

    # ── Cache check ───────────────────────────────────────────────────────────
    cache_key = f"advisory:{batch_id}:llm={llm_enabled}"
    cached = _cache_get(cache_key, cache_ttl)
    if cached is not None:
        return cached

    # ── Load readiness (only authoritative source) ────────────────────────────
    try:
        readiness = get_batch_readiness(batch_id)
    except Exception as exc:  # pragma: no cover
        raise AdvisoryError(f"readiness_load_failed: {exc!s}") from exc

    overall = readiness.get("overall") or {}
    blocked_domains: List[str] = list(overall.get("blocked_domains") or [])
    ready_for_closure: bool = bool(overall.get("ready_for_closure"))
    next_step: str = str(overall.get("next_step") or "")

    blockers: List[Dict[str, Any]] = []
    for domain in blocked_domains:
        d = readiness.get(domain) or {}
        blockers.append({
            "domain":           domain,
            "status":           str(d.get("status") or "unknown"),
            "message":          str(d.get("message") or ""),
            "why":              _why_for(domain, d),
            "what_unblocks_it": _unblock_hint_for(domain, d),
        })

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # ── LLM path (Phase 2) ─────────────────────────────────────────────────────
    if llm_enabled and _advisory_budget_ok():
        llm_text = _synthesise_via_llm(
            batch_id=batch_id,
            ready_for_closure=ready_for_closure,
            blockers=blockers,
            next_step=next_step,
            selected_model=selected_model,
            max_tokens=max_tokens,
        )
        if llm_text is not None:
            result = {
                "batch_id":          batch_id,
                "ready_for_closure": ready_for_closure,
                "blocked_domains":   blocked_domains,
                "next_step":         next_step,
                "blockers":          blockers,
                "summary":           llm_text,
                "advisory_class":    "R",
                "source":            "batch_readiness+llm",
                "llm_used":          True,
                "model_used":        selected_model,
                "generated_at":      generated_at,
            }
            _cache_set(cache_key, result)
            return result

    # ── Deterministic fallback (Phase 1 path) ─────────────────────────────────
    summary = synthesise_explanation(
        batch_id=batch_id,
        ready_for_closure=ready_for_closure,
        blockers=blockers,
        next_step=next_step,
    )
    result = {
        "batch_id":          batch_id,
        "ready_for_closure": ready_for_closure,
        "blocked_domains":   blocked_domains,
        "next_step":         next_step,
        "blockers":          blockers,
        "summary":           summary,
        "advisory_class":    "R",
        "source":            "batch_readiness",
        "llm_used":          False,
        "model_used":        None,
        "generated_at":      generated_at,
    }
    _cache_set(cache_key, result)
    return result


def synthesise_explanation(
    *,
    batch_id: str,
    ready_for_closure: bool,
    blockers: List[Dict[str, Any]],
    next_step: str,
) -> str:
    """
    Deterministic plain-English synthesis from structured readiness output.

    Phase 1 + Phase 2 fallback path. Called directly when:
    - ai_advisory_llm_enabled=False (default)
    - LLM path unavailable (no key, budget exhausted, CB open, gateway None)
    - Any error in LLM path

    The function signature is stable: callers pass only structured fields
    from authority output (never raw email/document text).
    """
    if ready_for_closure:
        return (
            f"Batch {batch_id} is ready for closure. "
            "All four readiness domains (warehouse, sales, wFirma, DHL) report ready."
        )

    if not blockers:
        return (
            f"Batch {batch_id} reports not-ready but no blocked domains were identified. "
            "Refresh readiness and re-check."
        )

    parts: List[str] = [
        f"Batch {batch_id} is blocked in {len(blockers)} domain(s): "
        + ", ".join(b["domain"] for b in blockers)
        + "."
    ]
    for b in blockers:
        parts.append(
            f"- {b['domain']}: {b['message'] or b['status']} "
            f"-> {b['what_unblocks_it']}"
        )
    if next_step:
        parts.append(f"Next step: {next_step}")
    return "\n".join(parts)


# ── Deterministic per-domain explanations ─────────────────────────────────────

def _why_for(domain: str, d: Dict[str, Any]) -> str:
    """Plain-English expansion of *why* this domain is not ready."""
    status = str(d.get("status") or "unknown")
    if domain == "warehouse":
        return {
            "n/a":     "No packing lines have been loaded for this batch yet.",
            "empty":   "Packing lines exist but nothing has been scanned into the warehouse.",
            "partial": "Some items scanned, but missing scans, invalid flows, or orphan inventory remain.",
        }.get(status, "Warehouse domain reports a non-ready state.")
    if domain == "sales":
        return {
            "n/a":     "Sales linkage has not been built yet.",
            "partial": "Some sales lines are linked, but invoice gaps or missing scans remain.",
        }.get(status, "Sales domain reports a non-ready state.")
    if domain == "wfirma":
        return {
            "not_configured": "wFirma reservation has not been configured for this batch.",
            "blocked":        "wFirma reports a hard blocker (customer/product authority gap or fiscal guard).",
            "created":        "wFirma reservation created but not yet ready for adoption.",
        }.get(status, "wFirma domain reports a non-ready state.")
    if domain == "dhl":
        if d.get("sla_breach"):
            return "DHL clearance pipeline has breached its SLA -- operator attention required."
        return "DHL clearance pipeline is waiting on an external event (SAD, agency reply, or carrier response)."
    return "Domain reports a non-ready state."


def _unblock_hint_for(domain: str, d: Dict[str, Any]) -> str:
    """Plain-English next-action hint for the operator (advisory only)."""
    status = str(d.get("status") or "unknown")
    if domain == "warehouse":
        if status == "n/a":
            return "Load the packing list for this batch."
        if status == "empty":
            return "Scan items into the warehouse."
        if status == "partial":
            return "Resolve missing scans, invalid flows, and orphans in the warehouse panel."
        return "Open the warehouse panel for this batch."
    if domain == "sales":
        return "Open the sales panel and complete invoice linkage / missing-scan resolution."
    if domain == "wfirma":
        if status == "not_configured":
            return "Open the wFirma panel and configure the reservation."
        if status == "blocked":
            return "Resolve customer/product authority gaps in the Customer Master / Product Master panels."
        return "Open the wFirma panel for next-step guidance."
    if domain == "dhl":
        if d.get("sla_breach"):
            return "Open the DHL clearance panel -- SLA breached, escalation may be required."
        return "Open the DHL clearance panel; the next external event is awaited."
    return "Open the domain panel for next-step guidance."
