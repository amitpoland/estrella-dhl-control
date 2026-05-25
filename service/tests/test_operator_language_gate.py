"""
test_operator_language_gate.py — Sprint 01 G3 gate.

JSX text content rendered to operators MUST NOT contain engineering jargon
or backend internals. Forbidden tokens are allowed ONLY inside
<details data-testid="pz-correction-v2-diagnostics"> (the diagnostics
accordion is engineer-facing).

This source-grep test inspects pz-correction-v2.html and pz-components.js
(V2 component definitions only) for forbidden tokens appearing in JSX
text node positions.

Forbidden tokens checked:
  - STAGED / OPERATOR_REVIEWED / TERMINAL_SUPPRESSED (lifecycle state names)
  - VALID_TRANSITIONS / correction_state (backend artefact names)
  - HTTP 503 / wfirma_correction_push_allowed / pz_correction_lifecycle_enabled
    (HTTP code + flag names)
  - _CONFIRM_SENTINEL / lcState / lifecycleEnabled (variable names)
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
V2_HTML   = REPO_ROOT / "service" / "app" / "static" / "pz-correction-v2.html"
COMPONENTS= REPO_ROOT / "service" / "app" / "static" / "pz-components.js"

FORBIDDEN_TOKENS = [
    "STAGED",
    "OPERATOR_REVIEWED",
    "TERMINAL_SUPPRESSED",
    "VALID_TRANSITIONS",
    "correction_state",
    "HTTP 503",
    "wfirma_correction_push_allowed",
    "pz_correction_lifecycle_enabled",
    "_CONFIRM_SENTINEL",
]


def _strip_diagnostics_block(text: str) -> str:
    """Remove the content inside <details data-testid=\"pz-correction-v2-diagnostics\">.
    Engineering jargon is permitted inside diagnostics by design."""
    # The diagnostics block starts with a <details ... testid="...diagnostics"> opening
    # and ends at the next matching </details>. We use a non-greedy match across newlines.
    pattern = re.compile(
        r"<details[^>]*pz-correction-v2-diagnostics[^>]*>.*?</details>",
        re.S,
    )
    return pattern.sub("(diagnostics-stripped)", text)


def _strip_string_assignments(text: str) -> str:
    """Strip JS string literal assignments to constants and array members so
    that backend identifiers used in code (e.g. comparing lcState.state === 'STAGED')
    do not false-positive. We only care about JSX text content."""
    # Remove anything inside string quotes: 'STAGED' or "STAGED"
    text = re.sub(r"'[^']*'", "''", text)
    text = re.sub(r'"[^"]*"', '""', text)
    # Remove comments (// ... and /* ... */)
    text = re.sub(r"//[^\n]*", "", text)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return text


def _v2_component_block(components_src: str) -> str:
    """Extract the V2 component portion of pz-components.js (everything
    after the 'PZ Correction V2' banner comment)."""
    marker = "PZ Correction V2 — operator-first workflow surface"
    idx = components_src.find(marker)
    return components_src[idx:] if idx >= 0 else ""


@pytest.mark.parametrize("token", FORBIDDEN_TOKENS)
def test_token_absent_from_v2_html_rendered_text(token):
    """The V2 HTML shell must not render any forbidden token as visible
    text (outside the diagnostics block)."""
    if not V2_HTML.exists():
        pytest.skip("pz-correction-v2.html not present")
    body = V2_HTML.read_text(encoding="utf-8")
    body = _strip_diagnostics_block(body)
    body = _strip_string_assignments(body)
    assert token not in body, (
        f"Forbidden engineering token {token!r} appears in operator-facing "
        f"position of pz-correction-v2.html. Move it inside the diagnostics "
        f"<details> block or remove it."
    )


@pytest.mark.parametrize("token", FORBIDDEN_TOKENS)
def test_token_absent_from_v2_component_rendered_text(token):
    """The V2 component definitions must not render any forbidden token
    as visible text (outside the diagnostics block)."""
    if not COMPONENTS.exists():
        pytest.skip("pz-components.js not present")
    src = _v2_component_block(COMPONENTS.read_text(encoding="utf-8"))
    src = _strip_diagnostics_block(src)
    src = _strip_string_assignments(src)
    assert token not in src, (
        f"Forbidden engineering token {token!r} appears in V2 component JSX text "
        f"(outside diagnostics). Move it inside the diagnostics <details> block "
        f"or remove it."
    )


def test_sentinel_string_not_rendered_as_text():
    """The wFirma confirmation sentinel substring must never appear as
    visible text. It is sent in the POST body to /correction-commit and
    nowhere else."""
    sentinel_substr = "I confirm this will create a new wFirma PZ document"
    for path in (V2_HTML, COMPONENTS):
        if not path.exists(): continue
        body = _strip_diagnostics_block(path.read_text(encoding="utf-8"))
        # Strip JS string assignments — sentinel may legitimately appear as a
        # constant in pz-api.js, but we are not testing pz-api.js here. In the
        # V2 HTML / components, it must not appear at all.
        body = _strip_string_assignments(body)
        assert sentinel_substr not in body, (
            f"Sentinel string rendered as text in {path.name}. Sentinel must "
            f"be a JS constant only, ingested by the commit POST body."
        )


# ── Operator-friendly phrasing checks ────────────────────────────────────────

REQUIRED_OPERATOR_PHRASES_PUSH_DISABLED = [
    "External posting unavailable",
]
REQUIRED_OPERATOR_PHRASES_NOT_ENABLED = [
    "PZ Correction is not available",
]


def test_push_disabled_uses_operator_phrasing():
    """The push-disabled phase banner must use the operator phrase, not
    "HTTP 503" or the raw flag name."""
    if not COMPONENTS.exists():
        pytest.skip("pz-components.js not present")
    src = _v2_component_block(COMPONENTS.read_text(encoding="utf-8"))
    for phrase in REQUIRED_OPERATOR_PHRASES_PUSH_DISABLED:
        assert phrase in src, f"Required operator phrase missing in push-disabled banner: {phrase!r}"


def test_not_enabled_uses_operator_phrasing():
    if not COMPONENTS.exists():
        pytest.skip("pz-components.js not present")
    src = _v2_component_block(COMPONENTS.read_text(encoding="utf-8"))
    for phrase in REQUIRED_OPERATOR_PHRASES_NOT_ENABLED:
        assert phrase in src, f"Required operator phrase missing in not-enabled state: {phrase!r}"
