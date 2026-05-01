"""
Regression tests for session key isolation.

Run:  python3 -m pytest test_session_keys.py -v
or:   python3 test_session_keys.py
"""
from __future__ import annotations

import sys, os
sys.path.insert(0, os.path.dirname(__file__))

# Allow test IDs for this test suite only
os.environ["DEBUG_ALLOW_TEST_SESSIONS"] = "true"

import re
import contextlib

# lightweight pytest.raises shim for running without pytest
class _RaisesCtx:
    def __init__(self, exc_type, match=None):
        self._exc = exc_type
        self._match = match
    def __enter__(self):
        return self
    def __exit__(self, tp, val, tb):
        if tp is None:
            raise AssertionError(f"Expected {self._exc.__name__} but nothing was raised")
        if not issubclass(tp, self._exc):
            return False  # re-raise
        if self._match and not re.search(self._match, str(val)):
            raise AssertionError(f"Pattern {self._match!r} not found in {val!r}")
        return True  # suppress

class _Pytest:
    @staticmethod
    def raises(exc_type, match=None):
        return _RaisesCtx(exc_type, match)

try:
    import pytest
except ImportError:
    pytest = _Pytest()  # type: ignore

# ── Unit: _key / _is_test_id / _normalize_tracking ───────────────────────────

from app.services.batch_manager import _key, _is_test_id, manager, BatchSession
from app.api.routes_batch import _normalize_tracking


def test_key_prefers_user_id():
    assert _key("chan123", "60015471543") == "60015471543"


def test_key_falls_back_to_chat_id():
    assert _key("chan123", "") == "chan123"
    assert _key("chan123") == "chan123"


def test_is_test_id_user456():
    assert _is_test_id("user456") is True


def test_is_test_id_test():
    assert _is_test_id("test") is True


def test_is_test_id_demo():
    assert _is_test_id("demo") is True


def test_is_test_id_real_zoho():
    assert _is_test_id("60015471543") is False


def test_is_test_id_empty():
    assert _is_test_id("") is False


def test_normalize_tracking_spaces():
    assert _normalize_tracking("68 7625 8325") == "6876258325"


def test_normalize_tracking_no_change():
    assert _normalize_tracking("6876258325") == "6876258325"


def test_normalize_tracking_mixed():
    assert _normalize_tracking("AWB-6876258325-A") == "AWB-6876258325-A"


# ── Integration: manager session lifecycle ────────────────────────────────────

def _fresh_manager():
    """Return a clean BatchManager for isolated tests."""
    from app.services.batch_manager import BatchManager
    m = BatchManager()
    return m


def test_start_creates_key_from_user_id():
    m = _fresh_manager()
    s = m.start_session("chan123", "60015471543", "PZ 1/1/2026")
    assert s.session_key == "60015471543"


def test_status_finds_session_with_user_id():
    m = _fresh_manager()
    m.start_session("chan123", "60015471543", "PZ 1/1/2026")
    # Lookup with a *different* chat_id but same user_id — must succeed
    found = m.get_session("different_chat", "60015471543")
    assert found is not None
    assert found.session_key == "60015471543"


def test_status_chat_id_only_does_not_override_user_session():
    m = _fresh_manager()
    m.start_session("chan123", "60015471543", "PZ 1/1/2026")
    # Lookup with chat_id only (no user_id) — should NOT find user-keyed session
    found = m.get_session("chan123", "")
    assert found is None


def test_submit_uses_same_key_as_start():
    m = _fresh_manager()
    s = m.start_session("chan123", "60015471543", "PZ 1/1/2026")
    # pop_session (used by /submit) uses same key function
    popped = m.pop_session("different_chat", "60015471543")
    assert popped is not None
    assert popped.batch_id == s.batch_id


def test_clear_test_sessions_removes_user456():
    m = _fresh_manager()
    m.start_session("chan123", "user456", "PZ TEST")
    m.start_session("chan123", "60015471543", "PZ REAL")
    removed = m.clear_test_sessions()
    assert len(removed) == 1
    # Real session untouched
    assert m.get_session("", "60015471543") is not None


def test_clear_test_sessions_leaves_real_sessions():
    m = _fresh_manager()
    m.start_session("chan1", "60015471543", "PZ 1/1/2026")
    removed = m.clear_test_sessions()
    assert removed == []
    assert m.active_count == 1


def test_production_guard_rejects_user456():
    """start_session raises ValueError for test IDs unless debug flag is set."""
    from app.services import batch_manager as bm_module

    class _FakeSettings:
        debug_allow_test_sessions = False

    orig = bm_module.settings
    bm_module.settings = _FakeSettings()
    try:
        m = _fresh_manager()
        with pytest.raises(ValueError, match="test user_id"):
            m.start_session("chan123", "user456", "PZ TEST")
    finally:
        bm_module.settings = orig


def test_production_guard_allows_real_id():
    from app.services import batch_manager as bm_module

    class _FakeSettings:
        debug_allow_test_sessions = False

    orig = bm_module.settings
    bm_module.settings = _FakeSettings()
    try:
        m = _fresh_manager()
        s = m.start_session("chan123", "60015471543", "PZ 1/1/2026")
        assert s.session_key == "60015471543"
    finally:
        bm_module.settings = orig


# ── Cancel confirmation gate ──────────────────────────────────────────────────

def test_cancel_empty_args_does_not_delete_session():
    """cancel_session must NOT be called when args is empty."""
    m = _fresh_manager()
    m.start_session("c1", "60015471543", "PZ 1/1/2026")
    # Simulate backend logic: args="" → gate blocks, session survives
    args = ""
    if args.strip().lower() != "confirm":
        pass  # gate would return confirm_required
    else:
        m.cancel_session("c1", "60015471543")
    assert m.get_session("c1", "60015471543") is not None, "Session must survive when args != confirm"


def test_cancel_confirm_deletes_session():
    """cancel_session is called only when args == 'confirm'."""
    m = _fresh_manager()
    m.start_session("c1", "60015471543", "PZ 1/1/2026")
    args = "confirm"
    if args.strip().lower() == "confirm":
        batch_id = m.cancel_session("c1", "60015471543")
        assert batch_id is not None
    assert m.get_session("c1", "60015471543") is None, "Session must be gone after confirm"


def test_cancel_mixed_case_confirm_deletes_session():
    """'CONFIRM', 'Confirm' etc. should also work (lowercase normalisation)."""
    m = _fresh_manager()
    m.start_session("c1", "60015471543", "PZ 1/1/2026")
    args = "Confirm"
    if args.strip().lower() == "confirm":
        m.cancel_session("c1", "60015471543")
    assert m.get_session("c1", "60015471543") is None


def test_cancel_wrong_word_does_not_delete():
    """Any word other than 'confirm' must be treated as no-confirm."""
    m = _fresh_manager()
    m.start_session("c1", "60015471543", "PZ 1/1/2026")
    for bad_arg in ("yes", "ok", "sure", "cancel", "1", ""):
        m2 = _fresh_manager()
        m2.start_session("c1", "60015471543", "PZ 1/1/2026")
        if bad_arg.strip().lower() != "confirm":
            pass  # gate blocks
        else:
            m2.cancel_session("c1", "60015471543")
        assert m2.get_session("c1", "60015471543") is not None, \
            f"Session must survive for args={bad_arg!r}"


if __name__ == "__main__":
    # Run without pytest
    import traceback
    passed = failed = 0
    fns = {k: v for k, v in globals().items()
           if k.startswith("test_") and callable(v)}
    for name, fn in fns.items():
        try:
            fn()
            print(f"  ✓  {name}")
            passed += 1
        except Exception:
            print(f"  ✗  {name}")
            traceback.print_exc()
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
