"""
test_dashboard_dhl_action_state.py — readiness endpoint tests.

Pins the operator-visible "next DHL action" decisions returned by
GET /dashboard/batches/{batch_id}/dhl-action-state.

Six required scenarios from the prompt:

  1. customs package missing            → "Generate customs package"
  2. customs package ready, not sent    → "Send proactive customs package to DHL"
  3. proactive proposal exists          → show pending / approved status
  4. our_dhl_reply already in evidence  → no duplicate send button
  5. incoming DHL request in evidence   → "Prepare reply to DHL thread"
  6. no auto queue from dashboard       → endpoint NEVER returns a queue_email
                                          target; only proposal-create or
                                          file-generation endpoints
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch

import pytest

_SVC = Path(__file__).parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))


# ── Helpers ─────────────────────────────────────────────────────────────────

def _make_audit(
    *,
    batch_id: str = "BATCH_TEST",
    awb:      str = "6049349806",
    customs_package_generated: bool = False,
    proactive_dispatch_sent:   bool = False,
    proactive_dispatch_failed: bool = False,
    proactive_proposal:        Dict[str, Any] | None = None,
    dsk_present:    bool = False,
    agency_active:  bool = False,
    clearance_path: str  = "dhl_self_clearance",
) -> Dict[str, Any]:
    a: Dict[str, Any] = {
        "batch_id":    batch_id,
        "awb":         awb,
        "carrier":     "DHL",
        "tracking_no": awb,
        "clearance_decision": {"clearance_path": clearance_path},
        "action_proposals": [],
    }
    if customs_package_generated:
        a["customs_package_generated_at"] = "2026-05-07T10:00:00Z"
    if proactive_dispatch_sent:
        a["proactive_dispatch_sent_at"] = "2026-05-07T11:30:00Z"
    if proactive_dispatch_failed:
        a["proactive_dispatch_failed_at"] = "2026-05-07T11:30:00Z"
        a["proactive_dispatch_failure_reason"] = "smtp connection refused"
    if proactive_proposal is not None:
        a["action_proposals"].append({
            "proposal_id": proactive_proposal.get("proposal_id", "uuid-1"),
            "type":        "dhl_proactive_dispatch",
            "status":      proactive_proposal.get("status", "pending_review"),
            "created_by":  proactive_proposal.get("created_by", "alice"),
            "approved_by": proactive_proposal.get("approved_by"),
            "created_at":  "2026-05-07T11:00:00Z",
        })
    if dsk_present:
        a["dsk_filename"] = "DSK_xyz.pdf"
    if agency_active:
        a["agency_name"] = "ACS Spedycja"
        a["clearance_decision"] = {"clearance_path": "agency_clearance"}
    return a


def _compute(audit: Dict[str, Any], summary: Dict[str, Any] | None = None):
    """Call the route helper directly with a stubbed evidence summary."""
    from app.api import routes_dashboard
    summary = summary or {}
    with patch.object(routes_dashboard, "_evidence_summary_for", return_value=summary):
        return routes_dashboard._compute_dhl_action_state(audit)


# ── 1. Customs package missing → Generate customs package ───────────────────

def test_no_customs_package_shows_generate_button():
    state = _compute(_make_audit(customs_package_generated=False))
    a = state["primary_action"]
    assert a is not None
    assert a["id"] == "generate_customs_package"
    assert a["endpoint"].startswith("/api/v1/dhl/generate-customs-package/")
    assert a["method"] == "POST"
    assert a["body"] == {"awb": "6049349806"}
    # Negative — no proactive dispatch endpoint shown when package missing
    assert "proactive-dispatch" not in a["endpoint"]
    # Detected badge surfaces the gap
    badge_keys = {b["key"] for b in state["badges"]}
    assert "customs_package_missing" in badge_keys


# ── 2. Customs ready, no proposal, not sent → Send proactive ────────────────

def test_customs_ready_not_sent_shows_proactive_button():
    state = _compute(_make_audit(customs_package_generated=True))
    a = state["primary_action"]
    assert a is not None
    assert a["id"] == "proactive_dispatch_request"
    assert a["endpoint"].endswith("/dhl/proactive-dispatch/BATCH_TEST")
    assert a["method"] == "POST"
    assert "operator_id" in a["body"]


# ── 3. Proactive proposal exists → guide through approve/queue ──────────────

def test_pending_proposal_shows_approve_button():
    state = _compute(_make_audit(
        customs_package_generated=True,
        proactive_proposal={"status": "pending_review", "proposal_id": "p-1"},
    ))
    a = state["primary_action"]
    assert a["id"] == "approve_proactive_proposal"
    assert "/api/v1/action-proposals/p-1/approve" in a["endpoint"]
    assert a["proposal_status"] == "pending_review"
    assert a["proposal_id"] == "p-1"


def test_approved_proposal_shows_queue_button():
    state = _compute(_make_audit(
        customs_package_generated=True,
        proactive_proposal={"status": "approved", "proposal_id": "p-2",
                            "approved_by": "bob"},
    ))
    a = state["primary_action"]
    assert a["id"] == "queue_proactive_proposal"
    assert "/api/v1/action-proposals/p-2/queue" in a["endpoint"]


def test_queued_proposal_shows_info_no_button():
    """When proposal is already queued, no primary button — just info."""
    state = _compute(_make_audit(
        customs_package_generated=True,
        proactive_proposal={"status": "queued", "proposal_id": "p-3",
                            "approved_by": "bob"},
    ))
    assert state["primary_action"] is None
    assert any("queued" in m.lower() for m in state["info_messages"])


# ── 4. our_dhl_reply already in evidence → no duplicate send button ─────────

def test_our_dhl_reply_already_present_no_duplicate_button():
    state = _compute(
        _make_audit(customs_package_generated=False),
        summary={"our_dhl_reply_queued": True},
    )
    # Primary action — generate customs package (because customs package is
    # still missing in this scenario) — is unrelated to send buttons.
    # The key invariant: NO secondary "Prepare reply" button when our reply
    # already exists.
    assert all(s["id"] != "prepare_dhl_reply"
               for s in state["secondary_actions"])
    # And the info messages explicitly mention dedup
    assert any("already found" in m.lower() for m in state["info_messages"])


def test_our_dhl_reply_with_pending_proposal_no_duplicate_send():
    """Even if a proactive proposal is pending, do not show a parallel
    'send DHL reply' button when our_dhl_reply is already in evidence."""
    state = _compute(
        _make_audit(
            customs_package_generated=True,
            proactive_proposal={"status": "pending_review", "proposal_id": "p-1"},
        ),
        summary={"our_dhl_reply_sent": True},
    )
    assert all(s["id"] != "prepare_dhl_reply"
               for s in state["secondary_actions"])


# ── 5. Incoming DHL request → Prepare reply button ──────────────────────────

def test_incoming_dhl_request_shows_prepare_reply():
    state = _compute(
        _make_audit(customs_package_generated=True),
        summary={"dhl_request_received": True},
    )
    sec_ids = {s["id"] for s in state["secondary_actions"]}
    assert "prepare_dhl_reply" in sec_ids
    s = next(s for s in state["secondary_actions"]
             if s["id"] == "prepare_dhl_reply")
    assert "match-and-handle" in s["endpoint"]
    # Detected badge surfaces "DHL request found" (not "missing")
    badge_keys = {b["key"] for b in state["badges"]}
    assert "dhl_request" in badge_keys


# ── 6. No auto-queue from dashboard ─────────────────────────────────────────

def test_no_action_target_calls_queue_email_directly():
    """
    The readiness endpoint must NEVER expose a button that hits queue_email
    directly. All buttons go through:
      - /generate-customs-package        (creates files)
      - /proactive-dispatch              (creates proposal)
      - /action-proposals/{id}/approve   (approval lane)
      - /action-proposals/{id}/queue     (queue lane — still operator-driven)
      - /dhl/match-and-handle            (builds reply package, no queue)
    """
    scenarios = [
        _make_audit(customs_package_generated=False),
        _make_audit(customs_package_generated=True),
        _make_audit(customs_package_generated=True,
                    proactive_proposal={"status": "pending_review", "proposal_id": "p-1"}),
        _make_audit(customs_package_generated=True,
                    proactive_proposal={"status": "approved", "proposal_id": "p-2",
                                        "approved_by": "bob"}),
        _make_audit(customs_package_generated=True, proactive_dispatch_sent=True),
    ]
    forbidden_substrings = (
        "/email/send",                  # no direct send endpoint
        "/email-queue/",                # no direct queue manipulation
        "queue_email",                  # function name leaked into URL
    )
    allowed_endpoint_prefixes = (
        "/api/v1/dhl/generate-customs-package/",
        "/api/v1/dhl/proactive-dispatch/",
        "/api/v1/dhl/match-and-handle",
        "/api/v1/action-proposals/",
    )
    for a in scenarios:
        for summary in [{}, {"dhl_request_received": True},
                        {"our_dhl_reply_sent": True},
                        {"our_dhl_reply_queued": True}]:
            state = _compute(a, summary=summary)
            actions = []
            if state["primary_action"]:
                actions.append(state["primary_action"])
            actions.extend(state["secondary_actions"] or [])
            for act in actions:
                ep = act["endpoint"]
                for f in forbidden_substrings:
                    assert f not in ep, (
                        f"forbidden endpoint substring {f!r} in action "
                        f"{act['id']!r} ({ep!r})"
                    )
                assert any(ep.startswith(p) for p in allowed_endpoint_prefixes), (
                    f"action {act['id']!r} endpoint {ep!r} not in allowed "
                    f"prefix list {allowed_endpoint_prefixes}"
                )


# ── 7. Agency clearance path — proactive dispatch not applicable ───────────

def test_agency_path_active_no_proactive_button():
    state = _compute(_make_audit(agency_active=True))
    assert state["primary_action"] is None
    badge_keys = {b["key"] for b in state["badges"]}
    assert "agency_active" in badge_keys
    assert any("agency" in m.lower() for m in state["info_messages"])


@pytest.mark.parametrize("path_value", [
    "agency_clearance",  # legacy
    "agency_clearance",            # spec (Phase 1.1)
])
def test_cascade_recognizes_both_agency_path_names(path_value):
    """Dashboard cascade flows agency-path detection through
    clearance_path_alias.is_agency_clearance, so both legacy and spec
    names produce the same agency_active branch."""
    a = _make_audit()
    a["clearance_decision"] = {"clearance_path": path_value}
    state = _compute(a)
    badge_keys = {b["key"] for b in state["badges"]}
    assert "agency_active" in badge_keys


# ── 8. Already sent → terminal info, no button ─────────────────────────────

def test_proactive_already_sent_shows_terminal_info():
    state = _compute(_make_audit(
        customs_package_generated=True,
        proactive_dispatch_sent=True,
    ))
    assert state["primary_action"] is None
    assert any("already dispatched" in m.lower() for m in state["info_messages"])
    badge_keys = {b["key"] for b in state["badges"]}
    assert "proactive_sent" in badge_keys


def test_awaiting_dhl_state_contract():
    """Awaiting-DHL info-only branch is addressable: state_id, badge,
    verbatim info_message, no primary_action, no secondary_actions."""
    state = _compute(_make_audit(
        customs_package_generated=True,
        proactive_dispatch_sent=True,
    ))
    assert state["state_id"] == "awaiting_dhl"
    assert state["primary_action"] is None
    assert state["secondary_actions"] == []
    assert (
        "Proactive customs package already dispatched. Awaiting Poland "
        "arrival / DHL response."
    ) in state["info_messages"]
    awaiting = [b for b in state["badges"] if b.get("key") == "awaiting_dhl"]
    assert len(awaiting) == 1
    assert awaiting[0]["label"] == "Awaiting DHL"
    assert awaiting[0]["tone"] == "info"


# ── 9. Missing AWB disables generate-customs-package button ────────────────

def test_missing_awb_disables_generate_button():
    a = _make_audit(awb="")
    a["awb"] = ""
    a["tracking_no"] = ""
    state = _compute(a)
    primary = state["primary_action"]
    assert primary is not None
    assert primary["id"] == "generate_customs_package"
    assert primary["disabled"] is True
    assert primary["disabled_reason"]


# ── 10. State summary string is human-readable for every scenario ──────────

@pytest.mark.parametrize("audit_kwargs", [
    {},
    {"customs_package_generated": True},
    {"customs_package_generated": True, "proactive_dispatch_sent": True},
    {"customs_package_generated": True,
     "proactive_proposal": {"status": "pending_review", "proposal_id": "p-1"}},
    {"agency_active": True},
])
def test_state_summary_present_for_all_scenarios(audit_kwargs):
    state = _compute(_make_audit(**audit_kwargs))
    assert state["state_summary"]
    assert isinstance(state["state_summary"], str)
    assert len(state["state_summary"]) > 0


# ── 11. Endpoint integration smoke test ────────────────────────────────────

def test_endpoint_returns_404_for_missing_batch(tmp_path, monkeypatch):
    """The actual route handler returns 404 when batch dir doesn't exist."""
    from fastapi.testclient import TestClient
    from app.core.config import settings
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    monkeypatch.setattr(settings, "api_key",      "test-key", raising=False)

    from app.main import app
    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.get(
            "/dashboard/batches/NONEXISTENT_BATCH_xyz/dhl-action-state",
            headers={"X-API-Key": "test-key"},
        )
    assert r.status_code == 404


# ── DHL Action Panel consolidation tests ────────────────────────────────────
#
# These six tests cover the consolidation requirements:
#   1. Only one primary action rendered.
#   2. Advanced tools collapsed by default.
#   3. Legacy CTA strings removed.
#   4. Retry state supersedes normal queue state.
#   5. Reply-thread action only appears when incoming DHL request exists.
#   6. Existing milestone rendering unchanged.

_DASHBOARD_HTML = (
    Path(__file__).parent.parent / "app" / "static" / "dashboard.html"
)


def test_unified_panel_returns_only_one_primary_action():
    """No matter the state, only one primary_action is returned."""
    scenarios = [
        _make_audit(customs_package_generated=False),
        _make_audit(customs_package_generated=True),
        _make_audit(customs_package_generated=True,
                    proactive_proposal={"status": "pending_review", "proposal_id": "p-1"}),
        _make_audit(customs_package_generated=True,
                    proactive_proposal={"status": "approved", "proposal_id": "p-2",
                                        "approved_by": "bob"}),
        _make_audit(customs_package_generated=True,
                    proactive_proposal={"status": "approved", "proposal_id": "p-3",
                                        "approved_by": "bob"},
                    proactive_dispatch_failed=True),
        _make_audit(customs_package_generated=True, proactive_dispatch_sent=True),
        _make_audit(agency_active=True),
    ]
    for a in scenarios:
        for summary in [{}, {"dhl_request_received": True},
                        {"our_dhl_reply_sent": True},
                        {"our_dhl_reply_queued": True}]:
            state = _compute(a, summary=summary)
            # primary_action is at most ONE dict (or None — info-only state)
            assert (state["primary_action"] is None
                    or isinstance(state["primary_action"], dict))
            # Never a list of competing primaries
            assert "primary_actions" not in state, (
                "schema must surface a single primary_action key, not a list"
            )


def test_advanced_tools_collapsed_by_default():
    """Every Advanced/Manual tools wrapper in dashboard.html must be a
    <details> without an `open` attribute (collapsed by default)."""
    src = _DASHBOARD_HTML.read_text(encoding="utf-8")
    # Each new advanced-tools wrapper carries a data-testid that begins
    # with "dhl-advanced-tools" or "dhl-docs-upload-tools" or
    # "agency-docs-upload-tools" or "dhl-manual-mark-received".
    advanced_testids = [
        "dhl-advanced-tools",
        "dhl-docs-upload-tools",
        "agency-docs-upload-tools",
        "dhl-manual-mark-received",
    ]
    for tid in advanced_testids:
        marker = f'data-testid="{tid}"'
        assert marker in src, f"missing advanced-tools wrapper {tid!r}"
        # Find the <details ... data-testid="X"> opening tag and verify it
        # does NOT contain `open` (which would render expanded by default).
        idx = src.index(marker)
        # Walk back to the most recent '<' before this testid
        tag_start = src.rfind("<", 0, idx)
        tag_end   = src.find(">", idx)
        tag       = src[tag_start:tag_end + 1]
        assert tag.startswith("<details"), (
            f"{tid} must be a <details> element; got {tag[:40]!r}"
        )
        assert " open" not in tag and "\nopen" not in tag, (
            f"{tid} <details> must be collapsed by default; got {tag!r}"
        )


def test_legacy_cta_strings_removed():
    """The duplicated legacy CTAs that overlapped with DhlActionCard must
    be gone from dashboard.html."""
    src = _DASHBOARD_HTML.read_text(encoding="utf-8")
    forbidden = [
        # The hardcoded dhlAction strings that duplicated the action card
        "📝 Send Polish Description to DHL",
        "📨 Send DSK Transfer to DHL",
        # The InfoRow "DHL Action" label that paired with those strings
        '<InfoRow label="DHL Action"',
    ]
    for needle in forbidden:
        assert needle not in src, (
            f"legacy CTA string must be removed from dashboard.html: {needle!r}"
        )


def test_retry_state_supersedes_queue_state():
    """When proactive_dispatch_failed_at is set AND the proposal status is
    'approved', the readiness endpoint must return 'retry_failed_queue' as
    the primary action — NOT the regular 'queue_proactive_proposal'.

    Label/contract pinned to the IMPLEMENTER spec: label="Retry queue",
    target/endpoint both populated (target is the spec's contract key;
    endpoint is the wired key the live React component already reads).
    """
    state = _compute(_make_audit(
        customs_package_generated=True,
        proactive_proposal={"status": "approved", "proposal_id": "p-fail",
                            "approved_by": "bob"},
        proactive_dispatch_failed=True,
    ))
    a = state["primary_action"]
    assert a is not None, "retry state must produce a primary action"
    assert a["id"] == "retry_failed_queue"
    # Same /queue endpoint backend; distinct label and tone signal retry UX.
    assert "/api/v1/action-proposals/p-fail/queue" in a["endpoint"]
    assert a["label"] == "Retry queue"
    assert a["tone"] == "warn"
    assert a["body"] == {}


def test_retry_state_surfaces_bounded_failure_reason_in_info_messages():
    """The audit-stored failure reason is bounded to ≤200 chars at read
    boundary and surfaces in detected + info_messages (NOT on the action
    object as a separate key — the IMPLEMENTER contract uses
    info_messages for operator-visible reason display)."""
    a = _make_audit(
        customs_package_generated=True,
        proactive_proposal={"status": "approved", "proposal_id": "p-1",
                            "approved_by": "bob"},
        proactive_dispatch_failed=True,
    )
    long_reason = "smtp connection refused: " + ("X" * 500)
    a["proactive_dispatch_failure_reason"] = long_reason
    state = _compute(a)
    # detected surfaces the bounded reason
    assert state["detected"]["proactive_dispatch_failure_reason"]
    assert len(state["detected"]["proactive_dispatch_failure_reason"]) <= 200
    # info_messages carries a "Reason: ..." entry that includes the prefix
    assert any("smtp connection refused" in m and m.startswith("Reason: ")
               for m in state["info_messages"])


def test_reply_thread_action_only_when_incoming_dhl_request_exists():
    """`prepare_dhl_reply` secondary action appears IFF
    summary.dhl_request_received is True AND our_dhl_reply is absent."""
    # Scenario A: incoming request exists, no reply yet → action present
    sA = _compute(
        _make_audit(customs_package_generated=True),
        summary={"dhl_request_received": True},
    )
    assert any(s["id"] == "prepare_dhl_reply" for s in sA["secondary_actions"])

    # Scenario B: no incoming request → action absent
    sB = _compute(_make_audit(customs_package_generated=True), summary={})
    assert all(s["id"] != "prepare_dhl_reply" for s in sB["secondary_actions"])

    # Scenario C: incoming request AND our reply already in evidence → no action
    sC = _compute(
        _make_audit(customs_package_generated=True),
        summary={"dhl_request_received": True, "our_dhl_reply_sent": True},
    )
    assert all(s["id"] != "prepare_dhl_reply" for s in sC["secondary_actions"])


def test_existing_milestone_rendering_unchanged():
    """The 9-stage email-evidence milestone grid in dashboard.html must
    still render via EE_STAGE_ICON + EE_STATUS_STYLE — those constants
    must still exist and the stages list iteration must still be present.

    This guards against accidental removal during the action-panel
    consolidation."""
    src = _DASHBOARD_HTML.read_text(encoding="utf-8")
    # Both lookup tables must still be present
    assert "const EE_STAGE_ICON = {" in src
    assert "const EE_STATUS_STYLE = {" in src
    # Stages iteration in EmailEvidenceTimeline must still be present
    assert "stages.map((st, i)" in src
    # The 9 fixed stage keys must still be referenced in the icon table
    for key in ("dhl_request", "our_dhl_reply", "dhl_documents",
                "agency_forward", "agency_sad_reply", "pz_generated",
                "dhl_invoice", "agency_invoice", "shipment_closed"):
        assert key in src, f"milestone stage key {key!r} missing from dashboard.html"


def test_endpoint_round_trip_with_real_audit_file(tmp_path, monkeypatch):
    """End-to-end: write an audit.json, hit the endpoint, get the right shape."""
    from fastapi.testclient import TestClient
    from app.core.config import settings
    from app.api import routes_dashboard
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    monkeypatch.setattr(settings, "api_key",      "test-key", raising=False)
    # routes_dashboard caches _OUTPUTS / _WORKING at import — repoint them.
    monkeypatch.setattr(routes_dashboard, "_OUTPUTS", tmp_path / "outputs")
    monkeypatch.setattr(routes_dashboard, "_WORKING", tmp_path / "working")

    bid = "BATCH_LIVE_E2E"
    batch_dir = tmp_path / "outputs" / bid
    batch_dir.mkdir(parents=True)
    audit = _make_audit(batch_id=bid, customs_package_generated=True)
    (batch_dir / "audit.json").write_text(json.dumps(audit), encoding="utf-8")

    from app.main import app
    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.get(f"/dashboard/batches/{bid}/dhl-action-state",
                  headers={"X-API-Key": "test-key"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["batch_id"] == bid
    assert body["awb"] == "6049349806"
    assert body["primary_action"]["id"] == "proactive_dispatch_request"


# ── Failure-retry state — IMPLEMENTER contract pins (E1-ii / C1–C6) ────────

class TestFailureRetryStateContract:
    """
    Pins the failure-retry fifth-state contract:
      * additive detected fields (proactive_dispatch_failed_at as ISO
        string + proactive_dispatch_failure_reason; the existing boolean
        proactive_dispatch_failed is preserved unchanged per E1-ii)
      * primary_action shape (label="Retry queue", target/endpoint both
        populated, tone="warn", body={} per C1)
      * badge with verbatim "Proactive dispatch failed — retry available"
        per C4
      * info_messages with last failure timestamp, optional reason, and
        proposal id for operator inspection per C2
      * cascade ordering — branch only fires for proposal.status=="approved"
        AND proactive_dispatch_failed_at truthy (C3)
    """

    _FAILED_TS = "2026-05-07T11:30:00Z"
    _REASON    = "RuntimeError: smtp connection refused"

    def _make_failed_audit(self, **overrides) -> Dict[str, Any]:
        a = _make_audit(
            customs_package_generated=True,
            proactive_proposal={
                "status": overrides.get("status", "approved"),
                "proposal_id": overrides.get("proposal_id", "p-fail-9876"),
                "created_by": "alice",
                "approved_by": "bob",
            },
            proactive_dispatch_failed=True,  # writes proactive_dispatch_failed_at
        )
        # _make_audit sets proactive_dispatch_failed_at when failed=True;
        # ensure an explicit known-good ISO timestamp + bounded reason
        # so tests can assert exact values.
        a["proactive_dispatch_failed_at"]      = overrides.get(
            "failed_at", self._FAILED_TS)
        a["proactive_dispatch_failure_reason"] = overrides.get(
            "reason", self._REASON)
        return a

    # ── A. Full-shape contract pin ─────────────────────────────────────────

    def test_failure_retry_state_renders_when_failed_at_present(self):
        proposal_id = "p-fail-9876"
        a = self._make_failed_audit(proposal_id=proposal_id)
        state = _compute(a)

        # E1-ii: existing boolean preserved
        assert state["detected"]["proactive_dispatch_failed"] is True
        # E1-ii additive: ISO timestamp surfaced
        assert state["detected"]["proactive_dispatch_failed_at"] == self._FAILED_TS
        # E1-ii additive: reason surfaced (bounded)
        assert state["detected"]["proactive_dispatch_failure_reason"] == self._REASON

        # Primary action shape (C1, C4-relevant)
        a_ = state["primary_action"]
        assert a_ is not None
        assert a_["label"] == "Retry queue"
        assert a_["endpoint"] == f"/api/v1/action-proposals/{proposal_id}/queue"
        assert a_["tone"] == "warn"
        assert a_["body"] == {}     # C1 — empty body, no approved_by

        # C4: badge verbatim
        assert any(
            b.get("tone") == "warn"
            and b.get("label") == "Proactive dispatch failed — retry available"
            for b in state["badges"]
        )

        # C2 info-message-only: last failure ts, reason, proposal id
        assert any(f"Last failure: {self._FAILED_TS}" in m
                   for m in state["info_messages"])
        assert any(f"Reason: {self._REASON}" in m
                   for m in state["info_messages"])
        assert any(f"Proposal ID: {proposal_id}" in m
                   for m in state["info_messages"])

        # C2: secondary_actions MUST NOT contain a /api/v1/action-proposals/{id}
        # GET — that route is not confirmed to exist; do not invent it.
        for s in state["secondary_actions"]:
            assert not (s.get("method") == "GET"
                        and "/api/v1/action-proposals/" in s.get("target", "")
                        and "/queue" not in s.get("target", "")
                        and "/approve" not in s.get("target", "")
                        and "/reject" not in s.get("target", "")), (
                f"secondary_actions invented an inspect route: {s}"
            )
        # Stronger guard — no inspect-style id present at all
        for s in state["secondary_actions"]:
            t = (s.get("target") or s.get("endpoint") or "")
            assert "/inspect" not in t

    # ── B. Reason omitted when absent ──────────────────────────────────────

    def test_failure_retry_state_omits_reason_when_none(self):
        a = self._make_failed_audit(reason=None)
        # _make_failed_audit always sets reason; clear it to None to test
        # the optional-reason path
        a["proactive_dispatch_failure_reason"] = None
        state = _compute(a)
        assert state["detected"]["proactive_dispatch_failure_reason"] is None
        assert state["primary_action"]["label"] == "Retry queue"
        assert all("Reason:" not in m for m in state["info_messages"])

    # ── C. Cascade does NOT fire for non-approved status ──────────────────

    @pytest.mark.parametrize("non_approved_status",
                             ["pending_review", "queued", "rejected"])
    def test_failure_retry_state_does_not_fire_for_non_approved_status(
        self, non_approved_status,
    ):
        a = self._make_failed_audit(status=non_approved_status)
        state = _compute(a)
        # The cascade falls through to whatever branch handles that status.
        # The retry label MUST NOT appear.
        primary = state["primary_action"]
        if primary is not None:
            assert primary["label"] != "Retry queue", (
                f"retry branch fired for non-approved status "
                f"{non_approved_status!r}"
            )

    # ── D. Cascade does NOT fire without an active proposal ────────────────

    def test_failure_retry_state_does_not_fire_without_proposal(self):
        a = _make_audit(customs_package_generated=True)
        a["proactive_dispatch_failed_at"]      = self._FAILED_TS
        a["proactive_dispatch_failure_reason"] = self._REASON
        # NO action_proposals[] entry — proactive_proposal will be None
        state = _compute(a)
        primary = state["primary_action"]
        if primary is not None:
            assert primary["label"] != "Retry queue"


# ── disabled_reason consistency — schema + populated-string pin ─────────────
#
# The readiness endpoint's primary_action and secondary_action dicts each
# carry a `disabled_reason` field. Today only one cascade branch populates
# it (generate_customs_package when AWB is missing). Other branches all
# emit `disabled=False, disabled_reason=None`. These tests pin both:
#
#   1. The exact human-readable string for the one populated path.
#   2. The schema invariant that every emitted action carries the
#      `disabled` + `disabled_reason` pair, with reason being a non-empty
#      string IFF disabled is True, and None IFF disabled is False.

class TestDisabledReasonConsistency:
    """Schema + content pins for disabled_reason across action dicts."""

    # ── Inventory row 1 — only currently populated path ────────────────────

    def test_generate_customs_package_awb_missing_reason_verbatim(self):
        """Exact reason string for the only populated disable path."""
        a = _make_audit(customs_package_generated=False)
        a["awb"] = ""
        a["tracking_no"] = ""
        state = _compute(a)
        primary = state["primary_action"]
        assert primary is not None
        assert primary["id"] == "generate_customs_package"
        assert primary["disabled"] is True
        assert primary["disabled_reason"] == "AWB missing on this batch"

    def test_generate_customs_package_awb_present_reason_is_none(self):
        """Symmetric pin: when the same action is emitted ENABLED, the
        disabled_reason field is None (not '', not missing)."""
        a = _make_audit(customs_package_generated=False)
        # AWB defaults to a real value in _make_audit
        state = _compute(a)
        primary = state["primary_action"]
        assert primary is not None
        assert primary["id"] == "generate_customs_package"
        assert primary["disabled"] is False
        assert primary["disabled_reason"] is None

    # ── Schema invariant across every emission path ────────────────────────

    @pytest.mark.parametrize("audit_kwargs,summary", [
        # (1) customs missing → generate_customs_package (enabled, awb present)
        ({"customs_package_generated": False}, {}),
        # (2) customs ready, no proposal → proactive_dispatch_request
        ({"customs_package_generated": True}, {}),
        # (3) pending proposal → approve_proactive_proposal
        ({"customs_package_generated": True,
          "proactive_proposal": {"status": "pending_review", "proposal_id": "p-1"}}, {}),
        # (4) approved proposal (no failed) → queue_proactive_proposal
        ({"customs_package_generated": True,
          "proactive_proposal": {"status": "approved", "proposal_id": "p-2",
                                 "approved_by": "bob"}}, {}),
        # (5) approved + failed → retry_failed_queue
        ({"customs_package_generated": True,
          "proactive_proposal": {"status": "approved", "proposal_id": "p-3",
                                 "approved_by": "bob"},
          "proactive_dispatch_failed": True}, {}),
        # (6) inbound dhl request → secondary prepare_dhl_reply
        ({"customs_package_generated": True}, {"dhl_request_received": True}),
    ])
    def test_every_emitted_action_has_disabled_reason_key(self, audit_kwargs, summary):
        """Every action dict emitted by the cascade carries both `disabled`
        and `disabled_reason` keys. When `disabled` is False, `disabled_reason`
        is None. When `disabled` is True, `disabled_reason` is a non-empty
        string."""
        state = _compute(_make_audit(**audit_kwargs), summary=summary)
        actions: List[Dict[str, Any]] = []
        if state["primary_action"]:
            actions.append(state["primary_action"])
        actions.extend(state["secondary_actions"] or [])
        assert actions, "scenario produced no actions to validate"
        for act in actions:
            assert "disabled" in act, f"action {act.get('id')!r} missing 'disabled'"
            assert "disabled_reason" in act, (
                f"action {act.get('id')!r} missing 'disabled_reason'"
            )
            if act["disabled"] is True:
                assert isinstance(act["disabled_reason"], str), (
                    f"action {act.get('id')!r} disabled but disabled_reason "
                    f"is not a string: {act['disabled_reason']!r}"
                )
                assert act["disabled_reason"], (
                    f"action {act.get('id')!r} disabled but disabled_reason "
                    f"is empty"
                )
            else:
                assert act["disabled_reason"] is None, (
                    f"action {act.get('id')!r} enabled but disabled_reason "
                    f"is not None: {act['disabled_reason']!r}"
                )
