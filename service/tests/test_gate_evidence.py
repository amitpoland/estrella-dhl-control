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
