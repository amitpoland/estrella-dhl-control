"""
test_backfill_sad_import_state.py — Tests for the SAD import state backfill tool.

Coverage
--------
  1. dry_run writes nothing to audit.json
  2. apply stamps sad_imported + sad_imported_ts on eligible batch
  3. blocked batch is skipped
  4. already-stamped batch is skipped (idempotent)
  5. batch with no SAD file is skipped
  6. rerun after apply does not duplicate timeline event
  7. ZC429 filename → zc429_received event
  8. generic SAD filename → sad_uploaded event
  9. sad_imported_ts uses file mtime when available
 10. corrupt audit is skipped (no crash)
 11. batch_filter limits scope to single batch
 12. apply returns "stamped" in result; scan returns "eligible"
"""
from __future__ import annotations

import json
import os
import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from app.core import timeline as tl
from app.core.config import settings


# ── Helpers ───────────────────────────────────────────────────────────────────

def _write_audit(batch_dir: Path, data: dict) -> Path:
    batch_dir.mkdir(parents=True, exist_ok=True)
    ap = batch_dir / "audit.json"
    ap.write_text(json.dumps(data), encoding="utf-8")
    return ap


def _read_audit(batch_dir: Path) -> dict:
    return json.loads((batch_dir / "audit.json").read_text(encoding="utf-8"))


def _write_sad(batch_dir: Path, filename: str = "ZC429_26PL_001.pdf") -> Path:
    sad_dir = batch_dir / "source" / "sad"
    sad_dir.mkdir(parents=True, exist_ok=True)
    p = sad_dir / filename
    p.write_bytes(b"%PDF-1.4 fake")
    return p


def _outputs(tmp_path: Path) -> Path:
    d = tmp_path / "outputs"
    d.mkdir(exist_ok=True)
    return d


# Import under test
from app.tools.backfill_sad_import_state import (
    scan_batches,
    apply_backfill,
)


# ── 1. dry-run writes nothing ─────────────────────────────────────────────────

def test_dry_run_writes_nothing(tmp_path):
    outputs = _outputs(tmp_path)
    d = outputs / "B_DRY"
    _write_audit(d, {"status": "partial", "timeline": []})
    _write_sad(d)

    original = _read_audit(d)
    with patch.object(settings, "storage_root", tmp_path):
        scan_batches(outputs)

    assert _read_audit(d) == original, "dry-run must not mutate audit.json"


# ── 2. apply stamps eligible batch ───────────────────────────────────────────

def test_apply_stamps_eligible_batch(tmp_path):
    outputs = _outputs(tmp_path)
    d = outputs / "B_APPLY"
    _write_audit(d, {"status": "partial", "timeline": []})
    _write_sad(d)

    results = apply_backfill(outputs)

    stamped = [r for r in results if r.batch_id == "B_APPLY"]
    assert len(stamped) == 1
    assert stamped[0].action == "stamped"

    audit = _read_audit(d)
    assert audit["sad_imported"] is True
    assert audit["sad_imported_ts"] is not None
    datetime.datetime.fromisoformat(audit["sad_imported_ts"])  # must be valid ISO


# ── 3. blocked batch is skipped ───────────────────────────────────────────────

def test_blocked_batch_skipped(tmp_path):
    outputs = _outputs(tmp_path)
    d = outputs / "B_BLOCKED"
    _write_audit(d, {"status": "blocked", "timeline": []})
    _write_sad(d)

    results = apply_backfill(outputs)

    r = next(x for x in results if x.batch_id == "B_BLOCKED")
    assert r.action == "skipped"
    assert r.skip_reason == "status_blocked"
    assert "sad_imported_ts" not in _read_audit(d)


# ── 4. already-stamped batch skipped (idempotent) ────────────────────────────

def test_already_stamped_batch_skipped(tmp_path):
    outputs = _outputs(tmp_path)
    d = outputs / "B_ALREADY"
    original_ts = "2026-01-01T00:00:00+00:00"
    _write_audit(d, {"status": "partial",
                     "sad_imported_ts": original_ts,
                     "timeline": []})
    _write_sad(d)

    results = apply_backfill(outputs)

    r = next(x for x in results if x.batch_id == "B_ALREADY")
    assert r.action == "skipped"
    assert r.skip_reason == "already_stamped"
    assert _read_audit(d)["sad_imported_ts"] == original_ts, "ts must not be overwritten"


# ── 5. no SAD file → skipped ──────────────────────────────────────────────────

def test_no_sad_file_skipped(tmp_path):
    outputs = _outputs(tmp_path)
    d = outputs / "B_NO_SAD"
    _write_audit(d, {"status": "partial", "timeline": []})
    # No source/sad directory at all

    results = apply_backfill(outputs)

    r = next(x for x in results if x.batch_id == "B_NO_SAD")
    assert r.action == "skipped"
    assert r.skip_reason == "no_sad_file"


# ── 6. rerun does not duplicate timeline event ────────────────────────────────

def test_rerun_does_not_duplicate_event(tmp_path):
    outputs = _outputs(tmp_path)
    d = outputs / "B_RERUN"
    _write_audit(d, {"status": "partial", "timeline": []})
    _write_sad(d, "ZC429_26PL_RERUN.pdf")

    apply_backfill(outputs)
    apply_backfill(outputs)  # second run

    events = [e["event"] for e in _read_audit(d).get("timeline", [])]
    assert events.count(tl.EV_ZC429_RECEIVED) == 1, "event must not be duplicated"


# ── 7. ZC429 filename → zc429_received ───────────────────────────────────────

def test_zc429_filename_emits_zc429_received(tmp_path):
    outputs = _outputs(tmp_path)
    d = outputs / "B_ZC429"
    _write_audit(d, {"status": "partial", "timeline": []})
    _write_sad(d, "ZC429_26PL44302D000TEST_1_PL.pdf")

    apply_backfill(outputs)

    events = [e["event"] for e in _read_audit(d).get("timeline", [])]
    assert tl.EV_ZC429_RECEIVED in events
    assert tl.EV_SAD_UPLOADED not in events


# ── 8. generic SAD filename → sad_uploaded ───────────────────────────────────

def test_generic_sad_filename_emits_sad_uploaded(tmp_path):
    outputs = _outputs(tmp_path)
    d = outputs / "B_SAD_GEN"
    _write_audit(d, {"status": "partial", "timeline": []})
    _write_sad(d, "Poswiadczone_zgloszenie_celne.pdf")

    apply_backfill(outputs)

    events = [e["event"] for e in _read_audit(d).get("timeline", [])]
    assert tl.EV_SAD_UPLOADED in events
    assert tl.EV_ZC429_RECEIVED not in events


# ── 9. sad_imported_ts uses file mtime when available ────────────────────────

def test_stamp_uses_file_mtime(tmp_path):
    outputs = _outputs(tmp_path)
    d = outputs / "B_MTIME"
    _write_audit(d, {"status": "partial", "timeline": []})
    sad_path = _write_sad(d, "ZC429_MTIME.pdf")

    # Force a specific mtime (2025-06-15T12:00:00 UTC = Unix 1750000000 approx)
    known_ts = 1750000000.0
    os.utime(sad_path, (known_ts, known_ts))

    apply_backfill(outputs)

    ts = _read_audit(d)["sad_imported_ts"]
    assert ts is not None
    dt = datetime.datetime.fromisoformat(ts)
    # Should be within 2 seconds of the mtime we set
    expected = datetime.datetime.fromtimestamp(known_ts, tz=datetime.timezone.utc)
    assert abs((dt - expected).total_seconds()) < 2


# ── 10. corrupt audit is skipped, no crash ───────────────────────────────────

def test_corrupt_audit_skipped_no_crash(tmp_path):
    outputs = _outputs(tmp_path)
    d = outputs / "B_CORRUPT"
    d.mkdir(parents=True, exist_ok=True)
    (d / "audit.json").write_text("{not valid json{{", encoding="utf-8")
    _write_sad(d)

    results = apply_backfill(outputs)   # must not raise

    r = next(x for x in results if x.batch_id == "B_CORRUPT")
    assert r.action == "skipped"
    assert "corrupt_audit" in r.skip_reason


# ── 11. batch_filter limits scope ────────────────────────────────────────────

def test_batch_filter_limits_scope(tmp_path):
    outputs = _outputs(tmp_path)
    for name in ("B_FILTER_1", "B_FILTER_2", "B_FILTER_3"):
        d = outputs / name
        _write_audit(d, {"status": "partial", "timeline": []})
        _write_sad(d)

    results = apply_backfill(outputs, batch_filter="B_FILTER_2")

    assert len(results) == 1
    assert results[0].batch_id == "B_FILTER_2"
    assert results[0].action == "stamped"

    # The other two must be untouched
    for name in ("B_FILTER_1", "B_FILTER_3"):
        assert "sad_imported_ts" not in _read_audit(outputs / name)


# ── 12. scan returns "eligible"; apply returns "stamped" ─────────────────────

def test_scan_eligible_vs_apply_stamped(tmp_path):
    outputs = _outputs(tmp_path)
    d = outputs / "B_LABEL"
    _write_audit(d, {"status": "partial", "timeline": []})
    _write_sad(d)

    scan_results = scan_batches(outputs)
    r_scan = next(x for x in scan_results if x.batch_id == "B_LABEL")
    assert r_scan.action == "eligible", "scan should report 'eligible', not write"
    assert "sad_imported_ts" not in _read_audit(d), "scan must not write"

    apply_results = apply_backfill(outputs)
    r_apply = next(x for x in apply_results if x.batch_id == "B_LABEL")
    assert r_apply.action == "stamped"
    assert _read_audit(d)["sad_imported"] is True
