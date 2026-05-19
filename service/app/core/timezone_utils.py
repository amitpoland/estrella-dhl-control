"""Timezone utilities for PZ service.

Warsaw is the canonical timezone for all operator-facing dates.
Use warsaw_today() wherever a "today's date" needs to be Poland-local.

Requires tzdata package on Windows (add tzdata>=2024.1 to requirements.txt).
Do NOT maintain manual DST rules — zoneinfo handles them via tzdata.
"""
from __future__ import annotations

import logging
from datetime import date, datetime

_log = logging.getLogger(__name__)


def warsaw_today() -> date:
    """Return today's date in Europe/Warsaw timezone.

    Uses zoneinfo (Python 3.9+) + tzdata package for Windows.
    Falls back to system local time (with a WARNING) if the tz database
    is unavailable — do NOT fall back to UTC since Warsaw and UTC differ
    by 1–2 hours and may land on different calendar days.
    """
    try:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError  # type: ignore[import]
        return datetime.now(ZoneInfo("Europe/Warsaw")).date()
    except Exception as exc:
        _log.warning(
            "timezone_utils: ZoneInfo('Europe/Warsaw') unavailable (%s). "
            "Falling back to system local time. Install tzdata>=2024.1 on Windows.",
            exc,
        )
        return datetime.now().date()
