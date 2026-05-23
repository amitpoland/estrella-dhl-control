"""
ai_gateway.py — Single AI execution authority for the EJ Dashboard Portal.

ARCHITECTURAL RULE (operator-locked, 2026-05-23):
    Services express intent. Gateway executes policy.

Call contract:
    from .ai_gateway import call as ai_call

    raw_text = ai_call(
        system="You are a customs extractor...",
        user="Extract from this document: ...",
        task_type="customs_extraction",
        service_name="ai_customs_parser",
        object_id="batch_id_or_filename",
        complexity="moderate",
        risk_level="medium",
        context_size=len(text),
        confidence_score=1.0,
        max_tokens=2000,
    )
    # Returns str (raw model response) or None (unavailable / disabled / error)

FORBIDDEN — gateway violation rule (PR-review gate):
    Any file outside ai_gateway.py that contains:
    - anthropic.Anthropic() or any external AI client construction
    - Direct model-name selection (passing claude-* strings as call arguments)
    - Retry logic for AI calls
    - Redaction transforms for AI prompts
    - Token accounting or budget checks
    - ai_call_ledger.record() calls

    ...must be blocked at PR review, unless it is a test proving the
    violation is forbidden, or a config/docs file.

Claude-first rule:
    Claude Code / Claude Work is the primary reasoning path.
    Anthropic API is the fallback only, invoked through this gateway when
    Claude-first execution is unavailable, times out, or returns low
    confidence. No service may call Anthropic directly.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, Optional, Tuple

log = logging.getLogger(__name__)

# ── Model tier constants (ONLY place in codebase where model names appear) ────

_MODEL_HAIKU  = "claude-haiku-4-5-20251001"
_MODEL_SONNET = "claude-sonnet-4-6"
_MODEL_OPUS   = "claude-opus-4-7"

_TIER_NAMES: Dict[str, str] = {
    _MODEL_HAIKU:  "haiku",
    _MODEL_SONNET: "sonnet",
    _MODEL_OPUS:   "opus",
}


# ── Circuit breaker ───────────────────────────────────────────────────────────

_CB_LOCK              = threading.Lock()
_cb_consecutive_fails : int   = 0
_cb_open_since        : float = 0.0  # epoch seconds when CB opened
_CB_THRESHOLD         : int   = 5    # failures before open
_CB_RESET_AFTER_S     : float = 60.0 # seconds before attempting half-open


def _cb_is_open() -> bool:
    global _cb_consecutive_fails, _cb_open_since
    with _CB_LOCK:
        if _cb_consecutive_fails < _CB_THRESHOLD:
            return False
        if time.monotonic() - _cb_open_since >= _CB_RESET_AFTER_S:
            # Half-open: allow one attempt
            return False
        return True


def _cb_record_success() -> None:
    global _cb_consecutive_fails, _cb_open_since
    with _CB_LOCK:
        _cb_consecutive_fails = 0
        _cb_open_since = 0.0


def _cb_record_failure() -> None:
    global _cb_consecutive_fails, _cb_open_since
    with _CB_LOCK:
        _cb_consecutive_fails += 1
        if _cb_consecutive_fails >= _CB_THRESHOLD:
            _cb_open_since = time.monotonic()


def reset_circuit_breaker() -> None:
    """Reset circuit breaker state. For tests only."""
    global _cb_consecutive_fails, _cb_open_since
    with _CB_LOCK:
        _cb_consecutive_fails = 0
        _cb_open_since = 0.0


# ── Model selection ───────────────────────────────────────────────────────────

def _select_model(
    task_type:        str,
    complexity:       str,
    risk_level:       str,
    confidence_score: float,
    operator_override: Optional[str],
) -> Tuple[str, str, Optional[str]]:
    """Return (model_id, selection_reason, escalation_reason).

    Selection policy:
    - Haiku  : simple tasks, low-medium risk, high confidence
    - Sonnet : moderate reasoning, structured analysis (default)
    - Opus   : high complexity, cross-domain, low confidence, critical risk,
               or explicit operator escalation
    """
    if operator_override:
        tier = _TIER_NAMES.get(operator_override, "custom")
        return operator_override, f"operator_override:{tier}", None

    # Escalation conditions for Opus
    needs_opus = (
        complexity == "complex"
        or risk_level == "critical"
        or (risk_level == "high" and confidence_score < 0.6)
        or confidence_score < 0.3
    )
    if needs_opus:
        reason = "high_complexity_or_risk"
        esc = f"complexity={complexity}, risk={risk_level}, confidence={confidence_score:.2f}"
        return _MODEL_OPUS, reason, esc

    # Haiku for simple, low-risk, high-confidence tasks
    if (
        complexity == "simple"
        and risk_level in ("low", "medium")
        and confidence_score >= 0.8
    ):
        return _MODEL_HAIKU, "simple_low_risk_high_confidence", None

    # Haiku may escalate to Sonnet on low confidence or ambiguity
    if complexity == "simple" and confidence_score < 0.7:
        return _MODEL_SONNET, "haiku_escalated_low_confidence", "confidence_below_0.7"

    # Default: Sonnet for all moderate work
    return _MODEL_SONNET, "moderate_default", None


# ── Gateway availability ──────────────────────────────────────────────────────

def is_available() -> bool:
    """Return True iff the gateway can make API calls."""
    try:
        from ..core.config import settings  # noqa: PLC0415
        if not getattr(settings, "ai_parser_enabled", False):
            return False
        key = getattr(settings, "anthropic_api_key", None) or ""
        return bool(key.strip())
    except Exception:
        return False


# ── Main entry point ──────────────────────────────────────────────────────────

def call(
    *,
    system:            str,
    user:              str,
    task_type:         str,
    service_name:      str           = "unknown",
    object_id:         Optional[str] = None,
    complexity:        str           = "moderate",
    risk_level:        str           = "medium",
    context_size:      int           = 0,
    confidence_score:  float         = 1.0,
    max_tokens:        int           = 2000,
    operator_override_model: Optional[str] = None,
) -> Optional[str]:
    """Execute one AI call through the gateway.

    Returns the raw model response text, or None when:
    - ai_parser_enabled=False (config disabled)
    - API key missing
    - Daily budget exceeded
    - Circuit breaker open
    - All retries exhausted
    - Any other error

    Never raises.
    """
    from . import ai_call_ledger as ledger  # noqa: PLC0415
    from . import ai_redactor as redactor   # noqa: PLC0415

    t_start = time.monotonic()

    # ── Gate 1: config enabled + key present ─────────────────────────────────
    try:
        from ..core.config import settings  # noqa: PLC0415
    except Exception as exc:
        log.error("[ai_gateway] config import failed: %s", exc)
        return None

    api_key = getattr(settings, "anthropic_api_key", None) or ""
    if not api_key.strip():
        log.debug("[ai_gateway] no API key — skipping")
        return None

    if not getattr(settings, "ai_parser_enabled", False):
        log.debug("[ai_gateway] ai_parser_enabled=False — skipping")
        return None

    # ── Gate 2: circuit breaker ───────────────────────────────────────────────
    if _cb_is_open():
        log.warning("[ai_gateway] circuit breaker OPEN — skipping call")
        return None

    # ── Gate 3: daily budget ──────────────────────────────────────────────────
    daily_budget = getattr(settings, "ai_gateway_daily_budget_usd", 0.0)
    if daily_budget > 0:
        spent = ledger.get_daily_cost_usd()
        if spent >= daily_budget:
            log.warning("[ai_gateway] daily budget %.4f USD exhausted (%.4f spent)", daily_budget, spent)
            return None

    # ── Model selection ───────────────────────────────────────────────────────
    selected_model, selection_reason, escalation_reason = _select_model(
        task_type=task_type,
        complexity=complexity,
        risk_level=risk_level,
        confidence_score=confidence_score,
        operator_override=operator_override_model,
    )
    model_tier = _TIER_NAMES.get(selected_model, "custom")

    # ── Redact prompts before any external call ───────────────────────────────
    system_clean, user_clean = redactor.redact_pair(system, user)
    p_hash = ledger.prompt_hash(system_clean, user_clean)

    # ── Token / cost estimates ────────────────────────────────────────────────
    est_in  = ledger.estimate_tokens(system_clean) + ledger.estimate_tokens(user_clean)
    est_out = max_tokens // 2  # conservative
    est_cost = ledger.estimate_cost(selected_model, est_in, est_out)

    # ── Call with retry ───────────────────────────────────────────────────────
    max_retries = max(0, getattr(settings, "ai_gateway_max_retries", 3))
    timeout_s   = getattr(settings, "ai_gateway_timeout_seconds", 30)

    raw_text:         Optional[str] = None
    actual_in:        Optional[int] = None
    actual_out:       Optional[int] = None
    actual_cost_val:  Optional[float] = None
    success           = False
    error_type:       Optional[str] = None

    try:
        import anthropic  # noqa: PLC0415
    except ImportError:
        log.error("[ai_gateway] anthropic package not installed — pip install anthropic")
        _ledger_write(
            ledger=ledger,
            task_type=task_type, service_name=service_name, object_id=object_id,
            requested_model=operator_override_model, selected_model=selected_model,
            model_tier=model_tier, selection_reason=selection_reason,
            escalation_reason=escalation_reason, confidence_score=confidence_score,
            p_hash=p_hash, est_in=est_in, est_out=est_out, est_cost=est_cost,
            actual_in=None, actual_out=None, actual_cost_val=None,
            latency_ms=int((time.monotonic() - t_start) * 1000),
            success=False, fallback_reason=None, error_type="ImportError",
        )
        return None

    client = anthropic.Anthropic(api_key=api_key, timeout=float(timeout_s))

    last_exc_type: Optional[str] = None
    for attempt in range(max_retries + 1):
        if attempt > 0:
            backoff = 2 ** (attempt - 1)  # 1s, 2s, 4s
            log.info("[ai_gateway] retry %d/%d after %ds", attempt, max_retries, backoff)
            time.sleep(backoff)

        try:
            response = client.messages.create(
                model=selected_model,
                max_tokens=max_tokens,
                system=system_clean,
                messages=[{"role": "user", "content": user_clean}],
            )
            raw_text = (response.content[0].text or "").strip()

            # Capture actual usage if reported
            usage = getattr(response, "usage", None)
            if usage:
                actual_in  = getattr(usage, "input_tokens",  None)
                actual_out = getattr(usage, "output_tokens", None)
                if actual_in is not None and actual_out is not None:
                    actual_cost_val = ledger.estimate_cost(selected_model, actual_in, actual_out)

            success = True
            last_exc_type = None
            _cb_record_success()
            break

        except Exception as exc:
            exc_type = type(exc).__name__
            last_exc_type = exc_type

            # Retry only on rate-limit or 5xx server errors
            retryable = _is_retryable(exc)
            log.warning("[ai_gateway] attempt %d failed (%s): %s", attempt + 1, exc_type, exc)

            if not retryable or attempt >= max_retries:
                _cb_record_failure()
                break

    error_type = last_exc_type
    latency_ms = int((time.monotonic() - t_start) * 1000)

    _ledger_write(
        ledger=ledger,
        task_type=task_type, service_name=service_name, object_id=object_id,
        requested_model=operator_override_model, selected_model=selected_model,
        model_tier=model_tier, selection_reason=selection_reason,
        escalation_reason=escalation_reason, confidence_score=confidence_score,
        p_hash=p_hash, est_in=est_in, est_out=est_out, est_cost=est_cost,
        actual_in=actual_in, actual_out=actual_out, actual_cost_val=actual_cost_val,
        latency_ms=latency_ms,
        success=success, fallback_reason=None, error_type=error_type,
    )

    if success:
        log.info("[ai_gateway] %s/%s OK model=%s latency=%dms",
                 service_name, task_type, selected_model, latency_ms)
        return raw_text

    log.error("[ai_gateway] %s/%s FAILED after %d attempts model=%s",
              service_name, task_type, max_retries + 1, selected_model)
    return None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _is_retryable(exc: Exception) -> bool:
    """Return True for rate-limit (429) and server errors (5xx)."""
    try:
        import anthropic  # noqa: PLC0415
        if isinstance(exc, anthropic.RateLimitError):
            return True
        if isinstance(exc, anthropic.APIStatusError):
            status = getattr(exc, "status_code", 0)
            return status >= 500
    except ImportError:
        pass
    # Fallback: retry on timeout-like exceptions by name
    name = type(exc).__name__.lower()
    return "timeout" in name or "ratelimit" in name


def _ledger_write(
    *,
    ledger: Any,
    task_type: str, service_name: str, object_id: Optional[str],
    requested_model: Optional[str], selected_model: str,
    model_tier: str, selection_reason: Optional[str],
    escalation_reason: Optional[str], confidence_score: float,
    p_hash: str, est_in: int, est_out: int, est_cost: float,
    actual_in: Optional[int], actual_out: Optional[int],
    actual_cost_val: Optional[float], latency_ms: int,
    success: bool, fallback_reason: Optional[str], error_type: Optional[str],
) -> None:
    ledger.record({
        "timestamp":               time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "service":                 service_name,
        "object_id":               object_id,
        "task_type":               task_type,
        "requested_model":         requested_model,
        "selected_model":          selected_model,
        "model_tier":              model_tier,
        "selection_reason":        selection_reason,
        "escalation_reason":       escalation_reason,
        "confidence_score":        confidence_score,
        "prompt_hash":             p_hash,
        "estimated_input_tokens":  est_in,
        "estimated_output_tokens": est_out,
        "estimated_cost":          est_cost,
        "actual_input_tokens":     actual_in,
        "actual_output_tokens":    actual_out,
        "actual_cost":             actual_cost_val,
        "latency_ms":              latency_ms,
        "success":                 success,
        "fallback_reason":         fallback_reason,
        "error_type":              error_type,
    })
