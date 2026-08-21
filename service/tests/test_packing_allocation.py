"""test_packing_allocation.py — allocation authority on packing lines (S2a).

The distinction these tests exist to defend: a supplier CAN say who a piece is
for, and that is worth recording, but it does not bind. Only an operator binds,
only against a Customer Master row, and a binding made against goods that later
changed reports itself stale rather than quietly applying to different goods.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


CUSTOMER_ID = "CM-4471"
OTHER_ID    = "CM-9902"


@pytest.fixture()
def pdb(tmp_path, monkeypatch):
    """packing_db initialised on a fresh file, with a real Customer Master
    behind it — the allocation writer consumes Customer Master for identity, so
    a stub would prove nothing about the guard that matters."""
    from app.core.config import settings
    from app.services import customer_master_db as cmdb
    from app.services import packing_db as _pdb

    monkeypatch.setattr(settings, "storage_root", tmp_path)

    cm_path = tmp_path / "customer_master.sqlite"
    cmdb.init_db(cm_path)
    for cid, name in ((CUSTOMER_ID, "Clear Diamonds BV"), (OTHER_ID, "Verhoeven NV")):
        cmdb.upsert_customer(cm_path, cmdb.CustomerMaster(
            bill_to_contractor_id=cid, bill_to_name=name, country="NL"))

    _pdb.init_packing_db(tmp_path / "packing.db")
    return _pdb


def _line(pdb, *, doc_stage="final", batch_id="SHIPMENT_ALLOC_1"):
    """One packing line under a document of the given stage. Returns its id."""
    doc_id = pdb.upsert_packing_document(
        batch_id=batch_id, invoice_no="INV-1",
        source_file_path="p.xlsx", source_file_hash="h-" + batch_id + doc_stage,
        extraction_status="ok", doc_stage=doc_stage)
    pdb.upsert_packing_lines([{
        "packing_document_id": doc_id, "batch_id": batch_id,
        "invoice_no": "INV-1", "invoice_line_position": 1,
        "design_no": "D-100", "quantity": 10, "unit_price": 25.0,
        "item_type": "RING", "metal": "14KT", "pack_sr": 1,
    }])
    rows = pdb.get_packing_lines_for_batch(batch_id)
    assert len(rows) == 1, "fixture must produce exactly one line"
    return rows[0]["id"]


def _read(pdb, line_id):
    with sqlite3.connect(str(pdb._db_path)) as con:
        con.row_factory = sqlite3.Row
        return dict(con.execute(
            "SELECT * FROM packing_lines WHERE id=?", (line_id,)).fetchone())


# ── 1. migration lands on a database that already has rows ───────────────────

def test_migration_adds_columns_to_a_preexisting_db(tmp_path, monkeypatch):
    """A production packing.db already holds rows. The migration must add the
    allocation columns to it without a backfill, leaving every existing line
    unallocated — the honest default. Nothing may be guessed onto history."""
    from app.services import packing_db as _pdb

    db = tmp_path / "packing.db"
    # The pre-allocation shape: base DDL only, exactly as it stood before S2a.
    with sqlite3.connect(str(db)) as con:
        con.executescript("""
            CREATE TABLE packing_documents (
                id TEXT PRIMARY KEY, batch_id TEXT NOT NULL,
                invoice_no TEXT NOT NULL DEFAULT '',
                source_file_path TEXT NOT NULL DEFAULT '',
                source_file_hash TEXT NOT NULL DEFAULT '',
                parser_name TEXT NOT NULL DEFAULT '',
                parser_version TEXT NOT NULL DEFAULT '',
                extraction_status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE TABLE packing_lines (
                id TEXT PRIMARY KEY, packing_document_id TEXT NOT NULL,
                batch_id TEXT NOT NULL, invoice_no TEXT NOT NULL DEFAULT '',
                invoice_line_position INTEGER DEFAULT NULL,
                product_code TEXT DEFAULT NULL,
                design_no TEXT NOT NULL DEFAULT '',
                batch_no TEXT NOT NULL DEFAULT '',
                bag_id TEXT NOT NULL DEFAULT '',
                tray_id TEXT NOT NULL DEFAULT '',
                item_type TEXT NOT NULL DEFAULT '',
                uom TEXT NOT NULL DEFAULT '',
                quantity REAL NOT NULL DEFAULT 0.0,
                gross_weight REAL NOT NULL DEFAULT 0.0,
                net_weight REAL NOT NULL DEFAULT 0.0,
                metal TEXT NOT NULL DEFAULT '',
                karat TEXT NOT NULL DEFAULT '',
                stone_type TEXT NOT NULL DEFAULT '',
                remarks TEXT NOT NULL DEFAULT '',
                extracted_confidence REAL NOT NULL DEFAULT 0.0,
                requires_manual_review INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
            INSERT INTO packing_documents VALUES
                ('doc-legacy','SHIPMENT_OLD','INV-9','','','','','ok','t','t');
            INSERT INTO packing_lines
                (id, packing_document_id, batch_id, invoice_no, design_no,
                 quantity, created_at, updated_at)
                VALUES ('line-legacy','doc-legacy','SHIPMENT_OLD','INV-9',
                        'D-OLD', 4, 't', 't');
        """)

    _pdb.init_packing_db(db)

    with sqlite3.connect(str(db)) as con:
        con.row_factory = sqlite3.Row
        cols = {r[1] for r in con.execute("PRAGMA table_info(packing_lines)")}
        row = dict(con.execute(
            "SELECT * FROM packing_lines WHERE id='line-legacy'").fetchone())

    for c in ("allocation_source", "suggested_customer_name",
              "suggested_customer_id", "allocated_customer_id",
              "allocation_confirmed_at", "allocation_confirmed_by",
              "allocation_source_revision", "allocation_strategy",
              "allocation_cleared_at", "allocation_cleared_by",
              "allocation_cleared_reason"):
        assert c in cols, f"migration did not add {c}"

    assert row["allocation_source"] == "", "an existing line is unallocated"
    assert row["allocated_customer_id"] is None, "no customer may be guessed"
    assert row["suggested_customer_name"] == ""
    assert row["allocation_source_revision"] is None
    assert row["allocation_cleared_at"] is None
    assert row["allocation_cleared_reason"] == ""
    assert row["quantity"] == 4, "the historical row is untouched"

    # Idempotent: running it again must not raise or change anything.
    _pdb.init_packing_db(db)


def test_migration_indexes_the_binding_column(pdb):
    with sqlite3.connect(str(pdb._db_path)) as con:
        idx = {r[1] for r in con.execute("PRAGMA index_list(packing_lines)")}
    assert "idx_pl_allocated_customer" in idx


# ── 2. a suggestion is not a commitment ──────────────────────────────────────

def test_suggestion_never_binds(pdb):
    lid = _line(pdb)
    out = pdb.set_allocation_suggestion(
        lid, "Clear Diamonds", CUSTOMER_ID, strategy="filename")

    assert out["allocation_source"] == "supplier_preallocated"
    row = _read(pdb, lid)
    assert row["allocated_customer_id"] is None, \
        "a supplier claim must never become a binding"
    assert row["suggested_customer_id"] == CUSTOMER_ID
    assert row["suggested_customer_name"] == "Clear Diamonds"
    assert row["allocation_strategy"] == "filename"
    assert row["allocation_confirmed_at"] is None
    assert row["allocation_confirmed_by"] == ""


def test_an_unresolvable_supplier_name_is_still_recorded(pdb):
    """The raw text is the reason a human should look. Dropping it because it
    did not resolve throws away the only evidence there is."""
    lid = _line(pdb)
    pdb.set_allocation_suggestion(lid, "Clear Diamonds (Amsterdam?)", None,
                                  strategy="filename")
    row = _read(pdb, lid)
    assert row["suggested_customer_name"] == "Clear Diamonds (Amsterdam?)"
    assert row["suggested_customer_id"] is None
    assert row["allocated_customer_id"] is None


def test_a_suggested_id_that_is_not_a_customer_is_refused(pdb):
    """A stored id reads as resolved. Storing an unknown one would lie."""
    lid = _line(pdb)
    with pytest.raises(ValueError, match="not a Customer Master"):
        pdb.set_allocation_suggestion(lid, "Ghost Ltd", "CM-NOPE")


# ── 3. binding requires a real customer ──────────────────────────────────────

def test_confirm_with_unknown_customer_id_raises(pdb):
    lid = _line(pdb)
    with pytest.raises(ValueError, match="not a Customer Master"):
        pdb.confirm_allocation(lid, "CM-0000", operator="jigar")
    assert _read(pdb, lid)["allocated_customer_id"] is None


def test_confirm_with_free_text_raises(pdb):
    """Allocation binds to Customer Master, never to a typed name — otherwise
    the binding cannot be resolved back to a customer later."""
    lid = _line(pdb)
    with pytest.raises(ValueError, match="not a Customer Master"):
        pdb.confirm_allocation(lid, "Clear Diamonds BV", operator="jigar")
    assert _read(pdb, lid)["allocated_customer_id"] is None


def test_confirm_binds_and_snapshots_the_revision(pdb):
    lid = _line(pdb)
    out = pdb.confirm_allocation(lid, CUSTOMER_ID, operator="jigar")

    row = _read(pdb, lid)
    assert row["allocated_customer_id"] == CUSTOMER_ID
    assert row["allocation_source"] == "operator_allocated"
    assert row["allocation_confirmed_by"] == "jigar"
    assert row["allocation_confirmed_at"]
    assert row["allocation_source_revision"] == pdb.compute_source_revision(row)
    assert out["allocation_source_revision"] == row["allocation_source_revision"]


def test_confirm_requires_an_operator(pdb):
    lid = _line(pdb)
    with pytest.raises(ValueError, match="required"):
        pdb.confirm_allocation(lid, CUSTOMER_ID, operator="")


# ── 4. a later suggestion cannot undo an operator's decision ─────────────────

def test_confirm_then_suggestion_does_not_overwrite_the_binding(pdb):
    """A re-import re-runs suggestions. It must not silently move goods an
    operator already committed to somebody else."""
    lid = _line(pdb)
    pdb.confirm_allocation(lid, CUSTOMER_ID, operator="jigar")

    out = pdb.set_allocation_suggestion(lid, "Verhoeven", OTHER_ID,
                                        strategy="client_column")

    row = _read(pdb, lid)
    assert row["allocated_customer_id"] == CUSTOMER_ID, "binding survives"
    assert row["allocation_source"] == "operator_allocated"
    assert row["allocation_confirmed_by"] == "jigar"
    assert out["bound"] is True
    # the competing suggestion is still recorded, next to the binding
    assert row["suggested_customer_id"] == OTHER_ID
    assert row["suggested_customer_name"] == "Verhoeven"


# ── 5. clearing is a repair, and repairs are accounted for ───────────────────

def test_clear_without_reason_raises(pdb):
    lid = _line(pdb)
    pdb.confirm_allocation(lid, CUSTOMER_ID, operator="jigar")
    with pytest.raises(ValueError, match="reason is required"):
        pdb.clear_allocation(lid, operator="jigar", reason="   ")
    assert _read(pdb, lid)["allocated_customer_id"] == CUSTOMER_ID


def test_clear_returns_the_line_to_stock_and_keeps_the_suggestion(pdb):
    lid = _line(pdb)
    pdb.set_allocation_suggestion(lid, "Clear Diamonds", CUSTOMER_ID,
                                  strategy="filename")
    pdb.confirm_allocation(lid, CUSTOMER_ID, operator="jigar")

    out = pdb.clear_allocation(lid, operator="amit", reason="customer cancelled")

    row = _read(pdb, lid)
    assert row["allocated_customer_id"] is None, "back to stock"
    assert row["allocation_source"] == "supplier_preallocated", \
        "the supplier's proposal is still standing — only the binding went"
    assert row["suggested_customer_id"] == CUSTOMER_ID
    assert row["suggested_customer_name"] == "Clear Diamonds"
    assert row["allocation_strategy"] == "filename"
    assert row["allocation_source_revision"] is None
    assert out["allocation_source"] == "supplier_preallocated"
    assert out["cleared_at"] == row["allocation_cleared_at"]


def test_clearing_records_who_why_and_when_in_its_own_columns(pdb):
    lid = _line(pdb)
    pdb.confirm_allocation(lid, CUSTOMER_ID, operator="jigar")
    pdb.clear_allocation(lid, operator="amit", reason="customer cancelled")

    row = _read(pdb, lid)
    assert row["allocation_cleared_reason"] == "customer cancelled"
    assert row["allocation_cleared_by"] == "amit"
    assert row["allocation_cleared_at"], "when it was undone is part of the account"


def test_clearing_never_writes_remarks(pdb):
    """``remarks`` describes the GOODS and reaches documents: routes_dhl_clearance
    reads it as the stone_type fallback on customs rows, and
    _build_matched_sales_lines copies it into sales_packing_lines where
    customer_incoterm_authority scans it for Incoterms. An allocation note in
    there becomes a stone type on a customs declaration."""
    lid = _line(pdb)
    before = _read(pdb, lid)["remarks"]
    pdb.confirm_allocation(lid, CUSTOMER_ID, operator="jigar")
    pdb.clear_allocation(lid, operator="amit",
                         reason="DIAMOND — cancelled, INCOTERM DAP")

    row = _read(pdb, lid)
    assert row["remarks"] == before, "the goods description must be untouched"
    assert "cancelled" not in (row["remarks"] or "")
    assert row["allocation_cleared_reason"] == "DIAMOND — cancelled, INCOTERM DAP"


def test_clearing_preserves_who_made_the_binding(pdb):
    """The pair reads as history: jigar committed the goods, amit undid it.
    Blanking confirmed_* would leave only the record of who undid it."""
    lid = _line(pdb)
    pdb.confirm_allocation(lid, CUSTOMER_ID, operator="jigar")
    confirmed_at = _read(pdb, lid)["allocation_confirmed_at"]

    pdb.clear_allocation(lid, operator="amit", reason="customer cancelled")

    row = _read(pdb, lid)
    assert row["allocation_confirmed_by"] == "jigar"
    assert row["allocation_confirmed_at"] == confirmed_at
    assert row["allocation_cleared_by"] == "amit"


def test_clearing_a_line_with_no_suggestion_returns_it_to_plain_stock(pdb):
    lid = _line(pdb)
    pdb.confirm_allocation(lid, CUSTOMER_ID, operator="jigar")
    pdb.clear_allocation(lid, operator="amit", reason="allocated in error")
    assert _read(pdb, lid)["allocation_source"] == ""


def test_confirm_after_clear_supersedes_the_clear(pdb):
    """A line that is allocated right now must not also read as an allocation
    somebody undid."""
    lid = _line(pdb)
    pdb.confirm_allocation(lid, CUSTOMER_ID, operator="jigar")
    pdb.clear_allocation(lid, operator="amit", reason="customer cancelled")
    assert _read(pdb, lid)["allocation_cleared_by"] == "amit"

    pdb.confirm_allocation(lid, OTHER_ID, operator="priya")

    row = _read(pdb, lid)
    assert row["allocated_customer_id"] == OTHER_ID
    assert row["allocation_source"] == "operator_allocated"
    assert row["allocation_confirmed_by"] == "priya", "the new binding's author"
    assert row["allocation_cleared_at"] is None
    assert row["allocation_cleared_by"] == ""
    assert row["allocation_cleared_reason"] == ""


# ── 6. a binding made against different goods reports itself ─────────────────

def test_stale_detection_flips_when_the_line_changes(pdb):
    lid = _line(pdb)
    pdb.confirm_allocation(lid, CUSTOMER_ID, operator="jigar")
    assert pdb.allocation_is_stale(_read(pdb, lid)) is False

    # a re-import materially changes the source: 10 pieces became 6
    with sqlite3.connect(str(pdb._db_path)) as con:
        con.execute("UPDATE packing_lines SET quantity=6 WHERE id=?", (lid,))

    assert pdb.allocation_is_stale(_read(pdb, lid)) is True, \
        "a binding made against 10 pieces must not silently cover 6"


def test_an_unbound_line_is_never_stale(pdb):
    """Calling an unallocated line stale would send an operator looking for a
    decision nobody made."""
    lid = _line(pdb)
    assert pdb.allocation_is_stale(_read(pdb, lid)) is False
    pdb.set_allocation_suggestion(lid, "Clear Diamonds", CUSTOMER_ID)
    assert pdb.allocation_is_stale(_read(pdb, lid)) is False


def test_reconfirming_clears_the_stale_flag(pdb):
    lid = _line(pdb)
    pdb.confirm_allocation(lid, CUSTOMER_ID, operator="jigar")
    with sqlite3.connect(str(pdb._db_path)) as con:
        con.execute("UPDATE packing_lines SET quantity=6 WHERE id=?", (lid,))
    assert pdb.allocation_is_stale(_read(pdb, lid)) is True

    pdb.confirm_allocation(lid, CUSTOMER_ID, operator="jigar")
    assert pdb.allocation_is_stale(_read(pdb, lid)) is False


# ── 7. provisional goods cannot be committed ─────────────────────────────────

def test_an_advance_line_accepts_a_suggestion(pdb):
    """The supplier announcing who a piece is for is exactly the information an
    advance list carries. Recording it is the point."""
    lid = _line(pdb, doc_stage="advance", batch_id="ADVANCE_ALLOC_1")
    pdb.set_allocation_suggestion(lid, "Clear Diamonds", CUSTOMER_ID,
                                  strategy="filename")
    row = _read(pdb, lid)
    assert row["suggested_customer_id"] == CUSTOMER_ID
    assert row["allocation_source"] == "supplier_preallocated"


def test_an_advance_line_cannot_be_confirmed(pdb):
    """An advance line describes goods that do not exist yet and carries no
    product identity. Binding one would be a promise about nothing."""
    lid = _line(pdb, doc_stage="advance", batch_id="ADVANCE_ALLOC_2")
    with pytest.raises(ValueError, match="advance packing line cannot be allocated"):
        pdb.confirm_allocation(lid, CUSTOMER_ID, operator="jigar")
    assert _read(pdb, lid)["allocated_customer_id"] is None


# ── the writer is the only writer ────────────────────────────────────────────

def test_no_module_outside_packing_db_writes_the_allocation_columns():
    """Single-writer authority, pinned in source. A second writer is how a
    binding starts disagreeing with itself."""
    import re

    app_dir = _ROOT / "app"
    owned = re.compile(
        r"(allocated_customer_id|allocation_source|allocation_confirmed_|"
        r"allocation_cleared_|suggested_customer_|allocation_strategy)\s*=")
    offenders = []
    for py in app_dir.rglob("*.py"):
        if py.name == "packing_db.py":
            continue
        text = py.read_text(encoding="utf-8", errors="ignore")
        for n, line in enumerate(text.splitlines(), 1):
            if owned.search(line):
                offenders.append(f"{py.relative_to(_ROOT)}:{n}")
    assert offenders == [], f"allocation columns written outside packing_db: {offenders}"


def test_line_id_must_exist(pdb):
    with pytest.raises(ValueError, match="no packing line"):
        pdb.confirm_allocation("no-such-line", CUSTOMER_ID, operator="jigar")
