"""
test_pz_output_audit_field.py — _build_pz_output writes correct pz_output block.

Coverage
--------
1. pdf and xlsx filenames present when files exist
2. paths are relative (filename only, no leading slash or backslash)
3. generated_at is an ISO timestamp string
4. mrn comes from result["zc429"]["mrn"]
5. awb taken from tracking_no arg
6. awb falls back to existing["tracking_no"] when arg is empty
7. awb falls back to existing["awb"] when tracking_no and existing["tracking_no"] absent
8. missing pdf → pdf slot is None, xlsx slot unaffected
9. missing xlsx → xlsx slot is None, pdf slot unaffected
10. re-call overwrites cleanly (idempotent — returns plain dict, not appended list)
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest


def _ensure_path() -> None:
    here = Path(__file__).resolve()
    for p in (str(here.parents[1]), str(here.parents[2])):
        if p not in sys.path:
            sys.path.insert(0, p)

_ensure_path()

from app.services.export_service import _build_pz_output  # noqa: E402


# Satisfy the conftest _guard_storage_root fixture: importing export_service pulls
# in settings; redirect storage_root to tmp_path so the guard doesn't fire.
@pytest.fixture(autouse=True)
def _isolate_storage(tmp_path, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "storage_root", tmp_path)


# ── helpers ───────────────────────────────────────────────────────────────────

def _result(mrn: str = "26PLTEST0001") -> dict:
    return {"zc429": {"mrn": mrn}}


def _make_files(tmp_path: Path, *, pdf: bool = True, xlsx: bool = True):
    pdf_path  = tmp_path / "PZ_AWB_1234_MRN_TEST_2026-01-01.pdf"
    xlsx_path = tmp_path / "PZ_CALC_AWB_1234_MRN_TEST_2026-01-01.xlsx"
    if pdf:
        pdf_path.write_bytes(b"%PDF-1.4 stub")
    if xlsx:
        xlsx_path.write_bytes(b"PK stub xlsx")
    return pdf_path, xlsx_path


# ── tests ─────────────────────────────────────────────────────────────────────

def test_pdf_and_xlsx_names(tmp_path):
    pdf, xlsx = _make_files(tmp_path)
    po = _build_pz_output(pdf, xlsx, _result(), "1234567890", {})
    assert po["pdf"]  == pdf.name
    assert po["xlsx"] == xlsx.name


def test_paths_are_relative(tmp_path):
    pdf, xlsx = _make_files(tmp_path)
    po = _build_pz_output(pdf, xlsx, _result(), "1234567890", {})
    for key in ("pdf", "xlsx"):
        val = po[key]
        assert val is not None
        assert not val.startswith("/"), f"pz_output.{key} must be relative, got: {val}"
        assert "\\" not in val


def test_generated_at_is_iso(tmp_path):
    pdf, xlsx = _make_files(tmp_path)
    po = _build_pz_output(pdf, xlsx, _result(), "1234567890", {})
    ts = po["generated_at"]
    assert isinstance(ts, str) and len(ts) >= 19
    import datetime
    datetime.datetime.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S")


def test_mrn_from_result(tmp_path):
    pdf, xlsx = _make_files(tmp_path)
    po = _build_pz_output(pdf, xlsx, _result(mrn="26PLSPECIAL"), "1234567890", {})
    assert po["mrn"] == "26PLSPECIAL"


def test_awb_from_tracking_no(tmp_path):
    pdf, xlsx = _make_files(tmp_path)
    po = _build_pz_output(pdf, xlsx, _result(), "9876543210", {})
    assert po["awb"] == "9876543210"


def test_awb_fallback_to_existing_tracking_no(tmp_path):
    pdf, xlsx = _make_files(tmp_path)
    existing = {"tracking_no": "FALLBACK_TRK", "carrier": "DHL"}
    po = _build_pz_output(pdf, xlsx, _result(), "", existing)
    assert po["awb"] == "FALLBACK_TRK"


def test_awb_fallback_to_existing_awb(tmp_path):
    pdf, xlsx = _make_files(tmp_path)
    existing = {"awb": "FALLBACK_AWB"}
    po = _build_pz_output(pdf, xlsx, _result(), "", existing)
    assert po["awb"] == "FALLBACK_AWB"


def test_missing_pdf_slot_is_none(tmp_path):
    pdf, xlsx = _make_files(tmp_path, pdf=False, xlsx=True)
    po = _build_pz_output(pdf, xlsx, _result(), "1234567890", {})
    assert po["pdf"]  is None
    assert po["xlsx"] == xlsx.name


def test_missing_xlsx_slot_is_none(tmp_path):
    pdf, xlsx = _make_files(tmp_path, pdf=True, xlsx=False)
    po = _build_pz_output(pdf, xlsx, _result(), "1234567890", {})
    assert po["pdf"]  == pdf.name
    assert po["xlsx"] is None


def test_idempotent_returns_dict(tmp_path):
    pdf, xlsx = _make_files(tmp_path)
    po1 = _build_pz_output(pdf, xlsx, _result(), "1234567890", {})
    time.sleep(1)
    po2 = _build_pz_output(pdf, xlsx, _result(), "1234567890", {})
    # Both calls return plain dicts — no list accumulation
    assert isinstance(po1, dict)
    assert isinstance(po2, dict)
    assert po1["pdf"]  == po2["pdf"]
    assert po1["xlsx"] == po2["xlsx"]
    assert po1["mrn"]  == po2["mrn"]
    assert po1["awb"]  == po2["awb"]
