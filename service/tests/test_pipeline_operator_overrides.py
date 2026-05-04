"""
test_pipeline_operator_overrides.py — _run_pipeline preserves operator decisions
and reconciles effective-blocked state after the engine write.

Background
----------
  process_shipment() (the PZ engine) writes a fresh audit.json that strips
  operator_overrides, pz_confirmed, and pz_confirmed_at.  It also sets
  status="blocked" based on failed_checks and amendment_flags alone, without
  any knowledge of operator overrides.

  _run_pipeline contains two post-engine patches:
    A) Preservation  — restores operator_overrides / pz_confirmed / pz_confirmed_at
                       from the pre-run audit so the audit trail is never lost.
    B) Reconciliation — if the engine said "blocked" but _compute_effective_blocked
                        returns False, promotes status to "partial" and sets
                        pz_generated=True so downstream workflow gates advance.

Coverage
--------
Preservation (tests 1–4):
  1. operator_overrides list restored after engine write
  2. pz_confirmed flag restored after engine write
  3. pz_confirmed_at timestamp restored after engine write
  4. no duplicate overrides created — same list, not concatenated

Reconciliation (tests 5–7):
  5. engine blocked + effective_blocked=False  → status promoted to partial
  6. engine blocked + effective_blocked=True   → status remains blocked
  7. promoted partial has pz_generated=True, sad_imported=True, sad_imported_ts set

Evidence preservation (tests 8–9):
  8. failed_checks remain exactly as engine wrote them after preservation
  9. amendment_flags remain exactly as engine wrote them after preservation

Financial integrity (test 10):
 10. no financial field (total_net, total_gross, duty_a00) mutated by
     preservation or reconciliation logic
"""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.services.batch_state_normalizer import ALLOWED_OVERRIDE_TYPES


# ═══════════════════════════════════════════════════════════════════════════════
# Shared fixtures / helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _override(check: str, batch_id: str) -> dict:
    return {
        "override_id":        str(uuid.uuid4()),
        "check":              check,
        "reason":             "Accepted by operator after review — sufficient reason text",
        "operator":           "operator@test.com",
        "timestamp":          datetime.now(timezone.utc).isoformat(),
        "evidence_reference": "test evidence",
        "batch_id":           batch_id,
        "original_value":     False,
    }


def _write_pre_run_audit(
    output_dir: Path,
    batch_id: str,
    overrides: list | None = None,
    pz_confirmed: bool = False,
    pz_confirmed_at: str | None = None,
    failed_checks: list | None = None,
    amendment_flags: list | None = None,
    extra: dict | None = None,
) -> None:
    """
    Write audit.json as the process endpoint leaves it: status='processing',
    operator_overrides intact, customs_declaration.mrn present (passes guard).
    """
    data: dict = {
        "batch_id":            batch_id,
        "status":              "processing",   # process endpoint sets this before dispatch
        "doc_no":              "PZ 1/1/2026",
        "operator_overrides":  overrides or [],
        "failed_checks":       failed_checks or [],
        "amendment_flags":     amendment_flags or [],
        "customs_declaration": {"mrn": "26PLTEST0001"},
        "inputs":              {},
    }
    if pz_confirmed:
        data["pz_confirmed"] = True
    if pz_confirmed_at:
        data["pz_confirmed_at"] = pz_confirmed_at
    if extra:
        data.update(extra)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "audit.json").write_text(json.dumps(data), encoding="utf-8")


def _seed_invoices(output_dir: Path) -> Path:
    inv_dir = output_dir / "source" / "invoices"
    inv_dir.mkdir(parents=True, exist_ok=True)
    (inv_dir / "invoice.pdf").write_bytes(b"%PDF-1.4 stub")
    return inv_dir


def _make_engine_result(
    status: str = "blocked",
    failed_checks: list | None = None,
    amendment_flags: list | None = None,
    financial: dict | None = None,
) -> dict:
    """Return what process_shipment would return (pure dict, no disk write)."""
    fin = financial or {"total_net": 1000.0, "total_gross": 1230.0, "duty_a00": 50.0}
    return {"status": status, **fin}


def _engine_side_effect(
    output_dir: Path,
    batch_id: str,
    status: str = "blocked",
    failed_checks: list | None = None,
    amendment_flags: list | None = None,
    financial: dict | None = None,
):
    """
    Return a callable suitable as the mock for export_service.process_shipment.
    When called, it simulates what the real engine does:
      - writes a fresh audit.json WITHOUT operator_overrides / pz_confirmed / pz_confirmed_at
      - returns the result dict
    Must be called AFTER _write_pre_run_audit so the pre-run state is in place first.
    """
    fin = financial or {"total_net": 1000.0, "total_gross": 1230.0, "duty_a00": 50.0}
    result = {"status": status, **fin}

    def _fake_process(**_kwargs):
        # Simulate engine overwriting audit.json — strips all operator fields
        data: dict = {
            "batch_id":            batch_id,
            "status":              status,
            "doc_no":              "PZ 1/1/2026",
            "operator_overrides":  [],      # engine always writes empty
            "failed_checks":       failed_checks or [],
            "amendment_flags":     amendment_flags or [],
            "customs_declaration": {"mrn": "26PLTEST0001"},
            "inputs":              {},
            **fin,
        }
        (output_dir / "audit.json").write_text(json.dumps(data), encoding="utf-8")
        return result

    return _fake_process


def _run(coro) -> None:
    """Run an async coroutine synchronously in a fresh event loop."""
    asyncio.run(coro)


def _make_pipeline_kwargs(output_dir: Path, batch_id: str) -> dict:
    inv_dir = _seed_invoices(output_dir)
    return dict(
        batch_id    = batch_id,
        output_dir  = output_dir,
        inv_dir     = inv_dir,
        sad_path    = None,
        tracking_no = "",
        carrier     = "DHL",
        doc_no      = "PZ 1/1/2026",
        inv_names   = ["invoice.pdf"],
        sad_name    = "sad.pdf",
        awb_name    = "",
    )


def _patch_pipeline(
    monkeypatch,
    output_dir: Path,
    batch_id: str,
    status: str = "blocked",
    failed_checks: list | None = None,
    amendment_flags: list | None = None,
    financial: dict | None = None,
) -> None:
    """
    Patch:
      - export_service.process_shipment → simulates engine write + returns result
      - build_clearance_decision        → safe stub (non-fatal if import fails)
    The engine side-effect writes a fresh audit.json (stripping operator fields)
    only when process_shipment is actually called, not before.
    """
    from app.api import routes_upload as ru

    monkeypatch.setattr(
        ru.export_service, "process_shipment",
        _engine_side_effect(output_dir, batch_id, status=status,
                            failed_checks=failed_checks,
                            amendment_flags=amendment_flags,
                            financial=financial),
    )

    # Suppress clearance_decision (non-fatal path; suppress to keep tests fast)
    try:
        from app.services import clearance_decision as cd_mod
        monkeypatch.setattr(cd_mod, "build_clearance_decision",
                            lambda _a: {"clearance_path": "routing_pending"})
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════════════
# 1–4: Preservation tests
# ═══════════════════════════════════════════════════════════════════════════════

def test_operator_overrides_preserved_after_engine_write(tmp_path, monkeypatch):
    """1. operator_overrides written by the operator are restored after engine run."""
    from app.api.routes_upload import _run_pipeline

    batch_id = "P1"
    output_dir = tmp_path / batch_id
    pre_overrides = [_override("cn_match", batch_id)]

    _write_pre_run_audit(output_dir, batch_id, overrides=pre_overrides)
    _patch_pipeline(monkeypatch, output_dir, batch_id, status="blocked",
                    amendment_flags=["Parse warning: test"])

    _run(_run_pipeline(**_make_pipeline_kwargs(output_dir, batch_id)))

    audit = json.loads((output_dir / "audit.json").read_text())
    assert audit.get("operator_overrides"), "operator_overrides must not be empty after run"
    assert audit["operator_overrides"][0]["check"] == "cn_match"
    assert audit["operator_overrides"][0]["override_id"] == pre_overrides[0]["override_id"]


def test_pz_confirmed_preserved_after_engine_write(tmp_path, monkeypatch):
    """2. pz_confirmed flag is restored after engine write (engine always omits it)."""
    from app.api.routes_upload import _run_pipeline

    batch_id = "P2"
    output_dir = tmp_path / batch_id
    _write_pre_run_audit(output_dir, batch_id,
                         overrides=[_override("cn_match", batch_id)],
                         pz_confirmed=True)
    _patch_pipeline(monkeypatch, output_dir, batch_id, status="blocked",
                    amendment_flags=["Parse warning: x"])

    _run(_run_pipeline(**_make_pipeline_kwargs(output_dir, batch_id)))

    audit = json.loads((output_dir / "audit.json").read_text())
    assert audit.get("pz_confirmed") is True, "pz_confirmed must survive engine rewrite"


def test_pz_confirmed_at_preserved_after_engine_write(tmp_path, monkeypatch):
    """3. pz_confirmed_at timestamp is restored after engine write."""
    from app.api.routes_upload import _run_pipeline

    batch_id = "P3"
    output_dir = tmp_path / batch_id
    ts = "2026-05-04T08:00:00+00:00"
    _write_pre_run_audit(output_dir, batch_id,
                         overrides=[_override("cn_match", batch_id)],
                         pz_confirmed=True, pz_confirmed_at=ts)
    _patch_pipeline(monkeypatch, output_dir, batch_id, status="blocked",
                    amendment_flags=["Parse warning: x"])

    _run(_run_pipeline(**_make_pipeline_kwargs(output_dir, batch_id)))

    audit = json.loads((output_dir / "audit.json").read_text())
    assert audit.get("pz_confirmed_at") == ts, (
        f"pz_confirmed_at must survive engine rewrite; got {audit.get('pz_confirmed_at')!r}"
    )


def test_no_duplicate_overrides_on_rerun(tmp_path, monkeypatch):
    """4. Rerunning pipeline does not duplicate existing overrides — same list, not extended."""
    from app.api.routes_upload import _run_pipeline

    batch_id = "P4"
    output_dir = tmp_path / batch_id
    pre_overrides = [_override("cn_match", batch_id), _override("exporter_match", batch_id)]

    _write_pre_run_audit(output_dir, batch_id, overrides=pre_overrides)
    _patch_pipeline(monkeypatch, output_dir, batch_id, status="blocked",
                    amendment_flags=["Parse warning: y"])

    _run(_run_pipeline(**_make_pipeline_kwargs(output_dir, batch_id)))

    audit = json.loads((output_dir / "audit.json").read_text())
    ids_after = [o["override_id"] for o in audit.get("operator_overrides", [])]
    ids_before = [o["override_id"] for o in pre_overrides]
    assert ids_after == ids_before, (
        f"Override list must be identical — no duplication.\n"
        f"Before: {ids_before}\n After:  {ids_after}"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 5–7: Reconciliation tests
# ═══════════════════════════════════════════════════════════════════════════════

def test_blocked_promoted_to_partial_when_effective_unblocked(tmp_path, monkeypatch):
    """5. Engine returns blocked but _compute_effective_blocked=False → status promoted to partial."""
    from app.api.routes_upload import _run_pipeline

    batch_id = "R1"
    output_dir = tmp_path / batch_id
    # cn_match override covers the cn_match failed_check → effective_blocked = False
    pre_overrides = [_override("cn_match", batch_id)]
    _write_pre_run_audit(output_dir, batch_id, overrides=pre_overrides)
    _patch_pipeline(monkeypatch, output_dir, batch_id, status="blocked",
                    failed_checks=["cn_match"], amendment_flags=[])

    _run(_run_pipeline(**_make_pipeline_kwargs(output_dir, batch_id)))

    audit = json.loads((output_dir / "audit.json").read_text())
    assert audit["status"] == "partial", (
        f"Status must be promoted to partial when overrides clear all blockers; got {audit['status']!r}"
    )


def test_blocked_remains_blocked_with_uncleared_hard_failure(tmp_path, monkeypatch):
    """6. Engine returns blocked with a non-overridden hard failure → status stays blocked."""
    from app.api.routes_upload import _run_pipeline

    batch_id = "R2"
    output_dir = tmp_path / batch_id
    # cn_match is overridden, but cif_match (FORBIDDEN) remains in failed_checks → still hard-blocked
    pre_overrides = [_override("cn_match", batch_id)]
    _write_pre_run_audit(output_dir, batch_id, overrides=pre_overrides)
    _patch_pipeline(monkeypatch, output_dir, batch_id, status="blocked",
                    failed_checks=["cn_match", "cif_match"], amendment_flags=[])

    _run(_run_pipeline(**_make_pipeline_kwargs(output_dir, batch_id)))

    audit = json.loads((output_dir / "audit.json").read_text())
    assert audit["status"] == "blocked", (
        f"Status must remain blocked when uncleared hard failure (cif_match) remains; "
        f"got {audit['status']!r}"
    )


def test_promoted_partial_has_pz_generated_and_sad_imported(tmp_path, monkeypatch):
    """7. Promoted partial sets pz_generated=True, sad_imported=True, sad_imported_ts."""
    from app.api.routes_upload import _run_pipeline

    batch_id = "R3"
    output_dir = tmp_path / batch_id
    pre_overrides = [_override("cn_match", batch_id)]
    _write_pre_run_audit(output_dir, batch_id, overrides=pre_overrides)
    _patch_pipeline(monkeypatch, output_dir, batch_id, status="blocked",
                    failed_checks=["cn_match"], amendment_flags=[])

    _run(_run_pipeline(**_make_pipeline_kwargs(output_dir, batch_id)))

    audit = json.loads((output_dir / "audit.json").read_text())
    assert audit["status"] == "partial"
    assert audit.get("pz_generated") is True, "pz_generated must be True after promotion"
    assert audit.get("sad_imported") is True, "sad_imported must be True after promotion"
    assert audit.get("sad_imported_ts"), "sad_imported_ts must be set after promotion"


# ═══════════════════════════════════════════════════════════════════════════════
# 8–9: Evidence preservation
# ═══════════════════════════════════════════════════════════════════════════════

def test_failed_checks_unchanged_by_preservation(tmp_path, monkeypatch):
    """8. failed_checks remain exactly as written by the engine — preservation does not clear them."""
    from app.api.routes_upload import _run_pipeline

    batch_id = "E1"
    output_dir = tmp_path / batch_id
    pre_overrides = [_override("cn_match", batch_id)]
    _write_pre_run_audit(output_dir, batch_id, overrides=pre_overrides)
    _patch_pipeline(monkeypatch, output_dir, batch_id, status="blocked",
                    failed_checks=["cn_match"], amendment_flags=[])

    _run(_run_pipeline(**_make_pipeline_kwargs(output_dir, batch_id)))

    audit = json.loads((output_dir / "audit.json").read_text())
    # Promoted to partial via reconciliation, but the original engine check must remain
    assert "cn_match" in audit.get("failed_checks", []), (
        "failed_checks must preserve the engine's verdict as an evidence record"
    )


def test_amendment_flags_unchanged_by_preservation(tmp_path, monkeypatch):
    """9. amendment_flags remain exactly as written by the engine."""
    from app.api.routes_upload import _run_pipeline

    batch_id = "E2"
    output_dir = tmp_path / batch_id
    parse_flag = "Parse warning: [LEARNING] CIF Value label not found"
    pre_overrides = [_override("invoice_number_parse_warning", batch_id)]
    _write_pre_run_audit(output_dir, batch_id, overrides=pre_overrides)
    _patch_pipeline(monkeypatch, output_dir, batch_id, status="blocked",
                    failed_checks=[], amendment_flags=[parse_flag])

    _run(_run_pipeline(**_make_pipeline_kwargs(output_dir, batch_id)))

    audit = json.loads((output_dir / "audit.json").read_text())
    # Promoted to partial, but the parse warning must remain as an audit record
    assert parse_flag in audit.get("amendment_flags", []), (
        "amendment_flags must preserve the engine's parse warning as an evidence record"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 10: Financial integrity
# ═══════════════════════════════════════════════════════════════════════════════

def test_financial_fields_not_mutated_by_preservation_or_reconciliation(tmp_path, monkeypatch):
    """10. Preservation and reconciliation do not alter any financial field."""
    from app.api.routes_upload import _run_pipeline

    batch_id = "F1"
    output_dir = tmp_path / batch_id
    pre_overrides = [_override("cn_match", batch_id)]
    _write_pre_run_audit(output_dir, batch_id, overrides=pre_overrides)
    financial = {"total_net": 48_778.64, "total_gross": 59_997.72, "duty_a00": 1_181.00}
    _patch_pipeline(monkeypatch, output_dir, batch_id, status="blocked",
                    failed_checks=["cn_match"], amendment_flags=[], financial=financial)

    _run(_run_pipeline(**_make_pipeline_kwargs(output_dir, batch_id)))

    audit = json.loads((output_dir / "audit.json").read_text())
    for field, expected in financial.items():
        actual = audit.get(field)
        assert actual == expected, (
            f"Financial field '{field}' must not be mutated by pipeline logic; "
            f"expected {expected}, got {actual}"
        )
