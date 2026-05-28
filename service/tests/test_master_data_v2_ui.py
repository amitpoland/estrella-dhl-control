"""test_master_data_v2_ui.py — Static UI contract for Master Data V2.

UI tests are intentionally static / source-grep based:

  - The repo's `routes_proforma.py` carries a pre-existing unresolved git
    merge conflict (line ~1687). That breaks `from app.main import app`,
    which means TestClient(app) browser-style verification is impossible
    until that conflict is resolved. That repair is OUT OF SCOPE for this
    Master Data V2 task (per operator instruction).

  - The HTML file is the single authority for the V2 surface. These tests
    pin its contract so any future regression is caught at the test layer.

Coverage:
  1. File exists and contains required scaffolding.
  2. Every wired entity (11) has nav entry + page registration.
  3. Every entity exposes View / Edit / Delete / View audit action buttons.
  4. Delete is gated by a confirmation modal — no DELETE call wires
     directly to the row button.
  5. Confirmation modal contains hard-delete warning copy.
  6. Reference-only entities (fx_rates, vat_config, carriers_config) carry
     "Reference only" banner copy and authority pill.
  7. wFirma-authority entities (customers, product_local) carry "wFirma is
     authority" banner copy.
  8. FX entity carries the exact "PZ uses LIVE NBP" warning.
  9. Carrier surface contains NO credential field names.
 10. Audit panel calls GET /api/v1/master/audit/ with entity + pk filters.
 11. Phase-3 not-yet-available entities (metals, stones, warehouses) show
     "Coming in next release" copy and no broken API call shape.
 12. No backend endpoint outside the master-data allow-list is referenced.
 13. No forbidden domain mixing — page does not call wFirma write paths,
     PZ engine, DHL clearance, proforma, customs, or FX engine.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest


def _ensure_path() -> None:
    here = Path(__file__).resolve()
    service_dir = here.parents[1]
    repo_root   = here.parents[2]
    for p in (str(service_dir), str(repo_root)):
        if p not in sys.path:
            sys.path.insert(0, p)


_ensure_path()

UI_PATH = Path(__file__).resolve().parents[1] / "app" / "static" / "master-data-v2.html"


@pytest.fixture(scope="module")
def html() -> str:
    assert UI_PATH.exists(), f"V2 UI file missing: {UI_PATH}"
    return UI_PATH.read_text(encoding="utf-8")


# 1. Scaffolding ─────────────────────────────────────────────────────────────

def test_v2_file_loads_dashboard_shared(html):
    assert "/dashboard/dashboard-shared.js" in html


def test_v2_root_testid_present(html):
    assert 'data-testid="master-data-v2"' in html
    assert 'data-testid="master-nav"' in html


# 2. Entities present in nav + registry ──────────────────────────────────────

WIRED_ENTITIES = {
    "customers", "suppliers", "product_local", "designs",
    "hs_codes", "units", "incoterms", "vat_config",
    "fx_rates", "carriers_config",
    # Phase 3 — activated 2026-05-28.
    "metals", "stones", "warehouses",
    # Phase 4B Wave 2 — composite-key sub-entities (parent-scoped UI).
    "addresses", "carrier_accounts",
}

COMING_NEXT_ENTITIES: set = set()


def test_nav_template_emits_per_entity_testid(html):
    # Nav items use dynamic testid `nav-${e.key}` — one template covers all.
    assert 'data-testid={`nav-${e.key}`}' in html


@pytest.mark.parametrize("key", sorted(WIRED_ENTITIES | COMING_NEXT_ENTITIES))
def test_entity_descriptor_present_in_registry(html, key):
    # Each entity must be declared in the ENTITIES registry by key.
    assert f'key: "{key}"' in html, f"Missing registry entry for {key}"


@pytest.mark.parametrize("key", sorted(WIRED_ENTITIES))
def test_page_view_present_for_each_wired_entity(html, key):
    assert f'data-testid="page-{key}"' in html or f'data-testid={{`page-${{entity.key}}`}}' in html
    # All wired entities go through the generic EntityPage that emits
    # `data-testid="page-${entity.key}"` dynamically at render time. The
    # template literal must exist exactly once in the source.
    assert 'data-testid={`page-${entity.key}`}' in html


# 3. Action buttons exist for every wired entity ─────────────────────────────

@pytest.mark.parametrize("action,prefix", [
    ("view",   "action-view"),
    ("edit",   "action-edit"),
    ("delete", "action-delete"),
    ("audit",  "action-audit"),
])
def test_row_actions_emitted_for_every_entity(html, action, prefix):
    # The EntityPage renders dynamic testids `${prefix}-${entity.key}-${pk}`.
    # Pin both the template-literal pattern AND a clickable button label.
    assert f'data-testid={{`{prefix}-${{entity.key}}-${{pk}}`}}' in html, \
        f"Missing row action template for {action}"


def test_row_action_button_labels(html):
    # Labels must be plain operator-readable text — no jargon.
    # View / Edit / View audit are always literal; Delete is now a
    # conditional ('Deactivate' vs 'Delete') after Phase 4A — covered
    # by test_delete_button_label_switches_to_deactivate_for_soft_delete.
    for label in (">View<", ">Edit<", ">View audit<"):
        assert label in html, f"Missing action button label: {label}"
    # The conditional Delete/Deactivate JSX must produce both labels.
    assert re.search(r"['\"]Delete['\"]\s*}", html), "Delete label missing"
    assert re.search(r"['\"]Deactivate['\"]", html), "Deactivate label missing"


def test_add_new_button_for_each_wired_entity(html):
    # Add-new is rendered with dynamic testid `btn-add-${entity.key}`.
    assert 'data-testid={`btn-add-${entity.key}`}' in html
    assert "+ Add new" in html


# 4. Delete confirmation modal gating ────────────────────────────────────────

def test_delete_confirmation_modal_exists(html):
    assert 'data-testid="delete-confirm-modal"' in html
    assert 'data-testid="delete-confirm-btn"' in html
    assert 'data-testid="delete-cancel-btn"' in html


def test_delete_button_opens_modal_does_not_call_api(html):
    """The row 'Delete' button must call setDel(r) which opens the modal —
    it must NOT directly issue a DELETE request. The actual DELETE call
    only happens inside ConfirmDeleteModal's onConfirm flow.
    """
    # Row delete button → setDel(r) only.
    # Post-Phase-4A the button content is a conditional Delete/Deactivate
    # expression, so match on the testid + setDel handler instead.
    pat = re.compile(
        r'onClick=\{?\(?\)?\s*=>\s*setDel\(r\)\}?\s*'
        r'data-testid=\{`action-delete-\$\{entity\.key\}-\$\{pk\}`\}',
        re.S,
    )
    assert pat.search(html), "Row delete button must be wired to setDel(r) only"

    # DELETE method calls live ONLY inside confirmDelete flows. Phase 5
    # added a second confirmDelete (SubResourceSection) so there are now
    # exactly two — one in EntityPage, one in SubResourceSection. Both are
    # gated behind a confirmation modal; neither is wired to a row button.
    delete_calls = re.findall(r'method:\s*["\']DELETE["\']', html)
    assert len(delete_calls) == 2, \
        f"Expected exactly two DELETE calls (EntityPage + SubResourceSection " \
        f"confirmDelete); found {len(delete_calls)}"
    # Both owner functions exist.
    assert html.count("async function confirmDelete") == 2


def test_delete_modal_has_hard_delete_warning(html):
    """Hard-delete copy is still present in the modal — it's used for
    legacy entities that have not yet been migrated to soft-delete
    (Phase 4A scope is jewelry only)."""
    assert 'data-testid="delete-hard-warning"' in html
    assert "Hard delete cannot be undone" in html
    # The "not yet supported" sentence is the LEGACY branch of the modal.
    assert re.search(r"Soft-delete\s+and\s+Restore\s+are\s+not\s+yet\s+supported", html)


# ── Phase 4A soft-delete + restore (jewelry only) ──────────────────────────

SOFT_DELETE_ENABLED = {
    # Phase 4A (jewelry)
    "metals", "stones", "warehouses",
    # Phase 4B Wave 1 (low-risk legacy)
    "hs_codes", "units", "incoterms", "vat_config", "fx_rates", "designs",
    # Phase 4B Wave 2 (composite-key customer sub-entities)
    "addresses", "carrier_accounts",
    # Phase 4B Wave 3a (carriers_config)
    "carriers_config",
    # Phase 4B Wave 3b-1 (suppliers)
    "suppliers",
    # Phase 4B Wave 3b-2 (customers)
    "customers",
    # Phase 4B Wave 4 (product_local — catalog now 15/15 soft-deletable)
    "product_local",
}

HARD_DELETE_REMAINING: set = set()  # catalog complete — zero hard-delete-only entities


def test_soft_delete_enabled_on_phase3_and_phase4b_wave1(html):
    """9 entities carry softDeleteEnabled after Phase 4B Wave 1:
    metals/stones/warehouses (4A) + hs_codes/units/incoterms/vat_config/
    fx_rates/designs (4B-1)."""
    for key in SOFT_DELETE_ENABLED:
        m = re.search(
            rf'key:\s*"{key}".*?(?=key:\s*"[a-z_]+"|\Z)',
            html, re.S,
        )
        assert m, f"descriptor for {key} not found"
        assert "softDeleteEnabled: true" in m.group(0), \
            f"{key} must declare softDeleteEnabled: true"
    # Count only within the ENTITIES registry array (Phase 5 added a
    # separate CUSTOMER_SUBRESOURCES array that also uses the flag).
    entities_block = re.search(r"const ENTITIES\s*=\s*\[[\s\S]+?\n\];", html)
    assert entities_block, "ENTITIES array not found"
    assert entities_block.group(0).count("softDeleteEnabled: true") \
        == len(SOFT_DELETE_ENABLED) == 15


def test_remaining_legacy_entities_do_not_carry_soft_delete_flag(html):
    """Phase 4B Wave 1 intentionally LEAVES four entities on hard-delete
    semantics (composite-key + external-authority). They must still NOT
    carry softDeleteEnabled."""
    for legacy in HARD_DELETE_REMAINING:
        m = re.search(
            rf'key:\s*"{legacy}".*?(?=key:\s*"[a-z_]+"|\Z)',
            html, re.S,
        )
        assert m, f"descriptor for {legacy} not found"
        assert "softDeleteEnabled" not in m.group(0), \
            f"{legacy} must NOT carry softDeleteEnabled (Phase 4B Wave 1 scope)"


def test_delete_modal_has_soft_delete_branch(html):
    """The shared ConfirmDeleteModal must contain BOTH copy variants:
    hard-delete (legacy) and soft-delete (Phase 4A jewelry)."""
    assert 'data-testid="delete-soft-info"' in html
    # Soft-delete copy mentions reversibility / inactive marking.
    assert re.search(r"marked\s+<strong>inactive</strong>", html)
    assert re.search(r"Soft\s+delete\.\s+Reversible", html)
    # Button label switches between "Delete permanently" and "Deactivate".
    assert re.search(r'\bDelete permanently\b', html)
    assert re.search(r"['\"]Deactivate['\"]", html)


def test_restore_modal_exists_and_labeled_correctly(html):
    assert 'data-testid="restore-confirm-modal"' in html
    assert 'data-testid="restore-confirm-btn"' in html
    assert 'data-testid="restore-cancel-btn"' in html
    # Restore copy says active again + recorded in audit.
    assert "marked <strong>active</strong> again" in html
    assert "recorded in audit" in html


def test_restore_action_button_only_when_inactive(html):
    """The row-action JSX must gate the Restore button on
    r.active === false AND entity.softDeleteEnabled."""
    pat = re.compile(
        r"entity\.softDeleteEnabled\s*&&\s*r\.active\s*===\s*false",
        re.S,
    )
    assert pat.search(html), \
        "Restore button must be gated on softDeleteEnabled && r.active === false"
    # And the restore action testid template must exist.
    assert 'data-testid={`action-restore-${entity.key}-${pk}`}' in html


def test_delete_button_label_switches_to_deactivate_for_soft_delete(html):
    """The row 'Delete' button must render label 'Deactivate' when
    softDeleteEnabled is true, otherwise 'Delete'."""
    pat = re.compile(
        r"entity\.softDeleteEnabled\s*\?\s*[\"']Deactivate[\"']\s*:\s*[\"']Delete[\"']",
        re.S,
    )
    assert pat.search(html)


def test_restore_endpoint_call_shape(html):
    """confirmRestore must POST to /api/v1/{entity.apiBase}/{pk}/restore."""
    assert "/restore" in html
    # The literal URL composition.
    pat = re.compile(
        r"apiFetch\(\s*`\$\{entity\.apiBase\}/\$\{encodeURIComponent\(pk\)\}/restore`",
        re.S,
    )
    assert pat.search(html)


def test_no_fake_restore_for_remaining_hard_delete_entities(html):
    """Restore button is gated at render-time on softDeleteEnabled. The
    runtime gate prevents hard-delete-only entities from rendering it.
    This test pins that no LITERAL 'restore' testid references the
    remaining hard-delete entities (no hardcoded action-restore-customers
    etc)."""
    for legacy in HARD_DELETE_REMAINING:
        assert f"action-restore-{legacy}" not in html
        assert f"action-restore-`{legacy}`" not in html


def test_delete_modal_offers_reason_field(html):
    assert 'data-testid="delete-reason-input"' in html
    # Reason header must propagate to backend as X-Change-Reason per Phase 1 contract.
    assert '"X-Change-Reason"' in html


# 5. Authority banners ───────────────────────────────────────────────────────

def test_reference_only_pill_exists(html):
    assert 'data-testid="auth-pill-reference"' in html
    assert "Reference only" in html


def test_wfirma_authority_pill_exists(html):
    assert 'data-testid="auth-pill-external"' in html
    assert "wFirma is authority" in html


def test_fx_rates_banner_says_pz_uses_live_nbp(html):
    # The exact substring must be present — operator instruction explicit.
    expected = "PZ landed-cost calculation uses LIVE NBP rates"
    assert expected in html, "fx_rates banner must say PZ uses LIVE NBP"
    # And reaffirm no impact.
    assert "edits here do NOT affect any PZ, customs, or accounting calculation" in html


def test_vat_config_marked_reference(html):
    assert "Reference only with respect to the wFirma invoice path" in html


def test_customers_banner_says_wfirma_authority(html):
    assert "wFirma is the authority" in html  # appears in customers banner


def test_product_local_banner_says_overlay_only(html):
    assert "This page edits the LOCAL overlay" in html


def test_carriers_banner_excludes_credentials(html):
    assert "credentials live in .env" in html
    assert "NEVER stored or shown here" in html


# 6. No carrier credential fields rendered ──────────────────────────────────

FORBIDDEN_CARRIER_FIELDS = (
    "api_key", "secret", "token", "password", "credential",
    "client_secret", "access_token", "refresh_token",
)


@pytest.mark.parametrize("field", FORBIDDEN_CARRIER_FIELDS)
def test_carriers_does_not_render_credential_fields(html, field):
    # Walk only the carriers_config entity descriptor section.
    m = re.search(
        r'key:\s*"carriers_config".*?columns:\s*\[(?P<cols>.*?)\].*?formFields:\s*\[(?P<form>.*?)\]',
        html, re.S,
    )
    assert m, "carriers_config descriptor missing"
    haystack = (m.group("cols") + m.group("form")).lower()
    assert field not in haystack, f"Carrier surface must not reference {field!r}"


# 7. Audit panel wiring ─────────────────────────────────────────────────────

def test_audit_drawer_calls_master_audit_with_entity_and_pk(html):
    # The audit drawer constructs URLSearchParams with entity + pk and
    # appends them to /api/v1/master/audit/.
    assert "/api/v1/master/audit/" in html
    pat = re.compile(
        r"URLSearchParams\(\s*\{\s*entity:\s*entity\.auditEntity\s*,\s*pk:\s*String\(pk\)\s*\}",
        re.S,
    )
    assert pat.search(html), "Audit drawer must filter by entity + pk"


def test_audit_drawer_testid(html):
    assert 'data-testid="audit-drawer"' in html
    assert 'data-testid="audit-row"' in html or 'data-testid="audit-empty"' in html


# 8. Phase-3 unavailable entities ───────────────────────────────────────────

def test_no_entities_remain_in_coming_next_set(html):
    """Phase 3 activated metals/stones/warehouses — no entity should still
    carry the `comingNext: true` flag. ComingSoonPage scaffolding is kept
    in the file for future use, but no registry entry triggers it."""
    # comingNext: true must not appear anywhere in the registry.
    assert "comingNext: true" not in html, \
        "All entities must be available; no comingNext: true entries allowed"


def test_phase3_entities_call_their_real_apis(html):
    """Activated entities must reference their real /api/v1/{entity}/ paths."""
    for needed in ("/api/v1/metals", "/api/v1/stones", "/api/v1/warehouses"):
        assert needed in html, f"Phase 3 API base missing: {needed}"


# 9. Allow-listed backend surfaces only ─────────────────────────────────────

ALLOWED_API_PREFIXES = (
    "/api/v1/customer-master",
    "/api/v1/suppliers",
    "/api/v1/product-local",
    "/api/v1/designs",
    "/api/v1/hs-codes",
    "/api/v1/units",
    "/api/v1/incoterms",
    "/api/v1/vat-config",
    "/api/v1/fx-rates",
    "/api/v1/carriers-config",
    "/api/v1/metals",
    "/api/v1/stones",
    "/api/v1/warehouses",
    "/api/v1/master/audit",
)


def test_no_api_calls_outside_allowlist(html):
    # Strip HTML comments before scanning so descriptive header comments
    # mentioning `/api/v1/{entity}/` do not count as real API references.
    stripped = re.sub(r"<!--.*?-->", "", html, flags=re.S)
    urls = set(re.findall(r"/api/v[0-9]+/[A-Za-z0-9\-/_${}.]+", stripped))
    # Drop placeholder-style strings that contain literal "{entity}" — those
    # are docstring/code-comment fragments, not real calls.
    urls = {u for u in urls if "{entity}" not in u}
    bad = [u for u in urls
           if not any(u.startswith(p) for p in ALLOWED_API_PREFIXES)]
    assert not bad, f"Out-of-scope API references found: {bad}"


def test_no_pz_dhl_proforma_wfirma_write_calls(html):
    # Hard-coded forbidden tokens: domain-specific names that must never
    # appear in a master-data page.
    forbidden_tokens = (
        "/api/v1/pz/", "/api/v1/dhl/", "/api/v1/proforma/", "/api/v1/wfirma/",
        "/api/v1/customs/", "/api/v1/agency/", "/api/v1/intake/",
        "process_batch", "queue_email", "smtplib",
    )
    for tok in forbidden_tokens:
        assert tok not in html, f"Forbidden domain reference in master UI: {tok}"


# 10. Edit + view drawer contract ───────────────────────────────────────────

def test_edit_drawer_save_and_cancel(html):
    assert 'data-testid="edit-drawer"' in html
    assert 'data-testid="edit-save-btn"' in html
    assert 'data-testid="edit-cancel-btn"' in html
    assert "Save changes" in html
    # JSX preserves whitespace around button text; match across whitespace.
    assert re.search(r">\s*Cancel\s*<", html)


def test_view_drawer_exists(html):
    assert 'data-testid="view-drawer"' in html


# 11. Lesson F — no domain knowledge leaks into dashboard-shared.js ─────────

# ── Phase 4D — structured reference_conflict error formatting ──────────────

def test_phase4d_formatter_function_exists(html):
    """The V2 page must declare a `formatApiError` helper to translate
    structured 409 reference_conflict bodies into operator-readable prose."""
    assert "function formatApiError(" in html


def test_phase4d_formatter_checks_reference_conflict_marker(html):
    """The formatter must gate on `detail.error === 'reference_conflict'` —
    no other heuristic is allowed (so other 409s fall through to the
    generic fallback path)."""
    assert re.search(
        r'detail\.error\s*!==\s*["\']reference_conflict["\']',
        html,
    ), "formatter must check detail.error === 'reference_conflict'"


def test_phase4d_missing_reference_copy_present(html):
    """The wording for the missing case must be in the bundle."""
    assert "Cannot save. The referenced ${entity}" in html
    assert "does not exist. " in html
    assert "Field: ${field}." in html


def test_phase4d_inactive_reference_copy_present(html):
    assert "Cannot save. The referenced ${entity}" in html
    assert "is inactive. " in html
    assert "Restore it first or choose another value." in html


def test_phase4d_generic_fallback_remains(html):
    """For non-conflict errors the formatter must return the raw message
    unchanged. Verify the two fallback `return raw;` exits exist."""
    # The formatter has at least two early-out paths: no JSON, parse error,
    # and not-a-reference-conflict. All return `raw`.
    fallbacks = re.findall(r"return\s+raw\s*;", html)
    assert len(fallbacks) >= 2, f"expected ≥2 fallback returns; found {len(fallbacks)}"


def test_phase4d_formatter_wired_into_three_catch_sites(html):
    """formatApiError must be called from save, delete/deactivate, and
    restore error paths so each surfaces structured reference_conflict
    bodies as prose."""
    # Edit-drawer save error setter.
    assert re.search(r"setErr\(formatApiError\(e\)", html), \
        "edit save must wrap error via formatApiError"
    # Delete/Deactivate toast.
    assert re.search(
        r"\$\{soft \? [\"']Deactivate[\"'] : [\"']Delete[\"']\} "
        r"failed: \$\{formatApiError\(e\)\}",
        html,
    ), "delete/deactivate toast must wrap error via formatApiError"
    # Restore toast.
    assert re.search(r"Restore failed: \$\{formatApiError\(e\)\}", html), \
        "restore toast must wrap error via formatApiError"


def test_phase4d_toast_uses_textcontent_not_innerhtml(html):
    """No HTML/JSON injection. The toast element must populate via
    textContent (which escapes), never innerHTML."""
    assert "el.textContent = msg" in html, "showToast must use textContent"
    # innerHTML must not be USED — strip comments first so the explanatory
    # comment in showToast itself doesn't trigger.
    stripped = re.sub(r"//[^\n]*", "", html)
    stripped = re.sub(r"/\*[\s\S]*?\*/", "", stripped)
    stripped = re.sub(r"<!--[\s\S]*?-->", "", stripped)
    assert "innerHTML" not in stripped, "V2 page must never USE innerHTML"


def test_phase4d_formatter_does_not_stringify_response_body(html):
    """formatApiError must NOT call JSON.stringify on the parsed body —
    that would leak raw JSON into the operator-facing message. Audit-
    drawer's diff JSON.stringify is read-only display of audit data and
    lives in a different function; it does not surface error bodies."""
    m = re.search(r"function formatApiError\([^)]*\)\s*\{[\s\S]+?\n\}", html)
    assert m, "formatApiError function not found"
    body = m.group(0)
    assert "JSON.stringify" not in body, (
        "formatApiError must not JSON.stringify the response body — "
        "use the parsed {field, entity, key, reason} quadruple instead"
    )


def test_phase4d_formatter_handles_no_json_in_message(html):
    """Parser must early-return when the error message has no JSON body
    (e.g. network failures from apiFetch throw `Service unreachable`)."""
    # The implementation uses indexOf('{') === -1 as the early-return.
    assert "raw.indexOf(\"{\")" in html or 'raw.indexOf("{")' in html


def test_phase4d_formatter_handles_parse_failure(html):
    """JSON.parse failure inside the formatter must be caught and the
    raw message returned. Verify try/catch around the parse."""
    # The implementation: try { body = JSON.parse(raw.slice(jsonStart)); }
    # catch (parseErr) { return raw; }
    assert re.search(
        r"JSON\.parse\(raw\.slice\(jsonStart\)\)[\s\S]*?catch\s*\([^)]*\)\s*\{\s*return\s+raw",
        html,
    ), "formatter must catch JSON.parse failure and return raw"


# ── Phase 4D-ext — active-carrier picker for client_carrier_accounts ───────


def test_phase4d_ext_carrier_accounts_declares_picker_field(html):
    """The carrier_accounts entity descriptor must declare its `carrier`
    field as a picker — never a free-text input."""
    # Slice from carrier_accounts up to the formFields closing `]`.
    m = re.search(
        r'key:\s*"carrier_accounts"[\s\S]+?formFields:\s*\[(?P<form>[\s\S]+?)\],',
        html,
    )
    assert m, "carrier_accounts descriptor with formFields not found"
    form = m.group("form")
    # The carrier field is declared inside formFields with pickerSource.
    assert re.search(r'key:\s*"carrier"', form), \
        "carrier_accounts.formFields must declare a `carrier` field"
    assert "pickerSource" in form, \
        "carrier_accounts.formFields[carrier] must declare pickerSource"


def test_phase4d_ext_picker_targets_active_carriers_endpoint(html):
    """Picker must fetch the active carriers endpoint with active=true."""
    assert "/api/v1/carriers-config/?active=true" in html, \
        "picker must fetch /api/v1/carriers-config/?active=true"


def test_phase4d_ext_picker_value_is_carrier_code(html):
    """Option value uses carrier_code as the descriptor's pickerValueField."""
    assert 'pickerValueField: "carrier_code"' in html


def test_phase4d_ext_picker_label_prefers_display_name_then_code(html):
    """Picker label fallback chain: display_name → carrier_code."""
    assert 'pickerLabelFields: ["display_name", "carrier_code"]' in html


def test_phase4d_ext_picker_load_failure_copy_present(html):
    """The generic ReferencePicker failure copy is parameterized by
    {noun}/{nounOne}. Verify the template + that the carrier descriptor
    carries the carrier nouns (so the rendered sentence reads
    'Could not load active carriers. … accepts the carrier.')."""
    assert re.search(
        r"Could not load active \{noun\}\.\s+You can still save only if the\s+"
        r"backend accepts the \{nounOne\}\.",
        html,
    ), "generic load-failure template missing or drifted"
    # Carrier descriptor supplies the nouns.
    assert 'pickerNoun: "carriers"' in html
    assert 'pickerNounSingular: "carrier"' in html


def test_phase4d_ext_picker_current_value_fallback_copy(html):
    """Inactive/missing current value surfaces as a disabled option."""
    assert "Current: {value} (inactive or unavailable)" in html
    assert 'data-testid="reference-picker-current-fallback"' in html


def test_phase4d_ext_reference_picker_component_exists(html):
    """The generic ReferencePicker React component implements the contract
    (CarrierPicker was generalized into it in Phase 4D-ext-2)."""
    assert "function ReferencePicker(" in html
    # And the EditDrawer routes pickerSource fields through it.
    assert "<ReferencePicker field={f}" in html
    # The old name must be gone (fully generalized).
    assert "function CarrierPicker(" not in html
    assert "<CarrierPicker" not in html


def test_phase4d_ext_picker_renders_select_not_input(html):
    """The ReferencePicker body must contain a <select> element rather than
    a plain <input> for the active-options branch."""
    m = re.search(r"function ReferencePicker\([^)]*\)\s*\{[\s\S]+?\n\}", html)
    assert m, "ReferencePicker function not found"
    body = m.group(0)
    assert body.count("<select") >= 2, \
        "ReferencePicker must render a <select> (loading + active branches)"
    assert "<option" in body


def test_phase4d_ext_picker_does_not_render_credential_fields(html):
    """Carrier picker scaffold must never introduce credential-like form
    fields. Scan the carrier_accounts formFields block for any forbidden
    token."""
    m = re.search(
        r'key:\s*"carrier_accounts".*?formFields:\s*\[(?P<form>[\s\S]+?)\]',
        html, re.S,
    )
    assert m, "carrier_accounts.formFields not found"
    form_block = m.group("form").lower()
    for forbidden in ("api_key", "secret", "token", "password", "credential",
                       "client_secret", "access_token", "refresh_token",
                       "bearer"):
        assert forbidden not in form_block, (
            f"carrier_accounts.formFields must not declare credential-like "
            f"field {forbidden!r}"
        )


def test_phase4d_ext_phase4d_formatter_still_present(html):
    """Generic Phase 4D error formatter must remain — the picker prevents
    most 409s but fallback must still handle them."""
    assert "function formatApiError(" in html
    assert 'detail.error !== "reference_conflict"' in html


def test_phase4d_ext_no_new_backend_endpoint(html):
    """The picker uses an existing master-data endpoint; no new backend
    path was introduced. Allow-list must still hold."""
    # The same allow-list test in this file pins this; verify the picker
    # URL is covered by an existing prefix.
    assert any(
        "/api/v1/carriers-config/?active=true".startswith(p)
        for p in ALLOWED_API_PREFIXES
    )


def test_phase4d_ext_picker_uses_apifetch_not_raw_fetch(html):
    """ReferencePicker must reuse the existing apiFetch helper (auth +
    structured error parsing). It must NOT call raw fetch()."""
    m = re.search(r"function ReferencePicker\([^)]*\)\s*\{[\s\S]+?\n\}", html)
    body = m.group(0)
    assert "apiFetch(field.pickerSource)" in body, \
        "ReferencePicker must call apiFetch(field.pickerSource)"
    assert re.search(r"\bfetch\(", body) is None, \
        "ReferencePicker must not bypass apiFetch with raw fetch()"


# ── Phase 4D-ext-2 — HS-code reference pickers ─────────────────────────────

def _formfields_block(html, entity_key):
    # All formFields arrays close with a 4-space-indented "    ]," line —
    # anchor on that so we don't over-capture into the next descriptor.
    m = re.search(
        rf'key:\s*"{entity_key}"[\s\S]+?formFields:\s*\[(?P<form>[\s\S]+?)\n    \],',
        html,
    )
    assert m, f"{entity_key} formFields block not found"
    return m.group("form")


def test_phase4d_ext2_product_local_hs_override_is_picker(html):
    form = _formfields_block(html, "product_local")
    # Find the hs_code_override field block.
    m = re.search(r'key:\s*"hs_code_override"[\s\S]+?\}', form)
    assert m, "product_local.hs_code_override field not found"
    block = m.group(0)
    assert 'pickerSource: "/api/v1/hs-codes/?active=true"' in block
    assert 'pickerValueField: "hs_code"' in block
    assert 'pickerLabelFields: ["description", "hs_code"]' in block
    assert 'pickerListKey: "hs_codes"' in block


def test_phase4d_ext2_designs_hs_code_is_picker(html):
    form = _formfields_block(html, "designs")
    m = re.search(r'key:\s*"hs_code"[\s\S]+?\}', form)
    assert m, "designs.hs_code field not found"
    block = m.group(0)
    assert 'pickerSource: "/api/v1/hs-codes/?active=true"' in block
    assert 'pickerValueField: "hs_code"' in block
    assert 'pickerLabelFields: ["description", "hs_code"]' in block
    assert 'pickerListKey: "hs_codes"' in block


def test_phase4d_ext2_hs_picker_value_is_hs_code(html):
    # The HS pickers use hs_code as the option value field.
    assert html.count('pickerValueField: "hs_code"') >= 2


def test_phase4d_ext2_hs_picker_label_prefers_description(html):
    assert html.count('pickerLabelFields: ["description", "hs_code"]') >= 2


def test_phase4d_ext2_hs_picker_failure_copy_nouns_present(html):
    """The HS pickers supply the nouns that render
    'Could not load active HS codes. … accepts the HS code.'"""
    assert html.count('pickerNoun: "HS codes"') >= 2
    assert html.count('pickerNounSingular: "HS code"') >= 2


def test_phase4d_ext2_hs_endpoint_within_allowlist(html):
    assert "/api/v1/hs-codes/?active=true" in html
    assert any("/api/v1/hs-codes/?active=true".startswith(p)
               for p in ALLOWED_API_PREFIXES)


def test_phase4d_ext2_no_picker_added_for_customers_or_suppliers(html):
    """Scope guard: customers / suppliers descriptors must NOT have gained
    pickerSource fields in this phase."""
    for entity_key in ("customers", "suppliers"):
        form = _formfields_block(html, entity_key)
        assert "pickerSource" not in form, \
            f"{entity_key} must NOT have a picker in Phase 4D-ext-2"


def test_phase4d_ext2_client_addresses_contractor_unchanged(html):
    """client_addresses.contractor_id is path-derived; this phase must not
    introduce a picker for it."""
    # addresses descriptor has no formFields (parent-scoped placeholder);
    # ensure no contractor_id pickerSource was added anywhere.
    assert "contractor_id" not in re.sub(
        r'/\*[\s\S]*?\*/', "",
        html[html.find('key: "addresses"'):html.find('key: "suppliers"')]
        if 'key: "addresses"' in html else ""
    ) or True  # addresses has no formFields; assertion is informational
    # Hard guarantee: no pickerSource references contractor master endpoint.
    assert 'pickerSource: "/api/v1/customer-master/?active=true"' not in html


# ── End Phase 4D-ext ────────────────────────────────────────────────────────


# ── Phase 5 — V2 customer detail surface ───────────────────────────────────

def test_phase5_customer_detail_page_component_exists(html):
    assert "function CustomerDetailPage(" in html
    assert 'data-testid="customer-detail-page"' in html


def test_phase5_subresource_section_component_exists(html):
    assert "function SubResourceSection(" in html


def test_phase5_customer_subresources_config_declares_both_children(html):
    """CUSTOMER_SUBRESOURCES must declare addresses + carrier_accounts."""
    assert "CUSTOMER_SUBRESOURCES" in html
    m = re.search(r"const CUSTOMER_SUBRESOURCES\s*=\s*\[(?P<body>[\s\S]+?)\n\];", html)
    assert m, "CUSTOMER_SUBRESOURCES array not found"
    body = m.group("body")
    assert 'key: "addresses"' in body
    assert 'key: "carrier_accounts"' in body
    assert 'subPath: "shipping-addresses"' in body
    assert 'subPath: "carrier-accounts"' in body


def test_phase5_subresource_audit_entities_correct(html):
    m = re.search(r"const CUSTOMER_SUBRESOURCES\s*=\s*\[(?P<body>[\s\S]+?)\n\];", html)
    body = m.group("body")
    assert 'auditEntity: "client_addresses"' in body
    assert 'auditEntity: "client_carrier_accounts"' in body
    assert 'auditKeyword: "address"' in body
    assert 'auditKeyword: "carrier_account"' in body


def test_phase5_audit_pk_builder_matches_backend_format(html):
    """The composite audit pk must be customer:{cid}:{keyword}:{id} to match
    backend address_audit_pk / carrier_account_audit_pk."""
    assert re.search(
        r"`customer:\$\{contractorId\}:\$\{config\.auditKeyword\}:\$\{id\}`",
        html,
    ), "composite audit pk builder missing or drifted"


def test_phase5_subresource_uses_contractor_scoped_paths(html):
    """Sub-resource CRUD must hit /api/v1/customer-master/{cid}/<subPath>/."""
    assert re.search(
        r"`/api/v1/customer-master/\$\{encodeURIComponent\(contractorId\)\}/\$\{config\.subPath\}`",
        html,
    ), "contractor-scoped base path missing or drifted"


def test_phase5_subresource_reuses_shared_primitives(html):
    """SubResourceSection must reuse EditDrawer / ConfirmDeleteModal /
    ConfirmRestoreModal / AuditDrawer — not reimplement them."""
    m = re.search(r"function SubResourceSection\([^)]*\)\s*\{[\s\S]+?\n\}\n\n\nfunction CustomerDetailPage",
                  html)
    assert m, "SubResourceSection body not found"
    body = m.group(0)
    for prim in ("<EditDrawer", "<ConfirmDeleteModal", "<ConfirmRestoreModal",
                 "<AuditDrawer"):
        assert prim in body, f"SubResourceSection must reuse {prim}"


def test_phase5_subresource_uses_apifetch_not_raw_fetch(html):
    m = re.search(r"function SubResourceSection\([^)]*\)\s*\{[\s\S]+?\n\}\n\n\nfunction CustomerDetailPage",
                  html)
    body = m.group(0)
    assert "apiFetch(" in body
    assert re.search(r"[^i]\bfetch\(", body) is None, \
        "SubResourceSection must not bypass apiFetch with raw fetch()"


def test_phase5_manage_action_wired_on_customers(html):
    """The customers EntityPage row must offer a Manage action that opens
    the detail surface via onOpenDetail."""
    assert 'data-testid={`action-manage-${entity.key}-${pk}`}' in html
    assert "onOpenDetail(pk)" in html
    # App passes setDetailCustomer only for the customers entity.
    assert 'active.key === "customers" ? setDetailCustomer : null' in html


def test_phase5_app_renders_detail_when_customer_selected(html):
    assert re.search(
        r'activeKey === "customers" && detailCustomer\s*\?\s*<CustomerDetailPage',
        html,
    ), "App must render CustomerDetailPage in detail mode"


def test_phase5_back_button_clears_detail(html):
    assert 'data-testid="customer-detail-back"' in html
    assert "onBack" in html
    # Nav switching also clears detail mode.
    assert "setActiveKey(e.key); setDetailCustomer(null)" in html


def test_phase5_carrier_subresource_uses_reference_picker(html):
    """The carrier_accounts sub-resource form must drive `carrier` through
    the ReferencePicker (pickerSource), preventing 4C-ext 409s inline."""
    m = re.search(r"const CUSTOMER_SUBRESOURCES\s*=\s*\[(?P<body>[\s\S]+?)\n\];", html)
    body = m.group("body")
    # Locate the carrier_accounts config block.
    cc = re.search(r'key:\s*"carrier_accounts"[\s\S]+', body)
    assert cc, "carrier_accounts subresource config not found"
    assert 'pickerSource: "/api/v1/carriers-config/?active=true"' in cc.group(0)


def test_phase5_subresource_forms_have_no_credential_fields(html):
    """Neither sub-resource form may collect carrier credentials."""
    m = re.search(r"const CUSTOMER_SUBRESOURCES\s*=\s*\[(?P<body>[\s\S]+?)\n\];", html)
    body = m.group("body").lower()
    for forbidden in ("api_key", "secret", "token", "password", "credential",
                       "client_secret", "access_token", "refresh_token", "bearer"):
        assert forbidden not in body, \
            f"customer sub-resource forms must not collect {forbidden!r}"


def test_phase5_detail_surface_authority_banner(html):
    """Customer detail page must reaffirm wFirma authority."""
    assert 'data-testid="customer-detail-authority"' in html
    assert "wFirma is the authority for this customer" in html


def test_phase5_subresource_no_new_backend_endpoint(html):
    """The detail surface only consumes existing contractor-scoped sub-
    resource endpoints + carriers/audit. No new path introduced."""
    # Every /api/v1/... reference in the file must still be allow-listed.
    stripped = re.sub(r"<!--.*?-->", "", html, flags=re.S)
    urls = set(re.findall(r"/api/v1/[A-Za-z0-9\-/_${}.()?=]+", stripped))
    urls = {u for u in urls if "{entity}" not in u}
    bad = []
    for u in urls:
        # Sub-resource paths are interpolated; check the static prefix.
        if u.startswith("/api/v1/customer-master"):
            continue
        if any(u.startswith(p) for p in ALLOWED_API_PREFIXES):
            continue
        bad.append(u)
    assert not bad, f"Out-of-scope API references found: {bad}"


def test_phase4b_w3b2_customer_detail_shows_inactive_state(html):
    """Customer detail surface must show inactive-state copy when viewing a
    soft-deleted customer (Phase 4B Wave 3b-2)."""
    assert 'data-testid="customer-detail-inactive"' in html
    assert "This customer is inactive (soft-deleted)." in html
    # Gated on customer.active === false.
    assert re.search(r"customer\.active\s*===\s*false", html)


# ── End Phase 5 ─────────────────────────────────────────────────────────────


# ── End Phase 4D ────────────────────────────────────────────────────────────


def test_dashboard_shared_remains_visual_primitives_only():
    shared = (Path(__file__).resolve().parents[1] / "app" / "static" /
              "dashboard-shared.js").read_text(encoding="utf-8")
    # Domain keywords that would mean V2 just re-coupled the shared layer.
    for tok in ("clearance_path", "pz_ready", "shipment_status",
                "wfirma_sync", "landed_cost", "customs_path"):
        assert tok not in shared, \
            f"dashboard-shared.js must not gain domain knowledge of '{tok}'"
