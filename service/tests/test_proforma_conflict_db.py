"""
test_proforma_conflict_db.py — ADR-029 PR-1 conflict-store unit tests.

Exercises the store contract directly against a tmp_path sqlite file:
  • init_db idempotency
  • upsert insert / refresh / terminal-no-resurrect
  • list / get
  • has_open_blocking_conflict (OPEN + error ONLY)
  • resolve (each resolution_type → status mapping)
  • validation errors

The store calls audit_safe() on every write; audit_safe swallows any audit
failure (returns -2) so these tests do not need a configured audit DB.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.services import proforma_conflict_db as pcdb
from app.services.proforma_conflict_db import (
    ProformaConflict,
    STATUS_OPEN,
    STATUS_ACKNOWLEDGED,
    STATUS_RESOLVED,
    STATUS_REVERTED,
)


@pytest.fixture(autouse=True)
def _isolate_storage(tmp_path):
    """Point storage_root at tmp_path so audit_safe()'s master_audit write
    (fired on every upsert/resolve) lands in the temp tree, not a live root —
    keeps the conftest storage-leak guard happy."""
    from app.core.config import settings
    with patch.object(settings, "storage_root", tmp_path):
        yield


def _db(tmp_path):
    return tmp_path / "proforma_conflicts.db"


def _seed(db, **over):
    """Insert one open conflict with sensible defaults; return the row."""
    base = dict(
        proforma_id="42",
        conflict_type="currency_vs_customer_default",
        severity="warning",
        authority_owner="Customer Service",
        field_affected="currency",
        current_value="USD",
        master_value="EUR",
        reason="draft currency USD differs from customer default EUR",
    )
    base.update(over)
    return pcdb.upsert_conflict(db, **base)


# ── init_db ──────────────────────────────────────────────────────────────────

def test_init_db_idempotent(tmp_path):
    db = _db(tmp_path)
    pcdb.init_db(db)
    pcdb.init_db(db)  # second call must not raise
    assert pcdb.list_conflicts(db, "42") == []


# ── upsert: insert ───────────────────────────────────────────────────────────

def test_upsert_inserts_open_conflict(tmp_path):
    db = _db(tmp_path)
    out = _seed(db)
    assert isinstance(out, ProformaConflict)
    assert out.conflict_id > 0
    assert out.status == STATUS_OPEN
    assert out.severity == "warning"
    assert out.current_value == "USD"
    assert out.master_value == "EUR"
    assert out.resolved_at is None


# ── upsert: refresh (same idempotency key, still open) ────────────────────────

def test_upsert_refreshes_open_conflict_in_place(tmp_path):
    db = _db(tmp_path)
    first = _seed(db, current_value="USD", master_value="EUR")
    second = _seed(db, current_value="GBP", master_value="EUR",
                   severity="warning", reason="now GBP")
    # Same idempotency key → SAME row id, refreshed facts.
    assert second.conflict_id == first.conflict_id
    assert second.current_value == "GBP"
    assert second.reason == "now GBP"
    assert len(pcdb.list_conflicts(db, "42")) == 1


# ── upsert: evidence_json immutability (B3 — written once at INSERT) ───────────

def test_evidence_json_immutable_on_redetect(tmp_path):
    """evidence_json is captured at INSERT and must NOT be overwritten when an
    open conflict is re-detected. Immutability is enforced *by omission* — the
    column is absent from the UPDATE SET clause — so this test pins the contract
    against a future edit silently starting to mutate frozen evidence."""
    db = _db(tmp_path)
    evidence_a = {"semantic": "divergence_not_temporal_drift", "snapshot": "A"}
    first = _seed(db, current_value="USD", evidence=evidence_a)
    assert pcdb.get_conflict(db, first.conflict_id).evidence == evidence_a

    # Re-detect the SAME idempotency key (still open) with refreshed facts AND a
    # different evidence payload — the UPDATE path must leave evidence untouched.
    evidence_b = {"semantic": "divergence_not_temporal_drift", "snapshot": "B"}
    second = _seed(db, current_value="GBP", reason="now GBP", evidence=evidence_b)

    assert second.conflict_id == first.conflict_id        # in-place update, no new row
    stored = pcdb.get_conflict(db, first.conflict_id)
    assert stored.current_value == "GBP"                  # detection facts DID refresh
    assert stored.evidence == evidence_a                  # evidence did NOT change
    assert stored.evidence != evidence_b


# ── upsert: terminal rows are not resurrected ─────────────────────────────────

def test_upsert_does_not_resurrect_resolved(tmp_path):
    db = _db(tmp_path)
    seeded = _seed(db)
    pcdb.resolve_conflict(
        db, seeded.conflict_id,
        resolution_type="use_master_default",
        resolution_reason=None, resolved_by="operator-1",
    )
    # Re-scan detects same drift → must NOT flip it back to open.
    re = _seed(db, current_value="USD", master_value="EUR")
    assert re.conflict_id == seeded.conflict_id
    assert re.status == STATUS_RESOLVED
    assert re.resolution_type == "use_master_default"


def test_upsert_does_not_resurrect_reverted(tmp_path):
    db = _db(tmp_path)
    seeded = _seed(db)
    pcdb.resolve_conflict(
        db, seeded.conflict_id, resolution_type="revert",
        resolution_reason=None, resolved_by="operator-1",
    )
    re = _seed(db)
    assert re.status == STATUS_REVERTED


def test_upsert_does_not_resurrect_acknowledged(tmp_path):
    db = _db(tmp_path)
    seeded = _seed(db)
    pcdb.resolve_conflict(
        db, seeded.conflict_id, resolution_type="accept_and_proceed",
        resolution_reason=None, resolved_by="operator-1",
    )
    re = _seed(db)
    assert re.status == STATUS_ACKNOWLEDGED


# ── different field_affected → distinct rows ──────────────────────────────────

def test_distinct_field_affected_are_separate_rows(tmp_path):
    db = _db(tmp_path)
    _seed(db, conflict_type="service_charge_defaults_changed",
          field_affected="service_charge.freight", current_value="75",
          master_value="50", authority_owner="Customer Service / Finance")
    _seed(db, conflict_type="service_charge_defaults_changed",
          field_affected="service_charge.insurance", current_value="30",
          master_value="20", authority_owner="Customer Service / Finance")
    assert len(pcdb.list_conflicts(db, "42")) == 2


# ── list / get ────────────────────────────────────────────────────────────────

def test_list_filters_by_status(tmp_path):
    db = _db(tmp_path)
    a = _seed(db, field_affected="currency")
    b = _seed(db, conflict_type="bank_account_currency_unsupported",
              field_affected="bank_account_currency", severity="error",
              current_value="GBP", master_value=None,
              authority_owner="Proforma / Finance",
              reason="GBP has no company bank account")
    pcdb.resolve_conflict(db, a.conflict_id, resolution_type="revert",
                          resolution_reason=None, resolved_by="op")
    open_only = pcdb.list_conflicts(db, "42", statuses=[STATUS_OPEN])
    assert [c.conflict_id for c in open_only] == [b.conflict_id]
    reverted = pcdb.list_conflicts(db, "42", statuses=[STATUS_REVERTED])
    assert [c.conflict_id for c in reverted] == [a.conflict_id]


def test_get_conflict_roundtrip_and_missing(tmp_path):
    db = _db(tmp_path)
    seeded = _seed(db)
    got = pcdb.get_conflict(db, seeded.conflict_id)
    assert got is not None and got.conflict_id == seeded.conflict_id
    assert pcdb.get_conflict(db, 999999) is None


# ── has_open_blocking_conflict ────────────────────────────────────────────────

def test_blocking_predicate_true_only_for_open_error(tmp_path):
    db = _db(tmp_path)
    # An open WARNING does not block.
    _seed(db, field_affected="currency", severity="warning")
    assert pcdb.has_open_blocking_conflict(db, "42") is False
    # An open ERROR blocks.
    err = _seed(db, conflict_type="bank_account_currency_unsupported",
                field_affected="bank_account_currency", severity="error",
                current_value="GBP", master_value=None,
                authority_owner="Proforma / Finance",
                reason="GBP unsupported")
    assert pcdb.has_open_blocking_conflict(db, "42") is True
    # Acknowledging the error clears the block.
    pcdb.resolve_conflict(db, err.conflict_id, resolution_type="accept_and_proceed",
                          resolution_reason=None, resolved_by="op")
    assert pcdb.has_open_blocking_conflict(db, "42") is False


def test_blocking_predicate_isolated_per_proforma(tmp_path):
    db = _db(tmp_path)
    _seed(db, proforma_id="100", conflict_type="bank_account_currency_unsupported",
          field_affected="bank_account_currency", severity="error",
          current_value="GBP", master_value=None,
          authority_owner="Proforma / Finance", reason="GBP unsupported")
    assert pcdb.has_open_blocking_conflict(db, "100") is True
    assert pcdb.has_open_blocking_conflict(db, "999") is False


# ── resolve: status mapping ───────────────────────────────────────────────────

@pytest.mark.parametrize("rtype,expected", [
    ("use_master_default",   STATUS_RESOLVED),
    ("override_with_reason", STATUS_RESOLVED),
    ("regenerate_lines",     STATUS_RESOLVED),
    ("accept_and_proceed",   STATUS_ACKNOWLEDGED),
    ("revert",               STATUS_REVERTED),
])
def test_resolve_status_mapping(tmp_path, rtype, expected):
    db = _db(tmp_path)
    seeded = _seed(db)
    reason = "operator override" if rtype == "override_with_reason" else None
    out = pcdb.resolve_conflict(
        db, seeded.conflict_id, resolution_type=rtype,
        resolution_reason=reason, resolved_by="operator-9",
    )
    assert out.status == expected
    assert out.resolution_type == rtype
    assert out.resolved_by == "operator-9"
    assert out.resolved_at is not None


# ── resolve: validation errors ────────────────────────────────────────────────

def test_resolve_unknown_id_raises(tmp_path):
    db = _db(tmp_path)
    with pytest.raises(ValueError, match="not found"):
        pcdb.resolve_conflict(db, 123456, resolution_type="revert",
                              resolution_reason=None, resolved_by="op")


def test_resolve_invalid_type_raises(tmp_path):
    db = _db(tmp_path)
    seeded = _seed(db)
    with pytest.raises(ValueError, match="resolution_type"):
        pcdb.resolve_conflict(db, seeded.conflict_id, resolution_type="nope",
                              resolution_reason=None, resolved_by="op")


def test_resolve_override_requires_reason(tmp_path):
    db = _db(tmp_path)
    seeded = _seed(db)
    with pytest.raises(ValueError, match="non-empty resolution_reason"):
        pcdb.resolve_conflict(db, seeded.conflict_id,
                              resolution_type="override_with_reason",
                              resolution_reason="   ", resolved_by="op")


def test_resolve_requires_resolved_by(tmp_path):
    db = _db(tmp_path)
    seeded = _seed(db)
    with pytest.raises(ValueError, match="resolved_by"):
        pcdb.resolve_conflict(db, seeded.conflict_id,
                              resolution_type="revert",
                              resolution_reason=None, resolved_by="  ")


def test_resolve_terminal_row_cannot_be_re_resolved(tmp_path):
    # A committed operator decision is terminal — a second resolve must raise,
    # not silently overwrite resolution_type/reason/resolved_by (symmetric to
    # upsert's no-resurrect guard; keeps the §5 posting gate tamper-safe).
    db = _db(tmp_path)
    seeded = _seed(db)
    first = pcdb.resolve_conflict(
        db, seeded.conflict_id, resolution_type="use_master_default",
        resolution_reason=None, resolved_by="operator-1",
    )
    assert first.status == STATUS_RESOLVED
    with pytest.raises(ValueError, match="terminal status"):
        pcdb.resolve_conflict(
            db, seeded.conflict_id, resolution_type="override_with_reason",
            resolution_reason="trying to overwrite", resolved_by="operator-2",
        )
    # The original decision is intact — no silent mutation occurred.
    after = pcdb.get_conflict(db, seeded.conflict_id)
    assert after.status == STATUS_RESOLVED
    assert after.resolution_type == "use_master_default"
    assert after.resolved_by == "operator-1"


# ── upsert: detection-payload validation ──────────────────────────────────────

def test_upsert_unknown_conflict_type_raises(tmp_path):
    db = _db(tmp_path)
    with pytest.raises(ValueError, match="unknown conflict_type"):
        _seed(db, conflict_type="not_a_real_type")


def test_upsert_bad_severity_raises(tmp_path):
    db = _db(tmp_path)
    with pytest.raises(ValueError, match="severity"):
        _seed(db, severity="critical")


def test_upsert_missing_authority_owner_raises(tmp_path):
    db = _db(tmp_path)
    with pytest.raises(ValueError, match="authority_owner"):
        _seed(db, authority_owner="  ")


def test_upsert_missing_field_affected_raises(tmp_path):
    db = _db(tmp_path)
    with pytest.raises(ValueError, match="field_affected"):
        _seed(db, field_affected="")


def test_upsert_missing_reason_raises(tmp_path):
    db = _db(tmp_path)
    with pytest.raises(ValueError, match="reason"):
        _seed(db, reason="")


def test_upsert_missing_proforma_id_raises(tmp_path):
    db = _db(tmp_path)
    with pytest.raises(ValueError, match="proforma_id"):
        _seed(db, proforma_id="   ")
