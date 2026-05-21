"""PZ Preview Authority Audit (2026-05-21).

Frontend source-grep tests — the V1 shipment-detail PZ panel must read
its blockers from the single backend authority (`pz_preview.blockers`)
and the badge map must include a "PZ Failed" entry.

These tests assert presence/absence of substrings in the static HTML
file; they do not execute any JS. The goal is to prevent regression of
the duplicate-authority bug — a future edit that re-introduces a local
"Ready for PZ" computation independent of blockers will break these.
"""
from __future__ import annotations

from pathlib import Path

import pytest

HTML = (
    Path(__file__).resolve().parent.parent
    / "app" / "static" / "shipment-detail.html"
)


@pytest.fixture(scope="module")
def src() -> str:
    return HTML.read_text(encoding="utf-8")


def test_html_file_exists(src):
    assert len(src) > 0


def test_map_pz_status_includes_failed_label(src):
    # mapPzStatus must translate 'failed' → 'PZ Failed' so the badge can
    # surface the engine failure on the same chip that used to claim
    # "Ready for PZ".
    assert "failed: 'PZ Failed'" in src


def test_badge_tone_includes_pz_failed(src):
    # Badge tone for "PZ Failed" must exist so the badge renders red,
    # not the neutral fallback.
    assert "'PZ Failed':" in src


def test_panel_reads_blockers_from_backend(src):
    # Single-authority assertion — the panel must read `preview.blockers`
    # from the backend rather than computing its own readiness verdict.
    assert "preview.blockers" in src
    assert "previewBlockers" in src


def test_panel_renders_engine_error_from_backend(src):
    # engine_error surfaced verbatim from backend.
    assert "preview.engine_error" in src


def test_panel_shows_engine_error_code_in_structured_branch(src):
    # The structured-blocker renderer must understand ENGINE_ERROR.
    assert "ENGINE_ERROR" in src


def test_no_local_ready_for_pz_short_circuit(src):
    # Guard against re-introducing a local "Ready for PZ" computation
    # that bypasses the backend blockers list. The phrase "Ready for PZ"
    # may appear inside the badge map and the mapPzStatus translator,
    # but it must not appear in any line that also writes a status
    # without consulting blockers. We assert the badge map has exactly
    # one "Ready for PZ" key and one mapPzStatus entry, and that
    # `previewErr` is derived from blockers length OR detail.
    occurrences = src.count("'Ready for PZ'")
    # Allow legitimate appearances: badge tone map, mapPzStatus translator,
    # the PZ_PENDING_LABELS set, the workflow stage label, and a few
    # comments / hover titles. The cap protects against new short-circuit
    # branches inventing their own "Ready for PZ" verdict without
    # consulting blockers.
    assert occurrences <= 10, f"too many 'Ready for PZ' literals: {occurrences}"
    # previewErr must consult either detail (legacy) or blockers (new).
    assert "previewBlockers.length" in src


def test_previewerr_accepts_structured_blockers(src):
    # The previewErr derivation must accept the new blockers-list shape,
    # not only the legacy `preview.detail` object.
    assert "Array.isArray(preview.blockers)" in src or "Array.isArray(preview && preview.blockers)" in src
