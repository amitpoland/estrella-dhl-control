"""
test_wfirma_pz_live_writer.py — guard tests for the live PZ writer.

NEVER hits the wFirma network. The HTTP sender is fully injected via
http_sender= or via a stub PzSendResult.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path
from typing import List

import pytest


def _ensure_path() -> None:
    here = Path(__file__).resolve()
    service_dir = here.parents[1]
    repo_root   = here.parents[2]
    for p in (str(service_dir), str(repo_root)):
        if p not in sys.path:
            sys.path.insert(0, p)


_ensure_path()

from app.tools import send_wfirma_pz_live_test as snd          # noqa: E402
from app.tools import build_wfirma_pz_payload as bld           # noqa: E402


# ── XML fixture builders ──────────────────────────────────────────────────────

def _single_line_payload() -> dict:
    return {
        "batch_id": "TEST",
        "invoice_no": "TEST-EJL-26-27-015-3",
        "supplier": "ESTRELLA JEWELS LLP.",
        "supplier_wfirma_id": "38142296",
        "warehouse_id": "347088",
        "document_date": "2026-04-04",
        "rows": [
            {
                "product_code": "EJL/26-27/015-3",
                "wfirma_good_id": "48461283",
                "name": "Wisiorek / Pendant",
                "quantity": 1,
                "unit": "szt.",
                "net_price_pln": 70.41,
            },
        ],
        "totals": {"net_pln": 70.41, "vat_rate": 23},
    }


def _two_line_payload() -> dict:
    p = _single_line_payload()
    p["rows"].append({
        "product_code": "EJL/26-27/013-1",
        "wfirma_good_id": "11111111",
        "name": "Other / Other",
        "quantity": 1,
        "unit": "szt.",
        "net_price_pln": 100.0,
    })
    return p


def _write_xml(tmp_path: Path, data: dict, name: str = "payload.xml") -> Path:
    xml = bld.build_pz_xml(data)
    out = tmp_path / name
    out.write_text(xml, encoding="utf-8")
    return out


# ── Plan extraction ───────────────────────────────────────────────────────────

def test_extract_plan_pulls_supplier_warehouse_codes(tmp_path: Path):
    xml_path = _write_xml(tmp_path, _single_line_payload())
    plan = snd.extract_plan(xml_path)

    assert plan.supplier_id  == "38142296"
    assert plan.warehouse_id == "347088"
    assert plan.date         == "2026-04-04"
    assert plan.line_count   == 1
    assert any("good_id=48461283" in s for s in plan.product_codes)
    assert plan.total_net    == 70.41
    assert "warehouse_document_p_z" in plan.endpoint


def test_extract_plan_rejects_missing_file(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        snd.extract_plan(tmp_path / "nope.xml")


def test_extract_plan_rejects_malformed_xml(tmp_path: Path):
    bad = tmp_path / "bad.xml"
    bad.write_text("<api><warehouse_document_p_z><not closed", encoding="utf-8")
    with pytest.raises(ValueError):
        snd.extract_plan(bad)


# ── Guard: missing flag aborts ────────────────────────────────────────────────

def test_main_without_flag_is_dry_run(tmp_path: Path, capsys, monkeypatch):
    xml_path = _write_xml(tmp_path, _single_line_payload())
    sent: List[str] = []

    def fake_sender(xml_body: str):
        sent.append(xml_body)
        raise AssertionError("sender must not run in dry-run")

    rc = snd.main(
        argv=[str(xml_path)],
        input_stream=io.StringIO(""),
        http_sender=fake_sender,
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert sent == []
    assert "DRY-RUN" in out
    assert "no HTTP call made" in out.lower() or "no HTTP call" in out


# ── Guard: flag present but >1 line is refused ────────────────────────────────

def test_multiline_refused_even_with_flag(tmp_path: Path, capsys):
    xml_path = _write_xml(tmp_path, _two_line_payload())
    sent: List[str] = []

    rc = snd.main(
        argv=[str(xml_path), snd.REQUIRED_FLAG],
        input_stream=io.StringIO(snd.REQUIRED_CONFIRMATION + "\n"),
        http_sender=lambda x: sent.append(x),
    )
    err = capsys.readouterr().err
    assert rc == 3
    assert sent == []
    assert "GUARD REFUSED" in err
    assert "1 line" in err


# ── Confirmation phrase enforcement ───────────────────────────────────────────

@pytest.mark.parametrize("typed", [
    "", "yes", "Yes", "y", "YES", "YES_CREATE_ONE_TEST_pz",
    " YES_CREATE_ONE_TEST_PZ", "YES_CREATE_ONE_TEST_PZ ",
    "YES CREATE ONE TEST PZ", "OK", "no",
])
def test_wrong_or_close_confirmations_abort(tmp_path: Path, capsys, typed: str):
    """Anything that isn't EXACTLY the phrase aborts with no HTTP."""
    xml_path = _write_xml(tmp_path, _single_line_payload())
    sent: List[str] = []

    rc = snd.main(
        argv=[str(xml_path), snd.REQUIRED_FLAG],
        input_stream=io.StringIO(typed + "\n"),
        http_sender=lambda x: sent.append(x),
    )
    err = capsys.readouterr().err
    assert sent == [], f"sender ran for typed={typed!r}"
    assert rc == 4
    assert "ABORTED" in err


# ── Correct confirmation triggers exactly one send ────────────────────────────

def test_exact_confirmation_sends_exactly_once(tmp_path: Path, capsys):
    xml_path = _write_xml(tmp_path, _single_line_payload())
    sent: List[str] = []

    def stub_sender(xml_body: str):
        sent.append(xml_body)
        return snd.PzSendResult(
            ok=True, http_status=200, wfirma_status="OK", wfirma_message="",
            document_id="999001",
            raw_response='<api><status><code>OK</code></status>'
                         '<warehouse_document_p_z><warehouse_document>'
                         '<id>999001</id></warehouse_document>'
                         '</warehouse_document_p_z></api>',
        )

    rc = snd.main(
        argv=[str(xml_path), snd.REQUIRED_FLAG],
        input_stream=io.StringIO(snd.REQUIRED_CONFIRMATION + "\n"),
        http_sender=stub_sender,
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert len(sent) == 1, "exactly one send required"
    assert "document ID    : 999001" in out
    assert "✓ OK" in out


# ── Failure response is reported as fail with non-zero rc ─────────────────────

def test_failure_response_returns_nonzero(tmp_path: Path, capsys):
    xml_path = _write_xml(tmp_path, _single_line_payload())

    def stub_sender(xml_body: str):
        return snd.PzSendResult(
            ok=False, http_status=200, wfirma_status="INPUT ERROR",
            wfirma_message="missing required field x",
            document_id=None,
            raw_response='<api><status><code>INPUT ERROR</code>'
                         '<message>missing required field x</message></status></api>',
        )

    rc = snd.main(
        argv=[str(xml_path), snd.REQUIRED_FLAG],
        input_stream=io.StringIO(snd.REQUIRED_CONFIRMATION + "\n"),
        http_sender=stub_sender,
    )
    out = capsys.readouterr().out
    assert rc == 1
    assert "✗ FAILED" in out
    assert "INPUT ERROR" in out
    assert "missing required field x" in out


# ── Response parser handles document ID + error envelope ──────────────────────

def test_parse_response_picks_up_document_id():
    body = (
        '<?xml version="1.0"?>'
        '<api><status><code>OK</code></status>'
        '<warehouse_document_p_z><warehouse_document><id>4242</id>'
        '</warehouse_document></warehouse_document_p_z></api>'
    )
    r = snd._parse_response(200, body)
    assert r.ok is True
    assert r.document_id == "4242"
    assert r.wfirma_status == "OK"


def test_parse_response_handles_error():
    body = (
        '<?xml version="1.0"?>'
        '<api><status><code>INPUT ERROR</code>'
        '<message>bad payload</message></status></api>'
    )
    r = snd._parse_response(200, body)
    assert r.ok is False
    assert r.document_id is None
    assert r.wfirma_status == "INPUT ERROR"
    assert "bad payload" in r.wfirma_message


def test_parse_response_handles_unparseable_text():
    r = snd._parse_response(500, "<<<not xml>>>")
    assert r.ok is False
    assert r.document_id is None


# ── Constants are locked (regression guard) ───────────────────────────────────

def test_constants_are_locked():
    assert snd.REQUIRED_FLAG         == "--live-confirm-I-understand"
    assert snd.REQUIRED_CONFIRMATION == "YES_CREATE_ONE_TEST_PZ"
    assert snd.MAX_LINES_FOR_TEST    == 1
    assert snd.WFIRMA_PZ_MODULE      == "warehouse_document_p_z"
    assert snd.WFIRMA_PZ_ACTION      == "add"


# ── Real test payload file is well-formed (if present) ────────────────────────

def test_real_test_payload_is_valid_single_line():
    repo = Path(__file__).resolve().parents[2]
    path = repo / "outputs" / "wfirma_pz_payload_TEST-EJL-26-27-015-3.xml"
    if not path.is_file():
        pytest.skip("test payload XML not generated yet")
    plan = snd.extract_plan(path)
    assert plan.line_count == 1
    assert any("good_id=48461283" in s for s in plan.product_codes)
    assert plan.supplier_id == "38142296"
    assert plan.warehouse_id == "347088"
    assert plan.total_net == 70.41
