"""
test_stock_promotion_be2b.py — BE-2b: receipt-path promotions produce Notes.

Operator rule (PROJECT_STATE DECISIONS "BE-2b", 2026-07-03, verbatim GO):
"Every stock movement must produce a document." The receipt path
(dhl_delivery_bridge.execute_goods_received — operator confirms physical
receipt after DHL shows delivered) was the LAST PURCHASE_TRANSIT →
WAREHOUSE_STOCK writer outside the shared authority. It now delegates to
run_stock_promotion(), gaining the idempotent skip, mirrors, and the Stock
Promotion Note.

Pins:
  - receipt produces a Note (trigger=warehouse_receive, goods_received
    reason preserved, operator recorded)
  - ordering: receipt-first-then-PZ and PZ-first-then-receipt each yield
    exactly ONE Note total (no doubles, no 409s)
  - return contract preserved (transitioned/errors; note_no additive)
  - ValueError validation contract unchanged
  - source pins: no direct engine transition remains in the bridge; the
    PT→WS writer set is exactly {stock_promotion.py}
  - boundary: sample/producer RETURNS to stock stay direct by design (they
    are not Temp Warehouse→Final Stock promotions — no Note)

Real DBs throughout (Lesson A) — same fixture family as the BE-1/BE-2 suites.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.services import packing_db as pdb
from app.services import warehouse_db as wdb
from app.services import inventory_state_engine as ise
from app.services import stock_promotion_note_db as ndb
from app.services.stock_promotion import run_stock_promotion
from app.services.dhl_delivery_bridge import execute_goods_received
from app.api.routes_packing import seed_purchase_transit

_APP = Path(__file__).resolve().parent.parent / "app"


@pytest.fixture()
def db(tmp_path, monkeypatch):
    pdb.init_packing_db(tmp_path / "packing.db")
    wdb.init_warehouse_db(tmp_path / "warehouse.db")
    from app.core.config import settings as _settings
    monkeypatch.setattr(_settings, "storage_root", tmp_path)
    return tmp_path


def _line(n: int, batch_id: str = "BATCH_B2B") -> dict:
    return {
        "batch_id":              batch_id,
        "packing_document_id":   f"PKDOC-{batch_id}",
        "product_code":          f"EJL/26-27/500-{n}",
        "design_no":             f"D-{n:03}",
        "batch_no":              f"BN-{n:02}",
        "bag_id":                "",
        "pack_sr":               float(n),
        "invoice_no":            "EJL/26-27/500",
        "invoice_line_position": n,
        "quantity":              1.0,
        "gross_weight":          5.0,
        "net_weight":            5.0,
    }


_RESOLUTION = {"received_by": "Izabela", "received_at": "2026-07-03",
               "location": "MAIN-A1"}


# ── 1. Receipt produces a Note ───────────────────────────────────────────────

def test_receipt_confirmation_produces_promotion_note(db):
    lines = [_line(1), _line(2)]
    pdb.upsert_packing_lines(lines)
    seed_purchase_transit("BATCH_B2B", lines)

    result = execute_goods_received("BATCH_B2B", {}, _RESOLUTION, "amit", db)

    assert result["transitioned"] == 2
    assert result["errors"] == []
    note_no = result["note_no"]
    assert note_no, "receipt must produce a Stock Promotion Note (BE-2b)"

    note = ndb.get_note(note_no)
    assert note["trigger"]  == "warehouse_receive"
    assert note["source"]   == "dhl_delivery_bridge"
    assert note["operator"] == "amit"
    assert "Izabela" in note["reason_note"]          # goods_received evidence
    assert "MAIN-A1" in note["reason_note"]
    assert note["piece_count"] == 2
    for l in note["lines"]:
        assert l["state_before"] == "PURCHASE_TRANSIT"
        assert l["state_after"]  == "WAREHOUSE_STOCK"
    # state truth
    counts = ise.count_by_state(batch_id="BATCH_B2B")
    assert counts[ise.WAREHOUSE_STOCK] == 2
    # trigger recorded on the engine audit rows
    for ln in lines:
        assert ise.get_history(pdb._compute_scan_code(ln))[-1]["trigger"] \
            == "warehouse_receive"


# ── 2. Orderings: exactly ONE Note total, both directions ────────────────────

def test_receipt_first_then_pz_single_note(db):
    lines = [_line(1)]
    pdb.upsert_packing_lines(lines)
    seed_purchase_transit("BATCH_B2B", lines)

    r1 = execute_goods_received("BATCH_B2B", {}, _RESOLUTION, "amit", db)
    r2 = run_stock_promotion("BATCH_B2B", trigger="pz_created",
                             source="wfirma_pz_create")

    assert r1["transitioned"] == 1 and r1["note_no"]
    assert r2["promoted"] == 0 and r2["note_no"] == ""
    assert len(ndb.list_notes("BATCH_B2B")) == 1


def test_pz_first_then_receipt_single_note_no_errors(db):
    lines = [_line(1)]
    pdb.upsert_packing_lines(lines)
    seed_purchase_transit("BATCH_B2B", lines)

    r1 = run_stock_promotion("BATCH_B2B", trigger="pz_created",
                             source="wfirma_pz_create")
    r2 = execute_goods_received("BATCH_B2B", {}, _RESOLUTION, "amit", db)

    assert r1["promoted"] == 1 and r1["note_no"]
    assert r2["transitioned"] == 0
    assert r2["skipped"] == 1            # REPLAY signal: already promoted…
    assert r2["errors"] == []            # …idempotent skip, never 409/raise
    assert r2["note_no"] == ""           # no second Note
    assert len(ndb.list_notes("BATCH_B2B")) == 1


def test_replay_distinguishable_from_empty_batch(db):
    """Verify-pass hardening: a caller must be able to tell a REPLAY
    (transitioned=0, skipped>0) from an empty/unknown batch
    (transitioned=0, skipped=0)."""
    empty = execute_goods_received("NO_SUCH_BATCH", {}, _RESOLUTION, "op", db)
    assert (empty["transitioned"], empty["skipped"]) == (0, 0)


def test_partial_failure_shape_pinned(db):
    """The aggregated error string is the DOCUMENTED shape (delta vs the old
    per-scan-code strings — disclosed; no production parser exists). One
    line's engine transition fails; the rest promote and ONE Note covers
    exactly the moved subset."""
    from unittest.mock import patch
    lines = [_line(1), _line(2), _line(3)]
    pdb.upsert_packing_lines(lines)
    seed_purchase_transit("BATCH_B2B", lines)

    failing = pdb._compute_scan_code(lines[1])
    real_transition = ise.transition

    def _raise_for_one(*args, **kwargs):
        if kwargs.get("scan_code") == failing:
            raise RuntimeError("simulated engine failure")
        return real_transition(*args, **kwargs)

    with patch.object(ise, "transition", side_effect=_raise_for_one):
        result = execute_goods_received("BATCH_B2B", {}, _RESOLUTION, "amit", db)

    assert result["transitioned"] == 2
    assert result["errors"] == [
        "1 line(s) failed to promote "
        "(see audit timeline inventory_transition_failed events)"
    ]
    note = ndb.get_note(result["note_no"])
    assert note["piece_count"] == 2      # moved subset only


def test_note_failure_surfaces_in_bridge_errors(db):
    """Verify-pass hardening: promoted-but-no-document must be a
    programmatic signal, not just a log line."""
    from unittest.mock import patch
    lines = [_line(1)]
    pdb.upsert_packing_lines(lines)
    seed_purchase_transit("BATCH_B2B", lines)

    with patch(
        "app.services.stock_promotion_note_db.write_promotion_note",
        side_effect=RuntimeError("note db down"),
    ):
        result = execute_goods_received("BATCH_B2B", {}, _RESOLUTION, "amit", db)

    assert result["transitioned"] == 1           # state truth stands
    assert result["note_no"] == ""
    assert any("note write FAILED" in e for e in result["errors"])


# ── 3. Contracts preserved ───────────────────────────────────────────────────

def test_validation_contract_unchanged(db):
    with pytest.raises(ValueError):
        execute_goods_received("BATCH_B2B", {}, {}, "op", db)


def test_missing_warehouse_db_still_honest(tmp_path, monkeypatch):
    pdb.init_packing_db(tmp_path / "packing.db")
    from app.core.config import settings as _settings
    monkeypatch.setattr(_settings, "storage_root", tmp_path)
    empty_root = tmp_path / "no_such"
    empty_root.mkdir()
    result = execute_goods_received("B", {}, _RESOLUTION, "op", empty_root)
    assert result["transitioned"] == 0
    assert any("warehouse.db not found" in e for e in result["errors"])


# ── 4. Source pins ───────────────────────────────────────────────────────────

def test_bridge_has_no_direct_engine_transition():
    src = (_APP / "services" / "dhl_delivery_bridge.py").read_text(
        encoding="utf-8", errors="replace")
    assert "ise.transition(" not in src, \
        "the bridge must not call the engine directly (BE-2b: shared authority only)"
    assert "run_stock_promotion(" in src
    assert 'trigger  = "warehouse_receive"' in src
    assert 'source   = "dhl_delivery_bridge"' in src


def test_pt_to_ws_writer_set_is_exactly_the_shared_authority():
    """Boundary pin: across service/app, transition calls targeting
    WAREHOUSE_STOCK exist ONLY in (a) stock_promotion.py — the promotion
    authority — and (b) the sample/producer RETURN writers, which move
    SAMPLE_OUT / RETURNED_TO_PRODUCER → WAREHOUSE_STOCK (returns to stock,
    NOT Temp Warehouse→Final Stock promotions; no Note by design under the
    operator contract). A new file in this set must justify itself against
    the BE-2b boundary."""
    import re
    hits = []
    for py in (_APP).rglob("*.py"):
        src = py.read_text(encoding="utf-8", errors="replace")
        if re.search(r"to_state\s*=\s*(?:ise\.|_ise\.|)WAREHOUSE_STOCK", src):
            hits.append(py.name)
    assert sorted(hits) == sorted([
        "stock_promotion.py",            # the ONE promotion authority
        "inventory_sample_writer.py",    # SAMPLE_OUT → WS (return, by design)
        "inventory_returns_writer.py",   # RETURNED_TO_PRODUCER → WS (by design)
    ]), f"unexpected WAREHOUSE_STOCK writer set: {sorted(hits)}"


def test_dev_seed_backfill_variable_promotion_stays_dev_gated():
    """STEP-0 divergence (PROJECT_STATE DECISIONS BE-2b): routes_packing's
    dev_seed_inventory_state promotes PT→WS through a VARIABLE target
    (chain planner, to_state=next_state) — invisible to the literal grep
    above. It is a dev-only legacy-backfill tool, HELD unconverted pending
    the operator's ruling on whether legacy backfills mint Notes. Until
    ruled, its dev gate is the boundary: this pin fires if the gate is
    removed or the site starts calling the engine outside dev."""
    src = (_APP / "api" / "routes_packing.py").read_text(
        encoding="utf-8", errors="replace")
    k = src.index("def dev_seed_inventory_state(")
    body = src[k:k + 2500]
    assert 'settings.environment != "dev"' in body, (
        "dev_seed_inventory_state lost its dev gate — the un-Noted variable "
        "PT→WS promotion would reach production before the operator ruling "
        "(BE-2b STEP-0 divergence)"
    )
    assert "@dev_router.post" in src[max(0, k - 200):k], \
        "seed-batch must stay on the dev_router"
