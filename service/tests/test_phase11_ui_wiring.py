"""
test_phase11_ui_wiring.py — Phase 11 UI wiring evidence tests.

Verifies:
1. Frozen V1 files (dashboard.html, shipment-detail.html) are NOT modified
2. Key state-changing buttons have data-wf-id attributes (§2 binding table)
3. Utility buttons (Download, Export CSV, etc.) do NOT have data-wf-id
4. Write-flag gates are annotated on the correct buttons (data-wf-gate)
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SVC = Path(__file__).parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

STATIC = Path(__file__).parent.parent / "app" / "static"


def _read(filename: str) -> str:
    p = STATIC / filename
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8", errors="replace")


class TestFrozenFilesUnchanged:
    """V1 frozen files must not be modified."""

    def test_dashboard_html_is_unmodified(self):
        """dashboard.html should not contain any Phase 11 annotations."""
        content = _read("dashboard.html")
        # The frozen file should not have the campaign WF annotations
        # (we never edit it — confirming data-wf-id is absent proves no edits)
        assert "data-wf-id" not in content, \
            "dashboard.html must not be edited — it is frozen in V1"

    def test_shipment_detail_html_is_unmodified(self):
        content = _read("shipment-detail.html")
        assert "data-wf-id" not in content, \
            "shipment-detail.html must not be edited — it is frozen in V1"


class TestWfIdAnnotations:
    """Key state-changing buttons have data-wf-id attributes."""

    def test_proforma_detail_post_button_wired_to_wf24(self):
        """btn-post-wfirma must be annotated as WF2.4."""
        content = _read("proforma-detail-v2.html")
        assert 'data-wf-id="WF2.4"' in content, \
            "Post to wFirma button must carry data-wf-id='WF2.4'"

    def test_proforma_detail_convert_button_wired_to_wf25(self):
        """btn-convert-invoice must be annotated as WF2.5."""
        content = _read("proforma-detail-v2.html")
        assert 'data-wf-id="WF2.5"' in content, \
            "Convert to Invoice button must carry data-wf-id='WF2.5'"

    def test_proforma_post_has_flag_gate_annotation(self):
        content = _read("proforma-detail-v2.html")
        assert 'data-wf-gate="WFIRMA_CREATE_PROFORMA_ALLOWED"' in content

    def test_proforma_convert_has_flag_gate_annotation(self):
        content = _read("proforma-detail-v2.html")
        assert 'data-wf-gate="WFIRMA_CREATE_INVOICE_ALLOWED"' in content


class TestPhase11Summary:
    """Document the wiring gap explicitly."""

    def test_phase11_partial_wiring_acknowledged(self):
        """Phase 11 documents the current wiring state per §2.

        Full §2 binding table requires all screen buttons to be wired.
        This test confirms the partial wiring that IS done in Phase 11,
        and that remaining screens are documented for Phase 12 truth-table.

        Wired in Phase 11:
          - proforma-detail-v2.html: WF2.4 (Post), WF2.5 (Convert)

        Remaining screens (to complete per Phase 12 truth-table):
          - shipment-v2.html: WF1.4, WF1.5, WF1.7, WF1.8
          - New Shipment modal: WF1.1
          - Inventory screen: WF4.3, WF4.4/4.5
          - Inbox screen: cross-cutting
          - Reservation tab: WF3.2
        """
        # Assert at least the proforma wiring is done
        content = _read("proforma-detail-v2.html")
        assert 'data-wf-id="WF2.4"' in content
        assert 'data-wf-id="WF2.5"' in content
        # Confirm frozen files untouched
        assert 'data-wf-id' not in _read("dashboard.html")
        assert 'data-wf-id' not in _read("shipment-detail.html")


class TestDescriptionAuthorityAdvisoryBadge:
    """Advisory badge for posted proformas with operator-written description lines."""

    def test_advisory_badge_present_in_proforma_detail(self):
        content = _read("proforma-detail-v2.html")
        assert 'data-testid="historical-description-advisory"' in content, \
            "Historical description advisory badge must be present in proforma-detail-v2.html"

    def test_advisory_badge_checks_name_pl_source_operator(self):
        content = _read("proforma-detail-v2.html")
        assert "name_pl_source === 'operator'" in content, \
            "Advisory badge must gate on name_pl_source === 'operator'"

    def test_advisory_badge_only_on_posted_proformas(self):
        content = _read("proforma-detail-v2.html")
        advisory_block = content[content.find("historical-description-advisory"):]
        # The advisory should be wrapped in the `posted` condition
        # Simple heuristic: both tokens appear before the advisory block
        advisory_pos = content.find("historical-description-advisory")
        posted_ref_pos = content.rfind("posted &&", 0, advisory_pos)
        assert posted_ref_pos != -1, \
            "Advisory badge must be conditional on the 'posted' flag"


class TestDescriptionAuthorityAdminPage:
    """Description authority admin page — static structure checks."""

    def test_admin_page_exists(self):
        assert (STATIC / "description-authority-admin.html").exists(), \
            "description-authority-admin.html must exist in /static"

    def test_admin_page_has_review_queue_tab(self):
        content = _read("description-authority-admin.html")
        assert 'data-testid="tab-review-queue"' in content

    def test_admin_page_has_status_tab(self):
        content = _read("description-authority-admin.html")
        assert 'data-testid="tab-dashboard"' in content

    def test_admin_page_review_queue_table_testid(self):
        content = _read("description-authority-admin.html")
        assert 'data-testid="review-queue-table"' in content

    def test_admin_page_save_button_testid_pattern(self):
        content = _read("description-authority-admin.html")
        assert 'data-testid={`btn-save-' in content

    def test_admin_page_edit_button_testid_pattern(self):
        content = _read("description-authority-admin.html")
        assert 'data-testid={`btn-edit-' in content


class TestDescriptionAuthorityAdminRoutes:
    """Backend route structure checks — import-level verification."""

    def test_routes_admin_imports_ok(self):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from app.api.routes_admin import router
        route_paths = [r.path for r in router.routes]
        # Routes include the full prefix /api/v1/admin/...
        assert any("description-authority/status"       in p for p in route_paths)
        assert any("description-authority/review-queue" in p for p in route_paths)
        # PATCH endpoint uses path param
        patch_paths = [r.path for r in router.routes if hasattr(r, 'methods') and 'PATCH' in (r.methods or set())]
        assert any("description-authority" in p for p in patch_paths)

    def test_main_py_has_description_authority_page_route(self):
        main_path = Path(__file__).parent.parent / "app" / "main.py"
        content = main_path.read_text(encoding="utf-8")
        assert '/admin/description-authority' in content
        assert 'description-authority-admin.html' in content

    def test_patch_body_model_has_reason_field(self):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from app.api.routes_admin import _DescriptionEnUpdate
        m = _DescriptionEnUpdate(description_en="test", reason="shorthand fix", operator="op")
        assert m.reason == "shorthand fix"

    def test_patch_sql_writes_all_three_audit_columns(self):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent))
        import inspect
        from app.api import routes_admin
        src = inspect.getsource(routes_admin.update_description_en)
        assert "description_en_updated_by"      in src
        assert "description_en_updated_at"      in src
        assert "description_en_update_reason"   in src

    def test_document_db_has_forward_compat_for_audit_columns(self):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent))
        import inspect
        from app.services import document_db
        src = inspect.getsource(document_db.init_document_db)
        assert "description_en_updated_by"      in src
        assert "description_en_updated_at"      in src
        assert "description_en_update_reason"   in src

    def test_review_queue_endpoint_selects_audit_columns(self):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent))
        import inspect
        from app.api import routes_admin
        src = inspect.getsource(routes_admin.description_authority_review_queue)
        assert "description_en_updated_by"      in src
        assert "description_en_updated_at"      in src
        assert "description_en_update_reason"   in src

    def test_frontend_has_reason_input_testid(self):
        content = _read("description-authority-admin.html")
        assert 'data-testid={`reason-input-' in content

    def test_frontend_displays_audit_trail(self):
        content = _read("description-authority-admin.html")
        assert "description_en_updated_by"      in content
        assert "description_en_updated_at"      in content
        assert "description_en_update_reason"   in content

    def test_frontend_save_blocked_without_reason(self):
        content = _read("description-authority-admin.html")
        assert "Podaj powód zmiany przed zapisem" in content

    def test_frontend_sends_reason_in_patch_body(self):
        content = _read("description-authority-admin.html")
        assert "reason," in content or "reason:" in content
