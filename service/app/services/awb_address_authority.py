"""AWB Address Authority Repair — Customer Master derivation for shipment creation.

Campaign 02.5 Workstream 3 implementation. Eliminates the raw recipient_address
bypass in POST /api/v1/carrier/{batch_id}/shipment by enforcing Customer Master
authority via the established resolve_delivery_address() pattern.

Authority rule (operator-mandated):
- Primary: Customer Master Ship-To (when ship_to_use_alternate=True and populated)
- Fallback: Customer Master Bill-To
- NO raw address bypasses permitted — there is no operator-typed, date-based or
  environment-flag path back to an unvalidated address. Unresolvable or
  ambiguous customer fails closed.

This module provides pure authority derivation functions following the existing
derive_*_authority pattern, with no I/O writes in the derivation logic itself.
"""
from typing import Dict, Optional
from pathlib import Path


class CustomerNotFoundError(Exception):
    """Customer cannot be resolved from the given batch_id."""
    pass


class AddressMissingError(Exception):
    """Customer exists but has no usable delivery address."""
    pass


def derive_awb_address_authority(
    batch_id: str,
    storage_root: Path,
    client_ref: Optional[str] = None,
) -> Dict[str, str]:
    """Derive the authoritative DHL delivery address for AWB shipment creation.

    Authority rule (operator-mandated):
    - Primary: Customer Master Ship-To (when ship_to_use_alternate=True and populated)
    - Fallback: Customer Master Bill-To
    - NO raw address bypasses permitted

    *client_ref* is the outbound commercial scope (the proforma draft's client
    name).  An import batch may carry several commercial customers, so the
    booking must resolve through the client's own document rather than a
    batch-level guess; without it an ambiguous batch fails closed as before.

    Args:
        batch_id: The batch identifier to resolve customer from
        storage_root: Storage root path for database access
        client_ref: Outbound commercial client scope (proforma draft client_name)

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
        customer = _resolve_customer_from_batch(
            batch_id,
            client_name=(client_ref or "").strip() or None,
            storage_root=storage_root,
        )
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


__all__ = [
    'CustomerNotFoundError',
    'AddressMissingError',
    'derive_awb_address_authority',
]