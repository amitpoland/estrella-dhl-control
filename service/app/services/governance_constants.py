"""
governance_constants.py — Single source of truth for autonomy boundaries.

WHY THIS EXISTS
    Multiple modules across the service independently decide what can run
    without human approval.  Scattering those decisions creates drift:
    a future developer adding a new action doesn't know to check three
    different files.  This module owns the classification once.

TWO SETS, ONE SOURCE
    SAFE_AUTONOMOUS_ACTIONS
        Actions the service may execute without any human approval.
        Criteria: read-only OR idempotent write with no financial/legal side
        effect, reversible, non-accounting.

    HUMAN_APPROVAL_REQUIRED_ACTIONS
        Actions that must NEVER run from a background worker, scheduler,
        webhook handler, retry queue, or any automatic path.  A live
        operator must explicitly confirm (X-Operator header, confirm token,
        or equivalent gate) before the system executes these.

RULES
    1.  Every new action introduced to the system MUST be classified in
        exactly one of the two sets before the PR is opened (GATE 1).
    2.  These sets are frozen at import time. Do not mutate them at runtime.
    3.  If an action moves from SAFE → HUMAN_REQUIRED: add it to
        HUMAN_APPROVAL_REQUIRED_ACTIONS and remove from SAFE_AUTONOMOUS_ACTIONS.
        The inverse (HUMAN_REQUIRED → SAFE) requires explicit operator sign-off
        documented in an ADR before the PR can merge.
    4.  This file contains no I/O, no HTTP, no DB.  Import it anywhere safely.

INVOICE ISSUANCE INVARIANT (permanent)
    Invoice issuance MUST NEVER run:
    - From a background worker
    - From a scheduler or cron
    - From a webhook handler
    - From a retry queue
    - Automatically for any reason
    This invariant is enforced by the HUMAN_APPROVAL_REQUIRED_ACTIONS set
    and by INVOICE_APPROVAL_REQUIRED sentinel in routes_proforma.py.
"""
from __future__ import annotations

# ── Safe Autonomous Actions ───────────────────────────────────────────────────
# Every action here is: read-only OR idempotent non-accounting write.
# Safe to run from background task, startup hook, or polling loop.

SAFE_AUTONOMOUS_ACTIONS: frozenset[str] = frozenset({
    # Product catalog — search-first, read-only wFirma probe
    "product.fetch_from_wfirma",            # GET goods/get
    "product.search_in_wfirma",             # GET goods/find
    "product.sync_local_mapping",           # wfirma_products upsert (no wFirma write)
    "product.auto_register_dry_run",        # ensure_products_for_batch(dry_run=True)
    "product.mirror_to_reservation_db",     # reservation_queue mirror (non-fatal)

    # Customer / contractor — search-first, read-only wFirma probe
    "customer.search_in_wfirma",            # GET contractors/find
    "customer.sync_local_mapping",          # wfirma_customers upsert
    "customer.auto_resolve",                # wfirma_customer_auto_resolve

    # Series catalog — read-only wFirma fetch, in-memory cache update only
    "series.refresh_from_wfirma",           # wfirma_dictionary_cache.refresh_from_wfirma()
    "series.get_cached_catalog",            # wfirma_dictionary_cache.get_dictionaries()

    # Proforma — create, preview, draft (never final invoice)
    "proforma.preview",                     # _build_preview — no wFirma write
    "proforma.create_in_wfirma",            # invoices/proforma/add (proforma ONLY)
    "proforma.reservation_create",          # wfirma_reservation.create_reservation
    "proforma.warehouse_sync",              # wfirma_reservation warehouse dispatch

    # Service charge management — operator-entered amounts, not accounting
    "service_charge.upsert",                # proforma_service_charges_db.upsert_charge
    "service_charge.delete",                # proforma_service_charges_db.delete_charge
    "service_charge.list",                  # proforma_service_charges_db.list_charges

    # Warehouse — scan, audit, state transitions (not accounting)
    "warehouse.scan_in",
    "warehouse.audit_check",
    "warehouse.product_create",             # wFirma warehouse product create (safe)

    # Tracking / monitoring — read-only
    "tracking.refresh",
    "tracking.fetch_status",
    "batch.readiness_check",
    "batch.preview_refresh",

    # DHL / customs — document intake and classification (no send)
    "dhl.document_classify",
    "dhl.customs_parse",
    "dhl.zc429_intake",
    "dhl.track_awb",
})


# ── Human Approval Required Actions ──────────────────────────────────────────
# Every action here MUST have an explicit human operator gate before execution.
# The gate = at minimum: env flag check + X-Operator header + confirm token.
# NEVER run these from: worker, scheduler, webhook, retry queue, or any
# automatic path.

HUMAN_APPROVAL_REQUIRED_ACTIONS: frozenset[str] = frozenset({
    # ── INVOICE ISSUANCE (PERMANENT INVARIANT) ────────────────────────────
    # Invoice issuance is ALWAYS human-approval. No exceptions. Ever.
    "invoice.create_final_invoice",         # invoices/add (WDT / final invoice)
    "invoice.convert_proforma_to_invoice",  # proforma_to_invoice conversion
    "invoice.activate",                     # any invoice activation path

    # ── PZ / ACCOUNTING ───────────────────────────────────────────────────
    "pz.post_final",                        # final PZ post to wFirma
    "pz.adopt",                             # proforma adoption into PZ
    "accounting.post_journal",              # any journal posting
    "accounting.dual_write_final",          # finance_dual_write final post
    "accounting.pz_builder_submit",         # import_pz_builder submit

    # ── PRODUCT CREATE (write to wFirma) ──────────────────────────────────
    # dry_run=False product creation requires WFIRMA_CREATE_PRODUCT_ALLOWED
    # flag AND operator action. This is not a background-safe operation.
    "product.create_in_wfirma",             # goods/add (wFirma write)

    # ── CUSTOMER CREATE ───────────────────────────────────────────────────
    "customer.create_in_wfirma",            # contractors/add (wFirma write)

    # ── DOCUMENT SEND ─────────────────────────────────────────────────────
    "dhl.send_customs_email",               # DHL customs email dispatch
    "dhl.proactive_dispatch",               # P2 proactive dispatch
    "email.send_any",                       # any outbound email

    # ── IRREVERSIBLE STATE CHANGES ────────────────────────────────────────
    "shipment.close",                       # shipment closure (terminal state)
    "batch.force_close",                    # operator batch force-close
    "data.delete_audit_record",             # audit record deletion
})


# ── Validation helper (import-time, no side effects) ─────────────────────────

def assert_no_overlap() -> None:
    """Raise AssertionError if any action appears in both sets."""
    overlap = SAFE_AUTONOMOUS_ACTIONS & HUMAN_APPROVAL_REQUIRED_ACTIONS
    if overlap:
        raise AssertionError(
            f"Governance violation: actions in BOTH sets: {sorted(overlap)}"
        )


# Validate at import time — catches errors introduced during refactoring.
assert_no_overlap()


__all__ = [
    "SAFE_AUTONOMOUS_ACTIONS",
    "HUMAN_APPROVAL_REQUIRED_ACTIONS",
    "assert_no_overlap",
]
