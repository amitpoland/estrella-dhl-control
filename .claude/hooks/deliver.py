"""The one canonical delivery entry point.

    python .claude/hooks/deliver.py plan      [--base origin/main]
    python .claude/hooks/deliver.py validate  [--base origin/main]
    python .claude/hooks/deliver.py status
    python .claude/hooks/deliver.py next

WHAT IT DOES
------------
classify (risk_lanes) -> validate (lane_validation) -> record a durable,
revision-bound checkpoint -> report the single next action.

WHAT IT DELIBERATELY CANNOT DO
-------------------------------
Deploy.  Authorize a deploy.  Merge.  Sign anything.  This module reports what
a change *needs*; ``deploy_authorization.py`` remains the sole authority for
whether a deploy may happen, and ``Deploy-PZ.ps1`` remains the sole mechanism
that performs one.  An L0 change reports ``deploy_required=false`` and there is
no code path here that could produce a deployment regardless of lane.

RUNTIME-PAYLOAD DIGEST
----------------------
CLAUDE.md: "A previous seven-agent GO remains valid only when a byte-for-byte
comparison between the previously approved runtime payload and the pending one
is empty."  The checkpoint therefore records a digest of the runtime payload --
the ``service/app`` tree object plus the blob ids of the 16 governed engine
files -- and NOT merely the commit SHA.  This implements the stated rule
directly: a later test-only or docs-only commit changes HEAD but leaves the
payload digest identical, so the checkpoint stays valid; any runtime byte change
invalidates it.

CHECKPOINT VALIDITY (Lesson Q rule 7)
-------------------------------------
A checkpoint records branch, HEAD, worktree and payload digest.  ``status``
re-derives all four and reports STALE rather than trusting the file.  A verdict
that cannot name its revision is re-run, not weighed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time

try:
    from . import risk_lanes, lane_validation  # type: ignore
except Exception:  # pragma: no cover - executed as a script
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import risk_lanes
    import lane_validation

STATE_RELPATH = ".claude/.delivery/checkpoint.json"

# ---------------------------------------------------------------- lifecycle
# Explicit states. A run is always in exactly one.
DISCOVERING = "DISCOVERING"
CLASSIFIED = "CLASSIFIED"
VALIDATED = "VALIDATED"
BLOCKED = "BLOCKED"                      # forbidden path -- terminal
CAMPAIGN_FAILURE = "CAMPAIGN_FAILURE"    # our defect -- repair and re-run
PRE_EXISTING_FAILURE = "PRE_EXISTING_FAILURE"  # tracked red -- advanceable
INCOMPLETE = "INCOMPLETE"                # did not finish -- diagnose, no retry loop
READY_TO_DELIVER = "READY_TO_DELIVER"
AWAITING_OPERATOR = "AWAITING_OPERATOR"  # a real operator-only boundary

TERMINAL = (BLOCKED,)
ADVANCEABLE = (VALIDATED, PRE_EXISTING_FAILURE, READY_TO_DELIVER)


# ------------------------------------------------------------------- helpers

def _git(root, *args, **kw):
    """Run git; return stdout stripped, or None on failure. Bounded."""
    try:
        proc = subprocess.run(["git"] + list(args), cwd=root, capture_output=True,
                              text=True, timeout=kw.get("timeout", 30))
    except Exception:
        return None
    return proc.stdout.strip() if proc.returncode == 0 else None


def payload_digest(root, rev="HEAD"):
    """Digest of the governed runtime payload at *rev*.

    service/app tree oid + the blob oid of each engine file named by the deploy
    configuration authority.  Returns (digest, detail).
    """
    config, err = risk_lanes.load_config(root)
    if config is None:
        return None, {"error": "config unavailable: %s" % err}

    app_rel = risk_lanes._app_prefix(config).rstrip("/")
    app_oid = _git(root, "rev-parse", "%s:%s" % (rev, app_rel))

    engines = {}
    for name in sorted(config.get("engine_files", [])):
        line = _git(root, "ls-tree", rev, "--", name)
        engines[name] = line.split()[2] if line and len(line.split()) >= 3 else None

    detail = {"app_tree": app_oid, "app_path": app_rel, "engine_blobs": engines}
    if not app_oid:
        return None, dict(detail, error="could not resolve %s:%s" % (rev, app_rel))

    blob = json.dumps(detail, sort_keys=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest(), detail


def changed_paths(root, base="origin/main"):
    """Paths changed between *base* and HEAD, plus uncommitted work."""
    out = set()
    merge_base = _git(root, "merge-base", base, "HEAD") or base
    for args in (("diff", "--name-only", "%s...HEAD" % merge_base),
                 ("diff", "--name-only", "HEAD"),
                 ("ls-files", "--others", "--exclude-standard")):
        got = _git(root, *args)
        if got:
            out.update(got.splitlines())
    return sorted(p for p in out if p.strip())


def context(root, base="origin/main"):
    head = _git(root, "rev-parse", "HEAD")
    digest, detail = payload_digest(root)
    return {
        "root": root,
        "branch": _git(root, "rev-parse", "--abbrev-ref", "HEAD"),
        "head": head,
        "base": base,
        "clean": _git(root, "status", "--porcelain") == "",
        "payload_digest": digest,
        "payload_detail": detail,
    }


# ---------------------------------------------------------------- checkpoint

def _state_path(root):
    return os.path.join(root, STATE_RELPATH.replace("/", os.sep))


def write_checkpoint(root, record):
    """Durable checkpoint. Lesson S ordering: content durable, then sentinel."""
    path = _state_path(root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(record, fh, indent=2, sort_keys=True)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)   # atomic; the record is complete before it is visible
    return path


def read_checkpoint(root):
    path = _state_path(root)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def checkpoint_status(root, saved):
    """Re-derive the revision and report whether *saved* still applies."""
    if not saved:
        return {"state": DISCOVERING, "valid": False,
                "why": "no checkpoint recorded"}

    now = context(root, saved.get("base", "origin/main"))
    drift = []
    if saved.get("branch") != now["branch"]:
        drift.append("branch %s -> %s" % (saved.get("branch"), now["branch"]))
    if saved.get("payload_digest") != now["payload_digest"]:
        drift.append("runtime payload digest changed")
    head_moved = saved.get("head") != now["head"]

    if drift:
        return {"state": saved.get("state"), "valid": False, "why": "; ".join(drift),
                "saved": saved, "now": now,
                "action": "re-run: validation bound to a payload that no longer exists"}
    if head_moved:
        return {"state": saved.get("state"), "valid": True,
                "why": ("HEAD moved %s -> %s but the runtime payload digest is "
                        "identical -- the checkpoint still binds (CLAUDE.md: a gate "
                        "verdict binds to the production bytes it reviewed)"
                        % (saved.get("head", "?")[:8], (now["head"] or "?")[:8])),
                "saved": saved, "now": now}
    return {"state": saved.get("state"), "valid": True,
            "why": "revision and payload unchanged", "saved": saved, "now": now}


# -------------------------------------------------------------- next action

def next_action(state, classification, ctx):
    if state == BLOCKED:
        return ("STOP -- forbidden path in the changeset: %s"
                % ", ".join(classification.to_dict()["blocked_paths"]))
    if state == CAMPAIGN_FAILURE:
        return "REPAIR -- unregistered test failure or ERROR; fix, then re-run validate"
    if state == INCOMPLETE:
        return ("DIAGNOSE -- a suite did not finish; inspect the producer before any "
                "re-run (Lesson S rule 6: no retry without a repair or transience evidence)")
    if state == CLASSIFIED:
        return "RUN -- deliver.py validate"
    if not classification.deploy_required:
        governance = any(d["klass"] == "GOVERNANCE" for d in classification.paths)
        base = ("no runtime payload byte changes -- no deploy, and the seven-agent "
                "gate is inapplicable because it binds to production bytes")
        if governance:
            return ("MERGE (operator-only) -- %s; but the changeset edits the safety "
                    "machinery itself, which merge_authorization.py lists in "
                    "PROTECTED_PATH_MARKERS, so merge is not autonomously "
                    "available by design" % base)
        return "MERGE -- %s (CLAUDE.md operating mode 2)" % base
    lane = classification.lane
    engine = classification.engine_paths
    parts = ["seven-agent gate on frozen head %s" % (ctx.get("head") or "?")[:8]]
    if lane == risk_lanes.LANE_L2:
        parts.append("extended review (sensitive class)")
    if engine:
        parts.append("Lesson J: SEPARATE engine sync for %s" % ", ".join(engine))
    parts.append("deploy authorization is operator-only "
                 "(sign via .claude/hooks/sign_deploy_authorization.py)")
    return "DELIVER -- " + "; then ".join(parts)


# -------------------------------------------------------------------- report

def build_report(root, base, validation=None):
    ctx = context(root, base)
    paths = changed_paths(root, base)
    cls = risk_lanes.classify(paths, root=root)
    cd = cls.to_dict()

    if cls.blocked:
        state = BLOCKED
    elif validation is None:
        state = CLASSIFIED
    else:
        state = {
            lane_validation.VERDICT_PASS: VALIDATED,
            lane_validation.VERDICT_PRE_EXISTING: PRE_EXISTING_FAILURE,
            lane_validation.VERDICT_CAMPAIGN: CAMPAIGN_FAILURE,
            lane_validation.VERDICT_FLOOR: CAMPAIGN_FAILURE,
            lane_validation.VERDICT_INCOMPLETE: INCOMPLETE,
        }.get(validation.get("verdict"), INCOMPLETE)
        if state in (VALIDATED, PRE_EXISTING_FAILURE):
            state = READY_TO_DELIVER

    return {
        "state": state,
        "advanceable": state in ADVANCEABLE,
        "terminal": state in TERMINAL,
        "lane": cd["lane"],
        "deploy_required": cd["deploy_required"],
        "required_validation": cd["required_validation"],
        "engine_paths": cd["engine_paths"],
        "blocked_paths": cd["blocked_paths"],
        "reasons": cd["reasons"],
        "changed_paths": paths,
        "classification": cd["paths"],
        "validation": validation,
        "next_action": next_action(state, cls, ctx),
        "branch": ctx["branch"],
        "head": ctx["head"],
        "base": base,
        "clean_tree": ctx["clean"],
        "payload_digest": ctx["payload_digest"],
        "worktree": root,
        "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "authority_note": (
            "This report classifies and validates. It grants nothing. Deployment "
            "authorization remains solely with deploy_authorization.py; deployment "
            "execution remains solely with .claude/deploy/Deploy-PZ.ps1."
        ),
    }


# ----------------------------------------------------------------- commands

def cmd_plan(root, args):
    print(json.dumps(build_report(root, args.base), indent=2, sort_keys=True))
    return 0


def cmd_validate(root, args):
    report = build_report(root, args.base)
    if report["state"] == BLOCKED:
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0

    needed = report["required_validation"]
    validation = {"ran": [], "skipped": []}

    if "metered-floors" in needed:
        validation.update(lane_validation.validate_metered(root=root,
                                                           timeout=args.timeout))
        validation["ran"].append("metered-floors")
    else:
        validation["verdict"] = lane_validation.VERDICT_PASS
        validation["skipped"].append(
            "metered-floors (lane %s touches no runtime payload byte)" % report["lane"])

    if "golden-regression" in needed:
        validation["golden"] = _run_golden(root, timeout=args.timeout)
        validation["ran"].append("golden-regression")
        if validation["golden"]["exit_code"] != 0:
            validation["verdict"] = lane_validation.VERDICT_CAMPAIGN
    else:
        validation["skipped"].append(
            "golden-regression (engine calculation authority untouched)")

    report = build_report(root, args.base, validation)
    write_checkpoint(root, report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


def _run_golden(root, timeout=600):
    """Root golden script -- engine calculation authority."""
    config, _ = risk_lanes.load_config(root)
    script = (config or {}).get("root_golden_script", "test_pz_regression.py")
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    started = time.time()
    try:
        proc = subprocess.run(["python", script], cwd=root, env=env,
                              capture_output=True, text=True, timeout=timeout)
        code, out = proc.returncode, (proc.stdout or "")
    except subprocess.TimeoutExpired:
        code, out = None, ""
    return {"script": script, "exit_code": code,
            "wall_ms": int((time.time() - started) * 1000),
            "tail": out.strip().splitlines()[-2:] if out else [],
            "_note": "exit_code is execution evidence, not authorization"}


def cmd_status(root, args):
    print(json.dumps(checkpoint_status(root, read_checkpoint(root)),
                     indent=2, sort_keys=True))
    return 0


def cmd_next(root, args):
    saved = read_checkpoint(root)
    status = checkpoint_status(root, saved)
    if saved and status["valid"]:
        print(saved.get("next_action", "?"))
    else:
        print(build_report(root, args.base)["next_action"])
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="Canonical delivery entry point")
    parser.add_argument("command", choices=["plan", "validate", "status", "next"])
    parser.add_argument("--base", default="origin/main")
    parser.add_argument("--timeout", type=int, default=900)
    args = parser.parse_args(argv)

    root = risk_lanes.repo_root()
    if not root:
        print(json.dumps({"error": "repository root not found"}))
        return 1

    return {"plan": cmd_plan, "validate": cmd_validate,
            "status": cmd_status, "next": cmd_next}[args.command](root, args)


if __name__ == "__main__":
    raise SystemExit(main())
