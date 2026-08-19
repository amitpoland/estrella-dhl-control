"""Concurrent pollers for one AWB make exactly one carrier call.

A login sweep by several operators at once hits the same active AWB set
simultaneously.  Without single-flight that is N identical calls against a
documented 250/day DHL quota.
"""
from __future__ import annotations

import threading


def _arm_dhl(mon, monkeypatch):
    monkeypatch.setattr(mon.settings, "dhl_tracking_api_status", "active", raising=False)
    monkeypatch.setattr(mon, "_dhl_express_secrets_present", lambda: True)
    monkeypatch.setattr(mon, "_delivery_proof_present", lambda cache_dir: False)


def test_concurrent_pollers_make_one_carrier_call(tmp_path, monkeypatch):
    from app.services import tracking_service as ts

    _arm_dhl(ts, monkeypatch)
    entered = threading.Event()
    release = threading.Event()
    calls = []

    def _slow_call(tracking_no):
        calls.append(tracking_no)
        entered.set()
        release.wait(timeout=10)
        return {
            "status": "in_transit",
            "status_label": "In Transit",
            "events": [{"timestamp": "2026-08-19T10:00:00", "description": "Processed"}],
        }

    monkeypatch.setattr(ts, "_call_dhl", _slow_call)

    results = {}

    def _poll(name, refresh):
        results[name] = ts.get_tracking_status("9999999999", "DHL", tmp_path, refresh=refresh)

    leader = threading.Thread(target=_poll, args=("leader", True))
    leader.start()
    assert entered.wait(timeout=10), "leader never reached the carrier call"

    # Waiters ask for a forced refresh too — they must still be coalesced.
    waiters = [threading.Thread(target=_poll, args=(f"w{i}", True)) for i in range(3)]
    for t in waiters:
        t.start()
    release.set()
    leader.join(timeout=15)
    for t in waiters:
        t.join(timeout=15)

    assert calls == ["9999999999"], calls
    assert results["leader"]["status"] == "in_transit"
    for i in range(3):
        assert results[f"w{i}"]["status"] == "in_transit"
        assert results[f"w{i}"]["source"] == "cache"


def test_lock_is_per_awb_not_global(tmp_path, monkeypatch):
    from app.services import tracking_service as ts

    _arm_dhl(ts, monkeypatch)
    both_in = threading.Barrier(2, timeout=10)

    def _call(tracking_no):
        both_in.wait()  # deadlocks (BrokenBarrier) if the two AWBs serialise
        return {"status": "in_transit", "status_label": "In Transit", "events": []}

    monkeypatch.setattr(ts, "_call_dhl", _call)

    errs = []

    def _poll(awb):
        try:
            ts.get_tracking_status(awb, "DHL", tmp_path / awb, refresh=True)
        except Exception as exc:  # BrokenBarrierError on timeout
            errs.append(exc)

    ts_threads = [threading.Thread(target=_poll, args=(a,)) for a in ("1010101010", "2020202020")]
    for t in ts_threads:
        t.start()
    for t in ts_threads:
        t.join(timeout=15)
    assert errs == [], errs


def test_blank_tracking_number_is_not_locked(tmp_path):
    from app.services import tracking_service as ts

    out = ts.get_tracking_status("   ", "DHL", tmp_path)
    assert out["source"] == "no_tracking_number"
