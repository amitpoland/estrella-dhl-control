"""Seven-agent gate evidence — strict JSON validation and tamper binding.

Covers `.claude/hooks/gate_evidence.py` and its two integration points:
`sign_deploy_authorization.py` (evidence gates signing) and
`deploy_authorization.evaluate()` (evidence re-checked at use time).

The authority model under test: evidence gates SIGNING, the signature gates the
DEPLOY. These tests must fail if that inverts — i.e. if evidence alone ever becomes
sufficient, or if a signed artifact stops being required.

WHY THESE TESTS LOOK LIKE THIS
------------------------------
The predecessor of this suite tested a tolerant Markdown parser. Over three rounds the
seven-agent gate found six distinct ways a human-visible BLOCK could be laundered into
a validated GO — each patched, each followed by another. Every test below is therefore
written as a MUTATION: take one valid document, change exactly one thing, prove the
validator refuses. A suite that only exercises the happy path cannot tell a strict
validator from a permissive one.

Refusals are asserted on `ok is False` plus a substring of the reason, never on the
whole message: the reason is operator-facing prose and may be reworded, the refusal is
the contract.

Every test here runs on any OS.

WHAT IS **NOT** COVERED HERE, STATED PLAINLY. `Deploy-PZ.ps1 -Release` does not exist at
this revision — `docs/ops/release-mode-implementation-plan.md` is a plan, and the tests
it proposes have not been written. An earlier version of this docstring claimed the
PowerShell side was "covered separately by the deploy-authority suite's text assertions
plus operator parse validation." That was false, and false in the permitting direction
(Lesson Q rule 6): it described coverage that does not exist. What IS live today is the
Python path — the signer refuses to mint without valid evidence, and
`deploy_authorization.evaluate()` re-checks the digest at use time, which `Deploy-PZ.ps1`
already invokes through `Assert-Authorization`. No PowerShell change was needed for that,
and none was made.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
HOOKS = REPO / ".claude" / "hooks"
if str(HOOKS) not in sys.path:
    sys.path.insert(0, str(HOOKS))

from gate_evidence import (  # noqa: E402
    MAX_VALIDITY, REQUIRED_AGENTS, SCHEMA_VERSION, digest_file, format_ref, parse_ref,
    validate_evidence,
)

# The hook modules this file imports under bare, very generic top-level names. They stay
# registered in sys.modules for the session, so a later test in ANY file could bind to
# the module object this file executed. Harmless today — they hold no state and resolve
# to the same files — but it is the same order-dependence the sibling suite
# (test_deploy_reconcile_signing.py) documents at length, and symmetry here is cheaper
# than diagnosing it later.
_HOOK_MODULES = ("gate_evidence", "deploy_authorization", "sign_deploy_authorization")


@pytest.fixture(autouse=True)
def _isolate_hook_modules():
    saved = {name: sys.modules.get(name) for name in _HOOK_MODULES}
    try:
        yield
    finally:
        for name, module in saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module

_SHA = "6e1de8b1a2c34d5e6f708192a3b4c5d6e7f80912"
_OTHER_SHA = "0123456789abcdef0123456789abcdef01234567"

# Sorted, so the generated document is deterministic. An agents list ordered by set
# iteration makes byte-level assertions flaky for reasons unrelated to the property.
_AGENTS = sorted(REQUIRED_AGENTS)


def _now():
    return datetime.now(timezone.utc)


def _agent(name, status="GO", blockers=None, risks=None):
    return {
        "agent": name,
        "status": status,
        "blockers": list(blockers or []),
        "risks": list(risks or []),
    }


def _doc(target=_SHA, agents=None, created=None, expires=None, lead="GO"):
    """A valid evidence document. Every refusal test mutates exactly one thing in it."""
    created = created if created is not None else _now() - timedelta(minutes=5)
    expires = expires if expires is not None else _now() + timedelta(hours=2)
    return {
        "schema_version": SCHEMA_VERSION,
        "target_sha": target,
        "created_at": created.isoformat() if hasattr(created, "isoformat") else created,
        "expires_at": expires.isoformat() if hasattr(expires, "isoformat") else expires,
        "agents": agents if agents is not None else [_agent(a) for a in _AGENTS],
        "lead_verdict": lead,
    }


def _write(tmp_path, doc, name="gate.json"):
    """Write a document (dict → JSON, str → verbatim) and return its path."""
    p = tmp_path / name
    p.write_text(doc if isinstance(doc, str) else json.dumps(doc, indent=2),
                 encoding="utf-8")
    return str(p)


def _refuse(tmp_path, doc, needle, target=_SHA, name="gate.json"):
    ok, reason, digest = validate_evidence(_write(tmp_path, doc, name), target)
    assert not ok, f"accepted a document that must be refused (reason={reason!r})"
    assert needle in reason, f"reason {reason!r} does not mention {needle!r}"
    return reason, digest


# ── the roster is pinned to the agent files, not editable in isolation ────────

# An INVOCATION, not a prose mention: the line must actually run python against the
# signer and name one of the two evidence-requiring actions as a bare word.
_SIGNER_CMD_RX = re.compile(
    r"^[^\n]*\bpython\b[^\n]*sign_deploy_authorization\.py[^\n]+\b(?:deploy|reconcile)\b"
    r"[^\n]*$",
    re.MULTILINE)

_DOCS_SHOWING_THE_SIGNER = (
    ".claude/hooks/sign_deploy_authorization.py",
    ".claude/commands/deploy.md",
    ".claude/contracts/seven-agent-evidence.md",
)


@pytest.mark.parametrize("relpath", _DOCS_SHOWING_THE_SIGNER)
def test_every_documented_deploy_mint_carries_gate_evidence(relpath):
    """An operator copy-pastes these. A documented command that now exits 2 is a defect.

    This regressed once already: when `--gate-evidence` became mandatory, the canonical
    PER-DEPLOY and RECONCILE commands in the signer's own docstring were left without
    it, so the file that teaches the command taught a command it rejects. Nothing pinned
    the text, so only a human reading it caught it — twice, in two separate gate rounds.

    Scanned per LINE, which also enforces the PowerShell constraint: the operator shell
    on the production host does not treat a trailing `\\` as a continuation, so a wrapped
    command pastes as two broken ones. A single-line command keeps the flag on the same
    line as the action, which is exactly what this regex requires.
    """
    text = (REPO / relpath).read_text(encoding="utf-8")
    missing = [m.group(0).strip() for m in _SIGNER_CMD_RX.finditer(text)
               if "--gate-evidence" not in m.group(0)]
    assert not missing, (
        f"{relpath} documents a deploy/reconcile mint without --gate-evidence; "
        f"pasted as written it exits 2:\n  " + "\n  ".join(missing))


def test_required_agents_matches_the_agent_files_on_disk():
    """REQUIRED_AGENTS is the WIDTH of the gate.

    CLAUDE.md names seven deploy authorities and each has a `.claude/agents/deploy_*.md`
    file. If one is renamed, added or removed, this test fails and forces the decision
    to be made deliberately — rather than the gate silently narrowing to six while
    every other test still passes.
    """
    on_disk = {p.stem for p in (REPO / ".claude" / "agents").glob("deploy_*.md")}
    assert on_disk == set(REQUIRED_AGENTS), (
        "REQUIRED_AGENTS and .claude/agents/deploy_*.md disagree: "
        f"only on disk={sorted(on_disk - set(REQUIRED_AGENTS))}, "
        f"only in code={sorted(set(REQUIRED_AGENTS) - on_disk)}")
    assert len(REQUIRED_AGENTS) == 7


# ── the happy path ────────────────────────────────────────────────────────────

def test_valid_evidence_passes(tmp_path):
    ok, reason, digest = validate_evidence(_write(tmp_path, _doc()), _SHA)
    assert ok, reason
    assert digest and len(digest) == 64


def test_uppercase_target_sha_argument_matches_lowercase_evidence(tmp_path):
    """Operators paste SHAs from tools that upper-case them. The document itself is
    still required to be canonical lowercase."""
    ok, reason, _ = validate_evidence(_write(tmp_path, _doc()), _SHA.upper())
    assert ok, reason


def test_risks_may_be_nonempty(tmp_path):
    """A GO carrying recorded risks is a normal outcome. Only BLOCKERS disqualify."""
    agents = [_agent(a, risks=["ops noted a slow query"] if a == _AGENTS[0] else [])
              for a in _AGENTS]
    ok, reason, _ = validate_evidence(_write(tmp_path, _doc(agents=agents)), _SHA)
    assert ok, reason


def test_the_base_document_is_actually_valid(tmp_path):
    """Guard against a mutation suite that passes because its BASE is broken.

    Every refusal test below mutates `_doc()`. If `_doc()` itself stopped validating,
    all of them would still 'pass' while proving nothing.
    """
    ok, reason, _ = validate_evidence(_write(tmp_path, copy.deepcopy(_doc())), _SHA)
    assert ok, f"base document invalid — every mutation test is vacuous: {reason}"


# ── document-level refusals ───────────────────────────────────────────────────

def test_duplicate_json_keys_are_refused(tmp_path):
    """`json.loads` has the SAME last-wins defect the Markdown parser died of, one
    layer down: a repeated key silently keeps the last value, so `"lead_verdict":
    "BLOCK"` followed by `"lead_verdict": "GO"` would validate as GO."""
    doc = json.dumps(_doc(), indent=2)
    forged = doc.replace('"lead_verdict": "GO"',
                         '"lead_verdict": "BLOCK",\n  "lead_verdict": "GO"')
    assert forged != doc, "precondition: the forgery was actually applied"
    _refuse(tmp_path, forged, "duplicate JSON key")


def test_duplicate_key_inside_an_agent_entry_is_refused(tmp_path):
    """The same defect nested deeper, where one agent's BLOCK is overwritten by a
    trailing GO within its own object."""
    doc = json.dumps(_doc(), indent=2)
    forged = doc.replace('"status": "GO"', '"status": "BLOCK",\n"status": "GO"', 1)
    assert forged != doc
    _refuse(tmp_path, forged, "duplicate JSON key")


def test_not_json_is_refused(tmp_path):
    _refuse(tmp_path, "AGENT: deploy_qa_reviewer\nSTATUS: GO\n", "not valid JSON")


def test_json_that_is_not_an_object_is_refused(tmp_path):
    _refuse(tmp_path, json.dumps([_doc()]), "must be a JSON object")


def test_invalid_utf8_is_refused(tmp_path):
    p = tmp_path / "gate.json"
    p.write_bytes(b'{"schema_version": 1, "target_sha": "\xff\xfe"}')
    ok, reason, digest = validate_evidence(str(p), _SHA)
    assert not ok and "not valid UTF-8" in reason
    assert digest, "a decode refusal must still report which bytes it rejected"


@pytest.mark.parametrize("encoding,label", [
    ("utf-16", "UTF-16 (PowerShell 5.1 Set-Content / Out-File default)"),
    ("utf-8-sig", "UTF-8 with BOM (Out-File -Encoding utf8 on PowerShell 5.1)"),
])
def test_windows_default_encodings_are_refused_not_half_read(tmp_path, encoding, label):
    """The deploy target is Windows, where the obvious way to write this file produces
    exactly these two encodings. Both must refuse cleanly — the failure mode to avoid is
    a partial parse, not the refusal itself."""
    p = tmp_path / "gate.json"
    p.write_bytes(json.dumps(_doc()).encode(encoding))
    ok, reason, _ = validate_evidence(str(p), _SHA)
    assert not ok, f"{label} was accepted"
    assert "not valid UTF-8" in reason or "not valid JSON" in reason


def test_empty_file_is_refused(tmp_path):
    """Zero bytes is valid UTF-8 and invalid JSON. It exists, so it reaches the parser."""
    p = tmp_path / "gate.json"
    p.write_bytes(b"")
    ok, reason, digest = validate_evidence(str(p), _SHA)
    assert not ok and "not valid JSON" in reason
    assert digest == hashlib.sha256(b"").hexdigest()


def test_deeply_nested_json_refuses_instead_of_raising(tmp_path):
    """RecursionError is a RuntimeError, not a ValueError, so without an explicit catch
    it propagates out of a function whose contract is "fail closed throughout". The
    caller does abort — but a traceback is not a refusal reason, and this was the one
    input class that left the stated invariant unproven."""
    ok, reason, _ = validate_evidence(
        _write(tmp_path, "[" * 100000 + "]" * 100000), _SHA)
    assert not ok
    assert "nested too deeply" in reason or "not valid JSON" in reason


@pytest.mark.parametrize("field", sorted(_doc().keys()))
def test_each_missing_top_level_field_is_refused(tmp_path, field):
    doc = _doc()
    doc.pop(field)
    _refuse(tmp_path, doc, field)


def test_unknown_top_level_field_is_refused(tmp_path):
    """An ignored field is somewhere a reviewer's caveat can live while the validator
    reads approval. Unknown fields are refused, not skipped."""
    doc = _doc()
    doc["override"] = "operator says ship it"
    _refuse(tmp_path, doc, "override")


@pytest.mark.parametrize("bad", [0, 2, "1", None, [1], {}])
def test_wrong_schema_version_is_refused(tmp_path, bad):
    doc = _doc()
    doc["schema_version"] = bad
    _refuse(tmp_path, doc, "schema_version")


@pytest.mark.parametrize("bad", [True, False, 1.0])
def test_schema_version_lookalikes_are_refused(tmp_path, bad):
    """`True == 1` and `1.0 == 1` in Python, so a bare `!= SCHEMA_VERSION` accepts
    `"schema_version": true`. Neither can reach a verdict — every approval-bearing field
    compares against a str — but a module whose thesis is "no tolerance" must not have a
    tolerated value anywhere in it."""
    doc = _doc()
    doc["schema_version"] = bad
    reason, _ = _refuse(tmp_path, doc, "schema_version")
    assert "must be an integer" in reason


def test_evidence_for_another_sha_is_refused(tmp_path):
    """The headline case: a real, fully approved gate run attached to the wrong
    revision."""
    reason, _ = _refuse(tmp_path, _doc(target=_OTHER_SHA), "approves")
    assert _OTHER_SHA[:12] in reason


@pytest.mark.parametrize("bad", [
    _SHA[:39],      # short
    _SHA + "0",     # long
    _SHA.upper(),   # uppercase — the document is canonical lowercase
    _SHA + "\n",    # trailing newline: `$` would accept this, `\Z` does not
    "\n" + _SHA,
    "not-a-sha",
    123,
    None,
])
def test_malformed_target_sha_in_the_document_is_refused(tmp_path, bad):
    _refuse(tmp_path, _doc(target=bad), "target_sha")


def test_sha_shape_check_rejects_a_trailing_newline(tmp_path):
    """Python's `$` also matches immediately before a trailing newline, so
    `^[0-9a-f]{40}$` accepts "<40 hex>\\n" as well-formed. The equality compare would
    then refuse it anyway — but a shape check that accepts a shape it calls invalid is
    one you must re-derive every time you read it. `\\Z` is the fix; this pins it at the
    shape stage by asserting the reason names the FORMAT, not the mismatch."""
    reason, _ = _refuse(tmp_path, _doc(target=_SHA + "\n"), "target_sha")
    assert "not a full 40-character" in reason, (
        f"refused for the wrong reason ({reason!r}) — the shape check let it through")


def test_bad_target_sha_argument_is_refused(tmp_path):
    """A caller that cannot name a full SHA cannot be told the evidence matches it."""
    ok, reason, digest = validate_evidence(_write(tmp_path, _doc()), "not-a-sha")
    assert not ok and "40-character" in reason
    assert digest is None, "the file must not be read before the argument is validated"


def test_expired_evidence_is_refused(tmp_path):
    _refuse(tmp_path, _doc(expires=_now() - timedelta(minutes=1)), "expired")


def test_evidence_expiring_exactly_now_is_refused(tmp_path):
    """The boundary belongs to the refusal side: `now >= expires` denies."""
    at = _now()
    doc = _doc(created=at - timedelta(hours=1), expires=at)
    ok, reason, _ = validate_evidence(_write(tmp_path, doc), _SHA, now=at)
    assert not ok and "expired" in reason


def test_expiry_before_creation_is_refused(tmp_path):
    """A window that closes before it opens is a malformed document, not a long one."""
    _refuse(tmp_path, _doc(created=_now(), expires=_now() - timedelta(hours=1)),
            "not after created_at")


def test_a_validity_window_longer_than_the_maximum_is_refused(tmp_path):
    """Before this, `created_at` was read and never constrained, and nothing bounded the
    window — so a document valid until 2099 satisfied every other rule while the contract
    said "hours, not days". That was advice with no enforcement behind it: a safety
    property nobody was checking."""
    created = _now() - timedelta(minutes=1)
    reason, _ = _refuse(tmp_path, _doc(created=created,
                                       expires=created + MAX_VALIDITY + timedelta(minutes=1)),
                        "longer than")
    assert "maximum" in reason


def test_a_window_at_exactly_the_maximum_is_accepted(tmp_path):
    """The cap is a ceiling, not an off-by-one trap for a document written to it."""
    created = _now() - timedelta(minutes=1)
    ok, reason, _ = validate_evidence(
        _write(tmp_path, _doc(created=created, expires=created + MAX_VALIDITY)), _SHA)
    assert ok, reason


def test_future_created_at_is_refused(tmp_path):
    """A gate round cannot have concluded in the future. This is also the shape a
    long-window document takes once the window itself is capped."""
    created = _now() + timedelta(hours=2)
    _refuse(tmp_path, _doc(created=created, expires=created + timedelta(hours=1)),
            "in the future")


def test_clock_skew_does_not_refuse_a_genuine_document(tmp_path):
    """Clocks disagree by seconds to minutes. Refusing on that would be a validator that
    fails on correct input, which teaches operators to work around it."""
    created = _now() + timedelta(minutes=2)
    ok, reason, _ = validate_evidence(
        _write(tmp_path, _doc(created=created, expires=created + timedelta(hours=1))), _SHA)
    assert ok, reason


@pytest.mark.parametrize("bad", ["soon", "", 1723000000, None])
@pytest.mark.parametrize("field", ["created_at", "expires_at"])
def test_malformed_timestamps_are_refused(tmp_path, field, bad):
    doc = _doc()
    doc[field] = bad
    _refuse(tmp_path, doc, field)


def test_naive_timestamps_are_read_as_utc(tmp_path):
    """Operators write `2026-08-05T12:00:00` with no offset. Reading that as UTC is
    deliberate; crashing on it — or skipping the expiry check — is not."""
    past = (_now() - timedelta(hours=1)).replace(tzinfo=None)
    _refuse(tmp_path, _doc(created=past - timedelta(hours=1), expires=past), "expired")

    future = (_now() + timedelta(hours=1)).replace(tzinfo=None)
    ok, reason, _ = validate_evidence(
        _write(tmp_path, _doc(created=_now().replace(tzinfo=None), expires=future)), _SHA)
    assert ok, reason


@pytest.mark.parametrize("bad", ["HOLD", "BLOCK", "go", "GO ", "", None, True])
def test_lead_verdict_must_be_exactly_GO(tmp_path, bad):
    _refuse(tmp_path, _doc(lead=bad), "lead_verdict")


# ── agent-list refusals ───────────────────────────────────────────────────────

def test_agents_must_be_a_list(tmp_path):
    _refuse(tmp_path, _doc(agents={a: "GO" for a in _AGENTS}), "must be a list")


def test_six_agents_is_refused(tmp_path):
    """A narrowed gate is the failure that matters most, because it looks complete."""
    missing = _AGENTS[3]
    reason, _ = _refuse(tmp_path,
                        _doc(agents=[_agent(a) for a in _AGENTS if a != missing]),
                        "missing agent result")
    assert missing in reason


@pytest.mark.parametrize("missing", _AGENTS)
def test_each_missing_agent_is_refused(tmp_path, missing):
    reason, _ = _refuse(tmp_path,
                        _doc(agents=[_agent(a) for a in _AGENTS if a != missing]),
                        missing)
    assert "missing agent result" in reason


def test_no_agents_at_all_is_refused(tmp_path):
    """An empty list is seven absences, not zero problems."""
    _refuse(tmp_path, _doc(agents=[]), "missing agent result")


def test_eight_agents_is_refused(tmp_path):
    """An eighth entry must never ride along unexamined.

    With seven exact names required and unknown names refused, an eighth entry can
    only be a repeat — so this lands on the duplicate check. The explicit count
    assertion in the validator is the backstop for the case where that reasoning
    stops holding.
    """
    _refuse(tmp_path, _doc(agents=[_agent(a) for a in _AGENTS] + [_agent(_AGENTS[0])]),
            "more than one result")


def test_duplicate_agent_is_refused_even_when_both_entries_agree(tmp_path):
    """Refused, not resolved. First-wins silently drops a later BLOCK; last-wins is the
    original defect. A repeat is a refusal in either direction."""
    agents = [_agent(a) for a in _AGENTS]
    agents.insert(2, _agent(_AGENTS[2]))
    reason, _ = _refuse(tmp_path, _doc(agents=agents), "more than one result")
    assert _AGENTS[2] in reason


def test_duplicate_agent_cannot_override_a_block(tmp_path):
    """The laundering attempt in its most direct form: a real BLOCK, then a clean
    restatement by the same agent."""
    agents = [_agent(a) for a in _AGENTS]
    agents[0] = _agent(_AGENTS[0], status="BLOCK", blockers=["credential in diff"])
    agents.append(_agent(_AGENTS[0]))
    ok, reason, _ = validate_evidence(_write(tmp_path, _doc(agents=agents)), _SHA)
    assert not ok, "a restated verdict overrode a BLOCK"
    # Either refusal is correct — what must never happen is acceptance.
    assert "BLOCK" in reason or "more than one result" in reason


@pytest.mark.parametrize("written", [
    "deploy-security-reviewer",         # kebab-case, as the files are named on disk
    "deploy_security_reviewer.md",      # with the extension
    "Deploy_Security_Reviewer",         # transcription
    " deploy_security_reviewer ",       # stray whitespace
    "deploy_security_reviewer (round 1)",
])
def test_near_miss_agent_names_are_refused_not_normalised(tmp_path, written):
    """Name tolerance is what let a BLOCK be attributed to an unrecognised author and
    then silently discarded. There is no normalisation here: a near miss is an unknown
    agent, and unknown agents are refused."""
    agents = [_agent(a) for a in _AGENTS if a != "deploy_security_reviewer"]
    agents.append(_agent(written))
    _refuse(tmp_path, _doc(agents=agents), "unknown agent")


def test_unknown_agent_carrying_a_block_is_still_refused(tmp_path):
    """The refusal must not depend on the entry being otherwise clean — an
    unrecognised author with a BLOCK is exactly the shape that was being dropped."""
    agents = [_agent(a) for a in _AGENTS]
    agents.append(_agent("deploy_extra_reviewer", status="BLOCK", blockers=["x"]))
    _refuse(tmp_path, _doc(agents=agents), "unknown agent")


@pytest.mark.parametrize("index", range(7))
def test_a_nonobject_agent_entry_is_refused(tmp_path, index):
    agents = [_agent(a) for a in _AGENTS]
    agents[index] = _AGENTS[index]
    _refuse(tmp_path, _doc(agents=agents), "not an object")


@pytest.mark.parametrize("field", ["agent", "status", "blockers", "risks"])
def test_each_missing_agent_field_is_refused(tmp_path, field):
    agents = [_agent(a) for a in _AGENTS]
    agents[1].pop(field)
    _refuse(tmp_path, _doc(agents=agents), field)


def test_unknown_agent_field_is_refused(tmp_path):
    agents = [_agent(a) for a in _AGENTS]
    agents[1]["waived_by"] = "operator"
    _refuse(tmp_path, _doc(agents=agents), "waived_by")


def test_nonstring_agent_name_is_refused(tmp_path):
    agents = [_agent(a) for a in _AGENTS]
    agents[1]["agent"] = 42
    _refuse(tmp_path, _doc(agents=agents), "must be a string")


# ── status refusals: one passing value, no synonyms ───────────────────────────

@pytest.mark.parametrize("status", [
    "HOLD", "BLOCK", "FAIL",             # explicit refusals
    "PASS", "CLEAR", "OK", "APPROVED",   # plausible synonyms — none of them pass
    "go", "Go", "GO ", " GO",            # case and whitespace variants
    "", None, True, 1,                   # non-strings
])
def test_only_exact_GO_is_a_passing_status(tmp_path, status):
    """Every synonym is a token to typo into, and an unrecognised status must never
    read as approval. There is exactly one passing value."""
    agents = [_agent(a) for a in _AGENTS]
    agents[4] = _agent(_AGENTS[4], status=status)
    reason, _ = _refuse(tmp_path, _doc(agents=agents), _AGENTS[4])
    assert "status is" in reason


@pytest.mark.parametrize("agent", _AGENTS)
def test_any_single_agent_short_of_GO_refuses_the_document(tmp_path, agent):
    """No agent is advisory. Each of the seven can refuse alone."""
    agents = [_agent(a, status="BLOCK" if a == agent else "GO") for a in _AGENTS]
    _refuse(tmp_path, _doc(agents=agents), agent)


def test_nonempty_blockers_refuse_even_with_a_GO_status(tmp_path):
    """A reviewer recording an unresolved blocker has not approved, whatever the status
    field says. The two must agree, and the stricter one wins."""
    agents = [_agent(a) for a in _AGENTS]
    agents[2] = _agent(_AGENTS[2], status="GO", blockers=["auth guard removed"])
    reason, _ = _refuse(tmp_path, _doc(agents=agents), _AGENTS[2])
    assert "blocker" in reason


@pytest.mark.parametrize("bad", ["none", {}, 0, None])
def test_blockers_must_be_a_list(tmp_path, bad):
    """`"blockers": "none"` is a non-list; accepting it as absence would let a line of
    prose stand in for an empty list — and `"blockers": "see section 4"` would too."""
    agents = [_agent(a) for a in _AGENTS]
    agents[2]["blockers"] = bad
    _refuse(tmp_path, _doc(agents=agents), "blockers")


@pytest.mark.parametrize("bad", ["none", {}, 0, None])
def test_risks_must_be_a_list(tmp_path, bad):
    agents = [_agent(a) for a in _AGENTS]
    agents[3]["risks"] = bad
    _refuse(tmp_path, _doc(agents=agents), "risks")


# ── file handling ─────────────────────────────────────────────────────────────

def test_missing_file_and_empty_path_are_refused(tmp_path):
    assert not validate_evidence(str(tmp_path / "nope.json"), _SHA)[0]
    assert not validate_evidence("", _SHA)[0]
    assert not validate_evidence(None, _SHA)[0]


def test_a_directory_is_refused(tmp_path):
    ok, reason, _ = validate_evidence(str(tmp_path), _SHA)
    assert not ok and "not found" in reason


def test_evidence_file_is_read_exactly_once(tmp_path, monkeypatch):
    """TOCTOU: hashing and parsing must be ONE read.

    An earlier version of this test hashed an unmodified file twice and compared the
    digests — which passes on the two-read implementation it claimed to pin, because
    the window it names is never opened. Counting opens is what actually distinguishes
    one read from two.
    """
    import builtins
    path = _write(tmp_path, _doc())
    real_open, opens = builtins.open, []

    def counting_open(file, *a, **kw):
        if str(file) == path:
            opens.append(kw.get("mode", a[0] if a else "r"))
        return real_open(file, *a, **kw)

    monkeypatch.setattr(builtins, "open", counting_open)
    ok, reason, digest = validate_evidence(path, _SHA)
    assert ok, reason
    assert len(opens) == 1, f"evidence file opened {len(opens)} times: {opens}"


def test_the_returned_digest_is_the_bytes_that_were_parsed(tmp_path):
    """What the single read buys, asserted on a REFUSAL path: the digest a caller
    records is always the digest of the bytes the validator actually read."""
    agents = [_agent(a, status="BLOCK" if a == _AGENTS[0] else "GO") for a in _AGENTS]
    path = _write(tmp_path, _doc(agents=agents))
    ok, _, digest = validate_evidence(path, _SHA)
    assert not ok
    # Read the bytes back in binary: `write_text` translates \n -> \r\n on Windows, so
    # comparing against text.encode() would assert a platform-specific expectation.
    with open(path, "rb") as fh:
        on_disk = fh.read()
    assert digest == hashlib.sha256(on_disk).hexdigest()


# ── ref binding ───────────────────────────────────────────────────────────────

def test_ref_roundtrip():
    ref = format_ref("/tmp/gate.json", "a" * 64)
    assert parse_ref(ref) == ("/tmp/gate.json", "a" * 64)


def test_legacy_freetext_ref_yields_no_digest():
    """Pre-binding artifacts must be detectable, not silently accepted."""
    assert parse_ref("see PR #123") == ("see PR #123", None)


def test_windows_path_ref_roundtrips():
    ref = format_ref(r"C:\PZ-secrets\gate.json", "b" * 64)
    assert parse_ref(ref) == (r"C:\PZ-secrets\gate.json", "b" * 64)


# ── integration: evidence gates signing ───────────────────────────────────────

def _signer_env(tmp_path, monkeypatch):
    key = tmp_path / "k.key"
    key.write_text("0" * 64, encoding="utf-8")
    store = tmp_path / "store"
    store.mkdir()
    monkeypatch.setenv("PZ_DEPLOY_AUTH_KEY_FILE", str(key))
    monkeypatch.setenv("PZ_DEPLOY_AUTH_DIR", str(store))
    # Clear the inline-key fallback too. `_load_key` prefers KEY_FILE whenever it is a
    # readable file, so this is belt-and-braces — but if the tmp key ever went missing,
    # an operator's real PZ_DEPLOY_AUTH_KEY would be reachable from a test run.
    monkeypatch.delenv("PZ_DEPLOY_AUTH_KEY", raising=False)
    monkeypatch.delenv("PZ_DEPLOY_AUTH_REPO", raising=False)
    return store


def _sign(argv):
    import sign_deploy_authorization
    return sign_deploy_authorization.main(argv)


def test_deploy_without_evidence_is_refused(tmp_path, monkeypatch):
    _signer_env(tmp_path, monkeypatch)
    assert _sign([_SHA, "deploy", "Both"]) == 2


def test_deploy_with_markdown_evidence_is_refused(tmp_path, monkeypatch):
    """The migration boundary. Evidence in the retired Markdown format is not 'nearly
    right' — it is not evidence, and it must fail loudly rather than be half-read."""
    _signer_env(tmp_path, monkeypatch)
    md = _write(tmp_path, f"TARGET_SHA: {_SHA}\n" + "".join(
        f"AGENT: {a}\nSTATUS: GO\nDISPOSITION: GO\n" for a in _AGENTS), name="gate.md")
    assert _sign([_SHA, "deploy", "Both", "--gate-evidence", md]) == 2


def test_deploy_with_wrong_sha_evidence_is_refused(tmp_path, monkeypatch):
    _signer_env(tmp_path, monkeypatch)
    ev = _write(tmp_path, _doc(target=_OTHER_SHA))
    assert _sign([_SHA, "deploy", "Both", "--gate-evidence", ev]) == 2


def test_deploy_with_a_blocking_agent_is_refused(tmp_path, monkeypatch):
    _signer_env(tmp_path, monkeypatch)
    agents = [_agent(a, status="BLOCK" if a == "deploy_security_reviewer" else "GO")
              for a in _AGENTS]
    ev = _write(tmp_path, _doc(agents=agents))
    assert _sign([_SHA, "deploy", "Both", "--gate-evidence", ev]) == 2


def test_deploy_with_expired_evidence_is_refused(tmp_path, monkeypatch):
    _signer_env(tmp_path, monkeypatch)
    ev = _write(tmp_path, _doc(expires=_now() - timedelta(minutes=1)))
    assert _sign([_SHA, "deploy", "Both", "--gate-evidence", ev]) == 2


def test_deploy_with_valid_evidence_signs_and_binds_the_digest(tmp_path, monkeypatch):
    store = _signer_env(tmp_path, monkeypatch)
    ev = _write(tmp_path, _doc())
    assert _sign([_SHA, "deploy", "Both", "--gate-evidence", ev]) == 0
    art = json.loads((store / f"{_SHA}.deploy.json").read_text(encoding="utf-8"))
    path, digest = parse_ref(art["gate_evidence_ref"])
    assert digest == digest_file(ev)
    assert os.path.isabs(path)


def test_reconcile_requires_fresh_evidence_for_the_target(tmp_path, monkeypatch):
    """Reconcile writes new bytes to production, so it is gated exactly like deploy —
    and the evidence must approve the TARGET sha, not the one production holds."""
    _signer_env(tmp_path, monkeypatch)
    assert _sign([_SHA, "reconcile", "Both", "--from-sha", _OTHER_SHA]) == 2

    wrong = _write(tmp_path, _doc(target=_OTHER_SHA), name="wrong.json")
    assert _sign([_SHA, "reconcile", "Both", "--from-sha", _OTHER_SHA,
                  "--gate-evidence", wrong]) == 2

    right = _write(tmp_path, _doc(), name="right.json")
    assert _sign([_SHA, "reconcile", "Both", "--from-sha", _OTHER_SHA,
                  "--gate-evidence", right]) == 0


def test_rollback_does_not_require_evidence(tmp_path, monkeypatch):
    """The incident path must not depend on assembling a fresh gate report."""
    _signer_env(tmp_path, monkeypatch)
    assert _sign([_SHA, "rollback", "Both"]) == 0


@pytest.mark.parametrize("argv_tail", [
    [],                                            # no evidence at all
    ["--gate-evidence", "nope.json"],              # evidence that does not exist
])
def test_a_refused_mint_writes_nothing_to_the_store(tmp_path, monkeypatch, argv_tail):
    """A refusal must not leave an artifact. The evidence checks are the newest refusal
    paths and were the ones not pinned: hoisting `os.makedirs`/`_load_key` above
    `validate_evidence` would pass every other test in this file."""
    store = _signer_env(tmp_path, monkeypatch)
    assert _sign([_SHA, "deploy", "Both"] + argv_tail) == 2
    assert not list(store.iterdir()), "a refused mint wrote to the authorization store"


def test_evidence_is_validated_before_the_signing_key_is_loaded(tmp_path, monkeypatch):
    """The claim in sign_deploy_authorization.py and in the contract — "an operator who
    cannot produce a seven-agent GO for that exact SHA never reaches the key".

    Every other signer test provisions a key first, so that ordering was an UNPINNED
    safety claim: hoisting `_load_key()` above `validate_evidence()` broke nothing
    (Lesson Q rules 1 and 6). Here the key is deliberately absent, so the error message
    reveals which check ran first.
    """
    store = tmp_path / "store"
    store.mkdir()
    monkeypatch.delenv("PZ_DEPLOY_AUTH_KEY_FILE", raising=False)
    monkeypatch.delenv("PZ_DEPLOY_AUTH_KEY", raising=False)
    monkeypatch.setenv("PZ_DEPLOY_AUTH_DIR", str(store))

    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = _sign([_SHA, "deploy", "Both", "--gate-evidence",
                    _write(tmp_path, _doc(target=_OTHER_SHA))])
    out = buf.getvalue()
    assert rc == 2
    assert "approves" in out, (
        f"expected the EVIDENCE refusal, got: {out!r} — if this says 'no signing key', "
        "the key is being loaded before evidence is validated")
    assert "no signing key" not in out


# ── integration: evidence re-checked at USE time ──────────────────────────────

def _evaluate(sha, action, scope, env, from_sha=None):
    import deploy_authorization
    return deploy_authorization.evaluate(sha, action, scope, from_sha=from_sha, env=env)


def test_signed_deploy_allows_when_evidence_is_untouched(tmp_path, monkeypatch):
    _signer_env(tmp_path, monkeypatch)
    ev = _write(tmp_path, _doc())
    assert _sign([_SHA, "deploy", "Both", "--gate-evidence", ev]) == 0
    decision, reason = _evaluate(_SHA, "deploy", "Both", dict(os.environ))
    assert decision == "allow", reason


def test_editing_evidence_after_signing_denies(tmp_path, monkeypatch):
    """The window between signing and deploying is when evidence gets 'tidied up'."""
    _signer_env(tmp_path, monkeypatch)
    ev = _write(tmp_path, _doc())
    assert _sign([_SHA, "deploy", "Both", "--gate-evidence", ev]) == 0
    Path(ev).write_text(json.dumps(_doc(), indent=4), encoding="utf-8")
    decision, reason = _evaluate(_SHA, "deploy", "Both", dict(os.environ))
    assert decision == "deny"
    assert "changed" in reason


def test_swapping_in_a_different_valid_evidence_file_denies(tmp_path, monkeypatch):
    """Signer and verifier must read the SAME bytes, not merely equally-valid ones.

    Two documents can both be valid for one SHA — e.g. a superseded gate round and the
    current one. The digest binds the authorization to the specific file the operator
    held at signing time, so substituting the other is a denial.
    """
    _signer_env(tmp_path, monkeypatch)
    signed = _write(tmp_path, _doc(), name="round2.json")
    # Differs in created_at only, and stays inside MAX_VALIDITY so it is genuinely valid
    # — the point is that validity is not what the digest check tests.
    other = _doc(created=_now() - timedelta(hours=1))
    assert _sign([_SHA, "deploy", "Both", "--gate-evidence", signed]) == 0
    ok, reason, _ = validate_evidence(_write(tmp_path, other, name="round1.json"), _SHA)
    assert ok, f"precondition: the substituted document is itself valid ({reason})"
    Path(signed).write_text(json.dumps(other, indent=2), encoding="utf-8")
    decision, reason = _evaluate(_SHA, "deploy", "Both", dict(os.environ))
    assert decision == "deny" and "changed" in reason


def test_deleting_evidence_after_signing_denies(tmp_path, monkeypatch):
    _signer_env(tmp_path, monkeypatch)
    ev = _write(tmp_path, _doc())
    assert _sign([_SHA, "deploy", "Both", "--gate-evidence", ev]) == 0
    os.remove(ev)
    decision, reason = _evaluate(_SHA, "deploy", "Both", dict(os.environ))
    assert decision == "deny" and "no longer readable" in reason


def test_moving_evidence_after_signing_denies(tmp_path, monkeypatch):
    """A moved file is a deleted file at the signed path. The ref records an ABSOLUTE
    path precisely so relocation cannot silently resolve to something else."""
    _signer_env(tmp_path, monkeypatch)
    ev = _write(tmp_path, _doc())
    assert _sign([_SHA, "deploy", "Both", "--gate-evidence", ev]) == 0
    os.rename(ev, str(tmp_path / "archived.json"))
    decision, reason = _evaluate(_SHA, "deploy", "Both", dict(os.environ))
    assert decision == "deny" and "no longer readable" in reason


def test_authorization_remains_single_use(tmp_path, monkeypatch):
    """Evidence binding must not weaken replay protection."""
    _signer_env(tmp_path, monkeypatch)
    ev = _write(tmp_path, _doc())
    assert _sign([_SHA, "deploy", "Both", "--gate-evidence", ev]) == 0
    assert _evaluate(_SHA, "deploy", "Both", dict(os.environ))[0] == "allow"
    decision, reason = _evaluate(_SHA, "deploy", "Both", dict(os.environ))
    assert decision == "deny" and "consumed" in reason


def test_evidence_alone_never_authorizes(tmp_path, monkeypatch):
    """The load-bearing invariant: valid evidence with NO signed artifact is a denial.

    If this ever passes, evidence has become the gate and the signature has been
    demoted — the exact inversion this design refuses. A JSON file on disk is not
    single-use, not key-protected, and not revocable.
    """
    _signer_env(tmp_path, monkeypatch)
    ev = _write(tmp_path, _doc())
    ok, _, _ = validate_evidence(ev, _SHA)
    assert ok, "precondition: the evidence itself is valid"
    decision, reason = _evaluate(_SHA, "deploy", "Both", dict(os.environ))
    assert decision == "deny" and "no authorization artifact" in reason


def test_rollback_authorization_needs_no_evidence_at_use_time(tmp_path, monkeypatch):
    _signer_env(tmp_path, monkeypatch)
    assert _sign([_SHA, "rollback", "Both"]) == 0
    assert _evaluate(_SHA, "rollback", "Both", dict(os.environ))[0] == "allow"


def test_a_rollback_digest_is_recorded_but_never_re_checked(tmp_path, monkeypatch):
    """Pins the EXEMPTION as an exemption, so nobody re-reads it as protection.

    An earlier comment in the signer claimed a rollback's recorded digest was "still
    tamper-evident". It is not: the use-time re-check is scoped to deploy and reconcile.
    The digest is audit trail — it says which bytes the operator held when signing. This
    test exists so that stays true by assertion rather than by memory, and so the
    contract's wording is falsifiable.
    """
    store = _signer_env(tmp_path, monkeypatch)
    ev = _write(tmp_path, _doc())
    assert _sign([_SHA, "rollback", "Both", "--gate-evidence", ev]) == 0

    art = json.loads((store / f"{_SHA}.rollback.json").read_text(encoding="utf-8"))
    _, digest = parse_ref(art["gate_evidence_ref"])
    assert digest == digest_file(ev), "the digest was not recorded for audit"

    os.remove(ev)   # the deploy path would DENY here
    assert _evaluate(_SHA, "rollback", "Both", dict(os.environ))[0] == "allow", (
        "a rollback was gated on its evidence — if this is now intended, the exemption "
        "documented in .claude/contracts/seven-agent-evidence.md must change with it")


def test_a_prebinding_authorization_is_refused_for_deploy(tmp_path, monkeypatch):
    """The contract says the pre-binding shape "is not grandfathered"
    (deploy_authorization.py, the `if not ev_digest` branch). Nothing exercised it: an
    artifact with a free-text ref would deny anyway, but incidentally — via "no longer
    readable" — so deleting the branch left the contract's claim false and the suite
    green. Assert the reason, not just the denial.
    """
    import deploy_authorization
    store = _signer_env(tmp_path, monkeypatch)
    ev = _write(tmp_path, _doc())
    assert _sign([_SHA, "deploy", "Both", "--gate-evidence", ev]) == 0

    # Re-sign the body with a legacy free-text ref, exactly as a pre-binding artifact
    # would carry — a valid signature over an unbound reference.
    path = store / f"{_SHA}.deploy.json"
    auth = json.loads(path.read_text(encoding="utf-8"))
    auth["gate_evidence_ref"] = "see PR #1094"
    auth.pop("signature")
    auth["signature"] = deploy_authorization.sign(auth, deploy_authorization._load_key())
    path.write_text(json.dumps(auth, indent=2, sort_keys=True), encoding="utf-8")

    decision, reason = _evaluate(_SHA, "deploy", "Both", dict(os.environ))
    assert decision == "deny"
    assert "digest-bound" in reason or "no digest" in reason, (
        f"denied for the wrong reason: {reason!r}")
