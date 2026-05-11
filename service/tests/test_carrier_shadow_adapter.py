"""
Phase C tests — DhlExpressShadowAdapter.

Verifies determinism, simulated=True contract, SIM- prefix,
and the hard absence of any HTTP library import.
No HTTP. No DB. No files.
"""
import inspect

import pytest

from app.services.carrier.adapters.shadow import DhlExpressShadowAdapter, _idempotency_key
from app.services.carrier.models.shipment import ShipmentMode, ShipmentRequest, ShipmentState


def _req(**kwargs) -> ShipmentRequest:
    defaults = dict(
        batch_id="BATCH-001",
        shipper_account="ACC-001",
        recipient_address={"name": "Test", "country": "PL"},
        declared_value=1000.0,
        currency="USD",
        weight_kg=2.5,
        dimensions={"length": 30, "width": 20, "height": 10},
    )
    defaults.update(kwargs)
    return ShipmentRequest(**defaults)


_adapter = DhlExpressShadowAdapter()


# ── simulated contract ────────────────────────────────────────────────────────


def test_create_shipment_simulated_true():
    result = _adapter.create_shipment(_req())
    assert result.simulated is True


def test_create_shipment_mode_is_shadow():
    result = _adapter.create_shipment(_req())
    assert result.mode == ShipmentMode.SHADOW


def test_create_shipment_state_is_submitted():
    result = _adapter.create_shipment(_req())
    assert result.state == ShipmentState.SUBMITTED


def test_get_shipment_simulated_true():
    result = _adapter.get_shipment("SIM-ABCD1234")
    assert result.simulated is True


def test_get_shipment_mode_is_shadow():
    result = _adapter.get_shipment("SIM-ABCD1234")
    assert result.mode == ShipmentMode.SHADOW


def test_get_shipment_state_is_complete():
    result = _adapter.get_shipment("SIM-ABCD1234")
    assert result.state == ShipmentState.COMPLETE


# ── tracking ref format ───────────────────────────────────────────────────────


def test_tracking_ref_starts_with_sim():
    result = _adapter.create_shipment(_req())
    assert result.tracking_ref.startswith("SIM-")


def test_tracking_ref_length():
    result = _adapter.create_shipment(_req())
    # "SIM-" + 8 hex chars uppercase = 12 chars
    assert len(result.tracking_ref) == 12


def test_tracking_ref_is_uppercase_hex_after_prefix():
    result = _adapter.create_shipment(_req())
    suffix = result.tracking_ref[4:]  # strip "SIM-"
    assert suffix == suffix.upper()
    assert all(c in "0123456789ABCDEF" for c in suffix)


# ── determinism ───────────────────────────────────────────────────────────────


def test_same_request_produces_same_idempotency_key():
    r1 = _req(batch_id="BATCH-DETERM")
    r2 = _req(batch_id="BATCH-DETERM")
    assert _idempotency_key(r1) == _idempotency_key(r2)


def test_same_request_produces_same_tracking_ref():
    r = _req(batch_id="BATCH-STABLE")
    result1 = _adapter.create_shipment(r)
    result2 = _adapter.create_shipment(r)
    assert result1.tracking_ref == result2.tracking_ref


def test_different_batch_id_produces_different_key():
    r1 = _req(batch_id="BATCH-X")
    r2 = _req(batch_id="BATCH-Y")
    assert _idempotency_key(r1) != _idempotency_key(r2)


def test_different_weight_produces_different_key():
    r1 = _req(weight_kg=1.0)
    r2 = _req(weight_kg=2.0)
    assert _idempotency_key(r1) != _idempotency_key(r2)


def test_different_value_produces_different_key():
    r1 = _req(declared_value=100.0)
    r2 = _req(declared_value=200.0)
    assert _idempotency_key(r1) != _idempotency_key(r2)


# ── idempotency key format ────────────────────────────────────────────────────


def test_idempotency_key_is_64_char_hex():
    key = _idempotency_key(_req())
    assert len(key) == 64
    assert all(c in "0123456789abcdef" for c in key)


def test_result_carries_idempotency_key():
    result = _adapter.create_shipment(_req(batch_id="BATCH-KEY"))
    assert len(result.idempotency_key) == 64


# ── no HTTP imports ───────────────────────────────────────────────────────────


def test_shadow_module_does_not_import_httpx():
    import app.services.carrier.adapters.shadow as mod
    src = inspect.getsource(mod)
    assert "import httpx" not in src


def test_shadow_module_does_not_import_requests():
    import app.services.carrier.adapters.shadow as mod
    src = inspect.getsource(mod)
    assert "import requests" not in src


def test_shadow_module_does_not_import_urllib():
    import app.services.carrier.adapters.shadow as mod
    src = inspect.getsource(mod)
    assert "urllib.request" not in src
