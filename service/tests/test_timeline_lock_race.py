"""timeline.log_event serialises its audit.json write under batch_write_lock.

The append is a whole-file read-modify-write that used to run unlocked, so a
concurrent batch_write_lock holder could clobber it (or be clobbered). It now
takes the lock — but the lock is non-reentrant and log_event is called both
inside and outside a held lock, so it must acquire only when the thread does
not already hold it. These tests pin both halves: no self-deadlock, and real
cross-thread serialisation.
"""
from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

import pytest

_SVC = Path(__file__).resolve().parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

from app.core import timeline as tl                       # noqa: E402
from app.utils.batch_lock import batch_write_lock, holds_batch_lock  # noqa: E402


@pytest.fixture
def batch(tmp_path, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    d = tmp_path / "outputs" / "SHIPMENT_LOGRACE"
    d.mkdir(parents=True)
    ap = d / "audit.json"
    ap.write_text(json.dumps({"batch_id": "SHIPMENT_LOGRACE"}), encoding="utf-8")
    return "SHIPMENT_LOGRACE", ap


def _timeline(ap):
    return json.loads(ap.read_text(encoding="utf-8")).get("timeline", [])


def test_log_event_writes_the_entry(batch):
    _bid, ap = batch
    tl.log_event(ap, "EV_TEST", "unit")
    tled = _timeline(ap)
    assert len(tled) == 1 and tled[0]["event"] == "EV_TEST"


def test_holds_batch_lock_tracks_acquisition(batch):
    bid, _ap = batch
    assert holds_batch_lock(bid) is False
    with batch_write_lock(bid):
        assert holds_batch_lock(bid) is True
    assert holds_batch_lock(bid) is False


def test_log_event_inside_lock_does_not_deadlock(batch):
    """The reentrancy hazard: a caller holding the lock then logging.

    Non-reentrant lock + unconditional acquire = hang. This must return fast.
    """
    bid, ap = batch
    done = threading.Event()

    def _run():
        with batch_write_lock(bid):
            # mutate + log, the real in-lock pattern
            a = json.loads(ap.read_text(encoding="utf-8"))
            a["status"] = "processing"
            ap.write_text(json.dumps(a), encoding="utf-8")
            tl.log_event(ap, "EV_INSIDE", "unit")   # would deadlock if unguarded
        done.set()

    t = threading.Thread(target=_run)
    t.start()
    assert done.wait(timeout=10), "log_event inside batch_write_lock deadlocked"
    t.join(timeout=5)

    a = json.loads(ap.read_text(encoding="utf-8"))
    assert a["status"] == "processing"          # writer's field survived
    assert [e["event"] for e in a.get("timeline", [])] == ["EV_INSIDE"]


def test_nested_batch_write_lock_same_thread_does_not_deadlock(batch):
    bid, _ap = batch
    with batch_write_lock(bid):
        with batch_write_lock(bid):   # re-entry on same thread
            assert holds_batch_lock(bid) is True
    assert holds_batch_lock(bid) is False


def test_concurrent_writer_and_log_event_do_not_lose_writes(batch):
    """A batch_write_lock holder and a log_event from another thread must
    serialise: the writer's field change AND the timeline entry both survive."""
    bid, ap = batch
    started = threading.Event()

    def _slow_writer():
        with batch_write_lock(bid):
            a = json.loads(ap.read_text(encoding="utf-8"))
            started.set()
            time.sleep(0.3)                     # hold the lock across the window
            a["writer_field"] = "kept"
            ap.write_text(json.dumps(a), encoding="utf-8")

    w = threading.Thread(target=_slow_writer)
    w.start()
    started.wait(timeout=5)
    # This thread does not hold the lock, so log_event must block on the writer
    tl.log_event(ap, "EV_CONCURRENT", "unit")
    w.join(timeout=5)

    a = json.loads(ap.read_text(encoding="utf-8"))
    assert a.get("writer_field") == "kept", "writer's field was clobbered by log_event"
    assert [e["event"] for e in a.get("timeline", [])] == ["EV_CONCURRENT"], \
        "timeline entry was clobbered by the writer"


def test_log_event_missing_audit_is_noop(batch):
    _bid, ap = batch
    ap.unlink()
    tl.log_event(ap, "EV_GONE", "unit")   # must not raise
