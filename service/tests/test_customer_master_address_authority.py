"""
test_customer_master_address_authority.py — Customer Master address authority helpers.

Tests for pick_email, resolve_billing_address, resolve_delivery_address.

Authority model (PROJECT_STATE.md DECISIONS 2026-06-07):
  bill_to_* = invoice / billing authority
  ship_to_* = DHL delivery / shipping authority
  DHL must use ship-to first, bill-to fallback second.
  Billing must never override a separate ship-to address.
  Shape B (ship_to_contractor_id) is wFirma receiver, NOT DHL delivery.

Sprint: Customer Master Resolver Helpers
Target: customer_master.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest


def _ensure_path() -> None:
    here = Path(__file__).resolve()
    service_dir = here.parents[1]
    repo_root = here.parents[2]
    for p in (str(service_dir), str(repo_root)):
        if p not in sys.path:
            sys.path.insert(0, p)


_ensure_path()

from app.services.customer_master_db import CustomerMaster  # noqa: E402
from app.services.customer_master import (  # noqa: E402
    pick_email,
    resolve_billing_address,
    resolve_delivery_address,
    ship_to_shape,
    SHIP_TO_NONE,
    SHIP_TO_ALTERNATE_ADDRESS,
    SHIP_TO_SEPARATE_CONTRACTOR,
)


# ── Fixtures ─────────────────────────────────────────────────────────────────

def _base_customer(**overrides) -> CustomerMaster:
    """Minimal customer with required fields only."""
    defaults = dict(
        bill_to_contractor_id="99001",
        bill_to_name="Estrella Test GmbH",
        country="DE",
    )
    defaults.update(overrides)
    return CustomerMaster(**defaults)


def _billing_customer(**overrides) -> CustomerMaster:
    """Customer with full billing address."""
    defaults = dict(
        bill_to_contractor_id="99002",
        bill_to_name="Goldhaus AG",
        country="AT",
        bill_to_email="billing@goldhaus.at",
        bill_to_phone="+43 1 234 5678",
        bill_to_street="Kärntner Straße 12",
        bill_to_city="Wien",
        bill_to_postal_code="1010",
    )
    defaults.update(overrides)
    return CustomerMaster(**defaults)


def _shipto_customer(**overrides) -> CustomerMaster:
    """Customer with billing + separate ship-to address."""
    defaults = dict(
        bill_to_contractor_id="99003",
        bill_to_name="Bijoux Parisien SARL",
        country="FR",
        bill_to_email="factures@bijoux.fr",
        bill_to_phone="+33 1 44 55 66 77",
        bill_to_street="8 Rue de Rivoli",
        bill_to_city="Paris",
        bill_to_postal_code="75001",
        # Separate DHL delivery address
        ship_to_use_alternate=True,
        ship_to_name="Bijoux Entrepôt",
        ship_to_person="Jean-Pierre Dupont",
        ship_to_street="Zone Industrielle Nord, Bât 4",
        ship_to_city="Roissy-en-France",
        ship_to_zip="95700",
        ship_to_country="FR",
        ship_to_phone="+33 1 99 88 77 66",
        ship_to_email="warehouse@bijoux.fr",
    )
    defaults.update(overrides)
    return CustomerMaster(**defaults)


# =============================================================================
# 1. pick_email
# =============================================================================

class TestPickEmail:
    """pick_email returns the best available email."""

    def test_bill_to_email_is_primary(self):
        c = _billing_customer()
        assert pick_email(c) == "billing@goldhaus.at"

    def test_bill_to_email_beats_ship_to_email(self):
        """bill_to_email is primary authority even when ship_to_email exists."""
        c = _shipto_customer()
        assert pick_email(c) == "factures@bijoux.fr"
        assert c.ship_to_email == "warehouse@bijoux.fr"  # exists but not used

    def test_fallback_to_ship_to_email_when_bill_to_missing(self):
        """ship_to_email is used ONLY when bill_to_email is absent."""
        c = _shipto_customer(bill_to_email=None)
        assert pick_email(c) == "warehouse@bijoux.fr"

    def test_fallback_to_ship_to_email_when_bill_to_empty_string(self):
        c = _shipto_customer(bill_to_email="")
        assert pick_email(c) == "warehouse@bijoux.fr"

    def test_fallback_to_ship_to_email_when_bill_to_whitespace(self):
        c = _shipto_customer(bill_to_email="   ")
        assert pick_email(c) == "warehouse@bijoux.fr"

    def test_returns_empty_when_no_email_at_all(self):
        c = _base_customer()
        assert pick_email(c) == ""

    def test_returns_empty_when_both_none(self):
        c = _base_customer(bill_to_email=None, ship_to_email=None)
        assert pick_email(c) == ""

    def test_strips_whitespace(self):
        c = _billing_customer(bill_to_email="  billing@goldhaus.at  ")
        assert pick_email(c) == "billing@goldhaus.at"

    def test_does_not_mutate_customer(self):
        """pick_email is a pure function — no mutation."""
        c = _billing_customer()
        original_email = c.bill_to_email
        pick_email(c)
        assert c.bill_to_email == original_email


# =============================================================================
# 2. resolve_billing_address
# =============================================================================

class TestResolveBillingAddress:
    """resolve_billing_address returns bill-to fields as a dict."""

    def test_returns_all_billing_fields(self):
        c = _billing_customer()
        addr = resolve_billing_address(c)
        assert addr["name"] == "Goldhaus AG"
        assert addr["street"] == "Kärntner Straße 12"
        assert addr["city"] == "Wien"
        assert addr["postal_code"] == "1010"
        assert addr["country"] == "AT"
        assert addr["phone"] == "+43 1 234 5678"
        assert addr["email"] == "billing@goldhaus.at"

    def test_uses_top_level_country(self):
        """country comes from the top-level field, not a bill_to_country."""
        c = _billing_customer(country="CH")
        addr = resolve_billing_address(c)
        assert addr["country"] == "CH"

    def test_missing_fields_are_empty_strings(self):
        c = _base_customer()
        addr = resolve_billing_address(c)
        assert addr["name"] == "Estrella Test GmbH"
        assert addr["street"] == ""
        assert addr["city"] == ""
        assert addr["postal_code"] == ""
        assert addr["country"] == "DE"
        assert addr["phone"] == ""
        assert addr["email"] == ""

    def test_strips_whitespace(self):
        c = _billing_customer(bill_to_street="  Kärntner Straße 12  ")
        addr = resolve_billing_address(c)
        assert addr["street"] == "Kärntner Straße 12"

    def test_does_not_include_ship_to_fields(self):
        """Billing address must NOT leak ship-to data."""
        c = _shipto_customer()
        addr = resolve_billing_address(c)
        assert addr["street"] == "8 Rue de Rivoli"  # bill-to, not ship-to
        assert addr["city"] == "Paris"  # bill-to, not Roissy
        assert "person" not in addr  # billing has no person field

    def test_does_not_mutate_customer(self):
        c = _billing_customer()
        original_name = c.bill_to_name
        resolve_billing_address(c)
        assert c.bill_to_name == original_name


# =============================================================================
# 3. resolve_delivery_address — ship-to authority
# =============================================================================

class TestResolveDeliveryAddress:
    """resolve_delivery_address implements ship-to first, bill-to fallback."""

    # ── Ship-to path ────────────────────────────────────────────────────────

    def test_uses_ship_to_when_alternate_enabled(self):
        """When ship_to_use_alternate=True and address populated → use ship-to."""
        c = _shipto_customer()
        addr = resolve_delivery_address(c)
        assert addr["source"] == "ship_to"
        assert addr["name"] == "Bijoux Entrepôt"
        assert addr["person"] == "Jean-Pierre Dupont"
        assert addr["street"] == "Zone Industrielle Nord, Bât 4"
        assert addr["city"] == "Roissy-en-France"
        assert addr["postal_code"] == "95700"
        assert addr["country"] == "FR"
        assert addr["phone"] == "+33 1 99 88 77 66"
        assert addr["email"] == "warehouse@bijoux.fr"

    def test_ship_to_does_not_contain_billing_data(self):
        """When ship-to is used, billing address must not leak in."""
        c = _shipto_customer()
        addr = resolve_delivery_address(c)
        assert addr["street"] != "8 Rue de Rivoli"  # not bill-to
        assert addr["city"] != "Paris"  # not bill-to

    def test_billing_never_overrides_ship_to(self):
        """Rule 6: billing address must not override a separate ship-to."""
        c = _shipto_customer()
        addr = resolve_delivery_address(c)
        assert addr["source"] == "ship_to"
        # Even though billing is fully populated, ship-to wins
        assert addr["name"] == "Bijoux Entrepôt"
        assert addr["street"] == "Zone Industrielle Nord, Bât 4"

    # ── Bill-to fallback path ───────────────────────────────────────────────

    def test_falls_back_to_billing_when_no_alternate(self):
        """When ship_to_use_alternate=False → use billing address."""
        c = _billing_customer()
        addr = resolve_delivery_address(c)
        assert addr["source"] == "bill_to_fallback"
        assert addr["name"] == "Goldhaus AG"
        assert addr["street"] == "Kärntner Straße 12"
        assert addr["city"] == "Wien"
        assert addr["postal_code"] == "1010"
        assert addr["country"] == "AT"

    def test_falls_back_when_alternate_enabled_but_address_empty(self):
        """ship_to_use_alternate=True but no actual address → fallback."""
        c = _base_customer(
            ship_to_use_alternate=True,
            bill_to_street="Bahnhofstraße 1",
            bill_to_city="Berlin",
            bill_to_postal_code="10115",
        )
        addr = resolve_delivery_address(c)
        assert addr["source"] == "bill_to_fallback"
        assert addr["city"] == "Berlin"

    def test_falls_back_when_ship_to_has_only_name(self):
        """Name only (no street/city) is not a deliverable address."""
        c = _base_customer(
            ship_to_use_alternate=True,
            ship_to_name="Some Warehouse",
            # No street, no city
            bill_to_street="Hauptstr. 5",
            bill_to_city="München",
        )
        addr = resolve_delivery_address(c)
        assert addr["source"] == "bill_to_fallback"
        assert addr["city"] == "München"

    def test_ship_to_with_city_only_is_valid(self):
        """City without street is borderline but treated as valid address."""
        c = _base_customer(
            ship_to_use_alternate=True,
            ship_to_city="Frankfurt",
            ship_to_country="DE",
        )
        addr = resolve_delivery_address(c)
        assert addr["source"] == "ship_to"
        assert addr["city"] == "Frankfurt"

    def test_ship_to_with_street_only_is_valid(self):
        """Street without city is borderline but treated as valid address."""
        c = _base_customer(
            ship_to_use_alternate=True,
            ship_to_street="Am Hafen 7",
        )
        addr = resolve_delivery_address(c)
        assert addr["source"] == "ship_to"
        assert addr["street"] == "Am Hafen 7"

    # ── Fallback dict shape ─────────────────────────────────────────────────

    def test_fallback_includes_person_as_empty(self):
        """Bill-to fallback must include 'person' key (empty) for shape parity."""
        c = _billing_customer()
        addr = resolve_delivery_address(c)
        assert addr["person"] == ""

    def test_both_paths_have_same_keys(self):
        """Ship-to and bill-to-fallback must have the same dict keys."""
        ship = resolve_delivery_address(_shipto_customer())
        bill = resolve_delivery_address(_billing_customer())
        assert set(ship.keys()) == set(bill.keys())

    # ── Shape B does not affect DHL delivery ────────────────────────────────

    def test_shape_b_does_not_replace_delivery_address(self):
        """Shape B (ship_to_contractor_id) is wFirma receiver, not DHL address."""
        c = _billing_customer(
            ship_to_contractor_id="77777",
            # No ship_to_use_alternate, no ship_to_* address fields
        )
        # Shape B is set, but it should NOT produce a ship-to delivery address
        assert ship_to_shape(c) == SHIP_TO_SEPARATE_CONTRACTOR
        addr = resolve_delivery_address(c)
        # Must fall back to billing — Shape B has no physical address
        assert addr["source"] == "bill_to_fallback"
        assert addr["name"] == "Goldhaus AG"

    def test_shape_b_with_alternate_address_uses_alternate(self):
        """Shape B + Shape A populated → Shape A wins for delivery."""
        c = _shipto_customer(ship_to_contractor_id="88888")
        # Has both Shape B and populated Shape A
        assert ship_to_shape(c) == SHIP_TO_SEPARATE_CONTRACTOR  # Shape B classifier
        addr = resolve_delivery_address(c)
        # Delivery uses Shape A (physical address), not Shape B
        assert addr["source"] == "ship_to"
        assert addr["name"] == "Bijoux Entrepôt"

    # ── No mutation ─────────────────────────────────────────────────────────

    def test_does_not_mutate_customer(self):
        """resolve_delivery_address is a pure function — no mutation."""
        c = _shipto_customer()
        original_name = c.ship_to_name
        original_street = c.ship_to_street
        resolve_delivery_address(c)
        assert c.ship_to_name == original_name
        assert c.ship_to_street == original_street

    def test_does_not_mutate_customer_on_fallback(self):
        c = _billing_customer()
        original_name = c.bill_to_name
        resolve_delivery_address(c)
        assert c.bill_to_name == original_name


# =============================================================================
# 4. Edge cases — whitespace, None, mixed
# =============================================================================

class TestEdgeCases:
    """Whitespace handling, None fields, and mixed scenarios."""

    def test_ship_to_whitespace_only_street_falls_back(self):
        """Whitespace-only ship-to fields are treated as empty."""
        c = _base_customer(
            ship_to_use_alternate=True,
            ship_to_street="   ",
            ship_to_city="   ",
            bill_to_street="Real Street 1",
            bill_to_city="Real City",
        )
        addr = resolve_delivery_address(c)
        assert addr["source"] == "bill_to_fallback"

    def test_all_none_customer_returns_empty_strings(self):
        c = _base_customer()
        email = pick_email(c)
        billing = resolve_billing_address(c)
        delivery = resolve_delivery_address(c)
        assert email == ""
        assert billing["street"] == ""
        assert delivery["source"] == "bill_to_fallback"
        assert delivery["street"] == ""

    def test_ship_to_email_fallback_does_not_require_alternate_flag(self):
        """pick_email falls back to ship_to_email regardless of ship_to_use_alternate."""
        c = _base_customer(
            ship_to_use_alternate=False,
            ship_to_email="fallback@example.com",
        )
        assert pick_email(c) == "fallback@example.com"


# =============================================================================
# 5. Source-grep: helpers exist in customer_master.py
# =============================================================================

class TestSourcePresence:
    """Verify the helpers are defined in the correct module."""

    def test_pick_email_in_module(self):
        import app.services.customer_master as cm
        assert hasattr(cm, "pick_email")
        assert callable(cm.pick_email)

    def test_resolve_billing_address_in_module(self):
        import app.services.customer_master as cm
        assert hasattr(cm, "resolve_billing_address")
        assert callable(cm.resolve_billing_address)

    def test_resolve_delivery_address_in_module(self):
        import app.services.customer_master as cm
        assert hasattr(cm, "resolve_delivery_address")
        assert callable(cm.resolve_delivery_address)

    def test_all_three_in_all_exports(self):
        import app.services.customer_master as cm
        assert "pick_email" in cm.__all__
        assert "resolve_billing_address" in cm.__all__
        assert "resolve_delivery_address" in cm.__all__

    def test_source_has_authority_comment(self):
        """The source must reference the authority model decision."""
        src = Path(__file__).resolve().parent.parent / "app" / "services" / "customer_master.py"
        text = src.read_text(encoding="utf-8")
        assert "PROJECT_STATE.md DECISIONS 2026-06-07" in text
        assert "bill_to_* = invoice / billing authority" in text
        assert "ship_to_* = DHL delivery / shipping authority" in text
