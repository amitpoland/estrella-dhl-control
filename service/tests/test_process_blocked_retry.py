"""Allow safe retry from `blocked` status (2026-05-21).

The `/process` endpoint historically rejected retry when the prior run
left the batch in `blocked` state, even when the engine code or inputs
had been updated. The engine re-evaluates `failed_checks` on every run
and writes `status=blocked` again if the mismatch persists, so allowing
retry from blocked is idempotent — no silent override of any financial
gate. The SAD agency hard-reject (agency_sad_decision.safe_to_run_pz)
remains in force.

These tests pin the allow-list and the SAD hard-reject precedence.
"""
from __future__ import annotations

import inspect
from pathlib import Path

# Source-grep tests on the route handler — avoid spinning up the full
# FastAPI app + DB fixtures for a one-line allow-list change.

ROUTES = (
    Path(__file__).resolve().parent.parent
    / "app" / "api" / "routes_upload.py"
)


def _process_block():
    """Return the source slice covering process_shipment status checks."""
    body = ROUTES.read_text(encoding="utf-8")
    marker = '@router.post("/shipment/{batch_id}/process"'
    start = body.find(marker)
    assert start != -1, "process_shipment route not found in routes_upload.py"
    end = body.find("@router.post", start + len(marker))
    if end == -1:
        end = start + 4000
    return body[start:end]


def test_allow_list_includes_blocked():
    src = _process_block()
    # The 6-element allow-list must contain 'blocked'.
    assert "'blocked'" in src or '"blocked"' in src, "blocked missing from allow-list"


def test_allow_list_keeps_legacy_statuses():
    src = _process_block()
    for legacy in ("ready", "partial", "success", "failed", "processing"):
        assert f"'{legacy}'" in src or f'"{legacy}"' in src, (
            f"legacy status {legacy!r} missing from allow-list — regression"
        )


def test_error_message_documents_blocked_state():
    src = _process_block()
    # The 409 error detail must mention `blocked` so the operator sees
    # the new accepted state when an exotic status is rejected.
    detail_chunk = src[src.find("Shipment must be in"):]
    assert detail_chunk, "error detail string not found"
    head = detail_chunk[:300]
    assert "'blocked'" in head or '"blocked"' in head


def test_sad_hard_reject_still_present():
    """SAD agency_sad_decision.safe_to_run_pz=False MUST still hard-reject
    independently of the status allow-list. This is the only safety net
    that prevents a SAD-blocked batch from being silently re-run."""
    src = _process_block()
    assert "safe_to_run_pz" in src
    assert "sad_validation_blocked" in src


def test_no_effective_unblocked_short_circuit():
    """The old `effectively_unblocked` short-circuit is removed because
    `blocked` is now first-class in the allow-list. The helper
    `_compute_effective_blocked` is still imported (used post-pipeline
    for status reconciliation) but must not gate /process entry."""
    src = _process_block()
    # The variable should not appear at the entry-check location.
    # We allow `_compute_effective_blocked` to be present elsewhere via
    # other imports/uses, so we scope the assertion to the early lines.
    head = src[: src.find("Hard guard")]
    assert "effectively_unblocked" not in head, (
        "stale effectively_unblocked short-circuit still present at /process entry"
    )


def test_compute_effective_blocked_still_imported_for_other_uses():
    """Status reconciliation after the pipeline runs uses
    `_compute_effective_blocked` to demote 'blocked' to 'partial' when
    the only remaining failures are operator-overridable non-financial
    checks. That helper must remain imported."""
    body = ROUTES.read_text(encoding="utf-8")
    assert "_compute_effective_blocked" in body
