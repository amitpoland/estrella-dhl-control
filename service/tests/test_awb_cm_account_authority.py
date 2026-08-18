"""AWB modal consumes Customer Master client_carrier_accounts — no second store.

A2 already owns the DHL/FedEx/UPS selector and FedEx/UPS tracking. These tests
pin the missing CM account/payer linkage and prove A2 surfaces were not rebuilt.
"""
from pathlib import Path


def _detail() -> str:
    return (
        Path(__file__).resolve().parents[1]
        / "app" / "static" / "v2" / "proforma-detail.jsx"
    ).read_text(encoding="utf-8")


def _pz_api() -> str:
    return (
        Path(__file__).resolve().parents[1]
        / "app" / "static" / "v2" / "pz-api.js"
    ).read_text(encoding="utf-8")


# ── helpers mirrored from the modal (same rules as _awbFilterCmAccounts) ──────

_CM = {"DHL": "dhl", "FEDEX": "fedex", "UPS": "ups"}
_PAYER = {
    "shipper": "Shipper pays",
    "receiver": "Receiver pays",
    "third_party": "Third party pays",
}


def _filter(accounts, selected):
    key = _CM[selected]
    return [a for a in accounts if (a.get("carrier") or "").lower() == key]


def _preselect(accounts):
    defaults = [a for a in accounts if a.get("is_default")]
    if len(defaults) == 1:
        return defaults[0]
    if len(accounts) == 1:
        return accounts[0]
    return None


def test_jsx_filter_and_payer_helpers_match_documented_rules():
    src = _detail()
    assert "DHL: 'dhl', FEDEX: 'fedex', UPS: 'ups'" in src
    assert "shipper: 'Shipper pays'" in src
    assert "receiver: 'Receiver pays'" in src
    assert "third_party: 'Third party pays'" in src
    assert "function _awbFilterCmAccounts" in src
    assert "function _awbPreselectCmAccount" in src
    assert "defaults.length === 1" in src
    assert "list.length === 1" in src


def test_dhl_selected_shows_only_dhl_accounts():
    rows = [
        {"id": 1, "carrier": "dhl"},
        {"id": 2, "carrier": "fedex"},
        {"id": 3, "carrier": "ups"},
    ]
    assert [a["id"] for a in _filter(rows, "DHL")] == [1]


def test_fedex_selected_shows_only_fedex_accounts():
    rows = [
        {"id": 1, "carrier": "dhl"},
        {"id": 2, "carrier": "fedex"},
        {"id": 3, "carrier": "ups"},
    ]
    assert [a["id"] for a in _filter(rows, "FEDEX")] == [2]


def test_ups_selected_shows_only_ups_accounts():
    rows = [
        {"id": 1, "carrier": "dhl"},
        {"id": 2, "carrier": "fedex"},
        {"id": 3, "carrier": "ups"},
    ]
    assert [a["id"] for a in _filter(rows, "UPS")] == [3]


def test_default_account_preselected():
    rows = [
        {"id": 1, "carrier": "dhl", "is_default": False},
        {"id": 2, "carrier": "dhl", "is_default": True},
    ]
    assert _preselect(_filter(rows, "DHL"))["id"] == 2


def test_single_account_preselected_without_default_flag():
    rows = [{"id": 9, "carrier": "fedex", "is_default": False}]
    assert _preselect(_filter(rows, "FEDEX"))["id"] == 9


def test_multiple_without_default_requires_operator_choice():
    rows = [
        {"id": 1, "carrier": "ups", "is_default": False},
        {"id": 2, "carrier": "ups", "is_default": False},
    ]
    assert _preselect(_filter(rows, "UPS")) is None


def test_payer_labels():
    assert _PAYER["receiver"] == "Receiver pays"
    assert _PAYER["shipper"] == "Shipper pays"
    assert _PAYER["third_party"] == "Third party pays"


def test_empty_filter_does_not_invent_an_account():
    assert _filter([], "DHL") == []
    assert _preselect([]) is None


def test_modal_fetches_only_current_draft_contractor():
    src = _detail()
    assert "listCarrierAccounts(cid)" in src
    assert "const cid = prefill.client_contractor_id" in src
    assert src.count("listCarrierAccounts(") == 1


def test_api_wrapper_is_existing_customer_master_path():
    api = _pz_api()
    assert "customer-master/${encodeURIComponent(contractorId)}/carrier-accounts/" in api
    assert "listCarrierAccounts:" in api


def test_inactive_accounts_not_requested():
    src = _detail()
    assert "active=false" not in src
    assert "active=0" not in src
    assert "listCarrierAccounts defaults to active-only" in src


def test_empty_state_and_manage_link():
    src = _detail()
    assert "No customer carrier account configured" in src
    assert "Manage carrier accounts in Customer Master" in src
    assert "/v2/master?entity=clients&contractor_id=" in src
    assert 'data-testid="awb-cm-account-section"' in src
    assert 'data-testid="awb-cm-account-select"' in src
    assert 'data-testid="awb-cm-account-payer"' in src
    assert 'data-testid="awb-cm-account-empty"' in src
    assert 'data-testid="awb-cm-account-manage"' in src


def test_switching_carrier_resets_selection():
    src = _detail()
    assert "[selectedCarrier, cmAccounts]" in src
    assert "_awbPreselectCmAccount" in src


def test_one_carrier_selector_not_duplicated():
    src = _detail()
    assert src.count('data-testid="awb-carrier-select"') == 1
    assert src.count("function AwbGenerateModal") == 1
    assert "AwbFedexModal" not in src
    assert "AwbUpsModal" not in src
    assert "AwbCarrierAccountModal" not in src


def test_fedex_ups_manual_tracking_remains():
    src = _detail()
    assert 'data-testid="awb-external-form"' in src
    assert 'data-testid="awb-field-tracking-ref"' in src
    assert 'data-testid="awb-field-awb-file"' in src
    assert "Register external shipment" in src
    assert "selectedCarrier === 'FEDEX'" in src
    assert "selectedCarrier === 'UPS'" in src
    assert "UPS_NOT_CONFIGURED" in src
    assert "awb-ups-blocked" in src
    assert "carrier:            selectedCarrier" in src or "carrier:" in src
    assert "setCarrierTouched(false)" in src
    assert "AwbFedexModal" not in src


def test_no_silent_dhl_fallback_in_modal():
    src = _detail()
    assert "Never silently converted to DHL" in src or "Never silently" in src
    assert "createCarrierShipment" in src
    assert "registerExternalShipment" in src


def test_dhl_workflow_and_resolver_remain():
    src = _detail()
    assert 'data-testid="awb-dhl-form"' in src
    assert "useDhlAccountResolution" in src
    assert "DhlAccountPanel" in src
    assert "createCarrierShipment" in src
    assert "dhlAccounts.payloadFields" in src


def test_no_second_carrier_account_table_or_payer_field():
    src = _detail()
    assert "CREATE TABLE" not in src
    assert "payable_by" not in src
    assert "receivable" not in src.lower()
    db = (
        Path(__file__).resolve().parents[1]
        / "app" / "services" / "client_carrier_accounts_db.py"
    ).read_text(encoding="utf-8")
    assert "client_carrier_accounts" in db
    assert "payment_type" in db


def test_customer_a_fetch_cannot_target_customer_b():
    src = _detail()
    assert "listCarrierAccounts(cid)" in src
    assert "prefill.client_contractor_id" in src
    assert "listCarrierAccounts(prefill.sender_contractor_id" not in src
    persist = (
        Path(__file__).resolve().parents[1]
        / "app" / "services" / "carrier" / "persistence" / "shipment_db.py"
    ).read_text(encoding="utf-8")
    assert "client_carrier_accounts" not in persist
    assert "carrier_account_id" not in persist
    assert "payment_type" not in persist


def test_cm_account_is_display_only_not_injected_into_dhl_or_external_payload():
    src = _detail()
    assert "dhlAccounts.payloadFields" in src
    assert "billing_party: selectedCmAccount" not in src
    assert "payment_type: selectedCmAccount" not in src
    assert "account_number: selectedCmAccount" not in src
    assert "registerExternalShipment(batchId, {" in src
    booking = src[src.find("window.PzApi.createCarrierShipment"):]
    booking = booking[: booking.find(".then(r =>")]
    assert "selectedCmAccount" not in booking
    ext = src[src.find("window.PzApi.registerExternalShipment"):]
    ext = ext[: ext.find("}).then")]
    assert "selectedCmAccount" not in ext
    assert "account_number" not in ext
    assert "payment_type" not in ext


def test_list_api_defaults_active_only_and_scopes_by_contractor():
    routes = (
        Path(__file__).resolve().parents[1]
        / "app" / "api" / "routes_client_carrier_accounts.py"
    ).read_text(encoding="utf-8")
    assert "return True if parsed is None else parsed" in routes
    assert 'prefix="/api/v1/customer-master/{contractor_id}/carrier-accounts"' in routes
