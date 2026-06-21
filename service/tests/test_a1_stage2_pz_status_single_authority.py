"""
test_a1_stage2_pz_status_single_authority.py — Campaign A1 Stage 2.

The effective-PZ-status logic must live in exactly ONE place:
``operational_authority.compute_effective_pz_status``. Stage 2 collapses the
former duplicate fork ``routes_wfirma._compute_effective_pz_status`` into a thin
DELEGATING SHIM, and repoints the two service importers
(``audit_evidence`` / ``audit_persist``) at the canonical leaf instead of the
routes module.

Structural guard only (source-grep). Functional byte-parity is covered by
``test_compute_effective_pz_status_extraction_parity.py`` (fork == leaf across 12
input classes) — after this collapse the fork literally calls the leaf, so that
parity is preserved trivially.
"""
from __future__ import annotations

from pathlib import Path

_APP = Path(__file__).resolve().parents[1] / "app"
_RW  = _APP / "api" / "routes_wfirma.py"
_OA  = _APP / "services" / "operational_authority.py"
_AE  = _APP / "services" / "audit_evidence.py"
_AP  = _APP / "services" / "audit_persist.py"


def _fork_body() -> str:
    src = _RW.read_text(encoding="utf-8")
    i = src.index("def _compute_effective_pz_status(")
    j = src.index("\ndef ", i + 1)   # next top-level def
    return src[i:j]


def test_canonical_defines_the_authority():
    oa = _OA.read_text(encoding="utf-8")
    assert "def compute_effective_pz_status(" in oa, (
        "the single effective-PZ-status authority must live in operational_authority"
    )


def test_fork_is_a_delegating_shim_not_a_duplicate():
    body = _fork_body()
    assert "_oa_compute_effective_pz_status(audit)" in body, (
        "the fork must DELEGATE to operational_authority.compute_effective_pz_status"
    )
    # the duplicate Path A / Path B logic must be gone — no inline re-implementation
    for token in ("customs_declaration", "pz_output", "cn_decision", "failed_checks", "cn_match"):
        assert token not in body, (
            f"fork must not re-implement the {token!r} branch — it is collapsed into the leaf"
        )
    assert body.count("return ") == 1, "a delegating shim has exactly one return path"


def test_importers_use_the_leaf_not_routes():
    for p in (_AE, _AP):
        src = p.read_text(encoding="utf-8")
        assert "from ..api.routes_wfirma import _compute_effective_pz_status" not in src, (
            f"{p.name} must not import the effective-PZ-status fork from routes_wfirma"
        )
        assert "from .operational_authority import" in src and "compute_effective_pz_status" in src, (
            f"{p.name} must import compute_effective_pz_status from the operational_authority leaf"
        )


def test_pz_done_set_is_shared_from_leaf():
    rw = _RW.read_text(encoding="utf-8")
    assert "from ..services.operational_authority import" in rw and "PZ_DONE as _PZ_DONE" in rw, (
        "routes_wfirma must source PZ_DONE from operational_authority (one 'what counts as done')"
    )
