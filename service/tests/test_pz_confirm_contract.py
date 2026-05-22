"""PZ Number Confirm — request contract regression lock (2026-05-22).

Root cause of recurring HTTP 422:
  shipment-detail.html sent FormData({ doc_no: value }) to /set_pz.
  Backend /set_pz expects pz_number: str = Form(...).
  FastAPI Pydantic validation rejected the missing field → 422.
  Operator saw "Confirm PZ Number failed: HTTP 422" with no further detail.

Permanent fix:
  - Frontend migrated to /wfirma/pz_confirm with JSON body { pz_number }
    or { pz_doc_id } (auto-detected by whether input is purely numeric).
  - _PZAdoptBody model_validator rejects empty body with clean 422 + reason.
  - Structured error parsing: operator never sees raw "HTTP 422".
  - Confirm button disabled when input is empty.

These tests pin the contract so it cannot regress silently.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_svc = Path(__file__).parent.parent
if str(_svc) not in sys.path:
    sys.path.insert(0, str(_svc))

HTML   = Path(__file__).resolve().parent.parent / "app" / "static" / "shipment-detail.html"
ROUTES = Path(__file__).resolve().parent.parent / "app" / "api" / "routes_wfirma.py"


# ── 1. _PZAdoptBody rejects empty body ───────────────────────────────────────

def test_pz_adopt_body_rejects_empty_body():
    """Empty {} body must raise ValidationError before reaching Guard 1."""
    from pydantic import ValidationError
    from app.api.routes_wfirma import _PZAdoptBody
    with pytest.raises(ValidationError) as exc_info:
        _PZAdoptBody()
    errors = exc_info.value.errors()
    assert any(
        "pz_doc_id or pz_number is required" in str(e)
        for e in errors
    ), errors


# ── 2. _PZAdoptBody accepts pz_number only ────────────────────────────────────

def test_pz_adopt_body_accepts_pz_number_only():
    from app.api.routes_wfirma import _PZAdoptBody
    b = _PZAdoptBody(pz_number="PZ 9/5/2026")
    assert b.pz_number == "PZ 9/5/2026"
    assert b.pz_doc_id is None


# ── 3. _PZAdoptBody accepts pz_doc_id only ────────────────────────────────────

def test_pz_adopt_body_accepts_pz_doc_id_only():
    from app.api.routes_wfirma import _PZAdoptBody
    b = _PZAdoptBody(pz_doc_id="185759075")
    assert b.pz_doc_id == "185759075"
    assert b.pz_number is None


# ── 4. _PZAdoptBody accepts both fields ───────────────────────────────────────

def test_pz_adopt_body_accepts_both_fields():
    from app.api.routes_wfirma import _PZAdoptBody
    b = _PZAdoptBody(pz_doc_id="185759075", pz_number="PZ 9/5/2026")
    assert b.pz_doc_id == "185759075"
    assert b.pz_number  == "PZ 9/5/2026"


# ── 5. /wfirma/pz_confirm route exists (source-grep) ─────────────────────────

def test_pz_confirm_route_exists_source_grep():
    src = ROUTES.read_text(encoding="utf-8")
    assert '"/shipment/{batch_id}/wfirma/pz_confirm"' in src, (
        "routes_wfirma.py must declare the /wfirma/pz_confirm route"
    )
    assert "model_validator" in src, (
        "_PZAdoptBody must include a model_validator"
    )


# ── 6. Frontend confirm uses /wfirma/pz_confirm not /set_pz ──────────────────

def test_frontend_confirm_uses_pz_confirm_not_set_pz():
    src = HTML.read_text(encoding="utf-8")
    # Confirm handler must reference the authority route
    assert "wfirma/pz_confirm" in src, (
        "shipment-detail.html confirm handler must call /wfirma/pz_confirm"
    )
    # 'doc_no' must NOT appear as a FormData field in the confirm context
    # (it was the bug that caused recurring 422)
    idx = src.find("btn-confirm-pz-number")
    assert idx > 0, "btn-confirm-pz-number testid must exist"
    # Within a reasonable vicinity, doc_no should not be appended for confirm
    context = src[max(0, idx - 200):idx + 800]
    assert "doc_no" not in context, (
        "confirm button context must not append 'doc_no' — the legacy broken field"
    )


# ── 7. Frontend confirm button has disabled logic ─────────────────────────────

def test_frontend_confirm_button_has_disabled_logic():
    src = HTML.read_text(encoding="utf-8")
    btn_idx = src.find('data-testid="btn-confirm-pz-number"')
    assert btn_idx > 0, "btn-confirm-pz-number testid must exist"
    vicinity = src[btn_idx:btn_idx + 300]
    assert "disabled=" in vicinity, (
        "Confirm button must have a disabled= attribute"
    )
    # Must check pzNumber is non-empty before enabling
    assert "pzNumber" in vicinity and ("trim" in vicinity or "!pzNumber" in vicinity), (
        "disabled state must reference pzNumber and/or .trim()"
    )


# ── 8. No raw HTTP 422 surfaced to operator ───────────────────────────────────

def test_frontend_no_raw_422_in_confirm_handler():
    src = HTML.read_text(encoding="utf-8")
    # The confirm button context must NOT throw `HTTP ${r.status}` raw
    btn_idx = src.find('data-testid="btn-confirm-pz-number"')
    assert btn_idx > 0
    # The onClick handler spans forward from the button — take a wide window
    handler_text = src[btn_idx:btn_idx + 2500]
    # Confirm the authority route is referenced inside the handler
    assert "wfirma/pz_confirm" in handler_text, (
        "Confirm button onClick must reference /wfirma/pz_confirm"
    )
    # Structured error parsing must be present
    assert "detail" in handler_text and "reason" in handler_text, (
        "Confirm handler must parse structured error detail into a reason variable"
    )
    # Raw HTTP status string must NOT be the final throw/toast message
    assert "`HTTP ${r.status}`" not in handler_text, (
        "Confirm handler must not throw raw `HTTP ${r.status}` — parse response body instead"
    )
