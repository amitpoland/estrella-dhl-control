"""
test_phase2_advisory_gates.py — Phase 2 evidence tests.

Verifies that HS-1 (DHL email + SAD), HS-2 (wFirma product sync),
HS-3 (PZ-before-proforma) are softened to advisory when
advisory_gates_enabled=True — no 422/400 raised; advisory dict returned.

Invariant: wFirma write flags (CREATE_PRODUCT/PZ/PROFORMA/INVOICE) remain
hard regardless of advisory_gates_enabled.
"""
from __future__ import annotations
import sys
import pytest
from pathlib import Path
from unittest.mock import patch

# Ensure service is importable
_SVC = Path(__file__).parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))


# ── HS-1a: guard_pz_requires_sad ─────────────────────────────────────────────

class TestGuardPzRequiresSad:
    """guard_pz_requires_sad advisory vs hard behaviour."""

    def _audit_no_sad(self) -> dict:
        return {"batch_id": "TEST", "status": "ready", "inputs": {}, "zc429": {}}

    def _audit_with_pdf(self) -> dict:
        return {"batch_id": "TEST", "status": "ready",
                "inputs": {"zc429": "path/to/zc429.pdf"}}

    def _audit_with_xml_mrn(self) -> dict:
        return {"batch_id": "TEST", "status": "ready",
                "inputs": {}, "customs_declaration": {"mrn": "MRN12345"}}

    def test_hard_mode_raises_when_no_sad(self, monkeypatch):
        """Default (advisory OFF) raises HTTPException 422."""
        from app.core.guards import guard_pz_requires_sad
        from app.core.config import settings
        from fastapi import HTTPException

        monkeypatch.setattr(settings, "advisory_gates_enabled", False)
        with pytest.raises(HTTPException) as exc_info:
            guard_pz_requires_sad(self._audit_no_sad())
        assert exc_info.value.status_code == 422
        assert exc_info.value.detail["code"] == "PZ_NO_SAD"

    def test_advisory_mode_returns_dict_not_raises(self, monkeypatch):
        """advisory_gates_enabled=True returns advisory dict, never raises."""
        from app.core.guards import guard_pz_requires_sad
        from app.core.config import settings

        monkeypatch.setattr(settings, "advisory_gates_enabled", True)
        result = guard_pz_requires_sad(self._audit_no_sad())
        assert result is not None
        assert result["advisory"] is True
        assert result["code"] == "PZ_NO_SAD"

    def test_passes_when_pdf_present_either_mode(self, monkeypatch):
        """Guard passes (returns None) when ZC429 PDF present."""
        from app.core.guards import guard_pz_requires_sad
        from app.core.config import settings

        for flag in (False, True):
            monkeypatch.setattr(settings, "advisory_gates_enabled", flag)
            assert guard_pz_requires_sad(self._audit_with_pdf()) is None

    def test_passes_when_xml_mrn_present(self, monkeypatch):
        """Guard passes when XML MRN is present."""
        from app.core.guards import guard_pz_requires_sad
        from app.core.config import settings

        monkeypatch.setattr(settings, "advisory_gates_enabled", False)
        assert guard_pz_requires_sad(self._audit_with_xml_mrn()) is None

    def test_already_blocked_always_hard(self, monkeypatch):
        """PZ_ALREADY_PROCESSED guard is ALWAYS hard — never softened."""
        from app.core.guards import guard_pz_requires_sad
        from app.core.config import settings
        from fastapi import HTTPException

        monkeypatch.setattr(settings, "advisory_gates_enabled", True)
        audit_blocked = {"batch_id": "T", "status": "blocked",
                         "inputs": {"zc429": "has_pdf.pdf"}}
        with pytest.raises(HTTPException) as exc_info:
            guard_pz_requires_sad(audit_blocked)
        assert exc_info.value.detail["code"] == "PZ_ALREADY_PROCESSED"


# ── HS-1b: guard_dhl_requires_email ──────────────────────────────────────────

class TestGuardDhlRequiresEmail:
    """guard_dhl_requires_email advisory vs hard behaviour."""

    def _audit_no_email(self) -> dict:
        return {"batch_id": "TEST", "clearance_status": "unknown"}

    def _audit_with_ticket(self) -> dict:
        return {"batch_id": "TEST", "clearance_status": None, "dhl_ticket": "T12345"}

    def _audit_status_ok(self) -> dict:
        return {"batch_id": "TEST", "clearance_status": "dhl_email_received"}

    def _audit_awaiting_status(self) -> dict:
        return {"batch_id": "TEST", "clearance_status": "awaiting_dhl_customs_email"}

    def test_hard_mode_raises_when_no_email(self, monkeypatch):
        from app.core.guards import guard_dhl_requires_email
        from app.core.config import settings
        from fastapi import HTTPException

        monkeypatch.setattr(settings, "advisory_gates_enabled", False)
        with pytest.raises(HTTPException) as exc_info:
            guard_dhl_requires_email(self._audit_no_email())
        assert exc_info.value.status_code == 422
        assert exc_info.value.detail["code"] == "DHL_NO_EMAIL"

    def test_advisory_mode_returns_advisory_not_raises(self, monkeypatch):
        from app.core.guards import guard_dhl_requires_email
        from app.core.config import settings

        monkeypatch.setattr(settings, "advisory_gates_enabled", True)
        result = guard_dhl_requires_email(self._audit_no_email())
        assert result is not None
        assert result["advisory"] is True
        assert result["code"] == "DHL_NO_EMAIL"

    def test_passes_when_ticket_present_either_mode(self, monkeypatch):
        from app.core.guards import guard_dhl_requires_email
        from app.core.config import settings

        for flag in (False, True):
            monkeypatch.setattr(settings, "advisory_gates_enabled", flag)
            assert guard_dhl_requires_email(self._audit_with_ticket()) is None

    def test_passes_when_clearance_status_ok(self, monkeypatch):
        from app.core.guards import guard_dhl_requires_email
        from app.core.config import settings

        monkeypatch.setattr(settings, "advisory_gates_enabled", False)
        assert guard_dhl_requires_email(self._audit_status_ok()) is None

    def test_passes_when_awaiting_email_status(self, monkeypatch):
        """awaiting_dhl_customs_email is in clearance_ok — always passes."""
        from app.core.guards import guard_dhl_requires_email
        from app.core.config import settings

        monkeypatch.setattr(settings, "advisory_gates_enabled", False)
        assert guard_dhl_requires_email(self._audit_awaiting_status()) is None

    def test_admin_override_always_passes(self, monkeypatch):
        from app.core.guards import guard_dhl_requires_email
        from app.core.config import settings

        monkeypatch.setattr(settings, "advisory_gates_enabled", False)
        assert guard_dhl_requires_email(self._audit_no_email(), admin_override=True) is None


# ── HS-3: _check_proforma_export_prerequisites ───────────────────────────────

class TestProformaExportPrerequisites:
    """_check_proforma_export_prerequisites advisory vs hard mode."""

    def test_hard_mode_returns_blockers_when_no_pz(self, monkeypatch, tmp_path):
        import json
        from app.core.config import settings
        from app.api.routes_proforma import _check_proforma_export_prerequisites

        # Create audit without wfirma_pz_doc_id
        batch_id = "BATCH_TEST_001"
        output_dir = tmp_path / "outputs" / batch_id
        output_dir.mkdir(parents=True)
        (output_dir / "audit.json").write_text(
            json.dumps({"batch_id": batch_id, "wfirma_export": {}})
        )

        monkeypatch.setattr(settings, "storage_root", tmp_path)
        monkeypatch.setattr(settings, "advisory_gates_enabled", False)

        blockers = _check_proforma_export_prerequisites(batch_id)
        assert len(blockers) == 1
        assert "wFirma PZ" in blockers[0]

    def test_advisory_mode_returns_empty_blockers(self, monkeypatch, tmp_path):
        import json
        from app.core.config import settings
        from app.api.routes_proforma import _check_proforma_export_prerequisites

        batch_id = "BATCH_TEST_002"
        output_dir = tmp_path / "outputs" / batch_id
        output_dir.mkdir(parents=True)
        (output_dir / "audit.json").write_text(
            json.dumps({"batch_id": batch_id, "wfirma_export": {}})
        )

        monkeypatch.setattr(settings, "storage_root", tmp_path)
        monkeypatch.setattr(settings, "advisory_gates_enabled", True)

        # Advisory mode: no blockers returned (advisory surfaced through export_advisories)
        blockers = _check_proforma_export_prerequisites(batch_id)
        assert blockers == []

    def test_passes_when_pz_doc_id_present(self, monkeypatch, tmp_path):
        import json
        from app.core.config import settings
        from app.api.routes_proforma import _check_proforma_export_prerequisites

        batch_id = "BATCH_TEST_003"
        output_dir = tmp_path / "outputs" / batch_id
        output_dir.mkdir(parents=True)
        (output_dir / "audit.json").write_text(
            json.dumps({"batch_id": batch_id,
                        "wfirma_export": {"wfirma_pz_doc_id": "PZ-12345"}})
        )

        monkeypatch.setattr(settings, "storage_root", tmp_path)
        monkeypatch.setattr(settings, "advisory_gates_enabled", False)

        assert _check_proforma_export_prerequisites(batch_id) == []


# ── Flag default is OFF ───────────────────────────────────────────────────────

class TestAdvisoryFlagDefault:
    """advisory_gates_enabled defaults to False (hard mode)."""

    def test_flag_default_false(self):
        from app.core.config import settings
        assert settings.advisory_gates_enabled is False

    def test_hard_mode_is_default(self, monkeypatch):
        """Without monkeypatching, guards raise in the default config."""
        from app.core.guards import guard_pz_requires_sad
        from fastapi import HTTPException

        # Default flag is False — hard mode
        audit = {"batch_id": "T", "status": "ready", "inputs": {}}
        with pytest.raises(HTTPException) as exc_info:
            guard_pz_requires_sad(audit)
        assert exc_info.value.status_code == 422
