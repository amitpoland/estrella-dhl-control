"""Tests for AWB Address Authority Repair (Campaign 02.5 Workstream 3).

Tests the new Customer Master authority derivation for shipment creation,
including feature flag behavior, error handling, and fallback mechanisms.

Also includes tests for the AWB resolution audit script (Condition 1 implementation).
"""
from __future__ import annotations

import json
import os
import time
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

# Import audit script functions for testing
from service.scripts.awb_resolution_audit import get_recent_batch_ids, run_audit


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


# ── AWB Resolution Audit Script Tests (Condition 1) ─────────────────────────────

class TestGetRecentBatchIds:
    """Test the batch discovery function."""

    def test_empty_storage_returns_empty_list(self, tmp_path):
        """Test that empty storage returns empty list."""
        storage_root = tmp_path / "storage"
        storage_root.mkdir()
        outputs_dir = storage_root / "outputs"
        outputs_dir.mkdir()

        result = get_recent_batch_ids(storage_root, days=30)
        assert result == []

    def test_missing_outputs_directory_returns_empty_list(self, tmp_path):
        """Test that missing outputs directory returns empty list."""
        storage_root = tmp_path / "storage"
        storage_root.mkdir()

        result = get_recent_batch_ids(storage_root, days=30)
        assert result == []

    def test_finds_recent_shipment_batches(self, tmp_path):
        """Test that recent SHIPMENT_ batches are found."""
        storage_root = tmp_path / "storage"
        outputs_dir = storage_root / "outputs"
        outputs_dir.mkdir(parents=True)

        # Create recent batch
        recent_batch = outputs_dir / "SHIPMENT_1234567890_2026-06_abcd1234"
        recent_batch.mkdir()
        audit_file = recent_batch / "audit.json"
        audit_file.write_text('{"batch_id": "SHIPMENT_1234567890_2026-06_abcd1234"}')

        # Create old batch (modify timestamp to be older than 30 days)
        old_batch = outputs_dir / "SHIPMENT_9876543210_2026-01_efgh5678"
        old_batch.mkdir()
        old_audit_file = old_batch / "audit.json"
        old_audit_file.write_text('{"batch_id": "SHIPMENT_9876543210_2026-01_efgh5678"}')

        # Set the old batch timestamp to be older than 30 days
        old_time = time.time() - (35 * 24 * 3600)  # 35 days ago
        os.utime(old_audit_file, (old_time, old_time))

        result = get_recent_batch_ids(storage_root, days=30)

        assert len(result) == 1
        assert "SHIPMENT_1234567890_2026-06_abcd1234" in result
        assert "SHIPMENT_9876543210_2026-01_efgh5678" not in result

    def test_finds_recent_awb_batches(self, tmp_path):
        """Test that recent AWB_ batches are found."""
        storage_root = tmp_path / "storage"
        outputs_dir = storage_root / "outputs"
        outputs_dir.mkdir(parents=True)

        # Create recent AWB batch
        recent_batch = outputs_dir / "AWB_1234567890"
        recent_batch.mkdir()
        audit_file = recent_batch / "audit.json"
        audit_file.write_text('{"awb": "1234567890"}')

        result = get_recent_batch_ids(storage_root, days=30)

        assert len(result) == 1
        assert "AWB_1234567890" in result

    def test_ignores_test_and_quarantine_directories(self, tmp_path):
        """Test that test and quarantine directories are ignored."""
        storage_root = tmp_path / "storage"
        outputs_dir = storage_root / "outputs"
        outputs_dir.mkdir(parents=True)

        # Create various directory types
        (outputs_dir / "SHIPMENT_1234567890_2026-06_abcd1234").mkdir()
        (outputs_dir / "SHIPMENT_1234567890_2026-06_abcd1234" / "audit.json").write_text("{}")

        (outputs_dir / "B_TEST_BATCH").mkdir()
        (outputs_dir / "B_TEST_BATCH" / "audit.json").write_text("{}")

        (outputs_dir / "TEST_SOMETHING").mkdir()
        (outputs_dir / "TEST_SOMETHING" / "audit.json").write_text("{}")

        (outputs_dir / "quarantine_old_batch").mkdir()
        (outputs_dir / "quarantine_old_batch" / "audit.json").write_text("{}")

        (outputs_dir / "some_random_dir").mkdir()
        (outputs_dir / "some_random_dir" / "audit.json").write_text("{}")

        result = get_recent_batch_ids(storage_root, days=30)

        # Should only find the SHIPMENT_ batch, ignoring test/quarantine/anomalous directories
        assert len(result) == 1
        assert "SHIPMENT_1234567890_2026-06_abcd1234" in result

    def test_uses_directory_mtime_when_audit_missing(self, tmp_path):
        """Test that directory mtime is used when audit.json is missing."""
        storage_root = tmp_path / "storage"
        outputs_dir = storage_root / "outputs"
        outputs_dir.mkdir(parents=True)

        # Create batch without audit.json
        recent_batch = outputs_dir / "SHIPMENT_1234567890_2026-06_abcd1234"
        recent_batch.mkdir()
        # No audit.json file

        result = get_recent_batch_ids(storage_root, days=30)

        assert len(result) == 1
        assert "SHIPMENT_1234567890_2026-06_abcd1234" in result

    def test_respects_days_parameter(self, tmp_path):
        """Test that the days parameter correctly filters results."""
        storage_root = tmp_path / "storage"
        outputs_dir = storage_root / "outputs"
        outputs_dir.mkdir(parents=True)

        # Create recent batch (within 7 days)
        recent_batch = outputs_dir / "SHIPMENT_1234567890_2026-06_recent"
        recent_batch.mkdir()
        recent_audit = recent_batch / "audit.json"
        recent_audit.write_text("{}")

        # Create medium-old batch (within 30 days but older than 7 days)
        medium_batch = outputs_dir / "SHIPMENT_9876543210_2026-06_medium"
        medium_batch.mkdir()
        medium_audit = medium_batch / "audit.json"
        medium_audit.write_text("{}")

        # Set medium batch to be 15 days old
        medium_time = time.time() - (15 * 24 * 3600)
        os.utime(medium_audit, (medium_time, medium_time))

        # Test with days=30 (should find both)
        result_30 = get_recent_batch_ids(storage_root, days=30)
        assert len(result_30) == 2

        # Test with days=7 (should find only recent)
        result_7 = get_recent_batch_ids(storage_root, days=7)
        assert len(result_7) == 1
        assert "SHIPMENT_1234567890_2026-06_recent" in result_7

    def test_returns_sorted_results(self, tmp_path):
        """Test that results are returned sorted."""
        storage_root = tmp_path / "storage"
        outputs_dir = storage_root / "outputs"
        outputs_dir.mkdir(parents=True)

        # Create batches in non-alphabetical order
        for batch_id in ["SHIPMENT_333_2026-06_c", "SHIPMENT_111_2026-06_a", "SHIPMENT_222_2026-06_b"]:
            batch_dir = outputs_dir / batch_id
            batch_dir.mkdir()
            (batch_dir / "audit.json").write_text("{}")

        result = get_recent_batch_ids(storage_root, days=30)

        assert result == sorted(result)
        assert len(result) == 3


class TestRunAudit:
    """Test the run_audit function."""

    @patch('service.scripts.awb_resolution_audit.test_batch_resolution')
    def test_no_batches_returns_error_code(self, mock_test_batch, tmp_path):
        """Test that no batches found returns error code 2."""
        storage_root = tmp_path / "storage"
        outputs_dir = storage_root / "outputs"
        outputs_dir.mkdir(parents=True)

        result = run_audit(storage_root, days=30)

        assert result == 2
        mock_test_batch.assert_not_called()

    @patch('service.scripts.awb_resolution_audit.test_batch_resolution')
    def test_success_rate_above_threshold_returns_success(self, mock_test_batch, tmp_path):
        """Test that success rate >= 95% returns success code 0."""
        storage_root = tmp_path / "storage"
        outputs_dir = storage_root / "outputs"
        outputs_dir.mkdir(parents=True)

        # Create test batches
        for i in range(20):
            batch_dir = outputs_dir / f"SHIPMENT_{i:010d}_2026-06_test{i}"
            batch_dir.mkdir()
            (batch_dir / "audit.json").write_text("{}")

        # Mock 19 successes out of 20 (95% success rate)
        def mock_resolution(batch_id, storage_root):
            if "19" in batch_id:  # Make the last one fail
                return False, "Test failure"
            return True, "Success"

        mock_test_batch.side_effect = mock_resolution

        result = run_audit(storage_root, days=30)

        assert result == 0
        assert mock_test_batch.call_count == 20

    @patch('service.scripts.awb_resolution_audit.test_batch_resolution')
    def test_success_rate_below_threshold_returns_failure(self, mock_test_batch, tmp_path):
        """Test that success rate < 95% returns failure code 1."""
        storage_root = tmp_path / "storage"
        outputs_dir = storage_root / "outputs"
        outputs_dir.mkdir(parents=True)

        # Create test batches
        for i in range(10):
            batch_dir = outputs_dir / f"SHIPMENT_{i:010d}_2026-06_test{i}"
            batch_dir.mkdir()
            (batch_dir / "audit.json").write_text("{}")

        # Mock 8 successes out of 10 (80% success rate - below threshold)
        def mock_resolution(batch_id, storage_root):
            if "8" in batch_id or "9" in batch_id:  # Make 2 fail
                return False, "Test failure"
            return True, "Success"

        mock_test_batch.side_effect = mock_resolution

        result = run_audit(storage_root, days=30)

        assert result == 1
        assert mock_test_batch.call_count == 10

    @patch('service.scripts.awb_resolution_audit.get_recent_batch_ids')
    def test_exception_during_audit_returns_error_code(self, mock_get_batches, tmp_path):
        """Test that exceptions during audit return error code 2."""
        storage_root = tmp_path / "storage"

        mock_get_batches.side_effect = RuntimeError("Test error")

        result = run_audit(storage_root, days=30)

        assert result == 2