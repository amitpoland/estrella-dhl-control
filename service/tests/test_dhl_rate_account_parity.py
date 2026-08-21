"""test_dhl_rate_account_parity.py — rate quote and AWB share ONE account.

Operator ruling 2026-07-20:

    shipment context
    → resolve_dhl_billing_account()
    → resolved shipping account
    → rate request
    → AWB creation

Before this change the adapter asked DHL for rate entitlements with
``config.account_number or request.shipper_account`` — config first — so a
resolved Client Master account was silently overridden by
DHL_EXPRESS_ACCOUNT_NUMBER for the rates query while AWB creation still used
the resolved one. Rate and shipment could run on different accounts.

Pins the twelve acceptance criteria of the phase.
"""
from __future__ import annotations

import pathlib
import re
import sys
import types

import pytest
from fastapi import HTTPException

SERVICE_DIR = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVICE_DIR))

from app.api.routes_carrier_actions import _resolve_shipment_accounts  # noqa: E402
from app.services.client_carrier_accounts_db import create_account, init_db  # noqa: E402

ADAPTER = SERVICE_DIR / "app" / "services" / "carrier" / "adapters" / "live.py"
ROUTE = SERVICE_DIR / "app" / "api" / "routes_carrier_actions.py"

SENDER = "STERLING001"
RECEIVER = "ACME002"


def _read(p: pathlib.Path) -> str:
    return p.read_text(encoding="utf-8")


def _code(p: pathlib.Path) -> str:
    """Source with ``#`` comment lines removed, so a comment cannot satisfy a
    test. Docstrings are left in place — the assertions below target code
    constructs that never appear in prose."""
    return "\n".join(ln for ln in _read(p).splitlines()
                     if not ln.strip().startswith("#"))


@pytest.fixture()
def storage(tmp_path):
    init_db(tmp_path / "customer_master.sqlite")
    return tmp_path


def _settings(storage_root, env_account=None):
    return types.SimpleNamespace(storage_root=storage_root,
                                 dhl_express_account_number=env_account)


def _body(**kw):
    base = dict(shipper_account=None, sender_contractor_id=None,
                receiver_contractor_id=None, billing_party=None,
                third_party_contractor_id=None, billing_account_id=None,
                client_ref=None)
    base.update(kw)
    return types.SimpleNamespace(**base)


# The resolver now takes the batch so it can identify the receiver from the
# proforma draft instead of trusting the request. These fixtures have no
# proforma store, so the draft lookup finds nothing — which is the point for
# the account-resolution tests below: they exercise the account rules, and the
# draft-confirmed payer rules are covered in test_dhl_receiver_transport_billing.
BATCH = "SHIPMENT_TEST_0001"


def _resolve(body, settings):
    """Account + resolution, the two values these tests assert on.

    ``_resolve_shipment_accounts`` returns the payer verdict as well now; this
    keeps each test focused on the account question it was written to pin.
    """
    acct, _payer, _billing, res = _resolve_shipment_accounts(body, settings, BATCH)
    return acct, res


def _add(storage, contractor, number, **kw):
    return create_account(storage / "customer_master.sqlite", contractor, {
        "carrier": "dhl", "account_number": number,
        "account_name": kw.get("name"), "payment_type": None,
        "is_default": kw.get("default", False),
    })


# ── 1 + 7. rate and AWB use the same resolved account ────────────────────

def test_rate_query_uses_the_resolved_account_first():
    """The rates lookup must prefer request.shipper_account over config."""
    code = _code(ADAPTER)
    assert "account=request.shipper_account or self._config.account_number," in code, \
        "rates must use the resolved account, with config only as legacy fallback"


def test_config_no_longer_overrides_the_resolved_account():
    code = _code(ADAPTER)
    assert "account=self._config.account_number or request.shipper_account" not in code, \
        "config must not take precedence over the resolved account"


def test_rate_and_awb_read_the_same_field():
    """Both paths must source the account from request.shipper_account."""
    code = _code(ADAPTER)
    assert "account=request.shipper_account" in code, "rate path"
    assert '"number": request.shipper_account' in code, "AWB path"


def test_single_rate_call_site():
    """Criterion 11 — exactly one rates query, no duplicate requests."""
    code = _code(ADAPTER)
    assert code.count("lookup_available_products(") == 2, \
        "one definition + one call site only"
    # Exactly one real HTTP request to /rates (docstrings also mention the
    # path, so match the request construction, not the bare word).
    assert code.count('{api_path}/rates') == 1, "exactly one DHL /rates request"


# ── 2 + 3. Client Master beats config; missing blocks, env ignored ───────

def test_selected_sender_account_beats_config_account(storage):
    _add(storage, SENDER, "958214771")
    acct, res = _resolve(
        _body(sender_contractor_id=SENDER),
        _settings(storage, env_account="ENV0000000"))
    assert acct == "958214771", "Client Master account must win over config"
    assert res is not None and res["ok"]


def test_known_sender_without_account_blocks_and_ignores_env(storage):
    with pytest.raises(HTTPException) as e:
        _resolve(
            _body(sender_contractor_id=SENDER),
            _settings(storage, env_account="ENV0000000"))
    assert e.value.detail["code"] == "DHL_ACCOUNT_UNRESOLVED"
    assert "ENV0000000" not in repr(e.value.detail)


# ── 4. unknown sender keeps the legacy env path ──────────────────────────

def test_unknown_sender_preserves_legacy_env_path(storage):
    acct, res = _resolve(
        _body(), _settings(storage, env_account="ENV0000000"))
    assert acct == "ENV0000000"
    assert res is None


def test_legacy_explicit_account_still_wins_for_unknown_sender(storage):
    acct, _ = _resolve(
        _body(shipper_account="EXPLICIT01"),
        _settings(storage, env_account="ENV0000000"))
    assert acct == "EXPLICIT01"


# ── 5. ambiguous accounts block the rate ─────────────────────────────────

def test_multiple_accounts_without_selection_block(storage):
    _add(storage, SENDER, "111111111")
    _add(storage, SENDER, "222222222")
    with pytest.raises(HTTPException) as e:
        _resolve(_body(sender_contractor_id=SENDER),
                                   _settings(storage))
    assert e.value.detail["code"] == "DHL_ACCOUNT_CHOICE_REQUIRED"


def test_selected_account_flows_through(storage):
    a = _add(storage, SENDER, "111111111")
    _add(storage, SENDER, "222222222")
    acct, _ = _resolve(
        _body(sender_contractor_id=SENDER, billing_account_id=a),
        _settings(storage))
    assert acct == "111111111", "the operator's selection must reach the rate request"


# ── 6. a caller can never widen who pays ─────────────────────────────────
#
# SUPERSEDED 2026-08-21. These two previously asserted DHL_BILLING_PARTY_NOT_
# ENABLED — receiver and third-party billing were held closed while the MyDHL
# account contract was unverified. Receiver-paid now executes, so the negative
# they protected is re-pinned at its real boundary, which is STRICTER than the
# blanket block it replaces: the payer comes from Customer Master's declaration
# against a DRAFT-CONFIRMED receiver, so a request can never nominate a payer.
# Deleting these would have removed the only pin standing between a request body
# and someone else's DHL account.

def test_request_cannot_nominate_a_receiver_payer(storage):
    """A body asking for receiver-paid, with no draft to corroborate it, is refused.

    The receiver here genuinely owns a DHL account, so the refusal is about
    AUTHORITY, not about the account being missing.
    """
    _add(storage, SENDER, "958214771")
    _add(storage, RECEIVER, "111222333")
    with pytest.raises(HTTPException) as e:
        _resolve(
            _body(sender_contractor_id=SENDER, receiver_contractor_id=RECEIVER,
                  billing_party="receiver"),
            _settings(storage))
    assert e.value.detail["code"] == "DHL_BILLING_PARTY_NOT_DECLARED"
    assert e.value.detail["declared"] == "sender"
    # No account number may appear in an error body.
    assert "958214771" not in repr(e.value.detail)
    assert "111222333" not in repr(e.value.detail)


def test_request_cannot_nominate_a_third_party_payer(storage):
    _add(storage, SENDER, "958214771")
    _add(storage, "THIRD003", "999888777")
    with pytest.raises(HTTPException) as e:
        _resolve(
            _body(sender_contractor_id=SENDER, billing_party="third_party",
                  third_party_contractor_id="THIRD003"),
            _settings(storage))
    assert e.value.detail["code"] == "DHL_BILLING_PARTY_NOT_DECLARED"
    assert "999888777" not in repr(e.value.detail)


def test_a_request_may_still_narrow_to_sender_paid(storage):
    """Asking for sender-paid is always allowed — it can only reduce exposure."""
    _add(storage, SENDER, "958214771")
    acct, res = _resolve(
        _body(sender_contractor_id=SENDER, billing_party="sender"),
        _settings(storage))
    assert acct == "958214771"
    assert res["billing_party"] == "sender"


# ── 8. adapter stays dumb ────────────────────────────────────────────────

def test_adapter_never_reads_client_master_storage():
    """The adapter must not CALL the account authority or open its store.

    Checked against executable code via the AST rather than raw text: the
    adapter now names ``resolve_dhl_billing_account`` in a docstring, to say
    that the verdict it serializes came from there. Explaining who decided is
    the opposite of deciding, and a substring search cannot tell them apart.
    """
    import ast
    tree = ast.parse(_read(ADAPTER))
    called = {
        node.func.id if isinstance(node.func, ast.Name) else
        getattr(node.func, "attr", "")
        for node in ast.walk(tree) if isinstance(node, ast.Call)
    }
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)

    for banned in ("resolve_dhl_billing_account", "list_accounts",
                   "resolve_declared_transport_payer"):
        assert banned not in called, \
            f"adapter must not call the account authority ({banned!r})"
        assert banned not in imported, \
            f"adapter must not import the account authority ({banned!r})"

    # String constants: the store must never be opened from here.
    consts = {n.value for n in ast.walk(tree)
              if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    for banned in ("customer_master.sqlite", "client_carrier_accounts"):
        assert not any(banned in c for c in consts), \
            f"adapter must not reach into the account store ({banned!r})"


def test_adapter_derives_no_default():
    code = _code(ADAPTER)
    for banned in ("is_default", "billing_party", "payment_type"):
        assert banned not in code, \
            f"adapter must not derive account selection ({banned!r})"


# ── 9. no full account number leaks ──────────────────────────────────────

def test_no_hardcoded_account_in_adapter():
    code = _code(ADAPTER)
    assert not re.search(r"\baccount\w*\s*=\s*[\"']\d{6,}[\"']", code), \
        "no hard-coded account number in the adapter"


def test_route_choice_payload_stays_masked(storage):
    _add(storage, SENDER, "111111111")
    _add(storage, SENDER, "222222222")
    with pytest.raises(HTTPException) as e:
        _resolve(_body(sender_contractor_id=SENDER),
                                   _settings(storage))
    blob = repr(e.value.detail)
    assert "111111111" not in blob and "222222222" not in blob
    assert "••••" in blob


# ── 10. sender-paid DHL request shape unchanged ──────────────────────────
#
# SUPERSEDED 2026-08-21. This asserted the literal source text of a one-account
# array and banned "payer" / "duties-taxes" while the MyDHL contract was
# unverified. It now pins the same guarantee BEHAVIOURALLY, by building the
# array — which is what actually reaches DHL, and which a source-text pin could
# never prove. The duties ban survives verbatim, because that one has not been
# superseded by anything: transport billing must not drag duty billing with it.

def _accounts(**kw):
    from app.services.carrier.adapters.live import _build_accounts
    from app.services.carrier.models.shipment import ShipmentRequest
    base = dict(batch_id="B", recipient_address={}, declared_value=1.0,
                currency="EUR", weight_kg=1.0, dimensions={})
    base.update(kw)
    return _build_accounts(ShipmentRequest(**base))


def test_sender_paid_shipment_payload_unchanged():
    """Sender-paid must still produce EXACTLY the single-entry array."""
    assert _accounts(shipper_account="958214771") == [
        {"typeCode": "shipper", "number": "958214771"},
    ]


def test_receiver_paid_adds_one_payer_entry():
    """Receiver-paid keeps the shipper entry and adds the payer beside it.

    The shipment still MOVES on the sender's account; only the charge is
    redirected. Losing the shipper entry would change what was shipped, not
    just who pays.
    """
    assert _accounts(shipper_account="958214771",
                     transport_payer="receiver",
                     billing_account="111222333") == [
        {"typeCode": "shipper", "number": "958214771"},
        {"typeCode": "payer", "number": "111222333"},
    ]


def test_a_payer_without_an_account_never_reaches_dhl():
    """A non-sender payer with no account is a resolver bug, not a DHL request.

    Emitting a payer entry with an empty number would ask DHL to bill nobody;
    falling back to the shipper-only shape keeps the charge where it already
    was rather than inventing a payer.
    """
    assert _accounts(shipper_account="958214771",
                     transport_payer="receiver",
                     billing_account=None) == [
        {"typeCode": "shipper", "number": "958214771"},
    ]


def test_duties_are_never_coupled_to_the_transport_payer():
    """Paying transport is not agreeing to pay duty.

    DHL carries the duty payer as its own account typeCode. This platform has
    no Customer Master authority for that decision, so it must never emit one —
    including, especially, when transport has just been redirected.
    """
    for accounts in (
        _accounts(shipper_account="958214771"),
        _accounts(shipper_account="958214771", transport_payer="receiver",
                  billing_account="111222333"),
    ):
        assert all(a["typeCode"] != "duties-taxes" for a in accounts)
    code = _code(ADAPTER)
    assert '"duties-taxes"' not in code, \
        "no duties typeCode until Customer Master owns that decision"


def test_rate_request_shape_unchanged():
    """Only the account VALUE changed — the query parameters did not."""
    code = _code(ADAPTER)
    for param in ('"accountNumber": account', '"originCountryCode"',
                  '"destinationCountryCode"', '"isCustomsDeclarable"'):
        assert param in code, f"rate query parameter {param} must be unchanged"
