"""Unified piece timeline composition tests — Phase B.2.

The piece view merges three append-only event sources into a single
chronologically-sorted timeline. These tests patch each reader at the
service boundary to inject deterministic data and assert the merge,
sort, tie-break, and degrade behaviour.

Single-writer discipline is enforced by a source-grep test: the
inventory_piece_view module must never call INSERT/UPDATE/DELETE.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_SVC = Path(__file__).resolve().parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

from app.services import inventory_piece_view as ipv  # noqa: E402


# ── Fixtures ──────────────────────────────────────────────────────────────

def _state_row(scan_code: str = "S1", state: str = "WAREHOUSE_STOCK"):
    return {
        "id":           "state-row-1",
        "scan_code":    scan_code,
        "state":        state,
        "product_code": "P1",
        "design_no":    "D1",
        "batch_id":     "B1",
        "updated_at":   "2026-05-12T10:00:00Z",
        "updated_by":   "op",
        "note":         "",
    }


def _location_row(loc: str = "A-12-3"):
    return {
        "id":               "loc-1",
        "scan_code":        "S1",
        "current_location": loc,
        "current_status":   "stored",
        "updated_at":       "2026-05-12T10:00:00Z",
        "updated_by":       "op",
    }


def _lifecycle_event(eid, occurred_at, frm, to, trigger="warehouse_receive"):
    return {
        "id":          eid,
        "scan_code":   "S1",
        "from_state":  frm,
        "to_state":    to,
        "trigger":     trigger,
        "occurred_at": occurred_at,
        "operator":    "op",
        "note":        "",
    }


def _movement_event(eid, event_time, frm, to, action="MOVE"):
    return {
        "id":            eid,
        "batch_id":      "B1",
        "scan_code":     "S1",
        "action":        action,
        "from_location": frm,
        "to_location":   to,
        "operator":      "op",
        "event_time":    event_time,
        "note":          "",
        "created_at":    event_time,
        "idempotency_key": "k-" + eid,
    }


def _sample_event(eid, occurred_at, direction, **extra):
    base = {
        "id":                     eid,
        "scan_code":              "S1",
        "direction":              direction,
        "operator":               "op",
        "recipient_client_name":  "",
        "recipient_client_id":    "",
        "sample_reason":          "",
        "expected_return_date":   "",
        "notes":                  "",
        "idempotency_key":        "k-" + eid,
        "linked_state_event_id":  "",
        "linked_origin_event_id": "",
        "occurred_at":            occurred_at,
        "created_at":             occurred_at,
    }
    base.update(extra)
    return base


# ── Envelope shape ────────────────────────────────────────────────────────

def test_envelope_contains_new_fields():
    """Phase B.2 envelope MUST include timeline, location, limitations."""
    with patch.object(ipv.inventory_state_engine, "get_state", return_value=None), \
         patch.object(ipv.warehouse_db,            "get_current_location",  return_value=None), \
         patch.object(ipv.inventory_state_engine, "get_history",           return_value=[]), \
         patch.object(ipv.warehouse_db,            "get_movement_history",  return_value=[]), \
         patch.object(ipv.warehouse_db,            "get_sample_out_history", return_value=[]):
        d = ipv.get_piece_detail("S-NOPE")
    for k in ("piece_id", "as_of", "found", "degraded",
              "state", "location", "history", "timeline", "limitations"):
        assert k in d, f"Missing envelope key {k!r}"
    assert d["found"] is False
    assert d["state"] is None
    assert d["location"] is None
    assert d["history"]     == []
    assert d["timeline"]    == []
    assert d["limitations"] == []
    assert d["degraded"]    is False


def test_legacy_history_field_preserved_as_lifecycle_rows():
    """Existing UI/tests that read pieceDetail.history must keep working.
    `history` MUST equal the raw lifecycle rows from
    inventory_state_engine.get_history (NOT the timeline subset). This
    preserves byte-for-byte compatibility for one release."""
    rows = [_lifecycle_event("ev-1", "2026-05-01T09:00:00Z", "",
                              "PURCHASE_TRANSIT", "pz_generated")]
    with patch.object(ipv.inventory_state_engine, "get_state",            return_value=_state_row()), \
         patch.object(ipv.warehouse_db,            "get_current_location",  return_value=None), \
         patch.object(ipv.inventory_state_engine, "get_history",           return_value=rows), \
         patch.object(ipv.warehouse_db,            "get_movement_history",  return_value=[]), \
         patch.object(ipv.warehouse_db,            "get_sample_out_history", return_value=[]):
        d = ipv.get_piece_detail("S1")
    assert d["history"] == rows, "history must be byte-equal to lifecycle reader output"


# ── Three-source merge ────────────────────────────────────────────────────

def test_timeline_merges_three_sources():
    lc = [_lifecycle_event("L1", "2026-05-01T09:00:00Z", "",
                            "PURCHASE_TRANSIT", "pz_generated"),
          _lifecycle_event("L2", "2026-05-02T08:00:00Z",
                            "PURCHASE_TRANSIT", "WAREHOUSE_STOCK",
                            "warehouse_receive")]
    mv = [_movement_event("M1", "2026-05-02T14:00:00Z", "RECEIVING", "A-12-3")]
    sm = [_sample_event("S1", "2026-05-09T11:00:00Z", "out",
                         recipient_client_name="Estrella Boutique",
                         sample_reason="customer_review",
                         expected_return_date="2026-05-23")]
    with patch.object(ipv.inventory_state_engine, "get_state",            return_value=_state_row()), \
         patch.object(ipv.warehouse_db,            "get_current_location",  return_value=_location_row()), \
         patch.object(ipv.inventory_state_engine, "get_history",           return_value=lc), \
         patch.object(ipv.warehouse_db,            "get_movement_history",  return_value=mv), \
         patch.object(ipv.warehouse_db,            "get_sample_out_history", return_value=sm):
        d = ipv.get_piece_detail("S1")
    kinds = [e["kind"] for e in d["timeline"]]
    assert kinds == ["lifecycle", "lifecycle", "movement", "sample"], \
        f"timeline order wrong: {kinds}"
    assert d["degraded"] is False
    assert d["limitations"] == []


def test_timeline_kind_discriminator_in_each_entry():
    lc = [_lifecycle_event("L1", "2026-05-01T09:00:00Z", "",
                            "PURCHASE_TRANSIT", "pz_generated")]
    mv = [_movement_event("M1", "2026-05-02T14:00:00Z", "", "A-12")]
    sm = [_sample_event("S1", "2026-05-09T11:00:00Z", "out",
                         recipient_client_name="X")]
    with patch.object(ipv.inventory_state_engine, "get_state",            return_value=_state_row()), \
         patch.object(ipv.warehouse_db,            "get_current_location",  return_value=None), \
         patch.object(ipv.inventory_state_engine, "get_history",           return_value=lc), \
         patch.object(ipv.warehouse_db,            "get_movement_history",  return_value=mv), \
         patch.object(ipv.warehouse_db,            "get_sample_out_history", return_value=sm):
        d = ipv.get_piece_detail("S1")
    for e in d["timeline"]:
        assert e["kind"] in {"lifecycle", "movement", "sample"}
        assert "occurred_at" in e
        assert "summary"     in e
        assert "detail"      in e
        assert "event_id"    in e


# ── Summary formats ───────────────────────────────────────────────────────

def test_lifecycle_summary_with_from_state():
    lc = [_lifecycle_event("L1", "2026-05-02T08:00:00Z",
                            "PURCHASE_TRANSIT", "WAREHOUSE_STOCK")]
    with patch.object(ipv.inventory_state_engine, "get_state",            return_value=_state_row()), \
         patch.object(ipv.warehouse_db,            "get_current_location",  return_value=None), \
         patch.object(ipv.inventory_state_engine, "get_history",           return_value=lc), \
         patch.object(ipv.warehouse_db,            "get_movement_history",  return_value=[]), \
         patch.object(ipv.warehouse_db,            "get_sample_out_history", return_value=[]):
        d = ipv.get_piece_detail("S1")
    assert d["timeline"][0]["summary"] == "PURCHASE_TRANSIT -> WAREHOUSE_STOCK"


def test_lifecycle_summary_first_event_no_from_state():
    lc = [_lifecycle_event("L1", "2026-05-01T09:00:00Z", "", "PURCHASE_TRANSIT")]
    with patch.object(ipv.inventory_state_engine, "get_state",            return_value=_state_row()), \
         patch.object(ipv.warehouse_db,            "get_current_location",  return_value=None), \
         patch.object(ipv.inventory_state_engine, "get_history",           return_value=lc), \
         patch.object(ipv.warehouse_db,            "get_movement_history",  return_value=[]), \
         patch.object(ipv.warehouse_db,            "get_sample_out_history", return_value=[]):
        d = ipv.get_piece_detail("S1")
    assert d["timeline"][0]["summary"] == "-> PURCHASE_TRANSIT"


def test_movement_summary_with_from_location():
    mv = [_movement_event("M1", "2026-05-02T14:00:00Z", "RECEIVING", "A-12-3")]
    with patch.object(ipv.inventory_state_engine, "get_state",            return_value=_state_row()), \
         patch.object(ipv.warehouse_db,            "get_current_location",  return_value=None), \
         patch.object(ipv.inventory_state_engine, "get_history",           return_value=[]), \
         patch.object(ipv.warehouse_db,            "get_movement_history",  return_value=mv), \
         patch.object(ipv.warehouse_db,            "get_sample_out_history", return_value=[]):
        d = ipv.get_piece_detail("S1")
    assert d["timeline"][0]["summary"] == "moved RECEIVING -> A-12-3"


def test_movement_summary_first_move_no_from():
    mv = [_movement_event("M1", "2026-05-02T14:00:00Z", "", "A-12-3")]
    with patch.object(ipv.inventory_state_engine, "get_state",            return_value=_state_row()), \
         patch.object(ipv.warehouse_db,            "get_current_location",  return_value=None), \
         patch.object(ipv.inventory_state_engine, "get_history",           return_value=[]), \
         patch.object(ipv.warehouse_db,            "get_movement_history",  return_value=mv), \
         patch.object(ipv.warehouse_db,            "get_sample_out_history", return_value=[]):
        d = ipv.get_piece_detail("S1")
    assert d["timeline"][0]["summary"] == "moved to A-12-3"


def test_sample_out_summary_includes_recipient_and_reason():
    sm = [_sample_event("S1", "2026-05-09T11:00:00Z", "out",
                         recipient_client_name="Estrella Boutique",
                         sample_reason="customer_review",
                         expected_return_date="2026-05-23")]
    with patch.object(ipv.inventory_state_engine, "get_state",            return_value=_state_row()), \
         patch.object(ipv.warehouse_db,            "get_current_location",  return_value=None), \
         patch.object(ipv.inventory_state_engine, "get_history",           return_value=[]), \
         patch.object(ipv.warehouse_db,            "get_movement_history",  return_value=[]), \
         patch.object(ipv.warehouse_db,            "get_sample_out_history", return_value=sm):
        d = ipv.get_piece_detail("S1")
    assert d["timeline"][0]["summary"] == \
        "sample-out to Estrella Boutique (customer_review)"
    # Detail must include the expected_return_date so the drawer can
    # render the recipient + due date inline.
    assert d["timeline"][0]["detail"]["expected_return_date"] != ""


def test_sample_return_summary_format():
    sm = [_sample_event("S1", "2026-05-15T11:00:00Z", "return",
                         linked_origin_event_id="origin-1")]
    with patch.object(ipv.inventory_state_engine, "get_state",            return_value=_state_row()), \
         patch.object(ipv.warehouse_db,            "get_current_location",  return_value=None), \
         patch.object(ipv.inventory_state_engine, "get_history",           return_value=[]), \
         patch.object(ipv.warehouse_db,            "get_movement_history",  return_value=[]), \
         patch.object(ipv.warehouse_db,            "get_sample_out_history", return_value=sm):
        d = ipv.get_piece_detail("S1")
    assert d["timeline"][0]["summary"] == "sample-return to warehouse"
    assert d["timeline"][0]["detail"]["linked_origin_event_id"] == "origin-1"


# ── Sort + tie-break ──────────────────────────────────────────────────────

def test_timeline_ascending_by_occurred_at():
    lc = [_lifecycle_event("L1", "2026-05-01T09:00:00Z", "", "PURCHASE_TRANSIT")]
    mv = [_movement_event("M1", "2026-05-04T14:00:00Z", "", "A-1")]
    sm = [_sample_event("S1", "2026-05-02T11:00:00Z", "out",
                         recipient_client_name="X")]
    with patch.object(ipv.inventory_state_engine, "get_state",            return_value=_state_row()), \
         patch.object(ipv.warehouse_db,            "get_current_location",  return_value=None), \
         patch.object(ipv.inventory_state_engine, "get_history",           return_value=lc), \
         patch.object(ipv.warehouse_db,            "get_movement_history",  return_value=mv), \
         patch.object(ipv.warehouse_db,            "get_sample_out_history", return_value=sm):
        d = ipv.get_piece_detail("S1")
    times = [e["occurred_at"] for e in d["timeline"]]
    assert times == sorted(times)


def test_tiebreak_lifecycle_before_movement_before_sample():
    """Same occurred_at → kind priority lifecycle < movement < sample."""
    ts = "2026-05-02T08:00:00Z"
    lc = [_lifecycle_event("L1", ts, "PURCHASE_TRANSIT", "WAREHOUSE_STOCK")]
    mv = [_movement_event("M1", ts, "", "A-1")]
    sm = [_sample_event("S1", ts, "out", recipient_client_name="X")]
    with patch.object(ipv.inventory_state_engine, "get_state",            return_value=_state_row()), \
         patch.object(ipv.warehouse_db,            "get_current_location",  return_value=None), \
         patch.object(ipv.inventory_state_engine, "get_history",           return_value=lc), \
         patch.object(ipv.warehouse_db,            "get_movement_history",  return_value=mv), \
         patch.object(ipv.warehouse_db,            "get_sample_out_history", return_value=sm):
        d = ipv.get_piece_detail("S1")
    kinds = [e["kind"] for e in d["timeline"]]
    assert kinds == ["lifecycle", "movement", "sample"], \
        f"tie-break failed: {kinds}"


# ── Degrade behaviour ─────────────────────────────────────────────────────

def test_degraded_when_movement_reader_raises():
    """If only the movement reader raises, lifecycle + sample still
    contribute their events; degraded=True; limitations names the
    failing source."""
    lc = [_lifecycle_event("L1", "2026-05-01T09:00:00Z", "", "PURCHASE_TRANSIT")]
    sm = [_sample_event("S1", "2026-05-09T11:00:00Z", "out",
                         recipient_client_name="X")]
    with patch.object(ipv.inventory_state_engine, "get_state",            return_value=_state_row()), \
         patch.object(ipv.warehouse_db,            "get_current_location",  return_value=None), \
         patch.object(ipv.inventory_state_engine, "get_history",           return_value=lc), \
         patch.object(ipv.warehouse_db,            "get_movement_history",  side_effect=RuntimeError("db not ready")), \
         patch.object(ipv.warehouse_db,            "get_sample_out_history", return_value=sm):
        d = ipv.get_piece_detail("S1")
    assert d["degraded"] is True
    assert any("inventory_movement_events" in l for l in d["limitations"])
    kinds = sorted({e["kind"] for e in d["timeline"]})
    assert kinds == ["lifecycle", "sample"]


def test_degraded_when_sample_reader_raises():
    with patch.object(ipv.inventory_state_engine, "get_state",            return_value=_state_row()), \
         patch.object(ipv.warehouse_db,            "get_current_location",  return_value=None), \
         patch.object(ipv.inventory_state_engine, "get_history",           return_value=[]), \
         patch.object(ipv.warehouse_db,            "get_movement_history",  return_value=[]), \
         patch.object(ipv.warehouse_db,            "get_sample_out_history", side_effect=RuntimeError("missing table")):
        d = ipv.get_piece_detail("S1")
    assert d["degraded"] is True
    assert any("sample_out_events" in l for l in d["limitations"])
    assert d["timeline"] == []


def test_state_reader_failure_fails_envelope_safely():
    """When the state reader itself fails, the envelope returns
    degraded=True, found=False, and empty everything — but NEVER raises
    out of get_piece_detail."""
    with patch.object(ipv.inventory_state_engine, "get_state",
                       side_effect=RuntimeError("warehouse_db not initialised")):
        d = ipv.get_piece_detail("S1")
    assert d["degraded"] is True
    assert d["found"]    is False
    assert d["state"]    is None
    assert d["location"] is None
    assert d["timeline"] == []
    assert d["history"]  == []
    assert any("inventory_state" in l for l in d["limitations"])


# ── Location snapshot ─────────────────────────────────────────────────────

def test_location_field_carries_current_location_row():
    loc = _location_row("A-12-3")
    with patch.object(ipv.inventory_state_engine, "get_state",            return_value=_state_row()), \
         patch.object(ipv.warehouse_db,            "get_current_location",  return_value=loc), \
         patch.object(ipv.inventory_state_engine, "get_history",           return_value=[]), \
         patch.object(ipv.warehouse_db,            "get_movement_history",  return_value=[]), \
         patch.object(ipv.warehouse_db,            "get_sample_out_history", return_value=[]):
        d = ipv.get_piece_detail("S1")
    assert d["location"] == loc
    assert d["location"]["current_location"] == "A-12-3"


def test_location_none_when_unknown_scan():
    with patch.object(ipv.inventory_state_engine, "get_state",            return_value=None), \
         patch.object(ipv.warehouse_db,            "get_current_location",  return_value=None), \
         patch.object(ipv.inventory_state_engine, "get_history",           return_value=[]), \
         patch.object(ipv.warehouse_db,            "get_movement_history",  return_value=[]), \
         patch.object(ipv.warehouse_db,            "get_sample_out_history", return_value=[]):
        d = ipv.get_piece_detail("S-NOPE")
    assert d["location"] is None


# ── Single-writer / source invariants ─────────────────────────────────────

def test_piece_view_module_has_no_writes():
    """The piece view composes readers only. No INSERT/UPDATE/DELETE."""
    src = inspect.getsource(ipv)
    code_lines = []
    in_docstring = False
    for line in src.splitlines():
        stripped = line.strip()
        if stripped.startswith('"""') or stripped.startswith("'''"):
            if stripped.count('"""') == 2 or stripped.count("'''") == 2:
                pass
            else:
                in_docstring = not in_docstring
            continue
        if in_docstring or stripped.startswith("#"):
            continue
        code_lines.append(line)
    code_only = "\n".join(code_lines)
    for forbidden in ('"INSERT INTO', "'INSERT INTO",
                      '"UPDATE ',     "'UPDATE ",
                      '"DELETE FROM', "'DELETE FROM",
                      ".add(", ".commit(", ".flush(", "executemany("):
        assert forbidden not in code_only, (
            f"piece_view must not write: {forbidden!r}"
        )


def test_sort_key_kind_priority_matches_design():
    """Tie-break order lifecycle(0) < movement(1) < sample(2). Documented
    in PIECE_TIMELINE_DESIGN.md §4.2; matched in inventory_piece_view."""
    assert ipv._KIND_PRIORITY["lifecycle"] < ipv._KIND_PRIORITY["movement"]
    assert ipv._KIND_PRIORITY["movement"]  < ipv._KIND_PRIORITY["sample"]
