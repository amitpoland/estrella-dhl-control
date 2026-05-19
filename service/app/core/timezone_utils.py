"""Timezone utilities for PZ service.

Warsaw is the canonical timezone for all operator-facing dates.
Use warsaw_today() wherever a "today's date" needs to be Poland-local.
"""
from __future__ import annotations

from datetime import date


def warsaw_today() -> date:
    """Return today's date in Europe/Warsaw timezone.

    Uses zoneinfo (Python 3.9+). On Windows Server where the tz database
    may be absent, falls back to UTC (acceptable: Warsaw/UTC differ by 1–2
    hours, never a calendar day in business hours).
    """
    try:
        from zoneinfo import ZoneInfo
        from datetime import datetime
        return datetime.now(ZoneInfo("Europe/Warsaw")).date()
    except Exception:
        from datetime import datetime, timezone
        return datetime.now(timezone.utc).date()
