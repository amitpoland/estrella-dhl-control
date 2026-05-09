"""
dhl_express_quota.py — DHL daily-call quota (UTC-day token bucket).

DL-F1 scope
-----------
Per-instance quota counter that:
  * Counts every live call the adapter makes today.
  * Resets automatically when the UTC date rolls over.
  * Raises ``CarrierRateLimitError`` BEFORE making the HTTP call when
    the limit is exhausted (defends against burning the quota on
    retry storms).

The DHL sandbox publishes a 500-calls-per-day quota by default; the
production quota is negotiated. Wiring a counter into the adapter
gives us a hard cap that's independent of DHL's own throttle, so
even a runaway retry loop on our side cannot exceed the daily budget.

Threading
---------
A single ``threading.Lock`` guards the counter. The handler /
coordinator may be invoked from multiple FastAPI request workers
sharing one adapter instance.

Test surface
------------
``clock`` is injectable: it returns a ``datetime.date`` (the UTC date
"today"). Tests use a fake clock to drive the day-rollover branch
without sleeping.
"""
from __future__ import annotations

import threading
from datetime import date, datetime, timezone
from typing import Callable, Optional

from .base import CarrierRateLimitError


def _utc_today() -> date:
    """Default clock — returns the current UTC date."""
    return datetime.now(timezone.utc).date()


class DHLDailyQuota:
    """Per-instance daily call counter keyed on UTC date.

    Construction
    ------------
    ``daily_limit`` is the hard cap. Must be > 0; ValueError otherwise.
    ``clock`` is an optional zero-arg callable returning a
    ``datetime.date``. Defaults to :func:`_utc_today`.
    """

    def __init__(
        self,
        *,
        daily_limit: int = 500,
        clock:       Optional[Callable[[], date]] = None,
    ) -> None:
        if daily_limit <= 0:
            raise ValueError(
                f"daily_limit must be positive, got {daily_limit!r}"
            )
        self._limit:        int                  = int(daily_limit)
        self._clock:        Callable[[], date]   = clock or _utc_today
        self._lock:         threading.Lock       = threading.Lock()
        self._current_day:  date                 = self._clock()
        self._calls_today:  int                  = 0

    def consume_or_raise(self) -> None:
        """Increment the counter. Raises if the daily cap has been
        reached *before* the increment (no over-counting)."""
        with self._lock:
            self._roll_over_locked()
            if self._calls_today >= self._limit:
                raise CarrierRateLimitError(
                    f"DHL daily quota exhausted "
                    f"({self._calls_today}/{self._limit})"
                )
            self._calls_today += 1

    def remaining_today(self) -> int:
        """Tokens left today. Honours rollover."""
        with self._lock:
            self._roll_over_locked()
            return max(0, self._limit - self._calls_today)

    def calls_today(self) -> int:
        """Calls already consumed today. Honours rollover."""
        with self._lock:
            self._roll_over_locked()
            return self._calls_today

    def reset_for_tests(self) -> None:
        """Test helper: zero the counter without changing the clock."""
        with self._lock:
            self._current_day = self._clock()
            self._calls_today = 0

    def _roll_over_locked(self) -> None:
        """If the UTC day has changed, reset the counter. Caller must
        already hold the lock."""
        today = self._clock()
        if today != self._current_day:
            self._current_day = today
            self._calls_today = 0
