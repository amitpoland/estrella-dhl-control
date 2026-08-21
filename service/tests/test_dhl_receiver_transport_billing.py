"""test_dhl_receiver_transport_billing.py — who DHL bills, and who decides it.

DG GmbH carried a receiver-paid DHL account in Customer Master for weeks, the
AWB panel displayed it, and every booking still billed Estrella. The panel and
the booking disagreed and the booking was the one spending money.

These pin the repair at its authority boundaries rather than at its source text:

    Customer Master  declares WHO pays   (payment_type on the receiver account)
    dhl_account_resolver  selects WHICH accounts that means
    the route         carries the verdict, and refuses to be told a different one
    the adapter       serializes it, and decides nothing

Everything below runs the REAL resolver against a REAL account store and the
REAL route function. No stub stands in for a producer whose shape matters —
that substitution is exactly how a green suite ends up describing a system that
does not exist (Lesson A).
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import sqlite3
import sys
import unittest.mock as mock
import types

import pytest
from fastapi import HTTPException

SERVICE_DIR = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVICE_DIR))

from app.api.routes_carrier_actions import _resolve_shipment_accounts  # noqa: E402
from app.services.carrier.adapters.live import _build_accounts  # noqa: E402
from app.services.carrier.models.shipment import ShipmentRequest  # noqa: E402
from app.services.client_carrier_accounts_db import create_account, init_db  # noqa: E402
from app.services.dhl_account_resolver import (  # noqa: E402
    PayerDeclarationUnavailable,
    resolve_declared_transport_payer,
)
from app.services import proforma_invoice_link_db as pildb  # noqa: E402

# Stand-ins for the two real legs on the live batch. Numbers are fixtures, not
# the production accounts: the point of the repair is that no customer account
# is ever named in code.
BATCH = "SHIPMENT_TESTBATCH_2026-08_aaaa1111"
RECEIVER_PAYS = "CID-RECEIVER-PAYS"     # DG GmbH shape
SENDER_PAYS = "CID-SENDER-PAYS"         # SAGAR SHAH shape
ENV_SENDER = "427000000"                # DHL_EXPRESS_ACCOUNT_NUMBER stand-in
RECEIVER_ACCT = "144000000"


@pytest.fixture()
def storage(tmp_path):
    init_db(tmp_path / "customer_master.sqlite")
    pildb.init_db(tmp_path / "proforma_links.db")
    return tmp_path


def _settings(storage_root, env_account=ENV_SENDER):
    return types.SimpleNamespace(storage_root=storage_root,
                                 dhl_express_account_number=env_account)


def _body(**kw):
    base = dict(shipper_account=None, sender_contractor_id=None,
                receiver_contractor_id=None, billing_party=None,
                third_party_contractor_id=None, billing_account_id=None,
                client_ref=None)
    base.update(kw)
    return types.SimpleNamespace(**base)


def _account(storage, contractor, number, *, payment_type="receiver",
             carrier="dhl", default=True, active=True):
    acct_id = create_account(storage / "customer_master.sqlite", contractor, {
        "carrier": carrier, "account_number": number,
        "account_name": "FIXTURE", "payment_type": payment_type,
        "is_default": default,
    })
    if not active:
        with sqlite3.connect(str(storage / "customer_master.sqlite")) as c:
            c.execute("UPDATE client_carrier_accounts SET active=0 WHERE id=?",
                      (acct_id,))
            c.commit()
    return acct_id


def _draft(storage, client_name, contractor_id):
    """A posted per-client draft — the identity the booking is scoped to."""
    db = storage / "proforma_links.db"
    with sqlite3.connect(str(db)) as conn:
        cur = conn.execute(
            """INSERT INTO proforma_drafts
                 (batch_id, client_name, client_contractor_id, status, currency,
                  draft_state, wfirma_proforma_id, wfirma_proforma_fullnumber,
                  source_lines_json, editable_lines_json, service_charges_json,
                  clone_generation, draft_version, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'),datetime('now'))""",
            # status and draft_state must agree: the legacy status column wins
            # on read, so a mismatched pair silently tests the wrong document.
            (BATCH, client_name, contractor_id, "issued", "USD",
             "posted", "500000000", "PROF TEST/2026", "[]", "[]", "[]", 0, 1),
        )
        conn.commit()
        return cur.lastrowid


def _cm_digest(storage) -> str:
    return hashlib.sha256(
        (storage / "customer_master.sqlite").read_bytes()).hexdigest()


# ═══════════════════════════════════════════════════════════════════════════
# Customer Master declares the payer
# ═══════════════════════════════════════════════════════════════════════════

def test_a_receiver_type_account_declares_receiver_paid(storage):
    _account(storage, RECEIVER_PAYS, RECEIVER_ACCT, payment_type="receiver")
    assert resolve_declared_transport_payer(
        storage / "customer_master.sqlite", RECEIVER_PAYS) == "receiver"


def test_a_shipper_type_account_is_theirs_to_ship_on_not_ours_to_bill(storage):
    """Owning a DHL account is not consent to be charged.

    payment_type='shipper' is the client's own shipping account. Billing it
    because it exists is exactly the inference the resolver has always refused.
    """
    _account(storage, SENDER_PAYS, "999000111", payment_type="shipper")
    assert resolve_declared_transport_payer(
        storage / "customer_master.sqlite", SENDER_PAYS) == "sender"


def test_no_account_at_all_is_sender_paid(storage):
    assert resolve_declared_transport_payer(
        storage / "customer_master.sqlite", SENDER_PAYS) == "sender"


def test_an_inactive_receiver_account_cannot_be_billed(storage):
    """A soft-deleted receiver account is refused, not quietly downgraded.

    Customer Master still holds a receiver-paid row, so the operator's intent is
    on record; only the account is unusable. Reading that as "sender pays" would
    charge the shipper for a cost that was deliberately assigned elsewhere. The
    row is what makes it ambiguous, and clearing or re-typing it in Client
    Master is the one-click fix — cheaper than a wrong carrier invoice.
    """
    _account(storage, RECEIVER_PAYS, RECEIVER_ACCT,
             payment_type="receiver", active=False)
    with pytest.raises(PayerDeclarationUnavailable):
        resolve_declared_transport_payer(
            storage / "customer_master.sqlite", RECEIVER_PAYS)


def test_a_non_dhl_account_cannot_be_billed_for_dhl(storage):
    _account(storage, RECEIVER_PAYS, RECEIVER_ACCT,
             payment_type="receiver", carrier="fedex")
    assert resolve_declared_transport_payer(
        storage / "customer_master.sqlite", RECEIVER_PAYS) == "sender"


def test_ambiguous_accounts_fail_closed_rather_than_picking_one(storage):
    """Two active receiver accounts, no default: refuse, do not guess a payer.

    An earlier version of this test asserted sender-paid here and called that
    "failing closed". It is not: the client demonstrably HAS a receiver-paid
    arrangement, so quietly billing the shipper instead is a wrong answer
    delivered silently, not an abstention. Raising makes the operator resolve
    the ambiguity in Client Master.
    """
    _account(storage, RECEIVER_PAYS, "144000001",
             payment_type="receiver", default=False)
    _account(storage, RECEIVER_PAYS, "144000002",
             payment_type="receiver", default=False)
    with pytest.raises(PayerDeclarationUnavailable):
        resolve_declared_transport_payer(
            storage / "customer_master.sqlite", RECEIVER_PAYS)


def test_an_unreadable_account_store_refuses_rather_than_assuming_sender(storage):
    """"Cannot tell" must never collapse into "the shipper pays".

    A lock or permissions blip on the account store is not evidence that the
    client has no bill-to arrangement; treating it as such bills a party who
    never agreed, with nothing raised.
    """
    with mock.patch("app.services.dhl_account_resolver.list_accounts",
                    side_effect=sqlite3.OperationalError("database is locked")):
        with pytest.raises(PayerDeclarationUnavailable):
            resolve_declared_transport_payer(
                storage / "customer_master.sqlite", RECEIVER_PAYS)


def test_reading_the_declaration_does_not_mutate_customer_master(storage):
    _account(storage, RECEIVER_PAYS, RECEIVER_ACCT, payment_type="receiver")
    before = _cm_digest(storage)
    for _ in range(3):
        resolve_declared_transport_payer(
            storage / "customer_master.sqlite", RECEIVER_PAYS)
    assert _cm_digest(storage) == before, "the resolver is a reader, never a writer"


# ═══════════════════════════════════════════════════════════════════════════
# The route carries the verdict — the two real legs
# ═══════════════════════════════════════════════════════════════════════════

def test_the_receiver_paid_leg_bills_the_customer_master_account(storage):
    """DG GmbH's shape: ships on the configured sender, bills the receiver."""
    _draft(storage, "DG GmbH", RECEIVER_PAYS)
    _account(storage, RECEIVER_PAYS, RECEIVER_ACCT, payment_type="receiver")

    acct, payer, billing, res = _resolve_shipment_accounts(
        _body(client_ref="DG GmbH"), _settings(storage), BATCH)

    assert payer == "receiver"
    assert acct == ENV_SENDER, "the shipment still moves on the sender's account"
    assert billing == RECEIVER_ACCT, "and the charge lands on Customer Master's"
    assert res is not None and res["ok"]


def test_the_sender_paid_leg_is_unchanged(storage):
    """SAGAR SHAH's shape: no receiver-paid arrangement, nothing to redirect."""
    _draft(storage, "SAGAR SHAH", SENDER_PAYS)

    acct, payer, billing, res = _resolve_shipment_accounts(
        _body(client_ref="SAGAR SHAH"), _settings(storage), BATCH)

    assert payer == "sender"
    assert acct == ENV_SENDER
    assert billing is None, "sender-paid carries no separate payer account"


def test_the_two_legs_resolve_independently_on_one_batch(storage):
    """One batch, two clients, two different payers — no leakage between them."""
    _draft(storage, "DG GmbH", RECEIVER_PAYS)
    _draft(storage, "SAGAR SHAH", SENDER_PAYS)
    _account(storage, RECEIVER_PAYS, RECEIVER_ACCT, payment_type="receiver")

    _, dg_payer, dg_billing, _ = _resolve_shipment_accounts(
        _body(client_ref="DG GmbH"), _settings(storage), BATCH)
    _, sagar_payer, sagar_billing, _ = _resolve_shipment_accounts(
        _body(client_ref="SAGAR SHAH"), _settings(storage), BATCH)

    assert (dg_payer, sagar_payer) == ("receiver", "sender")
    assert dg_billing == RECEIVER_ACCT
    assert sagar_billing is None, "the second leg must not inherit the first's payer"


def test_a_declared_receiver_with_no_usable_account_refuses(storage):
    """Declared receiver-paid, account deactivated mid-flight: refuse, never invert.

    This is the worst outcome the whole repair exists to prevent. The operator
    assigned this cost to the receiver; if the account becomes unusable between
    their preflight check and the booking, billing the shipper instead — with no
    error and no log line — charges Estrella for something it was never meant to
    carry. An earlier version of this test asserted exactly that inversion and
    called it correct.
    """
    acct_id = _account(storage, RECEIVER_PAYS, RECEIVER_ACCT,
                       payment_type="receiver")
    _draft(storage, "DG GmbH", RECEIVER_PAYS)
    with sqlite3.connect(str(storage / "customer_master.sqlite")) as c:
        c.execute("UPDATE client_carrier_accounts SET active=0 WHERE id=?",
                  (acct_id,))
        c.commit()

    with pytest.raises(HTTPException) as e:
        _resolve_shipment_accounts(
            _body(client_ref="DG GmbH"), _settings(storage), BATCH)
    assert e.value.status_code == 422
    assert e.value.detail["code"] == "DHL_PAYER_DECLARATION_UNAVAILABLE"
    assert ENV_SENDER not in repr(e.value.detail)


def test_a_client_with_no_arrangement_at_all_is_simply_sender_paid(storage):
    """Absence of an arrangement IS an answer, and differs from "cannot tell".

    The refusal above must not spread to every client who has no DHL account —
    that would block SAGAR SHAH, whose DAP terms mean seller-paid is correct.
    """
    _draft(storage, "SAGAR SHAH", SENDER_PAYS)
    acct, payer, billing, _ = _resolve_shipment_accounts(
        _body(client_ref="SAGAR SHAH"), _settings(storage), BATCH)
    assert (payer, billing, acct) == ("sender", None, ENV_SENDER)


# ═══════════════════════════════════════════════════════════════════════════
# A request may narrow the payer, never widen it
# ═══════════════════════════════════════════════════════════════════════════

def test_a_request_cannot_nominate_a_payer_the_draft_does_not_confirm(storage):
    """No draft behind the client_ref → a body receiver cannot escalate.

    Without this, a caller could name any contractor holding a receiver-type
    account and have that account billed for their shipment.
    """
    _account(storage, RECEIVER_PAYS, RECEIVER_ACCT, payment_type="receiver")
    acct, payer, billing, _ = _resolve_shipment_accounts(
        _body(receiver_contractor_id=RECEIVER_PAYS), _settings(storage), BATCH)
    assert payer == "sender"
    assert billing is None
    assert acct == ENV_SENDER


def test_a_request_naming_a_different_receiver_than_the_draft_is_refused(storage):
    _draft(storage, "DG GmbH", RECEIVER_PAYS)
    _account(storage, RECEIVER_PAYS, RECEIVER_ACCT, payment_type="receiver")
    with pytest.raises(HTTPException) as e:
        _resolve_shipment_accounts(
            _body(client_ref="DG GmbH", receiver_contractor_id="CID-SOMEONE-ELSE"),
            _settings(storage), BATCH)
    assert e.value.detail["code"] == "DHL_RECEIVER_IDENTITY_MISMATCH"


def test_a_request_cannot_downgrade_a_declared_receiver_silently(storage):
    """Asking for sender-paid where Customer Master declared receiver-paid.

    Narrowing is allowed — it can only reduce who is exposed to the charge —
    but it must be the caller's explicit act, and the resolver must not treat
    it as the declaration changing.
    """
    _draft(storage, "DG GmbH", RECEIVER_PAYS)
    _account(storage, RECEIVER_PAYS, RECEIVER_ACCT, payment_type="receiver")
    acct, payer, billing, _ = _resolve_shipment_accounts(
        _body(client_ref="DG GmbH", billing_party="sender"),
        _settings(storage), BATCH)
    assert payer == "sender" and billing is None
    # The declaration itself is untouched by one narrowed booking.
    assert resolve_declared_transport_payer(
        storage / "customer_master.sqlite", RECEIVER_PAYS) == "receiver"


def _draft_row(storage, client_name):
    """Every stored column of the draft, as a comparable tuple.

    Deliberately NOT a hash of the .db file: SQLite rewrites header pages on an
    ordinary read, so a byte digest reports a mutation that never touched a
    single value. Content is the property under test.
    """
    with sqlite3.connect(str(storage / "proforma_links.db")) as c:
        c.row_factory = sqlite3.Row
        row = c.execute(
            "SELECT * FROM proforma_drafts WHERE batch_id=? AND client_name=?",
            (BATCH, client_name)).fetchone()
    return {k: row[k] for k in row.keys()}


def test_booking_does_not_touch_the_proforma(storage):
    """Resolving a payer must not change one value on the fiscal document."""
    _draft(storage, "DG GmbH", RECEIVER_PAYS)
    _account(storage, RECEIVER_PAYS, RECEIVER_ACCT, payment_type="receiver")

    before = _draft_row(storage, "DG GmbH")
    _resolve_shipment_accounts(_body(client_ref="DG GmbH"),
                               _settings(storage), BATCH)
    after = _draft_row(storage, "DG GmbH")

    assert after == before, "payer resolution must not write to the proforma"
    # Named explicitly, so a future change that preserved the row by accident
    # while losing the posting identity still fails here.
    assert after["draft_state"] == "posted"
    assert after["wfirma_proforma_fullnumber"] == "PROF TEST/2026"
    assert after["wfirma_proforma_id"] == "500000000"


# ═══════════════════════════════════════════════════════════════════════════
# The verdict reaches DHL intact
# ═══════════════════════════════════════════════════════════════════════════

def test_the_resolved_verdict_serializes_end_to_end(storage):
    """Customer Master → resolver → route → ShipmentRequest → DHL accounts array."""
    _draft(storage, "DG GmbH", RECEIVER_PAYS)
    _account(storage, RECEIVER_PAYS, RECEIVER_ACCT, payment_type="receiver")

    acct, payer, billing, _ = _resolve_shipment_accounts(
        _body(client_ref="DG GmbH"), _settings(storage), BATCH)

    request = ShipmentRequest(
        batch_id=BATCH, shipper_account=acct, transport_payer=payer,
        billing_account=billing, recipient_address={}, declared_value=524.0,
        currency="USD", weight_kg=0.3, dimensions={},
    )
    assert _build_accounts(request) == [
        {"typeCode": "shipper", "number": ENV_SENDER},
        {"typeCode": "payer", "number": RECEIVER_ACCT},
    ]


def test_no_customer_account_number_is_written_into_runtime_code():
    """The two real production accounts must never appear in shipped code."""
    runtime = SERVICE_DIR / "app"
    for path in list(runtime.rglob("*.py")) + list(runtime.rglob("*.jsx")):
        text = path.read_text(encoding="utf-8", errors="ignore")
        for account in ("144649750", "427294774"):
            assert account not in text, \
                f"{path.name} hardcodes a DHL account number ({account})"
