"""AWB Address Authority Repair — Customer Master derivation for shipment creation.

Campaign 02.5 Workstream 3 implementation. Eliminates the raw recipient_address
bypass in POST /api/v1/carrier/{batch_id}/shipment by enforcing Customer Master
authority via the established resolve_delivery_address() pattern.

Authority rule (operator-mandated):
- Primary: Customer Master Ship-To (when ship_to_use_alternate=True and populated)
- Fallback: Customer Master Bill-To
- NO raw address bypasses permitted

This module provides pure authority derivation functions following the existing
derive_*_authority pattern, with no I/O writes in the derivation logic itself.
"""
from typing import Dict, Optional
from pathlib import Path
import re
from datetime import datetime, timedelta


class CustomerNotFoundError(Exception):
    """Customer cannot be resolved from the given batch_id."""
    pass


class AddressMissingError(Exception):
    """Customer exists but has no usable delivery address."""
    pass


def _is_historical_batch(batch_id: str, cutoff_days: int = 90) -> bool:
    """Check if a batch is older than the cutoff period (default 90 days).

    Attempts to parse date from common batch_id formats:
    - "SHIPMENT_XXXXXXXXXX_YYYY-MM_hash" → extract YYYY-MM
    - Other formats treated as recent (require authority resolution)

    Args:
        batch_id: The batch identifier
        cutoff_days: Days before today to consider "historical"

    Returns:
        True if batch appears to be older than cutoff_days, False otherwise
    """
    # Try to extract date from SHIPMENT_XXXXXXXXXX_YYYY-MM_hash format
    match = re.match(r'SHIPMENT_\d+_(\d{4})-(\d{2})_[a-f0-9]+$', batch_id)
    if match:
        year, month = int(match.group(1)), int(match.group(2))
        try:
            # Use first day of the month as batch date approximation
            batch_date = datetime(year, month, 1)
            cutoff_date = datetime.now() - timedelta(days=cutoff_days)
            return batch_date < cutoff_date
        except ValueError:
            # Invalid date, treat as recent
            return False

    # For AWB_XXXXXXXXXX and other formats, treat as recent
    # (requiring authority resolution)
    return False


def derive_awb_address_authority(batch_id: str, storage_root: Path) -> Dict[str, str]:
    """Derive the authoritative DHL delivery address for AWB shipment creation.

    Authority rule (operator-mandated):
    - Primary: Customer Master Ship-To (when ship_to_use_alternate=True and populated)
    - Fallback: Customer Master Bill-To
    - NO raw address bypasses permitted

    Args:
        batch_id: The batch identifier to resolve customer from
        storage_root: Storage root path for database access

    Returns:
        Dict with address fields suitable for DHL API + 'source' metadata

    Raises:
        CustomerNotFoundError: No customer resolvable from batch_id
        AddressMissingError: Customer found but neither ship-to nor bill-to address available
    """
    # Use the existing customer resolution pattern from doc_package.py
    from .carrier.doc_package import _resolve_customer_from_batch
    from .customer_master import resolve_delivery_address

    try:
        customer = _resolve_customer_from_batch(batch_id, client_name=None, storage_root=storage_root)
    except Exception as exc:
        raise CustomerNotFoundError(f"Customer resolution failed for batch_id={batch_id!r}: {exc}") from exc

    if customer is None:
        raise CustomerNotFoundError(f"No customer resolvable from batch_id={batch_id!r}")

    # Get the authoritative delivery address
    address = resolve_delivery_address(customer)

    # Validate minimum required fields for DHL shipment creation
    required_fields = ['name', 'street', 'city', 'country']
    missing = [f for f in required_fields if not address.get(f, '').strip()]

    if missing:
        source = address.get('source', 'unknown')
        raise AddressMissingError(
            f"Missing required address fields: {missing}. "
            f"Customer authority source: {source}. "
            f"Please ensure customer master record has complete delivery address."
        )

    return address


def derive_awb_address_authority_with_fallback(
    batch_id: str,
    storage_root: Path,
    raw_fallback: Optional[Dict] = None
) -> Dict[str, str]:
    """Derive AWB address authority with graceful degradation to raw fallback.

    Used for historical batch support (>90 days) when Customer Master resolution
    fails but operator needs to process legacy shipments.

    Args:
        batch_id: The batch identifier to resolve customer from
        storage_root: Storage root path for database access
        raw_fallback: Raw address dict to use if authority derivation fails

    Returns:
        Dict with address fields + 'source' metadata indicating authority path used

    Raises:
        AddressMissingError: Both authority derivation and raw fallback inadequate
    """
    try:
        return derive_awb_address_authority(batch_id, storage_root)
    except CustomerNotFoundError as exc:
        # Graceful degradation: use raw fallback only for historical batches
        if raw_fallback is not None and _is_historical_batch(batch_id):
            # Validate minimum required fields in raw fallback
            required_fields = ['name', 'street', 'city', 'country']
            missing = [f for f in required_fields if not raw_fallback.get(f, '').strip()]

            if missing:
                raise AddressMissingError(
                    f"Historical batch authority derivation failed and raw fallback is incomplete. "
                    f"Missing required fields in fallback: {missing}. "
                    f"Batch: {batch_id}, Original error: {exc}"
                )

            # Add source metadata to indicate fallback path
            result = dict(raw_fallback)
            result['source'] = 'raw_fallback_historical'

            # Log fallback usage for audit trail
            import logging
            logging.warning(
                f"AWB address authority: Using raw fallback for historical batch {batch_id}. "
                f"Customer Master resolution failed: {exc}"
            )
            return result

        # For recent batches, re-raise the customer resolution error
        raise


__all__ = [
    'CustomerNotFoundError',
    'AddressMissingError',
    'derive_awb_address_authority',
    'derive_awb_address_authority_with_fallback',
]