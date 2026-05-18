"""Source-grep tests for routes_settings.py (Phase 7)."""
from pathlib import Path

ROUTES = Path(__file__).resolve().parent.parent / "app" / "api" / "routes_settings.py"


def _read():
    return ROUTES.read_text(encoding="utf-8")


def test_company_profile_get_endpoint_exists():
    assert "company-profile" in _read()


def test_company_profile_patch_endpoint_exists():
    src = _read()
    assert "PATCH" in src or "@router.patch" in src


def test_no_wfirma_import():
    assert "wfirma" not in _read().lower()


def test_no_audit_mutation():
    src = _read()
    assert "audit.json" not in src
    assert "write_json_atomic" not in src


def test_auth_dependency_present():
    src = _read()
    assert "_auth" in src or "dependencies=[" in src
