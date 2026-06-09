"""
test_wfirma_pz_guard_normalization.py — pz_preview/pz_create/pz_adopt guard
must trust the effective audit state, not a stale persisted status
string.

Bug:
  After /cn-decision/accept-sad cleared cn_match from failed_checks,
  a subsequent engine re-run wrote audit.status="failed" with
  failed_checks=[]. _guard_wfirma_export rejected pz_preview with
  WFIRMA_PZ_NOT_GENERATED because it only inspected the status string.

Fix:
  _compute_effective_pz_status(audit) normalises stale status when:
    failed_checks empty
    + MRN present
    + (verification.cn_match=True OR cn_decision.approved=True)
  → effective_status = "partial"
  Hard blocks remain when failed_checks non-empty or MRN missing.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api import routes_wfirma as rw

_svc = Path(__file__).parent.parent
if str(_svc) not in sys.path:
    sys.path.insert(0, str(_svc))


# ── Pure helper unit tests ────────────────────────────────────────────────

class TestComputeEffectivePzStatus:
    def _audit(self, **overrides):
        base = {
            "status":              "failed",
            "failed_checks":       [],
            "inputs":              {"zc429": "ZC.pdf"},
            "customs_declaration": {"mrn": "26PL44302D00AUCWR3"},
            "verification":        {"cn_match": True},
            "cn_decision":         {"approved": True},
        }
        base.update(overrides)
        return base

    def test_failed_with_empty_failed_checks_and_cn_accepted_normalises(self):
        eff, norm = rw._compute_effective_pz_status(self._audit())
        assert eff == "partial"
        assert norm is True

    def test_already_done_status_returns_unchanged(self):
        for done in ("success", "partial"):
            eff, norm = rw._compute_effective_pz_status(self._audit(status=done))
            assert eff == done
            assert norm is False

    def test_real_failed_check_blocks_normalisation(self):
        eff, norm = rw._compute_effective_pz_status(
            self._audit(failed_checks=["cif_match"]))
        assert eff == "failed"
        assert norm is False

    def test_missing_mrn_blocks_normalisation(self):
        eff, norm = rw._compute_effective_pz_status(
            self._audit(customs_declaration={}))
        assert eff == "failed"
        assert norm is False

    def test_unresolved_cn_blocks_normalisation(self):
        eff, norm = rw._compute_effective_pz_status(
            self._audit(verification={"cn_match": False},
                        cn_decision={"approved": False}))
        assert eff == "failed"
        assert norm is False

    def test_blocked_status_with_clean_state_normalises(self):
        # Same compatibility belt should also lift "blocked" → "partial"
        eff, norm = rw._compute_effective_pz_status(self._audit(status="blocked"))
        assert eff == "partial"
        assert norm is True


# ── Guard-level tests ─────────────────────────────────────────────────────

class TestGuardWfirmaExport:
    def _audit(self, **overrides):
        base = {
            "status":              "failed",
            "failed_checks":       [],
            "inputs":              {"zc429": "ZC.pdf"},
            "customs_declaration": {"mrn": "26PL44302D00AUCWR3"},
            "verification":        {"cn_match": True},
            "cn_decision":         {"approved": True},
        }
        base.update(overrides)
        return base

    def test_clean_audit_with_stale_failed_status_passes_guard(self):
        # The bug case — should NOT raise after the fix.
        rw._guard_wfirma_export(self._audit())

    def test_real_failed_check_still_blocks(self):
        with pytest.raises(HTTPException) as excinfo:
            rw._guard_wfirma_export(self._audit(failed_checks=["cif_match"]))
        assert excinfo.value.status_code == 422
        assert excinfo.value.detail["code"] == "WFIRMA_PZ_NOT_GENERATED"

    def test_missing_zc429_input_blocks_with_no_sad_code(self):
        with pytest.raises(HTTPException) as excinfo:
            rw._guard_wfirma_export(self._audit(inputs={}))
        assert excinfo.value.detail["code"] == "WFIRMA_NO_SAD"

    def test_missing_mrn_blocks_pz_not_generated(self):
        # SAD upload reference exists but MRN parsed value missing.
        with pytest.raises(HTTPException) as excinfo:
            rw._guard_wfirma_export(self._audit(customs_declaration={}))
        assert excinfo.value.status_code == 422
        assert excinfo.value.detail["code"] == "WFIRMA_PZ_NOT_GENERATED"

    def test_guard_error_payload_carries_normalisation_fields(self):
        with pytest.raises(HTTPException) as excinfo:
            rw._guard_wfirma_export(self._audit(failed_checks=["cif_match"]))
        d = excinfo.value.detail
        assert "stored_status"     in d
        assert "effective_status"  in d
        assert "status_normalized" in d
        assert d["stored_status"]    == "failed"
        assert d["effective_status"] == "failed"
        assert d["status_normalized"] is False

    def test_success_status_passes_unchanged(self):
        rw._guard_wfirma_export(self._audit(status="success"))


# ── Safety: pz_create still gated by capability flag ──────────────────────

class TestPzCreateCapabilityFlag:
    def test_create_flag_off_still_blocks_create(self, monkeypatch):
        """The normalisation only affects the SAD/PZ-status guard.
        pz_create's WFIRMA_CREATE_PZ_ALLOWED guard is independent and
        must still reject when the flag is off."""
        # Read the source — assert the flag check is still present
        # (string-level — no need to actually POST).
        src = (rw.__file__).replace(".pyc", ".py")
        with open(src, encoding="utf-8") as fh:
            text = fh.read()
        assert 'if not getattr(settings, "wfirma_create_pz_allowed", False):' in text
        assert 'PZ_CREATE_GATE_OFF' in text


# ── Safety: guard does not call wFirma client ─────────────────────────────

class TestGuardNoWfirmaWrite:
    def test_guard_makes_no_wfirma_client_calls(self):
        from app.services import wfirma_client
        with patch.object(wfirma_client, "create_product",
                          side_effect=AssertionError("no write")), \
             patch.object(wfirma_client, "create_customer",
                          side_effect=AssertionError("no write")):
            audit = {
                "status":              "failed",
                "failed_checks":       [],
                "inputs":              {"zc429": "ZC.pdf"},
                "customs_declaration": {"mrn": "MRN"},
                "verification":        {"cn_match": True},
                "cn_decision":         {"approved": True},
            }
            rw._guard_wfirma_export(audit)


# ── Regression: normalisation flags in pz_preview response ────────────────

class TestPreviewResponseShape:
    def test_response_includes_normalisation_fields(self):
        """pz_preview response must surface stored_status, effective_status,
        status_normalized so the dashboard can render the chip honestly."""
        src = (rw.__file__).replace(".pyc", ".py")
        with open(src, encoding="utf-8") as fh:
            text = fh.read()
        # Both pz_preview return paths (already_created + fresh) should
        # carry the three fields.
        assert text.count('"stored_status"')     >= 2
        assert text.count('"effective_status"')  >= 2
        assert text.count('"status_normalized"') >= 2


# ── pz_adopt capability flag (Guard 0) ───────────────────────────────────

class TestPzAdoptCapabilityFlag:
    """pz_adopt shares the same WFIRMA_CREATE_PZ_ALLOWED kill-switch as
    pz_create.  When the flag is False (the safe default), adopt must return
    403 / blocked — identical governance to create."""

    @pytest.fixture()
    def _storage(self, tmp_path):
        from app.services import packing_db   as pdb
        from app.services import warehouse_db as wdb
        from app.services import document_db  as ddb
        from app.services import wfirma_db    as wfdb
        from app.services import proforma_service_charges_db as scdb
        pdb.init_packing_db(tmp_path / "packing.db")
        wdb.init_warehouse_db(tmp_path / "warehouse.db")
        ddb.init_document_db(tmp_path / "documents.db")
        wfdb.init_wfirma_db(tmp_path / "wfirma.db")
        scdb.init(tmp_path / "proforma_links.db")
        return tmp_path

    @pytest.fixture()
    def _client_flag_off(self, _storage):
        """TestClient with wfirma_create_pz_allowed=False (safe default)."""
        from app.core.config import settings
        from app.main import app
        with patch.object(settings, "storage_root", _storage), \
             patch.object(settings, "wfirma_create_pz_allowed", False):
            with TestClient(app, raise_server_exceptions=True) as c:
                yield c

    @staticmethod
    def _auth():
        from app.core.config import settings
        return {"X-API-KEY": settings.api_key or "test-key"}

    def test_adopt_blocked_when_flag_is_false(self, _client_flag_off):
        """Guard 0: wfirma_create_pz_allowed=False → 200 with status=blocked
        before any wFirma call is attempted."""
        with patch("app.api.routes_wfirma.wfirma_client.fetch_warehouse_pz") as mock_f, \
             patch("app.api.routes_wfirma.wfirma_client.find_warehouse_pz_by_number") as mock_n:
            r = _client_flag_off.post(
                "/api/v1/upload/shipment/TEST_ADOPT_GATE/wfirma/pz_adopt",
                headers={**self._auth(), "X-Operator": "test"},
                json={"pz_doc_id": "183167843"},
            )

        assert r.status_code in (200, 403), r.text
        body = r.json()
        # Accept either 403 HTTP or 200+blocked — both are valid governance responses
        if r.status_code == 200:
            assert body.get("status") == "blocked", body
        reasons = body.get("blocking_reasons") or body.get("detail", {}) or {}
        reason_text = str(reasons)
        assert "WFIRMA_CREATE_PZ_ALLOWED" in reason_text, reason_text
        mock_f.assert_not_called()
        mock_n.assert_not_called()

    def test_adopt_gate_source_check(self):
        """Source-level: wfirma_pz_adopt checks wfirma_create_pz_allowed,
        same as wfirma_pz_create. Assert both patterns exist in source."""
        src = rw.__file__.replace(".pyc", ".py")
        with open(src, encoding="utf-8") as fh:
            text = fh.read()
        # Both create and adopt must guard on the same flag
        occurrences = text.count('getattr(settings, "wfirma_create_pz_allowed", False)')
        assert occurrences >= 2, (
            f"Expected wfirma_create_pz_allowed guard in both pz_create and pz_adopt "
            f"(found {occurrences} occurrences)"
        )


# ── Path B: pz_output evidence normalises "blocked" when MRN not parsed ─────
#
# AWB 9938632830 (2026-06-09): ZC429 PDF raster-scanned; MRN not extracted by
# parser.  Amendment flag: "Parse warning: MRN not found in ZC429".
# audit.status = "blocked", failed_checks = [], pz_output.pdf set,
# pz_output.generated_at set.  Without Path B, _guard_wfirma_export raises
# WFIRMA_PZ_NOT_GENERATED even though the engine ran successfully.

class TestComputeEffectivePzStatusPathB:
    """Path B: MRN absent but pz_output artifacts confirm engine ran."""

    def _audit_path_b(self, **overrides):
        base = {
            "status":              "blocked",
            "failed_checks":       [],
            "inputs":              {"zc429": "ZC.pdf"},
            # No MRN — typical for raster/barcode-only ZC429 PDFs
            "customs_declaration": {"mrn": ""},
            "verification":        {"cn_match": True},
            "cn_decision":         {"approved": False},
            # pz_output evidence written by process_batch()
            "pz_output": {
                "pdf":          "PZ_AWB_9938632830_MRN_UNKNOWN_UNKNOWN.pdf",
                "xlsx":         "PZ_Calc_AWB_9938632830.xlsx",
                "generated_at": "2026-06-09T12:10:41Z",
            },
        }
        base.update(overrides)
        return base

    def test_path_b_normalises_blocked_when_pz_output_set(self):
        """Core Path B case: engine ran (pdf + generated_at), no MRN parsed,
        failed_checks empty, cn_match True → normalise to 'partial'."""
        eff, norm = rw._compute_effective_pz_status(self._audit_path_b())
        assert eff == "partial"
        assert norm is True

    def test_path_b_normalises_failed_status_too(self):
        """The fix applies regardless of whether stored status is 'blocked'
        or 'failed'."""
        eff, norm = rw._compute_effective_pz_status(
            self._audit_path_b(status="failed"))
        assert eff == "partial"
        assert norm is True

    def test_path_b_requires_generated_at(self):
        """pdf alone is not enough; generated_at must also be present."""
        audit = self._audit_path_b()
        audit["pz_output"]["generated_at"] = ""
        eff, norm = rw._compute_effective_pz_status(audit)
        assert eff == "blocked"
        assert norm is False

    def test_path_b_requires_pdf(self):
        """generated_at alone is not enough; pdf must also be present."""
        audit = self._audit_path_b()
        audit["pz_output"]["pdf"] = ""
        eff, norm = rw._compute_effective_pz_status(audit)
        assert eff == "blocked"
        assert norm is False

    def test_path_b_absent_pz_output_does_not_normalise(self):
        """Neither Path A nor Path B applies → stored status returned."""
        audit = self._audit_path_b(pz_output={})
        eff, norm = rw._compute_effective_pz_status(audit)
        assert eff == "blocked"
        assert norm is False

    def test_path_b_real_failed_check_blocks_even_with_pz_output(self):
        """Real engine failure (failed_checks non-empty) blocks Path B."""
        audit = self._audit_path_b(failed_checks=["cif_match"])
        eff, norm = rw._compute_effective_pz_status(audit)
        assert eff == "blocked"
        assert norm is False

    def test_path_b_cn_not_resolved_blocks(self):
        """CN unresolved blocks both Path A and Path B."""
        audit = self._audit_path_b(
            verification={"cn_match": False},
            cn_decision={"approved": False},
        )
        eff, norm = rw._compute_effective_pz_status(audit)
        assert eff == "blocked"
        assert norm is False

    def test_guard_passes_for_path_b_audit(self):
        """_guard_wfirma_export must not raise for a Path B audit."""
        rw._guard_wfirma_export(self._audit_path_b())

    def test_path_a_takes_priority_when_mrn_present(self):
        """Path A (MRN present) fires before Path B — verify no double-counting."""
        audit = self._audit_path_b()
        audit["customs_declaration"] = {"mrn": "26PL44302D00DL8YU2"}
        eff, norm = rw._compute_effective_pz_status(audit)
        assert eff == "partial"
        assert norm is True  # Path A, but result is the same
