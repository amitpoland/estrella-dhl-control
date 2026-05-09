"""
test_wfirma_pz_lock_status.py — read-only `pz_lock_status` envelope returned by
GET /api/v1/upload/shipment/{batch_id}/wfirma/pz_preview.

The status snapshot drives the dashboard's lock banner + create/adopt button
gating.  No write logic is exercised here.

Cases
-----
1. lock_status.locked = false when no PZ linked
2. lock_status.locked = true when wfirma_pz_doc_id field is set
3. lock_status.locked = true when only the timeline event is present
4. created_by_system  source label normalized from raw 'created_via_app'
5. adopted_existing   source label preserved
6. dashboard renders <pz-lock-status-banner data-reason=...>
7. can_create / can_adopt action gates flip with the lock state
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

_svc = Path(__file__).parent.parent
if str(_svc) not in sys.path:
    sys.path.insert(0, str(_svc))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _audit(*, doc_id="", source="", timeline=()):
    a = {
        "batch_id": "TEST_LOCK_STATUS_001",
        "status":   "success",
        "inputs":   {"zc429": "sad.pdf"},
        "wfirma_export": {},
    }
    if doc_id:  a["wfirma_export"]["wfirma_pz_doc_id"] = doc_id
    if source:  a["wfirma_export"]["pz_source"]        = source
    if timeline:
        a["timeline"] = [{"event": ev, "ts": "2026-05-07T00:00:00Z"} for ev in timeline]
    return a


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Pure helper — lock_status=false on a clean audit
# ═══════════════════════════════════════════════════════════════════════════════

def test_lock_status_false_when_no_pz_linked():
    from app.api.routes_wfirma import _compute_pz_lock_status
    out = _compute_pz_lock_status(
        _audit(),
        preview_ready=True,
        supplier_configured=True,
        warehouse_configured=True,
    )
    assert out["locked"]            is False
    assert out["reason"]            == "no_pz_linked"
    assert out["wfirma_pz_doc_id"]  is None
    assert out["pz_source"]         is None
    assert out["terminal_event"]    is None
    assert out["recovery_required"] is False
    assert out["can_create"]        is True
    assert out["can_adopt"]         is True


def test_lock_status_can_create_false_when_preview_not_ready():
    """No PZ linked yet but earlier steps incomplete → can_create=false."""
    from app.api.routes_wfirma import _compute_pz_lock_status
    out = _compute_pz_lock_status(
        _audit(),
        preview_ready=False,
        supplier_configured=True,
        warehouse_configured=True,
    )
    assert out["locked"]    is False
    assert out["can_create"] is False
    assert out["can_adopt"]  is True   # adoption doesn't require preview


def test_lock_status_can_create_false_when_settings_missing():
    """Supplier or warehouse env unset → can_create=false even on a clean audit."""
    from app.api.routes_wfirma import _compute_pz_lock_status
    out = _compute_pz_lock_status(
        _audit(),
        preview_ready=True,
        supplier_configured=False,    # missing
        warehouse_configured=True,
    )
    assert out["can_create"] is False


# ═══════════════════════════════════════════════════════════════════════════════
# 2. lock_status=true when wfirma_pz_doc_id is set
# ═══════════════════════════════════════════════════════════════════════════════

def test_lock_status_true_when_doc_id_set():
    from app.api.routes_wfirma import _compute_pz_lock_status
    out = _compute_pz_lock_status(
        _audit(doc_id="183167843"),
        preview_ready=True,
        supplier_configured=True,
        warehouse_configured=True,
    )
    assert out["locked"]            is True
    assert out["wfirma_pz_doc_id"]  == "183167843"
    assert out["recovery_required"] is False
    assert out["can_create"]        is False
    assert out["can_adopt"]         is False
    assert out["reason"]            == "pz_doc_id_set"
    assert out["code"]              == "PZ_ALREADY_LINKED"


# ═══════════════════════════════════════════════════════════════════════════════
# 3. lock_status=true via timeline event only — recovery_required path
# ═══════════════════════════════════════════════════════════════════════════════

def test_lock_status_true_when_only_timeline_event():
    """
    Operator manually removed the doc_id but the timeline still records
    EV_WFIRMA_PZ_CREATED.  lock_status must mark this as recovery_required so
    the dashboard prompts the operator to use Confirm Existing PZ.
    """
    from app.api.routes_wfirma import _compute_pz_lock_status
    out = _compute_pz_lock_status(
        _audit(timeline=("wfirma_pz_created",)),
        preview_ready=True,
        supplier_configured=True,
        warehouse_configured=True,
    )
    assert out["locked"]            is True
    assert out["recovery_required"] is True
    assert out["reason"]            == "audit_write_recovery_required"
    assert out["code"]              == "PZ_AUDIT_RECOVERY_NEEDED"
    assert out["terminal_event"]    == "wfirma_pz_created"
    assert out["can_create"]        is False
    # Recovery: adopt remains TRUE so the operator can manually link the live
    # wFirma doc id back into the audit
    assert out["can_adopt"]         is True


def test_lock_status_recovery_required_for_adopted_terminal_event():
    """
    Symmetric counterpart to test_lock_status_true_when_only_timeline_event:
    timeline records EV_WFIRMA_PZ_ADOPTED but wfirma_pz_doc_id is empty.
    The recovery path must be triggered for the adopted-terminal sub-case
    too, so the dashboard renders the same recovery banner with the
    adopted-event variant of the subtitle.
    """
    from app.api.routes_wfirma import _compute_pz_lock_status
    out = _compute_pz_lock_status(
        _audit(timeline=("wfirma_pz_adopted",)),
        preview_ready=True,
        supplier_configured=True,
        warehouse_configured=True,
    )
    assert out["locked"]            is True
    assert out["recovery_required"] is True
    assert out["reason"]            == "audit_write_recovery_required"
    assert out["code"]              == "PZ_AUDIT_RECOVERY_NEEDED"
    assert out["terminal_event"]    == "wfirma_pz_adopted"
    assert out["wfirma_pz_doc_id"]  is None
    assert out["pz_source"]         is None
    assert out["can_create"]        is False
    assert out["can_adopt"]         is True


# ═══════════════════════════════════════════════════════════════════════════════
# 4. created_by_system source label
# ═══════════════════════════════════════════════════════════════════════════════

def test_created_by_system_source_label():
    """Raw `created_via_app` is normalized to UI-friendly `created_by_system`."""
    from app.api.routes_wfirma import _compute_pz_lock_status
    out = _compute_pz_lock_status(
        _audit(doc_id="100", source="created_via_app",
               timeline=("wfirma_pz_created",)),
        preview_ready=True,
        supplier_configured=True,
        warehouse_configured=True,
    )
    assert out["pz_source"]   == "created_by_system"
    assert out["reason"]      == "pz_created_by_system"
    assert out["code"]        == "PZ_ALREADY_CREATED"
    assert out["can_create"]  is False
    assert out["can_adopt"]   is False


# ═══════════════════════════════════════════════════════════════════════════════
# 5. adopted_existing source label
# ═══════════════════════════════════════════════════════════════════════════════

def test_adopted_existing_source_label():
    from app.api.routes_wfirma import _compute_pz_lock_status
    out = _compute_pz_lock_status(
        _audit(doc_id="200", source="adopted_existing",
               timeline=("wfirma_pz_adopted",)),
        preview_ready=True,
        supplier_configured=True,
        warehouse_configured=True,
    )
    assert out["pz_source"]   == "adopted_existing"
    assert out["reason"]      == "pz_adopted_existing"
    assert out["code"]        == "PZ_ALREADY_ADOPTED"
    assert out["can_create"]  is False
    assert out["can_adopt"]   is False


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Dashboard renders the lock banner with data-reason and gate attributes
# ═══════════════════════════════════════════════════════════════════════════════

def test_dashboard_html_contains_lock_status_banner():
    """
    Static markup verification: dashboard.html includes the
    `pz-lock-status-banner` testid, reads the four required fields, and
    exposes `data-can-create` / `data-can-adopt` gate attributes for tests.
    """
    html = (Path(_svc) / "app" / "static" / "dashboard.html").read_text(encoding="utf-8")
    # Banner element with stable test id
    assert 'data-testid="pz-lock-status-banner"' in html
    # Reads all four important pz_lock_status fields
    for field in ("recovery_required", "wfirma_pz_doc_id", "pz_source", "terminal_event"):
        assert f"ls.{field}" in html or f'"{field}"' in html, (
            f"banner should reference pz_lock_status.{field}"
        )
    # Gate attributes are emitted so e2e/JS tests can assert disabled state
    assert 'data-can-create=' in html
    assert 'data-can-adopt='  in html
    assert 'data-reason='     in html


# ═══════════════════════════════════════════════════════════════════════════════
# 7. Create / Adopt button gating uses pz_lock_status
# ═══════════════════════════════════════════════════════════════════════════════

def test_dashboard_buttons_use_lock_status_for_disabled_state():
    """
    The Create button must check `pzPreview.pz_lock_status.can_create`
    (with a fallback to legacy ad-hoc checks).  The Adopt button must check
    `pzPreview.pz_lock_status.can_adopt`.
    """
    html = (Path(_svc) / "app" / "static" / "dashboard.html").read_text(encoding="utf-8")

    # Create button — extract the JSX block following data-testid="btn-pz-create"
    m = re.search(r'data-testid="btn-pz-create"[\s\S]{0,1200}', html)
    assert m, "btn-pz-create block not found"
    create_block = m.group(0)
    assert "pz_lock_status" in create_block, "create button must consult pz_lock_status"
    assert "can_create"     in create_block, "create button must consult can_create"

    # Adopt button — extract the JSX block following data-testid="btn-pz-adopt-open"
    m = re.search(r'data-testid="btn-pz-adopt-open"[\s\S]{0,1200}', html)
    assert m, "btn-pz-adopt-open block not found"
    adopt_block = m.group(0)
    assert "pz_lock_status" in adopt_block, "adopt button must consult pz_lock_status"
    assert "can_adopt"      in adopt_block, "adopt button must consult can_adopt"


# ═══════════════════════════════════════════════════════════════════════════════
# 8. End-to-end: pz_preview response includes pz_lock_status (both branches)
# ═══════════════════════════════════════════════════════════════════════════════

def test_pz_preview_response_already_created_includes_lock_status(tmp_path):
    """
    When a PZ is already linked, the early-return branch of pz_preview must
    include pz_lock_status (locked=True, recovery_required=False).
    """
    import asyncio
    from unittest.mock import patch
    from app.api.routes_wfirma import wfirma_pz_preview

    audit = _audit(doc_id="900", source="created_via_app",
                   timeline=("wfirma_pz_created",))
    (tmp_path / "audit.json").write_text(json.dumps(audit))

    with (
        patch("app.api.routes_wfirma.get_output_dir", return_value=tmp_path),
        patch("app.api.routes_wfirma._read_audit", return_value=audit),
        patch("app.api.routes_wfirma._guard_wfirma_export"),
    ):
        result = asyncio.get_event_loop().run_until_complete(
            wfirma_pz_preview("TEST_LOCK_STATUS_001"))
    body = json.loads(result.body)

    assert body["already_created"] is True
    assert "pz_lock_status" in body, body
    ls = body["pz_lock_status"]
    assert ls["locked"]        is True
    assert ls["pz_source"]     == "created_by_system"
    assert ls["wfirma_pz_doc_id"] == "900"
    assert ls["can_create"]    is False
    assert ls["can_adopt"]     is False
