"""
test_audit_persist.py — Append-only audit hardening helpers.

Pins:
  1. restamp_pz_status_if_done flips stale "failed" → "partial" when
     the operator-effective normalization says done.
  2. record_proforma_issued appends to audit.proforma_issued[] AND emits
     a timeline event. Idempotent on wfirma_proforma_id.
  3. record_inventory_direct_dispatch appends a timeline event.
  4. reconcile_from_timeline rebuilds wfirma_export.wfirma_pz_doc_id from
     a wfirma_pz_created timeline event when the export block is empty.
  5. After hardening, effective_pz_evidence reports has_evidence=True via
     the canonical signals (wfirma_export.wfirma_pz_doc_id) — restart-safe
     without depending on the timeline-only fallback.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.audit_persist import (
    EV_PROFORMA_ISSUED,
    EV_INVENTORY_DIRECT_DISPATCH_MARKED,
    record_inventory_direct_dispatch,
    record_proforma_issued,
    reconcile_from_timeline,
    restamp_pz_status_if_done,
)
from app.services.audit_evidence import effective_pz_evidence


def _stale_audit_with_pz_done() -> dict:
    """Stored status="failed" but operator-effective normalization should
    mark this as PZ-done: empty failed_checks + MRN populated + cn_match."""
    return {
        "status": "failed",
        "failed_checks": [],
        "customs_declaration": {"mrn": "26PL44302D00AUCWR3"},
        "verification": {"cn_match": True},
        "wfirma_export": {"wfirma_pz_doc_id": "183484963",
                          "pz_source": "created_via_app",
                          "pz_created_at": "2026-05-08T14:38:27"},
        "timeline": [
            {"ts": "2026-05-08T14:38:27+00:00",
             "event": "wfirma_pz_created", "trigger_source": "system",
             "actor": "wfirma",
             "detail": {"batch_id": "B", "wfirma_pz_doc_id": "183484963",
                        "line_count": 9}},
        ],
    }


def _stale_audit_export_empty() -> dict:
    """Worst case: status=failed, wfirma_export empty, only the timeline
    carries the doc id. Reconcile should restore the canonical field."""
    a = _stale_audit_with_pz_done()
    a["wfirma_export"] = {}
    return a


def _write(tmp_path: Path, audit: dict) -> Path:
    p = tmp_path / "audit.json"
    p.write_text(json.dumps(audit), encoding="utf-8")
    return p


# ── 1. Stale audit repaired by status restamp ───────────────────────────────

def test_restamp_pz_status_if_done_flips_failed_to_partial(tmp_path):
    p = _write(tmp_path, _stale_audit_with_pz_done())
    r = restamp_pz_status_if_done(p)
    assert r["changed"] is True
    assert r["stored_before"] == "failed"
    assert r["stored_after"]  == "partial"
    assert r["effective"]     == "partial"
    on_disk = json.loads(p.read_text())
    assert on_disk["status"] == "partial"


def test_restamp_pz_status_if_done_idempotent(tmp_path):
    p = _write(tmp_path, _stale_audit_with_pz_done())
    restamp_pz_status_if_done(p)
    second = restamp_pz_status_if_done(p)
    assert second["changed"] is False
    assert second["reason"] == "already aligned"


def test_restamp_pz_status_no_change_when_evidence_missing(tmp_path):
    # No MRN, no cn_match → effective remains "failed".
    p = _write(tmp_path, {"status": "failed", "failed_checks": []})
    r = restamp_pz_status_if_done(p)
    assert r["changed"] is False
    assert json.loads(p.read_text())["status"] == "failed"


def test_restamp_pz_status_does_not_demote_success(tmp_path):
    """Defence: a successful audit must never be touched."""
    p = _write(tmp_path, {"status": "success",
                           "customs_declaration": {"mrn": "X"},
                           "verification": {"cn_match": True}})
    r = restamp_pz_status_if_done(p)
    assert r["changed"] is False
    assert json.loads(p.read_text())["status"] == "success"


def test_restamp_handles_missing_audit(tmp_path):
    r = restamp_pz_status_if_done(tmp_path / "nope.json")
    assert r["changed"] is False
    assert "missing" in r["reason"]


# ── 2. record_proforma_issued ───────────────────────────────────────────────

def test_record_proforma_issued_appends_and_logs_timeline(tmp_path):
    p = _write(tmp_path, _stale_audit_with_pz_done())
    r = record_proforma_issued(
        p, batch_id="B", client_name="ACME",
        wfirma_proforma_id="467222691", line_count=3,
        currency="USD", operator="amit",
    )
    assert r["appended"] is True
    a = json.loads(p.read_text())
    assert len(a["proforma_issued"]) == 1
    row = a["proforma_issued"][0]
    assert row["wfirma_proforma_id"] == "467222691"
    assert row["client_name"]        == "ACME"
    assert row["line_count"]         == 3
    # Timeline event present.
    events = [e for e in a["timeline"] if e.get("event") == EV_PROFORMA_ISSUED]
    assert len(events) == 1
    assert events[0]["detail"]["wfirma_proforma_id"] == "467222691"


def test_record_proforma_issued_idempotent(tmp_path):
    p = _write(tmp_path, _stale_audit_with_pz_done())
    record_proforma_issued(p, batch_id="B", client_name="A",
                           wfirma_proforma_id="ID-1", line_count=1,
                           currency="USD", operator="amit")
    second = record_proforma_issued(p, batch_id="B", client_name="A",
                                     wfirma_proforma_id="ID-1", line_count=1,
                                     currency="USD", operator="amit")
    assert second["appended"] is False
    assert second["reason"]   == "already recorded"
    a = json.loads(p.read_text())
    assert len(a["proforma_issued"]) == 1
    # Timeline must not duplicate either.
    assert sum(1 for e in a["timeline"]
               if e.get("event") == EV_PROFORMA_ISSUED) == 1


def test_record_proforma_issued_rejects_empty_id(tmp_path):
    p = _write(tmp_path, _stale_audit_with_pz_done())
    r = record_proforma_issued(p, batch_id="B", client_name="A",
                                wfirma_proforma_id="", line_count=1,
                                currency="USD", operator="amit")
    assert r["appended"] is False
    assert "empty" in r["reason"]


def test_record_proforma_issued_supports_multiple_clients(tmp_path):
    p = _write(tmp_path, _stale_audit_with_pz_done())
    for cn, pid in [("A", "ID-A"), ("B", "ID-B"), ("C", "ID-C")]:
        record_proforma_issued(p, batch_id="X", client_name=cn,
                                wfirma_proforma_id=pid, line_count=1,
                                currency="USD", operator="amit")
    a = json.loads(p.read_text())
    ids = sorted(r["wfirma_proforma_id"] for r in a["proforma_issued"])
    assert ids == ["ID-A", "ID-B", "ID-C"]


# ── 3. record_inventory_direct_dispatch ─────────────────────────────────────

def test_record_inventory_direct_dispatch_appends_timeline(tmp_path):
    p = _write(tmp_path, _stale_audit_with_pz_done())
    r = record_inventory_direct_dispatch(
        p, batch_id="B",
        scan_codes=["sc1", "sc2"],
        transitioned=2, already_ready=0,
        operator="amit",
        customer_allocation="direct dispatch",
        customs_signals=["timeline:wfirma_pz_created"],
        evidence_note="11 RECEIVE scans",
    )
    assert r["appended"] is True
    a = json.loads(p.read_text())
    events = [e for e in a["timeline"]
              if e.get("event") == EV_INVENTORY_DIRECT_DISPATCH_MARKED]
    assert len(events) == 1
    detail = events[0]["detail"]
    assert detail["scan_codes"]      == ["sc1", "sc2"]
    assert detail["transitioned"]    == 2
    assert detail["customs_signals"] == ["timeline:wfirma_pz_created"]


def test_record_inventory_direct_dispatch_skips_when_no_progress(tmp_path):
    p = _write(tmp_path, _stale_audit_with_pz_done())
    r = record_inventory_direct_dispatch(
        p, batch_id="B", scan_codes=[], transitioned=0, already_ready=0,
        operator="amit", customer_allocation="X",
        customs_signals=[], evidence_note="",
    )
    assert r["appended"] is False
    a = json.loads(p.read_text())
    assert not [e for e in a["timeline"]
                if e.get("event") == EV_INVENTORY_DIRECT_DISPATCH_MARKED]


# ── 4. reconcile_from_timeline (legacy stale-audit recovery) ────────────────

def test_reconcile_copies_doc_id_from_timeline(tmp_path):
    p = _write(tmp_path, _stale_audit_export_empty())
    r = reconcile_from_timeline(p)
    assert r["changed"] is True
    assert "copied_wfirma_pz_doc_id_from_timeline" in r["actions"]
    a = json.loads(p.read_text())
    assert a["wfirma_export"]["wfirma_pz_doc_id"] == "183484963"
    assert a["wfirma_export"]["pz_source"]        == "created_via_app"
    # Status should also be normalized in the same pass.
    assert a["status"] == "partial"


def test_reconcile_idempotent(tmp_path):
    p = _write(tmp_path, _stale_audit_export_empty())
    reconcile_from_timeline(p)
    second = reconcile_from_timeline(p)
    assert second["changed"] is False


def test_reconcile_no_op_when_already_clean(tmp_path):
    audit = _stale_audit_with_pz_done()
    audit["status"] = "partial"  # already aligned
    p = _write(tmp_path, audit)
    r = reconcile_from_timeline(p)
    assert r["changed"] is False


# ── 5. Restart-safe recovery without the audit_evidence shim ────────────────

def test_canonical_fields_alone_satisfy_evidence_helper(tmp_path):
    """After hardening writes wfirma_export.wfirma_pz_doc_id and a normalised
    status, the evidence helper passes via *canonical* signals — operators
    relying on the audit alone (no timeline-only fallback) get a clean read."""
    p = _write(tmp_path, _stale_audit_export_empty())
    reconcile_from_timeline(p)
    a = json.loads(p.read_text())
    # Strip the timeline so the test confirms canonical signals alone work.
    a_no_timeline = dict(a)
    a_no_timeline["timeline"] = []
    ev = effective_pz_evidence(a_no_timeline)
    assert ev["has_evidence"] is True
    # The export-side signal is the canonical one and must be present.
    assert "wfirma_export.wfirma_pz_doc_id" in ev["signals"]
    # Timeline-only fallback must NOT be the path that fired.
    assert "timeline:wfirma_pz_created" not in ev["signals"]
    assert ev["wfirma_pz_doc_id"] == "183484963"
