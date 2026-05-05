"""
test_apply_snapshot_profiles_to_master.py — merger guard tests.

NEVER hits wFirma. Pure DB → DB.
Two SQLite DBs (snapshot + master) materialised per-test in tmp_path.
"""
from __future__ import annotations

import sys
from decimal import Decimal
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

from app.services.customer_master_db import (   # noqa: E402
    CustomerMaster, get_customer, upsert_customer,
)
from app.services.customer_invoice_snapshot_db import (   # noqa: E402
    ProfileSnapshotRow, upsert_profile,
)
from app.tools.apply_snapshot_profiles_to_master import (   # noqa: E402
    CONF_CONSISTENT_RECENT, CONF_EMPTY, CONF_SINGLE_DOC,
    CONF_STALE_LOW, CONF_VARYING,
    LOW_CONFIDENCE_STATES, MERGE_FIELDS, NEVER_TOUCH_FIELDS,
    apply, main, merge_one,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _setup_dbs(tmp_path: Path):
    return tmp_path / "snap.db", tmp_path / "master.db"


def _seed_master(master_db: Path, **overrides) -> None:
    base = dict(
        bill_to_contractor_id = "38582303",
        bill_to_name          = "Scandinavian Diamond",
        country               = "NO",
    )
    base.update(overrides)
    upsert_customer(master_db, CustomerMaster(**base))


def _seed_snapshot_profile(snap_db: Path, contractor_id: str = "38582303",
                            confidence: str = CONF_CONSISTENT_RECENT,
                            **overrides) -> None:
    base = dict(
        contractor_id                = contractor_id,
        period_from                  = "2025-11-03",
        period_to                    = "2026-05-03",
        invoice_count                = 5,
        preferred_currency           = "USD",
        preferred_language_id        = "1",
        preferred_invoice_series_id  = None,
        vat_mode                     = None,
        last_freight_amount          = None,
        avg_freight_amount           = None,
        freight_mode                 = None,
        insurance_min_detected       = Decimal("20"),
        insurance_mode               = None,
        ship_to_mode                 = "none",
        confidence_state             = confidence,
    )
    base.update(overrides)
    upsert_profile(snap_db, ProfileSnapshotRow(**base))


# ── Constants are locked ──────────────────────────────────────────────────────

def test_merge_fields_locked():
    """Merger contract: exactly these 10 (snapshot, master) mappings."""
    assert MERGE_FIELDS == [
        ("preferred_currency",          "default_currency"),
        ("preferred_language_id",       "default_language_id"),
        ("preferred_invoice_series_id", "preferred_invoice_series_id"),
        ("vat_mode",                    "vat_mode"),
        ("last_freight_amount",         "freight_last_amount"),
        ("avg_freight_amount",          "freight_avg_amount"),
        ("freight_mode",                "freight_mode"),
        ("preferred_currency",          "freight_currency"),
        ("insurance_min_detected",      "insurance_min_amount"),
        ("insurance_mode",              "insurance_mode"),
    ]


def test_insurance_min_override_is_not_in_merge_fields():
    """Operator's hard override field is NEVER auto-filled by the merger."""
    master_fields = {m for _, m in MERGE_FIELDS}
    assert "insurance_min_override" not in master_fields


def test_low_confidence_states_locked():
    assert LOW_CONFIDENCE_STATES == frozenset({"SINGLE_DOC", "STALE_LOW", "VARYING"})


def test_never_touch_fields_locked():
    expected = {
        "ship_to_use_alternate", "ship_to_name", "ship_to_person",
        "ship_to_street", "ship_to_city", "ship_to_zip",
        "ship_to_country", "ship_to_phone", "ship_to_email",
        "ship_to_contractor_id",
        "credit_limit", "credit_currency",
        "kuke_approved", "kuke_limit", "kuke_currency",
        "kuke_expiry_date", "risk_status",
        "notes",
    }
    assert NEVER_TOUCH_FIELDS == expected


# ── EMPTY profile is skipped ──────────────────────────────────────────────────

def test_empty_profile_skipped(tmp_path: Path):
    snap_db, master_db = _setup_dbs(tmp_path)
    _seed_snapshot_profile(snap_db, confidence=CONF_EMPTY)
    _seed_master(master_db)
    s = apply(snap_db, master_db, dry_run=False)
    assert s.fields_filled  == 0
    assert s.fields_forced  == 0
    assert any(o.action == "skip_empty_profile" for o in s.outcomes)
    # Master record untouched
    got = get_customer(master_db, "38582303")
    assert got.default_currency is None


# ── No master record → skip ───────────────────────────────────────────────────

def test_skip_when_no_master_record(tmp_path: Path):
    snap_db, master_db = _setup_dbs(tmp_path)
    _seed_snapshot_profile(snap_db)   # but master is empty
    s = apply(snap_db, master_db, dry_run=False)
    assert any(o.action == "skip_no_master_record" for o in s.outcomes)
    # Master remains empty
    assert get_customer(master_db, "38582303") is None


# ── Default mode: fills only empty fields ────────────────────────────────────

def test_fills_empty_master_fields(tmp_path: Path):
    snap_db, master_db = _setup_dbs(tmp_path)
    _seed_snapshot_profile(snap_db,
                            preferred_currency="EUR",
                            preferred_language_id="3",
                            insurance_min_detected=Decimal("15"))
    _seed_master(master_db)   # all defaults empty
    s = apply(snap_db, master_db, dry_run=False)
    # Filled: default_currency, default_language_id, freight_currency,
    # insurance_min_amount  → 4 fills
    assert s.fields_filled == 4
    got = get_customer(master_db, "38582303")
    assert got.default_currency      == "EUR"
    assert got.default_language_id   == "3"
    assert got.freight_currency      == "EUR"
    assert got.insurance_min_amount  == Decimal("15")
    # NOT filled — operator-only field
    assert got.insurance_min_override is None


def test_default_mode_skips_already_set_fields(tmp_path: Path):
    """Operator-enriched fields must NOT be overwritten by default."""
    snap_db, master_db = _setup_dbs(tmp_path)
    _seed_snapshot_profile(snap_db, preferred_currency="EUR")
    _seed_master(master_db, default_currency="USD")    # operator-set
    s = apply(snap_db, master_db, dry_run=False)
    skipped = [o for o in s.outcomes if o.action == "skip_already_set"]
    assert any(o.field == "default_currency" for o in skipped)
    got = get_customer(master_db, "38582303")
    assert got.default_currency == "USD"   # unchanged


def test_does_not_overwrite_scandinavian_enrichment(tmp_path: Path):
    """SD scenario: operator has USD/1/20. Snapshot has same.
    Merger must skip the already-set fields. The new fields (freight_currency,
    insurance_min_amount) WILL fill because they were empty."""
    snap_db, master_db = _setup_dbs(tmp_path)
    _seed_snapshot_profile(snap_db,
                            preferred_currency="USD",
                            preferred_language_id="1",
                            insurance_min_detected=Decimal("20"))
    _seed_master(master_db,
                 default_currency       = "USD",
                 default_language_id    = "1",
                 insurance_min_override = Decimal("20"))
    s = apply(snap_db, master_db, dry_run=False)
    # default_currency, default_language_id stay (already set)
    # freight_currency NEW → filled
    # insurance_min_amount NEW → filled
    # insurance_min_override (operator-only) → never touched
    skipped = [o for o in s.outcomes if o.action == "skip_already_set"]
    skipped_fields = {o.field for o in skipped}
    assert "default_currency"    in skipped_fields
    assert "default_language_id" in skipped_fields

    got = get_customer(master_db, "38582303")
    # Operator-set fields untouched
    assert got.default_currency       == "USD"
    assert got.default_language_id    == "1"
    assert got.insurance_min_override == Decimal("20")
    # New auto-filled fields
    assert got.freight_currency       == "USD"
    assert got.insurance_min_amount   == Decimal("20")


# ── --force ───────────────────────────────────────────────────────────────────

def test_force_overwrites_non_empty_basic_fields(tmp_path: Path):
    """--force overwrites mappable fields. insurance_min_override is NEVER
    overwritten because it's not in MERGE_FIELDS (operator-only)."""
    snap_db, master_db = _setup_dbs(tmp_path)
    _seed_snapshot_profile(snap_db,
                            preferred_currency="EUR",
                            preferred_language_id="3",
                            insurance_min_detected=Decimal("25"))
    _seed_master(master_db,
                 default_currency       = "USD",
                 default_language_id    = "1",
                 insurance_min_amount   = Decimal("20"),  # auto-filled previously
                 insurance_min_override = Decimal("99"))  # operator-only, never touched
    s = apply(snap_db, master_db, dry_run=False, force=True)
    forced = [o for o in s.outcomes if o.action == "force_overwrite"]
    forced_fields = {o.field for o in forced}
    # default_currency + default_language_id + insurance_min_amount are forced
    assert "default_currency"      in forced_fields
    assert "default_language_id"   in forced_fields
    assert "insurance_min_amount"  in forced_fields
    # operator-only override NEVER touched
    assert "insurance_min_override" not in forced_fields

    got = get_customer(master_db, "38582303")
    assert got.default_currency       == "EUR"
    assert got.default_language_id    == "3"
    assert got.insurance_min_amount   == Decimal("25")
    assert got.insurance_min_override == Decimal("99")    # operator value preserved


def test_force_does_not_change_value_when_already_equal(tmp_path: Path):
    snap_db, master_db = _setup_dbs(tmp_path)
    _seed_snapshot_profile(snap_db, preferred_currency="USD")
    _seed_master(master_db, default_currency="USD")
    s = apply(snap_db, master_db, dry_run=False, force=True)
    # No outcome with action=force_overwrite for this field — already equal
    forced = [o for o in s.outcomes if o.action == "force_overwrite"]
    assert not forced


# ── Never-touch fields ────────────────────────────────────────────────────────

def test_force_never_touches_credit_or_kuke_or_ship_to(tmp_path: Path):
    """Even with --force the merger never modifies these fields. The merger
    has no way to write them anyway, but we lock the contract here."""
    snap_db, master_db = _setup_dbs(tmp_path)
    _seed_snapshot_profile(snap_db, preferred_currency="EUR")
    _seed_master(master_db,
                 default_currency      = "USD",
                 ship_to_contractor_id = "99999",       # Shape B
                 credit_limit          = Decimal("50000"),
                 credit_currency       = "USD",
                 kuke_approved         = True,
                 kuke_limit            = Decimal("100000"),
                 kuke_currency         = "USD",
                 kuke_expiry_date      = "2027-12-31",
                 risk_status           = "approved",
                 notes                 = "operator note")
    apply(snap_db, master_db, dry_run=False, force=True)
    got = get_customer(master_db, "38582303")
    # Currency was overwritten
    assert got.default_currency == "EUR"
    # Everything else preserved
    assert got.ship_to_contractor_id == "99999"
    assert got.credit_limit          == Decimal("50000")
    assert got.credit_currency       == "USD"
    assert got.kuke_approved         is True
    assert got.kuke_limit            == Decimal("100000")
    assert got.kuke_expiry_date      == "2027-12-31"
    assert got.risk_status           == "approved"
    assert got.notes                 == "operator note"


# ── Confidence-state warnings ─────────────────────────────────────────────────

@pytest.mark.parametrize("low_conf", [CONF_SINGLE_DOC, CONF_STALE_LOW, CONF_VARYING])
def test_low_confidence_state_marks_warn(tmp_path: Path, low_conf):
    snap_db, master_db = _setup_dbs(tmp_path)
    _seed_snapshot_profile(snap_db, confidence=low_conf,
                            preferred_currency="EUR")
    _seed_master(master_db)
    s = apply(snap_db, master_db, dry_run=False)
    fills = [o for o in s.outcomes if o.action == "fill"]
    # Each fill carries a warn flag with the confidence reason
    assert all(o.warn for o in fills)
    assert all(o.warn_reason == low_conf for o in fills)


def test_consistent_recent_does_not_warn(tmp_path: Path):
    snap_db, master_db = _setup_dbs(tmp_path)
    _seed_snapshot_profile(snap_db, confidence=CONF_CONSISTENT_RECENT,
                            preferred_currency="EUR")
    _seed_master(master_db)
    s = apply(snap_db, master_db, dry_run=False)
    fills = [o for o in s.outcomes if o.action == "fill"]
    assert not any(o.warn for o in fills)


# ── Dry-run ───────────────────────────────────────────────────────────────────

def test_dry_run_writes_nothing(tmp_path: Path):
    snap_db, master_db = _setup_dbs(tmp_path)
    _seed_snapshot_profile(snap_db, preferred_currency="EUR")
    _seed_master(master_db)   # default_currency is None
    s = apply(snap_db, master_db, dry_run=True)
    # Outcomes still computed
    assert any(o.action == "fill" for o in s.outcomes)
    # But master was NOT updated
    got = get_customer(master_db, "38582303")
    assert got.default_currency is None


# ── --only filter ─────────────────────────────────────────────────────────────

def test_only_filter_restricts_processing(tmp_path: Path):
    snap_db, master_db = _setup_dbs(tmp_path)
    _seed_snapshot_profile(snap_db, contractor_id="38582303",
                            preferred_currency="EUR")
    _seed_snapshot_profile(snap_db, contractor_id="38533544",
                            preferred_currency="EUR")
    _seed_master(master_db, bill_to_contractor_id="38582303",
                 bill_to_name="A", country="NO")
    _seed_master(master_db, bill_to_contractor_id="38533544",
                 bill_to_name="B", country="CZ")
    s = apply(snap_db, master_db, dry_run=False, only_ids=["38582303"])
    contractors_in_outcomes = {o.contractor_id for o in s.outcomes}
    assert contractors_in_outcomes == {"38582303"}
    # Other customer untouched
    other = get_customer(master_db, "38533544")
    assert other.default_currency is None


# ── merge_one — pure function ────────────────────────────────────────────────

def test_merge_one_pure_no_io(tmp_path: Path):
    """merge_one is a pure function — no DB access."""
    profile = ProfileSnapshotRow(
        contractor_id          = "X",
        invoice_count          = 5,
        preferred_currency     = "EUR",
        preferred_language_id  = "3",
        insurance_min_detected = Decimal("15"),
        confidence_state       = CONF_CONSISTENT_RECENT,
    )
    master = CustomerMaster(
        bill_to_contractor_id="X", bill_to_name="X", country="DE",
    )
    merged, outcomes = merge_one(profile, master)
    assert merged.default_currency      == "EUR"
    assert merged.default_language_id   == "3"
    assert merged.freight_currency      == "EUR"
    assert merged.insurance_min_amount  == Decimal("15")
    # 4 fills: default_currency, default_language_id, freight_currency, insurance_min_amount
    assert sum(1 for o in outcomes if o.action == "fill") == 4


def test_merge_one_no_profile_value_means_no_change():
    """If the snapshot doesn't have a value for a field, no outcome is created."""
    profile = ProfileSnapshotRow(
        contractor_id          = "X",
        invoice_count          = 5,
        preferred_currency     = None,
        preferred_language_id  = None,
        insurance_min_detected = None,
        confidence_state       = CONF_CONSISTENT_RECENT,
    )
    master = CustomerMaster(
        bill_to_contractor_id="X", bill_to_name="X", country="DE",
    )
    merged, outcomes = merge_one(profile, master)
    assert merged is master   # no changes
    assert all(o.action != "fill" for o in outcomes)


# ── CLI ───────────────────────────────────────────────────────────────────────

def test_main_dry_run_returns_zero(tmp_path: Path, capsys):
    snap_db, master_db = _setup_dbs(tmp_path)
    _seed_snapshot_profile(snap_db,
                           preferred_currency="EUR",
                           preferred_language_id=None,
                           insurance_min_detected=None)
    _seed_master(master_db)
    rc = main(argv=["--snapshot-db", str(snap_db),
                     "--master-db",   str(master_db)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "DRY-RUN" in out
    # preferred_currency=EUR fills BOTH default_currency AND freight_currency = 2
    assert "fields filled      : 2" in out


def test_main_apply_writes(tmp_path: Path):
    snap_db, master_db = _setup_dbs(tmp_path)
    _seed_snapshot_profile(snap_db, preferred_currency="EUR")
    _seed_master(master_db)
    rc = main(argv=["--snapshot-db", str(snap_db),
                     "--master-db",   str(master_db),
                     "--apply"])
    assert rc == 0
    got = get_customer(master_db, "38582303")
    assert got.default_currency == "EUR"


def test_main_force_overwrites(tmp_path: Path):
    snap_db, master_db = _setup_dbs(tmp_path)
    _seed_snapshot_profile(snap_db, preferred_currency="EUR")
    _seed_master(master_db, default_currency="USD")
    rc = main(argv=["--snapshot-db", str(snap_db),
                     "--master-db",   str(master_db),
                     "--apply", "--force"])
    assert rc == 0
    got = get_customer(master_db, "38582303")
    assert got.default_currency == "EUR"


def test_main_only_filter(tmp_path: Path):
    snap_db, master_db = _setup_dbs(tmp_path)
    _seed_snapshot_profile(snap_db, contractor_id="A",
                            preferred_currency="EUR")
    _seed_snapshot_profile(snap_db, contractor_id="B",
                            preferred_currency="USD")
    _seed_master(master_db, bill_to_contractor_id="A",
                 bill_to_name="A", country="DE")
    _seed_master(master_db, bill_to_contractor_id="B",
                 bill_to_name="B", country="DE")
    rc = main(argv=["--snapshot-db", str(snap_db),
                     "--master-db",   str(master_db),
                     "--apply", "--only", "A"])
    assert rc == 0
    assert get_customer(master_db, "A").default_currency == "EUR"
    assert get_customer(master_db, "B").default_currency is None


# ── Output table sanity ──────────────────────────────────────────────────────

# ── New commercial fields (freight + invoice series + vat_mode + insurance) ──

def test_fills_invoice_series_and_vat_mode_and_freight(tmp_path: Path):
    """Snapshot has rich data — merger fills all 10 mappable master fields."""
    snap_db, master_db = _setup_dbs(tmp_path)
    _seed_snapshot_profile(
        snap_db,
        preferred_currency             = "EUR",
        preferred_language_id          = "3",
        preferred_invoice_series_id    = "15827921",
        vat_mode                       = 228,
        last_freight_amount            = Decimal("85"),
        avg_freight_amount             = Decimal("82.5"),
        freight_mode                   = "fixed",
        insurance_min_detected         = Decimal("20"),
        insurance_mode                 = "formula",
    )
    _seed_master(master_db)   # all defaults empty

    s = apply(snap_db, master_db, dry_run=False)
    got = get_customer(master_db, "38582303")

    # All 10 mappable fields filled
    assert got.default_currency             == "EUR"
    assert got.default_language_id          == "3"
    assert got.preferred_invoice_series_id  == "15827921"
    assert got.vat_mode                     == 228
    assert got.freight_last_amount          == Decimal("85")
    assert got.freight_avg_amount           == Decimal("82.5")
    assert got.freight_mode                 == "fixed"
    assert got.freight_currency             == "EUR"
    assert got.insurance_min_amount         == Decimal("20")
    assert got.insurance_mode               == "formula"
    # Defaulted constants on the dataclass
    assert got.freight_service_id           == "13002743"
    assert got.insurance_service_id         == "13102217"
    assert got.insurance_rate               == Decimal("0.0035")
    # NOT touched
    assert got.insurance_min_override       is None
    assert got.preferred_proforma_series_id is None  # not in snapshot, not auto-filled


def test_force_does_not_touch_freight_service_or_insurance_service_constants(tmp_path: Path):
    """freight_service_id and insurance_service_id should not be in MERGE_FIELDS
    — they're constants, never sourced from the snapshot."""
    master_targets = {m for _, m in MERGE_FIELDS}
    assert "freight_service_id"   not in master_targets
    assert "insurance_service_id" not in master_targets
    assert "insurance_rate"       not in master_targets


def test_force_does_not_touch_proforma_series_id():
    """preferred_proforma_series_id is operator-decided — snapshot only knows
    invoice series. So the merger never auto-fills it."""
    master_targets = {m for _, m in MERGE_FIELDS}
    assert "preferred_proforma_series_id" not in master_targets


def test_partial_snapshot_only_fills_what_it_has(tmp_path: Path):
    """Snapshot with only 2 fields should fill exactly those 2 (currency
    fills 2 master fields)."""
    snap_db, master_db = _setup_dbs(tmp_path)
    _seed_snapshot_profile(
        snap_db,
        preferred_currency             = "USD",
        preferred_language_id          = None,
        insurance_min_detected         = None,
        last_freight_amount            = Decimal("75"),
        avg_freight_amount             = None,
        freight_mode                   = "fixed",
        preferred_invoice_series_id    = None,
        vat_mode                       = None,
        insurance_mode                 = None,
    )
    _seed_master(master_db)
    s = apply(snap_db, master_db, dry_run=False)
    got = get_customer(master_db, "38582303")
    assert got.default_currency       == "USD"
    assert got.freight_currency       == "USD"
    assert got.freight_last_amount    == Decimal("75")
    assert got.freight_mode           == "fixed"
    # Untouched (no snapshot value)
    assert got.default_language_id    is None
    assert got.vat_mode               is None
    assert got.insurance_min_amount   is None


def test_force_overwrites_freight_fields(tmp_path: Path):
    snap_db, master_db = _setup_dbs(tmp_path)
    _seed_snapshot_profile(
        snap_db,
        preferred_currency  = "USD",
        last_freight_amount = Decimal("85"),
        freight_mode        = "fixed",
    )
    _seed_master(master_db,
                 default_currency    = "USD",
                 freight_last_amount = Decimal("75"),
                 freight_mode        = "variable")
    apply(snap_db, master_db, dry_run=False, force=True)
    got = get_customer(master_db, "38582303")
    assert got.freight_last_amount == Decimal("85")
    assert got.freight_mode        == "fixed"


def test_default_constants_appear_on_new_customer(tmp_path: Path):
    """Fresh customer master record should expose the service-id constants
    even before any snapshot merge."""
    snap_db, master_db = _setup_dbs(tmp_path)
    _seed_master(master_db)
    got = get_customer(master_db, "38582303")
    assert got.freight_service_id    == "13002743"
    assert got.insurance_service_id  == "13102217"
    assert got.insurance_rate        == Decimal("0.0035")


def test_summary_outcomes_describe_each_field(tmp_path: Path):
    snap_db, master_db = _setup_dbs(tmp_path)
    _seed_snapshot_profile(snap_db,
                            preferred_currency="EUR",
                            preferred_language_id="3",
                            insurance_min_detected=Decimal("15"))
    _seed_master(master_db, default_currency="USD")   # only currency pre-set
    s = apply(snap_db, master_db, dry_run=False)
    # default_currency: skip (already set)
    # default_language_id: fill
    # freight_currency: fill (NEW field, was empty)
    # insurance_min_amount: fill
    skip_currency = [o for o in s.outcomes
                     if o.field == "default_currency" and o.action == "skip_already_set"]
    assert len(skip_currency) == 1
    fills = [o for o in s.outcomes if o.action == "fill"]
    fill_fields = {o.field for o in fills}
    assert "default_language_id"  in fill_fields
    assert "freight_currency"     in fill_fields
    assert "insurance_min_amount" in fill_fields
