"""AWB receiver contact — company vs person from Customer Master delivery authority."""
from __future__ import annotations

from app.api.routes_carrier_actions import _carrier_address_from_delivery_authority
from app.services.carrier.adapters.live import _build_receiver_details
from app.services.customer_master import resolve_delivery_address
from app.services.customer_master_db import CustomerMaster


def _cm(**kw) -> CustomerMaster:
    defaults = dict(
        bill_to_contractor_id="C1",
        bill_to_name="Bill Co",
        country="FR",
        bill_to_street="Bill St 1",
        bill_to_city="Paris",
        bill_to_postal_code="75001",
        ship_to_use_alternate=True,
        ship_to_name="Warehouse Co",
        ship_to_person="Ada Contact",
        ship_to_street="Dock 9",
        ship_to_city="Roissy",
        ship_to_zip="95700",
        ship_to_country="FR",
        ship_to_phone="+331111",
        ship_to_email="wh@example.com",
    )
    defaults.update(kw)
    return CustomerMaster(**defaults)


def test_delivery_authority_keeps_company_and_person_separate():
    addr = resolve_delivery_address(_cm())
    assert addr["name"] == "Warehouse Co"
    assert addr["person"] == "Ada Contact"
    assert addr["name"] != addr["person"]


def test_carrier_address_projection_maps_person_to_contact():
    cm_addr = resolve_delivery_address(_cm())
    carrier = _carrier_address_from_delivery_authority(cm_addr)
    assert carrier["company"] == "Warehouse Co"
    assert carrier["person"] == "Ada Contact"
    assert carrier["name"] == "Ada Contact"
    assert carrier["country_code"] == "FR"


def test_dhl_payload_company_and_fullname_from_cm_delivery():
    cm_addr = resolve_delivery_address(_cm())
    carrier = _carrier_address_from_delivery_authority(cm_addr)
    ci = _build_receiver_details(carrier)["contactInformation"]
    assert ci["companyName"] == "Warehouse Co"
    assert ci["fullName"] == "Ada Contact"
    assert ci["fullName"] != ci["companyName"]


def test_missing_person_does_not_invent_from_company():
    cm_addr = resolve_delivery_address(_cm(ship_to_person=None))
    carrier = _carrier_address_from_delivery_authority(cm_addr)
    assert carrier.get("name") == ""
    assert carrier.get("person") == ""
    ci = _build_receiver_details(carrier)["contactInformation"]
    assert ci["companyName"] == "Warehouse Co"
    assert ci["fullName"] == ""


def test_ui_shape_company_plus_contact_name():
    """AWB modal submits company + name(contact) — both preserved."""
    ci = _build_receiver_details({
        "company": "Warehouse Co",
        "name": "Ada Contact",
        "person": "Ada Contact",
        "city": "Roissy",
        "country_code": "FR",
        "street": "Dock 9",
    })["contactInformation"]
    assert ci["companyName"] == "Warehouse Co"
    assert ci["fullName"] == "Ada Contact"
