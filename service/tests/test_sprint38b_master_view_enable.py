"""Sprint 38b — Master 'View' action enable (read-only detail modal).

Target: service/app/static/v2/master-page.jsx

Contract under test
-------------------
The per-row "View" action was previously hardcoded ``disabled`` with a *write*-
disabled reason — a defect, because View is a read action and the backend
``GET /api/v1/customer-master/{id}`` already exists. This suite pins the fix:

  1. View is ENABLED and opens a read-only detail modal (no write path).
  2. A ``RecordDetailModal`` component exists and is explicitly read-only.
  3. SCOPE GUARD: the genuine write buttons (New / Export CSV / Import CSV)
     REMAIN disabled with their explicit reasons — enabling View must not
     leak write capability anywhere else (Lesson M).

These are source-grep assertions, matching the style of
test_sprint38_master_data_wiring.py (the file is in-browser Babel JSX; there is
no bundler/AST step in this stack).
"""
import pathlib
import re

import pytest

V2_DIR = pathlib.Path(__file__).resolve().parent.parent / "app" / "static" / "v2"
MASTER_PAGE = V2_DIR / "master-page.jsx"


def _read():
    assert MASTER_PAGE.exists(), f"master-page.jsx not found at {MASTER_PAGE}"
    return MASTER_PAGE.read_text(encoding="utf-8")


# ── 1. View action is enabled and wired ──────────────────────────────────────

def test_view_button_has_testid():
    assert 'data-testid="btn-view-record"' in _read(), \
        "View button missing data-testid='btn-view-record'"


def test_view_button_opens_modal():
    src = _read()
    assert "setViewRecord(r)" in src, \
        "View button must open the detail modal via setViewRecord(r)"


def test_view_button_not_disabled():
    """The View button region must NOT carry a disabled attribute or a
    write-disabled reason (that was the original defect)."""
    src = _read()
    m = re.search(r'data-testid="btn-view-record"', src)
    assert m, "btn-view-record testid not found"
    # Inspect the Btn element surrounding the testid.
    region = src[max(0, m.start() - 200): m.end() + 80]
    assert "disabled" not in region, \
        "View button is still disabled — read action must be enabled"
    assert "writeDisabledReason" not in region, \
        "View button still carries a write-disabled reason (defect)"


def test_viewrecord_state_exists():
    src = _read()
    assert "viewRecord" in src and "setViewRecord" in src, \
        "viewRecord state hook missing"


# ── 2. Read-only detail modal ────────────────────────────────────────────────

def test_record_detail_modal_component_exists():
    src = _read()
    assert "function RecordDetailModal" in src, "RecordDetailModal component missing"
    # createElement style: 'data-testid': 'record-detail-modal' (renders identically)
    assert "record-detail-modal" in src, "record-detail-modal testid missing"


def test_record_detail_modal_is_read_only():
    src = _read()
    assert "'Read-only'" in src or '"Read-only"' in src, \
        "Detail modal must be explicitly labelled read-only"
    assert "btn-close-detail" in src, "Detail modal missing close button testid"


def test_detail_modal_has_no_write_call():
    """The read-only modal must not call any mutating PzApi method."""
    src = _read()
    start = src.index("function RecordDetailModal")
    end = src.index("function MasterPage")
    modal_src = src[start:end]
    for forbidden in ("updateCustomerMaster", "deleteCustomerMaster",
                      "PzApi.put", "PzApi.post", "PzApi.delete", "_put(", "_post"):
        assert forbidden not in modal_src, \
            f"Read-only detail modal must not reference '{forbidden}'"


def test_detail_modal_null_record_guard():
    """Opening the modal with no record must short-circuit (no crash)."""
    src = _read()
    start = src.index("function RecordDetailModal")
    end = src.index("function MasterPage")
    modal_src = src[start:end]
    assert "if (!record) return null" in modal_src, \
        "Detail modal missing null-record guard"


# ── Defense-in-depth: sensitive-field redaction ──────────────────────────────
# The list endpoints already sanitise (e.g. GET /auth/users -> _safe_user, an
# allow-list). The modal must ALSO redact sensitive-looking keys so a future
# endpoint regression can never surface a secret in the UI.

def test_detail_modal_redacts_sensitive_keys():
    src = _read()
    assert "SENSITIVE_KEY_RE" in src, "Detail modal missing sensitive-key deny-list"
    start = src.index("function RecordDetailModal")
    end = src.index("function MasterPage")
    modal_src = src[start:end]
    assert "SENSITIVE_KEY_RE.test" in modal_src, \
        "Sensitive-key filter is declared but not applied to the rendered entries"
    re_decl = src[src.index("const SENSITIVE_KEY_RE"): src.index("const SENSITIVE_KEY_RE") + 220]
    for tok in ("pass", "secret", "token", "hash", "key", "credential"):
        assert tok in re_decl, f"Sensitive-key regex missing coverage for '{tok}'"


def test_detail_modal_discloses_redactions():
    """When fields are hidden, the operator must be told (no silent omission)."""
    src = _read()
    assert "redacted-note" in src, \
        "Detail modal must disclose when sensitive fields are hidden"


# ── 3. Scope guard: write buttons stay disabled (Lesson M) ────────────────────

@pytest.mark.parametrize("testid", [
    "btn-new-record",
    "btn-export-csv",
    "btn-import-csv",
])
def test_write_buttons_remain_disabled(testid):
    src = _read()
    m = re.search(re.escape(f'data-testid="{testid}"'), src)
    assert m, f"{testid} not found — write button must remain present"
    region = src[max(0, m.start() - 220): m.end() + 60]
    assert "disabled" in region, \
        f"{testid} must remain disabled — View-enable must not leak write capability"


def test_write_disabled_reason_constant_preserved():
    src = _read()
    assert "WRITE_DISABLED_REASON" in src, "WRITE_DISABLED_REASON constant removed"
    assert "Write operations not yet wired" in src, \
        "Generic write-disabled reason message removed"
