"""
test_stock_promotion_note.py — BE-2: Stock Promotion Note pins.

Pins the PROJECT_STATE DECISIONS "BE-2 Stock Promotion Note" contract
(operator, verbatim): "Stock Promotion Note created on every Temp Warehouse
-> Final Stock move, recording: source stage, destination stage, packing
list / import reference, design numbers, batch numbers, piece count,
operator, timestamp, reason/note, before/after inventory state."

Coverage per the build instruction:
  - Note-on-promote: every contract field round-trips
  - NO-Note-on-noop: a second (idempotent-skip) promotion writes NO Note
  - partial promotion: ONE Note covering the moved subset only
  - series concurrency: parallel writers never duplicate a note_no
    *** THIS IS THE LOCAL-SERIES PRECEDENT — future series copy these
    semantics (BEGIN IMMEDIATE + MAX+1/year + UNIQUE retry) ***
  - year rollover: seq restarts at 001 in a new series_year
  - before/after state per piece
  - best-effort isolation: a Note-write failure never fails the promotion
  - GET route shape (list by batch + fetch by note_no incl. :path slashes)

Real DBs throughout (packing + warehouse + real seed builder) — no stubs
(Lesson A); same fixture family as test_stock_promotion_be1.py.
"""
from __future__ import annotations

import threading
from unittest.mock import patch

import pytest

from app.services import packing_db as pdb
from app.services import warehouse_db as wdb
from app.services import inventory_state_engine as ise
from app.services import stock_promotion_note_db as ndb
from app.services.stock_promotion import run_stock_promotion
from app.api.routes_packing import seed_purchase_transit


@pytest.fixture()
def db(tmp_path, monkeypatch):
    pdb.init_packing_db(tmp_path / "packing.db")
    wdb.init_warehouse_db(tmp_path / "warehouse.db")
    from app.core.config import settings as _settings
    monkeypatch.setattr(_settings, "storage_root", tmp_path)
    return tmp_path


def _line(n: int, batch_id: str = "BATCH_NOTE", invoice: str = "EJL/26-27/400") -> dict:
    return {
        "batch_id":              batch_id,
        "packing_document_id":   f"PKDOC-{batch_id}",
        "product_code":          f"{invoice}-{n}",
        "design_no":             f"D-{n:03}",
        "batch_no":              f"BN-{n:02}",
        "bag_id":                "",
        "pack_sr":               float(n),
        "invoice_no":            invoice,
        "invoice_line_position": n,
        "quantity":              1.0,
        "gross_weight":          5.0,
        "net_weight":            5.0,
    }


# ── 1. Note-on-promote: contract fields round-trip ───────────────────────────

def test_note_written_on_promotion_with_all_contract_fields(db):
    lines = [_line(1), _line(2), _line(3)]
    pdb.upsert_packing_lines(lines)
    seed_purchase_transit("BATCH_NOTE", lines)

    result = run_stock_promotion("BATCH_NOTE", trigger="pz_created",
                                 source="wfirma_pz_create", operator="amit",
                                 note="goods received OK")
    assert result["promoted"] == 3
    note_no = result["note_no"]
    assert note_no.startswith("SPN/") and note_no.endswith("/2026") or "/" in note_no

    note = ndb.get_note(note_no)
    assert note is not None
    # source stage / destination stage
    assert note["source_stage"] == "PURCHASE_TRANSIT"   # Temp Warehouse
    assert note["dest_stage"]   == "WAREHOUSE_STOCK"    # Final Stock
    # packing list / import reference — BOTH halves of the contract field
    assert "EJL/26-27/400" in note["invoice_nos"]
    assert "PKDOC-BATCH_NOTE" in note["packing_document_ids"], \
        "packing list reference must round-trip on the header"
    # piece count / operator / timestamp / reason
    assert note["piece_count"] == 3
    assert note["operator"]    == "amit"
    assert note["created_at"]
    assert note["reason_note"] == "goods received OK"
    assert note["trigger"]     == "pz_created"
    assert note["batch_id"]    == "BATCH_NOTE"
    # design numbers / batch numbers / before-after per piece (lines)
    assert len(note["lines"]) == 3
    designs = {l["design_no"] for l in note["lines"]}
    assert designs == {"D-001", "D-002", "D-003"}
    for l in note["lines"]:
        assert l["batch_no"].startswith("BN-")
        assert l["invoice_no"] == "EJL/26-27/400"
        assert l["packing_document_id"] == "PKDOC-BATCH_NOTE"
        assert l["state_before"] == "PURCHASE_TRANSIT"
        assert l["state_after"]  == "WAREHOUSE_STOCK"
        assert l["scan_code"]
        # engine event resolved (transition happened → event exists)
        assert l["transition_event_id"]


def test_note_no_in_summary_mirror_detail(db):
    import json as _json
    batch_id = "BATCH_NOTE"
    batch_dir = db / "outputs" / batch_id
    batch_dir.mkdir(parents=True, exist_ok=True)
    audit_path = batch_dir / "audit.json"
    audit_path.write_text(_json.dumps({"batch_id": batch_id, "timeline": []}),
                          encoding="utf-8")

    lines = [_line(1)]
    pdb.upsert_packing_lines(lines)
    seed_purchase_transit(batch_id, lines)
    result = run_stock_promotion(batch_id, trigger="pz_created",
                                 source="wfirma_pz_create")

    timeline = _json.loads(audit_path.read_text(encoding="utf-8"))["timeline"]
    summaries = [e for e in timeline
                 if e.get("event") == "inventory_warehouse_stock_promoted"]
    assert summaries and summaries[0]["detail"]["note_no"] == result["note_no"]
    assert result["note_no"]   # v0 view: note_no surfaces in the audit timeline


# ── 2. NO Note on a no-op re-promotion ───────────────────────────────────────

def test_noop_repromotion_writes_no_second_note(db):
    lines = [_line(1), _line(2)]
    pdb.upsert_packing_lines(lines)
    seed_purchase_transit("BATCH_NOTE", lines)

    first  = run_stock_promotion("BATCH_NOTE", trigger="pz_created",
                                 source="wfirma_pz_create")
    second = run_stock_promotion("BATCH_NOTE", trigger="pz_created",
                                 source="correction_push")

    assert first["note_no"]
    assert second["promoted"] == 0
    assert second["note_no"] == ""          # no Note for a no-op
    assert len(ndb.list_notes("BATCH_NOTE")) == 1


def test_writer_refuses_zero_piece_note(db):
    with pytest.raises(ValueError):
        ndb.write_promotion_note(batch_id="B", moved=[], trigger="manual")


# ── 3. Partial promotion → ONE Note, moved subset only ──────────────────────

def test_partial_promotion_single_note_moved_subset(db):
    lines = [_line(1), _line(2), _line(3)]
    pdb.upsert_packing_lines(lines)
    seed_purchase_transit("BATCH_NOTE", [lines[0], lines[1]])  # line 3 unseeded

    # line 2 already moved on (skip class: beyond)
    sc2 = pdb._compute_scan_code(lines[1])
    ise.transition(scan_code=sc2, to_state=ise.WAREHOUSE_STOCK)

    result = run_stock_promotion("BATCH_NOTE", trigger="pz_created",
                                 source="wfirma_pz_create")
    assert (result["promoted"], result["skipped"]) == (1, 2)

    notes = ndb.list_notes("BATCH_NOTE")
    assert len(notes) == 1
    note = ndb.get_note(notes[0]["note_no"])
    assert note["piece_count"] == 1
    assert len(note["lines"]) == 1
    assert note["lines"][0]["design_no"] == "D-001"


# ── 4. Series concurrency — THE LOCAL-SERIES PRECEDENT ──────────────────────

def test_series_concurrency_no_duplicate_note_no(db):
    """LOCAL-SERIES PRECEDENT PIN: parallel writers must never allocate the
    same note_no. Semantics under test: module _lock (in-process) + BEGIN
    IMMEDIATE (cross-process) + MAX+1/year + UNIQUE backstop with bounded
    retry. Future local series copy exactly these semantics."""
    results: list = []
    errors: list = []

    def _write(i: int) -> None:
        try:
            results.append(ndb.write_promotion_note(
                batch_id=f"B{i}", trigger="pz_created",
                moved=[{"scan_code": f"SC-{i}", "state_before": "PURCHASE_TRANSIT",
                        "state_after": "WAREHOUSE_STOCK"}],
            ))
        except Exception as exc:            # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=_write, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"series writers errored: {errors}"
    assert len(results) == 8
    assert len(set(results)) == 8, f"duplicate note_no allocated: {results}"
    seqs = sorted(int(n.split("/")[1]) for n in results)
    assert seqs == list(range(1, 9)), f"series must be gapless 1..8: {seqs}"


def test_year_rollover_restarts_sequence(db):
    """LOCAL-SERIES PRECEDENT PIN: the sequence is scoped per series_year and
    restarts at 001 in a new year."""
    m = [{"scan_code": "SC-Y", "state_before": "PURCHASE_TRANSIT",
          "state_after": "WAREHOUSE_STOCK"}]
    n_2026a = ndb.write_promotion_note(batch_id="B", moved=m, trigger="t",
                                       now_iso="2026-12-31T23:59:00+00:00")
    n_2026b = ndb.write_promotion_note(batch_id="B", moved=m, trigger="t",
                                       now_iso="2026-12-31T23:59:30+00:00")
    n_2027  = ndb.write_promotion_note(batch_id="B", moved=m, trigger="t",
                                       now_iso="2027-01-01T00:00:30+00:00")
    assert n_2026a == "SPN/001/2026"
    assert n_2026b == "SPN/002/2026"
    assert n_2027  == "SPN/001/2027"


# ── 5. Best-effort isolation: Note failure never fails the promotion ────────

def test_note_write_failure_does_not_fail_promotion(db):
    lines = [_line(1), _line(2)]
    pdb.upsert_packing_lines(lines)
    seed_purchase_transit("BATCH_NOTE", lines)

    with patch(
        "app.services.stock_promotion_note_db.write_promotion_note",
        side_effect=RuntimeError("note db down"),
    ):
        result = run_stock_promotion("BATCH_NOTE", trigger="pz_created",
                                     source="wfirma_pz_create")

    # STATE TRUTH > DOCUMENT: promotions stand, no exception escaped
    assert result["promoted"] == 2
    assert result["note_no"] == ""
    # Verify-pass hardening: the failure is a programmatic signal too
    assert result.get("note_failed") is True
    counts = ise.count_by_state(batch_id="BATCH_NOTE")
    assert counts[ise.WAREHOUSE_STOCK] == 2


# ── 6. GET routes ────────────────────────────────────────────────────────────

def test_get_routes_shape(db, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.core.config import settings as _settings

    # Dev-mode auth pass-through (require_api_key returns immediately when
    # api_key is unset outside prod) — forced explicitly, not assumed.
    monkeypatch.setattr(_settings, "api_key", "", raising=False)
    monkeypatch.setattr(_settings, "environment", "dev", raising=False)

    lines = [_line(1)]
    pdb.upsert_packing_lines(lines)
    seed_purchase_transit("BATCH_NOTE", lines)
    result = run_stock_promotion("BATCH_NOTE", trigger="pz_created",
                                 source="wfirma_pz_create")
    note_no = result["note_no"]

    client = TestClient(app)
    hdrs = {}

    listed = client.get("/api/v1/inventory/promotion-notes/BATCH_NOTE", headers=hdrs)
    assert listed.status_code == 200
    body = listed.json()
    assert body["total"] == 1
    assert body["notes"][0]["note_no"] == note_no

    # note_no contains slashes — the :path converter must accept it verbatim
    got = client.get(f"/api/v1/inventory/promotion-note/{note_no}", headers=hdrs)
    assert got.status_code == 200
    assert got.json()["note_no"] == note_no
    assert len(got.json()["lines"]) == 1

    missing = client.get("/api/v1/inventory/promotion-note/SPN/999/2099", headers=hdrs)
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "NOTE_NOT_FOUND"

    empty = client.get("/api/v1/inventory/promotion-notes/NO_SUCH_BATCH", headers=hdrs)
    assert empty.status_code == 200
    assert empty.json() == {"batch_id": "NO_SUCH_BATCH", "total": 0, "notes": []}
