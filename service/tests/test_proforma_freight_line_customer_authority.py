"""Outgoing freight-line good_id: Customer Master commercial method wins.

Pins the real draft-post composition path:

  _build_proforma_request_from_draft
    → _build_service_charge_lines
    → ProformaRequest.lines
    → _build_proforma_xml
    → <good><id>

Product Mirror product_code='freight' is fallback identity only. It must
not replace an explicit Customer Master freight_service_id.

No network. No live wFirma POST.
"""
from __future__ import annotations

import json
import re
import sys
from contextlib import ExitStack
from pathlib import Path
from typing import Any, Dict, Optional
from unittest.mock import MagicMock, patch


def _ensure_path() -> None:
    here = Path(__file__).resolve()
    for p in (str(here.parents[1]), str(here.parents[2])):
        if p not in sys.path:
            sys.path.insert(0, p)


_ensure_path()

from app.services.commercial_lookup import (  # noqa: E402
    FREIGHT_METHOD_FEDEX_COURIER,
    FREIGHT_METHOD_FREIGHT,
    WFIRMA_LANG_POLISH,
)
from app.services.customer_master_db import CustomerMaster  # noqa: E402
from app.services.proforma_invoice_link_db import ProformaDraft  # noqa: E402
from app.services.wfirma_client import _build_proforma_xml  # noqa: E402

_GOODS_CODE = "EJL/26-27/FREIGHT-AUTH-001"
_GOODS_ID = "48461283"
_INSURANCE_MIRROR = "13102217"
_CUST_ID = "WF-CUST-FREIGHT-AUTH"


def _customer_resolution() -> Dict[str, Any]:
    return {
        "raw_input": "TEST_CLIENT",
        "normalized_name": "test_client",
        "found": True,
        "ambiguous": False,
        "match_strategy": "exact",
        "customer": {
            "country": "PL",
            "vat_id": "",
            "ship_to_mode": "same_as_bill_to",
            "ship_to_wfirma_customer_id": "",
        },
        "wfirma_customer_id": _CUST_ID,
        "resolved_wfirma_name": "TEST_CLIENT",
        "candidates": [],
    }


def _cm(freight_service_id: Optional[str]) -> CustomerMaster:
    return CustomerMaster(
        bill_to_contractor_id=_CUST_ID,
        bill_to_name="TEST_CLIENT",
        country="PL",
        freight_service_id=freight_service_id,
        default_language_id=WFIRMA_LANG_POLISH,
    )


def _mirror_side_effect(product_code: str) -> Optional[str]:
    token = (product_code or "").strip().lower()
    if token == "freight":
        return FREIGHT_METHOD_FEDEX_COURIER
    if token == "insurance":
        return _INSURANCE_MIRROR
    if token:
        return _GOODS_ID
    return None


def _draft(
    freight_service_id_on_charge: Optional[str],
    include_insurance: bool = False,
) -> ProformaDraft:
    charges = []
    freight = {
        "charge_type": "freight",
        "amount": "150.00",
        "currency": "EUR",
    }
    if freight_service_id_on_charge is not None:
        freight["wfirma_service_id"] = freight_service_id_on_charge
    charges.append(freight)
    if include_insurance:
        charges.append({
            "charge_type": "insurance",
            "amount": "15.00",
            "currency": "EUR",
        })
    return ProformaDraft(
        batch_id="EJL-26-27-FREIGHT-AUTH",
        client_name="TEST_CLIENT",
        status="approved",
        draft_state="approved",
        currency="EUR",
        editable_lines_json=json.dumps([{
            "product_code": _GOODS_CODE,
            "qty": 1.0,
            "unit_price": 500.0,
            "currency": "EUR",
            "design_no": "D-FREIGHT-AUTH",
        }]),
        service_charges_json=json.dumps(charges),
        id=99,
    )


def _xml_good_ids(xml: str):
    return re.findall(r"<good>\s*<id>([^<]+)</id>\s*</good>", xml)


def _xml_lang_ids(xml: str):
    return re.findall(
        r"<translation_language>\s*<id>([^<]*)</id>\s*</translation_language>",
        xml,
    )


def _compose(cm_freight: Optional[str], charge_freight: Optional[str],
             include_insurance: bool = False):
    from app.api.routes_proforma import _build_proforma_request_from_draft

    mock_wfdb = MagicMock()
    mock_wfdb._db_path = Path("/fake/wfirma.db")
    with ExitStack() as stack:
        stack.enter_context(patch(
            "app.api.routes_proforma._resolve_customer",
            return_value=_customer_resolution(),
        ))
        stack.enter_context(patch(
            "app.api.routes_proforma.get_customer_master",
            return_value=_cm(cm_freight),
        ))
        stack.enter_context(patch("app.api.routes_proforma.wfdb", mock_wfdb))
        stack.enter_context(patch(
            "app.api.routes_proforma._c1f_mirror_good_id",
            side_effect=_mirror_side_effect,
        ))
        stack.enter_context(patch(
            "app.services.wfirma_client.resolve_vat_code_id_for_context",
            return_value="42",
        ))
        req, note, warnings, freeze = _build_proforma_request_from_draft(
            _draft(charge_freight, include_insurance=include_insurance),
        )
        xml = _build_proforma_xml(req)
    return req, xml, note, warnings, freeze


def _freight_good_id(req) -> Optional[str]:
    lines = [ln for ln in req.lines if ln.product_code == "freight"]
    assert len(lines) == 1, [ln.product_code for ln in req.lines]
    return lines[0].wfirma_good_id


class TestDraftPostFreightLineAuthority:
    def test_a_explicit_freight_reaches_xml(self):
        req, xml, *_ = _compose(FREIGHT_METHOD_FREIGHT, FREIGHT_METHOD_FREIGHT)
        assert _freight_good_id(req) == FREIGHT_METHOD_FREIGHT
        assert FREIGHT_METHOD_FREIGHT in _xml_good_ids(xml)
        assert FREIGHT_METHOD_FEDEX_COURIER not in _xml_good_ids(xml)

    def test_b_explicit_fedex_courier_reaches_xml(self):
        req, xml, *_ = _compose(
            FREIGHT_METHOD_FEDEX_COURIER, FREIGHT_METHOD_FEDEX_COURIER,
        )
        assert _freight_good_id(req) == FREIGHT_METHOD_FEDEX_COURIER
        assert FREIGHT_METHOD_FEDEX_COURIER in _xml_good_ids(xml)
        assert FREIGHT_METHOD_FREIGHT not in _xml_good_ids(xml)

    def test_c_unset_defaults_to_mirror_fedex_courier(self):
        req, xml, *_ = _compose(None, None)
        assert _freight_good_id(req) == FREIGHT_METHOD_FEDEX_COURIER
        assert FREIGHT_METHOD_FEDEX_COURIER in _xml_good_ids(xml)
        assert FREIGHT_METHOD_FREIGHT not in _xml_good_ids(xml)

    def test_d_mirror_cannot_override_explicit_freight(self):
        """Decisive conflict: CM Freight vs Product Mirror Fedex Courier."""
        req, xml, *_ = _compose(FREIGHT_METHOD_FREIGHT, FREIGHT_METHOD_FREIGHT)
        assert _freight_good_id(req) == FREIGHT_METHOD_FREIGHT
        assert _xml_good_ids(xml) == [_GOODS_ID, FREIGHT_METHOD_FREIGHT]

    def test_cm_freight_wins_when_charge_snapshot_omits_service_id(self):
        req, xml, *_ = _compose(FREIGHT_METHOD_FREIGHT, None)
        assert _freight_good_id(req) == FREIGHT_METHOD_FREIGHT
        assert FREIGHT_METHOD_FREIGHT in _xml_good_ids(xml)

    def test_insurance_stays_mirror_while_freight_is_explicit(self):
        req, xml, *_ = _compose(
            FREIGHT_METHOD_FREIGHT, FREIGHT_METHOD_FREIGHT,
            include_insurance=True,
        )
        by_code = {ln.product_code: ln.wfirma_good_id for ln in req.lines}
        assert by_code["freight"] == FREIGHT_METHOD_FREIGHT
        assert by_code["insurance"] == _INSURANCE_MIRROR
        assert _xml_good_ids(xml) == [
            _GOODS_ID, FREIGHT_METHOD_FREIGHT, _INSURANCE_MIRROR,
        ]

    def test_polish_language_zero_still_emitted(self):
        req, xml, *_ = _compose(FREIGHT_METHOD_FREIGHT, FREIGHT_METHOD_FREIGHT)
        assert req.translation_language_id == WFIRMA_LANG_POLISH
        assert _xml_lang_ids(xml) == [WFIRMA_LANG_POLISH]


class TestFreightGoodIdCensus:
    def test_canonical_consumer_uses_commercial_lookup_then_mirror(self):
        import inspect
        from app.api.routes_proforma import _build_service_charge_lines
        src = inspect.getsource(_build_service_charge_lines)
        assert "resolve_freight_method_id" in src
        assert "_c1f_mirror_good_id" in src
        assert "17833901" not in src
        assert "13002743" not in src

    def test_mydhl_shipment_body_untouched(self):
        live = (
            Path(__file__).resolve().parents[1]
            / "app" / "services" / "carrier" / "adapters" / "live.py"
        )
        src = live.read_text(encoding="utf-8")
        assert "def _build_shipment_body" in src
        assert '"productCode": product_code or request.product_code or "P"' in src

    def test_canonical_ids_unchanged(self):
        assert FREIGHT_METHOD_FREIGHT == "17833901"
        assert FREIGHT_METHOD_FEDEX_COURIER == "13002743"
        assert WFIRMA_LANG_POLISH == "0"
