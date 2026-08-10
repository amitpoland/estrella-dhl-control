"""Immutable ISO 3166-1 alpha-2 → English display name lookup.

Canonical storage is always alpha-2. Display names are derived at read time —
never a second editable country authority.
"""
from __future__ import annotations

from typing import Optional

# Coverage = Estrella origin/destination footprint + common EU partners.
# Unknown codes return the alpha-2 itself (honest), never invent a name.
_ALPHA2_TO_NAME = {
    "AT": "Austria",
    "AE": "United Arab Emirates",
    "BE": "Belgium",
    "BG": "Bulgaria",
    "CA": "Canada",
    "CH": "Switzerland",
    "CY": "Cyprus",
    "CZ": "Czechia",
    "DE": "Germany",
    "DK": "Denmark",
    "EE": "Estonia",
    "ES": "Spain",
    "FI": "Finland",
    "FR": "France",
    "GB": "United Kingdom",
    "GR": "Greece",
    "HR": "Croatia",
    "HU": "Hungary",
    "IE": "Ireland",
    "IL": "Israel",
    "IN": "India",
    "IT": "Italy",
    "LT": "Lithuania",
    "LU": "Luxembourg",
    "LV": "Latvia",
    "MT": "Malta",
    "NL": "Netherlands",
    "NO": "Norway",
    "PL": "Poland",
    "PT": "Portugal",
    "RO": "Romania",
    "SA": "Saudi Arabia",
    "SE": "Sweden",
    "SI": "Slovenia",
    "SK": "Slovakia",
    "TR": "Turkey",
    "UA": "Ukraine",
    "US": "United States",
}

_EU_ALPHA2 = frozenset({
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR",
    "DE", "GR", "HU", "IE", "IT", "LV", "LT", "LU", "MT", "NL",
    "PL", "PT", "RO", "SK", "SI", "ES", "SE",
})


def normalize_country_alpha2(raw: Optional[str]) -> Optional[str]:
    """Return uppercase ISO alpha-2, or None when blank/invalid length."""
    if raw is None:
        return None
    s = str(raw).strip().upper()
    if s == "UK":
        s = "GB"
    if len(s) == 2 and s.isalpha():
        return s
    return None


def country_display_name(alpha2: Optional[str]) -> Optional[str]:
    """Derive English display name from alpha-2. Does not store a second truth."""
    cc = normalize_country_alpha2(alpha2)
    if not cc:
        return None
    return _ALPHA2_TO_NAME.get(cc, cc)


def is_eu_country(alpha2: Optional[str]) -> bool:
    cc = normalize_country_alpha2(alpha2)
    return bool(cc and cc in _EU_ALPHA2)
