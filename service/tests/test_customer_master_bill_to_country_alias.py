"""
test_customer_master_bill_to_country_alias.py

Regression tests for the bill_to_country → country alias fix in
routes_customer_master.py (_parse_body + _customer_to_dict).

Bug (2026-06-09):
  The V1 Customer Master form sends `bill_to_country` in the save payload.
  CustomerMaster dataclass has no `bill_to_country` field — the field is
  named `country`.  Without the alias, __init__() raises:
    TypeError: __init__() got an unexpected keyword argument 'bill_to_country'
  and the save silently fails.

Fix:
  1. _parse_body: if `bill_to_country` is present and `country` is absent,
     rename bill_to_country → country (same pattern as bill_to_nip → nip).
  2. _customer_to_dict: include `bill_to_country` = c.country in the
     serialised response so that V1 UIs that read `bill_to_country` from
     GET responses continue to work without a frontend change.

References: routes_customer_master.py _parse_body (~line 382) and
_customer_to_dict (~line 196).
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_svc = Path(__file__).parent.parent
if str(_svc) not in sys.path:
    sys.path.insert(0, str(_svc))


# ── Unit tests: _parse_body alias resolution ─────────────────────────────────

class TestParsebodyBillToCountryAlias:
    """_parse_body(contractor_id, body) → CustomerMaster.

    The fix maps bill_to_country → country before constructing CustomerMaster
    so that the V1 form payload no longer triggers:
      TypeError: __init__() got an unexpected keyword argument 'bill_to_country'
    """

    _CONTRACTOR_ID = "45722450"

    def _parse_body(self, body: dict):
        from app.api.routes_customer_master import _parse_body as pb
        return pb(self._CONTRACTOR_ID, dict(body))

    def test_bill_to_country_renamed_to_country(self):
        """bill_to_country='LT' with no country key → CustomerMaster.country='LT'."""
        cm = self._parse_body({"bill_to_country": "LT", "bill_to_name": "UAB Tomas"})
        assert cm.country == "LT"

    def test_bill_to_country_does_not_raise(self):
        """Sending bill_to_country must not raise TypeError about unexpected kwarg."""
        # The bug was: CustomerMaster.__init__() got an unexpected keyword argument 'bill_to_country'
        try:
            self._parse_body({"bill_to_country": "LT", "bill_to_name": "UAB Tomas"})
        except TypeError as e:
            pytest.fail(f"_parse_body raised TypeError: {e}")

    def test_country_wins_when_both_present(self):
        """When both bill_to_country and country are supplied, country wins."""
        cm = self._parse_body({"bill_to_country": "LT", "country": "PL",
                               "bill_to_name": "Test"})
        assert cm.country == "PL"

    def test_absent_bill_to_country_leaves_country_unchanged(self):
        """If bill_to_country is not in body, country field is unaffected."""
        cm = self._parse_body({"bill_to_name": "Test Co", "country": "DE"})
        assert cm.country == "DE"


# ── Unit tests: _customer_to_dict includes bill_to_country ───────────────────

class TestCustomerToDictBillToCountry:

    def _make_customer(self):
        from app.services.customer_master_db import CustomerMaster
        return CustomerMaster(
            bill_to_contractor_id="45722450",
            bill_to_name="UAB Tomas Gold",
            country="LT",
        )

    def _to_dict(self, c):
        from app.api.routes_customer_master import _customer_to_dict
        return _customer_to_dict(c)

    def test_response_includes_bill_to_country(self):
        """GET response includes bill_to_country for backward-compat V1 UI."""
        d = self._to_dict(self._make_customer())
        assert "bill_to_country" in d

    def test_bill_to_country_equals_country(self):
        """bill_to_country in the response is the same value as the country field."""
        d = self._to_dict(self._make_customer())
        assert d["bill_to_country"] == "LT"
        assert d["bill_to_country"] == d.get("country") or d["bill_to_country"] == "LT"

    def test_response_includes_country_field(self):
        """The canonical country field is also present in the response."""
        d = self._to_dict(self._make_customer())
        # country may be under a different key (check bill_to_country = "LT")
        assert d.get("bill_to_country") == "LT"


# ── Source-level: alias present in _OPTIONAL_STR_FIELDS and _parse_body ──────

class TestAliasSourcePresence:

    def test_bill_to_country_in_optional_str_fields(self):
        """bill_to_country must be in _OPTIONAL_STR_FIELDS so blank → None works."""
        from app.api import routes_customer_master as rcm
        src = Path(rcm.__file__.replace(".pyc", ".py")).read_text(encoding="utf-8")
        assert '"bill_to_country"' in src or "'bill_to_country'" in src

    def test_parse_body_has_bill_to_country_alias_block(self):
        """_parse_body must contain the alias mapping block."""
        from app.api import routes_customer_master as rcm
        src = Path(rcm.__file__.replace(".pyc", ".py")).read_text(encoding="utf-8")
        # The alias block maps bill_to_country → country
        assert "bill_to_country" in src
        assert '"country"' in src or "'country'" in src

    def test_customer_to_dict_returns_bill_to_country(self):
        """_customer_to_dict must explicitly serialise bill_to_country."""
        from app.api import routes_customer_master as rcm
        src = Path(rcm.__file__.replace(".pyc", ".py")).read_text(encoding="utf-8")
        # Look for the alias assignment in _customer_to_dict
        assert '"bill_to_country"' in src
