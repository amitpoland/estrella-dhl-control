"""
test_dashboard_cache_freshness_api.py — guards against the regression
observed on SHIPMENT_6876258325_2026-04 where:
  - audit.json was stale (no row_schema_version)
  - cache_freshness was absent from the API response
  - the dashboard had no signal that it should not render download links
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_SVC = Path(__file__).parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

from app.api import routes_dashboard as rd  # noqa: E402


def _write_batch(outputs: Path, batch_id: str, *, fresh: bool, with_pdf: bool) -> Path:
    bdir = outputs / batch_id
    (bdir / "source" / "invoices").mkdir(parents=True, exist_ok=True)
    (bdir / "source" / "sad").mkdir(parents=True, exist_ok=True)
    audit = {
        "batch_id":    batch_id,
        "tracking_no": "1234567890",
        "doc_no":      "PZ TEST",
        "status":      "partial",
        "inputs":      {"invoices": ["x.pdf"], "zc429": "z.pdf"},
        "rows": [{
            "invoice_no":   "EJL/25-26/1247",
            "product_code": "EJL/25-26/1247-1" if fresh else "",
            "nazwa_pl":     "x" if fresh else "",
            "nazwa_en":     "x" if fresh else "",
            "nazwa":        "x / x" if fresh else "",
            "quantity":     1,
        }],
    }
    if fresh:
        audit["row_schema_version"] = "v2"
    (bdir / "audit.json").write_text(json.dumps(audit), encoding="utf-8")
    if with_pdf:
        (bdir / "PZ_test.pdf").write_bytes(b"%PDF-1.4 fake")
    return bdir


@pytest.fixture
def outputs(tmp_path, monkeypatch):
    """Repoint routes_dashboard at a temp outputs dir for each test."""
    out = tmp_path / "outputs"
    out.mkdir()
    monkeypatch.setattr(rd, "_OUTPUTS", out)
    return out


# ── Tests ────────────────────────────────────────────────────────────────────

def test_response_includes_cache_freshness_for_stale_batch(outputs):
    _write_batch(outputs, "SHIPMENT_STALE_001", fresh=False, with_pdf=False)
    body = rd.batch_detail("SHIPMENT_STALE_001")
    cf = body.get("cache_freshness")
    assert cf is not None, "cache_freshness must be present on every detail response"
    assert cf["stale"] is True
    assert cf["regenerate_required"] is True
    assert "product_code" in cf["rows_missing_fields"][0]["missing"]


def test_response_includes_cache_freshness_for_fresh_batch(outputs):
    _write_batch(outputs, "SHIPMENT_FRESH_001", fresh=True, with_pdf=True)
    body = rd.batch_detail("SHIPMENT_FRESH_001")
    cf = body["cache_freshness"]
    assert cf["stale"] is False
    assert cf["regenerate_required"] is False


def test_files_detail_always_present_even_when_files_missing(outputs):
    _write_batch(outputs, "SHIPMENT_NO_FILES", fresh=False, with_pdf=False)
    body  = rd.batch_detail("SHIPMENT_NO_FILES")
    files = (body.get("files_detail") or {}).get("files") or {}
    for key in ("pz_pdf", "calc_xlsx", "audit_en", "audit_pl", "audit_memo", "corrections"):
        assert key in files, f"files_detail.files.{key} must always be present"
        assert "exists" in files[key]
        assert isinstance(files[key]["exists"], bool)


def test_missing_pz_does_not_remove_files_detail_keys(outputs):
    """Regression: the dashboard relies on every output key being present
    so it can render a 'missing' chip rather than collapsing the panel."""
    _write_batch(outputs, "SHIPMENT_NO_PZ", fresh=False, with_pdf=False)
    body  = rd.batch_detail("SHIPMENT_NO_PZ")
    files = body["files_detail"]["files"]
    assert files["pz_pdf"]["exists"] is False
    assert files["pz_pdf"]["url"] == ""
    assert files["calc_xlsx"]["exists"] is False


def test_pz_pdf_url_present_when_file_exists(outputs):
    _write_batch(outputs, "SHIPMENT_HAS_PDF", fresh=True, with_pdf=True)
    body = rd.batch_detail("SHIPMENT_HAS_PDF")
    pz   = body["files_detail"]["files"]["pz_pdf"]
    assert pz["exists"] is True
    assert pz["url"].startswith("/api/v1/files/SHIPMENT_HAS_PDF/")


def test_stale_batch_still_returns_status_and_links_object(outputs):
    """Stale state must NOT cause the response to omit other sections."""
    _write_batch(outputs, "SHIPMENT_STALE_FULL", fresh=False, with_pdf=False)
    body = rd.batch_detail("SHIPMENT_STALE_FULL")
    assert body.get("status") == "partial"
    assert "files_detail" in body
    assert "cache_freshness" in body
    # All informational sections still served — staleness must not strip them.
    for key in ("inputs", "rows", "tracking_no", "doc_no"):
        assert key in body, f"{key} should still appear when audit is stale"
