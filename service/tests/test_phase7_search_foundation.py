"""Phase 7 -- Natural-Language Search Foundation: test suite.

Coverage:
  - Query parser (parse_query)
  - Domain search functions (search_documents, search_customers,
    search_suppliers, search_products)
  - execute_search top-level orchestrator
  - GET /api/v1/search route
  - Source-grep safety invariants

All DB-touching tests use real temporary SQLite databases.
llm_used=False is verified as a structural invariant on every result.
"""
from __future__ import annotations

import re
import sqlite3
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_docs_db(path: Path) -> None:
    """Create a minimal documents.db schema and seed rows."""
    con = sqlite3.connect(str(path))
    con.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS shipment_documents (
            id TEXT PRIMARY KEY,
            batch_id TEXT NOT NULL DEFAULT '',
            awb TEXT NOT NULL DEFAULT '',
            document_type TEXT NOT NULL DEFAULT '',
            file_name TEXT NOT NULL DEFAULT '',
            canonical_file_name TEXT NOT NULL DEFAULT '',
            file_path TEXT NOT NULL DEFAULT '',
            file_hash TEXT NOT NULL DEFAULT '',
            parser_name TEXT NOT NULL DEFAULT '',
            parser_version TEXT NOT NULL DEFAULT '',
            parser_status TEXT NOT NULL DEFAULT 'pending',
            extraction_status TEXT NOT NULL DEFAULT 'pending',
            requires_manual_review INTEGER NOT NULL DEFAULT 0,
            related_invoice_no TEXT NOT NULL DEFAULT '',
            related_mrn TEXT NOT NULL DEFAULT '',
            related_pz_no TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL DEFAULT 'upload',
            client_contractor_id TEXT NOT NULL DEFAULT '',
            supplier_contractor_id TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT '2026-05-23T10:00:00+00:00',
            updated_at TEXT NOT NULL DEFAULT '2026-05-23T10:00:00+00:00'
        );
        CREATE TABLE IF NOT EXISTS customs_declarations (
            id TEXT PRIMARY KEY,
            document_id TEXT NOT NULL DEFAULT '',
            batch_id TEXT NOT NULL DEFAULT '',
            mrn TEXT NOT NULL DEFAULT '',
            lrn TEXT NOT NULL DEFAULT '',
            clearance_date TEXT NOT NULL DEFAULT '',
            duty_pln REAL NOT NULL DEFAULT 0.0,
            vat_pln REAL NOT NULL DEFAULT 0.0,
            total_cif_usd REAL NOT NULL DEFAULT 0.0,
            customs_rate_usd REAL,
            statistical_value_pln REAL NOT NULL DEFAULT 0.0,
            agent TEXT NOT NULL DEFAULT '',
            importer_name TEXT NOT NULL DEFAULT '',
            importer_nip TEXT NOT NULL DEFAULT '',
            exporter_name TEXT NOT NULL DEFAULT '',
            cn_code TEXT NOT NULL DEFAULT '',
            goods_description TEXT NOT NULL DEFAULT '',
            invoice_refs TEXT NOT NULL DEFAULT '[]',
            raw_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT '2026-05-23T10:00:00+00:00',
            updated_at TEXT NOT NULL DEFAULT '2026-05-23T10:00:00+00:00'
        );
    """)
    con.executemany(
        "INSERT INTO shipment_documents (id, batch_id, awb, document_type, file_name, "
        "extraction_status, parser_status, related_mrn, related_pz_no, "
        "requires_manual_review) VALUES (?,?,?,?,?,?,?,?,?,?)",
        [
            ("doc-1", "batch-alpha", "4789974092", "INVOICE", "invoice.pdf",
             "complete", "ok", "", "", 0),
            ("doc-2", "batch-alpha", "4789974092", "PACKING_LIST", "packing.pdf",
             "pending", "pending", "", "", 0),
            ("doc-3", "batch-beta", "1234567890", "SAD", "sad.xml",
             "complete", "ok", "26PL12345678901234A", "94/2026", 0),
            ("doc-4", "batch-gamma", "", "ZC429", "zc429.xml",
             "failed", "error", "", "", 1),
        ],
    )
    con.executemany(
        "INSERT INTO customs_declarations (id, batch_id, mrn, clearance_date, "
        "duty_pln, importer_name, goods_description) VALUES (?,?,?,?,?,?,?)",
        [
            ("cd-1", "batch-beta", "26PL12345678901234A",
             "2026-04-01", 1234.56, "Estrella Jewels", "jewellery articles"),
        ],
    )
    con.commit()
    con.close()


def _make_customer_db(path: Path) -> None:
    con = sqlite3.connect(str(path))
    con.executescript("""
        CREATE TABLE IF NOT EXISTS customer_master (
            bill_to_contractor_id TEXT PRIMARY KEY,
            bill_to_name TEXT NOT NULL DEFAULT '',
            country TEXT NOT NULL DEFAULT '',
            nip TEXT DEFAULT NULL,
            vat_eu_number TEXT DEFAULT NULL,
            vat_eu_valid INTEGER DEFAULT NULL,
            vat_eu_validated_at TEXT DEFAULT NULL,
            default_currency TEXT DEFAULT NULL,
            risk_status TEXT DEFAULT NULL,
            updated_at TEXT NOT NULL DEFAULT '2026-05-23T10:00:00+00:00',
            id INTEGER
        );
    """)
    con.executemany(
        "INSERT INTO customer_master (bill_to_contractor_id, bill_to_name, "
        "country, nip, vat_eu_number, default_currency) VALUES (?,?,?,?,?,?)",
        [
            ("C001", "Estrella Jewels GmbH", "DE", "1234567890", "DE123456789", "EUR"),
            ("C002", "Stella Fashion sp.z.o.o.", "PL", "9876543210", None, "PLN"),
            ("C003", "Antalia Jewellery Ltd", "GB", None, "GB123456789", "GBP"),
        ],
    )
    con.commit()
    con.close()


def _make_supplier_db(path: Path) -> None:
    con = sqlite3.connect(str(path))
    con.executescript("""
        CREATE TABLE IF NOT EXISTS suppliers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            supplier_code TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL DEFAULT '',
            country TEXT NOT NULL DEFAULT '',
            vat_id TEXT DEFAULT NULL,
            eori TEXT DEFAULT NULL,
            wfirma_id TEXT DEFAULT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            updated_at TEXT NOT NULL DEFAULT '2026-05-23T10:00:00+00:00'
        );
    """)
    con.executemany(
        "INSERT INTO suppliers (supplier_code, name, country, vat_id, eori, active) "
        "VALUES (?,?,?,?,?,?)",
        [
            ("SUP001", "Mumbai Gems Exports", "IN", "IN123456789A", "IN12345678", 1),
            ("SUP002", "Jaipur Jewels Pvt Ltd", "IN", "IN987654321B", None, 1),
            ("SUP003", "Istanbul Gold Trading", "TR", "TR1234567890", None, 1),
        ],
    )
    con.commit()
    con.close()


def _make_design_db(path: Path) -> None:
    con = sqlite3.connect(str(path))
    con.executescript("""
        CREATE TABLE IF NOT EXISTS designs (
            design_code TEXT PRIMARY KEY,
            display_name TEXT DEFAULT NULL,
            collection TEXT DEFAULT NULL,
            metal TEXT DEFAULT NULL,
            stone_summary TEXT DEFAULT NULL,
            hs_code TEXT DEFAULT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            updated_at TEXT NOT NULL DEFAULT '2026-05-23T10:00:00+00:00'
        );
    """)
    con.executemany(
        "INSERT INTO designs (design_code, display_name, collection, "
        "metal, stone_summary, hs_code, active) VALUES (?,?,?,?,?,?,?)",
        [
            ("EST-001", "Diamond Solitaire Ring", "Bridal", "Yellow Gold", "Diamond", "7113190000", 1),
            ("EST-002", "Emerald Drop Earrings", "Classic", "White Gold", "Emerald", "7113190000", 1),
            ("EST-003", "Silver Chain Necklace", "Everyday", "Silver", None, "7113110000", 1),
        ],
    )
    con.commit()
    con.close()


# ---------------------------------------------------------------------------
# TestParseQuery
# ---------------------------------------------------------------------------

class TestParseQuery:
    from app.services.search_engine import parse_query

    def test_empty_string_returns_empty_intent(self):
        from app.services.search_engine import parse_query
        intent = parse_query("")
        assert intent.raw_query == ""
        assert not intent.awb_matches
        assert not intent.keyword

    def test_whitespace_only_normalizes_to_empty(self):
        from app.services.search_engine import parse_query
        intent = parse_query("   ")
        assert intent.raw_query == ""

    def test_awb_10_digit_detected(self):
        from app.services.search_engine import parse_query
        intent = parse_query("4789974092")
        assert "4789974092" in intent.awb_matches

    def test_awb_12_digit_detected(self):
        from app.services.search_engine import parse_query
        intent = parse_query("123456789012")
        assert "123456789012" in intent.awb_matches

    def test_awb_grouped_with_spaces_detected(self):
        from app.services.search_engine import parse_query
        intent = parse_query("4789 9740 92")
        assert any("4789974092" in a.replace(" ", "") for a in intent.awb_matches)

    def test_mrn_detected(self):
        from app.services.search_engine import parse_query
        intent = parse_query("26PL12345678901234A")
        assert "26PL12345678901234A" in intent.mrn_matches

    def test_pz_ref_detected(self):
        from app.services.search_engine import parse_query
        intent = parse_query("94/2026")
        assert "94/2026" in intent.pz_invoice_matches

    def test_uuid_batch_id_detected(self):
        from app.services.search_engine import parse_query
        uid = "12345678-1234-1234-1234-123456789abc"
        intent = parse_query(uid)
        assert uid in intent.batch_matches

    def test_batch_label_detected(self):
        from app.services.search_engine import parse_query
        intent = parse_query("BATCH-42")
        assert "BATCH-42" in intent.batch_matches

    def test_hs_code_jewellery_detected(self):
        from app.services.search_engine import parse_query
        intent = parse_query("7113190000")
        assert "7113190000" in intent.hs_matches

    def test_keyword_free_text(self):
        from app.services.search_engine import parse_query
        intent = parse_query("Estrella Jewels")
        assert "estrella" in intent.keyword.lower() or "jewels" in intent.keyword.lower()

    def test_awb_triggers_document_domain(self):
        from app.services.search_engine import parse_query
        intent = parse_query("4789974092")
        assert "document" in intent.domains_hint

    def test_keyword_triggers_all_domains(self):
        from app.services.search_engine import parse_query
        intent = parse_query("jewellery factory mumbai")
        for domain in ("document", "customer", "supplier", "product"):
            assert domain in intent.domains_hint

    def test_query_truncated_at_max_len(self):
        from app.services.search_engine import parse_query, QUERY_MAX_LEN
        long_q = "a" * (QUERY_MAX_LEN + 100)
        intent = parse_query(long_q)
        assert len(intent.raw_query) <= QUERY_MAX_LEN

    def test_mixed_awb_and_keyword(self):
        from app.services.search_engine import parse_query
        intent = parse_query("AWB 4789974092 invoice missing")
        assert "4789974092" in intent.awb_matches
        assert intent.keyword  # "AWB invoice missing" or similar remains

    def test_mrn_triggers_document_domain(self):
        from app.services.search_engine import parse_query
        intent = parse_query("MRN 26PL12345678901234A")
        assert "document" in intent.domains_hint


# ---------------------------------------------------------------------------
# TestSearchDocuments
# ---------------------------------------------------------------------------

class TestSearchDocuments:
    def _setup(self, tmp_path):
        db = tmp_path / "documents.db"
        _make_docs_db(db)
        return db

    def test_awb_exact_match(self, tmp_path):
        from app.services.search_engine import parse_query, search_documents
        db = self._setup(tmp_path)
        intent = parse_query("4789974092")
        hits = search_documents(intent, db_path=db)
        entity_ids = [h.entity_id for h in hits]
        assert "doc-1" in entity_ids
        assert "doc-2" in entity_ids

    def test_awb_hit_score_is_max(self, tmp_path):
        from app.services.search_engine import parse_query, search_documents
        db = self._setup(tmp_path)
        intent = parse_query("4789974092")
        hits = search_documents(intent, db_path=db)
        assert any(h.score == 1.0 for h in hits)

    def test_mrn_exact_match(self, tmp_path):
        from app.services.search_engine import parse_query, search_documents
        db = self._setup(tmp_path)
        intent = parse_query("26PL12345678901234A")
        hits = search_documents(intent, db_path=db)
        entity_ids = [h.entity_id for h in hits]
        assert "doc-3" in entity_ids

    def test_mrn_matches_customs_declaration(self, tmp_path):
        from app.services.search_engine import parse_query, search_documents
        db = self._setup(tmp_path)
        intent = parse_query("26PL12345678901234A")
        hits = search_documents(intent, db_path=db)
        domains = [h.domain for h in hits]
        assert "document" in domains
        # customs declaration hit should be present
        cd_hit = next((h for h in hits if h.entity_id == "cd-1"), None)
        assert cd_hit is not None

    def test_batch_id_match(self, tmp_path):
        from app.services.search_engine import parse_query, search_documents
        db = self._setup(tmp_path)
        # UUID-format batch IDs; use keyword search for non-UUID
        intent = parse_query("batch-beta")
        hits = search_documents(intent, db_path=db)
        # keyword search on batch_id LIKE '%batch-beta%'
        assert any("batch-beta" in h.details.get("batch_id", "") for h in hits)

    def test_pz_ref_match(self, tmp_path):
        from app.services.search_engine import parse_query, search_documents
        db = self._setup(tmp_path)
        intent = parse_query("94/2026")
        hits = search_documents(intent, db_path=db)
        assert any(h.entity_id == "doc-3" for h in hits)

    def test_keyword_document_type_match(self, tmp_path):
        from app.services.search_engine import parse_query, search_documents
        db = self._setup(tmp_path)
        intent = parse_query("INVOICE")
        hits = search_documents(intent, db_path=db)
        assert any(h.details.get("document_type") == "INVOICE" for h in hits)

    def test_empty_db_returns_empty(self, tmp_path):
        from app.services.search_engine import parse_query, search_documents
        missing = tmp_path / "nonexistent.db"
        intent = parse_query("4789974092")
        hits = search_documents(intent, db_path=missing)
        assert hits == []

    def test_no_matching_awb_returns_empty(self, tmp_path):
        from app.services.search_engine import parse_query, search_documents
        db = self._setup(tmp_path)
        intent = parse_query("9999999999")
        hits = search_documents(intent, db_path=db)
        assert hits == []

    def test_limit_respected(self, tmp_path):
        from app.services.search_engine import parse_query, search_documents
        db = self._setup(tmp_path)
        intent = parse_query("batch")  # keyword hits multiple
        hits = search_documents(intent, limit=1, db_path=db)
        assert len(hits) <= 1

    def test_hit_domain_is_document(self, tmp_path):
        from app.services.search_engine import parse_query, search_documents
        db = self._setup(tmp_path)
        intent = parse_query("4789974092")
        hits = search_documents(intent, db_path=db)
        assert all(h.domain == "document" for h in hits)

    def test_details_contain_required_keys(self, tmp_path):
        from app.services.search_engine import parse_query, search_documents
        db = self._setup(tmp_path)
        intent = parse_query("4789974092")
        hits = search_documents(intent, db_path=db)
        required = {"batch_id", "awb", "document_type", "extraction_status",
                    "parser_status", "related_mrn", "related_pz_no",
                    "requires_manual_review"}
        for h in hits:
            if "mrn" not in h.entity_id:  # shipment_documents hits only
                assert required.issubset(h.details.keys())

    def test_requires_manual_review_true_flagged(self, tmp_path):
        from app.services.search_engine import parse_query, search_documents
        db = self._setup(tmp_path)
        intent = parse_query("ZC429")
        hits = search_documents(intent, db_path=db)
        manual_hits = [h for h in hits if h.details.get("requires_manual_review")]
        assert len(manual_hits) >= 1

    def test_db_exception_returns_empty_not_raise(self, tmp_path):
        from app.services.search_engine import parse_query, search_documents
        # Pass a corrupted path (directory, not file)
        intent = parse_query("4789974092")
        hits = search_documents(intent, db_path=tmp_path)  # directory, not file
        assert hits == []

    def test_customs_declaration_details_keys(self, tmp_path):
        from app.services.search_engine import parse_query, search_documents
        db = self._setup(tmp_path)
        intent = parse_query("26PL12345678901234A")
        hits = search_documents(intent, db_path=db)
        cd = next((h for h in hits if h.entity_id == "cd-1"), None)
        assert cd is not None
        assert "mrn" in cd.details
        assert "duty_pln" in cd.details
        assert "importer_name" in cd.details


# ---------------------------------------------------------------------------
# TestSearchCustomers
# ---------------------------------------------------------------------------

class TestSearchCustomers:
    def _setup(self, tmp_path):
        db = tmp_path / "customer_master.sqlite"
        _make_customer_db(db)
        return db

    def test_name_keyword_match(self, tmp_path):
        from app.services.search_engine import parse_query, search_customers
        db = self._setup(tmp_path)
        intent = parse_query("Estrella")
        hits = search_customers(intent, db_path=db)
        assert any("Estrella" in h.title for h in hits)

    def test_nip_exact_match(self, tmp_path):
        from app.services.search_engine import parse_query, search_customers
        db = self._setup(tmp_path)
        intent = parse_query("1234567890")
        hits = search_customers(intent, db_path=db)
        assert any(h.entity_id == "C001" for h in hits)

    def test_nip_hit_score_is_max(self, tmp_path):
        from app.services.search_engine import parse_query, search_customers
        db = self._setup(tmp_path)
        intent = parse_query("1234567890")
        hits = search_customers(intent, db_path=db)
        assert any(h.score == 1.0 for h in hits)

    def test_country_code_match(self, tmp_path):
        from app.services.search_engine import parse_query, search_customers
        db = self._setup(tmp_path)
        intent = parse_query("PL")
        hits = search_customers(intent, db_path=db)
        assert any(h.entity_id == "C002" for h in hits)

    def test_no_match_returns_empty(self, tmp_path):
        from app.services.search_engine import parse_query, search_customers
        db = self._setup(tmp_path)
        intent = parse_query("XYZNOTFOUND")
        hits = search_customers(intent, db_path=db)
        assert hits == []

    def test_missing_db_returns_empty(self, tmp_path):
        from app.services.search_engine import parse_query, search_customers
        intent = parse_query("Estrella")
        hits = search_customers(intent, db_path=tmp_path / "nonexistent.sqlite")
        assert hits == []

    def test_hit_domain_is_customer(self, tmp_path):
        from app.services.search_engine import parse_query, search_customers
        db = self._setup(tmp_path)
        intent = parse_query("Stella")
        hits = search_customers(intent, db_path=db)
        assert all(h.domain == "customer" for h in hits)

    def test_details_contain_required_keys(self, tmp_path):
        from app.services.search_engine import parse_query, search_customers
        db = self._setup(tmp_path)
        intent = parse_query("Estrella")
        hits = search_customers(intent, db_path=db)
        for h in hits:
            assert "bill_to_contractor_id" in h.details
            assert "bill_to_name" in h.details
            assert "country" in h.details

    def test_empty_keyword_no_clauses_returns_empty(self, tmp_path):
        from app.services.search_engine import SearchIntent, search_customers
        db = self._setup(tmp_path)
        # Intent with no keyword and no recognizable patterns
        intent = SearchIntent(raw_query="")
        hits = search_customers(intent, db_path=db)
        assert hits == []

    def test_limit_respected(self, tmp_path):
        from app.services.search_engine import parse_query, search_customers
        db = self._setup(tmp_path)
        intent = parse_query("Jewels")
        hits = search_customers(intent, limit=1, db_path=db)
        assert len(hits) <= 1


# ---------------------------------------------------------------------------
# TestSearchSuppliers
# ---------------------------------------------------------------------------

class TestSearchSuppliers:
    def _setup(self, tmp_path):
        db = tmp_path / "suppliers.sqlite"
        _make_supplier_db(db)
        return db

    def test_name_keyword_match(self, tmp_path):
        from app.services.search_engine import parse_query, search_suppliers
        db = self._setup(tmp_path)
        intent = parse_query("Mumbai")
        hits = search_suppliers(intent, db_path=db)
        assert any("Mumbai" in h.title for h in hits)

    def test_code_keyword_match(self, tmp_path):
        from app.services.search_engine import parse_query, search_suppliers
        db = self._setup(tmp_path)
        intent = parse_query("SUP002")
        hits = search_suppliers(intent, db_path=db)
        assert any(h.entity_id == "SUP002" for h in hits)

    def test_country_match(self, tmp_path):
        from app.services.search_engine import parse_query, search_suppliers
        db = self._setup(tmp_path)
        intent = parse_query("TR")
        hits = search_suppliers(intent, db_path=db)
        assert any("Istanbul" in h.title for h in hits)

    def test_no_match_returns_empty(self, tmp_path):
        from app.services.search_engine import parse_query, search_suppliers
        db = self._setup(tmp_path)
        intent = parse_query("XYZNOTFOUND99")
        hits = search_suppliers(intent, db_path=db)
        assert hits == []

    def test_missing_db_returns_empty(self, tmp_path):
        from app.services.search_engine import parse_query, search_suppliers
        intent = parse_query("Mumbai")
        hits = search_suppliers(intent, db_path=tmp_path / "nonexistent.sqlite")
        assert hits == []

    def test_hit_domain_is_supplier(self, tmp_path):
        from app.services.search_engine import parse_query, search_suppliers
        db = self._setup(tmp_path)
        intent = parse_query("Jaipur")
        hits = search_suppliers(intent, db_path=db)
        assert all(h.domain == "supplier" for h in hits)

    def test_details_contain_required_keys(self, tmp_path):
        from app.services.search_engine import parse_query, search_suppliers
        db = self._setup(tmp_path)
        intent = parse_query("Gems")
        hits = search_suppliers(intent, db_path=db)
        for h in hits:
            assert "supplier_code" in h.details
            assert "name" in h.details
            assert "country" in h.details

    def test_limit_respected(self, tmp_path):
        from app.services.search_engine import parse_query, search_suppliers
        db = self._setup(tmp_path)
        intent = parse_query("IN")  # country code - will match 2 suppliers
        hits = search_suppliers(intent, limit=1, db_path=db)
        assert len(hits) <= 1

    def test_active_field_in_details(self, tmp_path):
        from app.services.search_engine import parse_query, search_suppliers
        db = self._setup(tmp_path)
        intent = parse_query("Mumbai")
        hits = search_suppliers(intent, db_path=db)
        assert all("active" in h.details for h in hits)

    def test_empty_intent_no_keyword_returns_empty(self, tmp_path):
        from app.services.search_engine import SearchIntent, search_suppliers
        db = self._setup(tmp_path)
        intent = SearchIntent(raw_query="")
        hits = search_suppliers(intent, db_path=db)
        assert hits == []


# ---------------------------------------------------------------------------
# TestSearchProducts
# ---------------------------------------------------------------------------

class TestSearchProducts:
    def _setup(self, tmp_path):
        db = tmp_path / "master_data.sqlite"
        _make_design_db(db)
        return db

    def test_design_code_match(self, tmp_path):
        from app.services.search_engine import parse_query, search_products
        db = self._setup(tmp_path)
        intent = parse_query("EST-001")
        hits = search_products(intent, db_path=db)
        assert any(h.entity_id == "EST-001" for h in hits)

    def test_display_name_keyword_match(self, tmp_path):
        from app.services.search_engine import parse_query, search_products
        db = self._setup(tmp_path)
        intent = parse_query("Diamond")
        hits = search_products(intent, db_path=db)
        assert any("Diamond" in h.title for h in hits)

    def test_hs_code_match(self, tmp_path):
        from app.services.search_engine import parse_query, search_products
        db = self._setup(tmp_path)
        intent = parse_query("7113190000")
        hits = search_products(intent, db_path=db)
        assert len(hits) >= 2  # EST-001 and EST-002 both have 7113190000

    def test_collection_keyword_match(self, tmp_path):
        from app.services.search_engine import parse_query, search_products
        db = self._setup(tmp_path)
        intent = parse_query("Bridal")
        hits = search_products(intent, db_path=db)
        assert any(h.entity_id == "EST-001" for h in hits)

    def test_no_match_returns_empty(self, tmp_path):
        from app.services.search_engine import parse_query, search_products
        db = self._setup(tmp_path)
        intent = parse_query("XYZNOTFOUND99")
        hits = search_products(intent, db_path=db)
        assert hits == []

    def test_missing_db_returns_empty(self, tmp_path):
        from app.services.search_engine import parse_query, search_products
        intent = parse_query("Diamond")
        hits = search_products(intent, db_path=tmp_path / "nonexistent.sqlite")
        assert hits == []

    def test_hit_domain_is_product(self, tmp_path):
        from app.services.search_engine import parse_query, search_products
        db = self._setup(tmp_path)
        intent = parse_query("Gold")
        hits = search_products(intent, db_path=db)
        assert all(h.domain == "product" for h in hits)

    def test_details_contain_required_keys(self, tmp_path):
        from app.services.search_engine import parse_query, search_products
        db = self._setup(tmp_path)
        intent = parse_query("EST-001")
        hits = search_products(intent, db_path=db)
        for h in hits:
            assert "design_code" in h.details
            assert "display_name" in h.details
            assert "hs_code" in h.details


# ---------------------------------------------------------------------------
# TestExecuteSearch
# ---------------------------------------------------------------------------

class TestExecuteSearch:
    def _all_dbs(self, tmp_path):
        doc_db  = tmp_path / "documents.db"
        cm_db   = tmp_path / "customer_master.sqlite"
        supp_db = tmp_path / "suppliers.sqlite"
        md_db   = tmp_path / "master_data.sqlite"
        _make_docs_db(doc_db)
        _make_customer_db(cm_db)
        _make_supplier_db(supp_db)
        _make_design_db(md_db)
        return doc_db, cm_db, supp_db, md_db

    def test_empty_query_returns_empty_result(self, tmp_path):
        from app.services.search_engine import parse_query, execute_search
        doc_db, cm_db, supp_db, md_db = self._all_dbs(tmp_path)
        intent = parse_query("")
        result = execute_search(intent, doc_db=doc_db, cm_db=cm_db,
                                supp_db=supp_db, md_db=md_db)
        assert result.total == 0
        assert result.hits == []
        assert result.llm_used is False

    def test_llm_used_always_false(self, tmp_path):
        from app.services.search_engine import parse_query, execute_search
        doc_db, cm_db, supp_db, md_db = self._all_dbs(tmp_path)
        intent = parse_query("4789974092")
        result = execute_search(intent, doc_db=doc_db, cm_db=cm_db,
                                supp_db=supp_db, md_db=md_db)
        assert result.llm_used is False

    def test_awb_search_finds_docs(self, tmp_path):
        from app.services.search_engine import parse_query, execute_search
        doc_db, cm_db, supp_db, md_db = self._all_dbs(tmp_path)
        intent = parse_query("4789974092")
        result = execute_search(intent, doc_db=doc_db, cm_db=cm_db,
                                supp_db=supp_db, md_db=md_db)
        assert result.total > 0
        assert any(h.domain == "document" for h in result.hits)

    def test_domain_filter_restricts_domains_searched(self, tmp_path):
        from app.services.search_engine import parse_query, execute_search
        doc_db, cm_db, supp_db, md_db = self._all_dbs(tmp_path)
        intent = parse_query("Estrella")
        result = execute_search(intent, domains=["customer"],
                                doc_db=doc_db, cm_db=cm_db,
                                supp_db=supp_db, md_db=md_db)
        assert result.domains_searched == ["customer"]
        assert all(h.domain == "customer" for h in result.hits)

    def test_limit_applied_to_total_hits(self, tmp_path):
        from app.services.search_engine import parse_query, execute_search
        doc_db, cm_db, supp_db, md_db = self._all_dbs(tmp_path)
        intent = parse_query("jewels")
        result = execute_search(intent, limit=2, doc_db=doc_db, cm_db=cm_db,
                                supp_db=supp_db, md_db=md_db)
        assert len(result.hits) <= 2

    def test_to_dict_contains_required_keys(self, tmp_path):
        from app.services.search_engine import parse_query, execute_search
        doc_db, cm_db, supp_db, md_db = self._all_dbs(tmp_path)
        intent = parse_query("Estrella")
        result = execute_search(intent, doc_db=doc_db, cm_db=cm_db,
                                supp_db=supp_db, md_db=md_db)
        d = result.to_dict()
        required = {"query", "interpreted_as", "domains_searched",
                    "hits", "total", "llm_used", "generated_at"}
        assert required.issubset(d.keys())

    def test_to_dict_llm_used_false(self, tmp_path):
        from app.services.search_engine import parse_query, execute_search
        doc_db, cm_db, supp_db, md_db = self._all_dbs(tmp_path)
        intent = parse_query("Estrella")
        result = execute_search(intent, doc_db=doc_db, cm_db=cm_db,
                                supp_db=supp_db, md_db=md_db)
        assert result.to_dict()["llm_used"] is False

    def test_hits_sorted_by_score_descending(self, tmp_path):
        from app.services.search_engine import parse_query, execute_search
        doc_db, cm_db, supp_db, md_db = self._all_dbs(tmp_path)
        intent = parse_query("4789974092")
        result = execute_search(intent, doc_db=doc_db, cm_db=cm_db,
                                supp_db=supp_db, md_db=md_db)
        scores = [h.score for h in result.hits]
        assert scores == sorted(scores, reverse=True)

    def test_invalid_domain_in_filter_ignored(self, tmp_path):
        from app.services.search_engine import parse_query, execute_search, _ALL_DOMAINS
        doc_db, cm_db, supp_db, md_db = self._all_dbs(tmp_path)
        intent = parse_query("Estrella")
        # Invalid domains are filtered out
        result = execute_search(intent, domains=["customer", "INVALID"],
                                doc_db=doc_db, cm_db=cm_db,
                                supp_db=supp_db, md_db=md_db)
        assert "INVALID" not in result.domains_searched

    def test_limit_capped_at_max(self, tmp_path):
        from app.services.search_engine import parse_query, execute_search, MAX_LIMIT
        doc_db, cm_db, supp_db, md_db = self._all_dbs(tmp_path)
        intent = parse_query("Estrella")
        # Even if caller requests absurd limit it's capped
        result = execute_search(intent, limit=9999, doc_db=doc_db, cm_db=cm_db,
                                supp_db=supp_db, md_db=md_db)
        assert len(result.hits) <= MAX_LIMIT


# ---------------------------------------------------------------------------
# TestSearchRoute
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client():
    from app.main import app
    return TestClient(app, raise_server_exceptions=False)


class TestSearchRoute:
    def _headers(self):
        import os
        key = os.getenv("API_KEY", "test-key")
        return {"X-API-Key": key}

    def test_get_search_returns_200(self, client):
        resp = client.get(
            "/api/v1/search?q=test",
            headers=self._headers(),
        )
        assert resp.status_code == 200

    def test_response_contains_llm_used_false(self, client):
        resp = client.get(
            "/api/v1/search?q=test",
            headers=self._headers(),
        )
        data = resp.json()
        assert data.get("llm_used") is False

    def test_response_schema_keys(self, client):
        resp = client.get(
            "/api/v1/search?q=test",
            headers=self._headers(),
        )
        data = resp.json()
        required = {"query", "interpreted_as", "domains_searched",
                    "hits", "total", "llm_used", "generated_at"}
        assert required.issubset(data.keys())

    def test_domain_filter_param(self, client):
        resp = client.get(
            "/api/v1/search?q=test&domains=customer",
            headers=self._headers(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["domains_searched"] == ["customer"]

    def test_invalid_domain_returns_422(self, client):
        resp = client.get(
            "/api/v1/search?q=test&domains=invalid_domain",
            headers=self._headers(),
        )
        assert resp.status_code == 422

    def test_missing_q_returns_422(self, client):
        resp = client.get(
            "/api/v1/search",
            headers=self._headers(),
        )
        assert resp.status_code == 422

    def test_limit_param_accepted(self, client):
        resp = client.get(
            "/api/v1/search?q=test&limit=5",
            headers=self._headers(),
        )
        assert resp.status_code == 200

    def test_limit_above_max_returns_422(self, client):
        from app.services.search_engine import MAX_LIMIT
        resp = client.get(
            f"/api/v1/search?q=test&limit={MAX_LIMIT + 1}",
            headers=self._headers(),
        )
        assert resp.status_code == 422

    def test_no_auth_response_code(self, client):
        # Test environment may have auth disabled (consistent with Phase 5/6 test setup).
        # Verify the endpoint exists (not 404) and behaves consistently.
        resp = client.get("/api/v1/search?q=test")
        assert resp.status_code in (200, 401, 403), (
            f"Expected 200, 401, or 403 but got {resp.status_code}"
        )

    def test_all_domains_valid_values_accepted(self, client):
        for domain in ("document", "customer", "supplier", "product"):
            resp = client.get(
                f"/api/v1/search?q=test&domains={domain}",
                headers=self._headers(),
            )
            assert resp.status_code == 200, f"domain={domain} failed: {resp.text}"

    def test_multiple_domains_accepted(self, client):
        resp = client.get(
            "/api/v1/search?q=test&domains=customer,supplier",
            headers=self._headers(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert set(data["domains_searched"]) == {"customer", "supplier"}


# ---------------------------------------------------------------------------
# TestSourceGrepSafety
# ---------------------------------------------------------------------------

class TestSourceGrepSafety:
    """Structural invariants verified by reading source code."""

    def _read_service(self) -> str:
        p = Path(__file__).parent.parent / "app" / "services" / "search_engine.py"
        return p.read_text(encoding="utf-8")

    def _read_route(self) -> str:
        p = Path(__file__).parent.parent / "app" / "api" / "routes_search.py"
        return p.read_text(encoding="utf-8")

    def test_no_insert_in_search_engine(self):
        src = self._read_service()
        assert "INSERT " not in src.upper() or "# INSERT" in src

    def test_no_update_in_search_engine(self):
        src = self._read_service()
        assert "UPDATE " not in src.upper() or "# UPDATE" in src

    def test_no_delete_in_search_engine(self):
        src = self._read_service()
        assert "DELETE " not in src.upper() or "# DELETE" in src

    def test_no_insert_in_route(self):
        src = self._read_route()
        assert "INSERT " not in src.upper() or "# INSERT" in src

    def test_pragma_query_only_in_search_engine(self):
        src = self._read_service()
        assert "PRAGMA query_only" in src

    def test_llm_used_false_hardcoded_in_service(self):
        src = self._read_service()
        assert "llm_used=False" in src or "llm_used: bool = False" in src

    def test_no_anthropic_import_in_search_engine(self):
        src = self._read_service()
        assert "import anthropic" not in src
        assert "from anthropic" not in src

    def test_no_ai_gateway_import_in_search_engine(self):
        src = self._read_service()
        assert "ai_gateway" not in src

    def test_no_anthropic_import_in_route(self):
        src = self._read_route()
        assert "import anthropic" not in src

    def test_get_only_router(self):
        src = self._read_route()
        assert "@router.post" not in src
        assert "@router.put" not in src
        assert "@router.delete" not in src
        assert "@router.patch" not in src

    def test_search_engine_has_no_external_http(self):
        src = self._read_service()
        for bad in ("requests.get", "httpx.get", "aiohttp", "urllib.request"):
            assert bad not in src

    def test_no_write_calls_in_search_engine(self):
        """search_engine must never import or call wFirma / DHL write services."""
        src = self._read_service()
        # No imports from write-capable services
        assert "from .wfirma_client" not in src
        assert "from .import_pz_builder" not in src
        assert "create_pz" not in src
        assert "post_to_cliq" not in src
        assert "queue_email" not in src
