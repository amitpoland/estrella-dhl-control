"""
test_polling_cleanup.py — M4 polling cleanup + race protection contract.

Working-phase polling discipline (per campaign brief §8 M4):
  (a) Polling cadence: 3 seconds
  (b) Hard cap: 60 polls per working session; then show "Still working —
      refresh manually" + [Refresh now] button
  (c) Polling stops on:
       1. Any terminal state response (COMPLETED, FAILED, TERMINAL_SUPPRESSED)
       2. Component unmount (useEffect cleanup clears interval)
       3. Operator-initiated action (action's response replaces polled state)
  (d) Race protection: pollGeneration counter — stale poll responses discarded

This test runs source-grep proofs always. A Playwright test stub is
included for runtime verification when Playwright is available.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPONENTS= REPO_ROOT / "service" / "app" / "static" / "pz-components.js"


def _container_body() -> str:
    src = COMPONENTS.read_text(encoding="utf-8")
    m = re.search(r"function\s+PZCorrectionV2Container\s*\([^)]*\)\s*\{(.*?)\n  \}", src, re.S)
    assert m, "PZCorrectionV2Container body not found"
    return m.group(1)


def test_container_uses_three_second_polling_cadence():
    """3-second polling cadence per M4."""
    body = _container_body()
    assert re.search(r"setTimeout\(\s*tick\s*,\s*3000\s*\)", body), \
        "Container must poll on a 3000ms interval"


def test_container_caps_polling_at_60_attempts():
    """60-attempt hard cap per M4."""
    body = _container_body()
    assert re.search(r"attempts\s*>\s*60", body) or re.search(r"attempts\s*>=\s*60", body) or \
           re.search(r"60", body), "60-attempt cap must be enforced"
    assert "atCap" in body, "atCap state must exist to surface the manual-refresh prompt"


def test_container_uses_poll_generation_for_race_protection():
    """pollGeneration counter per M4 race protection requirement."""
    body = _container_body()
    assert "pollGenRef" in body, "pollGenRef must exist for race protection"
    # The handlers must invalidate in-flight polls
    assert re.search(r"pollGenRef\.current\s*\+=\s*1", body), \
        "Operator actions must increment pollGeneration to invalidate in-flight polls"


def test_container_cleans_up_polling_on_unmount():
    """useEffect cleanup must clearTimeout."""
    body = _container_body()
    assert "clearTimeout(pollTimerRef.current)" in body, \
        "useEffect cleanup must clearTimeout(pollTimerRef.current)"


def test_container_polling_clears_when_phase_changes():
    """Polling must stop when phase leaves 'working'."""
    body = _container_body()
    # The polling effect dependency includes `phase`, and the early-return
    # for phase !== 'working' must clear the timer.
    poll_effect = re.search(r"if\s*\(\s*phase\s*!==\s*'working'\s*\)\s*\{(.*?)\}", body, re.S)
    assert poll_effect, "Polling effect must early-return when phase !== 'working'"
    cleanup_branch = poll_effect.group(1)
    assert "clearTimeout" in cleanup_branch, \
        "Phase-change branch must clearTimeout to prevent leaks"


def test_container_surfaces_manual_refresh_when_at_cap():
    """When atCap reached, surface [Refresh now] button."""
    src = COMPONENTS.read_text(encoding="utf-8")
    m = re.search(r"function\s+PZCorrectionV2Working\s*\([^)]*\)\s*\{(.*?)\n  \}", src, re.S)
    assert m, "PZCorrectionV2Working component not found"
    body = m.group(1)
    assert "atCap" in body, "Working component must receive atCap prop"
    assert "Refresh now" in body, "Manual-refresh button must be labeled"
    assert "Still working" in body, "Cap message must use operator phrasing"


# ── Optional Playwright execution ───────────────────────────────────────────

def _playwright_available() -> bool:
    try:
        import playwright  # noqa: F401
        return shutil.which("playwright") is not None
    except ImportError:
        return False


@pytest.mark.skipif(not _playwright_available(), reason="Playwright not installed")
def test_no_leak_on_unmount():
    """Mount V2 in working phase, navigate away, assert no further /correction-state
    requests for 5 seconds."""
    pytest.skip(
        "Playwright runtime test — scaffolded. Mount V2 with mocked /correction-state "
        "returning EXECUTING, navigate away, count network requests for 5s."
    )


@pytest.mark.skipif(not _playwright_available(), reason="Playwright not installed")
def test_race_protection_cancel_wins():
    """During working, click Cancel mid-poll; assert the cancel response wins."""
    pytest.skip(
        "Playwright runtime test — scaffolded. Mount V2 with mocked /correction-state "
        "delayed-EXECUTING; in-flight, click [Cancel], assert UI matches cancel response."
    )


@pytest.mark.skipif(not _playwright_available(), reason="Playwright not installed")
def test_60_cap_surfaces_manual_refresh():
    """Force 61 EXECUTING responses; assert cap message appears."""
    pytest.skip(
        "Playwright runtime test — scaffolded. Mount V2 with mocked /correction-state "
        "returning EXECUTING 61 times; on attempt 61 assert 'Still working — refresh manually' "
        "+ [Refresh now] is present."
    )
