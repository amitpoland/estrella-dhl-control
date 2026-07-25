"""
test_customer_invoice_snapshot.py — DB + sync tool tests.

NEVER hits wFirma. Fetcher is fully injected.
DB uses tmp_path so each test starts fresh.
"""
from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import List
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

from app.services.customer_invoice_snapshot_db import (   # noqa: E402
    InvoiceLineRow, InvoiceSnapshotRow, ProfileSnapshotRow,
    get_invoice_by_invoice_id, get_profile, init_db,
    list_distinct_contractors, list_invoices, list_profiles,
    upsert_invoice_with_lines, upsert_profile,
)
from app.tools.sync_customer_invoice_snapshot import (   # noqa: E402
    CONF_CONSISTENT_RECENT, CONF_EMPTY, CONF_SINGLE_DOC, CONF_STALE_LOW, CONF_VARYING,
    FREIGHT_SERVICE_ID, INSURANCE_SERVICE_ID,
    INVOICE_TYPES_SYNCED,
    classify_line, fetch_invoices_from_wfirma,
    main, parse_invoice_element, resolve_window, sync,
)


# ── XML fixtures ──────────────────────────────────────────────────────────────

def _xml_invoice(invoice_id="100",
                 fullnumber="WDT 1/2024",
                 invoice_date="2025-12-15",
                 invoice_type_text="WDT",
                 contractor_id="38533544",
                 contractor_name="NEXT GENERATION",
                 country="CZ", nip="CZ12345",
                 currency="USD",
                 series="15827921",
                 lang="1",
                 receiver_id="0",
                 description="",
                 lines_xml=""):
    return f"""
    <invoice>
      <id>{invoice_id}</id>
      <fullnumber>{fullnumber}</fullnumber>
      <date>{invoice_date}</date>
      <type>{invoice_type_text}</type>
      <currency>{currency}</currency>
      <netto>10000.00</netto>
      <brutto>10000.00</brutto>
      <translation_language><id>{lang}</id></translation_language>
      <series><id>{series}</id></series>
      <contractor><id>{contractor_id}</id></contractor>
      <contractor_detail>
        <name>{contractor_name}</name>
        <country>{country}</country>
        <nip>{nip}</nip>
      </contractor_detail>
      <contractor_receiver><id>{receiver_id}</id></contractor_receiver>
      <description>{description}</description>
      <invoicecontents>
        {lines_xml}
      </invoicecontents>
    </invoice>"""


def _xml_line(name="14KT Gold Ring", good_id="48462051",
              qty="1.0000", price="500.00", vat="228",
              netto="500.00", brutto="500.00",
              unit_text="szt."):
    return f"""
    <invoicecontent>
      <name>{name}</name>
      <good><id>{good_id}</id></good>
      <unit_count>{qty}</unit_count>
      <price>{price}</price>
      <unit>{unit_text}</unit>
      <netto>{netto}</netto>
      <brutto>{brutto}</brutto>
      <vat_code><id>{vat}</id></vat_code>
    </invoicecontent>"""


def _wrap(invoice_xml_pieces: list) -> ET.Element:
    """Wrap raw <invoice> XML pieces into a parseable root."""
    return ET.fromstring(f"<api><invoices>{''.join(invoice_xml_pieces)}</invoices></api>")


# ── Date window ──────────────────────────────────────────────────────────────

def test_resolve_window_default_6_months():
    today = date(2026, 5, 3)
    f, t = resolve_window(today=today)
    assert t == "2026-05-03"
    # 6 * 31 = 186 days back ≈ 2025-10-29 (not exactly 2025-11-03 because we use 31-day months)
    # Locking the actual computed value here.
    assert f == "2025-10-29"


def test_resolve_window_explicit_dates_override():
    f, t = resolve_window(date_from="2025-11-03", date_to="2026-05-03",
                          today=date(2026, 5, 3))
    assert (f, t) == ("2025-11-03", "2026-05-03")


def test_resolve_window_zero_or_negative_months_blocks():
    with pytest.raises(ValueError):
        resolve_window(months=0)
    with pytest.raises(ValueError):
        resolve_window(months=-1)


# ── Line classifier ──────────────────────────────────────────────────────────

def test_classify_freight_by_good_id():
    assert classify_line("Some line", FREIGHT_SERVICE_ID) == "freight"


def test_classify_insurance_by_good_id():
    assert classify_line("Some line", INSURANCE_SERVICE_ID) == "insurance"


@pytest.mark.parametrize("name", ["Fedex Courier", "DHL Express", "Freight charge", "Shipping"])
def test_classify_freight_by_keyword(name):
    assert classify_line(name, "9999") == "freight"


@pytest.mark.parametrize("name", ["Insurance covers...", "Ubezpieczenie xx"])
def test_classify_insurance_by_keyword(name):
    assert classify_line(name, "9999") == "insurance"


@pytest.mark.parametrize("name", ["14KT Gold Ring", "Pierścionek złoty", "EJL/26-27/015-3"])
def test_classify_product(name):
    assert classify_line(name, "12345") == "product"


def test_classify_other_falls_to_service():
    assert classify_line("Mystery service charge", "9999") == "service"


# ── parse_invoice_element ────────────────────────────────────────────────────

def test_parse_invoice_basic_header():
    invs = [_xml_invoice(lines_xml=_xml_line())]
    root = _wrap(invs)
    inv_el = root.find("invoices/invoice")
    row = parse_invoice_element(inv_el)
    assert row is not None
    assert row.invoice_id     == "100"
    assert row.contractor_id  == "38533544"
    assert row.invoice_type   == "normal"     # type=WDT → mapped to normal
    assert row.currency       == "USD"
    assert row.country        == "CZ"
    assert row.translation_language_id == "1"
    assert row.series_id      == "15827921"
    assert row.contractor_receiver_id  == "0"
    assert row.vat_codes_used == "228"
    assert len(row.lines)     == 1


def test_parse_invoice_marks_correction():
    invs = [_xml_invoice(invoice_type_text="KOREKTA", lines_xml=_xml_line())]
    row = parse_invoice_element(_wrap(invs).find("invoices/invoice"))
    assert row.invoice_type == "correction"


def test_parse_invoice_marks_proforma():
    invs = [_xml_invoice(invoice_type_text="PROFORMA", lines_xml=_xml_line())]
    row = parse_invoice_element(_wrap(invs).find("invoices/invoice"))
    assert row.invoice_type == "proforma"


def test_parse_invoice_lines_classified_correctly():
    lines_xml = (
        _xml_line(name="14KT Gold Ring", good_id="48462051", price="500.00")
        + _xml_line(name="Fedex Courier",   good_id=FREIGHT_SERVICE_ID,   price="85.00")
        + _xml_line(name="Insurance...",    good_id=INSURANCE_SERVICE_ID, price="20.00")
    )
    row = parse_invoice_element(_wrap([_xml_invoice(lines_xml=lines_xml)]).find("invoices/invoice"))
    types = [ln.line_type for ln in row.lines]
    assert types == ["product", "freight", "insurance"]


def test_parse_invoice_returns_none_for_missing_id():
    inv_el = ET.fromstring("<invoice><id></id></invoice>")
    assert parse_invoice_element(inv_el) is None


# ── DB CRUD ──────────────────────────────────────────────────────────────────

def test_init_db_creates_all_tables(tmp_path: Path):
    db = tmp_path / "snap.db"
    init_db(db)
    init_db(db)   # idempotent
    assert db.is_file()


def test_upsert_invoice_inserts_then_updates(tmp_path: Path):
    db = tmp_path / "snap.db"
    row = InvoiceSnapshotRow(
        invoice_id="100", contractor_id="38533544",
        invoice_type="normal", invoice_date="2026-01-01",
        currency="USD", series_id="15827921",
        translation_language_id="1", vat_codes_used="228",
        contractor_receiver_id="0",
        total_net=Decimal("500"), total_gross=Decimal("500"),
        lines=(InvoiceLineRow(line_type="product", price=Decimal("500"), qty=Decimal("1")),
               InvoiceLineRow(line_type="freight", price=Decimal("85"), qty=Decimal("1"))),
    )
    sid_1 = upsert_invoice_with_lines(db, row)
    sid_2 = upsert_invoice_with_lines(db, row)   # rerun must update, not duplicate
    assert sid_1 == sid_2

    got = get_invoice_by_invoice_id(db, "100")
    assert got is not None
    assert got.invoice_id == "100"
    assert len(got.lines) == 2
    assert got.lines[0].price == Decimal("500")


def test_upsert_invoice_replaces_lines_on_update(tmp_path: Path):
    db = tmp_path / "snap.db"
    base = InvoiceSnapshotRow(
        invoice_id="200", contractor_id="X",
        invoice_type="normal",
        lines=(InvoiceLineRow(line_type="product", price=Decimal("1")),),
    )
    upsert_invoice_with_lines(db, base)
    # Now update with completely different lines
    new = InvoiceSnapshotRow(
        invoice_id="200", contractor_id="X",
        invoice_type="normal",
        lines=(
            InvoiceLineRow(line_type="freight",   price=Decimal("85")),
            InvoiceLineRow(line_type="insurance", price=Decimal("20")),
        ),
    )
    upsert_invoice_with_lines(db, new)
    got = get_invoice_by_invoice_id(db, "200")
    assert len(got.lines) == 2
    types = sorted(ln.line_type for ln in got.lines)
    assert types == ["freight", "insurance"]


def test_list_invoices_filters(tmp_path: Path):
    db = tmp_path / "snap.db"
    upsert_invoice_with_lines(db, InvoiceSnapshotRow(
        invoice_id="A", contractor_id="C1", invoice_type="normal",
        invoice_date="2025-12-15"))
    upsert_invoice_with_lines(db, InvoiceSnapshotRow(
        invoice_id="B", contractor_id="C1", invoice_type="correction",
        invoice_date="2026-01-15"))
    upsert_invoice_with_lines(db, InvoiceSnapshotRow(
        invoice_id="C", contractor_id="C2", invoice_type="normal",
        invoice_date="2025-10-01"))
    only_c1 = list_invoices(db, contractor_id="C1")
    assert {r.invoice_id for r in only_c1} == {"A", "B"}
    only_normal = list_invoices(db, invoice_type="normal")
    assert {r.invoice_id for r in only_normal} == {"A", "C"}
    only_window = list_invoices(db, date_from="2025-11-01", date_to="2026-12-31")
    assert {r.invoice_id for r in only_window} == {"A", "B"}


def test_list_distinct_contractors(tmp_path: Path):
    db = tmp_path / "snap.db"
    for inv_id, cid, typ in [("A","C1","normal"),("B","C1","correction"),
                              ("C","C2","normal"),("D","C3","proforma")]:
        upsert_invoice_with_lines(db, InvoiceSnapshotRow(
            invoice_id=inv_id, contractor_id=cid, invoice_type=typ,
            invoice_date="2026-01-01"))
    assert sorted(list_distinct_contractors(db, invoice_type="normal")) == ["C1","C2"]


def test_upsert_profile_inserts_and_updates(tmp_path: Path):
    db = tmp_path / "snap.db"
    p1 = ProfileSnapshotRow(contractor_id="X", invoice_count=3, vat_mode=228,
                            preferred_currency="USD", confidence_state="CONSISTENT_RECENT")
    upsert_profile(db, p1)
    upsert_profile(db, p1)   # idempotent
    assert get_profile(db, "X").invoice_count == 3
    p2 = ProfileSnapshotRow(contractor_id="X", invoice_count=5, vat_mode=228,
                            preferred_currency="EUR", confidence_state="VARYING")
    upsert_profile(db, p2)
    after = get_profile(db, "X")
    assert after.invoice_count       == 5
    assert after.preferred_currency  == "EUR"


# ── Sync orchestrator ────────────────────────────────────────────────────────

def _stub_fetcher_factory(invoices_per_type: dict):
    """Returns a fetcher that maps invoice_type → list of <invoice> Elements."""
    def fetcher(invoice_type, date_from, date_to, only_ids=None, page_size=200):
        xml_pieces = invoices_per_type.get(invoice_type, [])
        return _wrap(xml_pieces).findall("invoices/invoice")
    return fetcher


def test_sync_dry_run_writes_nothing(tmp_path: Path):
    db = tmp_path / "snap.db"
    fetcher = _stub_fetcher_factory({
        "normal":      [_xml_invoice(invoice_id="100", invoice_date="2026-01-15", lines_xml=_xml_line())],
        "correction":  [],
    })
    s = sync(db, period_from="2025-11-03", period_to="2026-05-03",
             dry_run=True, fetcher=fetcher)
    assert s.fetched   == 1
    assert s.inserted  == 1   # would-have-inserted
    assert get_invoice_by_invoice_id(db, "100") is None  # nothing written


def test_sync_inserts_invoices_and_lines(tmp_path: Path):
    db = tmp_path / "snap.db"
    lines = (
        _xml_line(name="EJL/26-27/015-6", good_id="48462371", price="1000")
        + _xml_line(name="Fedex Courier",   good_id=FREIGHT_SERVICE_ID,   price="85")
        + _xml_line(name="Insurance...",    good_id=INSURANCE_SERVICE_ID, price="20")
    )
    fetcher = _stub_fetcher_factory({
        "normal":     [_xml_invoice(invoice_id="100", invoice_date="2026-01-15", lines_xml=lines)],
        "correction": [],
    })
    s = sync(db, period_from="2025-11-03", period_to="2026-05-03", fetcher=fetcher)
    assert s.inserted == 1
    inv = get_invoice_by_invoice_id(db, "100")
    assert inv is not None
    assert len(inv.lines) == 3
    types = [ln.line_type for ln in inv.lines]
    assert "product" in types
    assert "freight" in types
    assert "insurance" in types


def test_sync_excludes_proformas(tmp_path: Path):
    db = tmp_path / "snap.db"
    fetcher = _stub_fetcher_factory({
        "normal": [
            _xml_invoice(invoice_id="100", invoice_type_text="WDT",
                         invoice_date="2026-01-15", lines_xml=_xml_line()),
            _xml_invoice(invoice_id="200", invoice_type_text="PROFORMA",
                         invoice_date="2026-01-16", lines_xml=_xml_line()),
        ],
        "correction": [],
    })
    s = sync(db, period_from="2025-11-03", period_to="2026-05-03", fetcher=fetcher)
    assert s.inserted        == 1
    assert s.skipped_proforma == 1
    assert get_invoice_by_invoice_id(db, "100") is not None
    assert get_invoice_by_invoice_id(db, "200") is None


def test_sync_stores_corrections_with_correction_type(tmp_path: Path):
    db = tmp_path / "snap.db"
    fetcher = _stub_fetcher_factory({
        "normal":     [],
        "correction": [_xml_invoice(invoice_id="300", invoice_type_text="KOREKTA",
                                     invoice_date="2026-01-20", lines_xml=_xml_line())],
    })
    s = sync(db, period_from="2025-11-03", period_to="2026-05-03", fetcher=fetcher)
    assert s.inserted == 1
    inv = get_invoice_by_invoice_id(db, "300")
    assert inv.invoice_type == "correction"


def test_sync_idempotent_rerun(tmp_path: Path):
    db = tmp_path / "snap.db"
    fetcher = _stub_fetcher_factory({
        "normal":     [_xml_invoice(invoice_id="100", invoice_date="2026-01-15", lines_xml=_xml_line())],
        "correction": [],
    })
    sync(db, period_from="2025-11-03", period_to="2026-05-03", fetcher=fetcher)
    s2 = sync(db, period_from="2025-11-03", period_to="2026-05-03", fetcher=fetcher)
    assert s2.inserted == 0   # no new
    assert s2.updated  == 1
    rows = list_invoices(db)
    assert len(rows) == 1


def test_sync_filters_invoices_outside_window(tmp_path: Path):
    """Invoices with date outside the requested window are dropped, even if
    wFirma returns them (the API filter for dates is fragile)."""
    db = tmp_path / "snap.db"
    fetcher = _stub_fetcher_factory({
        "normal": [
            _xml_invoice(invoice_id="A", invoice_date="2026-01-15", lines_xml=_xml_line()),
            _xml_invoice(invoice_id="B", invoice_date="2020-05-27", lines_xml=_xml_line()),
            _xml_invoice(invoice_id="C", invoice_date="2026-06-30", lines_xml=_xml_line()),
        ],
        "correction": [],
    })
    s = sync(db, period_from="2025-11-03", period_to="2026-05-03", fetcher=fetcher)
    assert s.inserted        == 1
    assert s.skipped_no_export == 2
    rows = list_invoices(db)
    assert {r.invoice_id for r in rows} == {"A"}


def test_sync_builds_profile_per_contractor(tmp_path: Path):
    db = tmp_path / "snap.db"
    today = date.today()
    recent = (today - timedelta(days=30)).isoformat()
    older  = (today - timedelta(days=60)).isoformat()

    fetcher = _stub_fetcher_factory({
        "normal": [
            _xml_invoice(invoice_id="A",
                         contractor_id="38533544",
                         contractor_name="NGL", country="CZ",
                         currency="USD",
                         series="15827921",
                         lang="1",
                         invoice_date=recent,
                         lines_xml=(
                             _xml_line(name="EJL/X", good_id="48462371", price="500", vat="228")
                             + _xml_line(name="Fedex Courier", good_id=FREIGHT_SERVICE_ID, price="85", vat="228")
                             + _xml_line(name="Insurance...", good_id=INSURANCE_SERVICE_ID, price="20", vat="228")
                         )),
            _xml_invoice(invoice_id="B",
                         contractor_id="38533544",
                         contractor_name="NGL", country="CZ",
                         currency="USD",
                         series="15827921",
                         lang="1",
                         invoice_date=older,
                         lines_xml=(
                             _xml_line(name="EJL/Y", good_id="48462371", price="800", vat="228")
                             + _xml_line(name="Fedex Courier", good_id=FREIGHT_SERVICE_ID, price="85", vat="228")
                             + _xml_line(name="Insurance...", good_id=INSURANCE_SERVICE_ID, price="20", vat="228")
                         )),
        ],
        "correction": [],
    })

    period_from = (today - timedelta(days=180)).isoformat()
    period_to   = today.isoformat()
    s = sync(db, period_from=period_from, period_to=period_to, fetcher=fetcher)
    assert s.profiles_built == 1
    p = get_profile(db, "38533544")
    assert p is not None
    assert p.invoice_count            == 2
    assert p.preferred_currency       == "USD"
    assert p.preferred_language_id    == "1"
    assert p.preferred_invoice_series_id == "15827921"
    assert p.vat_mode                 == 228
    assert p.confidence_state         == CONF_CONSISTENT_RECENT
    assert p.freight_mode             == "fixed"
    assert p.last_freight_amount      == Decimal("85")
    # 80%-formula threshold: 0/2 hit formula → mode='fixed'
    assert p.insurance_mode           == "fixed"
    assert p.ship_to_mode             == "none"


def test_sync_only_filter_passes_through(tmp_path: Path):
    db = tmp_path / "snap.db"
    captured_only = []
    def fetcher(invoice_type, date_from, date_to, only_ids=None, page_size=200):
        captured_only.append(only_ids)
        return []
    sync(db, period_from="2025-11-03", period_to="2026-05-03",
         only_ids=["38582303","38533544"], fetcher=fetcher)
    # Once per invoice type
    assert all(c == ["38582303","38533544"] for c in captured_only)
    assert len(captured_only) == len(INVOICE_TYPES_SYNCED)


def test_sync_handles_fetcher_connection_error(tmp_path: Path, capsys):
    def bad_fetcher(*a, **k): raise ConnectionError("network down")
    s = sync(tmp_path / "snap.db",
             period_from="2025-11-03", period_to="2026-05-03",
             fetcher=bad_fetcher)
    assert s.errors >= 1
    err = capsys.readouterr().err
    assert "network down" in err


# ── CLI ──────────────────────────────────────────────────────────────────────

def test_main_dry_run_returns_zero(tmp_path: Path, capsys):
    fetcher = _stub_fetcher_factory({
        "normal":     [_xml_invoice(invoice_id="100",
                                    invoice_date=date.today().isoformat(),
                                    lines_xml=_xml_line())],
        "correction": [],
    })
    rc = main(argv=["--db", str(tmp_path / "snap.db"), "--dry-run"], fetcher=fetcher)
    out = capsys.readouterr().out
    assert rc == 0
    assert "DRY-RUN" in out
    assert "fetched          : 1" in out


def test_main_explicit_window(tmp_path: Path, capsys):
    fetcher = _stub_fetcher_factory({"normal": [], "correction": []})
    rc = main(argv=["--db", str(tmp_path / "snap.db"),
                     "--from", "2025-11-03", "--to", "2026-05-03"],
              fetcher=fetcher)
    assert rc == 0


def test_main_only_arg_parsed(tmp_path: Path):
    captured_only = []
    def fetcher(invoice_type, date_from, date_to, only_ids=None, page_size=200):
        captured_only.append(only_ids); return []
    rc = main(argv=["--db", str(tmp_path / "snap.db"),
                     "--only", "38582303,38533544"], fetcher=fetcher)
    assert rc == 0
    assert all(c == ["38582303","38533544"] for c in captured_only)


# ── HTTP-mocked live fetcher ─────────────────────────────────────────────────

def test_fetch_invoices_from_wfirma_paginates_and_stops():
    """First page returns full page_size of 2 invoices; second page returns 0 → loop exits."""
    page1 = "<api><invoices>" + _xml_invoice(invoice_id="1", lines_xml=_xml_line()) \
            + _xml_invoice(invoice_id="2", lines_xml=_xml_line()) + "</invoices></api>"
    page2 = "<api><invoices></invoices></api>"
    pages = [page1, page2]
    call_count = [0]
    def fake_http(method, module, action, body=""):
        idx = min(call_count[0], len(pages)-1)
        call_count[0] += 1
        return 200, pages[idx]
    from app.services import wfirma_client as wfc
    with patch.object(wfc, "_http_request", side_effect=fake_http):
        result = fetch_invoices_from_wfirma("normal", "2025-11-03", "2026-05-03",
                                            page_size=2)
    assert len(result) == 2
    assert call_count[0] == 2   # one page filled, second returned empty


def test_fetch_invoices_raises_on_http_error():
    from app.services import wfirma_client as wfc
    with patch.object(wfc, "_http_request", return_value=(500, "<server-error>")):
        with pytest.raises(ConnectionError, match="HTTP 500"):
            fetch_invoices_from_wfirma("normal", "2025-11-03", "2026-05-03")


# ── Layer boundary ───────────────────────────────────────────────────────────

def test_db_module_does_not_import_wfirma_client():
    src = (Path(__file__).resolve().parents[1] / "app" / "services" /
           "customer_invoice_snapshot_db.py").read_text(encoding="utf-8")
    assert "wfirma_client" not in src
