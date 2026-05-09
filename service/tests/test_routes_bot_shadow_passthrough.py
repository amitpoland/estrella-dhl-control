"""
test_routes_bot_shadow_passthrough.py

Phase G — verify the audit-hardening shadow telemetry pass-through
through routes_bot.post_to_channel:

  * routes_bot extracts result.get("shadow_status") and
    result.get("shadow_score") locally.
  * The cliq_service.build_success_message(...) call site passes
    audit_shadow_status= and audit_shadow_score= kwargs.
  * The BLOCKED-path raw-string-formatting branch does NOT mention
    `shadow_status` or `audit_shadow_status` — preserves the legacy
    BLOCKED Cliq output.
  * routes_bot does NOT set AUDIT_HARDENING_ENABLED or
    AUDIT_HARDENING_SHADOW_NOTIFY anywhere in code.
  * Regression sentinels:
      - audit_agent.py still emits shadow_status / shadow_score /
        shadow_blocked on its return surface
      - cliq_service.build_success_message signature still accepts
        audit_shadow_status and audit_shadow_score kwargs

Pure source-level grep. No HTTP, no Cliq calls.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest


_SERVICE = Path(__file__).resolve().parents[1]
_REPO    = _SERVICE.parent

_ROUTES_BOT     = _SERVICE / "app" / "api" / "routes_bot.py"
_CLIQ_SERVICE   = _SERVICE / "app" / "services" / "cliq_service.py"
_AUDIT_AGENT    = _REPO    / "audit_agent.py"


@pytest.fixture(scope="module")
def routes_bot_src() -> str:
    return _ROUTES_BOT.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def cliq_service_src() -> str:
    return _CLIQ_SERVICE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def audit_agent_src() -> str:
    return _AUDIT_AGENT.read_text(encoding="utf-8")


# ──────────────────────────────────────────────────────────────────────
# 1. routes_bot reads result.get("shadow_status")
# ──────────────────────────────────────────────────────────────────────

def test_routes_bot_extracts_shadow_status(routes_bot_src: str) -> None:
    pattern = re.compile(r'result\.get\(\s*[\'"]shadow_status[\'"]\s*\)')
    assert pattern.search(routes_bot_src), (
        "routes_bot.py does not extract result.get(\"shadow_status\"). "
        "Phase G must surface the shadow telemetry produced by "
        "audit_agent.build_audit_report."
    )


# ──────────────────────────────────────────────────────────────────────
# 2. routes_bot reads result.get("shadow_score")
# ──────────────────────────────────────────────────────────────────────

def test_routes_bot_extracts_shadow_score(routes_bot_src: str) -> None:
    pattern = re.compile(r'result\.get\(\s*[\'"]shadow_score[\'"]\s*\)')
    assert pattern.search(routes_bot_src), (
        "routes_bot.py does not extract result.get(\"shadow_score\"). "
        "Phase G must surface the shadow telemetry produced by "
        "audit_agent.build_audit_report."
    )


# ──────────────────────────────────────────────────────────────────────
# 3. The build_success_message(...) call passes audit_shadow_status=
# ──────────────────────────────────────────────────────────────────────

def test_build_success_message_passes_audit_shadow_status(routes_bot_src: str) -> None:
    """
    Find the cliq_service.build_success_message(...) invocation and
    confirm the call's argument list contains an `audit_shadow_status=`
    keyword argument. We don't pin the exact value expression — only
    that the kwarg is present.
    """
    # Slice from the build_success_message call to its closing `)`
    # by tracking parenthesis depth.
    call_start = re.search(
        r"cliq_service\.build_success_message\s*\(", routes_bot_src
    )
    assert call_start, (
        "cliq_service.build_success_message(...) call site not found in "
        "routes_bot.py. Cannot verify shadow kwarg pass-through."
    )
    start = call_start.end()
    depth = 1
    i = start
    while i < len(routes_bot_src) and depth > 0:
        if routes_bot_src[i] == "(":
            depth += 1
        elif routes_bot_src[i] == ")":
            depth -= 1
        i += 1
    call_body = routes_bot_src[start:i]
    assert "audit_shadow_status" in call_body and "=" in call_body, (
        "cliq_service.build_success_message(...) call does not pass "
        "audit_shadow_status= kwarg. Phase G must wire shadow telemetry "
        "into the success-path Cliq message."
    )


# ──────────────────────────────────────────────────────────────────────
# 4. The build_success_message(...) call passes audit_shadow_score=
# ──────────────────────────────────────────────────────────────────────

def test_build_success_message_passes_audit_shadow_score(routes_bot_src: str) -> None:
    call_start = re.search(
        r"cliq_service\.build_success_message\s*\(", routes_bot_src
    )
    assert call_start, "build_success_message call site not found."
    start = call_start.end()
    depth = 1
    i = start
    while i < len(routes_bot_src) and depth > 0:
        if routes_bot_src[i] == "(":
            depth += 1
        elif routes_bot_src[i] == ")":
            depth -= 1
        i += 1
    call_body = routes_bot_src[start:i]
    assert "audit_shadow_score" in call_body, (
        "cliq_service.build_success_message(...) call does not pass "
        "audit_shadow_score= kwarg."
    )


# ──────────────────────────────────────────────────────────────────────
# 5. BLOCKED-path branch does NOT mention shadow_status or
#    audit_shadow_status — legacy preserved
# ──────────────────────────────────────────────────────────────────────

def test_blocked_path_does_not_mention_shadow(routes_bot_src: str) -> None:
    """
    Slice the BLOCKED-message branch (the
    `if failed_keys or amendment_flags:` block leading up to
    `else: text = cliq_service.build_success_message(...)`) and confirm
    no `shadow_status` or `audit_shadow_status` reference appears.
    Phase G deliberately leaves the BLOCKED raw-string message alone.
    """
    blocked_start = re.search(
        r"if\s+failed_keys\s+or\s+amendment_flags\s*:", routes_bot_src
    )
    assert blocked_start, (
        "Could not find the `if failed_keys or amendment_flags:` BLOCKED "
        "branch in routes_bot.py."
    )
    # Find the next `else:` at the same indentation level. The simplest
    # heuristic: walk forward to the next `        else:` (8 spaces).
    after = routes_bot_src[blocked_start.end():]
    else_match = re.search(r"\n\s{8}else\s*:", after)
    assert else_match, (
        "Could not locate the matching `else:` for the BLOCKED branch."
    )
    branch_body = after[: else_match.start()]
    assert "shadow_status" not in branch_body, (
        "BLOCKED-path branch references `shadow_status`. Phase G must NOT "
        "modify the BLOCKED raw-string message; preserve legacy Cliq "
        "output."
    )
    assert "audit_shadow_status" not in branch_body, (
        "BLOCKED-path branch references `audit_shadow_status`. Phase G "
        "must NOT modify the BLOCKED branch."
    )


# ──────────────────────────────────────────────────────────────────────
# 6. routes_bot does NOT enable either env flag
# ──────────────────────────────────────────────────────────────────────

ENV_FLAGS = ["AUDIT_HARDENING_ENABLED", "AUDIT_HARDENING_SHADOW_NOTIFY"]


@pytest.mark.parametrize("flag", ENV_FLAGS)
def test_routes_bot_does_not_set_env_flag(routes_bot_src: str, flag: str) -> None:
    """
    routes_bot.py must not assign or mutate AUDIT_HARDENING_* env vars.
    Both flags are operator-controlled. Either of these patterns would
    fail: os.environ["FLAG"] = ..., os.environ.setdefault("FLAG", ...),
    os.environ.update({"FLAG": ...}).
    """
    assignment_pattern = re.compile(
        rf'os\.environ\s*\[\s*[\'"]{flag}[\'"]\s*\]\s*='
    )
    setdefault_pattern = re.compile(
        rf'os\.environ\.setdefault\(\s*[\'"]{flag}[\'"]'
    )
    update_pattern = re.compile(
        rf'os\.environ\.update\([^)]*[\'"]{flag}[\'"]'
    )
    monkeypatch_pattern = re.compile(
        rf'monkeypatch\.setenv\(\s*[\'"]{flag}[\'"]'
    )
    assert not assignment_pattern.search(routes_bot_src), (
        f"routes_bot.py assigns os.environ[{flag!r}] — operator-controlled "
        f"env vars must not be set from code."
    )
    assert not setdefault_pattern.search(routes_bot_src), (
        f"routes_bot.py uses os.environ.setdefault({flag!r}, …) — "
        f"operator-controlled env vars must not be set from code."
    )
    assert not update_pattern.search(routes_bot_src), (
        f"routes_bot.py uses os.environ.update({{...{flag!r}...}}) — "
        f"operator-controlled env vars must not be set from code."
    )
    assert not monkeypatch_pattern.search(routes_bot_src), (
        f"routes_bot.py uses monkeypatch.setenv({flag!r}, …) — that "
        f"belongs in tests, not in production source."
    )


# ──────────────────────────────────────────────────────────────────────
# 7. Regression sentinel: audit_agent still emits shadow_status /
#    shadow_score / shadow_blocked on its return surface
# ──────────────────────────────────────────────────────────────────────

SHADOW_KEYS = ["shadow_status", "shadow_score", "shadow_blocked"]


@pytest.mark.parametrize("key", SHADOW_KEYS)
def test_audit_agent_still_emits_shadow_keys(audit_agent_src: str, key: str) -> None:
    """
    audit_agent.build_audit_report must still emit shadow_status /
    shadow_score / shadow_blocked when the underlying score_batch
    returns them. Phase G is downstream of this — if audit_agent stops
    forwarding, routes_bot's extracts return None and the shadow line
    silently disappears.
    """
    assignment_pattern = re.compile(
        rf'(out|audit_data)\[\s*[\'"]{key}[\'"]\s*\]\s*='
    )
    assert assignment_pattern.search(audit_agent_src), (
        f"audit_agent.py no longer assigns {key!r} on out[…] or "
        f"audit_data[…]. Phase G's shadow pass-through depends on this "
        f"upstream emission."
    )


# ──────────────────────────────────────────────────────────────────────
# 8. Regression sentinel: cliq_service.build_success_message still
#    accepts the shadow kwargs
# ──────────────────────────────────────────────────────────────────────

SHADOW_KWARGS = ["audit_shadow_status", "audit_shadow_score"]


@pytest.mark.parametrize("kwarg", SHADOW_KWARGS)
def test_cliq_service_signature_keeps_shadow_kwargs(
    cliq_service_src: str, kwarg: str
) -> None:
    """
    cliq_service.build_success_message must continue to accept the two
    shadow kwargs. Without these, Phase G's pass-through wouldn't
    reach the `[SHADOW]` line that the operator sees.
    """
    # Slice the function definition: from `def build_success_message(`
    # to the matching closing `)`.
    fn_start = re.search(r"def\s+build_success_message\s*\(", cliq_service_src)
    assert fn_start, (
        "cliq_service.build_success_message function definition not "
        "found in cliq_service.py."
    )
    start = fn_start.end()
    depth = 1
    i = start
    while i < len(cliq_service_src) and depth > 0:
        if cliq_service_src[i] == "(":
            depth += 1
        elif cliq_service_src[i] == ")":
            depth -= 1
        i += 1
    sig_body = cliq_service_src[start:i]
    assert kwarg in sig_body, (
        f"cliq_service.build_success_message no longer accepts "
        f"{kwarg!r}. Phase G's wire is broken without it. Restore the "
        f"kwarg in cliq_service.py."
    )
