"""test_council_merge_guard.py — Council-authorized merge gate (fail-closed).

Deterministic tests for .claude/hooks/merge_authorization.py and its integration
with pz-deploy-guard.py. No network, no real store — the trust inputs are injected.
"""
from __future__ import annotations

import importlib.util
import pathlib
from datetime import datetime, timedelta, timezone

import pytest

_HOOKS = pathlib.Path(__file__).resolve().parents[2] / ".claude" / "hooks"


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, _HOOKS / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ma = _load("merge_authorization", "merge_authorization.py")
guard = _load("pz_deploy_guard", "pz-deploy-guard.py")

_KEY = b"test-signing-key-not-in-repo"
_REPO = "amitpoland/estrella-dhl-control"
_HEAD = "a" * 40
_NOW = datetime(2026, 7, 19, 12, 0, 0, tzinfo=timezone.utc)


def _auth(**over):
    files = over.pop("changed_files", ["service/app/services/foo.py",
                                       "service/tests/test_foo.py"])
    a = {
        "version": "1",
        "authorization_id": "jti-1",
        "repository": _REPO,
        "pr_number": 949,
        "head_sha": _HEAD,
        "base_sha": "b" * 40,
        "changed_files": files,
        "changed_files_digest": ma.compute_changed_files_digest(files),
        "council_verdict": "PASS",
        "focused_tests_ref": "focused:abc",
        "regression_tests_ref": "root:160/160",
        "merge_method": "squash",
        "issued_at": "2026-07-19T11:00:00+00:00",
        "expires_at": "2026-07-19T13:00:00+00:00",
    }
    a.update(over)
    a["signature"] = ma.sign(a, _KEY)   # sign AFTER overrides (unless overridden)
    if "signature" in over:
        a["signature"] = over["signature"]
    return a


def _ctx(auth, *, enabled=True, key=_KEY, consumed=None):
    consumed = consumed if consumed is not None else set()
    return ma.MergeContext(
        enabled=enabled, key=key, repository=_REPO,
        load_authorization=lambda pr: (auth if auth and str(auth["pr_number"]) == str(pr) else None),
        is_consumed=lambda jti: jti in consumed,
        mark_consumed=lambda jti: consumed.add(jti),
        now=lambda: _NOW,
    )


def _cmd(pr=949, method="--squash", head=_HEAD, admin=False):
    parts = [f"gh pr merge {pr}", method]
    if head:
        parts.append(f"--match-head-commit {head}")
    if admin:
        parts.append("--admin")
    return " ".join(parts)


def _decision(command, ctx):
    return ma.evaluate_merge(command, ctx)[0]


# ── the 15 required scenarios ────────────────────────────────────────────────

def test_1_valid_exact_sha_authorization_allows():
    consumed = set()
    d, r = ma.evaluate_merge(_cmd(), _ctx(_auth(), consumed=consumed))
    assert d == "allow", r
    assert "jti-1" in consumed          # consumed on allow

def test_2_missing_authorization_denies():
    assert _decision(_cmd(), _ctx(None)) == "deny"

def test_3_expired_authorization_denies():
    a = _auth(expires_at="2026-07-19T11:30:00+00:00")   # before _NOW
    assert _decision(_cmd(), _ctx(a)) == "deny"

def test_4_wrong_pr_denies():
    # Force the loader to return the artifact so the validator's OWN
    # artifact_pr != parsed["pr"] check (not the loader's key filter) is exercised.
    a = _auth(pr_number=949)
    ctx = _ctx(a)
    ctx._load_authorization = lambda pr: a
    d, r = ma.evaluate_merge(_cmd(pr=950), ctx)
    assert d == "deny" and "PR mismatch" in r

def test_5_wrong_head_sha_denies():
    assert _decision(_cmd(head="c" * 40), _ctx(_auth())) == "deny"

def test_6_changed_file_digest_mismatch_denies():
    a = _auth()
    a["changed_files_digest"] = "0" * 64      # tamper digest → but then signature invalid
    a["signature"] = ma.sign(a, _KEY)          # re-sign so we isolate the digest check
    assert _decision(_cmd(), _ctx(a)) == "deny"

def test_7_replay_consumed_denies():
    assert _decision(_cmd(), _ctx(_auth(), consumed={"jti-1"})) == "deny"

def test_8_protected_file_change_denies():
    a = _auth(changed_files=[".claude/hooks/pz-deploy-guard.py"])
    assert _decision(_cmd(), _ctx(a)) == "deny"

def test_9_schema_migration_change_denies():
    a = _auth(changed_files=["service/app/migrations/0007_add_column.py"])
    assert _decision(_cmd(), _ctx(a)) == "deny"

def test_10_guard_self_modification_denies():
    for f in (".claude/hooks/merge_authorization.py", ".claude/settings.json",
              "service/tests/test_council_merge_guard.py"):
        a = _auth(changed_files=[f, "service/app/x.py"])
        assert _decision(_cmd(), _ctx(a)) == "deny", f

def test_11_unsupported_merge_method_denies():
    assert _decision(_cmd(method="--merge"), _ctx(_auth())) == "deny"
    assert _decision(_cmd(method="--rebase"), _ctx(_auth())) == "deny"

def test_12_unresolved_or_failed_review_denies():
    a = _auth(council_verdict="CHANGES_REQUIRED")
    assert _decision(_cmd(), _ctx(a)) == "deny"

def test_13_failing_or_missing_tests_denies():
    a = _auth(focused_tests_ref="")
    assert _decision(_cmd(), _ctx(a)) == "deny"
    a2 = _auth(regression_tests_ref="")
    assert _decision(_cmd(), _ctx(a2)) == "deny"

def test_14_ordinary_approved_feature_pr_allows():
    a = _auth(changed_files=["service/app/api/routes_proforma.py",
                             "service/tests/test_routes_x.py"])
    assert _decision(_cmd(), _ctx(a)) == "allow"

def test_15_false_positive_inspection_command_denies():
    # a command that merely CONTAINS the phrase (e.g. an inspection grep) is not a
    # merge — parser rejects it → deny (never an accidental allow).
    d, r = ma.evaluate_merge('grep -n "gh pr merge" file.py', _ctx(_auth()))
    assert d == "deny"


# ── additional fail-closed guarantees ────────────────────────────────────────

def test_flag_default_off_denies():
    assert _decision(_cmd(), _ctx(_auth(), enabled=False)) == "deny"

def test_no_key_denies():
    assert _decision(_cmd(), _ctx(_auth(), key=None)) == "deny"

def test_tampered_signature_denies():
    a = _auth()
    a["council_verdict"] = "PASS"
    a["pr_number"] = 950            # tamper AFTER signing → signature no longer matches
    assert _decision(_cmd(pr=950), _ctx(a)) == "deny"

def test_admin_flag_denies():
    assert _decision(_cmd(admin=True), _ctx(_auth())) == "deny"

def test_missing_match_head_denies():
    assert _decision(_cmd(head=None), _ctx(_auth())) == "deny"

def test_repo_mismatch_denies():
    a = _auth(repository="someone/else")
    assert _decision(_cmd(), _ctx(a)) == "deny"

def test_top_level_secrets_dir_denies():
    # security-review MEDIUM: a top-level `secrets/` path must be protected
    # (the former "/secrets" marker missed repo-relative "secrets/...").
    a = _auth(changed_files=["secrets/signing_key.py", "service/app/x.py"])
    assert _decision(_cmd(), _ctx(a)) == "deny"

def test_mark_consumed_failure_fails_closed():
    # security-review LOW: if the consumed token cannot be persisted, deny
    # (else the same signed artifact could replay).
    def _boom(_jti):
        raise RuntimeError("read-only store")
    ctx = _ctx(_auth())
    ctx._mark_consumed = _boom
    assert ma.evaluate_merge(_cmd(), ctx)[0] == "deny"

def test_auth_layer_change_denies():
    # security seat advisory: service/app/auth/ (JWT+session) is operator-only.
    a = _auth(changed_files=["service/app/auth/session.py", "service/app/x.py"])
    assert _decision(_cmd(), _ctx(a)) == "deny"

def test_malformed_pr_number_denies():
    # module contract: deny (not raise) on a non-integer pr_number that still
    # somehow carries a valid signature. Force the loader to return the artifact
    # so the validator's own int()-guard is exercised (not the "no artifact" path).
    a = _auth(pr_number="abc")
    ctx = _ctx(a)
    ctx._load_authorization = lambda pr: a
    d, r = ma.evaluate_merge(_cmd(), ctx)
    assert d == "deny" and "malformed" in r

def test_default_mark_consumed_no_store_raises():
    # the default writer must RAISE (not silently pass) when no store is set,
    # so evaluate_merge's try/except converts it to a deny.
    with pytest.raises(Exception):
        ma._default_mark_consumed("jti-x")


# ── Council Level-3 review follow-ups (compound cmd, unreached branches) ──────

def test_compound_command_second_merge_denies():
    # challenge DEFECT-1: a chained command must NOT run under one authorization.
    valid_tail = _cmd()  # authorized shape for PR 949
    for compound in (
        valid_tail + " && gh pr merge 950 --squash --match-head-commit " + ("b" * 40),
        valid_tail + " && rm -rf /",
        valid_tail + " ; echo pwned",
        valid_tail + " | tee log",
    ):
        assert _decision(compound, _ctx(_auth())) == "deny", compound

def test_auth_side_merge_method_mismatch_denies():
    # validator's OWN artifact merge_method gate (command is squash, artifact is not).
    a = _auth(merge_method="rebase")
    ctx = _ctx(a)
    ctx._load_authorization = lambda pr: a
    assert ma.evaluate_merge(_cmd(), ctx)[0] == "deny"

def test_not_yet_valid_authorization_denies():
    a = _auth(issued_at="2026-07-19T12:30:00+00:00")   # after _NOW (12:00)
    assert _decision(_cmd(), _ctx(a)) == "deny"

def test_unsupported_version_denies():
    a = _auth(version="2")
    assert _decision(_cmd(), _ctx(a)) == "deny"

def test_is_consumed_unreadable_fails_closed():
    # is_consumed raising (unreadable store) must deny, not propagate.
    ctx = _ctx(_auth())
    ctx._is_consumed = lambda jti: (_ for _ in ()).throw(RuntimeError("unreadable"))
    assert ma.evaluate_merge(_cmd(), ctx)[0] == "deny"

def test_end_to_end_replay_sequence_denies_second():
    # allow → consume → the SAME artifact denied on the second evaluation.
    consumed = set()
    ctx = _ctx(_auth(), consumed=consumed)
    assert ma.evaluate_merge(_cmd(), ctx)[0] == "allow"
    ctx2 = _ctx(_auth(), consumed=consumed)   # same consumed store
    assert ma.evaluate_merge(_cmd(), ctx2)[0] == "deny"

def test_wfirma_fiscal_route_change_denies():
    # challenge DEFECT-2: remote wFirma / fiscal write surface is operator-only.
    for f in ("service/app/api/routes_wfirma.py",
              "service/app/services/customer_master_db.py",
              "service/app/carrier/coordinator.py"):
        a = _auth(changed_files=[f, "service/app/x.py"])
        assert _decision(_cmd(), _ctx(a)) == "deny", f


# ── hook integration: current behaviour preserved (default deny) ─────────────

def test_hook_denies_merge_by_default_env(monkeypatch):
    # no PZ_AUTONOMOUS_MERGE_ENABLED → hook rule-2 denies (current behaviour intact)
    monkeypatch.delenv("PZ_AUTONOMOUS_MERGE_ENABLED", raising=False)
    label, reason = guard._classify_command("gh pr merge 949 --squash")
    assert label == "gh-pr-merge"
    assert "operator-only" in reason

def test_hook_other_rules_unchanged():
    # rule 1 (prod copy), rule 3 (push main) still deny; ordinary command passes
    assert guard._classify_command("robocopy X C:\\PZ\\app")[0] == "deploy-to-prod-PZ"
    assert guard._classify_command("git push origin main")[0] == "git-push-main"
    assert guard._classify_command("pytest -q")[0] is None

def test_hook_validator_error_fails_closed(monkeypatch):
    # if the validator import/exec fails, the hook must DENY (fail closed).
    import sys as _sys
    monkeypatch.setitem(_sys.modules, "merge_authorization", None)  # force ImportError
    label, _ = guard._classify_command("gh pr merge 949 --squash --match-head-commit " + _HEAD)
    assert label == "gh-pr-merge"
