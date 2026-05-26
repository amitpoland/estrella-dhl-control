"""
ai_dhl_followup_drafter.py — AI-assisted DHL follow-up body drafting.

Wraps the deterministic dhl_followup_email_builder output with an optional
AI-enhancement pass.  Always falls back to the original deterministic body
if AI is disabled, unavailable, or produces invalid output.

Governance rules (enforced by this module):
  - Flag gate: ai_advisory_llm_enabled must be True (same flag as advisory).
  - Model: ai_advisory_model setting (locked to haiku via operator override).
  - Budget: ai_gateway (same budget ledger as advisory calls).
  - AI output MUST contain the AWB number — if missing, fallback fires.
  - AI MUST NOT invent CIF/duty/customs facts.  Prompt explicitly forbids it.
  - Subject, recipients, attachments: NEVER sourced from AI output.
  - This module is PURE of Lesson-E properties — caller (_process_dhl_followup)
    owns execution-time validation, terminal-state suppression, and send-time
    idempotency via queue_email.  This module only enhances body text.

Lesson K compliance (explicit negative scope in the AI prompt):
  The system prompt names specific forbidden actions to prevent scope drift.

Public API:
    enhance_email_body(audit, batch_id, pkg) -> dict
        Returns {pkg_updates, ai_used, model_used}.
        pkg_updates: dict with keys body_text + body_html (always present,
                     either AI-enhanced or deterministic original).
        ai_used:     True iff AI gateway call succeeded and validation passed.
        model_used:  model name string or None.
        Never raises.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

log = logging.getLogger(__name__)

# Module-level import so tests can patch app.services.ai_dhl_followup_drafter.ai_gateway.
# Mirrors the pattern used in ai_advisory.py (same patchability contract).
try:
    from . import ai_gateway  # noqa: F401
except Exception:  # pragma: no cover
    ai_gateway = None  # type: ignore[assignment]


# ── System prompt (Lesson K: explicit forbidden commands) ─────────────────────

_SYSTEM_PROMPT = """\
You are an import department email assistant for Estrella Jewels Sp. z o.o. Sp. k.,
a Polish jewelry importer. You improve the tone and urgency of outbound follow-up
emails sent to DHL Poland customs teams when documents are overdue.

Rules you MUST follow:
1. DO NOT add, change, or remove the AWB number, CIF value, invoice references,
   or any factual customs information already present.
2. DO NOT claim any new facts about shipment status, customs clearance, or duty.
3. DO NOT change the recipient salutation, sign-off block, or company name.
4. DO NOT use markdown, HTML tags, bullet points, numbered lists, or headers.
5. Return ONLY the improved plain-text email body. No preamble, no explanation.
6. Preserve the same paragraph/section structure as the original — do not merge
   or reorder paragraphs.
7. The AWB number provided in the context MUST appear verbatim in your response.\
"""

_MAX_INPUT_BODY_CHARS = 2000
_MAX_OUTPUT_TOKENS    = 350   # tight budget — body enhancement only
_MIN_OUTPUT_CHARS     = 50    # sanity floor: a coherent sentence is always > 50 chars


# ── Internal helpers ─────────────────────────────────────────────────────────

def _build_user_prompt(original_body: str, awb: str, followup_seq: int) -> str:
    """Build the user-turn prompt for the gateway call."""
    body_excerpt = original_body[:_MAX_INPUT_BODY_CHARS]
    return (
        f"Follow-up number: {followup_seq}\n"
        f"AWB: {awb}\n\n"
        f"Original email body:\n---\n{body_excerpt}\n---\n\n"
        f"Rewrite the above email body to be more urgent and professional while "
        f"preserving all factual information exactly as written. "
        f"The AWB number {awb!r} MUST appear verbatim in your response."
    )


def _validate_ai_output(text: str, awb: str) -> bool:
    """Return True iff the AI response is safe to substitute for the original.

    Validation rules (fail-fast):
      1. Non-empty string.
      2. Length above the sanity floor (_MIN_OUTPUT_CHARS).
      3. If AWB is known, it MUST appear verbatim in the response — the single
         most important factual identifier cannot be lost.
    """
    if not text or not isinstance(text, str):
        return False
    stripped = text.strip()
    if len(stripped) < _MIN_OUTPUT_CHARS:
        log.warning(
            "ai_dhl_followup_drafter: AI output rejected — too short (%d chars)",
            len(stripped),
        )
        return False
    if awb and awb not in stripped:
        log.warning(
            "ai_dhl_followup_drafter: AI output rejected — AWB %r not found in response",
            awb,
        )
        return False
    return True


def _text_to_html(body_text: str) -> str:
    """Wrap plain text in a minimal HTML shell (same format as original builder)."""
    return (
        "<div style='font-family:sans-serif'>"
        "<pre style='white-space:pre-wrap;font-family:Arial,sans-serif'>"
        + body_text
        + "</pre></div>"
    )


# ── Public API ────────────────────────────────────────────────────────────────

def enhance_email_body(
    audit:    Dict[str, Any],
    batch_id: str,
    pkg:      Dict[str, Any],
) -> Dict[str, Any]:
    """
    Optionally enhance the follow-up email body using AI.

    Parameters
    ----------
    audit    : Batch audit dict — used for AWB extraction only, not mutated.
    batch_id : Batch identifier for the AI gateway ledger record.
    pkg      : Output dict from build_dhl_followup_email.  The keys
               ``body_text`` and ``body_html`` are used as the baseline;
               all other keys (to, cc, subject, attachments…) are NOT touched.

    Returns
    -------
    {
        "pkg_updates": {"body_text": str, "body_html": str},
        "ai_used":     bool,
        "model_used":  str | None,
    }

    The ``pkg_updates`` dict always contains the body to use — either
    AI-enhanced (when ai_used=True) or the original deterministic content.
    Callers should update their pkg with:  ``pkg = {**pkg, **result["pkg_updates"]}``

    Never raises.  Any failure produces a fallback result.
    """
    original_body_text = pkg.get("body_text") or ""
    original_body_html = pkg.get("body_html") or ""

    # Extract AWB from audit (same cascade as dhl_followup_email_builder)
    awb: str = (
        audit.get("awb")
        or audit.get("tracking_no")
        or (audit.get("batch_meta") or {}).get("awb")
        or ""
    )
    followup_seq = int(pkg.get("followup_seq") or 1)

    _fallback: Dict[str, Any] = {
        "pkg_updates": {
            "body_text": original_body_text,
            "body_html": original_body_html,
        },
        "ai_used":    False,
        "model_used": None,
    }

    # ── Feature flag + config ─────────────────────────────────────────────────
    try:
        from ..core.config import settings   # noqa: PLC0415
        llm_enabled    = bool(getattr(settings, "ai_advisory_llm_enabled", False))
        selected_model = str(getattr(settings, "ai_advisory_model", ""))
    except Exception as exc:
        log.debug("ai_dhl_followup_drafter: settings load failed: %s", exc)
        return _fallback

    if not llm_enabled:
        return _fallback

    # ── AI gateway call ───────────────────────────────────────────────────────
    try:
        # Reference module-level ai_gateway so test patches work (same pattern
        # as ai_advisory.py).
        gw = ai_gateway
        if gw is None:
            return _fallback
        if not gw.is_available():
            log.debug("ai_dhl_followup_drafter: gateway unavailable — using deterministic body")
            return _fallback

        user_text = _build_user_prompt(original_body_text, awb, followup_seq)
        raw = gw.call(
            system=_SYSTEM_PROMPT,
            user=user_text,
            task_type="dhl_followup_draft",
            service_name="ai_dhl_followup_drafter",
            object_id=batch_id,
            complexity="simple",
            risk_level="low",
            confidence_score=1.0,
            max_tokens=_MAX_OUTPUT_TOKENS,
            operator_override_model=selected_model or None,
        )
    except Exception as exc:
        log.warning(
            "ai_dhl_followup_drafter: ai_gateway.call failed (non-fatal): %s",
            exc,
        )
        return _fallback

    if not raw:
        log.debug("ai_dhl_followup_drafter: gateway returned empty — using deterministic body")
        return _fallback

    ai_text = raw.strip()

    # ── Validation ────────────────────────────────────────────────────────────
    if not _validate_ai_output(ai_text, awb):
        return _fallback

    return {
        "pkg_updates": {
            "body_text": ai_text,
            "body_html": _text_to_html(ai_text),
        },
        "ai_used":    True,
        "model_used": selected_model or None,
    }
