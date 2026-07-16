"""
test_insurance_wording_invoice_approval.py
Phases 1–5: Insurance wording + human invoice approval regression tests.

Pins:
  Phase 1 — Invoice control hardening
    1.  INVOICE_APPROVAL_REQUIRED sentinel exists and is True.
    2.  _check_invoice_approval_gates blocks when flag is false.
    3.  _check_invoice_approval_gates blocks when confirm token is wrong.
    4.  _check_invoice_approval_gates blocks when X-Operator is empty.
    5.  _check_invoice_approval_gates returns None when all gates pass.
    6.  record_invoice_approval_attempt exists in audit_persist.
    7.  EV_INVOICE_APPROVAL_ATTEMPT constant defined in audit_persist.
    8.  record_invoice_approval_attempt accepts "approved" outcome.
    9.  record_invoice_approval_attempt accepts "blocked" outcome.
    10. record_invoice_approval_attempt rejects unknown outcome gracefully.
    11. source-grep: no auto-invoke of invoices/add outside proforma_to_invoice.

  Phase 2 — Canonical insurance wording
    12. DEFAULT_INSURANCE_LINE_NAME is the canonical string.
    13. build_insurance_line_name(None) returns DEFAULT_INSURANCE_LINE_NAME.
    14. build_insurance_line_name() with no argument returns DEFAULT.
    15. Custom provider changes provider clause.
    16. coverage_type="cif" changes coverage description.
    17. coverage_type="warehouse_to_port" changes coverage description.
    18. language="pl" returns Polish wording.
    19. Empty provider falls back to DEFAULT_PROVIDER.
    20. Determinism: same inputs → same output.
    21. Unicode safety: non-ASCII provider round-trips correctly.
    22. No newlines in output.

  Phase 3 — Document propagation
    23. _build_service_charge_lines uses canonical wording for insurance.
    24. _build_service_charge_lines does NOT use canonical wording for freight.
    25. Insurance line name in wording matches DEFAULT_INSURANCE_LINE_NAME.
    26. source-grep: _build_service_charge_lines imports insurance_wording.
    27. source-grep: preview response includes insurance_line_name field.

  Phase 4 — Commercial validation
    28. No insurance charge → no wording in lines.
    29. Insurance charge present → wording in ReservationLine.product_name.
    30. Wording preserved after proforma_to_invoice LineItem copy.
    31. Wording is XML-safe (no raw < > & characters unescaped).

  Phase 5 — Legal safety
    32. source-grep: EV_INVOICE_APPROVAL_ATTEMPT is in audit_persist.
    33. source-grep: record_invoice_approval_attempt fires in proforma_to_invoice.
    34. source-grep: proforma_to_invoice calls _check_invoice_approval_gates.
    35. source-grep: INVOICE_APPROVAL_REQUIRED constant exists in routes_proforma.
    36. source-grep: no "background" invoice issuance in execution_engine.
    37. source-grep: no auto-fire of to-invoice in routes_carrier_webhook.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ── path bootstrap ─────────────────────────────────────────────────────────────
def _ensure_path() -> None:
    here = Path(__file__).resolve()
    for p in (str(here.parents[1]), str(here.parents[2])):
        if p not in sys.path:
            sys.path.insert(0, p)

_ensure_path()

_ROUTES     = Path(__file__).resolve().parents[1] / "app" / "api" / "routes_proforma.py"
_AUDIT_PERS = Path(__file__).resolve().parents[1] / "app" / "services" / "audit_persist.py"
_INS_WORDING= Path(__file__).resolve().parents[1] / "app" / "services" / "insurance_wording.py"
_EXEC_ENG   = Path(__file__).resolve().parents[1] / "app" / "services" / "execution_engine.py"
_WEBHOOK    = Path(__file__).resolve().parents[1] / "app" / "api" / "routes_carrier_webhook.py"


# ═══════════════════════════════════════════════════════════════════════════
# PHASE 1 — Invoice control hardening
# ═══════════════════════════════════════════════════════════════════════════

def test_invoice_approval_required_sentinel():
    """Pin 1: INVOICE_APPROVAL_REQUIRED is True."""
    from app.api.routes_proforma import INVOICE_APPROVAL_REQUIRED
    assert INVOICE_APPROVAL_REQUIRED is True


def test_check_invoice_approval_gates_blocks_flag_false():
    """Pin 2: gate blocks when WFIRMA_CREATE_INVOICE_ALLOWED=false."""
    from app.api.routes_proforma import _check_invoice_approval_gates
    from app.core.config import settings

    original = settings.wfirma_create_invoice_allowed
    try:
        settings.wfirma_create_invoice_allowed = False
        result = _check_invoice_approval_gates(
            batch_id="BATCH_01",
            client_name="Test",
            operator="amit",
            confirm="YES_CREATE_FINAL_INVOICE_FROM_PROFORMA",
        )
        assert result is not None, "Expected blocked JSONResponse when flag is false"
        import json
        body = json.loads(result.body)
        assert body["ok"] is False
        assert body["status"] == "blocked"
        assert any("WFIRMA_CREATE_INVOICE_ALLOWED" in r for r in body["blocking_reasons"])
    finally:
        settings.wfirma_create_invoice_allowed = original


def test_check_invoice_approval_gates_blocks_wrong_token():
    """Pin 3: gate blocks when confirm token is wrong."""
    from app.api.routes_proforma import _check_invoice_approval_gates
    from app.core.config import settings

    original = settings.wfirma_create_invoice_allowed
    try:
        settings.wfirma_create_invoice_allowed = True
        result = _check_invoice_approval_gates(
            batch_id="BATCH_01",
            client_name="Test",
            operator="amit",
            confirm="WRONG_TOKEN",
        )
        assert result is not None
        import json
        body = json.loads(result.body)
        assert body["ok"] is False
        assert "confirm token" in body["blocking_reasons"][0].lower()
    finally:
        settings.wfirma_create_invoice_allowed = original


def test_check_invoice_approval_gates_blocks_empty_operator():
    """Pin 4: gate blocks when X-Operator is empty."""
    from app.api.routes_proforma import _check_invoice_approval_gates
    from app.core.config import settings

    original = settings.wfirma_create_invoice_allowed
    try:
        settings.wfirma_create_invoice_allowed = True
        result = _check_invoice_approval_gates(
            batch_id="BATCH_01",
            client_name="Test",
            operator="",
            confirm="YES_CREATE_FINAL_INVOICE_FROM_PROFORMA",
        )
        assert result is not None
        import json
        body = json.loads(result.body)
        assert body["ok"] is False
        assert any("operator" in r.lower() for r in body["blocking_reasons"])
    finally:
        settings.wfirma_create_invoice_allowed = original


def test_check_invoice_approval_gates_passes_all():
    """Pin 5: gate returns None when all gates pass."""
    from app.api.routes_proforma import _check_invoice_approval_gates
    from app.core.config import settings

    original = settings.wfirma_create_invoice_allowed
    try:
        settings.wfirma_create_invoice_allowed = True
        result = _check_invoice_approval_gates(
            batch_id="BATCH_01",
            client_name="Test",
            operator="amit",
            confirm="YES_CREATE_FINAL_INVOICE_FROM_PROFORMA",
        )
        assert result is None, f"Expected None (gates passed) but got {result}"
    finally:
        settings.wfirma_create_invoice_allowed = original


def test_record_invoice_approval_attempt_exists():
    """Pin 6: function exists in audit_persist."""
    from app.services.audit_persist import record_invoice_approval_attempt
    assert callable(record_invoice_approval_attempt)


def test_ev_invoice_approval_attempt_constant():
    """Pin 7: EV_INVOICE_APPROVAL_ATTEMPT constant defined."""
    from app.services.audit_persist import EV_INVOICE_APPROVAL_ATTEMPT
    assert EV_INVOICE_APPROVAL_ATTEMPT == "invoice_approval_attempt"


def test_record_invoice_approval_attempt_approved(tmp_path):
    """Pin 8: record_invoice_approval_attempt accepts 'approved' outcome."""
    from app.services.audit_persist import record_invoice_approval_attempt
    audit = tmp_path / "audit.json"
    audit.write_text('{"timeline": []}', encoding="utf-8")
    result = record_invoice_approval_attempt(
        audit,
        batch_id="BATCH_01",
        client_name="Test",
        wfirma_proforma_id="PID_001",
        operator="amit",
        outcome="approved",
    )
    assert result["appended"] is True


def test_record_invoice_approval_attempt_blocked(tmp_path):
    """Pin 9: record_invoice_approval_attempt accepts 'blocked' outcome."""
    from app.services.audit_persist import record_invoice_approval_attempt
    audit = tmp_path / "audit.json"
    audit.write_text('{"timeline": []}', encoding="utf-8")
    result = record_invoice_approval_attempt(
        audit,
        batch_id="BATCH_01",
        client_name="Test",
        wfirma_proforma_id="",
        operator="",
        outcome="blocked",
        blocking_reason="flag is false",
    )
    assert result["appended"] is True


def test_record_invoice_approval_attempt_unknown_outcome(tmp_path):
    """Pin 10: unknown outcome is normalised to 'unknown', not an error."""
    from app.services.audit_persist import record_invoice_approval_attempt
    audit = tmp_path / "audit.json"
    audit.write_text('{"timeline": []}', encoding="utf-8")
    # Must not raise even with junk outcome
    result = record_invoice_approval_attempt(
        audit,
        batch_id="BATCH_01",
        client_name="Test",
        wfirma_proforma_id="PID_001",
        operator="amit",
        outcome="JUNK_OUTCOME",
    )
    # Either appended or failed gracefully — must not raise
    assert "appended" in result


def test_no_auto_invoke_invoices_add_outside_proforma_route():
    """Pin 11: invoices/add is never auto-called outside the explicit route."""
    # Only routes_proforma.py and wfirma_client.py should call invoices/add.
    # execution_engine.py must not.
    if _EXEC_ENG.exists():
        text = _EXEC_ENG.read_text(encoding="utf-8")
        assert "invoices/add" not in text, (
            "execution_engine.py must not contain invoices/add — "
            "invoice issuance is manual-only via routes_proforma"
        )


# ═══════════════════════════════════════════════════════════════════════════
# PHASE 2 — Canonical insurance wording
# ═══════════════════════════════════════════════════════════════════════════

def test_default_insurance_line_name_is_canonical():
    """Pin 12: DEFAULT_INSURANCE_LINE_NAME matches the required wording."""
    from app.services.insurance_wording import DEFAULT_INSURANCE_LINE_NAME
    assert "Insurance covers the Door to Door" in DEFAULT_INSURANCE_LINE_NAME
    assert "Future Generali India Insurance Company Limited" in DEFAULT_INSURANCE_LINE_NAME
    assert DEFAULT_INSURANCE_LINE_NAME.endswith(".")


def test_build_none_returns_default():
    """Pin 13: build_insurance_line_name(None) == DEFAULT_INSURANCE_LINE_NAME."""
    from app.services.insurance_wording import (
        build_insurance_line_name, DEFAULT_INSURANCE_LINE_NAME,
    )
    assert build_insurance_line_name(None) == DEFAULT_INSURANCE_LINE_NAME


def test_build_no_arg_returns_default():
    """Pin 14: build_insurance_line_name() == DEFAULT_INSURANCE_LINE_NAME."""
    from app.services.insurance_wording import (
        build_insurance_line_name, DEFAULT_INSURANCE_LINE_NAME,
    )
    assert build_insurance_line_name() == DEFAULT_INSURANCE_LINE_NAME


def test_custom_provider():
    """Pin 15: custom provider replaces the default provider clause."""
    from app.services.insurance_wording import build_insurance_line_name, InsuranceWordingInput
    result = build_insurance_line_name(InsuranceWordingInput(insurance_provider="Acme Insurance Ltd"))
    assert "Acme Insurance Ltd" in result
    assert "Future Generali" not in result


def test_cif_coverage_type():
    """Pin 16: coverage_type='cif' produces 'CIF' in wording."""
    from app.services.insurance_wording import build_insurance_line_name, InsuranceWordingInput
    result = build_insurance_line_name(InsuranceWordingInput(coverage_type="cif"))
    assert "CIF" in result
    assert "Door to Door" not in result


def test_warehouse_to_port_coverage():
    """Pin 17: coverage_type='warehouse_to_port' produces 'Warehouse to Port'."""
    from app.services.insurance_wording import build_insurance_line_name, InsuranceWordingInput
    result = build_insurance_line_name(InsuranceWordingInput(coverage_type="warehouse_to_port"))
    assert "Warehouse to Port" in result


def test_polish_language():
    """Pin 18: language='pl' returns Polish wording starting with 'Ubezpieczenie'."""
    from app.services.insurance_wording import build_insurance_line_name, InsuranceWordingInput
    result = build_insurance_line_name(InsuranceWordingInput(language="pl"))
    assert "Ubezpieczenie" in result
    # English opening phrase must not appear (provider name may still contain "Insurance")
    assert "Insurance covers" not in result
    assert result.startswith("Ubezpieczenie")


def test_empty_provider_falls_back():
    """Pin 19: empty insurance_provider falls back to DEFAULT_PROVIDER."""
    from app.services.insurance_wording import (
        build_insurance_line_name, InsuranceWordingInput, DEFAULT_PROVIDER,
    )
    result = build_insurance_line_name(InsuranceWordingInput(insurance_provider=""))
    assert DEFAULT_PROVIDER in result


def test_determinism():
    """Pin 20: same inputs always produce same output."""
    from app.services.insurance_wording import build_insurance_line_name, InsuranceWordingInput
    inp = InsuranceWordingInput(insurance_provider="Test Co", coverage_type="cif")
    results = {build_insurance_line_name(inp) for _ in range(10)}
    assert len(results) == 1, "build_insurance_line_name must be deterministic"


def test_unicode_provider():
    """Pin 21: non-ASCII provider round-trips correctly."""
    from app.services.insurance_wording import build_insurance_line_name, InsuranceWordingInput
    provider = "Übersee Versicherungs AG"
    result = build_insurance_line_name(InsuranceWordingInput(insurance_provider=provider))
    assert provider in result


def test_no_newlines_in_output():
    """Pin 22: output never contains newlines."""
    from app.services.insurance_wording import build_insurance_line_name, InsuranceWordingInput
    for inp in (None, InsuranceWordingInput(), InsuranceWordingInput(language="pl")):
        result = build_insurance_line_name(inp)
        assert "\n" not in result
        assert "\r" not in result


# ═══════════════════════════════════════════════════════════════════════════
# PHASE 3 — Document propagation
# ═══════════════════════════════════════════════════════════════════════════

def _make_wfdb_mock(monkeypatch):
    """Wire the product resolution so _build_service_charge_lines finds both
    products. C-3g: identity (wfirma good id) now comes from the Product
    MIRROR via routes_proforma._c1f_mirror_good_id; emission metadata
    (display label, unit) comes from the PROFORMA authority's
    service_product_registry (pildb.get_all_service_product_meta). The
    legacy wfdb.get_product cache is no longer consulted by the route."""
    from app.api import routes_proforma
    import app.services.proforma_invoice_link_db as pildb

    _good_ids = {"freight": "WFP-99001", "insurance": "WFP-99002"}
    monkeypatch.setattr(routes_proforma, "_c1f_mirror_good_id",
                        lambda ct: _good_ids.get(ct))

    _meta = {
        "freight":   {"charge_type": "freight",   "product_name": "Fracht",
                      "vat_rate": "23", "unit": "szt.", "updated_at": ""},
        "insurance": {"charge_type": "insurance", "product_name": "Ubezpieczenie",
                      "vat_rate": "23", "unit": "szt.", "updated_at": ""},
    }
    monkeypatch.setattr(pildb, "get_all_service_product_meta",
                        lambda db_path: dict(_meta))


def test_build_service_charge_lines_insurance_uses_canonical_wording(monkeypatch):
    """Pin 23: insurance line uses DEFAULT_INSURANCE_LINE_NAME."""
    _make_wfdb_mock(monkeypatch)
    from app.api.routes_proforma import _build_service_charge_lines
    from app.services.insurance_wording import DEFAULT_INSURANCE_LINE_NAME

    lines, note = _build_service_charge_lines(
        [{"charge_type": "insurance", "amount": 60.00, "currency": "USD"}],
        "USD",
    )
    assert len(lines) == 1
    assert lines[0].product_name == DEFAULT_INSURANCE_LINE_NAME, (
        f"Expected canonical wording, got: {lines[0].product_name!r}"
    )
    assert note == ""


def test_build_service_charge_lines_freight_uses_registry_name(monkeypatch):
    """Pin 24: freight line uses registry product_name_pl, not canonical insurance wording."""
    _make_wfdb_mock(monkeypatch)
    from app.api.routes_proforma import _build_service_charge_lines

    lines, note = _build_service_charge_lines(
        [{"charge_type": "freight", "amount": 90.00, "currency": "USD"}],
        "USD",
    )
    assert len(lines) == 1
    assert lines[0].product_name == "Fracht"


def test_insurance_wording_matches_default_constant(monkeypatch):
    """Pin 25: the exact wording on the line matches DEFAULT_INSURANCE_LINE_NAME."""
    _make_wfdb_mock(monkeypatch)
    from app.api.routes_proforma import _build_service_charge_lines
    from app.services.insurance_wording import DEFAULT_INSURANCE_LINE_NAME

    lines, _ = _build_service_charge_lines(
        [{"charge_type": "insurance", "amount": 50.0, "currency": "EUR"}],
        "EUR",
    )
    assert lines[0].product_name == DEFAULT_INSURANCE_LINE_NAME


def test_routes_proforma_imports_insurance_wording():
    """Pin 26: source-grep: _build_service_charge_lines imports insurance_wording."""
    text = _ROUTES.read_text(encoding="utf-8")
    assert "insurance_wording" in text, (
        "routes_proforma.py must import from insurance_wording module"
    )
    assert "build_insurance_line_name" in text


def test_preview_response_includes_insurance_line_name_field():
    """Pin 27: source-grep: preview response contains 'insurance_line_name' key."""
    text = _ROUTES.read_text(encoding="utf-8")
    assert "insurance_line_name" in text, (
        "routes_proforma.py preview response must include 'insurance_line_name' field"
    )


# ═══════════════════════════════════════════════════════════════════════════
# PHASE 4 — Commercial validation
# ═══════════════════════════════════════════════════════════════════════════

def test_no_insurance_charge_means_no_wording(monkeypatch):
    """Pin 28: no insurance charge → empty lines (no wording)."""
    _make_wfdb_mock(monkeypatch)
    from app.api.routes_proforma import _build_service_charge_lines

    lines, note = _build_service_charge_lines(
        [{"charge_type": "freight", "amount": 90.00, "currency": "USD"}],
        "USD",
    )
    # Only freight — no insurance line
    assert all(l.product_code != "insurance" for l in lines)


def test_insurance_charge_produces_wording_in_product_name(monkeypatch):
    """Pin 29: insurance charge → ReservationLine.product_name = canonical wording."""
    _make_wfdb_mock(monkeypatch)
    from app.api.routes_proforma import _build_service_charge_lines
    from app.services.insurance_wording import DEFAULT_INSURANCE_LINE_NAME

    lines, _ = _build_service_charge_lines(
        [{"charge_type": "insurance", "amount": 75.0, "currency": "USD"}],
        "USD",
    )
    ins = next((l for l in lines if l.product_code == "insurance"), None)
    assert ins is not None
    assert ins.product_name == DEFAULT_INSURANCE_LINE_NAME


def test_invoice_conversion_preserves_line_name():
    """Pin 30: proforma_to_invoice.LineItem copies name verbatim."""
    from app.services.proforma_to_invoice import LineItem
    from app.services.insurance_wording import DEFAULT_INSURANCE_LINE_NAME

    item = LineItem(
        name        = DEFAULT_INSURANCE_LINE_NAME,
        good_id     = "WFP-99002",
        unit        = "szt.",
        unit_count  = "1.0000",
        price       = "75.00",
        vat_code_id = "VAT-23",
    )
    # LineItem is frozen — no mutation possible
    assert item.name == DEFAULT_INSURANCE_LINE_NAME


def test_wording_is_xml_safe():
    """Pin 31: canonical wording contains no raw XML-unsafe characters."""
    from app.services.insurance_wording import DEFAULT_INSURANCE_LINE_NAME
    # Raw (unescaped) chars that would break XML
    for char in ("<", ">", "&", '"', "'"):
        assert char not in DEFAULT_INSURANCE_LINE_NAME, (
            f"DEFAULT_INSURANCE_LINE_NAME contains raw XML-unsafe char: {char!r}"
        )


# ═══════════════════════════════════════════════════════════════════════════
# PHASE 5 — Legal safety (source-grep)
# ═══════════════════════════════════════════════════════════════════════════

def test_ev_invoice_approval_attempt_in_audit_persist():
    """Pin 32: EV_INVOICE_APPROVAL_ATTEMPT is defined in audit_persist."""
    text = _AUDIT_PERS.read_text(encoding="utf-8")
    assert "EV_INVOICE_APPROVAL_ATTEMPT" in text
    assert "invoice_approval_attempt" in text


def test_record_invoice_approval_attempt_fires_in_proforma_route():
    """Pin 33: routes_proforma calls record_invoice_approval_attempt."""
    text = _ROUTES.read_text(encoding="utf-8")
    assert "record_invoice_approval_attempt" in text, (
        "routes_proforma.py must call record_invoice_approval_attempt "
        "to ensure complete audit trail on every conversion attempt"
    )


def test_proforma_to_invoice_uses_check_gate():
    """Pin 34: proforma_to_invoice calls _check_invoice_approval_gates."""
    text = _ROUTES.read_text(encoding="utf-8")
    assert "_check_invoice_approval_gates" in text, (
        "proforma_to_invoice must use _check_invoice_approval_gates "
        "for the human approval boundary"
    )


def test_invoice_approval_required_in_routes():
    """Pin 35: INVOICE_APPROVAL_REQUIRED constant is in routes_proforma."""
    text = _ROUTES.read_text(encoding="utf-8")
    assert "INVOICE_APPROVAL_REQUIRED" in text


def test_execution_engine_has_no_invoice_issuance():
    """Pin 36: execution_engine never auto-invokes invoices/add."""
    if not _EXEC_ENG.exists():
        pytest.skip("execution_engine.py not found")
    text = _EXEC_ENG.read_text(encoding="utf-8")
    assert "invoices/add" not in text
    assert "to-invoice" not in text


def test_carrier_webhook_has_no_invoice_issuance():
    """Pin 37: routes_carrier_webhook never calls invoice creation."""
    if not _WEBHOOK.exists():
        pytest.skip("routes_carrier_webhook.py not found")
    text = _WEBHOOK.read_text(encoding="utf-8")
    assert "proforma_to_invoice" not in text, (
        "routes_carrier_webhook must never auto-trigger invoice creation"
    )
    assert "invoices/add" not in text
