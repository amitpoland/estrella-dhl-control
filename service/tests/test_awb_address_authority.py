"""Tests for AWB Address Authority Repair (Campaign 02.5 Workstream 3).

Tests the new Customer Master authority derivation for shipment creation,
including feature flag behavior, error handling, and fallback mechanisms.
"""
from __future__ import annotations

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from datetime import datetime

from app.services.awb_address_authority import (
    derive_awb_address_authority,
    derive_awb_address_authority_with_fallback,
    CustomerNotFoundError,
    AddressMissingError,
    _is_historical_batch,
)


# ── Feature Flag Integration Tests ──────────────────────────────────────────────


@pytest.fixture
def mock_storage_root(tmp_path):
    """Provide a temporary storage root path."""
    return tmp_path


@pytest.fixture
def mock_customer_with_ship_to():
    """Mock customer with populated ship-to address."""
    customer = MagicMock()
    customer.ship_to_use_alternate = True
    customer.ship_to_name = "Estrella Jewels Sp. z o.o."
    customer.ship_to_person = "Jan Kowalski"
    customer.ship_to_street = "ul. Złota 123"
    customer.ship_to_city = "Warszawa"
    customer.ship_to_zip = "00-001"
    customer.ship_to_country = "Poland"
    customer.ship_to_phone = "+48 123 456 789"
    customer.ship_to_email = "contact@estrellajewels.eu"
    return customer


@pytest.fixture
def mock_customer_bill_to_only():
    """Mock customer with only billing address (no ship-to)."""
    customer = MagicMock()
    customer.ship_to_use_alternate = False
    customer.ship_to_name = None
    customer.ship_to_street = None
    customer.ship_to_city = None
    return customer


@pytest.fixture
def mock_incomplete_customer():
    """Mock customer with incomplete addresses."""
    customer = MagicMock()
    customer.ship_to_use_alternate = True
    customer.ship_to_name = "Incomplete Customer"
    customer.ship_to_street = ""  # Missing required field
    customer.ship_to_city = ""    # Missing required field
    return customer


class TestHistoricalBatchDetection:
    """Test the _is_historical_batch helper function."""

    def test_recent_shipment_batch_not_historical(self):
        """Current month SHIPMENT batch should not be historical."""
        current_month = datetime.now().strftime("%Y-%m")
        batch_id = f"SHIPMENT_1234567890_{current_month}_abcd1234"
        assert not _is_historical_batch(batch_id)

    def test_old_shipment_batch_is_historical(self):
        """2025 SHIPMENT batch should be historical."""
        batch_id = "SHIPMENT_1234567890_2025-01_abcd1234"
        assert _is_historical_batch(batch_id)

    def test_awb_batch_not_historical(self):
        """AWB format batches are treated as recent."""
        assert not _is_historical_batch("AWB_1234567890")

    def test_invalid_shipment_format_not_historical(self):
        """Invalid SHIPMENT formats treated as recent."""
        assert not _is_historical_batch("SHIPMENT_invalid_format")
        assert not _is_historical_batch("SHIPMENT_1234567890_2025-99_abcd1234")


class TestAuthorityDerivation:
    """Test the core authority derivation functions."""

    @patch('app.services.customer_master.resolve_delivery_address')
    @patch('app.services.carrier.doc_package._resolve_customer_from_batch')
    def test_successful_ship_to_authority(self, mock_resolve_customer, mock_resolve_addr,
                                        mock_customer_with_ship_to, mock_storage_root):
        """Test successful authority derivation with ship-to address."""
        mock_resolve_customer.return_value = mock_customer_with_ship_to
        mock_resolve_addr.return_value = {
            "name": "Estrella Jewels Sp. z o.o.",
            "person": "Jan Kowalski",
            "street": "ul. Złota 123",
            "city": "Warszawa",
            "postal_code": "00-001",
            "country": "Poland",
            "phone": "+48 123 456 789",
            "email": "contact@estrellajewels.eu",
            "source": "ship_to",
        }

        result = derive_awb_address_authority("AWB_1234567890", mock_storage_root)

        assert result["name"] == "Estrella Jewels Sp. z o.o."
        assert result["source"] == "ship_to"
        mock_resolve_customer.assert_called_once_with("AWB_1234567890", client_name=None, storage_root=mock_storage_root)
        mock_resolve_addr.assert_called_once_with(mock_customer_with_ship_to)

    @patch('app.services.carrier.doc_package._resolve_customer_from_batch')
    def test_customer_not_found_error(self, mock_resolve_customer, mock_storage_root):
        """Test CustomerNotFoundError when batch cannot resolve to customer."""
        mock_resolve_customer.return_value = None

        with pytest.raises(CustomerNotFoundError) as exc_info:
            derive_awb_address_authority("INVALID_BATCH", mock_storage_root)

        assert "No customer resolvable from batch_id='INVALID_BATCH'" in str(exc_info.value)

    @patch('app.services.customer_master.resolve_delivery_address')
    @patch('app.services.carrier.doc_package._resolve_customer_from_batch')
    def test_address_missing_error(self, mock_resolve_customer, mock_resolve_addr,
                                 mock_incomplete_customer, mock_storage_root):
        """Test AddressMissingError when customer has incomplete address."""
        mock_resolve_customer.return_value = mock_incomplete_customer
        mock_resolve_addr.return_value = {
            "name": "Incomplete Customer",
            "street": "",  # Missing required field
            "city": "",    # Missing required field
            "country": "",
            "source": "ship_to",
        }

        with pytest.raises(AddressMissingError) as exc_info:
            derive_awb_address_authority("BATCH_INCOMPLETE", mock_storage_root)

        error_msg = str(exc_info.value)
        assert "Missing required address fields" in error_msg
        assert "street" in error_msg
        assert "city" in error_msg


class TestFallbackMechanism:
    """Test the graceful degradation with fallback."""

    @patch('app.services.awb_address_authority.derive_awb_address_authority')
    def test_fallback_for_historical_batch(self, mock_derive, mock_storage_root):
        """Test raw fallback is used for historical batches."""
        mock_derive.side_effect = CustomerNotFoundError("Customer not found")

        raw_fallback = {
            "name": "Legacy Customer",
            "street": "Old Street 1",
            "city": "Legacy City",
            "country": "Poland"
        }

        # Use a historical batch format
        historical_batch = "SHIPMENT_1234567890_2025-01_abcd1234"

        result = derive_awb_address_authority_with_fallback(
            historical_batch, mock_storage_root, raw_fallback
        )

        assert result["name"] == "Legacy Customer"
        assert result["source"] == "raw_fallback_historical"

    @patch('app.services.awb_address_authority.derive_awb_address_authority')
    def test_no_fallback_for_recent_batch(self, mock_derive, mock_storage_root):
        """Test that recent batches don't get raw fallback."""
        mock_derive.side_effect = CustomerNotFoundError("Customer not found")

        raw_fallback = {
            "name": "Should Not Be Used",
            "street": "Should Not Be Used",
            "city": "Should Not Be Used",
            "country": "Poland"
        }

        # Use a recent batch format
        recent_batch = "AWB_1234567890"

        with pytest.raises(CustomerNotFoundError):
            derive_awb_address_authority_with_fallback(
                recent_batch, mock_storage_root, raw_fallback
            )

    @patch('app.services.awb_address_authority.derive_awb_address_authority')
    def test_fallback_with_incomplete_raw_address(self, mock_derive, mock_storage_root):
        """Test that incomplete fallback address raises error."""
        mock_derive.side_effect = CustomerNotFoundError("Customer not found")

        incomplete_fallback = {
            "name": "Incomplete",
            # Missing street, city, country
        }

        historical_batch = "SHIPMENT_1234567890_2025-01_abcd1234"

        with pytest.raises(AddressMissingError) as exc_info:
            derive_awb_address_authority_with_fallback(
                historical_batch, mock_storage_root, incomplete_fallback
            )

        error_msg = str(exc_info.value)
        assert "raw fallback is incomplete" in error_msg
        assert "street" in error_msg
        assert "city" in error_msg
        assert "country" in error_msg


class TestIdempotencyKeyPreservation:
    """Test that idempotency key generation is not affected by address changes."""

    def test_idempotency_key_excludes_address(self):
        """Verify that idempotency key calculation doesn't include address fields."""
        from app.services.carrier.models.shipment import ShipmentRequest, compute_idempotency_key

        # Create two identical requests with different addresses
        request1 = ShipmentRequest(
            batch_id="TEST_BATCH",
            shipper_account="ACC123",
            recipient_address={"name": "Customer A", "city": "Warsaw"},
            declared_value=100.0,
            currency="USD",
            weight_kg=1.0,
            dimensions={"length": 10, "width": 10, "height": 10},
            special_instructions="Handle with care"
        )

        request2 = ShipmentRequest(
            batch_id="TEST_BATCH",
            shipper_account="ACC123",
            recipient_address={"name": "Customer B", "city": "Krakow"},  # Different address
            declared_value=100.0,
            currency="USD",
            weight_kg=1.0,
            dimensions={"length": 10, "width": 10, "height": 10},
            special_instructions="Handle with care"
        )

        # Keys should be identical despite different addresses
        key1 = compute_idempotency_key(request1)
        key2 = compute_idempotency_key(request2)
        assert key1 == key2


class TestAuthorityParity:
    """Test that authority derivation matches doc_package behavior."""

    @patch('app.services.carrier.doc_package._resolve_customer_from_batch')
    def test_authority_parity_with_doc_package(self, mock_resolve_customer,
                                             mock_customer_with_ship_to, mock_storage_root):
        """Test that AWB authority uses the same customer resolution and address derivation as doc_package."""
        mock_resolve_customer.return_value = mock_customer_with_ship_to

        # Get AWB authority result (this will use the real resolve_delivery_address function)
        awb_result = derive_awb_address_authority("TEST_BATCH", mock_storage_root)

        # Now call resolve_delivery_address directly with the same customer to verify parity
        from app.services.customer_master import resolve_delivery_address
        doc_result = resolve_delivery_address(mock_customer_with_ship_to)

        # Both should produce identical results since they use the same underlying logic
        assert awb_result == doc_result

        # Verify that the customer resolution was called with expected parameters
        mock_resolve_customer.assert_called_once_with("TEST_BATCH", client_name=None, storage_root=mock_storage_root)

        # Verify the result has the expected structure
        assert "name" in awb_result
        assert "source" in awb_result