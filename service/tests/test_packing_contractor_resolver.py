"""test_packing_contractor_resolver.py — B0.X R1 deterministic resolver.

Covers the 6 matching tiers + trip-wires guaranteeing no wFirma write,
no master-table write, no cross-module side effect.

Cases mirror the design doc Phase 7 contract.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from service.app.services import customer_master_db as cmdb
from service.app.services import suppliers_db as sdb
from service.app.services import packing_contractor_resolver as pcr


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def cm_db(tmp_path):
    """Empty Client Master sqlite seeded with three rows across PL/DE/IN."""
    db = tmp_path / "cm.sqlite"
    cmdb.init_db(db)
    # PL client with NIP + REGON + short_code alias
    cmdb.upsert_identity_only(
        db, bill_to_contractor_id="100", bill_to_name="ACME POLAND Sp. z o.o.",
        country="PL", nip="PL1234567890",
    )
    # DE client with EU VAT
    cmdb.upsert_identity_only(
        db, bill_to_contractor_id="200", bill_to_name="BETA GMBH",
        country="DE", nip="DE111222333",
    )
    # IN client with GSTIN
    cmdb.upsert_identity_only(
        db, bill_to_contractor_id="300", bill_to_name="GAMMA PVT LTD",
        country="IN", nip="29ABCDE1234F1Z5",
    )
    # Update PL one with a short_code via the legacy PUT path (Tier 4 alias)
    from service.app.api.routes_customer_master import _OPTIONAL_STR_FIELDS  # noqa
    # Use direct sqlite update for the test fixture (short_code is operator-entered).
    import sqlite3
    with sqlite3.connect(str(db)) as conn:
        conn.execute("UPDATE customer_master SET short_code = ? WHERE bill_to_contractor_id = ?",
                     ("ACMEPL", "100"))
        conn.commit()
    return db


@pytest.fixture
def sup_db(tmp_path):
    """Empty Supplier Master sqlite seeded with two IN exporters."""
    db = tmp_path / "sup.sqlite"
    sdb.init_db(db)
    sdb.upsert_supplier_identity_from_wfirma(
        db, wfirma_id="900", name="ESTRELLA JEWELS LLP", country="IN",
        vat_id="GSTIN-EJL-001",
    )
    sdb.upsert_supplier_identity_from_wfirma(
        db, wfirma_id="901", name="IDEAL JEWELLERY PVT LTD", country="IN",
        vat_id="GSTIN-IJP-002",
    )
    return db


def _resolve(parsed, role, cm_db=None, sup_db=None):
    return pcr.resolve_contractor(parsed, role,
                                  cm_db_path=cm_db, sup_db_path=sup_db)


# ── Tier 1 — wFirma id exact ──────────────────────────────────────────────


def test_tier1_exact_wfirma_id_client(cm_db):
    v = _resolve({"parsed_name": "anything", "parsed_wfirma_id": "100"},
                 "client", cm_db=cm_db)
    assert v["tier"]       == 1
    assert v["confidence"] == 1.00
    assert v["reason"]     == "wfirma_id_exact"
    assert v["matched_master_type"] == "client_master"
    assert v["matched_wfirma_id"]   == "100"
    assert v["status"]              == "auto"


def test_tier1_exact_wfirma_id_supplier(sup_db):
    v = _resolve({"parsed_name": "whatever", "parsed_wfirma_id": "900"},
                 "supplier", sup_db=sup_db)
    assert v["tier"]       == 1
    assert v["confidence"] == 1.00
    assert v["matched_master_type"] == "supplier_master"
    assert v["matched_wfirma_id"]   == "900"


# ── Tier 2 — tax / VAT id exact ──────────────────────────────────────────


def test_tier2_exact_tax_id_client_pl(cm_db):
    """Polish NIP — country prefix and spaces tolerated by normalisation."""
    v = _resolve({"parsed_name": "ACME", "parsed_tax_id": "PL 123-456-7890",
                  "parsed_country": "PL"}, "client", cm_db=cm_db)
    assert v["tier"]       == 2
    assert v["confidence"] == 0.95
    assert v["reason"]     == "tax_id_exact"
    assert v["matched_master_id"] is not None


def test_tier2_exact_tax_id_supplier_in(sup_db):
    v = _resolve({"parsed_name": "ESTRELLA", "parsed_tax_id": "GSTIN-EJL-001",
                  "parsed_country": "IN"}, "supplier", sup_db=sup_db)
    assert v["tier"]       == 2
    assert v["matched_master_type"] == "supplier_master"


# ── Tier 3 — normalised name + country ───────────────────────────────────


def test_tier3_name_plus_country_drops_legal_suffix(cm_db):
    """'ACME POLAND' (no suffix) must still match 'ACME POLAND Sp. z o.o.'"""
    v = _resolve({"parsed_name": "ACME POLAND", "parsed_country": "PL"},
                 "client", cm_db=cm_db)
    assert v["tier"]       == 3
    assert v["confidence"] == 0.85
    assert v["reason"]     == "name_plus_country_exact"


def test_tier3_name_plus_country_normalises_case_and_punctuation(cm_db):
    v = _resolve({"parsed_name": "  beta, GMBH! ", "parsed_country": "DE"},
                 "client", cm_db=cm_db)
    assert v["tier"]       == 3
    assert v["matched_wfirma_id"] == "200"


# ── Tier 4 — alias / short_code ─────────────────────────────────────────


def test_tier4_alias_short_code_match(cm_db):
    v = _resolve({"parsed_name": "ACMEPL", "parsed_country": "PL"},
                 "client", cm_db=cm_db)
    # ACMEPL is the short_code, NOT the bill_to_name — but Tier 3 won't fire
    # (normalised "acmepl" != "acme poland"). Tier 4 alias kicks in.
    assert v["tier"]       == 4
    assert v["confidence"] == 0.80
    assert v["reason"]     == "alias_exact"


def test_tier4_supplier_code_match(sup_db):
    # The deterministic supplier_code emitted by upsert is WF-<id>-<name>.
    # Operator may type that whole code as the parsed_name on rare packing
    # lists; the alias tier handles it.
    v = _resolve({"parsed_name": "WF-900-ESTRELLA_JEWELS_LLP", "parsed_country": "IN"},
                 "supplier", sup_db=sup_db)
    assert v["tier"]       == 4
    assert v["matched_wfirma_id"] == "900"


# ── Tier 5 — fuzzy name + country ───────────────────────────────────────


def test_tier5_fuzzy_above_threshold(cm_db):
    """Typo 'ACEM POLAND' → ratio high enough for fuzzy match."""
    v = _resolve({"parsed_name": "ACEM POLAND", "parsed_country": "PL"},
                 "client", cm_db=cm_db)
    assert v["tier"]        == 5
    assert v["confidence"] <= 0.70   # capped
    assert v["reason"].startswith("fuzzy_name_country:")
    assert v["matched_master_id"] is not None


def test_tier5_fuzzy_below_threshold_unresolved(cm_db):
    """'ZZZZ' → no candidate scores ≥ 85; falls through to unresolved."""
    v = _resolve({"parsed_name": "ZZZZ COMPANY", "parsed_country": "PL"},
                 "client", cm_db=cm_db)
    assert v["tier"]   == 6
    assert v["status"] == "unresolved"
    assert v["reason"] == "no_match"


# ── Tier 6 — ambiguous duplicate ────────────────────────────────────────


def test_tier3_collision_returns_unresolved(tmp_path):
    """Two rows with the SAME normalised name + country must NOT auto-match.
    They must be surfaced as candidates with status='unresolved'."""
    db = tmp_path / "cm-dup.sqlite"
    cmdb.init_db(db)
    cmdb.upsert_identity_only(
        db, bill_to_contractor_id="D1", bill_to_name="DUPLICATE CO", country="PL")
    cmdb.upsert_identity_only(
        db, bill_to_contractor_id="D2", bill_to_name="DUPLICATE CO Sp. z o.o.", country="PL")
    v = _resolve({"parsed_name": "DUPLICATE CO", "parsed_country": "PL"},
                 "client", cm_db=db)
    assert v["status"] == "unresolved"
    assert v["reason"] == "name_plus_country_ambiguous"
    assert len(v["candidates"]) >= 2


# ── Empty / degenerate input ─────────────────────────────────────────────


def test_empty_parsed_name_unresolved(cm_db):
    v = _resolve({"parsed_name": "", "parsed_country": "PL"},
                 "client", cm_db=cm_db)
    assert v["status"] == "unresolved"
    assert v["tier"]   == 6


def test_unknown_country_falls_back_to_fuzzy_or_unresolved(cm_db):
    # No country supplied — Tier 3 (needs country) skipped, Tier 5 scans all.
    v = _resolve({"parsed_name": "ACME POLAND", "parsed_country": ""},
                 "client", cm_db=cm_db)
    # Tier 5 should fire because the name matches and country filter is bypassed.
    assert v["tier"] in (5, 6)
    if v["tier"] == 5:
        assert v["matched_master_id"] is not None


# ── Generic-across-countries (PL / DE / IN) ─────────────────────────────


@pytest.mark.parametrize("name,country,expected_wfid", [
    ("ACME POLAND", "PL", "100"),
    ("BETA",        "DE", "200"),
    ("GAMMA",       "IN", "300"),
])
def test_resolver_generic_across_countries(cm_db, name, country, expected_wfid):
    v = _resolve({"parsed_name": name, "parsed_country": country},
                 "client", cm_db=cm_db)
    # Whatever tier wins, the matched row must be the expected country master.
    assert v["status"] == "auto", f"{country}: expected auto match, got {v}"
    assert v["matched_wfirma_id"] == expected_wfid


# ── Candidates always include top-5 ─────────────────────────────────────


def test_candidates_always_include_top_n(tmp_path):
    db = tmp_path / "cm-many.sqlite"
    cmdb.init_db(db)
    # Seed 7 PL clients so the top-5 filter actually trims.
    for i in range(7):
        cmdb.upsert_identity_only(
            db, bill_to_contractor_id=f"M{i}", bill_to_name=f"NAME {i}",
            country="PL")
    v = _resolve({"parsed_name": "NAME 0", "parsed_country": "PL"},
                 "client", cm_db=db)
    assert len(v["candidates"]) == 5
    # Highest-ranked candidate is the exact match
    assert v["candidates"][0]["display_name"] == "NAME 0"


def test_candidates_present_even_when_unresolved(cm_db):
    v = _resolve({"parsed_name": "TOTALLY UNKNOWN BRAND", "parsed_country": "PL"},
                 "client", cm_db=cm_db)
    assert v["status"] == "unresolved"
    # Even unresolved must show the operator the top-5 PL candidates.
    assert isinstance(v["candidates"], list)
    assert len(v["candidates"]) >= 1


# ── Trip-wires: no wFirma write, no master-table write ──────────────────


def test_resolver_does_not_import_wfirma_write_paths():
    """Source-grep guard: the resolver module must NOT call any wFirma
    write primitive. Reading allowed."""
    src = Path(pcr.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "create_customer(", "create_contractor(",
        "update_customer(", "update_contractor(",
        "delete_customer(", "delete_contractor(",
        "post_invoice(", "create_invoice(", "issue_invoice(",
        "create_proforma(", "post_proforma(",
    ):
        assert forbidden not in src, \
            f"resolver must not call wFirma write '{forbidden}'"


def test_resolver_does_not_call_wfirma_client_module(cm_db, monkeypatch):
    """Trip-wire: monkey-patch every wFirma client attribute and confirm
    none of them fires during resolve_contractor()."""
    from service.app.services import wfirma_client
    called: list = []
    for attr in dir(wfirma_client):
        if attr.startswith("_"):
            continue
        try:
            obj = getattr(wfirma_client, attr)
        except Exception:
            continue
        if callable(obj):
            def _trip(*_a, _n=attr, **_k):
                called.append(_n)
                raise AssertionError(f"resolver called wfirma_client.{_n}")
            try:
                monkeypatch.setattr(wfirma_client, attr, _trip)
            except (AttributeError, TypeError):
                # readonly / property attrs ignored
                pass
    # Run a representative resolve.
    _resolve({"parsed_name": "ACME POLAND", "parsed_country": "PL"},
             "client", cm_db=cm_db)
    assert called == [], f"resolver hit wfirma_client: {called}"


def test_resolver_does_not_write_to_master_tables(cm_db, monkeypatch):
    """Trip-wire on every master-table write entry point — none must fire
    during a resolver call."""
    write_calls: list = []
    # customer_master_db writes
    for attr in ("upsert_customer", "upsert_identity_only", "delete_customer"):
        if hasattr(cmdb, attr):
            original = getattr(cmdb, attr)
            def _trip(*a, _n=attr, _orig=original, **k):
                write_calls.append(_n)
                raise AssertionError(f"resolver wrote to cmdb.{_n}")
            monkeypatch.setattr(cmdb, attr, _trip)
    # suppliers_db writes
    for attr in ("create_supplier", "update_supplier", "delete_supplier",
                 "sync_from_wfirma", "upsert_supplier_identity_from_wfirma"):
        if hasattr(sdb, attr):
            original = getattr(sdb, attr)
            def _trip(*a, _n=attr, _orig=original, **k):
                write_calls.append(_n)
                raise AssertionError(f"resolver wrote to sdb.{_n}")
            monkeypatch.setattr(sdb, attr, _trip)
    _resolve({"parsed_name": "ACME POLAND", "parsed_country": "PL"},
             "client", cm_db=cm_db)
    assert write_calls == [], f"resolver triggered master writes: {write_calls}"


def test_resolver_module_does_not_import_proforma_pz_dhl_finance():
    """Source-grep: resolver must not import any of the forbidden subsystems."""
    src = Path(pcr.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "from ..services import proforma",
        "from ..services import wfirma_customer_sync",  # write helper
        "from ..api import routes_dhl",
        "from ..services import finance",
        "from ..services import dual_write",
        "import routes_pz",
        "create_proforma", "post_proforma",
    ):
        assert forbidden not in src, \
            f"resolver must not import / call '{forbidden}'"


# ── Invalid role ────────────────────────────────────────────────────────


def test_invalid_role_raises_value_error():
    with pytest.raises(ValueError):
        pcr.resolve_contractor({"parsed_name": "x"}, "kontrahent")


# ── Normalisation helpers ───────────────────────────────────────────────


def test_normalise_name_drops_legal_suffixes():
    assert pcr.normalise_name("ACME POLAND Sp. z o.o.")    == "acme poland"
    assert pcr.normalise_name("BETA GmbH")                 == "beta"
    assert pcr.normalise_name("GAMMA PVT LTD")             == "gamma"
    assert pcr.normalise_name("DELTA LLP.")                == "delta"
    assert pcr.normalise_name("EPSILON, OY")               == "epsilon"
    assert pcr.normalise_name("ZETA S.R.O.")               == "zeta"


def test_normalise_name_strips_accents_and_punctuation():
    assert pcr.normalise_name("Złoty Łańcuch")    == "zloty lancuch"
    assert pcr.normalise_name("CO., Ltd.")        == ""  # legal-suffix-only string


def test_normalise_tax_id_strips_country_prefix_and_separators():
    assert pcr.normalise_tax_id("PL 123-456-7890") == "1234567890"
    assert pcr.normalise_tax_id("DE111222333")     == "111222333"
    assert pcr.normalise_tax_id("")                 == ""
    assert pcr.normalise_tax_id(None)               == ""


def test_normalise_country_iso_alpha2_only():
    assert pcr.normalise_country("PL")        == "PL"
    assert pcr.normalise_country("pl")        == "PL"
    assert pcr.normalise_country("Poland")    == ""
    assert pcr.normalise_country(None)        == ""
