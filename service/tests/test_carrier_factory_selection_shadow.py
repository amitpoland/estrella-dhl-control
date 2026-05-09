"""
test_carrier_factory_selection_shadow.py — DL-F2 factory-selection
tests extending the DL-F1 selection rules with shadow-mode wrapping.

Required:
  * factory returns shadow when shadow=True + sandbox + creds.
  * factory returns shadow when shadow=True + production + creds.
  * factory returns stub when shadow=True but live disabled.
  * factory returns stub when shadow=True but pending.
  * factory returns stub when shadow=True but credentials missing.
  * factory returns live when shadow=False + sandbox + creds.
  * factory returns live when shadow=False + production + creds.
  * Existing selection-test invariants still hold.
  * Defensive: wrapper construction failure → stub fallback.
"""
from __future__ import annotations

import pytest

from app.api import routes_carrier_actions as rca
from app.core.config import settings
from app.services.carrier.adapters.dhl_express_live import (
    DHLExpressLiveAdapter,
)
from app.services.carrier.adapters.dhl_express_shadow import (
    DHLExpressShadowAdapter,
)
from app.services.carrier.adapters.dhl_express_stub import (
    DHLExpressStubAdapter,
)


def _wire(
    monkeypatch,
    *,
    enabled:        bool = False,
    shadow:         bool = False,
    status:         str = "pending",
    username:       str = "",
    password:       str = "",
    account_number: str = "",
):
    monkeypatch.setattr(
        settings, "carrier_dhl_live_enabled", enabled, raising=False,
    )
    monkeypatch.setattr(
        settings, "carrier_dhl_shadow_mode", shadow, raising=False,
    )
    monkeypatch.setattr(
        settings, "dhl_express_api_status", status, raising=False,
    )
    monkeypatch.setattr(
        settings, "dhl_express_api_username", username, raising=False,
    )
    monkeypatch.setattr(
        settings, "dhl_express_api_password", password, raising=False,
    )
    monkeypatch.setattr(
        settings, "dhl_express_account_number", account_number,
        raising=False,
    )


# ── Shadow-eligible cases ──────────────────────────────────────────────────

def test_shadow_true_sandbox_credentials_yields_shadow(monkeypatch):
    _wire(monkeypatch, enabled=True, shadow=True, status="sandbox",
          username="u", password="p", account_number="ACC")
    adapter = rca._select_carrier_adapter("op-shadow")
    assert isinstance(adapter, DHLExpressShadowAdapter)
    assert isinstance(adapter.stub, DHLExpressStubAdapter)
    assert isinstance(adapter.live, DHLExpressLiveAdapter)
    assert adapter.live.base_url == "https://express.api.dhl.com/mydhlapi/test"


def test_shadow_true_production_credentials_yields_shadow(monkeypatch):
    _wire(monkeypatch, enabled=True, shadow=True, status="production",
          username="u", password="p", account_number="ACC")
    adapter = rca._select_carrier_adapter("op-shadow")
    assert isinstance(adapter, DHLExpressShadowAdapter)
    assert adapter.live.base_url == "https://express.api.dhl.com/mydhlapi"


# ── Shadow gates fail open to stub ─────────────────────────────────────────

def test_shadow_true_but_live_disabled_yields_stub(monkeypatch):
    _wire(monkeypatch, enabled=False, shadow=True, status="production",
          username="u", password="p", account_number="ACC")
    adapter = rca._select_carrier_adapter("op")
    assert isinstance(adapter, DHLExpressStubAdapter)


def test_shadow_true_but_pending_yields_stub(monkeypatch):
    _wire(monkeypatch, enabled=True, shadow=True, status="pending",
          username="u", password="p", account_number="ACC")
    adapter = rca._select_carrier_adapter("op")
    assert isinstance(adapter, DHLExpressStubAdapter)


@pytest.mark.parametrize("missing", ["username", "password", "account_number"])
def test_shadow_true_but_credentials_missing_yields_stub(monkeypatch, missing):
    _wire(
        monkeypatch, enabled=True, shadow=True, status="sandbox",
        username="" if missing == "username" else "u",
        password="" if missing == "password" else "p",
        account_number="" if missing == "account_number" else "ACC",
    )
    adapter = rca._select_carrier_adapter("op")
    assert isinstance(adapter, DHLExpressStubAdapter)


def test_shadow_true_unknown_status_yields_stub(monkeypatch):
    _wire(monkeypatch, enabled=True, shadow=True, status="garbage",
          username="u", password="p", account_number="ACC")
    adapter = rca._select_carrier_adapter("op")
    assert isinstance(adapter, DHLExpressStubAdapter)


# ── Shadow off keeps DL-F1 behaviour ───────────────────────────────────────

def test_shadow_false_sandbox_yields_live(monkeypatch):
    _wire(monkeypatch, enabled=True, shadow=False, status="sandbox",
          username="u", password="p", account_number="ACC")
    adapter = rca._select_carrier_adapter("op")
    assert isinstance(adapter, DHLExpressLiveAdapter)
    assert not isinstance(adapter, DHLExpressShadowAdapter)
    assert adapter.base_url.endswith("/test")


def test_shadow_false_production_yields_live(monkeypatch):
    _wire(monkeypatch, enabled=True, shadow=False, status="production",
          username="u", password="p", account_number="ACC")
    adapter = rca._select_carrier_adapter("op")
    assert isinstance(adapter, DHLExpressLiveAdapter)
    assert not isinstance(adapter, DHLExpressShadowAdapter)
    assert adapter.base_url.endswith("/mydhlapi")
    assert not adapter.base_url.endswith("/test")


# ── Default settings still yield stub ──────────────────────────────────────

def test_default_settings_yield_stub():
    """No monkeypatch: defaults are live=False, shadow=False,
    pending. Out-of-the-box install must still select the stub."""
    adapter = rca._select_carrier_adapter("op")
    assert isinstance(adapter, DHLExpressStubAdapter)


# ── Defensive fallback ────────────────────────────────────────────────────

def test_shadow_constructor_failure_falls_back_to_stub(monkeypatch):
    """If the shadow wrapper itself raises during construction, the
    factory must NOT propagate; it falls back to the stub.
    Achieved here by patching the import to a class whose __init__
    raises."""
    _wire(monkeypatch, enabled=True, shadow=True, status="sandbox",
          username="u", password="p", account_number="ACC")

    import sys
    import types

    class _BoomAdapter:
        carrier = "dhl"
        def __init__(self, **kwargs):
            raise RuntimeError("simulated wrapper failure")

    fake_mod = types.ModuleType(
        "app.services.carrier.adapters.dhl_express_shadow"
    )
    fake_mod.DHLExpressShadowAdapter = _BoomAdapter
    monkeypatch.setitem(
        sys.modules,
        "app.services.carrier.adapters.dhl_express_shadow",
        fake_mod,
    )
    adapter = rca._select_carrier_adapter("op")
    assert isinstance(adapter, DHLExpressStubAdapter)


def test_factory_never_raises_on_shadow_combinations(monkeypatch):
    """Cartesian over enabled / shadow / status / creds — no
    combination should propagate an exception."""
    for enabled in [True, False]:
        for shadow in [True, False]:
            for status in ["pending", "sandbox", "production",
                            "garbage", ""]:
                for username in ["u", ""]:
                    for password in ["p", ""]:
                        for acct in ["ACC", ""]:
                            _wire(monkeypatch, enabled=enabled,
                                  shadow=shadow, status=status,
                                  username=username,
                                  password=password,
                                  account_number=acct)
                            try:
                                adapter = rca._select_carrier_adapter("a")
                            except Exception as exc:
                                pytest.fail(
                                    f"factory raised on enabled={enabled} "
                                    f"shadow={shadow} status={status!r} "
                                    f"u={username!r} p={password!r} "
                                    f"acct={acct!r}: {exc}"
                                )
                            assert adapter is not None
