"""
test_ai_gateway_violation.py — Gateway violation rule enforcement.

Source-grep contract tests: prove that no code outside ai_gateway.py
(and the explicitly exempted zones) creates Anthropic clients directly,
hard-codes model names, or performs token accounting.

These tests are structural — they grep actual source files at import time.
No mocking, no stubs. A failing test means a gateway violation was committed.

Exempted zones (must not be flagged as violations):
  - service/app/services/ai_gateway.py          (the authority itself)
  - service/app/core/config.py                   (model fallback config field only)
  - service/tests/                               (tests may reference model names)
  - service/docs/                                (documentation)
  - .claude/                                     (agent/memory files)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_SVC = Path(__file__).resolve().parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

_APP = _SVC / "app"
_TESTS = _SVC / "tests"

# ── Helpers ───────────────────────────────────────────────────────────────────

def _py_files_under(root: Path, exclude: list[Path] | None = None) -> list[Path]:
    """Return all .py files under root, excluding listed paths."""
    exclude = exclude or []
    result = []
    for p in root.rglob("*.py"):
        if any(p == ex or str(p).startswith(str(ex)) for ex in exclude):
            continue
        result.append(p)
    return result


def _grep(files: list[Path], pattern: str, flags: int = 0) -> list[tuple[Path, int, str]]:
    """
    Search files for pattern. Returns (file, line_no, line) for each match.
    """
    rx = re.compile(pattern, flags)
    hits = []
    for f in files:
        try:
            for i, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if rx.search(line):
                    hits.append((f, i, line.strip()))
        except Exception:
            pass
    return hits


def _rel(p: Path) -> str:
    return str(p.relative_to(_SVC))


# ── Files under scrutiny ──────────────────────────────────────────────────────

# Every .py file in app/ EXCEPT ai_gateway.py itself
_GATEWAY_FILE = _APP / "services" / "ai_gateway.py"

_APP_FILES_EXCLUDING_GATEWAY = _py_files_under(
    _APP,
    exclude=[_GATEWAY_FILE],
)


# ── Rule 1: No direct anthropic.Anthropic() instantiation ────────────────────

def test_no_direct_anthropic_client_outside_gateway():
    """
    No app/ file (outside ai_gateway.py) may call anthropic.Anthropic().
    anthropic.AsyncAnthropic() is also forbidden.
    """
    hits = _grep(
        _APP_FILES_EXCLUDING_GATEWAY,
        r"anthropic\s*\.\s*(Async)?Anthropic\s*\(",
    )
    violations = [
        f"  {_rel(f)}:{ln}  →  {line}"
        for f, ln, line in hits
    ]
    assert not violations, (
        "Gateway violation — direct Anthropic client construction outside ai_gateway.py:\n"
        + "\n".join(violations)
    )


def test_no_bare_anthropic_import_outside_gateway():
    """
    No app/ file (outside ai_gateway.py) may do `import anthropic` as a top-level
    (non-conditional, non-TYPE_CHECKING) import.

    This catches `import anthropic` at module level. Conditional imports inside
    try/except ImportError blocks are allowed (dependency availability checks).
    """
    # Look for `import anthropic` NOT inside a try/except block.
    # Simple heuristic: flag lines that are NOT indented AND contain `import anthropic`.
    hits = _grep(
        _APP_FILES_EXCLUDING_GATEWAY,
        r"^import anthropic\b",
    )
    violations = [
        f"  {_rel(f)}:{ln}  →  {line}"
        for f, ln, line in hits
    ]
    assert not violations, (
        "Gateway violation — bare `import anthropic` at module level outside ai_gateway.py:\n"
        + "\n".join(violations)
    )


# ── Rule 2: No hard-coded model name strings outside gateway/config/tests ─────

_MODEL_STRINGS = [
    "claude-haiku-4-5",
    "claude-sonnet-4-6",
    "claude-opus-4-7",
]

# Files allowed to contain model name strings
# ai_call_ledger.py is AI infrastructure — it holds the cost rate table indexed by model name.
_MODEL_STRING_EXEMPT = [
    _GATEWAY_FILE,
    _APP / "core" / "config.py",
    _APP / "services" / "ai_call_ledger.py",
]

_APP_FILES_EXCLUDING_MODEL_EXEMPT = _py_files_under(
    _APP,
    exclude=_MODEL_STRING_EXEMPT,
)


def test_no_hardcoded_haiku_outside_gateway():
    hits = _grep(
        _APP_FILES_EXCLUDING_MODEL_EXEMPT,
        r"claude-haiku-4-5",
    )
    violations = [f"  {_rel(f)}:{ln}  →  {line}" for f, ln, line in hits]
    assert not violations, (
        "Gateway violation — hard-coded 'claude-haiku-4-5' outside ai_gateway.py/config.py:\n"
        + "\n".join(violations)
    )


def test_no_hardcoded_sonnet_outside_gateway():
    hits = _grep(
        _APP_FILES_EXCLUDING_MODEL_EXEMPT,
        r"claude-sonnet-4-6",
    )
    violations = [f"  {_rel(f)}:{ln}  →  {line}" for f, ln, line in hits]
    assert not violations, (
        "Gateway violation — hard-coded 'claude-sonnet-4-6' outside ai_gateway.py/config.py:\n"
        + "\n".join(violations)
    )


def test_no_hardcoded_opus_outside_gateway():
    hits = _grep(
        _APP_FILES_EXCLUDING_MODEL_EXEMPT,
        r"claude-opus-4-7",
    )
    violations = [f"  {_rel(f)}:{ln}  →  {line}" for f, ln, line in hits]
    assert not violations, (
        "Gateway violation — hard-coded 'claude-opus-4-7' outside ai_gateway.py/config.py:\n"
        + "\n".join(violations)
    )


# ── Rule 3: No retry logic for AI calls outside gateway ──────────────────────

def test_no_ai_retry_loop_outside_gateway():
    """
    Retry logic for AI calls (exponential backoff loops targeting Anthropic errors)
    must live only in ai_gateway.py.

    We detect the combination of RateLimitError + sleep in the same file,
    which is the classic DIY retry pattern.
    """
    suspects = []
    for f in _APP_FILES_EXCLUDING_GATEWAY:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        has_rate_limit = bool(re.search(r"RateLimitError", text))
        has_sleep = bool(re.search(r"time\.sleep\s*\(", text))
        if has_rate_limit and has_sleep:
            suspects.append(_rel(f))

    assert not suspects, (
        "Gateway violation — DIY AI retry (RateLimitError + sleep) outside ai_gateway.py:\n"
        + "\n".join(f"  {s}" for s in suspects)
    )


# ── Rule 4: No token accounting outside gateway/ledger ───────────────────────

_LEDGER_FILE = _APP / "services" / "ai_call_ledger.py"

_APP_FILES_EXCLUDING_AI_INFRA = _py_files_under(
    _APP,
    exclude=[_GATEWAY_FILE, _LEDGER_FILE],
)


def test_no_token_accounting_outside_gateway():
    """
    No file outside ai_gateway.py and ai_call_ledger.py may read
    response.usage.input_tokens / output_tokens — that's token accounting
    which belongs to the gateway layer.
    """
    hits = _grep(
        _APP_FILES_EXCLUDING_AI_INFRA,
        r"\.usage\s*\.\s*(input_tokens|output_tokens)",
    )
    violations = [f"  {_rel(f)}:{ln}  →  {line}" for f, ln, line in hits]
    assert not violations, (
        "Gateway violation — token accounting outside gateway/ledger:\n"
        + "\n".join(violations)
    )


# ── Rule 5: Migrated services use gateway, not anthropic directly ─────────────

def test_customs_parser_uses_gateway():
    """ai_customs_parser.py must import ai_gateway and call ai_gateway.call()."""
    parser = _APP / "services" / "ai_customs_parser.py"
    text = parser.read_text(encoding="utf-8")
    assert "ai_gateway" in text, (
        "ai_customs_parser.py does not reference ai_gateway — migration incomplete"
    )
    assert "ai_gateway.call(" in text, (
        "ai_customs_parser.py does not call ai_gateway.call() — migration incomplete"
    )


def test_customs_evidence_uses_gateway():
    """ai_customs_evidence.py must import ai_gateway and call ai_gateway.call()."""
    evidence = _APP / "services" / "ai_customs_evidence.py"
    text = evidence.read_text(encoding="utf-8")
    assert "ai_gateway" in text, (
        "ai_customs_evidence.py does not reference ai_gateway — migration incomplete"
    )
    assert "ai_gateway.call(" in text, (
        "ai_customs_evidence.py does not call ai_gateway.call() — migration incomplete"
    )


def test_customs_parser_no_direct_client():
    """ai_customs_parser.py must NOT create an Anthropic client directly."""
    parser = _APP / "services" / "ai_customs_parser.py"
    text = parser.read_text(encoding="utf-8")
    assert "anthropic.Anthropic(" not in text, (
        "ai_customs_parser.py still creates anthropic.Anthropic() directly — migration incomplete"
    )
    assert "AsyncAnthropic(" not in text, (
        "ai_customs_parser.py still creates AsyncAnthropic() — migration incomplete"
    )


def test_customs_evidence_no_direct_client():
    """ai_customs_evidence.py must NOT create an Anthropic client directly."""
    evidence = _APP / "services" / "ai_customs_evidence.py"
    text = evidence.read_text(encoding="utf-8")
    assert "anthropic.Anthropic(" not in text, (
        "ai_customs_evidence.py still creates anthropic.Anthropic() directly — migration incomplete"
    )
    assert "AsyncAnthropic(" not in text, (
        "ai_customs_evidence.py still creates AsyncAnthropic() — migration incomplete"
    )


# ── Rule 6: Gateway file itself has the authority ────────────────────────────

def test_gateway_file_exists():
    """ai_gateway.py must exist — it is the single AI execution authority."""
    assert _GATEWAY_FILE.exists(), (
        f"ai_gateway.py not found at {_GATEWAY_FILE} — Phase 3 Proper not deployed"
    )


def test_gateway_exports_call_function():
    """ai_gateway.py must export a callable named 'call'."""
    text = _GATEWAY_FILE.read_text(encoding="utf-8")
    assert re.search(r"^def call\s*\(", text, re.MULTILINE), (
        "ai_gateway.py does not define a top-level 'call' function"
    )


def test_gateway_exports_is_available():
    """ai_gateway.py must export 'is_available'."""
    text = _GATEWAY_FILE.read_text(encoding="utf-8")
    assert re.search(r"^def is_available\s*\(", text, re.MULTILINE), (
        "ai_gateway.py does not define a top-level 'is_available' function"
    )


def test_gateway_contains_circuit_breaker():
    """ai_gateway.py must implement the circuit breaker."""
    text = _GATEWAY_FILE.read_text(encoding="utf-8")
    assert "_CB_THRESHOLD" in text, "ai_gateway.py missing _CB_THRESHOLD constant"
    assert "_cb_is_open" in text or "cb_is_open" in text, (
        "ai_gateway.py missing circuit breaker open-check function"
    )


def test_ledger_file_exists():
    """ai_call_ledger.py must exist."""
    assert _LEDGER_FILE.exists(), (
        f"ai_call_ledger.py not found at {_LEDGER_FILE}"
    )


def test_redactor_file_exists():
    """ai_redactor.py must exist."""
    redactor = _APP / "services" / "ai_redactor.py"
    assert redactor.exists(), (
        f"ai_redactor.py not found at {redactor}"
    )
