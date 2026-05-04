"""
test_lifecycle_layer.py — Combined coverage for the 8 lifecycle modules:
  customs_doc_classifier, shipment_folder_manager, sad_importer,
  workdrive_sync, agency_sla_engine, agency_sad_monitor,
  service_invoice_monitor, shipment_closure.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo  # type: ignore

_SVC = Path(__file__).parent.parent
sys.path.insert(0, str(_SVC))


def _settings(tmp_path: Path, workdrive_root: str = ""):
    class S:
        storage_root = tmp_path
        workdrive_sync_root = workdrive_root
    return S()


def _seed_audit(tmp_path: Path, batch_id: str, **fields) -> Path:
    p = tmp_path / "outputs" / batch_id / "audit.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    base = {"batch_id": batch_id, "tracking_no": "1010101010", "awb": "1010101010"}
    base.update(fields)
    p.write_text(json.dumps(base), encoding="utf-8")
    return p


# ── Classifier ───────────────────────────────────────────────────────────────

def test_classifier_xml_html_pdf():
    from app.services.customs_doc_classifier import classify
    assert classify("ZC429_AWB123.xml")["type"]   == "customs_xml"
    assert classify("PZC.html")["type"]            == "customs_html"
    assert classify("ZC429_AWB123.pdf")["type"]    == "customs_pdf"
    assert classify("DSK_123.pdf")["type"]         == "customs_pdf"
    assert classify("Polish_desc.pdf")["type"]     == "polish_desc"
    assert classify("INV.pdf")["type"]             == "invoice"
    assert classify("AWB_123.pdf")["type"]         == "awb"
    assert classify("nota_celna.pdf")["type"]      == "duty_note"
    assert classify("random.docx")["type"]         == "other"
    assert classify("")["type"]                    == "unknown"


def test_classifier_invoice_pattern():
    from app.services.customs_doc_classifier import classify
    r = classify("EJL-25-26-1247-09-03-26.pdf")
    assert r["type"] == "invoice"


# ── Folder manager ───────────────────────────────────────────────────────────

def test_folder_layout_created(tmp_path, monkeypatch):
    from app.services import shipment_folder_manager as fm
    monkeypatch.setattr(fm, "settings", _settings(tmp_path))
    layout = fm.ensure_layout("B_FOLDER")
    assert "01_invoices" in layout
    assert "06_customs_docs" in layout
    assert (tmp_path / "shipments" / "B_FOLDER" / "07_pz_output").is_dir()


def test_folder_routing_by_doc_type(tmp_path, monkeypatch):
    from app.services import shipment_folder_manager as fm
    monkeypatch.setattr(fm, "settings", _settings(tmp_path))
    src = tmp_path / "src.pdf"
    src.write_bytes(b"data")
    out = fm.save_file("B_ROUTE", str(src), "invoice")
    assert "01_invoices" in str(out)
    out2 = fm.save_file("B_ROUTE", str(src), "customs_xml")
    assert "06_customs_docs" in str(out2)


def test_folder_idempotent_same_size(tmp_path, monkeypatch):
    from app.services import shipment_folder_manager as fm
    monkeypatch.setattr(fm, "settings", _settings(tmp_path))
    src = tmp_path / "src.pdf"
    src.write_bytes(b"AAAA")
    a = fm.save_file("B_IDEM", str(src), "invoice")
    b = fm.save_file("B_IDEM", str(src), "invoice")
    assert a == b   # no rename — same size, treated as identical


def test_folder_versioning_on_size_conflict(tmp_path, monkeypatch):
    from app.services import shipment_folder_manager as fm
    monkeypatch.setattr(fm, "settings", _settings(tmp_path))
    # Two source files with same NAME but different content (different dirs)
    d1 = tmp_path / "a"; d1.mkdir(); src1 = d1 / "x.pdf"; src1.write_bytes(b"AAAA")
    d2 = tmp_path / "b"; d2.mkdir(); src2 = d2 / "x.pdf"; src2.write_bytes(b"BBBBBB")
    a = fm.save_file("B_VER", str(src1), "invoice")
    b = fm.save_file("B_VER", str(src2), "invoice")
    assert a != b
    assert "_v2" in b.name


# ── WorkDrive sync (TrueSync) ────────────────────────────────────────────────

def test_workdrive_skipped_when_not_configured(tmp_path, monkeypatch):
    from app.services import workdrive_sync as ws
    monkeypatch.setattr(ws, "settings", _settings(tmp_path, workdrive_root=""))
    src = tmp_path / "x.pdf"; src.write_bytes(b"data")
    r = ws.sync_to_workdrive("B_WD_OFF", src)
    assert r["synced"] is False
    assert r["reason"] == "workdrive_not_configured"


def test_workdrive_copies_to_truesync(tmp_path, monkeypatch):
    from app.services import workdrive_sync as ws
    wd_root = tmp_path / "workdrive"
    monkeypatch.setattr(ws, "settings", _settings(tmp_path, workdrive_root=str(wd_root)))
    src_dir = tmp_path / "shipments" / "B_WD" / "01_invoices"
    src_dir.mkdir(parents=True)
    src = src_dir / "INV.pdf"; src.write_bytes(b"invoice content")
    r = ws.sync_to_workdrive("B_WD", src)
    assert r["synced"] is True
    assert (wd_root / "Shipments" / "B_WD" / "01_invoices" / "INV.pdf").is_file()


# ── SAD importer ─────────────────────────────────────────────────────────────

def test_sad_importer_classifies_and_routes(tmp_path, monkeypatch):
    from app.services import sad_importer as si
    from app.services import shipment_folder_manager as fm
    from app.services import workdrive_sync as ws
    s = _settings(tmp_path)
    monkeypatch.setattr(si, "settings", s)
    monkeypatch.setattr(fm, "settings", s)
    monkeypatch.setattr(ws, "settings", s)

    _seed_audit(tmp_path, "B_SAD")
    files = []
    for nm in ("ZC429_X.xml", "SAD_X.pdf", "INV-1.pdf"):
        f = tmp_path / nm
        f.write_bytes(b"%PDF " + nm.encode())
        files.append(str(f))
    out = si.import_customs_docs("B_SAD", files, source="operator", auto_trigger_pz=False)
    assert out["ok"] is True
    assert len(out["imported"]) == 3
    audit = json.loads((tmp_path / "outputs" / "B_SAD" / "audit.json").read_text())
    types = {f["type"] for f in audit["customs_docs"]["files"]}
    assert "customs_xml" in types
    assert "customs_pdf" in types


# ── Agency SLA engine ────────────────────────────────────────────────────────

def _pl(year=2026, month=4, day=29, hour=10, minute=0):
    from app.services.dhl_followup_sla import POLAND_TZ
    return datetime(year, month, day, hour, minute, tzinfo=POLAND_TZ)


def test_agency_sla_first_at_2h_in_window():
    from app.services.agency_sla_engine import calculate_first_agency_followup_at
    out = calculate_first_agency_followup_at(_pl(hour=9))
    assert out.hour == 11 and out.minute == 0   # 09:00 + 2h = 11:00


def test_agency_sla_15_30_pushes_to_next_day_08():
    from app.services.agency_sla_engine import calculate_first_agency_followup_at
    out = calculate_first_agency_followup_at(_pl(hour=15, minute=30))
    # 15:30 + 2h = 17:30 → next day 08:00
    assert out.day == 30 and out.hour == 8


def test_agency_sla_lifecycle_start_record_stop():
    from app.services.agency_sla_engine import (
        start_agency_sla, record_agency_followup_sent, stop_agency_sla,
        is_agency_followup_due,
    )
    audit = {}
    start_agency_sla(audit, _pl(hour=9), "fwd_sent")
    sla = audit["sla"]
    assert sla["active"] is True
    assert sla["agency_followups"] == 0
    record_agency_followup_sent(audit, when=_pl(hour=11))
    assert audit["sla"]["agency_followups"] == 1
    assert audit["sla"]["next_followup_at"].startswith("2026-04-29T12:00")
    stop_agency_sla(audit, "agency_documents_received")
    assert audit["sla"]["active"] is False
    assert audit["sla"]["stop_reason"] == "agency_documents_received"


# ── Agency SAD monitor (push API) ────────────────────────────────────────────

def test_register_agency_documents_idempotent(tmp_path, monkeypatch):
    from app.services import agency_sad_monitor as asm
    from app.services import shipment_folder_manager as fm
    from app.services import workdrive_sync as ws
    s = _settings(tmp_path)
    for mod in (asm, fm, ws):
        monkeypatch.setattr(mod, "settings", s)
    _seed_audit(tmp_path, "B_REG")
    src = tmp_path / "PZC.pdf"; src.write_bytes(b"PDF")
    out1 = asm.register_agency_documents("B_REG", [str(src)])
    out2 = asm.register_agency_documents("B_REG", [str(src)])
    assert out1["ok"] and out2["ok"]
    audit = json.loads((tmp_path / "outputs" / "B_REG" / "audit.json").read_text())
    # Single file even after second call
    assert audit["agency_documents_received_state"]["files_count"] == 1
    assert audit["agency_documents_received"] is True


# ── Fix 1: no false receipt on all-invalid paths ─────────────────────────────

def test_register_agency_docs_all_invalid_paths_does_not_set_received(tmp_path, monkeypatch):
    """All-nonexistent paths must NOT write received=True to audit."""
    from app.services import agency_sad_monitor as asm
    from app.services import shipment_folder_manager as fm
    from app.services import workdrive_sync as ws
    s = _settings(tmp_path)
    for mod in (asm, fm, ws):
        monkeypatch.setattr(mod, "settings", s)
    _seed_audit(tmp_path, "B_BAD")
    out = asm.register_agency_documents("B_BAD", ["/nonexistent/SAD_12345.pdf"])
    assert out["ok"] is False
    assert out["error"] == "no_files_imported"
    # Audit must NOT have received=True
    audit = json.loads((tmp_path / "outputs" / "B_BAD" / "audit.json").read_text())
    assert audit.get("agency_documents_received") is not True
    state = audit.get("agency_documents_received_state") or {}
    assert state.get("received") is not True


def test_register_agency_docs_all_invalid_paths_returns_skipped(tmp_path, monkeypatch):
    """All-invalid-paths response must include skipped list and ok:False."""
    from app.services import agency_sad_monitor as asm
    from app.services import shipment_folder_manager as fm
    from app.services import workdrive_sync as ws
    s = _settings(tmp_path)
    for mod in (asm, fm, ws):
        monkeypatch.setattr(mod, "settings", s)
    _seed_audit(tmp_path, "B_SKIP2")
    out = asm.register_agency_documents("B_SKIP2", [
        "/nonexistent/a.pdf",
        "/nonexistent/b.pdf",
    ])
    assert out["ok"] is False
    assert out["error"] == "no_files_imported"
    assert len(out["skipped"]) == 2
    assert out["files_total"] == 0
    assert out["imported"] == []


def test_register_agency_docs_one_valid_sets_received(tmp_path, monkeypatch):
    """One valid file path must set received=True and return ok:True."""
    from app.services import agency_sad_monitor as asm
    from app.services import shipment_folder_manager as fm
    from app.services import workdrive_sync as ws
    s = _settings(tmp_path)
    for mod in (asm, fm, ws):
        monkeypatch.setattr(mod, "settings", s)
    _seed_audit(tmp_path, "B_VALID")
    src = tmp_path / "SAD_001.pdf"; src.write_bytes(b"%PDF-1.4")
    out = asm.register_agency_documents("B_VALID", [str(src)])
    assert out["ok"] is True
    assert len(out["imported"]) == 1
    assert out["files_total"] == 1
    audit = json.loads((tmp_path / "outputs" / "B_VALID" / "audit.json").read_text())
    assert audit["agency_documents_received"] is True
    assert audit["agency_documents_received_state"]["received"] is True
    assert audit["agency_documents_received_state"]["files_count"] == 1


def test_register_agency_docs_mixed_valid_invalid(tmp_path, monkeypatch):
    """Mixed valid + invalid: valid file imported, invalid reported in skipped."""
    from app.services import agency_sad_monitor as asm
    from app.services import shipment_folder_manager as fm
    from app.services import workdrive_sync as ws
    s = _settings(tmp_path)
    for mod in (asm, fm, ws):
        monkeypatch.setattr(mod, "settings", s)
    _seed_audit(tmp_path, "B_MIX")
    good = tmp_path / "ZC429_abc.pdf"; good.write_bytes(b"data")
    out = asm.register_agency_documents("B_MIX", [str(good), "/no/such/file.pdf"])
    assert out["ok"] is True
    assert len(out["imported"]) == 1
    assert len(out["skipped"])  == 1
    audit = json.loads((tmp_path / "outputs" / "B_MIX" / "audit.json").read_text())
    assert audit["agency_documents_received"] is True


# ── Fix 2: multipart upload endpoint ─────────────────────────────────────────

def _make_app(tmp_path, monkeypatch):
    """Return a TestClient wired to the real lifecycle router with patched settings."""
    import importlib
    from app.services import agency_sad_monitor as asm
    from app.services import shipment_folder_manager as fm
    from app.services import workdrive_sync as ws
    from app.api   import routes_lifecycle as rl
    from app.core  import security as sec
    s = _settings(tmp_path)
    for mod in (asm, fm, ws):
        monkeypatch.setattr(mod, "settings", s)
    # Disable auth for unit tests
    monkeypatch.setattr(sec, "require_api_key", lambda: None)
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    # Reload to pick up patched auth dependency
    importlib.reload(rl)
    app = FastAPI()
    app.include_router(rl.router)
    return TestClient(app)


def _make_upload_client(tmp_path, monkeypatch):
    """Return a TestClient for the lifecycle router with auth bypassed."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api import routes_lifecycle as rl
    from app.core.security import require_api_key
    from app.services import agency_sad_monitor as asm
    from app.services import shipment_folder_manager as fm
    from app.services import workdrive_sync as ws
    s = _settings(tmp_path)
    for mod in (asm, fm, ws):
        monkeypatch.setattr(mod, "settings", s)
    app = FastAPI()
    app.include_router(rl.router)
    # Override auth dependency so tests don't need an API key
    app.dependency_overrides[require_api_key] = lambda: None
    return TestClient(app)


def test_upload_agency_docs_saves_and_registers(tmp_path, monkeypatch):
    """Multipart upload with one valid PDF must set received=True in audit."""
    _seed_audit(tmp_path, "B_UP")
    client = _make_upload_client(tmp_path, monkeypatch)

    pdf_content = b"%PDF-1.4 test agency document"
    resp = client.post(
        "/api/v1/agency-documents/B_UP/upload",
        files=[("files", ("SAD_001.pdf", pdf_content, "application/pdf"))],
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert body["files_total"] >= 1
    audit = json.loads((tmp_path / "outputs" / "B_UP" / "audit.json").read_text())
    assert audit["agency_documents_received"] is True


def test_upload_agency_docs_rejects_no_files(tmp_path, monkeypatch):
    """Upload with zero files must return 422."""
    _seed_audit(tmp_path, "B_NOFILE")
    client = _make_upload_client(tmp_path, monkeypatch)

    resp = client.post("/api/v1/agency-documents/B_NOFILE/upload")
    assert resp.status_code in (422, 400), resp.text


def test_upload_agency_docs_rejects_invalid_extension(tmp_path, monkeypatch):
    """Upload with .exe extension must return 400."""
    _seed_audit(tmp_path, "B_EXT")
    client = _make_upload_client(tmp_path, monkeypatch)

    resp = client.post(
        "/api/v1/agency-documents/B_EXT/upload",
        files=[("files", ("malware.exe", b"MZ\x90\x00", "application/octet-stream"))],
    )
    assert resp.status_code == 400, resp.text


# ── Safety: no fake paths in implementation ──────────────────────────────────

def test_no_dev_null_in_agency_sad_monitor():
    """/dev/null must not appear in agency_sad_monitor.py."""
    src = Path(__file__).parent.parent / "app" / "services" / "agency_sad_monitor.py"
    assert "/dev/null" not in src.read_text(encoding="utf-8")


def test_no_dev_null_in_routes_lifecycle():
    """/dev/null must not appear in routes_lifecycle.py."""
    src = Path(__file__).parent.parent / "app" / "api" / "routes_lifecycle.py"
    assert "/dev/null" not in src.read_text(encoding="utf-8")


def test_no_placeholder_path_in_agency_upload_endpoint():
    """The upload endpoint must not reference fake or placeholder file paths."""
    src = Path(__file__).parent.parent / "app" / "api" / "routes_lifecycle.py"
    content = src.read_text(encoding="utf-8")
    # Find upload endpoint block
    idx = content.find("upload_agency_docs_endpoint")
    assert idx != -1
    snippet = content[idx:idx + 2000]
    # Only check for actual fake path patterns — not the English word "placeholder"
    # which legitimately appears in the docstring ("Does not use placeholder paths.")
    for bad in ("/dev/null", "fake_path", "manual_receipt"):
        assert bad not in snippet, f"Forbidden fake path '{bad}' in upload endpoint"


# ── Service invoice monitor ──────────────────────────────────────────────────

def test_service_invoice_vendor_classification(tmp_path, monkeypatch):
    from app.services import service_invoice_monitor as sim
    from app.services import shipment_folder_manager as fm
    from app.services import workdrive_sync as ws
    s = _settings(tmp_path)
    for mod in (sim, fm, ws):
        monkeypatch.setattr(mod, "settings", s)
    _seed_audit(tmp_path, "B_INV")
    f1 = tmp_path / "DHL_Invoice_123.pdf"; f1.write_bytes(b"d")
    f2 = tmp_path / "Ganther_FV2026_001.pdf"; f2.write_bytes(b"g")
    out = sim.register_service_invoices("B_INV", [str(f1), str(f2)])
    assert out["dhl_invoice_received"]    is True
    assert out["agency_invoice_received"] is True
    audit = json.loads((tmp_path / "outputs" / "B_INV" / "audit.json").read_text())
    vendors = {x["vendor"] for x in audit["service_invoices"]}
    assert "DHL"     in vendors
    assert "Ganther" in vendors


# ── Closure engine ───────────────────────────────────────────────────────────

def test_closure_not_ready_when_missing_anything(tmp_path, monkeypatch):
    from app.services import shipment_closure as sc
    from app.services.shipment_closure import evaluate_closure
    audit = {"customs_docs": {"received": True},
             "polish_desc_filename": "x.pdf",
             "agency_invoice_received": True,
             "dhl_invoice_received": False}
    d = evaluate_closure(audit)
    assert d["ready"] is False
    assert "dhl_invoice_received" in d["missing"]


def test_closure_ready_when_all_true(tmp_path, monkeypatch):
    from app.services import shipment_closure as sc
    monkeypatch.setattr(sc, "settings", _settings(tmp_path))
    p = _seed_audit(tmp_path, "B_CLOSE",
                    customs_docs={"received": True},
                    polish_desc_filename="x.pdf",
                    agency_invoice_received=True,
                    dhl_invoice_received=True)
    out = sc.apply_closure(p)
    assert out["ok"] is True
    assert out["ready"] is True
    audit_after = json.loads(p.read_text())
    assert audit_after["status"]               == "completed"
    assert audit_after["ready_for_accounting"] is True
    assert audit_after["closed_at"]


def test_closure_idempotent(tmp_path, monkeypatch):
    from app.services import shipment_closure as sc
    monkeypatch.setattr(sc, "settings", _settings(tmp_path))
    p = _seed_audit(tmp_path, "B_IDEM_CL",
                    customs_docs={"received": True},
                    polish_desc_filename="x.pdf",
                    agency_invoice_received=True,
                    dhl_invoice_received=True)
    out1 = sc.apply_closure(p)
    out2 = sc.apply_closure(p)
    assert out1["ready"] is True
    assert out2.get("already_completed") is True


# ── Monitor wiring: agency SLA start + closure auto-fire ─────────────────────

def test_monitor_starts_agency_sla_after_forward_sent(tmp_path, monkeypatch):
    from app.services import active_shipment_monitor as m
    from app.services import ai_bridge as ab
    monkeypatch.setattr(m,  "settings", _settings(tmp_path))
    monkeypatch.setattr(ab, "settings", _settings(tmp_path))
    # scan_active_shipments runs an autonomous email ingestion step (Step 0)
    # before processing any batches. That step calls get_valid_access_token()
    # which opens a real TLS connection to Zoho. Stub it out so the test stays
    # fully offline and exercises only the SLA-start logic it is named for.
    monkeypatch.setattr(
        "app.services.email_ingestion_worker.run_ingestion_cycle",
        lambda **kw: {"ok": False, "error": "stubbed", "active_batches": 0, "shipments": []},
    )
    _seed_audit(tmp_path, "B_FUSED",
                clearance_status="awaiting_dhl_customs_email",
                clearance_decision={"total_value_usd": 5000,
                                    "clearance_path":  "external_agency_clearance"},
                agency_forward_after_dhl={"sent": True, "sent_at": "2026-04-29T09:00:00+02:00"})
    out = m.scan_active_shipments()
    a = next(a for a in out["actions"] if a["batch_id"] == "B_FUSED")
    assert a.get("agency_sla", {}).get("started") is True
    audit = json.loads((tmp_path / "outputs" / "B_FUSED" / "audit.json").read_text())
    assert audit["sla"]["active"] is True
    assert audit["sla"]["kind"]   == "agency"


def test_monitor_closes_shipment_when_all_conditions_met(tmp_path, monkeypatch):
    from app.services import active_shipment_monitor as m
    from app.services import ai_bridge as ab
    monkeypatch.setattr(m,  "settings", _settings(tmp_path))
    monkeypatch.setattr(ab, "settings", _settings(tmp_path))
    # Same Step-0 stub — prevents TLS call to Zoho before the closure logic runs.
    monkeypatch.setattr(
        "app.services.email_ingestion_worker.run_ingestion_cycle",
        lambda **kw: {"ok": False, "error": "stubbed", "active_batches": 0, "shipments": []},
    )
    _seed_audit(tmp_path, "B_AUTOCLOSE",
                clearance_status="awaiting_dhl_customs_email",
                clearance_decision={"total_value_usd": 5000,
                                    "clearance_path":  "external_agency_clearance"},
                customs_docs={"received": True},
                polish_desc_filename="x.pdf",
                agency_invoice_received=True,
                dhl_invoice_received=True)
    out = m.scan_active_shipments()
    a = next(a for a in out["actions"] if a["batch_id"] == "B_AUTOCLOSE")
    assert a.get("closure", {}).get("ready") is True
    audit = json.loads((tmp_path / "outputs" / "B_AUTOCLOSE" / "audit.json").read_text())
    assert audit["status"] == "completed"


# ── No financial mutation across the new layer ───────────────────────────────

def test_no_financial_fields_modified_by_lifecycle_layer(tmp_path, monkeypatch):
    from app.services import (
        agency_sad_monitor as asm,
        service_invoice_monitor as sim,
        shipment_folder_manager as fm,
        workdrive_sync as ws,
        shipment_closure as sc,
    )
    s = _settings(tmp_path)
    for mod in (asm, sim, fm, ws, sc):
        monkeypatch.setattr(mod, "settings", s)
    p = _seed_audit(tmp_path, "B_FIN_LC",
                    invoice_totals={"total_cif_usd": 9999.99},
                    clearance_decision={"total_value_usd": 9999.99})
    src = tmp_path / "x.pdf"; src.write_bytes(b"d")
    asm.register_agency_documents("B_FIN_LC", [str(src)])
    sim.register_service_invoices("B_FIN_LC", [str(src)])
    sc.apply_closure(p)
    after = json.loads(p.read_text())
    assert after["invoice_totals"]["total_cif_usd"]       == 9999.99
    assert after["clearance_decision"]["total_value_usd"] == 9999.99


# ── /closure/{batch_id}/check — live route ───────────────────────────────────

def test_check_closure_endpoint_returns_200_and_is_read_only(tmp_path, monkeypatch):
    """
    GET /api/v1/closure/{batch_id}/check must return a structured response with
    ready/checks/current_status/already_completed and must NOT write status=completed.
    """
    import json as _json
    from app.api import routes_lifecycle as rl
    from app.core.security import require_api_key
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    # Seed an audit where all closure checks pass
    p = _seed_audit(
        tmp_path, "B_CHECK_LIVE",
        status="open",
        customs_docs={"received": True},
        pz_generated=True,
        agency_invoice_received=True,
        dhl_invoice_received=True,
    )

    s = _settings(tmp_path)
    monkeypatch.setattr(rl, "settings", s)

    app = FastAPI()
    app.include_router(rl.router)
    app.dependency_overrides[require_api_key] = lambda: None

    client = TestClient(app)
    resp = client.get("/api/v1/closure/B_CHECK_LIVE/check")

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "ready" in data,             "response must include 'ready'"
    assert "checks" in data,            "response must include 'checks'"
    assert "current_status" in data,    "response must include 'current_status'"
    assert "already_completed" in data, "response must include 'already_completed'"
    assert data["batch_id"] == "B_CHECK_LIVE"
    assert data["ready"] is True
    assert data["already_completed"] is False

    # Audit must not be mutated — status stays "open"
    after = _json.loads(p.read_text())
    assert after.get("status") == "open", "check endpoint must not set status=completed"


def test_check_closure_endpoint_returns_404_for_missing_batch(tmp_path, monkeypatch):
    """GET /closure/{batch_id}/check must return 404 when batch audit does not exist."""
    from app.api import routes_lifecycle as rl
    from app.core.security import require_api_key
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    s = _settings(tmp_path)
    monkeypatch.setattr(rl, "settings", s)

    app = FastAPI()
    app.include_router(rl.router)
    app.dependency_overrides[require_api_key] = lambda: None

    client = TestClient(app)
    resp = client.get("/api/v1/closure/B_CHECK_MISSING/check")
    assert resp.status_code == 404


# ── Service invoice monitor — service layer ───────────────────────────────────

def test_service_invoice_all_bad_paths_returns_ok_false(tmp_path, monkeypatch):
    """All-missing paths must return ok=False / no_files_imported; audit flags must not be set."""
    from app.services import service_invoice_monitor as sim
    from app.services import shipment_folder_manager as fm
    from app.services import workdrive_sync as ws
    s = _settings(tmp_path)
    for mod in (sim, fm, ws):
        monkeypatch.setattr(mod, "settings", s)
    _seed_audit(tmp_path, "B_SIM_ALLFAIL")

    out = sim.register_service_invoices("B_SIM_ALLFAIL", ["/no/such/dhl.pdf", "/no/such/agency.pdf"])

    assert out["ok"] is False, "all-bad paths must return ok=False"
    assert out["error"] == "no_files_imported"
    assert out["imported"] == []
    assert len(out["skipped"]) == 2

    # Audit must NOT have invoice flags set
    audit = json.loads((tmp_path / "outputs" / "B_SIM_ALLFAIL" / "audit.json").read_text())
    assert audit.get("dhl_invoice_received")    is not True
    assert audit.get("agency_invoice_received") is not True


def test_service_invoice_valid_dhl_sets_flag(tmp_path, monkeypatch):
    """A valid DHL-named file must set dhl_invoice_received=True in audit."""
    from app.services import service_invoice_monitor as sim
    from app.services import shipment_folder_manager as fm
    from app.services import workdrive_sync as ws
    s = _settings(tmp_path)
    for mod in (sim, fm, ws):
        monkeypatch.setattr(mod, "settings", s)
    _seed_audit(tmp_path, "B_SIM_DHL")
    f = tmp_path / "DHL_Invoice_001.pdf"
    f.write_bytes(b"dhl content")

    out = sim.register_service_invoices("B_SIM_DHL", [str(f)])

    assert out["ok"] is True
    assert out["dhl_invoice_received"] is True
    assert out["agency_invoice_received"] is False
    audit = json.loads((tmp_path / "outputs" / "B_SIM_DHL" / "audit.json").read_text())
    assert audit["dhl_invoice_received"] is True


def test_service_invoice_valid_agency_sets_flag(tmp_path, monkeypatch):
    """A valid Ganther-named file must set agency_invoice_received=True in audit."""
    from app.services import service_invoice_monitor as sim
    from app.services import shipment_folder_manager as fm
    from app.services import workdrive_sync as ws
    s = _settings(tmp_path)
    for mod in (sim, fm, ws):
        monkeypatch.setattr(mod, "settings", s)
    _seed_audit(tmp_path, "B_SIM_AGENCY")
    f = tmp_path / "Ganther_FV2026_002.pdf"
    f.write_bytes(b"agency content")

    out = sim.register_service_invoices("B_SIM_AGENCY", [str(f)])

    assert out["ok"] is True
    assert out["agency_invoice_received"] is True
    assert out["dhl_invoice_received"] is False
    audit = json.loads((tmp_path / "outputs" / "B_SIM_AGENCY" / "audit.json").read_text())
    assert audit["agency_invoice_received"] is True


def test_service_invoice_mixed_valid_bad(tmp_path, monkeypatch):
    """Mixed paths: valid goes to imported, bad goes to skipped; ok=True."""
    from app.services import service_invoice_monitor as sim
    from app.services import shipment_folder_manager as fm
    from app.services import workdrive_sync as ws
    s = _settings(tmp_path)
    for mod in (sim, fm, ws):
        monkeypatch.setattr(mod, "settings", s)
    _seed_audit(tmp_path, "B_SIM_MIX")
    good = tmp_path / "DHL_Invoice_mix.pdf"
    good.write_bytes(b"data")

    out = sim.register_service_invoices("B_SIM_MIX", [str(good), "/no/such/file.pdf"])

    assert out["ok"] is True
    assert len(out["imported"]) == 1
    assert len(out["skipped"])  == 1
    assert out["dhl_invoice_received"] is True


# ── Service invoice upload endpoint ──────────────────────────────────────────

def _make_svc_invoice_upload_client(tmp_path, monkeypatch):
    """TestClient for the lifecycle router with service-invoice modules patched."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api import routes_lifecycle as rl
    from app.core.security import require_api_key
    from app.services import service_invoice_monitor as sim
    from app.services import shipment_folder_manager as fm
    from app.services import workdrive_sync as ws
    s = _settings(tmp_path)
    for mod in (sim, fm, ws):
        monkeypatch.setattr(mod, "settings", s)
    app = FastAPI()
    app.include_router(rl.router)
    app.dependency_overrides[require_api_key] = lambda: None
    return TestClient(app)


def test_upload_service_invoice_accepts_valid_pdf(tmp_path, monkeypatch):
    """Multipart upload with a valid DHL-named PDF must set dhl_invoice_received=True."""
    _seed_audit(tmp_path, "B_SIMUP")
    client = _make_svc_invoice_upload_client(tmp_path, monkeypatch)

    resp = client.post(
        "/api/v1/service-invoices/B_SIMUP/upload",
        files=[("files", ("DHL_Invoice_B_SIMUP.pdf", b"%PDF-1.4 dhl invoice", "application/pdf"))],
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert body["dhl_invoice_received"] is True
    audit = json.loads((tmp_path / "outputs" / "B_SIMUP" / "audit.json").read_text())
    assert audit["dhl_invoice_received"] is True


def test_upload_service_invoice_rejects_invalid_extension(tmp_path, monkeypatch):
    """Upload with an unsupported extension must return 400."""
    _seed_audit(tmp_path, "B_SIMUP_EXT")
    client = _make_svc_invoice_upload_client(tmp_path, monkeypatch)

    resp = client.post(
        "/api/v1/service-invoices/B_SIMUP_EXT/upload",
        files=[("files", ("invoice.exe", b"MZ\x90\x00", "application/octet-stream"))],
    )
    assert resp.status_code == 400, resp.text


def test_upload_service_invoice_rejects_empty_file(tmp_path, monkeypatch):
    """Upload with a zero-byte file must return 400."""
    _seed_audit(tmp_path, "B_SIMUP_EMPTY")
    client = _make_svc_invoice_upload_client(tmp_path, monkeypatch)

    resp = client.post(
        "/api/v1/service-invoices/B_SIMUP_EMPTY/upload",
        files=[("files", ("DHL_Invoice_empty.pdf", b"", "application/pdf"))],
    )
    assert resp.status_code == 400, resp.text


def test_upload_service_invoice_rejects_no_files(tmp_path, monkeypatch):
    """Upload with no files at all must return 422."""
    _seed_audit(tmp_path, "B_SIMUP_NOFILE")
    client = _make_svc_invoice_upload_client(tmp_path, monkeypatch)

    resp = client.post("/api/v1/service-invoices/B_SIMUP_NOFILE/upload")
    assert resp.status_code in (422, 400), resp.text


def test_upload_service_invoice_returns_422_when_all_files_fail(tmp_path, monkeypatch):
    """Upload to an unknown batch (no audit) must return 422 — nothing was imported."""
    # Deliberately do NOT seed an audit for this batch_id
    client = _make_svc_invoice_upload_client(tmp_path, monkeypatch)

    resp = client.post(
        "/api/v1/service-invoices/B_SIMUP_NOFOUND/upload",
        files=[("files", ("DHL_Invoice_fail.pdf", b"%PDF-1.4 data", "application/pdf"))],
    )
    assert resp.status_code == 422, resp.text


# ── Safety: no fake paths in service invoice implementation ──────────────────

def test_no_dev_null_in_service_invoice_monitor():
    """/dev/null must not appear in service_invoice_monitor.py."""
    src = Path(__file__).parent.parent / "app" / "services" / "service_invoice_monitor.py"
    assert "/dev/null" not in src.read_text(encoding="utf-8")


def test_no_fake_path_in_service_invoice_upload_endpoint():
    """The service invoice upload endpoint must not reference fake or placeholder paths."""
    src = Path(__file__).parent.parent / "app" / "api" / "routes_lifecycle.py"
    content = src.read_text(encoding="utf-8")
    idx = content.find("upload_service_invoices_endpoint")
    assert idx != -1, "upload_service_invoices_endpoint not found in routes_lifecycle.py"
    snippet = content[idx: idx + 2500]
    for bad in ("/dev/null", "fake_path", "manual_receipt"):
        assert bad not in snippet, f"Forbidden fake path {bad!r} in service invoice upload endpoint"

# ── POST /closure/{batch_id}/evaluate → 410 Gone ─────────────────────────────

def _make_simple_client():
    """Minimal TestClient for the lifecycle router with auth bypassed."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api import routes_lifecycle as rl
    from app.core.security import require_api_key
    app = FastAPI()
    app.include_router(rl.router)
    app.dependency_overrides[require_api_key] = lambda: None
    return TestClient(app)


def test_closure_evaluate_post_returns_410():
    """POST /api/v1/closure/{id}/evaluate must return 410 Gone (deprecated)."""
    c = _make_simple_client()
    resp = c.post("/api/v1/closure/B_ANY/evaluate")
    assert resp.status_code == 410, (
        f"Expected 410 from deprecated evaluate endpoint, got {resp.status_code}: {resp.text}"
    )


def test_closure_evaluate_post_body_points_to_new_path():
    """410 response body must contain the correct replacement path."""
    c = _make_simple_client()
    resp = c.post("/api/v1/closure/B_ANY/evaluate")
    body = resp.json()
    assert body.get("ok") is False
    assert "/api/v1/execute/closure_confirm" in body.get("message", ""), (
        f"410 message must name the replacement endpoint, got: {body}"
    )


def test_closure_check_get_still_works_after_deprecation(tmp_path, monkeypatch):
    """GET /closure/{batch_id}/check must still return 404 (not 410) for missing batch."""
    c = _make_app(tmp_path, monkeypatch)
    resp = c.get("/api/v1/closure/B_NO_SUCH_BATCH/check")
    assert resp.status_code == 404, (
        f"GET /check must still be live — got {resp.status_code}"
    )
