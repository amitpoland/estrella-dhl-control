"""
test_b4_idempotency.py — Phase 3.2.x B4 (post-DHL agency forward)
idempotency hardening parity with Phase 3.2's B2 pattern.

Pins:
  - Lock + pre-marker (build_started_at) blocks re-fire across crash
    recovery and parallel sweeps.
  - Existing Phase 1.1.5 triple-check (sent / provider_message_id /
    email_id) still independently blocks re-fire.
  - Customs-value-freeze: observer never mutates verification /
    invoice_totals / clearance_decision.
"""
from __future__ import annotations

import json
import sys
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

_SVC = Path(__file__).parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))


# ── Fixtures ───────────────────────────────────────────────────────────────

def _settings_obj(tmp_path: Path):
    class S:
        storage_root = tmp_path
        smtp_host = "smtppro.zoho.in"
        smtp_port = 465
        smtp_user = None
        smtp_password = None
        smtp_use_ssl = True
        mcp_send_max_attachment_bytes = 200_000
    return S()


def _seed_b4(tmp_path: Path, *, batch_id: str = "B_B4_T",
             awb: str = "1012178215",
             extras: dict | None = None) -> tuple[Path, dict]:
    """Path B audit at the B4-trigger condition: agency clearance, DHL
    email received, dhl_documents_received non-empty."""
    batch_dir = tmp_path / "outputs" / batch_id
    awb_dir   = batch_dir / "source" / "awb"
    inv_dir   = batch_dir / "source" / "invoices"
    docs_dir  = batch_dir / "dhl_docs"
    polish_dir = tmp_path / "polish_descriptions"
    for d in (awb_dir, inv_dir, docs_dir, polish_dir):
        d.mkdir(parents=True, exist_ok=True)

    # Required files for the builder to succeed (path is real → builder
    # populates attachments). DSK doc + invoice + AWB + Polish desc.
    (inv_dir / "INV.pdf").write_bytes(b"%PDF inv")
    (polish_dir / "POLISH.pdf").write_bytes(b"%PDF polish")
    awb_filename = f"{awb} AWB.pdf"
    (awb_dir / awb_filename).write_bytes(b"%PDF awb")
    dhl_doc = docs_dir / "DSK_AWB.pdf"
    dhl_doc.write_bytes(b"%PDF DSK")

    audit = {
        "batch_id":    batch_id,
        "awb":         awb,
        "tracking_no": awb,
        "doc_no":      "PZ_TEST",
        "polish_desc_filename": "POLISH.pdf",
        "inputs":      {"awb": awb_filename},
        "clearance_decision": {
            "clearance_path":  "agency_clearance",
            "total_value_usd": 5000.0,
        },
        "invoice_totals": {"total_cif_usd": 5000.0},
        "verification":   {"invoice_cif_total_usd": 5000.0},
        "dhl_email":      {"received": True, "ticket": "T#1WA"},
        "dhl_documents_received": {
            "received":    True,
            "files":       [{"name": "DSK_AWB.pdf",
                             "path": str(dhl_doc),
                             "type": "DSK",
                             "size": dhl_doc.stat().st_size}],
            "received_at": "2026-04-29T08:00:00+00:00",
        },
    }
    if extras:
        audit.update(extras)

    ap = batch_dir / "audit.json"
    ap.write_text(json.dumps(audit), encoding="utf-8")
    return ap, audit


def _patch_settings(monkeypatch, tmp_path):
    from app.services import active_shipment_monitor as asm
    from app.services import agency_forward_after_dhl_builder as afb
    from app.core.config import settings as real_settings
    s = _settings_obj(tmp_path)
    monkeypatch.setattr(asm, "settings", s)
    monkeypatch.setattr(afb, "settings", s)
    monkeypatch.setattr(real_settings, "storage_root", tmp_path, raising=False)
    return s


def _stub_smtp_unconfigured(monkeypatch):
    monkeypatch.setattr("app.services.email_sender._smtp_configured",
                        lambda: False)


def _stub_queue_email(succeed: bool = True, exc: Exception | None = None):
    if exc is not None:
        return patch("app.services.email_service.queue_email", side_effect=exc)
    if succeed:
        return patch("app.services.email_service.queue_email",
                     return_value="b4-email-id-OK")
    return patch("app.services.email_service.queue_email",
                 side_effect=RuntimeError("smtp_down"))


# ── Parallel-fire idempotency ──────────────────────────────────────────────

def test_b4_idempotent_under_parallel_calls(tmp_path, monkeypatch):
    """Two threads invoke observer concurrently; queue_email called exactly
    once. Lock + in-lock re-check enforces single-fire."""
    _patch_settings(monkeypatch, tmp_path)
    _stub_smtp_unconfigured(monkeypatch)
    ap, _ = _seed_b4(tmp_path, batch_id="B_B4_PARA")
    from app.services import active_shipment_monitor as asm

    results = []
    with _stub_queue_email(succeed=True) as q:
        def runner():
            results.append(asm._ensure_agency_forward_after_dhl(
                ap, json.loads(ap.read_text())))
        threads = [threading.Thread(target=runner) for _ in range(4)]
        for t in threads: t.start()
        for t in threads: t.join()

    fired = [r for r in results if r.get("built")]
    assert len(fired) == 1
    assert q.call_count == 1


# ── Crash-recovery via pre-marker ──────────────────────────────────────────

def test_b4_idempotent_under_crash_recovery(tmp_path, monkeypatch):
    """Pre-marker (build_started_at) blocks re-fire even when no other
    idempotency field is set (simulates crash between queue_email and
    final write)."""
    _patch_settings(monkeypatch, tmp_path)
    _stub_smtp_unconfigured(monkeypatch)
    ap, _ = _seed_b4(tmp_path, batch_id="B_B4_CRASH")
    a = json.loads(ap.read_text())
    a["agency_forward_after_dhl"] = {"build_started_at": "2026-05-07T10:00:00+00:00"}
    ap.write_text(json.dumps(a), encoding="utf-8")

    from app.services import active_shipment_monitor as asm
    with _stub_queue_email(succeed=True) as q:
        result = asm._ensure_agency_forward_after_dhl(
            ap, json.loads(ap.read_text()))

    assert result.get("built") is False
    q.assert_not_called()


# ── Pre-marker written before queue_email ─────────────────────────────────

def test_b4_pre_marker_written_before_queue(tmp_path, monkeypatch):
    """At the moment queue_email is invoked, the audit on disk must
    already contain build_started_at. Pin the ordering."""
    _patch_settings(monkeypatch, tmp_path)
    _stub_smtp_unconfigured(monkeypatch)
    ap, _ = _seed_b4(tmp_path, batch_id="B_B4_ORDER")

    observed = {}
    def _capture(**kwargs):
        # Read audit at the moment queue_email is called
        observed["audit_at_queue"] = json.loads(ap.read_text())
        return "b4-email-id-ORDER"

    from app.services import active_shipment_monitor as asm
    with patch("app.services.email_service.queue_email", side_effect=_capture):
        asm._ensure_agency_forward_after_dhl(ap, json.loads(ap.read_text()))

    fwd_at_queue = (observed["audit_at_queue"].get(
        "agency_forward_after_dhl") or {})
    assert fwd_at_queue.get("build_started_at"), (
        "build_started_at must be written to disk BEFORE queue_email is called"
    )


# ── Triple-check parity (Phase 1.1.5 markers still independently block) ───

@pytest.mark.parametrize("fwd_state,label", [
    ({"sent": True},                                     "sent_only"),
    ({"email_id": "stale-id"},                           "email_id_only"),
    ({"sent": True, "provider_message_id": "stale-pm"},  "sent_with_provider"),
])
def test_b4_existing_triple_check_still_blocks(tmp_path, monkeypatch,
                                                fwd_state, label):
    """Phase 1.1.5's idempotency markers still independently block
    re-fire without the new build_started_at marker. Three states:
      - sent=True (early `already` gate)
      - email_id present (secondary hard-stop)
      - sent + provider_message_id (confirmed-delivered hard-stop)
    Regression: the Phase 3.2.x pre-marker is additive, not a replacement."""
    _patch_settings(monkeypatch, tmp_path)
    _stub_smtp_unconfigured(monkeypatch)
    ap, _ = _seed_b4(tmp_path, batch_id=f"B_B4_TRIPLE_{label}")
    a = json.loads(ap.read_text())
    a["agency_forward_after_dhl"] = dict(fwd_state)
    ap.write_text(json.dumps(a), encoding="utf-8")

    from app.services import active_shipment_monitor as asm
    with _stub_queue_email(succeed=True) as q:
        result = asm._ensure_agency_forward_after_dhl(
            ap, json.loads(ap.read_text()))
    assert result.get("built") is False
    q.assert_not_called()


# ── Customs-value-freeze ──────────────────────────────────────────────────

def test_b4_customs_value_freeze(tmp_path, monkeypatch):
    """B4 path writes only audit.agency_forward_after_dhl.* fields.
    verification, invoice_totals, clearance_decision are byte-identical
    pre/post observer pass."""
    _patch_settings(monkeypatch, tmp_path)
    _stub_smtp_unconfigured(monkeypatch)
    ap, audit_pre = _seed_b4(tmp_path, batch_id="B_B4_FREEZE")
    pre = {
        "verification":       json.loads(json.dumps(audit_pre["verification"])),
        "invoice_totals":     json.loads(json.dumps(audit_pre["invoice_totals"])),
        "clearance_decision": json.loads(json.dumps(audit_pre["clearance_decision"])),
    }

    from app.services import active_shipment_monitor as asm
    with _stub_queue_email(succeed=True):
        asm._ensure_agency_forward_after_dhl(ap, json.loads(ap.read_text()))

    audit_post = json.loads(ap.read_text())
    assert audit_post["verification"]       == pre["verification"]
    assert audit_post["invoice_totals"]     == pre["invoice_totals"]
    assert audit_post["clearance_decision"] == pre["clearance_decision"]
