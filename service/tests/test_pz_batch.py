"""
test_pz_batch.py — unit tests for build_pz_batch + validate_pz_batch + schema.

NEVER hits wFirma. The --resolve path is exercised with a mocked
get_product_by_code so no network is required.
"""
from __future__ import annotations

import csv
import io
import json
import sys
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest


def _ensure_path() -> None:
    here = Path(__file__).resolve()
    service_dir = here.parents[1]
    repo_root   = here.parents[2]
    for p in (str(service_dir), str(repo_root)):
        if p not in sys.path:
            sys.path.insert(0, p)


_ensure_path()

from app.models.pz_batch_schema import (   # noqa: E402
    DEFAULT_PZ_SERIES_ID, DEFAULT_UNIT_ID, DEFAULT_VAT_CODE_ID,
    PZBatch, PZBatchLine, Supplier,
)
from app.tools import build_pz_batch as bb     # noqa: E402
from app.tools import validate_pz_batch as vb  # noqa: E402


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _inv(invoice_no: str, rows: list, supplier_id="38142296",
         supplier="ESTRELLA JEWELS LLP.", date="2026-04-04") -> dict:
    return {
        "invoice_no":         invoice_no,
        "supplier":           supplier,
        "supplier_wfirma_id": supplier_id,
        "warehouse_id":       "347088",
        "document_date":      date,
        "rows":               rows,
    }


def _row(code: str, gid: str, name: str, qty, price) -> dict:
    return {
        "product_code":   code,
        "wfirma_good_id": gid,
        "name":           name,
        "quantity":       qty,
        "unit":           "szt.",
        "net_price_pln":  price,
    }


def _fixture_invoices() -> list:
    return [
        _inv("EJL/26-27/013", [
            _row("EJL/26-27/013-1", "48461859", "Wisiorek 18KT Gold / 18KT Gold Pendant", 5, 85.97),
            _row("EJL/26-27/013-2", "48461923", "Pierścionek 18KT Gold / 18KT Gold Ring", 1, 2112.31),
            _row("EJL/26-27/013-3", "48461987", "Kolczyki PT950 / PT950 Diamond Earrings", 1, 1801.02),
        ]),
        _inv("EJL/26-27/014", [
            _row("EJL/26-27/014-1", "48462051", "Pierścionek 14KT / 14KT Gold Diamond Ring", 1, 4502.55),
        ]),
    ]


# ── Schema decimal sanity ─────────────────────────────────────────────────────

def test_decimal_helper_avoids_float_precision_loss():
    # 70.41 stringified is exact; 70.41 as float would be 70.4099999...
    assert bb._decimal(70.41) == Decimal("70.41")
    assert bb._decimal("70.41") == Decimal("70.41")
    assert bb._decimal(2112.31) == Decimal("2112.31")


def test_pzbatch_total_net_uses_decimal_quantize():
    b = PZBatch(
        batch_id="AWB_1", awb="1", sad_number="", series_id="x",
        supplier=Supplier(wfirma_id="38142296", name="x"),
        warehouse_id="347088", document_date="2026-04-04",
        currency="PLN", price_type="netto",
        lines=[
            PZBatchLine("EJL/x-1", "111", "x", Decimal("5"), Decimal("85.97"),
                        invoice_no="EJL/A"),
            PZBatchLine("EJL/x-2", "222", "y", Decimal("1"), Decimal("2112.31"),
                        invoice_no="EJL/A"),
        ],
    )
    assert b.total_net() == Decimal("2542.16")


# ── build_batch ───────────────────────────────────────────────────────────────

def test_build_batch_merges_invoices_into_single_pz():
    invoices = _fixture_invoices()
    b = bb.build_batch(invoices, awb="6876258325", sad_number="PL123")
    assert b.awb == "6876258325"
    assert b.sad_number == "PL123"
    assert b.batch_id == "AWB_6876258325"
    assert b.supplier.wfirma_id == "38142296"
    assert len(b.lines) == 4
    assert b.total_net() == Decimal("8845.73")
    assert b.invoices == ["EJL/26-27/013", "EJL/26-27/014"]
    assert b.warehouse_id == "347088"
    assert b.series_id == DEFAULT_PZ_SERIES_ID


def test_build_batch_preserves_invoice_attribution_per_line():
    invoices = _fixture_invoices()
    b = bb.build_batch(invoices, awb="X", sad_number="")
    by_code = {ln.product_code: ln.invoice_no for ln in b.lines}
    assert by_code["EJL/26-27/013-1"] == "EJL/26-27/013"
    assert by_code["EJL/26-27/014-1"] == "EJL/26-27/014"


def test_build_batch_rejects_different_suppliers():
    a = _inv("EJL/A", [_row("EJL/A-1", "111", "x", 1, 10)], supplier_id="38142296")
    b = _inv("EJL/B", [_row("EJL/B-1", "222", "y", 1, 20)], supplier_id="99999999")
    with pytest.raises(ValueError, match="different suppliers"):
        bb.build_batch([a, b], awb="X", sad_number="")


def test_build_batch_rejects_no_invoices():
    with pytest.raises(ValueError, match="no invoices"):
        bb.build_batch([], awb="X", sad_number="")


def test_build_batch_rejects_different_warehouses():
    a = _inv("EJL/A", [_row("EJL/A-1", "111", "x", 1, 10)])
    a["warehouse_id"] = "111111"
    b = _inv("EJL/B", [_row("EJL/B-1", "222", "y", 1, 20)])
    b["warehouse_id"] = "222222"
    with pytest.raises(ValueError, match="different warehouse_id"):
        bb.build_batch([a, b], awb="X", sad_number="")


def test_build_batch_default_date_falls_back_to_invoice_date():
    inv = _inv("EJL/A", [_row("EJL/A-1", "111", "x", 1, 10)], date="2026-03-01")
    b = bb.build_batch([inv], awb="X", sad_number="")
    assert b.document_date == "2026-03-01"


def test_build_batch_explicit_date_overrides():
    inv = _inv("EJL/A", [_row("EJL/A-1", "111", "x", 1, 10)], date="2026-03-01")
    b = bb.build_batch([inv], awb="X", sad_number="", document_date="2026-09-09")
    assert b.document_date == "2026-09-09"


def test_build_batch_supplier_dict_form_accepted():
    inv = _inv("EJL/A", [_row("EJL/A-1", "111", "x", 1, 10)])
    inv["supplier"] = {"wfirma_id": "38142296", "name": "ESTRELLA JEWELS LLP."}
    inv.pop("supplier_wfirma_id", None)
    b = bb.build_batch([inv], awb="X", sad_number="")
    assert b.supplier.wfirma_id == "38142296"


# ── --resolve auto-resolution (mocked) ────────────────────────────────────────

def test_resolve_fills_missing_good_ids():
    inv = _inv("EJL/A", [
        _row("EJL/A-1", "", "x", 1, 10),     # good_id missing
        _row("EJL/A-2", "999", "y", 1, 20),   # good_id present, untouched
    ])

    class _StubProd:
        def __init__(self, wid): self.wfirma_id = wid

    fake_lookups = {"EJL/A-1": _StubProd("48461111"), "EJL/A-2": _StubProd("999")}

    with patch("app.services.wfirma_client.get_product_by_code",
               side_effect=lambda c: fake_lookups.get(c)):
        b = bb.build_batch([inv], awb="X", sad_number="", resolve_good_ids=True)

    by_code = {ln.product_code: ln.wfirma_good_id for ln in b.lines}
    assert by_code["EJL/A-1"] == "48461111"
    assert by_code["EJL/A-2"] == "999"


def test_resolve_raises_when_some_codes_unknown():
    inv = _inv("EJL/A", [_row("EJL/A-1", "", "x", 1, 10)])
    with patch("app.services.wfirma_client.get_product_by_code", side_effect=lambda c: None):
        with pytest.raises(ValueError, match="goods/find could not resolve"):
            bb.build_batch([inv], awb="X", sad_number="", resolve_good_ids=True)


# ── Validator ─────────────────────────────────────────────────────────────────

def _make_batch_from_fixture():
    return bb.build_batch(_fixture_invoices(), awb="X", sad_number="")


def test_validator_passes_clean_batch():
    b = _make_batch_from_fixture()
    v = vb.validate(b)
    assert v.ok is True
    assert v.errors == []


def test_validator_blocks_missing_good_id():
    b = _make_batch_from_fixture()
    b.lines[0].wfirma_good_id = ""
    v = vb.validate(b)
    assert v.ok is False
    assert any("wfirma_good_id MISSING" in e for e in v.errors)


def test_validator_blocks_zero_qty_or_price():
    b = _make_batch_from_fixture()
    b.lines[0].qty = Decimal("0")
    b.lines[1].price_net_pln = Decimal("0")
    v = vb.validate(b)
    assert v.ok is False
    assert any("qty must be > 0" in e for e in v.errors)
    assert any("price_net_pln must be > 0" in e for e in v.errors)


def test_validator_blocks_duplicate_invoice_code_pair():
    b = _make_batch_from_fixture()
    # Force duplicate (same invoice + same product_code)
    b.lines.append(PZBatchLine(
        product_code   = b.lines[0].product_code,
        wfirma_good_id = "00000001",
        name           = "dup",
        qty            = Decimal("1"),
        price_net_pln  = Decimal("1"),
        invoice_no     = b.lines[0].invoice_no,
    ))
    v = vb.validate(b)
    assert v.ok is False
    assert any("duplicate (invoice=" in e and "product_code=" in e for e in v.errors)


def test_validator_blocks_duplicate_invoice_good_id_pair():
    b = _make_batch_from_fixture()
    b.lines.append(PZBatchLine(
        product_code   = "EJL/X",
        wfirma_good_id = b.lines[0].wfirma_good_id,
        name           = "dup_gid",
        qty            = Decimal("1"),
        price_net_pln  = Decimal("1"),
        invoice_no     = b.lines[0].invoice_no,
    ))
    v = vb.validate(b)
    assert v.ok is False
    assert any("duplicate (invoice=" in e and "wfirma_good_id=" in e for e in v.errors)


def test_validator_blocks_currency_other_than_pln():
    b = _make_batch_from_fixture()
    b.currency = "USD"
    v = vb.validate(b)
    assert v.ok is False
    assert any("currency must be 'PLN'" in e for e in v.errors)


def test_validator_warns_on_empty_sad():
    b = _make_batch_from_fixture()
    b.sad_number = ""
    v = vb.validate(b)
    assert v.ok is True
    assert any("sad_number is empty" in w for w in v.warnings)


# ── End-to-end through the file system ───────────────────────────────────────

def test_save_json_csv_ui_round_trip(tmp_path: Path):
    inv1 = tmp_path / "PZ_READY_inv1.json"
    inv2 = tmp_path / "PZ_READY_inv2.json"
    inv1.write_text(json.dumps(_fixture_invoices()[0]), encoding="utf-8")
    inv2.write_text(json.dumps(_fixture_invoices()[1]), encoding="utf-8")

    invoices = [bb.load_pz_ready(p) for p in (inv1, inv2)]
    batch = bb.build_batch(invoices, awb="6876258325", sad_number="PL123")
    val = vb.validate(batch)
    assert val.ok

    out_dir = tmp_path / "outputs"
    pj = bb.save_json(batch, out_dir)
    pc = bb.save_csv(batch, out_dir)
    pu = bb.save_ui_payload(batch, out_dir)

    # JSON round-trip
    j = json.loads(pj.read_text(encoding="utf-8"))
    assert j["awb"] == "6876258325"
    assert j["total_net_pln"] == "8845.73"
    assert len(j["lines"]) == 4
    assert j["supplier"]["wfirma_id"] == "38142296"

    # CSV — first line, semicolon-separated, comma decimal
    # On-disk line endings must be exactly \r\n (one per row), never the doubled
    # \r\r\n produced by Path.write_text on Windows. Guard against regression.
    csv_bytes = pc.read_bytes()
    assert b"\r\r\n" not in csv_bytes
    raw = pc.read_text(encoding="utf-8-sig").splitlines()
    assert len(raw) == 4
    parsed = list(csv.reader(io.StringIO("\n".join(raw)), delimiter=";"))
    # Each row 11 cols; price has comma decimal; code is in cols 7 + 9
    for row in parsed:
        assert len(row) == 11
        assert "," in row[4]              # Cena
        assert row[6] == row[8]           # Szczegółowy opis == Kod produktu
        assert row[5] == "23%"
        assert row[7] == "netto"
        assert row[9] == "towar"

    # UI payload — lean structure
    u = json.loads(pu.read_text(encoding="utf-8"))
    assert u["awb"] == "6876258325"
    assert u["supplier_id"] == "38142296"
    assert len(u["lines"]) == 4
    for ln in u["lines"]:
        assert ln["product_code"] and ln["wfirma_good_id"]
        # Strings preserve precision
        assert "." in ln["price_net_pln"] or ln["price_net_pln"].isdigit()


def test_main_cli_writes_three_files(tmp_path: Path, capsys):
    inv1 = tmp_path / "PZ_READY_a.json"
    inv1.write_text(json.dumps(_fixture_invoices()[0]), encoding="utf-8")
    out = tmp_path / "out"
    rc = bb.main(["--awb", "AAA", "--sad", "SAD-001", "--out-dir", str(out), str(inv1)])
    assert rc == 0
    assert (out / "PZ_BATCH_AAA.json").is_file()
    assert (out / "PZ_BATCH_AAA.csv").is_file()
    assert (out / "PZ_BATCH_AAA_ui.json").is_file()
    captured = capsys.readouterr().out
    assert "PZ BATCH CREATED" in captured
    assert "AWB           : AAA" in captured


def test_main_cli_returns_nonzero_on_validation_fail(tmp_path: Path):
    bad = _fixture_invoices()[0]
    bad["rows"][0]["wfirma_good_id"] = ""    # block
    p = tmp_path / "PZ_READY_bad.json"
    p.write_text(json.dumps(bad), encoding="utf-8")
    rc = bb.main(["--awb", "X", "--sad", "", "--out-dir", str(tmp_path / "out"), str(p)])
    assert rc == 3
