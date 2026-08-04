"""Seven-agent gate evidence — parsing, validation, and tamper binding.

Covers `.claude/hooks/gate_evidence.py` and its two integration points:
`sign_deploy_authorization.py` (evidence gates signing) and
`deploy_authorization.evaluate()` (evidence re-checked at use time).

The authority model under test: evidence gates SIGNING, the signature gates the
DEPLOY. These tests must fail if that inverts — i.e. if evidence alone ever becomes
sufficient, or if a signed artifact stops being required.

Every test here runs on any OS. The PowerShell side of `-Release` cannot be exercised
from a Linux session and is covered separately by the deploy-authority suite's text
assertions plus operator parse validation.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
HOOKS = REPO / ".claude" / "hooks"
if str(HOOKS) not in sys.path:
    sys.path.insert(0, str(HOOKS))

from gate_evidence import (  # noqa: E402
    REQUIRED_AGENTS, digest_file, format_ref, parse_evidence, parse_ref, validate_evidence,
)

_SHA = "6e1de8b1a2c34d5e6f708192a3b4c5d6e7f80912"
_OTHER_SHA = "0123456789abcdef0123456789abcdef01234567"


def _evidence_text(target=_SHA, statuses=None, expires=None, omit=()):
    statuses = statuses or {}
    lines = [f"TARGET_SHA: {target}"]
    if expires:
        lines.append(f"EXPIRES_AT: {expires}")
    lines.append("")
    for agent in REQUIRED_AGENTS:
        if agent in omit:
            continue
        st = statuses.get(agent, "CLEAR")
        lines += [f"AGENT: {agent}", f"STATUS: {st}",
                  f"DISPOSITION: {'GO' if st in ('CLEAR', 'PASS', 'GO') else 'BLOCK:x'}", ""]
    return "\n".join(lines)


def _write(tmp_path, text, name="gate.md"):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return str(p)


# ── parsing ───────────────────────────────────────────────────────────────────

def test_parses_all_seven_agents():
    agents = parse_evidence(_evidence_text())
    assert set(REQUIRED_AGENTS).issubset(agents)


@pytest.mark.parametrize("written", [
    "deploy-security-reviewer",       # kebab-case, as agent files are named on disk
    "deploy_security_reviewer.md",    # with the file extension
    "  Deploy_Security_Reviewer  ",   # operator transcription
])
def test_agent_name_spellings_normalise(written):
    text = f"TARGET_SHA: {_SHA}\nAGENT: {written}\nSTATUS: CLEAR\n"
    assert "deploy_security_reviewer" in parse_evidence(text)


def test_parses_through_markdown_decoration():
    """Evidence is assembled by hand from seven reports; layout varies."""
    text = (f"# Gate\n**TARGET_SHA:** {_SHA}\n"
            + "".join(f"> - `AGENT`: {a}\n> STATUS: GO\n" for a in REQUIRED_AGENTS))
    ok, reason, _ = validate_evidence(_write_tmp(text), _SHA)
    assert ok, reason


_tmpfiles = []


def _write_tmp(text):
    import tempfile
    fd, path = tempfile.mkstemp(suffix=".md")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    _tmpfiles.append(path)
    return path


# ── validation: the refusal cases ─────────────────────────────────────────────

def test_valid_evidence_passes(tmp_path):
    ok, reason, digest = validate_evidence(_write(tmp_path, _evidence_text()), _SHA)
    assert ok, reason
    assert digest and len(digest) == 64


def test_evidence_for_another_sha_is_refused(tmp_path):
    """The headline case: a real gate run, attached to the wrong revision."""
    ok, reason, _ = validate_evidence(_write(tmp_path, _evidence_text(target=_OTHER_SHA)), _SHA)
    assert not ok
    assert "approves" in reason and _OTHER_SHA[:12] in reason


def test_missing_target_sha_is_refused_not_inferred(tmp_path):
    text = "\n".join(l for l in _evidence_text().splitlines() if not l.startswith("TARGET_SHA"))
    ok, reason, _ = validate_evidence(_write(tmp_path, text), _SHA)
    assert not ok
    assert "TARGET_SHA" in reason


@pytest.mark.parametrize("missing", list(REQUIRED_AGENTS))
def test_each_missing_agent_is_refused(tmp_path, missing):
    ok, reason, _ = validate_evidence(
        _write(tmp_path, _evidence_text(omit=(missing,))), _SHA)
    assert not ok
    assert missing in reason


@pytest.mark.parametrize("blocking", ["HOLD", "BLOCK", "FAIL"])
def test_any_blocking_status_is_refused(tmp_path, blocking):
    ok, reason, _ = validate_evidence(
        _write(tmp_path, _evidence_text(statuses={"deploy_qa_reviewer": blocking})), _SHA)
    assert not ok
    assert "deploy_qa_reviewer" in reason


def test_unrecognised_status_is_refused_not_treated_as_pass(tmp_path):
    """A typo must not read as approval.

    DISPOSITION is pinned to GO so only the STATUS branch can refuse: with a derived
    BLOCK disposition the blocking branch fires first and this never exercises the
    unrecognised-status path it exists for.
    """
    text = _evidence_text(omit=("deploy_security_reviewer",)).rstrip() + (
        "\n\nAGENT: deploy_security_reviewer\nSTATUS: CLEARED\nDISPOSITION: GO\n")
    ok, reason, _ = validate_evidence(_write(tmp_path, text), _SHA)
    assert not ok
    assert "unrecognised" in reason


def test_duplicate_agent_block_is_refused(tmp_path):
    """Blocker laundering by document layout (found by the 7-agent gate on PR #1094).

    Records were last-wins, so a second `AGENT: x` block later in the file silently
    overwrote an earlier STATUS: BLOCK. The digest binding cannot catch this -- it
    proves the file did not change after signing, not that the file says what it
    appears to say.
    """
    text = _evidence_text(statuses={"deploy_security_reviewer": "BLOCK"}).rstrip() + (
        "\n\nAGENT: deploy_security_reviewer\nSTATUS: CLEAR\nDISPOSITION: GO\n")
    ok, reason, _ = validate_evidence(_write(tmp_path, text), _SHA)
    assert not ok
    assert "restates a verdict" in reason and "deploy_security_reviewer" in reason


def test_notes_bullet_with_agent_line_is_refused(tmp_path):
    """Renamed from ...cannot_launder_a_blocking_verdict, which overclaimed.

    It only covered the route that includes an `AGENT:` line. Round 2 of the gate
    showed a bullet WITHOUT one still laundered, so the old name asserted a class was
    closed while a sibling route was open — Lesson Q rule 6. The class is covered by
    test_bare_status_restatement_* and test_unrecognised_agent_block_* below.
    """
    text = _evidence_text(statuses={"deploy_lead_coordinator": "BLOCK"}).rstrip() + (
        "\n\nNOTES:\n  - AGENT: deploy_lead_coordinator\n  - STATUS: GO\n")
    ok, reason, _ = validate_evidence(_write(tmp_path, text), _SHA)
    assert not ok
    assert "restates a verdict" in reason


def test_duplicate_agent_refused_even_when_both_blocks_agree(tmp_path):
    """Refused, not resolved. First-wins would silently drop a later BLOCK and
    last-wins is the defect, so a repeat is always a refusal."""
    text = _evidence_text().rstrip() + (
        "\n\nAGENT: deploy_qa_reviewer\nSTATUS: CLEAR\nDISPOSITION: GO\n")
    ok, reason, _ = validate_evidence(_write(tmp_path, text), _SHA)
    assert not ok and "restates a verdict" in reason


def test_bare_status_restatement_within_one_record_is_refused(tmp_path):
    """Round 2: laundering with NO second AGENT line at all.

    STATUS/DISPOSITION were last-write-wins *within* a record, so restating them after
    a blank line overrode an earlier BLOCK. Fixing only the duplicate-AGENT route left
    this open — verdict fields are now write-once.
    """
    text = _evidence_text(omit=("deploy_security_reviewer",)).rstrip() + (
        "\n\nAGENT: deploy_security_reviewer\nSTATUS: BLOCK\nDISPOSITION: BLOCK:creds\n"
        "\nSTATUS: CLEAR\nDISPOSITION: GO\n")
    ok, reason, _ = validate_evidence(_write(tmp_path, text), _SHA)
    assert not ok
    assert "restates a verdict" in reason


@pytest.mark.parametrize("field", ["STATUS", "DISPOSITION"])
def test_each_verdict_field_is_independently_write_once(tmp_path, field):
    """Isolate the two write-once branches.

    The combined test above restates BOTH fields, so it still passed with only one
    branch reverted — it could not tell which check was load-bearing. Each field is
    pinned alone here.
    """
    restate = "STATUS: CLEAR" if field == "STATUS" else "DISPOSITION: GO"
    text = _evidence_text(omit=("deploy_qa_reviewer",)).rstrip() + (
        f"\n\nAGENT: deploy_qa_reviewer\nSTATUS: BLOCK\nDISPOSITION: BLOCK:x\n\n{restate}\n")
    ok, reason, _ = validate_evidence(_write(tmp_path, text), _SHA)
    assert not ok, f"restating {field} alone was accepted"
    assert "restates a verdict" in reason


def test_unrecognised_agent_block_carrying_a_block_is_refused(tmp_path):
    """Round 2: a near-miss spelling must not swallow a BLOCK.

    `AGENT: deploy_security_reviewer (round 1)` normalises to a name outside
    REQUIRED_AGENTS, so its BLOCK was silently discarded and a later clean block
    registered as the only record. A blocking verdict is never dropped for having an
    unrecognised author.
    """
    text = ("AGENT: deploy_security_reviewer (round 1)\nSTATUS: BLOCK\n"
            "DISPOSITION: BLOCK:creds\n\n") + _evidence_text()
    ok, reason, _ = validate_evidence(_write(tmp_path, text), _SHA)
    assert not ok
    assert "unrecognised agent name" in reason


def test_contract_layout_with_interleaved_fields_still_validates(tmp_path):
    """Write-once must not break real evidence: gate_output_contract.md puts
    BLOCKERS / CHANGED_FILES / TESTS / RISKS (and blank lines) between STATUS and
    DISPOSITION. This is why `current` is NOT reset at blank lines."""
    lines = [f"TARGET_SHA: {_SHA}", ""]
    for agent in REQUIRED_AGENTS:
        lines += [f"AGENT: {agent}", "STATUS: CLEAR", "BLOCKERS:", "  - none",
                  "TESTS:", "  result: PASS", "", "DISPOSITION: GO", ""]
    ok, reason, _ = validate_evidence(_write(tmp_path, "\n".join(lines)), _SHA)
    assert ok, reason


def test_conflicting_target_sha_declarations_are_refused(tmp_path):
    """SHA-binding bypass found by the 7-agent gate on PR #1094.

    _find_target_sha was first-wins across TARGET_SHA / REVIEWED_SHA / APPROVED_SHA, so
    evidence genuinely approving commit A validated for commit B when a single line
    `APPROVED_SHA: B` was prepended -- the seven verdicts below were never cross-checked
    against it. That defeats the property this module exists to enforce.
    """
    real = _evidence_text(target=_SHA)
    forged = f"APPROVED_SHA: {_OTHER_SHA}\n" + real
    ok, reason, _ = validate_evidence(_write(tmp_path, forged), _OTHER_SHA)
    assert not ok
    assert "more than one distinct target SHA" in reason


def test_repeated_identical_target_sha_is_still_accepted(tmp_path):
    """Only DISTINCT declarations conflict; restating the same SHA is harmless."""
    text = f"REVIEWED_SHA: {_SHA}\n" + _evidence_text(target=_SHA)
    ok, reason, _ = validate_evidence(_write(tmp_path, text), _SHA)
    assert ok, reason


def test_evidence_file_is_read_exactly_once(tmp_path, monkeypatch):
    """TOCTOU: hashing and parsing must be ONE read.

    An earlier version of this test hashed an unmodified file twice and compared the
    digests — which passes on the two-read implementation it claimed to pin, because
    the window it names is never opened. Vacuous coverage is worse than none: it reads
    as protection. Counting opens is what actually distinguishes one read from two.
    """
    import builtins
    path = _write(tmp_path, _evidence_text())
    real_open, opens = builtins.open, []

    def counting_open(file, *a, **kw):
        if str(file) == path:
            opens.append(kw.get("mode", a[0] if a else "r"))
        return real_open(file, *a, **kw)

    monkeypatch.setattr(builtins, "open", counting_open)
    ok, reason, digest = validate_evidence(path, _SHA)
    assert ok, reason
    assert len(opens) == 1, f"evidence file opened {len(opens)} times: {opens}"
    assert digest == ge_module().digest_file(path)


def ge_module():
    import gate_evidence
    return gate_evidence


def test_swapped_file_cannot_bind_a_digest_to_unvalidated_bytes(tmp_path):
    """The property the single read buys: the returned digest is always the digest of
    the bytes that were actually parsed, on the refusal paths too."""
    import hashlib
    path = _write(tmp_path, _evidence_text(statuses={"deploy_qa_reviewer": "BLOCK"}))
    ok, _, digest = validate_evidence(path, _SHA)
    assert not ok
    # Hash the file's ACTUAL bytes, not the string that was written. `write_text`
    # translates \n -> \r\n on Windows, so comparing against text.encode() asserts a
    # platform-specific expectation and fails on the runner while passing on Linux.
    # The property under test is "the digest is over the bytes on disk" — so read them.
    with open(path, "rb") as fh:
        on_disk = fh.read()
    assert digest == hashlib.sha256(on_disk).hexdigest(), (
        "a refusal returned a digest that is not the parsed bytes")


@pytest.mark.parametrize("alias", ["EXPIRES_AT", "VALID_UNTIL"])
def test_both_expiry_aliases_are_enforced(tmp_path, alias):
    """VALID_UNTIL was a surviving mutant: deleting it from the alias tuple failed no
    test, and the failure direction is optimistic — expiry silently stops applying."""
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    text = f"{alias}: {past}\n" + _evidence_text()
    ok, reason, _ = validate_evidence(_write(tmp_path, text), _SHA)
    assert not ok and "expired" in reason


def test_timezone_naive_expiry_is_treated_as_utc_not_crashed_on(tmp_path):
    """The naive branch was never exercised; removing it raises TypeError out of
    validate_evidence instead of refusing cleanly."""
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).replace(tzinfo=None).isoformat()
    text = f"EXPIRES_AT: {past}\n" + _evidence_text()
    ok, reason, _ = validate_evidence(_write(tmp_path, text), _SHA)
    assert not ok and "expired" in reason

    future = (datetime.now(timezone.utc) + timedelta(hours=1)).replace(tzinfo=None).isoformat()
    ok, reason, _ = validate_evidence(
        _write(tmp_path, f"EXPIRES_AT: {future}\n" + _evidence_text()), _SHA)
    assert ok, reason


def test_blocking_disposition_alone_is_refused(tmp_path):
    """A lead-coordinator HOLD with a CLEAR status is a plausible real report, and was
    a surviving mutant: every test paired a blocking status with a blocking
    disposition, so deleting the disposition check failed nothing."""
    lines = [f"TARGET_SHA: {_SHA}", ""]
    for agent in REQUIRED_AGENTS:
        disp = "HOLD:needs rework" if agent == "deploy_lead_coordinator" else "GO"
        lines += [f"AGENT: {agent}", "STATUS: CLEAR", f"DISPOSITION: {disp}", ""]
    ok, reason, _ = validate_evidence(_write(tmp_path, "\n".join(lines)), _SHA)
    assert not ok
    assert "deploy_lead_coordinator" in reason


def test_expired_evidence_is_refused(tmp_path):
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    ok, reason, _ = validate_evidence(_write(tmp_path, _evidence_text(expires=past)), _SHA)
    assert not ok and "expired" in reason


def test_unexpired_evidence_passes(tmp_path):
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    ok, reason, _ = validate_evidence(_write(tmp_path, _evidence_text(expires=future)), _SHA)
    assert ok, reason


def test_malformed_expiry_is_refused(tmp_path):
    ok, reason, _ = validate_evidence(_write(tmp_path, _evidence_text(expires="soon")), _SHA)
    assert not ok and "malformed" in reason


def test_missing_file_and_empty_path_are_refused(tmp_path):
    assert not validate_evidence(str(tmp_path / "nope.md"), _SHA)[0]
    assert not validate_evidence("", _SHA)[0]


def test_bad_target_sha_argument_is_refused(tmp_path):
    ok, reason, _ = validate_evidence(_write(tmp_path, _evidence_text()), "not-a-sha")
    assert not ok and "40-character" in reason


# ── ref binding ───────────────────────────────────────────────────────────────

def test_ref_roundtrip():
    ref = format_ref("/tmp/gate.md", "a" * 64)
    assert parse_ref(ref) == ("/tmp/gate.md", "a" * 64)


def test_legacy_freetext_ref_yields_no_digest():
    """Pre-binding artifacts must be detectable, not silently accepted."""
    assert parse_ref("see PR #123") == ("see PR #123", None)


def test_windows_path_ref_roundtrips():
    ref = format_ref(r"C:\PZ-secrets\gate.md", "b" * 64)
    assert parse_ref(ref) == (r"C:\PZ-secrets\gate.md", "b" * 64)


# ── integration: evidence gates signing ───────────────────────────────────────

def _signer_env(tmp_path, monkeypatch):
    key = tmp_path / "k.key"
    key.write_text("0" * 64, encoding="utf-8")
    store = tmp_path / "store"
    store.mkdir()
    monkeypatch.setenv("PZ_DEPLOY_AUTH_KEY_FILE", str(key))
    monkeypatch.setenv("PZ_DEPLOY_AUTH_DIR", str(store))
    monkeypatch.delenv("PZ_DEPLOY_AUTH_REPO", raising=False)
    return store


def _sign(argv):
    import sign_deploy_authorization
    return sign_deploy_authorization.main(argv)


def test_deploy_without_evidence_is_refused(tmp_path, monkeypatch):
    _signer_env(tmp_path, monkeypatch)
    assert _sign([_SHA, "deploy", "Both"]) == 2


def test_deploy_with_wrong_sha_evidence_is_refused(tmp_path, monkeypatch):
    _signer_env(tmp_path, monkeypatch)
    ev = _write(tmp_path, _evidence_text(target=_OTHER_SHA))
    assert _sign([_SHA, "deploy", "Both", "--gate-evidence", ev]) == 2


def test_deploy_with_valid_evidence_signs_and_binds_the_digest(tmp_path, monkeypatch):
    store = _signer_env(tmp_path, monkeypatch)
    ev = _write(tmp_path, _evidence_text())
    assert _sign([_SHA, "deploy", "Both", "--gate-evidence", ev]) == 0
    art = json.loads((store / f"{_SHA}.deploy.json").read_text(encoding="utf-8"))
    path, digest = parse_ref(art["gate_evidence_ref"])
    assert digest == digest_file(ev)
    assert os.path.isabs(path)


def test_rollback_does_not_require_evidence(tmp_path, monkeypatch):
    """The incident path must not depend on assembling a fresh gate report."""
    _signer_env(tmp_path, monkeypatch)
    assert _sign([_SHA, "rollback", "Both"]) == 0


# ── integration: evidence re-checked at USE time ──────────────────────────────

def _evaluate(sha, action, scope, env, from_sha=None):
    import deploy_authorization
    return deploy_authorization.evaluate(sha, action, scope, from_sha=from_sha, env=env)


def test_signed_deploy_allows_when_evidence_is_untouched(tmp_path, monkeypatch):
    store = _signer_env(tmp_path, monkeypatch)
    ev = _write(tmp_path, _evidence_text())
    assert _sign([_SHA, "deploy", "Both", "--gate-evidence", ev]) == 0
    decision, reason = _evaluate(_SHA, "deploy", "Both", dict(os.environ))
    assert decision == "allow", reason


def test_editing_evidence_after_signing_denies(tmp_path, monkeypatch):
    """The window between signing and deploying is when evidence gets 'tidied up'."""
    _signer_env(tmp_path, monkeypatch)
    ev = _write(tmp_path, _evidence_text())
    assert _sign([_SHA, "deploy", "Both", "--gate-evidence", ev]) == 0
    Path(ev).write_text(_evidence_text() + "\n<!-- tidied -->\n", encoding="utf-8")
    decision, reason = _evaluate(_SHA, "deploy", "Both", dict(os.environ))
    assert decision == "deny"
    assert "changed" in reason


def test_deleting_evidence_after_signing_denies(tmp_path, monkeypatch):
    _signer_env(tmp_path, monkeypatch)
    ev = _write(tmp_path, _evidence_text())
    assert _sign([_SHA, "deploy", "Both", "--gate-evidence", ev]) == 0
    os.remove(ev)
    decision, reason = _evaluate(_SHA, "deploy", "Both", dict(os.environ))
    assert decision == "deny" and "no longer readable" in reason


def test_authorization_remains_single_use(tmp_path, monkeypatch):
    """Evidence binding must not weaken replay protection."""
    _signer_env(tmp_path, monkeypatch)
    ev = _write(tmp_path, _evidence_text())
    assert _sign([_SHA, "deploy", "Both", "--gate-evidence", ev]) == 0
    assert _evaluate(_SHA, "deploy", "Both", dict(os.environ))[0] == "allow"
    decision, reason = _evaluate(_SHA, "deploy", "Both", dict(os.environ))
    assert decision == "deny" and "consumed" in reason


def test_evidence_alone_never_authorizes(tmp_path, monkeypatch):
    """The load-bearing invariant: valid evidence with NO signed artifact is a denial.

    If this ever passes, evidence has become the gate and the signature has been
    demoted -- the exact inversion this design refuses.
    """
    _signer_env(tmp_path, monkeypatch)
    ev = _write(tmp_path, _evidence_text())
    ok, _, _ = validate_evidence(ev, _SHA)
    assert ok, "precondition: the evidence itself is valid"
    decision, reason = _evaluate(_SHA, "deploy", "Both", dict(os.environ))
    assert decision == "deny" and "no authorization artifact" in reason


def test_rollback_authorization_needs_no_evidence_at_use_time(tmp_path, monkeypatch):
    _signer_env(tmp_path, monkeypatch)
    assert _sign([_SHA, "rollback", "Both"]) == 0
    assert _evaluate(_SHA, "rollback", "Both", dict(os.environ))[0] == "allow"


def teardown_module(_module):
    for p in _tmpfiles:
        try:
            os.remove(p)
        except OSError:
            pass
