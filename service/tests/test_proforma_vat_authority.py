"""
test_proforma_vat_authority.py — Proforma WDT VAT authority agreement (Draft #34 / Clear-Diamonds).

ROOT CAUSE THIS PINS
--------------------
For an EU buyer whose EU VAT is stored in Customer Master's general tax-id field
``nip`` (e.g. Clear-Diamonds, HU, nip='HU32207880') while the canonical
``vat_eu_number`` field is blank:

  * the WDT readiness gate reads ``vat_eu_number`` (blank) and blocks, and
  * the V2 buyer card historically read ``buyer_override.vat_id`` (blank),

so the two surfaces disagreed with each other AND with the on-file VAT — the
operator was blocked for a "blank" VAT that was plainly on file, with no inline
repair path.

The fix surfaces the on-file ``nip`` as a confirm-and-save EU-VAT *candidate*
(``_eu_vat_candidate_from_master``) so the displayed VAT and the readiness VAT
reference the SAME value, and the blocker becomes actionable — WITHOUT ever
auto-accepting ``nip`` as the EU VAT (WDT stays gated until ``vat_eu_number`` is
explicitly saved; the WDT rule is tax-sensitive and must not be bypassed).

These are pure-function tests over the candidate resolver — no DB/app fixtures.
"""
from __future__ import annotations

import types

from app.api.routes_proforma import _eu_vat_candidate_from_master


def _cm(**kw):
    """Minimal stand-in for a customer_master record (helper uses getattr)."""
    base = {"country": None, "nip": None, "vat_eu_number": None}
    base.update(kw)
    return types.SimpleNamespace(**base)


# ── The Clear-Diamonds case: EU VAT lives in nip, vat_eu_number blank ────────

def test_clear_diamonds_nip_is_surfaced_as_eu_vat_candidate():
    """Displayed VAT (nip) and readiness VAT candidate must agree on the value."""
    cm = _cm(country="HU", nip="HU32207880", vat_eu_number=None)
    cand = _eu_vat_candidate_from_master(cm)
    assert cand is not None, "on-file HU nip must surface as a save candidate"
    assert cand["candidate_vat"] == "HU32207880"
    assert cand["candidate_source"] == "nip"


def test_candidate_value_matches_what_buyer_card_would_display():
    """The candidate the gate surfaces is exactly the nip a card displays —
    proving the displayed-VAT source and readiness-VAT source agree."""
    cm = _cm(country="HU", nip="HU32207880", vat_eu_number="")
    displayed_vat = (cm.vat_eu_number or cm.nip or "").strip()   # card fallback order
    cand = _eu_vat_candidate_from_master(cm)
    assert cand is not None
    assert cand["candidate_vat"] == displayed_vat == "HU32207880"


# ── WDT is NEVER bypassed: a candidate is not eligibility ────────────────────

def test_populated_vat_eu_number_yields_no_candidate():
    """Once the canonical field is set, there is nothing to save — and the gate
    (elsewhere) stops blocking. The candidate path is the blank-field case only."""
    cm = _cm(country="HU", nip="HU32207880", vat_eu_number="HU32207880")
    assert _eu_vat_candidate_from_master(cm) is None


def test_bare_domestic_nip_is_not_offered_as_eu_vat():
    """A nip with no ISO country prefix is a domestic tax id, NOT an EU VAT.
    Offering it would risk asserting WDT eligibility from the wrong number —
    forbidden by the tax-sensitivity safety gate."""
    cm = _cm(country="PL", nip="5252812119", vat_eu_number=None)
    assert _eu_vat_candidate_from_master(cm) is None


def test_non_eu_country_yields_no_wdt_candidate():
    """Non-EU customers are export (EXP), not WDT — no EU-VAT candidate."""
    cm = _cm(country="US", nip="US123456789", vat_eu_number=None)
    assert _eu_vat_candidate_from_master(cm) is None


def test_blank_nip_yields_no_candidate():
    """No tax number on file → no candidate (truly-blank VAT keeps the generic
    'add the EU VAT number' blocker, not the save-from-nip path)."""
    cm = _cm(country="HU", nip="", vat_eu_number=None)
    assert _eu_vat_candidate_from_master(cm) is None


def test_missing_country_yields_no_candidate():
    """No country → VAT treatment is blocked upstream; never offer a candidate."""
    cm = _cm(country=None, nip="HU32207880", vat_eu_number=None)
    assert _eu_vat_candidate_from_master(cm) is None


def test_candidate_tolerates_prefix_spacing_and_case():
    """nip stored with spaces / lower case still matches its country prefix."""
    cm = _cm(country="HU", nip="hu 32207880", vat_eu_number=None)
    cand = _eu_vat_candidate_from_master(cm)
    assert cand is not None and cand["candidate_source"] == "nip"
