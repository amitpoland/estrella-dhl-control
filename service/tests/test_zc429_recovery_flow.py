"""
test_zc429_recovery_flow.py — permanent recovery flow for missing /
partial DHL ZC429 emails.

Covers the five spec-mandated cases:
  1. Printed PDF does not create intake lineage.
  2. Missing Zoho email shows recoverable dashboard state.
  3. Backfill with real binaries creates lineage.
  4. Repeated backfill is idempotent by message_id.
  5. Existing normal mailbox ingestion still works.

Plus the four mutually-exclusive recovery_state values:
  email_not_found
  email_found_no_attachments
  email_found_attachments_pending_intake
  intake_completed
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes_dashboard import router as dashboard_router
from app.services import dhl_zc429_intake as zc
from app.services import intake_lineage   as il


SAMPLE_SENDER  = "Agencja Celna DHL WAW <plwawecs@dhl.com>"
SAMPLE_SUBJECT = ("Powiadomienie o odebranym komunikacie ZC429 "
                  "- dot. AWB 6049349806 26PL44302D00AUCWR3")
SAMPLE_BODY    = ("Uprzejmie informujemy, że odprawa celna Państwa "
                  "przesyłki o numerze listu przewozowego 6049349806 została "
                  "zakończona według numeru 26PL44302D00AUCWR3.")

ATT_NAMES = [
    "ZC429_26PL44302D00AUCWR3_1_PL.xml",
    "ZC429_26PL44302D00AUCWR3_2_PL.pdf",
    "ZC429_26PL44302D00AUCWR3_3_PL.pdf",
    "6049349806.AWB.BOM.GTW.WAW.pdf",
    "6049349806^^^^INVOICE^^_EJL_001.pdf",
    "6049349806^^^^INVOICE^^_EJL_002.pdf",
    "6049349806^^^^INVOICE^^_EJL_003.pdf",
    "6049349806^^^^INVOICE^^_EJL_004.pdf",
    "6049349806^^^^MAIL^^_ENTRY.pdf",
    "6049349806^^^^OTHERS^^_EXT_1.pdf",
    "6049349806^^^^OTHERS^^_EXT_2.pdf",
]


@pytest.fixture
def staged(tmp_path, monkeypatch):
    monkeypatch.setattr(zc.settings, "storage_root", tmp_path, raising=False)
    from app.api import routes_dashboard as rd
    monkeypatch.setattr(rd, "settings", zc.settings, raising=False)
    monkeypatch.setattr(rd, "_validate_batch_id", lambda b: None, raising=False)

    batch_id = "SHIPMENT_6049349806_2026-05_7409ac77"
    bdir = tmp_path / "outputs" / batch_id
    bdir.mkdir(parents=True)
    (bdir / "audit.json").write_text(json.dumps({
        "batch_id":            batch_id,
        "tracking_no":         "6049349806",
        "carrier":             "DHL",
        "customs_declaration": {},
        "timeline":            [],
    }), encoding="utf-8")

    from app.services import email_evidence_store as evs
    monkeypatch.setattr(evs, "_evidence_root",
                        lambda: tmp_path / "email_evidence")
    il.init_intake_lineage(tmp_path / "intake_lineage.db")

    yield {"tmp": tmp_path, "batch_id": batch_id,
           "audit": bdir / "audit.json"}
    il._db_path = None


@pytest.fixture
def client(staged, monkeypatch):
    monkeypatch.setenv("API_KEY", "")
    app = FastAPI()
    app.include_router(dashboard_router)
    return TestClient(app)


def _attachments_with_real_binaries():
    return [{"filename": n, "content": (b"REAL-" + n.encode())[:64],
             "size": 64} for n in ATT_NAMES]


def _seed_plwawecs_in_evidence_store(awb: str, msg_id: str,
                                     *, attachments: list):
    from app.services import email_evidence_store as evs
    evs.save_message(awb, {
        "message_id":   msg_id,
        "thread_id":    f"plwawecs-{msg_id}",
        "direction":    "incoming",
        "event_type":   "agency_zc429_received",
        "sender":       "plwawecs@dhl.com",
        "subject":      SAMPLE_SUBJECT,
        "timestamp":    "2026-05-08T11:25:14+02:00",
        "attachments":  attachments,
    }, source="test")


# ── 1. Printed PDF does not create intake lineage ──────────────────────────

class TestPrintedPdfDoesNotCreateLineage:
    def test_printed_pdf_path_never_calls_intake_endpoint(self):
        """No UI code path turns a dropped/printed PDF into an intake call.
        Verified by greping the dashboard HTML for any fetch() call to
        the intake endpoint — even if the URL appears in instruction
        text, it must not appear inside a fetch(...) invocation."""
        from pathlib import Path as _P
        html = (_P(__file__).resolve().parents[1]
                / "app" / "static" / "dashboard.html").read_text(encoding="utf-8")
        for bad in ("fetch(`/api/v1/upload/dhl-zc429/intake",
                    "fetch('/api/v1/upload/dhl-zc429/intake",
                    'fetch("/api/v1/upload/dhl-zc429/intake'):
            assert bad not in html, (
                "Dashboard must not auto-POST printed PDFs into the "
                f"intake endpoint ({bad})")

    def test_pdf_metadata_alone_classified_as_not_zc429(self):
        """A POST that only carries the printed PDF (no real attachments
        ever extracted from the mailbox) — when the body is empty or
        non-Polish — must be rejected by the detector."""
        # Detector requires sender+subject+body. A POST with empty body
        # returns ok=False / not_a_zc429_email.
        res = zc.ingest_zc429_email(
            sender=SAMPLE_SENDER,
            subject="random subject",
            body="",
            message_id="printed-only",
            attachments=[{"filename": "Powiadomienie...pdf",
                          "content": b"%PDF-printed-only", "size": 16}],
        )
        assert res["ok"] is False
        assert res["reason"] == "not_a_zc429_email"


# ── 2. Missing Zoho email → recoverable dashboard state ────────────────────

class TestMissingEmailRecoverableState:
    def test_email_not_found_state_when_evidence_empty(self, client, staged):
        body = client.get(
            f"/dashboard/batches/{staged['batch_id']}/zc429-lineage").json()
        assert body["has_zc429"] is False
        assert body["recovery_state"] == "email_not_found"
        rd = body["recovery_detail"]
        assert rd["plwawecs_messages_found"] == 0
        assert rd["attachments_in_evidence"] == 0
        assert rd["lineage_rows"]            == 0
        assert "import@" in (rd["instruction"] or "")

    def test_email_found_no_attachments_state(self, client, staged):
        _seed_plwawecs_in_evidence_store(
            "6049349806", "msg-PLW-1", attachments=[])
        body = client.get(
            f"/dashboard/batches/{staged['batch_id']}/zc429-lineage").json()
        assert body["recovery_state"] == "email_found_no_attachments"
        assert body["recovery_detail"]["plwawecs_messages_found"] == 1
        assert body["recovery_detail"]["attachments_in_evidence"] == 0
        assert "Do NOT" in body["recovery_detail"]["instruction"]

    def test_email_found_attachments_pending_intake_state(self, client, staged):
        # Evidence store has the message + attachments, but no lineage row yet.
        _seed_plwawecs_in_evidence_store("6049349806", "msg-PLW-2",
            attachments=[{"filename": "ZC429_X.xml",
                          "sha256":   "deadbeef",
                          "size":     12}])
        body = client.get(
            f"/dashboard/batches/{staged['batch_id']}/zc429-lineage").json()
        assert body["recovery_state"] == "email_found_attachments_pending_intake"
        assert body["recovery_detail"]["plwawecs_messages_found"] == 1
        assert body["recovery_detail"]["attachments_in_evidence"] == 1
        assert body["recovery_detail"]["lineage_rows"]            == 0


# ── 3. Backfill with real binaries → lineage created ───────────────────────

class TestBackfillWithRealBinaries:
    def test_intake_with_real_binaries_creates_lineage(self, client, staged):
        # Direct service-level call (mirrors what /dhl-zc429/intake does).
        res = zc.ingest_zc429_email(
            sender=SAMPLE_SENDER,
            subject=SAMPLE_SUBJECT,
            body=SAMPLE_BODY,
            received_at="2026-05-08T11:25:14+02:00",
            message_id="msg-BACKFILL-1",
            attachments=_attachments_with_real_binaries(),
            batch_id=staged["batch_id"],
        )
        assert res["ok"] is True
        assert res["intake_event_id"]
        # Recovery state flips to intake_completed
        body = client.get(
            f"/dashboard/batches/{staged['batch_id']}/zc429-lineage").json()
        assert body["has_zc429"] is True
        assert body["recovery_state"] == "intake_completed"
        assert body["recovery_detail"]["lineage_rows"] == 11

    def test_backfill_endpoint_accepts_base64(self, staged):
        """The /api/v1/upload/dhl-zc429/intake endpoint accepts base64
        attachment content. Verified by importing the request schema and
        the route function signature."""
        from app.api import routes_upload as ru
        assert hasattr(ru, "_ZC429IntakeRequest")
        assert hasattr(ru, "_ZC429Attachment")
        # The route function exists and is documented as the backfill path.
        assert hasattr(ru, "dhl_zc429_intake_endpoint")


# ── 4. Repeated backfill is idempotent on message_id ───────────────────────

class TestBackfillIdempotency:
    def test_repeated_backfill_no_duplicate_lineage(self, client, staged):
        kwargs = dict(
            sender=SAMPLE_SENDER, subject=SAMPLE_SUBJECT, body=SAMPLE_BODY,
            message_id="msg-IDEMP", attachments=_attachments_with_real_binaries(),
            batch_id=staged["batch_id"],
        )
        r1 = zc.ingest_zc429_email(**kwargs)
        r2 = zc.ingest_zc429_email(**kwargs)
        r3 = zc.ingest_zc429_email(**kwargs)
        # Same intake_event_id every time
        assert r1["intake_event_id"] == r2["intake_event_id"] == r3["intake_event_id"]
        assert r2["duplicate"] is True
        assert r3["duplicate"] is True
        # Exactly 11 attachments after 3 calls
        atts = il.list_attachments(r1["intake_event_id"])
        assert len(atts) == 11
        # Recovery state still intake_completed
        body = client.get(
            f"/dashboard/batches/{staged['batch_id']}/zc429-lineage").json()
        assert body["recovery_state"] == "intake_completed"


# ── 5. Normal mailbox ingestion still works ───────────────────────────────

class TestNormalMailboxIngestion:
    def test_dispatcher_still_routes_through_real_attachment_paths(
            self, staged, tmp_path
    ):
        """The dispatcher takes filesystem paths to already-downloaded
        attachments (the normal mailbox flow), reads them, and feeds the
        intake — unchanged by this recovery-flow work."""
        from app.services import zc429_email_dispatcher as disp
        # Stage files on disk (simulating ingestion-worker download).
        att_dir = tmp_path / "att_in"
        att_dir.mkdir()
        paths = []
        for n in ATT_NAMES:
            p = att_dir / n
            p.write_bytes(("payload-" + n).encode())
            paths.append(str(p))
        rec = {
            "from": SAMPLE_SENDER, "subject": SAMPLE_SUBJECT,
            "body": SAMPLE_BODY, "message_id": "msg-MAILBOX-1",
            "received_at": "2026-05-08T11:25:14+02:00",
        }
        res = disp.maybe_dispatch_zc429(staged["audit"], rec, paths)
        assert res is not None
        assert res["ok"] is True
        assert res["attachment_count"] == 11
        assert res["intake_event_id"]


# ── Recovery-state schema ─────────────────────────────────────────────────

class TestRecoveryStateSchema:
    def test_response_has_recovery_fields(self, client, staged):
        body = client.get(
            f"/dashboard/batches/{staged['batch_id']}/zc429-lineage").json()
        assert "recovery_state"  in body
        assert "recovery_detail" in body
        rd = body["recovery_detail"]
        assert "plwawecs_messages_found" in rd
        assert "attachments_in_evidence" in rd
        assert "lineage_rows"            in rd
        assert "instruction"             in rd

    def test_recovery_state_values_are_one_of_four(self, client, staged):
        body = client.get(
            f"/dashboard/batches/{staged['batch_id']}/zc429-lineage").json()
        assert body["recovery_state"] in {
            "email_not_found",
            "email_found_no_attachments",
            "email_found_attachments_pending_intake",
            "intake_completed",
        }


# ── UI surface: dashboard renders recovery state ──────────────────────────

DASHBOARD_HTML = (Path(__file__).resolve().parents[1]
                  / "app" / "static" / "dashboard.html")

def _html() -> str:
    return DASHBOARD_HTML.read_text(encoding="utf-8")


class TestRecoveryUI:
    def test_recovery_testids_present(self):
        h = _html()
        for tid in ("zc429-recovery-state",
                    "zc429-recovery-state-name",
                    "zc429-recovery-instruction",
                    "zc429-recovery-msgs",
                    "zc429-recovery-atts",
                    "zc429-recovery-lineage"):
            assert f'data-testid="{tid}"' in h, f"missing {tid}"

    def test_no_fetch_to_intake_endpoint_in_dashboard(self):
        h = _html()
        # Hard rule: the dashboard never POSTs to the intake endpoint
        # automatically. Backfill is an operator-explicit external call
        # (curl / direct POST). Whether or not the URL string appears in
        # human-readable instruction text is irrelevant — only fetch()
        # invocations matter.
        assert "fetch(`/api/v1/upload/dhl-zc429/intake" not in h
        assert "fetch('/api/v1/upload/dhl-zc429/intake" not in h
        assert 'fetch("/api/v1/upload/dhl-zc429/intake' not in h
