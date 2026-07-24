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
