"""test_supplier_invoice_ocr.py — Supplier invoice OCR review drafts.

Single extraction authority (2026-07-03): the expense-draft upload consumes
``vision_extractor.extract_invoice_lineitems_via_vision`` — the SAME extractor
the shipment-intake path uses (the DHL commercial invoice and the supplier's
purchase invoice are the same physical document; operator-confirmed). The
former second extractor (supplier_invoice_ocr_service.py) is deleted.

Route surface (/api/v1/supplier-invoice-ocr):
  * upload happy path (PDF + PNG) → 201, pending_review row persisted
  * gateway unavailable → 503, row persisted with extraction_method='failed'
  * extraction failed (other) → 422, row persisted pending_review (manual keying)
  * feature flag off → 503 BEFORE any extraction or file write
  * bad extension / wrong magic bytes / empty → 400; oversize → 413
  * drafts list + status filter; detail with parsed JSON columns
  * confirm → 200 with SERVER-SIDE operator identity; second confirm → 409;
    unauthenticated confirm → 401/403; machine_original preserved
  * reject → 200; source-file served with Cache-Control: no-store (Lesson G)

Shared-extractor layer (vision_extractor):
  * validate_invoice_extraction: NEW optional fields (supplier_address,
    supplier_gstin, invoice_date, unit, subtotal, tax_details, needs_review)
    validate correctly AND stay absent when the model omits them (no
    fabricated defaults — production blast-radius pin)
  * extract_invoice_lineitems_via_vision: PNG/JPEG input path (expense
    uploads), fence stripping, primary→secondary escalation, gateway
    unavailable; PDF input still goes through rasterize_pdf unchanged

Auth for confirm/reject is supplied by overriding get_current_user —
require_role's inner dependency (same pattern as
test_vision_invoice_confirm_route.py). No test writes outside tmp_path.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_BASE = "/api/v1/supplier-invoice-ocr"

_USER = {
    "id": 7,
    "full_name": "Test Operator",
    "email": "operator@example.com",
    "role": "accounts",
    "is_active": 1,
    "is_approved": 1,
}

# Validated-clean shape as produced by validate_invoice_extraction — the
# shared schema's names (supplier / invoice_no / hsn / unit_price_usd /
# total_usd), NOT renames of them.
_FIXTURE_FIELDS = {
    "supplier": "ABC Exports Pvt Ltd",
    "supplier_address": "Mumbai, India",
    "supplier_gstin": "27AABCS1234F1ZA",
    "invoice_no": "INV-2026-001",
    "invoice_date": "2026-01-15",
    "currency": "INR",
    "line_items": [
        {"description": "Gold Ring 22K", "hsn": "711319", "quantity": 5.0,
         "unit": "pcs", "unit_price_usd": 15000.0, "total_usd": 75000.0},
    ],
    "itemization_unavailable": False,
    "subtotal": 75000.0,
    "tax_details": [
        {"tax_type": "CGST", "rate": 1.5, "amount": 1125.0},
        {"tax_type": "SGST", "rate": 1.5, "amount": 1125.0},
    ],
    "total_amount": 77250.0,
    "needs_review": [],
    "confidence": 0.92,
}

# Model-side raw response (pre-validation names: unit_price / total).
_FIXTURE_MODEL_JSON = {
    "supplier": "ABC Exports Pvt Ltd",
    "supplier_address": "Mumbai, India",
    "supplier_gstin": "27AABCS1234F1ZA",
    "invoice_no": "INV-2026-001",
    "invoice_date": "2026-01-15",
    "currency": "INR",
    "itemization_available": True,
    "line_items": [
        {"description": "Gold Ring 22K", "hsn": "711319", "quantity": 5,
         "unit": "pcs", "unit_price": 15000.0, "total": 75000.0},
    ],
    "subtotal": 75000.0,
    "tax_details": [
        {"tax_type": "CGST", "rate": 1.5, "amount": 1125.0},
        {"tax_type": "SGST", "rate": 1.5, "amount": 1125.0},
    ],
    "total_amount": 77250.0,
    "needs_review": [],
    "confidence": 0.92,
    "source_page": 1,
    "source_reason": "DESCRIPTION / QTY / AMOUNT table",
}

_PDF_BYTES = b"%PDF-1.4\n%test supplier invoice\n%%EOF\n"
_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def _ok_prov(fields=None, **over):
    f = dict(_FIXTURE_FIELDS)
    if fields:
        f.update(fields)
    prov = {
        "ok": True,
        "extraction_method": "vision_llm",
        "model_attempt": "primary",
        "extraction_confidence": f.get("confidence", 0.0),
        "fields": f,
        "source_file": "x.pdf",
        "source_page": 1,
        "source_reason": "DESCRIPTION / QTY / AMOUNT table",
        "failed_layers": [],
        "validation_errors": [],
        "pages_rasterized": 1,
    }
    prov.update(over)
    return prov


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    from app.core.config import settings
    monkeypatch.setattr(settings, "storage_root", tmp_path, raising=False)
    monkeypatch.setattr(settings, "api_key", "", raising=False)
    monkeypatch.setattr(settings, "supplier_invoice_ocr_enabled", True, raising=False)
    from app.main import app
    from app.services import supplier_invoice_db as sidb
    sidb.init_db(tmp_path / "supplier_invoice_ocr.sqlite")
    from app.auth.dependencies import get_current_user
    app.dependency_overrides[get_current_user] = lambda: dict(_USER)
    try:
        yield TestClient(app), tmp_path
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def _mock_extraction(monkeypatch, prov):
    calls = []

    def fake(file_path, object_id=None):
        calls.append({"file_path": file_path, "object_id": object_id})
        return json.loads(json.dumps(prov))  # deep copy — route must not depend on shared state

    monkeypatch.setattr(
        "app.api.routes_supplier_invoice_ocr.extract_invoice_lineitems_via_vision", fake
    )
    return calls


def _upload(cl, name=_PDF_BYTES and "invoice.pdf", content=_PDF_BYTES, mime="application/pdf"):
    return cl.post(f"{_BASE}/upload", files={"file": (name, content, mime)})


def _db_rows(tmp_path):
    with sqlite3.connect(tmp_path / "supplier_invoice_ocr.sqlite") as cx:
        cx.row_factory = sqlite3.Row
        return cx.execute("SELECT * FROM supplier_invoice_drafts ORDER BY id").fetchall()


# ── Upload ───────────────────────────────────────────────────────────────────

def test_upload_pdf_happy_path(client, monkeypatch):
    cl, tmp = client
    calls = _mock_extraction(monkeypatch, _ok_prov())
    r = _upload(cl)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["status"] == "pending_review"
    assert body["extraction"]["supplier_name"] == "ABC Exports Pvt Ltd"
    assert body["extraction"]["invoice_number"] == "INV-2026-001"
    assert len(calls) == 1

    rows = _db_rows(tmp)
    assert len(rows) == 1
    row = rows[0]
    assert row["status"] == "pending_review"
    # columns are draft-store-local; VALUES come from the shared schema keys
    assert row["supplier_name"] == "ABC Exports Pvt Ltd"      # ← fields["supplier"]
    assert row["invoice_number"] == "INV-2026-001"            # ← fields["invoice_no"]
    assert row["supplier_gstin"] == "27AABCS1234F1ZA"
    assert row["invoice_date"] == "2026-01-15"
    # machine-extracted grand total (operator ruling 2026-07-03)
    assert row["total_amount"] == 77250.0
    machine = json.loads(row["machine_original_json"])
    assert machine["currency"] == "INR"
    assert machine["subtotal"] == 75000.0
    assert machine["line_items"][0]["hsn"] == "711319"
    # full provenance preserved, not just the fields
    raw = json.loads(row["raw_extraction_json"])
    assert raw["extraction_method"] == "vision_llm"
    assert raw["fields"]["supplier"] == "ABC Exports Pvt Ltd"
    # the uploaded file is on disk where the row says it is
    assert Path(row["source_file_path"]).read_bytes() == _PDF_BYTES
    assert str(tmp) in row["source_file_path"]


def test_upload_png_happy_path(client, monkeypatch):
    cl, tmp = client
    _mock_extraction(monkeypatch, _ok_prov())
    r = _upload(cl, "invoice.png", _PNG_BYTES, "image/png")
    assert r.status_code == 201, r.text
    assert _db_rows(tmp)[0]["source_filename"] == "invoice.png"


def test_upload_gateway_unavailable(client, monkeypatch):
    cl, tmp = client
    _mock_extraction(monkeypatch, {
        "ok": False, "extraction_method": "failed", "model_attempt": None,
        "extraction_confidence": 0.0, "fields": {}, "source_file": "x.pdf",
        "source_page": None, "source_reason": None,
        "failed_layers": ["ai_gateway_unavailable"],
        "validation_errors": [], "pages_rasterized": 0,
    })
    r = _upload(cl)
    assert r.status_code == 503, r.text
    body = r.json()
    assert body["error"] == "ai_extraction_unavailable"
    # partial success: the file + draft row are persisted for later retry
    assert body["draft_id"]
    rows = _db_rows(tmp)
    assert rows[0]["status"] == "pending_review"
    assert rows[0]["extraction_method"] == "failed"


def test_upload_extraction_failed_other(client, monkeypatch):
    cl, tmp = client
    _mock_extraction(monkeypatch, {
        "ok": False, "extraction_method": "failed", "model_attempt": None,
        "extraction_confidence": 0.0, "fields": {}, "source_file": "x.pdf",
        "source_page": None, "source_reason": None,
        "failed_layers": ["primary_unparseable_json", "secondary_unparseable_json"],
        "validation_errors": [], "pages_rasterized": 2,
    })
    r = _upload(cl)
    assert r.status_code == 422, r.text
    assert r.json()["error"] == "extraction_failed"
    assert _db_rows(tmp)[0]["status"] == "pending_review"  # operator can key manually


def test_upload_feature_flag_disabled(client, monkeypatch):
    cl, tmp = client
    from app.core.config import settings
    monkeypatch.setattr(settings, "supplier_invoice_ocr_enabled", False, raising=False)
    calls = _mock_extraction(monkeypatch, _ok_prov())
    r = _upload(cl)
    assert r.status_code == 503, r.text
    assert calls == []                       # AI never touched
    assert _db_rows(tmp) == []               # no row
    assert not (tmp / "supplier_invoice_ocr").exists()  # no orphaned file


def test_upload_extension_rejected(client, monkeypatch):
    cl, tmp = client
    calls = _mock_extraction(monkeypatch, _ok_prov())
    r = _upload(cl, "invoice.docx", b"PK\x03\x04junk", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    assert r.status_code == 400, r.text
    assert calls == []
    assert _db_rows(tmp) == []


def test_upload_magic_bytes_rejected(client, monkeypatch):
    cl, tmp = client
    calls = _mock_extraction(monkeypatch, _ok_prov())
    r = _upload(cl, "invoice.pdf", _PNG_BYTES, "application/pdf")  # .pdf ext, PNG content
    assert r.status_code == 400, r.text
    assert calls == []
    assert _db_rows(tmp) == []


def test_upload_empty_file_rejected(client, monkeypatch):
    cl, _ = client
    _mock_extraction(monkeypatch, _ok_prov())
    r = _upload(cl, "invoice.pdf", b"", "application/pdf")
    assert r.status_code == 400, r.text


def test_upload_too_large(client, monkeypatch):
    cl, _ = client
    from app.core.config import settings
    monkeypatch.setattr(settings, "max_upload_bytes", 64, raising=False)
    _mock_extraction(monkeypatch, _ok_prov())
    r = _upload(cl, "invoice.pdf", b"%PDF-1.4" + b"x" * 100, "application/pdf")
    assert r.status_code == 413, r.text


def test_upload_non_invoice_degrades_safely(client, monkeypatch):
    """Capability-gap pin (2026-07-03): the shared extractor has NO
    not_an_invoice classification (deliberately — adding one would change the
    production shipment prompt). A random non-invoice upload must still
    degrade safely: the model's "never guess" discipline returns all-null
    fields, has_value fails, and the route persists an EMPTY pending_review
    draft (422) that only an operator can confirm — never a crash, never
    fabricated data, never an auto-confirmed row.

    This test runs the REAL extractor + validator + route; only the AI
    gateway is mocked, returning what the prompt instructs the model to
    return for an unreadable/non-invoice document.
    """
    from app.services import ai_gateway
    calls = []

    def fake_call_vision(**kw):
        calls.append(kw)
        # A non-invoice document under the "never guess" rules: all nulls,
        # no line rows, honest low confidence.
        return json.dumps({
            "supplier": None, "supplier_address": None, "supplier_gstin": None,
            "invoice_no": None, "invoice_date": None, "currency": None,
            "fob_usd": None, "freight_usd": None, "insurance_usd": None,
            "cif_usd": None, "itemization_available": False, "line_items": [],
            "subtotal": None, "tax_details": [],
            "needs_review": ["supplier", "invoice_no", "line_items"],
            "confidence": 0.05, "source_page": None,
            "source_reason": "document does not contain an invoice table",
        })

    monkeypatch.setattr(ai_gateway, "is_available", lambda: True)
    monkeypatch.setattr(ai_gateway, "call_vision", fake_call_vision)

    cl, tmp = client
    r = _upload(cl, "holiday-photo.png", _PNG_BYTES, "image/png")
    # Safe degradation: 422 (not 5xx, no crash), draft persisted for review.
    assert r.status_code == 422, r.text
    body = r.json()
    assert body["error"] == "extraction_failed"
    assert body["draft_id"]

    # Both escalation attempts ran and gave up — no usable value invented.
    assert len(calls) == 2
    assert [c.get("complexity") for c in calls] == ["moderate", "complex"]

    rows = _db_rows(tmp)
    assert len(rows) == 1
    row = rows[0]
    assert row["status"] == "pending_review"          # review gate is the catch
    # No fabricated business data reached the draft columns.
    assert row["supplier_name"] is None
    assert row["invoice_number"] is None
    assert row["invoice_date"] is None
    assert row["currency"] is None
    assert row["total_amount"] is None
    assert row["machine_original_json"] is None
    raw = json.loads(row["raw_extraction_json"])
    assert raw["ok"] is False
    assert "primary_no_usable_value" in raw["failed_layers"]
    assert "secondary_no_usable_value" in raw["failed_layers"]

    did = body["draft_id"]
    # Nothing auto-confirms: an empty confirm payload is refused …
    assert cl.post(f"{_BASE}/drafts/{did}/confirm", json={}).status_code == 400
    assert cl.post(f"{_BASE}/drafts/{did}/confirm",
                   json={"confirmed_fields": {}}).status_code == 400
    # … and the operator's natural action on junk — Reject — works.
    assert cl.post(f"{_BASE}/drafts/{did}/reject").status_code == 200
    assert _db_rows(tmp)[0]["status"] == "rejected"


# ── List / detail / source-file ──────────────────────────────────────────────

def test_list_drafts_empty(client):
    cl, _ = client
    r = cl.get(f"{_BASE}/drafts")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["drafts"] == []
    assert body["total"] == 0


def test_list_drafts_with_status_filter(client, monkeypatch):
    cl, _ = client
    _mock_extraction(monkeypatch, _ok_prov())
    d1 = _upload(cl).json()["draft_id"]
    d2 = _upload(cl, "second.pdf").json()["draft_id"]
    cl.post(f"{_BASE}/drafts/{d1}/confirm", json={"confirmed_fields": {"total_amount": 1}})

    r = cl.get(f"{_BASE}/drafts", params={"status": "pending_review"})
    assert r.status_code == 200
    ids = [d["id"] for d in r.json()["drafts"]]
    assert ids == [d2]

    r2 = cl.get(f"{_BASE}/drafts", params={"status": "bogus"})
    assert r2.status_code == 400


def test_get_draft_detail(client, monkeypatch):
    cl, _ = client
    _mock_extraction(monkeypatch, _ok_prov(fields={"needs_review": ["subtotal", "invoice_date"]}))
    did = _upload(cl).json()["draft_id"]
    r = cl.get(f"{_BASE}/drafts/{did}")
    assert r.status_code == 200, r.text
    d = r.json()["draft"]
    assert d["needs_review"] == ["subtotal", "invoice_date"]
    assert d["machine_original"]["line_items"][0]["hsn"] == "711319"
    assert d["machine_original"]["line_items"][0]["unit"] == "pcs"
    # raw_extraction is the full provenance dict
    assert d["raw_extraction"]["fields"]["supplier_gstin"] == "27AABCS1234F1ZA"
    assert d["confirmed_fields"] is None


def test_get_draft_404(client):
    cl, _ = client
    assert cl.get(f"{_BASE}/drafts/99999").status_code == 404


def test_source_file_served_no_store(client, monkeypatch):
    cl, _ = client
    _mock_extraction(monkeypatch, _ok_prov())
    did = _upload(cl).json()["draft_id"]
    r = cl.get(f"{_BASE}/drafts/{did}/source-file")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/pdf")
    assert "no-store" in r.headers["cache-control"]        # Lesson G
    assert r.content == _PDF_BYTES


def test_source_file_404_unknown_draft(client):
    cl, _ = client
    assert cl.get(f"{_BASE}/drafts/99999/source-file").status_code == 404


# ── Confirm / reject ─────────────────────────────────────────────────────────

def test_confirm_draft(client, monkeypatch):
    cl, tmp = client
    _mock_extraction(monkeypatch, _ok_prov())
    did = _upload(cl).json()["draft_id"]

    corrected = dict(_FIXTURE_FIELDS)
    corrected["total_amount"] = 77000.0     # operator overrode the machine total
    corrected["subtotal"] = 74000.0         # and corrected the subtotal
    r = cl.post(f"{_BASE}/drafts/{did}/confirm", json={"confirmed_fields": corrected})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "confirmed"
    assert body["confirmed_by"] == "Test Operator"   # server-side identity
    assert body["confirmed_at"]

    row = _db_rows(tmp)[0]
    assert row["status"] == "confirmed"
    assert row["confirmed_by"] == "Test Operator"
    confirmed = json.loads(row["confirmed_fields_json"])
    assert confirmed["total_amount"] == 77000.0
    assert confirmed["subtotal"] == 74000.0
    # machine snapshot untouched by the operator's corrections
    machine = json.loads(row["machine_original_json"])
    assert machine["subtotal"] == 75000.0
    assert machine["total_amount"] == 77250.0


def test_confirm_requires_confirmed_fields(client, monkeypatch):
    cl, _ = client
    _mock_extraction(monkeypatch, _ok_prov())
    did = _upload(cl).json()["draft_id"]
    assert cl.post(f"{_BASE}/drafts/{did}/confirm", json={}).status_code == 400
    assert cl.post(f"{_BASE}/drafts/{did}/confirm",
                   json={"confirmed_fields": "nope"}).status_code == 400


def test_confirm_draft_already_confirmed(client, monkeypatch):
    cl, _ = client
    _mock_extraction(monkeypatch, _ok_prov())
    did = _upload(cl).json()["draft_id"]
    ok = cl.post(f"{_BASE}/drafts/{did}/confirm", json={"confirmed_fields": {"a": 1}})
    assert ok.status_code == 200
    again = cl.post(f"{_BASE}/drafts/{did}/confirm", json={"confirmed_fields": {"a": 2}})
    assert again.status_code == 409, again.text


def test_confirm_unauthenticated(client, monkeypatch):
    cl, _ = client
    _mock_extraction(monkeypatch, _ok_prov())
    did = _upload(cl).json()["draft_id"]

    from app.main import app
    from app.auth.dependencies import get_current_user
    app.dependency_overrides.pop(get_current_user, None)
    r = cl.post(f"{_BASE}/drafts/{did}/confirm", json={"confirmed_fields": {"a": 1}})
    assert r.status_code in (401, 403), r.text


def test_reject_draft(client, monkeypatch):
    cl, tmp = client
    _mock_extraction(monkeypatch, _ok_prov())
    did = _upload(cl).json()["draft_id"]
    r = cl.post(f"{_BASE}/drafts/{did}/reject")
    assert r.status_code == 200, r.text
    assert _db_rows(tmp)[0]["status"] == "rejected"
    # rejected draft can no longer be confirmed
    assert cl.post(f"{_BASE}/drafts/{did}/confirm",
                   json={"confirmed_fields": {"a": 1}}).status_code == 409


# ── Shared extractor: validate_invoice_extraction extensions ────────────────

def test_validate_new_fields_coerce_and_reject():
    from app.services.vision_extractor import validate_invoice_extraction
    clean, errs = validate_invoice_extraction({
        "supplier": "  X Ltd ",
        "supplier_address": " Mumbai ",
        "supplier_gstin": " 27AABCS1234F1ZA ",
        "invoice_date": "15/01/2026",          # wrong format → absent + error
        "currency": "inr",                     # lowercased → uppercased
        "subtotal": "1,234.50",                # string number → coerced
        "total_amount": "77,250.00",           # grand total — string number → coerced
        "line_items": [
            {"description": "Ring", "hsn": "711319", "quantity": "5",
             "unit": " pcs ", "unit_price": 10, "total": 50},
        ],
        "tax_details": [
            {"tax_type": "CGST", "rate": 0, "amount": 10},   # 0% rate is legal
            {"rate": 5},                       # no tax_type → dropped
            "junk",                            # non-object → dropped
        ],
        "needs_review": ["subtotal", "", None, "invoice_date"],
        "confidence": 0.4,
    })
    assert clean["supplier"] == "X Ltd"
    assert clean["supplier_address"] == "Mumbai"
    assert clean["supplier_gstin"] == "27AABCS1234F1ZA"
    assert "invoice_date" not in clean
    assert any("invoice_date" in e for e in errs)
    assert clean["currency"] == "INR"
    assert clean["subtotal"] == 1234.50
    assert clean["total_amount"] == 77250.0
    item = clean["line_items"][0]
    assert item["unit"] == "pcs"
    assert item["unit_price_usd"] == 10       # existing validated name — unchanged
    assert item["total_usd"] == 50
    assert clean["tax_details"] == [{"tax_type": "CGST", "rate": 0.0, "amount": 10}]
    assert clean["needs_review"] == ["subtotal", "invoice_date"]
    assert clean["confidence"] == 0.4


def test_validate_new_fields_absent_stay_absent():
    """Blast-radius pin: when the model omits the new optional fields (the
    normal case for a DHL-scan commercial invoice), the validator must NOT
    fabricate defaults for them — absence is distinguishable from failure."""
    from app.services.vision_extractor import validate_invoice_extraction
    clean, _ = validate_invoice_extraction({
        "supplier": "ACME",
        "invoice_no": "F-1",
        "currency": "USD",
        "fob_usd": 100.0,
        "line_items": [{"description": "Ring", "quantity": 1, "total": 100}],
        "confidence": 0.8,
    })
    for f in ("supplier_address", "supplier_gstin", "invoice_date",
              "subtotal", "tax_details", "needs_review", "total_amount"):
        assert f not in clean, f"{f} fabricated for a document that doesn't carry it"
    # existing fields untouched by the extension
    assert clean["supplier"] == "ACME"
    assert clean["fob_usd"] == 100.0
    assert clean["line_items"][0]["total_usd"] == 100
    assert "unit" not in clean["line_items"][0]


def test_validate_non_dict():
    from app.services.vision_extractor import validate_invoice_extraction
    clean, errs = validate_invoice_extraction("nonsense")
    assert clean["line_items"] == []
    assert clean["itemization_unavailable"] is True
    assert errs


# ── Shared extractor: extraction paths (gateway mocked — no real AI) ─────────

def _write_png(tmp_path) -> str:
    p = tmp_path / "inv.png"
    p.write_bytes(_PNG_BYTES)
    return str(p)


def test_extract_png_happy_with_fences(tmp_path, monkeypatch):
    from app.services import ai_gateway
    from app.services.vision_extractor import extract_invoice_lineitems_via_vision
    monkeypatch.setattr(ai_gateway, "is_available", lambda: True)
    raw = "```json\n" + json.dumps(_FIXTURE_MODEL_JSON) + "\n```"
    seen = []

    def fake(**kw):
        seen.append(kw)
        return raw

    monkeypatch.setattr(ai_gateway, "call_vision", fake)
    prov = extract_invoice_lineitems_via_vision(_write_png(tmp_path), object_id="T-1")
    assert prov["ok"] is True
    assert prov["extraction_method"] == "vision_llm"
    assert prov["model_attempt"] == "primary"
    assert prov["fields"]["invoice_no"] == "INV-2026-001"
    assert prov["fields"]["supplier_gstin"] == "27AABCS1234F1ZA"
    assert prov["fields"]["line_items"][0]["unit"] == "pcs"
    assert prov["extraction_confidence"] == pytest.approx(0.92)
    assert prov["pages_rasterized"] == 0      # image input — no rasterize step
    assert seen[0]["images"][0]["media_type"] == "image/png"
    assert seen[0]["task_type"] == "invoice_lineitem_extraction"


def test_extract_pdf_still_uses_rasterizer(tmp_path, monkeypatch):
    """The image-input branch must not disturb the PDF path the shipment flow
    uses: a .pdf input still goes through rasterize_pdf."""
    from app.services import ai_gateway, vision_extractor
    monkeypatch.setattr(ai_gateway, "is_available", lambda: True)
    monkeypatch.setattr(ai_gateway, "call_vision",
                        lambda **kw: json.dumps(_FIXTURE_MODEL_JSON))
    monkeypatch.setattr(vision_extractor, "rasterize_pdf",
                        lambda path, **kw: [(0, b"fake-png-bytes")])
    p = tmp_path / "inv.pdf"
    p.write_bytes(_PDF_BYTES)
    prov = vision_extractor.extract_invoice_lineitems_via_vision(str(p))
    assert prov["ok"] is True
    assert prov["pages_rasterized"] == 1


def test_extract_escalates_to_secondary(tmp_path, monkeypatch):
    from app.services import ai_gateway
    from app.services.vision_extractor import extract_invoice_lineitems_via_vision
    monkeypatch.setattr(ai_gateway, "is_available", lambda: True)
    responses = ["not json at all", json.dumps(_FIXTURE_MODEL_JSON)]
    seen = []

    def fake(**kw):
        seen.append({"complexity": kw.get("complexity"), "task_type": kw.get("task_type")})
        return responses[len(seen) - 1]

    monkeypatch.setattr(ai_gateway, "call_vision", fake)
    prov = extract_invoice_lineitems_via_vision(_write_png(tmp_path))
    assert prov["ok"] is True
    assert prov["extraction_method"] == "vision_llm_fallback"
    assert prov["model_attempt"] == "secondary"
    assert [s["complexity"] for s in seen] == ["moderate", "complex"]
    assert all(s["task_type"] == "invoice_lineitem_extraction" for s in seen)


def test_extract_gateway_unavailable(tmp_path, monkeypatch):
    from app.services import ai_gateway
    from app.services.vision_extractor import extract_invoice_lineitems_via_vision
    monkeypatch.setattr(ai_gateway, "is_available", lambda: False)
    prov = extract_invoice_lineitems_via_vision(_write_png(tmp_path))
    assert prov["ok"] is False
    assert "ai_gateway_unavailable" in prov["failed_layers"]
