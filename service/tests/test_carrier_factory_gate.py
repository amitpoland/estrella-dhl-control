"""
Phase C tests — CarrierFactory gate enforcement.

Verifies that the factory raises loudly for disallowed states and
returns the correct adapter class for allowed ones.
No HTTP. No DB. No credentials needed.
"""
import pytest

from app.services.carrier.adapters.live import DhlExpressLiveAdapter
from app.services.carrier.adapters.shadow import DhlExpressShadowAdapter
from app.services.carrier.factory import CarrierConfig, get_adapter
from app.services.carrier.models.shipment import CarrierGateError


def _cfg(**kwargs) -> CarrierConfig:
    return CarrierConfig(status="shadow", **kwargs)


# ── pending raises ────────────────────────────────────────────────────────────


def test_pending_status_raises_carrier_gate_error():
    cfg = CarrierConfig(status="pending")
    with pytest.raises(CarrierGateError, match="pending"):
        get_adapter(cfg)


def test_pending_error_message_is_actionable():
    cfg = CarrierConfig(status="pending")
    with pytest.raises(CarrierGateError) as exc:
        get_adapter(cfg)
    msg = str(exc.value)
    assert "CARRIER_API_STATUS" in msg or "pending" in msg


# ── unknown status raises ─────────────────────────────────────────────────────


def test_unknown_status_raises_carrier_gate_error():
    cfg = CarrierConfig(status="enabled")
    with pytest.raises(CarrierGateError, match="Unknown"):
        get_adapter(cfg)


def test_empty_status_raises():
    cfg = CarrierConfig(status="")
    with pytest.raises(CarrierGateError):
        get_adapter(cfg)


def test_typo_status_raises():
    for bad in ("SHADOW", "Live", "active", "on", "1"):
        cfg = CarrierConfig(status=bad)
        with pytest.raises(CarrierGateError):
            get_adapter(cfg)


# ── no silent fallback ────────────────────────────────────────────────────────


def test_pending_does_not_silently_return_shadow():
    cfg = CarrierConfig(status="pending")
    try:
        result = get_adapter(cfg)
        # if it didn't raise, it must not be a shadow adapter
        assert not isinstance(result, DhlExpressShadowAdapter), (
            "Factory silently fell back to shadow adapter for pending status"
        )
    except CarrierGateError:
        pass  # correct behaviour


# ── shadow returns correct type ───────────────────────────────────────────────


def test_shadow_status_returns_shadow_adapter():
    cfg = CarrierConfig(status="shadow")
    adapter = get_adapter(cfg)
    assert isinstance(adapter, DhlExpressShadowAdapter)


def test_shadow_adapter_is_not_live():
    cfg = CarrierConfig(status="shadow")
    adapter = get_adapter(cfg)
    assert not isinstance(adapter, DhlExpressLiveAdapter)


# ── live returns correct type ─────────────────────────────────────────────────


def test_live_status_returns_live_adapter():
    cfg = CarrierConfig(status="live", api_key="k", api_secret="s", live_allowlist="b1")
    adapter = get_adapter(cfg)
    assert isinstance(adapter, DhlExpressLiveAdapter)


def test_live_adapter_is_not_shadow():
    cfg = CarrierConfig(status="live", api_key="k", api_secret="s", live_allowlist="b1")
    adapter = get_adapter(cfg)
    assert not isinstance(adapter, DhlExpressShadowAdapter)


# ── factory produces fresh instances ─────────────────────────────────────────


def test_factory_returns_new_instance_each_call():
    cfg = CarrierConfig(status="shadow")
    a1 = get_adapter(cfg)
    a2 = get_adapter(cfg)
    assert a1 is not a2
