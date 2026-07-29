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
                third_party_contractor_id=None, billing_account_id=None)
    base.update(kw)
    return types.SimpleNamespace(**base)


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
    acct, res = _resolve_shipment_accounts(
        _body(sender_contractor_id=SENDER),
        _settings(storage, env_account="ENV0000000"))
    assert acct == "958214771", "Client Master account must win over config"
    assert res is not None and res["ok"]


def test_known_sender_without_account_blocks_and_ignores_env(storage):
    with pytest.raises(HTTPException) as e:
        _resolve_shipment_accounts(
            _body(sender_contractor_id=SENDER),
            _settings(storage, env_account="ENV0000000"))
    assert e.value.detail["code"] == "DHL_ACCOUNT_UNRESOLVED"
    assert "ENV0000000" not in repr(e.value.detail)


# ── 4. unknown sender keeps the legacy env path ──────────────────────────

def test_unknown_sender_preserves_legacy_env_path(storage):
    acct, res = _resolve_shipment_accounts(
        _body(), _settings(storage, env_account="ENV0000000"))
    assert acct == "ENV0000000"
    assert res is None


def test_legacy_explicit_account_still_wins_for_unknown_sender(storage):
    acct, _ = _resolve_shipment_accounts(
        _body(shipper_account="EXPLICIT01"),
        _settings(storage, env_account="ENV0000000"))
    assert acct == "EXPLICIT01"


# ── 5. ambiguous accounts block the rate ─────────────────────────────────

def test_multiple_accounts_without_selection_block(storage):
    _add(storage, SENDER, "111111111")
    _add(storage, SENDER, "222222222")
    with pytest.raises(HTTPException) as e:
        _resolve_shipment_accounts(_body(sender_contractor_id=SENDER),
                                   _settings(storage))
    assert e.value.detail["code"] == "DHL_ACCOUNT_CHOICE_REQUIRED"


def test_selected_account_flows_through(storage):
    a = _add(storage, SENDER, "111111111")
    _add(storage, SENDER, "222222222")
    acct, _ = _resolve_shipment_accounts(
        _body(sender_contractor_id=SENDER, billing_account_id=a),
        _settings(storage))
    assert acct == "111111111", "the operator's selection must reach the rate request"


# ── 6. receiver billing never falls back to the sender ───────────────────

def test_receiver_billing_blocks_before_any_rate_call(storage):
    _add(storage, SENDER, "958214771")
    _add(storage, RECEIVER, "111222333")
    with pytest.raises(HTTPException) as e:
        _resolve_shipment_accounts(
            _body(sender_contractor_id=SENDER, receiver_contractor_id=RECEIVER,
                  billing_party="receiver"),
            _settings(storage))
    assert e.value.detail["code"] == "DHL_BILLING_PARTY_NOT_ENABLED"
    assert "958214771" not in repr(e.value.detail)


def test_third_party_billing_blocked(storage):
    _add(storage, SENDER, "958214771")
    _add(storage, "THIRD003", "999888777")
    with pytest.raises(HTTPException) as e:
        _resolve_shipment_accounts(
            _body(sender_contractor_id=SENDER, billing_party="third_party",
                  third_party_contractor_id="THIRD003"),
            _settings(storage))
    assert e.value.detail["code"] == "DHL_BILLING_PARTY_NOT_ENABLED"


# ── 8. adapter stays dumb ────────────────────────────────────────────────

def test_adapter_never_reads_client_master_storage():
    code = _code(ADAPTER)
    for banned in ("client_carrier_accounts", "resolve_dhl_billing_account",
                   "customer_master.sqlite", "list_accounts"):
        assert banned not in code, \
            f"adapter must not reach into the account authority ({banned!r})"


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
        _resolve_shipment_accounts(_body(sender_contractor_id=SENDER),
                                   _settings(storage))
    blob = repr(e.value.detail)
    assert "111111111" not in blob and "222222222" not in blob
    assert "••••" in blob


# ── 10. sender-paid DHL request shape unchanged ──────────────────────────

def test_sender_paid_shipment_payload_unchanged():
    code = _code(ADAPTER)
    assert '"typeCode": "shipper"' in code
    assert '"number": request.shipper_account' in code
    for banned in ('"payer"', '"thirdParty"', '"duties-taxes"'):
        assert banned not in code, f"{banned} must not appear until verified"


def test_rate_request_shape_unchanged():
    """Only the account VALUE changed — the query parameters did not."""
    code = _code(ADAPTER)
    for param in ('"accountNumber": account', '"originCountryCode"',
                  '"destinationCountryCode"', '"isCustomsDeclarable"'):
        assert param in code, f"rate query parameter {param} must be unchanged"
