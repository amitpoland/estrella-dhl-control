"""
test_wfirma_pz_csv.py — CSV builder + validator tests. No HTTP, no wFirma.
"""
from __future__ import annotations

import csv
import io
import json
import sys
from pathlib import Path

import pytest


def _ensure_path() -> None:
    here = Path(__file__).resolve()
    service_dir = here.parents[1]
    repo_root   = here.parents[2]
    for p in (str(service_dir), str(repo_root)):
        if p not in sys.path:
            sys.path.insert(0, p)


_ensure_path()

from app.tools import build_wfirma_pz_csv as csvbld   # noqa: E402


def _payload() -> dict:
    return {
        "invoice_no": "EJL/26-27/013",
        "supplier": "ESTRELLA JEWELS LLP.",
        "currency": "PLN",
        "rows": [
            {
                "product_code": "EJL/26-27/013-1",
                "name": "Wisiorek ze złota próby 750 / 18KT Gold Plain Jewellery Pendant",
                "quantity": 5,
                "unit": "szt.",
                "net_price_pln": 85.97,
            },
            {
                "product_code": "EJL/26-27/013-2",
                "name": "Pierścionek ze złota próby 750 / 18KT Gold Plain Jewellery Ring",
                "quantity": 1,
                "unit": "szt.",
                "net_price_pln": 2112.31,
            },
        ],
        "totals": {"net_pln": 2542.16, "vat_rate": 23},
    }


# ── Column spec ───────────────────────────────────────────────────────────────

def test_column_spec_locked():
    assert csvbld.CSV_COLUMNS == (
        "Nazwa", "PKWiU", "Jednostka", "Ilość", "Cena", "Stawka",
        "Szczegółowy opis", "Rodzaj ceny", "Kod produktu", "Typ", "Kod EAN",
    )
    assert len(csvbld.CSV_COLUMNS) == 11
    assert csvbld.CSV_SEPARATOR == ";"
    assert csvbld.DEFAULT_UNIT == "szt."
    assert csvbld.DEFAULT_VAT == "23%"
    assert csvbld.DEFAULT_PRICE_TYPE == "netto"
    assert csvbld.DEFAULT_TYPE == "towar"


# ── PL formatting ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("v,expected", [
    (70.41,    "70,41"),
    (85.97,    "85,97"),
    (2112.31,  "2112,31"),
    (28879.62, "28879,62"),
    (0.10,     "0,10"),
])
def test_pl_decimal_uses_comma(v, expected):
    assert csvbld._pl_decimal(v, 2) == expected


@pytest.mark.parametrize("v,expected", [
    (1, "1"), (5, "5"), (21, "21"),
    (1.0, "1"), (5.5, "5,5"), (1.25, "1,25"),
])
def test_pl_qty_integers_stay_clean(v, expected):
    assert csvbld._pl_qty(v) == expected


# ── Validation ────────────────────────────────────────────────────────────────

def test_valid_payload_passes():
    v = csvbld.validate(_payload())
    assert v.ok is True
    assert v.blockers == []


def test_missing_product_code_blocks():
    d = _payload(); d["rows"][0]["product_code"] = ""
    v = csvbld.validate(d)
    assert v.ok is False
    assert any("product_code MISSING" in b for b in v.blockers)


def test_duplicate_product_code_blocks():
    d = _payload(); d["rows"][1]["product_code"] = d["rows"][0]["product_code"]
    v = csvbld.validate(d)
    assert v.ok is False
    assert any("duplicate product_code" in b for b in v.blockers)


def test_zero_qty_or_price_blocks():
    d = _payload(); d["rows"][0]["quantity"] = 0
    assert any("quantity must be > 0" in b for b in csvbld.validate(d).blockers)
    d = _payload(); d["rows"][0]["net_price_pln"] = 0
    assert any("net_price_pln must be > 0" in b for b in csvbld.validate(d).blockers)


def test_empty_name_blocks():
    d = _payload(); d["rows"][0]["name"] = ""
    v = csvbld.validate(d)
    assert v.ok is False
    assert any("name is empty" in b for b in v.blockers)


def test_empty_rows_blocks():
    d = _payload(); d["rows"] = []
    assert csvbld.validate(d).ok is False


# ── CSV row building ──────────────────────────────────────────────────────────

def test_each_row_has_exactly_11_columns():
    rows = csvbld.build_csv_rows(_payload())
    for r in rows:
        assert len(r) == 11


def test_column_values_match_spec():
    rows = csvbld.build_csv_rows(_payload())
    r0 = rows[0]
    assert r0[0] == "Wisiorek ze złota próby 750 / 18KT Gold Plain Jewellery Pendant"  # Nazwa
    assert r0[1] == ""                       # PKWiU
    assert r0[2] == "szt."                   # Jednostka
    assert r0[3] == "5"                      # Ilość
    assert r0[4] == "85,97"                  # Cena (PL comma decimal)
    assert r0[5] == "23%"                    # Stawka
    assert r0[6] == "EJL/26-27/013-1"        # Szczegółowy opis = product_code
    assert r0[7] == "netto"                  # Rodzaj ceny
    assert r0[8] == "EJL/26-27/013-1"        # Kod produktu
    assert r0[9] == "towar"                  # Typ
    assert r0[10] == ""                      # Kod EAN


def test_kod_produktu_equals_szczegolowy_opis():
    rows = csvbld.build_csv_rows(_payload())
    for r in rows:
        assert r[6] == r[8], "Szczegółowy opis must equal Kod produktu (the product_code)"


# ── CSV rendering ─────────────────────────────────────────────────────────────

def test_render_uses_semicolon_no_header():
    rows = csvbld.build_csv_rows(_payload())
    text = csvbld.render_csv(rows)
    # No header
    assert not text.startswith("Nazwa;")
    # First row begins with the first product's Nazwa
    assert text.startswith("Wisiorek ze złota")
    # Each line has 10 separators (= 11 columns)
    for line in text.splitlines():
        assert line.count(";") >= 10, f"line={line!r} has too few semicolons"


def test_render_round_trips_through_csv_reader():
    rows = csvbld.build_csv_rows(_payload())
    text = csvbld.render_csv(rows)
    parsed = list(csv.reader(io.StringIO(text), delimiter=";"))
    assert parsed == rows


# ── File output ───────────────────────────────────────────────────────────────

def test_write_csv_creates_file_with_bom(tmp_path: Path):
    rows = csvbld.build_csv_rows(_payload())
    out = tmp_path / "test.csv"
    csvbld.write_csv(out, rows)
    raw = out.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf"), "UTF-8 BOM missing"


def test_write_csv_line_endings_not_doubled(tmp_path: Path):
    # render_csv emits explicit \r\n terminators. write_csv must preserve them
    # exactly on disk — never the doubled \r\r\n that Path.write_text produces in
    # text mode on Windows. A doubled terminator splits each row into an extra
    # blank line on read-back and corrupts the wFirma import.
    rows = csvbld.build_csv_rows(_payload())
    out = tmp_path / "endings.csv"
    csvbld.write_csv(out, rows)
    raw = out.read_bytes()
    assert b"\r\r\n" not in raw
    lines = out.read_text(encoding=csvbld.CSV_ENCODING).splitlines()
    assert len(lines) == len(rows)            # no blank separator lines


def test_build_for_file_writes_csv_and_returns_path(tmp_path: Path):
    src = tmp_path / "PZ_READY_test.json"
    src.write_text(json.dumps(_payload()), encoding="utf-8")
    out_dir = tmp_path / "outputs"
    val, out_path, rows = csvbld.build_for_file(src, out_dir)
    assert val.ok
    assert out_path is not None and out_path.is_file()
    assert out_path.name == "wfirma_pz_csv_EJL-26-27-013.csv"
    assert len(rows) == 2


def test_build_for_file_skips_csv_on_blockers(tmp_path: Path):
    bad = _payload(); bad["rows"][0]["product_code"] = ""
    src = tmp_path / "PZ_READY_bad.json"
    src.write_text(json.dumps(bad), encoding="utf-8")
    out_dir = tmp_path / "outputs"
    val, out_path, rows = csvbld.build_for_file(src, out_dir)
    assert val.ok is False
    assert out_path is None
    assert rows == []


# ── Runbook + ticket ──────────────────────────────────────────────────────────

def test_write_runbook_includes_files(tmp_path: Path):
    rb = tmp_path / "runbook.md"
    csvbld.write_runbook(rb, [tmp_path / "a.csv", tmp_path / "b.csv"])
    text = rb.read_text(encoding="utf-8")
    assert "Magazyn → Towary → Importuj z pliku" in text
    assert "a.csv" in text and "b.csv" in text


def test_write_support_ticket_mentions_pz_endpoint(tmp_path: Path):
    out = tmp_path / "ticket.txt"
    csvbld.write_support_ticket(out)
    text = out.read_text(encoding="utf-8")
    assert "warehouse_document_p_z/add" in text
    assert "INPUT ERROR" in text
    assert "ESTRELLA JEWELS" in text


# ── Real PZ_READY round-trip (if files present) ───────────────────────────────

@pytest.mark.parametrize("fname", [
    "PZ_READY_EJL-26-27-013.json",
    "PZ_READY_EJL-26-27-014.json",
    "PZ_READY_EJL-26-27-015.json",
])
def test_real_pz_ready_files_validate_and_build(tmp_path: Path, fname: str):
    repo = Path(__file__).resolve().parents[2]
    src = repo / fname
    if not src.is_file():
        pytest.skip(f"{fname} not present")
    val, out_path, rows = csvbld.build_for_file(src, tmp_path)
    assert val.ok, f"{fname}: blockers={val.blockers}"
    assert out_path and out_path.is_file()
    # Expected row counts
    expected = {"013": 3, "014": 1, "015": 10}
    for k, n in expected.items():
        if k in fname:
            assert len(rows) == n
            break
    # All rows have exactly 11 columns
    for r in rows:
        assert len(r) == 11
