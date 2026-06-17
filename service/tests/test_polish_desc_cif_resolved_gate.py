"""
test_polish_desc_cif_resolved_gate.py — regression for the Polish-description
generation gate after the split-CIF-authority removal.

Origin (operator directive, 2026-06-16)
----------------------------------------
AWB 2315714531 resolves its customs CIF (USD 732) ONLY from the carrier-declared
AWB Custom Val — its commercial invoice never produced a parsed CIF, so the raw
``invoice_cif`` is 0. The legacy ``generate_description`` route blocked Polish
description generation on that raw invoice CIF of 0 ("CIF = 0.00 — invoice values
not parsed"), contradicting the clearance-routing layer which had already
resolved a usable customs value from the AWB. Operators saw a hard block on a
shipment that was, in fact, fully routable.

The fix replaces the raw-invoice ``cif_zero`` guard with a resolved-CIF guard
that shares authority parity with ``clearance_decision`` and the shipment UI:
the blocker is an *unresolved* customs CIF (``cif_state == unknown``), NOT a raw
invoice CIF of 0. A value resolved from AWB Custom Val (or the OCR/AI fallback)
is sufficient to proceed.

What this module pins
---------------------
1. Behavioural authority (resolver + decision) for the exact 2315714531 shape —
   invoice CIF explicitly 0, AWB Custom Val USD 732 → RESOLVED 732, source
   visible, clearance decision carries the resolved value. This proves a raw
   invoice 0 never wins over a usable AWB value and is never mistaken for a
   declared zero.

2. The ROUTE GUARD FLIP on ``generate_description``:
   - resolved-732 audit (invoice CIF 0)  → the CIF guard does NOT fire; the
     request falls through to a *downstream* guard (lines_missing) — i.e. a raw
     invoice CIF of 0 alone no longer blocks Polish description generation.
   - all-unknown audit (no invoice, no AWB value) → the CIF guard DOES fire with
     ``code == "cif_unresolved"`` — a genuinely unresolved customs value still
     blocks, so the fix did not weaken the real safety property.

3. Source contract: the route uses the resolved-CIF resolver and exposes the
   ``cif_state`` / ``cif_source`` provenance, and the old raw-invoice
   ``cif_zero`` blocker is gone.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

_SVC = Path(__file__).parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

from app.api import routes_dhl_clearance as _routes
from app.api.routes_dhl_clearance import generate_description
from app.core.config import settings
from app.services.cif_resolver import (
    CIF_DECLARED_ZERO,
    CIF_RESOLVED,
    CIF_UNKNOWN,
    resolve_cif,
)
from app.services.clearance_decision import build_clearance_decision
from app.services.clearance_path_alias import (
    PATH_DHL_SELF_CLEARANCE,
    is_dhl_self_clearance,
)

# AWB whose ONLY customs authority is the carrier-declared AWB Custom Val.
_AWB = "2315714531"
_RESOLVED_USD = 732.0


# ── Harness ───────────────────────────────────────────────────────────────────

def _seed_audit(tmp_path: Path, audit: dict) -> str:
    """Write audit.json under the route's expected outputs/<batch>/ layout and
    point settings.storage_root at tmp_path. Returns the batch_id."""
    batch_id = "BATCH_CIF_GATE"
    out = tmp_path / "outputs" / batch_id
    out.mkdir(parents=True, exist_ok=True)
    (out / "audit.json").write_text(json.dumps(audit), encoding="utf-8")
    return batch_id


def _resolved_732_audit() -> dict:
    """AWB 2315714531 shape: invoice CIF parsed as 0, AWB Custom Val USD 732.

    ``clearance_status`` is seeded to an email-pending state so the DHL-email
    guard (which runs BEFORE the CIF guard on the carrier path) passes and the
    request reaches the CIF guard under test.
    """
    return {
        "awb": _AWB,
        "carrier": "DHL",
        "clearance_status": "awaiting_dhl_customs_email",  # satisfies DHL-email guard
        "invoice_totals": {"total_cif_usd": 0, "total_fob_usd": 0},  # raw invoice CIF = 0
        "awb_customs": {"value_usd": _RESOLVED_USD, "currency": "USD", "gap": None},
    }


def _all_unknown_audit() -> dict:
    """No invoice CIF, no usable AWB value → genuinely UNKNOWN customs CIF.

    ``invoice_names`` is present so the resolver's gap diagnosis lands on the
    extraction layers rather than 'no invoice uploaded' — this is the
    unresolved-after-parse case, which must still block.
    """
    return {
        "awb": _AWB,
        "carrier": "DHL",
        "clearance_status": "awaiting_dhl_customs_email",
        "invoice_names": ["inv.pdf"],
        "invoice_totals": {"total_cif_usd": 0, "total_fob_usd": 0},
        "awb_customs": {"value_usd": None, "currency": "", "gap": "label_no_value"},
    }


def _invoke(batch_id: str):
    return asyncio.run(generate_description(batch_id, awb="", customs_view="invoice_positions"))


# ── 1. Behavioural authority for the 2315714531 shape ─────────────────────────

def test_resolver_prefers_awb_value_over_raw_invoice_zero():
    """Raw invoice CIF of 0 does NOT win and is NOT a declared zero — the AWB
    Custom Val (USD 732) resolves the customs CIF, with its source visible."""
    res = resolve_cif(_resolved_732_audit())
    assert res["cif_state"] == CIF_RESOLVED
    assert res["cif_usd"] == pytest.approx(_RESOLVED_USD)
    assert res["cif_source"] == "awb_customs.value_usd"   # source is visible
    assert res["extraction_gap"] is None


def test_clearance_decision_carries_resolved_cif():
    """The clearance decision exposes the resolved value (not the raw invoice 0)
    and routes the 732 shipment to carrier self-clearance."""
    dec = build_clearance_decision(_resolved_732_audit())
    assert dec["cif_state"] == CIF_RESOLVED
    assert dec["total_value_usd"] == pytest.approx(_RESOLVED_USD)
    assert dec["cif_source"] == "awb_customs.value_usd"
    assert is_dhl_self_clearance(dec["clearance_path"])
    assert dec["clearance_path"] == PATH_DHL_SELF_CLEARANCE
    assert dec["require_dsk"] is False


def test_declared_zero_is_not_resolved_and_not_unknown():
    """A genuine declared zero (AWB Custom Val field present, currency blank →
    treated as USD, value literally 0, no gap) classifies as DECLARED_ZERO —
    NOT a fake-zero UNKNOWN and NOT a positive RESOLVED. This pins the directive
    rule that a real zero is honoured ONLY when the source explicitly declares
    it, while a parser-miss stays UNKNOWN (see the all-unknown case below)."""
    audit = {
        "awb": _AWB,
        "carrier": "DHL",
        "invoice_totals": {"total_cif_usd": 0, "total_fob_usd": 0},
        "awb_customs": {"value_usd": 0, "currency": "", "gap": None},  # currency "" → USD
    }
    res = resolve_cif(audit)
    assert res["cif_state"] == CIF_DECLARED_ZERO
    assert res["cif_state"] != CIF_UNKNOWN
    assert res["cif_usd"] == 0.0          # explicit zero, not None and not positive
    assert res["cif_source"] == "awb_customs.value_usd"
    assert res["extraction_gap"] is None  # a declared zero is not an extraction gap


# ── 2. Route guard flip on generate_description ───────────────────────────────

def test_generate_description_not_blocked_by_raw_invoice_zero(tmp_path, monkeypatch):
    """With invoice CIF 0 but a resolved AWB value of 732, the CIF guard must
    NOT fire. The request falls through to a downstream row guard
    (lines_missing_for_description) — proving a raw invoice CIF of 0 alone no
    longer blocks Polish description generation."""
    monkeypatch.setattr(settings, "storage_root", tmp_path, raising=False)
    # Isolate the guard sequence: skip real row injection so an empty batch
    # deterministically reaches the lines-missing guard rather than the engine.
    monkeypatch.setattr(_routes, "_inject_rows_from_sources",
                        lambda _bid, a, **_kw: a, raising=False)

    batch_id = _seed_audit(tmp_path, _resolved_732_audit())

    with pytest.raises(HTTPException) as ei:
        _invoke(batch_id)

    detail = ei.value.detail
    code = detail.get("code") if isinstance(detail, dict) else None
    # The CIF guard did NOT fire ...
    assert code != "cif_unresolved", f"CIF guard wrongly blocked a resolved value: {detail}"
    assert code != "cif_zero", f"legacy raw-invoice cif_zero guard reappeared: {detail}"
    # ... a downstream guard did, proving the request passed the CIF gate.
    assert code == "lines_missing_for_description", (
        f"expected to fall through to the row guard, got: {detail}"
    )


def test_generate_description_still_blocks_unresolved_cif(tmp_path, monkeypatch):
    """An audit with no invoice CIF and no usable AWB value is genuinely
    UNKNOWN — the CIF guard must still fire with code 'cif_unresolved'. This
    pins that the fix did not weaken the real safety property."""
    monkeypatch.setattr(settings, "storage_root", tmp_path, raising=False)
    batch_id = _seed_audit(tmp_path, _all_unknown_audit())

    with pytest.raises(HTTPException) as ei:
        _invoke(batch_id)

    detail = ei.value.detail
    assert isinstance(detail, dict)
    assert detail.get("code") == "cif_unresolved", detail
    assert detail.get("cif_state") == "unknown", detail
    # Provenance is surfaced to the operator on the block, too.
    assert "cif_source" in detail


# ── 2b. Integration: the batch route the UI binds to carries resolved CIF ─────

def test_batch_detail_route_injects_resolved_cif_for_the_ui(tmp_path, monkeypatch):
    """The shipment UI reads its CIF authority from
    ``GET /dashboard/batches/{id}``.clearance_decision (backfilled on load).

    This drives the REAL ``batch_detail`` handler with the 2315714531 audit
    (invoice CIF 0, AWB Custom Val USD 732) and asserts the response the page
    binds to carries the RESOLVED authority — total_value_usd 732, cif_state
    'resolved', cif_source visible — while the raw invoice CIF stays 0. This is
    the wire that makes the UI panels read one authority instead of the raw
    invoice zero, verified end-to-end through the actual route, not a stub."""
    from app.api import routes_dashboard as _dash

    outputs = tmp_path / "outputs"
    monkeypatch.setattr(_dash, "_OUTPUTS", outputs, raising=False)
    bdir = outputs / _AWB
    bdir.mkdir(parents=True, exist_ok=True)
    (bdir / "audit.json").write_text(json.dumps(_resolved_732_audit()), encoding="utf-8")

    result = _dash.batch_detail(_AWB)

    dec = result["clearance_decision"]
    assert dec["cif_state"] == CIF_RESOLVED
    assert dec["total_value_usd"] == pytest.approx(_RESOLVED_USD)
    assert dec["cif_source"] == "awb_customs.value_usd"
    # The raw invoice CIF the legacy panels keyed off is still 0 — proving the
    # UI now reads the resolved authority, NOT the raw invoice zero.
    assert (result.get("invoice_totals") or {}).get("total_cif_usd") == 0


# ── 3. Source contract — resolved-CIF guard present, legacy blocker gone ──────

def test_route_uses_resolved_cif_guard_not_raw_invoice_zero():
    src = (_SVC / "app" / "api" / "routes_dhl_clearance.py").read_text(encoding="utf-8")
    # New resolved-CIF guard wiring is present.
    assert "from ..services.cif_resolver import resolve_cif, CIF_RESOLVED" in src
    assert "\"code\":   \"cif_unresolved\"" in src or '"code":   "cif_unresolved"' in src
    # The route exposes the resolved provenance on the block.
    assert "cif_state" in src and "cif_source" in src
    # The legacy raw-invoice blocker key is gone from this route.
    assert "cif_zero" not in src


def test_ui_gates_dsk_on_resolved_cif_so_no_zero_value_declaration():
    """The DSK generate/repair buttons carry the customs value on the
    declaration. They must be gated on the SAME resolved-CIF authority as the
    Polish Description (``_dskBlocked = !_decResolved``) so the UI can never POST
    a ``value_usd`` of 0 — a false zero-value customs declaration — when no
    authority has resolved a positive customs value. Source-grep contract on the
    V1 shipment-detail page (vanilla JSX, no bundler to assert against)."""
    html = (_SVC / "app" / "static" / "shipment-detail.html").read_text(encoding="utf-8")
    # The DSK gate exists and keys off the resolved-CIF authority.
    assert "_dskBlocked = !_decResolved" in html
    # Both DSK buttons honour the gate (disabled when CIF unresolved).
    assert html.count("|| _dskBlocked}") >= 2
    # The block surfaces an explicit operator reason (Lesson M: visible + disabled + reason).
    assert "CIF unresolved" in html
    assert "before generating a DSK" in html
