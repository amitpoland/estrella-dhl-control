"""test_advance_packing.py — pre-shipment (advance) packing lists.

The capability is an extension of the ONE packing authority (packing_db), so
these tests are mostly about what an advance row must NOT become: no product
identity, no piece identity, no shipment directory, no inventory.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


_ROWS = [
    {"design_no": "D-100", "quantity": 10, "uom": "PCS", "item_type": "RING"},
    {"design_no": "D-200", "quantity": 5, "uom": "PCS", "item_type": "RING"},
]


@pytest.fixture()
def adv(tmp_path, monkeypatch):
    from app.services import advance_packing as adv_mod
    from app.services.packing_db import init_packing_db

    init_packing_db(tmp_path / "packing.db")
    monkeypatch.setattr(adv_mod, "_storage", lambda: tmp_path)
    monkeypatch.setattr(adv_mod, "extract_packing",
                        lambda p, **kw: (list(_ROWS), "stub", "1.0", {}))
    return adv_mod


@pytest.fixture()
def src(tmp_path):
    f = tmp_path / "advance.xlsx"
    f.write_bytes(b"stub-advance-packing-list")
    return f


def _lines(batch_id):
    from app.services import packing_db as pdb
    return pdb.get_packing_lines_for_batch(batch_id)


# ── identity: an advance row carries neither product nor piece identity ─────

def test_advance_rows_have_no_product_code_and_no_scan_code(adv, src):
    res = adv.ingest_advance(src, operator="tester")
    assert adv.is_advance_batch(res["batch_id"])
    assert res["rows_stored"] == 2

    rows = _lines(res["batch_id"])
    assert len(rows) == 2
    assert all(not r["product_code"] for r in rows), \
        "ADR-024 mints product_code from the purchase invoice, which does not exist yet"
    assert all(r["scan_code"] is None for r in rows), \
        "no goods exist, so no piece identity"
    assert {r["design_no"] for r in rows} == {"D-100", "D-200"}


def test_advance_document_is_stamped_advance_and_unlinked(adv, src):
    from app.services import packing_db as pdb
    res = adv.ingest_advance(src)
    doc = pdb.get_packing_document(res["document_id"])
    assert doc["doc_stage"] == "advance"
    assert doc["linked_batch_id"] == ""
    assert doc["invoice_no"] == ""


def test_ingest_is_idempotent_on_the_same_file(adv, src):
    a = adv.ingest_advance(src)
    b = adv.ingest_advance(src, batch_id=a["batch_id"])
    assert b["document_id"] == a["document_id"]
    assert len(_lines(a["batch_id"])) == 2


def test_repeated_design_rows_are_not_collapsed(adv, src, monkeypatch):
    """402 of 1523 production packing lines carry neither pack_sr nor bag_id.
    An advance list has no invoice_no, no line position and no unit_price
    either, so without a per-row ordinal the dedup key would swallow the
    second bag and understate the announced quantity."""
    rows = [{"design_no": "D-100", "quantity": 10},
            {"design_no": "D-100", "quantity": 10},
            {"design_no": "D-100", "quantity": 7}]
    monkeypatch.setattr(adv, "extract_packing",
                        lambda p, **kw: (list(rows), "stub", "1.0", {}))
    res = adv.ingest_advance(src)
    stored = _lines(res["batch_id"])
    assert len(stored) == 3
    assert sum(r["quantity"] for r in stored) == 27
    assert sorted(r["pack_sr"] for r in stored) == [1, 2, 3]


def test_a_second_file_needs_its_own_advance_batch(adv, src, tmp_path):
    a = adv.ingest_advance(src)
    other = tmp_path / "advance2.xlsx"
    other.write_bytes(b"a different advance list")
    with pytest.raises(ValueError, match="already holds document"):
        adv.ingest_advance(other, batch_id=a["batch_id"])
    assert adv.ingest_advance(other)["batch_id"] != a["batch_id"]


def test_advance_sources_live_outside_outputs(adv, tmp_path, src):
    res = adv.ingest_advance(src)
    d = adv.advance_source_dir(res["batch_id"])
    assert "outputs" not in d.parts
    assert not (tmp_path / "outputs" / res["batch_id"]).exists(), \
        "an advance batch must never get a shipment directory"


def test_backfill_scan_codes_never_touches_advance_rows(adv, src):
    from app.services import packing_db as pdb
    res = adv.ingest_advance(src)
    pdb.upsert_packing_document(batch_id="SHIPMENT_X", invoice_no="EJL/26-27/1",
                                source_file_path="x", source_file_hash="h",
                                document_id="DOCFINAL")
    pdb.upsert_packing_lines([{
        "packing_document_id": "DOCFINAL", "batch_id": "SHIPMENT_X",
        "invoice_no": "EJL/26-27/1", "product_code": "EJL/26-27/1-1",
        "design_no": "D-100", "quantity": 10,
    }])
    with pdb._connect() as con:
        con.execute("UPDATE packing_lines SET scan_code=NULL")

    pdb.backfill_scan_codes()

    assert all(r["scan_code"] is None for r in _lines(res["batch_id"]))
    assert any(r["scan_code"] for r in _lines("SHIPMENT_X")), \
        "backfill must still work for real shipment rows"


# ── link: set once, never rewrites either document ─────────────────────────

def _final_batch(tmp_path, batch_id="SHIPMENT_1234567890_2026-08_abcdef01",
                 rows=(("D-100", 10.0), ("D-200", 5.0))):
    from app.services import packing_db as pdb
    (tmp_path / "outputs" / batch_id).mkdir(parents=True, exist_ok=True)
    doc_id = "DOCF_" + batch_id[-8:]
    pdb.upsert_packing_document(batch_id=batch_id, invoice_no="EJL/26-27/1",
                                source_file_path="x", source_file_hash="h2" + batch_id,
                                document_id=doc_id)
    pdb.upsert_packing_lines([
        {"packing_document_id": doc_id, "batch_id": batch_id,
         "invoice_no": "EJL/26-27/1", "product_code": "EJL/26-27/1-%d" % i,
         "design_no": d, "quantity": q}
        for i, (d, q) in enumerate(rows, start=1)
    ])
    return batch_id


def test_link_requires_a_real_shipment_directory(adv, src, tmp_path):
    res = adv.ingest_advance(src)
    with pytest.raises(ValueError, match="does not exist"):
        adv.link_to_batch(res["document_id"], "SHIPMENT_NOPE_2026-08_00000000")


def test_link_refuses_advance_to_advance(adv, src):
    res = adv.ingest_advance(src)
    with pytest.raises(ValueError, match="real shipment batch"):
        adv.link_to_batch(res["document_id"], adv.new_advance_id())


def test_link_is_idempotent_but_refuses_relink(adv, src, tmp_path):
    res = adv.ingest_advance(src)
    bid = _final_batch(tmp_path)
    assert adv.link_to_batch(res["document_id"], bid)["changed"] is True
    assert adv.link_to_batch(res["document_id"], bid)["changed"] is False

    other = _final_batch(tmp_path, "SHIPMENT_9999999999_2026-08_beefbeef")
    with pytest.raises(ValueError, match="already linked"):
        adv.link_to_batch(res["document_id"], other)


def test_link_does_not_rewrite_the_advance_lines(adv, src, tmp_path):
    res = adv.ingest_advance(src)
    adv.link_to_batch(res["document_id"], _final_batch(tmp_path))
    rows = _lines(res["batch_id"])
    assert all(not r["product_code"] and r["scan_code"] is None for r in rows)


# ── reconcile: read-only, expected vs actual, never physical truth ──────────

def test_reconcile_needs_a_link(adv, src):
    res = adv.ingest_advance(src)
    with pytest.raises(ValueError, match="not linked"):
        adv.reconcile(res["document_id"])


def test_reconcile_reports_match(adv, src, tmp_path):
    res = adv.ingest_advance(src)
    adv.link_to_batch(res["document_id"], _final_batch(tmp_path))
    r = adv.reconcile(res["document_id"])
    assert r["summary"]["fully_matched"] is True
    assert r["summary"]["expected_total"] == r["summary"]["actual_total"] == 15.0


@pytest.mark.parametrize("rows,design,status", [
    ((("D-100", 10.0), ("D-200", 5.0), ("D-300", 2.0)), "D-300", "extra"),
    ((("D-100", 10.0),), "D-200", "missing"),
    ((("D-100", 4.0), ("D-200", 5.0)), "D-100", "short"),
    ((("D-100", 40.0), ("D-200", 5.0)), "D-100", "over"),
])
def test_reconcile_variance_statuses(adv, src, tmp_path, rows, design, status):
    res = adv.ingest_advance(src)
    adv.link_to_batch(res["document_id"], _final_batch(tmp_path, rows=rows))
    r = adv.reconcile(res["document_id"])
    got = {ln["design_no"]: ln["status"] for ln in r["lines"]}
    assert got[design] == status


# ── listing ────────────────────────────────────────────────────────────────

def test_list_filters_on_linked_state(adv, src, tmp_path):
    res = adv.ingest_advance(src)
    assert [d["id"] for d in adv.list_advance_documents(linked=False)] == [res["document_id"]]
    assert adv.list_advance_documents(linked=True) == []
    adv.link_to_batch(res["document_id"], _final_batch(tmp_path))
    assert adv.list_advance_documents(linked=False) == []
    assert len(adv.list_advance_documents(linked=True)) == 1


def test_get_advance_document_rejects_a_final_document(adv, src):
    from app.services import packing_db as pdb
    pdb.upsert_packing_document(batch_id="SHIPMENT_X", invoice_no="EJL/26-27/1",
                                source_file_path="x", source_file_hash="h3",
                                document_id="DOCFIN2")
    assert adv.get_advance_document("DOCFIN2") is None


# ── regression: the shipment list is a directory scan of outputs/ ──────────

def test_shipment_list_never_sees_an_advance_batch(adv, src, tmp_path):
    """routes_dashboard.list_batches iterates storage/outputs/. An advance
    batch has no directory there, so it cannot surface as a phantom shipment."""
    res = adv.ingest_advance(src)
    _final_batch(tmp_path)
    outputs = sorted(p.name for p in (tmp_path / "outputs").iterdir())
    assert res["batch_id"] not in outputs
    assert outputs == ["SHIPMENT_1234567890_2026-08_abcdef01"]
