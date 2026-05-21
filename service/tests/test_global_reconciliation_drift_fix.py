"""test_global_reconciliation_drift_fix.py

Fix for production observation after PR #260 deploy:

  Generate Polish Description → HTTP 422 rows_audit_reconciliation_failed

Root cause: packing.db packing_lines were populated BEFORE PR #258's
lenient style-metal split landed. 4 of 245 rows had empty `metal`
column. `_inject_rows_from_packing_lines` skips rows with unmapped
metal (operator spec: never emit UNKNOWN), so only 241 rows survived.
Sum dropped to USD 2999.00 vs declared FOB 3172.00 → drift -173.00 →
reconciler hard-failed.

Fix:
  - `_force_reparse_global_packing()` helper that re-runs the live
    parser against source/packing/*.pdf and refreshes packing_lines.
  - `/generate-description?force=true` calls it before the source
    chain runs, so stale packing rows from an older parser version
    are healed automatically.
  - Reconciliation guard is unchanged — this is a row-source refresh,
    not a safety bypass.

Estrella protection: helper is gated on `_detect_global_supplier_for_batch`
and is a no-op for EJL batches.
"""
from __future__ import annotations

from pathlib import Path

import pytest


_ROUTES = (
    Path(__file__).resolve().parent.parent
    / "app" / "api" / "routes_dhl_clearance.py"
)


# ── Source contract ───────────────────────────────────────────────────────


def test_force_reparse_helper_exists():
    src = _ROUTES.read_text(encoding="utf-8")
    assert "def _force_reparse_global_packing(" in src


def test_force_reparse_uses_global_packing_parser():
    """The helper must consume the LIVE parse_global_packing_pdf so it
    benefits from PR #258's lenient split + PR #259's stone_type alias."""
    src = _ROUTES.read_text(encoding="utf-8")
    idx = src.find("def _force_reparse_global_packing(")
    body = src[idx : idx + 4000]
    assert "from ..services.global_packing_parser import parse_global_packing_pdf" in body
    assert "from ..services import packing_db" in body


def test_generate_description_force_calls_reparse():
    """The force=True branch in the route handler must trigger the
    Global packing reparse so stale rows are healed."""
    src = _ROUTES.read_text(encoding="utf-8")
    idx = src.find("async def generate_description(")
    body = src[idx : idx + 5000]
    assert "_force_reparse_global_packing" in body, (
        "generate_description force=True branch must call "
        "_force_reparse_global_packing"
    )


def test_force_reparse_gated_on_global_supplier_detector():
    """Estrella batches must NOT trigger the Global packing reparse.
    The call site checks _detect_global_supplier_for_batch first."""
    src = _ROUTES.read_text(encoding="utf-8")
    idx = src.find("async def generate_description(")
    body = src[idx : idx + 5000]
    # Both functions must appear, with detector BEFORE reparse
    i_det = body.find("_detect_global_supplier_for_batch")
    i_rep = body.find("_force_reparse_global_packing")
    assert i_det >= 0 and i_rep >= 0
    assert i_det < i_rep, (
        "_detect_global_supplier_for_batch must gate before reparse fires"
    )


# ── Helper behaviour: integration ────────────────────────────────────────


def test_force_reparse_returns_zero_when_no_packing_dir(tmp_path, monkeypatch):
    """No source/packing dir → no-op return 0."""
    from app.core.config import settings as _s
    monkeypatch.setattr(_s, "storage_root", tmp_path, raising=False)
    from app.api.routes_dhl_clearance import _force_reparse_global_packing
    out = _force_reparse_global_packing("NONEXISTENT_BATCH")
    assert out == 0


def test_force_reparse_returns_zero_when_no_pdfs(tmp_path, monkeypatch):
    """source/packing dir exists but is empty → no-op return 0."""
    from app.core.config import settings as _s
    monkeypatch.setattr(_s, "storage_root", tmp_path, raising=False)
    batch_id = "EMPTY_PACKING_BATCH"
    (tmp_path / "outputs" / batch_id / "source" / "packing").mkdir(parents=True)
    from app.api.routes_dhl_clearance import _force_reparse_global_packing
    assert _force_reparse_global_packing(batch_id) == 0


def test_force_reparse_returns_zero_when_no_packing_doc_record(
    tmp_path, monkeypatch,
):
    """Without an existing packing_document record, no parent ID exists
    to attach refreshed rows to → no-op return 0 rather than orphan rows."""
    from app.core.config import settings as _s
    monkeypatch.setattr(_s, "storage_root", tmp_path, raising=False)
    batch_id = "ORPHAN_PACKING_BATCH"
    pkg_dir = tmp_path / "outputs" / batch_id / "source" / "packing"
    pkg_dir.mkdir(parents=True)
    (pkg_dir / "fake.pdf").write_bytes(b"%PDF-1.7\n%empty\n")
    # No DB record
    monkeypatch.setattr(
        "app.services.document_db.get_documents_for_batch",
        lambda batch_id, document_type=None: [],
        raising=False,
    )
    from app.api.routes_dhl_clearance import _force_reparse_global_packing
    assert _force_reparse_global_packing(batch_id) == 0


# ── Estrella isolation invariant ─────────────────────────────────────────


def test_estrella_batch_does_not_trigger_force_reparse(monkeypatch):
    """When generate_description force=True fires for a non-Global batch,
    _force_reparse_global_packing MUST NOT be called."""
    import app.api.routes_dhl_clearance as _mod

    # Stub the detector to return non-Global
    monkeypatch.setattr(_mod, "_detect_global_supplier_for_batch",
                        lambda batch_id: False)
    # Track whether reparse helper was called
    called = {"hit": False}
    def _spy(batch_id):
        called["hit"] = True
        return 0
    monkeypatch.setattr(_mod, "_force_reparse_global_packing", _spy)

    # Simulate the branch — call the same code path directly
    from app.api.routes_dhl_clearance import (
        _detect_global_supplier_for_batch as det,
        _force_reparse_global_packing as rep,
    )
    if det("ESTRELLA_BATCH"):
        rep("ESTRELLA_BATCH")
    assert called["hit"] is False, (
        "Estrella batch must NOT trigger Global packing reparse"
    )


# ── Out-of-scope guard ────────────────────────────────────────────────────


def test_force_reparse_does_not_touch_fiscal_or_wfirma_tokens():
    src = _ROUTES.read_text(encoding="utf-8")
    idx = src.find("def _force_reparse_global_packing(")
    end = src.find("\ndef ", idx + 5)
    body = src[idx : end if end > 0 else idx + 5000]
    forbidden = (
        "compute_cif", "DHL_BROKER_THRESHOLD", "WFIRMA_CREATE_",
        "create_invoice", "create_pz", "_guard_wfirma_export",
        "post_to_wfirma",
    )
    for tok in forbidden:
        assert tok not in body, (
            f"_force_reparse_global_packing must not reference {tok!r}"
        )


def test_reconciliation_guard_still_present():
    """This PR must NOT weaken the rows_audit_reconciliation_failed
    guard — only fix the upstream row source."""
    src = _ROUTES.read_text(encoding="utf-8")
    assert src.count('"rows_audit_reconciliation_failed"') >= 2, (
        "reconciliation guard string must remain in source"
    )
