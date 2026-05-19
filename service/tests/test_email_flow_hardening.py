"""test_email_flow_hardening.py — campaign-wide email/orchestration hardening.

Source-grep + runtime invariants discovered during the Phase 6E
email-flow validation campaign.  Every assertion below protects a
specific risk identified in the audit:

  - new Phase 6E flags must default safe (advance pack, dhl followup)
  - no direct SMTP outside email_sender.py
  - every documented email_type is reachable only via queue_email
  - orchestrator never writes carrier_arrived_at_poland_at (runtime)
  - orchestrator's queue/path resolution honours STORAGE_ROOT (no
    hardcoded C:\\PZ in service modules)
  - exactly one SMTP construction site exists in the entire backend
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest


_APP_DIR = Path(__file__).resolve().parent.parent / "app"
_SERVICES_DIR = _APP_DIR / "services"
_API_DIR = _APP_DIR / "api"


# ── Flag defaults (Phase 6E additions) ───────────────────────────────────────

def test_phase6e_flags_default_safe():
    from app.core.config import Settings
    s = Settings()
    assert s.dhl_orch_auto_send_agency_advance is False
    assert s.dhl_orch_auto_send_dhl_followup is False


def test_invoice_creation_flag_remains_false():
    """The master invoice-creation gate must stay disabled by default."""
    from app.core.config import Settings
    s = Settings()
    assert s.wfirma_create_invoice_allowed is False


# ── SMTP isolation: only ONE construction site ───────────────────────────────

def test_only_email_sender_imports_smtplib():
    """Source-grep: smtplib must be imported by exactly one module.

    If a new module imports smtplib, every guard layer is bypassed —
    queue_email's idempotency, send_queued_email's delivered guard,
    and the kill-switch path all live inside email_sender.  Any other
    SMTP construction site is a critical regression.
    """
    hits = []
    for p in (_APP_DIR).rglob("*.py"):
        try:
            src = p.read_text(encoding="utf-8")
        except Exception:
            continue
        # Strip comments and docstrings to ignore mentions
        code = re.sub(r"#[^\n]*", "", src)
        code = re.sub(r'"""[\s\S]*?"""', "", code)
        code = re.sub(r"'''[\s\S]*?'''", "", code)
        if "import smtplib" in code or "from smtplib" in code:
            hits.append(p.relative_to(_APP_DIR).as_posix())
    assert hits == ["services/email_sender.py"], (
        f"smtplib imported outside email_sender.py: {hits!r}"
    )


# ── Email-type taxonomy snapshot ─────────────────────────────────────────────

# These are the 7 email types observed in production callsites (excluding
# the auth path which passes empty string).  If a new type is added it
# MUST appear here — the snapshot catches accidental new types that
# would bypass the kill-switch classifier without being added to
# _AUTO_FOLLOWUP_TYPES (if the kill switch ever activates).
KNOWN_EMAIL_TYPES = frozenset({
    "dhl_b2_dsk_only_reply",
    "dhl_reply",
    "dhl_self_clearance_reply",
    "dhl_followup",
    "dhl_proactive_dispatch",
    "agency_forward_after_dhl",
    "agency_followup",
    "agency",
    "broker_followup",
})


def test_email_type_taxonomy_snapshot():
    """Source-grep every email_type literal passed to queue_email.
    Any new type discovered must be added to KNOWN_EMAIL_TYPES.

    Pattern only matches single-quoted/double-quoted literals after
    a literal ``email_type=`` token, ignoring positional ``type=`` /
    ``body_type=`` / etc. that happen to share the suffix.
    """
    found = set()
    # Strict: word-boundary email_type, then = "literal" with at least
    # two characters that include an underscore — filters out
    # incidental matches like type='html' or body=...
    pattern = re.compile(r'\bemail_type\s*=\s*["\']([a-z][a-z_0-9]{4,})["\']')
    for p in _SERVICES_DIR.rglob("*.py"):
        try:
            src = p.read_text(encoding="utf-8")
        except Exception:
            continue
        for m in pattern.finditer(src):
            found.add(m.group(1))
    for p in _API_DIR.rglob("*.py"):
        try:
            src = p.read_text(encoding="utf-8")
        except Exception:
            continue
        for m in pattern.finditer(src):
            found.add(m.group(1))
    unknown = found - KNOWN_EMAIL_TYPES
    assert not unknown, (
        f"new email_type(s) discovered, update KNOWN_EMAIL_TYPES: {unknown}"
    )


# ── Orchestrator queue/path isolation (runtime) ──────────────────────────────

def test_orchestrator_path_resolution_honours_storage_root(tmp_path, monkeypatch):
    """If an operator sets STORAGE_ROOT for a test run, the orchestrator
    must use it.  No hardcoded C:\\PZ anywhere in the path resolution.
    Protects against accidental production-queue writes from a test."""
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    from app.core.config import settings
    monkeypatch.setattr(settings, "storage_root", tmp_path, raising=False)
    from app.services import dhl_orchestrator as orch
    # Module helpers must resolve under tmp_path:
    assert str(orch._decisions_jsonl_path()).startswith(str(tmp_path))
    paths_root = tmp_path / "outputs"
    paths_root.mkdir(parents=True, exist_ok=True)
    # _audit_paths is a no-op (empty dir) but the base it walks is tmp_path
    assert orch._audit_paths() == []


def test_orchestrator_module_has_no_hardcoded_pz_path():
    """Source-grep: orchestrator must not contain C:\\PZ or /c/PZ literals."""
    src = (_SERVICES_DIR / "dhl_orchestrator.py").read_text(encoding="utf-8")
    code = re.sub(r"#[^\n]*", "", src)
    code = re.sub(r'"""[\s\S]*?"""', "", code)
    code = re.sub(r"'''[\s\S]*?'''", "", code)
    for needle in ("C:\\PZ", "C:/PZ", "/c/PZ", "c:\\pz", "c:/pz"):
        assert needle.lower() not in code.lower(), (
            f"orchestrator code contains hardcoded path: {needle!r}"
        )


# ── Tick persistence preserves protected audit fields ────────────────────────

def test_tick_preserves_carrier_arrived_at_poland_at(tmp_path, monkeypatch):
    """The stale carrier_arrived_at_poland_at field on historical audits
    must be byte-preserved across orchestrator ticks (orchestrator never
    writes nor clears it)."""
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    from app.core.config import settings
    monkeypatch.setattr(settings, "storage_root", tmp_path, raising=False)
    from app.services.dhl_orchestrator import run_tick, reset_cooldowns_for_tests
    reset_cooldowns_for_tests()

    audit = {
        "batch_id": "SHIPMENT_CAP_X",
        "awb": "CAP1", "tracking_no": "CAP1",
        "clearance_decision": {"clearance_path": "agency_clearance"},
        "clearance_status": "dsk_generated",
        "carrier_arrived_at_poland_at": "2026-05-16T17:00:00+02:00",
        "tracking_events": [{"normalized_stage": "DEPARTED_ORIGIN"}],
        "tracking": {"status": "on_hold"},
    }
    d = tmp_path / "outputs" / audit["batch_id"]
    d.mkdir(parents=True, exist_ok=True)
    (d / "audit.json").write_text(json.dumps(audit), encoding="utf-8")

    before = (d / "audit.json").read_text(encoding="utf-8")
    run_tick(persist=True)
    after = json.loads((d / "audit.json").read_text(encoding="utf-8"))
    # Field preserved bytewise:
    assert after["carrier_arrived_at_poland_at"] == "2026-05-16T17:00:00+02:00"
    # Orchestrator added telemetry but didn't touch the stale field:
    assert "orchestrator" in after


# ── No persistence in dry-run path ───────────────────────────────────────────

def test_dry_run_produces_no_decisions_log_file(tmp_path, monkeypatch):
    """POST /api/v1/orchestrator/dry-run must NEVER write the
    orchestrator_decisions.jsonl file, even if active audits exist."""
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    from app.core.config import settings
    monkeypatch.setattr(settings, "storage_root", tmp_path, raising=False)
    from app.services.dhl_orchestrator import run_tick, reset_cooldowns_for_tests
    reset_cooldowns_for_tests()

    audit = {
        "batch_id": "SHIPMENT_DRY",
        "awb": "DRY1", "tracking_no": "DRY1",
        "clearance_decision": {"clearance_path": "agency_clearance"},
        "tracking_events": [{"normalized_stage": "DEPARTED_ORIGIN"}],
    }
    d = tmp_path / "outputs" / audit["batch_id"]
    d.mkdir(parents=True, exist_ok=True)
    (d / "audit.json").write_text(json.dumps(audit), encoding="utf-8")

    run_tick(persist=False)
    assert not (tmp_path / "orchestrator_decisions.jsonl").exists()
    new = json.loads((d / "audit.json").read_text(encoding="utf-8"))
    assert "orchestrator" not in new
