"""
test_stock_promotion_be1.py — slice B×7-1b BE-1: shared stock promotion authority.

Pins run_stock_promotion() (services/stock_promotion.py) per operator decision
(a) (PROJECT_STATE DECISIONS "slice B×7-1b BE-1", 2026-07-02):

  Rule: If PZ is created through Atlas/EJ pipeline, auto-promote
  PURCHASE_TRANSIT -> WAREHOUSE_STOCK. If PZ is created directly inside
  wFirma, it remains manual/exception handling until webhook/poll extension
  is approved (BE-1c, parked).

Operator-required coverage:
  - idempotent skip (double promotion no-ops cleanly, never raises)
  - receipt-first-then-PZ ordering
  - PZ-first-then-receipt ordering
  - both wFirma PZ writers call the shared function (source-grep pins)
  - the pre-existing generation-path caller delegates (no Logic A/Logic B)

Lesson A: no stubs — real packing_db + warehouse_db + the real
seed_purchase_transit() builder, same fixture pattern as the pre-existing
test_warehouse_stock_promotion.py suite (which must stay green unmodified).
"""
from __future__ import annotations

import json as _json
from pathlib import Path
from unittest.mock import patch

import pytest

from app.services import packing_db as pdb
from app.services import warehouse_db as wdb
from app.services import inventory_state_engine as ise
from app.services.stock_promotion import run_stock_promotion
from app.api.routes_packing import seed_purchase_transit

_APP = Path(__file__).resolve().parent.parent / "app"


@pytest.fixture()
def db(tmp_path, monkeypatch):
    pdb.init_packing_db(tmp_path / "packing.db")
    wdb.init_warehouse_db(tmp_path / "warehouse.db")
    # Redirect storage_root so the timeline mirrors write under tmp_path,
    # not the live storage tree.
    from app.core.config import settings as _settings
    monkeypatch.setattr(_settings, "storage_root", tmp_path)
    return tmp_path


def _line(n: int, batch_id: str = "BATCH_BE1") -> dict:
    return {
        "batch_id":              batch_id,
        "product_code":          f"EJL/26-27/200-{n}",
        "design_no":             f"D-{n:03}",
        "bag_id":                "",
        "pack_sr":               float(n),
        "invoice_no":            "EJL/26-27/200",
        "invoice_line_position": n,
        "quantity":              1.0,
        "gross_weight":          5.0,
        "net_weight":            5.0,
    }


def _audit_stub(root: Path, batch_id: str) -> Path:
    batch_dir = root / "outputs" / batch_id
    batch_dir.mkdir(parents=True, exist_ok=True)
    audit_path = batch_dir / "audit.json"
    audit_path.write_text(_json.dumps({"batch_id": batch_id, "timeline": []}),
                          encoding="utf-8")
    return audit_path


# ── 1. Happy path: promotes and records the trigger ──────────────────────────

def test_promotes_purchase_transit_and_records_trigger(db):
    lines = [_line(i) for i in range(1, 4)]
    pdb.upsert_packing_lines(lines)
    seed_purchase_transit("BATCH_BE1", lines)

    result = run_stock_promotion("BATCH_BE1", trigger="pz_created",
                                 source="wfirma_pz_create", operator="amit")

    assert result["promoted"] == 3
    assert result["skipped"]  == 0
    assert result["errors"]   == 0
    counts = ise.count_by_state(batch_id="BATCH_BE1")
    assert counts[ise.PURCHASE_TRANSIT] == 0
    assert counts[ise.WAREHOUSE_STOCK]  == 3
    # The trigger + operator are recorded on the state-transition audit row
    for ln in lines:
        sc = pdb._compute_scan_code(ln)
        last = ise.get_history(sc)[-1]
        assert last["to_state"] == ise.WAREHOUSE_STOCK
        assert last["trigger"]  == "pz_created"
        assert last["operator"] == "amit"


# ── 2. Double promotion no-ops cleanly (operator scope: MUST) ────────────────

def test_double_promotion_no_ops_cleanly(db):
    lines = [_line(i) for i in range(1, 4)]
    pdb.upsert_packing_lines(lines)
    seed_purchase_transit("BATCH_BE1", lines)

    first  = run_stock_promotion("BATCH_BE1", trigger="pz_created",
                                 source="wfirma_pz_create")
    second = run_stock_promotion("BATCH_BE1", trigger="pz_created",
                                 source="correction_push")

    assert first["promoted"]  == 3
    assert second["promoted"] == 0
    assert second["skipped"]  == 3
    assert second["errors"]   == 0    # skip, not 409/raise
    # No duplicate transition events: exactly [PURCHASE_TRANSIT, WAREHOUSE_STOCK]
    for ln in lines:
        sc = pdb._compute_scan_code(ln)
        states = [e["to_state"] for e in ise.get_history(sc)]
        assert states == [ise.PURCHASE_TRANSIT, ise.WAREHOUSE_STOCK]


# ── 3. Ordering: receipt first, then PZ (operator scope: MUST) ───────────────

def test_receipt_first_then_pz_no_ops(db):
    """Operator confirms physical receipt (warehouse_receive) BEFORE the
    wFirma PZ is booked — the later PZ-created hook must no-op cleanly."""
    lines = [_line(i) for i in range(1, 3)]
    pdb.upsert_packing_lines(lines)
    seed_purchase_transit("BATCH_BE1", lines)

    # Receipt path (dhl_delivery_bridge idiom): direct engine transitions
    for ln in lines:
        ise.transition(scan_code=pdb._compute_scan_code(ln),
                       to_state=ise.WAREHOUSE_STOCK,
                       trigger="warehouse_receive", operator="op")

    result = run_stock_promotion("BATCH_BE1", trigger="pz_created",
                                 source="wfirma_pz_create")

    assert result["promoted"] == 0
    assert result["skipped"]  == 2
    assert result["errors"]   == 0
    # State untouched; single WAREHOUSE_STOCK event per piece (no duplicates)
    for ln in lines:
        sc = pdb._compute_scan_code(ln)
        history = ise.get_history(sc)
        assert [e["to_state"] for e in history] == \
            [ise.PURCHASE_TRANSIT, ise.WAREHOUSE_STOCK]
        assert history[-1]["trigger"] == "warehouse_receive"


# ── 4. Ordering: PZ first, then receipt (operator scope: MUST) ───────────────

def test_pz_first_then_receipt_leaves_nothing_to_receive(db):
    """PZ books first and promotes; the later receipt path selects
    PURCHASE_TRANSIT rows (dhl_delivery_bridge SELECT) — it must find none,
    so receipt no-ops. A direct re-transition attempt raises the engine's
    illegal-transition error, which the bridge's per-row try/except swallows
    (pinned here so that contract can't rot silently)."""
    lines = [_line(i) for i in range(1, 3)]
    pdb.upsert_packing_lines(lines)
    seed_purchase_transit("BATCH_BE1", lines)

    result = run_stock_promotion("BATCH_BE1", trigger="pz_created",
                                 source="wfirma_pz_create")
    assert result["promoted"] == 2

    # The receipt path's input set (state=PURCHASE_TRANSIT for batch) is empty
    remaining = ise.list_by_state(ise.PURCHASE_TRANSIT, batch_id="BATCH_BE1")
    assert remaining == []

    # And a blind re-transition (what the bridge would do per row if it had
    # rows) raises — WAREHOUSE_STOCK → WAREHOUSE_STOCK is illegal — which the
    # bridge catches per-row (dhl_delivery_bridge.py try/except).
    sc = pdb._compute_scan_code(lines[0])
    with pytest.raises(ValueError):
        ise.transition(scan_code=sc, to_state=ise.WAREHOUSE_STOCK,
                       trigger="warehouse_receive", operator="op")
    assert ise.get_state(sc)["state"] == ise.WAREHOUSE_STOCK


# ── 5. Mixed batch: beyond / unseeded / transit ──────────────────────────────

def test_mixed_batch_promotes_only_purchase_transit(db):
    lines = [_line(1), _line(2), _line(3)]
    pdb.upsert_packing_lines(lines)
    seed_purchase_transit("BATCH_BE1", [lines[0], lines[1]])  # line 3 unseeded

    # Advance line 2 beyond WAREHOUSE_STOCK — must never be demoted
    sc2 = pdb._compute_scan_code(lines[1])
    ise.transition(scan_code=sc2, to_state=ise.WAREHOUSE_STOCK)
    ise.transition(scan_code=sc2, to_state=ise.SALES_TRANSIT)

    result = run_stock_promotion("BATCH_BE1", trigger="pz_created",
                                 source="wfirma_pz_create")

    assert result["promoted"] == 1          # line 1 only
    assert result["skipped"]  == 2          # beyond + unseeded
    assert result["errors"]   == 0
    assert ise.get_state(sc2)["state"] == ise.SALES_TRANSIT   # never demoted
    assert ise.get_state(pdb._compute_scan_code(lines[2])) is None


# ── 6. Never raises; errors counted + mirrored ───────────────────────────────

def test_engine_failure_counted_never_raises(db):
    batch_id = "BATCH_BE1"
    audit_path = _audit_stub(db, batch_id)

    lines = [_line(i) for i in range(1, 4)]
    pdb.upsert_packing_lines(lines)
    seed_purchase_transit(batch_id, lines)

    db_lines = pdb.get_packing_lines_for_batch(batch_id)
    failing = db_lines[1]["scan_code"] or pdb._compute_scan_code(db_lines[1])
    real_transition = ise.transition

    def _raise_for_one(*args, **kwargs):
        if kwargs.get("scan_code") == failing \
                and kwargs.get("to_state") == ise.WAREHOUSE_STOCK:
            raise RuntimeError("simulated engine failure")
        return real_transition(*args, **kwargs)

    with patch.object(ise, "transition", side_effect=_raise_for_one):
        result = run_stock_promotion(batch_id, trigger="pz_created",
                                     source="wfirma_pz_create")

    assert result["promoted"] == 2
    assert result["errors"]   == 1

    timeline = _json.loads(audit_path.read_text(encoding="utf-8"))["timeline"]
    failures = [e for e in timeline if e.get("event") == "inventory_transition_failed"]
    assert len(failures) == 1
    assert failures[0]["trigger_source"] == "wfirma_pz_create"
    assert failures[0]["detail"]["scan_code"] == failing


# ── 6b. Benign race counts as skipped, not error (verify-pass hardening) ─────

def test_benign_race_counts_as_skipped_not_error(db):
    """TOCTOU hardening (verify pass 2026-07-02): a piece promoted by a
    concurrent path between get_state and transition must be counted as
    skipped — not as an error — and no failure mirror is emitted."""
    batch_id = "BATCH_BE1"
    audit_path = _audit_stub(db, batch_id)
    lines = [_line(1)]
    pdb.upsert_packing_lines(lines)
    seed_purchase_transit(batch_id, lines)
    sc = pdb._compute_scan_code(lines[0])

    # The racer wins first: the piece is ALREADY at WAREHOUSE_STOCK...
    ise.transition(scan_code=sc, to_state=ise.WAREHOUSE_STOCK,
                   trigger="warehouse_receive", operator="op")

    # ...but run_stock_promotion's FIRST get_state read is stale (returns
    # PURCHASE_TRANSIT), so it attempts the transition, which raises the
    # engine's illegal-transition ValueError. The recheck (second get_state,
    # unpatched truth) must classify this as a clean skip.
    real_get_state = ise.get_state
    calls = {"n": 0}

    def _stale_once(scan_code):
        calls["n"] += 1
        if calls["n"] == 1:
            row = dict(real_get_state(scan_code) or {})
            row["state"] = ise.PURCHASE_TRANSIT
            return row
        return real_get_state(scan_code)

    with patch.object(ise, "get_state", side_effect=_stale_once):
        result = run_stock_promotion(batch_id, trigger="pz_created",
                                     source="wfirma_pz_create")

    assert result["errors"]   == 0
    assert result["skipped"]  == 1
    assert result["promoted"] == 0
    assert ise.get_state(sc)["state"] == ise.WAREHOUSE_STOCK
    timeline = _json.loads(audit_path.read_text(encoding="utf-8"))["timeline"]
    assert not [e for e in timeline
                if e.get("event") == "inventory_transition_failed"], \
        "benign race must not emit a failure mirror"


# ── 7. Summary mirror carries the full counters + trigger ────────────────────

def test_summary_mirror_event(db):
    batch_id = "BATCH_BE1"
    audit_path = _audit_stub(db, batch_id)

    lines = [_line(1), _line(2)]
    pdb.upsert_packing_lines(lines)
    seed_purchase_transit(batch_id, [lines[0]])   # one seeded, one skipped

    result = run_stock_promotion(batch_id, trigger="pz_created",
                                 source="correction_push")
    assert (result["promoted"], result["skipped"]) == (1, 1)

    timeline = _json.loads(audit_path.read_text(encoding="utf-8"))["timeline"]
    summaries = [e for e in timeline
                 if e.get("event") == "inventory_warehouse_stock_promoted"]
    assert len(summaries) == 1
    ev = summaries[0]
    assert ev["trigger_source"]    == "correction_push"
    assert ev["actor"]             == "system"
    assert ev["detail"]["promoted"] == 1
    assert ev["detail"]["skipped"]  == 1
    assert ev["detail"]["errors"]   == 0
    assert ev["detail"]["trigger"]  == "pz_created"
    forbidden = {"unit_price", "total_value", "cif", "duty", "vat", "amount"}
    assert not (forbidden & set(ev["detail"].keys()))


# ── 8. Source-grep pins: both wFirma writers call the shared function ────────

def _src(rel: str) -> str:
    return (_APP / rel).read_text(encoding="utf-8", errors="replace")


def test_wfirma_pz_create_calls_shared_promotion_after_created_event():
    src = _src("api/routes_wfirma.py")
    ev_idx   = src.index("EV_WFIRMA_PZ_CREATED,\n            \"system\",\n            \"wfirma\",")
    call_idx = src.index("run_stock_promotion(", ev_idx)
    assert call_idx > ev_idx, "promotion must fire AFTER EV_WFIRMA_PZ_CREATED"
    block = src[call_idx:call_idx + 300]
    assert 'trigger  = "pz_created"' in block
    assert 'source   = "wfirma_pz_create"' in block
    # surfaced in the create response
    assert '"stock_promotion":  stock_promotion' in src


def test_global_pz_push_calls_shared_promotion():
    src = _src("services/global_pz_push.py")
    k = src.index("run_stock_promotion(")
    block = src[k:k + 300]
    assert 'trigger  = "pz_created"' in block
    assert 'source   = "correction_push"' in block


def test_generation_path_delegates_no_logic_divergence():
    """routes_upload._promote_to_warehouse_stock must DELEGATE to the shared
    authority — it must no longer carry its own transition loop (the
    one-shared-function rule: no Logic A / Logic B)."""
    src = _src("api/routes_upload.py")
    k = src.index("def _promote_to_warehouse_stock(")
    end = src.index("\ndef ", k + 1)
    body = src[k:end]
    assert "run_stock_promotion(" in body
    assert 'trigger  = "pz_generated"' in body
    assert 'source   = "pz_pipeline"' in body
    assert "for line in lines" not in body, "duplicate promotion loop must be gone"
    assert ".transition(" not in body, "delegating wrapper must not call the engine itself"


def test_shared_module_names_operator_rule_and_be1c():
    src = _src("services/stock_promotion.py")
    assert "App-pipeline PZs only for now" in src, "operator decision (a) must be quoted"
    assert "BE-1c" in src, "the parked direct-wFirma extension must be named"
    assert "directly inside" in src
    assert "never raises" in src.lower()
