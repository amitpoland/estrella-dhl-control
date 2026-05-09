"""
test_purchase_transit_seeding.py — Producer wiring at packing upload.

Covers seed_purchase_transit():
  1. seeds PURCHASE_TRANSIT for every line with a scan_code
  2. re-upload (re-seed) is idempotent — no duplicate state events
  3. state-engine failure does not break the producer (best-effort)
  4. lines without scan_code are skipped, not raised
  5. seeds carry product_code, design_no, batch_id forward
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.services import packing_db as pdb
from app.services import warehouse_db as wdb
from app.services import inventory_state_engine as ise
from app.api.routes_packing import seed_purchase_transit


@pytest.fixture()
def db(tmp_path, monkeypatch):
    pdb.init_packing_db(tmp_path / "packing.db")
    wdb.init_warehouse_db(tmp_path / "warehouse.db")
    # Redirect storage_root so the seed_purchase_transit timeline mirror
    # writes its audit-event under tmp_path rather than the live storage tree.
    from app.core.config import settings as _settings
    monkeypatch.setattr(_settings, "storage_root", tmp_path)
    return tmp_path


def _line(n: int, **kwargs) -> dict:
    base = {
        "batch_id":     "BATCH_PT_TEST",
        "product_code": f"EJL/26-27/100-{n}",
        "design_no":    f"D-{n:03}",
        "bag_id":       "",
        "pack_sr":      float(n),
        "invoice_no":   "EJL/26-27/100",
        "invoice_line_position": n,
        "quantity":     1.0,
        "gross_weight": 5.0,
        "net_weight":   5.0,
    }
    base.update(kwargs)
    return base


# ── 1. Seeds every line ──────────────────────────────────────────────────────

def test_seed_creates_purchase_transit_for_every_line(db):
    lines = [_line(i) for i in range(1, 4)]
    seeded = seed_purchase_transit("BATCH_PT_TEST", lines)
    assert seeded == 3

    for ln in lines:
        sc = pdb._compute_scan_code(ln)
        st = ise.get_state(sc)
        assert st is not None
        assert st["state"]        == ise.PURCHASE_TRANSIT
        assert st["product_code"] == ln["product_code"]
        assert st["design_no"]    == ln["design_no"]
        assert st["batch_id"]     == "BATCH_PT_TEST"

    counts = ise.count_by_state(batch_id="BATCH_PT_TEST")
    assert counts[ise.PURCHASE_TRANSIT] == 3


# ── 2. Re-seed is idempotent ─────────────────────────────────────────────────

def test_reseed_is_idempotent(db):
    lines = [_line(1), _line(2)]
    first  = seed_purchase_transit("BATCH_PT_TEST", lines)
    second = seed_purchase_transit("BATCH_PT_TEST", lines)
    assert first  == 2
    assert second == 0  # already seeded → all skipped

    # No duplicate transition events for the same scan_code
    for ln in lines:
        sc = pdb._compute_scan_code(ln)
        history = ise.get_history(sc)
        assert len(history) == 1
        assert history[0]["to_state"] == ise.PURCHASE_TRANSIT


# ── 3. Engine failure must not break the producer ───────────────────────────

def test_state_engine_failure_does_not_break_producer(db):
    lines = [_line(1), _line(2)]
    with patch.object(ise, "transition", side_effect=RuntimeError("boom")):
        # Must not raise
        seeded = seed_purchase_transit("BATCH_PT_TEST", lines)
    assert seeded == 0
    # No states recorded since every transition raised
    assert ise.count_by_state(batch_id="BATCH_PT_TEST")[ise.PURCHASE_TRANSIT] == 0


# ── 4. Lines without scan_code are skipped ──────────────────────────────────

def test_lines_without_scan_code_are_skipped(db):
    # No product_code → _compute_scan_code returns "" → skip
    bad = {"batch_id": "BATCH_PT_TEST", "product_code": "", "design_no": "",
           "bag_id": "", "pack_sr": None}
    good = _line(1)
    seeded = seed_purchase_transit("BATCH_PT_TEST", [bad, good])
    assert seeded == 1
    assert ise.get_state(pdb._compute_scan_code(good))["state"] == ise.PURCHASE_TRANSIT


# ── 5. Existing-state guard: lines already in any state are skipped ─────────

def test_existing_state_skipped(db):
    ln = _line(1)
    sc = pdb._compute_scan_code(ln)
    # Pre-seed manually to a later state
    ise.transition(scan_code=sc, to_state=ise.PURCHASE_TRANSIT,
                   product_code=ln["product_code"], design_no=ln["design_no"],
                   batch_id="BATCH_PT_TEST")
    ise.transition(scan_code=sc, to_state=ise.WAREHOUSE_STOCK)

    # Now run seeder — must not attempt to demote to PURCHASE_TRANSIT
    seeded = seed_purchase_transit("BATCH_PT_TEST", [ln])
    assert seeded == 0
    assert ise.get_state(sc)["state"] == ise.WAREHOUSE_STOCK


# ── 6. Audit timeline mirror event ──────────────────────────────────────────

def test_seed_emits_purchase_transit_mirror_event(db):
    """
    seed_purchase_transit must append a single per-batch mirror event
    (EV_INVENTORY_PURCHASE_TRANSIT_SEEDED) to audit.json["timeline"].  The
    detail dict carries only non-financial summary fields.
    """
    import json as _json
    batch_id = "BATCH_PT_TEST"

    # Stub audit.json under the patched storage_root
    batch_dir = db / "outputs" / batch_id
    batch_dir.mkdir(parents=True, exist_ok=True)
    audit_path = batch_dir / "audit.json"
    audit_path.write_text(_json.dumps({"batch_id": batch_id, "timeline": []}),
                          encoding="utf-8")

    lines  = [_line(i) for i in range(1, 4)]
    seeded = seed_purchase_transit(batch_id, lines)
    assert seeded == 3

    audit = _json.loads(audit_path.read_text(encoding="utf-8"))
    timeline = audit.get("timeline", [])
    mirrors  = [e for e in timeline
                if e.get("event") == "inventory_purchase_transit_seeded"]
    assert len(mirrors) == 1, mirrors
    ev = mirrors[0]
    assert ev["trigger_source"] == "packing_upload"
    assert ev["actor"]          == "system"
    assert ev["detail"]["batch_id"]    == batch_id
    assert ev["detail"]["seeded"]      == seeded
    assert ev["detail"]["total_lines"] == len(lines)
    # No financial / customs fields leaked into detail
    forbidden = {"unit_price", "total_value", "cif", "duty", "vat", "amount"}
    assert not (forbidden & set(ev["detail"].keys()))


# ── 7. Per-line failure mirror event ────────────────────────────────────────

def test_seed_emits_transition_failed_on_engine_error(db):
    """
    seed_purchase_transit must append a per-line
    EV_INVENTORY_TRANSITION_FAILED event for every row whose ise.transition
    raises, while still committing the surviving rows AND still emitting the
    summary EV_INVENTORY_PURCHASE_TRANSIT_SEEDED at the end.

    Detail is bounded: scan_code + to_state + truncated error string + batch_id.
    """
    import json as _json
    batch_id = "BATCH_PT_TEST"

    # Stub audit.json under the patched storage_root
    batch_dir = db / "outputs" / batch_id
    batch_dir.mkdir(parents=True, exist_ok=True)
    audit_path = batch_dir / "audit.json"
    audit_path.write_text(_json.dumps({"batch_id": batch_id, "timeline": []}),
                          encoding="utf-8")

    lines = [_line(i) for i in range(1, 4)]
    failing_line     = lines[1]
    failing_scancode = pdb._compute_scan_code(failing_line)

    real_transition = ise.transition

    def _raise_for_one(*args, **kwargs):
        if kwargs.get("scan_code") == failing_scancode:
            raise RuntimeError("simulated engine failure for one line " + ("X" * 300))
        return real_transition(*args, **kwargs)

    with patch.object(ise, "transition", side_effect=_raise_for_one):
        seeded = seed_purchase_transit(batch_id, lines)

    # Surviving rows still transitioned (best-effort posture preserved)
    assert seeded == 2

    audit = _json.loads(audit_path.read_text(encoding="utf-8"))
    timeline = audit.get("timeline", [])

    # Summary event still fires after partial failure
    summaries = [e for e in timeline
                 if e.get("event") == "inventory_purchase_transit_seeded"]
    assert len(summaries) == 1, summaries
    assert summaries[0]["detail"]["seeded"]      == 2
    assert summaries[0]["detail"]["total_lines"] == len(lines)

    # Exactly one per-line failure event, with bounded error
    failures = [e for e in timeline
                if e.get("event") == "inventory_transition_failed"]
    assert len(failures) == 1, failures
    fev = failures[0]
    assert fev["trigger_source"]           == "packing_upload"
    assert fev["actor"]                    == "system"
    assert fev["detail"]["batch_id"]       == batch_id
    assert fev["detail"]["scan_code"]      == failing_scancode
    assert fev["detail"]["to_state"]       == "purchase_transit"
    assert isinstance(fev["detail"]["error"], str)
    assert len(fev["detail"]["error"])     >  0
    assert len(fev["detail"]["error"])     <= 200
    forbidden = {"unit_price", "total_value", "cif", "duty", "vat", "amount"}
    assert not (forbidden & set(fev["detail"].keys()))


# ── Dev trigger endpoint ─────────────────────────────────────────────────────

@pytest.fixture()
def dev_client(tmp_path):
    """TestClient with packing/warehouse DBs initialised under tmp_path."""
    from unittest.mock import patch as _patch
    from fastapi.testclient import TestClient
    from app.core.config import settings
    pdb.init_packing_db(tmp_path / "packing.db")
    wdb.init_warehouse_db(tmp_path / "warehouse.db")
    from app.main import app
    with _patch.object(settings, "storage_root", tmp_path):
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


def test_dev_trigger_seeds_existing_lines(dev_client):
    lines = [_line(i) for i in range(1, 4)]
    pdb.upsert_packing_lines(lines)
    # Producer hasn't run yet — packing_lines exist but no inventory_state
    assert ise.count_by_state(batch_id="BATCH_PT_TEST")[ise.PURCHASE_TRANSIT] == 0

    r = dev_client.post(
        "/api/v1/dev/packing/trigger",
        json={"batch_id": "BATCH_PT_TEST"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["lines"]     == 3
    assert body["processed"] == 3

    counts = ise.count_by_state(batch_id="BATCH_PT_TEST")
    assert counts[ise.PURCHASE_TRANSIT] == 3


def test_dev_trigger_idempotent(dev_client):
    lines = [_line(i) for i in range(1, 3)]
    pdb.upsert_packing_lines(lines)

    r1 = dev_client.post("/api/v1/dev/packing/trigger",
                         json={"batch_id": "BATCH_PT_TEST"})
    r2 = dev_client.post("/api/v1/dev/packing/trigger",
                         json={"batch_id": "BATCH_PT_TEST"})
    assert r1.json()["processed"] == 2
    assert r2.json()["processed"] == 0   # already seeded → no new transitions

    # Still only one event per scan_code in history
    for ln in lines:
        sc = pdb._compute_scan_code(ln)
        assert len(ise.get_history(sc)) == 1


def test_dev_trigger_empty_batch(dev_client):
    r = dev_client.post(
        "/api/v1/dev/packing/trigger",
        json={"batch_id": "BATCH_DOES_NOT_EXIST"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["lines"]     == 0
    assert body["processed"] == 0


# ── Dev seed-batch endpoint (legacy backfill) ───────────────────────────────

import json as _json

SEED_URL = "/api/v1/dev/inventory-state/seed-batch"


def _write_audit(storage_root, batch_id: str, audit: dict, sub: str = "outputs"):
    d = storage_root / sub / batch_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "audit.json").write_text(_json.dumps(audit), encoding="utf-8")


def test_seed_no_pz_targets_purchase_transit(dev_client, tmp_path):
    pdb.upsert_packing_lines([_line(1, batch_id="LEGACY_PT")])
    _write_audit(tmp_path, "LEGACY_PT", {"status": "blocked"})

    r = dev_client.post(SEED_URL, json={"batch_id": "LEGACY_PT"})
    body = r.json()
    assert body["decided_target"] == ise.PURCHASE_TRANSIT
    assert body["transitioned"]    == 1
    assert body["errors"]          == []
    sc = pdb._compute_scan_code(_line(1, batch_id="LEGACY_PT"))
    assert ise.get_state(sc)["state"] == ise.PURCHASE_TRANSIT


def test_seed_with_pz_filename_targets_warehouse_stock(dev_client, tmp_path):
    pdb.upsert_packing_lines([_line(2, batch_id="LEGACY_WS_F")])
    _write_audit(tmp_path, "LEGACY_WS_F",
                  {"status": "blocked", "pz_pdf_filename": "PZ_X.pdf"})

    body = dev_client.post(SEED_URL, json={"batch_id": "LEGACY_WS_F"}).json()
    assert body["decided_target"] == ise.WAREHOUSE_STOCK
    assert body["transitioned"]    == 2  # PT then WS
    sc = pdb._compute_scan_code(_line(2, batch_id="LEGACY_WS_F"))
    assert ise.get_state(sc)["state"] == ise.WAREHOUSE_STOCK
    history = ise.get_history(sc)
    assert [e["to_state"] for e in history] == [ise.PURCHASE_TRANSIT,
                                                ise.WAREHOUSE_STOCK]


def test_seed_with_pz_generated_flag_targets_warehouse_stock(dev_client, tmp_path):
    pdb.upsert_packing_lines([_line(3, batch_id="LEGACY_WS_FLAG")])
    _write_audit(tmp_path, "LEGACY_WS_FLAG",
                  {"status": "blocked", "pz_generated": True})
    body = dev_client.post(SEED_URL, json={"batch_id": "LEGACY_WS_FLAG"}).json()
    assert body["decided_target"] == ise.WAREHOUSE_STOCK


def test_seed_with_status_partial_targets_warehouse_stock(dev_client, tmp_path):
    pdb.upsert_packing_lines([_line(4, batch_id="LEGACY_WS_PART")])
    _write_audit(tmp_path, "LEGACY_WS_PART", {"status": "partial"})
    body = dev_client.post(SEED_URL, json={"batch_id": "LEGACY_WS_PART"}).json()
    assert body["decided_target"] == ise.WAREHOUSE_STOCK


def test_seed_dry_run_writes_nothing(dev_client, tmp_path):
    pdb.upsert_packing_lines([_line(5, batch_id="LEGACY_DRY")])
    _write_audit(tmp_path, "LEGACY_DRY", {"status": "blocked"})

    body = dev_client.post(SEED_URL, json={
        "batch_id": "LEGACY_DRY", "dry_run": True,
    }).json()
    assert body["dry_run"] is True
    assert body["planned"]      == 1
    assert body["transitioned"] == 0
    sc = pdb._compute_scan_code(_line(5, batch_id="LEGACY_DRY"))
    assert ise.get_state(sc) is None  # nothing written


def test_seed_idempotent(dev_client, tmp_path):
    pdb.upsert_packing_lines([_line(6, batch_id="LEGACY_IDM")])
    _write_audit(tmp_path, "LEGACY_IDM", {"status": "blocked"})
    r1 = dev_client.post(SEED_URL, json={"batch_id": "LEGACY_IDM"}).json()
    r2 = dev_client.post(SEED_URL, json={"batch_id": "LEGACY_IDM"}).json()
    assert r1["transitioned"] == 1
    assert r2["transitioned"] == 0
    assert r2["skipped"]      == 1
    sc = pdb._compute_scan_code(_line(6, batch_id="LEGACY_IDM"))
    assert len(ise.get_history(sc)) == 1


def test_seed_missing_audit_returns_400(dev_client, tmp_path):
    pdb.upsert_packing_lines([_line(7, batch_id="LEGACY_NOAUDIT")])
    r = dev_client.post(SEED_URL, json={"batch_id": "LEGACY_NOAUDIT"})
    assert r.status_code == 400
    assert "audit.json" in r.json()["detail"].lower()


def test_seed_rejects_sales_transit_target(dev_client, tmp_path):
    r = dev_client.post(SEED_URL, json={
        "batch_id": "LEGACY_X", "target_state": "SALES_TRANSIT",
    })
    assert r.status_code == 400


def test_seed_rejects_closed_target(dev_client, tmp_path):
    r = dev_client.post(SEED_URL, json={
        "batch_id": "LEGACY_X", "target_state": "CLOSED",
    })
    assert r.status_code == 400


def test_seed_does_not_touch_sales_packing_lines(dev_client, tmp_path):
    """Sales-side rows must NOT produce inventory_state rows."""
    from app.services import document_db as ddb
    ddb.init_document_db(tmp_path / "documents.db")
    pdb.upsert_packing_lines([_line(8, batch_id="LEGACY_NOSALES")])
    _write_audit(tmp_path, "LEGACY_NOSALES", {"status": "blocked"})
    sd = ddb.store_sales_document(
        batch_id="LEGACY_NOSALES",
        document_id="doc-x",
        data={"client_name": "ACME", "sales_doc_no": "SO-1"},
    )
    ddb.store_sales_packing_lines(sd, "LEGACY_NOSALES", [{
        "client_name": "ACME", "client_ref": "",
        "product_code": "SALES_SKU_X", "design_no": "SALES_SKU_X",
        "bag_id": "", "quantity": 1.0, "remarks": "",
    }])

    dev_client.post(SEED_URL, json={"batch_id": "LEGACY_NOSALES"})

    # Only the purchase scan_code should appear in inventory_state
    purchase_sc = pdb._compute_scan_code(_line(8, batch_id="LEGACY_NOSALES"))
    assert ise.get_state(purchase_sc) is not None
    # Sales SKU never seeded
    sales_sc_guess = "SALES_SKU_X"
    assert ise.get_state(sales_sc_guess) is None


def test_seed_skips_items_already_beyond_target(dev_client, tmp_path):
    """Pre-set one scan_code to SALES_TRANSIT — seeder must not demote."""
    pdb.upsert_packing_lines([_line(9, batch_id="LEGACY_BEY")])
    _write_audit(tmp_path, "LEGACY_BEY",
                  {"status": "blocked", "pz_pdf_filename": "PZ.pdf"})
    sc = pdb._compute_scan_code(_line(9, batch_id="LEGACY_BEY"))
    # Walk well beyond the target
    ise.transition(scan_code=sc, to_state=ise.PURCHASE_TRANSIT,
                   batch_id="LEGACY_BEY",
                   product_code="EJL/26-27/100-9", design_no="D-009")
    ise.transition(scan_code=sc, to_state=ise.WAREHOUSE_STOCK)
    ise.transition(scan_code=sc, to_state=ise.SALES_TRANSIT)

    body = dev_client.post(SEED_URL, json={"batch_id": "LEGACY_BEY"}).json()
    assert body["decided_target"] == ise.WAREHOUSE_STOCK
    assert body["transitioned"]    == 0
    assert body["skipped"]         == 1
    assert ise.get_state(sc)["state"] == ise.SALES_TRANSIT


def test_seed_per_row_failure_captured(dev_client, tmp_path):
    """A failing row logs an error; the batch continues."""
    from unittest.mock import patch as _p
    pdb.upsert_packing_lines([
        _line(10, batch_id="LEGACY_ERR"),
        _line(11, batch_id="LEGACY_ERR"),
    ])
    _write_audit(tmp_path, "LEGACY_ERR", {"status": "blocked"})

    sc_bad = pdb._compute_scan_code(_line(10, batch_id="LEGACY_ERR"))
    real_transition = ise.transition

    def maybe_fail(*args, **kwargs):
        if kwargs.get("scan_code") == sc_bad:
            raise RuntimeError("boom-row-10")
        return real_transition(*args, **kwargs)

    with _p.object(ise, "transition", side_effect=maybe_fail):
        body = dev_client.post(SEED_URL, json={"batch_id": "LEGACY_ERR"}).json()

    assert body["transitioned"] == 1   # the good one
    assert len(body["errors"])  == 1
    assert body["errors"][0]["scan_code"]
    assert "RuntimeError" in body["errors"][0]["error"]
