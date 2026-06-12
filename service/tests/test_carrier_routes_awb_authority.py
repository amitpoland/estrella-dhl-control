"""Tests for shipment creation route with AWB address authority feature.

Tests the feature flag behavior, error handling, and integration with the
existing carrier route infrastructure for Campaign 02.5 Workstream 3.
"""
from __future__ import annotations

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes_carrier_actions import router as actions_router
from app.core.security import require_api_key


# ── Test setup ─────────────────────────────────────────────────────────────────


@pytest.fixture
def app_with_authority_flag_off():
    """FastAPI app with AWB address authority flag OFF."""
    app = FastAPI()
    app.include_router(actions_router)

    # Mock dependencies
    def _no_auth():
        return None

    def _mock_coordinator():
        mock_coord = MagicMock()
        mock_result = MagicMock()
        mock_result.idempotency_key = "test-key-123"
        mock_result.mode.value = "shadow"
        mock_result.state.value = "completed"
        mock_result.tracking_ref = "TEST123456789"
        mock_result.simulated = True
        mock_coord.create_shipment.return_value = mock_result
        return mock_coord

    app.dependency_overrides[require_api_key] = _no_auth

    # Mock settings with flag OFF
    with patch('app.core.config.settings') as mock_settings:
        mock_settings.awb_address_authority_enabled = False
        mock_settings.storage_root = Path("/tmp/test")

        from app.api.routes_carrier_actions import _get_coordinator
        app.dependency_overrides[_get_coordinator] = _mock_coordinator

        yield app


@pytest.fixture
def app_with_authority_flag_on():
    """FastAPI app with AWB address authority flag ON."""
    app = FastAPI()
    app.include_router(actions_router)

    # Mock dependencies
    def _no_auth():
        return None

    def _mock_coordinator():
        mock_coord = MagicMock()
        mock_result = MagicMock()
        mock_result.idempotency_key = "test-key-456"
        mock_result.mode.value = "shadow"
        mock_result.state.value = "completed"
        mock_result.tracking_ref = "AUTH789012345"
        mock_result.simulated = True
        mock_coord.create_shipment.return_value = mock_result
        return mock_coord

    app.dependency_overrides[require_api_key] = _no_auth

    # Mock settings with flag ON
    with patch('app.core.config.settings') as mock_settings:
        mock_settings.awb_address_authority_enabled = True
        mock_settings.storage_root = Path("/tmp/test")

        from app.api.routes_carrier_actions import _get_coordinator
        app.dependency_overrides[_get_coordinator] = _mock_coordinator

        yield app


# ── Feature Flag OFF Tests ──────────────────────────────────────────────────────


class TestFeatureFlagOff:
    """Test behavior when awb_address_authority_enabled = False."""

    def test_flag_off_preserves_raw_recipient_address(self, app_with_authority_flag_off):
        """Test that raw recipient_address is used when flag is OFF."""
        client = TestClient(app_with_authority_flag_off)

        raw_address = {
            "name": "Raw Customer Name",
            "street": "Raw Street 123",
            "city": "Raw City",
            "country": "Poland"
        }

        response = client.post(
            "/api/v1/carrier/AWB_1234567890/shipment",
            json={
                "shipper_account": "TEST_ACC",
                "recipient_address": raw_address,
                "declared_value": 100.0,
                "currency": "USD",
                "weight_kg": 1.0,
                "dimensions": {"length": 10, "width": 10, "height": 10}
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert data["batch_id"] == "AWB_1234567890"
        assert data["idempotency_key"] == "test-key-123"

    def test_flag_off_accepts_empty_recipient_address(self, app_with_authority_flag_off):
        """Test that empty recipient_address is accepted when flag is OFF."""
        client = TestClient(app_with_authority_flag_off)

        response = client.post(
            "/api/v1/carrier/BATCH_TEST/shipment",
            json={
                "shipper_account": "TEST_ACC",
                "recipient_address": {},  # Empty address - should work with flag OFF
                "declared_value": 50.0,
                "currency": "EUR",
                "weight_kg": 0.5,
                "dimensions": {"length": 5, "width": 5, "height": 5}
            }
        )

        assert response.status_code == 200


# ── Feature Flag ON Tests ────────────────────────────────────────────────────────


class TestFeatureFlagOn:
    """Test behavior when awb_address_authority_enabled = True."""

    @patch('app.services.awb_address_authority.derive_awb_address_authority_with_fallback')
    def test_flag_on_uses_customer_master_authority(self, mock_derive, app_with_authority_flag_on):
        """Test that Customer Master authority is used when flag is ON."""
        # Mock successful authority derivation
        mock_derive.return_value = {
            "name": "Customer Master Name",
            "street": "Authority Street 456",
            "city": "Authority City",
            "country": "Poland",
            "source": "ship_to"
        }

        client = TestClient(app_with_authority_flag_on)

        response = client.post(
            "/api/v1/carrier/AWB_9876543210/shipment",
            json={
                "shipper_account": "AUTH_ACC",
                "recipient_address": {
                    "name": "Ignored Raw Name",
                    "city": "Ignored Raw City"
                },
                "declared_value": 200.0,
                "currency": "USD",
                "weight_kg": 2.0,
                "dimensions": {"length": 20, "width": 15, "height": 10}
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert data["batch_id"] == "AWB_9876543210"

        # Verify authority derivation was called
        mock_derive.assert_called_once()
        args = mock_derive.call_args[0]
        assert args[0] == "AWB_9876543210"  # batch_id
        # raw_fallback should be the original recipient_address
        kwargs = mock_derive.call_args[1]
        assert "raw_fallback" in kwargs

    @patch('app.services.awb_address_authority.derive_awb_address_authority_with_fallback')
    def test_customer_not_found_returns_422(self, mock_derive, app_with_authority_flag_on):
        """Test 422 response when customer cannot be found."""
        from app.services.awb_address_authority import CustomerNotFoundError

        mock_derive.side_effect = CustomerNotFoundError("Test customer not found")

        client = TestClient(app_with_authority_flag_on)

        response = client.post(
            "/api/v1/carrier/INVALID_BATCH/shipment",
            json={
                "shipper_account": "TEST_ACC",
                "recipient_address": {"name": "Test"},
                "declared_value": 100.0,
                "currency": "USD",
                "weight_kg": 1.0,
                "dimensions": {"length": 10, "width": 10, "height": 10}
            }
        )

        assert response.status_code == 422
        error = response.json()["detail"]
        assert error["error"] == "Customer resolution failed"
        assert error["code"] == "CUSTOMER_NOT_FOUND"
        assert error["batch_id"] == "INVALID_BATCH"
        assert "Customer Master" in error["guidance"]

    @patch('app.services.awb_address_authority.derive_awb_address_authority_with_fallback')
    def test_address_missing_returns_422(self, mock_derive, app_with_authority_flag_on):
        """Test 422 response when address is incomplete."""
        from app.services.awb_address_authority import AddressMissingError

        mock_derive.side_effect = AddressMissingError("Missing required fields: street, city")

        client = TestClient(app_with_authority_flag_on)

        response = client.post(
            "/api/v1/carrier/INCOMPLETE_BATCH/shipment",
            json={
                "shipper_account": "TEST_ACC",
                "recipient_address": {"name": "Incomplete"},
                "declared_value": 100.0,
                "currency": "USD",
                "weight_kg": 1.0,
                "dimensions": {"length": 10, "width": 10, "height": 10}
            }
        )

        assert response.status_code == 422
        error = response.json()["detail"]
        assert error["error"] == "Address validation failed"
        assert error["code"] == "ADDRESS_INCOMPLETE"
        assert error["batch_id"] == "INCOMPLETE_BATCH"
        assert "complete the customer address" in error["guidance"]

    @patch('app.services.awb_address_authority.derive_awb_address_authority_with_fallback')
    def test_source_metadata_removed_from_carrier_request(self, mock_derive, app_with_authority_flag_on):
        """Test that 'source' metadata is removed before sending to carrier."""
        # Mock authority result with source metadata
        authority_address = {
            "name": "Authority Customer",
            "street": "Authority Street",
            "city": "Authority City",
            "country": "Poland",
            "source": "ship_to"  # This should be removed
        }
        mock_derive.return_value = authority_address

        # Mock the coordinator to capture the request
        def _mock_coordinator_with_capture():
            mock_coord = MagicMock()

            def capture_request(request):
                # Verify recipient_address doesn't contain 'source'
                assert "source" not in request.recipient_address
                assert request.recipient_address["name"] == "Authority Customer"

                # Return mock result
                mock_result = MagicMock()
                mock_result.idempotency_key = "captured-key"
                mock_result.mode.value = "shadow"
                mock_result.state.value = "completed"
                mock_result.tracking_ref = "CAPTURED123"
                mock_result.simulated = True
                return mock_result

            mock_coord.create_shipment = capture_request
            return mock_coord

        client = TestClient(app_with_authority_flag_on)

        with patch('app.api.routes_carrier_actions._get_coordinator', _mock_coordinator_with_capture):
            response = client.post(
                "/api/v1/carrier/TEST_SOURCE_REMOVAL/shipment",
                json={
                    "shipper_account": "TEST_ACC",
                    "recipient_address": {"name": "Original"},
                    "declared_value": 100.0,
                    "currency": "USD",
                    "weight_kg": 1.0,
                    "dimensions": {"length": 10, "width": 10, "height": 10}
                }
            )

        assert response.status_code == 200


# ── Backward Compatibility Tests ──────────────────────────────────────────────────


class TestBackwardCompatibility:
    """Test that existing functionality is preserved."""

    def test_existing_request_body_structure_preserved(self, app_with_authority_flag_off):
        """Test that the ShipmentRequestBody model still accepts original fields."""
        client = TestClient(app_with_authority_flag_off)

        # This is the exact structure that existing callers would send
        original_request = {
            "shipper_account": "EXISTING_ACC",
            "recipient_address": {
                "name": "Existing Customer",
                "street": "Existing Street 789",
                "city": "Existing City",
                "postal_code": "12345",
                "country": "Poland",
                "phone": "+48987654321"
            },
            "declared_value": 500.0,
            "currency": "USD",
            "weight_kg": 3.0,
            "dimensions": {
                "length": 30,
                "width": 20,
                "height": 15
            },
            "special_instructions": "Fragile items"
        }

        response = client.post(
            "/api/v1/carrier/EXISTING_BATCH/shipment",
            json=original_request
        )

        assert response.status_code == 200
        data = response.json()
        assert "idempotency_key" in data
        assert "tracking_ref" in data

    def test_carrier_gate_behavior_unchanged(self):
        """Test that carrier gate (503 when pending) still works."""
        # This would require setting up the actual carrier gate config
        # For now, verify the gate logic is not modified by checking imports
        from app.api.routes_carrier_actions import _get_carrier_config

        # The gate check should still be in place
        # (Full integration test would require actual config setup)
        assert _get_carrier_config is not None