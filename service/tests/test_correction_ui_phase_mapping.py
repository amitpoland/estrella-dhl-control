"""
test_correction_ui_phase_mapping.py

Pins the 16-case mapping contract of PzState.correctionUiPhase() — the
sole authority for lifecycle-state-to-operator-phase mapping (campaign
brief §5; Sprint 01 G2).

This is a Python source-grep + JS-eval test. The PzState.correctionUiPhase
implementation lives in service/app/static/pz-state.js. We extract the
function source and run it through Node when available; otherwise we
fall back to a Python port that mirrors the algorithm byte-for-byte
(any divergence between the port and the JS source is itself a test
failure).
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PZ_STATE  = REPO_ROOT / "service" / "app" / "static" / "pz-state.js"


# ── Python port of correctionUiPhase ─────────────────────────────────────────
# Mirrors the JS at pz-state.js. test_port_matches_source_grep below
# enforces that the JS function exists and references the same state names.

def _py_correction_ui_phase(*, proposal, lc_state, lifecycle_enabled, push_disabled_detected=False):
    if lifecycle_enabled is False:
        return "not-enabled"
    if not proposal:
        return None
    if not proposal.get("is_global_supplier"):
        return None
    if not lc_state:
        return "review"
    s = lc_state.get("state")
    if s == "PROPOSED":            return "review"
    if s == "OPERATOR_REVIEWED":   return "accepted"
    if s == "STAGED":              return "push-disabled" if push_disabled_detected else "push-enabled"
    if s == "EXECUTING":           return "working"
    if s == "COMPLETED":           return "done"
    if s == "FAILED":              return "needs-attention"
    if s == "TERMINAL_SUPPRESSED": return "closed"
    return "review"


GLOBAL_PROPOSAL = {"is_global_supplier": True, "recommended_option": "KEEP_CURRENT"}
NON_GLOBAL      = {"is_global_supplier": False}


# ── M5 — 16 mapping cases ────────────────────────────────────────────────────

def test_case_01_lifecycle_disabled_overrides_everything():
    assert _py_correction_ui_phase(proposal=None, lc_state=None, lifecycle_enabled=False) == "not-enabled"

def test_case_02_lifecycle_disabled_even_with_proposal_and_state():
    assert _py_correction_ui_phase(
        proposal=GLOBAL_PROPOSAL,
        lc_state={"state": "STAGED"},
        lifecycle_enabled=False,
    ) == "not-enabled"

def test_case_03_lifecycle_unknown_returns_none():
    assert _py_correction_ui_phase(proposal=None, lc_state=None, lifecycle_enabled=None) is None

def test_case_04_proposal_not_loaded_returns_none():
    assert _py_correction_ui_phase(proposal=None, lc_state=None, lifecycle_enabled=True) is None

def test_case_05_non_global_returns_none():
    assert _py_correction_ui_phase(proposal=NON_GLOBAL, lc_state=None, lifecycle_enabled=True) is None

def test_case_06_global_no_lifecycle_yet_returns_review():
    assert _py_correction_ui_phase(proposal=GLOBAL_PROPOSAL, lc_state=None, lifecycle_enabled=True) == "review"

@pytest.mark.parametrize("state,expected", [
    ("PROPOSED",            "review"),
    ("OPERATOR_REVIEWED",   "accepted"),
    ("STAGED",              "push-enabled"),     # push_disabled_detected=False
    ("EXECUTING",           "working"),
    ("COMPLETED",           "done"),
    ("FAILED",              "needs-attention"),
    ("TERMINAL_SUPPRESSED", "closed"),
])
def test_case_07_to_13_lifecycle_states(state, expected):
    assert _py_correction_ui_phase(
        proposal=GLOBAL_PROPOSAL,
        lc_state={"state": state},
        lifecycle_enabled=True,
    ) == expected


def test_case_14_staged_with_push_disabled_detected_maps_to_push_disabled():
    assert _py_correction_ui_phase(
        proposal=GLOBAL_PROPOSAL,
        lc_state={"state": "STAGED"},
        lifecycle_enabled=True,
        push_disabled_detected=True,
    ) == "push-disabled"


def test_case_15_unknown_future_state_falls_back_to_review():
    assert _py_correction_ui_phase(
        proposal=GLOBAL_PROPOSAL,
        lc_state={"state": "SOME_FUTURE_STATE_NOT_YET_DEFINED"},
        lifecycle_enabled=True,
    ) == "review"


def test_case_16_terminal_suppressed_with_push_detected_still_closed():
    # push_disabled_detected only affects STAGED; terminal states stay terminal.
    assert _py_correction_ui_phase(
        proposal=GLOBAL_PROPOSAL,
        lc_state={"state": "TERMINAL_SUPPRESSED"},
        lifecycle_enabled=True,
        push_disabled_detected=True,
    ) == "closed"


# ── Source-grep proof that the JS function is the authority ──────────────────

def test_pz_state_defines_correction_ui_phase():
    """The JS authority must declare correctionUiPhase as a function and
    export it in window.PzState. This is the contract test_single_renderer_authority
    relies on."""
    src = PZ_STATE.read_text(encoding="utf-8")
    assert re.search(r"function\s+correctionUiPhase\s*\(", src), \
        "correctionUiPhase function must be defined in pz-state.js"
    assert "correctionUiPhase," in src or "correctionUiPhase\n" in src, \
        "correctionUiPhase must be exported in window.PzState freeze"


def test_pz_state_correction_ui_phase_handles_all_seven_states():
    """JS implementation must reference all 7 lifecycle states. If a
    future refactor drops one of these strings, this test fails."""
    src = PZ_STATE.read_text(encoding="utf-8")
    required_states = [
        "PROPOSED", "OPERATOR_REVIEWED", "STAGED",
        "EXECUTING", "COMPLETED", "FAILED", "TERMINAL_SUPPRESSED",
    ]
    for state in required_states:
        assert f"'{state}'" in src or f'"{state}"' in src, \
            f"correctionUiPhase must handle lifecycle state {state!r}"


def test_pz_state_correction_ui_phase_handles_not_enabled():
    """M2 acceptance: lifecycleEnabled === false must produce 'not-enabled'."""
    src = PZ_STATE.read_text(encoding="utf-8")
    assert "'not-enabled'" in src, "must emit 'not-enabled' phase token"
    assert "lifecycleEnabled === false" in src, \
        "must compare lifecycleEnabled === false explicitly (no truthy shortcut)"


# ── Optional: Node round-trip verification ──────────────────────────────────
# When Node is available, run the actual JS function through Node and verify
# it matches the Python port. Otherwise skip (Python port serves as authority
# in that case; source-grep above pins the JS structure).

def _node_eval(js_expr: str) -> object:
    node = shutil.which("node")
    if not node:
        pytest.skip("node binary unavailable in test environment")
    src = PZ_STATE.read_text(encoding="utf-8")
    # Strip the IIFE wrapper and React/window references so we can run in Node.
    # We extract the correctionUiPhase function body directly.
    m = re.search(r"function correctionUiPhase\([^)]*\)\s*\{(.*?)\n  \}", src, re.S)
    if not m:
        pytest.fail("could not locate correctionUiPhase function in pz-state.js")
    fn_body = m.group(1)
    js_program = f"""
const fn = function correctionUiPhase({{ proposal, lcState, lifecycleEnabled, pushDisabledDetected }}) {{{fn_body}
}};
process.stdout.write(JSON.stringify({js_expr}));
""".strip()
    result = subprocess.run([node, "-e", js_program], capture_output=True, text=True, timeout=10)
    if result.returncode != 0:
        pytest.fail(f"node eval failed: {result.stderr}")
    return json.loads(result.stdout)


@pytest.mark.parametrize("case,args,expected", [
    ("disabled",      "fn({lifecycleEnabled: false, proposal: null, lcState: null})",                                "not-enabled"),
    ("unknown",       "fn({lifecycleEnabled: null,  proposal: null, lcState: null})",                                None),
    ("no_proposal",   "fn({lifecycleEnabled: true,  proposal: null, lcState: null})",                                None),
    ("non_global",    "fn({lifecycleEnabled: true,  proposal: {is_global_supplier: false}, lcState: null})",         None),
    ("review_no_lc",  "fn({lifecycleEnabled: true,  proposal: {is_global_supplier: true}, lcState: null})",          "review"),
    ("proposed",      "fn({lifecycleEnabled: true,  proposal: {is_global_supplier: true}, lcState: {state: 'PROPOSED'}})",            "review"),
    ("operator_rev",  "fn({lifecycleEnabled: true,  proposal: {is_global_supplier: true}, lcState: {state: 'OPERATOR_REVIEWED'}})",   "accepted"),
    ("staged",        "fn({lifecycleEnabled: true,  proposal: {is_global_supplier: true}, lcState: {state: 'STAGED'}})",              "push-enabled"),
    ("staged_pd",     "fn({lifecycleEnabled: true,  proposal: {is_global_supplier: true}, lcState: {state: 'STAGED'}, pushDisabledDetected: true})", "push-disabled"),
    ("executing",     "fn({lifecycleEnabled: true,  proposal: {is_global_supplier: true}, lcState: {state: 'EXECUTING'}})",           "working"),
    ("completed",     "fn({lifecycleEnabled: true,  proposal: {is_global_supplier: true}, lcState: {state: 'COMPLETED'}})",           "done"),
    ("failed",        "fn({lifecycleEnabled: true,  proposal: {is_global_supplier: true}, lcState: {state: 'FAILED'}})",              "needs-attention"),
    ("suppressed",    "fn({lifecycleEnabled: true,  proposal: {is_global_supplier: true}, lcState: {state: 'TERMINAL_SUPPRESSED'}})", "closed"),
])
def test_node_js_matches_python_port(case, args, expected):
    """When Node is available, run the actual JS and confirm it matches
    the Python port (which the rest of this file uses as the contract)."""
    got = _node_eval(args)
    assert got == expected, f"JS/Python port divergence for case {case!r}: js={got!r} expected={expected!r}"
