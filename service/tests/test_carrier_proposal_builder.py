"""
test_carrier_proposal_builder.py — DL-D2 read-only proposal builder.

Required coverage:
  1. Deterministic proposal IDs.
  2. create-shipment proposal enabled for batch with no shipments.
  3. create-shipment proposal disabled when active shipment exists.
  4. create-shipment proposal allowed again when only terminal
     shipment(s) exist.
  5. mark-label-printed enabled only for ``label_created``.
  6. mark-handed-to-carrier enabled only for ``label_printed``.
  7. cancel enabled only for pre-handover states.
  8. cancel disabled after handed_to_carrier.
  9. cancel disabled for terminal states.
  10. build_proposals_for_batch emits correct proposals for a batch.
  11. build_all_open_proposals reads registry and emits proposals
      without writing.
  12. proposal shape contains all required keys.
  13. severity is one of info / warning / blocked.
  14. Source-grep — no FastAPI / Flask import.
  15. Source-grep — no carrier_coordinator import.
  16. Source-grep — no adapter import.
  17. Source-grep — no requests / httpx import.
  18. Source-grep — no DB write functions referenced (upsert_shipment,
      record_transition).
"""
from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.services.carrier import carrier_proposal_builder as pb
from app.services.carrier import carrier_shipment_db as csdb
from app.services.carrier import carrier_state_engine as cse
from app.services.carrier.base import CARRIER_DHL


_BUILDER_FILE = (
    Path(__file__).resolve().parents[1]
    / "app" / "services" / "carrier" / "carrier_proposal_builder.py"
)


# ── Required keys + valid severities ────────────────────────────────────────

REQUIRED_KEYS = {
    "proposal_id", "action", "carrier", "batch_id", "awb", "state",
    "title", "reason", "severity", "enabled", "blocking_reasons", "metadata",
}


@pytest.fixture(scope="module")
def builder_src() -> str:
    return _BUILDER_FILE.read_text(encoding="utf-8")


@pytest.fixture()
def db(tmp_path) -> Path:
    """Fresh carrier shipments DB; returns the db path."""
    p = tmp_path / "carrier.db"
    csdb.init_db(p)
    return p


def _row(**overrides):
    """Synthetic shipment row (matches the DB schema shape)."""
    base = {
        "id":            "ship-uuid-1",
        "carrier":       CARRIER_DHL,
        "awb":           "DHLSTUB000001",
        "state":         cse.LABEL_CREATED,
        "batch_id":      "B-1",
        "label_sha256":  "a" * 64,
        "manifest_path": "/tmp/m.json",
        "created_at":    "2026-04-01T10:00:00+00:00",
        "updated_at":    "2026-04-01T10:00:00+00:00",
    }
    base.update(overrides)
    return base


# ── 1. Deterministic IDs ────────────────────────────────────────────────────

def test_proposal_ids_are_deterministic_for_same_inputs():
    p1 = pb.build_create_shipment_proposal("B-DET-1")
    p2 = pb.build_create_shipment_proposal("B-DET-1")
    assert p1["proposal_id"] == p2["proposal_id"]
    # And the id encodes the action so logs are readable
    assert p1["proposal_id"].startswith(f"carrier-{pb.ACTION_CREATE_SHIPMENT}-")


def test_proposal_ids_differ_when_batch_differs():
    p1 = pb.build_create_shipment_proposal("B-DET-A")
    p2 = pb.build_create_shipment_proposal("B-DET-B")
    assert p1["proposal_id"] != p2["proposal_id"]


def test_proposal_ids_differ_when_state_differs():
    """Same shipment in different states yields different proposal ids
    so an action+identity+state tuple uniquely keys the proposal."""
    a = pb.build_cancel_shipment_proposal(_row(state=cse.LABEL_CREATED))
    b = pb.build_cancel_shipment_proposal(_row(state=cse.LABEL_PRINTED))
    assert a["proposal_id"] != b["proposal_id"]


# ── 2. create_shipment enabled when batch has no shipments ──────────────────

def test_create_shipment_proposal_enabled_for_empty_batch():
    p = pb.build_create_shipment_proposal("B-EMPTY")
    assert p["enabled"] is True
    assert p["severity"] == pb.SEVERITY_INFO
    assert p["blocking_reasons"] == []
    assert p["batch_id"] == "B-EMPTY"


# ── 3. create_shipment blocked when active shipment exists ──────────────────

def test_create_shipment_proposal_blocked_when_active_exists():
    rows = [_row(state=cse.LABEL_CREATED, awb="DHLSTUB000099")]
    p = pb.build_create_shipment_proposal("B-1", existing_shipments=rows)
    assert p["enabled"] is False
    assert p["severity"] == pb.SEVERITY_BLOCKED
    assert p["blocking_reasons"], "must list active shipment as blocker"
    assert any("DHLSTUB000099" in r for r in p["blocking_reasons"])
    assert "DHLSTUB000099" in p["metadata"]["active_shipments"]


# ── 4. create_shipment allowed again when only terminal shipments exist ─────

@pytest.mark.parametrize("term_state", [cse.DELIVERED, cse.RETURNED, cse.VOIDED])
def test_create_shipment_proposal_allowed_after_terminal(term_state):
    rows = [_row(state=term_state, awb="DHLSTUB000010")]
    p = pb.build_create_shipment_proposal("B-2", existing_shipments=rows)
    assert p["enabled"] is True
    assert p["severity"] == pb.SEVERITY_INFO
    assert p["blocking_reasons"] == []
    assert "DHLSTUB000010" in p["metadata"]["terminal_shipments"]


def test_create_shipment_blank_batch_id_raises():
    with pytest.raises(ValueError):
        pb.build_create_shipment_proposal("")


# ── 5. mark-label-printed only for label_created ───────────────────────────

def test_mark_label_printed_enabled_for_label_created():
    p = pb.build_mark_label_printed_proposal(_row(state=cse.LABEL_CREATED))
    assert p["enabled"] is True
    assert p["severity"] == pb.SEVERITY_INFO
    assert p["state"] == cse.LABEL_CREATED


@pytest.mark.parametrize("state", [
    cse.PRE_AWB, cse.AWB_ISSUED, cse.LABEL_PRINTED,
    cse.HANDED_TO_CARRIER, cse.IN_TRANSIT, cse.DELIVERED,
    cse.RETURNED, cse.VOIDED,
])
def test_mark_label_printed_blocked_for_other_states(state):
    p = pb.build_mark_label_printed_proposal(_row(state=state))
    assert p["enabled"] is False
    assert p["severity"] == pb.SEVERITY_BLOCKED
    assert p["blocking_reasons"]
    assert cse.LABEL_CREATED in p["blocking_reasons"][0]


# ── 6. mark-handed-to-carrier only for label_printed ───────────────────────

def test_mark_handed_to_carrier_enabled_for_label_printed():
    p = pb.build_mark_handed_to_carrier_proposal(_row(state=cse.LABEL_PRINTED))
    assert p["enabled"] is True
    assert p["severity"] == pb.SEVERITY_INFO


@pytest.mark.parametrize("state", [
    cse.PRE_AWB, cse.AWB_ISSUED, cse.LABEL_CREATED,
    cse.HANDED_TO_CARRIER, cse.IN_TRANSIT, cse.DELIVERED,
    cse.RETURNED, cse.VOIDED,
])
def test_mark_handed_to_carrier_blocked_for_other_states(state):
    p = pb.build_mark_handed_to_carrier_proposal(_row(state=state))
    assert p["enabled"] is False
    assert p["severity"] == pb.SEVERITY_BLOCKED
    assert cse.LABEL_PRINTED in p["blocking_reasons"][0]


# ── 7. cancel enabled only for pre-handover states ─────────────────────────

@pytest.mark.parametrize("state", [
    cse.AWB_ISSUED, cse.LABEL_CREATED, cse.LABEL_PRINTED,
])
def test_cancel_enabled_for_pre_handover(state):
    p = pb.build_cancel_shipment_proposal(_row(state=state))
    assert p["enabled"] is True
    assert p["severity"] == pb.SEVERITY_INFO
    assert p["blocking_reasons"] == []


def test_cancel_severity_warning_when_stale():
    """If updated_at is older than stale_hours, severity → warning."""
    old = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
    p = pb.build_cancel_shipment_proposal(
        _row(state=cse.LABEL_CREATED, updated_at=old),
        stale_hours=24.0,
    )
    assert p["enabled"] is True
    assert p["severity"] == pb.SEVERITY_WARNING
    assert p["metadata"]["is_stale"] is True
    assert p["metadata"]["hours_since_update"] is not None
    assert p["metadata"]["hours_since_update"] >= 24


def test_cancel_severity_info_when_not_stale_yet():
    fresh = datetime.now(timezone.utc).isoformat()
    p = pb.build_cancel_shipment_proposal(
        _row(state=cse.LABEL_CREATED, updated_at=fresh),
        stale_hours=24.0,
    )
    assert p["severity"] == pb.SEVERITY_INFO
    assert p["metadata"]["is_stale"] is False


# ── 8. cancel disabled after handed_to_carrier ─────────────────────────────

@pytest.mark.parametrize("state", [
    cse.HANDED_TO_CARRIER, cse.IN_TRANSIT,
])
def test_cancel_blocked_after_handover(state):
    p = pb.build_cancel_shipment_proposal(_row(state=state))
    assert p["enabled"] is False
    assert p["severity"] == pb.SEVERITY_BLOCKED
    assert "carrier" in p["blocking_reasons"][0].lower()


# ── 9. cancel disabled for terminal states ─────────────────────────────────

@pytest.mark.parametrize("state", [cse.DELIVERED, cse.RETURNED])
def test_cancel_blocked_for_terminal_non_voided(state):
    p = pb.build_cancel_shipment_proposal(_row(state=state))
    assert p["enabled"] is False
    assert p["severity"] == pb.SEVERITY_BLOCKED


def test_cancel_blocked_for_already_voided():
    p = pb.build_cancel_shipment_proposal(_row(state=cse.VOIDED))
    assert p["enabled"] is False
    assert p["severity"] == pb.SEVERITY_BLOCKED
    assert any("voided" in r.lower() for r in p["blocking_reasons"])


# ── 10. build_proposals_for_batch emits correct set ────────────────────────

def test_build_proposals_for_batch_no_shipments(db):
    out = pb.build_proposals_for_batch(db, "B-NEW")
    actions = [p["action"] for p in out]
    # Only a create_shipment proposal — no per-shipment proposals exist.
    assert actions == [pb.ACTION_CREATE_SHIPMENT]
    assert out[0]["enabled"] is True


def test_build_proposals_for_batch_with_label_created(db):
    csdb.upsert_shipment(
        carrier=CARRIER_DHL, awb="LBL-1",
        state=cse.LABEL_CREATED, batch_id="B-LBL",
    )
    out = pb.build_proposals_for_batch(db, "B-LBL")
    actions = [p["action"] for p in out]
    # create_shipment (blocked because shipment is active) +
    # mark_label_printed + cancel
    assert pb.ACTION_CREATE_SHIPMENT in actions
    assert pb.ACTION_MARK_LABEL_PRINTED in actions
    assert pb.ACTION_CANCEL_SHIPMENT in actions
    create = next(p for p in out if p["action"] == pb.ACTION_CREATE_SHIPMENT)
    assert create["enabled"] is False
    mark = next(p for p in out if p["action"] == pb.ACTION_MARK_LABEL_PRINTED)
    assert mark["enabled"] is True


def test_build_proposals_for_batch_with_label_printed(db):
    csdb.upsert_shipment(
        carrier=CARRIER_DHL, awb="LBL-2",
        state=cse.LABEL_PRINTED, batch_id="B-LP",
    )
    out = pb.build_proposals_for_batch(db, "B-LP")
    actions = [p["action"] for p in out]
    assert pb.ACTION_MARK_HANDED_TO_CARRIER in actions
    assert pb.ACTION_CANCEL_SHIPMENT in actions
    assert pb.ACTION_MARK_LABEL_PRINTED not in actions


def test_build_proposals_for_batch_after_handover(db):
    csdb.upsert_shipment(
        carrier=CARRIER_DHL, awb="LBL-3",
        state=cse.HANDED_TO_CARRIER, batch_id="B-HND",
    )
    out = pb.build_proposals_for_batch(db, "B-HND")
    actions = [p["action"] for p in out]
    # After handover: create blocked (active shipment), no
    # mark-* proposals, and cancel is omitted entirely (post-
    # handover cancel is structurally invalid — emitting it would
    # be noise).
    assert pb.ACTION_MARK_LABEL_PRINTED not in actions
    assert pb.ACTION_MARK_HANDED_TO_CARRIER not in actions
    assert pb.ACTION_CANCEL_SHIPMENT not in actions
    create = next(p for p in out if p["action"] == pb.ACTION_CREATE_SHIPMENT)
    assert create["enabled"] is False


# ── 11. build_all_open_proposals reads without writing ─────────────────────

def test_build_all_open_proposals_emits_per_shipment(db):
    csdb.upsert_shipment(
        carrier=CARRIER_DHL, awb="ALL-1",
        state=cse.LABEL_CREATED, batch_id="B-A1",
    )
    csdb.upsert_shipment(
        carrier=CARRIER_DHL, awb="ALL-2",
        state=cse.LABEL_PRINTED, batch_id="B-A2",
    )
    csdb.upsert_shipment(
        carrier=CARRIER_DHL, awb="ALL-3",
        state=cse.DELIVERED, batch_id="B-A3",
    )

    out = pb.build_all_open_proposals(db)
    awb_actions = [(p["awb"], p["action"]) for p in out]
    # ALL-1 (label_created) → mark_label_printed + cancel
    assert ("ALL-1", pb.ACTION_MARK_LABEL_PRINTED) in awb_actions
    assert ("ALL-1", pb.ACTION_CANCEL_SHIPMENT) in awb_actions
    # ALL-2 (label_printed) → mark_handed_to_carrier + cancel
    assert ("ALL-2", pb.ACTION_MARK_HANDED_TO_CARRIER) in awb_actions
    assert ("ALL-2", pb.ACTION_CANCEL_SHIPMENT) in awb_actions
    # ALL-3 (delivered) → no proposals
    assert not any(awb == "ALL-3" for awb, _ in awb_actions)
    # No create_shipment proposals emitted (no batch context)
    assert not any(act == pb.ACTION_CREATE_SHIPMENT for _, act in awb_actions)


def test_build_all_open_proposals_does_not_write_to_db(db):
    csdb.upsert_shipment(
        carrier=CARRIER_DHL, awb="RO-1",
        state=cse.LABEL_CREATED, batch_id="B-RO",
    )

    # Snapshot table contents
    con = sqlite3.connect(str(db))
    before_ship = list(con.execute("SELECT * FROM carrier_shipments").fetchall())
    before_trans = list(con.execute(
        "SELECT * FROM carrier_shipment_transitions"
    ).fetchall())
    con.close()

    pb.build_all_open_proposals(db)
    pb.build_proposals_for_batch(db, "B-RO")

    con = sqlite3.connect(str(db))
    after_ship = list(con.execute("SELECT * FROM carrier_shipments").fetchall())
    after_trans = list(con.execute(
        "SELECT * FROM carrier_shipment_transitions"
    ).fetchall())
    con.close()

    assert before_ship  == after_ship
    assert before_trans == after_trans


# ── 12. Proposal shape contains all required keys ──────────────────────────

def _all_proposals():
    """One-of-each via the synthetic row, plus a bare create."""
    return [
        pb.build_create_shipment_proposal("B-X"),
        pb.build_mark_label_printed_proposal(_row(state=cse.LABEL_CREATED)),
        pb.build_mark_handed_to_carrier_proposal(_row(state=cse.LABEL_PRINTED)),
        pb.build_cancel_shipment_proposal(_row(state=cse.LABEL_CREATED)),
    ]


def test_proposal_shape_has_required_keys():
    for p in _all_proposals():
        missing = REQUIRED_KEYS - set(p.keys())
        extra   = set(p.keys()) - REQUIRED_KEYS
        assert not missing, f"missing keys: {missing} on {p['action']}"
        assert not extra,   f"extra keys: {extra} on {p['action']}"


def test_proposal_field_types():
    for p in _all_proposals():
        assert isinstance(p["proposal_id"], str)
        assert isinstance(p["action"], str)
        assert isinstance(p["carrier"], str)
        assert isinstance(p["title"], str)
        assert isinstance(p["reason"], str)
        assert isinstance(p["severity"], str)
        assert isinstance(p["enabled"], bool)
        assert isinstance(p["blocking_reasons"], list)
        assert isinstance(p["metadata"], dict)


# ── 13. Severity is one of the three values ───────────────────────────────

def test_severity_only_three_values():
    for p in _all_proposals():
        assert p["severity"] in {"info", "warning", "blocked"}


def test_severity_constants_match_spec():
    assert pb.SEVERITY_INFO    == "info"
    assert pb.SEVERITY_WARNING == "warning"
    assert pb.SEVERITY_BLOCKED == "blocked"
    assert pb.VALID_SEVERITIES == frozenset({"info", "warning", "blocked"})


# ── 14-18. Source-grep ────────────────────────────────────────────────────

@pytest.mark.parametrize("forbidden", [
    "import fastapi", "from fastapi",
    "import flask",   "from flask",
])
def test_builder_source_no_web_framework(builder_src, forbidden):
    assert forbidden not in builder_src, (
        f"carrier_proposal_builder.py contains {forbidden!r} — "
        f"proposal builder is service-layer only, no web framework imports."
    )


@pytest.mark.parametrize("forbidden", [
    "carrier_coordinator", "from .carrier_coordinator",
    "from . import carrier_coordinator",
])
def test_builder_source_no_coordinator_import(builder_src, forbidden):
    assert forbidden not in builder_src, (
        f"carrier_proposal_builder.py contains {forbidden!r} — DL-D2 "
        f"must not couple to the coordinator; that's DL-D3."
    )


@pytest.mark.parametrize("forbidden", [
    ".adapters", "from .adapters", "from ..adapters",
    "DHLExpressStubAdapter", "CarrierAdapter",
])
def test_builder_source_no_adapter_import(builder_src, forbidden):
    assert forbidden not in builder_src, (
        f"carrier_proposal_builder.py contains {forbidden!r} — "
        f"the proposal builder is read-only and must not reach into "
        f"any adapter, live or stub."
    )


@pytest.mark.parametrize("forbidden", [
    "import requests", "from requests",
    "import httpx",    "from httpx",
    "import urllib",   "from urllib",
])
def test_builder_source_no_http_clients(builder_src, forbidden):
    assert forbidden not in builder_src, (
        f"carrier_proposal_builder.py contains {forbidden!r} — "
        f"proposal builder makes no outbound HTTP calls."
    )


@pytest.mark.parametrize("forbidden", [
    "csdb.upsert_shipment",
    "csdb.record_transition",
    "upsert_shipment(",
    "record_transition(",
])
def test_builder_source_no_db_writes(builder_src, forbidden):
    assert forbidden not in builder_src, (
        f"carrier_proposal_builder.py contains {forbidden!r} — "
        f"proposal builder is read-only; DB writes belong in the "
        f"coordinator."
    )


def test_builder_source_no_env_reads(builder_src):
    for forbidden in ["os.environ", "os.getenv", "getenv("]:
        assert forbidden not in builder_src, (
            f"carrier_proposal_builder.py contains {forbidden!r} — "
            f"all dependencies arrive via function arguments."
        )
