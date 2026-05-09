"""
test_polish_desc_validator.py — Mandatory format validation for the Polish
customs description PDF.

Pins the locked baseline (approved AWB 6049349806 line-for-line layout):
  good PDF passes; old synthetic PDF fails; missing invoice numbers fail;
  forbidden wording fails; missing consolidated summary fails; synthetic
  split values fail; CIF mismatch fails; quantity mismatch fails.

Also pins the gate behavior — approve and queue MUST hard-block when
validation fails, with audit and timeline markers persisted.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple
from unittest.mock import patch

import pytest

_ROOT = Path(__file__).parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

os.environ.setdefault("API_KEY", "test-key")


# ── Helpers ─────────────────────────────────────────────────────────────────

def _build_baseline_pdf(out_path: Path,
                       *,
                       use_full_refs: bool = True,
                       include_summary: bool = True,
                       include_grand_cif: bool = True,
                       grand_cif_value: str = "1,784.00",
                       inject_18kt: bool = False,
                       inject_colour_stone: bool = False,
                       inject_kamienie: bool = False,
                       inject_synthetic_split: bool = False,
                       inject_na: bool = False,
                       drop_proba_585: bool = False,
                       drop_srebro_925: bool = False,
                       per_invoice_cif: bool = True) -> Path:
    """Render a minimal PDF that mirrors the approved layout's text content
    so the validator (text-extraction-based) sees the markers it expects."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer

    styles = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=styles["Normal"], fontSize=8, leading=10)

    doc = SimpleDocTemplate(str(out_path), pagesize=A4,
                            leftMargin=18*mm, rightMargin=18*mm,
                            topMargin=16*mm, bottomMargin=16*mm)
    story: List[Any] = [
        Paragraph("ESTRELLA JEWELS Sp. z o.o. Sp. k.", body),
        Paragraph("OPIS TOWARÓW DO ODPRAWY CELNEJ DHL", body),
        Paragraph("AWB / Nr listu: 6049349806   Data / Date: 07.05.2026", body),
        Paragraph("Faktury / Invoices: 4 szt.", body),
        Spacer(1, 4*mm),
    ]
    refs = ["EJL/26-27/121", "EJL/26-27/122", "EJL/26-27/123", "EJL/26-27/124"]
    short_refs = ["121", "122", "123", "124"]
    sec_refs = refs if use_full_refs else short_refs

    # Per-invoice sections — line + per-invoice CIF
    inv_data = [
        ("121", "199.00", [("RING", "71131913", "PCS", "1", "164.00", "164.00")],
         "1 PCS · 0 PRS"),
        ("122", "658.00", [("RING", "71131914", "PCS", "1", "337.00", "337.00"),
                           ("RING", "71131911", "PCS", "1", "286.00", "286.00")],
         "2 PCS · 0 PRS"),
        ("123", "465.00", [("RING", "71131914", "PCS", "1", "176.00", "176.00"),
                           ("PENDANT", "71131911", "PCS", "1", "36.00", "36.00"),
                           ("PENDANT", "71131141", "PCS", "1", "4.00", "4.00"),
                           ("EARRINGS", "71131144", "PRS", "1", "43.00", "43.00"),
                           ("EARRINGS", "71131914", "PRS", "3", "57.00", "171.00")],
         "3 PCS · 4 PRS"),
        ("124", "462.00", [("RING", "71131914", "PCS", "1", "462.00", "462.00")],
         "1 PCS · 0 PRS"),
    ]
    for (short, cif, lines, qty_line), section_ref in zip(inv_data, sec_refs):
        story.append(Paragraph(f"FAKTURA / INVOICE: {section_ref}", body))
        # 14KT / SL925 markers
        if not drop_proba_585:
            story.append(Paragraph("14-karatowe złoto próby 585 z diamentami laboratoryjnymi", body))
        if short == "123" and not drop_srebro_925:
            story.append(Paragraph("Srebro próby 925 z diamentami laboratoryjnymi", body))
        for itype, hsn, uom, qty, rate, amt in lines:
            story.append(Paragraph(
                f"Pierścionek ({itype})  HSN {hsn}  {uom}  Qty {qty}  Rate {rate}  Amount {amt}", body))
        story.append(Paragraph(f"Suma sztuk / Total quantity: {qty_line}", body))
        if per_invoice_cif:
            story.append(Paragraph(f"Razem CIF faktury / Invoice CIF total: USD {cif}", body))
        story.append(Spacer(1, 3*mm))

    if include_summary:
        story.append(Paragraph("PODSUMOWANIE / CONSOLIDATED CUSTOMS SUMMARY", body))
        story.append(Paragraph("Razem ilość / Total quantity: 7 PCS · 4 PRS", body))
        story.append(Paragraph("Razem FOB / Total FOB: USD 1,679.00", body))
        story.append(Paragraph("Fracht / Freight: USD 75.00", body))
        story.append(Paragraph("Ubezpieczenie / Insurance: USD 30.00", body))
    if include_grand_cif:
        story.append(Paragraph(
            f"RAZEM CIF / TOTAL CIF (customs value): USD {grand_cif_value}", body))

    if inject_18kt:
        story.append(Paragraph("Lab Grown Diamond Studded 18KT Gold Jewellery RING", body))
    if inject_colour_stone:
        story.append(Paragraph("Diamond & Colour Stone 18KT Gold Jewellery PENDANT", body))
    if inject_kamienie:
        story.append(Paragraph("kamienie kolorowe (colour stones)", body))
    if inject_synthetic_split:
        story.append(Paragraph("Wartość / Value: USD 152.64", body))
    if inject_na:
        story.append(Paragraph("FAKTURA / INVOICE 1: N/A", body))
        story.append(Paragraph("Faktury / Invoices: 1 szt. (N/A)", body))

    doc.build(story)
    return out_path


def _baseline_audit() -> Dict[str, Any]:
    """Audit shape that matches the AWB 6049349806 baseline."""
    return {
        "awb":         "6049349806",
        "tracking_no": "6049349806",
        "invoice_names": [
            "121 Invoice EJL-26-27-121-04-05-26.pdf",
            "122 Invoice EJL-26-27-122-04-05-26.pdf",
            "123 Invoice EJL-26-27-123-04-05-26.pdf",
            "124 Invoice EJL-26-27-124-04-05-26.pdf",
        ],
        "invoice_totals": {
            "total_pcs":             7,
            "total_prs":             4,
            "total_fob_usd":         1679.0,
            "total_freight_usd":     75.0,
            "total_insurance_usd":   30.0,
            "total_cif_usd":         1784.0,
        },
    }


# ── Validator unit tests ────────────────────────────────────────────────────

class TestValidatorUnit:

    def test_baseline_pdf_passes(self, tmp_path):
        from app.services.polish_desc_validator import validate_polish_customs_description
        pdf = _build_baseline_pdf(tmp_path / "good.pdf")
        r = validate_polish_customs_description(str(pdf), _baseline_audit())
        assert r["valid"], f"baseline must pass; failed: {r['failed_rules']}"
        # Spot-check a representative subset of rules
        for rule in ("R01", "R02", "R04", "R08", "R09", "R10", "R11"):
            assert rule in r["passed_rules"], f"rule {rule} should pass on baseline"

    def test_short_refs_fail_R01(self, tmp_path):
        """Section-only short refs ('121') without full 'EJL/26-27/121' fail R01."""
        from app.services.polish_desc_validator import validate_polish_customs_description
        pdf = _build_baseline_pdf(tmp_path / "short.pdf", use_full_refs=False)
        r = validate_polish_customs_description(str(pdf), _baseline_audit())
        rules = [f["rule"] for f in r["failed_rules"]]
        assert not r["valid"]
        assert "R01" in rules

    def test_18kt_fails_R08(self, tmp_path):
        from app.services.polish_desc_validator import validate_polish_customs_description
        pdf = _build_baseline_pdf(tmp_path / "18kt.pdf", inject_18kt=True)
        r = validate_polish_customs_description(str(pdf), _baseline_audit())
        rules = [f["rule"] for f in r["failed_rules"]]
        assert not r["valid"]
        assert "R08" in rules

    def test_colour_stone_fails_R08(self, tmp_path):
        from app.services.polish_desc_validator import validate_polish_customs_description
        pdf = _build_baseline_pdf(tmp_path / "cs.pdf", inject_colour_stone=True)
        r = validate_polish_customs_description(str(pdf), _baseline_audit())
        rules = [f["rule"] for f in r["failed_rules"]]
        assert not r["valid"]
        assert "R08" in rules

    def test_kamienie_kolorowe_fails_R08(self, tmp_path):
        from app.services.polish_desc_validator import validate_polish_customs_description
        pdf = _build_baseline_pdf(tmp_path / "kk.pdf", inject_kamienie=True)
        r = validate_polish_customs_description(str(pdf), _baseline_audit())
        rules = [f["rule"] for f in r["failed_rules"]]
        assert not r["valid"]
        assert "R08" in rules

    def test_synthetic_split_value_fails_R04_and_R08(self, tmp_path):
        from app.services.polish_desc_validator import validate_polish_customs_description
        pdf = _build_baseline_pdf(tmp_path / "synth.pdf", inject_synthetic_split=True)
        r = validate_polish_customs_description(str(pdf), _baseline_audit())
        rules = [f["rule"] for f in r["failed_rules"]]
        assert not r["valid"]
        assert "R04" in rules
        assert "R08" in rules

    def test_na_invoice_block_fails_R08(self, tmp_path):
        from app.services.polish_desc_validator import validate_polish_customs_description
        pdf = _build_baseline_pdf(tmp_path / "na.pdf", inject_na=True)
        r = validate_polish_customs_description(str(pdf), _baseline_audit())
        rules = [f["rule"] for f in r["failed_rules"]]
        assert not r["valid"]
        assert "R08" in rules

    def test_missing_consolidated_summary_fails_R09(self, tmp_path):
        from app.services.polish_desc_validator import validate_polish_customs_description
        pdf = _build_baseline_pdf(tmp_path / "no_sum.pdf", include_summary=False)
        r = validate_polish_customs_description(str(pdf), _baseline_audit())
        rules = [f["rule"] for f in r["failed_rules"]]
        assert not r["valid"]
        assert "R09" in rules

    def test_grand_cif_mismatch_fails_R10(self, tmp_path):
        from app.services.polish_desc_validator import validate_polish_customs_description
        # PDF says 9,999.00; audit says 1,784.00
        pdf = _build_baseline_pdf(tmp_path / "cif_bad.pdf", grand_cif_value="9,999.00")
        r = validate_polish_customs_description(str(pdf), _baseline_audit())
        rules = [f["rule"] for f in r["failed_rules"]]
        assert not r["valid"]
        assert "R10" in rules

    def test_missing_per_invoice_cif_fails_R11(self, tmp_path):
        from app.services.polish_desc_validator import validate_polish_customs_description
        pdf = _build_baseline_pdf(tmp_path / "no_inv_cif.pdf", per_invoice_cif=False)
        r = validate_polish_customs_description(str(pdf), _baseline_audit())
        rules = [f["rule"] for f in r["failed_rules"]]
        assert not r["valid"]
        assert "R11" in rules

    def test_quantity_mismatch_vs_audit_fails_R12(self, tmp_path):
        """When source invoices not on disk, validator falls back to audit
        invoice_totals. PDF says 7 PCS / 4 PRS but audit claims 99 PCS — fail."""
        from app.services.polish_desc_validator import validate_polish_customs_description
        audit = _baseline_audit()
        audit["invoice_totals"]["total_pcs"] = 99
        pdf = _build_baseline_pdf(tmp_path / "qty.pdf")
        r = validate_polish_customs_description(str(pdf), audit)
        rules = [f["rule"] for f in r["failed_rules"]]
        assert not r["valid"]
        assert "R12" in rules

    def test_drop_proba_585_when_14kt_fails_R06(self, tmp_path):
        from app.services.polish_desc_validator import validate_polish_customs_description
        pdf = _build_baseline_pdf(tmp_path / "no585.pdf", drop_proba_585=True)
        r = validate_polish_customs_description(str(pdf), _baseline_audit())
        # baseline body still references 14KT (RING line uses item_type+rate text);
        # but our minimal PDF builder only emits the explicit "14-karatowe" string.
        # Without drop, R06 passes; with drop, the 14KT token in line text exists
        # only via item type "RING" (no "14KT" substring) — so test specifically
        # verifies that when 14KT IS present and próba 585 is missing, R06 fails.
        # We re-render with explicit 14KT token to make this test deterministic:
        from reportlab.lib.pagesizes import A4
        from reportlab.platypus import SimpleDocTemplate, Paragraph
        from reportlab.lib.styles import getSampleStyleSheet
        styles = getSampleStyleSheet()
        p2 = tmp_path / "no585_with_14kt.pdf"
        d = SimpleDocTemplate(str(p2), pagesize=A4)
        d.build([
            Paragraph("FAKTURA / INVOICE: EJL/26-27/121", styles["Normal"]),
            Paragraph("FAKTURA / INVOICE: EJL/26-27/122", styles["Normal"]),
            Paragraph("FAKTURA / INVOICE: EJL/26-27/123", styles["Normal"]),
            Paragraph("FAKTURA / INVOICE: EJL/26-27/124", styles["Normal"]),
            Paragraph("Some line containing 14KT explicitly", styles["Normal"]),
            Paragraph("PODSUMOWANIE / CONSOLIDATED CUSTOMS SUMMARY", styles["Normal"]),
            Paragraph("Razem CIF faktury / Invoice CIF total: USD 199.00", styles["Normal"]),
            Paragraph("Razem CIF faktury / Invoice CIF total: USD 658.00", styles["Normal"]),
            Paragraph("Razem CIF faktury / Invoice CIF total: USD 465.00", styles["Normal"]),
            Paragraph("Razem CIF faktury / Invoice CIF total: USD 462.00", styles["Normal"]),
            Paragraph("Razem ilość / Total quantity: 7 PCS · 4 PRS", styles["Normal"]),
            Paragraph("RAZEM CIF / TOTAL CIF (customs value): USD 1,784.00", styles["Normal"]),
        ])
        r2 = validate_polish_customs_description(str(p2), _baseline_audit())
        rules = [f["rule"] for f in r2["failed_rules"]]
        assert "R06" in rules

    def test_unreadable_pdf_returns_invalid(self, tmp_path):
        from app.services.polish_desc_validator import validate_polish_customs_description
        bogus = tmp_path / "missing.pdf"
        r = validate_polish_customs_description(str(bogus), _baseline_audit())
        assert r["valid"] is False
        assert any(f["rule"] == "R00" for f in r["failed_rules"])


# ── Gate integration tests (approve / queue hard-blocks) ────────────────────

@pytest.fixture(autouse=True)
def _isolate_storage(tmp_path, monkeypatch):
    """Point storage_root + outputs scope at tmp_path; reset proposal locks."""
    from app.core.config import settings as _s
    monkeypatch.setattr(_s, "storage_root", tmp_path, raising=False)
    monkeypatch.setattr(_s, "smtp_user", "", raising=False)
    monkeypatch.setattr(_s, "smtp_password", "", raising=False)
    monkeypatch.setattr(_s, "dhl_customs_email", "customs@dhl.example", raising=False)
    monkeypatch.setattr(_s, "dhl_customs_cc", "ops@estrellajewels.eu", raising=False)
    monkeypatch.setattr(_s, "api_key", "test-key", raising=False)
    monkeypatch.setattr(_s, "environment", "dev", raising=False)
    from app.api import routes_action_proposals as rap
    from app.services import action_email_builder as aeb
    monkeypatch.setattr(rap, "_OUTPUTS", tmp_path / "outputs")
    monkeypatch.setattr(aeb, "_OUTPUTS", tmp_path / "outputs")
    from app.utils import proposal_lock
    proposal_lock._reset_locks_for_tests()


def _client():
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app, raise_server_exceptions=False)


def _seed_batch_with_polish_desc(tmp_path: Path, *, valid_pdf: bool = True) -> Tuple[str, Path, Path]:
    """Seed a batch with audit + a Polish desc PDF. ``valid_pdf=False`` injects
    a forbidden phrase so the validator hard-fails."""
    bid = "BATCH_VALIDATOR_TEST"
    bdir = tmp_path / "outputs" / bid
    (bdir / "source" / "invoices").mkdir(parents=True, exist_ok=True)
    (bdir / "source" / "awb").mkdir(parents=True, exist_ok=True)
    # Source-invoice files with the same names parsed from invoice_names
    for n in ("121", "122", "123", "124"):
        (bdir / "source" / "invoices" / f"{n} Invoice EJL-26-27-{n}-04-05-26.pdf").write_bytes(b"%PDF inv")
    (bdir / "source" / "awb" / "awb.pdf").write_bytes(b"%PDF awb")

    pdfdir = tmp_path / "polish_descriptions"
    pdfdir.mkdir(parents=True, exist_ok=True)
    pdf_path = pdfdir / "POLISH_DESC_AWB_6049349806_20260507.pdf"
    if valid_pdf:
        _build_baseline_pdf(pdf_path)
    else:
        _build_baseline_pdf(pdf_path, inject_18kt=True)

    audit = _baseline_audit()
    audit["batch_id"] = bid
    audit["clearance_decision"] = {
        "total_value_usd": 1784.0, "threshold_usd": 2500.0,
        "clearance_path":  "dhl_self_clearance", "require_dsk": False,
    }
    audit["customs_package_generated_at"] = "2026-05-07T10:00:00Z"
    audit["polish_desc_filename"] = pdf_path.name
    audit["polish_desc_path"]     = str(pdf_path)
    audit["polish_desc_generated_at"] = "2026-05-07T10:30:00Z"
    audit["timeline"]         = []
    audit["action_proposals"] = []
    audit["inputs"] = {
        "invoices": [f"{n} Invoice EJL-26-27-{n}-04-05-26.pdf" for n in ("121","122","123","124")],
        "awb":      "awb.pdf",
    }
    audit["awb"]      = "6049349806"
    audit["dhl_awb"]  = "6049349806"
    audit["carrier"]  = "DHL"

    ap = bdir / "audit.json"
    ap.write_text(json.dumps(audit, ensure_ascii=False), encoding="utf-8")
    return bid, bdir, ap


def _read_audit(ap: Path) -> Dict[str, Any]: return json.loads(ap.read_text(encoding="utf-8"))


class TestApproveGate:

    def test_approve_blocked_when_validation_fails(self, tmp_path):
        bid, _, ap = _seed_batch_with_polish_desc(tmp_path, valid_pdf=False)
        c = _client()

        # Create a pending proactive-dispatch proposal
        r0 = c.post(f"/api/v1/dhl/proactive-dispatch/{bid}",
                    json={"operator_id": "alice"},
                    headers={"X-API-Key": "test-key"})
        assert r0.status_code == 200, r0.text
        pid = r0.json()["proposal_id"]

        # Approval must hard-block (HTTP 422) with polish_desc_validation_failed
        r1 = c.post(f"/api/v1/action-proposals/{pid}/approve",
                    json={"approved_by": "bob"},
                    headers={"X-API-Key": "test-key"})
        assert r1.status_code == 422, r1.text
        body = r1.json()["detail"]
        assert body["code"] == "polish_desc_validation_failed"
        assert body["stage"] == "approve"
        assert any(f["rule"] == "R08" for f in body["failed_rules"])

        # Proposal status remains pending_review (not approved)
        a = _read_audit(ap)
        prop = a["action_proposals"][0]
        assert prop["status"] == "pending_review"
        assert "polish_desc_validation" in a
        assert a["polish_desc_validation"]["valid"] is False
        events = [e["event"] for e in a["timeline"]]
        assert "polish_desc_validation_failed" in events

    def test_approve_passes_with_valid_pdf(self, tmp_path):
        bid, _, ap = _seed_batch_with_polish_desc(tmp_path, valid_pdf=True)
        c = _client()
        r0 = c.post(f"/api/v1/dhl/proactive-dispatch/{bid}",
                    json={"operator_id": "alice"},
                    headers={"X-API-Key": "test-key"})
        pid = r0.json()["proposal_id"]
        r1 = c.post(f"/api/v1/action-proposals/{pid}/approve",
                    json={"approved_by": "bob"},
                    headers={"X-API-Key": "test-key"})
        assert r1.status_code == 200, r1.text
        a = _read_audit(ap)
        events = [e["event"] for e in a["timeline"]]
        assert "polish_desc_validation_passed" in events
        assert a["polish_desc_validation"]["valid"] is True


class TestQueueGate:

    def test_queue_blocked_when_validation_fails_at_queue_time(self, tmp_path):
        """Setup: PDF starts valid → approval succeeds → PDF goes bad
        before queue → queue must hard-block (the gate re-runs)."""
        bid, bdir, ap = _seed_batch_with_polish_desc(tmp_path, valid_pdf=True)
        c = _client()

        r0 = c.post(f"/api/v1/dhl/proactive-dispatch/{bid}",
                    json={"operator_id": "alice"},
                    headers={"X-API-Key": "test-key"})
        pid = r0.json()["proposal_id"]
        r1 = c.post(f"/api/v1/action-proposals/{pid}/approve",
                    json={"approved_by": "bob"},
                    headers={"X-API-Key": "test-key"})
        assert r1.status_code == 200, r1.text

        # Tamper: replace the PDF with a 18KT-injected one
        a = _read_audit(ap)
        pdf_path = Path(a["polish_desc_path"])
        _build_baseline_pdf(pdf_path, inject_18kt=True)

        with patch("app.services.email_service.queue_email", return_value="qid-X"):
            r2 = c.post(f"/api/v1/action-proposals/{pid}/queue",
                        headers={"X-API-Key": "test-key"})
        assert r2.status_code == 422, r2.text
        body = r2.json()["detail"]
        assert body["code"] == "polish_desc_validation_failed"
        assert body["stage"] == "queue"

        a2 = _read_audit(ap)
        events = [e["event"] for e in a2["timeline"]]
        assert "polish_desc_validation_failed" in events
        # Proposal stays at approved (not queued)
        prop = a2["action_proposals"][0]
        assert prop["status"] == "approved"
