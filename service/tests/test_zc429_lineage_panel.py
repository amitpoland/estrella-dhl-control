"""
test_zc429_lineage_panel.py — read-only ZC429 evidence chain in
the dashboard.

Covers:
  • GET /dashboard/batches/{batch_id}/zc429-lineage
      - has_zc429=False cleanly when no ZC429 yet
      - full envelope when present
      - classified_counts computed from lineage rows
      - mismatch warning when audit count != lineage count
      - integrity warning when received=true but no intake_event_id
      - integrity warning when intake_event_id present but row missing
      - endpoint never mutates audit/lineage/email_queue
  • dashboard.html surface
      - ZC429 / SAD Evidence card defined and mounted in PZ/wFirma tab
      - data-testid markers present
      - waiting message appears when no ZC429
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
SAMPLE_BODY    = (
    "Uprzejmie informujemy, że odprawa celna Państwa przesyłki o numerze "
    "listu przewozowego 6049349806 została zakończona według numeru "
    "26PL44302D00AUCWR3."
)
SAMPLE_ATTACHMENTS = [
    {"filename": "ZC429_26PL44302D00AUCWR3_1_PL.xml",  "content": b"<xml/>"},
    {"filename": "ZC429_26PL44302D00AUCWR3_2_PL.pdf",  "content": b"%PDF-zc1"},
    {"filename": "ZC429_26PL44302D00AUCWR3_3_PL.pdf",  "content": b"%PDF-zc2"},
    {"filename": "6049349806.AWB.BOM.GTW.WAW.pdf",     "content": b"%PDF-awb"},
    {"filename": "6049349806^^^^INVOICE^^_EJL_001.pdf","content": b"%PDF-i1"},
    {"filename": "6049349806^^^^INVOICE^^_EJL_002.pdf","content": b"%PDF-i2"},
    {"filename": "6049349806^^^^INVOICE^^_EJL_003.pdf","content": b"%PDF-i3"},
    {"filename": "6049349806^^^^INVOICE^^_EJL_004.pdf","content": b"%PDF-i4"},
    {"filename": "6049349806^^^^MAIL^^_ENTRY.pdf",     "content": b"%PDF-mail"},
    {"filename": "6049349806^^^^OTHERS^^_EXT_1.pdf",   "content": b"%PDF-o1"},
    {"filename": "6049349806^^^^OTHERS^^_EXT_2.pdf",   "content": b"%PDF-o2"},
]


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def staged(tmp_path, monkeypatch):
    """Stage a tmp storage_root + batch + audit, init lineage DB."""
    monkeypatch.setattr(zc.settings, "storage_root", tmp_path, raising=False)
    # Also override settings used by routes_dashboard.
    from app.api import routes_dashboard as rd
    monkeypatch.setattr(rd, "_validate_batch_id", lambda b: None, raising=False)

    batch_id = "SHIPMENT_6049349806_2026-05_7409ac77"
    bdir = tmp_path / "outputs" / batch_id
    bdir.mkdir(parents=True)
    (bdir / "audit.json").write_text(json.dumps({
        "tracking_no":         "6049349806",
        "carrier":             "DHL",
        "customs_declaration": {},
        "timeline":            [],
    }), encoding="utf-8")

    from app.services import email_evidence_store as evs
    monkeypatch.setattr(evs, "_evidence_root",
                        lambda: tmp_path / "email_evidence")
    il.init_intake_lineage(tmp_path / "intake_lineage.db")

    # Patch the routes_dashboard's resolved settings so it reads from
    # tmp_path.  routes_dashboard imports `settings` lazily inside the
    # endpoint, so set the same module attribute zc points at:
    monkeypatch.setattr(rd, "settings", zc.settings, raising=False)

    yield {"tmp": tmp_path, "batch_id": batch_id, "audit": bdir / "audit.json"}
    il._db_path = None


@pytest.fixture
def client(staged, monkeypatch):
    monkeypatch.setenv("API_KEY", "")
    app = FastAPI()
    app.include_router(dashboard_router)
    return TestClient(app)


# ── Endpoint behaviour ──────────────────────────────────────────────────────

class TestEndpointShape:
    def test_has_zc429_false_when_missing(self, client, staged):
        r = client.get(
            f"/dashboard/batches/{staged['batch_id']}/zc429-lineage")
        assert r.status_code == 200
        body = r.json()
        assert body["has_zc429"]       is False
        assert body["intake_event_id"] == ""
        assert body["event"]           is None
        assert body["attachments"]     == []
        assert body["classified_counts"] == {
            "zc429": 0, "awb": 0, "invoices": 0,
            "mail_evidence": 0, "others": 0,
        }
        assert body["processing_history"]     == []
        assert body["linked_timeline_events"] == []
        # Pure-missing case: no warnings either.
        assert body["warnings"] == []

    def test_full_envelope_after_ingest(self, client, staged):
        zc.ingest_zc429_email(
            sender=SAMPLE_SENDER, subject=SAMPLE_SUBJECT, body=SAMPLE_BODY,
            message_id="msg-VIEW", attachments=SAMPLE_ATTACHMENTS,
            batch_id=staged["batch_id"],
        )
        r = client.get(
            f"/dashboard/batches/{staged['batch_id']}/zc429-lineage")
        body = r.json()
        assert body["has_zc429"] is True
        assert body["intake_event_id"]
        ev = body["event"]
        assert ev["awb"]       == "6049349806"
        assert ev["zc_number"] == "26PL44302D00AUCWR3"
        assert ev["sender"]    == SAMPLE_SENDER
        assert ev["processing_version"] == "1.0"
        assert len(body["attachments"]) == 11
        assert body["classified_counts"] == {
            "zc429": 3, "awb": 1, "invoices": 4,
            "mail_evidence": 1, "others": 2,
        }
        # At least one timeline event linked back to the intake event id.
        assert len(body["linked_timeline_events"]) >= 1
        for e in body["linked_timeline_events"]:
            assert e["detail"]["intake_event_id"] == body["intake_event_id"]

    def test_classified_counts_sum_to_attachment_total(self, client, staged):
        zc.ingest_zc429_email(
            sender=SAMPLE_SENDER, subject=SAMPLE_SUBJECT, body=SAMPLE_BODY,
            message_id="msg-CC", attachments=SAMPLE_ATTACHMENTS,
            batch_id=staged["batch_id"],
        )
        body = client.get(
            f"/dashboard/batches/{staged['batch_id']}/zc429-lineage").json()
        counts_total = sum(body["classified_counts"].values())
        assert counts_total == len(body["attachments"]) == 11

    def test_warning_when_received_but_no_intake_event_id(self, client, staged):
        # Hand-craft an audit that claims received=true with no eid.
        bad = json.loads(staged["audit"].read_text(encoding="utf-8"))
        bad["customs_declaration"] = {"received": True, "attachments_count": 5}
        staged["audit"].write_text(json.dumps(bad), encoding="utf-8")

        body = client.get(
            f"/dashboard/batches/{staged['batch_id']}/zc429-lineage").json()
        assert body["has_zc429"] is False
        assert any("intake_event_id" in w for w in body["warnings"])

    def test_warning_when_pointer_is_stale(self, client, staged):
        bad = json.loads(staged["audit"].read_text(encoding="utf-8"))
        bad["customs_declaration"] = {
            "received":         True,
            "intake_event_id":  "not-a-real-uuid",
        }
        staged["audit"].write_text(json.dumps(bad), encoding="utf-8")
        body = client.get(
            f"/dashboard/batches/{staged['batch_id']}/zc429-lineage").json()
        assert body["has_zc429"] is False
        assert any("stale pointer" in w for w in body["warnings"])

    def test_count_mismatch_warning(self, client, staged):
        zc.ingest_zc429_email(
            sender=SAMPLE_SENDER, subject=SAMPLE_SUBJECT, body=SAMPLE_BODY,
            message_id="msg-MM", attachments=SAMPLE_ATTACHMENTS,
            batch_id=staged["batch_id"],
        )
        # Tamper with audit count
        bad = json.loads(staged["audit"].read_text(encoding="utf-8"))
        bad["customs_declaration"]["attachments_count"] = 99
        staged["audit"].write_text(json.dumps(bad), encoding="utf-8")

        body = client.get(
            f"/dashboard/batches/{staged['batch_id']}/zc429-lineage").json()
        assert body["has_zc429"] is True
        assert any("attachments_count=99" in w and "rows=11" in w
                   for w in body["warnings"]), body["warnings"]

    def test_invalid_batch_id_400(self, client):
        r = client.get("/dashboard/batches/..%2Fevil/zc429-lineage")
        # Either 400 from the path-traversal guard or 404 from FastAPI.
        assert r.status_code in (400, 404)


# ── No-mutation guarantee ──────────────────────────────────────────────────

class TestNoMutation:
    def test_endpoint_does_not_mutate_audit_or_lineage(self, client, staged):
        zc.ingest_zc429_email(
            sender=SAMPLE_SENDER, subject=SAMPLE_SUBJECT, body=SAMPLE_BODY,
            message_id="msg-RO", attachments=SAMPLE_ATTACHMENTS,
            batch_id=staged["batch_id"],
        )
        audit_before = staged["audit"].read_bytes()
        ldb = staged["tmp"] / "intake_lineage.db"
        ldb_before  = ldb.stat().st_mtime_ns

        # Hit the endpoint multiple times.
        for _ in range(5):
            client.get(f"/dashboard/batches/{staged['batch_id']}/zc429-lineage")

        audit_after = staged["audit"].read_bytes()
        ldb_after   = ldb.stat().st_mtime_ns
        assert audit_after == audit_before, "audit must not change on read"
        assert ldb_after   == ldb_before,   "lineage DB must not change on read"


# ── Dashboard HTML surface ──────────────────────────────────────────────────

DASHBOARD_HTML = (Path(__file__).resolve().parents[1]
                  / "app" / "static" / "dashboard.html")
# Shipment detail UI lives in its own file (Phase 2 split from dashboard.html)
SHIPMENT_DETAIL_HTML = (Path(__file__).resolve().parents[1]
                        / "app" / "static" / "shipment-detail.html")


def _html() -> str:
    return DASHBOARD_HTML.read_text(encoding="utf-8")


class TestDashboardSurface:
    def test_card_component_defined(self):
        assert "function ZC429EvidenceCard(" in _html()

    def test_card_mounted_in_pz_wfirma_tab(self):
        """ZC429EvidenceCard component is still defined; it is now
        rendered as part of the Evidence section of OperatorWorkflowCard
        (the unified pre-PZ workflow). Verify the workflow card lives
        in the PZ/Accounting tab — that gives the operator access to the
        ZC429 evidence chain.

        Note: detail-panel tab logic lives in shipment-detail.html
        (Phase 2 split).  The ordering check reads that file; the
        component-defined check uses dashboard.html (shared component
        library that both files include).
        """
        h = SHIPMENT_DETAIL_HTML.read_text(encoding="utf-8")
        idx_tab      = h.index("activeTab === 'PZ / Accounting'")
        idx_workflow = h.index("<OperatorWorkflowCard ", idx_tab)
        idx_close    = h.index("Section 3 — PZ / Accounting", idx_tab)
        assert idx_tab < idx_workflow < idx_close
        # ZC429EvidenceCard component is still defined (so its data-testids
        # remain greppable for the rest of this suite)
        assert "function ZC429EvidenceCard(" in h

    def test_card_has_required_data_testids(self):
        h = _html()
        for tid in (
            "zc429-evidence-card",
            "zc429-status-chip",
            "zc429-event-block",
            "zc429-classified-counts",
            "zc429-attachments",
            "zc429-processing-history",
            "zc429-linked-timeline",
            "zc429-warnings",
            "zc429-waiting-message",
        ):
            assert f'data-testid="{tid}"' in h, f"missing testid: {tid}"

    def test_card_uses_only_read_endpoint(self):
        h = _html()
        # The card must call the read-only endpoint and nothing else.
        # Find the function body and look for write verbs / suspicious
        # endpoints inside it.
        start = h.index("function ZC429EvidenceCard(")
        # Match up to the ProformaReadinessCard banner that follows.
        end   = h.index("PROFORMA READINESS PANEL", start)
        body  = h[start:end]
        assert "/zc429-lineage" in body
        # No POST / PUT / DELETE / PATCH from this card.
        for verb in ("method: 'POST'", "method: 'PUT'",
                     "method: 'DELETE'", "method: 'PATCH'"):
            assert verb not in body, \
                f"ZC429 evidence card must be read-only ({verb} present)"
        # Specifically must not reach into PZ create / wFirma write paths.
        for path in ("/api/v1/wfirma/goods/auto-register",
                     "/api/v1/wfirma/customers/auto-create-from-name",
                     "/api/v1/pz/process",
                     "/api/v1/wfirma/pz"):
            assert path not in body

    def test_waiting_message_present(self):
        h = _html()
        assert "Waiting for DHL ZC429 / SAD email" in h
