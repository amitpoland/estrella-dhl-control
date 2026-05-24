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

Claude-first rule (Phase 2B — provider abstraction):
    Claude Code / Claude Work (Cowork) is the primary reasoning path.
    Anthropic API is the fallback only, invoked through this gateway when
    Claude-first execution is unavailable, times out, or returns low
    confidence.  No service may call Anthropic directly.

    Provider selection policy:
      1. If ai_cowork_enabled=True AND ai_provider_preference="claude_cowork":
             → try _cowork_call() first (stub in 2B; live in Phase 3)
             → if cowork returns None AND ai_fallback_enabled=True:
                 → try _anthropic_call() as governed fallback
             → if cowork returns None AND ai_fallback_enabled=False:
                 → return None (no fallback allowed)
      2. Otherwise (cowork disabled or preference != claude_cowork):
             → _anthropic_call() directly (backward-compatible path)

    provider_requested / provider_used / fallback_used are recorded in
    ai_call_ledger on every call attempt, regardless of outcome.
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

# ── Provider constants (Phase 2B) ─────────────────────────────────────────────

_PROVIDER_COWORK    = "claude_cowork"
_PROVIDER_ANTHROPIC = "anthropic_api"


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
    """Return True iff the gateway can make API calls.

    Phase 2B: True when either the Anthropic API path is configured OR the
    Cowork provider is enabled (even as a stub).

    Admin API key health: if ANTHROPIC_ADMIN_API_KEY and ANTHROPIC_API_KEY_ID
    are both configured, this also validates that the key status is "active".
    If the Admin API check fails or is not configured, the simpler non-empty
    key check is used (graceful degradation — never blocks on Admin API error).
    """
    try:
        from ..core.config import settings  # noqa: PLC0415
        if not getattr(settings, "ai_parser_enabled", False):
            return False
        cowork_enabled = bool(getattr(settings, "ai_cowork_enabled", False))
        if cowork_enabled:
            return True
        key = getattr(settings, "anthropic_api_key", None) or ""
        if not key.strip():
            return False
        # Optional Admin API key health check
        health = check_key_health()
        if health is not None and health.get("error") is None:
            return health.get("status") == "active"
        # Fallback: key present = available
        return True
    except Exception:
        return False


# ── Admin API key health check ────────────────────────────────────────────────

# Simple TTL cache: {cache_key: (result_dict, expiry_monotonic)}
_KEY_HEALTH_CACHE: Dict[str, Tuple[dict, float]] = {}
_KEY_HEALTH_LOCK  = threading.Lock()
_KEY_HEALTH_TTL   = 300  # 5-minute cache
_ADMIN_API_BASE   = "https://api.anthropic.com/v1"


def check_key_health(*, force_refresh: bool = False) -> Optional[dict]:
    """Check the status of the configured Anthropic API key via Admin API.

    Requires settings.anthropic_admin_api_key AND settings.anthropic_api_key_id.
    Returns None if either is absent (graceful degradation — caller falls back
    to the legacy "key non-empty" check).

    Returns a dict on success or Admin API error:
        {
            "status":           "active" | "inactive" | "archived" | "expired",
            "name":             str,
            "partial_key_hint": str,
            "expires_at":       str (RFC 3339) | None,
            "workspace_id":     str | None,
            "checked_at":       str (ISO 8601 UTC),
            "error":            str | None,   # set when Admin API call failed
        }

    Results are cached for 5 minutes. Use force_refresh=True to bypass cache.
    Never raises.
    """
    try:
        from ..core.config import settings  # noqa: PLC0415
        admin_key = getattr(settings, "anthropic_admin_api_key", None) or ""
        key_id    = getattr(settings, "anthropic_api_key_id",    None) or ""
    except Exception:
        return None

    if not admin_key.strip() or not key_id.strip():
        return None  # Admin API not configured — graceful degradation

    cache_key = key_id
    checked_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    with _KEY_HEALTH_LOCK:
        if not force_refresh and cache_key in _KEY_HEALTH_CACHE:
            cached_result, expiry = _KEY_HEALTH_CACHE[cache_key]
            if time.monotonic() < expiry:
                return cached_result

    try:
        import httpx  # noqa: PLC0415
        url = f"{_ADMIN_API_BASE}/organizations/api_keys/{key_id}"
        headers = {
            "anthropic-version": "2023-06-01",
            "X-Api-Key":         admin_key,
        }
        resp = httpx.get(url, headers=headers, timeout=10.0)
        resp.raise_for_status()
        data = resp.json()

        result: dict = {
            "status":           data.get("status"),
            "name":             data.get("name"),
            "partial_key_hint": data.get("partial_key_hint"),
            "expires_at":       data.get("expires_at"),
            "workspace_id":     data.get("workspace_id"),
            "checked_at":       checked_at,
            "error":            None,
        }
        log.info("[ai_gateway] key health: id=%s status=%s name=%s",
                 key_id, result["status"], result["name"])

    except Exception as exc:
        log.warning("[ai_gateway] Admin API key health check failed: %s", exc)
        result = {
            "status":           None,
            "name":             None,
            "partial_key_hint": None,
            "expires_at":       None,
            "workspace_id":     None,
            "checked_at":       checked_at,
            "error":            str(exc),
        }

    with _KEY_HEALTH_LOCK:
        _KEY_HEALTH_CACHE[cache_key] = (result, time.monotonic() + _KEY_HEALTH_TTL)

    return result


# ── Provider: Cowork stub (Phase 2B) ─────────────────────────────────────────

def _cowork_call(
    *,
    system: str,
    user: str,
    selected_model: str,
    max_tokens: int,
    timeout_s: int,
) -> Tuple[Optional[str], Optional[str]]:
    """Cowork / Claude-first provider call.

    Phase 2B: stub implementation.  Returns (None, "cowork_not_implemented").
    Does NOT make any network calls.
    Does NOT increment the circuit breaker (logical gate, not a network failure).

    Phase 3 will replace this body with real Cowork/Claude API integration.

    Returns:
        (raw_text, error_type) — raw_text is None on any failure/stub.
    """
    log.debug("[ai_gateway] Cowork provider: stub — not yet implemented")
    return None, "cowork_not_implemented"


# ── Provider: Anthropic API ───────────────────────────────────────────────────

def _anthropic_call(
    *,
    api_key: str,
    system: str,
    user: str,
    selected_model: str,
    max_tokens: int,
    max_retries: int,
    timeout_s: int,
    ledger: Any,
) -> Tuple[Optional[str], Optional[int], Optional[int], Optional[float], Optional[str]]:
    """Execute call via Anthropic API with retry logic.

    Returns:
        (raw_text, actual_in, actual_out, actual_cost_val, error_type)
        raw_text is None on failure.
    """
    try:
        import anthropic  # noqa: PLC0415
    except ImportError:
        log.error("[ai_gateway] anthropic package not installed — pip install anthropic")
        return None, None, None, None, "ImportError"

    client = anthropic.Anthropic(api_key=api_key, timeout=float(timeout_s))

    raw_text:        Optional[str]   = None
    actual_in:       Optional[int]   = None
    actual_out:      Optional[int]   = None
    actual_cost_val: Optional[float] = None
    last_exc_type:   Optional[str]   = None

    for attempt in range(max_retries + 1):
        if attempt > 0:
            backoff = 2 ** (attempt - 1)  # 1s, 2s, 4s
            log.info("[ai_gateway] retry %d/%d after %ds", attempt, max_retries, backoff)
            time.sleep(backoff)

        try:
            response = client.messages.create(
                model=selected_model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            raw_text = (response.content[0].text or "").strip()

            # Capture actual usage if reported
            usage = getattr(response, "usage", None)
            if usage:
                actual_in  = getattr(usage, "input_tokens",  None)
                actual_out = getattr(usage, "output_tokens", None)
                if actual_in is not None and actual_out is not None:
                    actual_cost_val = ledger.estimate_cost(selected_model, actual_in, actual_out)

            last_exc_type = None
            _cb_record_success()
            break

        except Exception as exc:
            exc_type = type(exc).__name__
            last_exc_type = exc_type

            retryable = _is_retryable(exc)
            log.warning("[ai_gateway] attempt %d failed (%s): %s", attempt + 1, exc_type, exc)

            if not retryable or attempt >= max_retries:
                _cb_record_failure()
                break

    return raw_text, actual_in, actual_out, actual_cost_val, last_exc_type


# ── Circuit-breaker failure discriminator ─────────────────────────────────────

def _is_cb_failure(error_type: Optional[str]) -> bool:
    """Return True only for real network/API failures that should trip the CB.

    Logical gate outcomes (cowork_not_implemented, budget_exhausted, cb_open,
    disabled, ImportError) must NOT increment the circuit breaker — they signal
    configuration or policy decisions, not external service degradation.
    """
    _LOGICAL_GATES = {
        "cowork_not_implemented",
        "budget_exhausted",
        "cb_open",
        "disabled",
        "ImportError",
    }
    return bool(error_type) and error_type not in _LOGICAL_GATES


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
    - API key missing (and cowork not enabled)
    - Daily budget exceeded
    - Circuit breaker open
    - All retries exhausted
    - Cowork unavailable AND fallback disabled
    - Any other error

    Never raises.
    """
    from . import ai_call_ledger as ledger  # noqa: PLC0415
    from . import ai_redactor as redactor   # noqa: PLC0415

    t_start = time.monotonic()

    # ── Gate 1: config enabled ────────────────────────────────────────────────
    try:
        from ..core.config import settings  # noqa: PLC0415
    except Exception as exc:
        log.error("[ai_gateway] config import failed: %s", exc)
        return None

    if not getattr(settings, "ai_parser_enabled", False):
        log.debug("[ai_gateway] ai_parser_enabled=False — skipping")
        return None

    # Read provider config
    cowork_enabled      = bool(getattr(settings, "ai_cowork_enabled", False))
    cowork_timeout_s    = int(getattr(settings, "ai_cowork_timeout_seconds", 30))
    provider_preference = str(getattr(settings, "ai_provider_preference", _PROVIDER_COWORK))
    fallback_enabled    = bool(getattr(settings, "ai_fallback_enabled", False))

    api_key = getattr(settings, "anthropic_api_key", None) or ""

    # Determine intended provider path
    use_cowork_first = cowork_enabled and (provider_preference == _PROVIDER_COWORK)
    provider_requested = _PROVIDER_COWORK if use_cowork_first else _PROVIDER_ANTHROPIC

    # If not using cowork: Anthropic API key is required
    if not use_cowork_first and not api_key.strip():
        log.debug("[ai_gateway] no API key and cowork not enabled — skipping")
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

    # ── Provider call settings ────────────────────────────────────────────────
    max_retries = max(0, getattr(settings, "ai_gateway_max_retries", 3))
    timeout_s   = getattr(settings, "ai_gateway_timeout_seconds", 30)

    # ── Provider execution ────────────────────────────────────────────────────
    raw_text:         Optional[str]   = None
    actual_in:        Optional[int]   = None
    actual_out:       Optional[int]   = None
    actual_cost_val:  Optional[float] = None
    success                           = False
    error_type:       Optional[str]   = None
    provider_used:    Optional[str]   = None
    fallback_used:    bool            = False

    if use_cowork_first:
        # ── Path A: Cowork primary ────────────────────────────────────────────
        cowork_text, cowork_err = _cowork_call(
            system=system_clean,
            user=user_clean,
            selected_model=selected_model,
            max_tokens=max_tokens,
            timeout_s=cowork_timeout_s,
        )

        if cowork_text is not None:
            raw_text     = cowork_text
            success      = True
            provider_used = _PROVIDER_COWORK
            fallback_used = False
            error_type   = None
        else:
            # Cowork did not return a result
            if not fallback_enabled:
                # No fallback allowed — log and return None
                log.debug("[ai_gateway] cowork returned None; fallback disabled (reason=%s)", cowork_err)
                _ledger_write(
                    ledger=ledger,
                    task_type=task_type, service_name=service_name, object_id=object_id,
                    requested_model=operator_override_model, selected_model=selected_model,
                    model_tier=model_tier, selection_reason=selection_reason,
                    escalation_reason=escalation_reason, confidence_score=confidence_score,
                    p_hash=p_hash, est_in=est_in, est_out=est_out, est_cost=est_cost,
                    actual_in=None, actual_out=None, actual_cost_val=None,
                    latency_ms=int((time.monotonic() - t_start) * 1000),
                    success=False, fallback_reason=cowork_err, error_type=cowork_err,
                    provider_requested=provider_requested, provider_used=None,
                    fallback_used=False,
                )
                return None

            # ── Path A → fallback: Anthropic API ─────────────────────────────
            if not api_key.strip():
                log.debug("[ai_gateway] cowork failed; fallback enabled but no API key")
                _ledger_write(
                    ledger=ledger,
                    task_type=task_type, service_name=service_name, object_id=object_id,
                    requested_model=operator_override_model, selected_model=selected_model,
                    model_tier=model_tier, selection_reason=selection_reason,
                    escalation_reason=escalation_reason, confidence_score=confidence_score,
                    p_hash=p_hash, est_in=est_in, est_out=est_out, est_cost=est_cost,
                    actual_in=None, actual_out=None, actual_cost_val=None,
                    latency_ms=int((time.monotonic() - t_start) * 1000),
                    success=False, fallback_reason="no_api_key", error_type="no_api_key",
                    provider_requested=provider_requested, provider_used=None,
                    fallback_used=True,
                )
                return None

            log.info("[ai_gateway] cowork unavailable (reason=%s); trying Anthropic fallback", cowork_err)
            fallback_used = True
            ant_text, ant_in, ant_out, ant_cost, ant_err = _anthropic_call(
                api_key=api_key,
                system=system_clean,
                user=user_clean,
                selected_model=selected_model,
                max_tokens=max_tokens,
                max_retries=max_retries,
                timeout_s=timeout_s,
                ledger=ledger,
            )
            raw_text        = ant_text
            actual_in       = ant_in
            actual_out      = ant_out
            actual_cost_val = ant_cost
            error_type      = ant_err
            success         = ant_text is not None
            provider_used   = _PROVIDER_ANTHROPIC if success else None

    else:
        # ── Path B: Direct Anthropic (backward-compatible) ────────────────────
        ant_text, ant_in, ant_out, ant_cost, ant_err = _anthropic_call(
            api_key=api_key,
            system=system_clean,
            user=user_clean,
            selected_model=selected_model,
            max_tokens=max_tokens,
            max_retries=max_retries,
            timeout_s=timeout_s,
            ledger=ledger,
        )
        raw_text        = ant_text
        actual_in       = ant_in
        actual_out      = ant_out
        actual_cost_val = ant_cost
        error_type      = ant_err
        success         = ant_text is not None
        provider_used   = _PROVIDER_ANTHROPIC if success else None
        fallback_used   = False

    # ── Ledger write ──────────────────────────────────────────────────────────
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
        provider_requested=provider_requested, provider_used=provider_used,
        fallback_used=fallback_used,
    )

    if success:
        log.info("[ai_gateway] %s/%s OK model=%s provider=%s fallback=%s latency=%dms",
                 service_name, task_type, selected_model, provider_used, fallback_used, latency_ms)
        return raw_text

    log.error("[ai_gateway] %s/%s FAILED model=%s provider_requested=%s",
              service_name, task_type, selected_model, provider_requested)
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
    provider_requested: Optional[str] = None,
    provider_used: Optional[str] = None,
    fallback_used: bool = False,
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
        "provider_requested":      provider_requested,
        "provider_used":           provider_used,
        "fallback_used":           fallback_used,
    })
