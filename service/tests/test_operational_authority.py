"""
test_operational_authority.py — ATLAS P1 single-authority contract (PZ status).

Pins:
  1. derive_pz_status emits the canonical 4-value set with the documented precedence.
  2. is_pz_done == (derive_pz_status == 'complete').
  3. routes_dashboard._derive_pz_status IS the canonical function (no second backend
     derivation survives — the P1 WRONG-AUTHORITY fix).
  4. routes_wfirma._PZ_DONE IS the shared operational_authority.PZ_DONE set.

These guard the consolidation: changing WHERE truth is derived, never the truth.
"""
import pytest

from app.services import operational_authority as oa


# ── 1. canonical value set + precedence ──────────────────────────────────────
def test_complete_via_wfirma_pz_doc_id():
    # Layer 0: wFirma PZ doc id is ground truth, overrides a stale engine_error.
    a = {"wfirma_export": {"wfirma_pz_doc_id": "PZ/1"}, "status": "failed",
         "engine_error": "boom"}
    assert oa.derive_pz_status(a) == "complete"


def test_failed_via_status_or_engine_error():
    assert oa.derive_pz_status({"status": "failed"}) == "failed"
    assert oa.derive_pz_status({"engine_error": "parse error"}) == "failed"


def test_complete_via_engine_success_partial():
    assert oa.derive_pz_status({"status": "success"}) == "complete"
    assert oa.derive_pz_status({"status": "partial"}) == "complete"


def test_locked_when_sad_missing():
    # no wfirma doc, not failed, status not done, no SAD anywhere -> locked
    a = {"status": "ready", "inputs": {}, "files_detail": {}, "batch_id": ""}
    assert oa.derive_pz_status(a) == "locked"


def test_ready_default_when_sad_present_not_done():
    a = {"status": "ready",
         "inputs": {"zc429": "sad.pdf"},
         "customs_declaration": {"mrn": "26PL..."}}
    # SAD present (uploaded_parsed), not done, not failed -> ready
    assert oa.derive_pz_status(a) == "ready"


# ── 2. is_pz_done predicate parity ───────────────────────────────────────────
@pytest.mark.parametrize("audit", [
    {"wfirma_export": {"wfirma_pz_doc_id": "PZ/1"}},
    {"status": "success"},
    {"status": "failed"},
    {"status": "ready", "inputs": {}},
])
def test_is_pz_done_matches_complete(audit):
    assert oa.is_pz_done(audit) == (oa.derive_pz_status(audit) == "complete")


# ── 3. dashboard consumes the canonical function (no second derivation) ──────
def test_dashboard_uses_canonical_pz_status():
    import app.api.routes_dashboard as rd
    assert rd._derive_pz_status is oa.derive_pz_status
    assert rd._derive_status is oa.derive_status
    assert rd._derive_sad_status is oa.derive_sad_status


# ── 4. wFirma guard shares the PZ_DONE vocabulary ───────────────────────────
def test_wfirma_pz_done_is_shared():
    import app.api.routes_wfirma as rw
    assert rw._PZ_DONE is oa.PZ_DONE
    assert oa.PZ_DONE == {"success", "partial"}
