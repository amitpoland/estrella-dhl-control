#!/usr/bin/env python3
"""a1_mutation_check.py — Campaign-2 A1.1 · internal mutation testing.

mutmut / cosmic-ray are not installed (and installing into the shared
interpreter is undesirable), so this is the council-permitted internal mutation
script. It:

  1. exports the committed tree (HEAD) to an isolated temp dir via `git archive`;
  2. for each semantic mutation of document_comparator.py, writes the mutant into
     the isolated tree and runs the REAL comparator test suite
     (tests/test_document_comparator.py) against it;
  3. a mutant is KILLED if the suite fails, SURVIVED if it passes.

All mutations must be KILLED — that proves the tests actually protect the
comparator's behaviour. Never mutates the real working tree.

Usage: python scripts/a1_mutation_check.py
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
REL_MODULE = "service/app/services/document_comparator.py"
TEST_TARGET = "tests/test_document_comparator.py"

# Each mutation flips one behaviour. (id, description, find, replace).
# `find` must occur exactly once in the module or the mutation is reported ERROR.
MUTATIONS = [
    ("M1_tolerance_widened", "0.02 tolerance -> huge (total check never fires)",
     'if total_diff > _D("0.02"):', 'if total_diff > _D("999999"):'),
    ("M2_tolerance_inverted", "total comparison > -> <",
     'if total_diff > _D("0.02"):', 'if total_diff < _D("0.02"):'),
    ("M3_contractor_inverted", "contractor != -> ==",
     'if v_contractor_id != plan.contractor_id:', 'if v_contractor_id == plan.contractor_id:'),
    ("M4_type_inverted", "type not in -> in",
     'if v_type not in ("normal", "vat"):', 'if v_type in ("normal", "vat"):'),
    ("M5_linecount_inverted", "line count != -> ==",
     'if actual_line_count != expected_line_count:', 'if actual_line_count == expected_line_count:'),
    ("M6_currency_inverted", "currency != -> ==",
     'if v_currency and v_currency != plan.currency:', 'if v_currency and v_currency == plan.currency:'),
    ("M7_receiver_disabled", "receiver check disabled",
     'if plan.contractor_receiver_id:', 'if False and plan.contractor_receiver_id:'),
    ("M8_line_name_inverted", "per-line name != -> ==",
     'if _a_name != expected_line.name:', 'if _a_name == expected_line.name:'),
    ("M9_line_price_inverted", "per-line price != -> ==",
     'if _a_price != expected_line.price:', 'if _a_price == expected_line.price:'),
    ("M10_blocking_never", "first_blocking_gap never returns a gap",
     'if g.blocking:\n                return g', 'if False:\n                return g'),
    ("M11_message_altered", "contractor message text changed",
     'contractor mismatch — ', 'contractor differs — '),
]


def _run_suite(tree: Path) -> bool:
    """Return True if the suite PASSES (mutant survived)."""
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", TEST_TARGET, "-q", "--no-header", "-p", "no:cacheprovider"],
        cwd=str(tree / "service"),
        env={"PYTHONUTF8": "1", "PATH": _env_path(), "SYSTEMROOT": _sysroot()},
        capture_output=True, text=True,
    )
    return proc.returncode == 0


def _env_path() -> str:
    import os
    return os.environ.get("PATH", "")


def _sysroot() -> str:
    import os
    return os.environ.get("SYSTEMROOT", r"C:\Windows")


def main() -> int:
    base = Path(tempfile.mkdtemp(prefix="a1mut_"))
    # export committed HEAD (contains comparator + test) into isolated tree
    archive = subprocess.run(["git", "archive", "HEAD"], cwd=str(REPO),
                             capture_output=True)
    if archive.returncode != 0:
        print("git archive failed:", archive.stderr.decode(errors="replace"))
        return 2
    import tarfile, io
    with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as tf:
        tf.extractall(base)

    module_path = base / REL_MODULE
    pristine = module_path.read_text(encoding="utf-8")

    # sanity: unmutated suite must PASS
    print("=== baseline (unmutated) ===")
    t0 = time.time()
    baseline_pass = _run_suite(base)
    print(f"baseline suite pass={baseline_pass} ({time.time()-t0:.1f}s)")
    if not baseline_pass:
        print("ABORT: baseline suite does not pass in isolated tree")
        return 3

    killed, survived, errored = [], [], []
    for mid, desc, find, repl in MUTATIONS:
        n = pristine.count(find)
        if n != 1:
            errored.append((mid, f"find-count={n} (expected 1)"))
            print(f"[ERROR ] {mid}: pattern occurs {n}x")
            continue
        module_path.write_text(pristine.replace(find, repl), encoding="utf-8")
        t0 = time.time()
        survived_flag = _run_suite(base)
        module_path.write_text(pristine, encoding="utf-8")  # restore
        dt = time.time() - t0
        if survived_flag:
            survived.append((mid, desc))
            print(f"[SURVIVED] {mid}: {desc} ({dt:.1f}s)  <-- TESTS DID NOT CATCH")
        else:
            killed.append((mid, desc))
            print(f"[KILLED ] {mid}: {desc} ({dt:.1f}s)")

    total = len(MUTATIONS)
    print("\n=== MUTATION SUMMARY ===")
    print(f"killed:   {len(killed)}/{total}")
    print(f"survived: {len(survived)}/{total}")
    print(f"errored:  {len(errored)}/{total}")
    score = (len(killed) / total * 100) if total else 0.0
    print(f"mutation score: {score:.1f}%")
    for mid, why in errored:
        print(f"  ERROR {mid}: {why}")
    for mid, desc in survived:
        print(f"  SURVIVED {mid}: {desc}")
    # non-zero exit if any mutant survived or errored
    return 0 if (not survived and not errored) else 1


if __name__ == "__main__":
    raise SystemExit(main())
