"""
test_tracking_timeline_milestones.py
====================================

Tracking → Intelligence integration tests for the post-architecture-correction
milestone-emitter design.

Locked invariants under test:

  A. tracking_events stays the transport telemetry source of truth.
  B. Intelligence + SLA read tracking_events directly (no timeline mirror).
  C. Exactly two transport-class events may cross into timeline:
       carrier_arrived_poland
       carrier_delivered
  D. Runtime allowlist (_MILESTONE_ALLOWLIST) blocks any other event.
  E. Dedup oracle = scan of audit["timeline"] for (event_name, milestone_ts).
     Side-fields (carrier_arrived_at_poland_at, shipment_delivered) are
     advisory mirrors only — never consulted for dedup.
  F. apply_workflow_progression_locked() wraps load+mutate+write under the
     per-batch advisory write lock. Exactly-once emission under concurrent
     writes is required.
  G. Milestone schema is FROZEN: detail keys are exactly
       carrier_arrived_poland: {awb, first_pl_event_time, milestone_ts}
       carrier_delivered:      {awb, delivered_event_time, milestone_ts}
     milestone_ts is mandatory and equals the canonical dedup timestamp.
  H. tracking_normalizer does NOT mutate clearance_status.
"""
from __future__ import annotations

import json
import sys
import threading
from pathlib import Path
from typing import Any, Dict, List

import pytest

_SVC = Path(__file__).parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

from app.services.tracking_normalizer import (  # noqa: E402
    _MILESTONE_ALLOWLIST,
    _country_code_from_location,
    _emit_milestone,
    apply_workflow_progression,
    apply_workflow_progression_locked,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _ev(
    *,
    stage:       str,
    location:    str,
    event_time:  str,
    raw_description: str = "",
    awb:         str = "AWB123",
    source:      str = "dhl_api",
) -> Dict[str, Any]:
    """Build a minimal normalized tracking_events entry."""
    return {
        "event_id":               f"id_{event_time}_{stage}",
        "batch_id":               "BATCH_TEST",
        "awb":                    awb,
        "source":                 source,
        "raw_status":             "",
        "raw_description":        raw_description or stage,
        "normalized_stage":       stage,
        "location":               location,
        "event_time":             event_time,
        "captured_at":            "2026-05-07T00:00:00Z",
        "confidence":             0.9,
        "requires_manual_review": False,
    }


def _audit(events: List[Dict[str, Any]] | None = None,
           timeline: List[Dict[str, Any]] | None = None,
           **extra: Any) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "batch_id":        "BATCH_TEST",
        "awb":             "AWB123",
        "tracking_events": list(events or []),
        "timeline":        list(timeline or []),
    }
    base.update(extra)
    return base


# ── 1) carrier_arrived_poland — single emission ─────────────────────────────

def test_milestone_emitter_emits_carrier_arrived_poland_once():
    audit = _audit(events=[
        _ev(stage="ARRIVED_DESTINATION_COUNTRY",
            location="WARSAW - POLAND - PL",
            event_time="2026-05-05T17:40:00+02:00"),
    ])

    out = apply_workflow_progression(audit)

    pl_events = [e for e in out["timeline"]
                 if e.get("event") == "carrier_arrived_poland"]
    assert len(pl_events) == 1
    assert pl_events[0]["detail"]["milestone_ts"] == "2026-05-05T17:40:00+02:00"
    assert out["carrier_arrived_at_poland_at"] == "2026-05-05T17:40:00+02:00"


# ── 2) carrier_delivered — single emission ──────────────────────────────────

def test_milestone_emitter_emits_carrier_delivered_once():
    audit = _audit(events=[
        _ev(stage="DELIVERED",
            location="WARSAW - POLAND - PL",
            event_time="2026-05-10T09:00:00+02:00"),
    ])

    out = apply_workflow_progression(audit)

    delivered = [e for e in out["timeline"]
                 if e.get("event") == "carrier_delivered"]
    assert len(delivered) == 1
    assert delivered[0]["detail"]["milestone_ts"] == "2026-05-10T09:00:00+02:00"
    assert out.get("shipment_delivered") is True


# ── 3) Idempotent within a single call ──────────────────────────────────────

def test_milestone_idempotent_within_single_call():
    """Calling apply twice on the same in-memory audit must not duplicate."""
    audit = _audit(events=[
        _ev(stage="CUSTOMS_PENDING",
            location="WARSAW - POLAND - PL",
            event_time="2026-05-05T17:40:00+02:00"),
    ])

    apply_workflow_progression(audit)
    apply_workflow_progression(audit)

    pl = [e for e in audit["timeline"] if e.get("event") == "carrier_arrived_poland"]
    assert len(pl) == 1


# ── 4) Idempotent across calls (persist + reload) ───────────────────────────

def test_milestone_idempotent_across_calls(tmp_path):
    """After persist + reload, second apply must not duplicate."""
    from app.utils.io import write_json_atomic

    audit = _audit(events=[
        _ev(stage="CUSTOMS_PENDING",
            location="WARSAW - POLAND - PL",
            event_time="2026-05-05T17:40:00+02:00"),
    ])
    apply_workflow_progression(audit)
    p = tmp_path / "audit.json"
    write_json_atomic(p, audit)

    reloaded = json.loads(p.read_text(encoding="utf-8"))
    apply_workflow_progression(reloaded)

    pl = [e for e in reloaded["timeline"] if e.get("event") == "carrier_arrived_poland"]
    assert len(pl) == 1


# ── 5) Dedup under concurrent writes (process-level lock + dedup oracle) ────

def test_milestone_dedup_under_concurrent_writes(tmp_path, monkeypatch):
    """
    Two threads call apply_workflow_progression_locked concurrently. The
    per-batch advisory lock + timeline-scan dedup oracle must combine to
    yield exactly one milestone entry on disk.
    """
    from app.core.config import settings
    from app.utils.io import write_json_atomic

    monkeypatch.setattr(settings, "storage_root", tmp_path)
    batch_id = "BATCH_CONCURRENT"
    batch_dir = tmp_path / "outputs" / batch_id
    batch_dir.mkdir(parents=True)
    audit_path = batch_dir / "audit.json"

    write_json_atomic(audit_path, _audit(events=[
        _ev(stage="CUSTOMS_PENDING",
            location="WARSAW - POLAND - PL",
            event_time="2026-05-05T17:40:00+02:00"),
    ]))

    errors: List[Exception] = []

    def worker():
        try:
            apply_workflow_progression_locked(batch_id, audit_path=audit_path)
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert not errors, f"Worker errors: {errors}"

    final = json.loads(audit_path.read_text(encoding="utf-8"))
    pl = [e for e in final["timeline"] if e.get("event") == "carrier_arrived_poland"]
    assert len(pl) == 1, f"Expected exactly 1 milestone, got {len(pl)}: {pl}"


# ── 6) Uses earliest PL event, not latest ───────────────────────────────────

def test_milestone_uses_first_pl_event_not_latest():
    """The dedup timestamp is the earliest PL event_time, not the most recent."""
    audit = _audit(events=[
        _ev(stage="CUSTOMS_PENDING",
            location="WARSAW - POLAND - PL",
            event_time="2026-05-05T17:40:00+02:00"),
        _ev(stage="CUSTOMS_DOCUMENTS_REQUESTED",
            location="WARSAW - POLAND - PL",
            event_time="2026-05-06T12:00:00+02:00"),
        _ev(stage="CUSTOMS_UNDER_REVIEW",
            location="WARSAW - POLAND - PL",
            event_time="2026-05-06T18:00:00+02:00"),
    ])

    out = apply_workflow_progression(audit)

    pl = [e for e in out["timeline"] if e.get("event") == "carrier_arrived_poland"]
    assert len(pl) == 1
    assert pl[0]["detail"]["milestone_ts"] == "2026-05-05T17:40:00+02:00"
    assert pl[0]["detail"]["first_pl_event_time"] == "2026-05-05T17:40:00+02:00"


# ── 7) Side-field clear does NOT cause re-emission (dedup is timeline-only) ─

def test_milestone_dedup_resilient_to_sidefield_clear():
    """
    Even if the advisory side-field carrier_arrived_at_poland_at is wiped,
    the timeline-scan dedup must still block re-emission. The side-field is
    advisory; the timeline is the canonical oracle.
    """
    events = [
        _ev(stage="CUSTOMS_PENDING",
            location="WARSAW - POLAND - PL",
            event_time="2026-05-05T17:40:00+02:00"),
    ]
    audit = _audit(events=events)
    apply_workflow_progression(audit)

    # Wipe the side-field — dedup must NOT depend on this
    audit.pop("carrier_arrived_at_poland_at", None)

    apply_workflow_progression(audit)

    pl = [e for e in audit["timeline"] if e.get("event") == "carrier_arrived_poland"]
    assert len(pl) == 1


# ── 8) Allowlist enforcement — unknown event name ───────────────────────────

def test_emit_milestone_rejects_unknown_event_name():
    audit = _audit()
    with pytest.raises(ValueError, match="only.*are permitted"):
        _emit_milestone(audit, "carrier_arrived_hub", "2026-05-05T00:00:00Z",
                        {"awb": "AWB123"})


# ── 9) Allowlist enforcement — explicit regression for rejected design ──────

def test_emit_milestone_rejects_carrier_tracking_refreshed():
    """Regression guard against the previously-rejected mirror-everything design."""
    audit = _audit()
    with pytest.raises(ValueError):
        _emit_milestone(audit, "carrier_tracking_refreshed",
                        "2026-05-05T00:00:00Z", {"awb": "AWB123"})


# ── 10) Allowlist size locked — surfaces architecture-review trigger ────────

def test_milestone_allowlist_size_locked():
    """
    The allowlist is exactly two events. Any expansion requires fresh
    architecture review — this test must fail in that case so the reviewer
    sees the trigger explicitly.
    """
    assert len(_MILESTONE_ALLOWLIST) == 2
    assert _MILESTONE_ALLOWLIST == frozenset({
        "carrier_arrived_poland",
        "carrier_delivered",
    })


# ── 11) Schema — milestone_ts is mandatory ──────────────────────────────────

def test_milestone_detail_has_milestone_ts():
    audit = _audit(events=[
        _ev(stage="CUSTOMS_PENDING",
            location="WARSAW - POLAND - PL",
            event_time="2026-05-05T17:40:00+02:00"),
        _ev(stage="DELIVERED",
            location="WARSAW - POLAND - PL",
            event_time="2026-05-10T09:00:00+02:00"),
    ])
    out = apply_workflow_progression(audit)

    milestones = [e for e in out["timeline"]
                  if e.get("event") in _MILESTONE_ALLOWLIST]
    assert len(milestones) == 2
    for m in milestones:
        assert "milestone_ts" in m["detail"]
        assert m["detail"]["milestone_ts"]


# ── 12) Schema — milestone_ts equals canonical dedup timestamp ──────────────

def test_milestone_ts_equals_canonical_dedup_timestamp():
    audit = _audit(events=[
        _ev(stage="CUSTOMS_PENDING",
            location="WARSAW - POLAND - PL",
            event_time="2026-05-05T17:40:00+02:00"),
        _ev(stage="DELIVERED",
            location="WARSAW - POLAND - PL",
            event_time="2026-05-10T09:00:00+02:00"),
    ])
    out = apply_workflow_progression(audit)

    arrived = next(e for e in out["timeline"]
                   if e["event"] == "carrier_arrived_poland")
    delivered = next(e for e in out["timeline"]
                     if e["event"] == "carrier_delivered")

    assert arrived["detail"]["milestone_ts"] == arrived["detail"]["first_pl_event_time"]
    assert delivered["detail"]["milestone_ts"] == delivered["detail"]["delivered_event_time"]


# ── 13) Schema — detail key set is FROZEN ───────────────────────────────────

def test_milestone_detail_schema_locked():
    """
    detail keys must be EXACTLY the closed set:
      carrier_arrived_poland: {awb, first_pl_event_time, milestone_ts}
      carrier_delivered:      {awb, delivered_event_time, milestone_ts}
    """
    audit = _audit(events=[
        _ev(stage="CUSTOMS_PENDING",
            location="WARSAW - POLAND - PL",
            event_time="2026-05-05T17:40:00+02:00"),
        _ev(stage="DELIVERED",
            location="WARSAW - POLAND - PL",
            event_time="2026-05-10T09:00:00+02:00"),
    ])
    out = apply_workflow_progression(audit)

    arrived = next(e for e in out["timeline"]
                   if e["event"] == "carrier_arrived_poland")
    delivered = next(e for e in out["timeline"]
                     if e["event"] == "carrier_delivered")

    assert set(arrived["detail"].keys()) == {
        "awb", "first_pl_event_time", "milestone_ts",
    }
    assert set(delivered["detail"].keys()) == {
        "awb", "delivered_event_time", "milestone_ts",
    }


# ── 14) Dedup uses milestone_ts, NOT ts ─────────────────────────────────────

def test_dedup_uses_milestone_ts_not_ts():
    """
    Two manually-written milestone entries with identical event names and
    identical milestone_ts but DIFFERENT ts (write timestamp) must be
    treated as the same milestone — dedup uses milestone_ts only.
    """
    canonical_ts = "2026-05-05T17:40:00+02:00"
    audit = _audit(timeline=[{
        "event":          "carrier_arrived_poland",
        "trigger_source": "dhl_api",
        "actor":          "system",
        "ts":             "2026-05-05T18:00:00Z",   # write time A
        "detail": {
            "awb":                 "AWB123",
            "first_pl_event_time": canonical_ts,
            "milestone_ts":        canonical_ts,
        },
    }], events=[
        _ev(stage="CUSTOMS_PENDING",
            location="WARSAW - POLAND - PL",
            event_time=canonical_ts),
    ])

    apply_workflow_progression(audit)

    pl = [e for e in audit["timeline"] if e.get("event") == "carrier_arrived_poland"]
    # Despite a different ts that would naturally appear on a fresh emit,
    # dedup against milestone_ts blocks the second append.
    assert len(pl) == 1
    assert pl[0]["ts"] == "2026-05-05T18:00:00Z"  # original ts preserved


# ── 15) Non-PL hub event must NOT emit a timeline event ─────────────────────

def test_no_non_pl_hub_event_emitted():
    """
    Hub arrivals at non-PL locations (Hong Kong, Leipzig, etc.) must NOT
    create timeline events. This is the rejected `carrier_arrived_hub`
    design — explicit regression guard.
    """
    audit = _audit(events=[
        _ev(stage="ARRIVED_ORIGIN_HUB",
            location="HONG KONG - HONG KONG SAR, CHINA - HK",
            event_time="2026-05-06T14:01:00+08:00"),
        _ev(stage="ARRIVED_ORIGIN_HUB",
            location="LEIPZIG - GERMANY - DE",
            event_time="2026-05-07T01:06:00+02:00"),
        _ev(stage="DEPARTED_ORIGIN_HUB",
            location="HONG KONG - HONG KONG SAR, CHINA - HK",
            event_time="2026-05-06T17:12:00+08:00"),
    ])

    out = apply_workflow_progression(audit)

    transport_events_in_timeline = [
        e for e in out["timeline"]
        if e.get("event", "").startswith("carrier_")
    ]
    assert transport_events_in_timeline == []
    # Specifically, no carrier_arrived_hub or carrier_tracking_refreshed
    assert not any(e.get("event") == "carrier_arrived_hub"
                   for e in out["timeline"])
    assert not any(e.get("event") == "carrier_tracking_refreshed"
                   for e in out["timeline"])


# ── 16) Intelligence last_event prefers tracking_events when newer ──────────

def test_intelligence_last_event_reads_tracking_events_when_newer():
    from app.api.routes_intelligence import _resolve_last_event

    timeline = [{
        "event":          "dhl_email_received",
        "ts":             "2026-05-04T10:00:00Z",
        "trigger_source": "email_classifier",
        "detail":         {"awb": "AWB123"},
    }]
    tracking_events = [
        _ev(stage="CUSTOMS_PENDING",
            location="WARSAW - POLAND - PL",
            event_time="2026-05-06T17:40:00Z"),
    ]

    last = _resolve_last_event(timeline, tracking_events)
    assert last is not None
    assert last["source"] == "tracking"
    assert last["event"] == "carrier_customs_pending"
    assert last["detail"]["normalized_stage"] == "CUSTOMS_PENDING"


def test_intelligence_last_event_prefers_timeline_when_newer():
    """Symmetric coverage — newer document event wins over older tracking event."""
    from app.api.routes_intelligence import _resolve_last_event

    timeline = [{
        "event":          "dhl_email_received",
        "ts":             "2026-05-08T10:00:00Z",
        "trigger_source": "email_classifier",
        "detail":         {"awb": "AWB123"},
    }]
    tracking_events = [
        _ev(stage="CUSTOMS_PENDING",
            location="WARSAW - POLAND - PL",
            event_time="2026-05-06T17:40:00Z"),
    ]

    last = _resolve_last_event(timeline, tracking_events)
    assert last is not None
    assert last["source"] == "timeline"
    assert last["event"] == "dhl_email_received"


# ── 17) Intelligence next_step reads tracking_events for carrier state ──────

def test_intelligence_next_step_reads_tracking_events_for_carrier_state():
    from app.api.routes_intelligence import _next_step

    audit = _audit(events=[
        _ev(stage="CUSTOMS_PENDING",
            location="WARSAW - POLAND - PL",
            event_time="2026-05-05T17:40:00+02:00"),
    ])
    # Note: timeline does NOT contain `carrier_arrived` — _next_step must
    # still recognise PL transport state from tracking_events directly.
    step = _next_step(
        timeline        = audit["timeline"],
        tracking_events = audit["tracking_events"],
        carrier         = "DHL",
        audit           = audit,
    )
    assert "cesja" in step.lower()
    assert "Await cesja" in step


def test_intelligence_next_step_falls_back_when_no_pl_event():
    """No PL event in tracking_events → the default carrier-arrival prompt."""
    from app.api.routes_intelligence import _next_step

    audit = _audit(events=[
        _ev(stage="ARRIVED_ORIGIN_HUB",
            location="HONG KONG - HONG KONG SAR, CHINA - HK",
            event_time="2026-05-06T14:01:00+08:00"),
    ])
    step = _next_step(
        timeline        = audit["timeline"],
        tracking_events = audit["tracking_events"],
        carrier         = "DHL",
        audit           = audit,
    )
    assert "Await carrier arrival confirmation" in step


# ── 18) SLA triggers on PL customs stage ────────────────────────────────────

def test_should_start_followup_triggers_on_pl_customs_stage():
    from app.services.dhl_followup_sla import should_start_followup

    audit = _audit(events=[
        _ev(stage="CUSTOMS_PENDING",
            location="WARSAW - POLAND - PL",
            event_time="2026-05-05T17:40:00+02:00"),
    ])

    result = should_start_followup(audit)
    assert result == {"reason": "poland_customs_stage_detected"}


def test_should_start_followup_no_trigger_on_non_pl():
    from app.services.dhl_followup_sla import should_start_followup

    audit = _audit(events=[
        _ev(stage="CUSTOMS_PENDING",
            location="LEIPZIG - GERMANY - DE",
            event_time="2026-05-07T01:06:00+02:00"),
    ])
    assert should_start_followup(audit) is None


def test_should_start_followup_skipped_when_dhl_email_received():
    from app.services.dhl_followup_sla import should_start_followup

    audit = _audit(
        events=[
            _ev(stage="CUSTOMS_PENDING",
                location="WARSAW - POLAND - PL",
                event_time="2026-05-05T17:40:00+02:00"),
        ],
        dhl_email={"received": True},
    )
    assert should_start_followup(audit) is None


# ── 19) clearance_status must NOT be mutated by tracking layer ──────────────

def test_clearance_status_unchanged_by_tracking_refresh():
    """
    tracking_normalizer never advances clearance_status. That ownership
    belongs to the email/orchestration layer.
    """
    audit = _audit(events=[
        _ev(stage="CUSTOMS_PENDING",
            location="WARSAW - POLAND - PL",
            event_time="2026-05-05T17:40:00+02:00"),
        _ev(stage="DELIVERED",
            location="WARSAW - POLAND - PL",
            event_time="2026-05-10T09:00:00+02:00"),
    ], clearance_status="awaiting_dhl_customs_email")

    out = apply_workflow_progression(audit)

    # Same value before and after — even with PL+DELIVERED both present
    assert out["clearance_status"] == "awaiting_dhl_customs_email"


# ── 20) No financial keys in milestone detail ───────────────────────────────

def test_no_financial_keys_in_milestone_detail():
    """
    customs-value-freeze: milestone detail must not contain any monetary
    fields, recalculated or otherwise. Defensive guard against future drift.
    """
    audit = _audit(events=[
        _ev(stage="CUSTOMS_PENDING",
            location="WARSAW - POLAND - PL",
            event_time="2026-05-05T17:40:00+02:00"),
        _ev(stage="DELIVERED",
            location="WARSAW - POLAND - PL",
            event_time="2026-05-10T09:00:00+02:00"),
    ])
    out = apply_workflow_progression(audit)

    forbidden = {"unit_price", "total_value", "cif", "duty", "vat",
                 "amount", "tax", "currency", "duty_a00_pln", "total_value_usd"}

    milestones = [e for e in out["timeline"]
                  if e.get("event") in _MILESTONE_ALLOWLIST]
    for m in milestones:
        assert not (forbidden & set(m["detail"].keys())), \
            f"Milestone {m['event']} leaks financial key: {m['detail']}"


# ── Production caller (tracking_service) acquires the batch lock ────────────

def test_tracking_service_production_caller_uses_batch_write_lock(
    tmp_path, monkeypatch,
):
    """
    Regression: tracking_service.get_tracking_status must acquire the
    per-batch advisory lock around the audit-mutation block (load events
    → append → apply_workflow_progression → write_json_atomic). This guard
    prevents a future refactor from accidentally re-introducing the
    unlocked write path.

    Strategy:
      1. Set settings.storage_root + settings.dhl_tracking_api_status to
         drive the function down the live-API branch.
      2. Stub _call_dhl to return a single Polish customs event.
      3. Spy on app.utils.batch_lock.batch_write_lock to record every
         (batch_id) it is called with.
      4. Call get_tracking_status(refresh=True) and assert the spy
         observed exactly one acquisition for the batch under test.
      5. As an end-to-end verification, also assert that the milestone
         landed on disk — proving the lock-wrapped block executed end
         to end, not just acquired the lock.
    """
    from app.core.config import settings
    from app.services import tracking_service
    from app.utils import batch_lock as _batch_lock
    from app.utils.io import write_json_atomic

    monkeypatch.setattr(settings, "storage_root", tmp_path)
    monkeypatch.setattr(settings, "dhl_tracking_api_status", "active")
    monkeypatch.setattr(settings, "dhl_tracking_api_key", "k")
    monkeypatch.setattr(settings, "dhl_tracking_api_secret", "s")

    batch_id = "BATCH_LOCK_PROBE"
    awb      = "AWB_LOCK_PROBE"
    batch_dir = tmp_path / "outputs" / batch_id
    batch_dir.mkdir(parents=True)
    audit_path = batch_dir / "audit.json"
    write_json_atomic(audit_path, {
        "batch_id":        batch_id,
        "awb":             awb,
        "tracking_events": [],
        "timeline":        [],
    })

    # Stub the live DHL call to return one PL customs event.
    def _stub_call_dhl(_tn):
        return {
            "status":              "on_hold",
            "status_label":        "On Hold",
            "last_location":       "WARSAW - POLAND - PL",
            "last_update":         "2026-05-05T17:40:00+02:00",
            "last_update_display": "2026-05-05 17:40",
            "events": [{
                "timestamp":   "2026-05-05T17:40:00+02:00",
                "location":    "WARSAW - POLAND - PL",
                "status":      "RR",
                "description": "Customs clearance status updated",
            }],
            "source":     "dhl_unified_api",
            "api_status": "ok",
        }

    monkeypatch.setattr(tracking_service, "_call_dhl", _stub_call_dhl)

    # Spy on batch_write_lock — record each batch_id it is acquired with.
    acquisitions: List[str] = []
    real_lock = _batch_lock.batch_write_lock

    def _spy_lock(bid: str, *args, **kwargs):
        acquisitions.append(bid)
        return real_lock(bid, *args, **kwargs)

    # Patch BOTH the canonical location and the attribute name the call site
    # imports (`from ..utils.batch_lock import batch_write_lock`). The spy
    # must be visible to the import inside tracking_service.
    monkeypatch.setattr(_batch_lock, "batch_write_lock", _spy_lock)

    result = tracking_service.get_tracking_status(
        tracking_no = awb,
        carrier     = "DHL",
        cache_dir   = batch_dir,
        refresh     = True,
    )

    assert result.get("available") is True

    # The spy must have observed exactly one acquisition for this batch.
    assert acquisitions == [batch_id], (
        f"Expected one batch_write_lock acquisition for {batch_id!r}, "
        f"got: {acquisitions}"
    )

    # End-to-end: the milestone made it to disk under the lock.
    final = json.loads(audit_path.read_text(encoding="utf-8"))
    pl_milestones = [
        e for e in final.get("timeline", [])
        if e.get("event") == "carrier_arrived_poland"
    ]
    assert len(pl_milestones) == 1
    assert pl_milestones[0]["detail"]["milestone_ts"] == "2026-05-05T17:40:00+02:00"


# ── Country code parser — covered as supporting unit tests ──────────────────

class TestCountryCodeParser:
    def test_canonical_dhl_format_pl(self):
        assert _country_code_from_location("WARSAW - POLAND - PL") == "PL"

    def test_canonical_dhl_format_with_subregion(self):
        assert _country_code_from_location(
            "HONG KONG - HONG KONG SAR, CHINA - HK"
        ) == "HK"

    def test_canonical_dhl_format_with_parens(self):
        assert _country_code_from_location("MUMBAI (BOMBAY) - INDIA - IN") == "IN"

    def test_empty_returns_empty(self):
        assert _country_code_from_location("") == ""

    def test_malformed_returns_empty(self):
        assert _country_code_from_location("WARSAW") == ""
        assert _country_code_from_location("WARSAW - POLAND") == ""

    def test_three_letter_trailing_returns_empty(self):
        assert _country_code_from_location("CITY - COUNTRY - POL") == ""

    def test_lowercase_normalized_to_upper(self):
        assert _country_code_from_location("warsaw - poland - pl") == "PL"
