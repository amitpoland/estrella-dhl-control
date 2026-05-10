"""
test_dashboard_derive_status_promotion.py — unit tests for _derive_status()
and _derive_action_reason() in routes_dashboard.py.

Covers the regression case where a batch stores status="failed" but has no
real failures (failed_checks=[]) and PZ output files already exist — the
engine crashed post-generation in a naming step.  The fix must promote such
a batch to "partial" (VERIFY-GAP present) rather than surfacing "failed".

Tests:
  1. failed + empty failed_checks + pz files + VERIFY-GAP → "partial"
  2. failed + empty failed_checks + pz files + no gaps + verification → "success"
  3. failed + empty failed_checks + pz files + hard verification fail → "blocked"
  4. failed + empty failed_checks + pz files + no verification at all → "partial"
  5. failed + non-empty failed_checks → stays "failed" (real failure)
  6. failed + pz files absent → stays "failed"
  7. success / partial / blocked → passed through unchanged
  8. _derive_action_reason: engine_error truncated to 120 chars
  9. _derive_action_reason: failed_checks[0] returned first
 10. _derive_action_reason: verification hard-fail returned when no other reason
 11. _derive_action_reason: empty string when batch is clean
"""
from __future__ import annotations

import sys
from pathlib import Path

_SVC = Path(__file__).parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

import os
os.environ.setdefault("API_KEY", "test-key")

from app.api.routes_dashboard import _derive_status, _derive_action_reason  # noqa: E402


# ── Helpers ───────────────────────────────────────────────────────────────────

def _audit(
    status="failed",
    failed_checks=None,
    pz_generated_at=None,
    pdf_sha256=None,
    corrections_log=None,
    verification=None,
    engine_error=None,
):
    a = {"status": status}
    if failed_checks is not None:
        a["failed_checks"] = failed_checks
    if engine_error is not None:
        a["engine_error"] = engine_error
    if pz_generated_at or pdf_sha256:
        a["pz_output"] = {"generated_at": pz_generated_at} if pz_generated_at else {}
        if pdf_sha256:
            a["files"] = {"pdf": {"sha256": pdf_sha256}}
    if corrections_log is not None:
        a["corrections_log"] = corrections_log
    if verification is not None:
        a["verification"] = verification
    return a


# ── Tests: _derive_status ─────────────────────────────────────────────────────

class TestDeriveStatusPromotion:
    def test_failed_with_verify_gaps_and_pz_files_becomes_partial(self):
        a = _audit(
            failed_checks=[],
            pz_generated_at="2026-05-08T11:49:28Z",
            corrections_log=["[VERIFY-GAP] SAD CIF not available"],
            verification={"importer": True},
        )
        assert _derive_status(a) == "partial"

    def test_failed_with_clean_verification_and_pz_files_becomes_success(self):
        a = _audit(
            failed_checks=[],
            pdf_sha256="abc123",
            corrections_log=[],
            verification={"importer": True, "total_value": True},
        )
        assert _derive_status(a) == "success"

    def test_failed_with_hard_verification_fail_and_pz_files_becomes_blocked(self):
        a = _audit(
            failed_checks=[],
            pdf_sha256="abc123",
            verification={"importer": False},
        )
        assert _derive_status(a) == "blocked"

    def test_failed_with_no_verification_and_pz_files_becomes_partial(self):
        a = _audit(
            failed_checks=[],
            pz_generated_at="2026-05-08T11:49:28Z",
        )
        assert _derive_status(a) == "partial"

    def test_failed_with_real_failed_checks_stays_failed(self):
        a = _audit(
            failed_checks=["importer_mismatch"],
            pdf_sha256="abc123",
        )
        assert _derive_status(a) == "failed"

    def test_failed_without_pz_files_stays_failed(self):
        a = _audit(failed_checks=[], corrections_log=["[VERIFY-GAP] gap"])
        assert _derive_status(a) == "failed"

    def test_success_passes_through(self):
        assert _derive_status({"status": "success"}) == "success"

    def test_partial_passes_through(self):
        assert _derive_status({"status": "partial"}) == "partial"

    def test_blocked_passes_through(self):
        assert _derive_status({"status": "blocked"}) == "blocked"


# ── Tests: _derive_action_reason ──────────────────────────────────────────────

class TestDeriveActionReason:
    def test_engine_error_truncated(self):
        long_error = "x" * 200
        reason = _derive_action_reason({"engine_error": long_error})
        assert len(reason) == 120
        assert reason == "x" * 120

    def test_failed_checks_takes_priority_over_engine_error(self):
        a = {"failed_checks": ["importer_mismatch"], "engine_error": "something else"}
        assert _derive_action_reason(a) == "importer_mismatch"

    def test_verification_hard_fail_returned(self):
        a = {"verification": {"importer": False, "total_value": True}}
        reason = _derive_action_reason(a)
        assert "importer" in reason

    def test_empty_string_for_clean_batch(self):
        a = {"failed_checks": [], "verification": {"importer": True}}
        assert _derive_action_reason(a) == ""

    def test_short_engine_error_returned_as_is(self):
        a = {"engine_error": "'NoneType' object has no attribute 'name'"}
        reason = _derive_action_reason(a)
        assert reason == "'NoneType' object has no attribute 'name'"
