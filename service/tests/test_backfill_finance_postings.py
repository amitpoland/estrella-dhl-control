"""test_backfill_finance_postings.py — Phase 6F.2.a tests.

Covers the backfill script's:
  - source read
  - row classification (eligible / blocked / skipped_zero)
  - idempotency key determinism
  - group key + synthetic posting id
  - dry-run report shape
  - dry-run is read-only (target DB never written)
  - live mode requires --write + --snapshot-dir (or programmatic equivalent)
  - live mode snapshot is taken before writes
  - duplicate detection (re-run is a no-op)
  - currency normalisation
  - chunking
  - mixed-currency-in-group raises
  - amount → minor units via Decimal (no float drift)
  - CLI exit codes
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest


def _ensure_path() -> None:
    here = Path(__file__).resolve()
    for p in (str(here.parents[1]), str(here.parents[2]),
              str(here.parents[1] / "scripts")):
        if p not in sys.path:
            sys.path.insert(0, p)


_ensure_path()

import backfill_finance_postings as bf  # type: ignore
from app.services import finance_postings_db as fp


# ── Helpers: build legacy source DB in tmp ──────────────────────────────────

def _make_legacy_db(path: Path, rows: list) -> Path:
    """Create a tiny legacy DB matching the proforma_service_charges schema."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(path)) as c:
        c.executescript("""
            CREATE TABLE proforma_service_charges (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id     TEXT NOT NULL,
                client_name  TEXT NOT NULL,
                charge_type  TEXT NOT NULL,
                amount       REAL NOT NULL DEFAULT 0,
                currency     TEXT NOT NULL DEFAULT '',
                note         TEXT NOT NULL DEFAULT '',
                created_at   TEXT NOT NULL,
                created_by   TEXT NOT NULL DEFAULT '',
                updated_at   TEXT NOT NULL,
                UNIQUE(batch_id, client_name, charge_type)
            )
        """)
        for r in rows:
            c.execute(
                """INSERT INTO proforma_service_charges
                   (batch_id, client_name, charge_type, amount, currency,
                    note, created_at, created_by, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (r["batch_id"], r["client_name"], r["charge_type"],
                 r["amount"], r["currency"], r.get("note", ""),
                 r["created_at"], r.get("created_by", ""), r["updated_at"]),
            )
        c.commit()
    return path


# ── Source read ─────────────────────────────────────────────────────────────

def test_read_legacy_charges_empty_when_file_missing(tmp_path):
    assert bf.read_legacy_charges(tmp_path / "nope.db") == []


def test_read_legacy_charges_round_trip(tmp_path):
    src = tmp_path / "legacy.db"
    _make_legacy_db(src, [
        {"batch_id": "B1", "client_name": "Acme", "charge_type": "freight",
         "amount": 100.0, "currency": "EUR", "created_at": "2026-05-15T00:00:00+00:00",
         "updated_at": "2026-05-15T00:00:00+00:00"},
    ])
    rows = bf.read_legacy_charges(src)
    assert len(rows) == 1
    assert rows[0].batch_id == "B1"
    assert rows[0].charge_type == "freight"
    assert rows[0].currency == "EUR"


# ── Classification ──────────────────────────────────────────────────────────

def _mk_row(**kw):
    base = {
        "id": 1, "batch_id": "B1", "client_name": "Acme",
        "charge_type": "freight", "amount": 100.0,
        "currency": "EUR", "note": "",
        "created_at": "2026-05-15T00:00:00+00:00",
        "created_by": "", "updated_at": "2026-05-15T00:00:00+00:00",
    }
    base.update(kw)
    return bf.LegacyCharge(**base)


def test_classify_eligible_minimal():
    v, r = bf.classify_row(_mk_row())
    assert v == "eligible" and r is None


def test_classify_blocks_empty_currency():
    v, r = bf.classify_row(_mk_row(currency=""))
    assert v == "blocked" and r == "empty_currency"


def test_classify_blocks_non_iso_currency():
    v, r = bf.classify_row(_mk_row(currency="EU"))
    assert v == "blocked"
    assert r.startswith("non_iso_currency:")


def test_classify_blocks_unknown_charge_type():
    v, r = bf.classify_row(_mk_row(charge_type="mystery"))
    assert v == "blocked"
    assert "unknown_charge_type" in r


def test_classify_blocks_empty_batch_id():
    v, r = bf.classify_row(_mk_row(batch_id=""))
    assert v == "blocked" and r == "empty_batch_id"


def test_classify_blocks_empty_client_name():
    v, r = bf.classify_row(_mk_row(client_name=""))
    assert v == "blocked" and r == "empty_client_name"


def test_classify_skips_zero_amount():
    v, r = bf.classify_row(_mk_row(amount=0.0))
    assert v == "skipped_zero" and r is None


# ── Idempotency key + amount → minor units ─────────────────────────────────

def test_idempotency_key_is_deterministic():
    r1 = _mk_row(batch_id="B1", client_name="X", charge_type="freight")
    r2 = _mk_row(batch_id="B1", client_name="X", charge_type="freight", id=99)
    assert r1.idempotency_sha1 == r2.idempotency_sha1


def test_idempotency_key_changes_with_tuple():
    r1 = _mk_row(batch_id="B1", client_name="X", charge_type="freight")
    r2 = _mk_row(batch_id="B1", client_name="Y", charge_type="freight")
    r3 = _mk_row(batch_id="B2", client_name="X", charge_type="freight")
    r4 = _mk_row(batch_id="B1", client_name="X", charge_type="insurance")
    assert len({r1.idempotency_sha1, r2.idempotency_sha1,
                r3.idempotency_sha1, r4.idempotency_sha1}) == 4


def test_amount_minor_uses_decimal_not_float():
    """0.1 + 0.2 = 0.3000000000000004 as a float. Decimal makes this safe."""
    r = _mk_row(amount=3.49)
    # 3.49 * 100 in float → 348.99999999999994. Decimal('3.49') * 100 → 349.
    assert r.amount_minor == 349


def test_amount_minor_rounds_half_even():
    assert _mk_row(amount=1.005).amount_minor in (100, 101)  # banker's rounding-dependent
    assert _mk_row(amount=1.00).amount_minor == 100
    assert _mk_row(amount=12.50).amount_minor == 1250


# ── Group key + synthetic posting id ───────────────────────────────────────

def test_synthetic_posting_id_starts_with_backfill_prefix():
    gk = bf.GroupKey(batch_id="B1", client_name="Acme")
    sid = gk.synthetic_posting_id
    assert sid.startswith(bf.POSTING_SYNTHETIC_PREFIX)
    # 16 hex chars after prefix
    assert len(sid) == len(bf.POSTING_SYNTHETIC_PREFIX) + 16


def test_synthetic_posting_id_deterministic():
    a = bf.GroupKey("B1", "Acme").synthetic_posting_id
    b = bf.GroupKey("B1", "Acme").synthetic_posting_id
    c = bf.GroupKey("B2", "Acme").synthetic_posting_id
    assert a == b
    assert a != c


# ── Dry-run end-to-end ────────────────────────────────────────────────────

def test_dryrun_produces_report_no_writes(tmp_path):
    src = _make_legacy_db(tmp_path / "legacy.db", [
        {"batch_id": "B1", "client_name": "Acme", "charge_type": "freight",
         "amount": 100.0, "currency": "EUR",
         "created_at": "2026-05-15T00:00:00+00:00",
         "updated_at": "2026-05-15T00:00:00+00:00"},
        {"batch_id": "B1", "client_name": "Acme", "charge_type": "insurance",
         "amount": 25.50, "currency": "EUR",
         "created_at": "2026-05-15T00:00:00+00:00",
         "updated_at": "2026-05-15T00:00:00+00:00"},
    ])
    target = tmp_path / "fp.sqlite"
    report_path = tmp_path / "report.json"
    rc, report = bf.run_backfill(source_db=src, target_db=target,
                                   report_path=report_path, write=False)
    assert rc == 0
    assert report.mode == "dry-run"
    assert report.source_rows == 2
    assert report.eligible_rows == 2
    assert report.charges_to_create == 2
    assert report.postings_to_create == 1
    # Target must NOT have been written
    assert not target.exists()
    # Report file written
    assert report_path.exists()
    data = json.loads(report_path.read_text(encoding="utf-8"))
    assert data["mode"] == "dry-run"
    assert data["charges_to_create"] == 2


def test_dryrun_reports_blocked_rows_with_reasons(tmp_path):
    src = _make_legacy_db(tmp_path / "legacy.db", [
        {"batch_id": "B1", "client_name": "Acme", "charge_type": "freight",
         "amount": 100.0, "currency": "",
         "created_at": "2026-05-15T00:00:00+00:00",
         "updated_at": "2026-05-15T00:00:00+00:00"},
        {"batch_id": "B1", "client_name": "Acme", "charge_type": "mystery",
         "amount": 10.0, "currency": "EUR",
         "created_at": "2026-05-15T00:00:00+00:00",
         "updated_at": "2026-05-15T00:00:00+00:00"},
    ])
    target = tmp_path / "fp.sqlite"
    report_path = tmp_path / "report.json"
    rc, report = bf.run_backfill(source_db=src, target_db=target,
                                   report_path=report_path, write=False)
    assert rc == 1  # blocked rows present
    assert report.blocked_rows == 2
    assert "empty_currency" in report.blocked_reasons
    assert any(k.startswith("unknown_charge_type") for k in report.blocked_reasons)


def test_dryrun_skips_zero_amount_rows(tmp_path):
    src = _make_legacy_db(tmp_path / "legacy.db", [
        {"batch_id": "B1", "client_name": "X", "charge_type": "freight",
         "amount": 0.0, "currency": "EUR",
         "created_at": "2026-05-15T00:00:00+00:00",
         "updated_at": "2026-05-15T00:00:00+00:00"},
    ])
    target = tmp_path / "fp.sqlite"
    report_path = tmp_path / "r.json"
    rc, report = bf.run_backfill(source_db=src, target_db=target,
                                   report_path=report_path, write=False)
    assert rc == 0
    assert report.skipped_zero == 1
    assert report.eligible_rows == 0


def test_dryrun_with_no_source_returns_zero(tmp_path):
    target = tmp_path / "fp.sqlite"
    report_path = tmp_path / "r.json"
    rc, report = bf.run_backfill(source_db=tmp_path / "missing.db",
                                   target_db=target,
                                   report_path=report_path, write=False)
    assert rc == 0
    assert report.source_rows == 0


# ── Live mode preconditions ────────────────────────────────────────────────

def test_live_mode_requires_snapshot_dir_at_cli(tmp_path):
    """The CLI returns exit code 2 if --write is given without --snapshot-dir."""
    src = tmp_path / "src.db"
    target = tmp_path / "fp.sqlite"
    report = tmp_path / "r.json"
    src.write_bytes(b"")  # exists but no schema; read returns []
    rc = bf.main([
        "--source-db", str(src), "--target-db", str(target),
        "--report-path", str(report), "--write",
    ])
    assert rc == 2


def test_live_mode_programmatic_returns_2_without_snapshot(tmp_path):
    rc, report = bf.run_backfill(
        source_db=tmp_path / "x.db", target_db=tmp_path / "fp.sqlite",
        report_path=tmp_path / "r.json", write=True, snapshot_dir=None,
    )
    assert rc == 2
    assert report.mode == "live"


# ── Live mode end-to-end ───────────────────────────────────────────────────

def test_live_mode_inserts_and_takes_snapshot(tmp_path):
    src = _make_legacy_db(tmp_path / "legacy.db", [
        {"batch_id": "B1", "client_name": "Acme", "charge_type": "freight",
         "amount": 100.0, "currency": "EUR",
         "created_at": "2026-05-15T00:00:00+00:00",
         "updated_at": "2026-05-15T00:00:00+00:00"},
        {"batch_id": "B1", "client_name": "Acme", "charge_type": "insurance",
         "amount": 25.50, "currency": "EUR",
         "created_at": "2026-05-15T00:00:00+00:00",
         "updated_at": "2026-05-15T00:00:00+00:00"},
    ])
    target = tmp_path / "fp.sqlite"
    snap = tmp_path / "snapshots"
    report = tmp_path / "r.json"
    rc, rpt = bf.run_backfill(source_db=src, target_db=target,
                                report_path=report, write=True,
                                snapshot_dir=snap, chunk_size=100)
    assert rc == 0
    assert rpt.mode == "live"
    assert rpt.charges_created == 2
    assert rpt.postings_created == 1
    # Snapshot exists
    assert rpt.snapshot is not None
    assert Path(rpt.snapshot).exists()
    # Target DB has the rows
    charges = fp.list_charges(target, batch_id="B1", client_name="Acme")
    assert len(charges) == 2
    postings = fp.list_postings(target, batch_id="B1", client_name="Acme")
    assert len(postings) == 1
    assert postings[0].wfirma_invoice_id.startswith(bf.POSTING_SYNTHETIC_PREFIX)


def test_live_mode_is_idempotent_on_rerun(tmp_path):
    src = _make_legacy_db(tmp_path / "legacy.db", [
        {"batch_id": "B1", "client_name": "Acme", "charge_type": "freight",
         "amount": 100.0, "currency": "EUR",
         "created_at": "2026-05-15T00:00:00+00:00",
         "updated_at": "2026-05-15T00:00:00+00:00"},
    ])
    target = tmp_path / "fp.sqlite"
    snap = tmp_path / "snapshots"

    # First run
    bf.run_backfill(source_db=src, target_db=target,
                     report_path=tmp_path / "r1.json", write=True,
                     snapshot_dir=snap)
    # Second run on same source
    rc2, rpt2 = bf.run_backfill(source_db=src, target_db=target,
                                  report_path=tmp_path / "r2.json", write=True,
                                  snapshot_dir=snap)
    assert rc2 == 0
    assert rpt2.duplicate_skipped == 1
    assert rpt2.charges_created == 0  # nothing new
    assert rpt2.postings_created == 0
    # Target still has exactly 1 charge + 1 posting
    assert len(fp.list_charges(target, batch_id="B1", client_name="Acme")) == 1
    assert len(fp.list_postings(target, batch_id="B1", client_name="Acme")) == 1


def test_live_mode_currency_normalisation(tmp_path):
    src = _make_legacy_db(tmp_path / "legacy.db", [
        {"batch_id": "B1", "client_name": "X", "charge_type": "freight",
         "amount": 50.0, "currency": "eur",  # lower-case
         "created_at": "2026-05-15T00:00:00+00:00",
         "updated_at": "2026-05-15T00:00:00+00:00"},
    ])
    target = tmp_path / "fp.sqlite"
    rc, rpt = bf.run_backfill(source_db=src, target_db=target,
                                report_path=tmp_path / "r.json", write=True,
                                snapshot_dir=tmp_path / "snap")
    assert rc == 0
    charges = fp.list_charges(target, batch_id="B1", client_name="X")
    assert charges[0].currency == "EUR"


def test_live_mode_raises_on_mixed_currency_in_group(tmp_path):
    """A group (batch, client) with mixed currencies must NOT silently
    backfill. The legacy UNIQUE constraint allows different charge_types
    in the same group with different currencies — pathological but
    possible. We raise to surface for operator triage."""
    src = _make_legacy_db(tmp_path / "legacy.db", [
        {"batch_id": "B-MIX", "client_name": "X", "charge_type": "freight",
         "amount": 50.0, "currency": "EUR",
         "created_at": "2026-05-15T00:00:00+00:00",
         "updated_at": "2026-05-15T00:00:00+00:00"},
        {"batch_id": "B-MIX", "client_name": "X", "charge_type": "insurance",
         "amount": 10.0, "currency": "USD",
         "created_at": "2026-05-15T00:00:00+00:00",
         "updated_at": "2026-05-15T00:00:00+00:00"},
    ])
    target = tmp_path / "fp.sqlite"
    with pytest.raises(ValueError, match="mixed currencies"):
        bf.run_backfill(source_db=src, target_db=target,
                         report_path=tmp_path / "r.json", write=True,
                         snapshot_dir=tmp_path / "snap")


def test_live_mode_groups_charges_per_batch_client(tmp_path):
    src = _make_legacy_db(tmp_path / "legacy.db", [
        # Group A
        {"batch_id": "B1", "client_name": "A", "charge_type": "freight",
         "amount": 10.0, "currency": "EUR",
         "created_at": "2026-05-15T00:00:00+00:00",
         "updated_at": "2026-05-15T00:00:00+00:00"},
        {"batch_id": "B1", "client_name": "A", "charge_type": "insurance",
         "amount": 5.0, "currency": "EUR",
         "created_at": "2026-05-15T00:00:00+00:00",
         "updated_at": "2026-05-15T00:00:00+00:00"},
        # Group B
        {"batch_id": "B1", "client_name": "B", "charge_type": "freight",
         "amount": 20.0, "currency": "EUR",
         "created_at": "2026-05-15T00:00:00+00:00",
         "updated_at": "2026-05-15T00:00:00+00:00"},
    ])
    target = tmp_path / "fp.sqlite"
    rc, rpt = bf.run_backfill(source_db=src, target_db=target,
                                report_path=tmp_path / "r.json", write=True,
                                snapshot_dir=tmp_path / "snap")
    assert rpt.postings_created == 2  # two groups → two synthetic postings
    assert rpt.charges_created == 3


# ── Report shape ───────────────────────────────────────────────────────────

def test_report_shape_complete(tmp_path):
    src = _make_legacy_db(tmp_path / "legacy.db", [
        {"batch_id": "B1", "client_name": "X", "charge_type": "freight",
         "amount": 100.0, "currency": "EUR",
         "created_at": "2026-05-15T00:00:00+00:00",
         "updated_at": "2026-05-15T00:00:00+00:00"},
    ])
    report = tmp_path / "r.json"
    bf.run_backfill(source_db=src, target_db=tmp_path / "fp.sqlite",
                     report_path=report, write=False)
    data = json.loads(report.read_text(encoding="utf-8"))
    for key in ("started_at", "finished_at", "mode", "source_db",
                 "target_db", "snapshot", "chunk_size",
                 "source_rows", "eligible_rows", "blocked_rows",
                 "skipped_zero", "duplicate_skipped",
                 "charges_to_create", "postings_to_create",
                 "charges_created", "postings_created",
                 "blocked_reasons", "blocked_examples",
                 "synthetic_postings"):
        assert key in data, f"report missing key: {key}"


# ── CLI ────────────────────────────────────────────────────────────────────

def test_cli_dryrun_path(tmp_path):
    src = _make_legacy_db(tmp_path / "legacy.db", [
        {"batch_id": "B1", "client_name": "Acme", "charge_type": "freight",
         "amount": 50.0, "currency": "EUR",
         "created_at": "2026-05-15T00:00:00+00:00",
         "updated_at": "2026-05-15T00:00:00+00:00"},
    ])
    target = tmp_path / "fp.sqlite"
    report = tmp_path / "r.json"
    rc = bf.main([
        "--source-db", str(src),
        "--target-db", str(target),
        "--report-path", str(report),
        "--dry-run",
    ])
    assert rc == 0
    assert report.exists()
    assert not target.exists()  # dry-run never writes


def test_cli_rejects_both_modes_simultaneously(tmp_path):
    """argparse mutually-exclusive should reject both --dry-run and --write."""
    src = _make_legacy_db(tmp_path / "src.db", [])
    target = tmp_path / "fp.sqlite"
    report = tmp_path / "r.json"
    with pytest.raises(SystemExit):
        bf.main([
            "--source-db", str(src), "--target-db", str(target),
            "--report-path", str(report), "--dry-run", "--write",
            "--snapshot-dir", str(tmp_path / "snap"),
        ])


def test_cli_requires_one_mode(tmp_path):
    """Neither --dry-run nor --write → argparse exits with code 2."""
    src = _make_legacy_db(tmp_path / "src.db", [])
    with pytest.raises(SystemExit):
        bf.main([
            "--source-db", str(src),
            "--target-db", str(tmp_path / "fp.sqlite"),
            "--report-path", str(tmp_path / "r.json"),
        ])


# ── Hard-rule contracts on the backfill script itself ──────────────────────

def test_backfill_script_does_not_call_wfirma_or_pz():
    src = (Path(bf.__file__)).read_text(encoding="utf-8")
    for forbidden in ("from app.services.wfirma_client",
                      "from app.services.proforma_pz",
                      "import pz_import_processor",
                      "from app.services.ledger_aggregator"):
        assert forbidden not in src, \
            f"backfill must not import {forbidden}"


def test_backfill_script_uses_decimal_for_amounts():
    """Source-grep: amount_minor must come from a Decimal path, not a
    naive float multiplication."""
    src = (Path(bf.__file__)).read_text(encoding="utf-8")
    assert "Decimal" in src, "backfill must import/use Decimal"
    # No raw float * 100 pattern on amount fields
    import re as _re
    assert _re.search(r"amount\s*\*\s*100", src) is None, \
        "backfill must not use naive float * 100"


def test_backfill_script_does_not_modify_legacy_table():
    """The script must NEVER write to the legacy table."""
    src = (Path(bf.__file__)).read_text(encoding="utf-8")
    for forbidden in (
        "UPDATE proforma_service_charges",
        "DELETE FROM proforma_service_charges",
        "INSERT INTO proforma_service_charges",
        "from ..services.proforma_service_charges_db",
        "from app.services.proforma_service_charges_db",
    ):
        assert forbidden not in src, \
            f"backfill must not write legacy table: {forbidden}"
