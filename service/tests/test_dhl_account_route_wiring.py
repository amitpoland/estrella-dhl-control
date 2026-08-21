"""test_dhl_account_route_wiring.py — shipment route ↔ canonical resolver.

Operator ruling 2026-07-20:
  * One canonical chain: Client Master account → resolve_dhl_billing_account()
    → shipment billing decision → existing adapter → existing shipment route.
  * Priority: selected CM account → sender default CM account → env fallback → block.
  * Sender-paid only. Receiver/third-party billing is resolved and surfaced but
    AWB creation is BLOCKED until the MyDHL accounts[].typeCode is verified.
  * Silent fallback that charges the sender instead is forbidden.
  * Full account numbers must never reach operational payloads or logs.
"""
from __future__ import annotations

import pathlib
import sys
import types

import pytest
from fastapi import HTTPException

SERVICE_DIR = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVICE_DIR))

from app.api.routes_carrier_actions import _resolve_shipment_accounts  # noqa: E402
from app.services.client_carrier_accounts_db import create_account, init_db  # noqa: E402

SENDER = "STERLING001"
RECEIVER = "ACME002"


@pytest.fixture()
def storage(tmp_path):
    init_db(tmp_path / "customer_master.sqlite")
    return tmp_path


def _settings(storage_root, env_account=None):
    return types.SimpleNamespace(
        storage_root=storage_root,
        dhl_express_account_number=env_account,
    )


def _body(**kw):
    base = dict(
        shipper_account=None, sender_contractor_id=None,
        receiver_contractor_id=None, billing_party=None,
        third_party_contractor_id=None, billing_account_id=None,
        client_ref=None,
    )
    base.update(kw)
    return types.SimpleNamespace(**base)


# The resolver takes the batch now, so it can identify the receiver from the
# proforma draft instead of trusting the request body. These fixtures have no
# proforma store, so that lookup finds nothing — which is what these tests
# want: they pin the ACCOUNT rules. The draft-confirmed payer rules live in
# test_dhl_receiver_transport_billing.py.
BATCH = "SHIPMENT_TEST_0001"


def _resolve(body, settings):
    """Account + resolution — the two values these tests were written against."""
    acct, _payer, _billing, res = _resolve_shipment_accounts(body, settings, BATCH)
    return acct, res


def _add(storage, contractor, number, **kw):
    return create_account(storage / "customer_master.sqlite", contractor, {
        "carrier": kw.get("carrier", "dhl"),
        "account_number": number,
        "account_name": kw.get("name"),
        "payment_type": kw.get("payment_type"),
        "is_default": kw.get("default", False),
    })


# ── Priority chain ───────────────────────────────────────────────────────

def test_client_master_account_wins_over_env_fallback(storage):
    _add(storage, SENDER, "958214771")
    acct, res = _resolve(
        _body(sender_contractor_id=SENDER),
        _settings(storage, env_account="ENV0000000"))
    assert acct == "958214771"
    assert res is not None and res["ok"]


def test_sender_default_account_chosen_when_several(storage):
    _add(storage, SENDER, "111111111")
    _add(storage, SENDER, "222222222", default=True)
    acct, _ = _resolve(
        _body(sender_contractor_id=SENDER), _settings(storage))
    assert acct == "222222222"


def test_selected_sender_without_account_blocks_and_ignores_env(storage):
    """Operator ruling 2026-07-20 — the chain is:

        selected CM account → sender default CM account → block

    DHL_EXPRESS_ACCOUNT_NUMBER is NOT a step. Once a sender is selected,
    silently billing the environment account is forbidden.
    """
    with pytest.raises(HTTPException) as e:
        _resolve(
            _body(sender_contractor_id=SENDER),
            _settings(storage, env_account="ENV0000000"))
    assert e.value.status_code == 422
    assert e.value.detail["code"] == "DHL_ACCOUNT_UNRESOLVED"
    assert "ENV0000000" not in repr(e.value.detail)


def test_block_when_no_account_and_no_env(storage):
    with pytest.raises(HTTPException) as e:
        _resolve(_body(sender_contractor_id=SENDER),
                                   _settings(storage))
    assert e.value.status_code == 422
    assert e.value.detail["code"] == "DHL_ACCOUNT_UNRESOLVED"


def test_legacy_caller_without_client_context_still_works(storage):
    """Existing callers that pass no contractor ids must not regress."""
    acct, res = _resolve(
        _body(shipper_account="EXPLICIT01"), _settings(storage))
    assert acct == "EXPLICIT01" and res is None


def test_env_fallback_only_for_legacy_no_sender_context(storage):
    """The environment account survives ONLY where there is no sender context."""
    acct, res = _resolve(
        _body(), _settings(storage, env_account="ENV0000000"))
    assert acct == "ENV0000000"
    assert res is None, "env fallback is never a canonical resolution"


# ── Operator choice ──────────────────────────────────────────────────────

def test_ambiguous_accounts_require_choice(storage):
    _add(storage, SENDER, "111111111")
    _add(storage, SENDER, "222222222")
    with pytest.raises(HTTPException) as e:
        _resolve(_body(sender_contractor_id=SENDER),
                                   _settings(storage))
    d = e.value.detail
    assert d["code"] == "DHL_ACCOUNT_CHOICE_REQUIRED"
    assert len(d["choices"]) == 2


def test_choice_payload_is_masked_only(storage):
    _add(storage, SENDER, "111111111")
    _add(storage, SENDER, "222222222")
    with pytest.raises(HTTPException) as e:
        _resolve(_body(sender_contractor_id=SENDER),
                                   _settings(storage))
    blob = repr(e.value.detail)
    assert "111111111" not in blob and "222222222" not in blob, \
        "full account numbers must never reach an operational payload"
    assert "••••" in blob


def test_explicit_operator_pick_is_honoured(storage):
    a = _add(storage, SENDER, "111111111")
    _add(storage, SENDER, "222222222")
    acct, _ = _resolve(
        _body(sender_contractor_id=SENDER, billing_account_id=a),
        _settings(storage))
    assert acct == "111111111"


# ── Receiver-paid: who may declare it ────────────────────────────────────
#
# SUPERSEDED 2026-08-21. These asserted DHL_BILLING_PARTY_NOT_ENABLED — the hold
# that stood while the MyDHL account contract was unverified. Receiver-paid now
# executes, and the boundary that replaces the blanket block is tighter: a
# REQUEST may never declare a payer at all, whatever accounts exist. Where the
# old pin refused a body asking for receiver-paid, so does the new one; it just
# refuses it for the durable reason instead of the temporary one.

def test_a_request_may_not_declare_receiver_billing(storage):
    """Both parties own DHL accounts — the refusal is about authority, not data."""
    _add(storage, SENDER, "958214771")
    _add(storage, RECEIVER, "111222333", payment_type="receiver", default=True)
    with pytest.raises(HTTPException) as e:
        _resolve(
            _body(sender_contractor_id=SENDER, receiver_contractor_id=RECEIVER,
                  billing_party="receiver"),
            _settings(storage))
    d = e.value.detail
    assert d["code"] == "DHL_BILLING_PARTY_NOT_DECLARED"
    assert d["declared"] == "sender", \
        "with no draft to corroborate the receiver, sender-paid stands"


def test_receiver_billing_never_silently_charges_sender(storage):
    """The forbidden failure mode: quietly billing the sender instead.

    Unchanged in intent — only the refusal code moved. A request that cannot
    have its payer honoured must be refused, never downgraded into a charge on
    an account the operator did not choose, and no account number may leak.
    """
    _add(storage, SENDER, "958214771")
    _add(storage, RECEIVER, "111222333", payment_type="receiver", default=True)
    with pytest.raises(HTTPException) as e:
        _resolve(
            _body(sender_contractor_id=SENDER, receiver_contractor_id=RECEIVER,
                  billing_party="receiver"),
            _settings(storage, env_account="ENV0000000"))
    assert e.value.status_code == 422
    assert "958214771" not in repr(e.value.detail)
    assert "111222333" not in repr(e.value.detail)
    assert "ENV0000000" not in repr(e.value.detail)


def test_no_account_number_reaches_a_refusal_payload(storage):
    """Refusals stay masked — this replaces the old surfaces-masked pin.

    That test asserted a masked account appeared in the receiver-billing block
    body. There is no such block any more, so the guarantee is re-pinned where
    it still applies: the ambiguity refusal, which does carry account choices.
    """
    _add(storage, SENDER, "111111111")
    _add(storage, SENDER, "222222222")
    with pytest.raises(HTTPException) as e:
        _resolve(_body(sender_contractor_id=SENDER), _settings(storage))
    blob = repr(e.value.detail)
    assert "111111111" not in blob and "222222222" not in blob
    assert "••••" in blob


def test_receiver_billing_without_receiver_account_blocks(storage):
    """A payer with no usable account is refused, not silently reassigned."""
    _add(storage, SENDER, "958214771")
    with pytest.raises(HTTPException) as e:
        _resolve(
            _body(sender_contractor_id=SENDER, receiver_contractor_id=RECEIVER,
                  billing_party="receiver"),
            _settings(storage))
    assert e.value.detail["code"] == "DHL_BILLING_PARTY_NOT_DECLARED"


# ── No duplicate authority ───────────────────────────────────────────────

def test_route_does_not_reimplement_resolution():
    """The route must delegate selection; it may only pass results through.

    The real duplicate-authority risk is the route querying the account store
    itself or re-deriving a default. Echoing the resolver's ``is_default`` flag
    into the operator's choice list is presentation, not selection.
    """
    src = (SERVICE_DIR / "app" / "api" / "routes_carrier_actions.py").read_text(encoding="utf-8")
    assert "resolve_dhl_billing_account" in src, "route must call the canonical resolver"
    assert "list_accounts" not in src, \
        "route must not query the carrier-account store directly"
    for dup in ("is_default=True", "is_default == True", "if c.is_default",
                "if a.is_default", "sorted(", "ORDER BY"):
        assert dup not in src, \
            f"account-selection logic ({dup!r}) must not be duplicated in the route"


def test_adapter_does_not_choose_accounts():
    """The DHL adapter only transmits the resolved account.

    Comment lines are stripped first: the adapter may *document* which
    authority resolved the account, it just must not call it.
    """
    import ast
    raw = (SERVICE_DIR / "app" / "services" / "carrier" / "adapters" / "live.py").read_text(encoding="utf-8")
    tree = ast.parse(raw)
    # Checked on the AST, not the text: the adapter names the resolver in a
    # docstring to record where the verdict it serializes was decided. Saying
    # who decided is the opposite of deciding, and a substring search cannot
    # tell the two apart — it would force the adapter to stay silent about its
    # own authority in order to pass.
    called = {
        node.func.id if isinstance(node.func, ast.Name) else
        getattr(node.func, "attr", "")
        for node in ast.walk(tree) if isinstance(node, ast.Call)
    }
    for banned in ("resolve_dhl_billing_account", "resolve_declared_transport_payer",
                   "list_accounts"):
        assert banned not in called, f"the adapter must not call {banned!r}"
    consts = {n.value for n in ast.walk(tree)
              if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    assert not any("client_carrier_accounts" in c for c in consts), \
        "the adapter must never read the Client Master account store"
