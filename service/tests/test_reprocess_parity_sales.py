"""test_reprocess_parity_sales.py — reprocess-parity fixes for the sales lane.

Pins the fixes shipped in the sales reprocess parity PR:

  Gap #1  get_sales_packing_lines(physical_only=True) returns one row per
          physical item, scoped PER sales_document: a document with canonical
          'packing_xlsx_value' rows is de-duped to those; a document parsed
          without that pass (only 'excel_symbol'/'' rows) keeps all of its rows.
          A mixed batch must neither under-count the parsed documents nor
          double-count the promoted ones.

  Gap #2  the reprocess sales branch flips shipment_documents.extraction_status
          to 'extracted' — but only when at least one line has real content
          (product_code or design_no).

  Gap #3  the reprocess sales path keys sales_packing_lines.sales_document_id to
          the sales packing list's shipment_documents.id (doc_id), and
          ensure_sales_document_id guarantees a sales_documents row whose
          PRIMARY KEY id == doc_id. wfirma_reservation and the v_sales_to_wfirma
          view join lines on sales_documents.id, so this invariant
          (every sales_packing_lines.sales_document_id is a real
          sales_documents.id) is what keeps those readers non-empty.

Gap #4 (proforma draft sync) was already present in reprocess — not retested here.

Run: python -m pytest tests/test_reprocess_parity_sales.py -q
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.services import document_db as ddb


@pytest.fixture()
def docdb(tmp_path):
    ddb.init_document_db(tmp_path / "documents.db")
    return tmp_path


def _row(pc, dn, price, src, cur="EUR"):
    return {
        "client_name": "C", "client_ref": "", "product_code": pc, "design_no": dn,
        "bag_id": "", "quantity": 1.0, "remarks": "",
        "unit_price": price, "total_value": price, "currency": cur, "price_source": src,
    }


# ── Gap #1 — physical_only one-row-per-item, scoped per sales_document ───────

def test_physical_only_returns_reparse_rows_when_no_canonical(docdb):
    """A document parsed without an import/promote pass (only excel_symbol/''
    rows) must be fully surfaced by physical_only, not return []."""
    B = "BATCH_REPARSE_ONLY"
    ddb.store_sales_packing_lines("sd1", B, [
        _row("P1", "D1", 10.0, "excel_symbol"),
        _row("P2", "D2", 20.0, ""),
    ])
    phys = ddb.get_sales_packing_lines(B, physical_only=True)
    assert len(phys) == 2, "reparse rows must be visible to physical_only (Gap #1)"


def test_physical_only_dedups_when_both_row_types_exist(docdb):
    """A document with BOTH packing_xlsx_value + excel_symbol for one item must
    return ONE canonical row per item — no double-count."""
    B = "BATCH_DUAL"
    ddb.store_sales_packing_lines("sd1", B, [
        _row("P1", "D1", 10.0, "packing_xlsx_value", cur="USD"),
        _row("P1", "D1", 15.0, "excel_symbol"),
    ])
    phys = ddb.get_sales_packing_lines(B, physical_only=True)
    assert len(phys) == 1, "physical_only must de-dup to the canonical row"
    assert phys[0]["price_source"] == "packing_xlsx_value"
    allrows = ddb.get_sales_packing_lines(B, physical_only=False)
    assert len(allrows) == 2, "non-physical must return all authority rows"


def test_physical_only_mixed_documents_no_undercount(docdb):
    """Mixed batch: doc sdA promoted (canonical rows), doc sdB parsed
    (excel-only). physical_only must return sdA's canonical rows AND all of
    sdB's rows — never drop the parsed document because another document has
    canonical rows."""
    B = "BATCH_MIXED"
    # Promoted document: canonical + a redundant excel row for the SAME item.
    ddb.store_sales_packing_lines("sdA", B, [
        _row("PA", "DA", 11.0, "packing_xlsx_value", cur="USD"),
        _row("PA", "DA", 19.0, "excel_symbol"),
    ])
    # Parsed (reprocess) document: excel/'' only, two distinct items.
    ddb.store_sales_packing_lines("sdB", B, [
        _row("PB1", "DB1", 21.0, "excel_symbol"),
        _row("PB2", "DB2", 22.0, ""),
    ])
    phys = ddb.get_sales_packing_lines(B, physical_only=True)
    by_doc = {}
    for r in phys:
        by_doc.setdefault(r["sales_document_id"], []).append(r)
    # sdA de-duped to its 1 canonical row; sdB keeps both parsed rows.
    assert len(by_doc.get("sdA", [])) == 1, "promoted doc must de-dup to canonical"
    assert by_doc["sdA"][0]["price_source"] == "packing_xlsx_value"
    assert len(by_doc.get("sdB", [])) == 2, "parsed doc must NOT be under-counted"
    assert len(phys) == 3


# ── Gap #2 — status flip gated on real content ──────────────────────────────

def test_update_document_status_flips_extraction_status(docdb):
    """Mechanism: update_document_status flips shipment_documents off 'pending'."""
    B = "BATCH_STATUS"
    doc_id = ddb.register_document(
        batch_id=B, document_type="sales_packing_list",
        file_name="s.xlsx", awb="X9", source="intake",
    )
    assert doc_id
    ddb.update_document_status(doc_id, extraction_status="extracted", parser_status="complete")
    rows = ddb.get_documents_for_batch(B, document_type="sales_packing_list")
    assert rows and rows[0]["extraction_status"] == "extracted"
    assert rows[0]["parser_status"] == "complete"


def test_reprocess_sales_branch_gates_status_on_content():
    """Call-site: the reprocess handler flips status only behind a content gate
    (product_code/design_no), and uses the FK-correct ensure_sales_document_id."""
    src = (Path(__file__).resolve().parents[1] / "app" / "api" / "routes_packing.py").read_text(encoding="utf-8")
    assert "update_document_status(" in src, "reprocess must call update_document_status"
    assert 'extraction_status="extracted"' in src
    assert "_has_content" in src and "if _has_content:" in src, "status flip must be content-gated"
    assert "ensure_sales_document_id(" in src, "reprocess must use the FK-correct helper"


# ── Gap #3 — FK invariant the id-joining readers depend on ──────────────────

def test_ensure_sales_document_id_is_idempotent_and_id_equals_doc(docdb):
    """ensure_sales_document_id returns doc_id and creates exactly one
    sales_documents row whose primary-key id == doc_id; repeat calls reuse it."""
    B = "BATCH_FK"
    doc_id = "shipdoc-aaa"
    a = ddb.ensure_sales_document_id(B, doc_id, document_type="sales_packing_list")
    b = ddb.ensure_sales_document_id(B, doc_id, client_name="ACME")
    assert a == doc_id and b == doc_id
    sds = [d for d in ddb.get_sales_documents(B) if d["id"] == doc_id]
    assert len(sds) == 1, "exactly one canonical sales_documents row with id==doc_id"
    assert sds[0]["client_name"] == "ACME", "client_name updated in place on repeat"


def test_reprocess_fk_invariant_for_id_joining_readers(docdb):
    """Simulate the reprocess write (ensure_sales_document_id then store lines
    keyed to doc_id) and assert every sales_packing_lines.sales_document_id is a
    real sales_documents.id — the invariant wfirma_reservation /
    v_sales_to_wfirma join on. Pre-fix, lines were orphaned under a UUID-less
    shipment-doc id."""
    B = "BATCH_FK2"
    doc_id = "shipdoc-bbb"
    sales_doc_id = ddb.ensure_sales_document_id(B, doc_id, document_type="sales_packing_list")
    assert sales_doc_id == doc_id
    ddb.store_sales_packing_lines(sales_doc_id, B, [
        _row("P1", "D1", 10.0, "excel_symbol"),
        _row("P2", "D2", 20.0, "excel_symbol"),
    ])
    sd_ids = {d["id"] for d in ddb.get_sales_documents(B)}
    spls = ddb.get_sales_packing_lines(B)
    assert spls, "lines must be persisted"
    for r in spls:
        assert r["sales_document_id"] in sd_ids, (
            "every line FK must resolve to a real sales_documents.id "
            "(wfirma_reservation / v_sales_to_wfirma join target)"
        )
    # Simulate wfirma_reservation's lookup: spl_by_doc keyed by sales_document_id,
    # looked up by sales_documents.id — must be non-empty for the doc.
    spl_by_doc = {}
    for r in spls:
        spl_by_doc.setdefault(r["sales_document_id"], []).append(r)
    assert spl_by_doc.get(doc_id), "id-join lookup must find the document's lines"


def test_reprocess_twice_converges_to_one_canonical_row(docdb):
    """Re-reprocess (ensure + replace lines, twice) converges: exactly one
    canonical sales_documents row (id==doc_id), lines re-written under it, and
    the FK invariant still holds. Guards the idempotency / concurrent-INSERT
    hardening (INSERT OR IGNORE)."""
    B = "BATCH_TWICE"
    doc_id = "shipdoc-eee"
    for _ in range(2):
        sales_doc_id = ddb.ensure_sales_document_id(B, doc_id, document_type="sales_packing_list")
        assert sales_doc_id == doc_id
        ddb.replace_sales_packing_lines(sales_doc_id, B, [
            _row("P1", "D1", 10.0, "excel_symbol"),
            _row("P2", "D2", 20.0, "excel_symbol"),
        ])
    canon = [d for d in ddb.get_sales_documents(B) if d["id"] == doc_id]
    assert len(canon) == 1, "re-reprocess must converge to one canonical row"
    spls = ddb.get_sales_packing_lines(B)
    assert len(spls) == 2, "replace (not append) on the second run"
    sd_ids = {d["id"] for d in ddb.get_sales_documents(B)}
    assert all(r["sales_document_id"] in sd_ids for r in spls), "FK invariant holds after re-reprocess"


def test_ensure_sales_document_id_purges_lineless_phantom(docdb):
    """A pre-fix phantom (random-UUID id, same document_id, no lines) is removed
    once the canonical id==doc_id row is ensured; a phantom that owns lines is
    NEVER deleted."""
    B = "BATCH_PHANTOM"
    doc_id = "shipdoc-ccc"
    # Pre-fix behaviour: store_sales_document mints a random-UUID id row.
    phantom_id = ddb.store_sales_document(
        batch_id=B, document_id=doc_id,
        data={"document_type": "sales_packing_list", "extraction_status": "pending"},
    )
    assert phantom_id and phantom_id != doc_id
    # Ensure the canonical row → phantom (line-less) must be purged.
    ddb.ensure_sales_document_id(B, doc_id, document_type="sales_packing_list")
    ids = {d["id"] for d in ddb.get_sales_documents(B)}
    assert doc_id in ids, "canonical id==doc_id row must exist"
    assert phantom_id not in ids, "line-less phantom must be purged"


def test_ensure_sales_document_id_keeps_phantom_that_owns_lines(docdb):
    """Safety: a sibling sales_documents row that actually owns lines is NOT
    deleted by the phantom cleanup."""
    B = "BATCH_PHANTOM_SAFE"
    doc_id = "shipdoc-ddd"
    other_id = ddb.store_sales_document(
        batch_id=B, document_id=doc_id,
        data={"document_type": "sales_packing_list"},
    )
    # Give the sibling real lines so it must be preserved.
    ddb.store_sales_packing_lines(other_id, B, [_row("PX", "DX", 5.0, "excel_symbol")])
    ddb.ensure_sales_document_id(B, doc_id, document_type="sales_packing_list")
    ids = {d["id"] for d in ddb.get_sales_documents(B)}
    assert doc_id in ids
    assert other_id in ids, "a sibling that owns lines must never be purged"
