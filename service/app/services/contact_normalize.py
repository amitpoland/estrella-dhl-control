"""Shared contact normalizers — one email + one E.164 phone helper.

Used at Customer Master validate boundaries and return-draft writes.
Never invents a country dial code for ambiguous national numbers.
"""
from __future__ import annotations

import re
from typing import Optional, Tuple

# Dial prefixes for Estrella's real footprint only — used ONLY when the
# operator/authority already supplied an ISO alpha-2 country_code. Ambiguous
# national numbers without a country never get a silent invent.
_DIAL_BY_ALPHA2 = {
    "PL": "48",
    "DE": "49",
    "FR": "33",
    "IT": "39",
    "ES": "34",
    "NL": "31",
    "BE": "32",
    "AT": "43",
    "CZ": "420",
    "SK": "421",
    "HU": "36",
    "RO": "40",
    "BG": "359",
    "PT": "351",
    "SE": "46",
    "DK": "45",
    "FI": "358",
    "IE": "353",
    "LT": "370",
    "LV": "371",
    "EE": "372",
    "GR": "30",
    "HR": "385",
    "SI": "386",
    "GB": "44",
    "UK": "44",
    "US": "1",
    "CA": "1",
    "IN": "91",
    "CH": "41",
    "NO": "47",
    "AE": "971",
    "SA": "966",
    "IL": "972",
    "TR": "90",
    "UA": "380",
}

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_email(raw: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """Return ``(normalized_email, error)``.

    Strips whitespace and lowercases the full address. Empty → ``(None, None)``.
    Invalid shape → ``(None, reason)``.
    """
    if raw is None:
        return None, None
    s = str(raw).strip()
    if not s:
        return None, None
    s = s.lower()
    if not _EMAIL_RE.match(s) or s.count("@") != 1:
        return None, "email_invalid"
    return s, None


def normalize_phone_e164(
    raw: Optional[str],
    *,
    country_code: Optional[str] = None,
) -> Tuple[Optional[str], Optional[str], bool]:
    """Return ``(e164_or_None, error_or_None, needs_review)``.

    Rules:
    - Blank → ``(None, None, False)``
    - Already ``+`` / ``00`` international → normalize to ``+digits`` when valid length
    - National digits + known ``country_code`` → prefix that country's dial code
    - Ambiguous national number without usable country → ``needs_review=True``
      (never invent a dial code)
    """
    if raw is None:
        return None, None, False
    s = str(raw).strip()
    if not s:
        return None, None, False

    compact = re.sub(r"[\s\-().]", "", s)
    if not compact:
        return None, None, False

    # 00… → +…
    if compact.startswith("00") and len(compact) > 2:
        compact = "+" + compact[2:]

    if compact.startswith("+"):
        digits = compact[1:]
        if digits.isdigit() and 8 <= len(digits) <= 15:
            return f"+{digits}", None, False
        return None, "phone_e164_invalid", True

    # Digits only (possibly with leading 0 national trunk)
    digits = compact
    if not digits.isdigit():
        return None, "phone_non_digit", True

    cc = (country_code or "").strip().upper()
    if cc == "UK":
        cc = "GB"
    dial = _DIAL_BY_ALPHA2.get(cc)
    if not dial:
        # Ambiguous — do not invent a country code.
        return None, "phone_needs_country", True

    national = digits.lstrip("0") or digits
    candidate = f"+{dial}{national}"
    body = candidate[1:]
    if body.isdigit() and 8 <= len(body) <= 15:
        return candidate, None, False
    return None, "phone_e164_invalid", True
