"""Payment deletion convergence — lifecycle authority and its fail-safe matrix.

ROOT CAUSE this pins: the payment sync was forward-only (INSERT OR IGNORE, "does
not delete snapshots"), so a payment deleted in wFirma stayed financially active
locally and kept reducing AR/AP forever. wFirma exposes NO deletion flag on
<payment> — the only ``*_del`` tags are compensation_del / interest_del, which are
AMOUNTS — so deletion can only be detected by set reconciliation against a
COMPLETE contractor fetch.

That makes the completeness of the fetch load-bearing, and it cuts both ways:

  * a failed / timed-out / TRUNCATED fetch must never tombstone anything, or a
    transient upstream hiccup silently deletes valid payments and AR/AP jumps up;
  * a SUCCESSFUL fetch returning ZERO payments is a legitimate result and MUST
    tombstone — a contractor whose every payment was deleted upstream reports
    exactly zero. The distinction comes from the error channel and the paginator
    stop reason, NEVER from the row count.

All fixtures here are SYNTHETIC (repo is public): invented ids in a reserved
range, placeholder names, round amounts. No real customer, payment or balance.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from app.services import wfirma_client
from app.services.wfirma_payment_db import (
    init_payment_db,
    list_payments_as_of,
    list_tombstoned_payments,
    payment_lifecycle_stats,
    reconcile_contractor_payments,
)
from app.services.wfirma_payment_sync_processor import sync_payments_for_contractor

CONTRACTOR = "70000001"
OTHER_CONTRACTOR = "70000002"
NOW = "2026-01-02T00:00:00+00:00"
AS_OF = "2026-12-31"

# Synthetic payments: one linked to an invoice (AR), one to an expense (AP),
# one unapplied (linked to neither).
P_AR = "800000001"
P_AP = "800000002"
P_UNAPPLIED = "800000003"
INVOICE = "900000001"
EXPENSE = "900000002"


def _payment_xml(payment_id, *, invoice_id=None, expense_id=None, value="100.00"):
    inv = f"<invoice><id>{invoice_id or 0}</id></invoice>"
    exp = f"<expense><id>{expense_id or 0}</id></expense>"
    return ET.fromstring(
        f"<payment><id>{payment_id}</id>"
        f"<contractor><id>{CONTRACTOR}</id></contractor>"
        f"{inv}{exp}"
        f"<date>2026-01-01</date><value>{value}</value><value_pln>{value}</value_pln>"
        f"<currency_label>USD</currency_label><payment_method>transfer</payment_method>"
        f"<payment_type>payment</payment_type><type>payment</type>"
        f"<notes>synthetic fixture</notes></payment>"
    )


ALL_NODES = [
    _payment_xml(P_AR, invoice_id=INVOICE),
    _payment_xml(P_AP, expense_id=EXPENSE),
    _payment_xml(P_UNAPPLIED, value="7.00"),
]


@pytest.fixture
def db(tmp_path):
    p = tmp_path / "payment_state.db"
    init_payment_db(p)
    return p


def _fake_fetch(nodes, *, stop_reason="short", raises=None):
    """Stand-in for the read-only wFirma paginator."""
    def _fetch(contractor_id, date_from, date_to, stats=None):
        if raises is not None:
            raise raises
        if stats is not None:
            stats["stopped_reason"] = stop_reason
            stats["items_kept"] = len(nodes)
        return list(nodes)
    return _fetch


def _seed(db, monkeypatch, nodes=ALL_NODES):
    """Populate the db through the real sync path, then assert it landed."""
    monkeypatch.setattr(
        wfirma_client, "fetch_payments_for_contractor", _fake_fetch(nodes)
    )
    sync_payments_for_contractor(contractor_id=CONTRACTOR, payment_db=db, now=NOW)
    assert len(list_payments_as_of(db, AS_OF)) == len(nodes)


def _active_ids(db):
    return {r["payment_id"] for r in list_payments_as_of(db, AS_OF)}


def _all_ids(db):
    """Every row on disk, active or tombstoned — proves nothing was deleted."""
    return _active_ids(db) | {
        r["payment_id"] for r in list_tombstoned_payments(db)
    }


# --------------------------------------------------------------------------
# 1-2. A fetch that FAILED must never tombstone.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("exc", [
    RuntimeError("payments\\find wFirma status=ERROR: LIMIT EXCEEDED"),
    ConnectionError("connection reset by peer"),
    TimeoutError("read timed out"),
])
def test_failed_fetch_never_tombstones(db, monkeypatch, exc):
    _seed(db, monkeypatch)
    monkeypatch.setattr(
        wfirma_client, "fetch_payments_for_contractor",
        _fake_fetch([], raises=exc),
    )
    new, existing, err = sync_payments_for_contractor(
        contractor_id=CONTRACTOR, payment_db=db, now=NOW
    )
    assert err, "a failed fetch must report through the error channel"
    assert (new, existing) == (0, 0)
    assert _active_ids(db) == {P_AR, P_AP, P_UNAPPLIED}
    assert list_tombstoned_payments(db) == []


# --------------------------------------------------------------------------
# 3. A TRUNCATED-but-not-failed fetch must never tombstone. This is the
#    adversarial case: the paginator returns a PARTIAL set without raising.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("stop_reason", ["safety_cap", "no_new_ids", "", None])
def test_partial_fetch_never_tombstones(db, monkeypatch, stop_reason):
    _seed(db, monkeypatch)
    # Upstream "loses" two payments, but the paginator also reports that it did
    # not exhaust the collection. Absence is therefore not evidence of deletion.
    monkeypatch.setattr(
        wfirma_client, "fetch_payments_for_contractor",
        _fake_fetch([ALL_NODES[0]], stop_reason=stop_reason),
    )
    _, _, err = sync_payments_for_contractor(
        contractor_id=CONTRACTOR, payment_db=db, now=NOW
    )
    assert err is None
    assert _active_ids(db) == {P_AR, P_AP, P_UNAPPLIED}


def test_node_without_id_blocks_reconciliation(db, monkeypatch):
    """An unidentifiable node makes the live set unreliable — fail closed."""
    _seed(db, monkeypatch)
    anon = ET.fromstring("<payment><value>1.00</value></payment>")
    monkeypatch.setattr(
        wfirma_client, "fetch_payments_for_contractor",
        _fake_fetch([ALL_NODES[0], anon]),
    )
    sync_payments_for_contractor(contractor_id=CONTRACTOR, payment_db=db, now=NOW)
    assert _active_ids(db) == {P_AR, P_AP, P_UNAPPLIED}


# --------------------------------------------------------------------------
# 4. A SUCCESSFUL zero-result fetch IS valid and MUST tombstone.
#    (The production fixture for this is a real contractor whose only payment
#    was deleted upstream; it now legitimately returns zero.)
# --------------------------------------------------------------------------

def test_successful_zero_result_tombstones_all(db, monkeypatch):
    _seed(db, monkeypatch)
    monkeypatch.setattr(
        wfirma_client, "fetch_payments_for_contractor",
        _fake_fetch([], stop_reason="empty"),
    )
    _, _, err = sync_payments_for_contractor(
        contractor_id=CONTRACTOR, payment_db=db, now=NOW
    )
    assert err is None, "zero payments is a RESULT, not an error"
    assert _active_ids(db) == set()
    assert _all_ids(db) == {P_AR, P_AP, P_UNAPPLIED}, "no row may be deleted"


# --------------------------------------------------------------------------
# 5. A subset tombstones ONLY the missing id. This is the root-cause pin: the
#    deleted payment stops participating, and the money moves only because of
#    that — nothing patches a balance.
# --------------------------------------------------------------------------

def test_subset_tombstones_only_the_missing_payment(db, monkeypatch):
    _seed(db, monkeypatch)
    before = list_payments_as_of(db, AS_OF, invoice_ids=[INVOICE])
    assert [r["payment_id"] for r in before] == [P_AR]

    monkeypatch.setattr(
        wfirma_client, "fetch_payments_for_contractor",
        _fake_fetch([ALL_NODES[1], ALL_NODES[2]]),  # P_AR deleted upstream
    )
    sync_payments_for_contractor(contractor_id=CONTRACTOR, payment_db=db, now=NOW)

    assert _active_ids(db) == {P_AP, P_UNAPPLIED}
    # The invoice's settlement disappears from the shared money read, so the
    # remaining balance rises by exactly this payment. No amount was edited.
    assert list_payments_as_of(db, AS_OF, invoice_ids=[INVOICE]) == []
    tomb = list_tombstoned_payments(db)
    assert [r["payment_id"] for r in tomb] == [P_AR]
    assert tomb[0]["value"] == "100.00", "the audit row keeps its original amount"


def test_reconciliation_is_contractor_scoped(db, monkeypatch):
    """Another contractor's payments are untouched by this one's reconciliation."""
    _seed(db, monkeypatch)
    reconcile_contractor_payments(
        db, contractor_id=OTHER_CONTRACTOR, live_payment_ids=[], now_iso=NOW
    )
    assert _active_ids(db) == {P_AR, P_AP, P_UNAPPLIED}


# --------------------------------------------------------------------------
# 6. Reappearance restores in place — no duplicate row.
# --------------------------------------------------------------------------

def test_reappearance_restores_without_duplicating(db, monkeypatch):
    _seed(db, monkeypatch)
    monkeypatch.setattr(
        wfirma_client, "fetch_payments_for_contractor",
        _fake_fetch([ALL_NODES[1], ALL_NODES[2]]),
    )
    sync_payments_for_contractor(contractor_id=CONTRACTOR, payment_db=db, now=NOW)
    assert _active_ids(db) == {P_AP, P_UNAPPLIED}

    # wFirma restores it (or the deletion was an upstream mistake).
    monkeypatch.setattr(
        wfirma_client, "fetch_payments_for_contractor", _fake_fetch(ALL_NODES)
    )
    sync_payments_for_contractor(contractor_id=CONTRACTOR, payment_db=db, now=NOW)

    rows = list_payments_as_of(db, AS_OF)
    assert _active_ids(db) == {P_AR, P_AP, P_UNAPPLIED}
    assert len(rows) == 3, "restore must not insert a second row"
    assert list_tombstoned_payments(db) == []
    assert payment_lifecycle_stats(db)["payments_restored_ever"] == 1


# --------------------------------------------------------------------------
# 7. Replay is idempotent.
# --------------------------------------------------------------------------

def test_replay_is_idempotent(db, monkeypatch):
    _seed(db, monkeypatch)
    monkeypatch.setattr(
        wfirma_client, "fetch_payments_for_contractor",
        _fake_fetch([ALL_NODES[0]]),
    )
    first = None
    for _ in range(3):
        sync_payments_for_contractor(contractor_id=CONTRACTOR, payment_db=db, now=NOW)
        snapshot = sorted(
            (r["payment_id"], r["source_deleted_at"]) for r in list_tombstoned_payments(db)
        )
        if first is None:
            first = snapshot
        assert snapshot == first, "a replay must not re-stamp or re-tombstone"
    assert _active_ids(db) == {P_AR}


def test_direct_reconcile_replay_is_a_noop(db, monkeypatch):
    _seed(db, monkeypatch)
    args = dict(contractor_id=CONTRACTOR, live_payment_ids=[P_AR], now_iso=NOW)
    first = reconcile_contractor_payments(db, **args)
    second = reconcile_contractor_payments(db, **args)
    assert first["tombstoned"] == 2
    assert second["tombstoned"] == 0 and second["restored"] == 0


# --------------------------------------------------------------------------
# 8. The AP path behaves exactly like the AR path — one shared read, one rule.
# --------------------------------------------------------------------------

def test_ap_expense_linked_payment_follows_the_same_lifecycle(db, monkeypatch):
    _seed(db, monkeypatch)
    ap_before = [
        r for r in list_payments_as_of(db, AS_OF) if r["expense_id"] == EXPENSE
    ]
    assert [r["payment_id"] for r in ap_before] == [P_AP]

    monkeypatch.setattr(
        wfirma_client, "fetch_payments_for_contractor",
        _fake_fetch([ALL_NODES[0], ALL_NODES[2]]),  # AP payment deleted upstream
    )
    sync_payments_for_contractor(contractor_id=CONTRACTOR, payment_db=db, now=NOW)

    assert [r for r in list_payments_as_of(db, AS_OF) if r["expense_id"] == EXPENSE] == []
    assert _active_ids(db) == {P_AR, P_UNAPPLIED}


def test_ap_untouched_when_only_an_ar_payment_is_deleted(db, monkeypatch):
    """Non-regression: AR-side convergence must not disturb AP settlements."""
    _seed(db, monkeypatch)
    monkeypatch.setattr(
        wfirma_client, "fetch_payments_for_contractor",
        _fake_fetch([ALL_NODES[1], ALL_NODES[2]]),
    )
    sync_payments_for_contractor(contractor_id=CONTRACTOR, payment_db=db, now=NOW)
    ap = [r for r in list_payments_as_of(db, AS_OF) if r["expense_id"] == EXPENSE]
    assert len(ap) == 1 and ap[0]["value"] == "100.00"


# --------------------------------------------------------------------------
# 9. A stale UNAPPLIED payment tombstones, but moves no money.
# --------------------------------------------------------------------------

def _linked(db):
    """Payments that actually settle a document. wFirma sends ``id=0`` as the
    no-link sentinel, so a bare truthiness check would count everything."""
    def has(v):
        return (v or "").strip() not in ("", "0")
    return [
        r for r in list_payments_as_of(db, AS_OF)
        if has(r["invoice_id"]) or has(r["expense_id"])
    ]


def test_unapplied_stale_payment_tombstones_with_no_financial_delta(db, monkeypatch):
    _seed(db, monkeypatch)
    linked_before = _linked(db)
    assert {r["payment_id"] for r in linked_before} == {P_AR, P_AP}

    monkeypatch.setattr(
        wfirma_client, "fetch_payments_for_contractor",
        _fake_fetch([ALL_NODES[0], ALL_NODES[1]]),  # only the unapplied one vanishes
    )
    sync_payments_for_contractor(contractor_id=CONTRACTOR, payment_db=db, now=NOW)

    assert [r["payment_id"] for r in list_tombstoned_payments(db)] == [P_UNAPPLIED]
    assert _linked(db) == linked_before, "no settled document may change"


# --------------------------------------------------------------------------
# 10. as_of semantics survive the new predicate, and the audit trail is readable.
# --------------------------------------------------------------------------

def test_as_of_filter_still_applies_alongside_the_lifecycle_filter(db, monkeypatch):
    _seed(db, monkeypatch)
    assert list_payments_as_of(db, "2025-12-31") == [], "dated after as_of"
    assert len(list_payments_as_of(db, "2026-01-01")) == 3
    reconcile_contractor_payments(
        db, contractor_id=CONTRACTOR, live_payment_ids=[P_AR], now_iso=NOW
    )
    # Both predicates hold at once: active AND on/before as_of.
    assert [r["payment_id"] for r in list_payments_as_of(db, "2026-01-01")] == [P_AR]
    assert list_payments_as_of(db, "2025-12-31") == []


def test_tombstone_evidence_is_inspectable(db, monkeypatch):
    _seed(db, monkeypatch)
    reconcile_contractor_payments(
        db, contractor_id=CONTRACTOR, live_payment_ids=[P_AR], now_iso=NOW
    )
    tomb = list_tombstoned_payments(db)
    assert {r["payment_id"] for r in tomb} == {P_AP, P_UNAPPLIED}
    assert all(r["source_deleted_at"] == NOW for r in tomb), "when it happened"
    assert all(r["contractor_id"] == CONTRACTOR for r in tomb), "whose it was"

    stats = payment_lifecycle_stats(db)
    assert stats["payments_total"] == 3
    assert stats["payments_active"] == 1
    assert stats["payments_tombstoned"] == 2
    assert stats["contractors_reconciled"] == 1
    assert stats["last_reconciled_at"] == NOW


def test_pre_migration_rows_read_as_active(db):
    """Backward compatibility: rows written before this change have a NULL
    source_deleted_at and must keep participating in AR/AP untouched."""
    import sqlite3
    with sqlite3.connect(str(db)) as conn:
        conn.execute(
            "INSERT INTO wfirma_payment_snapshots "
            "(payment_id, contractor_id, invoice_id, payment_date, value, "
            " fetched_at, raw_json) VALUES (?,?,?,?,?,?,?)",
            ("800000099", CONTRACTOR, INVOICE, "2026-01-01", "50.00", NOW, "{}"),
        )
        conn.commit()
    rows = list_payments_as_of(db, AS_OF)
    assert [r["payment_id"] for r in rows] == ["800000099"]
    assert payment_lifecycle_stats(db)["payments_tombstoned"] == 0


def test_reconcile_refuses_a_blank_contractor(db):
    with pytest.raises(ValueError):
        reconcile_contractor_payments(
            db, contractor_id="  ", live_payment_ids=[], now_iso=NOW
        )


# --- Phase P: observability ------------------------------------------------
# Stale local payment state is invisible unless the reason convergence did not
# run is durable. These pin that the counters measure what actually happened.

def test_failed_fetch_records_why_convergence_did_not_run(db, monkeypatch):
    _seed(db, monkeypatch)
    monkeypatch.setattr(
        wfirma_client, "fetch_payments_for_contractor",
        _fake_fetch([], raises=ConnectionError("wFirma unreachable")),
    )
    sync_payments_for_contractor(contractor_id=CONTRACTOR, payment_db=db, now=NOW)

    stats = payment_lifecycle_stats(db)
    assert stats["contractors_failing"] == 1
    assert "fetch failed" in stats["last_error"]
    assert stats["last_error_at"] == NOW
    assert stats["payments_tombstoned"] == 0, "a failure must never tombstone"


def test_partial_fetch_records_the_stop_reason(db, monkeypatch):
    _seed(db, monkeypatch)
    monkeypatch.setattr(
        wfirma_client, "fetch_payments_for_contractor",
        _fake_fetch(ALL_NODES, stop_reason="safety_cap"),
    )
    sync_payments_for_contractor(contractor_id=CONTRACTOR, payment_db=db, now=NOW)
    assert "safety_cap" in payment_lifecycle_stats(db)["last_error"]


def test_successful_convergence_clears_a_previous_error(db, monkeypatch):
    _seed(db, monkeypatch)
    monkeypatch.setattr(
        wfirma_client, "fetch_payments_for_contractor",
        _fake_fetch([], raises=TimeoutError("timed out")),
    )
    sync_payments_for_contractor(contractor_id=CONTRACTOR, payment_db=db, now=NOW)
    assert payment_lifecycle_stats(db)["contractors_failing"] == 1

    monkeypatch.setattr(
        wfirma_client, "fetch_payments_for_contractor", _fake_fetch(ALL_NODES),
    )
    sync_payments_for_contractor(contractor_id=CONTRACTOR, payment_db=db, now=NOW)
    stats = payment_lifecycle_stats(db)
    assert stats["contractors_failing"] == 0
    assert stats["last_error"] is None


def test_status_counters_expose_no_identifiers(db, monkeypatch):
    """This dict is rendered on a general status panel, so it must stay
    aggregate-only — no contractor, payment, invoice or expense id, ever."""
    _seed(db, monkeypatch)
    assert set(payment_lifecycle_stats(db)) == {
        "payments_total", "payments_active", "payments_tombstoned",
        "payments_restored_ever", "contractors_reconciled",
        "contractors_failing", "last_reconciled_at", "last_error",
        "last_error_at",
    }
