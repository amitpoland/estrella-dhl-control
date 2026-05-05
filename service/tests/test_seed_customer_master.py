"""
test_seed_customer_master.py — unit tests for the wFirma → customer_master seeder.

NEVER hits wFirma. fetcher is fully injected.
DB uses tmp_path so each test starts fresh.
"""
from __future__ import annotations

import sys
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

from app.services.customer_master_db import (   # noqa: E402
    CustomerMaster, get_customer, list_customers, upsert_customer,
)
from app.tools.seed_customer_master_from_wfirma import (   # noqa: E402
    BASIC_FIELDS, SeedOutcome, SeedSummary,
    fetch_wfirma_contractors, main, map_contractor_to_basic_master,
    merge_basic_into_existing, seed,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _raw(contractor_id="38582303",
         name="Scandinavian Diamond",
         country="NO",
         nip="VAT ID 854785362",
         different_contact_address="0",
         **kwargs) -> dict:
    return {
        "contractor_id":              contractor_id,
        "name":                       name,
        "altname":                    "",
        "country":                    country,
        "nip":                        nip,
        "different_contact_address":  different_contact_address,
        "contact_name":               kwargs.get("contact_name", ""),
        "contact_person":             kwargs.get("contact_person", ""),
        "contact_street":             kwargs.get("contact_street", ""),
        "contact_city":               kwargs.get("contact_city", ""),
        "contact_zip":                kwargs.get("contact_zip", ""),
        "contact_country":            kwargs.get("contact_country", ""),
    }


# ── Mapping ───────────────────────────────────────────────────────────────────

def test_map_basic_fields():
    c = map_contractor_to_basic_master(_raw())
    assert c.bill_to_contractor_id == "38582303"
    assert c.bill_to_name          == "Scandinavian Diamond"
    assert c.country               == "NO"
    assert c.nip                   == "VAT ID 854785362"
    assert c.ship_to_use_alternate is False
    # No alternate ship-to → all ship_to_* fields stay None
    assert c.ship_to_name is None
    assert c.ship_to_city is None


def test_map_alternate_ship_to_imported_when_flag_set():
    c = map_contractor_to_basic_master(_raw(
        different_contact_address="1",
        contact_name="Warehouse Hub",
        contact_person="Hub Manager",
        contact_street="Industrial Way 5",
        contact_city="Oslo",
        contact_zip="N-0123",
        contact_country="no",
    ))
    assert c.ship_to_use_alternate is True
    assert c.ship_to_name    == "Warehouse Hub"
    assert c.ship_to_person  == "Hub Manager"
    assert c.ship_to_street  == "Industrial Way 5"
    assert c.ship_to_city    == "Oslo"
    assert c.ship_to_zip     == "N-0123"
    assert c.ship_to_country == "NO"


def test_map_alternate_flag_zero_drops_contact_fields():
    """If different_contact_address=0 we don't import contact_*."""
    c = map_contractor_to_basic_master(_raw(
        different_contact_address="0",
        contact_name="ignored",
        contact_street="ignored",
    ))
    assert c.ship_to_use_alternate is False
    assert c.ship_to_name is None
    assert c.ship_to_street is None


def test_map_country_normalised():
    c = map_contractor_to_basic_master(_raw(country="de"))
    assert c.country == "DE"


def test_map_uses_altname_when_name_empty():
    raw = _raw(name="")
    raw["altname"] = "Alt Name LLC"
    c = map_contractor_to_basic_master(raw)
    assert c.bill_to_name == "Alt Name LLC"


@pytest.mark.parametrize("bad_country", ["", "POL", "X"])
def test_map_blocks_invalid_country(bad_country):
    with pytest.raises(ValueError, match="country"):
        map_contractor_to_basic_master(_raw(country=bad_country))


def test_map_blocks_missing_id():
    with pytest.raises(ValueError, match="contractor_id"):
        map_contractor_to_basic_master(_raw(contractor_id=""))


def test_map_blocks_missing_name():
    raw = _raw(name="")
    raw["altname"] = ""
    with pytest.raises(ValueError, match="name"):
        map_contractor_to_basic_master(raw)


# ── Merge logic — preserve enriched, never overwrite ─────────────────────────

def _enriched_existing(**overrides) -> CustomerMaster:
    base = dict(
        bill_to_contractor_id   = "38582303",
        bill_to_name            = "Old Name",
        country                 = "NO",
        nip                     = None,
        # Operator-enriched fields
        vat_eu_number           = "NO12345",
        vat_eu_valid            = True,
        default_currency        = "USD",
        default_language_id     = "1",
        insurance_min_override  = Decimal("25"),
        credit_limit            = Decimal("50000"),
        credit_currency         = "USD",
        kuke_approved           = True,
        kuke_limit              = Decimal("100000"),
        kuke_currency           = "USD",
        risk_status             = "approved",
        notes                   = "operator note",
    )
    base.update(overrides)
    return CustomerMaster(**base)


def test_merge_preserves_enriched_fields_default():
    existing = _enriched_existing()
    from_w   = map_contractor_to_basic_master(_raw(name="New Name"))   # name change
    merged, changed = merge_basic_into_existing(existing, from_w, force_basic=False)
    # Old basic field was "Old Name" — non-empty — so default mode should NOT overwrite
    assert "bill_to_name" not in changed
    assert merged.bill_to_name == "Old Name"
    # All enriched fields preserved
    assert merged.vat_eu_number  == "NO12345"
    assert merged.default_currency == "USD"
    assert merged.kuke_approved  is True
    assert merged.kuke_limit     == Decimal("100000")
    assert merged.notes          == "operator note"


def test_merge_default_only_fills_empty_basic_fields():
    """Default mode only sets basic fields whose CURRENT value is empty."""
    existing = _enriched_existing(
        bill_to_name = "Old Name",
        nip          = None,             # empty — will be filled
    )
    from_w = map_contractor_to_basic_master(_raw(name="New Name", nip="NEW-NIP"))
    merged, changed = merge_basic_into_existing(existing, from_w, force_basic=False)
    assert "bill_to_name" not in changed       # already had value
    assert "nip" in changed                    # was empty, now filled
    assert merged.nip == "NEW-NIP"
    assert merged.bill_to_name == "Old Name"


def test_merge_force_basic_overwrites_basic_but_preserves_enriched():
    existing = _enriched_existing(bill_to_name="Old", nip="OLD-NIP")
    from_w   = map_contractor_to_basic_master(_raw(name="NEW Name", nip="NEW-NIP"))
    merged, changed = merge_basic_into_existing(existing, from_w, force_basic=True)
    assert "bill_to_name" in changed
    assert "nip" in changed
    assert merged.bill_to_name == "NEW Name"
    assert merged.nip          == "NEW-NIP"
    # Enriched fields untouched
    assert merged.kuke_approved   is True
    assert merged.default_currency == "USD"
    assert merged.notes            == "operator note"


def test_merge_force_basic_preserves_ship_to_contractor_id():
    """Shape B (separate receiver entity) is operator-decided enrichment, never overwritten."""
    existing = _enriched_existing(
        ship_to_contractor_id = "99999999",
    )
    from_w = map_contractor_to_basic_master(_raw(different_contact_address="1",
                                                  contact_name="ALT", contact_street="ALT"))
    merged, _ = merge_basic_into_existing(existing, from_w, force_basic=True)
    assert merged.ship_to_contractor_id == "99999999"   # untouched


def test_merge_no_change_returns_empty_change_list():
    existing = _enriched_existing(bill_to_name="Old", nip="X")
    same     = map_contractor_to_basic_master(_raw(name="Old", nip="X"))
    merged, changed = merge_basic_into_existing(existing, same, force_basic=True)
    assert changed == []
    assert merged is existing       # no copy when no changes


# ── Seed orchestration ───────────────────────────────────────────────────────

def test_dry_run_writes_nothing(tmp_path: Path):
    db = tmp_path / "cm.db"
    sent_db: List[CustomerMaster] = []   # tracker

    fetcher = lambda only: [_raw(contractor_id="A1", name="Alpha", country="NO"),
                            _raw(contractor_id="B2", name="Beta",  country="DE")]
    summary = seed(db, dry_run=True, fetcher=fetcher)
    assert summary.inserted == 2
    # DB must be empty (init_db creates the file but no rows)
    assert get_customer(db, "A1") is None
    assert get_customer(db, "B2") is None


def test_inserts_new_customer(tmp_path: Path):
    db = tmp_path / "cm.db"
    fetcher = lambda only: [_raw(contractor_id="38582303", name="Scandinavian Diamond", country="NO")]
    summary = seed(db, fetcher=fetcher)
    assert summary.inserted == 1
    assert summary.updated  == 0
    saved = get_customer(db, "38582303")
    assert saved is not None
    assert saved.country == "NO"


def test_updates_basic_fields_only_when_existing_empty_default_mode(tmp_path: Path):
    db = tmp_path / "cm.db"
    # Operator-pre-enriched record with name set, nip empty
    upsert_customer(db, _enriched_existing(bill_to_name="Operator Name", nip=None))
    # wFirma sees a name change AND a new nip
    fetcher = lambda only: [_raw(contractor_id="38582303",
                                  name="WFIRMA New Name",
                                  nip="NEW-NIP")]
    summary = seed(db, fetcher=fetcher)
    assert summary.updated == 1
    saved = get_customer(db, "38582303")
    # bill_to_name was already set → preserved
    assert saved.bill_to_name == "Operator Name"
    # nip was empty → filled from wFirma
    assert saved.nip          == "NEW-NIP"
    # Enriched fields preserved
    assert saved.default_currency == "USD"
    assert saved.kuke_approved   is True


def test_does_not_overwrite_freight_credit_or_kuke(tmp_path: Path):
    """Critical: enriched fields (freight pointer, currency, Kuke) are NEVER touched."""
    db = tmp_path / "cm.db"
    upsert_customer(db, _enriched_existing(
        default_currency = "EUR",
        kuke_limit       = Decimal("123456"),
        risk_status      = "watch",
    ))
    fetcher = lambda only: [_raw(contractor_id="38582303", name="Fresh", country="NO")]
    seed(db, fetcher=fetcher, force_basic=True)   # even with force-basic
    saved = get_customer(db, "38582303")
    assert saved.default_currency == "EUR"
    assert saved.kuke_limit       == Decimal("123456")
    assert saved.risk_status      == "watch"


def test_alternate_ship_to_imported_from_contact_fields(tmp_path: Path):
    db = tmp_path / "cm.db"
    fetcher = lambda only: [_raw(
        contractor_id="X1", name="Acme", country="DE",
        different_contact_address="1",
        contact_name="Acme Warehouse",
        contact_street="Warehouse Way 5",
        contact_city="Hamburg",
        contact_zip="22117",
        contact_country="DE",
    )]
    seed(db, fetcher=fetcher)
    saved = get_customer(db, "X1")
    assert saved.ship_to_use_alternate is True
    assert saved.ship_to_name          == "Acme Warehouse"
    assert saved.ship_to_street        == "Warehouse Way 5"
    assert saved.ship_to_city          == "Hamburg"
    assert saved.ship_to_country       == "DE"


def test_skipped_unchanged_counted(tmp_path: Path):
    db = tmp_path / "cm.db"
    fetcher = lambda only: [_raw(contractor_id="A1", name="Alpha", country="NO")]
    seed(db, fetcher=fetcher)                        # insert
    summary = seed(db, fetcher=fetcher)              # second run — no change
    assert summary.skipped_unchanged == 1
    assert summary.updated == 0


def test_skipped_missing_country(tmp_path: Path):
    db = tmp_path / "cm.db"
    fetcher = lambda only: [
        _raw(contractor_id="A1", name="Has Country", country="DE"),
        _raw(contractor_id="A2", name="No Country",  country=""),
        _raw(contractor_id="A3", name="Bad Country", country="POLAND"),
    ]
    summary = seed(db, fetcher=fetcher)
    assert summary.inserted                == 1
    assert summary.skipped_missing_country == 2
    # DB has only the valid one
    rows = list_customers(db)
    assert {r.bill_to_contractor_id for r in rows} == {"A1"}


def test_only_filter_passes_through_to_fetcher(tmp_path: Path):
    db = tmp_path / "cm.db"
    received_only = []
    def fetcher(only):
        received_only.append(only)
        return [_raw(contractor_id="38582303", name="SD", country="NO")]
    seed(db, only_ids=["38582303", "11111"], fetcher=fetcher)
    assert received_only == [["38582303", "11111"]]


def test_force_basic_overwrites_basic_fields(tmp_path: Path):
    db = tmp_path / "cm.db"
    upsert_customer(db, _enriched_existing(bill_to_name="Operator Name", nip="OLD-NIP"))
    fetcher = lambda only: [_raw(contractor_id="38582303",
                                  name="WFIRMA Authoritative",
                                  nip="WFIRMA-NIP")]
    seed(db, fetcher=fetcher, force_basic=True)
    saved = get_customer(db, "38582303")
    assert saved.bill_to_name == "WFIRMA Authoritative"
    assert saved.nip          == "WFIRMA-NIP"


def test_summary_outcomes_describe_each_record(tmp_path: Path):
    db = tmp_path / "cm.db"
    upsert_customer(db, CustomerMaster(
        bill_to_contractor_id="EXISTING", bill_to_name="Already there",
        country="NO", nip="X",
    ))
    fetcher = lambda only: [
        _raw(contractor_id="NEW1", name="New One",  country="DE"),
        _raw(contractor_id="EXISTING", name="No change", country="NO"),
        _raw(contractor_id="BAD", name="No country", country=""),
    ]
    summary = seed(db, fetcher=fetcher)
    actions = {o.contractor_id: o.action for o in summary.outcomes}
    assert actions["NEW1"]     == "inserted"
    assert actions["EXISTING"] == "skipped_unchanged"
    assert actions["BAD"]      == "skipped_missing_country"


# ── CLI surface ──────────────────────────────────────────────────────────────

def test_main_dry_run_returns_zero(tmp_path: Path, capsys):
    fetcher = lambda only: [_raw(contractor_id="A1", name="A", country="NO")]
    rc = main(argv=["--db", str(tmp_path / "cm.db"), "--dry-run"], fetcher=fetcher)
    out = capsys.readouterr().out
    assert rc == 0
    assert "DRY-RUN" in out
    assert "inserted              : 1" in out


def test_main_only_arg_parsed(tmp_path: Path, capsys):
    seen_only = []
    def fetcher(only):
        seen_only.append(only)
        return []
    rc = main(argv=["--db", str(tmp_path / "cm.db"),
                     "--only", "38582303,99999",
                     "--dry-run"], fetcher=fetcher)
    assert rc == 0
    assert seen_only == [["38582303", "99999"]]


def test_main_real_write(tmp_path: Path):
    fetcher = lambda only: [_raw(contractor_id="A1", name="A", country="NO")]
    rc = main(argv=["--db", str(tmp_path / "cm.db")], fetcher=fetcher)
    assert rc == 0
    saved = get_customer(tmp_path / "cm.db", "A1")
    assert saved is not None
    assert saved.bill_to_name == "A"


def test_main_handles_connection_error(tmp_path: Path, capsys):
    def bad_fetch(_): raise ConnectionError("network down")
    rc = main(argv=["--db", str(tmp_path / "cm.db")], fetcher=bad_fetch)
    err = capsys.readouterr().err
    assert rc == 5
    assert "network down" in err


# ── fetch_wfirma_contractors — HTTP fully mocked ─────────────────────────────

def test_fetch_wfirma_contractors_parses_response():
    body = """<?xml version="1.0"?>
<api>
  <contractors>
    <contractor>
      <id>38582303</id>
      <name>Scandinavian Diamond</name>
      <altname>SD</altname>
      <country>NO</country>
      <nip>VAT 12345</nip>
      <different_contact_address>0</different_contact_address>
      <contact_name></contact_name>
      <contact_country></contact_country>
    </contractor>
  </contractors>
  <status><code>OK</code></status>
</api>"""
    from app.services import wfirma_client as wfc
    with patch.object(wfc, "_http_request", return_value=(200, body)):
        result = fetch_wfirma_contractors()
    assert len(result) == 1
    assert result[0]["contractor_id"] == "38582303"
    assert result[0]["country"]       == "NO"
    assert result[0]["nip"]           == "VAT 12345"


def test_fetch_wfirma_contractors_raises_on_http_error():
    from app.services import wfirma_client as wfc
    with patch.object(wfc, "_http_request", return_value=(500, "<server error>")):
        with pytest.raises(ConnectionError, match="HTTP 500"):
            fetch_wfirma_contractors()


# ── No I/O leak ──────────────────────────────────────────────────────────────

def test_module_only_imports_wfirma_inside_fetcher():
    """The seeder calls wfirma_client only inside the live fetcher function.
    All other paths must work with the injected fetcher and never import wFirma."""
    src = Path(__file__).resolve().parents[1] / "app" / "tools" / "seed_customer_master_from_wfirma.py"
    text = src.read_text(encoding="utf-8")
    # wfirma_client should be referenced only within fetch_wfirma_contractors body
    assert text.count("wfirma_client") <= 2   # one import-style ref inside the function, plus possibly mention in docstring
