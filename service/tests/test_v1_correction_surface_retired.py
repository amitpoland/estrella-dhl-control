"""
test_v1_correction_surface_retired.py — Phase B retirement guard.

After Phase B cutover, the V1 PZ Correction renderer (function
GlobalPZCorrectionProposalCard inside shipment-detail.html) MUST NOT
exist in the static surface. This test fires on every PR; if a future
PR re-introduces the V1 string via copy-paste from git history, the
test fails before merge.

Lesson F binding: V1 freeze + V2 authority isolation.
Sprint 01 §10 Phase B check B3.
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SHIPMENT_DETAIL = REPO_ROOT / "service" / "app" / "static" / "shipment-detail.html"
STATIC          = REPO_ROOT / "service" / "app" / "static"

FORBIDDEN_V1_STRINGS = [
    "GlobalPZCorrectionProposalCard",
    "global-pz-correction-card",
    "global-pz-correction-error",
    "global-pz-correction-recommended-badge",
    "global-pz-correction-lifecycle-state",
    "global-pz-correction-readonly-label",
    "global-pz-correction-lifecycle-disabled",
    "global-pz-correction-stats",
    "global-pz-correction-keep-notice",
    "global-pz-correction-terminal-banner",
    "global-pz-correction-staged-banner",
    "global-pz-correction-executing-banner",
    "global-pz-correction-failed-banner",
    "global-pz-correction-result",
    "global-pz-correction-options",
    "global-pz-correction-confirm-modal",
    "global-pz-correction-reason-input",
    "global-pz-correction-confirm-btn",
    "global-pz-correction-cancel-btn",
    "global-pz-correction-staged-actions",
    "global-pz-correction-commit-btn",
    "global-pz-correction-commit-panel",
    "global-pz-correction-commit-reason-input",
    "global-pz-correction-commit-confirm-btn",
    "global-pz-correction-commit-cancel-btn",
    "global-pz-correction-reset-stage-btn",
    "global-pz-correction-suppress-btn",
    "global-pz-correction-suppress-panel",
    "global-pz-correction-suppress-reason-input",
    "global-pz-correction-suppress-confirm-btn",
    "global-pz-correction-suppress-cancel-btn",
    "global-pz-correction-refresh",
]


@pytest.mark.parametrize("forbidden", FORBIDDEN_V1_STRINGS)
def test_v1_surface_string_absent_from_shipment_detail(forbidden):
    """The V1 renderer's identifiers must not appear in shipment-detail.html
    after Phase B. If you are seeing this fail, it means the V1 renderer
    has been re-introduced. Delete it and re-run."""
    if not SHIPMENT_DETAIL.exists():
        pytest.skip("shipment-detail.html not present in this checkout")
    body = SHIPMENT_DETAIL.read_text(encoding="utf-8")
    assert forbidden not in body, (
        f"Forbidden V1 PZ-correction string {forbidden!r} present in "
        f"shipment-detail.html. V1 is retired (Phase B). Use "
        f"pz-correction-v2.html via PzComponents.PZCorrectionV2Container."
    )


def test_v1_renderer_absent_across_static_surface():
    """Even outside shipment-detail.html, no static file may re-introduce
    the V1 function name."""
    offenders = []
    for path in STATIC.rglob("*"):
        if not path.is_file(): continue
        if path.suffix not in {".html", ".js"}: continue
        if "GlobalPZCorrectionProposalCard" in path.read_text(encoding="utf-8", errors="ignore"):
            offenders.append(str(path.relative_to(REPO_ROOT)))
    assert not offenders, (
        f"V1 PZ correction renderer name appears in: {offenders}. "
        "Phase B retired this function — delete the reference."
    )
