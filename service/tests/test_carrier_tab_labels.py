"""test_carrier_tab_labels.py — Carrier tab presentation contract.

Operator ruling 2026-07-20: presentation-only. Existing fields are reused
(payment_type, is_default, active) and the existing carrier-account CRUD is the
only save path. No new field, flag, endpoint, enum, table or business rule.

Key distinction pinned here: "Billing role" (payment_type — the account's
billing function) and "Default shipping account" (is_default — the default
choice among a client's accounts) are separate concepts. Neither is merged,
renamed into the other, or inferred from the other.
"""
from __future__ import annotations

import pathlib
import re
import sys

import pytest

SERVICE_DIR = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVICE_DIR))

CLIENT_DETAIL = SERVICE_DIR / "app" / "static" / "v2" / "client-detail.jsx"
API = SERVICE_DIR / "app" / "static" / "v2" / "pz-api.js"
DB = SERVICE_DIR / "app" / "services" / "client_carrier_accounts_db.py"


def _read(p: pathlib.Path) -> str:
    return p.read_text(encoding="utf-8")


def _code(p: pathlib.Path) -> str:
    return "\n".join(ln for ln in _read(p).splitlines()
                     if not ln.strip().startswith("//"))


def _carriers_panel() -> str:
    code = _code(CLIENT_DETAIL)
    start = code.index("cd-panel-carriers")
    return code[start:code.index("tab === 'kyc'")]


# ── 10. V1-style labels render ───────────────────────────────────────────

@pytest.mark.parametrize("label", [
    "DHL Express accounts", "Account number", "Billing role",
    "Default shipping account",
])
def test_required_label_present(label):
    assert label in _carriers_panel(), f"label {label!r} must render"


def test_old_labels_replaced():
    panel = _carriers_panel()
    assert "Payment type" not in panel
    assert "Set as default carrier account" not in panel


# ── 1 + 2. stored enum values are labelled, never rewritten ──────────────

@pytest.mark.parametrize("stored,shown", [
    ("shipper", "Sender"),
    ("receiver", "Receiver"),
    ("third_party", "Third party"),
])
def test_stored_value_labelled(stored, shown):
    """The option keeps the stored value and shows the business label."""
    panel = _carriers_panel()
    assert re.search(rf'<option value="{stored}">{re.escape(shown)}</option>', panel), \
        f"{stored!r} must render as {shown!r} while storing {stored!r}"


def test_stored_enum_values_unchanged_in_backend():
    """Criterion 2 — labels are presentation; the backend enum is untouched."""
    src = _read(DB)
    assert 'VALID_PAYMENT_TYPES = frozenset({"shipper", "receiver", "third_party"})' in src


def test_label_map_does_not_rewrite_values():
    code = _code(CLIENT_DETAIL)
    m = re.search(r"_CD_BILLING_ROLE_LABELS = \{(.*?)\}", code, re.S)
    assert m, "label map must exist"
    for stored in ("shipper", "receiver", "third_party"):
        assert stored in m.group(1)
    # The map is only ever read for display.
    assert "payment_type: _cdBillingRoleLabel" not in code, \
        "the label must never be written back into payment_type"


# ── 3 + 4. payload keys unchanged ────────────────────────────────────────

def test_is_default_payload_key_unchanged():
    panel = _carriers_panel()
    assert "is_default: e.target.checked" in panel
    assert "isDefault" not in panel, "must send the existing is_default key"


def test_active_key_not_invented():
    """`active` is the real column name; `is_active` does not exist."""
    assert "is_active" not in _code(CLIENT_DETAIL)
    assert 'active         = bool(int(row["active"]))' in _read(DB)


def test_payment_type_payload_key_unchanged():
    panel = _carriers_panel()
    assert "payment_type: e.target.value" in panel
    assert "billing_role:" not in panel, "must send the existing payment_type key"


# ── 5. billing role and default are independent ──────────────────────────

def test_role_and_default_are_independent():
    """Neither control may mutate the other."""
    panel = _carriers_panel()
    role = re.search(r"payment_type: e\.target\.value[^}]*\}\)\)", panel)
    assert role and "is_default" not in role.group(0), \
        "changing billing role must not change the default flag"
    default = re.search(r"is_default: e\.target\.checked[^}]*\}\)\)", panel)
    assert default and "payment_type" not in default.group(0), \
        "toggling default must not change the billing role"


def test_default_is_not_inferred_from_role():
    panel = _carriers_panel()
    for banned in ("payment_type === 'shipper'", 'payment_type === "shipper"',
                   "is_default = payment_type", "payment_type ? true"):
        assert banned not in panel, f"default must not be inferred from role ({banned!r})"


# ── 6 + 7. one save path, no duplicate endpoint ──────────────────────────

def test_save_uses_existing_carrier_account_endpoints():
    code = _code(CLIENT_DETAIL)
    assert "PzApi.createCarrierAccount" in code
    assert "PzApi.updateCarrierAccount" in code


def test_no_duplicate_carrier_account_endpoint():
    api = _read(API)
    assert api.count("createCarrierAccount:") == 1
    assert api.count("updateCarrierAccount:") == 1
    assert api.count("deleteCarrierAccount:") == 1
    assert api.count("listCarrierAccounts:") == 1


def test_single_save_handler():
    code = _code(CLIENT_DETAIL)
    assert code.count("const handleCarrierSave") == 1, "one save path only"


# ── 8. existing edit / delete behaviour intact ───────────────────────────

def test_edit_and_delete_controls_intact():
    panel = _carriers_panel()
    assert "-edit'" in panel and "-delete'" in panel
    assert "handleCarrierDelete" in panel
    assert "setCarrierForm({ ...acct })" in panel, "Edit must load the record unchanged"


def test_active_is_read_only_in_the_form():
    """`active` is not writable via update_account, so no editable control.

    update_account()'s UPDATE clause covers carrier, account_number,
    account_name, payment_type, service_level and is_default only. The active
    column belongs to the soft-delete / restore endpoints. An editable Active
    checkbox would silently discard the operator's click.
    """
    db = _read(DB)
    m = re.search(r"UPDATE client_carrier_accounts\s*\n\s*SET (.*?)WHERE id=\?", db, re.S)
    assert m, "update statement must exist"
    assert "active=" not in m.group(1), \
        "if update_account starts writing `active`, make the Active control editable"
    panel = _carriers_panel()
    assert "active: e.target.checked" not in panel, \
        "Active must not be an editable form control while it is not writable"


def test_active_state_is_still_visible():
    """Read-only, but the operator must still see it."""
    panel = _carriers_panel()
    assert "acct.active === false" in panel
    assert "inactive" in panel


# ── 9. masking elsewhere is unaffected ───────────────────────────────────

def test_shipment_masking_untouched():
    hook = SERVICE_DIR / "app" / "static" / "v2" / "use-dhl-account-resolution.jsx"
    code = "\n".join(ln for ln in _read(hook).splitlines()
                     if not ln.strip().startswith("//"))
    assert "masked" in code
    assert "account_number" not in code, \
        "the shipment UI must keep showing masked accounts only"


def test_carrier_tab_may_show_full_number():
    """The authorized Carrier tab already edits the full number — unchanged."""
    panel = _carriers_panel()
    assert "carrierForm.account_number" in panel


def test_no_credentials_or_technical_metadata_in_panel():
    panel = _carriers_panel()
    for banned in ("api_key", "api_secret", "credential", "token",
                   "resolver", "awb_blocked", "contractor_id:"):
        assert banned not in panel, f"operational screen must not expose {banned!r}"
