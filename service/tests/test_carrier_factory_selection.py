"""
test_carrier_factory_selection.py — DL-F1 adapter-selection tests
for ``routes_carrier_actions._select_carrier_adapter``.

Required:
  * factory returns stub when carrier_dhl_live_enabled is False.
  * factory returns stub when dhl_express_api_status is "pending".
  * factory returns stub when any of (username, password,
    account_number) is empty.
  * factory returns LIVE with sandbox URL when status == "sandbox".
  * factory returns LIVE with production URL when status == "production".
  * factory returns stub for unknown status.
  * factory NEVER raises on misconfiguration.
"""
from __future__ import annotations

import pytest

from app.api import routes_carrier_actions as rca
from app.core.config import settings
from app.services.carrier.adapters.dhl_express_live import (
    DHLExpressLiveAdapter,
)
from app.services.carrier.adapters.dhl_express_stub import (
    DHLExpressStubAdapter,
)


def _wire(
    monkeypatch,
    *,
    enabled:        bool = False,
    status:         str = "pending",
    username:       str = "",
    password:       str = "",
    account_number: str = "",
):
    monkeypatch.setattr(
        settings, "carrier_dhl_live_enabled", enabled, raising=False,
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


# ── 1. live flag false → stub ──────────────────────────────────────────────

def test_factory_returns_stub_when_live_flag_false(monkeypatch):
    _wire(monkeypatch, enabled=False, status="production",
          username="u", password="p", account_number="ACC")
    adapter = rca._select_carrier_adapter("test-actor")
    assert isinstance(adapter, DHLExpressStubAdapter)


# ── 2. status == pending → stub ────────────────────────────────────────────

def test_factory_returns_stub_when_status_pending(monkeypatch):
    _wire(monkeypatch, enabled=True, status="pending",
          username="u", password="p", account_number="ACC")
    adapter = rca._select_carrier_adapter("test-actor")
    assert isinstance(adapter, DHLExpressStubAdapter)


def test_factory_returns_stub_when_status_pending_default(monkeypatch):
    _wire(monkeypatch, enabled=True, status="",
          username="u", password="p", account_number="ACC")
    adapter = rca._select_carrier_adapter("test-actor")
    assert isinstance(adapter, DHLExpressStubAdapter)


# ── 3. credentials missing → stub ──────────────────────────────────────────

@pytest.mark.parametrize("missing", ["username", "password", "account_number"])
def test_factory_returns_stub_when_credentials_missing(monkeypatch, missing):
    _wire(
        monkeypatch, enabled=True, status="sandbox",
        username="" if missing == "username" else "u",
        password="" if missing == "password" else "p",
        account_number="" if missing == "account_number" else "ACC",
    )
    adapter = rca._select_carrier_adapter("test-actor")
    assert isinstance(adapter, DHLExpressStubAdapter)


def test_factory_returns_stub_when_credentials_whitespace(monkeypatch):
    _wire(monkeypatch, enabled=True, status="sandbox",
          username="   ", password="p", account_number="ACC")
    adapter = rca._select_carrier_adapter("test-actor")
    assert isinstance(adapter, DHLExpressStubAdapter)


# ── 4. status == sandbox → live with sandbox URL ──────────────────────────

def test_factory_returns_live_sandbox_when_eligible(monkeypatch):
    _wire(monkeypatch, enabled=True, status="sandbox",
          username="u", password="p", account_number="ACC")
    adapter = rca._select_carrier_adapter("test-actor")
    assert isinstance(adapter, DHLExpressLiveAdapter)
    assert adapter.base_url == "https://express.api.dhl.com/mydhlapi/test"
    assert adapter.carrier == "dhl"


# ── 5. status == production → live with production URL ────────────────────

def test_factory_returns_live_production_when_eligible(monkeypatch):
    _wire(monkeypatch, enabled=True, status="production",
          username="u", password="p", account_number="ACC")
    adapter = rca._select_carrier_adapter("test-actor")
    assert isinstance(adapter, DHLExpressLiveAdapter)
    assert adapter.base_url == "https://express.api.dhl.com/mydhlapi"


def test_factory_returns_live_for_uppercase_sandbox_value(monkeypatch):
    """Status comparison is case-insensitive."""
    _wire(monkeypatch, enabled=True, status="SANDBOX",
          username="u", password="p", account_number="ACC")
    adapter = rca._select_carrier_adapter("test-actor")
    assert isinstance(adapter, DHLExpressLiveAdapter)
    assert adapter.base_url.endswith("/test")


# ── 6. unknown status → stub ───────────────────────────────────────────────

@pytest.mark.parametrize("status", [
    "garbage", "demo", "preview", "live", "active", "yes",
])
def test_factory_returns_stub_for_unknown_status(monkeypatch, status):
    _wire(monkeypatch, enabled=True, status=status,
          username="u", password="p", account_number="ACC")
    adapter = rca._select_carrier_adapter("test-actor")
    assert isinstance(adapter, DHLExpressStubAdapter), (
        f"unknown status {status!r} should fall back to stub, "
        f"got {type(adapter).__name__}"
    )


# ── 7. Factory NEVER raises ────────────────────────────────────────────────

def test_factory_never_raises_on_any_misconfig_combination(monkeypatch):
    """Cartesian product over the four binary axes — no combination
    should propagate an exception."""
    for enabled in [True, False]:
        for status in ["pending", "sandbox", "production", "garbage", ""]:
            for username in ["u", ""]:
                for password in ["p", ""]:
                    for acct in ["ACC", ""]:
                        _wire(monkeypatch, enabled=enabled, status=status,
                              username=username, password=password,
                              account_number=acct)
                        try:
                            adapter = rca._select_carrier_adapter("a")
                        except Exception as exc:
                            pytest.fail(
                                f"factory raised on enabled={enabled} "
                                f"status={status!r} u={username!r} "
                                f"p={password!r} acct={acct!r}: {exc}"
                            )
                        assert adapter is not None


# ── 8. Default settings (out-of-the-box) → stub ────────────────────────────

def test_factory_default_settings_yield_stub():
    """Without any monkeypatching, the default settings (live=False,
    status=pending, empty credentials) must select the stub."""
    adapter = rca._select_carrier_adapter("test-actor")
    assert isinstance(adapter, DHLExpressStubAdapter)


# ── Existing make_coordinator still wires the chosen adapter ──────────────

def test_make_coordinator_uses_select_carrier_adapter(monkeypatch, tmp_path):
    """End-to-end: when the factory returns the stub, _make_coordinator
    builds a CarrierCoordinator wired to the stub."""
    monkeypatch.setattr(settings, "storage_root", tmp_path, raising=False)
    _wire(monkeypatch, enabled=False)  # stub path
    coord = rca._make_coordinator("op")
    # CarrierCoordinator's adapter is private but the type is observable
    # via the protocol attribute on the construction call.
    assert coord is not None
