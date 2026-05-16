"""Phase 6F.5 — Dual-write is idempotent across re-runs.

Re-running the dual-write for the same (batch_id, client_name) tuple must
NOT create duplicate posting or charge rows. Detection uses the sha1
idempotency keys baked into ``wfirma_invoice_id`` (postings) and
``notes`` (charges).
"""
from __future__ import annotations

from pathlib import Path

from app.services import finance_dual_write as fdw
from app.services import finance_postings_db as fpdb


_CHARGES_JSON = (
    '[{"charge_type":"freight","amount":12.34,"currency":"EUR"},'
    ' {"charge_type":"insurance","amount":2.50,"currency":"EUR"}]'
)


def _call(db, **overrides):
    kwargs = dict(
        db_path=db,
        batch_id="B/2026/001",
        client_name="Acme GmbH",
        currency="EUR",
        full_number="FV/PR/1/2026",
        service_charges_json=_CHARGES_JSON,
        enabled=True,
        shadow=False,
    )
    kwargs.update(overrides)
    return fdw.dual_write_proforma_post(**kwargs)


def test_first_run_creates_one_posting_two_charges(tmp_path: Path):
    db = tmp_path / "finance_postings.sqlite"
    res = _call(db)
    assert res["ok"] is True
    assert res["mode"] == "live"
    assert res["created_posting"] is True
    assert res["created_charges"] == 2
    assert res["skipped_charges"] == 0
    postings = fpdb.list_postings(db)
    charges = fpdb.list_charges(db, batch_id="B/2026/001")
    assert len(postings) == 1
    assert len(charges) == 2
    assert postings[0].wfirma_invoice_id.startswith(fdw.POSTING_LIVE_PREFIX)


def test_second_run_creates_nothing(tmp_path: Path):
    db = tmp_path / "finance_postings.sqlite"
    _call(db)
    res2 = _call(db)
    assert res2["ok"] is True
    assert res2["created_posting"] is False
    assert res2["created_charges"] == 0
    assert res2["skipped_charges"] == 2
    assert len(fpdb.list_postings(db)) == 1
    assert len(fpdb.list_charges(db, batch_id="B/2026/001")) == 2


def test_third_run_after_extra_charge_added_only_inserts_new(tmp_path: Path):
    db = tmp_path / "finance_postings.sqlite"
    _call(db)
    # Same tuple but the draft now carries only the freight charge (a real
    # operator could have deleted insurance). The previously-inserted
    # insurance row stays (audit) — the re-run does not duplicate freight
    # and does not insert a new insurance row.
    res = _call(db, service_charges_json='[{"charge_type":"freight","amount":12.34,"currency":"EUR"}]')
    assert res["ok"] is True
    assert res["created_posting"] is False
    assert res["created_charges"] == 0
    assert res["skipped_charges"] == 1
    assert len(fpdb.list_charges(db, batch_id="B/2026/001")) == 2


def test_posting_id_is_stable_across_runs(tmp_path: Path):
    db = tmp_path / "finance_postings.sqlite"
    res1 = _call(db)
    res2 = _call(db)
    assert res1["synthetic_posting_id"] == res2["synthetic_posting_id"]
    assert res1["synthetic_posting_id"].startswith("LIVE-")
    # length: prefix LIVE- (5) + 16 hex chars
    assert len(res1["synthetic_posting_id"]) == 5 + 16
