"""
PR B — Customer address + service-charge authority tests.

Covers:
  - POST /draft/{id}/apply-customer-address
  - GET  /draft/{id}/suggest-service-charges
  - POST /draft/{id}/apply-service-charges

Seeding strategy: drafts via direct SQLite INSERT (no draft-create endpoint
exists); customer master via upsert_customer.  All tests use tmp_path storage
so live DB is never touched.
"""
from __future__ import annotations

import json
import sqlite3 as _s
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.services import proforma_invoice_link_db as pildb
from app.services.customer_master_db import CustomerMaster, init_db as cm_init_db, upsert_customer


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def fresh(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    monkeypatch.setenv("PZ_STORAGE_ROOT", str(tmp_path))
    monkeypatch.setattr(settings, "storage_root", tmp_path, raising=False)
    monkeypatch.setattr(settings, "api_key", "", raising=False)
    from app.services import wfirma_db as wfdb
    from app.services import proforma_service_charges_db as scdb
    wfdb.init_wfirma_db(tmp_path / "wfirma.db")
    pildb.init_db(tmp_path / "proforma_links.db")
    scdb.init(tmp_path / "proforma_links.db")
    cm_init_db(tmp_path / "customer_master.sqlite")
    return tmp_path


@pytest.fixture()
def client(fresh):
    from app.main import app
    from app.auth.dependencies import get_current_user
    app.dependency_overrides[get_current_user] = lambda: {"id": "t", "email": "t@local"}
    with patch.object(settings, "storage_root", fresh):
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c
    app.dependency_overrides.clear()


def _seed_draft(
    tmp: Path,
    *,
    client_name: str,
    currency: str = "EUR",
    buyer_override: dict | None = None,
    draft_state: str = "editing",
    service_charges: list | None = None,
) -> tuple[int, str]:
    """Insert a minimal draft; return (draft_id, updated_at)."""
    db = tmp / "proforma_links.db"
    pildb.init_db(db)
    bo_json = json.dumps(buyer_override or {}, ensure_ascii=False)
    sc_json = json.dumps(service_charges or [], ensure_ascii=False)
    now = pildb._now_utc_iso()
    with _s.connect(str(db)) as conn:
        pildb._ensure_drafts_table(conn)
        cur = conn.execute(
            """INSERT INTO proforma_drafts
               (batch_id, client_name, status, currency, draft_state, draft_version,
                source_lines_json, editable_lines_json,
                buyer_override_json, service_charges_json,
                created_at, updated_at)
               VALUES (?, ?, 'draft', ?, ?, 1, '[]', '[]', ?, ?, ?, ?)""",
            ("EJL/26-27/TEST", client_name, currency, draft_state,
             bo_json, sc_json, now, now),
        )
        return int(cur.lastrowid), now


def _seed_cm_basic(tmp: Path, client_name: str = "UAB Tomas Gold",
                   contractor_id: str = "CM001") -> dict:
    """Seed a simple Customer Master record; returns fixture dict."""
    cm_db = tmp / "customer_master.sqlite"
    cm_init_db(cm_db)
    cm = CustomerMaster(
        bill_to_contractor_id=contractor_id,
        bill_to_name=client_name,
        country="LT",
        nip=None,
        vat_eu_number="LT100123456",
        bill_to_street="Gedimino pr. 1",
        bill_to_city="Vilnius",
        bill_to_postal_code="LT-01103",
    )
    upsert_customer(cm_db, cm)
    return {
        "client_name":          client_name,
        "bill_to_name":         client_name,
        "bill_to_contractor_id": contractor_id,
        "bill_to_street":       "Gedimino pr. 1",
        "bill_to_city":         "Vilnius",
        "country":              "LT",
        "vat_eu_number":        "LT100123456",
    }


def _seed_cm_with_shipto(tmp: Path, client_name: str = "UAB Ship Different",
                         contractor_id: str = "CM002") -> dict:
    """Seed CM with ship_to_use_alternate=True."""
    cm_db = tmp / "customer_master.sqlite"
    cm_init_db(cm_db)
    cm = CustomerMaster(
        bill_to_contractor_id=contractor_id,
        bill_to_name=client_name,
        country="LT",
        ship_to_use_alternate=True,
        ship_to_name="UAB Warehouse",
        ship_to_street="Kalvarijų g. 2",
        ship_to_city="Kaunas",
        ship_to_zip="LT-44001",
        ship_to_country="LT",
    )
    upsert_customer(cm_db, cm)
    return {
        "client_name":          client_name,
        "bill_to_contractor_id": contractor_id,
        "ship_to_name":         "UAB Warehouse",
        "ship_to_city":         "Kaunas",
    }


def _seed_cm_freight_insurance(tmp: Path, client_name: str = "UAB Freight Co",
                                contractor_id: str = "CM003") -> dict:
    """Seed CM with freight + insurance data for EUR drafts."""
    cm_db = tmp / "customer_master.sqlite"
    cm_init_db(cm_db)
    cm = CustomerMaster(
        bill_to_contractor_id=contractor_id,
        bill_to_name=client_name,
        country="DE",
        freight_service_id="13002743",
        freight_mode="fixed",
        freight_fixed_amount_eur=Decimal("120.00"),
        freight_label_en="FedEx Courier",
        insurance_service_id="13102217",
        insurance_enabled=True,
        insurance_mode="fixed",
        insurance_fixed_amount_eur=Decimal("5.00"),
        insurance_label_en="Cargo Insurance",
    )
    upsert_customer(cm_db, cm)
    return {
        "client_name":          client_name,
        "bill_to_contractor_id": contractor_id,
        "freight_service_id":   "13002743",
    }


@pytest.fixture()
def seeded_customer_master(fresh):
    return _seed_cm_basic(fresh)


@pytest.fixture()
def seeded_customer_master_with_shipto(fresh):
    return _seed_cm_with_shipto(fresh)


@pytest.fixture()
def seeded_cm_with_freight_and_insurance(fresh):
    return _seed_cm_freight_insurance(fresh)


def _auth_header():
    return {"X-Operator": "test-operator"}


# ---------------------------------------------------------------------------
# apply-customer-address
# ---------------------------------------------------------------------------

class TestApplyCustomerAddress:

    def test_apply_resolves_cm_and_sets_buyer_override(self, client, seeded_customer_master, fresh):
        draft_id, updated_at = _seed_draft(
            fresh,
            client_name=seeded_customer_master["client_name"],
            buyer_override={"wfirma_customer_id": seeded_customer_master["bill_to_contractor_id"]},
        )
        r = client.post(
            f"/api/v1/proforma/draft/{draft_id}/apply-customer-address",
            json={"expected_updated_at": updated_at},
            headers=_auth_header(),
        )
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["ok"] is True
        bo = d["draft"]["buyer_override"]
        assert bo["_source"] == "customer_master"
        assert bo["name"] == seeded_customer_master["bill_to_name"]
        assert bo["street"] == seeded_customer_master["bill_to_street"]
        assert bo["country"] == seeded_customer_master["country"]
        assert bo["wfirma_customer_id"] == seeded_customer_master["bill_to_contractor_id"]

    def test_apply_sets_ship_to_when_alternate_flag_is_true(self, client, fresh):
        cm = _seed_cm_with_shipto(fresh)
        draft_id, updated_at = _seed_draft(
            fresh,
            client_name=cm["client_name"],
            buyer_override={"wfirma_customer_id": cm["bill_to_contractor_id"]},
        )
        r = client.post(
            f"/api/v1/proforma/draft/{draft_id}/apply-customer-address",
            json={"expected_updated_at": updated_at},
            headers=_auth_header(),
        )
        assert r.status_code == 200, r.text
        sto = r.json()["draft"]["ship_to_override"]
        assert sto is not None
        assert sto["name"] == cm["ship_to_name"]
        assert sto["city"] == cm["ship_to_city"]

    def test_apply_missing_cm_returns_404(self, client, fresh):
        draft_id, updated_at = _seed_draft(fresh, client_name="Unknown Client XYZ")
        r = client.post(
            f"/api/v1/proforma/draft/{draft_id}/apply-customer-address",
            json={"expected_updated_at": updated_at},
            headers=_auth_header(),
        )
        assert r.status_code == 404
        assert "not found" in r.json().get("detail", "").lower()

    def test_apply_locked_draft_returns_409(self, client, fresh):
        cm = _seed_cm_basic(fresh)
        draft_id, updated_at = _seed_draft(
            fresh,
            client_name=cm["client_name"],
            draft_state="invoiced",
            buyer_override={"wfirma_customer_id": cm["bill_to_contractor_id"]},
        )
        r = client.post(
            f"/api/v1/proforma/draft/{draft_id}/apply-customer-address",
            json={"expected_updated_at": updated_at},
            headers=_auth_header(),
        )
        assert r.status_code in (409, 422)

    def test_apply_stale_updated_at_returns_409(self, client, fresh):
        cm = _seed_cm_basic(fresh)
        draft_id, _ = _seed_draft(
            fresh,
            client_name=cm["client_name"],
            buyer_override={"wfirma_customer_id": cm["bill_to_contractor_id"]},
        )
        r = client.post(
            f"/api/v1/proforma/draft/{draft_id}/apply-customer-address",
            json={"expected_updated_at": "2000-01-01T00:00:00"},
            headers=_auth_header(),
        )
        assert r.status_code == 409

    def test_apply_records_audit_event(self, client, fresh):
        cm = _seed_cm_basic(fresh)
        draft_id, updated_at = _seed_draft(
            fresh,
            client_name=cm["client_name"],
            buyer_override={"wfirma_customer_id": cm["bill_to_contractor_id"]},
        )
        client.post(
            f"/api/v1/proforma/draft/{draft_id}/apply-customer-address",
            json={"expected_updated_at": updated_at},
            headers=_auth_header(),
        )
        r = client.get(f"/api/v1/proforma/draft/{draft_id}/events")
        assert r.status_code == 200
        events = r.json().get("events", [])
        event_types = [e.get("event") for e in events]
        assert "buyer_override_from_customer_master" in event_types


# ---------------------------------------------------------------------------
# suggest-service-charges
# ---------------------------------------------------------------------------

class TestSuggestServiceCharges:

    def test_suggest_returns_freight_and_insurance(self, client, fresh):
        cm = _seed_cm_freight_insurance(fresh)
        draft_id, _ = _seed_draft(
            fresh,
            client_name=cm["client_name"],
            currency="EUR",
            buyer_override={"wfirma_customer_id": cm["bill_to_contractor_id"]},
        )
        r = client.get(f"/api/v1/proforma/draft/{draft_id}/suggest-service-charges")
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["ok"] is True
        assert d["freight"]["available"] is True
        assert float(d["freight"]["amount"]) > 0
        assert d["insurance"]["available"] is True
        assert float(d["insurance"]["amount"]) > 0

    def test_suggest_marks_already_applied_freight(self, client, fresh):
        cm = _seed_cm_freight_insurance(fresh)
        draft_id, updated_at = _seed_draft(
            fresh,
            client_name=cm["client_name"],
            currency="EUR",
            buyer_override={"wfirma_customer_id": cm["bill_to_contractor_id"]},
        )
        client.post(
            f"/api/v1/proforma/draft/{draft_id}/service-charges",
            json={
                "expected_updated_at": updated_at,
                "charge": {"charge_type": "freight", "amount": "50.00", "currency": "EUR"},
            },
            headers=_auth_header(),
        )
        r = client.get(f"/api/v1/proforma/draft/{draft_id}/suggest-service-charges")
        assert r.status_code == 200
        assert r.json()["freight"]["already_applied"] is True

    def test_suggest_blocked_for_non_eur_usd_currency(self, client, fresh):
        cm = _seed_cm_freight_insurance(fresh)
        draft_id, _ = _seed_draft(
            fresh,
            client_name=cm["client_name"],
            currency="PLN",
            buyer_override={"wfirma_customer_id": cm["bill_to_contractor_id"]},
        )
        r = client.get(f"/api/v1/proforma/draft/{draft_id}/suggest-service-charges")
        assert r.status_code == 200
        d = r.json()
        assert d["freight"]["available"] is False
        assert d["freight"]["blocked_reason"]

    def test_suggest_missing_cm_returns_blocked(self, client, fresh):
        draft_id, _ = _seed_draft(fresh, client_name="Unknown Client ABC", currency="EUR")
        r = client.get(f"/api/v1/proforma/draft/{draft_id}/suggest-service-charges")
        assert r.status_code == 200
        d = r.json()
        assert d["freight"]["available"] is False
        assert d["insurance"]["available"] is False


# ---------------------------------------------------------------------------
# apply-service-charges
# ---------------------------------------------------------------------------

class TestApplyServiceCharges:

    def test_apply_freight_adds_charge(self, client, fresh):
        cm = _seed_cm_freight_insurance(fresh)
        draft_id, updated_at = _seed_draft(
            fresh,
            client_name=cm["client_name"],
            currency="EUR",
            buyer_override={"wfirma_customer_id": cm["bill_to_contractor_id"]},
        )
        r = client.post(
            f"/api/v1/proforma/draft/{draft_id}/apply-service-charges",
            json={"expected_updated_at": updated_at, "apply": ["freight"]},
            headers=_auth_header(),
        )
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["ok"] is True
        applied_types = [c["charge_type"] for c in d["applied"]]
        assert "freight" in applied_types
        charge_types = [c["charge_type"] for c in d["draft"]["service_charges"]]
        assert "freight" in charge_types

    def test_apply_both_adds_both_charges(self, client, fresh):
        cm = _seed_cm_freight_insurance(fresh)
        draft_id, updated_at = _seed_draft(
            fresh,
            client_name=cm["client_name"],
            currency="EUR",
            buyer_override={"wfirma_customer_id": cm["bill_to_contractor_id"]},
        )
        r = client.post(
            f"/api/v1/proforma/draft/{draft_id}/apply-service-charges",
            json={"expected_updated_at": updated_at, "apply": ["freight", "insurance"]},
            headers=_auth_header(),
        )
        assert r.status_code == 200
        d = r.json()
        applied_types = [c["charge_type"] for c in d["applied"]]
        assert "freight" in applied_types
        assert "insurance" in applied_types

    def test_apply_already_existing_type_skipped(self, client, fresh):
        cm = _seed_cm_freight_insurance(fresh)
        draft_id, updated_at = _seed_draft(
            fresh,
            client_name=cm["client_name"],
            currency="EUR",
            buyer_override={"wfirma_customer_id": cm["bill_to_contractor_id"]},
        )
        r1 = client.post(
            f"/api/v1/proforma/draft/{draft_id}/service-charges",
            json={
                "expected_updated_at": updated_at,
                "charge": {"charge_type": "freight", "amount": "50.00", "currency": "EUR"},
            },
            headers=_auth_header(),
        )
        assert r1.status_code == 200
        new_updated_at = r1.json()["draft"]["updated_at"]

        r2 = client.post(
            f"/api/v1/proforma/draft/{draft_id}/apply-service-charges",
            json={"expected_updated_at": new_updated_at, "apply": ["freight"]},
            headers=_auth_header(),
        )
        assert r2.status_code == 200
        d2 = r2.json()
        skipped_types = [c["charge_type"] for c in d2["skipped"]]
        assert "freight" in skipped_types
        freight_charges = [c for c in d2["draft"]["service_charges"]
                           if c["charge_type"] == "freight"]
        assert len(freight_charges) == 1

    def test_apply_stores_wfirma_service_id(self, client, fresh):
        cm = _seed_cm_freight_insurance(fresh)
        draft_id, updated_at = _seed_draft(
            fresh,
            client_name=cm["client_name"],
            currency="EUR",
            buyer_override={"wfirma_customer_id": cm["bill_to_contractor_id"]},
        )
        r = client.post(
            f"/api/v1/proforma/draft/{draft_id}/apply-service-charges",
            json={"expected_updated_at": updated_at, "apply": ["freight"]},
            headers=_auth_header(),
        )
        assert r.status_code == 200
        charges = r.json()["draft"]["service_charges"]
        freight = next((c for c in charges if c["charge_type"] == "freight"), None)
        assert freight is not None
        assert freight.get("wfirma_service_id") == cm.get("freight_service_id")

    def test_apply_optimistic_lock(self, client, fresh):
        cm = _seed_cm_freight_insurance(fresh)
        draft_id, _ = _seed_draft(
            fresh,
            client_name=cm["client_name"],
            currency="EUR",
            buyer_override={"wfirma_customer_id": cm["bill_to_contractor_id"]},
        )
        r = client.post(
            f"/api/v1/proforma/draft/{draft_id}/apply-service-charges",
            json={"expected_updated_at": "2000-01-01T00:00:00", "apply": ["freight"]},
            headers=_auth_header(),
        )
        assert r.status_code == 409

    def test_apply_does_not_mutate_customer_master(self, client, fresh):
        """Apply charges must never write to Customer Master — verified via direct DB read."""
        from app.services.customer_master_db import get_customer
        cm = _seed_cm_freight_insurance(fresh)
        cm_db = fresh / "customer_master.sqlite"
        draft_id, updated_at = _seed_draft(
            fresh,
            client_name=cm["client_name"],
            currency="EUR",
            buyer_override={"wfirma_customer_id": cm["bill_to_contractor_id"]},
        )
        cm_before = get_customer(cm_db, cm["bill_to_contractor_id"])

        client.post(
            f"/api/v1/proforma/draft/{draft_id}/apply-service-charges",
            json={"expected_updated_at": updated_at, "apply": ["freight", "insurance"]},
            headers=_auth_header(),
        )

        cm_after = get_customer(cm_db, cm["bill_to_contractor_id"])
        # freight_fixed_amount_eur and all identifying fields must be unchanged
        assert cm_before.freight_fixed_amount_eur == cm_after.freight_fixed_amount_eur
        assert cm_before.bill_to_contractor_id == cm_after.bill_to_contractor_id
        assert cm_before.freight_service_id == cm_after.freight_service_id
        assert cm_before.insurance_fixed_amount_eur == cm_after.insurance_fixed_amount_eur
