"""
test_zc429_email_dispatcher.py — mailbox-to-intake bridge.

Covers:
  • plwawecs ZC429 email + on-disk attachments → ingest_zc429_email
  • duplicate message_id → no duplicate lineage rows
  • route_email ZC429 branch wins over generic customs branch
  • odprawacelna semantics unchanged
  • email_classifier returns zc429_completion only for plwawecs + matching body
  • email_search_context advertises plwawecs in known senders
  • dhl_readiness sad_received fallback for legacy mrn-only audits
  • dashboard PZ gate has gating UI + onClick-only pz_create
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.smoke

from app.services import dhl_zc429_intake as zc
from app.services import intake_lineage   as il
from app.services import zc429_email_dispatcher as disp
from app.services import email_classifier as ec
from app.services import email_search_context as esc


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

    # Drop attachments to a sibling staging dir.
    att_dir = tmp_path / "att_in"
    att_dir.mkdir()
    paths = []
    for n in ATT_NAMES:
        p = att_dir / n
        p.write_bytes(("payload-" + n).encode())
        paths.append(str(p))

    yield {"tmp": tmp_path, "batch_id": batch_id,
           "audit_path": bdir / "audit.json", "attachment_paths": paths}
    il._db_path = None


# ── Dispatcher ──────────────────────────────────────────────────────────────

class TestDispatcher:
    def test_plwawecs_email_calls_intake(self, staged):
        rec = {
            "from":        SAMPLE_SENDER,
            "subject":     SAMPLE_SUBJECT,
            "body":        SAMPLE_BODY,
            "received_at": "2026-05-08T11:25:14+02:00",
            "message_id":  "msg-DISP-1",
        }
        res = disp.maybe_dispatch_zc429(
            staged["audit_path"], rec, staged["attachment_paths"])
        assert res is not None
        assert res["ok"] is True
        assert res["awb"] == "6049349806"
        assert res["zc_number"] == "26PL44302D00AUCWR3"
        assert res["attachment_count"] == 11
        assert res["intake_event_id"]
        # Audit + timeline updated
        audit = json.loads(staged["audit_path"].read_text(encoding="utf-8"))
        cd = audit["customs_declaration"]
        assert cd["received"] is True
        assert cd["intake_event_id"] == res["intake_event_id"]
        assert sum(1 for e in audit["timeline"]
                   if e.get("event") == "zc429_received") == 1

    def test_non_zc429_returns_none(self, staged):
        rec = {
            "from": "odprawacelna@dhl.com",
            "subject": "Random update",
            "body": "Hello",
            "message_id": "x",
        }
        assert disp.maybe_dispatch_zc429(
            staged["audit_path"], rec, []) is None

    def test_duplicate_message_id_no_duplicate_rows(self, staged):
        rec = {
            "from": SAMPLE_SENDER, "subject": SAMPLE_SUBJECT,
            "body": SAMPLE_BODY, "message_id": "msg-DUP",
        }
        r1 = disp.maybe_dispatch_zc429(
            staged["audit_path"], rec, staged["attachment_paths"])
        r2 = disp.maybe_dispatch_zc429(
            staged["audit_path"], rec, staged["attachment_paths"])
        assert r1["intake_event_id"] == r2["intake_event_id"]
        assert r2["duplicate"] is True
        atts = il.list_attachments(r1["intake_event_id"])
        assert len(atts) == 11

    def test_missing_attachment_files_tolerated(self, staged):
        bogus = ["/nonexistent/foo.xml"]
        rec = {
            "from": SAMPLE_SENDER, "subject": SAMPLE_SUBJECT,
            "body": SAMPLE_BODY, "message_id": "msg-MISS",
        }
        res = disp.maybe_dispatch_zc429(
            staged["audit_path"], rec, bogus)
        assert res["ok"] is True
        # dispatcher_warnings carries the missing-file note
        assert any("attachment_missing_or_empty" in w
                   for w in res.get("dispatcher_warnings") or [])


# ── Classifier ──────────────────────────────────────────────────────────────

class TestClassifier:
    def test_plwawecs_zc429_returns_zc429_completion(self):
        c = ec.classify_email(
            sender="plwawecs@dhl.com",
            subject=SAMPLE_SUBJECT,
            body=SAMPLE_BODY,
            attachments=ATT_NAMES,
        )
        assert c["type"] == "zc429_completion"
        assert c["sender_role"] == "dhl_agency_notification"
        assert c["awb"] == "6049349806"

    def test_plwawecs_unrelated_email_does_not_misclassify(self):
        c = ec.classify_email(
            sender="plwawecs@dhl.com",
            subject="Test",
            body="Hello",
            attachments=[],
        )
        assert c["type"] == "dhl_agency_other"
        assert c["matched_rule"] == "dhl_waw_unknown_template"

    def test_odprawacelna_semantics_unchanged(self):
        c = ec.classify_email(
            sender="odprawacelna@dhl.com",
            subject="[T#1WA1234567] Agencja Celna DHL - przesyłka 6049349806",
            body="Please send DSK", attachments=[],
        )
        assert c["type"] == "dhl_arrival"
        assert c["matched_rule"] == "dhl_odprawacelna_arrival"

    def test_search_context_includes_plwawecs(self):
        ctx = esc.build_email_search_context({"awb": "6049349806"})
        assert "plwawecs@dhl.com" in ctx["known_senders"]
        assert any("Powiadomienie" in t for t in ctx["search_terms"])


# ── route_email branch ──────────────────────────────────────────────────────

class TestRouteEmailBranch:
    def test_zc429_branch_wins_over_customs_branch(self, staged, monkeypatch):
        from app.services import event_trigger_engine as ete

        # Sentinel — if generic customs path runs, we'll see this.
        called = {"import_customs_docs": 0,
                  "register_agency_documents": 0}
        monkeypatch.setattr(
            ete, "import_customs_docs",
            lambda *a, **kw: (called.__setitem__(
                "import_customs_docs",
                called["import_customs_docs"] + 1) or {"ok": True}),
        )
        monkeypatch.setattr(
            ete, "register_agency_documents",
            lambda *a, **kw: (called.__setitem__(
                "register_agency_documents",
                called["register_agency_documents"] + 1) or {"ok": True}),
        )
        rec = {
            "from":          SAMPLE_SENDER,
            "subject":       SAMPLE_SUBJECT,
            "body":          SAMPLE_BODY,
            "message_id":    "msg-RT-1",
            "detected_type": "zc429_completion",
            "sender_role":   "dhl_agency_notification",
            "received_at":   "2026-05-08T11:25:14+02:00",
        }
        result = ete.route_email(
            str(staged["audit_path"]), rec, staged["attachment_paths"])
        assert result["ok"] is True
        assert result.get("branch") == "zc429_completion"
        # Generic branches MUST NOT have run.
        assert called["import_customs_docs"] == 0
        assert called["register_agency_documents"] == 0
        # ZC429 action recorded.
        actions = result.get("actions") or []
        assert any(a["action"] == "dhl_zc429_intake" for a in actions)


# ── email_ingestion_worker import path ──────────────────────────────────────

class TestIngestionWorkerImport:
    def test_import_resolves_without_dhl_email_monitor(self, monkeypatch):
        # Fail-safe stubs so the worker doesn't reach the network.
        from app.services import email_ingestion_worker as eiw
        from app.services import zoho_auth
        monkeypatch.setattr(zoho_auth, "has_zoho_credentials",
                            lambda: False, raising=False)
        # No active audits → cycle returns ok=False (no_credentials) without
        # raising on the broken legacy import. The key bit: importing the
        # module + calling run_ingestion_cycle does NOT raise ModuleNotFoundError.
        out = eiw.run_ingestion_cycle()
        assert isinstance(out, dict)
        # Either no_credentials (creds missing) or ok=True (no audits) —
        # both are acceptable; the regression we're guarding against is
        # the legacy `from dhl_email_monitor import ...` ModuleNotFoundError.
        assert "scan_fn_unavailable" not in str(out.get("error", ""))


# ── Readiness compatibility ─────────────────────────────────────────────────

class TestReadinessCompatibility:
    def _audit(self, **cd):
        return {
            "batch_id":            "B1",
            "tracking_no":         "6049349806",
            "customs_declaration": cd,
            "timeline":            [],
        }

    def test_received_true_lights_sad_received(self):
        from app.services import dhl_readiness as dr
        out = dr.compute_dhl_readiness(self._audit(received=True,
                                                  received_at="2026-05-08T11:25Z"))
        assert out["dhl_status"] == "sad_received"
        assert out["sad_received"] == "2026-05-08T11:25Z"

    def test_legacy_mrn_only_lights_sad_received(self):
        from app.services import dhl_readiness as dr
        out = dr.compute_dhl_readiness(
            self._audit(mrn="26PL44302D00AUCWR3",
                        clearance_date="2026-05-08"))
        assert out["dhl_status"] == "sad_received"
        assert out["sad_received"] == "2026-05-08"

    def test_no_signal_no_false_readiness(self):
        from app.services import dhl_readiness as dr
        out = dr.compute_dhl_readiness(self._audit())
        assert out["dhl_status"] != "sad_received"
        assert out["sad_received"] is None


# ── Dashboard surface ───────────────────────────────────────────────────────

DASHBOARD_HTML = (Path(__file__).resolve().parents[1]
                  / "app" / "static" / "dashboard.html")
# Shipment detail UI lives in its own file (Phase 2 split from dashboard.html)
SHIPMENT_DETAIL_HTML = (Path(__file__).resolve().parents[1]
                        / "app" / "static" / "shipment-detail.html")

def _html() -> str:
    return DASHBOARD_HTML.read_text(encoding="utf-8")


class TestDashboardSurface:
    def test_execute_pz_gate_component_defined(self):
        assert "function ExecutePZGate(" in _html()

    def test_execute_pz_gate_mounted_in_pz_wfirma_tab(self):
        """ExecutePZGate is embedded inside OperatorWorkflowCard's
        Execute section — reachable from the PZ/Accounting tab via the
        unified workflow.

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
        # ExecutePZGate is rendered inside the workflow body
        assert "<ExecutePZGate " in h

    def test_execute_pz_gate_has_gating_testids(self):
        h = _html()
        for tid in ("execute-pz-gate", "execute-pz-status-chip",
                    "execute-pz-summary", "execute-pz-button",
                    "execute-pz-refresh"):
            assert f'data-testid="{tid}"' in h, f"missing {tid}"

    def test_pz_create_only_inside_onclick_handler(self):
        """The pz_create POST must live ONLY inside an onClick handler.
        On page load / mount / re-render it must NEVER fire automatically."""
        h = _html()
        start = h.index("function ExecutePZGate(")
        end   = h.index("// ════════════════════════════════════════════════════════════════════\n"
                        "// ZC429 / SAD EVIDENCE CARD", start)
        body  = h[start:end]
        # The only POST inside this component is /wfirma/pz_create.
        assert "pz_create" in body
        # The pz_create call sits inside `const onExecute = ...` and is
        # bound to the button via onClick={onExecute}. There must be no
        # top-level await fetch(...pz_create) outside that callback.
        assert "useEffect(() => { refresh(); }" in body
        # Crude but effective: count POST calls; ensure none reference
        # pz_create from useEffect.
        useeffect_block = body[body.index("useEffect"):body.index("onExecute")]
        assert "pz_create" not in useeffect_block

    def test_button_disabled_attr_when_not_ready(self):
        h = _html()
        start = h.index("function ExecutePZGate(")
        end   = h.index("// ZC429 / SAD EVIDENCE CARD", start)
        body  = h[start:end]
        assert "disabled={!enabled}" in body
        # Reasons section is rendered when not enabled.
        assert 'data-testid="execute-pz-reasons"' in body
        # Confirm prompt before any execute.
        assert "window.confirm(" in body
