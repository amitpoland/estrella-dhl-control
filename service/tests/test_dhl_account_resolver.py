"""test_dhl_account_resolver.py — pins the DHL account-resolution authority.

Operator directive 2026-07-20:
  * Client Master owns the account, the shipment resolves it, the adapter only sends it.
  * Shipping account and billing account are SEPARATE concepts.
  * Defaults: one active → auto-select; several → operator chooses; none → block.
  * No hard-coded account numbers anywhere.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

SERVICE_DIR = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVICE_DIR))

from app.services.client_carrier_accounts_db import create_account, init_db  # noqa: E402
from app.services.dhl_account_resolver import (  # noqa: E402
    BILLING_RECEIVER,
    BILLING_SENDER,
    BILLING_THIRD_PARTY,
    DEFAULT_BILLING_PARTY,
    REASON_AMBIGUOUS,
    REASON_BAD_BILLING_PARTY,
    REASON_NO_RECEIVER_ACCOUNT,
    REASON_NO_SENDER,
    REASON_NO_SENDER_ACCOUNT,
    REASON_NO_THIRD_PARTY_ACCOUNT,
    list_dhl_accounts,
    resolve_dhl_billing_account,
)

SENDER = "STERLING001"
RECEIVER = "ACME002"
THIRD = "THIRD003"


@pytest.fixture()
def db(tmp_path):
    p = tmp_path / "client_carrier_accounts.sqlite"
    init_db(p)
    return p


def _add(db, contractor, number, *, carrier="dhl", default=False,
         payment_type=None, name=None):
    return create_account(db, contractor, {
        "carrier": carrier,
        "account_number": number,
        "account_name": name,
        "payment_type": payment_type,
        "is_default": default,
    })


# ── Default billing party ────────────────────────────────────────────────

def test_default_billing_party_is_sender():
    assert DEFAULT_BILLING_PARTY == BILLING_SENDER


def test_receiver_owning_an_account_does_not_make_them_the_payer(db):
    """Being able to bill the receiver must never auto-switch billing."""
    _add(db, SENDER, "958214771")
    _add(db, RECEIVER, "111222333")
    r = resolve_dhl_billing_account(db, SENDER, RECEIVER)  # no billing_party
    assert r.ok
    assert r.billing_party == BILLING_SENDER
    assert r.billing_account.account_number == "958214771"


# ── Auto-select rules ────────────────────────────────────────────────────

def test_single_active_sender_account_auto_selected(db):
    _add(db, SENDER, "958214771")
    r = resolve_dhl_billing_account(db, SENDER, RECEIVER, BILLING_SENDER)
    assert r.ok
    assert r.shipping_account.account_number == "958214771"
    assert r.billing_account.account_number == "958214771"


def test_several_accounts_with_one_default_auto_selects_default(db):
    _add(db, SENDER, "111111111")
    _add(db, SENDER, "222222222", default=True)
    r = resolve_dhl_billing_account(db, SENDER, RECEIVER, BILLING_SENDER)
    assert r.ok
    assert r.billing_account.account_number == "222222222"
    assert r.billing_account.is_default


def test_several_accounts_without_default_requires_operator_choice(db):
    _add(db, SENDER, "111111111")
    _add(db, SENDER, "222222222")
    r = resolve_dhl_billing_account(db, SENDER, RECEIVER, BILLING_SENDER)
    assert not r.ok
    assert r.reason == REASON_AMBIGUOUS
    assert {c.account_number for c in r.choices} == {"111111111", "222222222"}


def test_operator_explicit_choice_wins(db):
    a = _add(db, SENDER, "111111111")
    _add(db, SENDER, "222222222")
    r = resolve_dhl_billing_account(db, SENDER, RECEIVER, BILLING_SENDER,
                                    selected_billing_account_id=a)
    assert r.ok
    assert r.billing_account.account_number == "111111111"


# ── Blocking rules ───────────────────────────────────────────────────────

def test_no_sender_blocks(db):
    r = resolve_dhl_billing_account(db, None, RECEIVER)
    assert not r.ok and r.reason == REASON_NO_SENDER


def test_sender_without_account_blocks(db):
    r = resolve_dhl_billing_account(db, SENDER, RECEIVER, BILLING_SENDER)
    assert not r.ok
    assert r.reason == REASON_NO_SENDER_ACCOUNT
    assert "sender" in r.message.lower()


def test_receiver_billing_without_receiver_account_blocks(db):
    _add(db, SENDER, "958214771")
    r = resolve_dhl_billing_account(db, SENDER, RECEIVER, BILLING_RECEIVER)
    assert not r.ok
    assert r.reason == REASON_NO_RECEIVER_ACCOUNT
    assert "receiver" in r.message.lower()


def test_third_party_billing_without_account_blocks(db):
    _add(db, SENDER, "958214771")
    r = resolve_dhl_billing_account(db, SENDER, RECEIVER, BILLING_THIRD_PARTY,
                                    third_party_contractor_id=THIRD)
    assert not r.ok and r.reason == REASON_NO_THIRD_PARTY_ACCOUNT


def test_invalid_billing_party_blocks(db):
    _add(db, SENDER, "958214771")
    r = resolve_dhl_billing_account(db, SENDER, RECEIVER, "whoever")
    assert not r.ok and r.reason == REASON_BAD_BILLING_PARTY


# ── Shipping vs billing separation ───────────────────────────────────────

def test_receiver_billing_keeps_sender_as_shipping_account(db):
    """Sender ships; receiver pays. The two accounts must differ."""
    _add(db, SENDER, "958214771")
    _add(db, RECEIVER, "111222333")
    r = resolve_dhl_billing_account(db, SENDER, RECEIVER, BILLING_RECEIVER)
    assert r.ok
    assert r.shipping_account.account_number == "958214771"
    assert r.billing_account.account_number == "111222333"
    assert r.shipping_account.account_number != r.billing_account.account_number


def test_third_party_billing_keeps_sender_shipping_account(db):
    _add(db, SENDER, "958214771")
    _add(db, THIRD, "999888777")
    r = resolve_dhl_billing_account(db, SENDER, RECEIVER, BILLING_THIRD_PARTY,
                                    third_party_contractor_id=THIRD)
    assert r.ok
    assert r.shipping_account.account_number == "958214771"
    assert r.billing_account.account_number == "999888777"


# ── Authority + hygiene ──────────────────────────────────────────────────

def test_only_dhl_accounts_are_considered(db):
    _add(db, SENDER, "FEDEX123", carrier="fedex")
    r = resolve_dhl_billing_account(db, SENDER, RECEIVER, BILLING_SENDER)
    assert not r.ok and r.reason == REASON_NO_SENDER_ACCOUNT


def test_list_reads_client_master_store(db):
    _add(db, SENDER, "958214771", default=True, name="Sterling Jewels")
    accts = list_dhl_accounts(db, SENDER)
    assert len(accts) == 1
    assert accts[0].account_name == "Sterling Jewels"


def test_account_number_is_masked_for_operational_display(db):
    _add(db, SENDER, "958214771")
    r = resolve_dhl_billing_account(db, SENDER, RECEIVER, BILLING_SENDER)
    assert r.billing_account.masked == "DHL account •••• 4771"


def test_no_hardcoded_account_numbers_in_resolver():
    """No literal account number may be embedded in the resolution logic."""
    import re
    src = (SERVICE_DIR / "app" / "services" / "dhl_account_resolver.py").read_text(encoding="utf-8")
    code = "\n".join(ln for ln in src.splitlines()
                     if not ln.strip().startswith("#"))
    assert not re.search(r"\b\d{7,}\b", code), \
        "resolver must contain no hard-coded account numbers"


def test_resolver_exposes_no_credentials(db):
    """Operational payload carries business info only — no keys/secrets."""
    _add(db, SENDER, "958214771")
    d = resolve_dhl_billing_account(db, SENDER, RECEIVER, BILLING_SENDER).to_dict()
    blob = repr(d).lower()
    for banned in ("api_key", "api_secret", "password", "credential", "token"):
        assert banned not in blob
