"""PZ Preview Authority Audit (2026-05-21).

`_derive_pz_status` must surface engine failures as `'failed'` instead of
returning the optimistic `'ready'` whenever SAD is present. Fault A in the
audit's root cause analysis: a batch with status=='failed' or engine_error
must NEVER show "Ready for PZ" on the badge.
"""
from __future__ import annotations

from service.app.api.routes_dashboard import _derive_pz_status


def _a(**kwargs):
    base = {"status": "ready", "inputs": {"zc429": "x"}}
    base.update(kwargs)
    return base


def test_status_failed_returns_failed():
    assert _derive_pz_status(_a(status="failed")) == "failed"


def test_engine_error_alone_returns_failed():
    # No status, but engine_error truthy.
    assert _derive_pz_status({"engine_error": "Total before-duty PLN is zero"}) == "failed"


def test_engine_error_overrides_success_marker():
    # If a stale "ready" status got set after engine actually failed,
    # engine_error still wins.
    assert _derive_pz_status(_a(status="ready", engine_error="x")) == "failed"


def test_success_returns_complete():
    # Regression: a real success must keep producing 'complete'.
    a = {"status": "success", "inputs": {"zc429": "x"}}
    assert _derive_pz_status(a) == "complete"


def test_partial_returns_complete():
    a = {"status": "partial", "inputs": {"zc429": "x"}}
    assert _derive_pz_status(a) == "complete"


def test_sad_missing_returns_locked():
    # Regression: empty inputs → locked.
    a = {"status": "ready", "inputs": {}}
    assert _derive_pz_status(a) == "locked"


def test_default_returns_ready():
    a = {"status": "ready", "inputs": {"zc429": "x"}}
    assert _derive_pz_status(a) == "ready"


def test_empty_string_engine_error_does_not_trigger_failed():
    # Defensive: empty engine_error string must not flip the badge.
    a = {"status": "ready", "inputs": {"zc429": "x"}, "engine_error": ""}
    assert _derive_pz_status(a) == "ready"


def test_whitespace_engine_error_does_not_trigger_failed():
    a = {"status": "ready", "inputs": {"zc429": "x"}, "engine_error": "   "}
    assert _derive_pz_status(a) == "ready"


def test_case_insensitive_failed_status():
    assert _derive_pz_status({"status": "FAILED", "inputs": {"zc429": "x"}}) == "failed"
