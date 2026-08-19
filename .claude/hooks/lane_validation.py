"""Contract-based validation verdicts for the delivery pipeline.

THE SEPARATION THIS MODULE EXISTS TO ENFORCE
--------------------------------------------
A process exit status is **execution evidence**: it proves a command ran and
what it returned.  It is not authorization.  This distinction is not academic
here -- it is measured:

    tests/test_carrier_*.py  ->  exit 1, 758 passed, 3 failed
    contract floor           ->  604 required   (PASS, +154)
    all 3 failures           ->  registered in the known-failing exclusions

A pipeline gating on ``exit == 0`` would block that deploy.  A pipeline gating
on the contract passes it, correctly.  So the verdict here is computed from
``.claude/contracts/test-baseline.md``, which states the rule itself:

    "Any failure listed here is accepted at gate time; any FAILED test NOT
     listed here, and any ERROR, is an unconditional block."
    "Any count below the required threshold is an unconditional block."

WHY --junitxml AND NOT THE SUMMARY LINE
----------------------------------------
Engineering Lesson S rule 8: never infer pytest results from summary-line
formatting -- ``-q``, ``--no-header``, non-tty stdout and terminal width all
change whether the summary is padded.  Completion comes from the exit status;
*content* comes from the JUnit XML, which is machine-readable by contract.

VERDICTS
--------
    PASS                   floors met, every failure registered, no errors
    PRE_EXISTING_FAILURE   failures present but all registered; floors met
    CAMPAIGN_FAILURE       an unregistered FAILED test, or any ERROR
    FLOOR_BREACH           pass count below the contract floor
    INCOMPLETE             the suite did not finish (timeout / crash)

Only PASS and PRE_EXISTING_FAILURE are advanceable.  This module still grants
nothing: deployment authorization remains with ``deploy_authorization.py``.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
import xml.etree.ElementTree as ET

try:
    from . import risk_lanes  # type: ignore
except Exception:  # pragma: no cover - executed as a script
    import risk_lanes

CONTRACT_RELPATH = ".claude/contracts/test-baseline.md"

VERDICT_PASS = "PASS"
VERDICT_PRE_EXISTING = "PRE_EXISTING_FAILURE"
VERDICT_CAMPAIGN = "CAMPAIGN_FAILURE"
VERDICT_FLOOR = "FLOOR_BREACH"
VERDICT_INCOMPLETE = "INCOMPLETE"

ADVANCEABLE = (VERDICT_PASS, VERDICT_PRE_EXISTING)

# | PZ regression | `tests/test_pz_*.py` | **260** | Unconditional deploy block |
_FLOOR_ROW = re.compile(
    r"^\|\s*([^|]+?)\s*\|\s*`([^`]+)`\s*\|\s*\*\*(\d+)\*\*\s*\|", re.MULTILINE
)
# | `test_x.py::test_y` | tracking | reason |
_EXCLUSION_ROW = re.compile(r"^\|\s*`([^`]+::[^`]+)`\s*\|", re.MULTILINE)


# --------------------------------------------------------------------------
# contract
# --------------------------------------------------------------------------

def load_contract(root=None):
    """Parse the baseline contract. Returns (contract, error).

    Fail-closed: any parse anomaly returns an error, and callers must treat an
    unreadable contract as non-advanceable rather than as "no constraints".
    """
    root = root or risk_lanes.repo_root()
    if not root:
        return None, "repo root not found"
    path = os.path.join(root, CONTRACT_RELPATH.replace("/", os.sep))
    try:
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
    except Exception as exc:
        return None, "%s: %s" % (type(exc).__name__, exc)

    suites = {}
    for name, pattern, floor in _FLOOR_ROW.findall(text):
        if not pattern.startswith("tests/"):
            continue
        suites[pattern] = {"name": name.strip(), "pattern": pattern,
                           "floor": int(floor)}
    if len(suites) < 2:
        return None, ("expected at least 2 metered suites in %s, parsed %d "
                      "-- refusing to proceed on a partially understood contract"
                      % (CONTRACT_RELPATH, len(suites)))

    exclusions = set(_EXCLUSION_ROW.findall(text))
    return {"suites": suites, "exclusions": exclusions, "path": path}, None


# --------------------------------------------------------------------------
# execution (evidence only)
# --------------------------------------------------------------------------

def run_suite(pattern, cwd, junit_path, timeout=900, extra_args=None):
    """Run one suite. Returns execution evidence -- never a verdict.

    Bounded by *timeout* (Lesson S rule 4: every waiter has a finite timeout).
    """
    import glob as _glob

    files = sorted(_glob.glob(os.path.join(cwd, pattern.replace("/", os.sep))))
    rel = [os.path.relpath(f, cwd).replace(os.sep, "/") for f in files]

    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"  # Lesson L: this host is cp1252

    argv = ["python", "-m", "pytest"] + rel + [
        "-q", "-p", "no:cacheprovider", "--junitxml=" + junit_path,
    ] + list(extra_args or [])

    started = time.time()
    timed_out = False
    try:
        proc = subprocess.run(argv, cwd=cwd, env=env, capture_output=True,
                              text=True, timeout=timeout)
        code, out = proc.returncode, (proc.stdout or "")
    except subprocess.TimeoutExpired:
        code, out, timed_out = None, "", True
    wall_ms = int((time.time() - started) * 1000)

    return {
        "pattern": pattern,
        "files": len(rel),
        "exit_code": code,
        "wall_ms": wall_ms,
        "timed_out": timed_out,
        "junit": junit_path,
        "junit_written": os.path.isfile(junit_path),
        "stdout_tail": out.strip().splitlines()[-3:] if out else [],
        "_note": "exit_code is execution evidence, not authorization",
    }


# --------------------------------------------------------------------------
# content (machine-readable)
# --------------------------------------------------------------------------

def _nodeid(classname, name):
    """junit classname/name -> 'test_module.py::Class::test_name'."""
    parts = [p for p in (classname or "").split(".") if p]
    idx = -1
    for i, part in enumerate(parts):
        if part.startswith("test_") and part[:1].islower():
            idx = i
    if idx < 0:
        return name
    tail = "".join("::" + p for p in parts[idx + 1:])
    return "%s.py%s::%s" % (parts[idx], tail, name)


def parse_junit(path):
    """Parse a JUnit XML report. Returns (result, error)."""
    try:
        root = ET.parse(path).getroot()
    except Exception as exc:
        return None, "%s: %s" % (type(exc).__name__, exc)

    failed, errored, skipped, total = [], [], 0, 0
    for case in root.iter("testcase"):
        total += 1
        nid = _nodeid(case.get("classname", ""), case.get("name", ""))
        if case.find("error") is not None:
            errored.append(nid)
        elif case.find("failure") is not None:
            failed.append(nid)
        elif case.find("skipped") is not None:
            skipped += 1
    passed = total - len(failed) - len(errored) - skipped
    return {"total": total, "passed": passed, "skipped": skipped,
            "failed": sorted(failed), "errors": sorted(errored)}, None


# --------------------------------------------------------------------------
# verdict (contract-based)
# --------------------------------------------------------------------------

def evaluate_suite(suite, execution, parsed, exclusions):
    """Apply the contract to one suite's parsed results."""
    if execution.get("timed_out") or parsed is None:
        return {
            "suite": suite["name"], "verdict": VERDICT_INCOMPLETE,
            "why": "suite did not complete (timeout or unreadable report)",
            "floor": suite["floor"], "passed": None,
            "unregistered_failures": [], "errors": [],
        }

    unregistered = [n for n in parsed["failed"] if n not in exclusions]
    registered = [n for n in parsed["failed"] if n in exclusions]

    if parsed["errors"]:
        verdict = VERDICT_CAMPAIGN
        why = "%d ERROR(s) -- the contract makes any ERROR an unconditional block" % len(parsed["errors"])
    elif unregistered:
        verdict = VERDICT_CAMPAIGN
        why = "%d FAILED test(s) not registered in the known-failing exclusions" % len(unregistered)
    elif parsed["passed"] < suite["floor"]:
        verdict = VERDICT_FLOOR
        why = "pass count %d is below the contract floor %d" % (parsed["passed"], suite["floor"])
    elif registered:
        verdict = VERDICT_PRE_EXISTING
        why = ("%d registered pre-existing failure(s); floor %d met with %d passed (+%d)"
               % (len(registered), suite["floor"], parsed["passed"],
                  parsed["passed"] - suite["floor"]))
    else:
        verdict = VERDICT_PASS
        why = ("floor %d met with %d passed (+%d), no failures"
               % (suite["floor"], parsed["passed"], parsed["passed"] - suite["floor"]))

    return {
        "suite": suite["name"], "pattern": suite["pattern"],
        "verdict": verdict, "why": why,
        "floor": suite["floor"], "passed": parsed["passed"],
        "margin": parsed["passed"] - suite["floor"],
        "registered_failures": registered,
        "unregistered_failures": unregistered,
        "errors": parsed["errors"],
        "exit_code": execution.get("exit_code"),
        "exit_code_agrees_with_verdict":
            (execution.get("exit_code") == 0) == (verdict == VERDICT_PASS),
    }


def validate_metered(root=None, service_dir=None, out_dir=None, timeout=900):
    """Run and evaluate every metered suite in the contract."""
    root = root or risk_lanes.repo_root()
    contract, err = load_contract(root)
    if contract is None:
        return {"verdict": VERDICT_INCOMPLETE, "why": "contract unreadable: %s" % err,
                "suites": []}

    service_dir = service_dir or os.path.join(root, "service")
    out_dir = out_dir or os.path.join(root, ".claude", ".validation")
    try:
        os.makedirs(out_dir, exist_ok=True)
    except Exception:
        pass

    results = []
    for pattern, suite in sorted(contract["suites"].items()):
        junit = os.path.join(out_dir, re.sub(r"\W+", "_", pattern) + ".xml")
        execution = run_suite(pattern, service_dir, junit, timeout=timeout)
        parsed, perr = (parse_junit(junit) if execution["junit_written"]
                        else (None, "no junit report written"))
        row = evaluate_suite(suite, execution, parsed, contract["exclusions"])
        row["execution"] = execution
        if perr:
            row["parse_error"] = perr
        results.append(row)

    worst = VERDICT_PASS
    rank = {VERDICT_PASS: 0, VERDICT_PRE_EXISTING: 1, VERDICT_FLOOR: 2,
            VERDICT_CAMPAIGN: 3, VERDICT_INCOMPLETE: 4}
    for row in results:
        if rank[row["verdict"]] > rank[worst]:
            worst = row["verdict"]

    return {
        "verdict": worst,
        "advanceable": worst in ADVANCEABLE,
        "suites": results,
        "contract": contract["path"],
        "authority_note": (
            "validation verdict only -- deployment authorization remains with "
            "deploy_authorization.py"
        ),
    }


def main(argv=None):
    import sys
    argv = list(sys.argv[1:] if argv is None else argv)
    timeout = int(argv[0]) if argv and argv[0].isdigit() else 900
    print(json.dumps(validate_metered(timeout=timeout), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
