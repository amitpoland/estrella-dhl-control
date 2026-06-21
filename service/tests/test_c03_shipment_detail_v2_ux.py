"""
test_c03_shipment_detail_v2_ux.py — Campaign-03 Sprint 03.2 UX contract.

Covers the authority-honest UX polish of the served Shipment Detail V2 page
(service/app/static/v2/shipment-detail-page.jsx). Static source-grep only — no
server, no JSX execution.

Intent (operator-authorized Option B — "Polish + Lesson-M Honesty"):
  • Every fake-success action (simulateAction / notify setTimeout / local setters
    that lie about backend progress) is converted to an HONEST backend-pending
    control: visible, disabled, with an explicit reason + the real backend route.
  • Full data-testid coverage for every interactive control.
  • Accessibility: tablist/tab/tabpanel roles, aria-selected, aria-current,
    keyboard navigation, page-local focus-visible styling.
  • Real paths preserved verbatim (Documents fetch, Proforma navigation).

These assertions are the regression fence for Lesson M (no capability removed —
each stays visible+disabled+reasoned) and B1 (no enabled success without backend).
"""
from __future__ import annotations

import re
from pathlib import Path

_DETAIL = Path(__file__).resolve().parents[1] / "app" / "static" / "v2" / "shipment-detail-page.jsx"
_MOCK_BADGE = Path(__file__).resolve().parents[1] / "app" / "static" / "v2" / "mock-badge.jsx"


def _src() -> str:
    return _DETAIL.read_text(encoding="utf-8")


# ── A. Fake-success machinery removed ─────────────────────────────────────────

def test_no_simulate_action():
    """The fake setTimeout 'simulateAction' helper must be gone."""
    assert "simulateAction" not in _src(), (
        "simulateAction still present — fake-success action machinery not removed"
    )


def test_no_notify_toast():
    """The fake 'notify' toast (faked success/info) must be gone."""
    src = _src()
    assert "notify(" not in src and "const notify" not in src, (
        "notify() fake toast still present — actions must not fake success"
    )
    assert "setNotification" not in src, "notification state must be removed"


def test_no_fake_progress_setters():
    """Workflow state must be derived read-only — no local setters faking progress."""
    src = _src()
    for forbidden in (
        "setSadUploaded", "setPzGenerated", "setPzExported",
        "setDhlEmailReceived", "setReplySent", "setConfirmingPz", "setPzNumber",
    ):
        assert forbidden not in src, (
            f"{forbidden} still present — workflow progress must be derived from "
            "authoritative shipment props, never faked by a local setter"
        )


def test_state_is_derived_from_props():
    """sadUploaded/pzGenerated/etc must be derived consts off the shipment prop."""
    src = _src()
    assert "const sadUploaded" in src and "shipment.sadStatus" in src
    assert "const pzGenerated" in src and "shipment.pzStatus" in src
    assert "const replySent" in src and "shipment.dhlStatus" in src


# ── B. Honest backend-pending controls ────────────────────────────────────────

def test_pending_action_component_present():
    """A PendingAction primitive renders disabled controls with route + state attrs."""
    src = _src()
    assert "function PendingAction(" in src, "PendingAction component missing"
    assert 'data-action-state="backend-pending"' in src, "backend-pending state attr missing"
    assert "data-backend-route=" in src, "data-backend-route attribute missing"
    # PendingAction must render a disabled control (no enabled fake success)
    assert "disabled" in src.split("function PendingAction(")[1].split("}")[0] + \
        src.split("function PendingAction(")[1][:400], "PendingAction must be disabled"


def test_backend_pending_banner_present():
    """An explicit operator-facing reason banner heads the backend-pending panels."""
    src = _src()
    assert "function BackendPendingBanner(" in src, "BackendPendingBanner missing"
    assert "BACKEND_GAP_REGISTER.md" in src, "must reference the backend gap register"
    assert 'testid="dhl-actions-pending-note"' in src
    assert 'testid="pz-actions-pending-note"' in src


def test_all_action_testids_present():
    """Every converted action control keeps a stable testid (capability still visible)."""
    src = _src()
    for tid in (
        "scan-dhl-inbox", "mark-email-received", "generate-polish-desc",
        "generate-dsk", "build-reply-package", "send-reply", "upload-sad",
        "run-pz", "confirm-pz", "copy-wfirma", "export-wfirma",
    ):
        assert f'testid="{tid}"' in src, f"action testid '{tid}' missing"


def test_action_controls_name_real_routes():
    """Each backend-pending control names the real backend route it maps to."""
    src = _src()
    for route in (
        "/api/v1/dhl/scan-inbox",
        "/api/v1/dhl/mark-email-received/",
        "/api/v1/dhl/generate-description/",
        "/api/v1/dhl/generate-customs-package/",
        "/api/v1/dhl/send-reply/",
        "/api/v1/upload/shipment/",
        # wFirma PZ routes live under the upload router prefix (/api/v1/upload),
        # NOT a bare /api/v1/shipment path. Pin the full real prefix so an
        # "honest" backend-pending control can never name a 404 route again.
        "/api/v1/upload/shipment/' + bid + '/wfirma/pz_create",
        "/api/v1/upload/shipment/' + bid + '/wfirma/pz_confirm",
        "/api/v1/upload/shipment/' + bid + '/wfirma/clipboard",
    ):
        assert route in src, f"backend route reference '{route}' missing"
    # Negative: the bare /api/v1/shipment/.../wfirma path (missing the /upload
    # router prefix) is a 404 — it must never be named as a "real" route.
    assert "/api/v1/shipment/' + bid + '/wfirma/" not in src, (
        "wFirma PZ route is missing the /api/v1/upload prefix — that path 404s, "
        "so naming it in a backend-pending control reintroduces the B1 lie"
    )


# ── C. Lesson M — relocation keeps a redirect to real authority ───────────────

def test_pz_downloads_relocated_with_redirect():
    """The 6 PZ download buttons relocate to Documents with a visible redirect +
    named file types (Lesson M: visible + named + redirect, no silent removal)."""
    src = _src()
    assert 'data-testid="pz-open-documents"' in src, "Documents redirect button missing"
    assert "setActiveTab('documents')" in src, "redirect must switch to Documents tab"
    for label in ("PZ PDF", "Calculation XLSX", "Audit EN", "Audit PL", "Audit Memo", "Corrections"):
        assert label in src, f"relocated file type '{label}' must stay named on the page"


def test_pz_locked_state_is_honest():
    """PZ locked precondition is an explicit unavailable state, not a hidden tab."""
    src = _src()
    assert 'data-testid="pz-locked"' in src
    assert 'data-action-state="unavailable"' in src


# ── D. Accessibility ──────────────────────────────────────────────────────────

def test_tablist_aria_roles():
    """Tabs use proper tablist/tab/tabpanel semantics."""
    src = _src()
    assert 'role="tablist"' in src
    assert 'role="tab"' in src
    assert 'role="tabpanel"' in src
    assert "aria-selected=" in src
    assert "aria-current=" in src
    assert "aria-controls=" in src


def test_tab_keyboard_navigation():
    """Tab strip supports arrow/Home/End keyboard navigation."""
    src = _src()
    assert "onTabKeyDown" in src, "keyboard handler missing"
    for key in ("ArrowRight", "ArrowLeft", "Home", "End"):
        assert key in src, f"keyboard key '{key}' not handled"


def test_tab_testids_dynamic():
    """Each tab carries a deterministic tab-<id> testid."""
    src = _src()
    assert "data-testid={'tab-' + t.id}" in src, "dynamic tab testid missing"


def test_focus_visible_styling():
    """A page-local focus-visible outline exists for keyboard users."""
    src = _src()
    assert ":focus-visible" in src, "focus-visible styling missing"


def test_back_button_accessible():
    """Back button has a testid and an aria-label."""
    src = _src()
    assert 'data-testid="detail-back"' in src
    assert 'aria-label="Back to shipment list"' in src


def test_workflow_strip_list_semantics():
    """Workflow progress strip exposes list/listitem semantics with state labels."""
    src = _src()
    assert 'role="list"' in src and 'role="listitem"' in src
    assert 'data-testid="workflow-strip"' in src


# ── E. Real paths preserved (no regression of designated real wiring) ─────────

def test_documents_fetch_preserved():
    """Documents tab still fetches the real dashboard files endpoint."""
    src = _src()
    assert "/api/v1/dashboard/batches/" in src and "/files" in src
    assert "if (!batchId)" in src


def test_proforma_navigation_preserved():
    """Proforma tab still navigates to the real Pro Forma hub with batch context."""
    src = _src()
    assert "/v2/proforma?batch_id=" in src
    assert 'data-testid="proforma-tab-open"' in src


def test_no_alert_calls():
    """No dead-end alert() mock navigation anywhere on the page."""
    assert "alert(" not in _src(), "alert() must not be used — real navigation only"


def test_uses_components_jsx_atoms_not_pz_components():
    """Page reuses v2/components.jsx atoms (Btn/Badge); must not reference pz-components.js."""
    src = _src()
    assert "pz-components" not in src, "must not reference pz-components.js (B2)"


# ── F. Authority-honest data wiring (detail-wiring) ───────────────────────────
# The page must render REAL values from the full-audit authority endpoint, never
# the design-time literals that made operators report "still a mockup page". The
# MOCK banner is only retired (page added to WIRED_PAGES) because of this wiring.

def test_fetches_full_audit_authority():
    """Detail page reads GET /api/v1/dashboard/batches/{batch_id} (full-audit authority)."""
    src = _src()
    assert "/api/v1/dashboard/batches/' + encodeURIComponent(batchId)" in src, (
        "detail page must fetch the full-audit endpoint GET /api/v1/dashboard/batches/{batch_id}"
    )
    assert "function deriveDetail(" in src, "deriveDetail (audit → display fields) missing"


def test_derive_reads_real_authority_blocks():
    """deriveDetail must read the real audit authority blocks, not invent values."""
    src = _src()
    for key in ("customs_declaration", "dhl_precheck", "wfirma_export", "audit.timeline"):
        assert key in src, f"deriveDetail must read real authority block '{key}'"


def test_no_fabricated_detail_values():
    """Every literal that triggered the 'still a mockup' report must be gone."""
    src = _src()
    for fake in (
        "EUR 1,280", "27 Apr 2024", "Agencja Celna", "PZ/2024/001234",
        "WF-2024-04-PZ-1234", "LRN-20240427", "EUR/PLN 4.2650", "EUR/PLN 4.2510",
        "TIMELINE_EVENTS",
    ):
        assert fake not in src, f"fabricated value '{fake}' still present — not authority-honest"


def test_pz_and_wfirma_from_audit():
    """PZ number + wFirma external doc id come from the wfirma_export authority."""
    src = _src()
    assert "wfirma_pz_fullnumber" in src and "wfirma_pz_doc_id" in src


def test_cif_is_usd_not_eur():
    """CIF is denominated in USD (invoice currency) from dhl_precheck, not a faked EUR figure."""
    src = _src()
    assert "function _fmtUsd(" in src, "USD formatter missing"
    assert "invoice_cif_total_usd" in src, "CIF must read dhl_precheck.invoice_cif_total_usd"


def test_missing_fields_render_dash():
    """A _dash() helper renders '—' for any field the authority does not carry (no fakes)."""
    src = _src()
    assert "function _dash(" in src


def test_timeline_renders_real_events():
    """Timeline renders the real audit.timeline event log, not a hardcoded array."""
    src = _src()
    assert "d.timeline" in src, "timeline must come from the audit event log"
    assert 'data-testid="timeline-empty"' in src, "empty-state must be honest when no events"


def test_detail_in_wired_pages():
    """'detail' (the shipment drill-down) is wired → MOCK banner retired for it."""
    badge = _MOCK_BADGE.read_text(encoding="utf-8")
    m = re.search(r"const WIRED_PAGES\s*=\s*\[([^\]]+)\]", badge)
    assert m and "'detail'" in m.group(1), "'detail' must be in WIRED_PAGES"


def test_normalizes_snake_case_prop():
    """Raw snake_case batch rows (the actual caller shape) are normalized to the
    camelCase shape the page reads — otherwise awb/sadStatus/etc. are undefined."""
    src = _src()
    assert "function _normalizeShipment(" in src, "shipment prop normalizer missing"
    assert "s.tracking_no" in src, "awb must fall back to tracking_no for raw rows"
    for mapper in ("_mapSad(s.sad_status)", "_mapPz(s.pz_status)", "_mapDhl(s.dhl_status)"):
        assert mapper in src, f"status mapper call '{mapper}' missing"
    assert "shipment = _normalizeShipment(shipment)" in src, "page must normalize the prop on entry"


def test_doc_generation_from_real_existence_flag():
    """Polish Description / DSK 'Generated ✓' come from the endpoint's on-disk
    existence flag, not a status proxy (no 'Generated' for a missing file)."""
    src = _src()
    assert "polish_desc_file_exists" in src and "dsk_file_exists" in src
    assert "d.polishDescGenerated" in src and "d.dskGenerated" in src
    # the email-status proxy must no longer drive document-generation rows
    assert "dhlEmailReceived ? 'Generated ✓'" not in src, (
        "document generation must not be inferred from dhlEmailReceived"
    )


def test_precheck_stage_not_hardcoded_done():
    """The pre-check workflow stage reflects the real dhl_precheck.completed_at signal."""
    src = _src()
    assert "precheckDone" in src and "pc.completed_at" in src
    assert "if (id === 'precheck') return d.precheckDone" in src
