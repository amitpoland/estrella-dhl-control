"""
Campaign A1, Stage 1 — extraction equivalence.

Proves that ``operational_authority.compute_effective_pz_status`` (the new
canonical home) is byte-for-byte behaviourally identical to the live fork
``routes_wfirma._compute_effective_pz_status`` across every input class.

This is EXTRACTION-EQUIVALENCE testing (fork vs new), NOT a comparison against
``derive_pz_status`` — the effective-status authority and the display authority
are intentionally different (Path B has no display equivalent), so they are not
compared here.

Stage 1 is additive: no caller is repointed and the fork is not retired. This
test is the gate that authorises later repointing under a default-OFF flag. If
this test fails, the fork has drifted from the extracted copy — STOP and
reconcile before shipping.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

# service/ on path so `app` package imports resolve (mirrors existing tests).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from app.api import routes_wfirma as rw
from app.services import operational_authority as oa


# (id, audit, expected_tuple) — covers: success/partial fast-path, failed_checks,
# CN unresolved, Path A (MRN via cn_match and via cn_decision), Path B (pz_output),
# failed+pz_output edge, and the no-evidence / pdf-without-ts / unknown-status /
# empty-audit boundaries.
FIXTURES = [
    # ── fast-path: stored already in PZ_DONE ──
    ("success_fastpath",        {"status": "success"},                                   ("success", False)),
    ("partial_fastpath",        {"status": "partial"},                                   ("partial", False)),

    # ── hard block: real engine failure ──
    ("failed_checks_nonempty",  {"status": "failed", "failed_checks": ["before-duty PLN is zero"]},
                                                                                          ("failed", False)),

    # ── hard block: CN unresolved (cn_match False, cn_decision absent) ──
    ("cn_unresolved",           {"status": "failed", "failed_checks": [],
                                 "verification": {"cn_match": False}, "cn_decision": {}}, ("failed", False)),

    # ── Path A: MRN present (via cn_match, and via cn_decision.approved) ──
    ("pathA_mrn_cn_match",      {"status": "failed", "failed_checks": [],
                                 "verification": {"cn_match": True},
                                 "customs_declaration": {"mrn": "22PL445010E1234567"}},   ("partial", True)),
    ("pathA_mrn_cn_decision",   {"status": "failed", "failed_checks": [],
                                 "cn_decision": {"approved": True},
                                 "customs_declaration": {"mrn": "22PL445010E1234567"}},   ("partial", True)),

    # ── Path B: pz_output present, MRN empty (barcode/raster SAD) ──
    ("pathB_pzoutput_cn_match", {"status": "failed", "failed_checks": [],
                                 "verification": {"cn_match": True},
                                 "customs_declaration": {"mrn": ""},
                                 "pz_output": {"pdf": "batch_calc.pdf",
                                               "generated_at": "2026-06-01T10:00:00"}},   ("partial", True)),
    # ── failed + pz_output edge case (Path B via cn_decision.approved) ──
    ("failed_plus_pzoutput",    {"status": "failed", "failed_checks": [],
                                 "cn_decision": {"approved": True},
                                 "pz_output": {"pdf": "batch_calc.pdf",
                                               "generated_at": "2026-06-01T10:00:00"}},   ("partial", True)),

    # ── boundary: cn ok but neither MRN nor pz_output evidence → stays blocked ──
    ("no_evidence_cn_ok",       {"status": "failed", "failed_checks": [],
                                 "verification": {"cn_match": True},
                                 "customs_declaration": {"mrn": ""}, "pz_output": {}},    ("failed", False)),

    # ── boundary: Path B needs BOTH pdf AND generated_at (pdf only → blocked) ──
    ("pathB_pdf_without_ts",    {"status": "failed", "failed_checks": [],
                                 "verification": {"cn_match": True},
                                 "pz_output": {"pdf": "batch_calc.pdf"}},                 ("failed", False)),

    # ── boundary: non-standard stored status, Path A applies ──
    ("unknown_status_pathA",    {"status": "unknown", "failed_checks": [],
                                 "verification": {"cn_match": True},
                                 "customs_declaration": {"mrn": "X"}},                    ("partial", True)),

    # ── boundary: empty audit ──
    ("empty_audit",             {},                                                       ("", False)),
]

_IDS = [f[0] for f in FIXTURES]


@pytest.mark.parametrize("audit,expected", [(f[1], f[2]) for f in FIXTURES], ids=_IDS)
def test_new_function_returns_expected_tuple(audit, expected):
    """The extracted function returns the identical (effective_status, normalized) tuple."""
    assert oa.compute_effective_pz_status(copy.deepcopy(audit)) == expected


@pytest.mark.parametrize("audit,expected", [(f[1], f[2]) for f in FIXTURES], ids=_IDS)
def test_fork_and_new_are_equivalent(audit, expected):
    """The live fork and the new canonical function produce byte-for-byte identical output."""
    fork_result = rw._compute_effective_pz_status(copy.deepcopy(audit))
    new_result = oa.compute_effective_pz_status(copy.deepcopy(audit))
    assert new_result == fork_result == expected


def test_new_function_never_mutates_audit():
    """Pure read — the audit payload is not mutated (matches the fork's contract)."""
    a = {"status": "failed", "failed_checks": [],
         "verification": {"cn_match": True},
         "customs_declaration": {"mrn": "22PL445010E1234567"}}
    before = copy.deepcopy(a)
    oa.compute_effective_pz_status(a)
    assert a == before


def test_shared_done_set_has_no_drift_source():
    """Both implementations resolve PZ_DONE from the same operational_authority set."""
    assert oa.PZ_DONE == rw._PZ_DONE == {"success", "partial"}
