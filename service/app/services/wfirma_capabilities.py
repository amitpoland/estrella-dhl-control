"""
wfirma_capabilities.py — wFirma integration capability checker.

Returns the current configuration state of the wFirma API integration
without making any live API calls. This is a config-only check.

A live API probe (to verify warehouse module status server-side) will be
added later once credentials are confirmed working.

Capability model
----------------
  api_configured          → wfirma_access_key + wfirma_secret_key + wfirma_app_key + wfirma_company_id set
  api_user_configured     → same as api_configured
  warehouse_module_enabled → WFIRMA_WAREHOUSE_MODULE_ENABLED=true AND warehouse_id set
  reservation_supported   → warehouse_module_enabled (reservations require expanded pkg)
  product_api_supported   → api_configured (product CRUD is base API)
  customer_api_supported  → api_configured (customer CRUD is base API)
  proforma_supported      → api_configured (pro forma is base API)
  currency_supported      → api_configured (multi-currency is base API)
  blocking_reasons        → list of human-readable gaps

ready_to_reserve = api_configured AND warehouse_module_enabled
"""
from __future__ import annotations

from typing import Any, Dict, List

from ..core.config import settings
from ..core.logging import get_logger

log = get_logger(__name__)


def get_capabilities() -> Dict[str, Any]:
    """
    Return the current wFirma capability state based on settings.

    Does NOT make any HTTP calls to wFirma.  A future
    `probe_capabilities()` function will do live verification.
    """
    api_configured = bool(
        settings.wfirma_access_key
        and settings.wfirma_secret_key
        and settings.wfirma_app_key
        and settings.wfirma_company_id
    )

    warehouse_module_enabled = bool(
        api_configured
        and settings.wfirma_warehouse_module_enabled
        and settings.wfirma_warehouse_id
    )

    reservation_supported   = warehouse_module_enabled
    product_api_supported   = api_configured
    customer_api_supported  = api_configured
    proforma_supported      = api_configured
    currency_supported      = api_configured

    blocking_reasons: List[str] = []

    if not settings.wfirma_access_key:
        blocking_reasons.append("WFIRMA_ACCESS_KEY not configured")
    if not settings.wfirma_secret_key:
        blocking_reasons.append("WFIRMA_SECRET_KEY not configured")
    if not settings.wfirma_app_key:
        blocking_reasons.append("WFIRMA_APP_KEY not configured")
    if not settings.wfirma_company_id:
        blocking_reasons.append("WFIRMA_COMPANY_ID not configured")

    if api_configured:
        if not settings.wfirma_warehouse_module_enabled:
            blocking_reasons.append(
                "WFIRMA_WAREHOUSE_MODULE_ENABLED=false — "
                "confirm expanded warehouse package is active in wFirma"
            )
        if not settings.wfirma_warehouse_id:
            blocking_reasons.append(
                "WFIRMA_WAREHOUSE_ID not set — "
                "set after identifying the warehouse in wFirma"
            )

    return {
        "api_configured":           api_configured,
        "api_user_configured":      api_configured,
        "warehouse_module_enabled": warehouse_module_enabled,
        "reservation_supported":    reservation_supported,
        "product_api_supported":    product_api_supported,
        "customer_api_supported":   customer_api_supported,
        "proforma_supported":       proforma_supported,
        "currency_supported":       currency_supported,
        "create_product_allowed":   settings.wfirma_create_product_allowed,
        "create_customer_allowed":  settings.wfirma_create_customer_allowed,
        "create_pz_allowed":        settings.wfirma_create_pz_allowed,
        "wfirma_create_pz_allowed": settings.wfirma_create_pz_allowed,
        "warehouse_id":             settings.wfirma_warehouse_id or None,
        "company_id":               settings.wfirma_company_id or None,
        "blocking_reasons":         blocking_reasons,
        "ready_to_reserve":         api_configured and warehouse_module_enabled,
    }
