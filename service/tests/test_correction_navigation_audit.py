"""
test_correction_navigation_audit.py — M1 audit codified as a test.

Phase B cannot delete V1 cleanly if any entry point still points at it.
Lesson F violation if even one deep link survives the cutover. This test
runs on every PR after Phase B merges.

Asserts:
  1. Every correction-endpoint string reference inside service/app/static/
     lives in one of the V2 owner files (pz-correction-v2.html, pz-api.js,
     pz-state.js, pz-components.js). Any reference elsewhere (e.g. inline
     fetch() in shipment-detail.html) is a navigation-audit violation.
  2. pz-correction-v2.html exists and is reachable — at minimum, one
     navigation target points at it in the static surface.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
STATIC    = REPO_ROOT / "service" / "app" / "static"
TEMPLATES = REPO_ROOT / "service" / "app" / "templates"

V2_OWNER_FILES = {
    "pz-correction-v2.html",
    "pz-api.js",
    "pz-state.js",
    "pz-components.js",
}

CORRECTION_ENDPOINT_PATTERNS = [
    "correction-proposal",
    "correction-state",
    "correction-stage",
    "correction-commit",
    "correction-suppress",
    "correction-execute",
    "correction-push-wfirma",
]


def _scan_html_js(root: Path):
    if not root.exists():
        return []
    out = []
    for path in root.rglob("*"):
        if not path.is_file(): continue
        if path.suffix not in {".html", ".js", ".jsx", ".tsx", ".ts"}: continue
        out.append(path)
    return out


def test_v2_html_file_exists():
    assert (STATIC / "pz-correction-v2.html").exists(), \
        "Phase A artifact missing: service/app/static/pz-correction-v2.html"


def test_v2_html_is_reachable_from_static_surface():
    """At least one static file references pz-correction-v2.html as a
    navigation target. Without this, Phase B's deletion of the V1 mount
    leaves V2 unreachable."""
    found = False
    for path in _scan_html_js(STATIC) + _scan_html_js(TEMPLATES):
        if path.name == "pz-correction-v2.html":
            continue  # self-reference doesn't count
        if "pz-correction-v2.html" in path.read_text(encoding="utf-8", errors="ignore"):
            found = True
            break
    assert found, (
        "pz-correction-v2.html is not referenced from any navigation target. "
        "Add a link from shipment-detail.html (or another page) so operators "
        "can reach the V2 surface after Phase B cutover."
    )


@pytest.mark.parametrize("pattern", CORRECTION_ENDPOINT_PATTERNS)
def test_correction_endpoint_only_referenced_in_v2_owner_files(pattern):
    """A correction-endpoint string must only appear in the V2 owners.
    Inline fetch() to /correction-* from any other static file is a
    Phase B navigation-audit violation."""
    offenders = []
    for path in _scan_html_js(STATIC):
        if path.name in V2_OWNER_FILES:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        # Skip comments-only matches — we still care if it's in executable code.
        if pattern in text:
            # Allow proforma-v2.html since it does NOT touch correction endpoints,
            # but if a future PR adds them there it's a layer violation.
            offenders.append(str(path.relative_to(REPO_ROOT)))
    assert not offenders, (
        f"Correction endpoint pattern {pattern!r} appears in non-V2-owner files: "
        f"{offenders}. Move the reference into pz-api.js / pz-components.js or remove it."
    )
