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
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path, PureWindowsPath

import pytest

REPO = Path(__file__).resolve().parents[2]
HOOKS = REPO / ".claude" / "hooks"
if str(HOOKS) not in sys.path:
    sys.path.insert(0, str(HOOKS))

from gate_evidence import (  # noqa: E402
    CLOCK_SKEW, MAX_VALIDITY, REQUIRED_AGENTS, SCHEMA_VERSION, digest_file, format_ref,
    parse_ref, validate_evidence,
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
    saved_path = list(sys.path)
    try:
        yield
    finally:
        for name, module in saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module
        # sys.path too. Popping the hook modules means each test re-executes them, and
        # each execution used to re-run their sys.path.insert -- so a full run left
        # dozens of duplicate entries behind. Path resolution is the half that can
        # actually change a LATER file's imports, so restoring modules but not path
        # closed the visible leak and left the consequential one.
        sys.path[:] = saved_path

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

# Any line that INVOKES the signer, however the interpreter is spelled (`python`,
# `python3`, `py -3`) — a prose mention of the filename is not a command.
# `py` must be a bare interpreter token, not the `.py` of some other filename on the
# line — `\bpy\b` matched `deploy_authorization.py` because `.` is a word boundary, so a
# prose line naming two modules read as an invocation.
_SIGNER_INVOCATION_RX = re.compile(
    r"^[^\n]*(?:(?<![\w.])py(?![\w.])|\bpython[0-9.]*\b)[^\n]*"
    r"sign_deploy_authorization\.py[^\n]*$",
    re.MULTILINE)
# ...and of those, the ones naming an evidence-requiring action as a bare word.
_ACTION_RX = re.compile(r"\b(?:deploy|reconcile)\b")
# A flag is only usable if its VALUE is on the same line.
_EVIDENCE_WITH_VALUE_RX = re.compile(r"--gate-evidence\s+\S")
_FROM_SHA_WITH_VALUE_RX = re.compile(r"--from-sha\s+\S")
# A line explicitly marked as a historical record rather than an instruction.
_SUPERSEDED_RX = re.compile(r"\bSUPERSEDED\b|\bDO NOT RUN\b|_superseded\b")
# A line that continues onto the next one.
# A trailing backslash continues a line. A trailing BACKTICK does not — in Markdown it
# closes an inline code span, so treating it as a continuation spliced the next prose
# line into the command and reported a correct single-line command as broken. PowerShell
# backtick-continuation is only a continuation at the end of a *code* line, which in
# these files always sits inside a fence; the backslash form is what operators actually
# paste, and it is what the pin needs to catch.
_CONTINUED_RX = re.compile(r"\\\s*$")

# Every tracked file that shows the operator how to invoke the signer. Discovered, not
# hardcoded: a hardcoded list silently stops covering a doc the moment someone adds one,
# and one such file (.claude/memory/TASK_STATE.md) was already outside an earlier
# hardcoded tuple while carrying a mint command that exits 2.
_SEARCH_ROOTS = (".claude", "docs", "service/docs")
_SEARCH_SUFFIXES = (".md", ".py", ".ps1", ".txt")


def _tracked_files():
    """Git-TRACKED candidate files under the search roots.

    Deliberately not a working-tree walk. `.claude/memory/PROJECT_STATE.md` is
    gitignored precisely because it accumulates operator-local content including
    third-party PII, and a walk that reads it makes this suite's result depend on which
    machine it runs on — CI and the operator's box would disagree, and the assertion
    message prints the matching line. Only tracked files are documentation this repo is
    responsible for.
    """
    try:
        out = subprocess.run(
            ["git", "-C", str(REPO), "ls-files", "-z", "--", *_SEARCH_ROOTS],
            capture_output=True, timeout=30, check=True,
        ).stdout.decode("utf-8", "replace")
    except (OSError, subprocess.SubprocessError) as exc:
        # FAIL, not skip. A skip is invisible in a green summary — the pin would report
        # success while running zero assertions, which is the same vacuity the
        # precondition test exists to prevent, reopened at the discovery layer. And
        # `check=True` means this fires on more than "git absent": a `git archive`
        # export with no .git (which Lesson Q rule 7 actively recommends for
        # commit-scoped reads), a safe.directory/dubious-ownership container, a corrupt
        # index, or the timeout would each silently disarm the only pin keeping the
        # operator's copy-pasted mint commands runnable.
        pytest.fail(f"git unavailable, so the documentation pin cannot run: {exc}")
    for rel in filter(None, out.split("\0")):
        path = REPO / rel
        if path.suffix in _SEARCH_SUFFIXES and path.is_file():
            yield path


def _files_invoking_the_signer():
    hits = []
    for path in _tracked_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if _SIGNER_INVOCATION_RX.search(text):
            # as_posix(): on Windows `str(relative_to(...))` yields backslash separators,
            # so comparing against a "a/b/c.py" literal fails there and passes on Linux.
            # This suite's whole point is the deploy target, which IS Windows — CI caught
            # it when local runs could not.
            hits.append((path.relative_to(REPO).as_posix(), text))
    return hits


def _checked_mint_lines():
    """[(relpath, line)] — the mint commands that actually reach an assertion.

    Shared by the precondition and the pin so the two cannot drift: a filter change
    narrows both at once, and the precondition notices.
    """
    out, broken_wrap = [], []
    for relpath, text in _files_invoking_the_signer():
        for m in _SIGNER_INVOCATION_RX.finditer(text):
            line = m.group(0).strip()
            # A WRAPPED command is still one command. If the invocation line ends in a
            # continuation (`\` or PowerShell's backtick), splice the following lines in
            # before filtering — otherwise a command wrapped so the ACTION word falls on
            # line 2 matches nothing and vanishes from the pin entirely, which is exactly
            # the hole an earlier docstring here claimed was closed.
            tail = text[m.end():]
            while line.rstrip().endswith("\\") and tail:
                # lstrip the newline first: m.end() sits BEFORE it, so partitioning
                # directly yields an empty segment and the splice silently no-ops.
                nxt, _, tail = tail.lstrip("\n").partition("\n")
                if not nxt.strip():
                    break
                line = line.rstrip().rstrip("\\").rstrip() + " " + nxt.strip()
            # Strip the script name first: `sign_deploy_authorization.py` contains
            # "deploy" and would satisfy the action filter on its own.
            if not _ACTION_RX.search(line.replace("sign_deploy_authorization.py", "")):
                continue                       # rollback, or a bare `--help` example
            if _SUPERSEDED_RX.search(line):
                # Checked BEFORE the wrap report: a line marked SUPERSEDED / DO NOT RUN
                # is a historical record, and reporting it as a broken command would
                # fail the pin on a line it declares exempt.
                continue
            if _CONTINUED_RX.search(m.group(0)):
                # Spliced above so the flags are visible — but the operator's shell will
                # NOT join them. PowerShell does not honour a trailing backslash at all,
                # so a wrapped mint command is broken however it reads on the page.
                broken_wrap.append(f"{relpath}: command wrapped across lines; PowerShell "
                                   f"does not join these\n    {m.group(0).strip()}")
            out.append((relpath, line))
    return out, broken_wrap


def test_the_signer_documentation_pin_finds_something_to_check():
    """Guard against the pin becoming vacuous.

    The test below is a universal quantifier over a discovered set: if the discovery
    finds nothing, it passes while pinning nothing, and a docs reword is all it takes.
    An earlier version had exactly this shape with no precondition — and its docstring
    additionally claimed to enforce the PowerShell single-line rule, which it did not:
    a command wrapped so the ACTION word falls on the continuation line matched no line
    at all and was invisible. Both are fixed; this asserts the discovery is live.
    """
    found = _files_invoking_the_signer()
    assert found, "no file documents a signer invocation — the pin below checks nothing"
    names = {p for p, _ in found}

    # Pin the NORMALISATION, not its output. Asserting `"\\" not in name` over
    # `as_posix()` results was vacuous twice over: as_posix() cannot emit a backslash on
    # any platform, and the regression it named (reverting to `str()`) yields forward
    # slashes on Linux, so it could not fire on the platform CI runs. Instead, take a
    # path that WOULD differ across platforms and assert the comparison key is
    # separator-independent — which is the actual property the membership checks need.
    probe = PureWindowsPath(r"a\b\c.md")
    assert probe.as_posix() == "a/b/c.md", "as_posix() is not normalising separators"
    assert str(probe) != probe.as_posix(), (
        "this probe no longer distinguishes str() from as_posix(), so it cannot pin "
        "the normalisation the membership assertions depend on")
    for expected in (".claude/hooks/sign_deploy_authorization.py",
                     ".claude/commands/deploy.md"):
        assert expected in names, f"{expected} no longer shows a signer invocation"

    # The discovery set is NOT what the pin asserts over. Two further filters run first
    # — the action filter and the SUPERSEDED exemption — and if the POST-FILTER set
    # empties, the universal quantifier below is vacuous again while this precondition
    # stays green. Marking every command `SUPERSEDED` would do it. Count what actually
    # reaches an assertion.
    checked, _wrapped = _checked_mint_lines()
    assert len(checked) >= 5, (
        f"only {len(checked)} documented mint command(s) reach an assertion; the pin is "
        "nearly vacuous. Lines are dropped by the action filter or the SUPERSEDED "
        f"exemption: {[c[0] for c in checked]}")
    files_checked = {relpath for relpath, _ in checked}
    for expected in (".claude/hooks/sign_deploy_authorization.py",
                     ".claude/commands/deploy.md",
                     ".claude/contracts/seven-agent-evidence.md"):
        assert expected in files_checked, (
            f"{expected} has a signer invocation but none of its lines survive the "
            "filters, so nothing in it is actually checked")


def test_every_documented_mint_is_runnable_as_written():
    """An operator copy-pastes these. A documented command that exits 2 is a defect.

    This regressed twice across gate rounds with nothing to catch it: when
    `--gate-evidence` became mandatory, the canonical PER-DEPLOY and RECONCILE commands
    in the signer's own docstring were left without it, so the file that teaches the
    command taught a command the tool rejects.

    Three properties, all per-line — which is also how the PowerShell constraint is
    enforced, since the operator shell does not treat a trailing `\\` as a continuation:
      * a deploy/reconcile mint carries `--gate-evidence` (required, both actions);
      * a reconcile mint also carries `--from-sha` (required, refused for the others);
      * each flag has its VALUE on the same line — a flag whose argument wrapped to the
        next line exits 2 with "expected one argument", which is exactly as broken.
    """
    checked, wrapped = _checked_mint_lines()
    broken = list(wrapped)
    for relpath, line in checked:
            if not _EVIDENCE_WITH_VALUE_RX.search(line):
                broken.append(f"{relpath}: --gate-evidence missing or has no value\n    {line}")
            if "reconcile" in line and not _FROM_SHA_WITH_VALUE_RX.search(line):
                broken.append(f"{relpath}: reconcile without --from-sha\n    {line}")
    assert not broken, (
        "documented mint commands that do not run as written (each exits 2):\n  "
        + "\n  ".join(broken))


def test_the_time_constants_match_the_figures_the_contract_publishes():
    """Pin the MAGNITUDES, not just the behaviour.

    Every window test computes its inputs from the imported symbols, so widening
    `MAX_VALIDITY` to 30 days — or `CLOCK_SKEW` to an hour — leaves the entire suite
    green while the contract still tells operators "at most 24 hours" and "5 minutes".
    The published figure and the enforced figure must be the same number, and this is
    the same code-to-document pin the roster already gets below.
    """
    contract = (REPO / ".claude" / "contracts" / "seven-agent-evidence.md").read_text(
        encoding="utf-8")
    assert MAX_VALIDITY == timedelta(hours=24), (
        f"MAX_VALIDITY is {MAX_VALIDITY}; the contract publishes 24 hours")
    assert CLOCK_SKEW == timedelta(minutes=5), (
        f"CLOCK_SKEW is {CLOCK_SKEW}; the contract publishes 5 minutes")
    # Anchored: a bare `"24 h" in contract` also matches inside "1024 h", and would be
    # satisfied by the figure appearing anywhere in a 300-line file — including in
    # historical prose describing a value that is no longer enforced.
    assert re.search(r"\*\*at most 24 h\*\*", contract), (
        "the contract no longer publishes the 24-hour cap in the field table")
    assert re.search(r"\b5 min(?:utes)? skew\b|\(5 min skew allowed\)", contract), (
        "the contract no longer publishes the 5-minute clock skew")


def test_the_contract_does_not_document_a_timestamp_form_the_code_refuses(tmp_path):
    """The contract is the AUTHORITY; drift between it and the validator is the defect.

    Five of six reviewers in one gate round found the same thing: the code was changed to
    refuse naive timestamps, and the contract kept saying "a timestamp with no offset is
    read as UTC" and listing "no offset at all" as accepted. The code's own refusal
    message points the operator at that document, so the guard was routed around by its
    own error text.

    Prose cannot be diffed against behaviour in general — but the specific claims can be
    executed. For each timestamp form the contract could describe, this asserts the
    contract's stance and the validator's stance agree.
    """
    contract = (REPO / ".claude" / "contracts" / "seven-agent-evidence.md").read_text(
        encoding="utf-8")

    # Every form, and what the validator ACTUALLY does with it, measured not assumed.
    forms = {
        "+00:00": True,
        "Z": True,
        "+02:00": False,
        "naive": False,
    }
    for form, should_pass in forms.items():
        # +6h, not +1h. With +1h and a `+02:00` suffix the resolved instant is BEFORE
        # created_at, so the document refused at the `expires <= created` check and the
        # UTC rule was never reached — deleting the UTC check left this row green.
        base = (_now() + timedelta(hours=6)).replace(microsecond=0, tzinfo=None)
        stamp = base.isoformat() + ("" if form == "naive" else
                                    ("Z" if form == "Z" else form))
        doc = _doc()
        doc["expires_at"] = stamp
        ok, reason, _ = validate_evidence(_write(tmp_path, doc), _SHA)
        assert ok is should_pass, (
            f"{form!r} timestamp: validator says {'accept' if ok else 'refuse'} "
            f"({reason}); the test table says {'accept' if should_pass else 'refuse'}")
        if not should_pass:
            assert "UTC" in reason, (
                f"{form!r} was refused, but for the wrong reason ({reason}) — the UTC "
                "rule was not what fired, so this row does not pin it")

    # The contract must not advertise either refused form as acceptable, and must not
    # still be telling operators that a bare local time is read as UTC.
    banned = [
        "A timestamp with no offset is read as UTC",
        "or no offset at all\n   (read as UTC)",
    ]
    for phrase in banned:
        assert phrase not in contract, (
            f"the contract still documents a form the validator refuses: {phrase!r}")

    # ...and it must positively state the rule the code enforces.
    assert "must state UTC explicitly" in contract, (
        "the contract no longer states the explicit-UTC requirement that "
        "gate_evidence._parse_ts enforces")


def test_the_contract_publishes_the_ttl_ceiling_the_signer_enforces(tmp_path, monkeypatch):
    """The `--ttl` maximum existed only in argparse help and a source comment.

    An operator planning a standby rollback artifact needs to know it cannot outlive
    24 hours BEFORE the incident, not at exit 2 during one.
    """
    contract = (REPO / ".claude" / "contracts" / "seven-agent-evidence.md").read_text(
        encoding="utf-8")
    ceiling = int(MAX_VALIDITY.total_seconds() // 60)
    # Anchored to the CLAIM, not the digits. A bare `str(ceiling) in contract` is
    # satisfied by the number appearing anywhere — including inside the worked example
    # two lines below, which is how the first version of this pin passed while the
    # ceiling itself had been deleted.
    assert re.search(rf"maximum\s*\*{{0,2}}\s*{ceiling}\b", contract), (
        f"the contract does not publish the {ceiling}-minute --ttl ceiling as a MAXIMUM; "
        "sign_deploy_authorization enforces it")

    # And the enforcement is real at the boundary, in both directions. Rollback is
    # evidence-exempt, so no evidence file is needed here.
    store = _signer_env(tmp_path, monkeypatch)
    assert _sign([_SHA, "rollback", "Both", "--ttl", str(ceiling)]) == 0
    minted = json.loads((store / f"{_SHA}.rollback.json").read_text(encoding="utf-8"))
    before = minted["expires_at"]

    assert _sign([_SHA, "rollback", "Both", "--ttl", str(ceiling + 1)]) == 2
    # Asserting the store still holds ONE file cannot fail: an over-ceiling mint would
    # write to the same artifact_name and os.replace would overwrite it. Assert the
    # CONTENT is untouched instead.
    after = json.loads((store / f"{_SHA}.rollback.json").read_text(encoding="utf-8"))
    assert after["expires_at"] == before, "the refused mint overwrote the existing artifact"


def test_the_clock_skew_boundary_is_where_the_constant_says_it_is(tmp_path):
    """Derive the inputs FROM the constant, so the pair brackets the real boundary.

    Fixed 2-minute / 2-hour cases could not distinguish a 5-minute skew from a
    119-minute one, so widening CLOCK_SKEW survived them. Just inside must pass, just
    outside must refuse — at whatever value the constant holds.
    """
    inside = _now() + CLOCK_SKEW - timedelta(seconds=30)
    ok, reason, _ = validate_evidence(
        _write(tmp_path, _doc(created=inside, expires=inside + timedelta(hours=1))), _SHA)
    assert ok, f"a document inside the skew allowance was refused: {reason}"

    outside = _now() + CLOCK_SKEW + timedelta(minutes=1)
    _refuse(tmp_path, _doc(created=outside, expires=outside + timedelta(hours=1)),
            "in the future")


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


def test_a_zero_length_window_is_refused(tmp_path):
    """`expires == created` — a surviving mutant until now.

    Every other test used expires < created, so relaxing `<=` to `<` failed nothing:
    a document with created == expires == now+2min passes the skew check (not far
    enough future), the cap (window is 0), and the expiry check (now < expires), and
    would be ACCEPTED. A window with no duration is not a window.
    """
    at = _now() + timedelta(minutes=2)
    _refuse(tmp_path, _doc(created=at, expires=at), "not after created_at")


@pytest.mark.parametrize("offset,label", [
    ("+12:00", "east"),
    ("-11:00", "west"),
    ("+05:30", "half-hour offset"),
    ("+00:01", "one minute off UTC"),
])
def test_non_utc_offsets_are_refused(tmp_path, offset, label):
    """Offsets were the last place a human and the validator could read one document
    two ways. `created_at: 12:00+12:00` with `expires_at: 12:00-11:00` reads as two
    identical instants and resolves to a 23-hour window — inside the cap, accepted.
    Requiring UTC removes the divergence rather than documenting it."""
    doc = _doc()
    doc["created_at"] = f"2026-08-05T12:00:00{offset}"
    reason, _ = _refuse(tmp_path, doc, "must be UTC")
    assert "created_at" in reason


def test_the_mixed_offset_window_that_motivated_the_utc_rule(tmp_path):
    """The concrete document from the round-5 security finding, pinned as refused."""
    doc = _doc()
    doc["created_at"] = "2026-08-05T12:00:00+12:00"
    doc["expires_at"] = "2026-08-05T12:00:00-11:00"
    _refuse(tmp_path, doc, "must be UTC")


@pytest.mark.parametrize("spelling", ["+00:00", "Z"])
def test_utc_spellings_are_accepted(tmp_path, spelling):
    """Both canonical UTC forms must work — refusing `Z` would reject the spelling the
    contract itself recommends."""
    created = _now() - timedelta(minutes=1)
    expires = created + timedelta(hours=2)

    def fmt(dt):
        base = dt.replace(microsecond=0, tzinfo=None).isoformat()
        return base + ("+00:00" if spelling == "+00:00" else "Z")

    ok, reason, _ = validate_evidence(
        _write(tmp_path, _doc(created=fmt(created), expires=fmt(expires))), _SHA)
    assert ok, reason


def test_a_naive_now_is_honoured_as_utc_not_discarded(tmp_path):
    """`fail closed throughout` had one hole: a naive `now=` raised TypeError out of
    validate_evidence instead of producing a verdict.

    Asserting only `ok is True` with a naive `utcnow()` was VACUOUS: an implementation
    that silently threw the caller's value away and used real UTC now would pass, since
    the two are the same instant. So the naive value here is deliberately FAR from now —
    two days back, which makes the document's created_at look two days in the future. A
    discarding implementation accepts; an honouring one refuses.
    """
    doc = _doc()
    ok, reason, _ = validate_evidence(
        _write(tmp_path, doc), _SHA, now=datetime.utcnow() - timedelta(days=2))
    assert not ok, "the caller's naive `now` was discarded, not honoured"
    assert "in the future" in reason

    # ...and the near case still validates, so the refusal above is about the VALUE,
    # not about naive input being rejected outright.
    ok, reason, _ = validate_evidence(_write(tmp_path, doc), _SHA, now=datetime.utcnow())
    assert ok, reason


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


@pytest.mark.parametrize("field", ["created_at", "expires_at"])
def test_naive_timestamps_are_refused(tmp_path, field):
    """A bare local time is the SAME defect as a non-UTC offset, in a worse shape.

    It was accepted and read as UTC. This project's operator works in UTC+2 (the
    `+02:00` stamps in .claude/memory/TASK_STATE.md), so writing `16:00:00` to mean
    14:00Z bought two extra hours of validity — and on `expires_at` that direction is
    FAIL-OPEN. Unlike an offset, there is nothing on the line for a reader to notice.
    """
    doc = _doc()
    doc[field] = _now().replace(tzinfo=None, microsecond=0).isoformat()
    reason, _ = _refuse(tmp_path, doc, "must state UTC explicitly")
    assert field in reason


def test_the_offset_refusal_does_not_advise_deleting_the_offset(tmp_path):
    """The message is part of the mechanism.

    The old text offered "or no offset at all" as a remedy, so an operator refused for
    writing `+02:00` would delete it — turning `14:00+02:00` (12:00Z) into `14:00Z` and
    silently shifting the instant two hours later. Refusing naive timestamps closes the
    landing site; this pins that the message stops pointing at it.
    """
    doc = _doc()
    doc["created_at"] = "2026-08-05T12:00:00+02:00"
    reason, _ = _refuse(tmp_path, doc, "must be UTC")
    assert "no offset" not in reason, "the refusal still advises deleting the offset"
    assert "convert the time itself" in reason


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
    """A directory that exists is not "not found" — the message named the wrong cause."""
    ok, reason, _ = validate_evidence(str(tmp_path), _SHA)
    assert not ok and "is a directory" in reason


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
    ["--gate-evidence", "__absent__.json"],        # evidence that does not exist
])
def test_a_refused_mint_writes_nothing_to_the_store(tmp_path, monkeypatch, argv_tail):
    """A refusal must not leave an artifact.

    Scope, stated precisely: this pins that no ARTIFACT is written on the evidence
    refusal paths, which are the newest ones. It does NOT catch a hoisted
    `os.makedirs`, because `_signer_env` pre-creates the store, so an early makedirs is
    a no-op here and the directory is empty either way. The `_load_key` ordering is
    pinned separately, by test_evidence_is_validated_before_the_signing_key_is_loaded.
    """
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
    monkeypatch.delenv("PZ_DEPLOY_AUTH_REPO", raising=False)
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

    # EDIT the content first: an implementation that re-checked a present file and only
    # tolerated absence would pass a deletion-only test, so absence alone does not prove
    # "never re-checked".
    Path(ev).write_text(json.dumps(_doc(), indent=4), encoding="utf-8")
    assert _evaluate(_SHA, "rollback", "Both", dict(os.environ))[0] == "allow", (
        "a rollback was gated on its evidence CONTENT — the digest is audit trail")

    # ...and then delete it, for the absence half.
    assert _sign([_SHA, "rollback", "Both", "--gate-evidence", ev]) == 0
    os.remove(ev)   # the deploy path would DENY here
    assert _evaluate(_SHA, "rollback", "Both", dict(os.environ))[0] == "allow", (
        "a rollback was gated on its evidence — if this is now intended, the exemption "
        "documented in .claude/contracts/seven-agent-evidence.md must change with it")


def test_an_evidence_tamper_denial_does_not_burn_the_single_use_artifact(tmp_path, monkeypatch):
    """A recoverable denial must stay recoverable.

    `evaluate()` re-checks the evidence digest BEFORE `_consume()`. If those were
    reordered, an operator who tampered with — or merely reformatted — the evidence
    would get a denial AND lose the artifact, turning a fixable mistake into a re-mint
    mid-deploy. Nothing pinned the ordering; hoisting `_consume` broke no test.
    """
    _signer_env(tmp_path, monkeypatch)
    ev = _write(tmp_path, _doc())
    original = Path(ev).read_bytes()
    assert _sign([_SHA, "deploy", "Both", "--gate-evidence", ev]) == 0

    Path(ev).write_text(json.dumps(_doc(), indent=4), encoding="utf-8")
    assert _evaluate(_SHA, "deploy", "Both", dict(os.environ))[0] == "deny"

    Path(ev).write_bytes(original)          # undo the change
    decision, reason = _evaluate(_SHA, "deploy", "Both", dict(os.environ))
    assert decision == "allow", (
        f"the artifact was consumed by a denial it should have survived: {reason}")


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


# ── gaps the round-6 gate named as unpinned ──────────────────────────────────

def test_expires_at_non_utc_offset_is_refused_on_its_own(tmp_path):
    """The offset check must be applied at BOTH call sites.

    Every other offset test mutates `created_at`, which is validated first — so
    applying the UTC rule only to `created_at` survived them all. `expires_at` is the
    field where a widened window actually lands.
    """
    doc = _doc()
    doc["expires_at"] = "2026-08-05T18:00:00+05:30"
    reason, _ = _refuse(tmp_path, doc, "must be UTC")
    assert "expires_at" in reason


def test_the_evidence_ref_is_covered_by_the_signature(tmp_path, monkeypatch):
    """`gate_evidence_ref` must be IN `_SIGNED_FIELDS`, pinned behaviourally.

    The whole tamper-binding design rests on it: the digest is signed "without adding a
    signed field" precisely because this one was already signed. Yet every existing
    tamper test re-signs the body or edits the evidence FILE, so removing
    `gate_evidence_ref` from `_SIGNED_FIELDS` broke nothing. Here the ref is edited in
    the stored artifact WITHOUT the key — only a signature that covers it can refuse.
    """
    import deploy_authorization
    store = _signer_env(tmp_path, monkeypatch)
    ev = _write(tmp_path, _doc())
    assert _sign([_SHA, "deploy", "Both", "--gate-evidence", ev]) == 0

    other = _write(tmp_path, _doc(created=_now() - timedelta(hours=1)), name="other.json")
    path = store / f"{_SHA}.deploy.json"
    auth = json.loads(path.read_text(encoding="utf-8"))
    auth["gate_evidence_ref"] = format_ref(os.path.abspath(other), digest_file(other))
    path.write_text(json.dumps(auth, indent=2, sort_keys=True), encoding="utf-8")

    decision, reason = _evaluate(_SHA, "deploy", "Both", dict(os.environ))
    assert decision == "deny", (
        "the evidence ref was repointed at a different file without the key and the "
        "authorization was ACCEPTED — gate_evidence_ref is not covered by the signature")
    assert "signature" in reason, f"denied for the wrong reason: {reason!r}"


@pytest.mark.parametrize("ttl", [0, -1, 1441, 43200])
def test_out_of_range_ttl_is_refused(tmp_path, monkeypatch, ttl):
    """The artifact TTL is the ONLY bound on the deploy window.

    `evaluate()` re-hashes the evidence but never re-runs `validate_evidence`, so the
    24h MAX_VALIDITY is enforced at signing time only. An unbounded `--ttl` let
    `--ttl 43200` mint a 30-day authorization off a document capped at 24 hours, while
    the contract described the artifact TTL as "shorter" — a safety word with nothing
    enforcing it, which is the identical defect this tooling fixed for evidence.
    """
    store = _signer_env(tmp_path, monkeypatch)
    ev = _write(tmp_path, _doc())
    assert _sign([_SHA, "deploy", "Both", "--gate-evidence", ev, "--ttl", str(ttl)]) == 2
    assert not list(store.iterdir()), "a refused mint wrote to the store"


def test_the_ttl_ceiling_is_accepted_at_the_boundary(tmp_path, monkeypatch):
    """Exactly at the cap is accepted — the documented rollback TTL (1440) sits there,
    so an off-by-one would break the incident path."""
    _signer_env(tmp_path, monkeypatch)
    ev = _write(tmp_path, _doc())
    at_cap = int(MAX_VALIDITY.total_seconds() // 60)
    assert at_cap == 1440
    assert _sign([_SHA, "deploy", "Both", "--gate-evidence", ev, "--ttl", str(at_cap)]) == 0
    assert _sign([_SHA, "rollback", "Both", "--ttl", str(at_cap)]) == 0


def test_the_authorization_may_not_outlive_the_evidence(tmp_path, monkeypatch):
    """The two windows must not COMPOSE.

    Capping --ttl at 24h is not enough by itself: evidence created at T and valid to
    T+24h, minted against at T+23h59m with --ttl 1440, would deploy at T+47h58m —
    roughly double what "the evidence window is capped at 24 hours, enforced" leads a
    reader to expect. `evaluate()` cannot catch it, because at use time it re-hashes the
    evidence and never re-validates it, so an expired document is invisible there.

    The signer therefore clamps the artifact expiry to the evidence expiry, which also
    makes the contract's word "shorter" true rather than aspirational.
    """
    store = _signer_env(tmp_path, monkeypatch)
    created = _now() - timedelta(hours=1)
    evidence_expires = created + timedelta(hours=2)        # 1h of life left
    ev = _write(tmp_path, _doc(created=created, expires=evidence_expires))

    assert _sign([_SHA, "deploy", "Both", "--gate-evidence", ev, "--ttl", "1440"]) == 0
    art = json.loads((store / f"{_SHA}.deploy.json").read_text(encoding="utf-8"))
    minted = datetime.fromisoformat(art["expires_at"])

    assert minted <= evidence_expires + timedelta(seconds=1), (
        f"the authorization expires at {minted.isoformat()}, AFTER the evidence expires "
        f"at {evidence_expires.isoformat()} — the two windows composed")
    # ...and it is genuinely shorter than the requested TTL, not merely capped at 24h.
    assert minted < _now() + timedelta(hours=23), (
        "the 1440-minute TTL was honoured in full despite shorter evidence")


def test_a_ttl_inside_the_evidence_window_is_left_alone(tmp_path, monkeypatch):
    """The clamp must not shorten a TTL that already fits — otherwise every mint would
    silently inherit the evidence expiry and --ttl would stop meaning anything."""
    store = _signer_env(tmp_path, monkeypatch)
    ev = _write(tmp_path, _doc(created=_now() - timedelta(minutes=1),
                               expires=_now() + timedelta(hours=20)))
    assert _sign([_SHA, "deploy", "Both", "--gate-evidence", ev, "--ttl", "60"]) == 0
    art = json.loads((store / f"{_SHA}.deploy.json").read_text(encoding="utf-8"))
    minted = datetime.fromisoformat(art["expires_at"])
    assert minted < _now() + timedelta(minutes=75), (
        f"a 60-minute TTL was stretched to {minted.isoformat()}")


def test_the_artifact_expiry_is_enforced_at_use_time(tmp_path, monkeypatch):
    """The gap the --ttl cap's entire justification rests on.

    `sign_deploy_authorization` argues the artifact TTL is "the ONLY bound on the deploy
    window". Nothing pinned that bound: deleting the `now >= expires_at` check in
    `evaluate()` killed no test in either file, while making the window UNBOUNDED. A
    safety word with nothing enforcing it is exactly what the cap was added to fix — this
    pins the enforcement one layer down.
    """
    import deploy_authorization
    store = _signer_env(tmp_path, monkeypatch)
    ev = _write(tmp_path, _doc())
    assert _sign([_SHA, "deploy", "Both", "--gate-evidence", ev, "--ttl", "60"]) == 0

    # Back-date the artifact's expiry and re-sign, so only the expiry check can refuse.
    path = store / f"{_SHA}.deploy.json"
    auth = json.loads(path.read_text(encoding="utf-8"))
    auth["expires_at"] = (_now() - timedelta(minutes=1)).isoformat()
    auth["signature"] = deploy_authorization.sign(auth, deploy_authorization._load_key())
    path.write_text(json.dumps(auth, indent=2, sort_keys=True), encoding="utf-8")

    decision, reason = _evaluate(_SHA, "deploy", "Both", dict(os.environ))
    assert decision == "deny", "an expired authorization was accepted"
    assert "expired" in reason, f"denied for the wrong reason: {reason!r}"


def test_an_artifact_that_is_not_yet_valid_is_refused(tmp_path, monkeypatch):
    """The sibling check at the other end of the window, equally unpinned."""
    import deploy_authorization
    store = _signer_env(tmp_path, monkeypatch)
    ev = _write(tmp_path, _doc())
    assert _sign([_SHA, "deploy", "Both", "--gate-evidence", ev, "--ttl", "60"]) == 0

    path = store / f"{_SHA}.deploy.json"
    auth = json.loads(path.read_text(encoding="utf-8"))
    auth["issued_at"] = (_now() + timedelta(hours=1)).isoformat()
    auth["signature"] = deploy_authorization.sign(auth, deploy_authorization._load_key())
    path.write_text(json.dumps(auth, indent=2, sort_keys=True), encoding="utf-8")

    decision, reason = _evaluate(_SHA, "deploy", "Both", dict(os.environ))
    assert decision == "deny", "an authorization from the future was accepted"
    assert "not yet valid" in reason, (
        f"denied for the wrong reason: {reason!r} — with issued_at pushed an hour out "
        "and the clamped expires_at ~60m away, an expiry denial would also read as a "
        "pass here")


def test_a_jti_that_escapes_the_store_is_refused(tmp_path, monkeypatch):
    """The jti becomes a path component in `_consume` (store/consumed/<jti>.used).

    A non-empty-string check let `"../x"` place the single-use marker outside the store
    — and that marker IS the replay record. Minting one needs the key, so this is not
    agent-reachable; a durable safety record should still not depend on the attacker
    lacking a key.
    """
    import deploy_authorization
    store = _signer_env(tmp_path, monkeypatch)
    ev = _write(tmp_path, _doc())
    assert _sign([_SHA, "deploy", "Both", "--gate-evidence", ev]) == 0

    path = store / f"{_SHA}.deploy.json"
    auth = json.loads(path.read_text(encoding="utf-8"))
    auth["jti"] = "../escaped"
    auth["signature"] = deploy_authorization.sign(auth, deploy_authorization._load_key())
    path.write_text(json.dumps(auth, indent=2, sort_keys=True), encoding="utf-8")

    decision, reason = _evaluate(_SHA, "deploy", "Both", dict(os.environ))
    assert decision == "deny", "a jti containing a path traversal was accepted"
    assert "jti" in reason
    # `_consume` builds <store>/consumed/<jti>.used, so "../escaped" would land in
    # <store>/escaped.used — NOT tmp_path/escaped.used, which the earlier version of
    # this assertion checked and which therefore could never fail.
    assert not (store / "escaped.used").exists(), "the marker escaped into the store root"
    assert not (tmp_path / "escaped.used").exists(), "the marker escaped the store entirely"
    consumed = store / "consumed"
    if consumed.is_dir():
        assert not any(consumed.iterdir()), "a refused jti still consumed the artifact"


def test_use_time_re_hashes_but_never_re_validates_the_document(tmp_path, monkeypatch):
    """Pin the PERMISSIVE property, deliberately — and pin the case that matters.

    `evaluate()` compares the evidence digest; it does not re-run `validate_evidence`.
    The operational consequence is the migration hazard both the runbook and the
    governance doc call out: an authorization minted BEFORE the JSON format existed, and
    digest-bound to a MARKDOWN evidence file, still verifies. The bytes are unchanged, so
    the digest matches, and nothing checks the document against the schema. That is why
    the migration instruction says re-mint every deploy/reconcile artifact regardless of
    what its ref looks like — the no-digest case is not the only one.

    An earlier version demonstrated the property via evidence expiry. That stopped being
    observable once the signer began clamping the artifact expiry to the evidence expiry
    (they now expire together), and it had been vacuous before that anyway: `evaluate()`
    takes no `now`, so the evidence had not really expired at use time and a
    re-validating implementation would have allowed too.
    """
    import deploy_authorization
    store = _signer_env(tmp_path, monkeypatch)

    # A Markdown evidence file — the retired format, which validate_evidence refuses.
    md = tmp_path / "gate.md"
    md.write_text(f"TARGET_SHA: {_SHA}\nAGENT: all\nSTATUS: GO\n", encoding="utf-8")
    ok, _reason, _ = validate_evidence(str(md), _SHA)
    assert not ok, "precondition: the Markdown document must fail validation"

    # Hand-mint an artifact digest-bound to it, exactly as a pre-JSON signer would have.
    now = _now()
    auth = {
        "reviewed_sha": _SHA, "action": "deploy", "scope": "Both", "from_sha": None,
        "repository": "",
        "gate_evidence_ref": format_ref(str(md.resolve()), digest_file(str(md))),
        "issued_at": now.isoformat(),
        "expires_at": (now + timedelta(minutes=60)).isoformat(),
        "jti": "0123abcd-4567-89ef-0123-456789abcdef",
    }
    auth["signature"] = deploy_authorization.sign(auth, deploy_authorization._load_key())
    (store / f"{_SHA}.deploy.json").write_text(
        json.dumps(auth, indent=2, sort_keys=True), encoding="utf-8")

    decision, reason = _evaluate(_SHA, "deploy", "Both", dict(os.environ))
    assert decision == "allow", (
        f"use time now re-validates the evidence document ({reason}). That may be an "
        "improvement, but the migration instruction in .claude/commands/deploy.md and "
        "service/docs/production_deployment_rule.md documents the opposite — change "
        "them in the same commit.")


# ── reconcile: the half of a published claim that had no test ────────────────

def _sign_reconcile(ev, ttl="60"):
    return _sign([_SHA, "reconcile", "Both", "--from-sha", _OTHER_SHA,
                  "--gate-evidence", ev, "--ttl", ttl])


def _evaluate_reconcile():
    return _evaluate(_SHA, "reconcile", "Both", dict(os.environ), from_sha=_OTHER_SHA)


def test_editing_evidence_after_signing_denies_a_reconcile(tmp_path, monkeypatch):
    """`gate_evidence` publishes: "FOR `deploy` AND `reconcile` ONLY … re-hashes the file
    at use time." Half of that claim had no test behind it.

    Deleting `"reconcile"` from the action tuple in `deploy_authorization.evaluate()`
    killed ZERO tests in either file: the existing reconcile tests only ever exercised
    SIGNING, or denials produced by the filename / equality / signature layers with the
    evidence file untouched. And reconcile is the more dangerous action — the module's
    own docstring calls it "strictly more dangerous than deploy, because it is the one
    mode that runs against a runtime the identity gate has already refused."
    """
    _signer_env(tmp_path, monkeypatch)
    ev = _write(tmp_path, _doc())
    assert _sign_reconcile(ev) == 0
    assert _evaluate_reconcile()[0] == "allow", "precondition: the artifact verifies"

    assert _sign_reconcile(ev) == 0                      # fresh, unconsumed artifact
    Path(ev).write_text(json.dumps(_doc(), indent=4), encoding="utf-8")
    decision, reason = _evaluate_reconcile()
    assert decision == "deny", "a reconcile accepted edited gate evidence"
    assert "changed" in reason, f"denied for the wrong reason: {reason!r}"


def test_deleting_evidence_after_signing_denies_a_reconcile(tmp_path, monkeypatch):
    _signer_env(tmp_path, monkeypatch)
    ev = _write(tmp_path, _doc())
    assert _sign_reconcile(ev) == 0
    os.remove(ev)
    decision, reason = _evaluate_reconcile()
    assert decision == "deny", "a reconcile accepted missing gate evidence"
    assert "no longer readable" in reason, f"denied for the wrong reason: {reason!r}"


def test_a_prebinding_authorization_is_refused_for_reconcile(tmp_path, monkeypatch):
    """The pre-binding shape is not grandfathered for reconcile either."""
    import deploy_authorization
    store = _signer_env(tmp_path, monkeypatch)
    ev = _write(tmp_path, _doc())
    assert _sign_reconcile(ev) == 0

    path = store / deploy_authorization.artifact_name(_SHA, "reconcile", _OTHER_SHA)
    auth = json.loads(path.read_text(encoding="utf-8"))
    auth["gate_evidence_ref"] = "see PR #1094"
    auth.pop("signature")
    auth["signature"] = deploy_authorization.sign(auth, deploy_authorization._load_key())
    path.write_text(json.dumps(auth, indent=2, sort_keys=True), encoding="utf-8")

    decision, reason = _evaluate_reconcile()
    assert decision == "deny"
    assert "digest-bound" in reason or "no digest" in reason, (
        f"denied for the wrong reason: {reason!r}")


def test_the_evidence_clamp_applies_to_reconcile_too(tmp_path, monkeypatch):
    """The clamp is action-agnostic, but reconcile is the action worth pinning."""
    store = _signer_env(tmp_path, monkeypatch)
    created = _now() - timedelta(hours=1)
    evidence_expires = created + timedelta(hours=2)
    ev = _write(tmp_path, _doc(created=created, expires=evidence_expires))
    assert _sign_reconcile(ev, ttl="1440") == 0

    import deploy_authorization
    art = json.loads((store / deploy_authorization.artifact_name(
        _SHA, "reconcile", _OTHER_SHA)).read_text(encoding="utf-8"))
    minted = datetime.fromisoformat(art["expires_at"])
    assert minted <= evidence_expires + timedelta(seconds=1), (
        "a reconcile authorization outlived the evidence that justified it")


def test_the_verifier_cli_accepts_the_5_argument_reconcile_shape(tmp_path, monkeypatch, capsys):
    """The reconcile argv form the deploy script actually uses had no CLI-level test.

    `main()` is sys.argv-shaped: it accepts `len(argv) in (4, 5)` and reads `argv[4]`
    as `from_sha`. The 5-element form is reconcile, and it is what the deploy script
    invokes -- `& python $helper $Sha $Action $UnitScope $SourceSha`.

    What the suite pinned before this test: the REJECTED arities on both sides of the
    accepted range (3 and 6 -> exit 2, `test_the_verifier_cli_usage_contract`), and the
    4-element DEPLOY form (`test_the_verifier_cli_maps_allow_and_deny_to_exit_codes`).
    The 5-element form in between was never exercised through the CLI. The reconcile
    tests above reach `evaluate()` directly with `from_sha=` as a KEYWORD, so none of
    them cross the positional-decoding boundary.

    That mattered because the mapping is load-bearing and invisible: reordering the
    trailing positionals, or narrowing the accepted arity to `== 4`, left every test
    green while breaking reconcile authorization on the only path production uses --
    surfacing first on a Windows host, mid-incident, since reconcile is the mode
    reached for when the identity gate has already refused the runtime.

    Issue #1098.
    """
    import deploy_authorization
    _signer_env(tmp_path, monkeypatch)
    ev = _write(tmp_path, _doc())
    assert _sign_reconcile(ev) == 0, "precondition: a reconcile artifact was minted"

    rc = deploy_authorization.main(["prog", _SHA, "reconcile", "Both", _OTHER_SHA])
    out = capsys.readouterr().out
    assert rc == 0, (
        f"the 5-argument reconcile CLI shape did not exit 0 (out={out!r}). This is the "
        "exact argv the deploy script builds for reconcile; a non-zero exit is BLOCKED "
        "at the PowerShell caller.")
    assert "ALLOW" in out.upper()


def test_the_verifier_cli_denies_a_wrong_argv4_without_consuming_the_artifact(
        tmp_path, monkeypatch, capsys):
    """Arity alone is a weak pin: `main()` could accept 5 arguments and ignore the fifth.

    Two properties, both about `argv[4]`:

    (a) The direction is decoded from `argv[4]` specifically. A wrong from_sha there
        has to DENY -- if it were dropped or read from the wrong index, this call would
        be indistinguishable from the correct one and the deploy script would authorize
        a reconcile whose proved starting identity was never checked.

    (b) That denial does NOT spend the artifact: `evaluate()` returns long before
        `_consume()` (`deploy_authorization.py:302`), so a mistyped from_sha must not
        burn an operator's single-use token -- a typo during an incident should cost a
        retry, not a re-mint that needs the signing key.

    Which guard fires matters, so the deny REASON is asserted rather than the exit code
    alone. A wrong argv[4] is caught at the FILENAME layer: `artifact_name()` embeds
    from_sha, so a different direction resolves to a different path and denies with "no
    authorization artifact". It never reaches the equality check at `:249` -- that layer
    is only reachable by editing a stored artifact, which is what
    test_deploy_reconcile_signing.py covers (see its three-layer note at `:155-158`).

    Two other reconcile guards also deny with rc 1 -- "reconcile requires from_sha"
    (`:200-201`) and the self-reconcile "nothing to reconcile" (`:202-203`). Asserting
    only "DENY" would let this test silently drift onto either one and keep passing
    while no longer testing argv[4] decoding at all.

    Issue #1098.
    """
    import deploy_authorization
    _signer_env(tmp_path, monkeypatch)
    ev = _write(tmp_path, _doc())
    assert _sign_reconcile(ev) == 0, "precondition: a reconcile artifact was minted"

    wrong_from = "f" * 40
    # Must differ from BOTH the signed direction and the target: colliding with _SHA
    # would trip the `:202-203` self-reconcile guard instead of the mismatch guard.
    assert wrong_from != _OTHER_SHA, "the negative case must differ from the signed direction"
    assert wrong_from != _SHA, "the negative case must differ from the reconcile TARGET"

    rc = deploy_authorization.main(["prog", _SHA, "reconcile", "Both", wrong_from])
    out = capsys.readouterr().out
    assert rc == 1, (
        f"a reconcile with the WRONG from_sha in argv[4] was not denied (out={out!r}); "
        "argv[4] is being ignored or read from the wrong position")
    assert "no authorization artifact" in out.lower(), (
        f"denied, but not by the direction-binding filename layer (out={out!r}) -- this "
        "test is no longer exercising argv[4] decoding")

    # The artifact must survive the denial: a refused direction is not a use, so the
    # operator's single-use token is still spendable on the correct call.
    rc = deploy_authorization.main(["prog", _SHA, "reconcile", "Both", _OTHER_SHA])
    out = capsys.readouterr().out
    assert rc == 0, (
        f"the correct direction failed after a denied one (out={out!r}) -- a rejected "
        "from_sha consumed the artifact, which would burn an operator's authorization "
        "on a typo")


def test_the_verifier_cli_denies_a_reconcile_with_argv4_missing(tmp_path, monkeypatch, capsys):
    """The adjacent CLI shape: reconcile requested, but `argv[4]` absent entirely.

    `Deploy-PZ.ps1:129` picks its call shape on `if ($SourceSha)`, so a falsy
    `$SourceSha` routes into the `else` branch and drops the 4th token -- producing a
    4-element argv with action "reconcile". `evaluate()`'s "reconcile requires from_sha"
    guard (`deploy_authorization.py:200-201`) is covered directly in
    test_deploy_reconcile_signing.py, but through `evaluate()`, not through the argv
    decoding this module's CLI performs. Pinning it here keeps the whole reconcile
    branch of `main()`'s arity handling observable.

    Issue #1098.
    """
    import deploy_authorization
    _signer_env(tmp_path, monkeypatch)
    ev = _write(tmp_path, _doc())
    assert _sign_reconcile(ev) == 0, "precondition: a reconcile artifact was minted"

    rc = deploy_authorization.main(["prog", _SHA, "reconcile", "Both"])
    out = capsys.readouterr().out
    assert rc == 1, (
        f"a reconcile with no from_sha in argv was not denied (out={out!r}); a missing "
        "direction must never be treated as an unconstrained reconcile")
    assert "from_sha" in out.lower(), f"denied for the wrong reason: {out!r}"


def test_the_repository_binding_is_enforced(tmp_path, monkeypatch):
    """`repository` is a SIGNED field with a documented purpose — "an artifact minted for
    one repository would validate against another if the key were reused".

    Both fixtures delenv PZ_DEPLOY_AUTH_REPO, so `expected_repo` was always empty and the
    branch never executed: deleting the check killed nothing.
    """
    _signer_env(tmp_path, monkeypatch)
    monkeypatch.setenv("PZ_DEPLOY_AUTH_REPO", "estrella/pz")
    ev = _write(tmp_path, _doc())
    assert _sign([_SHA, "deploy", "Both", "--gate-evidence", ev]) == 0
    assert _evaluate(_SHA, "deploy", "Both", dict(os.environ))[0] == "allow"

    # Same artifact, different repository identity at use time.
    assert _sign([_SHA, "deploy", "Both", "--gate-evidence", ev]) == 0
    env = dict(os.environ)
    env["PZ_DEPLOY_AUTH_REPO"] = "someone-else/pz"
    decision, reason = _evaluate(_SHA, "deploy", "Both", env)
    assert decision == "deny", "an artifact minted for one repository validated in another"
    assert "repositor" in reason, f"denied for the wrong reason: {reason!r}"


def test_a_naive_timestamp_in_a_signed_artifact_is_refused(tmp_path, monkeypatch):
    """`_parse_iso` must REFUSE a naive timestamp, not fill it to UTC.

    Filling resolved the original TypeError crash in the permitting direction: a
    hand-built artifact carrying naive LOCAL time would have `issued_at` read as UTC,
    shifting it earlier and making the "not yet valid" check less likely to fire. The
    sibling validator refuses naive outright; both halves of the authorization path must
    mean the same thing by a timestamp.
    """
    import deploy_authorization
    store = _signer_env(tmp_path, monkeypatch)
    ev = _write(tmp_path, _doc())
    assert _sign([_SHA, "deploy", "Both", "--gate-evidence", ev]) == 0

    path = store / f"{_SHA}.deploy.json"
    auth = json.loads(path.read_text(encoding="utf-8"))
    auth["expires_at"] = (_now() + timedelta(hours=1)).replace(tzinfo=None).isoformat()
    auth["signature"] = deploy_authorization.sign(auth, deploy_authorization._load_key())
    path.write_text(json.dumps(auth, indent=2, sort_keys=True), encoding="utf-8")

    decision, reason = _evaluate(_SHA, "deploy", "Both", dict(os.environ))
    assert decision == "deny", "a naive timestamp was interpreted rather than refused"
    assert "expires_at" in reason or "malformed" in reason, (
        f"denied for the wrong reason: {reason!r}")


@pytest.mark.parametrize("argv", [[], ["prog"], ["prog", "a", "b"],
                                 ["prog", "a", "b", "c", "d", "e"]])
def test_the_verifier_cli_usage_contract(tmp_path, monkeypatch, argv):
    """The deploy script reaches this module through its CLI and branches on the EXIT
    CODE. Nothing pinned the argv handling or the mapping, so a refactor could change
    the caller's behaviour without failing a test."""
    import deploy_authorization
    _signer_env(tmp_path, monkeypatch)
    assert deploy_authorization.main(argv) == 2


def test_the_verifier_cli_maps_allow_and_deny_to_exit_codes(tmp_path, monkeypatch, capsys):
    """allow -> 0, deny -> 1. The PowerShell caller treats non-zero as BLOCKED."""
    import deploy_authorization
    _signer_env(tmp_path, monkeypatch)
    ev = _write(tmp_path, _doc())
    assert _sign([_SHA, "deploy", "Both", "--gate-evidence", ev]) == 0

    # sys.argv-shaped: main() indexes from argv[1], so argv[0] is the program name.
    # The deploy script invokes it as `python <helper> <sha> <action> <scope> [<from>]`.
    rc = deploy_authorization.main(["prog", _SHA, "deploy", "Both"])
    out = capsys.readouterr().out
    assert rc == 0, f"a valid authorization did not exit 0 (out={out!r})"
    assert "ALLOW" in out.upper()

    rc = deploy_authorization.main(["prog", _SHA, "deploy", "Both"])   # consumed
    out = capsys.readouterr().out
    assert rc == 1, f"a denied authorization did not exit 1 (out={out!r})"
    assert "DENY" in out.upper()
