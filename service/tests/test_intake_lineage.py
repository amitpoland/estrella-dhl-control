"""
test_intake_lineage.py — Immutable intake-event lineage.

Covers:
  • intake_event_id stable across duplicate ingest of same message_id
  • attachments linked to intake_event_id
  • lineage preserved if classification changes between runs (we still
    do not duplicate the underlying lineage rows, but do record a
    processing note)
  • readiness/timeline payload references intake_event_id
  • duplicate email creates no duplicate attachment rows
  • explainability lookup returns a single envelope answering "which
    DHL email & attachment created this readiness state?"
  • append-only: history grows; events/attachments never updated
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from app.services import dhl_zc429_intake as zc
from app.services import intake_lineage as il


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
    yield {"tmp": tmp_path, "batch_id": batch_id, "audit": bdir / "audit.json"}
    il._db_path = None


# ── Lineage primitives ──────────────────────────────────────────────────────

class TestPrimitives:
    def test_get_or_create_returns_existing_on_second_call(self, staged):
        a, was_a = il.get_or_create_intake_event(
            source_kind="dhl_zc429_email",
            source_message_id="msg-1",
            awb="6049349806",
            zc_number="26PL44302D00AUCWR3",
            batch_id=staged["batch_id"],
        )
        b, was_b = il.get_or_create_intake_event(
            source_kind="dhl_zc429_email",
            source_message_id="msg-1",
            awb="6049349806",
            zc_number="26PL44302D00AUCWR3",
            batch_id=staged["batch_id"],
        )
        assert was_a is False
        assert was_b is True
        assert a["intake_event_id"] == b["intake_event_id"]

    def test_record_attachment_dedupe_on_event_sha_filename(self, staged):
        ev, _ = il.get_or_create_intake_event(
            source_kind="dhl_zc429_email",
            source_message_id="msg-2",
        )
        a1 = il.record_attachment(
            intake_event_id=ev["intake_event_id"],
            original_filename="x.xml",
            sha256="abc",
            classified_type="customs_xml",
        )
        a2 = il.record_attachment(
            intake_event_id=ev["intake_event_id"],
            original_filename="x.xml",
            sha256="abc",
            classified_type="customs_xml",
        )
        assert a1 != ""        # first insert
        assert a2 == ""        # duplicate ignored
        rows = il.list_attachments(ev["intake_event_id"])
        assert len(rows) == 1

    def test_processing_history_is_append_only(self, staged):
        ev, _ = il.get_or_create_intake_event(
            source_kind="dhl_zc429_email",
            source_message_id="msg-3",
        )
        for note in ("first", "second", "third"):
            il.record_processing_note(
                intake_event_id=ev["intake_event_id"], note=note)
        hist = il.list_processing_history(ev["intake_event_id"])
        assert [h["note"] for h in hist] == ["first", "second", "third"]

    def test_no_update_or_delete_method_exposed(self):
        public = {n for n in dir(il) if not n.startswith("_")}
        forbidden = {n for n in public
                     if n.startswith(("update_", "delete_", "drop_", "remove_"))}
        assert forbidden == set(), f"lineage must be append-only; found: {forbidden}"


# ── Full intake integration ─────────────────────────────────────────────────

class TestZC429IntakeLineage:
    def test_intake_creates_event_and_attachments(self, staged):
        res = zc.ingest_zc429_email(
            sender=SAMPLE_SENDER, subject=SAMPLE_SUBJECT, body=SAMPLE_BODY,
            message_id="msg-A", attachments=SAMPLE_ATTACHMENTS,
            batch_id=staged["batch_id"],
        )
        assert res["ok"] is True
        eid = res["intake_event_id"]
        assert eid and len(eid) >= 32

        # Lineage event present
        ev = il.get_intake_event(eid)
        assert ev is not None
        assert ev["source_kind"]       == "dhl_zc429_email"
        assert ev["source_message_id"] == "msg-A"
        assert ev["awb"]               == "6049349806"
        assert ev["zc_number"]         == "26PL44302D00AUCWR3"
        assert ev["batch_id"]          == staged["batch_id"]

        # All 11 attachments persisted with FK
        atts = il.list_attachments(eid)
        assert len(atts) == 11
        assert all(a["intake_event_id"] == eid for a in atts)
        assert all(a["sha256"]    for a in atts)
        assert all(a["stored_path"] for a in atts)

    def test_intake_event_id_stable_on_duplicate(self, staged):
        kw = dict(
            sender=SAMPLE_SENDER, subject=SAMPLE_SUBJECT, body=SAMPLE_BODY,
            message_id="msg-DUP", attachments=SAMPLE_ATTACHMENTS,
            batch_id=staged["batch_id"],
        )
        r1 = zc.ingest_zc429_email(**kw)
        r2 = zc.ingest_zc429_email(**kw)
        assert r1["ok"] and r2["ok"]
        assert r2["duplicate"] is True
        assert r1["intake_event_id"] == r2["intake_event_id"]

        # No duplicate attachment rows
        atts = il.list_attachments(r1["intake_event_id"])
        assert len(atts) == 11

        # Processing history recorded the reprocess attempt
        hist = il.list_processing_history(r1["intake_event_id"])
        notes = [h["note"] for h in hist]
        assert any(n.startswith("processed:") for n in notes)
        assert any(n.startswith("reprocess_skipped:") for n in notes)

    def test_audit_and_timeline_carry_intake_event_id(self, staged):
        res = zc.ingest_zc429_email(
            sender=SAMPLE_SENDER, subject=SAMPLE_SUBJECT, body=SAMPLE_BODY,
            message_id="msg-AUD", attachments=SAMPLE_ATTACHMENTS,
            batch_id=staged["batch_id"],
        )
        eid   = res["intake_event_id"]
        audit = json.loads(staged["audit"].read_text(encoding="utf-8"))
        cd = audit["customs_declaration"]
        assert cd["intake_event_id"]    == eid
        assert cd["processing_version"] == zc.PROCESSING_VERSION
        # Every document carries the back-pointer
        assert all(d["intake_event_id"] == eid for d in cd["documents"])
        assert all(d.get("lineage_id") for d in cd["documents"])

        # Timeline event detail also references it.
        tl_evs = [e for e in audit["timeline"]
                  if e.get("event") == "zc429_received"]
        assert len(tl_evs) == 1
        det = tl_evs[0]["detail"]
        assert det["intake_event_id"] == eid
        assert det["processing_version"] == zc.PROCESSING_VERSION

    def test_duplicate_does_not_duplicate_evidence_rows(self, staged):
        for _ in range(3):
            zc.ingest_zc429_email(
                sender=SAMPLE_SENDER, subject=SAMPLE_SUBJECT, body=SAMPLE_BODY,
                message_id="msg-3X", attachments=SAMPLE_ATTACHMENTS,
                batch_id=staged["batch_id"],
            )
        # Find the only event for this message_id
        ev = il.get_intake_event_by_message_id("dhl_zc429_email", "msg-3X")
        assert ev is not None
        atts = il.list_attachments(ev["intake_event_id"])
        assert len(atts) == 11, "lineage must not duplicate attachment rows"

        # Audit must hold a single zc429_received timeline entry
        audit = json.loads(staged["audit"].read_text(encoding="utf-8"))
        assert sum(1 for e in audit["timeline"]
                   if e.get("event") == "zc429_received") == 1

    def test_lineage_preserved_after_reclassification(self, staged):
        """If we reprocess the same email after the classifier changes,
        attachment rows must still NOT be duplicated. The new
        attempt is tracked through the processing-history table only."""
        zc.ingest_zc429_email(
            sender=SAMPLE_SENDER, subject=SAMPLE_SUBJECT, body=SAMPLE_BODY,
            message_id="msg-RC", attachments=SAMPLE_ATTACHMENTS,
            batch_id=staged["batch_id"],
        )
        ev = il.get_intake_event_by_message_id("dhl_zc429_email", "msg-RC")
        eid = ev["intake_event_id"]
        before = il.list_attachments(eid)

        # Append a manual reclassification note
        il.record_processing_note(
            intake_event_id=eid,
            note="reclassified: invoice → customs_pdf for OTHERS_2",
            actor="amit",
        )
        # Reprocess (simulating operator re-trigger)
        zc.ingest_zc429_email(
            sender=SAMPLE_SENDER, subject=SAMPLE_SUBJECT, body=SAMPLE_BODY,
            message_id="msg-RC", attachments=SAMPLE_ATTACHMENTS,
            batch_id=staged["batch_id"],
        )
        after = il.list_attachments(eid)
        assert len(before) == len(after) == 11
        assert {a["id"] for a in before} == {a["id"] for a in after}

        notes = [h["note"] for h in il.list_processing_history(eid)]
        assert any("reclassified" in n for n in notes)


# ── Explainability ──────────────────────────────────────────────────────────

class TestExplainability:
    def test_lineage_envelope_answers_which_email_caused_state(self, staged):
        res = zc.ingest_zc429_email(
            sender=SAMPLE_SENDER, subject=SAMPLE_SUBJECT, body=SAMPLE_BODY,
            message_id="msg-EXP", attachments=SAMPLE_ATTACHMENTS,
            batch_id=staged["batch_id"],
        )
        eid = res["intake_event_id"]
        env = il.lineage_envelope(eid, audit_path=staged["audit"])

        assert env["intake_event"]["intake_event_id"] == eid
        assert env["intake_event"]["source_message_id"] == "msg-EXP"
        assert env["intake_event"]["awb"] == "6049349806"
        assert env["intake_event"]["zc_number"] == "26PL44302D00AUCWR3"

        assert len(env["attachments"]) == 11
        assert {a["bucket"] for a in env["attachments"]} >= {
            "zc429", "awb", "invoices", "mail_evidence", "others"}

        # Linked timeline event must point back at the same event id.
        assert len(env["linked_timeline_events"]) == 1
        assert env["linked_timeline_events"][0]["detail"]["intake_event_id"] == eid

        # Processing history at least carries the "processed" note.
        assert any(h["note"].startswith("processed:")
                   for h in env["processing_history"])

    def test_list_intake_events_for_batch_returns_only_this_batch(self, staged):
        zc.ingest_zc429_email(
            sender=SAMPLE_SENDER, subject=SAMPLE_SUBJECT, body=SAMPLE_BODY,
            message_id="msg-BATCH-1", attachments=SAMPLE_ATTACHMENTS,
            batch_id=staged["batch_id"],
        )
        # Stage a second batch and ingest a different message into it.
        other_batch = "SHIPMENT_OTHER"
        odir = staged["tmp"] / "outputs" / other_batch
        odir.mkdir(parents=True)
        (odir / "audit.json").write_text(json.dumps({
            "tracking_no": "9999999999", "customs_declaration": {}, "timeline": [],
        }), encoding="utf-8")
        zc.ingest_zc429_email(
            sender=SAMPLE_SENDER,
            subject="Powiadomienie ZC429 - dot. AWB 9999999999 26PL00000D00BCDEFG1",
            body="odprawa celna ... została zakończona według numeru "
                 "26PL00000D00BCDEFG1",
            message_id="msg-BATCH-2", attachments=[],
            batch_id=other_batch,
        )
        events = il.list_intake_events_for_batch(staged["batch_id"])
        assert len(events) == 1
        assert events[0]["batch_id"] == staged["batch_id"]


# ── Append-only at the SQLite level ─────────────────────────────────────────

class TestAppendOnlySQL:
    def test_intake_event_row_count_does_not_shrink(self, staged):
        for i in range(3):
            zc.ingest_zc429_email(
                sender=SAMPLE_SENDER, subject=SAMPLE_SUBJECT, body=SAMPLE_BODY,
                message_id=f"msg-AO-{i}", attachments=[],
                batch_id=staged["batch_id"],
            )
        with sqlite3.connect(str(staged["tmp"] / "intake_lineage.db")) as con:
            n_events = con.execute(
                "SELECT COUNT(*) FROM intake_events").fetchone()[0]
        assert n_events == 3

    def test_unique_constraint_enforced_on_message_id(self, staged):
        il.get_or_create_intake_event(
            source_kind="dhl_zc429_email", source_message_id="msg-UQ")
        with sqlite3.connect(str(staged["tmp"] / "intake_lineage.db")) as con:
            with pytest.raises(sqlite3.IntegrityError):
                con.execute(
                    "INSERT INTO intake_events "
                    "(intake_event_id, source_kind, source_message_id, created_at) "
                    "VALUES (?,?,?,?)",
                    ("dup-uuid", "dhl_zc429_email", "msg-UQ",
                     "2026-05-08T00:00:00Z"),
                )
