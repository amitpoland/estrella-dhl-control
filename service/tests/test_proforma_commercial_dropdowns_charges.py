"""test_proforma_commercial_dropdowns_charges.py — PR-3.

Two additions, both through EXISTING writers:

  1. Operator-set commercial defaults — POST /draft/{id}/set-commercial-defaults.
     Controlled, wFirma-backed values (payment method / days / invoice language /
     VAT/WDT) chosen by the operator, validated against the canonical enum/id sets
     and written via apply_customer_commercial_to_draft (no second writer) under a
     distinct 'commercial_defaults_operator_set' audit event. An invalid selection
     is rejected with a field-level 422 and NOTHING is persisted. This is separate
     from apply-customer-commercial (which copies CM defaults and stays lenient).

  2. In-place service-charge edit — PATCH /draft/{id}/service-charges/{charge_id}
     via the new update_draft_service_charge writer, completing add/edit/remove on
     the one canonical service-charge writer (amount / currency / label /
     wfirma_service_id / rate_pct; charge_type immutable).

Requested coverage: dropdown selections validate (422 on invalid); freight/
insurance add + edit + remove persists.
"""
from __future__ import annotations

import json
import sqlite3
import sys
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

_ROOT = Path(__file__).parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

BATCH  = "BATCH_PR3_COMMERCIAL"
CLIENT = "PR3_CLIENT"


@pytest.fixture()
def storage(tmp_path):
    from app.services import packing_db as pdb
    from app.services import document_db as ddb
    from app.services import wfirma_db as wfdb
    from app.services import proforma_invoice_link_db as pildb

    pdb.init_packing_db(tmp_path / "packing.db")
    ddb.init_document_db(tmp_path / "documents.db")
    wfdb.init_wfirma_db(tmp_path / "wfirma.db")
    pildb.init_db(tmp_path / "proforma_links.db")

    out = tmp_path / "outputs" / BATCH
    (out / "source").mkdir(parents=True, exist_ok=True)
    (out / "audit.json").write_text(json.dumps(
        {"batch_id": BATCH, "tracking_no": BATCH, "awb": BATCH,
         "carrier": "DHL", "timeline": []}), encoding="utf-8")
    return tmp_path


@pytest.fixture()
def client(storage):
    from app.core.config import settings
    from app.main import app
    with patch.object(settings, "storage_root", storage):
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c, storage


def _auth():
    from app.core.config import settings
    return {"X-API-KEY": settings.api_key or "test-key"}


def _op():
    return {"X-Operator": "test-op", **_auth()}


def _line(currency="EUR"):
    return {"line_id": str(uuid.uuid4()), "product_code": "EJL/1", "design_no": "D1",
            "name_pl": "Ring", "unit_price": 100.0, "qty": 1.0, "quantity": 1.0,
            "currency": currency}


def _seed_draft(storage, lines=None, status="draft", currency="EUR"):
    db = storage / "proforma_links.db"
    with sqlite3.connect(str(db)) as conn:
        cur = conn.execute(
            """INSERT INTO proforma_drafts
                 (batch_id, client_name, status, currency, draft_state,
                  wfirma_proforma_id, wfirma_proforma_fullnumber,
                  source_lines_json, editable_lines_json, service_charges_json,
                  clone_generation, draft_version, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'),datetime('now'))""",
            (BATCH, CLIENT, status, currency, status, None, "", "[]",
             json.dumps(lines or []), "[]", 0, 1),
        )
        conn.commit()
        return cur.lastrowid


def _get(c, did):
    r = c.get(f"/api/v1/proforma/draft/{did}", headers=_auth())
    assert r.status_code == 200, r.text
    return r.json()["draft"]


def _events(storage, did):
    with sqlite3.connect(str(storage / "proforma_links.db")) as conn:
        return [r[0] for r in conn.execute(
            "SELECT event FROM proforma_draft_events WHERE draft_id=?", (did,)).fetchall()]


def _set_commercial(c, did, body, headers=None):
    return c.post(f"/api/v1/proforma/draft/{did}/set-commercial-defaults",
                  json=body, headers=headers if headers is not None else _op())


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Operator-set commercial defaults — validation + persistence
# ═══════════════════════════════════════════════════════════════════════════════

def test_set_commercial_valid_persists(client):
    c, storage = client
    did = _seed_draft(storage)
    d = _get(c, did)
    r = _set_commercial(c, did, {
        "expected_updated_at": d["updated_at"],
        "payment_method": "transfer", "payment_terms_days": 30,
        "invoice_language_id": "2", "vat_mode": "228",
    })
    assert r.status_code == 200, r.text
    refreshed = _get(c, did)
    pt = refreshed.get("payment_terms") or {}
    assert pt.get("method") == "transfer"
    assert int(pt.get("days")) == 30
    assert pt.get("invoice_language_id") == "2"
    assert refreshed.get("vat_code") == "228"
    assert "commercial_defaults_operator_set" in _events(storage, did)


def test_set_commercial_invalid_vat_mode_422(client):
    c, storage = client
    did = _seed_draft(storage)
    d = _get(c, did)
    r = _set_commercial(c, did, {"expected_updated_at": d["updated_at"], "vat_mode": "999"})
    assert r.status_code == 422, r.text
    assert "vat_mode" in r.text
    # nothing persisted
    assert _get(c, did).get("vat_code") is None


def test_set_commercial_invalid_payment_method_422(client):
    c, storage = client
    did = _seed_draft(storage)
    d = _get(c, did)
    r = _set_commercial(c, did, {"expected_updated_at": d["updated_at"],
                                 "payment_method": "bitcoin"})
    assert r.status_code == 422, r.text
    assert "payment_method" in r.text
    assert (_get(c, did).get("payment_terms") or {}).get("method") in (None, "")


def test_set_commercial_invalid_language_422(client):
    c, storage = client
    did = _seed_draft(storage)
    d = _get(c, did)
    r = _set_commercial(c, did, {"expected_updated_at": d["updated_at"],
                                 "invoice_language_id": "99"})
    assert r.status_code == 422, r.text
    assert "invoice_language_id" in r.text


def test_set_commercial_empty_language_is_valid(client):
    """'' = default account language is a VALID selection."""
    c, storage = client
    did = _seed_draft(storage)
    d = _get(c, did)
    r = _set_commercial(c, did, {"expected_updated_at": d["updated_at"],
                                 "invoice_language_id": ""})
    assert r.status_code == 200, r.text


def test_set_commercial_nothing_supplied_400(client):
    c, storage = client
    did = _seed_draft(storage)
    d = _get(c, did)
    r = _set_commercial(c, did, {"expected_updated_at": d["updated_at"]})
    assert r.status_code == 400, r.text


def test_set_commercial_missing_operator_400(client):
    c, storage = client
    did = _seed_draft(storage)
    d = _get(c, did)
    r = _set_commercial(c, did, {"expected_updated_at": d["updated_at"],
                                 "vat_mode": "222"}, headers=_auth())
    assert r.status_code == 400


def test_set_commercial_posted_draft_409(client):
    c, storage = client
    did = _seed_draft(storage, status="posted")
    d = _get(c, did)
    r = _set_commercial(c, did, {"expected_updated_at": d["updated_at"],
                                 "vat_mode": "222"})
    assert r.status_code == 409


def test_set_commercial_stale_lock_409(client):
    c, storage = client
    did = _seed_draft(storage)
    r = _set_commercial(c, did, {"expected_updated_at": "2000-01-01T00:00:00+00:00",
                                 "vat_mode": "222"})
    assert r.status_code == 409


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Freight / insurance add + edit + remove (existing writer + new update)
# ═══════════════════════════════════════════════════════════════════════════════

def _add_charge(c, did, charge, updated_at):
    return c.post(f"/api/v1/proforma/draft/{did}/service-charges",
                  json={"expected_updated_at": updated_at, "charge": charge},
                  headers=_op())


def _patch_charge(c, did, charge_id, updates, updated_at):
    return c.patch(f"/api/v1/proforma/draft/{did}/service-charges/{charge_id}",
                   json={"expected_updated_at": updated_at, "updates": updates},
                   headers=_op())


def _charges(c, did):
    return _get(c, did).get("service_charges") or []


def test_charge_add_edit_remove_roundtrip(client):
    c, storage = client
    did = _seed_draft(storage, lines=[_line("EUR")], currency="EUR")

    # Add freight
    d = _get(c, did)
    r = _add_charge(c, did, {"charge_type": "freight", "amount": 50.0,
                             "currency": "EUR", "label": "DHL",
                             "wfirma_service_id": "13002743"}, d["updated_at"])
    assert r.status_code == 200, r.text
    charges = _charges(c, did)
    fr = next(x for x in charges if x["charge_type"] == "freight")
    assert fr["amount"] == 50.0 and fr["wfirma_service_id"] == "13002743"

    # Edit amount + service id in place
    d = _get(c, did)
    r = _patch_charge(c, did, fr["charge_id"],
                      {"amount": 65.5, "wfirma_service_id": "99999"}, d["updated_at"])
    assert r.status_code == 200, r.text
    fr2 = next(x for x in _charges(c, did) if x["charge_type"] == "freight")
    assert fr2["amount"] == 65.5 and fr2["wfirma_service_id"] == "99999"
    assert "draft_service_charge_updated" in _events(storage, did)

    # Remove
    d = _get(c, did)
    r = c.delete(f"/api/v1/proforma/draft/{did}/service-charges/{fr['charge_id']}",
                 params={"expected_updated_at": d["updated_at"]}, headers=_op())
    assert r.status_code == 200, r.text
    assert not any(x["charge_type"] == "freight" for x in _charges(c, did))


def test_insurance_add_with_rate_then_edit_rate(client):
    c, storage = client
    did = _seed_draft(storage, lines=[_line("EUR")], currency="EUR")
    d = _get(c, did)
    r = _add_charge(c, did, {"charge_type": "insurance", "amount": 12.0,
                             "currency": "EUR", "formula_basis": {"rate_pct": 0.35}},
                    d["updated_at"])
    assert r.status_code == 200, r.text
    ins = next(x for x in _charges(c, did) if x["charge_type"] == "insurance")
    assert ins["formula_basis"]["rate_pct"] == 0.35

    d = _get(c, did)
    r = _patch_charge(c, did, ins["charge_id"], {"rate_pct": 0.50}, d["updated_at"])
    assert r.status_code == 200, r.text
    ins2 = next(x for x in _charges(c, did) if x["charge_type"] == "insurance")
    assert ins2["formula_basis"]["rate_pct"] == 0.50


def test_charge_edit_invalid_amount_rejected(client):
    c, storage = client
    did = _seed_draft(storage, lines=[_line("EUR")], currency="EUR")
    d = _get(c, did)
    _add_charge(c, did, {"charge_type": "freight", "amount": 10.0, "currency": "EUR"},
                d["updated_at"])
    fr = next(x for x in _charges(c, did) if x["charge_type"] == "freight")
    d = _get(c, did)
    r = _patch_charge(c, did, fr["charge_id"], {"amount": -5}, d["updated_at"])
    assert r.status_code == 400, r.text     # ValueError → 400 via dispatch, never 500
    # unchanged
    assert next(x for x in _charges(c, did) if x["charge_type"] == "freight")["amount"] == 10.0


def test_charge_edit_unknown_id_400(client):
    c, storage = client
    did = _seed_draft(storage, lines=[_line("EUR")], currency="EUR")
    d = _get(c, did)
    r = _patch_charge(c, did, 4242, {"amount": 5.0}, d["updated_at"])
    assert r.status_code == 400, r.text


def test_charge_patch_missing_operator_400(client):
    c, storage = client
    did = _seed_draft(storage, lines=[_line("EUR")], currency="EUR")
    d = _get(c, did)
    r = c.patch(f"/api/v1/proforma/draft/{did}/service-charges/1",
                json={"expected_updated_at": d["updated_at"], "updates": {"amount": 5}},
                headers=_auth())   # no X-Operator
    assert r.status_code == 400


# ═══════════════════════════════════════════════════════════════════════════════
# 3. update_draft_service_charge writer unit — charge_type immutable
# ═══════════════════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════════════════
# 4. CommercialLookupService — single authority / anti-drift guard
# ═══════════════════════════════════════════════════════════════════════════════

def test_commercial_lookup_is_single_payment_authority():
    """Customer Master record validation and the operator editor must consume the
    SAME payment-method authority — no independent tables that can drift."""
    from app.services import commercial_lookup as cl
    from app.api import routes_customer_master as rcm
    from app.services import wfirma_dictionary_cache as wdc
    # Customer Master validator delegates to the service.
    assert rcm._ALLOWED_PAYMENT_METHODS == cl.payment_method_ids()
    # The UI dictionary serves the SAME payment methods the service validates.
    dict_ids = {str(m["id"]).strip().lower() for m in wdc.get_dictionaries()["payment_methods"]}
    assert dict_ids == cl.payment_method_ids()


def test_commercial_lookup_enum_ids_are_canonical():
    from app.services import commercial_lookup as cl
    assert cl.vat_mode_ids() == frozenset({"222", "228", "229"})
    assert {"", "1", "2", "3", "4", "5", "6"} <= cl.invoice_language_ids()
    # Validators normalise typed values (int VAT mode, mixed-case payment).
    assert cl.validate_vat_mode(228) and cl.validate_vat_mode("228")
    assert cl.validate_payment_method("TRANSFER")
    assert cl.validate_invoice_language("")          # default language is valid
    assert not cl.validate_vat_mode("999")
    assert not cl.validate_payment_method("bitcoin")
    assert not cl.validate_invoice_language("99")


def test_commercial_lookup_service_product_validation():
    from app.services import commercial_lookup as cl
    assert cl.validate_service_product("freight", "13002743")
    assert cl.validate_service_product("insurance", "13102217")
    assert not cl.validate_service_product("freight", "")      # empty id
    assert not cl.validate_service_product("bogus", "123")     # bad charge type


def test_update_writer_does_not_change_charge_type(client):
    c, storage = client
    from app.services import proforma_invoice_link_db as pildb
    did = _seed_draft(storage, lines=[_line("EUR")], currency="EUR")
    d = _get(c, did)
    _add_charge(c, did, {"charge_type": "freight", "amount": 10.0, "currency": "EUR"},
                d["updated_at"])
    fr = next(x for x in _charges(c, did) if x["charge_type"] == "freight")
    db = storage / "proforma_links.db"
    d = _get(c, did)
    # charge_type is not an editable key — passing it is ignored, type stays freight.
    pildb.update_draft_service_charge(
        db, int(did), int(fr["charge_id"]),
        {"charge_type": "insurance", "amount": 20.0},
        operator="op", expected_updated_at=d["updated_at"])
    after = _charges(c, did)
    fr2 = next(x for x in after if x["charge_id"] == fr["charge_id"])
    assert fr2["charge_type"] == "freight"
    assert fr2["amount"] == 20.0
