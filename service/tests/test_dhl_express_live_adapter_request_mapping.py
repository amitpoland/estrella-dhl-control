"""
test_dhl_express_live_adapter_request_mapping.py — DL-F1 pure-logic
mapping tests for ``build_create_shipment_body``.

Required:
  * Multi-package requests produce N entries in content.packages[].
  * Account number always lands at accounts[0].number.
  * batch_id / reference land in customerReferences[].
  * Address fields land at the documented JSON paths.
  * Defaults for productCode / incoterm fire when caller omits them.
  * Empty packages or empty account_number raise ValueError.
"""
from __future__ import annotations

import pytest

from app.services.carrier.adapters.dhl_express_live_request import (
    build_create_shipment_body,
)
from app.services.carrier.base import (
    CarrierAddress, CarrierShipmentRequest, PackageSpec,
)


def _addr(country="PL") -> CarrierAddress:
    return CarrierAddress(
        name="Estrella Jewels", company="Estrella Jewels",
        street_1="ul. Marszalkowska 1", street_2="floor 5",
        city="Warsaw", postal_code="00-001", country=country,
        phone="+48-22-555-0000", email="ops@estrellajewels.eu",
    )


def _pkg(weight=0.5, value=999.0, currency="USD",
         description="Diamond pendant") -> PackageSpec:
    return PackageSpec(
        weight_kg=weight, length_cm=15.0, width_cm=10.0, height_cm=5.0,
        declared_value=value, declared_currency=currency,
        description=description,
    )


def _req(packages=None, batch_id="B-RM-1", reference="R-RM",
         service_code="P") -> CarrierShipmentRequest:
    return CarrierShipmentRequest(
        batch_id=batch_id,
        ship_from=_addr("PL"), ship_to=_addr("US"),
        packages=tuple(packages or [_pkg()]),
        service_code=service_code, reference=reference,
    )


# ── Account number is mandatory and always present ────────────────────────

def test_request_helper_always_includes_account_number():
    body = build_create_shipment_body(_req(), account_number="ACC-12345")
    assert body["accounts"][0]["number"] == "ACC-12345"
    assert body["accounts"][0]["typeCode"] == "shipper"


def test_request_helper_rejects_blank_account_number():
    with pytest.raises(ValueError):
        build_create_shipment_body(_req(), account_number="")


def test_request_helper_rejects_blank_account_number_whitespace():
    with pytest.raises(ValueError):
        build_create_shipment_body(_req(), account_number="   ")


# ── Multi-package mapping ────────────────────────────────────────────────

def test_request_helper_maps_multi_package_requests():
    pkgs = [_pkg(weight=0.5), _pkg(weight=1.2), _pkg(weight=2.0)]
    body = build_create_shipment_body(_req(packages=pkgs),
                                       account_number="ACC-1")
    assert len(body["content"]["packages"]) == 3
    assert body["content"]["packages"][0]["weight"] == 0.5
    assert body["content"]["packages"][1]["weight"] == 1.2
    assert body["content"]["packages"][2]["weight"] == 2.0


def test_request_helper_rejects_empty_packages():
    bad = CarrierShipmentRequest(
        batch_id="B", ship_from=_addr(), ship_to=_addr("US"),
        packages=(), service_code="P", reference="R",
    )
    with pytest.raises(ValueError):
        build_create_shipment_body(bad, account_number="ACC-1")


# ── batch_id + reference at customerReferences[] ─────────────────────────

def test_batch_id_and_reference_land_in_customer_references():
    body = build_create_shipment_body(_req(batch_id="B-X", reference="R-Y"),
                                       account_number="ACC")
    refs = body["customerReferences"]
    values = {r["value"] for r in refs}
    assert "B-X" in values
    assert "R-Y" in values


def test_reference_equal_to_batch_id_emits_only_one():
    body = build_create_shipment_body(_req(batch_id="SAME", reference="SAME"),
                                       account_number="ACC")
    assert len(body["customerReferences"]) == 1
    assert body["customerReferences"][0]["value"] == "SAME"


def test_empty_reference_emits_only_batch_id():
    body = build_create_shipment_body(_req(batch_id="B", reference=""),
                                       account_number="ACC")
    assert [r["value"] for r in body["customerReferences"]] == ["B"]


# ── Address mapping ────────────────────────────────────────────────────

def test_shipper_and_receiver_addresses_land_at_documented_paths():
    body = build_create_shipment_body(_req(), account_number="ACC")
    sh = body["customerDetails"]["shipperDetails"]
    re = body["customerDetails"]["receiverDetails"]
    assert sh["postalAddress"]["countryCode"] == "PL"
    assert re["postalAddress"]["countryCode"] == "US"
    assert sh["postalAddress"]["addressLine1"] == "ul. Marszalkowska 1"
    assert sh["postalAddress"]["addressLine2"] == "floor 5"
    assert sh["postalAddress"]["cityName"]    == "Warsaw"
    assert sh["postalAddress"]["postalCode"]  == "00-001"
    assert sh["contactInformation"]["fullName"]    == "Estrella Jewels"
    assert sh["contactInformation"]["companyName"] == "Estrella Jewels"
    assert sh["contactInformation"]["phone"]       == "+48-22-555-0000"


# ── Defaults + service code mapping ────────────────────────────────────

def test_default_product_code_when_service_code_blank():
    body = build_create_shipment_body(_req(service_code=""),
                                       account_number="ACC")
    assert body["productCode"] == "P"   # EXPRESS WORLDWIDE default


def test_caller_supplied_product_code_passed_through():
    body = build_create_shipment_body(_req(service_code="W"),
                                       account_number="ACC")
    assert body["productCode"] == "W"


def test_default_incoterm_is_dap():
    body = build_create_shipment_body(_req(), account_number="ACC")
    assert body["content"]["incoterm"] == "DAP"


def test_caller_supplied_incoterm_passed_through():
    body = build_create_shipment_body(_req(), account_number="ACC",
                                       incoterm="DDP")
    assert body["content"]["incoterm"] == "DDP"


# ── Declared value aggregation ─────────────────────────────────────────

def test_declared_value_sums_across_packages():
    pkgs = [_pkg(value=100.0), _pkg(value=250.0), _pkg(value=50.0)]
    body = build_create_shipment_body(_req(packages=pkgs),
                                       account_number="ACC")
    assert body["content"]["declaredValue"] == 400.0


def test_declared_currency_taken_from_first_package():
    pkgs = [_pkg(currency="EUR"), _pkg(currency="USD")]
    body = build_create_shipment_body(_req(packages=pkgs),
                                       account_number="ACC")
    assert body["content"]["declaredValueCurrency"] == "EUR"


# ── Output image template ─────────────────────────────────────────────

def test_default_label_template_present():
    body = build_create_shipment_body(_req(), account_number="ACC")
    options = body["outputImageProperties"]["imageOptions"]
    assert options[0]["templateName"] == "ECOM26_84_001"
    assert options[0]["typeCode"]     == "label"
    assert options[0]["isRequested"]  is True


def test_planned_shipping_dt_caller_override_passes_through():
    body = build_create_shipment_body(
        _req(), account_number="ACC",
        planned_shipping_dt="2026-04-15T10:00:00+00:00",
    )
    assert body["plannedShippingDateAndTime"] == "2026-04-15T10:00:00+00:00"


# ── Pickup is never inline ────────────────────────────────────────────

def test_pickup_is_always_not_requested_inline():
    """Estrella books pickups via /pickups; never inline on shipments."""
    body = build_create_shipment_body(_req(), account_number="ACC")
    assert body["pickup"]["isRequested"] is False


# ── DL-F3 — Paperless Trade mapping ─────────────────────────────────────

def test_no_paperless_trade_block_when_no_pdf_bytes():
    """Backwards-compat with DL-F1 baseline: when the caller passes
    no PLT bytes, body has no exportDeclaration / documentImages."""
    body = build_create_shipment_body(_req(), account_number="ACC")
    assert "exportDeclaration" not in body["content"]
    assert "documentImages" not in body


def test_paperless_trade_inlines_document_images_when_bytes_provided():
    pdf = b"%PDF-1.4\nlive-bytes\n%%EOF\n"
    body = build_create_shipment_body(
        _req(), account_number="ACC",
        paperless_trade_pdf_bytes=pdf,
    )
    assert "documentImages" in body
    assert len(body["documentImages"]) == 1
    img = body["documentImages"][0]
    assert img["typeCode"]    == "INV"
    assert img["imageFormat"] == "PDF"
    import base64 as _b64
    decoded = _b64.b64decode(img["content"])
    assert decoded == pdf


def test_paperless_trade_adds_export_declaration_block():
    pdf = b"%PDF-1.4\n"
    body = build_create_shipment_body(
        _req(batch_id="B-PLT", reference="R-PLT"),
        account_number="ACC", paperless_trade_pdf_bytes=pdf,
    )
    decl = body["content"]["exportDeclaration"]
    assert decl["invoice"]["number"]    == "R-PLT"   # reference wins
    assert decl["invoice"]["function"]  == "import"
    # signatureName is the documented constant for Estrella
    assert decl["invoice"]["signatureName"] == "Estrella Jewels"
    assert decl["exportReason"]         == "permanent"
    assert decl["shipmentType"]         == "commercial"


def test_paperless_trade_uses_batch_id_when_reference_missing():
    pdf = b"%PDF-1.4\n"
    body = build_create_shipment_body(
        _req(batch_id="B-ONLY", reference=""),
        account_number="ACC", paperless_trade_pdf_bytes=pdf,
    )
    assert body["content"]["exportDeclaration"]["invoice"]["number"] == "B-ONLY"


def test_paperless_trade_signature_name_override():
    pdf = b"%PDF-1.4\n"
    body = build_create_shipment_body(
        _req(), account_number="ACC",
        paperless_trade_pdf_bytes=pdf,
        paperless_trade_signature_name="Other Signer",
    )
    assert body["content"]["exportDeclaration"]["invoice"]["signatureName"] == "Other Signer"


def test_paperless_trade_invoice_date_uses_planned_shipping_dt():
    pdf = b"%PDF-1.4\n"
    body = build_create_shipment_body(
        _req(), account_number="ACC",
        planned_shipping_dt="2026-04-15T10:00:00+00:00",
        paperless_trade_pdf_bytes=pdf,
    )
    assert body["content"]["exportDeclaration"]["invoice"]["date"] == "2026-04-15"


def test_paperless_trade_zero_bytes_leaves_body_unchanged():
    """Empty bytes is treated as no PLT — same as None."""
    body = build_create_shipment_body(
        _req(), account_number="ACC", paperless_trade_pdf_bytes=b"",
    )
    assert "documentImages" not in body
    assert "exportDeclaration" not in body["content"]


def test_paperless_trade_payload_is_json_serialisable():
    """Body with PLT must round-trip through json.dumps cleanly."""
    import json as _json
    pdf = b"%PDF-1.4\nbinary-junk\x00\x01\x02\n%%EOF\n"
    body = build_create_shipment_body(
        _req(), account_number="ACC",
        paperless_trade_pdf_bytes=pdf,
    )
    encoded = _json.dumps(body)
    decoded = _json.loads(encoded)
    # And the documentImages content is a plain ASCII string, not bytes
    assert isinstance(decoded["documentImages"][0]["content"], str)
