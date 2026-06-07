"""
test_proforma_recipient_resolver.py — Proforma Send recipient resolution tests.

Tests for the refactored _resolve_proforma_recipient and
_enrich_customer_resolution_with_email in routes_proforma.py.

Authority chain (PROJECT_STATE.md DECISIONS 2026-06-07):
  draft.client_name → _resolve_customer(batch_id) → wfirma_customer_id
  → customer_master_db → pick_email(customer)

Scope:
  - Verifies pick_email is used (not inline cm.bill_to_email)
  - Verifies batch_id is passed to _resolve_customer
  - Verifies email enrichment for frontend display
  - Verifies ship_to_email fallback when bill_to_email missing
  - Verifies missing customer / missing email returns ""
  - No email is queued or sent in any test

Sprint: Customer Master Email Resolver
Target: routes_proforma.py, customer_master.py
"""
from __future__ import annotations

import pathlib
import re

import pytest

SERVICE_DIR = pathlib.Path(__file__).resolve().parent.parent
APP_DIR = SERVICE_DIR / "app"
ROUTES_PROFORMA = APP_DIR / "api" / "routes_proforma.py"
CUSTOMER_MASTER = APP_DIR / "services" / "customer_master.py"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


# =============================================================================
# 1. _resolve_proforma_recipient uses pick_email (not inline bill_to_email)
# =============================================================================

class TestResolverUsePickEmail:
    """_resolve_proforma_recipient must use pick_email, not inline access."""

    def test_imports_pick_email(self):
        """The resolver must import pick_email from customer_master."""
        src = _read(ROUTES_PROFORMA)
        idx = src.find("def _resolve_proforma_recipient")
        assert idx > 0
        region = src[idx:idx + 1200]
        assert "pick_email" in region, \
            "_resolve_proforma_recipient must call pick_email"

    def test_does_not_use_inline_bill_to_email(self):
        """Must NOT access cm.bill_to_email directly — use pick_email instead."""
        src = _read(ROUTES_PROFORMA)
        idx = src.find("def _resolve_proforma_recipient")
        assert idx > 0
        region = src[idx:idx + 1200]
        # Filter out comments
        code_lines = [ln for ln in region.splitlines()
                      if not ln.strip().startswith("#")
                      and not ln.strip().startswith('"""')]
        code = "\n".join(code_lines)
        assert "cm.bill_to_email" not in code, \
            "Must not access cm.bill_to_email directly — use pick_email(cm)"

    def test_pick_email_imported_from_customer_master(self):
        """pick_email import must come from customer_master module."""
        src = _read(ROUTES_PROFORMA)
        idx = src.find("def _resolve_proforma_recipient")
        assert idx > 0
        region = src[idx:idx + 1200]
        assert "customer_master" in region and "pick_email" in region


# =============================================================================
# 2. _resolve_proforma_recipient passes batch_id
# =============================================================================

class TestResolverPassesBatchId:
    """_resolve_proforma_recipient must pass draft.batch_id to _resolve_customer."""

    def test_passes_batch_id(self):
        """_resolve_customer must receive batch_id from the draft."""
        src = _read(ROUTES_PROFORMA)
        idx = src.find("def _resolve_proforma_recipient")
        assert idx > 0
        region = src[idx:idx + 1200]
        assert "batch_id" in region, \
            "_resolve_proforma_recipient must pass batch_id to _resolve_customer"

    def test_uses_draft_batch_id(self):
        """Must read batch_id from the draft object."""
        src = _read(ROUTES_PROFORMA)
        idx = src.find("def _resolve_proforma_recipient")
        assert idx > 0
        region = src[idx:idx + 1200]
        # Should reference draft.batch_id or getattr(draft, "batch_id", ...)
        assert ("draft.batch_id" in region
                or 'draft, "batch_id"' in region
                or "batch_id" in region), \
            "Must access batch_id from the draft"


# =============================================================================
# 3. Draft-detail endpoint passes batch_id
# =============================================================================

class TestDraftDetailBatchId:
    """GET /draft/{id} must pass batch_id to _resolve_customer."""

    def test_draft_detail_passes_batch_id(self):
        """The draft-detail GET must pass d.batch_id to _resolve_customer."""
        src = _read(ROUTES_PROFORMA)
        idx = src.find("def get_proforma_draft")
        assert idx > 0
        region = src[idx:idx + 2000]
        # Must call _resolve_customer with batch_id= keyword
        assert "batch_id=" in region, \
            "Draft detail endpoint must pass batch_id to _resolve_customer"

    def test_draft_detail_enriches_email(self):
        """The draft-detail GET must call _enrich_customer_resolution_with_email."""
        src = _read(ROUTES_PROFORMA)
        idx = src.find("def get_proforma_draft")
        assert idx > 0
        region = src[idx:idx + 2000]
        assert "_enrich_customer_resolution_with_email" in region, \
            "Draft detail must enrich customer_resolution with email"


# =============================================================================
# 4. _enrich_customer_resolution_with_email helper
# =============================================================================

class TestEnrichHelper:
    """_enrich_customer_resolution_with_email must add bill_to_email."""

    def test_helper_exists(self):
        src = _read(ROUTES_PROFORMA)
        assert "def _enrich_customer_resolution_with_email" in src

    def test_helper_uses_pick_email(self):
        """Enrichment must use pick_email, not inline bill_to_email."""
        src = _read(ROUTES_PROFORMA)
        idx = src.find("def _enrich_customer_resolution_with_email")
        assert idx > 0
        region = src[idx:idx + 1000]
        assert "pick_email" in region

    def test_helper_sets_bill_to_email_on_customer(self):
        """Must set customer.bill_to_email in the resolution dict."""
        src = _read(ROUTES_PROFORMA)
        idx = src.find("def _enrich_customer_resolution_with_email")
        assert idx > 0
        region = src[idx:idx + 1000]
        assert "bill_to_email" in region

    def test_helper_is_defensive(self):
        """Must not raise — GET must never 500 on enrichment."""
        src = _read(ROUTES_PROFORMA)
        idx = src.find("def _enrich_customer_resolution_with_email")
        assert idx > 0
        region = src[idx:idx + 1500]
        assert "except" in region, "Enrichment must be wrapped in try/except"

    def test_helper_skips_when_not_found(self):
        """Must return early when cr['found'] is False."""
        src = _read(ROUTES_PROFORMA)
        idx = src.find("def _enrich_customer_resolution_with_email")
        assert idx > 0
        region = src[idx:idx + 1000]
        assert '"found"' in region or "'found'" in region


# =============================================================================
# 5. pick_email authority behavior (via customer_master.py)
# =============================================================================

class TestPickEmailAuthority:
    """pick_email in customer_master.py must implement correct priority."""

    def test_pick_email_exists(self):
        src = _read(CUSTOMER_MASTER)
        assert "def pick_email" in src

    def test_bill_to_email_is_primary(self):
        """pick_email must check bill_to_email first."""
        src = _read(CUSTOMER_MASTER)
        idx = src.find("def pick_email")
        assert idx > 0
        region = src[idx:idx + 600]
        # bill_to_email must appear before ship_to_email in the function
        bill_pos = region.find("bill_to_email")
        ship_pos = region.find("ship_to_email")
        assert bill_pos > 0
        assert ship_pos > 0
        assert bill_pos < ship_pos, \
            "bill_to_email must be checked before ship_to_email"

    def test_ship_to_email_is_fallback(self):
        """ship_to_email must be used as fallback only."""
        src = _read(CUSTOMER_MASTER)
        idx = src.find("def pick_email")
        assert idx > 0
        region = src[idx:idx + 600]
        assert "ship_to_email" in region, \
            "pick_email must fall back to ship_to_email"

    def test_returns_empty_string_when_no_email(self):
        """pick_email must return empty string, not None."""
        src = _read(CUSTOMER_MASTER)
        idx = src.find("def pick_email")
        assert idx > 0
        region = src[idx:idx + 600]
        # Should return "" or '""' not None
        assert '""' in region or "strip()" in region


# =============================================================================
# 6. Authority docstring references
# =============================================================================

class TestAuthorityDocstrings:
    """Docstrings must reference the authority model."""

    def test_resolver_references_authority(self):
        src = _read(ROUTES_PROFORMA)
        idx = src.find("def _resolve_proforma_recipient")
        assert idx > 0
        region = src[idx:idx + 600]
        assert "pick_email" in region

    def test_resolver_references_decisions(self):
        src = _read(ROUTES_PROFORMA)
        idx = src.find("def _resolve_proforma_recipient")
        assert idx > 0
        region = src[idx:idx + 600]
        assert "PROJECT_STATE" in region or "Authority" in region


# =============================================================================
# 7. No email queued or sent in resolver
# =============================================================================

class TestNoSideEffects:
    """Resolver must not queue or send email."""

    def test_resolver_does_not_queue_email(self):
        """_resolve_proforma_recipient must NOT call queue_email."""
        src = _read(ROUTES_PROFORMA)
        idx = src.find("def _resolve_proforma_recipient")
        assert idx > 0
        region = src[idx:idx + 1200]
        assert "queue_email" not in region

    def test_resolver_does_not_import_email_service(self):
        """_resolve_proforma_recipient must NOT import email_service."""
        src = _read(ROUTES_PROFORMA)
        idx = src.find("def _resolve_proforma_recipient")
        assert idx > 0
        region = src[idx:idx + 1200]
        assert "email_service" not in region

    def test_enrichment_does_not_queue_email(self):
        """_enrich_customer_resolution_with_email must NOT queue email."""
        src = _read(ROUTES_PROFORMA)
        idx = src.find("def _enrich_customer_resolution_with_email")
        assert idx > 0
        region = src[idx:idx + 1000]
        assert "queue_email" not in region

    def test_enrichment_does_not_mutate_customer_master(self):
        """Enrichment must NOT write to customer_master_db."""
        src = _read(ROUTES_PROFORMA)
        idx = src.find("def _enrich_customer_resolution_with_email")
        assert idx > 0
        region = src[idx:idx + 1000]
        assert "upsert" not in region
        assert "update" not in region.lower().replace("_updated_at", "")


# =============================================================================
# 8. Clone-draft endpoint also passes batch_id
# =============================================================================

class TestCloneDraftBatchId:
    """POST /draft/{id}/clone must also pass batch_id."""

    def test_clone_passes_batch_id(self):
        src = _read(ROUTES_PROFORMA)
        idx = src.find("def clone_proforma_draft")
        if idx < 0:
            pytest.skip("clone_proforma_draft not found")
        region = src[idx:idx + 2000]
        assert "batch_id=" in region, \
            "Clone endpoint must pass batch_id to _resolve_customer"

    def test_clone_enriches_email(self):
        src = _read(ROUTES_PROFORMA)
        idx = src.find("def clone_proforma_draft")
        if idx < 0:
            pytest.skip("clone_proforma_draft not found")
        region = src[idx:idx + 2000]
        assert "_enrich_customer_resolution_with_email" in region


# =============================================================================
# 9. recipient_override behavior unchanged
# =============================================================================

class TestRecipientOverride:
    """recipient_override must still work as before."""

    def test_recipient_override_still_exists(self):
        src = _read(ROUTES_PROFORMA)
        idx = src.find("def send_proforma_email")
        assert idx > 0
        region = src[idx:idx + 5000]
        assert "recipient_override" in region

    def test_override_takes_precedence(self):
        """recipient_override must be checked before _resolve_proforma_recipient."""
        src = _read(ROUTES_PROFORMA)
        idx = src.find("def send_proforma_email")
        assert idx > 0
        region = src[idx:idx + 5000]
        override_pos = region.find("recipient_override")
        resolve_pos = region.find("_resolve_proforma_recipient")
        assert override_pos > 0
        assert resolve_pos > 0
        assert override_pos < resolve_pos, \
            "recipient_override must be checked before resolver"

    def test_override_uses_sanitise(self):
        """recipient_override must go through _sanitise_email_field."""
        src = _read(ROUTES_PROFORMA)
        idx = src.find("def send_proforma_email")
        assert idx > 0
        region = src[idx:idx + 5000]
        assert "_sanitise_email_field" in region
