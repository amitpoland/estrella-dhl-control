"""B-014: V2 proforma list surfaces draft birth-blocks (V1 parity).

Prod default remains V1 shipment-detail.html until operator cutover approval
(see .claude/memory/b014-cutover-checkpoint.md). This pin only asserts the
non-destructive V2 parity surface exists and calls the same API contract.
"""
from __future__ import annotations

from pathlib import Path

SRC = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "static"
    / "v2"
    / "proforma-list.jsx"
)


def test_b014_v2_list_fetches_creation_and_advisory_blocks():
    text = SRC.read_text(encoding="utf-8")
    assert "include_advisory=false" in text
    assert "contractor-projection/blocks/" in text
    assert 'data-testid="proforma-blocked-records-panel"' in text
    assert 'data-testid="proforma-advisory-blocks-panel"' in text
    assert "contractor-projection/assign/" in text
    assert "V2DraftBirthBlocksPanel" in text
