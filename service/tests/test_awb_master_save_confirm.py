"""
AWB modal → Customer Master save-confirmation workflow (2026-07-06).

When the AWB modal's shipping fields differ from the client's Customer Master
record, the operator must explicitly choose before any booking:
  Yes  — save to Customer Master ship_to_* fields, then continue booking
  No   — book with the modal values only, master untouched
  Cancel — no save, no booking

Pins:
  - exact prompt texts (general + phone-only variants) and button labels
  - the confirmation gate runs BEFORE booking; createCarrierShipment lives
    only inside doBooking(); the submit button is disabled while the panel
    is open
  - Yes → updateCustomerMaster, and doBooking() only on save success
    (save failure blocks booking); No → doBooking with no master write;
    Cancel → neither
  - saves write ONLY ship_to_* fields (bill_to never touched); VAT/EORI are
    info-only, never written from the modal
  - diff semantics (mirrored): match → no prompt; blank modal value keeps
    master value; country compare case-insensitive; phone-only detection
  - existing endpoint authority reused (PUT /customer-master/{id}); no new
    endpoint, no new page
  - no live DHL calls anywhere (source-pin suite, zero HTTP)
"""
from __future__ import annotations

import re
from pathlib import Path


_V2 = Path(__file__).resolve().parents[1] / "app" / "static" / "v2"
JSX = (_V2 / "proforma-detail.jsx").read_text(encoding="utf-8")
API = (_V2 / "pz-api.js").read_text(encoding="utf-8")

GENERAL_TEXT = ("These shipping details are different from Customer Master. "
                "Save them to this customer\\'s shipping details?")
PHONE_TEXT = ("Receiver phone is required by DHL Express. "
              "Save this phone to Customer Master shipping contact?")


def _modal_src() -> str:
    """The AwbGenerateModal function body."""
    start = JSX.index("function AwbGenerateModal")
    end = JSX.index("function ProformaActionBar")
    return JSX[start:end]


# ── Prompt texts + buttons ─────────────────────────────────────────────────────


class TestConfirmationUx:
    def test_general_prompt_text_exact(self):
        assert GENERAL_TEXT in JSX

    def test_phone_prompt_text_exact(self):
        assert PHONE_TEXT in JSX

    def test_three_buttons_general_labels(self):
        src = _modal_src()
        assert "'Yes, save to Customer Master and continue'" in src
        assert "'No, use only for this AWB'" in src
        assert "awb-master-save-cancel" in src

    def test_three_buttons_phone_labels(self):
        src = _modal_src()
        assert "'No, use only once'" in src
        assert "phoneOnly ? 'Yes'" in src

    def test_saved_note_text(self):
        assert "Shipping details saved to Customer Master" in JSX
        assert "awb-master-saved-note" in JSX

    def test_panel_testids(self):
        for tid in ("awb-master-save-confirm", "awb-master-save-yes",
                    "awb-master-save-no", "awb-master-save-cancel",
                    "awb-master-save-error"):
            assert tid in JSX, tid


# ── Gate ordering: no booking until confirmation resolved ──────────────────────


class TestBookingGate:
    def test_gate_runs_before_booking(self):
        """In handleSubmit the diff check + setSaveConfirm + return come
        BEFORE doBooking(); the booking call itself lives only in doBooking."""
        src = _modal_src()
        submit = src[src.index("const handleSubmit"):src.index("const doBooking")]
        assert "computeMasterDiffs()" in submit
        assert "setSaveConfirm(" in submit
        # the gate returns before doBooking is reached
        assert submit.index("setSaveConfirm(") < submit.index("doBooking()")
        assert "createCarrierShipment" not in submit    # booking not in submit path

    def test_create_shipment_only_inside_dobooking(self):
        src = _modal_src()
        booking = src[src.index("const doBooking"):]
        assert "createCarrierShipment" in booking

    def test_submit_button_disabled_while_panel_open(self):
        assert "disabled={loading || isPending || !!saveConfirm}" in JSX

    def test_yes_books_only_after_successful_save(self):
        """Yes → updateCustomerMaster; doBooking() only in the r.ok branch;
        the failure branch sets an error and does NOT book."""
        src = _modal_src()
        save = src[src.index("const saveShippingToMaster"):src.index("const handleSubmit")]
        assert "saveCustomerMaster" in save
        ok_branch = save[save.index("if (r && r.ok)"):save.index("} else {")]
        assert "doBooking()" in ok_branch
        fail_branch = save[save.index("} else {"):]
        assert "doBooking" not in fail_branch
        assert "setSaveError" in fail_branch

    def test_no_books_without_master_write(self):
        """The No button continues booking and never touches the master."""
        src = _modal_src()
        m = re.search(r"onClick=\{\(\) => \{ setSaveConfirm\(null\); doBooking\(\); \}\}", src)
        assert m, "No button must clear the panel and book directly"
        # the No handler contains no master update
        assert "saveCustomerMaster" not in m.group(0)

    def test_cancel_neither_saves_nor_books(self):
        src = _modal_src()
        m = re.search(
            r"onClick=\{\(\) => \{ setSaveConfirm\(null\); setSaveError\(null\); \}\}", src)
        assert m, "Cancel must only dismiss the panel"
        assert "doBooking" not in m.group(0)
        assert "saveCustomerMaster" not in m.group(0)


# ── Save scope: ship_to only, never billing, VAT/EORI info-only ────────────────


class TestSaveScope:
    def test_ship_field_map_targets_only_ship_to(self):
        src = _modal_src()
        block = src[src.index("_SHIP_FIELD_MAP = ["):src.index("_INFO_FIELD_MAP")]
        targets = re.findall(r"'(ship_to_\w+|bill_to_\w+|\w+)',\s+'", block)
        master_fields = re.findall(r",\s+'(\w+)',\s+'", block)
        assert master_fields and all(f.startswith("ship_to_") for f in master_fields), master_fields

    def test_billing_never_written_from_modal(self):
        src = _modal_src()
        save = src[src.index("const saveShippingToMaster"):src.index("const handleSubmit")]
        assert "bill_to" not in save

    def test_vat_eori_are_info_only(self):
        src = _modal_src()
        assert "_INFO_FIELD_MAP" in src
        assert "not saved from here" in src
        save = src[src.index("const saveShippingToMaster"):src.index("const handleSubmit")]
        assert "info" not in save.replace("setSavingMaster", "")  # payload built from diffs only
        assert "saveConfirm.diffs" in save

    def test_new_ship_to_sets_alternate_flag(self):
        """A brand-new shipping address (master had none) is saved AS the
        client's shipping address — ship_to_use_alternate set, billing intact."""
        src = _modal_src()
        save = src[src.index("const saveShippingToMaster"):src.index("const handleSubmit")]
        assert "ship_to_use_alternate = true" in save
        assert "hadShipTo" in save


# ── Diff semantics (Python mirror of the pinned JS) ────────────────────────────


SHIP_FIELD_MAP = [
    ("company_name", "ship_to_name"), ("name", "ship_to_person"),
    ("street", "ship_to_street"), ("city", "ship_to_city"),
    ("postal_code", "ship_to_zip"), ("country_code", "ship_to_country"),
    ("phone", "ship_to_phone"), ("email", "ship_to_email"),
]


def _diffs(master: dict, form: dict) -> list:
    """Mirror of computeMasterDiffs (ship fields only)."""
    out = []
    for fk, mk in SHIP_FIELD_MAP:
        mv = str(master.get(mk) or "").strip()
        fv = str(form.get(fk) or "").strip()
        if not fv:
            continue
        same = mv.upper() == fv.upper() if fk == "country_code" else mv == fv
        if not same:
            out.append(fk)
    return out


MASTER = {
    "ship_to_name": "MAIRO DIAMONDS s.r.o.", "ship_to_street": "Republiky 6/5",
    "ship_to_city": "PLZEN 1", "ship_to_zip": "30100",
    "ship_to_country": "CZ", "ship_to_phone": "", "ship_to_email": "",
}
FORM_MATCH = {
    "company_name": "MAIRO DIAMONDS s.r.o.", "street": "Republiky 6/5",
    "city": "PLZEN 1", "postal_code": "30100", "country_code": "cz",
    "phone": "", "email": "",
}


class TestDiffSemantics:
    def test_no_prompt_when_values_match_master(self):
        assert _diffs(MASTER, FORM_MATCH) == []

    def test_country_compare_case_insensitive(self):
        assert "country_code" not in _diffs(MASTER, {**FORM_MATCH, "country_code": "Cz"})

    def test_changed_address_prompts(self):
        assert _diffs(MASTER, {**FORM_MATCH, "street": "New Street 1"}) == ["street"]

    def test_new_phone_is_phone_only_diff(self):
        """Master phone empty + modal phone typed → exactly the phone-only case."""
        d = _diffs(MASTER, {**FORM_MATCH, "phone": "+420777123456"})
        assert d == ["phone"]

    def test_blank_modal_value_keeps_master_value(self):
        """Blank modal field is NOT a difference — never erases master data."""
        assert _diffs(MASTER, {**FORM_MATCH, "city": ""}) == []

    def test_phone_only_pinned_in_source(self):
        src = _modal_src()
        assert "d.formKey === 'phone' && masterPhoneEmpty" in src.replace("cmp.diffs[0].formKey", "d.formKey")


# ── Authority reuse + safety ───────────────────────────────────────────────────


class TestAuthorityAndSafety:
    def test_existing_customer_master_endpoint_reused(self):
        """No new endpoint: the modal saves via the existing PUT wrapper."""
        assert "saveCustomerMaster" in API
        assert "customer-master/${encodeURIComponent(" in API
        src = _modal_src()
        assert "getCustomerMaster(prefill.client_contractor_id)" in src

    def test_no_baseline_means_no_prompt_no_save(self):
        src = _modal_src()
        assert "if (!master) return null" in src

    def test_parent_passes_client_identity(self):
        assert "client_contractor_id: (liveDraft && liveDraft.client_contractor_id)" in JSX

    def test_dhl_adapter_untouched_by_feature(self):
        live = (Path(__file__).resolve().parents[1]
                / "app" / "services" / "carrier" / "adapters" / "live.py").read_text(encoding="utf-8")
        assert "customer_master" not in live
        assert "saveCustomerMaster" not in live
