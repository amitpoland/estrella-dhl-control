"""
test_phase8_intelligence_graph.py -- Phase 8 Sprint 1: batch_id-centered Resolver.

Test strategy:
  - Fully isolated: all DB paths injected via tmp_path fixtures
  - No production DBs touched
  - Synthetic fixtures: create minimal SQLite tables + seed rows
  - Source-grep invariants verified textually (no writes, llm_used=False, PRAGMA)
  - 5 test classes: 40+ tests total

Classes
-------
TestAttributedValueAndLinkCompleteness  (5 tests) -- dataclass contracts
TestBuildAwbGraph                       (9 tests) -- AWB resolution + conflicts
TestBuildBatchGraph                     (10 tests) -- full cross-DB graph
TestBuildCustomerGraph                  (8 tests) -- customer resolution + conflicts
TestBuildInvoiceGraph                   (7 tests) -- invoice/MRN/PZ resolution
TestPhase8SourceGrep                    (5 tests) -- governance invariants
"""
from __future__ import annotations

import re
import sqlite3
import uuid
from pathlib import Path
from typing import Optional

import pytest

from app.services.intelligence_graph import (
    AttributedValue,
    GraphResult,
    LinkCompleteness,
    _BUILDER_AWB,
    _BUILDER_BATCH,
    _BUILDER_CUSTOMER,
    _BUILDER_INVOICE,
    build_awb_graph,
    build_batch_graph,
    build_customer_graph,
    build_invoice_graph,
)


# ── Fixture helpers ────────────────────────────────────────────────────────────


def _make_doc_db(path: Path) -> None:
    """Create minimal documents.db with shipment_documents, invoice_lines, customs_declarations."""
    con = sqlite3.connect(str(path))
    con.executescript("""
        CREATE TABLE IF NOT EXISTS shipment_documents (
            id                    TEXT PRIMARY KEY,
            batch_id              TEXT NOT NULL,
            awb                   TEXT NOT NULL DEFAULT '',
            document_type         TEXT NOT NULL,
            file_name             TEXT NOT NULL DEFAULT '',
            canonical_file_name   TEXT NOT NULL DEFAULT '',
            file_path             TEXT NOT NULL DEFAULT '',
            file_hash             TEXT NOT NULL DEFAULT '',
            parser_name           TEXT NOT NULL DEFAULT '',
            parser_version        TEXT NOT NULL DEFAULT '',
            parser_status         TEXT NOT NULL DEFAULT 'pending',
            extraction_status     TEXT NOT NULL DEFAULT 'pending',
            requires_manual_review INTEGER NOT NULL DEFAULT 0,
            related_invoice_no    TEXT NOT NULL DEFAULT '',
            related_mrn           TEXT NOT NULL DEFAULT '',
            related_pz_no         TEXT NOT NULL DEFAULT '',
            source                TEXT NOT NULL DEFAULT 'upload',
            client_contractor_id  TEXT NOT NULL DEFAULT '',
            supplier_contractor_id TEXT NOT NULL DEFAULT '',
            created_at            TEXT NOT NULL DEFAULT '2026-01-01T00:00:00+00:00',
            updated_at            TEXT NOT NULL DEFAULT '2026-01-01T00:00:00+00:00'
        );

        CREATE TABLE IF NOT EXISTS invoice_lines (
            id                TEXT PRIMARY KEY,
            document_id       TEXT NOT NULL DEFAULT '',
            batch_id          TEXT NOT NULL,
            invoice_no        TEXT NOT NULL DEFAULT '',
            line_position     INTEGER NOT NULL DEFAULT 0,
            product_code      TEXT NOT NULL DEFAULT '',
            quantity          REAL NOT NULL DEFAULT 0.0,
            unit_price        REAL NOT NULL DEFAULT 0.0,
            currency          TEXT NOT NULL DEFAULT 'EUR',
            created_at        TEXT NOT NULL DEFAULT '2026-01-01T00:00:00+00:00',
            updated_at        TEXT NOT NULL DEFAULT '2026-01-01T00:00:00+00:00'
        );

        CREATE TABLE IF NOT EXISTS customs_declarations (
            id                  TEXT PRIMARY KEY,
            batch_id            TEXT NOT NULL,
            mrn                 TEXT NOT NULL DEFAULT '',
            declaration_type    TEXT NOT NULL DEFAULT '',
            invoice_refs        TEXT NOT NULL DEFAULT '[]',
            raw_json            TEXT NOT NULL DEFAULT '{}',
            created_at          TEXT NOT NULL DEFAULT '2026-01-01T00:00:00+00:00',
            updated_at          TEXT NOT NULL DEFAULT '2026-01-01T00:00:00+00:00'
        );
    """)
    con.commit()
    con.close()


def _make_tracking_db(path: Path) -> None:
    """Create minimal tracking_events.db with shipment_tracking_events."""
    con = sqlite3.connect(str(path))
    con.executescript("""
        CREATE TABLE IF NOT EXISTS shipment_tracking_events (
            id                     TEXT PRIMARY KEY,
            batch_id               TEXT NOT NULL,
            awb                    TEXT NOT NULL,
            carrier                TEXT NOT NULL DEFAULT 'DHL',
            stage                  TEXT NOT NULL,
            status                 TEXT NOT NULL DEFAULT '',
            event_time             TEXT NOT NULL,
            captured_at            TEXT NOT NULL,
            source                 TEXT NOT NULL,
            source_ref             TEXT DEFAULT '',
            email_message_id       TEXT DEFAULT '',
            raw_subject            TEXT DEFAULT '',
            raw_sender             TEXT DEFAULT '',
            location               TEXT DEFAULT '',
            description            TEXT DEFAULT '',
            normalized_stage       TEXT NOT NULL DEFAULT '',
            confidence             REAL NOT NULL DEFAULT 0.0,
            requires_manual_review INTEGER NOT NULL DEFAULT 0,
            created_at             TEXT NOT NULL
        );
    """)
    con.commit()
    con.close()


def _make_customer_db(path: Path) -> None:
    """Create minimal customer_master.sqlite."""
    con = sqlite3.connect(str(path))
    con.executescript("""
        CREATE TABLE IF NOT EXISTS customer_master (
            id                      TEXT PRIMARY KEY,
            bill_to_contractor_id   TEXT NOT NULL UNIQUE,
            bill_to_name            TEXT NOT NULL DEFAULT '',
            country                 TEXT NOT NULL DEFAULT '',
            nip                     TEXT NOT NULL DEFAULT '',
            created_at              TEXT NOT NULL DEFAULT '2026-01-01T00:00:00+00:00',
            updated_at              TEXT NOT NULL DEFAULT '2026-01-01T00:00:00+00:00'
        );
    """)
    con.commit()
    con.close()


def _make_supplier_db(path: Path) -> None:
    """Create minimal suppliers.sqlite with wfirma_id column."""
    con = sqlite3.connect(str(path))
    con.executescript("""
        CREATE TABLE IF NOT EXISTS suppliers (
            id            TEXT PRIMARY KEY,
            supplier_code TEXT NOT NULL UNIQUE,
            name          TEXT NOT NULL DEFAULT '',
            country       TEXT NOT NULL DEFAULT '',
            vat_id        TEXT NOT NULL DEFAULT '',
            active        INTEGER NOT NULL DEFAULT 1,
            wfirma_id     TEXT,
            created_at    TEXT NOT NULL DEFAULT '2026-01-01T00:00:00+00:00',
            updated_at    TEXT NOT NULL DEFAULT '2026-01-01T00:00:00+00:00'
        );
    """)
    con.commit()
    con.close()


def _insert_doc(
    path:                Path,
    batch_id:            str,
    awb:                 str = "9765416334",
    document_type:       str = "invoice",
    related_invoice_no:  str = "",
    related_mrn:         str = "",
    related_pz_no:       str = "",
    client_contractor_id: str = "",
    supplier_contractor_id: str = "",
) -> str:
    doc_id = str(uuid.uuid4())
    con = sqlite3.connect(str(path))
    con.execute(
        """
        INSERT INTO shipment_documents (
            id, batch_id, awb, document_type,
            related_invoice_no, related_mrn, related_pz_no,
            client_contractor_id, supplier_contractor_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (doc_id, batch_id, awb, document_type,
         related_invoice_no, related_mrn, related_pz_no,
         client_contractor_id, supplier_contractor_id),
    )
    con.commit()
    con.close()
    return doc_id


def _insert_tracking(
    path:                  Path,
    batch_id:              str,
    awb:                   str = "9765416334",
    stage:                 str = "IN_TRANSIT",
    normalized_stage:      str = "in_transit",
    event_time:            str = "2026-05-01T10:00:00+00:00",
    requires_manual_review: int = 0,
) -> str:
    row_id = str(uuid.uuid4())
    con = sqlite3.connect(str(path))
    con.execute(
        """
        INSERT INTO shipment_tracking_events (
            id, batch_id, awb, stage, event_time, captured_at,
            source, normalized_stage, requires_manual_review, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (row_id, batch_id, awb, stage, event_time, event_time,
         "test", normalized_stage, requires_manual_review, event_time),
    )
    con.commit()
    con.close()
    return row_id


def _insert_customer(
    path:                  Path,
    bill_to_contractor_id: str,
    bill_to_name:          str,
    country:               str = "PL",
    nip:                   str = "",
) -> None:
    con = sqlite3.connect(str(path))
    con.execute(
        """
        INSERT INTO customer_master (id, bill_to_contractor_id, bill_to_name, country, nip)
        VALUES (?, ?, ?, ?, ?)
        """,
        (str(uuid.uuid4()), bill_to_contractor_id, bill_to_name, country, nip),
    )
    con.commit()
    con.close()


def _insert_supplier(
    path:          Path,
    supplier_code: str,
    name:          str,
    wfirma_id:     str,
    country:       str = "IN",
) -> None:
    con = sqlite3.connect(str(path))
    con.execute(
        """
        INSERT INTO suppliers (id, supplier_code, name, country, wfirma_id)
        VALUES (?, ?, ?, ?, ?)
        """,
        (str(uuid.uuid4()), supplier_code, name, country, wfirma_id),
    )
    con.commit()
    con.close()


def _insert_invoice_line(
    path:       Path,
    batch_id:   str,
    invoice_no: str = "INV-001/2026",
) -> None:
    con = sqlite3.connect(str(path))
    con.execute(
        """
        INSERT INTO invoice_lines (id, batch_id, invoice_no, line_position, quantity)
        VALUES (?, ?, ?, 1, 10.0)
        """,
        (str(uuid.uuid4()), batch_id, invoice_no),
    )
    con.commit()
    con.close()


def _insert_customs(
    path:     Path,
    batch_id: str,
    mrn:      str = "26PL0000000000001Y",
) -> None:
    con = sqlite3.connect(str(path))
    con.execute(
        """
        INSERT INTO customs_declarations (id, batch_id, mrn, declaration_type)
        VALUES (?, ?, ?, 'SAD')
        """,
        (str(uuid.uuid4()), batch_id, mrn),
    )
    con.commit()
    con.close()


# ── Test class 1: dataclass contracts ─────────────────────────────────────────


class TestAttributedValueAndLinkCompleteness:
    """Dataclass contract tests -- 5 tests."""

    def test_attributed_value_fields(self):
        av = AttributedValue(value="9765416334", authority="shipment_documents")
        assert av.value == "9765416334"
        assert av.authority == "shipment_documents"

    def test_attributed_value_none_value(self):
        av = AttributedValue(value=None, authority="customer_master")
        assert av.value is None
        assert av.authority == "customer_master"

    def test_link_completeness_defaults_all_false(self):
        lc = LinkCompleteness()
        assert lc.awb_linked is False
        assert lc.tracking_linked is False
        assert lc.customer_linked is False
        assert lc.supplier_linked is False
        assert lc.invoice_linked is False
        assert lc.customs_linked is False
        assert lc.missing == []

    def test_link_completeness_compute_missing_all_false(self):
        lc = LinkCompleteness()
        lc._compute_missing()
        assert set(lc.missing) == {"awb", "tracking", "customer", "supplier", "invoice", "customs"}

    def test_link_completeness_compute_missing_partial(self):
        lc = LinkCompleteness(awb_linked=True, invoice_linked=True)
        lc._compute_missing()
        assert "awb" not in lc.missing
        assert "invoice" not in lc.missing
        assert "customer" in lc.missing
        assert "supplier" in lc.missing


# ── Test class 2: build_awb_graph ─────────────────────────────────────────────


class TestBuildAwbGraph:
    """AWB resolution + tracking -- 9 tests."""

    def test_awb_from_docs_only(self, tmp_path):
        doc_db = tmp_path / "docs.db"
        track_db = tmp_path / "track.db"
        _make_doc_db(doc_db)
        _make_tracking_db(track_db)
        bid = "BATCH-AWB-TEST-001"
        _insert_doc(doc_db, bid, awb="9765416334")

        result = build_awb_graph(bid, doc_db=doc_db, tracking_db=track_db)

        assert isinstance(result, GraphResult)
        assert result.batch_id == bid
        assert result.llm_used is False
        assert result.builder == _BUILDER_AWB
        assert result.awb is not None
        assert result.awb.value == "9765416334"
        assert result.awb.authority == "shipment_documents"

    def test_awb_from_tracking_fallback(self, tmp_path):
        doc_db = tmp_path / "docs.db"
        track_db = tmp_path / "track.db"
        _make_doc_db(doc_db)
        _make_tracking_db(track_db)
        bid = "BATCH-AWB-TEST-002"
        # No doc, only tracking
        _insert_tracking(track_db, bid, awb="4789974092")

        result = build_awb_graph(bid, doc_db=doc_db, tracking_db=track_db)

        assert result.awb is not None
        assert result.awb.value == "4789974092"
        assert result.awb.authority == "shipment_tracking_events"

    def test_awb_absent_both_sources(self, tmp_path):
        doc_db = tmp_path / "docs.db"
        track_db = tmp_path / "track.db"
        _make_doc_db(doc_db)
        _make_tracking_db(track_db)
        bid = "BATCH-AWB-UNKNOWN"

        result = build_awb_graph(bid, doc_db=doc_db, tracking_db=track_db)

        assert result.awb is None
        assert result.awb_conflict is None
        assert result.link_completeness.awb_linked is False
        assert "awb" in result.link_completeness.missing

    def test_awb_conflict_detection(self, tmp_path):
        doc_db = tmp_path / "docs.db"
        track_db = tmp_path / "track.db"
        _make_doc_db(doc_db)
        _make_tracking_db(track_db)
        bid = "BATCH-AWB-CONFLICT"
        _insert_doc(doc_db, bid, awb="9765416334")          # docs say AWB A
        _insert_tracking(track_db, bid, awb="4789974092")   # tracking says AWB B

        result = build_awb_graph(bid, doc_db=doc_db, tracking_db=track_db)

        # Primary: docs
        assert result.awb.value == "9765416334"
        assert result.awb.authority == "shipment_documents"
        # Conflict: tracking
        assert result.awb_conflict is not None
        assert result.awb_conflict.value == "4789974092"
        assert result.awb_conflict.authority == "shipment_tracking_events"
        assert "awb" in result.conflict_keys

    def test_awb_no_conflict_when_same(self, tmp_path):
        doc_db = tmp_path / "docs.db"
        track_db = tmp_path / "track.db"
        _make_doc_db(doc_db)
        _make_tracking_db(track_db)
        bid = "BATCH-AWB-SAME"
        _insert_doc(doc_db, bid, awb="9765416334")
        _insert_tracking(track_db, bid, awb="9765416334")

        result = build_awb_graph(bid, doc_db=doc_db, tracking_db=track_db)

        assert result.awb_conflict is None
        assert "awb" not in result.conflict_keys

    def test_tracking_event_count(self, tmp_path):
        doc_db = tmp_path / "docs.db"
        track_db = tmp_path / "track.db"
        _make_doc_db(doc_db)
        _make_tracking_db(track_db)
        bid = "BATCH-TRACK-COUNT"
        _insert_doc(doc_db, bid, awb="9765416334")
        _insert_tracking(track_db, bid, awb="9765416334", event_time="2026-05-01T10:00:00+00:00")
        _insert_tracking(track_db, bid, awb="9765416334", event_time="2026-05-02T10:00:00+00:00")

        result = build_awb_graph(bid, doc_db=doc_db, tracking_db=track_db)

        assert result.tracking_event_count == 2
        assert result.link_completeness.tracking_linked is True

    def test_manual_review_flag(self, tmp_path):
        doc_db = tmp_path / "docs.db"
        track_db = tmp_path / "track.db"
        _make_doc_db(doc_db)
        _make_tracking_db(track_db)
        bid = "BATCH-MANUAL-REVIEW"
        _insert_doc(doc_db, bid, awb="9765416334")
        _insert_tracking(track_db, bid, awb="9765416334", requires_manual_review=1)

        result = build_awb_graph(bid, doc_db=doc_db, tracking_db=track_db)

        assert result.tracking_has_manual_review is True

    def test_missing_db_files_do_not_crash(self, tmp_path):
        bid = "BATCH-NO-DBS"
        result = build_awb_graph(
            bid,
            doc_db=tmp_path / "nonexistent_docs.db",
            tracking_db=tmp_path / "nonexistent_track.db",
        )
        assert isinstance(result, GraphResult)
        assert result.awb is None
        assert result.llm_used is False

    def test_llm_used_always_false(self, tmp_path):
        doc_db = tmp_path / "docs.db"
        _make_doc_db(doc_db)
        bid = "BATCH-LLM-CHECK"
        result = build_awb_graph(bid, doc_db=doc_db, tracking_db=tmp_path / "no_track.db")
        assert result.llm_used is False


# ── Test class 3: build_batch_graph ───────────────────────────────────────────


class TestBuildBatchGraph:
    """Full cross-DB graph resolution -- 10 tests."""

    def test_builder_name(self, tmp_path):
        doc_db = tmp_path / "docs.db"
        _make_doc_db(doc_db)
        result = build_batch_graph("BATCH-NAME-CHECK", doc_db=doc_db)
        assert result.builder == _BUILDER_BATCH

    def test_customer_resolved_from_master(self, tmp_path):
        doc_db = tmp_path / "docs.db"
        cm_db = tmp_path / "cm.db"
        _make_doc_db(doc_db)
        _make_customer_db(cm_db)
        bid = "BATCH-CM-RESOLVE"
        contractor_id = "ctr_12345"
        _insert_doc(doc_db, bid, client_contractor_id=contractor_id)
        _insert_customer(cm_db, contractor_id, "Estrella Jewels GmbH", "DE")

        result = build_batch_graph(
            bid,
            doc_db=doc_db,
            cm_db=cm_db,
            tracking_db=tmp_path / "no_track.db",
            supp_db=tmp_path / "no_supp.db",
        )

        assert result.customer is not None
        assert result.customer.authority == "customer_master"
        assert "Estrella Jewels GmbH" in result.customer.value
        assert result.link_completeness.customer_linked is True

    def test_customer_raw_when_cm_miss(self, tmp_path):
        doc_db = tmp_path / "docs.db"
        cm_db = tmp_path / "cm.db"
        _make_doc_db(doc_db)
        _make_customer_db(cm_db)
        bid = "BATCH-CM-MISS"
        _insert_doc(doc_db, bid, client_contractor_id="ctr_unknown_99")

        result = build_batch_graph(bid, doc_db=doc_db, cm_db=cm_db)

        assert result.customer is not None
        assert result.customer.authority == "shipment_documents"
        assert result.customer.value == "ctr_unknown_99"
        # customer_linked=False because CM has no entry
        assert result.link_completeness.customer_linked is False

    def test_supplier_resolved_from_registry(self, tmp_path):
        doc_db = tmp_path / "docs.db"
        supp_db = tmp_path / "supp.db"
        _make_doc_db(doc_db)
        _make_supplier_db(supp_db)
        bid = "BATCH-SUPP-RESOLVE"
        supplier_cid = "sup_wfirma_456"
        _insert_doc(doc_db, bid, supplier_contractor_id=supplier_cid)
        _insert_supplier(supp_db, "EJL", "Estrella Jewels Ltd", supplier_cid, "IN")

        result = build_batch_graph(
            bid,
            doc_db=doc_db,
            supp_db=supp_db,
            tracking_db=tmp_path / "no_track.db",
            cm_db=tmp_path / "no_cm.db",
        )

        assert result.supplier is not None
        assert result.supplier.value == "Estrella Jewels Ltd"
        assert result.supplier.authority == "suppliers"
        assert result.supplier_code is not None
        assert result.supplier_code.value == "EJL"
        assert result.link_completeness.supplier_linked is True

    def test_supplier_null_when_no_doc_link(self, tmp_path):
        doc_db = tmp_path / "docs.db"
        _make_doc_db(doc_db)
        bid = "BATCH-NO-SUPPLIER"
        _insert_doc(doc_db, bid, supplier_contractor_id="")

        result = build_batch_graph(bid, doc_db=doc_db)

        assert result.supplier is None
        assert result.link_completeness.supplier_linked is False
        assert "supplier" in result.link_completeness.missing

    def test_invoice_line_count(self, tmp_path):
        doc_db = tmp_path / "docs.db"
        _make_doc_db(doc_db)
        bid = "BATCH-INVOICE-LINES"
        _insert_doc(doc_db, bid, related_invoice_no="INV-94/2026")
        _insert_invoice_line(doc_db, bid, invoice_no="INV-94/2026")
        _insert_invoice_line(doc_db, bid, invoice_no="INV-94/2026")

        result = build_batch_graph(bid, doc_db=doc_db)

        assert result.invoice_line_count == 2
        assert result.link_completeness.invoice_linked is True

    def test_mrn_from_customs_preferred_over_doc_hint(self, tmp_path):
        doc_db = tmp_path / "docs.db"
        _make_doc_db(doc_db)
        bid = "BATCH-MRN-PRIORITY"
        _insert_doc(doc_db, bid, related_mrn="26PL_DOC_HINT_MRN")
        _insert_customs(doc_db, bid, mrn="26PL0000000000001Y")

        result = build_batch_graph(bid, doc_db=doc_db)

        assert result.mrn is not None
        assert result.mrn.value == "26PL0000000000001Y"
        assert result.mrn.authority == "customs_declarations"
        assert result.link_completeness.customs_linked is True

    def test_customer_conflict_multiple_contractor_ids(self, tmp_path):
        doc_db = tmp_path / "docs.db"
        cm_db = tmp_path / "cm.db"
        _make_doc_db(doc_db)
        _make_customer_db(cm_db)
        bid = "BATCH-CUST-CONFLICT"
        _insert_doc(doc_db, bid, client_contractor_id="ctr_primary_001")
        _insert_doc(doc_db, bid, client_contractor_id="ctr_secondary_002",
                    document_type="packing_list")
        _insert_customer(cm_db, "ctr_primary_001", "Estrella GmbH", "DE")
        _insert_customer(cm_db, "ctr_secondary_002", "Estrella Jewels GmbH", "PL")

        result = build_batch_graph(bid, doc_db=doc_db, cm_db=cm_db)

        assert result.customer is not None
        assert result.customer_conflict is not None
        assert "customer" in result.conflict_keys
        # Primary is first contractor
        assert "Estrella GmbH" in result.customer.value

    def test_full_graph_all_linked(self, tmp_path):
        doc_db = tmp_path / "docs.db"
        track_db = tmp_path / "track.db"
        cm_db = tmp_path / "cm.db"
        supp_db = tmp_path / "supp.db"
        _make_doc_db(doc_db)
        _make_tracking_db(track_db)
        _make_customer_db(cm_db)
        _make_supplier_db(supp_db)
        bid = "BATCH-FULL-GRAPH"
        _insert_doc(doc_db, bid, awb="9765416334",
                    client_contractor_id="ctr_100",
                    supplier_contractor_id="sup_200",
                    related_invoice_no="INV-94/2026",
                    related_pz_no="183/2026")
        _insert_tracking(track_db, bid, awb="9765416334")
        _insert_customer(cm_db, "ctr_100", "Estrella Jewels GmbH", "PL")
        _insert_supplier(supp_db, "EJL", "EJ Ltd", "sup_200", "IN")
        _insert_invoice_line(doc_db, bid)
        _insert_customs(doc_db, bid, mrn="26PL0000000000001Y")

        result = build_batch_graph(
            bid,
            doc_db=doc_db,
            tracking_db=track_db,
            cm_db=cm_db,
            supp_db=supp_db,
        )

        lc = result.link_completeness
        assert lc.awb_linked
        assert lc.tracking_linked
        assert lc.customer_linked
        assert lc.supplier_linked
        assert lc.invoice_linked
        assert lc.customs_linked
        assert lc.missing == []

    def test_missing_dbs_return_empty_graph(self, tmp_path):
        bid = "BATCH-MISSING-ALL"
        result = build_batch_graph(
            bid,
            doc_db=tmp_path / "none1.db",
            tracking_db=tmp_path / "none2.db",
            cm_db=tmp_path / "none3.db",
            supp_db=tmp_path / "none4.db",
        )
        assert result.batch_id == bid
        assert result.awb is None
        assert result.customer is None
        assert result.supplier is None
        assert result.llm_used is False
        assert len(result.link_completeness.missing) == 6


# ── Test class 4: build_customer_graph ────────────────────────────────────────


class TestBuildCustomerGraph:
    """Customer resolution + conflict exposure -- 8 tests."""

    def test_builder_name(self, tmp_path):
        doc_db = tmp_path / "docs.db"
        _make_doc_db(doc_db)
        result = build_customer_graph("BATCH-CNAME", doc_db=doc_db)
        assert result.builder == _BUILDER_CUSTOMER

    def test_customer_linked_from_master(self, tmp_path):
        doc_db = tmp_path / "docs.db"
        cm_db = tmp_path / "cm.db"
        _make_doc_db(doc_db)
        _make_customer_db(cm_db)
        bid = "BATCH-CUST-LINKED"
        _insert_doc(doc_db, bid, client_contractor_id="ctr_abc")
        _insert_customer(cm_db, "ctr_abc", "Star Fashion GmbH", "DE")

        result = build_customer_graph(bid, doc_db=doc_db, cm_db=cm_db)

        assert result.customer.authority == "customer_master"
        assert "Star Fashion GmbH" in result.customer.value
        assert result.link_completeness.customer_linked is True

    def test_customer_raw_fallback(self, tmp_path):
        doc_db = tmp_path / "docs.db"
        cm_db = tmp_path / "cm.db"
        _make_doc_db(doc_db)
        _make_customer_db(cm_db)
        bid = "BATCH-CUST-RAW"
        _insert_doc(doc_db, bid, client_contractor_id="ctr_orphan_999")

        result = build_customer_graph(bid, doc_db=doc_db, cm_db=cm_db)

        assert result.customer is not None
        assert result.customer.authority == "shipment_documents"
        assert result.customer.value == "ctr_orphan_999"
        assert result.link_completeness.customer_linked is False

    def test_no_customer_when_no_docs(self, tmp_path):
        doc_db = tmp_path / "docs.db"
        _make_doc_db(doc_db)
        bid = "BATCH-NO-CUST"
        # No documents inserted

        result = build_customer_graph(bid, doc_db=doc_db)

        assert result.customer is None
        assert result.link_completeness.customer_linked is False

    def test_conflict_exposed_not_winner_picked(self, tmp_path):
        doc_db = tmp_path / "docs.db"
        cm_db = tmp_path / "cm.db"
        _make_doc_db(doc_db)
        _make_customer_db(cm_db)
        bid = "BATCH-CUST-CONFLICT2"
        _insert_doc(doc_db, bid, client_contractor_id="ctr_A")
        _insert_doc(doc_db, bid, client_contractor_id="ctr_B", document_type="packing_list")
        _insert_customer(cm_db, "ctr_A", "Company A", "DE")
        _insert_customer(cm_db, "ctr_B", "Company B", "PL")

        result = build_customer_graph(bid, doc_db=doc_db, cm_db=cm_db)

        # Both exposed -- no winner selected silently
        assert result.customer is not None      # primary
        assert result.customer_conflict is not None  # secondary
        assert "customer" in result.conflict_keys
        # Primary authority must be customer_master (resolved from CM)
        assert result.customer.authority == "customer_master"

    def test_awb_populated_for_context(self, tmp_path):
        doc_db = tmp_path / "docs.db"
        _make_doc_db(doc_db)
        bid = "BATCH-CUST-AWB"
        _insert_doc(doc_db, bid, awb="1122334455", client_contractor_id="ctr_X")

        result = build_customer_graph(bid, doc_db=doc_db)

        assert result.awb is not None
        assert result.awb.value == "1122334455"

    def test_llm_used_false(self, tmp_path):
        doc_db = tmp_path / "docs.db"
        _make_doc_db(doc_db)
        result = build_customer_graph("BATCH-LLM", doc_db=doc_db)
        assert result.llm_used is False

    def test_missing_db_no_crash(self, tmp_path):
        result = build_customer_graph(
            "BATCH-MISSING",
            doc_db=tmp_path / "no_docs.db",
            cm_db=tmp_path / "no_cm.db",
        )
        assert isinstance(result, GraphResult)
        assert result.customer is None


# ── Test class 5: build_invoice_graph ─────────────────────────────────────────


class TestBuildInvoiceGraph:
    """Invoice / customs / PZ resolution -- 7 tests."""

    def test_builder_name(self, tmp_path):
        doc_db = tmp_path / "docs.db"
        _make_doc_db(doc_db)
        result = build_invoice_graph("BATCH-INV-NAME", doc_db=doc_db)
        assert result.builder == _BUILDER_INVOICE

    def test_invoice_ref_from_doc_hint(self, tmp_path):
        doc_db = tmp_path / "docs.db"
        _make_doc_db(doc_db)
        bid = "BATCH-INV-REF"
        _insert_doc(doc_db, bid, related_invoice_no="INV-94/2026")

        result = build_invoice_graph(bid, doc_db=doc_db)

        assert result.invoice_ref is not None
        assert result.invoice_ref.value == "INV-94/2026"
        assert result.invoice_ref.authority == "shipment_documents"
        assert result.link_completeness.invoice_linked is True

    def test_pz_ref(self, tmp_path):
        doc_db = tmp_path / "docs.db"
        _make_doc_db(doc_db)
        bid = "BATCH-PZ-REF"
        _insert_doc(doc_db, bid, related_pz_no="183/2026")

        result = build_invoice_graph(bid, doc_db=doc_db)

        assert result.pz_ref is not None
        assert result.pz_ref.value == "183/2026"

    def test_customs_mrn_authoritative(self, tmp_path):
        doc_db = tmp_path / "docs.db"
        _make_doc_db(doc_db)
        bid = "BATCH-MRN-AUTH"
        _insert_doc(doc_db, bid, related_mrn="26PL_DOC_HINT")
        _insert_customs(doc_db, bid, mrn="26PL_REAL_MRN")

        result = build_invoice_graph(bid, doc_db=doc_db)

        # Customs table wins
        assert result.mrn.value == "26PL_REAL_MRN"
        assert result.mrn.authority == "customs_declarations"
        assert result.link_completeness.customs_linked is True

    def test_mrn_fallback_to_doc_hint(self, tmp_path):
        doc_db = tmp_path / "docs.db"
        _make_doc_db(doc_db)
        bid = "BATCH-MRN-HINT"
        _insert_doc(doc_db, bid, related_mrn="26PL_HINT_ONLY")
        # No customs_declarations row

        result = build_invoice_graph(bid, doc_db=doc_db)

        assert result.mrn.value == "26PL_HINT_ONLY"
        assert result.mrn.authority == "shipment_documents"

    def test_invoice_line_count_in_result(self, tmp_path):
        doc_db = tmp_path / "docs.db"
        _make_doc_db(doc_db)
        bid = "BATCH-INV-COUNT"
        _insert_doc(doc_db, bid)
        for _ in range(5):
            _insert_invoice_line(doc_db, bid)

        result = build_invoice_graph(bid, doc_db=doc_db)

        assert result.invoice_line_count == 5
        assert result.link_completeness.invoice_linked is True

    def test_empty_batch_all_null(self, tmp_path):
        doc_db = tmp_path / "docs.db"
        _make_doc_db(doc_db)
        bid = "BATCH-INV-EMPTY"

        result = build_invoice_graph(bid, doc_db=doc_db)

        assert result.invoice_ref is None
        assert result.pz_ref is None
        assert result.mrn is None
        assert result.invoice_line_count == 0
        assert result.link_completeness.invoice_linked is False
        assert result.link_completeness.customs_linked is False


# ── Test class 6: source-grep governance invariants ───────────────────────────


class TestPhase8SourceGrep:
    """
    Governance invariants verified by reading the source file.
    These tests confirm the structural rules Phase 8 must never violate.
    """

    @pytest.fixture(scope="class")
    def source(self) -> str:
        src = Path(__file__).parent.parent / "app" / "services" / "intelligence_graph.py"
        return src.read_text(encoding="utf-8")

    def test_llm_used_false_hardcoded(self, source):
        """llm_used = False must be hardcoded -- never True."""
        assert "llm_used = False" in source
        # Must never set llm_used to True
        assert "llm_used = True" not in source
        assert "llm_used=True" not in source

    def test_pragma_query_only_present(self, source):
        """Every DB connection must use PRAGMA query_only = ON."""
        assert "PRAGMA query_only = ON" in source

    def test_no_write_sql_statements(self, source):
        """No INSERT / UPDATE / DELETE in the service module."""
        for forbidden in ("INSERT ", "UPDATE ", "DELETE "):
            assert forbidden not in source, (
                f"Found forbidden write SQL keyword '{forbidden}' in intelligence_graph.py"
            )

    def test_ro_conn_used_for_all_db_access(self, source):
        """All DB opens must go through _ro_conn(), not sqlite3.connect() directly."""
        # _ro_conn is defined and used
        assert "def _ro_conn(" in source
        # Every sqlite3.connect call must be inside _ro_conn itself
        # i.e., there should be exactly one sqlite3.connect reference (in _ro_conn)
        connect_count = source.count("sqlite3.connect(")
        assert connect_count == 1, (
            f"Expected exactly 1 sqlite3.connect() call (inside _ro_conn), found {connect_count}"
        )

    def test_no_external_calls(self, source):
        """No HTTP, wFirma, DHL, or email calls in Phase 8."""
        for forbidden in ("requests.get", "requests.post", "httpx.", "wfirma_client", "email_service"):
            assert forbidden not in source, (
                f"Forbidden external call '{forbidden}' found in intelligence_graph.py"
            )
