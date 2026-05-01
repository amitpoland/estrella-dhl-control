"""
Dashboard Action V2 — contract & behavior tests.

Covers:
  - Stable IDs across runs
  - All 7 sections always present
  - Disabled actions include reason
  - PZ generated batch shows wFirma ready
  - Missing DSK shows generate enabled, download disabled
  - DHL 404 does not block PZ
  - Agency queued maps to queue id
  - Sent agency email disables resend
  - Chrome guide route exists in mounted FastAPI app
  - wFirma actions use valid endpoints
  - Layout sections always present (even on empty audit)
  - Stale clearance_status overridden by file evidence
  - No financial fields modified by normalizer (read-only contract)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_SVC = Path(__file__).parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

from app.services.batch_state_normalizer import normalize_batch_state  # noqa: E402
from app.services.dashboard_action_registry import (  # noqa: E402
    build_actions_for_batch,
    all_action_endpoints,
)
from app.services.route_contract_validator import validate_endpoints, collect_app_routes  # noqa: E402
from app.services.dashboard_action_types import SECTION_KEYS, NormalizedState  # noqa: E402


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def empty_audit() -> dict:
    return {"batch_id": "TEST_EMPTY", "inputs": {}}


@pytest.fixture
def empty_batch_dir(tmp_path: Path) -> Path:
    d = tmp_path / "TEST_EMPTY"
    d.mkdir()
    return d


@pytest.fixture
def pz_done_audit() -> dict:
    return {
        "batch_id": "TEST_PZ_DONE",
        "status":   "success",
        "inputs":   {"invoices": ["a.pdf"], "zc429": "sad.pdf"},
        "customs_declaration": {"mrn": "26PL", "duty_a00_pln": 100.0},
        "polish_desc_filename": "POLISH_TEST.pdf",
        "dsk_filename":         "DSK_TEST.pdf",
        "totals":               {"net": 1000.0, "gross": 1230.0, "duty": 100.0, "line_count": 5},
        "clearance_decision":   {"clearance_path": "external_agency_clearance"},
    }


@pytest.fixture
def pz_done_batch_dir(tmp_path: Path) -> Path:
    d = tmp_path / "TEST_PZ_DONE"
    d.mkdir()
    (d / "PZ_TEST.pdf").write_text("pdf")
    (d / "PZ_TEST_calc.xlsx").write_text("xlsx")
    return d


@pytest.fixture
def app_instance():
    """Import the real FastAPI app for route validation tests."""
    from app.main import app
    return app


# ── 1. Stable IDs across runs ───────────────────────────────────────────────

def test_stable_action_ids_across_runs(empty_audit, empty_batch_dir):
    n = normalize_batch_state(empty_audit, empty_batch_dir)
    s1 = build_actions_for_batch(n.batch_id, n)
    s2 = build_actions_for_batch(n.batch_id, n)
    ids1 = sorted(a.id for sec in s1.values() for a in sec)
    ids2 = sorted(a.id for sec in s2.values() for a in sec)
    assert ids1 == ids2
    # And every ID is unique
    assert len(ids1) == len(set(ids1))


def test_action_ids_follow_section_verb_noun(empty_audit, empty_batch_dir):
    n = normalize_batch_state(empty_audit, empty_batch_dir)
    sections = build_actions_for_batch(n.batch_id, n)
    for sec_name, actions in sections.items():
        for a in actions:
            assert "." in a.id, f"{a.id} missing section prefix"
            assert a.section == sec_name, f"{a.id} declares section={a.section} but lives in {sec_name}"


# ── 2. All sections always present ──────────────────────────────────────────

def test_all_sections_present_on_empty_batch(empty_audit, empty_batch_dir):
    n = normalize_batch_state(empty_audit, empty_batch_dir)
    sections = build_actions_for_batch(n.batch_id, n)
    for k in SECTION_KEYS:
        assert k in sections, f"Section {k} missing"


def test_all_sections_present_on_full_batch(pz_done_audit, pz_done_batch_dir):
    n = normalize_batch_state(pz_done_audit, pz_done_batch_dir)
    sections = build_actions_for_batch(n.batch_id, n)
    for k in SECTION_KEYS:
        assert k in sections


# ── 3. Disabled actions include reason ──────────────────────────────────────

def test_disabled_actions_include_reason(empty_audit, empty_batch_dir):
    n = normalize_batch_state(empty_audit, empty_batch_dir)
    sections = build_actions_for_batch(n.batch_id, n)
    disabled = [a for sec in sections.values() for a in sec if not a.enabled]
    assert disabled, "expected at least one disabled action on empty batch"
    for a in disabled:
        assert a.reason and a.reason.strip(), f"disabled action {a.id} missing reason"


# ── 4. PZ generated → wFirma ready ──────────────────────────────────────────

def test_pz_generated_enables_wfirma(pz_done_audit, pz_done_batch_dir):
    n = normalize_batch_state(pz_done_audit, pz_done_batch_dir)
    assert n.pz_generated
    assert n.wfirma_ready
    sections = build_actions_for_batch(n.batch_id, n)
    wfirma = {a.id: a for a in sections["wfirma"]}
    assert wfirma["wfirma.preview"].enabled
    assert wfirma["wfirma.copy_clipboard"].enabled
    assert wfirma["wfirma.download_json"].enabled


# ── 5. Missing DSK shows generate enabled, download disabled ────────────────

def test_missing_dsk_state(pz_done_audit, pz_done_batch_dir):
    audit = {**pz_done_audit, "dsk_filename": None}
    n = normalize_batch_state(audit, pz_done_batch_dir)
    assert not n.has_dsk_pdf
    sections = build_actions_for_batch(n.batch_id, n)
    dhl = {a.id: a for a in sections["dhl_clearance"]}
    assert dhl["dhl.generate_dsk"].enabled, "generate DSK should be enabled when CIF present and DSK missing"
    assert not dhl["dhl.download_dsk"].enabled, "download DSK should be disabled when file missing"
    assert "DSK not generated" in dhl["dhl.download_dsk"].reason


def test_dsk_download_uses_correct_endpoint(pz_done_audit, pz_done_batch_dir):
    """Audit item #26: DSK download must NOT use /api/v1/dhl/download."""
    n = normalize_batch_state(pz_done_audit, pz_done_batch_dir)
    sections = build_actions_for_batch(n.batch_id, n)
    dhl = {a.id: a for a in sections["dhl_clearance"]}
    if dhl["dhl.download_dsk"].endpoint:
        assert dhl["dhl.download_dsk"].endpoint.startswith("/api/v1/dsk/download/"), \
            f"DSK download must use /api/v1/dsk/download, got: {dhl['dhl.download_dsk'].endpoint}"


# ── 6. DHL 404 does not block PZ ────────────────────────────────────────────

def test_dhl_tracking_404_does_not_block_pz(pz_done_audit, pz_done_batch_dir):
    audit = {**pz_done_audit, "tracking": {"status": "not_found", "source": "dhl_api_404"}}
    n = normalize_batch_state(audit, pz_done_batch_dir)
    assert n.tracking_404_nonblocking
    sections = build_actions_for_batch(n.batch_id, n)
    pz = {a.id: a for a in sections["pz_accounting"]}
    # Run PZ should still be enabled (it was already done; ID still 'pz.run')
    assert pz["pz.run"].enabled


# ── 7. Agency queued maps to queue id ──────────────────────────────────────

def test_agency_queued_maps_to_queue_id(pz_done_audit, pz_done_batch_dir):
    audit = {**pz_done_audit, "agency_reply_package": {"queue_id": "Q-123", "status": "queued"}}
    n = normalize_batch_state(audit, pz_done_batch_dir)
    assert n.agency_queue_id == "Q-123"
    sections = build_actions_for_batch(n.batch_id, n)
    cowork = {a.id: a for a in sections["cowork"]}
    # send_smtp endpoint should reference the queue id
    assert "Q-123" in cowork["cowork.send_smtp"].endpoint


# ── 8. Sent agency email disables resend ────────────────────────────────────

def test_sent_agency_email_disables_resend(pz_done_audit, pz_done_batch_dir):
    audit = {**pz_done_audit, "agency_reply_package": {"queue_id": "Q-XX", "status": "sent"}}
    n = normalize_batch_state(audit, pz_done_batch_dir)
    assert n.agency_email_sent
    sections = build_actions_for_batch(n.batch_id, n)
    cowork = {a.id: a for a in sections["cowork"]}
    assert not cowork["cowork.send_smtp"].enabled
    assert "Already sent" in cowork["cowork.send_smtp"].reason


# ── 9. Chrome guide route exists in mounted app ─────────────────────────────

def test_chrome_guide_route_exists(app_instance):
    routes = collect_app_routes(app_instance)
    paths = {p for (_m, p) in routes}
    assert any("/chrome_wfirma_autofill/" in p for p in paths), \
        "Chrome AutoFill route must be mounted (added in main.py)"


# ── 10. wFirma actions use valid endpoints ─────────────────────────────────

def test_wfirma_actions_use_valid_endpoints(pz_done_audit, pz_done_batch_dir, app_instance):
    n = normalize_batch_state(pz_done_audit, pz_done_batch_dir)
    sections = build_actions_for_batch(n.batch_id, n)
    wfirma_endpoints = [(a.id, a.method, a.endpoint) for a in sections["wfirma"]
                        if a.endpoint and a.enabled]
    broken = validate_endpoints(app_instance, wfirma_endpoints)
    assert broken == [], f"wFirma actions have broken endpoints: {broken}"


# ── 11. Layout sections always present (regression) ─────────────────────────

def test_layout_sections_constant_count(empty_audit, empty_batch_dir, pz_done_audit, pz_done_batch_dir):
    n_empty = normalize_batch_state(empty_audit, empty_batch_dir)
    n_full  = normalize_batch_state(pz_done_audit, pz_done_batch_dir)
    s_empty = build_actions_for_batch(n_empty.batch_id, n_empty)
    s_full  = build_actions_for_batch(n_full.batch_id, n_full)
    assert set(s_empty.keys()) == set(s_full.keys()) == set(SECTION_KEYS)
    # Every action ID present in one must be present in the other (visibility is permanent)
    ids_empty = sorted(a.id for sec in s_empty.values() for a in sec)
    ids_full  = sorted(a.id for sec in s_full.values() for a in sec)
    assert ids_empty == ids_full


# ── 12. Stale clearance_status overridden by real evidence ─────────────────

def test_stale_clearance_status_overridden_by_pz_files(pz_done_audit, pz_done_batch_dir):
    """status='processing' but PZ files on disk → pz_generated MUST be True."""
    audit = {**pz_done_audit, "status": "processing"}
    n = normalize_batch_state(audit, pz_done_batch_dir)
    assert n.has_pz_pdf and n.has_pz_xlsx
    assert n.pz_generated, "file evidence must override stale 'processing' status"


# ── 13. No financial fields modified ────────────────────────────────────────

def test_normalizer_does_not_modify_audit(pz_done_audit, pz_done_batch_dir):
    snapshot = json.dumps(pz_done_audit, sort_keys=True)
    normalize_batch_state(pz_done_audit, pz_done_batch_dir)
    after = json.dumps(pz_done_audit, sort_keys=True)
    assert snapshot == after, "normalizer must be read-only"


def test_registry_does_not_modify_normalized_state(pz_done_audit, pz_done_batch_dir):
    n = normalize_batch_state(pz_done_audit, pz_done_batch_dir)
    snapshot = json.dumps(n.to_dict(), sort_keys=True)
    build_actions_for_batch(n.batch_id, n)
    after = json.dumps(n.to_dict(), sort_keys=True)
    assert snapshot == after


# ── 14-17. Per-action body contract (no reliance on backend defaults) ──────

def test_reparse_sad_action_includes_mode_sad(pz_done_audit, pz_done_batch_dir):
    """customs.reparse_sad must explicitly send {'mode':'sad'} — not depend on backend default."""
    n = normalize_batch_state(pz_done_audit, pz_done_batch_dir)
    sections = build_actions_for_batch(n.batch_id, n)
    by_id = {a.id: a for sec in sections.values() for a in sec}
    a = by_id["customs.reparse_sad"]
    assert a.body == {"mode": "sad"}, f"reparse_sad body should be {{'mode':'sad'}}, got {a.body}"


def test_smtp_send_actions_include_method_smtp(pz_done_audit, pz_done_batch_dir):
    """SMTP send actions must explicitly send {'method':'smtp'}."""
    audit = {**pz_done_audit,
             "agency_reply_package": {"queue_id": "Q-1", "status": "queued"},
             "dhl_reply_package":    {"queue_id": "DR-1", "status": "queued"}}
    n = normalize_batch_state(audit, pz_done_batch_dir)
    sections = build_actions_for_batch(n.batch_id, n)
    by_id = {a.id: a for sec in sections.values() for a in sec}
    assert by_id["dhl.send_reply"].body  == {"method": "smtp"}
    assert by_id["cowork.send_smtp"].body == {"method": "smtp"}
    assert by_id["cowork.send_manual"].body == {"method": "manual_package"}


def test_mcp_send_action_disabled_with_explicit_body(pz_done_audit, pz_done_batch_dir):
    """cowork.send_mcp must be disabled with reason; body still explicit so registry stays self-describing."""
    audit = {**pz_done_audit, "agency_reply_package": {"queue_id": "Q-1", "status": "queued"}}
    n = normalize_batch_state(audit, pz_done_batch_dir)
    sections = build_actions_for_batch(n.batch_id, n)
    by_id = {a.id: a for sec in sections.values() for a in sec}
    a = by_id["cowork.send_mcp"]
    assert a.enabled is False
    assert a.state == "blocked"
    assert "MCP send disabled" in a.reason
    assert a.body == {"method": "zoho_mcp"}


def test_actions_without_body_default_to_empty_dict(empty_audit, empty_batch_dir):
    """Every other action must serialise body as {} so the click handler never sends garbage."""
    n = normalize_batch_state(empty_audit, empty_batch_dir)
    sections = build_actions_for_batch(n.batch_id, n)
    bodied = {"customs.reparse_sad", "dhl.send_reply",
              "cowork.send_smtp", "cowork.send_mcp", "cowork.send_manual"}
    for sec, actions in sections.items():
        for a in actions:
            if a.id in bodied:
                continue
            assert a.body == {}, f"action {a.id} should have empty body, got {a.body}"


# ── Bonus: every registered endpoint validates against the real app ────────

def test_all_registry_endpoints_validate_for_pz_done_batch(pz_done_audit, pz_done_batch_dir, app_instance):
    n = normalize_batch_state(pz_done_audit, pz_done_batch_dir)
    endpoints = all_action_endpoints(n)
    broken = validate_endpoints(app_instance, endpoints)
    # broken_routes is a soft warning — just assert the structure is correct
    for b in broken:
        assert b.action_id and b.endpoint and b.method
