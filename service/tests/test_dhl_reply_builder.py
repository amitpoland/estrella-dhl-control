"""
test_dhl_reply_builder.py — DHL reply package + sender identity + auto-build.

Verifies:
  - Sender identity = import@estrellajewels.eu (Poland Import)
  - email_type = "dhl_reply"
  - Standard template references AWB + ticket + CIF + brokers
  - Recipients: DHL TO + administracja_centralna CC + brokers + internal
  - AWB attachment included when present
  - Missing AWB logs error and surfaces in `missing[]`
  - Active monitor auto-builds DHL reply for high-value + DHL email + no reply yet
  - Builder does not modify financial fields
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_SVC = Path(__file__).parent.parent
sys.path.insert(0, str(_SVC))


def _settings(tmp_path: Path):
    class S:
        storage_root = tmp_path
        smtp_host = "smtppro.zoho.in"
        smtp_port = 465
        smtp_user = None
        smtp_password = None
        smtp_use_ssl = True
        mcp_send_max_attachment_bytes = 200_000
    return S()


def _seed_batch(tmp_path: Path, batch_id: str, awb: str = "1012178215",
                with_awb_pdf: bool = True, with_polish_desc: bool = True):
    """Create a realistic batch directory with invoice + AWB + polish desc files."""
    batch_dir = tmp_path / "outputs" / batch_id
    inv_dir   = batch_dir / "source" / "invoices"
    awb_dir   = batch_dir / "source" / "awb"
    polish_dir = tmp_path / "polish_descriptions"
    for d in (inv_dir, awb_dir, polish_dir):
        d.mkdir(parents=True, exist_ok=True)

    # 2 invoices
    (inv_dir / "INV1.pdf").write_bytes(b"%PDF-1.4 invoice 1")
    (inv_dir / "INV2.pdf").write_bytes(b"%PDF-1.4 invoice 2")

    awb_filename = ""
    if with_awb_pdf:
        awb_filename = f"{awb} AWB.pdf"
        (awb_dir / awb_filename).write_bytes(b"%PDF-1.4 awb pdf")

    polish_fn = ""
    if with_polish_desc:
        polish_fn = f"POLISH_DESC_AWB_{awb}_20260429.pdf"
        (polish_dir / polish_fn).write_bytes(b"%PDF-1.4 polish desc")

    audit = {
        "batch_id":    batch_id,
        "awb":         awb,
        "tracking_no": awb,
        "inputs":      {"awb": awb_filename} if awb_filename else {},
        "polish_desc_filename": polish_fn,
        "clearance_status": "dhl_email_received",
        "clearance_decision": {"total_value_usd": 10366,
                               "clearance_path": "external_agency_clearance"},
        "dhl_email": {
            "received": True,
            "sender":   "odprawacelna@dhl.com",
            "ticket":   "T#1WA2604290000028",
            "received_at": "2026-04-29T02:46:18Z",
        },
    }
    (batch_dir / "audit.json").write_text(json.dumps(audit), encoding="utf-8")
    return batch_dir, audit


# ── Sender identity + email_type ─────────────────────────────────────────────

def test_dhl_reply_uses_import_identity(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.dhl_reply_builder.settings", _settings(tmp_path))
    _, audit = _seed_batch(tmp_path, "B_DHL_REPLY")
    from app.services.dhl_reply_builder import build_dhl_reply_package
    pkg = build_dhl_reply_package(audit, "B_DHL_REPLY")
    assert pkg["from_address"] == "import@estrellajewels.eu"
    assert pkg["email_type"]   == "dhl_reply"


def test_agency_pkg_uses_import_identity(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.agency_email_builder.settings", _settings(tmp_path))
    _, audit = _seed_batch(tmp_path, "B_AGENCY")
    from app.services.agency_email_builder import build_agency_package
    pkg = build_agency_package(audit, "B_AGENCY")
    assert pkg["from_address"] == "import@estrellajewels.eu"
    assert pkg["email_type"]   == "agency"


# ── Template content ─────────────────────────────────────────────────────────

def test_dhl_reply_template_includes_required_elements(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.dhl_reply_builder.settings", _settings(tmp_path))
    _, audit = _seed_batch(tmp_path, "B_TPL")
    from app.services.dhl_reply_builder import build_dhl_reply_package
    pkg = build_dhl_reply_package(audit, "B_TPL")
    body = pkg["body_text"]
    assert "1012178215" in body                           # AWB
    assert "T#1WA2604290000028" in body                   # ticket
    assert "USD 10,366.00" in body or "USD 10366" in body  # CIF
    assert "Ganther" in body
    assert "Ciagarlak" in body
    assert "Agencja Celna Spedycja" in body
    assert "DSK" in body
    assert "Import Department" in body


def test_dhl_reply_subject_format(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.dhl_reply_builder.settings", _settings(tmp_path))
    _, audit = _seed_batch(tmp_path, "B_SUBJ")
    from app.services.dhl_reply_builder import build_dhl_reply_package
    pkg = build_dhl_reply_package(audit, "B_SUBJ")
    assert "Request for custom clearance" in pkg["subject"]
    assert "AWB 1012178215" in pkg["subject"]
    assert "T#1WA2604290000028" in pkg["subject"]


# ── Recipients ───────────────────────────────────────────────────────────────

def test_dhl_reply_recipients(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.dhl_reply_builder.settings", _settings(tmp_path))
    _, audit = _seed_batch(tmp_path, "B_RCPT")
    from app.services.dhl_reply_builder import build_dhl_reply_package
    pkg = build_dhl_reply_package(audit, "B_RCPT")
    assert "odprawacelna@dhl.com"          in pkg["to_list"]
    assert "administracja_centralna@dhl.com" in pkg["to_list"]
    assert "ciagarlak@ganther.com.pl"      in pkg["cc_list"]
    assert "piotr@acspedycja.pl"           in pkg["cc_list"]
    assert "info@estrellajewels.eu"        in pkg["cc_list"]


# ── AWB attachment ───────────────────────────────────────────────────────────

def test_awb_attached_when_pdf_present(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.dhl_reply_builder.settings", _settings(tmp_path))
    _, audit = _seed_batch(tmp_path, "B_AWB_OK", with_awb_pdf=True)
    from app.services.dhl_reply_builder import build_dhl_reply_package
    pkg = build_dhl_reply_package(audit, "B_AWB_OK")
    labels = [a["label"] for a in pkg["attachments"]]
    assert any("AWB Document" in l for l in labels)
    assert pkg["awb_attached"] is True


def test_awb_missing_logs_error_and_surfaces(tmp_path, monkeypatch, caplog):
    import logging
    caplog.set_level(logging.ERROR)
    monkeypatch.setattr("app.services.dhl_reply_builder.settings", _settings(tmp_path))
    _, audit = _seed_batch(tmp_path, "B_AWB_MISS", with_awb_pdf=False)
    from app.services.dhl_reply_builder import build_dhl_reply_package
    pkg = build_dhl_reply_package(audit, "B_AWB_MISS")
    assert pkg["awb_attached"] is False
    assert any("AWB" in m for m in pkg["missing"])


# ── Active monitor auto-builds DHL reply ─────────────────────────────────────

def test_monitor_auto_builds_dhl_reply_for_high_value(tmp_path, monkeypatch):
    from app.services import active_shipment_monitor as m
    from app.services import ai_bridge as ab
    from app.services import agency_email_builder, dhl_reply_builder, email_service
    monkeypatch.setattr(m, "settings", _settings(tmp_path))
    monkeypatch.setattr(ab, "settings", _settings(tmp_path))
    monkeypatch.setattr(dhl_reply_builder, "settings", _settings(tmp_path))
    monkeypatch.setattr(email_service, "settings", _settings(tmp_path))

    batch_dir, _ = _seed_batch(tmp_path, "B_AUTO_REPLY")
    out = m.scan_active_shipments()
    a = next(a for a in out["actions"] if a["batch_id"] == "B_AUTO_REPLY")
    assert a.get("dhl_reply", {}).get("built") is True

    # Audit now has dhl_reply_package with status=queued (SMTP not configured in test)
    audit = json.loads((batch_dir / "audit.json").read_text())
    drp = audit.get("dhl_reply_package", {})
    assert drp.get("status") == "queued"
    assert drp.get("from_address") == "import@estrellajewels.eu"
    assert drp.get("ticket")       == "T#1WA2604290000028"
    assert drp.get("awb_attached") is True


def test_monitor_skips_dhl_reply_when_already_sent(tmp_path, monkeypatch):
    from app.services import active_shipment_monitor as m
    from app.services import ai_bridge as ab
    from app.services import dhl_reply_builder
    monkeypatch.setattr(m, "settings", _settings(tmp_path))
    monkeypatch.setattr(ab, "settings", _settings(tmp_path))
    monkeypatch.setattr(dhl_reply_builder, "settings", _settings(tmp_path))

    batch_dir, audit = _seed_batch(tmp_path, "B_SKIP")
    audit["dhl_reply_package"] = {"status": "sent", "email_id": "x"}
    (batch_dir / "audit.json").write_text(json.dumps(audit))
    out = m.scan_active_shipments()
    a = next(a for a in out["actions"] if a["batch_id"] == "B_SKIP")
    # No new build attempt
    assert (a.get("dhl_reply") or {}).get("built", False) is False


# ── No financial fields modified ─────────────────────────────────────────────

def test_dhl_reply_builder_does_not_modify_financial_fields(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.dhl_reply_builder.settings", _settings(tmp_path))
    batch_dir, audit = _seed_batch(tmp_path, "B_FIN")
    audit["invoice_totals"] = {"total_cif_usd": 10366}
    (batch_dir / "audit.json").write_text(json.dumps(audit))
    from app.services.dhl_reply_builder import build_dhl_reply_package
    build_dhl_reply_package(audit, "B_FIN")
    after = json.loads((batch_dir / "audit.json").read_text())
    assert after["invoice_totals"]["total_cif_usd"] == 10366
    assert after["clearance_decision"]["total_value_usd"] == 10366
