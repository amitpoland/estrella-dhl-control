"""
test_wfirma_good_live_writer.py — guard tests for the goods/add live writer.
NEVER hits wFirma network. http_sender + existence_check are fully injected.
"""
from __future__ import annotations

import io
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List, Optional

import pytest


def _ensure_path() -> None:
    here = Path(__file__).resolve()
    service_dir = here.parents[1]
    repo_root   = here.parents[2]
    for p in (str(service_dir), str(repo_root)):
        if p not in sys.path:
            sys.path.insert(0, p)


_ensure_path()

from app.tools import send_wfirma_good_live_test as snd          # noqa: E402


# ── Constants are locked ──────────────────────────────────────────────────────

def test_constants_locked():
    assert snd.REQUIRED_FLAG         == "--live-confirm-I-understand"
    assert snd.REQUIRED_CONFIRMATION == "YES_CREATE_ONE_TEST_GOOD"
    assert snd.WFIRMA_GOODS_MODULE   == "goods"
    assert snd.WFIRMA_GOODS_ACTION   == "add"


def test_target_registry_has_ejl_015_3():
    t = snd.get_target("ejl-015-3")
    assert t.code        == "EJL/26-27/015-3"
    assert t.unit        == "szt."
    assert t.netto_pln   == 70.41
    assert t.vat_code_id == "222"
    assert t.warehouse_id == "347088"
    assert t.type_value  == "good"
    assert "Wisiorek" in t.name
    assert "Silver LGD" in t.name


def test_target_registry_has_013_set():
    """All three 013 targets present, each with vat=222 / wh=347088 / unit=szt."""
    for key, code, expected_net in [
        ("ejl-013-1", "EJL/26-27/013-1",   85.97),
        ("ejl-013-2", "EJL/26-27/013-2", 2112.31),
        ("ejl-013-3", "EJL/26-27/013-3", 1801.02),
    ]:
        t = snd.get_target(key)
        assert t.code         == code
        assert t.netto_pln    == expected_net
        assert t.vat_code_id  == "222"
        assert t.warehouse_id == "347088"
        assert t.unit         == "szt."
        assert t.type_value   == "good"


def test_all_targets_have_unique_codes():
    codes = [snd.get_target(k).code for k in snd.list_targets()]
    assert len(set(codes)) == len(codes), f"duplicate codes in registry: {codes}"


def test_full_14_target_registry():
    """All 14 EJL/26-27 codes present, all uniform on vat/warehouse/unit/type."""
    expected = {
        "ejl-013-1": ("EJL/26-27/013-1",   85.97),
        "ejl-013-2": ("EJL/26-27/013-2", 2112.31),
        "ejl-013-3": ("EJL/26-27/013-3", 1801.02),
        "ejl-014-1": ("EJL/26-27/014-1", 4502.55),
        "ejl-015-1": ("EJL/26-27/015-1",  926.45),
        "ejl-015-2": ("EJL/26-27/015-2",  578.10),
        "ejl-015-3": ("EJL/26-27/015-3",   70.41),
        "ejl-015-4": ("EJL/26-27/015-4",  109.54),
        "ejl-015-5": ("EJL/26-27/015-5",  346.49),
        "ejl-015-6": ("EJL/26-27/015-6", 1375.22),
        "ejl-015-7": ("EJL/26-27/015-7",  949.91),
        "ejl-015-8": ("EJL/26-27/015-8", 1234.03),
        "ejl-015-9": ("EJL/26-27/015-9",  575.81),
        "ejl-015-10":("EJL/26-27/015-10", 156.87),
    }
    actual_keys = set(snd.list_targets())
    assert actual_keys == set(expected), (
        f"registry mismatch — extra={actual_keys-set(expected)} "
        f"missing={set(expected)-actual_keys}"
    )
    for key, (code, net) in expected.items():
        t = snd.get_target(key)
        assert t.code         == code,      f"{key}: code={t.code}"
        assert t.netto_pln    == net,       f"{key}: net={t.netto_pln}"
        assert t.vat_code_id  == "222",     f"{key}: vat={t.vat_code_id}"
        assert t.warehouse_id == "347088",  f"{key}: wh={t.warehouse_id}"
        assert t.unit         == "szt.",    f"{key}: unit={t.unit}"
        assert t.warehouse_type == "extended"
        assert t.type_value   == "good"


def test_unknown_target_rejected_at_argparse(capsys):
    with pytest.raises(SystemExit):
        snd.main(argv=["--target", "made-up"], input_stream=io.StringIO(""))


# ── XML body validation ──────────────────────────────────────────────────────

def test_xml_well_formed_and_contains_required_fields():
    t = snd.get_target("ejl-015-3")
    xml = snd.build_good_xml(t)
    root = ET.fromstring(xml)
    assert root.tag == "api"
    good = root.find("goods/good")
    assert good is not None
    assert good.findtext("code") == t.code
    assert good.findtext("name") == t.name
    assert good.findtext("unit") == t.unit
    assert good.findtext("type") == "good"
    assert good.findtext("netto") == f"{t.netto_pln:.2f}"
    assert good.find("vat_code/id").text == t.vat_code_id
    assert good.find("vat_code_purchase/id").text == t.vat_code_id
    assert good.find("warehouse/id").text == t.warehouse_id
    assert good.findtext("warehouse_type") == t.warehouse_type


def test_xml_uses_dot_decimal_for_netto():
    t = snd.get_target("ejl-015-3")
    xml = snd.build_good_xml(t)
    assert "<netto>70.41</netto>" in xml
    assert ",41" not in xml


def test_xml_escapes_special_chars_in_name():
    """If a future target has special chars in name, output must stay well-formed."""
    rogue = snd.GoodTarget(
        key="rogue", code="X/1",
        name="Test <evil> & 'quote' \"x\"",
        unit="szt.", netto_pln=1.0,
        vat_code_id="222", warehouse_id="347088",
        warehouse_type="extended", type_value="good",
    )
    xml = snd.build_good_xml(rogue)
    ET.fromstring(xml)   # must parse
    assert "<evil>" not in xml


# ── Dry-run path: no flag → no HTTP ───────────────────────────────────────────

def test_dry_run_without_flag(capsys):
    sent: List[str] = []
    rc = snd.main(
        argv=["--target", "ejl-015-3"],
        input_stream=io.StringIO(""),
        http_sender=lambda x: sent.append(x) or pytest.fail("must not send"),
        existence_check=lambda code: pytest.fail("must not check existence in dry-run"),
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert sent == []
    assert "DRY-RUN" in out
    assert "EJL/26-27/015-3" in out
    assert "EXPECTED RESULT" in out
    assert "ROLLBACK" in out


# ── Existence guard: refuses if code already in wFirma ────────────────────────

def test_refuses_when_code_already_exists(capsys):
    sent: List[str] = []
    rc = snd.main(
        argv=["--target", "ejl-015-3", snd.REQUIRED_FLAG],
        input_stream=io.StringIO(snd.REQUIRED_CONFIRMATION + "\n"),
        existence_check=lambda code: "29579251",   # pretend it already exists
        http_sender=lambda x: sent.append(x),
    )
    err = capsys.readouterr().err
    assert rc == 6
    assert sent == []
    assert "ALREADY EXISTS" in err
    assert "29579251" in err


# ── Confirmation phrase guard ─────────────────────────────────────────────────

@pytest.mark.parametrize("typed", [
    "", "yes", "Y", "YES", "YES_CREATE_ONE_TEST_good",
    " YES_CREATE_ONE_TEST_GOOD", "YES_CREATE_ONE_TEST_GOOD ",
    "YES_CREATE_ONE_TEST_PZ",   # the OTHER confirmation
])
def test_wrong_confirmation_aborts(capsys, typed):
    sent: List[str] = []
    rc = snd.main(
        argv=["--target", "ejl-015-3", snd.REQUIRED_FLAG],
        input_stream=io.StringIO(typed + "\n"),
        existence_check=lambda code: None,
        http_sender=lambda x: sent.append(x),
    )
    err = capsys.readouterr().err
    assert rc == 4
    assert sent == []
    assert "ABORTED" in err


# ── Happy path: exact phrase + no existing good = exactly one send ────────────

def test_exact_confirmation_sends_exactly_once(capsys):
    sent: List[str] = []

    def stub_sender(xml_body: str):
        sent.append(xml_body)
        return snd.GoodSendResult(
            ok=True, http_status=200, wfirma_status="OK", wfirma_message="",
            good_id="9876543",
            raw_response='<api><status><code>OK</code></status>'
                         '<goods><good><id>9876543</id></good></goods></api>',
        )

    rc = snd.main(
        argv=["--target", "ejl-015-3", snd.REQUIRED_FLAG],
        input_stream=io.StringIO(snd.REQUIRED_CONFIRMATION + "\n"),
        existence_check=lambda code: None,
        http_sender=stub_sender,
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert len(sent) == 1
    assert "good ID        : 9876543" in out
    assert "✓ OK" in out


# ── Failure response is non-zero ──────────────────────────────────────────────

def test_failure_response_returns_nonzero(capsys):
    def stub_sender(xml_body: str):
        return snd.GoodSendResult(
            ok=False, http_status=200, wfirma_status="INPUT ERROR",
            wfirma_message="missing field foo",
            good_id=None,
            raw_response='<api><status><code>INPUT ERROR</code>'
                         '<message>missing field foo</message></status></api>',
        )

    rc = snd.main(
        argv=["--target", "ejl-015-3", snd.REQUIRED_FLAG],
        input_stream=io.StringIO(snd.REQUIRED_CONFIRMATION + "\n"),
        existence_check=lambda code: None,
        http_sender=stub_sender,
    )
    out = capsys.readouterr().out
    assert rc == 1
    assert "✗ FAILED" in out
    assert "INPUT ERROR" in out
    assert "missing field foo" in out


# ── Response parser ───────────────────────────────────────────────────────────

def test_parse_response_picks_up_good_id():
    body = (
        '<?xml version="1.0"?>'
        '<api><status><code>OK</code></status>'
        '<goods><good><id>4242</id></good></goods></api>'
    )
    r = snd._parse_response(200, body)
    assert r.ok is True
    assert r.good_id == "4242"
    assert r.wfirma_status == "OK"


def test_parse_response_handles_input_error():
    body = (
        '<?xml version="1.0"?>'
        '<api><status><code>INPUT ERROR</code>'
        '<message>bad</message></status></api>'
    )
    r = snd._parse_response(200, body)
    assert r.ok is False
    assert r.good_id is None
    assert "bad" in r.wfirma_message


def test_parse_response_handles_unparseable_text():
    r = snd._parse_response(500, "<<not xml>>")
    assert r.ok is False
    assert r.good_id is None
