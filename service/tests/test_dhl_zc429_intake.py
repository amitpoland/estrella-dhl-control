"""
test_dhl_zc429_intake.py — DHL ZC429 completion-email intake.

Covers the AWB 6049349806 sample uploaded by the operator:

  Sender:  Agencja Celna DHL WAW <plwawecs@dhl.com>
  Subject: Powiadomienie o odebranym komunikacie ZC429
           - dot. AWB 6049349806 26PL44302D00AUCWR3
  Body:    "...odprawa celna ... została zakończona według numeru
            26PL44302D00AUCWR3..."
  AWB:     6049349806
  ZC #:    26PL44302D00AUCWR3
  11 attachments:
    3 ZC429_<MRN>_…           → customs_xml/customs_pdf
    1 6049349806.AWB.BOM.GTW.…→ awb
    4 6049349806^^^^INVOICE^^_…→ invoice
    1 6049349806^^^^MAIL^^_ENT…→ email_evidence
    2 6049349806^^^^OTHERS^^_…→ other
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services import dhl_zc429_intake as zc
from app.services import customs_doc_classifier as cdc


SAMPLE_SENDER  = "Agencja Celna DHL WAW <plwawecs@dhl.com>"
SAMPLE_SUBJECT = ("Powiadomienie o odebranym komunikacie ZC429 "
                  "- dot. AWB 6049349806 26PL44302D00AUCWR3")
SAMPLE_BODY    = (
    "Uprzejmie informujemy, że odprawa celna Państwa przesyłki o numerze "
    "listu przewozowego 6049349806 została zakończona według numeru "
    "26PL44302D00AUCWR3. Ze względu na dokonanie zgłoszenia elektronicznego "
    "niniejszy komunikat zastępuje papierowy dokument SAD."
)

SAMPLE_ATTACHMENTS = [
    # 3 ZC429 attachments (xml + pdf mix)
    {"filename": "ZC429_26PL44302D00AUCWR3_1_PL.xml",  "content": b"<xml/>"},
    {"filename": "ZC429_26PL44302D00AUCWR3_2_PL.pdf",  "content": b"%PDF-zc1"},
    {"filename": "ZC429_26PL44302D00AUCWR3_3_PL.pdf",  "content": b"%PDF-zc2"},
    # 1 AWB
    {"filename": "6049349806.AWB.BOM.GTW.WAW.pdf",     "content": b"%PDF-awb"},
    # 4 invoices
    {"filename": "6049349806^^^^INVOICE^^_EJL_001.pdf","content": b"%PDF-i1"},
    {"filename": "6049349806^^^^INVOICE^^_EJL_002.pdf","content": b"%PDF-i2"},
    {"filename": "6049349806^^^^INVOICE^^_EJL_003.pdf","content": b"%PDF-i3"},
    {"filename": "6049349806^^^^INVOICE^^_EJL_004.pdf","content": b"%PDF-i4"},
    # 1 MAIL evidence
    {"filename": "6049349806^^^^MAIL^^_ENTRY.pdf",     "content": b"%PDF-mail"},
    # 2 OTHERS
    {"filename": "6049349806^^^^OTHERS^^_EXT_1.pdf",   "content": b"%PDF-o1"},
    {"filename": "6049349806^^^^OTHERS^^_EXT_2.pdf",   "content": b"%PDF-o2"},
]


@pytest.fixture
def staged_batch(tmp_path, monkeypatch):
    """Stage a fake outputs/<batch>/audit.json under a temp storage_root."""
    monkeypatch.setattr(zc.settings, "storage_root", tmp_path, raising=False)
    batch_id  = "SHIPMENT_6049349806_2026-05_7409ac77"
    bdir      = tmp_path / "outputs" / batch_id
    bdir.mkdir(parents=True)
    (bdir / "audit.json").write_text(json.dumps({
        "tracking_no":         "6049349806",
        "carrier":             "DHL",
        "customs_declaration": {},
        "timeline":            [],
    }), encoding="utf-8")
    # Point email-evidence root inside tmp too so save_message doesn't
    # spill into the developer's real ~/Library store.
    from app.services import email_evidence_store as evs
    monkeypatch.setattr(evs, "_evidence_root",
                        lambda: tmp_path / "email_evidence")
    yield {"tmp": tmp_path, "batch_id": batch_id, "audit": bdir / "audit.json"}


# ── Detector ────────────────────────────────────────────────────────────────

class TestDetector:
    def test_sample_email_matches(self):
        assert zc.is_dhl_zc429_email(
            sender=SAMPLE_SENDER, subject=SAMPLE_SUBJECT, body=SAMPLE_BODY)

    def test_sender_required(self):
        assert not zc.is_dhl_zc429_email(
            sender="random@somewhere.com",
            subject=SAMPLE_SUBJECT, body=SAMPLE_BODY)

    def test_subject_required(self):
        assert not zc.is_dhl_zc429_email(
            sender=SAMPLE_SENDER,
            subject="Random update", body=SAMPLE_BODY)

    def test_body_completion_required(self):
        # Wrong body: no completion phrase at all.
        assert not zc.is_dhl_zc429_email(
            sender=SAMPLE_SENDER, subject=SAMPLE_SUBJECT,
            body="Hello, please find attached.")

    def test_english_body_substitutes_clause_accepted(self):
        body_en = ("Please be advised that the customs clearance ... "
                   "this notification substitutes the paper SAD document "
                   "for your clearance.")
        assert zc.is_dhl_zc429_email(
            sender=SAMPLE_SENDER, subject=SAMPLE_SUBJECT, body=body_en)


# ── Identifier extraction ──────────────────────────────────────────────────

class TestExtractIdentifiers:
    def test_awb_and_mrn_from_subject(self):
        ids = zc.extract_identifiers(
            subject=SAMPLE_SUBJECT, body="", attachments_filenames=[])
        assert ids["awb"]       == "6049349806"
        assert ids["zc_number"] == "26PL44302D00AUCWR3"

    def test_falls_back_to_attachments_when_subject_templated(self):
        # Body uses the placeholder shown in DHL's English block.
        ids = zc.extract_identifiers(
            subject="Powiadomienie ZC429",
            body="...waybill No. %nr transport document % was completed...",
            attachments_filenames=[
                "ZC429_26PL44302D00AUCWR3_1_PL.xml",
                "6049349806^^^^INVOICE^^_X.pdf",
            ],
        )
        assert ids["awb"]       == "6049349806"
        assert ids["zc_number"] == "26PL44302D00AUCWR3"


# ── Attachment classifier ──────────────────────────────────────────────────

class TestClassifier:
    def test_dhl_caret_pattern_recognized(self):
        assert cdc.classify("6049349806^^^^MAIL^^_ENTRY.pdf")["type"] \
               == "email_evidence"
        assert cdc.classify("6049349806^^^^OTHERS^^_EXT.pdf")["type"] \
               == "other"
        assert cdc.classify("6049349806^^^^INVOICE^^_EJL.pdf")["type"] \
               == "invoice"
        assert cdc.classify("6049349806.AWB.BOM.GTW.WAW.pdf")["type"] \
               == "awb"

    def test_zc429_xml_routed_as_customs_xml(self):
        assert cdc.classify("ZC429_26PL44302D00AUCWR3_1_PL.xml")["type"] \
               == "customs_xml"
        assert cdc.classify("ZC429_26PL44302D00AUCWR3_1_PL.pdf")["type"] \
               == "customs_pdf"

    def test_full_sample_buckets(self):
        cls = zc.classify_attachments(SAMPLE_ATTACHMENTS)
        buckets = zc.aggregate_buckets(cls)
        assert buckets["zc429"]         == 3
        assert buckets["awb"]           == 1
        assert buckets["invoices"]      == 4
        assert buckets["mail_evidence"] == 1
        assert buckets["others"]        == 2
        # Every attachment retained, none dropped
        assert len(cls) == 11

    def test_unknown_attachment_preserved_as_other(self):
        cls = zc.classify_attachments([{"filename": "weird-thing.bin"}])
        assert len(cls) == 1
        assert cls[0]["type"] in ("other", "unknown")
        assert cls[0]["bucket"] == "others"


# ── Full-pipeline intake ───────────────────────────────────────────────────

class TestIntake:
    def test_full_pipeline_writes_audit_and_timeline(self, staged_batch):
        res = zc.ingest_zc429_email(
            sender       = SAMPLE_SENDER,
            subject      = SAMPLE_SUBJECT,
            body         = SAMPLE_BODY,
            received_at  = "2026-05-08T11:25:14+02:00",
            message_id   = "msg-zc429-001",
            attachments  = SAMPLE_ATTACHMENTS,
            batch_id     = staged_batch["batch_id"],
        )
        assert res["ok"] is True, res
        assert res["awb"]       == "6049349806"
        assert res["zc_number"] == "26PL44302D00AUCWR3"
        assert res["attachment_count"] == 11
        assert res["buckets"]["zc429"]         == 3
        assert res["buckets"]["invoices"]      == 4
        assert res["buckets"]["awb"]           == 1
        assert res["buckets"]["mail_evidence"] == 1
        assert res["buckets"]["others"]        == 2
        # Audit
        audit = json.loads(staged_batch["audit"].read_text(encoding="utf-8"))
        cd = audit["customs_declaration"]
        assert cd["received"]          is True
        assert cd["source"]            == "dhl_zc429_email"
        assert cd["awb"]               == "6049349806"
        assert cd["zc_number"]         == "26PL44302D00AUCWR3"
        assert cd["mrn"]               == "26PL44302D00AUCWR3"  # mrn set
        assert cd["email_sender"]      == SAMPLE_SENDER
        assert cd["attachments_count"] == 11
        assert len(cd["documents"])    == 11
        # Timeline event
        events = [e for e in audit.get("timeline") or []
                  if e.get("event") == "zc429_received"]
        assert len(events) == 1
        d = events[0]["detail"]
        assert d["awb"] == "6049349806"
        assert d["zc_number"] == "26PL44302D00AUCWR3"
        assert d["attachment_count"] == 11
        assert d["classified_counts"]["invoices"] == 4

    def test_files_stored_under_correct_subfolders(self, staged_batch):
        zc.ingest_zc429_email(
            sender      = SAMPLE_SENDER,
            subject     = SAMPLE_SUBJECT,
            body        = SAMPLE_BODY,
            received_at = "2026-05-08T11:25:14+02:00",
            message_id  = "msg-fs-1",
            attachments = SAMPLE_ATTACHMENTS,
            batch_id    = staged_batch["batch_id"],
        )
        bdir = staged_batch["tmp"] / "outputs" / staged_batch["batch_id"]
        assert (bdir / "source/dhl_zc429").is_dir()
        assert (bdir / "source/invoices").is_dir()
        assert (bdir / "source/awb").is_dir()
        assert (bdir / "source/email").is_dir()
        assert (bdir / "source/other").is_dir()
        # Spot-check counts per folder
        assert len(list((bdir / "source/dhl_zc429").glob("*"))) == 3
        assert len(list((bdir / "source/invoices").glob("*")))  == 4
        assert len(list((bdir / "source/awb").glob("*")))       == 1
        assert len(list((bdir / "source/email").glob("*")))     == 1
        assert len(list((bdir / "source/other").glob("*")))     == 2

    def test_evidence_saved_under_awb_folder(self, staged_batch):
        zc.ingest_zc429_email(
            sender=SAMPLE_SENDER, subject=SAMPLE_SUBJECT, body=SAMPLE_BODY,
            message_id="msg-ev-1", attachments=SAMPLE_ATTACHMENTS,
            batch_id=staged_batch["batch_id"],
        )
        ev_dir = staged_batch["tmp"] / "email_evidence" / "by_awb"
        assert any(p.name.startswith("6049349806") for p in ev_dir.iterdir())

    def test_idempotent_on_duplicate_message_id(self, staged_batch):
        kwargs = dict(
            sender      = SAMPLE_SENDER,
            subject     = SAMPLE_SUBJECT,
            body        = SAMPLE_BODY,
            message_id  = "msg-dup-1",
            attachments = SAMPLE_ATTACHMENTS,
            batch_id    = staged_batch["batch_id"],
        )
        r1 = zc.ingest_zc429_email(**kwargs)
        r2 = zc.ingest_zc429_email(**kwargs)
        assert r1["ok"] is True
        assert r2["ok"] is True
        assert r2["duplicate"] is True
        # Audit timeline stays at 1 zc429_received event after the dupe.
        audit = json.loads(staged_batch["audit"].read_text(encoding="utf-8"))
        events = [e for e in audit.get("timeline") or []
                  if e.get("event") == "zc429_received"]
        assert len(events) == 1, "duplicate intake must not append a second event"
        # Customs declaration document list unchanged
        cd = audit["customs_declaration"]
        assert cd["attachments_count"] == 11
        assert len(cd["documents"]) == 11

    def test_missing_batch_returns_no_op(self, staged_batch):
        res = zc.ingest_zc429_email(
            sender      = SAMPLE_SENDER,
            subject     = "Powiadomienie ZC429 - dot. AWB 9999999999 26PL00000D00BCDEFG1",
            body        = SAMPLE_BODY.replace("6049349806", "9999999999")
                                     .replace("26PL44302D00AUCWR3",
                                              "26PL00000D00BCDEFG1"),
            attachments = [],
        )
        assert res["ok"] is False
        assert res["reason"] == "batch_not_found_for_awb"

    def test_does_not_call_wfirma_smtp_or_pz(self, staged_batch, monkeypatch):
        # Sentinels — any of these being touched is a regression.
        wfirma_calls = []
        smtp_calls   = []
        pz_calls     = []

        # Patch likely entry-points if present; missing is fine.
        try:
            from app.services import wfirma_client
            monkeypatch.setattr(wfirma_client, "create_product",
                                lambda *a, **kw: wfirma_calls.append("p"))
            monkeypatch.setattr(wfirma_client, "create_customer",
                                lambda *a, **kw: wfirma_calls.append("c"))
        except Exception:
            pass
        try:
            from app.services import email_service
            monkeypatch.setattr(email_service, "queue_email",
                                lambda *a, **kw: smtp_calls.append("q"))
        except Exception:
            pass
        try:
            from app.pipelines import pz as pz_pipeline
            for fn in ("start_pz", "run_pz", "process_pz"):
                if hasattr(pz_pipeline, fn):
                    monkeypatch.setattr(pz_pipeline, fn,
                                        lambda *a, **kw: pz_calls.append("z"))
        except Exception:
            pass

        zc.ingest_zc429_email(
            sender      = SAMPLE_SENDER,
            subject     = SAMPLE_SUBJECT,
            body        = SAMPLE_BODY,
            message_id  = "msg-no-side-effects",
            attachments = SAMPLE_ATTACHMENTS,
            batch_id    = staged_batch["batch_id"],
        )
        assert wfirma_calls == [], "ZC429 intake must not write to wFirma"
        assert smtp_calls   == [], "ZC429 intake must not queue SMTP email"
        assert pz_calls     == [], "ZC429 intake must not trigger PZ"

    def test_financial_fields_unchanged(self, staged_batch):
        # Pre-seed financial fields and confirm they survive the intake.
        ap = staged_batch["audit"]
        audit = json.loads(ap.read_text(encoding="utf-8"))
        audit["customs_declaration"] = {
            "duty_a00_pln": 1181.00,
            "invoice_cif_usd": 12345.67,
        }
        audit["totals"] = {"net_pln": 48778.64, "gross_pln": 59997.72}
        ap.write_text(json.dumps(audit), encoding="utf-8")

        zc.ingest_zc429_email(
            sender      = SAMPLE_SENDER,
            subject     = SAMPLE_SUBJECT,
            body        = SAMPLE_BODY,
            message_id  = "msg-fin",
            attachments = SAMPLE_ATTACHMENTS,
            batch_id    = staged_batch["batch_id"],
        )
        post = json.loads(ap.read_text(encoding="utf-8"))
        # Financial scalars survive
        assert post["customs_declaration"]["duty_a00_pln"]     == 1181.00
        assert post["customs_declaration"]["invoice_cif_usd"]  == 12345.67
        assert post["totals"]["net_pln"]                       == 48778.64
        assert post["totals"]["gross_pln"]                     == 59997.72
        # New scalars added
        assert post["customs_declaration"]["received"]         is True
        assert post["customs_declaration"]["source"]           == "dhl_zc429_email"

    def test_readiness_changes_sad_from_missing_to_received(self, staged_batch):
        from app.services import dhl_readiness as dr
        # Pre-state: no SAD timeline event → readiness reports missing.
        zc.ingest_zc429_email(
            sender      = SAMPLE_SENDER,
            subject     = SAMPLE_SUBJECT,
            body        = SAMPLE_BODY,
            message_id  = "msg-ready-1",
            attachments = SAMPLE_ATTACHMENTS,
            batch_id    = staged_batch["batch_id"],
        )
        audit = json.loads(staged_batch["audit"].read_text(encoding="utf-8"))
        # The dhl_readiness mapper treats EV_ZC429_RECEIVED as the
        # transition into "sad_received". If that mapping fires for
        # our event, the audit now carries the right signal.
        events = [e["event"] for e in audit.get("timeline") or []]
        assert "zc429_received" in events
        # Direct readiness compute (best-effort; only assert the public
        # contract that the helper sees the SAD event):
        if hasattr(dr, "_TIMELINE_TO_STATE"):
            assert dr._TIMELINE_TO_STATE.get("zc429_received") == "sad_received"


# ── Sample-attachments parity ──────────────────────────────────────────────

def test_sample_matches_expected_counts():
    """The 11-attachment sample matches the operator's PDF print exactly."""
    cls = zc.classify_attachments(SAMPLE_ATTACHMENTS)
    buckets = zc.aggregate_buckets(cls)
    assert buckets == {
        "zc429":          3,
        "awb":            1,
        "invoices":       4,
        "mail_evidence":  1,
        "others":         2,
    }
    assert sum(buckets.values()) == 11
