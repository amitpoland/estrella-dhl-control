"""Tests for CompanyProfile DB operations (Phase 7)."""
import pytest
from pathlib import Path
from app.services.master_data_db import (
    get_company_profile, upsert_company_profile, CompanyProfile,
    _ensure_company_profile_table,
)


def test_get_returns_none_when_no_row(tmp_path):
    db = tmp_path / "master_data.sqlite"
    result = get_company_profile(db)
    assert result is None


def test_upsert_creates_row(tmp_path):
    db = tmp_path / "master_data.sqlite"
    upsert_company_profile(db, legal_name="Estrella Jewels Sp. z o.o. Sp. k.")
    result = get_company_profile(db)
    assert result is not None
    assert result.legal_name == "Estrella Jewels Sp. z o.o. Sp. k."


def test_upsert_partial_update_preserves_other_fields(tmp_path):
    db = tmp_path / "master_data.sqlite"
    upsert_company_profile(db, legal_name="Test Co", nip="1234567890")
    upsert_company_profile(db, iban_eur="PL12345")
    result = get_company_profile(db)
    assert result.legal_name == "Test Co"
    assert result.nip == "1234567890"
    assert result.iban_eur == "PL12345"


def test_upsert_refreshes_updated_at(tmp_path):
    db = tmp_path / "master_data.sqlite"
    upsert_company_profile(db, legal_name="A")
    r1 = get_company_profile(db)
    import time; time.sleep(0.01)
    upsert_company_profile(db, legal_name="B")
    r2 = get_company_profile(db)
    assert r2.updated_at >= r1.updated_at
    assert r2.legal_name == "B"


def test_all_fields_round_trip(tmp_path):
    db = tmp_path / "master_data.sqlite"
    fields = dict(
        legal_name="Estrella Jewels Sp. z o.o. Sp. k.",
        short_name="Estrella Jewels",
        street="ul. Nowy Swiat 27 lok. 39",
        postal_city="00-029 Warszawa",
        country="PL",
        nip="5252812119",
        vat_eu="PL5252812119",
        regon="123456789",
        email="import@estrellajewels.eu",
        phone="+48123456789",
        iban_eur="PL10111213141516171819202122",
        iban_usd="PL20212223242526272829303132",
        iban_pln="PL30313233343536373839404142",
        swift="BPKOPLPW",
        bank_name="Santander",
        place_of_issue="Warszawa",
        signatory_name="Amit Gupta",
        signatory_title="CEO",
        returns_policy_pl="Zwroty w ciagu 14 dni.",
        gdpr_text_pl="Dane przetwarzane zgodnie z RODO.",
    )
    upsert_company_profile(db, **fields)
    result = get_company_profile(db)
    for k, v in fields.items():
        assert getattr(result, k) == v, f"Field {k} mismatch"


def test_idempotent_table_creation(tmp_path):
    """Calling _ensure_company_profile_table twice must not raise."""
    import sqlite3
    db = tmp_path / "master_data.sqlite"
    with sqlite3.connect(str(db)) as conn:
        _ensure_company_profile_table(conn)
        _ensure_company_profile_table(conn)  # second call must be silent
