"""
test_self_clearance_flow.py — Bifurcated DHL clearance flow.

Verifies:
  - Low-value (carrier_self_clearance) DHL reply attaches all docs (invoices +
    AWB + Polish description), reply-mode in same DHL thread
  - Low-value path does NOT build agency package or DSK transfer reply
  - High-value (external_agency_clearance) builds DSK transfer reply (existing)
  - Sender = import@estrellajewels.eu for both paths
  - AWB-PDF-missing on low-value blocks send
  - No duplicate emails (cooldown + status check)
  - No financial fields modified
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

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


def _seed_low_value_batch(tmp_path: Path, batch_id: str, awb: str = "5555555555",
                           cif: float = 1500.0, with_awb_pdf: bool = True):
    batch_dir  = tmp_path / "outputs" / batch_id
    inv_dir    = batch_dir / "source" / "invoices"
    awb_dir    = batch_dir / "source" / "awb"
    polish_dir = tmp_path / "polish_descriptions"
    for d in (inv_dir, awb_dir, polish_dir):
        d.mkdir(parents=True, exist_ok=True)

    (inv_dir / "INV-LV.pdf").write_bytes(b"%PDF-1.4 invoice low-value")
    awb_filename = ""
    if with_awb_pdf:
        awb_filename = f"{awb} AWB.pdf"
        (awb_dir / awb_filename).write_bytes(b"%PDF-1.4 awb pdf")
    polish_fn = f"POLISH_DESC_AWB_{awb}_20260429.pdf"
    (polish_dir / polish_fn).write_bytes(b"%PDF-1.4 polish desc")

    audit = {
        "batch_id":     batch_id,
        "awb":          awb,
        "tracking_no":  awb,
        "inputs":       {"awb": awb_filename} if awb_filename else {},
        "polish_desc_filename": polish_fn,
        "clearance_status":     "dhl_email_received",
        "clearance_decision":   {"total_value_usd": cif,
                                 "clearance_path":  "carrier_self_clearance"},
        "dhl_email":            {"received": True,
                                 "sender":   "odprawacelna@dhl.com",
                                 "ticket":   "T#LV-1",
                                 "received_at": "2026-04-29T10:00:00Z"},
    }
    (batch_dir / "audit.json").write_text(json.dumps(audit), encoding="utf-8")
    return batch_dir, audit


# ── Builder: low-value package ───────────────────────────────────────────────

def test_low_value_builder_includes_all_docs(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.dhl_self_clearance_builder.settings", _settings(tmp_path))
    _, audit = _seed_low_value_batch(tmp_path, "B_LV1")
    from app.services.dhl_self_clearance_builder import build_dhl_self_clearance_reply
    pkg = build_dhl_self_clearance_reply(audit, "B_LV1")
    labels = [a["label"] for a in pkg["attachments"]]
    assert any("Polish Customs Description" in l for l in labels)
    assert any("Invoice" in l                 for l in labels)
    assert any("AWB Document" in l            for l in labels)
    assert pkg["awb_attached"] is True


def test_low_value_uses_import_identity(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.dhl_self_clearance_builder.settings", _settings(tmp_path))
    _, audit = _seed_low_value_batch(tmp_path, "B_LV2")
    from app.services.dhl_self_clearance_builder import build_dhl_self_clearance_reply
    pkg = build_dhl_self_clearance_reply(audit, "B_LV2")
    assert pkg["from_address"] == "import@estrellajewels.eu"
    assert pkg["email_type"]   == "dhl_self_clearance_reply"


def test_low_value_recipients_dhl_only_no_agency(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.dhl_self_clearance_builder.settings", _settings(tmp_path))
    _, audit = _seed_low_value_batch(tmp_path, "B_LV3")
    from app.services.dhl_self_clearance_builder import build_dhl_self_clearance_reply
    pkg = build_dhl_self_clearance_reply(audit, "B_LV3")
    assert "odprawacelna@dhl.com" in pkg["to_list"]
    # No agency / Ganther recipients on the self-clearance path
    cc_blob = " ".join(pkg["cc_list"]).lower()
    assert "acspedycja"   not in cc_blob
    assert "ganther"      not in cc_blob
    # Only internal CCs allowed
    assert any("estrellajewels" in a for a in pkg["cc_list"])


def test_low_value_subject_uses_thread_reply_format(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.dhl_self_clearance_builder.settings", _settings(tmp_path))
    _, audit = _seed_low_value_batch(tmp_path, "B_LV4")
    from app.services.dhl_self_clearance_builder import build_dhl_self_clearance_reply
    pkg = build_dhl_self_clearance_reply(audit, "B_LV4")
    assert "Re:" in pkg["subject"]
    assert "T#LV-1" in pkg["subject"]
    assert "5555555555" in pkg["subject"]


# ── Monitor branching: low-value triggers self-clearance, NOT agency ─────────

def test_monitor_low_value_path_builds_self_clearance_reply(tmp_path, monkeypatch):
    from app.services import active_shipment_monitor as m
    from app.services import dhl_self_clearance_builder, ai_bridge as ab, email_service
    monkeypatch.setattr(m, "settings", _settings(tmp_path))
    monkeypatch.setattr(ab, "settings", _settings(tmp_path))
    monkeypatch.setattr(dhl_self_clearance_builder, "settings", _settings(tmp_path))
    monkeypatch.setattr(email_service, "settings", _settings(tmp_path))

    batch_dir, _ = _seed_low_value_batch(tmp_path, "B_LV_MON")
    out = m.scan_active_shipments()
    a = next(a for a in out["actions"] if a["batch_id"] == "B_LV_MON")
    assert a.get("dhl_reply", {}).get("built") is True
    assert a["dhl_reply"]["path"] == "carrier_self_clearance"

    audit_after = json.loads((batch_dir / "audit.json").read_text())
    sc_pkg = audit_after.get("dhl_self_clearance_reply_package", {})
    assert sc_pkg.get("status")        == "queued"
    assert sc_pkg.get("from_address")  == "import@estrellajewels.eu"
    assert sc_pkg.get("awb_attached") is True
    # Low-value must NOT have built agency or DSK transfer packages
    assert "agency_reply_package"   not in audit_after or not (audit_after.get("agency_reply_package") or {}).get("status")
    assert "dhl_reply_package"      not in audit_after or not (audit_after.get("dhl_reply_package") or {}).get("status")


def test_monitor_low_value_awb_missing_blocks(tmp_path, monkeypatch):
    """When AWB known but no PDF on disk, block the send with clear error."""
    from app.services import active_shipment_monitor as m
    from app.services import dhl_self_clearance_builder, ai_bridge as ab, email_service
    monkeypatch.setattr(m, "settings", _settings(tmp_path))
    monkeypatch.setattr(ab, "settings", _settings(tmp_path))
    monkeypatch.setattr(dhl_self_clearance_builder, "settings", _settings(tmp_path))
    monkeypatch.setattr(email_service, "settings", _settings(tmp_path))

    batch_dir, _ = _seed_low_value_batch(tmp_path, "B_LV_NOAWB", with_awb_pdf=False)
    out = m.scan_active_shipments()
    a = next(a for a in out["actions"] if a["batch_id"] == "B_LV_NOAWB")
    assert a.get("dhl_reply", {}).get("built") is False
    assert a["dhl_reply"]["error"] == "awb_pdf_missing"


def test_monitor_idempotent_no_duplicate_self_clearance_reply(tmp_path, monkeypatch):
    """Once the package is queued, second sweep does not rebuild."""
    from app.services import active_shipment_monitor as m
    from app.services import dhl_self_clearance_builder, ai_bridge as ab, email_service
    monkeypatch.setattr(m, "settings", _settings(tmp_path))
    monkeypatch.setattr(ab, "settings", _settings(tmp_path))
    monkeypatch.setattr(dhl_self_clearance_builder, "settings", _settings(tmp_path))
    monkeypatch.setattr(email_service, "settings", _settings(tmp_path))

    _seed_low_value_batch(tmp_path, "B_LV_IDEM")
    out1 = m.scan_active_shipments()
    out2 = m.scan_active_shipments()
    a1 = next(a for a in out1["actions"] if a["batch_id"] == "B_LV_IDEM")
    a2 = next(a for a in out2["actions"] if a["batch_id"] == "B_LV_IDEM")
    assert a1["dhl_reply"]["built"] is True
    # Second pass must not rebuild
    assert a2.get("dhl_reply", {}).get("built", False) is False


# ── No financial mutation on low-value path ──────────────────────────────────

def test_low_value_path_does_not_modify_financial_fields(tmp_path, monkeypatch):
    from app.services import active_shipment_monitor as m
    from app.services import dhl_self_clearance_builder, ai_bridge as ab, email_service
    monkeypatch.setattr(m, "settings", _settings(tmp_path))
    monkeypatch.setattr(ab, "settings", _settings(tmp_path))
    monkeypatch.setattr(dhl_self_clearance_builder, "settings", _settings(tmp_path))
    monkeypatch.setattr(email_service, "settings", _settings(tmp_path))

    batch_dir, audit = _seed_low_value_batch(tmp_path, "B_LV_FIN")
    audit["invoice_totals"] = {"total_cif_usd": 1500.0}
    (batch_dir / "audit.json").write_text(json.dumps(audit))
    m.scan_active_shipments()
    after = json.loads((batch_dir / "audit.json").read_text())
    assert after["invoice_totals"]["total_cif_usd"] == 1500.0
    assert after["clearance_decision"]["total_value_usd"] == 1500.0
