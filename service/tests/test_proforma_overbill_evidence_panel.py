"""
test_proforma_overbill_evidence_panel.py — display-only V2 panel for the
duplicate / over-bill product_code billing guard (#686).

#686 (backend) made `_derive_draft_readiness` return a structured
`duplicate_product_codes` list — every purchase lot (product_code) billed across
>1 draft line, with billed vs available packing quantity and an `over_billed`
flag. Over-billed lots are ALSO raised as hard blockers; legitimate mixed lots
(billed <= available) are surfaced for transparency only.

#686 shipped backend-only. This adds the V2 `proforma-detail.jsx` panel that
renders that evidence (display-only, no write actions). These tests:
  A. pin #686's pure classifier `_analyze_product_code_billing` contract that the
     panel renders (so a rename/shape change is caught by the UI's own suite);
  B. pin the gate-integration shape via the real readiness gate (packing mocked);
  C. pin the UI wiring and that the panel stays DISPLAY-ONLY.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from app.api.routes_proforma import _analyze_product_code_billing


def _ln(pc, design="D", qty=1, line_id=None):
    d = {"product_code": pc, "design_no": design, "qty": qty}
    if line_id is not None:
        d["line_id"] = line_id
    return d


# ── A. #686 classifier contract (the data the panel renders) ─────────────────

def test_mixed_lot_within_available_is_surfaced_not_over_billed():
    # 299-2 billed on 2 lines (10 pieces total) but 10 available → legitimate.
    rows = _analyze_product_code_billing(
        [_ln("299-2", "JR04929", 6), _ln("299-2", "J3806R00973", 4)],
        available_by_pc={"299-2": 10},
        invoice_by_pc={"299-2": "INV/1"})
    assert len(rows) == 1
    r = rows[0]
    assert r["product_code"] == "299-2"
    assert r["over_billed"] is False
    assert r["billed_qty"] == 10
    assert r["available_qty"] == 10
    assert r["line_count"] == 2
    assert r["invoice_no"] == "INV/1"
    assert set(r["design_nos"]) == {"JR04929", "J3806R00973"}


def test_over_bill_flagged():
    rows = _analyze_product_code_billing(
        [_ln("299-9", "JR04929", 3), _ln("299-9", "JR04929", 3)],
        available_by_pc={"299-9": 4})
    assert rows[0]["over_billed"] is True
    assert rows[0]["billed_qty"] == 6
    assert rows[0]["available_qty"] == 4


def test_single_line_within_available_is_not_surfaced():
    # One line, within available — not a multi-line lot, not over-billed → omitted.
    rows = _analyze_product_code_billing(
        [_ln("RNG-1", "D1", 1)], available_by_pc={"RNG-1": 5})
    assert rows == []


def test_single_line_over_available_is_surfaced():
    rows = _analyze_product_code_billing(
        [_ln("RNG-1", "D1", 9)], available_by_pc={"RNG-1": 5})
    assert len(rows) == 1 and rows[0]["over_billed"] is True


def test_over_billed_sorted_first():
    rows = _analyze_product_code_billing(
        [_ln("AAA", "D", 1), _ln("AAA", "D", 1),      # mixed, available 5 → ok
         _ln("ZZZ", "D", 9)],                          # over (avail 1)
        available_by_pc={"AAA": 5, "ZZZ": 1})
    assert rows[0]["product_code"] == "ZZZ" and rows[0]["over_billed"] is True


def test_blank_product_code_skipped():
    rows = _analyze_product_code_billing(
        [_ln("", "D", 1), _ln(None, "D", 1)], available_by_pc={})
    assert rows == []


# ── B. Real readiness gate returns the field (packing mocked, leak-free) ──────

def _draft(lines):
    from app.services import proforma_invoice_link_db as pildb
    return pildb.ProformaDraft(
        id=1, batch_id="B", client_name="C", status="pending_local",
        editable_lines_json=json.dumps(lines))


def _run_gate(lines, packing_rows, intent="approve"):
    from app.api import routes_proforma as rp
    from app.services.product_authority_resolver import resolve_batch_product_authority
    with patch.object(rp, "_build_preview", lambda *a, **k: {}), \
         patch.object(rp, "_preflight_approve", lambda *a, **k: None), \
         patch.object(rp, "_resolve_customer", lambda *a, **k: {}), \
         patch.object(rp.wfdb, "get_product",
                      lambda *a, **k: {"wfirma_product_id": "1"}), \
         patch("app.services.design_product_bridge.populate_from_packing",
               lambda *a, **k: {}), \
         patch("app.services.packing_db.get_packing_lines_for_batch",
               lambda *a, **k: packing_rows), \
         patch("app.services.cpa_product_service.authority_snapshot",
               lambda bid, **k: resolve_batch_product_authority(bid, packing_rows=packing_rows)):
        return rp._derive_draft_readiness(_draft(lines), intent=intent)


@pytest.mark.parametrize("intent", ["approve", "post", "convert"])
def test_gate_surfaces_mixed_lot_without_blocking(intent):
    res = _run_gate(
        [_ln("299-2", "JR04929", 6, 1), _ln("299-2", "J3806R00973", 4, 2)],
        [{"product_code": "299-2", "quantity": 10, "invoice_no": "INV/1"}],
        intent=intent)
    dp = {d["product_code"]: d for d in res["duplicate_product_codes"]}
    assert "299-2" in dp
    assert dp["299-2"]["over_billed"] is False
    # A legitimate mixed lot must NOT add an over-bill blocker — for ANY intent.
    assert not any("over-billed" in r for r in res["blocking_reasons"])


@pytest.mark.parametrize("intent", ["approve", "post", "convert"])
def test_gate_blocks_over_bill(intent):
    # The guard lives in the ONE gate shared by approve/post/convert — an
    # over-bill must block all three, with the structured evidence surfaced.
    res = _run_gate(
        [_ln("299-9", "JR04929", 3, 1), _ln("299-9", "JR04929", 3, 2)],
        [{"product_code": "299-9", "quantity": 4, "invoice_no": "INV/9"}],
        intent=intent)
    dp = {d["product_code"]: d for d in res["duplicate_product_codes"]}
    assert dp["299-9"]["over_billed"] is True
    assert res["ready"] is False
    assert any("over-billed" in r and "299-9" in r
               for r in res["blocking_reasons"])


# ── C. UI wiring pins (display-only) ─────────────────────────────────────────

_JSX = (Path(__file__).resolve().parents[1] / "app" / "static" / "v2"
        / "proforma-detail.jsx")


def test_panel_renders_the_backend_field():
    src = _JSX.read_text(encoding="utf-8")
    assert "overbill-evidence-panel" in src
    assert "duplicate_product_codes" in src          # reads the backend field
    assert "overbill-row-" in src
    assert "over_billed" in src                       # uses the over-bill flag
    assert "billed_qty" in src and "available_qty" in src


def test_panel_is_display_only():
    """The panel must reflect the backend gate, never offer a write that could
    bypass the over-bill block (no manual 'allow' override — that was the wrong
    model #686 replaced)."""
    src = _JSX.read_text(encoding="utf-8")
    # No remnant of the rejected manual-override model anywhere in the file.
    assert "setDraftSplitAuthority" not in src        # no override transport
    assert "/split-authority" not in src
    assert "btn-allow-split-" not in src              # no grant control
    assert "btn-revoke-split-" not in src             # no revoke control
    # The panel block itself must be INERT — no handlers, transport, inputs, or
    # local state. Scoped to the panel region (up to the next sibling section).
    start = src.index("overbill-evidence-panel")
    end = src.index("Party cards", start)
    panel = src[start:end]
    for forbidden in ("onClick", "PzApi", "fetch(", "<button", "<input", "useState"):
        assert forbidden not in panel, \
            f"display-only panel must not contain {forbidden!r}"
