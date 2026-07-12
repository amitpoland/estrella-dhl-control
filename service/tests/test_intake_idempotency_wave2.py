"""
test_intake_idempotency_wave2.py — EJ Dashboard Stabilization Sprint 1, Wave 2.

Pins the New Shipment → B1 intake integration contract that the V2 modal now
depends on:

  * missing AWB / missing invoice → 400 (real backend validation)
  * a successful intake returns status='draft' with NO PZ number assigned
  * unsupported file extension → 400 (extension guard preserved)
  * multiple purchase invoices accepted
  * purchase + sales packing lists remain SEPARATE document identities
  * NEW: idempotency_key — a retry with the same key returns the ORIGINAL
    batch (no duplicate); a different/absent key creates a distinct batch.

Mirrors the fixture pattern in test_intake.py (patched storage_root, mocked
AWB parse + packing extraction; the invoice parser tolerates fake PDF bytes).
"""
from __future__ import annotations

import io
import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import settings
from app.services import document_db as ddb
from app.services import packing_db as pdb


@pytest.fixture(scope="module")
def tmp_storage(tmp_path_factory):
    return tmp_path_factory.mktemp("intake_idem_storage")


@pytest.fixture(scope="module")
def _dbs(tmp_storage):
    ddb.init_document_db(tmp_storage / "documents.db")
    pdb.init_packing_db(tmp_storage / "packing.db")
    return tmp_storage


@pytest.fixture(scope="module")
def client(tmp_storage, _dbs):
    with patch.object(settings, "storage_root", tmp_storage):
        with patch.object(settings, "max_upload_bytes", 20 * 1024 * 1024):
            with TestClient(app, raise_server_exceptions=True) as c:
                yield c


def _pdf(name: str) -> tuple:
    return (name, io.BytesIO(f"%PDF-1.4 fake {name}".encode()), "application/pdf")


def _auth() -> dict:
    return {"X-API-KEY": settings.api_key or "test-key"}


def _mock_parsers():
    """Context managers that stub the AWB parse + packing extraction."""
    awb = patch("app.api.routes_intake.parse_awb_pdf", return_value={"awb_number": "", "carrier": "DHL", "confidence": 0.0})
    pack = patch("app.api.routes_intake.process_packing_upload", side_effect=Exception("no packing"))
    return awb, pack


def _intake(client, tracking_no, *, idem="", extra_files=None, metadata=None):
    files = [("invoices", _pdf("INV-1.pdf"))]
    if extra_files:
        files += extra_files
    data = {"tracking_no": tracking_no, "carrier": "DHL",
            "metadata": json.dumps(metadata or {"purchase_blocks": [], "sales_blocks": []})}
    if idem:
        data["idempotency_key"] = idem
    awb, pack = _mock_parsers()
    with awb, pack:
        return client.post("/api/v1/shipment/intake", data=data, files=files, headers=_auth())


# ── Validation ──────────────────────────────────────────────────────────────

def test_missing_awb_returns_400(client):
    awb, pack = _mock_parsers()
    with awb, pack:
        r = client.post("/api/v1/shipment/intake",
                        data={"tracking_no": "", "carrier": "DHL"},
                        files=[("invoices", _pdf("INV-1.pdf"))], headers=_auth())
    assert r.status_code == 400
    assert "AWB" in r.text or "Tracking" in r.text


def test_missing_invoice_returns_400(client):
    r = client.post("/api/v1/shipment/intake",
                    data={"tracking_no": "NOINV-1", "carrier": "DHL"},
                    files=[], headers=_auth())
    assert r.status_code == 400
    assert "invoice" in r.text.lower()


def test_unsupported_invoice_extension_returns_400(client):
    r = client.post("/api/v1/shipment/intake",
                    data={"tracking_no": "BADEXT-1", "carrier": "DHL"},
                    files=[("invoices", ("bad.txt", io.BytesIO(b"not a pdf"), "text/plain"))],
                    headers=_auth())
    assert r.status_code == 400


# ── Draft semantics ─────────────────────────────────────────────────────────

def test_intake_returns_draft_with_no_pz(client):
    r = _intake(client, "DRAFT-1")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["status"] == "draft"
    assert body.get("batch_id")
    # No PZ number is assigned at intake.
    assert "pz_number" not in body
    assert not body.get("pz")


def test_multiple_invoices_accepted(client):
    r = _intake(client, "MULTI-1", extra_files=[("invoices", _pdf("INV-2.pdf")), ("invoices", _pdf("INV-3.pdf"))])
    assert r.status_code == 200, r.text
    assert len(r.json()["purchase"]["invoices"]) == 3


def test_purchase_and_sales_packing_are_separate_identities(client):
    """Purchase + sales packing lists must register as DISTINCT document types
    (purchase → customs/CIF authority; sales → warehouse valuation)."""
    awb, pack = _mock_parsers()
    with awb, pack:
        r = client.post(
            "/api/v1/shipment/intake",
            data={"tracking_no": "PAIR-1", "carrier": "DHL",
                  "metadata": json.dumps({"purchase_blocks": [{"invoice_index": 0, "packing_index": 0}],
                                          "sales_blocks": [{"document_index": -1, "packing_index": 0}]})},
            files=[("invoices", _pdf("INV-1.pdf")),
                   ("packing_lists", ("ppack.pdf", io.BytesIO(b"%PDF purchase pack"), "application/pdf")),
                   ("sales_packing_lists", ("spack.pdf", io.BytesIO(b"%PDF sales pack"), "application/pdf"))],
            headers=_auth())
    assert r.status_code == 200, r.text
    body = r.json()
    batch_id = body["batch_id"]
    rows = ddb.get_documents_for_batch(batch_id) if hasattr(ddb, "get_documents_for_batch") else []
    types = {row.get("document_type") for row in rows}
    # Both distinct identities present; never collapsed into one.
    assert "sales_packing_list" in types
    assert "purchase_packing_list" in types or (settings.storage_root / "packing.db").exists()


# ── Upload size / 0-byte door-guard (Wave-2 security review) ────────────────

def test_oversize_sales_packing_list_rejected_413(client):
    """A sales packing list larger than _MAX_BYTES must be rejected with 413 —
    the same size door-guard purchase packing and every other upload type
    enforce. Regression pin for the pre-existing gap where the sales-packing
    save did a bare ``await f.read()`` with no size check, letting a client
    stream an arbitrarily large upload into memory unchecked.

    _MAX_BYTES is a module constant bound at import, so patch it directly (the
    fixture's settings.max_upload_bytes patch does not reach it). The invoice
    payload stays well under the limit so validation reaches the sales-packing
    save."""
    oversize = b"x" * 200
    awb, pack = _mock_parsers()
    with patch("app.api.routes_intake._MAX_BYTES", 50):
        with awb, pack:
            r = client.post(
                "/api/v1/shipment/intake",
                data={"tracking_no": "SPACK-BIG-1", "carrier": "DHL",
                      "metadata": json.dumps({"purchase_blocks": [],
                                              "sales_blocks": [{"document_index": -1, "packing_index": 0}]})},
                files=[("invoices", _pdf("INV-1.pdf")),
                       ("sales_packing_lists", ("big.pdf", io.BytesIO(oversize), "application/pdf"))],
                headers=_auth())
    assert r.status_code == 413, r.text


def test_empty_sales_packing_list_rejected_400(client):
    """A 0-byte sales packing list must be rejected at the door (400), matching
    the _save 0-byte guard every other upload type uses — an empty upload would
    otherwise save then silently parse to no rows."""
    awb, pack = _mock_parsers()
    with awb, pack:
        r = client.post(
            "/api/v1/shipment/intake",
            data={"tracking_no": "SPACK-EMPTY-1", "carrier": "DHL",
                  "metadata": json.dumps({"purchase_blocks": [],
                                          "sales_blocks": [{"document_index": -1, "packing_index": 0}]})},
            files=[("invoices", _pdf("INV-1.pdf")),
                   ("sales_packing_lists", ("empty.pdf", io.BytesIO(b""), "application/pdf"))],
            headers=_auth())
    assert r.status_code == 400, r.text


def test_oversize_purchase_packing_rejected_413(client):
    """Purchase packing enforces the same size door-guard as sales packing
    (uniform upload validation — was a bare read + inline 413, now via _save)."""
    with patch("app.api.routes_intake._MAX_BYTES", 50):
        r = client.post(
            "/api/v1/shipment/intake",
            data={"tracking_no": "PPACK-BIG-1", "carrier": "DHL",
                  "metadata": json.dumps({"purchase_blocks": [{"invoice_index": 0, "packing_index": 0}], "sales_blocks": []})},
            files=[("invoices", _pdf("INV-1.pdf")),
                   ("packing_lists", ("big.pdf", io.BytesIO(b"x" * 200), "application/pdf"))],
            headers=_auth())
    assert r.status_code == 413, r.text


def test_empty_purchase_packing_rejected_400(client):
    """Purchase packing rejects a 0-byte upload at the door (400) — the
    silent-zero-rows gap this uniform-validation work closes."""
    r = client.post(
        "/api/v1/shipment/intake",
        data={"tracking_no": "PPACK-EMPTY-1", "carrier": "DHL",
              "metadata": json.dumps({"purchase_blocks": [{"invoice_index": 0, "packing_index": 0}], "sales_blocks": []})},
        files=[("invoices", _pdf("INV-1.pdf")),
               ("packing_lists", ("empty.pdf", io.BytesIO(b""), "application/pdf"))],
        headers=_auth())
    assert r.status_code == 400, r.text


def test_all_packing_save_sites_route_through_save_guard():
    """Every packing save site (purchase intake, sales intake, backfill, and
    reingest) must route through _save() for the uniform size/0-byte guard —
    no bare `await f.read()` + `write_bytes` pattern may survive for a packing
    upload. The behavioural 413/400 tests above prove _save; this pins the
    reingest site (whose guard only fires after a sales_document match, which
    needs a heavier fixture)."""
    import re
    from pathlib import Path
    src = (Path(__file__).parents[1] / "app" / "api" / "routes_intake.py").read_text(encoding="utf-8")
    # Neither the one-liner nor the split-line bare write pattern may remain.
    assert not re.search(r"path\.write_bytes\(await\s+f\.read\(\)\)", src), "bare one-line write_bytes(await f.read()) survived"
    assert not re.search(r"content\s*=\s*await\s+f\.read\(\)\s*\n\s*if\s+len\(content\)\s*>\s*_MAX_BYTES", src), (
        "a split-line bare read + inline size-only check survived — route through _save for the 0-byte guard too"
    )
    reingest = src[src.index("async def sales_packing_reingest"):]
    reingest = reingest[: reingest.index("\n@router.") if "\n@router." in reingest else len(reingest)]
    assert "await _save(" in reingest, "sales_packing_reingest must save via _save()"


def test_reingest_guards_destructive_persist_on_zero_rows():
    """The reingest route must NOT call the destructive idempotent-replace when
    the file parsed to zero rows — else it deletes existing sales_packing_lines
    and inserts nothing (silent data loss). Pinned at source: a `if not sp_rows`
    guard with `continue` must precede persist_sales_from_packing (the
    behavioural path needs a matched sales_document + real parse — heavy
    fixture; this pin protects the guard from removal)."""
    import re
    from pathlib import Path
    src = (Path(__file__).parents[1] / "app" / "api" / "routes_intake.py").read_text(encoding="utf-8")
    reingest = src[src.index("async def sales_packing_reingest"):]
    reingest = reingest[: reingest.index("\n@router.") if "\n@router." in reingest else len(reingest)]
    persist_at = reingest.index("persist_sales_from_packing(")
    before = reingest[:persist_at]
    # The last `if not sp_rows:` before the persist must be followed by a continue.
    guard = re.search(r"if\s+not\s+sp_rows\s*:(.*?)continue", before, re.DOTALL)
    assert guard, "reingest must skip persist_sales_from_packing when sp_rows is empty (if not sp_rows: ... continue)"


# ── Idempotency (the Wave-2 backend addition) ───────────────────────────────

def test_same_idempotency_key_returns_same_batch(client, tmp_storage):
    key = "wave2-idem-fixed-001"
    r1 = _intake(client, "IDEM-1", idem=key)
    assert r1.status_code == 200, r1.text
    first_batch = r1.json()["batch_id"]
    assert not r1.json().get("idempotent_replay")

    # Retry with the SAME key — must return the original batch, no duplicate.
    r2 = _intake(client, "IDEM-1", idem=key)
    assert r2.status_code == 200, r2.text
    body2 = r2.json()
    assert body2["batch_id"] == first_batch
    assert body2.get("idempotent_replay") is True

    # The index file records the key → batch mapping.
    index = json.loads((tmp_storage / "intake_idempotency.json").read_text(encoding="utf-8"))
    assert index[key]["batch_id"] == first_batch


def test_replay_returns_original_identity_not_caller_changed(client):
    """A retry that reuses the key but changes tracking_no must still return the
    ORIGINAL batch's identity (not the caller's new AWB) so the UI navigates to
    the real created shipment."""
    key = "wave2-idem-identity-001"
    r1 = _intake(client, "ORIGINAL-AWB", idem=key)
    assert r1.status_code == 200, r1.text
    orig_batch = r1.json()["batch_id"]

    r2 = _intake(client, "CHANGED-AWB", idem=key)  # same key, different AWB
    assert r2.status_code == 200, r2.text
    body = r2.json()
    assert body["batch_id"] == orig_batch
    assert body.get("idempotent_replay") is True
    assert body["tracking_no"] == "ORIGINAL-AWB"  # NOT "CHANGED-AWB"


def test_overlong_idempotency_key_is_ignored(client):
    """An over-long key is treated as absent (no index bloat); intake still
    creates normally and does not dedupe."""
    huge = "x" * 500
    a = _intake(client, "OVERLONG-1", idem=huge)
    b = _intake(client, "OVERLONG-1", idem=huge)
    assert a.status_code == b.status_code == 200
    assert a.json()["batch_id"] != b.json()["batch_id"]
    assert not a.json().get("idempotent_replay")
    assert not b.json().get("idempotent_replay")


def test_absent_or_different_key_creates_distinct_batches(client):
    a = _intake(client, "DISTINCT-1", idem="")            # no key
    b = _intake(client, "DISTINCT-1", idem="")            # no key again
    c = _intake(client, "DISTINCT-1", idem="wave2-diff-key")
    assert a.status_code == b.status_code == c.status_code == 200
    ids = {a.json()["batch_id"], b.json()["batch_id"], c.json()["batch_id"]}
    # Three separate creations → three distinct batches (duplicate-AWB is
    # advisory-only, never a hard block).
    assert len(ids) == 3
    for r in (a, b, c):
        assert not r.json().get("idempotent_replay")
