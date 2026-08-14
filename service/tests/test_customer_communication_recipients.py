"""Recipient resolver + delivery lifecycle matrix."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services import customer_communication_recipients as ccr
from app.services import customer_master_db as cmdb


def _seed_customer(db: Path, cid: str = "1001", email: str = "primary@example.com", ship: str = ""):
    cmdb.init_db(db)
    c = cmdb.CustomerMaster(
        bill_to_contractor_id=cid,
        bill_to_name="Test Co",
        country="IE",
        bill_to_email=email or None,
        ship_to_email=ship or None,
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
    )
    cmdb.upsert_customer(db, c)
    return cid


def test_legacy_bill_to_only(tmp_path):
    db = tmp_path / "cm.sqlite"
    _seed_customer(db, email="bill@ex.com", ship="ship@ex.com")
    r = ccr.resolve_customer_communication_recipients(db_path=db, contractor_id="1001")
    assert r["to"] == ["bill@ex.com"]
    assert r["cc"] == []
    assert r["source"] == "legacy_bill_to_ship_to"


def test_legacy_ship_to_when_bill_missing(tmp_path):
    db = tmp_path / "cm.sqlite"
    _seed_customer(db, email="", ship="ship@ex.com")
    r = ccr.resolve_customer_communication_recipients(db_path=db, contractor_id="1001")
    assert r["to"] == ["ship@ex.com"]


def test_multi_to_cc_and_dedupe(tmp_path):
    db = tmp_path / "cm.sqlite"
    _seed_customer(db)
    with pytest.raises(ccr.RecipientValidationError):
        ccr.replace_communication_recipients(
            db_path=db,
            contractor_id="1001",
            to=[
                {"email": "a@ex.com", "is_primary": True},
                {"email": "b@ex.com"},
                {"email": "A@ex.com"},  # case dup within To
            ],
            cc=[{"email": "cc@ex.com"}],
        )


def test_multi_to_cc_ok(tmp_path):
    db = tmp_path / "cm.sqlite"
    _seed_customer(db)
    ccr.replace_communication_recipients(
        db_path=db,
        contractor_id="1001",
        to=[{"email": "a@ex.com", "is_primary": True}, {"email": "b@ex.com"}],
        cc=[{"email": "cc@ex.com"}, {"email": "a@ex.com"}],
    )
    r = ccr.resolve_customer_communication_recipients(db_path=db, contractor_id="1001")
    assert r["to"] == ["a@ex.com", "b@ex.com"]
    assert r["cc"] == ["cc@ex.com"]  # a@ dropped from CC
    assert r["source"] == "customer_master"


def test_crlf_rejected():
    with pytest.raises(ccr.RecipientValidationError):
        ccr.validate_email_address("evil@ex.com\\nBcc: x@y.com")


def test_invalid_email_rejected(tmp_path):
    db = tmp_path / "cm.sqlite"
    _seed_customer(db)
    with pytest.raises(ccr.RecipientValidationError):
        ccr.replace_communication_recipients(
            db_path=db, contractor_id="1001",
            to=[{"email": "not-an-email"}], cc=[],
        )


def test_send_override_not_persisted(tmp_path):
    db = tmp_path / "cm.sqlite"
    _seed_customer(db)
    ccr.replace_communication_recipients(
        db_path=db, contractor_id="1001",
        to=[{"email": "stored@ex.com", "is_primary": True}],
        cc=[{"email": "stored-cc@ex.com"}],
    )
    r = ccr.resolve_customer_communication_recipients(
        db_path=db, contractor_id="1001",
        to_override=["oneoff@ex.com"],
        cc_override=["oneoff-cc@ex.com"],
    )
    assert r["to"] == ["oneoff@ex.com"]
    assert r["cc"] == ["oneoff-cc@ex.com"]
    assert r["source"] == "send_override"
    again = ccr.resolve_customer_communication_recipients(db_path=db, contractor_id="1001")
    assert again["to"] == ["stored@ex.com"]
    assert again["cc"] == ["stored-cc@ex.com"]


def test_merge_cc_keeps_internal_out_of_to():
    merged = ccr.merge_cc_layers(
        customer_cc=["cust-cc@ex.com"],
        mandatory_internal_cc=["internal@estrella.eu"],
        to=["cust@ex.com", "internal@estrella.eu"],
    )
    assert "internal@estrella.eu" not in merged
    assert "cust-cc@ex.com" in merged


def test_air_waybill_never_promotes_receipt():
    from app.services.customer_send import _resolve_air_waybill_entry
    from app.services.shipment_document_manifest import GENERATED
    manifest = {
        "groups": {
            "carrier": [
                {
                    "document_type": "dhl_receipt",
                    "status": GENERATED,
                    "download_available": True,
                    "download_url": "/receipt",
                    "reference": "1",
                }
            ]
        }
    }
    assert _resolve_air_waybill_entry(manifest) is None


def test_fedex_label_promotes_to_air_waybill():
    from app.services.customer_send import _resolve_air_waybill_entry
    from app.services.shipment_document_manifest import GENERATED
    manifest = {
        "groups": {
            "carrier": [
                {
                    "document_type": "dhl_label",
                    "status": GENERATED,
                    "download_available": True,
                    "download_url": "/label",
                    "reference": "7946",
                    "source": "FEDEX",
                }
            ]
        }
    }
    entry = _resolve_air_waybill_entry(manifest)
    assert entry["_store_kind"] == "label"
    assert entry["document_type"] == "air_waybill"
