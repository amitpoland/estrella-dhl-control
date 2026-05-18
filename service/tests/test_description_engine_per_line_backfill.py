"""test_description_engine_per_line_backfill.py

Tests for the PR that ensures ``product_descriptions`` rows are generated
from EACH invoice line's own description text — never from the overall
invoice header description.  Models the operator-reported bug on
invoice EJL/26-27/149 where four distinct line products (plain RING,
diamond-stud PENDANT, diamond-stud 14KT RING, diamond-stud 18KT RING)
must produce four distinct Polish names.

The function under test is
:func:`app.services.description_engine.regenerate_descriptions_for_invoice_lines`.

Read-only on its own side-paths: no wFirma / PZ / DHL / proforma post
calls.  Only ``invoice_lines`` (read), ``product_master`` (read),
``product_descriptions`` (read + dry-run-default write) are touched.
"""
from __future__ import annotations

import sqlite3 as _s
import uuid as _u
from datetime import datetime as _dt, timezone as _tz
from pathlib import Path

import pytest


@pytest.fixture()
def fresh(tmp_path, monkeypatch):
    """Per-test storage root with documents.db + reservation_queue.db
    initialised.  Replicates the module-level _db_path binding pattern
    used elsewhere in the suite.

    The module-level _db_path inside document_db is saved on entry and
    restored on exit so other test suites that don't initialise their
    own document_db (e.g. test_proforma_draft_editor_contract) are not
    polluted with a stale tmp path."""
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    monkeypatch.setenv("PZ_STORAGE_ROOT", str(tmp_path))
    from app.core.config import settings
    monkeypatch.setattr(settings, "storage_root", tmp_path, raising=False)
    from app.services import document_db as ddb
    _saved_doc_path = ddb._db_path
    ddb.init_document_db(tmp_path / "documents.db")
    from app.services import reservation_db as rdb
    rdb.init_reservation_db(tmp_path / "reservation_queue.db")
    try:
        yield tmp_path
    finally:
        ddb._db_path = _saved_doc_path


def _seed_invoice_line(tmp: Path, *, batch_id: str, invoice_no: str,
                       position: int, product_code: str,
                       description: str) -> None:
    """Insert one invoice_lines row directly — bypasses parser code so
    tests don't depend on document intake machinery."""
    now = _dt.now(_tz.utc).isoformat()
    with _s.connect(str(tmp / "documents.db")) as con:
        con.execute(
            "INSERT INTO invoice_lines "
            "(id, document_id, batch_id, invoice_no, line_position, "
            " product_code, description, quantity, unit_price, "
            " total_value, currency, hs_code, gross_weight, net_weight, "
            " rate_usd, amount_usd, hsn_code, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                str(_u.uuid4()), "doc-test-" + invoice_no, batch_id,
                invoice_no, position, product_code, description,
                1.0, 100.0, 100.0, "USD", "", 0.0, 0.0,
                0.0, 0.0, "", now,
            ),
        )
        con.commit()


def _seed_invoice_149(tmp: Path) -> None:
    """Reproduces the four EJL/26-27/149 invoice lines exactly as parsed
    by the production extractor: per-line, not header-aggregated."""
    rows = (
        ("EJL/26-27/149-1", 1, "PCS, 18KT Gold,Plain Jewellery RING"),
        ("EJL/26-27/149-2", 2, "PCS, 18KT Gold,Stud With Diam Jewellery PENDANT"),
        ("EJL/26-27/149-3", 3, "PCS, 14KT Gold,Stud With Diam Jewellery RING"),
        ("EJL/26-27/149-4", 4, "PCS, 18KT Gold,Stud With Diam Jewellery RING"),
    )
    for pc, pos, desc in rows:
        _seed_invoice_line(
            tmp,
            batch_id     = "SHIPMENT_TEST_149",
            invoice_no   = "EJL/26-27/149",
            position     = pos,
            product_code = pc,
            description  = desc,
        )


def _get_pd(pc: str) -> dict:
    from app.services import document_db as ddb
    row = ddb.get_product_description(pc) or {}
    return dict(row)


# ── 1. dry-run plan: 4 distinct lines, 4 would_write ───────────────────

def test_dry_run_plans_one_write_per_invoice_line(fresh):
    _seed_invoice_149(fresh)
    from app.services import description_engine as de
    res = de.regenerate_descriptions_for_invoice_lines(
        batch_id="SHIPMENT_TEST_149",
        dry_run=True,
    )
    assert res["dry_run"] is True
    assert res["scanned"] == 4
    assert res["would_write"] == 4
    assert res["written"] == 0
    assert res["skipped_existing"] == 0
    assert res["skipped_manual"] == 0
    assert res["skipped_blank"] == 0
    assert res["errors"] == []
    # No row should have been created — dry-run is read-only.
    from app.services import document_db as ddb
    for pc in ("EJL/26-27/149-1", "EJL/26-27/149-2",
               "EJL/26-27/149-3", "EJL/26-27/149-4"):
        assert ddb.get_product_description(pc) is None


# ── 2. write mode: each line gets its OWN Polish row ───────────────────

def test_write_mode_produces_per_line_polish_rows(fresh):
    _seed_invoice_149(fresh)
    from app.services import description_engine as de
    res = de.regenerate_descriptions_for_invoice_lines(
        batch_id="SHIPMENT_TEST_149",
        dry_run=False,
    )
    assert res["written"] == 4
    assert res["errors"] == [], f"unexpected errors: {res['errors']!r}"
    rows = {pc: _get_pd(pc) for pc in (
        "EJL/26-27/149-1", "EJL/26-27/149-2",
        "EJL/26-27/149-3", "EJL/26-27/149-4",
    )}
    for pc, r in rows.items():
        assert r, f"missing product_descriptions row for {pc}"
        assert r.get("source") == "auto", (
            f"row for {pc} must be source='auto', got {r.get('source')!r}"
        )
        assert (r.get("name_pl") or "").strip(), (
            f"row for {pc} has blank name_pl"
        )


def test_149_1_ring_plain_produces_ring_polish(fresh):
    _seed_invoice_149(fresh)
    from app.services import description_engine as de
    de.regenerate_descriptions_for_invoice_lines(
        batch_id="SHIPMENT_TEST_149", dry_run=False,
    )
    r = _get_pd("EJL/26-27/149-1")
    assert r["item_type"] == "RING", r
    name = (r.get("name_pl") or "")
    # Polish word for "ring" must appear; no "diamond" / "wysadzany" /
    # "PENDANT" leakage from a different line.
    assert "pierścion" in name.lower(), name
    assert "wisior"   not in name.lower(), \
        f"plain ring must not carry pendant text: {name!r}"


def test_149_2_pendant_stud_produces_pendant_polish(fresh):
    _seed_invoice_149(fresh)
    from app.services import description_engine as de
    de.regenerate_descriptions_for_invoice_lines(
        batch_id="SHIPMENT_TEST_149", dry_run=False,
    )
    r = _get_pd("EJL/26-27/149-2")
    assert r["item_type"] == "PENDANT", r
    name = (r.get("name_pl") or "").lower()
    assert "wisior" in name, name
    assert "pierścion" not in name, (
        f"pendant must not carry ring text: {name!r}"
    )


def test_149_3_and_149_4_are_distinct_rows(fresh):
    """149-3 is a 14KT diamond-stud RING; 149-4 is an 18KT diamond-stud
    RING.  They must have SEPARATE product_descriptions rows — never
    collapsed onto a single header-derived row."""
    _seed_invoice_149(fresh)
    from app.services import description_engine as de
    de.regenerate_descriptions_for_invoice_lines(
        batch_id="SHIPMENT_TEST_149", dry_run=False,
    )
    r3 = _get_pd("EJL/26-27/149-3")
    r4 = _get_pd("EJL/26-27/149-4")
    assert r3 and r4
    assert r3["item_type"] == "RING"
    assert r4["item_type"] == "RING"
    # Both are persisted rows keyed by product_code — independent IDs.
    assert (r3.get("product_code") or "") == "EJL/26-27/149-3"
    assert (r4.get("product_code") or "") == "EJL/26-27/149-4"


# ── 3. header-text rule: header description NEVER feeds line rows ──────

def test_header_description_not_used_when_invoice_lines_have_per_line_text(fresh):
    """Even if the overall invoice header text would be technically
    available elsewhere (e.g. customs declarations), the generator must
    only consume invoice_lines.description for the matching
    product_code.  We assert this by checking that the four 149 Polish
    rows differ between PENDANT and RING — which only happens if each
    line's own description was used."""
    _seed_invoice_149(fresh)
    from app.services import description_engine as de
    de.regenerate_descriptions_for_invoice_lines(
        batch_id="SHIPMENT_TEST_149", dry_run=False,
    )
    rows = {pc: _get_pd(pc) for pc in (
        "EJL/26-27/149-1", "EJL/26-27/149-2",
        "EJL/26-27/149-3", "EJL/26-27/149-4",
    )}
    # The pendant row (149-2) must differ from the ring rows on
    # item_type — proves the generator branched per line, not by a
    # single header.
    pendants = [r for pc, r in rows.items() if r.get("item_type") == "PENDANT"]
    rings    = [r for pc, r in rows.items() if r.get("item_type") == "RING"]
    assert len(pendants) == 1
    assert len(rings)    == 3
    pendant_name = (pendants[0].get("name_pl") or "").lower()
    for ring_row in rings:
        ring_name = (ring_row.get("name_pl") or "").lower()
        assert pendant_name != ring_name, (
            f"pendant name {pendant_name!r} must not match any ring name "
            f"{ring_name!r} — header-vs-line bug"
        )


# ── 4. manual rows preserved ───────────────────────────────────────────

def test_manual_row_is_preserved_and_counted(fresh):
    _seed_invoice_149(fresh)
    from app.services import description_engine as de
    # Operator pre-writes a manual override for 149-1.
    de.set_manual_block(
        product_code   = "EJL/26-27/149-1",
        item_type      = "RING",
        name_pl        = "OPERATOR_MANUAL_NAME",
        description_pl = "OPERATOR_MANUAL_DESCRIPTION",
        material_pl    = "operator_material",
        purpose_pl     = "operator_purpose",
        description_en = "Operator manual",
    )
    res = de.regenerate_descriptions_for_invoice_lines(
        batch_id="SHIPMENT_TEST_149", dry_run=False,
    )
    assert res["skipped_manual"] >= 1
    # The manual row must not be touched.
    r = _get_pd("EJL/26-27/149-1")
    assert r["source"]  == "manual"
    assert r["name_pl"] == "OPERATOR_MANUAL_NAME"
    # The other three lines are still written.
    assert res["written"] >= 3


# ── 5. scoping: product_code overrides batch_id ────────────────────────

def test_product_code_filter_isolates_one_row(fresh):
    _seed_invoice_149(fresh)
    from app.services import description_engine as de
    res = de.regenerate_descriptions_for_invoice_lines(
        product_code="EJL/26-27/149-3", dry_run=False,
    )
    assert res["scanned"] == 1
    assert res["written"] == 1
    # Only 149-3 was written; the other three lines were not touched.
    from app.services import document_db as ddb
    assert ddb.get_product_description("EJL/26-27/149-3") is not None
    for pc in ("EJL/26-27/149-1", "EJL/26-27/149-2", "EJL/26-27/149-4"):
        assert ddb.get_product_description(pc) is None


def test_batch_filter_isolates_a_batch(fresh):
    _seed_invoice_149(fresh)
    # Add a different batch with one line — must not be touched when
    # we filter by the 149 batch.
    _seed_invoice_line(
        fresh,
        batch_id     = "SHIPMENT_TEST_OTHER",
        invoice_no   = "EJL/26-27/999",
        position     = 1,
        product_code = "EJL/26-27/999-1",
        description  = "PCS, 18KT Gold, Plain Jewellery RING",
    )
    from app.services import description_engine as de
    res = de.regenerate_descriptions_for_invoice_lines(
        batch_id="SHIPMENT_TEST_149", dry_run=False,
    )
    assert res["scanned"] == 4
    from app.services import document_db as ddb
    assert ddb.get_product_description("EJL/26-27/999-1") is None


# ── 6. product_master fallback ─────────────────────────────────────────

def test_product_master_description_is_used_when_invoice_line_blank(fresh):
    """If an invoice_lines row exists with a blank description but
    product_master has a per-line description for the same code, the
    generator must use product_master.description (not give up)."""
    # Seed an invoice_lines row with blank description.
    _seed_invoice_line(
        fresh,
        batch_id     = "SHIPMENT_PM_FB",
        invoice_no   = "EJL/26-27/PMFB",
        position     = 1,
        product_code = "EJL/26-27/PMFB-1",
        description  = "",
    )
    # Seed product_master with a usable English description.
    from app.services import reservation_db as rdb
    rdb.upsert_product_master(
        fresh / "reservation_queue.db",
        product_code = "EJL/26-27/PMFB-1",
        design_no    = "DPM-1",
        description  = "PCS, 14KT Gold, Stud With Diam Jewellery RING",
        item_type    = "RING",
        source_batch_id = "SHIPMENT_PM_FB",
    )
    from app.services import description_engine as de
    res = de.regenerate_descriptions_for_invoice_lines(
        batch_id="SHIPMENT_PM_FB", dry_run=False,
    )
    assert res["written"] == 1, res
    r = _get_pd("EJL/26-27/PMFB-1")
    assert r["item_type"] == "RING"
    assert (r.get("name_pl") or "").strip()


# ── 7. invariants: no external write paths, no design_no-as-product_code

def test_function_source_has_no_wfirma_or_external_call_paths():
    """Source-grep guard: regenerate_descriptions_for_invoice_lines must
    not reach wfirma_client / posting / external HTTP — read-only on
    document_db, reservation_db, and description_engine itself."""
    src = (Path(__file__).resolve().parents[1] / "app" / "services"
           / "description_engine.py").read_text(encoding="utf-8")
    start = src.index("def regenerate_descriptions_for_invoice_lines(")
    # Bound at end of file or next top-level def.
    rest = src[start:]
    # Find next top-level def starting in column 0 after this one.
    nxt = rest.find("\n\n\ndef ", 1)
    body = rest if nxt < 0 else rest[: nxt]
    for forbidden in (
        "wfirma_client",
        "requests.post", "requests.patch", "requests.delete",
        "httpx.post",    "httpx.patch",    "httpx.delete",
        "create_product", "create_customer", "create_proforma",
        "send_email", "dhl_dispatch",
    ):
        assert forbidden not in body, (
            f"regenerate_descriptions_for_invoice_lines must not "
            f"reference {forbidden!r}"
        )


def test_function_source_never_aliases_design_no_as_product_code():
    """Design-no never feeds product_code in either direction."""
    src = (Path(__file__).resolve().parents[1] / "app" / "services"
           / "description_engine.py").read_text(encoding="utf-8")
    start = src.index("def regenerate_descriptions_for_invoice_lines(")
    rest  = src[start:]
    nxt = rest.find("\n\n\ndef ", 1)
    body = rest if nxt < 0 else rest[: nxt]
    # No assignment that uses design_no as product_code.
    assert "design_no" not in body or "product_code = design_no" not in body
    assert "product_code=design_no" not in body
