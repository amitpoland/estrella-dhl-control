"""
test_freight_resolver.py — unit tests for the freight resolver + DB.

NEVER hits wFirma. wfirma_search is fully injected.
DB uses tmp_path so each test starts with a fresh SQLite file.
"""
from __future__ import annotations

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Optional
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

from app.services.freight_history_db import (   # noqa: E402
    FreightRecord, get_latest_freight, init_db, list_freight_history, save_freight_history,
)
from app.services.freight_resolver import (     # noqa: E402
    FREIGHT_KEYWORDS, FREIGHT_SERVICE_ID_DEFAULT,
    FreightUnresolved, ResolvedFreight,
    _is_freight_line, find_freight_in_wfirma, resolve_freight,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_resolved(amount=Decimal("75.00"),
                   source_type="invoice",
                   contractor_id="38582303",
                   currency="USD",
                   doc_no="EXPORT 1/2020/EX",
                   doc_date="2020-05-27") -> ResolvedFreight:
    return ResolvedFreight(
        amount             = amount,
        source_type        = source_type,
        source_doc_id      = "12345",
        source_doc_number  = doc_no,
        source_doc_date    = doc_date,
        contractor_id      = contractor_id,
        contractor_name    = "Scandinavian Diamond",
        country            = "NO",
        currency           = currency,
        freight_service_id = FREIGHT_SERVICE_ID_DEFAULT,
    )


# ── DB module ────────────────────────────────────────────────────────────────

def test_init_db_creates_table_idempotent(tmp_path: Path):
    db = tmp_path / "freight.sqlite"
    init_db(db)
    init_db(db)   # second call must not crash
    assert db.is_file()


def test_save_and_get_round_trip(tmp_path: Path):
    db = tmp_path / "f.db"
    init_db(db)
    rec = FreightRecord(
        contractor_id      = "38582303",
        contractor_name    = "Scandinavian Diamond",
        country            = "NO",
        currency           = "USD",
        freight_service_id = "13002743",
        freight_amount     = Decimal("75.00"),
        source_type        = "invoice",
        source_doc_id      = "33365789",
        source_doc_number  = "EXPORT 1/2020/EX",
        source_doc_date    = "2020-05-27",
    )
    new_id = save_freight_history(db, rec)
    assert new_id > 0

    got = get_latest_freight(db, "38582303", "USD")
    assert got is not None
    assert got.freight_amount == Decimal("75.00")
    assert got.source_type    == "invoice"
    assert got.country        == "NO"


def test_get_latest_returns_most_recent(tmp_path: Path):
    db = tmp_path / "f.db"
    init_db(db)
    base = FreightRecord(
        contractor_id="X", contractor_name="C", country="NO", currency="USD",
        freight_service_id="13002743",
        freight_amount=Decimal("70.00"), source_type="invoice",
    )
    save_freight_history(db, base)
    save_freight_history(db, FreightRecord(
        contractor_id="X", contractor_name="C", country="NO", currency="USD",
        freight_service_id="13002743",
        freight_amount=Decimal("85.00"), source_type="manual",
    ))
    latest = get_latest_freight(db, "X", "USD")
    assert latest.freight_amount == Decimal("85.00")
    assert latest.source_type    == "manual"


def test_get_latest_returns_none_for_unknown(tmp_path: Path):
    db = tmp_path / "f.db"
    init_db(db)
    assert get_latest_freight(db, "UNKNOWN", "USD") is None


def test_get_latest_currency_specific(tmp_path: Path):
    db = tmp_path / "f.db"
    init_db(db)
    save_freight_history(db, FreightRecord(
        contractor_id="X", contractor_name="C", country="DE", currency="USD",
        freight_service_id="13002743",
        freight_amount=Decimal("80.00"), source_type="invoice",
    ))
    save_freight_history(db, FreightRecord(
        contractor_id="X", contractor_name="C", country="DE", currency="EUR",
        freight_service_id="13002743",
        freight_amount=Decimal("85.00"), source_type="invoice",
    ))
    assert get_latest_freight(db, "X", "USD").freight_amount == Decimal("80.00")
    assert get_latest_freight(db, "X", "EUR").freight_amount == Decimal("85.00")


def test_get_latest_returns_none_for_missing_db_file(tmp_path: Path):
    db = tmp_path / "does_not_exist.db"
    assert get_latest_freight(db, "X", "USD") is None


@pytest.mark.parametrize("bad_source", ["", "unknown", "INVOICE_lower_check_required"])
def test_save_rejects_invalid_source_type(tmp_path: Path, bad_source: str):
    db = tmp_path / "f.db"
    init_db(db)
    with pytest.raises(ValueError, match="source_type must be"):
        save_freight_history(db, FreightRecord(
            contractor_id="X", contractor_name="C", country="X", currency="USD",
            freight_service_id="13002743",
            freight_amount=Decimal("10"),
            source_type=bad_source,
        ))


def test_save_rejects_zero_or_negative_amount(tmp_path: Path):
    db = tmp_path / "f.db"
    init_db(db)
    for bad in (Decimal("0"), Decimal("-1")):
        with pytest.raises(ValueError, match="freight_amount must be > 0"):
            save_freight_history(db, FreightRecord(
                contractor_id="X", contractor_name="C", country="X", currency="USD",
                freight_service_id="13002743",
                freight_amount=bad, source_type="invoice",
            ))


def test_list_freight_history_orders_newest_first(tmp_path: Path):
    db = tmp_path / "f.db"
    init_db(db)
    for amt in ("60", "70", "85"):
        save_freight_history(db, FreightRecord(
            contractor_id="X", contractor_name="C", country="X", currency="USD",
            freight_service_id="13002743",
            freight_amount=Decimal(amt), source_type="invoice",
        ))
    rows = list_freight_history(db, contractor_id="X", currency="USD")
    assert [r.freight_amount for r in rows] == [Decimal("85"), Decimal("70"), Decimal("60")]


# ── Freight line classifier ──────────────────────────────────────────────────

def test_is_freight_line_by_good_id():
    assert _is_freight_line("13002743", "Some line name", "13002743") is True
    assert _is_freight_line("99999",    "Some line name", "13002743") is False


@pytest.mark.parametrize("name", [
    "Fedex Courier", "DHL Express", "Freight charge", "Shipping cost",
    "Fracht morski", "International courier",
])
def test_is_freight_line_by_name_keyword(name):
    assert _is_freight_line("99999", name, "13002743") is True


def test_is_freight_line_negative():
    assert _is_freight_line("99999", "14KT Gold Ring", "13002743") is False


# ── Resolver — manual override ────────────────────────────────────────────────

def test_manual_override_uses_arg_and_saves_to_db(tmp_path: Path):
    db = tmp_path / "f.db"
    res = resolve_freight(
        db, "38582303", "USD",
        manual_amount    = Decimal("100"),
        contractor_name  = "Scandinavian Diamond",
        country          = "NO",
        wfirma_search    = lambda *a, **k: pytest.fail("must not call wFirma when manual is given"),
    )
    assert res.amount      == Decimal("100")
    assert res.source_type == "manual"

    # Saved to DB
    saved = get_latest_freight(db, "38582303", "USD")
    assert saved is not None
    assert saved.freight_amount == Decimal("100")
    assert saved.source_type    == "manual"


def test_manual_override_zero_or_negative_blocks(tmp_path: Path):
    db = tmp_path / "f.db"
    for bad in (Decimal("0"), Decimal("-1")):
        with pytest.raises(ValueError, match="manual_amount must be > 0"):
            resolve_freight(db, "X", "USD", manual_amount=bad,
                            wfirma_search=lambda *a, **k: None)


# ── Resolver — DB hit (no API call) ──────────────────────────────────────────

def test_db_hit_returns_without_api_call(tmp_path: Path):
    db = tmp_path / "f.db"
    init_db(db)
    save_freight_history(db, FreightRecord(
        contractor_id="38582303", contractor_name="SD", country="NO", currency="USD",
        freight_service_id="13002743",
        freight_amount=Decimal("75"), source_type="invoice",
        source_doc_number="EXPORT 1/2020/EX", source_doc_date="2020-05-27",
    ))
    api_calls = []
    def stub_search(*a, **k): api_calls.append(a); return None
    res = resolve_freight(db, "38582303", "USD", wfirma_search=stub_search)
    assert res.amount      == Decimal("75")
    assert res.source_type == "db"
    assert res.source_doc_number == "EXPORT 1/2020/EX"
    assert api_calls == []


# ── Resolver — invoice preferred over proforma ───────────────────────────────

def test_invoice_history_preferred_over_proforma(tmp_path: Path):
    db = tmp_path / "f.db"
    invoice_called = []
    proforma_called = []

    def stub_search(contractor_id, currency, doc_type):
        if doc_type == "normal":
            invoice_called.append(1)
            return _make_resolved(amount=Decimal("85"), source_type="invoice",
                                  doc_no="EXPORT 99/2024", doc_date="2024-09-09")
        else:
            proforma_called.append(1)
            return _make_resolved(amount=Decimal("70"), source_type="proforma",
                                  doc_no="PROF 1/2025", doc_date="2025-01-01")

    res = resolve_freight(db, "38582303", "USD",
                          contractor_name="SD", country="NO",
                          wfirma_search=stub_search)
    assert res.amount      == Decimal("85")
    assert res.source_type == "invoice"
    assert invoice_called  == [1]
    assert proforma_called == []   # never reached because invoice was found

    # Also persisted to DB
    saved = get_latest_freight(db, "38582303", "USD")
    assert saved.freight_amount == Decimal("85")
    assert saved.source_type    == "invoice"


def test_proforma_used_if_invoice_absent(tmp_path: Path):
    db = tmp_path / "f.db"
    def stub_search(contractor_id, currency, doc_type):
        if doc_type == "normal":
            return None    # no invoice
        return _make_resolved(amount=Decimal("70"), source_type="proforma",
                              doc_no="PROF 1/2025", doc_date="2025-01-01")
    res = resolve_freight(db, "38582303", "USD",
                          contractor_name="SD", country="NO",
                          wfirma_search=stub_search)
    assert res.amount      == Decimal("70")
    assert res.source_type == "proforma"


def test_missing_history_blocks(tmp_path: Path):
    db = tmp_path / "f.db"
    with pytest.raises(FreightUnresolved) as exc:
        resolve_freight(db, "X", "USD",
                        wfirma_search=lambda *a, **k: None)
    assert exc.value.contractor_id == "X"
    assert exc.value.currency      == "USD"


def test_currency_specific_lookup(tmp_path: Path):
    """USD lookup returns USD record; EUR lookup returns EUR record; never crosses."""
    db = tmp_path / "f.db"
    init_db(db)
    save_freight_history(db, FreightRecord(
        contractor_id="X", contractor_name="C", country="DE", currency="USD",
        freight_service_id="13002743",
        freight_amount=Decimal("85"), source_type="invoice",
    ))
    save_freight_history(db, FreightRecord(
        contractor_id="X", contractor_name="C", country="DE", currency="EUR",
        freight_service_id="13002743",
        freight_amount=Decimal("84"), source_type="invoice",
    ))
    api_calls = []
    def stub(*a, **k): api_calls.append(a); return None

    usd = resolve_freight(db, "X", "USD", wfirma_search=stub)
    eur = resolve_freight(db, "X", "EUR", wfirma_search=stub)
    assert usd.amount == Decimal("85")
    assert eur.amount == Decimal("84")
    assert api_calls == []


def test_manual_override_beats_existing_db_value(tmp_path: Path):
    db = tmp_path / "f.db"
    init_db(db)
    save_freight_history(db, FreightRecord(
        contractor_id="X", contractor_name="C", country="DE", currency="EUR",
        freight_service_id="13002743",
        freight_amount=Decimal("80"), source_type="invoice",
    ))
    res = resolve_freight(db, "X", "EUR",
                          manual_amount=Decimal("125"),
                          contractor_name="C", country="DE",
                          wfirma_search=lambda *a, **k: None)
    assert res.amount      == Decimal("125")
    assert res.source_type == "manual"
    # Subsequent lookup gets the manual value (most recent)
    next_call = resolve_freight(db, "X", "EUR",
                                wfirma_search=lambda *a, **k: pytest.fail("unreachable"))
    assert next_call.amount      == Decimal("125")
    assert next_call.source_type == "db"     # came from DB cache, originally manual


def test_history_value_persisted_for_next_call(tmp_path: Path):
    db = tmp_path / "f.db"
    invoice_calls = []
    def stub(contractor_id, currency, doc_type):
        if doc_type == "normal":
            invoice_calls.append(1)
            return _make_resolved(amount=Decimal("85"))
        return None

    # First call: hits invoice search, saves to DB
    r1 = resolve_freight(db, "X", "USD", contractor_name="C", country="DE",
                         wfirma_search=stub)
    assert r1.source_type == "invoice"
    assert len(invoice_calls) == 1

    # Second call: hits DB, no API call
    r2 = resolve_freight(db, "X", "USD",
                         wfirma_search=lambda *a, **k: pytest.fail("must not search"))
    assert r2.source_type == "db"
    assert r2.amount      == Decimal("85")
    assert len(invoice_calls) == 1   # unchanged — no second call


# ── find_freight_in_wfirma — HTTP fully mocked ───────────────────────────────

def _wfirma_response_with_freight(freight_price="85.00", currency="USD",
                                   doc_no="EXPORT 1/2020/EX", inv_date="2020-05-27",
                                   good_id="13002743", line_name="Fedex Courier"):
    return f"""<?xml version="1.0"?>
<api>
  <invoices>
    <invoice>
      <id>9999</id>
      <fullnumber>{doc_no}</fullnumber>
      <date>{inv_date}</date>
      <currency>{currency}</currency>
      <contractor_detail>
        <name>Test Contractor</name>
        <country>NO</country>
      </contractor_detail>
      <invoicecontents>
        <invoicecontent>
          <name>14KT Gold Ring</name>
          <good><id>1234</id></good>
          <unit_count>1.0000</unit_count>
          <price>500.00</price>
          <vat_code><id>229</id></vat_code>
        </invoicecontent>
        <invoicecontent>
          <name>{line_name}</name>
          <good><id>{good_id}</id></good>
          <unit_count>1.0000</unit_count>
          <price>{freight_price}</price>
          <vat_code><id>229</id></vat_code>
        </invoicecontent>
      </invoicecontents>
    </invoice>
  </invoices>
  <status><code>OK</code></status>
</api>"""


def test_find_freight_in_wfirma_extracts_freight_line():
    from app.services import wfirma_client as wfc
    body = _wfirma_response_with_freight(freight_price="85.00", doc_no="EXPORT 99/2024")

    def fake_http(method, module, action, body_xml=""):
        return 200, body

    with patch.object(wfc, "_http_request", side_effect=fake_http):
        match = find_freight_in_wfirma("X", "USD", "normal")
    assert match is not None
    assert match.amount             == Decimal("85.00")
    assert match.source_type        == "invoice"
    assert match.source_doc_number  == "EXPORT 99/2024"
    assert match.source_doc_date    == "2020-05-27"
    assert match.country            == "NO"
    assert match.contractor_name    == "Test Contractor"
    assert match.freight_service_id == "13002743"


def test_find_freight_in_wfirma_returns_none_when_no_freight_line():
    from app.services import wfirma_client as wfc
    body = """<?xml version="1.0"?>
<api>
  <invoices>
    <invoice>
      <id>1</id>
      <fullnumber>X</fullnumber>
      <date>2024-01-01</date>
      <currency>USD</currency>
      <invoicecontents>
        <invoicecontent>
          <name>14KT Gold Ring</name>
          <good><id>1234</id></good>
          <price>500.00</price>
        </invoicecontent>
      </invoicecontents>
    </invoice>
  </invoices>
  <status><code>OK</code></status>
</api>"""
    with patch.object(wfc, "_http_request", return_value=(200, body)):
        match = find_freight_in_wfirma("X", "USD", "normal")
    assert match is None


def test_find_freight_in_wfirma_doc_type_distinction():
    """Confirm we actually filter by doc_type — proforma sources match by name."""
    from app.services import wfirma_client as wfc
    body = _wfirma_response_with_freight(doc_no="PROF 1/2025")
    with patch.object(wfc, "_http_request", return_value=(200, body)):
        match = find_freight_in_wfirma("X", "USD", "proforma")
    assert match is not None
    assert match.source_type == "proforma"


def test_find_freight_raises_on_http_error():
    from app.services import wfirma_client as wfc
    with patch.object(wfc, "_http_request", return_value=(500, "<server-error>")):
        with pytest.raises(ConnectionError, match="HTTP 500"):
            find_freight_in_wfirma("X", "USD", "normal")


def test_find_freight_in_wfirma_classifies_by_keyword_when_good_id_differs():
    """Operator may have entered a freight line with a different service id;
    keyword in the line name should still classify it as freight."""
    from app.services import wfirma_client as wfc
    body = _wfirma_response_with_freight(good_id="9999", line_name="DHL Express International")
    with patch.object(wfc, "_http_request", return_value=(200, body)):
        match = find_freight_in_wfirma("X", "USD", "normal")
    assert match is not None
    assert match.amount == Decimal("85.00")
