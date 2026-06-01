"""
test_adr027_vat_from_master.py — ADR-027: proforma VAT + document defaults
from customer_master (D1-D6).

Coverage
--------
Unit tests (resolve_vat_context_from_master):
  U1. vat_mode=228 (operator) → wdt / WDT / decision_source=operator_vat_mode
  U2. vat_mode=222 (operator) → domestic / 23
  U3. vat_mode=229 (operator) → export / EXP
  U4. Unknown vat_mode → ValueError (block draft, never guess)
  U5. Derived PL → domestic / 23
  U6. Derived EU + vat_eu_number set → wdt / WDT, no warning
  U7. Derived EU + empty vat_eu_number → wdt / WDT + vies_unverified warning (D3)
  U8. Derived EU + vat_eu_number set + vat_eu_valid=False → wdt + warning (D3)
  U9. Derived non-EU → export / EXP
  U10. Derived country empty → blocked
  U11. Operator vat_mode wins over country (override priority 1 always beats P2)

Integration tests (routes layer, wFirma mocked):
  I1. /draft/{id}/post → operator vat_mode=228 (EU RC) → WDT/228 sent to wFirma
  I2. /draft/{id}/post → unknown vat_mode → blocked (ValueError), no wFirma call
  I3. /draft/{id}/post → D3 VIES warning in response, not a block
  I4. /draft/{id}/post → D4 freeze written to draft (vat_context/vat_code/decision_source)
  I5. /draft/{id}/post → D4 drift warning when frozen != re-resolved
  I6. /draft/{id}/post → D5 currency mismatch → vat_warnings includes currency_mismatch
  I7. /draft/{id}/post → D6 payment_terms_days in wFirma XML when set
  I8. /draft/{id}/post → D6 translation_language_id in wFirma XML when set
  I9. /draft/{id}/post → D6 fields absent from XML when null
  I10. verify-after-create still runs (regression guard)
  I11. WFIRMA_CREATE_PROFORMA_ALLOWED=False → no wFirma call (gate guard)
"""
from __future__ import annotations

import dataclasses
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch
from xml.etree import ElementTree as ET

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.services import proforma_invoice_link_db as pildb
from app.services import wfirma_client
from app.services.customer_master_db import CustomerMaster


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _make_cm(**kwargs) -> CustomerMaster:
    """Build a minimal CustomerMaster for testing."""
    defaults = dict(
        bill_to_contractor_id="9001",
        bill_to_name="TestCo",
        country=None,
        vat_eu_number=None,
        vat_eu_valid=None,
        vat_mode=None,
        default_currency=None,
        default_language_id=None,
        preferred_proforma_series_id=None,
        preferred_invoice_series_id=None,
        preferred_payment_method=None,
        payment_terms_days=None,
        nip=None,
    )
    defaults.update(kwargs)
    # Build using only fields the dataclass actually has
    valid = {f.name for f in dataclasses.fields(CustomerMaster)}
    filtered = {k: v for k, v in defaults.items() if k in valid}
    return CustomerMaster(**filtered)


def _parse_xml_body(captured: list) -> ET.Element:
    """Return the parsed XML root from the last captured wFirma call."""
    assert captured, "no wFirma call was captured"
    body = captured[-1]
    return ET.fromstring(body)


# ──────────────────────────────────────────────────────────────────────────────
# U-series: unit tests for resolve_vat_context_from_master
# ──────────────────────────────────────────────────────────────────────────────

class TestResolveVatContextFromMaster:

    def test_u1_operator_wdt(self):
        """U1: vat_mode=228 → wdt, WDT, operator_vat_mode."""
        cm = _make_cm(vat_mode=228, country="DE")
        result = wfirma_client.resolve_vat_context_from_master(cm)
        assert result["context"] == "wdt"
        assert result["vat_code"] == "WDT"
        assert result["decision_source"] == "operator_vat_mode"
        assert not result["blocked"]
        assert not result["warnings"]

    def test_u2_operator_domestic(self):
        """U2: vat_mode=222 → domestic, 23, operator_vat_mode."""
        cm = _make_cm(vat_mode=222, country="DE")  # country irrelevant
        result = wfirma_client.resolve_vat_context_from_master(cm)
        assert result["context"] == "domestic"
        assert result["vat_code"] == "23"
        assert result["decision_source"] == "operator_vat_mode"

    def test_u3_operator_export(self):
        """U3: vat_mode=229 → export, EXP."""
        cm = _make_cm(vat_mode=229, country="US")
        result = wfirma_client.resolve_vat_context_from_master(cm)
        assert result["context"] == "export"
        assert result["vat_code"] == "EXP"
        assert result["decision_source"] == "operator_vat_mode"

    def test_u4_unknown_vat_mode_raises(self):
        """U4: unknown vat_mode → ValueError (block draft, never guess)."""
        cm = _make_cm(vat_mode=999)
        with pytest.raises(ValueError, match="vat_mode=999"):
            wfirma_client.resolve_vat_context_from_master(cm)

    def test_u5_derived_pl(self):
        """U5: no vat_mode, country=PL → domestic, 23, derived."""
        cm = _make_cm(country="PL")
        result = wfirma_client.resolve_vat_context_from_master(cm)
        assert result["context"] == "domestic"
        assert result["vat_code"] == "23"
        assert result["decision_source"] == "derived"
        assert not result["blocked"]

    def test_u6_derived_eu_with_vat_no_warning(self):
        """U6: EU + vat_eu_number set + vat_eu_valid=True → wdt, no warning."""
        cm = _make_cm(country="DE", vat_eu_number="DE123456789",
                      vat_eu_valid=True)
        result = wfirma_client.resolve_vat_context_from_master(cm)
        assert result["context"] == "wdt"
        assert result["vat_code"] == "WDT"
        assert result["decision_source"] == "derived"
        assert not result["warnings"], f"unexpected warnings: {result['warnings']}"

    def test_u7_derived_eu_no_vat_number_d3_warning(self):
        """U7: EU + no vat_eu_number → wdt-intent with D3 warning, NOT blocked."""
        cm = _make_cm(country="FR", vat_eu_number=None)
        result = wfirma_client.resolve_vat_context_from_master(cm)
        assert result["context"] == "wdt"
        assert result["vat_code"] == "WDT"
        assert not result["blocked"]
        assert any("vies_unverified" in w for w in result["warnings"])

    def test_u8_derived_eu_vat_present_but_invalid_d3(self):
        """U8: EU + vat_eu_number set + vat_eu_valid=False → wdt + D3 warning."""
        cm = _make_cm(country="IT", vat_eu_number="IT12345678",
                      vat_eu_valid=False)
        result = wfirma_client.resolve_vat_context_from_master(cm)
        assert result["context"] == "wdt"
        assert not result["blocked"]
        assert any("vies_unverified" in w for w in result["warnings"])

    def test_u9_derived_non_eu(self):
        """U9: non-EU country → export, EXP."""
        cm = _make_cm(country="US", vat_eu_number=None)
        result = wfirma_client.resolve_vat_context_from_master(cm)
        assert result["context"] == "export"
        assert result["vat_code"] == "EXP"

    def test_u10_derived_empty_country_blocked(self):
        """U10: country empty → blocked, vat_code=None."""
        cm = _make_cm(country=None)
        result = wfirma_client.resolve_vat_context_from_master(cm)
        assert result["blocked"]
        assert result["vat_code"] is None

    def test_u11_operator_wins_over_country(self):
        """U11: vat_mode=228 on a PL customer → wdt (override beats derived PL)."""
        cm = _make_cm(country="PL", vat_mode=228)
        result = wfirma_client.resolve_vat_context_from_master(cm)
        assert result["context"] == "wdt"
        assert result["decision_source"] == "operator_vat_mode"


# ──────────────────────────────────────────────────────────────────────────────
# I-series: integration tests (routes, wFirma fully mocked)
# ──────────────────────────────────────────────────────────────────────────────

BATCH = "B-ADR027"
CLIENT = "TESTCO-EU"
CONTRACTOR_ID = "9001"
PRODUCT_CODE = "RING-001"
WFIRMA_GOOD_ID = "42001"
WFIRMA_PROFORMA_ID = "77001"


def _wfirma_add_ok_xml(proforma_id: str = WFIRMA_PROFORMA_ID) -> str:
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>'
        f'<api><status><code>OK</code></status>'
        f'<invoices><invoice><id>{proforma_id}</id>'
        f'<fullnumber>PROF 1/2026</fullnumber></invoice></invoices></api>'
    )


def _wfirma_verify_xml(
    proforma_id: str = WFIRMA_PROFORMA_ID,
    good_id: str = WFIRMA_GOOD_ID,
    vat_code_id: str = "228",
) -> str:
    """Simulate the verify-after-create fetch (1 line, matching vat_code_id)."""
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>'
        f'<api><status><code>OK</code></status>'
        f'<invoices><invoice><id>{proforma_id}</id>'
        f'<invoicecontents><invoicecontent>'
        f'<good><id>{good_id}</id></good>'
        f'<vat_code><id>{vat_code_id}</id></vat_code>'
        f'</invoicecontent></invoicecontents></invoice></invoices></api>'
    )


@pytest.fixture()
def app_client(tmp_path, monkeypatch) -> TestClient:
    """Minimal app fixture with wFirma MOCKED and required settings set."""
    from app.main import app
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    monkeypatch.setattr(settings, "wfirma_create_proforma_allowed", True)
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


def _setup_db_for_draft(tmp_path: Path, cm: CustomerMaster) -> pildb.ProformaDraft:
    """
    Create proforma_drafts DB + approved draft + customer_master + wfirma mapping.
    Returns the created draft.
    NOTE: caller must have already patched wfdb._db_path via _patch_env before
    calling this function so module-level DB operations land in tmp_path.
    """
    from app.services import customer_master_db as cmdb
    from app.services import wfirma_db as wfdb

    db_path = tmp_path / "proforma_drafts.sqlite"

    # Insert customer_master record
    cm_db = tmp_path / "customer_master.sqlite"
    cmdb.init_db(cm_db)
    cmdb.upsert_customer(cm_db, cm)

    # Insert wfirma_customers mapping (needed for contractor_id resolution)
    # _db_path was already patched by _patch_env before this call
    wf_db = tmp_path / "wfirma.sqlite"
    wfdb.init_wfirma_db(wf_db)
    wfdb.upsert_customer(
        CLIENT,
        wfirma_customer_id=CONTRACTOR_ID,
        vat_id=cm.nip or "",
        country=cm.country or "DE",
    )

    # Insert wfirma_products mapping
    wfdb.upsert_product(
        product_code=PRODUCT_CODE,
        wfirma_product_id=WFIRMA_GOOD_ID,
        product_name="Ring",
    )

    # Insert a draft row directly with status='draft' (not 'pending_local') so
    # the _ensure_drafts_table backfill never reverts draft_state to 'posting'.
    lines_json = json.dumps([{
        "product_code": PRODUCT_CODE, "design_no": "R1",
        "qty": 1.0, "unit_price": 100.0, "currency": "EUR",
    }])
    now = "2026-01-01T00:00:00Z"
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        pildb._ensure_drafts_table(conn)
        conn.execute(
            """
            INSERT INTO proforma_drafts
              (batch_id, client_name, status, draft_state, currency,
               source_lines_json, editable_lines_json, service_charges_json,
               clone_generation, created_at, updated_at)
            VALUES (?, ?, 'draft', 'approved', 'EUR', ?, ?, '[]', 0, ?, ?)
            """,
            (BATCH, CLIENT, lines_json, lines_json, now, now),
        )
        row_id = conn.execute(
            "SELECT id FROM proforma_drafts WHERE batch_id=? AND client_name=? LIMIT 1",
            (BATCH, CLIENT),
        ).fetchone()["id"]

    return pildb.get_draft_by_id(db_path, row_id)


def _post_draft(app_client, draft_id: int, draft) -> dict:
    """POST /draft/{id}/post with the correct confirm token."""
    resp = app_client.post(
        f"/api/v1/proforma/draft/{draft_id}/post",
        json={
            "expected_updated_at": draft.updated_at,
            "confirm_token": "YES_POST_LOCAL_PROFORMA_DRAFT_TO_WFIRMA",
        },
        headers={"X-API-Key": "test-key", "X-Operator": "test-op"},
    )
    return resp


class TestADR027Integration:
    """Integration tests: proforma /post route with wFirma fully mocked."""

    def _patch_env(self, tmp_path, monkeypatch, cm: CustomerMaster):
        """Patch storage paths so the route reads from tmp_path DBs."""
        from app.api import routes_proforma as rp
        monkeypatch.setattr(rp, "_proforma_db_path",
                            lambda: tmp_path / "proforma_drafts.sqlite")
        monkeypatch.setattr(rp, "_customer_master_db_path",
                            lambda: tmp_path / "customer_master.sqlite")

        from app.services import wfirma_db as wfdb
        # Patch the _db_path reference used by wfdb module-level helpers
        monkeypatch.setattr(wfdb, "_db_path", tmp_path / "wfirma.sqlite")

    def _mock_wfirma_http(self, monkeypatch, vat_code_id: str = "228",
                          captured: Optional[List[str]] = None):
        """
        Mock _http_request: returns success for invoices/add + verify GET,
        and the vat_codes/find for each code.
        """
        call_count = [0]
        bodies: List[str] = captured if captured is not None else []

        def _fake_http(method, controller, action, body=""):
            bodies.append(body)
            call_count[0] += 1

            if controller == "invoices" and action == "add":
                return 200, _wfirma_add_ok_xml()
            if controller == "invoices" and action == "get":
                return 200, _wfirma_verify_xml(vat_code_id=vat_code_id)
            if controller == "vat_codes" and action == "find":
                # Return the mapped numeric id based on the <code> in body
                _code_map = {
                    "23": "222", "WDT": "228", "EXP": "229",
                    "NP": "230", "NPUE": "231", "ZW": "233", "0": "234",
                }
                for code_str, num_id in _code_map.items():
                    if f"<value>{code_str}</value>" in body:
                        return 200, (
                            f'<?xml version="1.0" encoding="UTF-8"?>'
                            f'<api><status><code>OK</code></status>'
                            f'<vat_codes><vat_code>'
                            f'<id>{num_id}</id><code>{code_str}</code>'
                            f'</vat_code></vat_codes></api>'
                        )
                return 200, (
                    '<?xml version="1.0" encoding="UTF-8"?>'
                    '<api><status><code>OK</code></status>'
                    '<vat_codes></vat_codes></api>'
                )
            # fetch_invoice_xml used by verify-after-create
            if controller == "invoices" and action.startswith("get/"):
                return 200, _wfirma_verify_xml(vat_code_id=vat_code_id)
            return 200, (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<api><status><code>OK</code></status></api>'
            )

        monkeypatch.setattr(wfirma_client, "_http_request", _fake_http)
        # Also clear the vat code cache so each test starts fresh
        wfirma_client._VAT_CODE_ID_CACHE.clear()
        return bodies

    def test_i1_operator_wdt_sends_228(self, tmp_path, monkeypatch, app_client):
        """I1: vat_mode=228 → WDT/228 sent to wFirma; response includes vat_context."""
        cm = _make_cm(
            bill_to_contractor_id=CONTRACTOR_ID,
            bill_to_name=CLIENT,
            country="DE",
            vat_eu_number="DE123456789",
            vat_eu_valid=True,
            vat_mode=228,
        )
        self._patch_env(tmp_path, monkeypatch, cm)
        draft = _setup_db_for_draft(tmp_path, cm)
        captured = self._mock_wfirma_http(monkeypatch, vat_code_id="228")

        resp = _post_draft(app_client, draft.id, draft)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "posted"
        assert body.get("vat_context") == "wdt"
        assert body.get("vat_code") == "WDT"
        assert body.get("decision_source") == "operator_vat_mode"

        # Verify wFirma XML contained vat_code_id=228
        add_xml = next((b for b in captured if "invoices" in b and "proforma" in b), None)
        assert add_xml is not None, "no invoices/add XML captured"
        root = ET.fromstring(add_xml)
        vc_ids = [n.text for n in root.findall(".//vat_code/id")]
        assert "228" in vc_ids, f"expected 228 in vat_code ids, got {vc_ids}"

    def test_i2_unknown_vat_mode_blocked(self, tmp_path, monkeypatch, app_client):
        """I2: vat_mode=999 → blocked before wFirma call.

        customer_master_db validates vat_mode in (222,228,229), so we
        insert the row directly via SQL to bypass that guard and test
        that the VAT resolver correctly errors on an unknown value.
        """
        cm = _make_cm(
            bill_to_contractor_id=CONTRACTOR_ID,
            bill_to_name=CLIENT,
            country="DE",
            vat_mode=None,  # valid for upsert; override in SQL after
        )
        self._patch_env(tmp_path, monkeypatch, cm)
        draft = _setup_db_for_draft(tmp_path, cm)

        # Directly write vat_mode=999 to bypass the upsert validator
        from app.services import customer_master_db as cmdb
        cm_db = tmp_path / "customer_master.sqlite"
        with sqlite3.connect(str(cm_db)) as conn:
            conn.execute(
                "UPDATE customer_master SET vat_mode=999 WHERE bill_to_contractor_id=?",
                (CONTRACTOR_ID,),
            )

        captured = self._mock_wfirma_http(monkeypatch)

        resp = _post_draft(app_client, draft.id, draft)
        data = resp.json()
        # Route returns 400 for pre-commit validation failures
        assert resp.status_code == 400, resp.text
        add_calls = [b for b in captured if "proforma" in b and "invoice" in b]
        assert not add_calls, "wFirma call should not have been made"
        assert data.get("status") == "blocked", \
            f"expected blocked, got: {data}"

    def test_i3_vies_warning_not_block(self, tmp_path, monkeypatch, app_client):
        """I3: EU customer, vat_eu_valid=False → post succeeds with vat_warnings."""
        cm = _make_cm(
            bill_to_contractor_id=CONTRACTOR_ID,
            bill_to_name=CLIENT,
            country="FR",
            vat_eu_number="FR12345678",
            vat_eu_valid=False,
            vat_mode=None,
        )
        self._patch_env(tmp_path, monkeypatch, cm)
        draft = _setup_db_for_draft(tmp_path, cm)
        self._mock_wfirma_http(monkeypatch, vat_code_id="228")

        resp = _post_draft(app_client, draft.id, draft)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["status"] == "posted"
        warnings = data.get("vat_warnings") or []
        assert any("vies_unverified" in w for w in warnings), \
            f"expected vies_unverified in warnings: {warnings}"

    def test_i4_vat_freeze_written_to_draft(self, tmp_path, monkeypatch, app_client):
        """I4: after post, draft row has vat_context/vat_code/decision_source set."""
        cm = _make_cm(
            bill_to_contractor_id=CONTRACTOR_ID,
            bill_to_name=CLIENT,
            country="DE",
            vat_eu_number="DE999",
            vat_eu_valid=True,
            vat_mode=228,
        )
        self._patch_env(tmp_path, monkeypatch, cm)
        draft = _setup_db_for_draft(tmp_path, cm)
        self._mock_wfirma_http(monkeypatch, vat_code_id="228")

        resp = _post_draft(app_client, draft.id, draft)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["status"] == "posted"

        # Read the draft from DB and verify freeze
        db = tmp_path / "proforma_drafts.sqlite"
        updated = pildb.get_draft_by_id(db, draft.id)
        assert updated is not None
        assert updated.vat_context == "wdt", f"vat_context={updated.vat_context!r}"
        assert updated.vat_code == "WDT", f"vat_code={updated.vat_code!r}"
        assert updated.decision_source == "operator_vat_mode", \
            f"decision_source={updated.decision_source!r}"

    def test_i5_drift_warning(self, tmp_path, monkeypatch, app_client):
        """I5: draft frozen with 'domestic', re-resolved as 'wdt' → drift warning."""
        cm = _make_cm(
            bill_to_contractor_id=CONTRACTOR_ID,
            bill_to_name=CLIENT,
            country="DE",
            vat_eu_number="DE999",
            vat_eu_valid=True,
            vat_mode=228,  # wdt
        )
        self._patch_env(tmp_path, monkeypatch, cm)
        draft = _setup_db_for_draft(tmp_path, cm)

        # Pre-freeze with 'domestic' to simulate drift
        db = tmp_path / "proforma_drafts.sqlite"
        pildb.freeze_draft_vat_context(
            db, draft.id,
            vat_context="domestic",
            vat_code="23",
            decision_source="derived",
        )
        draft = pildb.get_draft_by_id(db, draft.id)  # refresh

        self._mock_wfirma_http(monkeypatch, vat_code_id="228")

        resp = _post_draft(app_client, draft.id, draft)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        # Post should succeed (drift is a warning, not a block)
        assert data["status"] == "posted"
        warnings = data.get("vat_warnings") or []
        assert any("vat_drift" in w or "drift" in w.lower() for w in warnings), \
            f"expected drift warning, got: {warnings}"

    def test_i6_currency_mismatch_warning_d5(self, tmp_path, monkeypatch, app_client):
        """I6: draft currency EUR, customer_master.default_currency=PLN → mismatch warning."""
        cm = _make_cm(
            bill_to_contractor_id=CONTRACTOR_ID,
            bill_to_name=CLIENT,
            country="DE",
            vat_eu_number="DE999",
            vat_eu_valid=True,
            vat_mode=228,
            default_currency="PLN",  # differs from draft EUR
        )
        self._patch_env(tmp_path, monkeypatch, cm)
        draft = _setup_db_for_draft(tmp_path, cm)  # draft is EUR
        self._mock_wfirma_http(monkeypatch, vat_code_id="228")

        resp = _post_draft(app_client, draft.id, draft)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["status"] == "posted"
        warnings = data.get("vat_warnings") or []
        assert any("currency_mismatch" in w or "mismatch" in w.lower()
                   for w in warnings), \
            f"expected currency_mismatch warning, got: {warnings}"

    def test_i7_d6_payment_terms_in_xml(self, tmp_path, monkeypatch, app_client):
        """I7: payment_terms_days=30 → <paymentdays>30</paymentdays> in wFirma XML."""
        cm = _make_cm(
            bill_to_contractor_id=CONTRACTOR_ID,
            bill_to_name=CLIENT,
            country="DE",
            vat_eu_number="DE999",
            vat_eu_valid=True,
            vat_mode=228,
            payment_terms_days=30,
        )
        self._patch_env(tmp_path, monkeypatch, cm)
        draft = _setup_db_for_draft(tmp_path, cm)
        captured = self._mock_wfirma_http(monkeypatch, vat_code_id="228")

        resp = _post_draft(app_client, draft.id, draft)
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "posted"

        add_xml = next((b for b in captured if "proforma" in b and "invoice" in b), None)
        assert add_xml, "no invoices/add XML captured"
        assert "<paymentdays>30</paymentdays>" in add_xml, \
            f"<paymentdays>30</paymentdays> not in XML:\n{add_xml}"

    def test_i8_d6_language_in_xml(self, tmp_path, monkeypatch, app_client):
        """I8: default_language_id='5' → <translation_language><id>5</id></translation_language>."""
        cm = _make_cm(
            bill_to_contractor_id=CONTRACTOR_ID,
            bill_to_name=CLIENT,
            country="DE",
            vat_eu_number="DE999",
            vat_eu_valid=True,
            vat_mode=228,
            default_language_id="5",
        )
        self._patch_env(tmp_path, monkeypatch, cm)
        draft = _setup_db_for_draft(tmp_path, cm)
        captured = self._mock_wfirma_http(monkeypatch, vat_code_id="228")

        resp = _post_draft(app_client, draft.id, draft)
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "posted"

        add_xml = next((b for b in captured if "proforma" in b and "invoice" in b), None)
        assert add_xml, "no invoices/add XML captured"
        assert "<translation_language><id>5</id></translation_language>" in add_xml, \
            f"language element not in XML:\n{add_xml}"

    def test_i9_d6_omit_when_null(self, tmp_path, monkeypatch, app_client):
        """I9: payment_terms_days=None, language_id=None → elements absent from XML."""
        cm = _make_cm(
            bill_to_contractor_id=CONTRACTOR_ID,
            bill_to_name=CLIENT,
            country="DE",
            vat_eu_number="DE999",
            vat_eu_valid=True,
            vat_mode=228,
            payment_terms_days=None,
            default_language_id=None,
        )
        self._patch_env(tmp_path, monkeypatch, cm)
        draft = _setup_db_for_draft(tmp_path, cm)
        captured = self._mock_wfirma_http(monkeypatch, vat_code_id="228")

        resp = _post_draft(app_client, draft.id, draft)
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "posted"

        add_xml = next((b for b in captured if "proforma" in b and "invoice" in b), None)
        assert add_xml, "no invoices/add XML captured"
        assert "<paymentdays>" not in add_xml, \
            f"paymentdays should be absent: {add_xml}"
        assert "<translation_language>" not in add_xml, \
            f"translation_language should be absent: {add_xml}"

    def test_i10_verify_after_create_still_runs(self, tmp_path, monkeypatch, app_client):
        """I10: verify-after-create gate rejects vat_code mismatch (regression guard)."""
        cm = _make_cm(
            bill_to_contractor_id=CONTRACTOR_ID,
            bill_to_name=CLIENT,
            country="DE",
            vat_eu_number="DE999",
            vat_eu_valid=True,
            vat_mode=228,
        )
        self._patch_env(tmp_path, monkeypatch, cm)
        draft = _setup_db_for_draft(tmp_path, cm)

        # Mock: invoices/add says OK/228, but verify fetch returns wrong vat_code_id=222
        def _bad_http(method, controller, action, body=""):
            if controller == "invoices" and action == "add":
                return 200, _wfirma_add_ok_xml()
            if controller == "invoices":
                # verify-after-create: return mismatched vat_code_id
                return 200, _wfirma_verify_xml(vat_code_id="222")  # mismatch!
            if controller == "vat_codes":
                return 200, (
                    '<?xml version="1.0" encoding="UTF-8"?>'
                    '<api><status><code>OK</code></status>'
                    '<vat_codes><vat_code><id>228</id><code>WDT</code></vat_code></vat_codes></api>'
                )
            return 200, '<api><status><code>OK</code></status></api>'

        monkeypatch.setattr(wfirma_client, "_http_request", _bad_http)
        wfirma_client._VAT_CODE_ID_CACHE.clear()

        resp = _post_draft(app_client, draft.id, draft)
        assert resp.status_code == 200
        data = resp.json()
        # verify-after-create should have raised → status=failed
        assert data["status"] == "failed", \
            f"expected failed due to vat_code mismatch, got: {data}"
        assert "vat_code" in (data.get("error") or "").lower() or \
               "mismatch" in (data.get("error") or "").lower(), \
            f"error should mention vat_code mismatch: {data.get('error')}"

    def test_i11_gate_off_no_wfirma_call(self, tmp_path, monkeypatch, app_client):
        """I11: WFIRMA_CREATE_PROFORMA_ALLOWED=False → no wFirma write."""
        cm = _make_cm(
            bill_to_contractor_id=CONTRACTOR_ID,
            bill_to_name=CLIENT,
            country="DE",
            vat_mode=228,
        )
        self._patch_env(tmp_path, monkeypatch, cm)
        draft = _setup_db_for_draft(tmp_path, cm)
        monkeypatch.setattr(settings, "wfirma_create_proforma_allowed", False)
        captured = self._mock_wfirma_http(monkeypatch)

        resp = _post_draft(app_client, draft.id, draft)
        # Gate-off returns 400 blocked (pre-commit validation error)
        assert resp.status_code == 400, resp.text
        data = resp.json()
        assert data["status"] == "blocked", f"unexpected status: {data}"
        add_calls = [b for b in captured if "proforma" in b and "invoice" in b]
        assert not add_calls, "no wFirma call should occur when gate is off"
