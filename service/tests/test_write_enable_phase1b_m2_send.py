"""Write Enablement Phase 1B — M2 Send Proforma Email regression tests.

Source-grep tests verifying that:
1. M2 Send Email: Backend route exists (POST /draft/{id}/send-email)
2. M2 Send Email: Uses email_service.queue_email (not direct SMTP)
3. M2 Send Email: Requires confirm_token (YES_SEND_PROFORMA_EMAIL)
4. M2 Send Email: Guards for terminal states (cancelled/deleted/converted/invoiced)
5. M2 Send Email: Guards for missing wfirma_proforma_id (no PDF)
6. M2 Send Email: Resolves recipient from customer_master bill_to_email
7. M2 Send Email: Records timeline event (EV_PROFORMA_EMAIL_QUEUED)
8. M2 Send Email: X-Operator header required
9. M2 Send Email: Idempotency via _find_pending_duplicate / FollowupSuppressedError
10. M2 pz-api.js: sendProformaEmail transport defined
11. M2 Frontend: SendProformaModal component exists
12. M2 Frontend: tb-send conditionally enabled (not hardcoded disabled)
13. M2 Frontend: canSend derived from state + wfirma_proforma_id
14. M2 Frontend: Send modal has confirmation UI
15. M2 Frontend: Send modal exported to window
16. Lesson M: CMR/Generate/More remain visible and disabled with reasons
17. Lesson M: No planned controls removed (all testids still present)

Sprint: Write Enablement Phase 1B — M2 Send Proforma Email
Target: routes_proforma.py, proforma-detail.jsx, pz-api.js, timeline.py
"""

import pathlib
import re

import pytest

SERVICE_DIR = pathlib.Path(__file__).resolve().parent.parent
APP_DIR = SERVICE_DIR / "app"
V2_DIR = APP_DIR / "static" / "v2"
DETAIL = V2_DIR / "proforma-detail.jsx"
PZ_API = V2_DIR / "pz-api.js"
ROUTES_PROFORMA = APP_DIR / "api" / "routes_proforma.py"
TIMELINE = APP_DIR / "core" / "timeline.py"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


# =============================================================================
# 1. Backend Route — routes_proforma.py
# =============================================================================

class TestM2BackendRoute:
    """POST /draft/{draft_id}/send-email route must exist with proper guards."""

    def test_send_email_route_exists(self):
        """Route decorator for send-email must exist."""
        src = _read(ROUTES_PROFORMA)
        assert '"/draft/{draft_id}/send-email"' in src, \
            "send-email route decorator must exist in routes_proforma.py"

    def test_send_email_function_exists(self):
        """Route handler function must exist."""
        src = _read(ROUTES_PROFORMA)
        assert "def send_proforma_email" in src

    def test_uses_queue_email(self):
        """Must use email_service.queue_email, not direct SMTP."""
        src = _read(ROUTES_PROFORMA)
        # Find the send_proforma_email function region
        idx = src.find("def send_proforma_email")
        assert idx > 0
        region = src[idx:idx + 5000]
        assert "queue_email" in region, \
            "send_proforma_email must call queue_email"

    def test_requires_confirm_token(self):
        """Must check for YES_SEND_PROFORMA_EMAIL confirmation token."""
        src = _read(ROUTES_PROFORMA)
        assert "YES_SEND_PROFORMA_EMAIL" in src

    def test_guards_terminal_states(self):
        """Must reject sends for cancelled/deleted/converted drafts."""
        src = _read(ROUTES_PROFORMA)
        idx = src.find("def send_proforma_email")
        assert idx > 0
        region = src[idx:idx + 5000]
        assert "cancelled" in region, "Must guard against cancelled state"
        assert "deleted" in region, "Must guard against deleted state"
        assert "converted" in region, "Must guard against converted state"

    def test_guards_missing_wfirma_id(self):
        """Must reject sends when wfirma_proforma_id is missing (no PDF)."""
        src = _read(ROUTES_PROFORMA)
        idx = src.find("def send_proforma_email")
        assert idx > 0
        region = src[idx:idx + 5000]
        assert "wfirma_proforma_id" in region, \
            "Must check wfirma_proforma_id presence"

    def test_resolves_recipient_from_customer_master(self):
        """Must resolve recipient from customer_master bill_to_email."""
        src = _read(ROUTES_PROFORMA)
        assert "def _resolve_proforma_recipient" in src
        idx = src.find("def _resolve_proforma_recipient")
        region = src[idx:idx + 800]
        assert "bill_to_email" in region, \
            "Must resolve bill_to_email from customer master"

    def test_requires_x_operator_header(self):
        """Route must require X-Operator header."""
        src = _read(ROUTES_PROFORMA)
        idx = src.find("def send_proforma_email")
        assert idx > 0
        region = src[idx:idx + 500]
        assert "x_operator" in region or "X-Operator" in region, \
            "Route must accept X-Operator header"
        # Must call _require_operator
        region2 = src[idx:idx + 2000]
        assert "_require_operator" in region2, \
            "Must call _require_operator to validate header"

    def test_handles_followup_suppressed(self):
        """Must handle FollowupSuppressedError for idempotency."""
        src = _read(ROUTES_PROFORMA)
        idx = src.find("def send_proforma_email")
        assert idx > 0
        region = src[idx:idx + 5000]
        assert "FollowupSuppressedError" in region, \
            "Must catch FollowupSuppressedError for duplicate send handling"

    def test_email_type_is_proforma_send(self):
        """Email type must be 'proforma_send' for idempotency key."""
        src = _read(ROUTES_PROFORMA)
        idx = src.find("def send_proforma_email")
        assert idx > 0
        region = src[idx:idx + 5000]
        assert '"proforma_send"' in region or "'proforma_send'" in region, \
            "email_type must be 'proforma_send'"

    def test_returns_ok_response_shape(self):
        """Response must include ok, queued_id, recipient, subject."""
        src = _read(ROUTES_PROFORMA)
        idx = src.find("def send_proforma_email")
        assert idx > 0
        region = src[idx:idx + 5000]
        assert '"ok"' in region or "'ok'" in region
        assert '"queued_id"' in region or "'queued_id'" in region
        assert '"recipient"' in region or "'recipient'" in region
        assert '"subject"' in region or "'subject'" in region

    def test_no_direct_smtp_import(self):
        """Route must NOT import smtplib directly."""
        src = _read(ROUTES_PROFORMA)
        idx = src.find("def send_proforma_email")
        assert idx > 0
        region = src[idx:idx + 5000]
        assert "smtplib" not in region, \
            "Must not use smtplib directly — use queue_email"

    def test_from_address_is_import(self):
        """From address should be import@estrellajewels.eu."""
        src = _read(ROUTES_PROFORMA)
        idx = src.find("def send_proforma_email")
        assert idx > 0
        region = src[idx:idx + 5000]
        assert "import@estrellajewels.eu" in region, \
            "From address should be import@estrellajewels.eu"


# =============================================================================
# 2. Timeline Event
# =============================================================================

class TestM2TimelineEvent:
    """EV_PROFORMA_EMAIL_QUEUED must exist in timeline.py."""

    def test_timeline_constant_exists(self):
        src = _read(TIMELINE)
        assert "EV_PROFORMA_EMAIL_QUEUED" in src

    def test_timeline_event_value(self):
        src = _read(TIMELINE)
        assert '"proforma_email_queued"' in src or \
               "'proforma_email_queued'" in src

    def test_route_uses_timeline_event(self):
        """Route must record the timeline event."""
        src = _read(ROUTES_PROFORMA)
        idx = src.find("def send_proforma_email")
        assert idx > 0
        region = src[idx:idx + 5000]
        assert "EV_PROFORMA_EMAIL_QUEUED" in region or \
               "proforma_email_queued" in region


# =============================================================================
# 3. pz-api.js — Transport
# =============================================================================

class TestPzApiTransport:
    """pz-api.js must have the sendProformaEmail transport."""

    def test_transport_defined(self):
        src = _read(PZ_API)
        assert "sendProformaEmail" in src

    def test_transport_targets_send_email_route(self):
        src = _read(PZ_API)
        assert "send-email" in src, "Transport must target /send-email endpoint"

    def test_transport_sends_confirm_token(self):
        src = _read(PZ_API)
        idx = src.find("sendProformaEmail")
        assert idx > 0
        region = src[idx:idx + 400]
        assert "confirm_token" in region, \
            "Transport must send confirm_token in body"

    def test_transport_uses_post(self):
        """Send email transport must use POST (write operation)."""
        src = _read(PZ_API)
        idx = src.find("sendProformaEmail")
        assert idx > 0
        region = src[idx:idx + 400]
        assert "_postM(" in region, "Send email must use _postM (POST method)"


# =============================================================================
# 4. Frontend — SendProformaModal
# =============================================================================

class TestSendProformaModal:
    """SendProformaModal component must exist with proper UI elements."""

    def test_modal_component_exists(self):
        src = _read(DETAIL)
        assert "function SendProformaModal" in src

    def test_modal_has_testid(self):
        src = _read(DETAIL)
        assert "send-proforma-modal" in src

    def test_modal_has_submit_button(self):
        src = _read(DETAIL)
        assert "send-proforma-submit" in src

    def test_modal_shows_recipient(self):
        src = _read(DETAIL)
        assert "send-proforma-default-recipient" in src or \
               "send-proforma-recipient-override" in src

    def test_modal_shows_pdf_info(self):
        src = _read(DETAIL)
        assert "send-proforma-pdf-info" in src

    def test_modal_has_error_state(self):
        src = _read(DETAIL)
        assert "send-proforma-error" in src

    def test_modal_has_success_state(self):
        src = _read(DETAIL)
        assert "send-proforma-success" in src

    def test_modal_has_subject_field(self):
        src = _read(DETAIL)
        assert "send-proforma-subject" in src

    def test_modal_exported_to_window(self):
        src = _read(DETAIL)
        export_idx = src.find("Object.assign(window,")
        assert export_idx > 0
        region = src[export_idx:export_idx + 400]
        assert "SendProformaModal" in region, \
            "SendProformaModal must be window-exported"

    def test_modal_calls_send_api(self):
        """Modal must call PzApi.sendProformaEmail."""
        src = _read(DETAIL)
        idx = src.find("function SendProformaModal")
        assert idx > 0
        region = src[idx:idx + 5000]
        assert "sendProformaEmail" in region


# =============================================================================
# 5. Frontend — tb-send button enablement
# =============================================================================

class TestTbSendEnablement:
    """tb-send button must be conditionally enabled, not hardcoded disabled."""

    def test_tb_send_not_hardcoded_disabled(self):
        """The send button must NOT have a bare 'disabled' without condition."""
        src = _read(DETAIL)
        idx = src.find('data-testid="tb-send"')
        assert idx > 0
        # Look at the region before tb-send — must have canSend or onClick
        region = src[max(0, idx - 300):idx]
        assert "canSend" in region or "onClick" in region, \
            "tb-send must be conditionally enabled"

    def test_can_send_derived(self):
        """canSend must be derived from draft state."""
        src = _read(DETAIL)
        assert "canSend" in src, "canSend variable must exist"

    def test_can_send_checks_wfirma_id(self):
        """canSend derivation must check wfirma_proforma_id."""
        src = _read(DETAIL)
        # canSend should reference hasWfirmaId or wfirma_proforma_id
        assert "hasWfirmaId" in src or \
               ("canSend" in src and "wfirma_proforma_id" in src)

    def test_send_opens_modal(self):
        """Clicking tb-send must open the SendProformaModal."""
        src = _read(DETAIL)
        assert "showSendModal" in src, "showSendModal state must exist"
        assert "setShowSendModal" in src, "setShowSendModal setter must exist"

    def test_send_button_has_onclick(self):
        """Send button must have an onClick handler."""
        src = _read(DETAIL)
        idx = src.find('data-testid="tb-send"')
        assert idx > 0
        region = src[max(0, idx - 300):idx]
        assert "onClick" in region, "tb-send must have onClick handler"

    def test_send_disabled_reason_when_no_pdf(self):
        """Must show a reason when send is disabled due to missing PDF."""
        src = _read(DETAIL)
        assert "Post draft to wFirma first" in src or \
               "no PDF available" in src, \
            "Must explain why send is disabled when no PDF"

    def test_old_disabled_text_removed(self):
        """Old hardcoded disabled text must be replaced."""
        src = _read(DETAIL)
        assert "Email send not yet wired to backend" not in src, \
            "Old hardcoded disabled text must be replaced"


# =============================================================================
# 6. Lesson M — Disabled controls preserved
# =============================================================================

class TestLessonMPreservation:
    """CMR, Generate, More buttons must remain visible and disabled."""

    @pytest.mark.parametrize("testid,label_fragment", [
        ("tb-cmr",      "CMR"),
        ("tb-generate", "Generate"),
        ("tb-more",     "⋯"),
    ])
    def test_disabled_button_still_present(self, testid, label_fragment):
        src = _read(DETAIL)
        assert testid in src, f"Button {testid} must still exist (Lesson M)"
        idx = src.find(f'data-testid="{testid}"')
        region = src[max(0, idx - 200):idx + 100]
        assert "disabled" in region, f"Button {testid} must still be disabled"

    def test_cmr_has_explicit_reason(self):
        src = _read(DETAIL)
        assert "CMR print" in src and "no backend PDF generation route" in src

    def test_generate_has_explicit_reason(self):
        src = _read(DETAIL)
        assert "Document generation not yet available" in src

    def test_no_testids_removed(self):
        """All original toolbar testids must still be present."""
        src = _read(DETAIL)
        required_testids = [
            "tb-edit", "tb-delete", "tb-duplicate", "tb-post",
            "tb-convert", "tb-preview", "tb-cmr", "tb-send",
            "tb-generate", "tb-more", "tb-back",
            "proforma-detail-download-pdf",
        ]
        for tid in required_testids:
            assert tid in src, f"Required testid '{tid}' must still exist"

    def test_send_button_still_visible(self):
        """Send button must still be visible (Lesson M — no removal)."""
        src = _read(DETAIL)
        assert 'data-testid="tb-send"' in src
        idx = src.find('data-testid="tb-send"')
        region = src[max(0, idx - 200):idx + 200]
        assert "➤ Send" in region, "Send button label must be visible"


# =============================================================================
# 7. Safety Constraints
# =============================================================================

class TestSafetyConstraints:
    """M2 must not introduce unsafe patterns."""

    def test_no_auto_send_on_mount(self):
        """No automatic email sending on component mount."""
        src = _read(DETAIL)
        # sendProformaEmail should only appear in the modal handler context,
        # not in a useEffect or mount-time call
        lines = src.split('\n')
        for i, line in enumerate(lines):
            if 'useEffect' in line and 'sendProformaEmail' in line:
                assert False, "sendProformaEmail must not be called in useEffect"

    def test_no_smtplib_import_in_frontend(self):
        """Frontend must never import or use smtplib directly."""
        src = _read(DETAIL)
        assert "smtplib" not in src, \
            "Frontend must not import smtplib"
        assert "import smtp" not in src.lower(), \
            "Frontend must not import SMTP modules"

    def test_modal_requires_confirmation(self):
        """Send modal must require explicit user action (not auto-send)."""
        src = _read(DETAIL)
        idx = src.find("function SendProformaModal")
        assert idx > 0
        region = src[idx:idx + 5000]
        assert "YES_SEND_PROFORMA_EMAIL" in region, \
            "Modal must send confirmation token"

    def test_no_delete_whole_draft_in_api(self):
        """pz-api.js must NOT have a deleteWholeDraft transport."""
        src = _read(PZ_API)
        code = "\n".join(ln for ln in src.splitlines()
                         if not ln.strip().startswith("//"))
        matches = re.findall(r'deleteDraft\b(?!Line)', code)
        assert len(matches) == 0, \
            "No deleteDraft (whole-draft) transport — M1a uses cancelDraft"
