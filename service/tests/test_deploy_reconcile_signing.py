"""The operator signer must be able to mint every action the verifier accepts.

`reconcile` was added to deploy_authorization (VALID_ACTIONS, a signed `from_sha`
field, and a two-SHA artifact filename) but the operator tool that mints artifacts
was never taught about it. It accepted `reconcile` as an action -- argparse takes
its choices straight from VALID_ACTIONS -- and then minted an artifact that could
never verify:

  * `from_sha` was never set, so the signed body carried None and the verifier
    returned "reconcile requires from_sha";
  * the filename was hardcoded `f"{sha}.{action}.json"` while the verifier looks up
    `artifact_name()` == `f"{to}.reconcile.{from}.json"`, so the file was not even
    found at the path the lookup uses.

A production tree whose bytes and marker disagree is repairable ONLY through
-Reconcile, so an unmintable reconcile authorization means the documented repair
path cannot be executed at all. These tests pin mint->verify as a round trip
rather than asserting on either side alone: an artifact nobody can verify is not
an authorization, and only the pair proves the two halves still agree.

No real signing key is touched: every test points the key and store env vars at a
tmp_path.

GATE EVIDENCE. `deploy` and `reconcile` now require a validated seven-agent evidence
file (`.claude/hooks/gate_evidence.py`), so these mint calls supply one. The gate was
tightened deliberately, which makes an unmodified test here a stale-test signal, not a
reason to relax the signer -- Lesson O. `rollback` stays evidence-free on purpose: it is
the incident path and must not depend on assembling a fresh gate report.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parents[2] / ".claude" / "hooks"

# The hook modules this file loads by path. They shadow whatever else in the session
# holds these (very generic) top-level names -- see _isolate_hook_modules.
_HOOK_MODULES = ("gate_evidence", "deploy_authorization", "sign_deploy_authorization")


@pytest.fixture(autouse=True)
def _isolate_hook_modules():
    """Restore sys.modules after every test in this file.

    `_load` writes into `sys.modules` under bare names like `deploy_authorization`,
    which is required -- `sign_deploy_authorization` does a plain
    `from deploy_authorization import ...`, so the dependency must be resolvable by
    name while the module executes. What was missing is the other half: nothing put
    sys.modules back. Every test left three freshly-executed modules registered
    globally, so a later test in the same session (in ANY file) could bind to a
    module object this file happened to execute last, with this file's tmp_path env
    already read. Test order then decides behaviour, which is how a suite starts
    passing or failing depending on what ran before it.
    """
    saved = {name: sys.modules.get(name) for name in _HOOK_MODULES}
    try:
        yield
    finally:
        for name, module in saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


def _load(name):
    spec = importlib.util.spec_from_file_location(name, HOOKS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def signing_env(tmp_path, monkeypatch):
    """A throwaway key + store. Never the operator's real key."""
    key = tmp_path / "test.key"
    key.write_text("0" * 64, encoding="utf-8")
    store = tmp_path / "store"
    store.mkdir()
    monkeypatch.setenv("PZ_DEPLOY_AUTH_KEY_FILE", str(key))
    monkeypatch.setenv("PZ_DEPLOY_AUTH_DIR", str(store))
    monkeypatch.delenv("PZ_DEPLOY_AUTH_KEY", raising=False)
    monkeypatch.delenv("PZ_DEPLOY_AUTH_REPO", raising=False)
    return store


FROM = "a" * 40
TO = "b" * 40


@pytest.fixture()
def evidence(tmp_path):
    """A valid seven-agent GO for TO, as the signer now requires.

    Strict JSON per `.claude/contracts/seven-agent-evidence.md`. The schema itself is
    exercised in test_gate_evidence.py; here it is only a precondition, so this builds
    the minimal valid document and nothing more.
    """
    ge = _load("gate_evidence")
    now = datetime.now(timezone.utc)
    doc = {
        "schema_version": ge.SCHEMA_VERSION,
        "target_sha": TO,
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(hours=2)).isoformat(),
        "agents": [{"agent": a, "status": "GO", "blockers": [], "risks": []}
                   for a in sorted(ge.REQUIRED_AGENTS)],
        "lead_verdict": "GO",
    }
    path = tmp_path / "gate-evidence.json"
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return str(path)


def test_reconcile_artifact_mints_and_verifies(signing_env, evidence):
    """The round trip that was impossible before: mint a reconcile, verify it."""
    signer = _load("sign_deploy_authorization")
    auth = _load("deploy_authorization")

    rc = signer.main([TO, "reconcile", "Both", "--from-sha", FROM, "--ttl", "60",
                      "--gate-evidence", evidence])
    assert rc == 0, "signer refused to mint a reconcile authorization"

    # Written where the verifier actually looks.
    expected = signing_env / auth.artifact_name(TO, "reconcile", FROM)
    assert expected.is_file(), (
        f"artifact not at the path the verifier resolves; store holds "
        f"{[p.name for p in signing_env.iterdir()]}"
    )
    assert json.loads(expected.read_text(encoding="utf-8"))["from_sha"] == FROM

    decision, reason = auth.evaluate(TO, "reconcile", "Both", from_sha=FROM)
    assert decision == "allow", f"minted reconcile did not verify: {reason}"


def test_reconcile_artifact_is_bound_to_its_direction(signing_env, evidence):
    """One ordered pair only -- an artifact must not repair a different drift."""
    signer = _load("sign_deploy_authorization")
    auth = _load("deploy_authorization")
    assert signer.main([TO, "reconcile", "Both", "--from-sha", FROM,
                        "--gate-evidence", evidence]) == 0

    other = "c" * 40
    decision, _ = auth.evaluate(TO, "reconcile", "Both", from_sha=other)
    assert decision == "deny", "a reconcile artifact repaired a different starting identity"


def _refusal_output(signer, argv):
    """(rc, stdout) — the reason matters, not just the exit code.

    Both the from_sha guards and the gate-evidence check return 2. Asserting on `rc`
    alone therefore does not distinguish them: with evidence omitted, deleting the
    from_sha guards outright left these tests green, because the flow fell through to
    "no gate evidence supplied" and still returned 2. Supplying valid evidence makes the
    from_sha guard the ONLY remaining reason to refuse, and reading the message proves
    it is the one that fired.
    """
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = signer.main(argv)
    return rc, buf.getvalue()


def test_reconcile_without_from_sha_is_refused(signing_env, evidence):
    """Minting an unverifiable artifact is worse than refusing: it looks like authority."""
    signer = _load("sign_deploy_authorization")
    rc, out = _refusal_output(
        signer, [TO, "reconcile", "Both", "--gate-evidence", evidence])
    assert rc == 2
    assert "requires --from-sha" in out, f"refused for the wrong reason: {out!r}"
    assert not list(signing_env.iterdir()), "a refused mint still wrote an artifact"


@pytest.mark.parametrize("action", ["deploy", "rollback"])
def test_from_sha_refused_for_non_reconcile(signing_env, evidence, action):
    """from_sha is signed, so a deploy carrying one is a different operation shape
    and the verifier denies it. Refuse at mint time rather than at 3am.

    Evidence is supplied for both actions — harmless for rollback, which is exempt —
    so that the from_sha guard is the only check left that can refuse.
    """
    signer = _load("sign_deploy_authorization")
    rc, out = _refusal_output(
        signer, [TO, action, "Both", "--from-sha", FROM, "--gate-evidence", evidence])
    assert rc == 2
    assert "only meaningful for reconcile" in out, f"refused for the wrong reason: {out!r}"
    assert not list(signing_env.iterdir()), "a refused mint still wrote an artifact"


@pytest.mark.parametrize("action", ["deploy", "rollback"])
def test_plain_actions_still_mint_and_verify(signing_env, evidence, action):
    """Negative control: adding the signed field must not break the existing shapes."""
    signer = _load("sign_deploy_authorization")
    auth = _load("deploy_authorization")
    argv = [TO, action, "Both"]
    if action == "deploy":                      # rollback is evidence-exempt
        argv += ["--gate-evidence", evidence]
    assert signer.main(argv) == 0
    assert (signing_env / auth.artifact_name(TO, action)).is_file()
    decision, reason = auth.evaluate(TO, action, "Both")
    assert decision == "allow", reason


def test_signer_can_mint_every_action_the_verifier_accepts(signing_env, evidence):
    """The general pin. This drift happened because the two sides were extended
    independently; VALID_ACTIONS is the shared authority, so every action in it
    must be mintable. A new action added to the verifier fails here until the
    operator tool can actually produce it."""
    signer = _load("sign_deploy_authorization")
    auth = _load("deploy_authorization")
    assert auth.VALID_ACTIONS, "no actions resolved -- import authority is broken"

    unmintable = {}
    for action in auth.VALID_ACTIONS:
        argv = [TO, action, "Both"]
        if action == "reconcile":
            argv += ["--from-sha", FROM]
        if action in ("deploy", "reconcile"):
            argv += ["--gate-evidence", evidence]
        try:
            rc = signer.main(argv)
        except SystemExit as exc:          # argparse rejected the action outright
            unmintable[action] = f"argparse exit {exc.code}"
            continue
        if rc != 0:
            unmintable[action] = f"signer returned {rc}"
            continue
        kw = {"from_sha": FROM} if action == "reconcile" else {}
        decision, reason = auth.evaluate(TO, action, "Both", **kw)
        if decision != "allow":
            unmintable[action] = f"minted but did not verify: {reason}"

    assert not unmintable, (
        "the verifier accepts actions the operator signer cannot mint, so the "
        f"documented repair path cannot be executed: {json.dumps(unmintable, indent=2)}"
    )
