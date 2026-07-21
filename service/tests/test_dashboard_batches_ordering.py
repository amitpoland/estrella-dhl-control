"""list_batches orders by audit.timestamp, not directory mtime.

Regression lock: the list used to be sorted on the batch directory's st_mtime.
mtime advances on ANY later write into the folder (PZ regeneration, email
evidence, an audit patch), so a genuinely older batch jumped to the top of the
observer surface whenever something touched it. Each test below builds batches
whose mtime order is the REVERSE of their timestamp order, so any return to
mtime sorting fails here.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

_SVC = Path(__file__).resolve().parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

from app.api import routes_dashboard as rd  # noqa: E402


def _batch(outputs: Path, batch_id: str, timestamp, mtime: int) -> None:
    """Write a batch whose audit.timestamp and dir mtime can disagree."""
    d = outputs / batch_id
    d.mkdir(parents=True)
    audit = {"batch_id": batch_id, "status": "success"}
    if timestamp is not None:
        audit["timestamp"] = timestamp
    (d / "audit.json").write_text(json.dumps(audit), encoding="utf-8")
    os.utime(d, (mtime, mtime))


@pytest.fixture
def outputs(tmp_path, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    out = tmp_path / "outputs"
    out.mkdir()
    monkeypatch.setattr(rd, "_OUTPUTS", out)
    return out


def _ids(rows):
    return [r["batch_id"] for r in rows]


def test_newest_audit_timestamp_first(outputs):
    # mtime says OLD is newest; audit.timestamp says NEW is newest.
    _batch(outputs, "OLD", "2026-01-01T00:00:00", mtime=9_000_000)
    _batch(outputs, "NEW", "2026-06-01T00:00:00", mtime=1_000_000)
    assert _ids(rd.list_batches()) == ["NEW", "OLD"]


def test_mtime_churn_does_not_reorder(outputs):
    # Touching an old batch (regeneration, evidence write) must not float it up.
    _batch(outputs, "A_2026_01", "2026-01-01T00:00:00", mtime=9_999_999)
    _batch(outputs, "B_2026_03", "2026-03-01T00:00:00", mtime=2_000_000)
    _batch(outputs, "C_2026_05", "2026-05-01T00:00:00", mtime=1_000_000)
    assert _ids(rd.list_batches()) == ["C_2026_05", "B_2026_03", "A_2026_01"]


def test_missing_timestamp_sorts_last(outputs):
    # A batch with no timestamp must sink, never lead the list.
    _batch(outputs, "DATED", "2026-02-01T00:00:00", mtime=1_000_000)
    _batch(outputs, "UNDATED", None, mtime=9_999_999)
    assert _ids(rd.list_batches())[-1] == "UNDATED"


def test_all_runs_is_also_ordered(outputs):
    # ?all=1 bypasses dedup but must still be newest-first.
    _batch(outputs, "R1", "2026-01-01T00:00:00", mtime=9_000_000)
    _batch(outputs, "R2", "2026-04-01T00:00:00", mtime=1_000_000)
    assert _ids(rd.list_batches(all_runs=True)) == ["R2", "R1"]


def test_dedup_keeps_newest_run_by_timestamp(outputs):
    # Same (mrn, doc_no) twice: the surviving row must be the later timestamp,
    # even though the older run has the newer mtime.
    for bid, ts, mt in (("RUN_OLD", "2026-01-01T00:00:00", 9_000_000),
                        ("RUN_NEW", "2026-07-01T00:00:00", 1_000_000)):
        d = outputs / bid
        d.mkdir()
        (d / "audit.json").write_text(json.dumps({
            "batch_id": bid, "status": "success", "timestamp": ts,
            "mrn": "26PLSAME0001", "doc_no": "DOC-1",
        }), encoding="utf-8")
        os.utime(d, (mt, mt))

    # all_runs must be passed explicitly: the signature default is
    # Query(False, alias="all"), and a Query object is TRUTHY when the function
    # is called directly in Python, so `if all_runs: return raw` would skip
    # dedup. FastAPI resolves it to False on the real HTTP path.
    rows = rd.list_batches(all_runs=False)
    assert len(rows) == 1, f"expected dedup to one row, got {_ids(rows)}"
    assert rows[0]["batch_id"] == "RUN_NEW"
