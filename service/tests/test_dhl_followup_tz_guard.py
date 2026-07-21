"""
test_dhl_followup_tz_guard.py — POLAND_TZ must survive a missing tz database.

zoneinfo has no system tz database on Windows; it needs the `tzdata` package
(service/requirements.txt). Deploys robocopy app/ with no pip step, so an
unguarded ZoneInfo("Europe/Warsaw") at module scope turns a missing tzdata into
a request-time 500 on every DHL follow-up, DSK chase, and agency SLA path —
all three import this constant.

The failure is at IMPORT time, so it cannot be reproduced by monkeypatching
after the module is loaded. Each case runs in a subprocess that poisons
zoneinfo.ZoneInfo BEFORE the import.

The fallback must stay an AWARE tzinfo: POLAND_TZ is passed to datetime.now()
and dt.replace(tzinfo=...), and None there yields naive datetimes that raise
TypeError against the aware ones the SLA maths already carries.
"""
from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

_SVC = Path(__file__).resolve().parent.parent

_POISON = """
import sys, os
sys.path.insert(0, r'{svc}'); os.environ.setdefault('API_KEY', 'test-key')
import zoneinfo
def _boom(*a, **k):
    raise zoneinfo.ZoneInfoNotFoundError('No time zone found with key Europe/Warsaw')
zoneinfo.ZoneInfo = _boom
from app.services import dhl_followup_sla as m
from datetime import datetime, timedelta
{body}
"""


def _run_without_tzdata(body: str) -> str:
    src = _POISON.format(svc=str(_SVC), body=textwrap.dedent(body))
    r = subprocess.run([sys.executable, "-c", src], capture_output=True, text=True)
    assert r.returncode == 0, f"import/exec failed without tzdata:\n{r.stderr[-2000:]}"
    return r.stdout.strip()


class TestMissingTzDatabase:

    def test_module_still_imports(self):
        assert _run_without_tzdata("print('imported')") == "imported"

    def test_poland_tz_is_not_none(self):
        """None would make datetime.now(POLAND_TZ) naive and break SLA maths."""
        assert _run_without_tzdata("print(m.POLAND_TZ is None)") == "False"

    def test_now_poland_stays_offset_aware(self):
        assert _run_without_tzdata("print(m._now_poland().tzinfo is not None)") == "True"

    def test_aware_arithmetic_does_not_raise(self):
        """The real failure mode of a None fallback: naive vs aware TypeError."""
        out = _run_without_tzdata("""
            delta = m._now_poland() - datetime.now(m.POLAND_TZ)
            print(abs(delta) < timedelta(seconds=5))
        """)
        assert out == "True"

    def test_fallback_is_not_utc(self):
        """Warsaw is 1–2h ahead of UTC and WORK_START/WORK_END are Warsaw
        wall-clock, so degrading to UTC would silently shift the working window.
        On a UTC-configured host local IS UTC — assert the intent, not the host:
        the fallback must be the host's local offset."""
        out = _run_without_tzdata("""
            local = datetime.now().astimezone().utcoffset()
            print(datetime.now(m.POLAND_TZ).utcoffset() == local)
        """)
        assert out == "True"


class TestNormalEnvironment:

    def test_real_zoneinfo_is_used_when_available(self):
        from zoneinfo import ZoneInfo
        from app.services import dhl_followup_sla as m
        assert m.POLAND_TZ == ZoneInfo("Europe/Warsaw"), \
            "with tzdata present the guard must not degrade anything"

    def test_dst_transitions_still_tracked_when_available(self):
        """Guards the guard: the fixed-offset fallback cannot silently become
        the normal path, since it would freeze the offset across a DST switch."""
        from datetime import datetime
        from app.services import dhl_followup_sla as m
        summer = datetime(2026, 7, 1, 12, 0, tzinfo=m.POLAND_TZ).utcoffset()
        winter = datetime(2026, 1, 1, 12, 0, tzinfo=m.POLAND_TZ).utcoffset()
        assert summer != winter
