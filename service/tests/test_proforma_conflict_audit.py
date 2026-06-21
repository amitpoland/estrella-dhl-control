"""
test_proforma_conflict_audit.py — ADR-029 PR-1 audit-behavior tests.

Pins the master_audit contract for the conflict store:
  • detect (new row)  → audit op=create
  • resolve           → audit op=transition
  • audit_safe -2 / failure tolerance: a failing audit MUST NOT corrupt the
    primary conflict write (the row is committed before audit is attempted).

Audit entity is "proforma_conflict" (singular, preserved from #626).
"""
from __future__ import annotations

import pytest

from app.core.config import settings
from app.core.audit import list_audit
from app.services import proforma_conflict_db as pcdb


@pytest.fixture()
def store(tmp_path, monkeypatch):
    # Patch storage_root so the conflict DB AND master_audit.sqlite stay in tmp
    # (also satisfies the conftest storage-root leak guard).
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    db = tmp_path / "proforma_conflicts.db"
    pcdb.init_db(db)
    return db


def _detect(db, **over):
    kw = dict(
        proforma_id="101",
        conflict_type="bank_account_currency_unsupported",
        severity="error",
        authority_owner="Proforma / Finance",
        field_affected="currency",
        current_value="GBP",
        master_value="EUR,PLN,USD",
        reason="GBP has no company bank account",
        actor="amit",
    )
    kw.update(over)
    return pcdb.upsert_conflict(db, **kw)


def test_detect_writes_master_audit_create(store):
    c = _detect(store)
    rows = list_audit(entity="proforma_conflict")
    assert any(r["op"] == "create" and str(r["pk"]) == str(c.conflict_id) for r in rows)


def test_resolve_writes_master_audit_transition(store):
    c = _detect(store)
    pcdb.resolve_conflict(
        store, c.conflict_id,
        resolution_type="accept_and_proceed", resolution_reason=None,
        resolved_by="amit", actor="amit",
    )
    rows = list_audit(entity="proforma_conflict")
    assert any(r["op"] == "transition" and str(r["pk"]) == str(c.conflict_id) for r in rows)


def test_audit_failure_does_not_corrupt_resolve(store, monkeypatch):
    """audit_safe returning -2 (failure) must not break the primary write."""
    c = _detect(store)
    monkeypatch.setattr(pcdb, "audit_safe", lambda *a, **k: -2)
    out = pcdb.resolve_conflict(
        store, c.conflict_id,
        resolution_type="accept_and_proceed", resolution_reason=None,
        resolved_by="amit", actor="amit",
    )
    assert out.status == "acknowledged"                       # accept_and_proceed → acknowledged
    assert pcdb.get_conflict(store, c.conflict_id).status == "acknowledged"


def test_evidence_persisted_and_returned(store):
    """B2/B3: evidence (incl. the divergence marker) round-trips through the store."""
    c = _detect(
        store,
        conflict_type="currency_vs_customer_default", severity="warning",
        authority_owner="Customer Service", field_affected="currency",
        evidence={"semantic": "divergence_not_temporal_drift", "pr2_todo": "PR-2"},
    )
    got = pcdb.get_conflict(store, c.conflict_id)
    assert got.evidence == {"semantic": "divergence_not_temporal_drift", "pr2_todo": "PR-2"}
