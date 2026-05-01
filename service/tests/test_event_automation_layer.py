"""
test_event_automation_layer.py — Tests for the event-driven ingestion layer.

Covers:
  - event_trigger_engine.route_email   (agency / customs / invoice / dhl)
  - event_trigger_engine.handle_tracking_event
  - event_trigger_engine idempotency (same message_id replayed)
  - email_ingestion_worker.run_ingestion_cycle  (with stubbed scan + downloader)
  - email_sender read-receipt headers (header-build only; no SMTP)
  - active_shipment_monitor wiring (ingestion runs, ingestion failure non-fatal)
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest


# ── Helpers ──────────────────────────────────────────────────────────────────

def _settings(tmp_path):
    return SimpleNamespace(
        storage_root=tmp_path,
        workdrive_sync_root="",
        zoho_mail_account_id="acct_test",
        zoho_mail_api_base="https://mail.example.test/api",
        email_read_receipt_enabled=False,
        email_read_receipt_to="",
    )


def _seed_audit(tmp_path, batch_id, awb="1234567890", extra=None):
    bdir = tmp_path / "outputs" / batch_id
    bdir.mkdir(parents=True, exist_ok=True)
    obj = {"batch_id": batch_id, "tracking_no": awb, "status": "active"}
    if extra:
        obj.update(extra)
    (bdir / "audit.json").write_text(json.dumps(obj))
    return bdir / "audit.json"


def _patch_settings(monkeypatch, *modules, settings_obj):
    for m in modules:
        monkeypatch.setattr(m, "settings", settings_obj)


# ── event_trigger_engine: routing ────────────────────────────────────────────

def test_route_email_agency_reply_with_customs_pdf(tmp_path, monkeypatch):
    from app.services import event_trigger_engine as ete
    from app.services import agency_sad_monitor as asm
    from app.services import sad_importer as si
    from app.services import service_invoice_monitor as sim
    from app.services import shipment_folder_manager as fm
    from app.services import workdrive_sync as ws
    s = _settings(tmp_path)
    _patch_settings(monkeypatch, asm, si, sim, fm, ws, settings_obj=s)
    audit_path = _seed_audit(tmp_path, "B_AGY")
    pdf = tmp_path / "ZC429_AB.pdf"; pdf.write_bytes(b"PDF")
    rec = {
        "message_id":     "msg-agency-1",
        "from":           "celna@acspedycja.pl",
        "sender_role":    "agency",
        "detected_type":  "agency_reply",
        "subject":        "Re: AWB 1234567890 - dokumenty SAD",
        "received_at":    "2026-04-29T10:00:00Z",
        "attachments":    [{"filename": pdf.name}],
    }
    out = ete.route_email(audit_path, rec, [str(pdf)])
    assert out["ok"]
    actions = {a["action"] for a in out["actions"]}
    assert "register_agency_documents" in actions
    audit = json.loads(audit_path.read_text())
    assert audit["agency_documents_received"] is True
    assert audit["email_ingestion"]["emails_processed"] == 1


def test_route_email_idempotent_on_replay(tmp_path, monkeypatch):
    from app.services import event_trigger_engine as ete
    from app.services import agency_sad_monitor as asm
    from app.services import sad_importer as si
    from app.services import service_invoice_monitor as sim
    from app.services import shipment_folder_manager as fm
    from app.services import workdrive_sync as ws
    s = _settings(tmp_path)
    _patch_settings(monkeypatch, asm, si, sim, fm, ws, settings_obj=s)
    audit_path = _seed_audit(tmp_path, "B_DUP")
    pdf = tmp_path / "ZC429.pdf"; pdf.write_bytes(b"PDF")
    rec = {"message_id": "dup-1", "from": "celna@acspedycja.pl",
           "sender_role": "agency", "detected_type": "agency_reply",
           "subject": "x", "attachments": [{"filename": pdf.name}]}
    o1 = ete.route_email(audit_path, rec, [str(pdf)])
    o2 = ete.route_email(audit_path, rec, [str(pdf)])
    assert o1["ok"] and not o1.get("skipped")
    assert o2["ok"] and o2.get("skipped") == "already_processed"
    audit = json.loads(audit_path.read_text())
    assert audit["email_ingestion"]["emails_processed"] == 1


def test_route_email_dhl_event_flag(tmp_path, monkeypatch):
    from app.services import event_trigger_engine as ete
    from app.services import agency_sad_monitor as asm
    from app.services import sad_importer as si
    from app.services import service_invoice_monitor as sim
    from app.services import shipment_folder_manager as fm
    from app.services import workdrive_sync as ws
    s = _settings(tmp_path)
    _patch_settings(monkeypatch, asm, si, sim, fm, ws, settings_obj=s)
    audit_path = _seed_audit(tmp_path, "B_DHL")
    rec = {"message_id": "dhl-1", "from": "odprawacelna@dhl.com",
           "sender_role": "dhl", "detected_type": "translation",
           "subject": "Tłumaczenie zawartości — przesyłka 1234567890",
           "attachments": []}
    out = ete.route_email(audit_path, rec, [])
    assert any(a["action"] == "flag_dhl_event" for a in out["actions"])
    audit = json.loads(audit_path.read_text())
    assert "translation" in audit["dhl_inbox_flags"]


def test_route_email_service_invoice(tmp_path, monkeypatch):
    from app.services import event_trigger_engine as ete
    from app.services import agency_sad_monitor as asm
    from app.services import sad_importer as si
    from app.services import service_invoice_monitor as sim
    from app.services import shipment_folder_manager as fm
    from app.services import workdrive_sync as ws
    s = _settings(tmp_path)
    _patch_settings(monkeypatch, asm, si, sim, fm, ws, settings_obj=s)
    audit_path = _seed_audit(tmp_path, "B_SI")
    inv = tmp_path / "DHL_Invoice_900.pdf"; inv.write_bytes(b"x")
    rec = {"message_id": "si-1", "from": "billing@dhl.com",
           "sender_role": "dhl", "detected_type": "carrier_status",
           "subject": "Faktura", "attachments": [{"filename": inv.name}]}
    out = ete.route_email(audit_path, rec, [str(inv)])
    actions = {a["action"] for a in out["actions"]}
    assert "register_service_invoices" in actions
    audit = json.loads(audit_path.read_text())
    assert audit["dhl_invoice_received"] is True


def test_handle_tracking_event_immediate_scan(tmp_path):
    from app.services import event_trigger_engine as ete
    audit_path = _seed_audit(tmp_path, "B_TRK")
    out = ete.handle_tracking_event(audit_path,
        {"description": "Customs clearance status updated"})
    assert out["ok"] and out["immediate_scan"] is True
    audit = json.loads(audit_path.read_text())
    assert "ingestion_priority" in audit


def test_handle_tracking_event_unrelated(tmp_path):
    from app.services import event_trigger_engine as ete
    audit_path = _seed_audit(tmp_path, "B_TRK2")
    out = ete.handle_tracking_event(audit_path,
        {"description": "Shipment picked up by courier"})
    assert out["ok"] and out["immediate_scan"] is False


# ── email_ingestion_worker: end-to-end with stubbed scan + downloader ────────

def test_ingestion_worker_routes_through_engine(tmp_path, monkeypatch):
    from app.services import email_ingestion_worker as eiw
    from app.services import event_trigger_engine  as ete
    from app.services import agency_sad_monitor as asm
    from app.services import sad_importer as si
    from app.services import service_invoice_monitor as sim
    from app.services import shipment_folder_manager as fm
    from app.services import workdrive_sync as ws
    s = _settings(tmp_path)
    _patch_settings(monkeypatch, eiw, asm, si, sim, fm, ws, settings_obj=s)
    audit_path = _seed_audit(tmp_path, "B_ING", awb="9876543210")

    pdf = tmp_path / "ZC429_test.pdf"; pdf.write_bytes(b"PDF-DATA")

    fake_email = {
        "message_id":    "msg-ing-1",
        "from":          "celna@ganther.pl",
        "sender_role":   "agency",
        "detected_type": "agency_reply",
        "subject":       "AWB 9876543210 SAD attached",
        "received_at":   "2026-04-29T10:00:00Z",
        "attachments":   [{"attachmentId": "att-1", "filename": pdf.name}],
    }

    def fake_scan(target_awb=None, limit=30, api_base="", token_provider=None, **_kw):
        if target_awb == "9876543210":
            return {"emails": [fake_email]}
        return {"emails": []}

    def fake_download(token, account_id, email_record, batch_id, api_base):
        return [str(pdf)]

    out = eiw.run_ingestion_cycle(
        scan_fn=fake_scan,
        token_provider=lambda: "tok",
        download_fn=fake_download,
    )
    assert out["ok"] and out["active_batches"] == 1
    assert out["shipments"][0]["events"] >= 1

    audit = json.loads(audit_path.read_text())
    assert audit["agency_documents_received"] is True
    assert audit["email_ingestion"]["last_scan_at"]


def test_ingestion_worker_no_credentials(tmp_path, monkeypatch):
    from app.services import email_ingestion_worker as eiw
    s = _settings(tmp_path)
    monkeypatch.setattr(eiw, "settings", s)
    _seed_audit(tmp_path, "B_NOCRED")

    # Fake auth module that says creds missing
    class FakeAuth:
        @staticmethod
        def has_zoho_credentials(): return False
        @staticmethod
        def get_valid_access_token(): raise RuntimeError("no creds")
    import sys
    monkeypatch.setitem(sys.modules, "app.services.zoho_auth", FakeAuth)

    out = eiw.run_ingestion_cycle(scan_fn=lambda **kw: {"emails": []})
    assert out["ok"] is False
    assert out["error"] in ("no_credentials", "auth_unavailable")


def test_ingestion_worker_skips_terminal_audits(tmp_path, monkeypatch):
    from app.services import email_ingestion_worker as eiw
    s = _settings(tmp_path)
    monkeypatch.setattr(eiw, "settings", s)
    _seed_audit(tmp_path, "B_DONE", extra={"status": "completed"})
    _seed_audit(tmp_path, "B_LIVE")

    seen = []
    def fake_scan(target_awb=None, **kw):
        seen.append(target_awb)
        return {"emails": []}
    out = eiw.run_ingestion_cycle(
        scan_fn=fake_scan,
        token_provider=lambda: "tok",
        download_fn=lambda *a, **k: [],
    )
    assert out["active_batches"] == 1


# ── email_sender read-receipt header injection ───────────────────────────────

def test_email_sender_read_receipt_disabled_by_default():
    from app.services import email_sender
    msg = email_sender._build_mime(
        sender="import@estrellajewels.eu",
        to_list=["a@b.com"], cc_list=[], subject="x",
        body_text="hi", body_html="", attachments=[],
    )
    assert "Disposition-Notification-To" not in msg
    assert "Return-Receipt-To"            not in msg


def test_email_sender_read_receipt_enabled(monkeypatch):
    from app.services import email_sender
    fake = SimpleNamespace(
        email_read_receipt_enabled=True,
        email_read_receipt_to="receipts@estrellajewels.eu",
    )
    monkeypatch.setattr(email_sender, "settings", fake)
    msg = email_sender._build_mime(
        sender="import@estrellajewels.eu",
        to_list=["a@b.com"], cc_list=[], subject="x",
        body_text="hi", body_html="", attachments=[],
    )
    assert msg["Disposition-Notification-To"] == "receipts@estrellajewels.eu"
    assert msg["Return-Receipt-To"]           == "receipts@estrellajewels.eu"
    assert msg["X-Confirm-Reading-To"]        == "receipts@estrellajewels.eu"


def test_email_sender_read_receipt_falls_back_to_sender(monkeypatch):
    from app.services import email_sender
    fake = SimpleNamespace(
        email_read_receipt_enabled=True,
        email_read_receipt_to="",
    )
    monkeypatch.setattr(email_sender, "settings", fake)
    msg = email_sender._build_mime(
        sender="import@estrellajewels.eu",
        to_list=["a@b.com"], cc_list=[], subject="x",
        body_text="", body_html="", attachments=[],
    )
    assert msg["Disposition-Notification-To"] == "import@estrellajewels.eu"


# ── monitor wiring: ingestion runs (failure is non-fatal) ────────────────────

def test_monitor_calls_ingestion_and_swallows_errors(tmp_path, monkeypatch):
    from app.services import active_shipment_monitor as asm
    monkeypatch.setattr(asm, "_all_audit_paths", lambda: [])
    # Force the import inside scan_active_shipments to raise
    import sys
    bad = SimpleNamespace(run_ingestion_cycle=lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setitem(sys.modules, "app.services.email_ingestion_worker", bad)
    out = asm.scan_active_shipments()
    assert "ingestion" in out
    assert out["ingestion"]["ok"] is False
    # Sweep itself completed normally
    assert out["scanned"] == 0
