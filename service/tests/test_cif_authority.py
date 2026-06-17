"""
test_cif_authority.py — the shared backend CIF-authority gate.

Pins the single platform rule (operator directive, 2026-06-17): every
customs/PZ/DHL action resolves the customs CIF through ONE authority —
``cif_authority.get_cif_authority`` / ``require_resolved_cif`` (wrapping
``cif_resolver.resolve_cif``) — and never independently keys off a raw invoice
CIF of 0.

Coverage:

1. ``get_cif_authority`` — the read-only decision dict for the three tri-states
   (resolved-from-AWB, unknown, declared-zero), including the advisory flag that
   marks a raw invoice CIF as evidence-only when it is not the winning source.

2. ``require_resolved_cif`` — the gate: returns on RESOLVED, raises 422 with a
   distinct machine code on UNKNOWN (``cif_unresolved``) and DECLARED_ZERO
   (``cif_declared_zero``).

3. The DSK ``/generate`` route and the ``generate_customs_package`` route now
   gate on this shared authority — a shipment whose CIF resolves ONLY from the
   AWB Custom Val (the AWB 2315714531 shape) is no longer a false "Missing CIF
   value" block, while a genuinely unresolved value still blocks.

AWB 2315714531 (invoice CIF 0, AWB Custom Val USD 732) is carried as a permanent
regression fixture, matching test_polish_desc_cif_resolved_gate.py.
"""
from __future__ import annotations

import asyncio
import json
import sys
import types
from pathlib import Path

import pytest
from fastapi import HTTPException

_SVC = Path(__file__).parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

from app.services.cif_authority import (
    CODE_CIF_DECLARED_ZERO,
    CODE_CIF_UNRESOLVED,
    get_cif_authority,
    require_resolved_cif,
)
from app.services.cif_resolver import (
    CIF_DECLARED_ZERO,
    CIF_RESOLVED,
    CIF_UNKNOWN,
)

_AWB = "2315714531"
_RESOLVED_USD = 732.0


# ── Fixtures (shared shapes) ───────────────────────────────────────────────────

def _resolved_732_audit() -> dict:
    """invoice CIF parsed as 0, AWB Custom Val USD 732 → RESOLVED 732."""
    return {
        "awb": _AWB,
        "carrier": "DHL",
        "clearance_status": "awaiting_dhl_customs_email",
        "invoice_totals": {"total_cif_usd": 0, "total_fob_usd": 0},
        "awb_customs": {"value_usd": _RESOLVED_USD, "currency": "USD", "gap": None},
    }


def _unknown_audit() -> dict:
    """No CIF in any layer, invoice present → genuinely UNKNOWN (not zero)."""
    return {
        "awb": _AWB,
        "carrier": "DHL",
        "clearance_status": "awaiting_dhl_customs_email",
        "invoice_names": ["inv.pdf"],
        "invoice_totals": {"total_cif_usd": 0, "total_fob_usd": 0},
        "awb_customs": {"value_usd": None, "currency": "", "gap": "label_no_value"},
    }


def _declared_zero_audit() -> dict:
    """AWB Custom Val field present, currency blank → USD, value literally 0,
    no gap → a genuine DECLARED_ZERO."""
    return {
        "awb": _AWB,
        "carrier": "DHL",
        "clearance_status": "awaiting_dhl_customs_email",
        "invoice_totals": {"total_cif_usd": 0, "total_fob_usd": 0},
        "awb_customs": {"value_usd": 0, "currency": "", "gap": None},
    }


# ── 1. get_cif_authority — the read-only decision dict ────────────────────────

def test_get_authority_resolved_from_awb():
    info = get_cif_authority(_resolved_732_audit())
    assert info["cif_state"] == CIF_RESOLVED
    assert info["cif_usd"] == pytest.approx(_RESOLVED_USD)
    assert info["cif_source"] == "awb_customs.value_usd"
    assert info["is_resolved"] is True
    assert info["is_blocked"] is False
    assert info["blocker_reason"] is None
    # Raw invoice CIF is surfaced as EVIDENCE only, flagged advisory because it
    # is NOT what resolved the authority.
    assert info["invoice_cif_parsed"] == 0.0
    assert info["invoice_cif_advisory"] is True


def test_get_authority_unknown_is_blocked_with_reason_not_zero():
    info = get_cif_authority(_unknown_audit())
    assert info["cif_state"] == CIF_UNKNOWN
    assert info["cif_usd"] is None          # never a fabricated 0.0
    assert info["is_resolved"] is False
    assert info["is_blocked"] is True
    assert info["blocker_reason"]            # human reason present
    assert info["extraction_gap"]            # gap marker present


def test_get_authority_declared_zero_is_blocked_pending_review():
    info = get_cif_authority(_declared_zero_audit())
    assert info["cif_state"] == CIF_DECLARED_ZERO
    assert info["cif_usd"] == 0.0            # explicit zero, not None
    assert info["is_blocked"] is True
    assert "review" in (info["blocker_reason"] or "").lower()
    assert info["extraction_gap"] is None    # a declared zero is not a gap


def test_get_authority_never_raises_on_empty_audit():
    info = get_cif_authority({})
    assert info["cif_state"] == CIF_UNKNOWN
    assert info["cif_usd"] is None


# ── 2. require_resolved_cif — the gate ────────────────────────────────────────

def test_require_returns_on_resolved():
    info = require_resolved_cif(_resolved_732_audit(), action="a test action")
    assert info["cif_usd"] == pytest.approx(_RESOLVED_USD)
    assert info["cif_state"] == CIF_RESOLVED


def test_require_blocks_unknown_with_cif_unresolved_code():
    with pytest.raises(HTTPException) as ei:
        require_resolved_cif(_unknown_audit(), action="a Polish customs description")
    detail = ei.value.detail
    assert ei.value.status_code == 422
    assert isinstance(detail, dict)
    assert detail["code"] == CODE_CIF_UNRESOLVED == "cif_unresolved"
    assert detail["cif_state"] == CIF_UNKNOWN
    assert "cif_source" in detail
    assert "a Polish customs description" in detail["error"]


def test_require_blocks_declared_zero_with_distinct_review_code():
    with pytest.raises(HTTPException) as ei:
        require_resolved_cif(_declared_zero_audit(), action="a DSK broker notification")
    detail = ei.value.detail
    assert ei.value.status_code == 422
    assert detail["code"] == CODE_CIF_DECLARED_ZERO == "cif_declared_zero"
    assert detail["cif_state"] == CIF_DECLARED_ZERO
    # Distinct from the unknown blocker — a declared zero is a review gate.
    assert detail["code"] != CODE_CIF_UNRESOLVED
    assert "review" in detail["error"].lower()


# ── 3. DSK /generate route gates on the shared authority ──────────────────────

def _seed_batch(tmp_path: Path, audit: dict, batch_id: str = "BATCH_DSK") -> str:
    out = tmp_path / "outputs" / batch_id
    out.mkdir(parents=True, exist_ok=True)
    (out / "audit.json").write_text(json.dumps(audit), encoding="utf-8")
    return batch_id


def _install_fake_dsk_generator(monkeypatch, captured: dict):
    """Inject a stub dsk_generator so the route's CIF gate + value derivation are
    exercised without producing a real PDF. Captures the value_usd it receives."""
    fake = types.ModuleType("dsk_generator")

    def generate_dsk(*, awb, value_usd, **_kw):
        captured["value_usd"] = value_usd
        return {
            "generated":     True,
            "filename":      "DSK_TEST.pdf",
            "awb_clean":     awb.replace(" ", ""),
            "awb_formatted": awb,
            "date":          "01-01-2026",
            "output_path":   None,
        }

    fake.generate_dsk = generate_dsk
    monkeypatch.setitem(sys.modules, "dsk_generator", fake)


def test_dsk_generate_resolves_from_awb_value(tmp_path, monkeypatch):
    """The AWB 2315714531 shape (invoice CIF 0, AWB Custom Val 732) must NOT be a
    'Missing CIF value' block on DSK — the value resolves from the shared
    authority's AWB layer."""
    from app.api import routes_dsk as _dsk
    from app.api.routes_dsk import DskRequest, generate_dsk_endpoint
    from app.core.config import settings

    monkeypatch.setattr(settings, "storage_root", tmp_path, raising=False)
    captured: dict = {}
    _install_fake_dsk_generator(monkeypatch, captured)

    batch_id = _seed_batch(tmp_path, _resolved_732_audit())
    body = DskRequest(awb=_AWB, batch_id=batch_id)  # no value_usd → derive from audit
    resp = asyncio.run(generate_dsk_endpoint(body))

    assert resp.generated is True
    assert captured["value_usd"] == pytest.approx(_RESOLVED_USD)


def test_dsk_generate_blocks_unknown_cif(tmp_path, monkeypatch):
    """A genuinely unresolved CIF still blocks DSK with the cif_unresolved code."""
    from app.api.routes_dsk import DskRequest, generate_dsk_endpoint
    from app.core.config import settings

    monkeypatch.setattr(settings, "storage_root", tmp_path, raising=False)
    batch_id = _seed_batch(tmp_path, _unknown_audit())
    body = DskRequest(awb=_AWB, batch_id=batch_id)

    with pytest.raises(HTTPException) as ei:
        asyncio.run(generate_dsk_endpoint(body))
    detail = ei.value.detail
    assert isinstance(detail, dict)
    assert detail["code"] == "cif_unresolved"


def test_dsk_generate_respects_explicit_payload_override(tmp_path, monkeypatch):
    """An explicit payload value_usd is the operator's own authority and bypasses
    the audit-derived gate even when the audit CIF is unknown."""
    from app.api.routes_dsk import DskRequest, generate_dsk_endpoint
    from app.core.config import settings

    monkeypatch.setattr(settings, "storage_root", tmp_path, raising=False)
    captured: dict = {}
    _install_fake_dsk_generator(monkeypatch, captured)

    batch_id = _seed_batch(tmp_path, _unknown_audit())
    body = DskRequest(awb=_AWB, value_usd=1500.0, batch_id=batch_id)
    resp = asyncio.run(generate_dsk_endpoint(body))

    assert resp.generated is True
    assert captured["value_usd"] == pytest.approx(1500.0)


# ── 4. Source contract — the shared gate is wired into the customs routes ─────

def test_customs_routes_use_shared_authority_helper():
    dhl = (_SVC / "app" / "api" / "routes_dhl_clearance.py").read_text(encoding="utf-8")
    dsk = (_SVC / "app" / "api" / "routes_dsk.py").read_text(encoding="utf-8")
    # Both the Polish-description and customs-package routes gate on the helper.
    assert dhl.count("require_resolved_cif(audit") >= 2
    assert "from ..services.cif_authority import require_resolved_cif" in dhl
    # DSK derives its value through the shared authority, not just two layers.
    assert "require_resolved_cif" in dsk
