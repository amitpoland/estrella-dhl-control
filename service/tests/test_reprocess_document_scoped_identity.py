"""Document-scoped reprocess-prices identity resolver — pins.

Repairs the reprocess-prices flow so each parsed source-price row resolves to
exactly one stored packing row via the canonical, already-stored identity
(batch_id, packing_document_id, pack_sr := pack_sr or line_position), rejecting
0/multi matches BEFORE any financial write. Motivated by the 2026-07-11 stopped
canary on SHIPMENT_8400636576: the Global-Jewellery parser emits no pack_sr
(only a document-local line_position), so the route fell into the ambiguous
(batch, invoice, invoice_line_position, design_no) fallback — invoice 235
pack_sr 4 and 5 share (ilp=1, design=J4007P00407-1.0) but cost 372 vs 458.

These tests exercise packing_db.resolve_price_reprocess_targets /
apply_price_reprocess_targets directly. backfill_unit_price_eur (PR #890's
direct (batch,invoice,pack_sr) caller contract) is verified intact.
"""
from __future__ import annotations

import sqlite3
import uuid
from typing import Any, Dict

import pytest

from app.services import packing_db as pdb


@pytest.fixture()
def db(tmp_path):
    pdb.init_packing_db(tmp_path / "packing.db")
    return tmp_path / "packing.db"


def _doc(batch: str, fhash: str, path: str, invoice: str = "") -> str:
    return pdb.upsert_packing_document(
        batch_id=batch, invoice_no=invoice, source_file_path=path,
        source_file_hash=fhash, parser_name="t", parser_version="1",
        extraction_status="complete",
    )


def _seed_row(db_path, *, doc_id, batch, invoice, pack_sr, unit_price, upe,
              ilp=1, design="D", pcode="P") -> str:
    rid = str(uuid.uuid4()); ts = "2026-06-01T00:00:00+00:00"
    con = sqlite3.connect(str(db_path))
    con.execute(
        "INSERT INTO packing_lines (id, packing_document_id, batch_id, invoice_no, "
        "invoice_line_position, product_code, design_no, quantity, pack_sr, "
        "unit_price, total_value, unit_price_eur, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (rid, doc_id, batch, invoice, ilp, pcode, design, 1.0, pack_sr,
         unit_price, unit_price, upe, ts, ts),
    )
    con.commit(); con.close()
    return rid


def _doc_raw(db_path, batch, fhash, path) -> str:
    """Insert a packing_documents row directly (bypasses upsert's hash-dedup) so a
    genuinely multiply-registered hash can be constructed."""
    did = str(uuid.uuid4()); ts = "2026-06-01T00:00:00+00:00"
    con = sqlite3.connect(str(db_path))
    con.execute(
        "INSERT INTO packing_documents (id, batch_id, invoice_no, source_file_path, "
        "source_file_hash, parser_name, parser_version, extraction_status, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (did, batch, "", path, fhash, "t", "1", "complete", ts, ts),
    )
    con.commit(); con.close()
    return did


def _pos_file(file_name, fhash, rows):
    """rows: list of (line_position, unit_price[, pack_sr])."""
    return {"file_name": file_name, "source_file_hash": fhash,
            "rows": [{"pack_sr": (r[2] if len(r) > 2 else None),
                      "line_position": r[0], "unit_price": r[1]} for r in rows]}


def _upe(db_path, rid):
    con = sqlite3.connect(str(db_path)); con.row_factory = sqlite3.Row
    v = con.execute("SELECT unit_price_eur, updated_at, quantity, design_no, product_code "
                    "FROM packing_lines WHERE id=?", (rid,)).fetchone()
    con.close(); return v


# ── 1. line_position reconstructs the stored pack_sr ────────────────────────
def test_line_position_reconstructs_pack_sr(db):
    d = _doc("B", "hP", "/x/pl-Poland.xls")
    r = _seed_row(db, doc_id=d, batch="B", invoice="INV/1", pack_sr=3.0, unit_price=404.0, upe=0.0)
    res = pdb.resolve_price_reprocess_targets("B", [_pos_file("pl-Poland.xls", "hP", [(3, 404.0)])])
    assert not res["blocking"]
    assert [t["row_id"] for t in res["targets"]] == [r]
    assert res["targets"][0]["pack_sr"] == 3.0


# ── 3 + 9. Client .xlsx and Poland .xls stay document-separated ─────────────
def test_client_invoice_total_cannot_update_poland_serial(db):
    dP = _doc("B", "hP", "/x/236-Poland.xls")
    dC = _doc("B", "hC", "/x/236-Client.xlsx")
    poland = _seed_row(db, doc_id=dP, batch="B", invoice="INV/236", pack_sr=1.0, unit_price=675.0, upe=0.0)
    _seed_row(db, doc_id=dC, batch="B", invoice="INV/236", pack_sr=None, unit_price=0.0, upe=875.0, design="TOTAL")
    files = [_pos_file("236-Client.xlsx", "hC", [(1, 875.0)]),   # Client invoice-total, sorts first
             _pos_file("236-Poland.xls", "hP", [(1, 675.0)])]    # Poland serial (correct)
    res = pdb.resolve_price_reprocess_targets("B", files)
    assert not res["blocking"]
    assert [t["row_id"] for t in res["targets"]] == [poland]            # only the Poland serial is a target
    assert len(res["non_target"]) == 1                                  # Client row → non-target (non-serial doc)
    pdb.apply_price_reprocess_targets("B", res["targets"])
    assert _upe(db, poland)["unit_price_eur"] == 675.0                  # correct source price, NOT 875


# ── 4 + 15. Canary collision: serial 4→372, 5→458 (no fallback ambiguity) ───
def test_canary_collision_serials_map_correctly(db):
    d = _doc("B", "h235", "/x/235-Poland.xls")
    r4 = _seed_row(db, doc_id=d, batch="B", invoice="INV/235", pack_sr=4.0, unit_price=372.0, upe=0.0,
                   ilp=1, design="J4007P00407-1.0")
    r5 = _seed_row(db, doc_id=d, batch="B", invoice="INV/235", pack_sr=5.0, unit_price=458.0, upe=0.0,
                   ilp=1, design="J4007P00407-1.0")   # same ilp + design as r4 (the fallback trap)
    res = pdb.resolve_price_reprocess_targets("B", [_pos_file("235-Poland.xls", "h235", [(4, 372.0), (5, 458.0)])])
    assert not res["blocking"] and len(res["targets"]) == 2
    pdb.apply_price_reprocess_targets("B", res["targets"])
    assert _upe(db, r4)["unit_price_eur"] == 372.0
    assert _upe(db, r5)["unit_price_eur"] == 458.0


# ── 5. Thirteen source records resolve to thirteen rows ─────────────────────
def test_thirteen_records_resolve_to_thirteen_rows(db):
    d = _doc("B", "h", "/x/big-Poland.xls")
    ids = [_seed_row(db, doc_id=d, batch="B", invoice="INV/9", pack_sr=float(i), unit_price=100.0 + i, upe=0.0,
                     design=f"D-{i}") for i in range(1, 14)]
    res = pdb.resolve_price_reprocess_targets("B", [_pos_file("big-Poland.xls", "h", [(i, 100.0 + i) for i in range(1, 14)])])
    assert not res["blocking"] and len(res["targets"]) == 13
    n = pdb.apply_price_reprocess_targets("B", res["targets"])
    assert n == 13
    assert all(_upe(db, ids[i - 1])["unit_price_eur"] == 100.0 + i for i in range(1, 14))


# ── 6. Ambiguous document registration blocks with zero updates ─────────────
def test_ambiguous_document_registration_blocks(db):
    # two packing_documents share the same source_file_hash within one batch
    _doc_raw(db, "B", "dup", "/x/a.xls"); _doc_raw(db, "B", "dup", "/x/a-copy.xls")
    _seed_row(db, doc_id=_doc("B", "other", "/x/o.xls"), batch="B", invoice="INV/1", pack_sr=1.0, unit_price=10.0, upe=0.0)
    res = pdb.resolve_price_reprocess_targets("B", [_pos_file("a.xls", "dup", [(1, 50.0)])])
    assert res["blocking"] and len(res["invalid"]) == 1
    assert res["invalid"][0]["reason"] == "multiply_registered_document"
    assert len(res["targets"]) == 0


# ── 7. Duplicate stored (document, serial) blocks with zero updates ─────────
def test_duplicate_stored_serial_blocks(db):
    d = _doc("B", "h", "/x/pl.xls")
    _seed_row(db, doc_id=d, batch="B", invoice="INV/1", pack_sr=1.0, unit_price=100.0, upe=0.0, design="A")
    _seed_row(db, doc_id=d, batch="B", invoice="INV/1", pack_sr=1.0, unit_price=200.0, upe=0.0, design="B")  # same (doc,pack_sr)
    res = pdb.resolve_price_reprocess_targets("B", [_pos_file("pl.xls", "h", [(1, 100.0)])])
    assert res["blocking"] and len(res["ambiguous"]) == 1 and res["ambiguous"][0]["match_count"] == 2
    assert len(res["targets"]) == 0


# ── 8. Unknown document hash returns honest diagnostics ─────────────────────
def test_unknown_document_hash_diagnostic(db):
    _seed_row(db, doc_id=_doc("B", "known", "/x/k.xls"), batch="B", invoice="INV/1", pack_sr=1.0, unit_price=10.0, upe=0.0)
    res = pdb.resolve_price_reprocess_targets("B", [_pos_file("ghost.xls", "no-such-hash", [(1, 50.0)])])
    assert res["blocking"] and res["invalid"][0]["reason"] == "no_exact_document_hash_match"


# ── BLOCKER-1 regression: content drift (same basename, changed hash) blocks ─
def test_content_drift_same_basename_blocks(db):
    # doc registered under the ORIGINAL content hash
    d = _doc("B", "HASH_ORIGINAL", "/x/f.xls")
    r = _seed_row(db, doc_id=d, batch="B", invoice="INV/1", pack_sr=1.0, unit_price=100.0, upe=0.0)
    before = _upe(db, r)["unit_price_eur"]
    # a replaced/modified same-name file: DIFFERENT hash, matching basename.
    # It must NOT resolve via basename and must NOT write.
    res = pdb.resolve_price_reprocess_targets(
        "B", [_pos_file("f.xls", "HASH_CHANGED_content", [(1, 999.0)])])
    assert res["blocking"] and len(res["targets"]) == 0
    assert res["invalid"][0]["reason"] == "no_exact_document_hash_match"
    # even if a caller wrongly applied res["targets"], there are none → 0 writes
    assert pdb.apply_price_reprocess_targets("B", res["targets"]) == 0
    assert _upe(db, r)["unit_price_eur"] == before == 0.0        # untouched (no content-drift write)


# ── BLOCKER-2 regression: recoverable non-serial row blocks (not non_target) ─
def test_recoverable_nonserial_row_blocks(db):
    d = _doc("B", "hZ", "/x/z.xls")
    # exact document contains an UNPRICED (upe<=0) row → still recoverable
    r = _seed_row(db, doc_id=d, batch="B", invoice="INV/1", pack_sr=None, unit_price=0.0, upe=0.0, design="TOTAL")
    res = pdb.resolve_price_reprocess_targets("B", [_pos_file("z.xls", "hZ", [(1, 500.0)])])
    assert res["blocking"] and len(res["unmatched"]) == 1 and len(res["non_target"]) == 0
    assert res["unmatched"][0]["reason"] == "unresolved_positive_row_in_recoverable_document"
    assert _upe(db, r)["unit_price_eur"] == 0.0                  # nothing written


# ── Legitimate non_target: exact document is already fully priced ────────────
def test_fully_priced_document_is_non_target(db):
    d = _doc("B", "hC", "/x/client.xlsx")
    _seed_row(db, doc_id=d, batch="B", invoice="INV/1", pack_sr=None, unit_price=0.0, upe=420.0, design="TOTAL")
    res = pdb.resolve_price_reprocess_targets("B", [_pos_file("client.xlsx", "hC", [(1, 420.0)])])
    assert not res["blocking"] and len(res["non_target"]) == 1 and len(res["targets"]) == 0
    assert res["non_target"][0]["reason"] == "document_fully_priced_no_recoverable_row"


# ── One valid matched row + one unsafe unmatched row → zero total writes ─────
def test_one_valid_plus_one_unsafe_blocks_all(db):
    dP = _doc("B", "hP", "/x/poland.xls")
    good = _seed_row(db, doc_id=dP, batch="B", invoice="INV/1", pack_sr=1.0, unit_price=100.0, upe=0.0)
    dZ = _doc("B", "hZ", "/x/z.xls")
    _seed_row(db, doc_id=dZ, batch="B", invoice="INV/2", pack_sr=None, unit_price=0.0, upe=0.0)   # recoverable, non-serial
    files = [_pos_file("poland.xls", "hP", [(1, 100.0)]),
             _pos_file("z.xls", "hZ", [(1, 500.0)])]   # this one is unmatched → blocks the whole op
    res = pdb.resolve_price_reprocess_targets("B", files)
    assert res["blocking"] and len(res["targets"]) == 1 and len(res["unmatched"]) == 1
    # route contract: apply is NOT called when blocking → good row is NOT written
    assert _upe(db, good)["unit_price_eur"] == 0.0


# ── Resolver is read-only: a blocking scan writes nothing ───────────────────
def test_resolver_read_only_snapshot_unchanged_on_block(db):
    d = _doc("B", "hZ", "/x/z.xls")
    r = _seed_row(db, doc_id=d, batch="B", invoice="INV/1", pack_sr=None, unit_price=0.0, upe=0.0)
    con = sqlite3.connect(str(db))
    snap_before = con.execute("SELECT id, unit_price_eur, updated_at FROM packing_lines ORDER BY id").fetchall()
    res = pdb.resolve_price_reprocess_targets("B", [_pos_file("z.xls", "hZ", [(1, 500.0)])])
    assert res["blocking"]
    snap_after = con.execute("SELECT id, unit_price_eur, updated_at FROM packing_lines ORDER BY id").fetchall()
    con.close()
    assert snap_before == snap_after                            # resolver mutated nothing


# ── 10. Direct pack_sr callers still use #890's (batch,invoice,pack_sr) ──────
def test_direct_backfill_pack_sr_caller_preserved(db):
    d = _doc("B", "h", "/x/pl.xls")
    r = _seed_row(db, doc_id=d, batch="B", invoice="INV/1", pack_sr=7.0, unit_price=0.0, upe=0.0)
    n = pdb.backfill_unit_price_eur("B", [{"batch_id": "B", "invoice_no": "INV/1",
                                           "pack_sr": 7.0, "unit_price_eur": 2056.0}])
    assert n == 1 and _upe(db, r)["unit_price_eur"] == 2056.0


# ── 11 + 13. Non-price fields never change; zero-price rows are not targets ──
def test_only_price_and_timestamp_change(db):
    d = _doc("B", "h", "/x/pl.xls")
    r = _seed_row(db, doc_id=d, batch="B", invoice="INV/1", pack_sr=1.0, unit_price=404.0, upe=0.0,
                  design="DES-X", pcode="PCODE-X")
    before = _upe(db, r)
    res = pdb.resolve_price_reprocess_targets("B", [_pos_file("pl.xls", "h", [(1, 404.0)])])
    pdb.apply_price_reprocess_targets("B", res["targets"])
    after = _upe(db, r)
    assert after["unit_price_eur"] == 404.0
    assert after["quantity"] == before["quantity"]
    assert after["design_no"] == before["design_no"] == "DES-X"
    assert after["product_code"] == before["product_code"] == "PCODE-X"


# ── 12. Repeated reprocess is idempotent ────────────────────────────────────
def test_idempotent_repeated_reprocess(db):
    d = _doc("B", "h", "/x/pl.xls")
    r = _seed_row(db, doc_id=d, batch="B", invoice="INV/1", pack_sr=1.0, unit_price=404.0, upe=0.0)
    files = [_pos_file("pl.xls", "h", [(1, 404.0)])]
    res1 = pdb.resolve_price_reprocess_targets("B", files)
    assert pdb.apply_price_reprocess_targets("B", res1["targets"]) == 1
    res2 = pdb.resolve_price_reprocess_targets("B", files)   # now already priced
    assert not res2["blocking"] and len(res2["targets"]) == 0 and len(res2["already_priced"]) == 1
    assert pdb.apply_price_reprocess_targets("B", res2["targets"]) == 0
    assert _upe(db, r)["unit_price_eur"] == 404.0             # unchanged on 2nd run


# ── 14. Transaction rolls back on update-count mismatch ─────────────────────
def test_apply_rolls_back_on_count_mismatch(db):
    d = _doc("B", "h", "/x/pl.xls")
    r = _seed_row(db, doc_id=d, batch="B", invoice="INV/1", pack_sr=1.0, unit_price=100.0, upe=999.0)  # already priced
    # a hand-built target pointing at an already-priced row: guarded UPDATE hits 0 rows -> mismatch -> rollback
    with pytest.raises(ValueError):
        pdb.apply_price_reprocess_targets("B", [{"row_id": r, "unit_price": 100.0, "pack_sr": 1.0}])
    assert _upe(db, r)["unit_price_eur"] == 999.0             # untouched (rolled back)
