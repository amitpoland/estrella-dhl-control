"""
test_proforma_mapping_repair_ui.py — UI contract for the #1008/#1009 mapping
repair. Source-grep (no browser) assertions on proforma-detail.jsx plus an
endpoint-response check for the honest re-check payload.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_SVC = Path(__file__).resolve().parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))
os.environ.setdefault("API_KEY", "test-key")

_JSX = _SVC / "app" / "static" / "v2" / "proforma-detail.jsx"


def _src() -> str:
    return _JSX.read_text(encoding="utf-8")


def _code_only(src: str) -> str:
    return "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("//"))


class TestRecheckHonestToast:
    """#1009 — Re-check Mapping never reports false success."""

    def test_no_unconditional_success_wording(self):
        # the old toast reported "confirmed rows preserved" regardless of outcome
        assert "confirmed rows preserved" not in _code_only(_src()), \
            "re-check must not report a fixed success string regardless of result"

    def test_empty_draft_is_warned_not_succeeded(self):
        code = _code_only(_src())
        # the 0-line branch drives a warn, not a green success msg
        assert "line_count" in code
        assert "this draft has no lines" in _src().lower() or "no lines" in _src().lower()

    def test_missing_count_surfaces_a_warning(self):
        code = _code_only(_src())
        assert "missing" in code and "recheck.warn" in code

    def test_warn_channel_rendered_amber(self):
        code = _code_only(_src())
        assert 'data-testid="pf-source-recheck-warn"' in code
        assert "badge-amber-text" in code  # warn/err use the amber token, not green


class TestEnrichEndpointReportsLineCount:
    """The re-check endpoint response must carry line_count so the UI can tell
    an empty draft from an all-mapped one."""

    def test_response_includes_line_count(self, tmp_path, monkeypatch):
        from fastapi.testclient import TestClient
        from app.core.config import settings
        monkeypatch.setattr(settings, "api_key", "")   # disable auth for the unit call
        from app.main import app
        from app.services import proforma_invoice_link_db as pildb
        db = tmp_path / "proforma_links.db"
        monkeypatch.setattr("app.api.routes_proforma._proforma_db_path", lambda: db)
        d, _ = pildb.auto_create_draft_from_sales_packing(
            db, batch_id="RB1", client_name="ACME",
            currency="EUR", lines=[], operator="t")
        with TestClient(app, raise_server_exceptions=True) as c:
            r = c.post(f"/api/v1/proforma/draft/{d.id}/enrich-from-product-descriptions",
                       json={"expected_updated_at": d.updated_at})
        assert r.status_code == 200, r.text
        body = r.json()
        assert "line_count" in body, "response must carry line_count for honest UI reporting"
        assert body["line_count"] == 0


class TestUnmappedDesignsSurfacing:
    """#1009 — a draft must never be silently empty; designs with a design_no
    but no product_code are surfaced so the operator gets a reason + bind path."""

    class _Draft:
        def __init__(self, batch_id, cid="", cn=""):
            self.batch_id = batch_id
            self.client_contractor_id = cid
            self.client_name = cn

    def test_lists_unmapped_designs_for_client(self, monkeypatch):
        from app.api import routes_proforma as rp
        rows = [
            {"client_contractor_id": "C1", "client_name": "ACME", "design_no": "D-1", "product_code": ""},
            {"client_contractor_id": "C1", "client_name": "ACME", "design_no": "D-2", "product_code": ""},
            {"client_contractor_id": "C1", "client_name": "ACME", "design_no": "D-3", "product_code": "EJL/1-1"},  # mapped
            {"client_contractor_id": "C2", "client_name": "OTHER", "design_no": "D-9", "product_code": ""},        # other client
        ]
        monkeypatch.setattr(rp.ddb, "get_sales_packing_lines", lambda b: rows)
        out = rp._unmapped_designs_for_draft(self._Draft("B1", cid="C1", cn="ACME"))
        assert out == ["D-1", "D-2"], "only THIS client's unmapped designs, mapped/other excluded"

    def test_falls_back_to_client_name_when_no_contractor_id(self, monkeypatch):
        from app.api import routes_proforma as rp
        rows = [
            {"client_contractor_id": "", "client_name": "ACME", "design_no": "D-1", "product_code": ""},
            {"client_contractor_id": "", "client_name": "OTHER", "design_no": "D-2", "product_code": ""},
        ]
        monkeypatch.setattr(rp.ddb, "get_sales_packing_lines", lambda b: rows)
        out = rp._unmapped_designs_for_draft(self._Draft("B1", cid="", cn="ACME"))
        assert out == ["D-1"]

    def test_empty_when_all_mapped(self, monkeypatch):
        from app.api import routes_proforma as rp
        rows = [{"client_contractor_id": "C1", "client_name": "ACME", "design_no": "D-1", "product_code": "EJL/1-1"}]
        monkeypatch.setattr(rp.ddb, "get_sales_packing_lines", lambda b: rows)
        assert rp._unmapped_designs_for_draft(self._Draft("B1", cid="C1")) == []

    def test_dedupes_and_sorts(self, monkeypatch):
        from app.api import routes_proforma as rp
        rows = [
            {"client_contractor_id": "C1", "design_no": "D-2", "product_code": ""},
            {"client_contractor_id": "C1", "design_no": "D-1", "product_code": ""},
            {"client_contractor_id": "C1", "design_no": "D-1", "product_code": ""},
        ]
        monkeypatch.setattr(rp.ddb, "get_sales_packing_lines", lambda b: rows)
        assert rp._unmapped_designs_for_draft(self._Draft("B1", cid="C1")) == ["D-1", "D-2"]
