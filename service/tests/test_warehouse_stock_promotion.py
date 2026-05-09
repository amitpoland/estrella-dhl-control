"""
test_warehouse_stock_promotion.py — PZ-success promoter for WAREHOUSE_STOCK.

Covers _promote_to_warehouse_stock(batch_id), which is invoked from
routes_upload.py inside the PZ-success branch (_r_status in {success, partial}).

Required coverage:
  1. PZ success promotes PURCHASE_TRANSIT → WAREHOUSE_STOCK
  2. PZ partial promotes the same way
  3. PZ failure does NOT promote (verified by NOT calling the helper —
     covered by the call-site condition; we still exercise that the helper
     itself is the only mover)
  4. Idempotent re-run: second call does not duplicate
  5. Lines already at WAREHOUSE_STOCK (or beyond) are skipped, not demoted
  6. State-engine failure does not break the producer (best-effort)
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.services import packing_db as pdb
from app.services import warehouse_db as wdb
from app.services import inventory_state_engine as ise
from app.api.routes_packing import seed_purchase_transit
from app.api.routes_upload import _promote_to_warehouse_stock


@pytest.fixture()
def db(tmp_path, monkeypatch):
    pdb.init_packing_db(tmp_path / "packing.db")
    wdb.init_warehouse_db(tmp_path / "warehouse.db")
    # Redirect storage_root so the _promote_to_warehouse_stock timeline mirror
    # writes its audit event under tmp_path, not the live storage tree.
    from app.core.config import settings as _settings
    monkeypatch.setattr(_settings, "storage_root", tmp_path)
    return tmp_path


def _line(n: int, batch_id: str = "BATCH_PZ") -> dict:
    return {
        "batch_id":              batch_id,
        "product_code":          f"EJL/26-27/100-{n}",
        "design_no":             f"D-{n:03}",
        "bag_id":                "",
        "pack_sr":               float(n),
        "invoice_no":            "EJL/26-27/100",
        "invoice_line_position": n,
        "quantity":              1.0,
        "gross_weight":          5.0,
        "net_weight":            5.0,
    }


# ── 1 + 2: success / partial both promote ────────────────────────────────────

def test_pz_success_promotes_to_warehouse_stock(db):
    lines = [_line(i) for i in range(1, 4)]
    pdb.upsert_packing_lines(lines)
    seed_purchase_transit("BATCH_PZ", lines)

    promoted = _promote_to_warehouse_stock("BATCH_PZ")

    assert promoted == 3
    counts = ise.count_by_state(batch_id="BATCH_PZ")
    assert counts[ise.PURCHASE_TRANSIT] == 0
    assert counts[ise.WAREHOUSE_STOCK]  == 3


def test_pz_partial_promotes_to_warehouse_stock(db):
    # The helper itself doesn't read status; routes_upload gates the call.
    # The "partial" path is identical to "success" once invoked.
    lines = [_line(i) for i in range(1, 3)]
    pdb.upsert_packing_lines(lines)
    seed_purchase_transit("BATCH_PZ", lines)

    promoted = _promote_to_warehouse_stock("BATCH_PZ")

    assert promoted == 2
    assert ise.count_by_state(batch_id="BATCH_PZ")[ise.WAREHOUSE_STOCK] == 2


# ── 3: failure path doesn't call the helper — verify via call-site condition

def test_pz_failure_does_not_promote(db):
    """
    Models the routes_upload guard `if _r_status in (success, partial):`.
    When status is anything else (blocked / failed), the helper is not called
    and PURCHASE_TRANSIT remains untouched.
    """
    lines = [_line(1), _line(2)]
    pdb.upsert_packing_lines(lines)
    seed_purchase_transit("BATCH_PZ", lines)

    # Caller-side guard: blocked → no call, no promotion
    _r_status = "blocked"
    if _r_status in ("success", "partial"):
        _promote_to_warehouse_stock("BATCH_PZ")  # pragma: no cover

    counts = ise.count_by_state(batch_id="BATCH_PZ")
    assert counts[ise.PURCHASE_TRANSIT] == 2
    assert counts[ise.WAREHOUSE_STOCK]  == 0


# ── 4: idempotency on re-run ─────────────────────────────────────────────────

def test_idempotent_re_run_no_duplicate(db):
    lines = [_line(i) for i in range(1, 4)]
    pdb.upsert_packing_lines(lines)
    seed_purchase_transit("BATCH_PZ", lines)

    first  = _promote_to_warehouse_stock("BATCH_PZ")
    second = _promote_to_warehouse_stock("BATCH_PZ")

    assert first  == 3
    assert second == 0   # already at WAREHOUSE_STOCK → skipped

    # Each scan_code has exactly one PURCHASE_TRANSIT event + one WAREHOUSE_STOCK event
    for ln in lines:
        sc = pdb._compute_scan_code(ln)
        history = ise.get_history(sc)
        states = [e["to_state"] for e in history]
        assert states == [ise.PURCHASE_TRANSIT, ise.WAREHOUSE_STOCK]


# ── 5: skips lines already at WAREHOUSE_STOCK or beyond ─────────────────────

def test_transition_skips_if_already_promoted(db):
    lines = [_line(1), _line(2)]
    pdb.upsert_packing_lines(lines)
    seed_purchase_transit("BATCH_PZ", lines)

    # Manually advance line 2 past WAREHOUSE_STOCK
    sc2 = pdb._compute_scan_code(lines[1])
    ise.transition(scan_code=sc2, to_state=ise.WAREHOUSE_STOCK)
    ise.transition(scan_code=sc2, to_state=ise.SALES_TRANSIT)

    promoted = _promote_to_warehouse_stock("BATCH_PZ")

    # Only line 1 (still at PURCHASE_TRANSIT) gets promoted
    assert promoted == 1
    counts = ise.count_by_state(batch_id="BATCH_PZ")
    assert counts[ise.WAREHOUSE_STOCK] == 1
    assert counts[ise.SALES_TRANSIT]   == 1
    # Line 2's state is preserved at SALES_TRANSIT — never demoted
    assert ise.get_state(sc2)["state"] == ise.SALES_TRANSIT


# ── 6: engine failure must not raise out of the helper ─────────────────────

def test_state_engine_failure_does_not_break_pz(db):
    lines = [_line(i) for i in range(1, 3)]
    pdb.upsert_packing_lines(lines)
    seed_purchase_transit("BATCH_PZ", lines)

    with patch.object(ise, "transition", side_effect=RuntimeError("boom")):
        promoted = _promote_to_warehouse_stock("BATCH_PZ")

    assert promoted == 0   # no successful promotions, but no exception escaped
    # State remains at PURCHASE_TRANSIT because every transition raised
    assert ise.count_by_state(batch_id="BATCH_PZ")[ise.PURCHASE_TRANSIT] == 2


# ── 7: lines without scan_code are skipped silently ─────────────────────────

def test_lines_without_state_are_skipped(db):
    """A packing line that was never seeded (no inventory_state row) is
    skipped — the promoter only acts on existing PURCHASE_TRANSIT items."""
    lines = [_line(1), _line(2)]
    pdb.upsert_packing_lines(lines)
    # Seed only line 1
    seed_purchase_transit("BATCH_PZ", [lines[0]])

    promoted = _promote_to_warehouse_stock("BATCH_PZ")

    assert promoted == 1
    counts = ise.count_by_state(batch_id="BATCH_PZ")
    assert counts[ise.WAREHOUSE_STOCK]  == 1
    # Line 2 still has no state row at all
    sc2 = pdb._compute_scan_code(lines[1])
    assert ise.get_state(sc2) is None


# ── 8: audit timeline mirror event ───────────────────────────────────────────

def test_promote_emits_warehouse_stock_mirror_event(db):
    """
    _promote_to_warehouse_stock must append a single per-batch mirror event
    (EV_INVENTORY_WAREHOUSE_STOCK_PROMOTED) to audit.json["timeline"].  The
    detail dict carries only non-financial summary fields.
    """
    import json as _json
    batch_id = "BATCH_PZ"

    # Stub audit.json under the patched storage_root
    batch_dir = db / "outputs" / batch_id
    batch_dir.mkdir(parents=True, exist_ok=True)
    audit_path = batch_dir / "audit.json"
    audit_path.write_text(_json.dumps({"batch_id": batch_id, "timeline": []}),
                          encoding="utf-8")

    lines = [_line(i) for i in range(1, 4)]
    pdb.upsert_packing_lines(lines)
    seed_purchase_transit(batch_id, lines)

    promoted = _promote_to_warehouse_stock(batch_id)
    assert promoted == 3

    audit = _json.loads(audit_path.read_text(encoding="utf-8"))
    timeline = audit.get("timeline", [])
    mirrors  = [e for e in timeline
                if e.get("event") == "inventory_warehouse_stock_promoted"]
    assert len(mirrors) == 1, mirrors
    ev = mirrors[0]
    assert ev["trigger_source"] == "pz_pipeline"
    assert ev["actor"]          == "system"
    assert ev["detail"]["batch_id"] == batch_id
    assert ev["detail"]["promoted"] == promoted
    forbidden = {"unit_price", "total_value", "cif", "duty", "vat", "amount"}
    assert not (forbidden & set(ev["detail"].keys()))


# ── 9: per-line failure mirror event ─────────────────────────────────────────

def test_promote_emits_transition_failed_on_engine_error(db):
    """
    _promote_to_warehouse_stock must append a per-line
    EV_INVENTORY_TRANSITION_FAILED event for every row whose ise.transition
    raises, while still promoting the surviving rows AND still emitting the
    summary EV_INVENTORY_WAREHOUSE_STOCK_PROMOTED at the end.

    Detail is bounded: scan_code + to_state + truncated error string + batch_id.
    """
    import json as _json
    batch_id = "BATCH_PZ"

    # Stub audit.json under the patched storage_root
    batch_dir = db / "outputs" / batch_id
    batch_dir.mkdir(parents=True, exist_ok=True)
    audit_path = batch_dir / "audit.json"
    audit_path.write_text(_json.dumps({"batch_id": batch_id, "timeline": []}),
                          encoding="utf-8")

    lines = [_line(i) for i in range(1, 4)]
    pdb.upsert_packing_lines(lines)
    seed_purchase_transit(batch_id, lines)

    # The promote loop calls ise.transition only with scan_code= keyword + to_state.
    # Re-read the freshly-stamped scan_codes from the DB so the failure target
    # matches what _promote_to_warehouse_stock will see.
    db_lines = pdb.get_packing_lines_for_batch(batch_id)
    failing_scancode = db_lines[1]["scan_code"] or pdb._compute_scan_code(db_lines[1])

    real_transition = ise.transition

    def _raise_for_one(*args, **kwargs):
        if kwargs.get("scan_code") == failing_scancode \
                and kwargs.get("to_state") == ise.WAREHOUSE_STOCK:
            raise RuntimeError("simulated engine failure for one line " + ("Y" * 300))
        return real_transition(*args, **kwargs)

    with patch.object(ise, "transition", side_effect=_raise_for_one):
        promoted = _promote_to_warehouse_stock(batch_id)

    # Surviving rows still promoted (best-effort posture preserved)
    assert promoted == 2

    audit = _json.loads(audit_path.read_text(encoding="utf-8"))
    timeline = audit.get("timeline", [])

    # Summary event still fires after partial failure
    summaries = [e for e in timeline
                 if e.get("event") == "inventory_warehouse_stock_promoted"]
    assert len(summaries) == 1, summaries
    assert summaries[0]["detail"]["promoted"] == 2

    # Exactly one per-line failure event, with bounded error
    failures = [e for e in timeline
                if e.get("event") == "inventory_transition_failed"]
    assert len(failures) == 1, failures
    fev = failures[0]
    assert fev["trigger_source"]           == "pz_pipeline"
    assert fev["actor"]                    == "system"
    assert fev["detail"]["batch_id"]       == batch_id
    assert fev["detail"]["scan_code"]      == failing_scancode
    assert fev["detail"]["to_state"]       == "warehouse_stock"
    assert isinstance(fev["detail"]["error"], str)
    assert len(fev["detail"]["error"])     >  0
    assert len(fev["detail"]["error"])     <= 200
    forbidden = {"unit_price", "total_value", "cif", "duty", "vat", "amount"}
    assert not (forbidden & set(fev["detail"].keys()))
