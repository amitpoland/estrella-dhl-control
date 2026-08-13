"""B-012: ProformaDraftLineRow Save button must name the write destination.

Frontend standard §5.3 — write buttons label what they write ("Save to draft",
not bare "Save"). Production authority surface is V1 shipment-detail.html;
dashboard.html carries the same ProformaDraftLineRow mirror.

Run: python -m pytest tests/test_b012_save_to_draft_label.py -q
"""
from __future__ import annotations

from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"


def _assert_line_save_label(html: str, path: Path) -> None:
    needle = "data-testid={`btn-line-save-${line.line_id}`}"
    idx = html.find(needle)
    assert idx > 0, f"{path.name}: missing btn-line-save testid"
    # Label is immediately after the opening tag that carries the testid.
    window = html[idx : idx + 120]
    assert ">Save to draft</Btn>" in window, (
        f"{path.name}: btn-line-save must read 'Save to draft', got window={window!r}"
    )
    assert ">Save</Btn>" not in window


def test_b012_shipment_detail_line_save_says_save_to_draft():
    path = STATIC / "shipment-detail.html"
    _assert_line_save_label(path.read_text(encoding="utf-8"), path)


def test_b012_dashboard_line_save_says_save_to_draft():
    path = STATIC / "dashboard.html"
    _assert_line_save_label(path.read_text(encoding="utf-8"), path)
