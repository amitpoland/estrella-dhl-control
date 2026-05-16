"""Phase 6F.5 — Live dual-write and 6F.2.a backfill must coexist.

Three sha1 namespaces:
- 6F.2.a backfill: ``BACKFILL-<sha1>`` postings + ``[backfill:sha1=...]`` notes
- 6F.5 dual-write: ``LIVE-<sha1>`` postings + ``[live:sha1=...]`` notes
- Real wFirma path (future): numeric wfirma_invoice_id, no prefix

These namespaces are sha1-disjoint AND prefix-disjoint. They cannot collide.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from app.services import finance_dual_write as fdw
from app.services import finance_postings_db as fpdb


def _insert_backfill_posting_and_charge(db: Path, batch: str, client: str):
    """Simulate what the 6F.2.a backfill script would write."""
    import hashlib
    fpdb.init_db(db)
    bf_post_hash = hashlib.sha1(f"legacy_psc_posting:{batch}:{client}".encode()).hexdigest()[:16]
    bf_id = f"BACKFILL-{bf_post_hash}"
    posting = fpdb.create_posting(db, {
        "batch_id":           batch,
        "client_name":        client,
        "wfirma_invoice_id":  bf_id,
        "wfirma_doc_number":  "",
        "posting_kind":       "proforma",
        "posted_at":          "2026-01-01T00:00:00Z",
        "issued_total_minor": 1234,
        "currency":           "EUR",
    })
    bf_charge_hash = hashlib.sha1(
        f"legacy_psc:{batch}:{client}:freight".encode()
    ).hexdigest()
    fpdb.create_charge(db, {
        "batch_id":     batch,
        "client_name":  client,
        "charge_type":  "freight",
        "amount_minor": 1234,
        "currency":     "EUR",
        "source":       "legacy_backfill",
        "posting_id":   posting.id,
        "notes":        f"[backfill:sha1={bf_charge_hash}]\nlegacy note",
    })


def test_backfill_and_live_postings_coexist(tmp_path: Path):
    db = tmp_path / "finance_postings.sqlite"
    batch = "B/2026/COEXIST"
    client = "Coexist Ltd"
    _insert_backfill_posting_and_charge(db, batch, client)

    res = fdw.dual_write_proforma_post(
        db_path=db, batch_id=batch, client_name=client,
        currency="EUR", full_number="FV/1/2026",
        service_charges_json='[{"charge_type":"freight","amount":12.34,"currency":"EUR"}]',
        enabled=True, shadow=False,
    )
    assert res["ok"] is True

    postings = fpdb.list_postings(db, batch_id=batch)
    assert len(postings) == 2, "Expected one BACKFILL- and one LIVE- posting"
    prefixes = sorted(p.wfirma_invoice_id.split("-", 1)[0] + "-" for p in postings)
    assert prefixes == ["BACKFILL-", "LIVE-"]


def test_backfill_and_live_charges_coexist(tmp_path: Path):
    db = tmp_path / "finance_postings.sqlite"
    batch = "B/2026/COEXIST"
    client = "Coexist Ltd"
    _insert_backfill_posting_and_charge(db, batch, client)
    fdw.dual_write_proforma_post(
        db_path=db, batch_id=batch, client_name=client,
        currency="EUR", full_number="FV/1/2026",
        service_charges_json='[{"charge_type":"freight","amount":12.34,"currency":"EUR"}]',
        enabled=True, shadow=False,
    )
    charges = fpdb.list_charges(db, batch_id=batch)
    sources = sorted({c.source for c in charges})
    assert sources == ["legacy_backfill", "operator"], (
        f"Expected one legacy_backfill + one operator charge, got sources={sources}"
    )
    notes_prefixes = sorted(set(
        c.notes.split("]")[0] + "]" for c in charges if c.notes
    ))
    assert any(n.startswith("[backfill:sha1=") for n in notes_prefixes)
    assert any(n.startswith("[live:sha1=") for n in notes_prefixes)


def test_sha1_namespaces_disjoint():
    """The sha1 input strings differ — they cannot collide as hex output."""
    import hashlib
    batch = "B"
    client = "C"
    backfill_posting = hashlib.sha1(f"legacy_psc_posting:{batch}:{client}".encode()).hexdigest()
    live_posting = hashlib.sha1(f"live_psc_posting:{batch}:{client}".encode()).hexdigest()
    backfill_charge = hashlib.sha1(f"legacy_psc:{batch}:{client}:freight".encode()).hexdigest()
    live_charge = hashlib.sha1(f"live_psc:{batch}:{client}:freight".encode()).hexdigest()
    assert backfill_posting != live_posting
    assert backfill_charge != live_charge


def test_prefix_disjoint():
    assert fdw.POSTING_LIVE_PREFIX == "LIVE-"
    assert fdw.CHARGES_LIVE_NOTE_PREFIX == "[live:sha1="
    # Backfill uses BACKFILL- and [backfill:sha1= — different first characters.
    assert not fdw.POSTING_LIVE_PREFIX.startswith("BACKFILL")
    assert not fdw.CHARGES_LIVE_NOTE_PREFIX.startswith("[backfill")
