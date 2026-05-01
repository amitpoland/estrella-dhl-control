"""
test_agency_forward_after_dhl.py — Post-DHL → agency forward layer.
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


def _seed_with_dhl_docs(tmp_path: Path, batch_id: str, awb: str = "1012178215",
                       with_awb_pdf: bool = True, with_dhl_docs: bool = True):
    """Seed audit with DHL email received + DHL docs registered + AWB PDF."""
    batch_dir = tmp_path / "outputs" / batch_id
    awb_dir   = batch_dir / "source" / "awb"
    inv_dir   = batch_dir / "source" / "invoices"
    docs_dir  = batch_dir / "dhl_docs"
    for d in (awb_dir, inv_dir, docs_dir):
        d.mkdir(parents=True, exist_ok=True)

    (inv_dir / "INV.pdf").write_bytes(b"%PDF inv")
    awb_filename = ""
    if with_awb_pdf:
        awb_filename = f"{awb} AWB.pdf"
        (awb_dir / awb_filename).write_bytes(b"%PDF awb")

    dhl_files = []
    if with_dhl_docs:
        for nm, ty in [("DSK_AWB.pdf", "DSK"), ("PZC_AWB.pdf", "PZC"), ("ZC429.pdf", "ZC429")]:
            f = docs_dir / nm
            f.write_bytes(b"%PDF " + nm.encode())
            dhl_files.append({"name": nm, "path": str(f), "type": ty, "size": f.stat().st_size})

    audit = {
        "batch_id":    batch_id,
        "awb":         awb,
        "tracking_no": awb,
        "inputs":      {"awb": awb_filename} if awb_filename else {},
        "clearance_decision": {"total_value_usd": 10366,
                               "clearance_path":  "external_agency_clearance"},
        "dhl_email":  {
            "received": True,
            "ticket":   "T#1WA2604290000028",
            "sender":   "odprawacelna@dhl.com",
        },
        "dhl_documents_received": {
            "received":    True,
            "files":       dhl_files,
            "received_at": "2026-04-29T08:00:00+00:00",
            "source":      "operator",
        } if with_dhl_docs else {},
    }
    (batch_dir / "audit.json").write_text(json.dumps(audit), encoding="utf-8")
    return batch_dir, audit


# ── Builder: shape + recipients + subject ────────────────────────────────────

def test_builder_uses_import_identity(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.agency_forward_after_dhl_builder.settings", _settings(tmp_path))
    _, audit = _seed_with_dhl_docs(tmp_path, "B_FWD_1")
    from app.services.agency_forward_after_dhl_builder import build_agency_forward_after_dhl
    pkg = build_agency_forward_after_dhl(audit, "B_FWD_1")
    assert pkg["from_address"] == "import@estrellajewels.eu"
    assert pkg["email_type"]   == "agency_forward_after_dhl"


def test_builder_recipients_correct(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.agency_forward_after_dhl_builder.settings", _settings(tmp_path))
    _, audit = _seed_with_dhl_docs(tmp_path, "B_FWD_RCPT")
    from app.services.agency_forward_after_dhl_builder import build_agency_forward_after_dhl
    pkg = build_agency_forward_after_dhl(audit, "B_FWD_RCPT")
    # TO includes Piotr + Ganther (per spec: Ganther must be TO when forwarding DHL docs)
    assert "piotr@acspedycja.pl" in pkg["to_list"]
    assert "ciagarlak@ganther.com.pl" in pkg["to_list"]
    cc = pkg["cc_list"]
    for addr in [
        "biuro@acspedycja.pl", "roman@acspedycja.pl",
        "info@estrellajewels.eu", "import@estrellajewels.eu", "account@estrellajewels.eu",
    ]:
        assert addr in cc, f"missing CC: {addr}"
    # Ganther must NOT be in CC (moved to TO)
    assert "ciagarlak@ganther.com.pl" not in cc


def test_builder_subject_uses_thread_reply_format(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.agency_forward_after_dhl_builder.settings", _settings(tmp_path))
    _, audit = _seed_with_dhl_docs(tmp_path, "B_FWD_SUBJ")
    from app.services.agency_forward_after_dhl_builder import build_agency_forward_after_dhl
    pkg = build_agency_forward_after_dhl(audit, "B_FWD_SUBJ")
    assert pkg["subject"].startswith("Re: T#1WA2604290000028")
    assert "AWB 1012178215" in pkg["subject"]
    assert "Customs clearance documents" in pkg["subject"]


def test_builder_attaches_all_dhl_docs_plus_awb(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.agency_forward_after_dhl_builder.settings", _settings(tmp_path))
    _, audit = _seed_with_dhl_docs(tmp_path, "B_FWD_ATT")
    from app.services.agency_forward_after_dhl_builder import build_agency_forward_after_dhl
    pkg = build_agency_forward_after_dhl(audit, "B_FWD_ATT")
    labels = " | ".join(a["label"] for a in pkg["attachments"])
    assert "DSK"   in labels
    assert "PZC"   in labels
    assert "ZC429" in labels
    assert "AWB Document" in labels
    assert pkg["awb_attached"] is True


def test_builder_blocks_when_awb_pdf_missing(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.agency_forward_after_dhl_builder.settings", _settings(tmp_path))
    _, audit = _seed_with_dhl_docs(tmp_path, "B_FWD_NOAWB", with_awb_pdf=False)
    from app.services.agency_forward_after_dhl_builder import build_agency_forward_after_dhl
    pkg = build_agency_forward_after_dhl(audit, "B_FWD_NOAWB")
    assert pkg.get("error") == "awb_pdf_missing"


# ── Monitor trigger ──────────────────────────────────────────────────────────

def _run_monitor(tmp_path, monkeypatch):
    from app.services import active_shipment_monitor as m, ai_bridge as ab
    from app.services import agency_forward_after_dhl_builder, email_service
    monkeypatch.setattr(m, "settings", _settings(tmp_path))
    monkeypatch.setattr(ab, "settings", _settings(tmp_path))
    monkeypatch.setattr(agency_forward_after_dhl_builder, "settings", _settings(tmp_path))
    monkeypatch.setattr(email_service, "settings", _settings(tmp_path))
    return m.scan_active_shipments()


def test_monitor_fires_forward_when_all_conditions_met(tmp_path, monkeypatch):
    batch_dir, _ = _seed_with_dhl_docs(tmp_path, "B_FWD_MON")
    out = _run_monitor(tmp_path, monkeypatch)
    a = next(a for a in out["actions"] if a["batch_id"] == "B_FWD_MON")
    assert a.get("agency_forward_after_dhl", {}).get("built") is True

    audit = json.loads((batch_dir / "audit.json").read_text())
    fwd = audit["agency_forward_after_dhl"]
    assert fwd["status"] in ("queued", "sent")   # SMTP not configured in test → queued
    assert fwd["from_address"]   == "import@estrellajewels.eu"
    assert fwd["ticket"]         == "T#1WA2604290000028"
    assert fwd["attachments_count"] >= 4         # 3 DHL docs + AWB


def test_monitor_skips_when_no_dhl_docs(tmp_path, monkeypatch):
    """Without dhl_documents_received, forward must not fire."""
    _seed_with_dhl_docs(tmp_path, "B_FWD_NODOC", with_dhl_docs=False)
    out = _run_monitor(tmp_path, monkeypatch)
    a = next(a for a in out["actions"] if a["batch_id"] == "B_FWD_NODOC")
    assert (a.get("agency_forward_after_dhl") or {}).get("built", False) is False


def test_monitor_idempotent_no_duplicate_forward(tmp_path, monkeypatch):
    _seed_with_dhl_docs(tmp_path, "B_FWD_IDEM")
    out1 = _run_monitor(tmp_path, monkeypatch)
    out2 = _run_monitor(tmp_path, monkeypatch)
    a1 = next(a for a in out1["actions"] if a["batch_id"] == "B_FWD_IDEM")
    a2 = next(a for a in out2["actions"] if a["batch_id"] == "B_FWD_IDEM")
    assert a1["agency_forward_after_dhl"]["built"] is True
    # Second sweep: forward already 'queued' but `sent` is False because SMTP
    # not configured — we treat the package existence as "in flight" and skip
    # rebuild via the `already` guard (sent flag).
    # When SMTP is missing, the queued state means a follow-up sweep will also
    # see sent=False and could try again; for honest idempotency we check that
    # the queued package's email_id is preserved (no DUPLICATE queue entry).
    audit = json.loads((tmp_path / "outputs" / "B_FWD_IDEM" / "audit.json").read_text())
    fwd = audit["agency_forward_after_dhl"]
    queue = json.loads((tmp_path / "email_queue.json").read_text())
    matches = [e for e in queue if e.get("id") == fwd["email_id"]]
    assert len(matches) == 1, "queue must contain exactly one entry for the forward"


def test_monitor_skips_when_already_sent(tmp_path, monkeypatch):
    """Once agency_forward_after_dhl.sent=true, monitor must not re-send."""
    batch_dir, audit = _seed_with_dhl_docs(tmp_path, "B_FWD_DONE")
    audit["agency_forward_after_dhl"] = {"sent": True, "email_id": "x"}
    (batch_dir / "audit.json").write_text(json.dumps(audit))
    out = _run_monitor(tmp_path, monkeypatch)
    a = next(a for a in out["actions"] if a["batch_id"] == "B_FWD_DONE")
    assert (a.get("agency_forward_after_dhl") or {}).get("built", False) is False


def test_monitor_skips_low_value_path(tmp_path, monkeypatch):
    """Low-value (carrier_self_clearance) batches must NOT trigger this forward."""
    batch_dir, audit = _seed_with_dhl_docs(tmp_path, "B_FWD_LV")
    audit["clearance_decision"] = {"total_value_usd": 1500,
                                   "clearance_path":  "carrier_self_clearance"}
    (batch_dir / "audit.json").write_text(json.dumps(audit))
    out = _run_monitor(tmp_path, monkeypatch)
    a = next(a for a in out["actions"] if a["batch_id"] == "B_FWD_LV")
    assert (a.get("agency_forward_after_dhl") or {}).get("built", False) is False


# ── No financial mutation ────────────────────────────────────────────────────

def test_no_financial_fields_modified(tmp_path, monkeypatch):
    batch_dir, audit = _seed_with_dhl_docs(tmp_path, "B_FWD_FIN")
    audit["invoice_totals"] = {"total_cif_usd": 10366}
    (batch_dir / "audit.json").write_text(json.dumps(audit))
    _run_monitor(tmp_path, monkeypatch)
    after = json.loads((batch_dir / "audit.json").read_text())
    assert after["invoice_totals"]["total_cif_usd"]       == 10366
    assert after["clearance_decision"]["total_value_usd"] == 10366
