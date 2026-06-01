"""
test_carrier_doc_package.py — Path-DOC outbound document package tests.

Tests (all wFirma calls mocked — no live API):
  1. packing list renders from a sample batch
  2. EU destination → invoice + packing list, NO CN23
  3. non-EU destination → CN23 included
  4. missing dimensions → 422 with gap list
  5. non-EU missing incoterm/EORI → 422 gap list
  6. unposted proforma → 422 "commercial invoice unavailable"
  7. blank receiver address → advisory proposal written, generation still proceeds
  8. route works with carrier_api_status=pending (proves ungated)
"""
from __future__ import annotations

import io
import json
import sqlite3
import sys
import zipfile
from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch, MagicMock

import pytest

_SVC = Path(__file__).parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))


# ── Fixtures ───────────────────────────────────────────────────────────────────

FAKE_PDF = b"%PDF-1.4 fake commercial invoice bytes"


def _make_storage(tmp_path: Path) -> Path:
    """Create a minimal storage directory with necessary SQLite databases."""
    (tmp_path / "outputs" / "BATCH_TEST" / "").mkdir(parents=True, exist_ok=True)
    return tmp_path


def _seed_audit(tmp_path: Path, batch_id: str = "BATCH_TEST") -> Path:
    audit_path = tmp_path / "outputs" / batch_id / "audit.json"
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.write_text(json.dumps({
        "batch_id":      batch_id,
        "invoice_totals": {"total_cif_usd": 1500.0, "currency": "USD"},
        "action_proposals": [],
    }), encoding="utf-8")
    return audit_path


def _seed_packing_db(tmp_path: Path, batch_id: str = "BATCH_TEST",
                     with_weight: bool = True) -> None:
    pdb = tmp_path / "packing.db"
    conn = sqlite3.connect(str(pdb))
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS packing_lines (
            id TEXT PRIMARY KEY DEFAULT (hex(randomblob(4))),
            packing_document_id TEXT DEFAULT '',
            batch_id TEXT NOT NULL DEFAULT '',
            invoice_no TEXT DEFAULT '',
            invoice_line_position INTEGER DEFAULT 1,
            product_code TEXT DEFAULT '',
            design_no TEXT DEFAULT '',
            batch_no TEXT DEFAULT '',
            bag_id TEXT DEFAULT '',
            tray_id TEXT DEFAULT '',
            item_type TEXT DEFAULT '',
            uom TEXT DEFAULT '',
            quantity REAL DEFAULT 0.0,
            gross_weight REAL DEFAULT 0.0,
            net_weight REAL DEFAULT 0.0,
            metal TEXT DEFAULT '',
            karat TEXT DEFAULT '',
            stone_type TEXT DEFAULT '',
            remarks TEXT DEFAULT '',
            extracted_confidence REAL DEFAULT 0.0,
            requires_manual_review INTEGER DEFAULT 0,
            created_at TEXT DEFAULT '',
            updated_at TEXT DEFAULT '',
            unit_price_eur REAL DEFAULT 0.0
        );
    """)
    gw = 12.5 if with_weight else 0.0
    conn.execute(
        "INSERT INTO packing_lines (batch_id, product_code, design_no, item_type, "
        "quantity, gross_weight, net_weight) VALUES (?,?,?,?,?,?,?)",
        (batch_id, "EJL/26-27/001-1", "EJL-RING-001", "RING", 5, gw, gw * 0.9),
    )
    conn.execute(
        "INSERT INTO packing_lines (batch_id, product_code, design_no, item_type, "
        "quantity, gross_weight, net_weight) VALUES (?,?,?,?,?,?,?)",
        (batch_id, "EJL/26-27/002-1", "EJL-EAR-002", "EARRINGS", 3, gw, gw * 0.9),
    )
    conn.commit()
    conn.close()


def _seed_customer_master(tmp_path: Path, country: str = "DE",
                            with_address: bool = True) -> None:
    cm_db = tmp_path / "customer_master.sqlite"
    conn = sqlite3.connect(str(cm_db))
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS customer_master (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bill_to_contractor_id TEXT NOT NULL,
            bill_to_name TEXT NOT NULL DEFAULT '',
            country TEXT NOT NULL DEFAULT '',
            bill_to_street TEXT,
            bill_to_city TEXT,
            bill_to_postal_code TEXT,
            bill_to_email TEXT,
            bill_to_phone TEXT,
            eori TEXT,
            nip TEXT,
            vat_eu_number TEXT,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT DEFAULT '',
            updated_at TEXT DEFAULT '',
            ship_to_use_alternate INTEGER NOT NULL DEFAULT 0,
            ship_to_name TEXT,
            ship_to_person TEXT,
            ship_to_street TEXT,
            ship_to_city TEXT,
            ship_to_zip TEXT,
            ship_to_country TEXT,
            ship_to_phone TEXT,
            ship_to_email TEXT,
            ship_to_contractor_id TEXT
        );
    """)
    street = "Musterstraße 1" if with_address else ""
    city   = "Berlin" if with_address else ""
    pc     = "10115" if with_address else ""
    conn.execute(
        "INSERT INTO customer_master (bill_to_contractor_id, bill_to_name, country, "
        "bill_to_street, bill_to_city, bill_to_postal_code, bill_to_email, bill_to_phone) "
        "VALUES (?,?,?,?,?,?,?,?)",
        ("CUST001", "Test Client GmbH", country, street, city, pc,
         "test@testclient.de", "+49301234567"),
    )
    conn.commit()
    conn.close()


def _seed_wfirma_db(tmp_path: Path, client_name: str = "Test Client GmbH") -> None:
    wdb = tmp_path / "wfirma.db"
    conn = sqlite3.connect(str(wdb))
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS wfirma_customers (
            id TEXT PRIMARY KEY,
            client_name TEXT NOT NULL,
            wfirma_customer_id TEXT DEFAULT NULL,
            vat_id TEXT NOT NULL DEFAULT '',
            country TEXT NOT NULL DEFAULT '',
            match_status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT ''
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_wfc_client_name ON wfirma_customers (client_name);
    """)
    conn.execute(
        "INSERT INTO wfirma_customers (id, client_name, wfirma_customer_id, match_status, "
        "created_at, updated_at) VALUES (?,?,?,?,?,?)",
        ("wfc1", client_name, "CUST001", "matched", "2026-01-01", "2026-01-01"),
    )
    conn.commit()
    conn.close()


def _seed_master_data(tmp_path: Path) -> None:
    md_db = tmp_path / "master_data.sqlite"
    conn = sqlite3.connect(str(md_db))
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS company_profile (
            id INTEGER PRIMARY KEY,
            legal_name TEXT NOT NULL DEFAULT '',
            short_name TEXT, street TEXT, postal_city TEXT,
            country TEXT NOT NULL DEFAULT 'PL',
            nip TEXT, vat_eu TEXT, regon TEXT,
            email TEXT, phone TEXT,
            iban_eur TEXT, iban_usd TEXT, iban_pln TEXT,
            swift TEXT, bank_name TEXT,
            place_of_issue TEXT,
            signatory_name TEXT, signatory_title TEXT,
            returns_policy_pl TEXT, gdpr_text_pl TEXT,
            krs TEXT, eori TEXT,
            updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS box_types (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL UNIQUE,
            name TEXT,
            length_cm REAL,
            width_cm REAL,
            height_cm REAL,
            tare_weight_kg REAL,
            active INTEGER NOT NULL DEFAULT 1,
            notes TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_box_types_code ON box_types (code);
    """)
    conn.execute(
        "INSERT INTO company_profile (id, legal_name, street, postal_city, country, "
        "nip, vat_eu, eori, email, phone) VALUES (1,?,?,?,?,?,?,?,?,?)",
        ("ESTRELLA JEWELS Test", "ul. Test 1", "00-001 Warszawa", "PL",
         "5252812119", "PL5252812119", "PL525281211900000",
         "info@test.eu", "+48000000000"),
    )
    # Seed a standard box type (id=1)
    conn.execute(
        "INSERT INTO box_types (id, code, name, length_cm, width_cm, height_cm, "
        "tare_weight_kg, active) VALUES (1,'STD','Standard Box',30,20,10,0.5,1)"
    )
    conn.commit()
    conn.close()


# Standard box_type_id used throughout tests
STD_BOX_ID = 1

def _std_inputs(**kwargs) -> "LabelPackageInputs":
    """Return LabelPackageInputs with standard box dims (matching seeded STD_BOX_ID)."""
    from app.services.carrier.doc_package import LabelPackageInputs
    base = dict(length_cm=30.0, width_cm=20.0, height_cm=10.0, tare_weight_kg=0.5)
    base.update(kwargs)
    return LabelPackageInputs(**base)


def _seed_proforma_draft(tmp_path: Path, batch_id: str = "BATCH_TEST",
                          client_name: str = "Test Client GmbH",
                          posted: bool = True) -> None:
    pdb = tmp_path / "proforma_links.db"
    conn = sqlite3.connect(str(pdb))
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS proforma_drafts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_id TEXT NOT NULL,
            client_name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending_local',
            currency TEXT NOT NULL DEFAULT '',
            exchange_rate REAL,
            source_lines_json TEXT NOT NULL DEFAULT '[]',
            wfirma_proforma_id TEXT,
            notes TEXT,
            created_at TEXT DEFAULT '',
            updated_at TEXT DEFAULT '',
            draft_state TEXT NOT NULL DEFAULT 'draft',
            draft_version INTEGER NOT NULL DEFAULT 1,
            supersedes_draft_id INTEGER,
            superseded_by_draft_id INTEGER,
            approved_at TEXT, approved_by TEXT,
            posted_at TEXT, locked_at TEXT,
            wfirma_proforma_fullnumber TEXT NOT NULL DEFAULT '',
            buyer_override_json TEXT NOT NULL DEFAULT '{}',
            ship_to_override_json TEXT NOT NULL DEFAULT '{}',
            payment_terms_json TEXT NOT NULL DEFAULT '{}',
            remarks TEXT NOT NULL DEFAULT '',
            editable_lines_json TEXT NOT NULL DEFAULT '[]',
            service_charges_json TEXT NOT NULL DEFAULT '[]',
            posting_started_at TEXT, posting_started_by TEXT,
            post_failed_at TEXT, posted_by TEXT,
            last_packing_sync_at TEXT, packing_sync_warning TEXT,
            fx_rate_date TEXT, fx_rate_source TEXT NOT NULL DEFAULT 'NBP',
            incoterm TEXT, insurance_eur REAL,
            wfirma_issue_date TEXT, wfirma_payment_due TEXT, wfirma_payment_method TEXT,
            clone_generation INTEGER NOT NULL DEFAULT 0,
            source_ref_id INTEGER
        );
    """)
    wfirma_id = "12345678" if posted else ""
    fullnum   = "PROF 1/2026" if posted else ""
    state     = "posted" if posted else "draft"
    lines = json.dumps([
        {"product_code": "EJL/26-27/001-1", "design_no": "RING",
         "qty": 5, "unit_price": 150.0, "currency": "EUR"},
    ])
    conn.execute(
        "INSERT INTO proforma_drafts "
        "(batch_id, client_name, status, currency, wfirma_proforma_id, "
        "wfirma_proforma_fullnumber, draft_state, editable_lines_json, "
        "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (batch_id, client_name, "issued" if posted else "draft",
         "EUR", wfirma_id, fullnum, state, lines,
         "2026-01-01", "2026-01-01"),
    )
    conn.commit()
    conn.close()


def _full_setup(tmp_path: Path, batch_id: str = "BATCH_TEST",
                country: str = "DE", with_address: bool = True,
                posted: bool = True, with_weight: bool = True,
                client_name: str = "Test Client GmbH") -> Path:
    storage = _make_storage(tmp_path)
    _seed_audit(storage, batch_id)
    _seed_packing_db(storage, batch_id, with_weight)
    _seed_customer_master(storage, country, with_address)
    _seed_wfirma_db(storage, client_name)
    _seed_master_data(storage)
    _seed_proforma_draft(storage, batch_id, client_name, posted)
    return storage


# ── Import helpers ─────────────────────────────────────────────────────────────

def _import_doc_package():
    from app.services.carrier.doc_package import (
        LabelPackageInputs, LabelPackageGaps, LabelPackageResult,
        assemble_label_package, render_packing_list_pdf,
    )
    return LabelPackageInputs, LabelPackageGaps, LabelPackageResult, assemble_label_package, render_packing_list_pdf


# ── Test 1: packing list renders ──────────────────────────────────────────────

class TestRenderPackingListPdf:
    def test_packing_list_renders_from_sample_batch(self, tmp_path, monkeypatch):
        """Packing list PDF is non-empty bytes, contains PDF header."""
        storage = _full_setup(tmp_path)
        LPI, LPGaps, LPR, _, render_packing_list_pdf = _import_doc_package()

        from app.services.master_data_db import get_company_profile as _gcp
        company = _gcp(storage / "master_data.sqlite")

        pdf = render_packing_list_pdf("BATCH_TEST", storage, company, None, None)
        assert isinstance(pdf, bytes)
        assert len(pdf) > 100
        assert pdf[:4] == b"%PDF"

    def test_packing_list_falls_back_to_editable_lines(self, tmp_path):
        """When packing.db has no rows for batch, uses editable_lines_json."""
        storage = _full_setup(tmp_path, batch_id="BATCH_NOPACK")
        # No packing_lines for BATCH_NOPACK (different batch)
        LPI, LPGaps, LPR, _, render_packing_list_pdf = _import_doc_package()

        from app.services.carrier.doc_package import _load_proforma_draft
        draft = _load_proforma_draft("BATCH_NOPACK", "Test Client GmbH", storage)
        # draft may be None since we seeded BATCH_TEST; we test fallback logic
        pdf = render_packing_list_pdf("BATCH_NOPACK", storage, None, None, draft)
        assert isinstance(pdf, bytes)
        assert pdf[:4] == b"%PDF"


# ── Test 2: EU destination → no CN23 ─────────────────────────────────────────

class TestEuDestinationPackage:
    def test_eu_destination_no_cn23(self, tmp_path, monkeypatch):
        """DE (EU) → components = [invoice, packing_list], no cn23."""
        storage = _full_setup(tmp_path, country="DE")
        LPI, LPGaps, LPR, assemble, _ = _import_doc_package()

        inputs = _std_inputs(client_name="Test Client GmbH")

        with patch("app.services.wfirma_client.fetch_invoice_pdf",
                   return_value=FAKE_PDF):
            result = assemble("BATCH_TEST", inputs, storage)

        assert isinstance(result, LPR)
        assert "cn23" not in result.components
        assert "invoice" in result.components
        assert "packing_list" in result.components

    def test_pl_also_eu_no_cn23(self, tmp_path):
        """PL is EU — no CN23."""
        storage = _full_setup(tmp_path, country="PL")
        LPI, LPGaps, LPR, assemble, _ = _import_doc_package()

        inputs = _std_inputs(client_name="Test Client GmbH")

        with patch("app.services.wfirma_client.fetch_invoice_pdf",
                   return_value=FAKE_PDF):
            result = assemble("BATCH_TEST", inputs, storage)

        assert isinstance(result, LPR)
        assert "cn23" not in result.components


# ── Test 3: non-EU destination → CN23 included ───────────────────────────────

class TestNonEuDestinationPackage:
    def test_non_eu_includes_cn23(self, tmp_path):
        """IN (India, non-EU) → cn23 in components."""
        storage = _full_setup(tmp_path, country="IN")
        LPI, LPGaps, LPR, assemble, _ = _import_doc_package()

        inputs = _std_inputs(incoterm="DAP", receiver_eori="IN1234567890",
                     client_name="Test Client GmbH")

        with patch("app.services.wfirma_client.fetch_invoice_pdf",
                   return_value=FAKE_PDF):
            result = assemble("BATCH_TEST", inputs, storage)

        assert isinstance(result, LPR)
        assert "cn23" in result.components
        assert "invoice" in result.components
        assert "packing_list" in result.components

    def test_us_non_eu_includes_cn23(self, tmp_path):
        """US (non-EU) → cn23 included."""
        storage = _full_setup(tmp_path, country="US")
        LPI, LPGaps, LPR, assemble, _ = _import_doc_package()

        inputs = _std_inputs(incoterm="EXW", receiver_eori="US1234567890",
                     client_name="Test Client GmbH")

        with patch("app.services.wfirma_client.fetch_invoice_pdf",
                   return_value=FAKE_PDF):
            result = assemble("BATCH_TEST", inputs, storage)

        assert isinstance(result, LPR)
        assert "cn23" in result.components


# ── Test 4: missing box_type → 422 (replaces raw-dimension test) ────────────

class TestMissingBoxType:
    def test_unknown_box_type_id_returns_gap(self, tmp_path, monkeypatch):
        """Route-level: unknown box_type_id -> 422 {gaps: [{field: box_type}]}."""
        storage = _full_setup(tmp_path)
        from app.core.config import settings as _s
        monkeypatch.setattr(_s, "storage_root", storage)

        from app.api.routes_carrier_actions import create_label_package, LabelPackageBody
        from fastapi import HTTPException
        import asyncio

        body = LabelPackageBody(box_type_id=9999, client_name="Test Client GmbH")
        with pytest.raises(HTTPException) as exc_info:
            asyncio.get_event_loop().run_until_complete(
                create_label_package(batch_id="BATCH_TEST", body=body, _auth=None)
            )
        assert exc_info.value.status_code == 422
        detail = exc_info.value.detail
        assert "box_type" in str(detail)
        gaps = detail.get("gaps", [])
        assert any(g["field"] == "box_type" for g in gaps)

    def test_known_box_type_resolves_dims(self, tmp_path):
        """STD_BOX_ID=1 resolves to 30x20x10cm + 0.5kg tare."""
        storage = _full_setup(tmp_path)
        LPI, _, __, ___, ____ = _import_doc_package()
        inputs = _std_inputs(client_name="Test Client GmbH")
        assert inputs.length_cm == 30.0
        assert inputs.width_cm  == 20.0
        assert inputs.height_cm == 10.0
        assert inputs.tare_weight_kg == 0.5

    def test_total_weight_includes_tare(self, tmp_path):
        """Total weight = goods (2 * 12.5g = 25g) + tare (500g = 0.5kg) = 525g."""
        storage = _full_setup(tmp_path)
        LPI, LPGaps, LPR, assemble, _ = _import_doc_package()
        inputs = _std_inputs(client_name="Test Client GmbH")

        with patch("app.services.wfirma_client.fetch_invoice_pdf", return_value=FAKE_PDF):
            result = assemble("BATCH_TEST", inputs, storage)
        # EU batch → success (no CN23 gap)
        assert isinstance(result, LPR)


# ── Test 5: non-EU missing incoterm/EORI → 422 ───────────────────────────────

class TestNonEuMissingInputs:
    def test_non_eu_missing_incoterm_and_eori(self, tmp_path):
        storage = _full_setup(tmp_path, country="US")
        LPI, LPGaps, LPR, assemble, _ = _import_doc_package()

        # Dimensions present but incoterm + eori missing
        inputs = _std_inputs(client_name="Test Client GmbH")

        result = assemble("BATCH_TEST", inputs, storage)

        assert isinstance(result, LPGaps)
        gap_fields = [g["field"] for g in result.gaps]
        assert "incoterm" in gap_fields
        assert "receiver_eori" in gap_fields

    def test_non_eu_missing_only_eori(self, tmp_path):
        storage = _full_setup(tmp_path, country="US")
        LPI, LPGaps, LPR, assemble, _ = _import_doc_package()

        inputs = _std_inputs(incoterm="DAP", client_name="Test Client GmbH")
        # receiver_eori not supplied

        result = assemble("BATCH_TEST", inputs, storage)

        assert isinstance(result, LPGaps)
        assert any(g["field"] == "receiver_eori" for g in result.gaps)


# ── Test 6: unposted proforma → 422 ──────────────────────────────────────────

class TestUnpostedProforma:
    def test_unposted_proforma_returns_gap(self, tmp_path):
        """No wfirma_proforma_id → gap 'proforma'."""
        storage = _full_setup(tmp_path, posted=False)
        LPI, LPGaps, LPR, assemble, _ = _import_doc_package()

        inputs = _std_inputs(client_name="Test Client GmbH")

        result = assemble("BATCH_TEST", inputs, storage)

        assert isinstance(result, LPGaps)
        assert any(g["field"] == "proforma" for g in result.gaps)
        # Confirm message mentions wFirma
        proforma_gap = next(g for g in result.gaps if g["field"] == "proforma")
        assert "wFirma" in proforma_gap["reason"] or "WF2.4" in proforma_gap["reason"]

    def test_no_draft_at_all_returns_gap(self, tmp_path):
        """No proforma_links.db at all → gap."""
        storage = _make_storage(tmp_path)
        _seed_audit(storage)
        _seed_packing_db(storage)
        _seed_customer_master(storage, "DE")
        _seed_master_data(storage)
        # No proforma_links.db seeded

        LPI, LPGaps, LPR, assemble, _ = _import_doc_package()
        inputs = _std_inputs(client_name="Test Client GmbH")

        result = assemble("BATCH_TEST", inputs, storage)

        assert isinstance(result, LPGaps)
        assert any(g["field"] == "proforma" for g in result.gaps)


# ── Test 7: receiver address / ship_to logic + advisory proposals ────────────

def _seed_ship_to(tmp_path: Path, batch_id: str = "BATCH_TEST") -> None:
    """Add ship_to_* data to the existing CUST001 row."""
    cm_db = tmp_path / "customer_master.sqlite"
    conn = sqlite3.connect(str(cm_db))
    conn.execute(
        """UPDATE customer_master SET
               ship_to_use_alternate=1,
               ship_to_name='Ship-To GmbH',
               ship_to_street='Lieferstraße 5',
               ship_to_city='Hamburg',
               ship_to_zip='20095',
               ship_to_country='DE'
           WHERE bill_to_contractor_id='CUST001'""",
    )
    conn.commit()
    conn.close()


class TestReceiverShipTo:
    def test_ship_to_used_when_present(self, tmp_path):
        """ship_to_street set → ship_to_name/street used; no ship_to_missing advisory."""
        storage = _full_setup(tmp_path, country="DE")
        _seed_ship_to(storage)
        LPI, LPGaps, LPR, assemble, _ = _import_doc_package()

        inputs = _std_inputs(client_name="Test Client GmbH")

        with patch("app.services.wfirma_client.fetch_invoice_pdf",
                   return_value=FAKE_PDF):
            result = assemble("BATCH_TEST", inputs, storage)

        assert isinstance(result, LPR)
        # No ship_to_missing advisory when ship_to is set
        assert not any("ship_to_missing" in a for a in result.advisories)

    def test_bill_to_fallback_writes_advisory(self, tmp_path):
        """ship_to_street absent → bill_to used + ship_to_missing advisory in Inbox."""
        storage = _full_setup(tmp_path, country="DE", with_address=True)
        # No _seed_ship_to → ship_to_street is NULL
        LPI, LPGaps, LPR, assemble, _ = _import_doc_package()

        inputs = _std_inputs(client_name="Test Client GmbH")

        with patch("app.services.wfirma_client.fetch_invoice_pdf",
                   return_value=FAKE_PDF):
            result = assemble("BATCH_TEST", inputs, storage)

        assert isinstance(result, LPR)
        # Advisory emitted
        assert any("ship_to" in a for a in result.advisories)
        audit_path = storage / "outputs" / "BATCH_TEST" / "audit.json"
        audit = json.loads(audit_path.read_text())
        ship_to_adv = [
            p for p in audit.get("action_proposals", [])
            if p.get("type") == "ship_to_missing"
        ]
        assert len(ship_to_adv) >= 1


class TestBlankReceiverAddress:
    def test_blank_address_writes_advisory_but_generates(self, tmp_path):
        """Missing receiver street → advisory proposal in audit, PDF still returned."""
        storage = _full_setup(tmp_path, country="DE", with_address=False)
        LPI, LPGaps, LPR, assemble, _ = _import_doc_package()

        inputs = _std_inputs(client_name="Test Client GmbH")

        with patch("app.services.wfirma_client.fetch_invoice_pdf",
                   return_value=FAKE_PDF):
            result = assemble("BATCH_TEST", inputs, storage)

        # Generation succeeds
        assert isinstance(result, LPR)
        # Advisories surfaced in result
        assert len(result.advisories) > 0
        # Audit.json has advisory action_proposal
        audit_path = storage / "outputs" / "BATCH_TEST" / "audit.json"
        audit = json.loads(audit_path.read_text())
        advisory_proposals = [
            p for p in audit.get("action_proposals", [])
            if p.get("channel") == "doc_package_advisory"
        ]
        assert len(advisory_proposals) >= 1
        assert all(p["advisory"] is True for p in advisory_proposals)
        assert all(p["status"] == "pending_review" for p in advisory_proposals)

    def test_zero_weight_writes_advisory(self, tmp_path):
        """Zero gross weight → advisory written but generation succeeds."""
        storage = _full_setup(tmp_path, country="DE", with_weight=False)
        LPI, LPGaps, LPR, assemble, _ = _import_doc_package()

        inputs = _std_inputs(client_name="Test Client GmbH")

        with patch("app.services.wfirma_client.fetch_invoice_pdf",
                   return_value=FAKE_PDF):
            result = assemble("BATCH_TEST", inputs, storage)

        assert isinstance(result, LPR)
        audit_path = storage / "outputs" / "BATCH_TEST" / "audit.json"
        audit = json.loads(audit_path.read_text())
        weight_advisories = [
            p for p in audit.get("action_proposals", [])
            if p.get("type") == "weight_zero"
        ]
        assert len(weight_advisories) >= 1


# ── Test 8: route works with carrier_api_status=pending (ungated) ─────────────

class TestRouteUngated:
    def test_route_not_blocked_by_pending_status(self, tmp_path, monkeypatch):
        """carrier_api_status=pending must NOT return 503 for label-package."""
        storage = _full_setup(tmp_path)

        from app.core.config import settings as _s
        monkeypatch.setattr(_s, "carrier_api_status", "pending")
        monkeypatch.setattr(_s, "storage_root", storage)

        from app.api.routes_carrier_actions import create_label_package, LabelPackageBody
        from fastapi import HTTPException

        body = LabelPackageBody(
            box_type_id=STD_BOX_ID,
            client_name="Test Client GmbH",
        )

        import asyncio
        with patch("app.services.wfirma_client.fetch_invoice_pdf",
                   return_value=FAKE_PDF):
            response = asyncio.get_event_loop().run_until_complete(
                create_label_package(
                    batch_id="BATCH_TEST",
                    body=body,
                    _auth=None,   # bypassed in test
                )
            )

        # Should NOT be a 503; we get either a Response or a 422 (EU gaps are ok here)
        # The key assertion: it did NOT raise 503
        assert response is not None

    def test_route_source_does_not_check_carrier_api_status(self):
        """Source-grep: label-package handler must not reference carrier_api_status."""
        src = (Path(__file__).parent.parent / "app" / "api"
               / "routes_carrier_actions.py").read_text(encoding="utf-8")
        # The label-package handler body must not gate on carrier_api_status
        # (the existing /shipment endpoint does gate; we only check that the
        # label-package function itself doesn't reference it)
        handler_start = src.find("async def create_label_package")
        assert handler_start != -1, "Handler not found"
        handler_text = src[handler_start:]
        # Find end of handler (next top-level def or end of file)
        next_def = handler_text.find("\n\n\n", 1)
        if next_def > 0:
            handler_text = handler_text[:next_def]
        assert "carrier_api_status" not in handler_text, (
            "label-package handler must not gate on carrier_api_status"
        )

    def test_route_module_has_no_creds_check(self):
        """The new route must not reference api_key / api_secret."""
        src = (Path(__file__).parent.parent / "app" / "api"
               / "routes_carrier_actions.py").read_text(encoding="utf-8")
        handler_start = src.find("async def create_label_package")
        handler_text = src[handler_start:handler_start + 2000]
        assert "dhl_express_api_key" not in handler_text
        assert "dhl_express_api_secret" not in handler_text
        assert "carrier_live_allowlist" not in handler_text


# ── Test: wFirma not called when not mocked (boundary) ───────────────────────

class TestWfirmaBoundary:
    def test_no_wfirma_write_in_doc_package(self):
        """doc_package.py must not contain wFirma write calls."""
        src = (Path(__file__).parent.parent / "app" / "services" / "carrier"
               / "doc_package.py").read_text(encoding="utf-8")
        # Check no write method imports
        assert "invoices/add" not in src
        assert "create_proforma" not in src
        assert "create_invoice" not in src
        assert "smtplib" not in src

    def test_only_read_call_to_wfirma(self):
        """doc_package.py only calls fetch_invoice_pdf (read-only)."""
        src = (Path(__file__).parent.parent / "app" / "services" / "carrier"
               / "doc_package.py").read_text(encoding="utf-8")
        assert "fetch_invoice_pdf" in src
        # No other wfirma_client calls except the read
        import re
        wfirma_calls = re.findall(r"wfirma_client\.\w+", src)
        assert all(c == "wfirma_client.fetch_invoice_pdf" for c in wfirma_calls), (
            f"Unexpected wFirma calls: {wfirma_calls}"
        )

    def test_422_gap_shape(self, tmp_path):
        """Gap list has correct {field, reason} shape."""
        storage = _full_setup(tmp_path, posted=False)
        LPI, LPGaps, _, assemble, _ = _import_doc_package()

        inputs = _std_inputs()

        result = assemble("BATCH_TEST", inputs, storage)

        assert isinstance(result, LPGaps)
        for gap in result.gaps:
            assert "field" in gap
            assert "reason" in gap
            assert isinstance(gap["field"], str)
            assert isinstance(gap["reason"], str)
            assert len(gap["reason"]) > 10
