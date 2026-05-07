"""
test_dhl_document_engine.py — Tests for the DHL document auto-forward engine.

Covers:
  1. DHL document classifier (filename + email context)
  2. DHL document validator (AWB, ticket, CIF, invoice overlap)
  3. Event trigger engine integration (classify → validate → register)
  4. Agency forward builder (Ganther TO, not CC)
  5. Idempotency and financial field immutability
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.dhl_document_classifier import (
    classify_dhl_email_documents,
    _classify_single,
    DHL_CESJA_DOC, DSK_DOCUMENT, SAD_DOCUMENT, PZC_DOCUMENT,
    ZC429_DOCUMENT, AWB_DOCUMENT, INVOICE_DOCUMENT, POLISH_DESCRIPTION,
    UNKNOWN,
)
from app.services.dhl_document_validator import validate_dhl_document_set


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


def _seed_audit(tmp_path, batch_id, awb="1012178215", extra=None):
    bdir = tmp_path / "outputs" / batch_id
    bdir.mkdir(parents=True, exist_ok=True)
    obj = {
        "batch_id":       batch_id,
        "tracking_no":    awb,
        "status":         "active",
        "clearance_decision": {
            "total_value_usd": 10366.0,
            "clearance_path":  "agency_clearance",
        },
        "dhl_email": {
            "received":    True,
            "ticket":      "T#1WA2604290000028",
            "received_at": "2026-04-29T02:46:18Z",
        },
        "inputs": {
            "awb":      "AWB_1012178215.pdf",
            "invoices": ["EJL-25-26-098.pdf", "EJL-25-26-099.pdf"],
        },
        "polish_description": {"generated": True},
        # Sentinel financial fields — must not be touched
        "totals":         {"netto": 48778.64, "brutto": 59997.72},
        "invoice_totals": {"net": 48778.64},
        "engine_version": "v1.0.0",
    }
    if extra:
        obj.update(extra)
    (bdir / "audit.json").write_text(json.dumps(obj))
    return bdir / "audit.json"


def _make_attachment(tmp_path, filename, content=b"PDF-DATA"):
    """Create a fake attachment file and return its path."""
    f = tmp_path / filename
    f.write_bytes(content)
    return str(f)


def _email_record(subject="", body_text="", attachments=None, msg_id="dhl-doc-1"):
    return {
        "message_id":    msg_id,
        "from":          "odprawacelna@dhl.com",
        "sender_role":   "dhl",
        "detected_type": "translation",
        "subject":       subject or "Fwd: [T#1WA2604290000028] – AWB 1012178215",
        "body_text":     body_text or "AWB 1012178215 CIF Value: USD 10,366.00",
        "received_at":   "2026-04-29T02:46:18Z",
        "attachments":   attachments or [],
    }


# ══════════════════════════════════════════════════════════════════════════════
# 1. DHL document classifier — filename classification
# ══════════════════════════════════════════════════════════════════════════════

def test_classify_dsk_filename():
    r = _classify_single("DSK_AWB_1012178215.pdf")
    assert r["dhl_type"] == DSK_DOCUMENT
    assert r["confidence"] == "high"


def test_classify_cesja_filename():
    r = _classify_single("cesja_praw_DHL.pdf")
    assert r["dhl_type"] == DHL_CESJA_DOC
    assert r["confidence"] == "high"


def test_classify_pzc_filename():
    r = _classify_single("PZC_1012178215.pdf")
    assert r["dhl_type"] == PZC_DOCUMENT


def test_classify_sad_filename():
    r = _classify_single("SAD_declaration.pdf")
    assert r["dhl_type"] == SAD_DOCUMENT


def test_classify_zc429_filename():
    r = _classify_single("ZC429_import.pdf")
    assert r["dhl_type"] == ZC429_DOCUMENT


def test_classify_awb_filename():
    r = _classify_single("AWB_1012178215.pdf")
    assert r["dhl_type"] == AWB_DOCUMENT


def test_classify_invoice_filename():
    r = _classify_single("EJL-25-26-098_invoice.pdf")
    assert r["dhl_type"] == INVOICE_DOCUMENT


def test_classify_polish_desc_filename():
    r = _classify_single("opis_towaru_1012178215.pdf")
    assert r["dhl_type"] == POLISH_DESCRIPTION


def test_classify_unknown_fallback():
    r = _classify_single("random_document_2026.pdf")
    assert r["dhl_type"] == UNKNOWN


# ══════════════════════════════════════════════════════════════════════════════
# 2. DHL document classifier — full email classification
# ══════════════════════════════════════════════════════════════════════════════

def test_full_email_classification(tmp_path):
    dsk = _make_attachment(tmp_path, "DSK_1012178215.pdf")
    inv = _make_attachment(tmp_path, "EJL-25-26-098.pdf")
    awb = _make_attachment(tmp_path, "AWB_1012178215.pdf")
    desc = _make_attachment(tmp_path, "opis_towaru.pdf")

    audit = {
        "tracking_no": "1012178215",
        "dhl_email": {"ticket": "T#1WA2604290000028"},
        "clearance_decision": {"total_value_usd": 10366.0},
        "inputs": {"awb": "AWB_1012178215.pdf", "invoices": ["EJL-25-26-098.pdf"]},
        "polish_description": {"generated": True},
    }
    email = _email_record(
        subject="Fwd: [T#1WA2604290000028] – AWB 1012178215",
        body_text="AWB 1012178215\nCIF Value: USD 10,366.00\nEJL-25-26-098",
    )
    result = classify_dhl_email_documents(email, [dsk, inv, awb, desc], audit)

    assert result["awb_match"] is True
    assert result["ticket_match"] is True
    assert result["complete_for_agency_forward"] is True
    assert result["confidence"] == "high"
    assert DSK_DOCUMENT in result["document_types"]
    assert len(result["classified_files"]) == 4


# ══════════════════════════════════════════════════════════════════════════════
# 3. DHL document validator
# ══════════════════════════════════════════════════════════════════════════════

def test_validate_awb_match_passes(tmp_path):
    dsk = _make_attachment(tmp_path, "DSK_1012178215.pdf")
    classification = {
        "awb_match": True,
        "ticket_match": True,
        "cif_match": True,
        "invoice_matches": ["EJL-25-26-098"],
        "classified_files": [{"file_path": dsk, "dhl_type": DSK_DOCUMENT}],
        "risk_flags": [],
    }
    audit = {"tracking_no": "1012178215"}
    result = validate_dhl_document_set(classification, audit)
    assert result["valid"] is True
    assert len(result["validated_files"]) == 1
    assert result["errors"] == []


def test_validate_wrong_awb_blocks_forward(tmp_path):
    dsk = _make_attachment(tmp_path, "DSK_9999999999.pdf")
    classification = {
        "awb_match": False,
        "ticket_match": None,
        "cif_match": None,
        "invoice_matches": [],
        "classified_files": [{"file_path": dsk, "dhl_type": DSK_DOCUMENT}],
        "risk_flags": ["awb_not_found_in_email"],
    }
    audit = {"tracking_no": "1012178215"}
    result = validate_dhl_document_set(classification, audit)
    assert result["valid"] is False
    assert "AWB" in result["errors"][0]


def test_validate_cif_mismatch_blocks_forward(tmp_path):
    dsk = _make_attachment(tmp_path, "DSK_1012178215.pdf")
    classification = {
        "awb_match": True,
        "ticket_match": True,
        "cif_match": False,
        "invoice_matches": [],
        "classified_files": [{"file_path": dsk, "dhl_type": DSK_DOCUMENT}],
        "risk_flags": ["cif_mismatch"],
    }
    audit = {"tracking_no": "1012178215"}
    result = validate_dhl_document_set(classification, audit)
    assert result["valid"] is False
    assert any("CIF" in e for e in result["errors"])


# ══════════════════════════════════════════════════════════════════════════════
# 4. Event trigger engine integration
# ══════════════════════════════════════════════════════════════════════════════

def test_dhl_email_triggers_classification_and_registration(tmp_path, monkeypatch):
    from app.services import event_trigger_engine as ete
    from app.services import agency_sad_monitor as asm
    from app.services import sad_importer as si
    from app.services import service_invoice_monitor as sim
    from app.services import shipment_folder_manager as fm
    from app.services import workdrive_sync as ws
    s = _settings(tmp_path)
    for m in (asm, si, sim, fm, ws):
        monkeypatch.setattr(m, "settings", s)

    audit_path = _seed_audit(tmp_path, "B_DHL_DOC")
    dsk = _make_attachment(tmp_path, "DSK_1012178215.pdf")
    inv = _make_attachment(tmp_path, "EJL-25-26-098.pdf")

    email = _email_record(
        subject="Fwd: [T#1WA2604290000028] – AWB 1012178215",
        body_text="AWB 1012178215 CIF Value: USD 10,366.00 EJL-25-26-098",
        attachments=[{"filename": "DSK_1012178215.pdf"}, {"filename": "EJL-25-26-098.pdf"}],
    )
    out = ete.route_email(audit_path, email, [dsk, inv])
    assert out["ok"] is True

    # Check that dhl_docs_classified_and_registered is in actions
    action_names = {a["action"] for a in out["actions"]}
    assert "dhl_docs_classified_and_registered" in action_names

    # Check audit has dhl_documents_received
    audit = json.loads(audit_path.read_text())
    assert audit["dhl_documents_received"]["received"] is True
    assert audit["dhl_documents_received"]["validated"] is True


def test_dhl_validation_failure_creates_risk_flag(tmp_path, monkeypatch):
    from app.services import event_trigger_engine as ete
    from app.services import agency_sad_monitor as asm
    from app.services import sad_importer as si
    from app.services import service_invoice_monitor as sim
    from app.services import shipment_folder_manager as fm
    from app.services import workdrive_sync as ws
    s = _settings(tmp_path)
    for m in (asm, si, sim, fm, ws):
        monkeypatch.setattr(m, "settings", s)

    # Wrong AWB in audit — should fail validation
    audit_path = _seed_audit(tmp_path, "B_DHL_FAIL", awb="9999999999")
    dsk = _make_attachment(tmp_path, "DSK_1012178215.pdf")

    email = _email_record(
        subject="Fwd: [T#1WA2604290000028] – AWB 1012178215",
        body_text="AWB 1012178215",
        attachments=[{"filename": "DSK_1012178215.pdf"}],
    )
    out = ete.route_email(audit_path, email, [dsk])
    action_names = {a["action"] for a in out["actions"]}
    assert "dhl_docs_validation_failed" in action_names

    audit = json.loads(audit_path.read_text())
    assert "dhl_document_validation_failed" in audit.get("risk_flags", [])
    assert audit["dhl_documents_received"]["validated"] is False


def test_duplicate_dhl_email_does_not_resend(tmp_path, monkeypatch):
    from app.services import event_trigger_engine as ete
    from app.services import agency_sad_monitor as asm
    from app.services import sad_importer as si
    from app.services import service_invoice_monitor as sim
    from app.services import shipment_folder_manager as fm
    from app.services import workdrive_sync as ws
    s = _settings(tmp_path)
    for m in (asm, si, sim, fm, ws):
        monkeypatch.setattr(m, "settings", s)

    audit_path = _seed_audit(tmp_path, "B_DHL_IDEM")
    dsk = _make_attachment(tmp_path, "DSK_1012178215.pdf")

    email = _email_record(msg_id="dhl-dup-1")
    o1 = ete.route_email(audit_path, email, [dsk])
    o2 = ete.route_email(audit_path, email, [dsk])

    assert o1["ok"] and not o1.get("skipped")
    assert o2["ok"] and o2.get("skipped") == "already_processed"


# ══════════════════════════════════════════════════════════════════════════════
# 5. Agency forward builder — Ganther TO
# ══════════════════════════════════════════════════════════════════════════════

def test_ganther_is_to_not_cc(tmp_path, monkeypatch):
    from app.services import agency_forward_after_dhl_builder as afb
    monkeypatch.setattr(afb, "settings", _settings(tmp_path))

    # Create AWB file so builder doesn't error
    batch_id = "B_GANTHER"
    awb_dir = tmp_path / "outputs" / batch_id / "source" / "awb"
    awb_dir.mkdir(parents=True)
    (awb_dir / "AWB_1012178215.pdf").write_bytes(b"AWB")

    audit = {
        "tracking_no": "1012178215",
        "dhl_email": {"ticket": "T#1WA2604290000028"},
        "inputs": {"awb": "AWB_1012178215.pdf"},
        "dhl_documents_received": {
            "files": [{"path": str(tmp_path / "DSK.pdf"), "type": "DSK_DOCUMENT"}],
        },
    }
    # Create the DSK file
    (tmp_path / "DSK.pdf").write_bytes(b"DSK-DATA")

    pkg = afb.build_agency_forward_after_dhl(audit, batch_id)
    assert "error" not in pkg

    to_lower = [a.lower() for a in pkg["to_list"]]
    cc_lower = [a.lower() for a in pkg["cc_list"]]
    assert "ciagarlak@ganther.com.pl" in to_lower
    assert "ciagarlak@ganther.com.pl" not in cc_lower


# ══════════════════════════════════════════════════════════════════════════════
# 6. DHL docs stored in 04_dhl_docs folder
# ══════════════════════════════════════════════════════════════════════════════

def test_validated_docs_stored_in_dhl_docs_folder(tmp_path, monkeypatch):
    from app.services import shipment_folder_manager as fm
    monkeypatch.setattr(fm, "settings", _settings(tmp_path))

    batch_id = "B_STORE"
    dsk = _make_attachment(tmp_path, "DSK_1012178215.pdf")
    saved = fm.save_file(batch_id, dsk, "dhl_doc")
    assert "04_dhl_docs" in str(saved)
    assert saved.is_file()


# ══════════════════════════════════════════════════════════════════════════════
# 7. Financial fields immutability
# ══════════════════════════════════════════════════════════════════════════════

def test_no_financial_fields_modified(tmp_path, monkeypatch):
    from app.services import event_trigger_engine as ete
    from app.services import agency_sad_monitor as asm
    from app.services import sad_importer as si
    from app.services import service_invoice_monitor as sim
    from app.services import shipment_folder_manager as fm
    from app.services import workdrive_sync as ws
    s = _settings(tmp_path)
    for m in (asm, si, sim, fm, ws):
        monkeypatch.setattr(m, "settings", s)

    audit_path = _seed_audit(tmp_path, "B_FIN")
    before = json.loads(audit_path.read_text())

    dsk = _make_attachment(tmp_path, "DSK_1012178215.pdf")
    email = _email_record(
        body_text="AWB 1012178215 CIF Value: USD 10,366.00",
    )
    ete.route_email(audit_path, email, [dsk])

    after = json.loads(audit_path.read_text())
    assert after["totals"] == before["totals"]
    assert after["invoice_totals"] == before["invoice_totals"]
    assert after["engine_version"] == before["engine_version"]


# ══════════════════════════════════════════════════════════════════════════════
# 8. AWB 1012178215 live shape regression
# ══════════════════════════════════════════════════════════════════════════════

def test_awb_1012178215_classification(tmp_path):
    """Reproduce the real email shape for AWB 1012178215."""
    dsk  = _make_attachment(tmp_path, "DSK_1012178215.pdf")
    inv1 = _make_attachment(tmp_path, "EJL-25-26-098.pdf")
    inv2 = _make_attachment(tmp_path, "EJL-25-26-099.pdf")
    inv3 = _make_attachment(tmp_path, "EJL-25-26-100.pdf")
    inv4 = _make_attachment(tmp_path, "EJL-25-26-101.pdf")
    inv5 = _make_attachment(tmp_path, "EJL-25-26-102.pdf")
    awb  = _make_attachment(tmp_path, "AWB_1012178215.pdf")
    desc = _make_attachment(tmp_path, "opis_towaru_1012178215.pdf")

    audit = {
        "tracking_no": "1012178215",
        "dhl_email": {"ticket": "T#1WA2604290000028"},
        "clearance_decision": {"total_value_usd": 10366.0},
        "inputs": {
            "awb": "AWB_1012178215.pdf",
            "invoices": [
                "EJL-25-26-098.pdf", "EJL-25-26-099.pdf",
                "EJL-25-26-100.pdf", "EJL-25-26-101.pdf",
                "EJL-25-26-102.pdf",
            ],
        },
        "polish_description": {"generated": True},
    }
    email = _email_record(
        subject="Fwd: [T#1WA2604290000028] – Request for custom clearance – AWB 1012178215",
        body_text=(
            "AWB: 1012178215\n"
            "CIF Value: USD 10,366.00\n"
            "Invoices: EJL-25-26-098 through EJL-25-26-102\n"
            "T#1WA2604290000028\n"
        ),
    )
    attachments = [dsk, inv1, inv2, inv3, inv4, inv5, awb, desc]
    result = classify_dhl_email_documents(email, attachments, audit)

    assert result["awb_match"] is True
    assert result["ticket_match"] is True
    assert result["complete_for_agency_forward"] is True
    assert result["confidence"] == "high"
    assert DSK_DOCUMENT in result["document_types"]
    assert INVOICE_DOCUMENT in result["document_types"]
    assert AWB_DOCUMENT in result["document_types"]
    assert POLISH_DESCRIPTION in result["document_types"]
    assert len(result["invoice_matches"]) >= 1
