"""
test_email_evidence_zoho_in_region.py — regression tests for two bugs that
caused "0 stored messages" on AWB 6049349806 (and silently on every AWB)
after the Zoho mailbox migrated to the .in region.

Also covers the follow-on classifier bug (AWB 6049349806 reply being
classified as ``other``): the outgoing branch of classify_event_type
needed a subject-based fallback for DHL ticket threads when the scanner
omits ``to_addresses`` from the projected message dict.

Both bugs were latent — the live mailbox is at https://zmail.zoho.in/api,
but unit tests had been mocking scan_fn with the .eu shape so neither bug
was caught.

Bug 1 — searchKey prefix
  dhl_email_monitor._fetch_messages used to send `searchKey=<bare AWB>`.
  The Zoho .in region rejects this form with HTTP 400 "Invalid Input /
  Index 1 out of bounds for length 1". The .in region requires the
  ``entire:`` prefix (or a field-specific prefix). This file pins the
  prefix into the constructed search query.

Bug 2 — processor module load
  email_evidence_processor.py:28 referenced ``evs.EVIDENCE_ROOT`` which is
  not a module-level attribute of email_evidence_store.py — only
  ``_evidence_root()`` exists. Importing the processor crashed with
  AttributeError, so every POST to /email-evidence/process returned 500.
  This file pins the import to be importable and the lock dir resolution
  to run lazily.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SVC = Path(__file__).parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))
_CLI_ROOT = _SVC.parent
if str(_CLI_ROOT) not in sys.path:
    sys.path.insert(0, str(_CLI_ROOT))


# ── Bug 1: searchKey carries entire: prefix ─────────────────────────────────

class TestZohoInRegionSearchKeyPrefix:

    def test_targeted_awb_search_uses_entire_prefix(self, monkeypatch):
        """
        scan_for_dhl_customs_emails must send `searchKey=entire:<awb>` to
        Zoho. A bare AWB triggered HTTP 400 on the .in region.
        """
        captured: list = []

        class _Resp:
            status_code = 200
            def raise_for_status(self): pass
            def json(self): return {"data": []}

        def fake_get(url, headers=None, params=None, timeout=None):
            captured.append({"url": url, "params": dict(params or {})})
            return _Resp()

        # Patch requests.get directly — dhl_email_monitor does
        # `import requests as _req` inside the function and calls _req.get.
        import requests
        monkeypatch.setattr(requests, "get", fake_get)

        import dhl_email_monitor as monitor
        result = monitor.scan_for_dhl_customs_emails(
            target_awb="6049349806",
            limit=25,
            api_base="https://zmail.zoho.in/api",
            token_provider=lambda: "fake-token",
        )

        assert captured, "Zoho HTTP call was never issued"
        sk = captured[0]["params"].get("searchKey")
        assert sk == "entire:6049349806", (
            f"searchKey must use entire: prefix for Zoho .in region, got {sk!r}"
        )
        # Result shape preserved
        assert result["awb_used"] == "6049349806"
        assert result["scan_method"] in ("rest_api_search", "no_credentials")
        assert "entire:6049349806" in result["query_used"]

    def test_ticket_fallback_also_uses_entire_prefix(self, monkeypatch):
        """If the AWB search misses and a dhl_ticket is known, the ticket
        fallback must also use the entire: prefix to avoid the same
        HTTP 400."""
        calls: list = []

        class _Resp:
            status_code = 200
            def raise_for_status(self): pass
            def json(self): return {"data": []}

        def fake_get(url, headers=None, params=None, timeout=None):
            calls.append(dict(params or {}))
            return _Resp()

        import requests
        monkeypatch.setattr(requests, "get", fake_get)

        import dhl_email_monitor as monitor
        monitor.scan_for_dhl_customs_emails(
            target_awb="6049349806",
            limit=25,
            api_base="https://zmail.zoho.in/api",
            token_provider=lambda: "fake-token",
            dhl_ticket="T#1WA00012345",
        )

        # Three calls: primary AWB → spaced AWB → ticket fallback. The spaced
        # variant is an in-between attempt that must also use the entire:
        # prefix. The LAST call is the ticket fallback.
        search_keys = [c.get("searchKey") for c in calls]
        assert search_keys[0] == "entire:6049349806"
        # All search keys must use entire: prefix (no bare keyword)
        for k in search_keys:
            assert k and k.startswith("entire:"), f"non-prefixed key: {k!r}"
        # The ticket-fallback request is issued last
        assert search_keys[-1] == "entire:1WA00012345", search_keys

    def test_no_legacy_newentire_prefix_reintroduced(self):
        """Hard guard: the legacy `newentire::` prefix is rejected by .in.
        Forbid its reintroduction in dhl_email_monitor."""
        src = (_CLI_ROOT / "dhl_email_monitor.py").read_text(encoding="utf-8")
        # Allow it inside docstrings/comments, but the literal must not
        # appear in an f-string or assignment building a searchKey value.
        forbidden_active = 'searchKey": f"newentire::'
        assert forbidden_active not in src, (
            "dhl_email_monitor must not build searchKey using newentire:: — "
            "the .in region rejects it with HTTP 400."
        )


# ── Bug 2: processor module imports cleanly + lock dir resolves lazily ─────

class TestEmailEvidenceProcessorImport:

    def test_module_imports_cleanly(self):
        """Pre-fix this raised AttributeError on `evs.EVIDENCE_ROOT`."""
        # Force a fresh import to defeat any cached module
        import importlib
        if "app.services.email_evidence_processor" in sys.modules:
            del sys.modules["app.services.email_evidence_processor"]
        mod = importlib.import_module("app.services.email_evidence_processor")
        assert hasattr(mod, "process_awb_evidence")
        assert hasattr(mod, "_lock_dir")

    def test_lock_dir_resolves_under_storage_root(self, tmp_path, monkeypatch):
        """_lock_dir() must read settings.storage_root at call time so tests
        can isolate it via monkeypatch."""
        from app.core.config import settings
        monkeypatch.setattr(settings, "storage_root", tmp_path)
        from app.services import email_evidence_processor as proc
        ld = proc._lock_dir()
        assert ld == tmp_path / "email_evidence" / "_locks"

    def test_process_awb_evidence_smoke_runs_without_storage_setup(
        self, tmp_path, monkeypatch,
    ):
        """End-to-end smoke: with no stored evidence, process_awb_evidence
        must return a well-formed result, not crash. Pre-fix this 500'd at
        import time before reaching the function body."""
        from app.core.config import settings
        monkeypatch.setattr(settings, "storage_root", tmp_path)

        from app.services.email_evidence_processor import process_awb_evidence
        result = process_awb_evidence("6049349806", batch_id="BATCH_TEST")
        assert result["awb"] == "6049349806"
        assert result["batch_id"] == "BATCH_TEST"
        assert result["actions"] == []     # no stored messages → no actions
        assert result["skipped"] == 0
        assert result["ts"]


# ── End-to-end visibility: rescan → store → dashboard reader ───────────────

def test_end_to_end_rescan_persistence_dashboard_visibility(
    tmp_path, monkeypatch,
):
    """
    Wire scan_and_ingest with a stub scan_fn that returns one DHL email
    matching AWB 6049349806; assert the dashboard reader's get_by_awb
    surfaces the message + summary.

    This pins the full chain: ingestor → store → reader. Mocks only the
    Zoho transport (scan_fn); everything else is real code on a tmp_path
    storage root.
    """
    from app.core.config import settings
    monkeypatch.setattr(settings, "storage_root", tmp_path)

    awb = "6049349806"
    batch_id = "SHIPMENT_6049349806_2026-05_TESTABC"

    batch_dir = tmp_path / "outputs" / batch_id
    batch_dir.mkdir(parents=True)
    audit_path = batch_dir / "audit.json"
    import json
    audit = {
        "batch_id":    batch_id,
        "awb":         awb,
        "tracking_no": awb,
        "carrier":     "DHL",
        "timeline":    [],
    }
    audit_path.write_text(json.dumps(audit), encoding="utf-8")

    # Stub scan_fn — simulate Zoho returning ONE DHL customs email
    def stub_scan(target_awb=None, limit=50, api_base=None,
                  token_provider=None, dhl_ticket=None,
                  identity_emails=None, **kwargs):
        if target_awb == awb:
            return {
                "scanned": 1, "matched": 1,
                "emails": [{
                    "message_id":   "msg_lvl_001",
                    "thread_id":    "thread_001",
                    "subject":      f"Customs clearance request — AWB {awb}",
                    "from":         "odprawacelna@dhl.com",
                    "received_at":  "2026-05-08T10:00:00",
                    "body_text":    f"Please send customs documents for AWB {awb}.",
                    "to":           ["import@estrellajewels.eu"],
                    "attachments":  [],
                    "dhl_ticket":   "T#1WA9999",
                    "awb":          awb,
                }],
                "scan_method": "rest_api_search",
                "search_mode": "awb_targeted",
                "query_used":  f"searchKey=entire:{awb}",
                "awb_used":    awb,
            }
        return {"scanned": 0, "matched": 0, "emails": [],
                "scan_method": "rest_api_search", "search_mode": "broad_recent",
                "query_used": "", "awb_used": None}

    from app.services.email_evidence_ingestor import scan_and_ingest
    result = scan_and_ingest(
        awb, batch_id, audit_path, audit,
        limit=10,
        token_provider=lambda: "fake",
        scan_fn=stub_scan,
    )

    assert result["ok"] is True
    assert result["ingested"] == 1
    assert "entire:" in result["query_used"], (
        f"ingestor must surface the entire: prefix in query_used; "
        f"got {result['query_used']!r}"
    )

    # Reader path — what the dashboard /email-evidence endpoint returns
    from app.services.email_evidence_store import get_by_awb
    doc = get_by_awb(awb)
    assert doc["awb"] == awb
    assert batch_id in doc.get("batch_ids", [])
    summary = doc.get("summary") or {}
    assert summary.get("dhl_request_received") is True, (
        "evidence summary must mark dhl_request_received=True after a "
        "DHL customs request email is ingested for this AWB"
    )

    # Per-message visibility
    all_msgs = []
    for thread in doc.get("threads", []):
        all_msgs.extend(thread.get("messages", []))
    assert len(all_msgs) == 1
    msg = all_msgs[0]
    assert msg["message_id"] == "msg_lvl_001"
    assert msg["sender"] == "odprawacelna@dhl.com"
    assert msg["event_type"] == "dhl_request"


# ── DHL ticket-thread classifier — subject-based fallback ─────────────────

class TestDhlTicketThreadClassifier:
    """
    The Zoho scanner output sometimes omits ``to`` from the projected
    message dict. The classifier's outgoing branch used to fall through to
    ``other`` whenever ``to_addresses`` was empty, even on obvious DHL
    customs ticket threads. This class pins the subject-based fallback.
    """

    # The exact subject seen live for AWB 6049349806 — pre-fix this returned
    # ``other`` because to_addresses was empty.
    LIVE_SUBJECT = "Re:T#1WA2605070000083 - Agencja Celna DHL - przesyłka numer: 6049349806"

    def test_live_awb_6049349806_subject_returns_our_dhl_reply(self):
        from app.services.email_thread_mapper import classify_event_type
        ev = classify_event_type(
            direction   = "outgoing",
            sender_role = "internal",
            subject     = self.LIVE_SUBJECT,
            body        = "",
            attachments = [],
            to_addresses = [],   # scanner omitted recipient list
        )
        assert ev == "our_dhl_reply", (
            f"AWB 6049349806 reply must classify as our_dhl_reply, got {ev!r}"
        )

    @pytest.mark.parametrize("subject", [
        "T#1WA2605070000083 - Agencja Celna DHL - przesyłka numer: 6049349806",
        "Re:T#1WA2605070000083 - Agencja Celna DHL - przesyłka numer: 6049349806",
        "Fwd: T#1WA9999 — Agencja Celna DHL",
        "Odprawa celna DHL — przesyłka numer: 1234567890",
        "DHL Customs Agency — clearance request",
        "T#1WA0000 plain ticket without other markers",
    ])
    def test_dhl_ticket_subject_variants_classify_our_dhl_reply(self, subject):
        from app.services.email_thread_mapper import classify_event_type
        ev = classify_event_type(
            direction="outgoing", sender_role="internal",
            subject=subject, body="", attachments=[], to_addresses=[],
        )
        assert ev == "our_dhl_reply", f"subject {subject!r} → {ev!r}"

    def test_outgoing_with_explicit_dhl_recipient_still_returns_our_dhl_reply(self):
        """The pre-existing path (to=dhl.com → our_dhl_reply) must keep working."""
        from app.services.email_thread_mapper import classify_event_type
        ev = classify_event_type(
            direction="outgoing", sender_role="internal",
            subject="Re:T#1WA0000 - reply",
            body="", attachments=[],
            to_addresses=["odprawacelna@dhl.com"],
        )
        assert ev == "our_dhl_reply"

    def test_outgoing_to_agency_still_returns_agency_forward(self):
        """Recipient-based agency_forward path unchanged."""
        from app.services.email_thread_mapper import classify_event_type
        # Subject contains a DHL ticket marker but recipient is the agency —
        # recipient match wins, returns agency_forward (this is the
        # forwarding-to-agency case).
        ev = classify_event_type(
            direction="outgoing", sender_role="internal",
            subject="Fwd: T#1WA0000 - forwarded for clearance",
            body="", attachments=[],
            to_addresses=["piotr@acspedycja.pl"],
        )
        assert ev == "agency_forward"

    def test_outgoing_unrelated_subject_still_returns_other(self):
        """Don't blindly classify every internal email as our_dhl_reply."""
        from app.services.email_thread_mapper import classify_event_type
        ev = classify_event_type(
            direction="outgoing", sender_role="internal",
            subject="Re: holiday schedule",
            body="", attachments=[], to_addresses=[],
        )
        assert ev == "other"

    def test_outgoing_subject_no_ticket_no_dhl_phrase_returns_other(self):
        """Plain subject without any DHL marker → other."""
        from app.services.email_thread_mapper import classify_event_type
        ev = classify_event_type(
            direction="outgoing", sender_role="internal",
            subject="Re: invoice payment",
            body="", attachments=[], to_addresses=["accounts@somewhere.com"],
        )
        assert ev == "other"

    def test_incoming_dhl_request_path_unchanged(self):
        """The original DHL request from odprawacelna@dhl.com still classifies
        as dhl_request via the existing sender_role==dhl branch."""
        from app.services.email_thread_mapper import classify_event_type
        ev = classify_event_type(
            direction="incoming", sender_role="dhl",
            subject="T#1WA2605070000083 - Agencja Celna DHL - przesyłka numer: 6049349806",
            body="W celu zachowania ciągłości korespondencji ... tłumaczenie zawartości ...",
            attachments=[], to_addresses=["import@estrellajewels.eu"],
        )
        assert ev == "dhl_request"

    def test_incoming_external_with_ticket_marker_falls_through_to_dhl_request(self):
        """A DHL-style email from a non-canonical sender (forwarder/alias) still
        gets recognized as dhl_request via the subject-based last-resort fallback."""
        from app.services.email_thread_mapper import classify_event_type
        ev = classify_event_type(
            direction="incoming", sender_role="external",
            subject="T#1WA0000 - Agencja Celna DHL - przesyłka numer: 1234567890",
            body="", attachments=[], to_addresses=["import@estrellajewels.eu"],
        )
        assert ev == "dhl_request"


# ── Helper coverage: _is_dhl_ticket_thread ─────────────────────────────────

class TestIsDhlTicketThreadHelper:

    @pytest.mark.parametrize("subject,expected", [
        ("T#1WA2605070000083 - foo", True),
        ("Re:T#1WA2605070000083 - bar", True),
        ("Re: Agencja Celna DHL — przesyłka numer: 1234567890", True),
        ("DHL Customs Agency clearance reminder", True),
        ("Odprawa celna DHL — request", True),
        ("Re: invoice payment", False),
        ("", False),
        ("T#" , False),                       # no token — not a ticket
        ("T#abc12", False),                   # only 5 chars after T# — too short
        ("Random subject T#999", False),     # too few alphanum chars (6+ required)
        ("T#abc123", True),                   # 6 alphanum chars — counts as ticket-shaped
    ])
    def test_subject_match(self, subject, expected):
        from app.services.email_thread_mapper import _is_dhl_ticket_thread
        assert _is_dhl_ticket_thread(subject) is expected, (
            f"_is_dhl_ticket_thread({subject!r}) — expected {expected}"
        )
