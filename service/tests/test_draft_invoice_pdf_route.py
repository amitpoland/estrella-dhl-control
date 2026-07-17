"""
test_draft_invoice_pdf_route.py — GET /api/v1/proforma/draft/{draft_id}/invoice.pdf

Backend for the "View wFirma Invoice" follow-up action that replaces Convert
once a canonical invoice link exists (2026-07-17 projection-convergence repair).

Contract:
  * READ-ONLY. Reuses wfirma_client.fetch_invoice_pdf (GET invoices/download/{id}),
    the same helper the proforma document.pdf route uses. Never writes to wFirma,
    never creates an invoice.
  * Authority = draft.wfirma_invoice_id (the draft-side mirror of the
    proforma_invoice_links row). Empty ⇒ 404, never a guess.
  * Guarded by _auth, NOT _auth_write: viewing an invoice is a read and must stay
    available to read-only roles, exactly like document.pdf (#934 shape).

Pins:
  1. 200 + application/pdf on the happy path.
  2. Filename derives from wfirma_invoice_number, slashes sanitised.
  3. Filename falls back to the invoice id when no number is stored.
  4. Lesson G — no-store cache headers on a live-fetched artifact.
  5. 404 when the draft has no linked invoice (not converted).
  6. 404 when the draft does not exist.
  7. 502 when the wFirma fetch raises.
  8. 502 when wFirma returns an unusably small body (blank-PDF guard).
  9. The route calls fetch_invoice_pdf with the INVOICE id, not the proforma id.
 10. Structural: the route is _auth, not _auth_write.
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.services import wfirma_client as wc
from app.services import proforma_invoice_link_db as pildb

BATCH = "BATCH_INVPDF_TEST"
CLIENT = "ACME"
PROFORMA_ID = "467236963"
INVOICE_ID = "489960355"
INVOICE_NUMBER = "WDT 144/2026"
# The blank-PDF guard rejects < 200 bytes, so a realistic fixture must clear it.
PDF_BYTES = b"%PDF-1.4\n" + b"x" * 400 + b"\n%%EOF"


def _auth():
    return {"X-API-KEY": settings.api_key or "test-key"}


@pytest.fixture()
def storage(tmp_path):
    pildb.init_db(tmp_path / "proforma_links.db")
    return tmp_path


@pytest.fixture()
def client(storage):
    from app.main import app
    with patch.object(settings, "storage_root", storage):
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


def _seed_draft(storage, *, invoice_id="", invoice_number="") -> int:
    """Seed a posted draft, optionally carrying a converted invoice mirror."""
    db = storage / "proforma_links.db"
    pildb.upsert_pending_draft(
        db, batch_id=BATCH, client_name=CLIENT,
        currency="EUR", exchange_rate=None, source_lines_json="[]",
    )
    pildb.mark_draft_issued(db, BATCH, CLIENT, wfirma_proforma_id=PROFORMA_ID)
    d = pildb.get_draft(db, BATCH, CLIENT)
    if invoice_id:
        # Mirror exactly what conversion_persistence.persist_invoice_to_draft writes.
        conn = sqlite3.connect(str(db))
        try:
            conn.execute(
                "UPDATE proforma_drafts SET draft_state='converted', "
                "wfirma_invoice_id=?, wfirma_invoice_number=? WHERE id=?",
                (invoice_id, invoice_number, d.id),
            )
            conn.commit()
        finally:
            conn.close()
    return int(d.id)


def _url(draft_id) -> str:
    return f"/api/v1/proforma/draft/{draft_id}/invoice.pdf"


# ── 1 + 2: happy path ────────────────────────────────────────────────────────

def test_serves_pdf_for_converted_draft(client, storage):
    did = _seed_draft(storage, invoice_id=INVOICE_ID, invoice_number=INVOICE_NUMBER)
    with patch.object(wc, "fetch_invoice_pdf", return_value=PDF_BYTES):
        r = client.get(_url(did), headers=_auth())
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/pdf"
    assert r.content == PDF_BYTES


def test_filename_uses_invoice_number_with_slashes_sanitised(client, storage):
    """wFirma series notation ('WDT 144/2026') is invalid in Content-Disposition."""
    did = _seed_draft(storage, invoice_id=INVOICE_ID, invoice_number=INVOICE_NUMBER)
    with patch.object(wc, "fetch_invoice_pdf", return_value=PDF_BYTES):
        r = client.get(_url(did), headers=_auth())
    cd = r.headers["content-disposition"]
    assert 'filename="WDT 144_2026.pdf"' in cd, cd
    assert "/" not in re.search(r'filename="([^"]+)"', cd).group(1)


# ── 3: filename fallback ─────────────────────────────────────────────────────

def test_filename_falls_back_to_invoice_id(client, storage):
    did = _seed_draft(storage, invoice_id=INVOICE_ID, invoice_number="")
    with patch.object(wc, "fetch_invoice_pdf", return_value=PDF_BYTES):
        r = client.get(_url(did), headers=_auth())
    assert r.status_code == 200
    assert f'filename="invoice-{INVOICE_ID}.pdf"' in r.headers["content-disposition"]


# ── 4: Lesson G ──────────────────────────────────────────────────────────────

def test_no_store_cache_headers(client, storage):
    """Lesson G: a live-fetched artifact must never be cached."""
    did = _seed_draft(storage, invoice_id=INVOICE_ID, invoice_number=INVOICE_NUMBER)
    with patch.object(wc, "fetch_invoice_pdf", return_value=PDF_BYTES):
        r = client.get(_url(did), headers=_auth())
    assert "no-store" in r.headers["cache-control"]
    assert r.headers["pragma"] == "no-cache"
    assert r.headers["expires"] == "0"


# ── 5 + 6: 404 paths ─────────────────────────────────────────────────────────

def test_404_when_draft_has_no_linked_invoice(client, storage):
    """A posted-but-unconverted draft has nothing to show — never guess."""
    did = _seed_draft(storage)  # no invoice mirror
    with patch.object(wc, "fetch_invoice_pdf") as fetch:
        r = client.get(_url(did), headers=_auth())
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "INVOICE_NOT_LINKED"
    fetch.assert_not_called()   # no wFirma call for an unconverted draft


def test_404_when_draft_missing(client, storage):
    with patch.object(wc, "fetch_invoice_pdf") as fetch:
        r = client.get(_url(999999), headers=_auth())
    assert r.status_code == 404
    fetch.assert_not_called()


# ── 7 + 8: 502 paths ─────────────────────────────────────────────────────────

def test_502_when_wfirma_fetch_fails(client, storage):
    did = _seed_draft(storage, invoice_id=INVOICE_ID, invoice_number=INVOICE_NUMBER)
    with patch.object(wc, "fetch_invoice_pdf", side_effect=RuntimeError("boom")):
        r = client.get(_url(did), headers=_auth())
    assert r.status_code == 502
    assert r.json()["detail"]["code"] == "INVOICE_PDF_FETCH_FAILED"


def test_502_when_wfirma_returns_blank_pdf(client, storage):
    """Serving a blank PDF looks like success and prints empty pages — fail loudly."""
    did = _seed_draft(storage, invoice_id=INVOICE_ID, invoice_number=INVOICE_NUMBER)
    with patch.object(wc, "fetch_invoice_pdf", return_value=b"%PDF-1.4\n%%EOF"):
        r = client.get(_url(did), headers=_auth())
    assert r.status_code == 502
    assert r.json()["detail"]["code"] == "INVOICE_PDF_EMPTY"


# ── 9: reads the invoice authority, not the proforma ─────────────────────────

def test_fetches_the_invoice_id_not_the_proforma_id(client, storage):
    """The whole point of the route: it must open the INVOICE, not the proforma."""
    did = _seed_draft(storage, invoice_id=INVOICE_ID, invoice_number=INVOICE_NUMBER)
    with patch.object(wc, "fetch_invoice_pdf", return_value=PDF_BYTES) as fetch:
        client.get(_url(did), headers=_auth())
    fetch.assert_called_once_with(INVOICE_ID)
    assert fetch.call_args[0][0] != PROFORMA_ID


# ── 10: structural auth pin ──────────────────────────────────────────────────

def test_route_is_read_auth_not_privileged():
    """#934 shape: GETs stay readable. Viewing an invoice is a read, so read-only
    roles must not be locked out of it."""
    src = (Path(__file__).resolve().parents[1] / "app" / "api" / "routes_proforma.py"
           ).read_text(encoding="utf-8")
    block = src[src.index('"/draft/{draft_id}/invoice.pdf"'):]
    block = block[:block.index("async def draft_invoice_pdf")]
    # Assert on CODE, not prose — the decorator's own comment explains why this
    # route is deliberately not _auth_write, and would otherwise trip the check.
    code = "\n".join(ln for ln in block.splitlines()
                     if not ln.strip().startswith("#"))
    assert "dependencies=[_auth]" in code, (
        "invoice.pdf must be guarded by _auth."
    )
    assert "_auth_write" not in code, (
        "invoice.pdf is a read — gating it behind _auth_write would deny "
        "viewer/auditor roles the document they are entitled to read."
    )
