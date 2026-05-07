"""
test_b2_idempotency.py — Phase 3.2 B2 (Path B reply when DHL emails for
the customs package) tests.

Pins:
  - Spec rule 5 compliance: B2 builder attaches DSK only, CC internal only.
  - DSK gate: observer skips silently when audit.dsk_filename absent OR
    file not on disk; re-fires once operator generates DSK.
  - Idempotency: lock + pre-marker (build_started_at) + status check.
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


def _seed_b2(tmp_path: Path, *, batch_id: str = "B_B2_T",
             awb: str = "1012178215",
             with_dsk: bool = True,
             dhl_email_received: bool = True,
             extras: dict | None = None) -> tuple[Path, dict]:
    """Seed a Path B audit with DHL email received and (optionally) DSK on disk."""
    batch_dir = tmp_path / "outputs" / batch_id
    batch_dir.mkdir(parents=True, exist_ok=True)
    dsk_dir = tmp_path / "dsk"
    dsk_dir.mkdir(parents=True, exist_ok=True)

    dsk_filename = f"DSK_{awb}_07-05-2026.pdf"
    dsk_path     = dsk_dir / dsk_filename
    if with_dsk:
        dsk_path.write_bytes(b"%PDF DSK content")

    audit = {
        "batch_id":    batch_id,
        "awb":         awb,
        "tracking_no": awb,
        "doc_no":      "PZ_TEST",
        "clearance_decision": {
            "clearance_path":  "agency_clearance",
            "total_value_usd": 5000.0,
        },
        "invoice_totals":  {"total_cif_usd": 5000.0},
        "verification":    {"invoice_cif_total_usd": 5000.0},
        "dhl_email":       {"received": dhl_email_received,
                            "ticket": "T#1WA2604290000028"},
        "dhl_ticket":      "T#1WA2604290000028",
    }
    if with_dsk:
        audit["dsk_filename"] = dsk_filename
        audit["dsk_path"]     = str(dsk_path)
        audit["dsk_status"]   = "generated"
    if extras:
        audit.update(extras)

    ap = batch_dir / "audit.json"
    ap.write_text(json.dumps(audit), encoding="utf-8")
    return ap, audit


def _patch_settings(monkeypatch, tmp_path):
    from app.services import active_shipment_monitor as asm
    from app.services import dhl_reply_builder as drb
    from app.core.config import settings as real_settings
    s = _settings_obj(tmp_path)
    monkeypatch.setattr(asm, "settings", s)
    monkeypatch.setattr(drb, "settings", s)
    monkeypatch.setattr(real_settings, "storage_root", tmp_path, raising=False)
    return s


def _stub_smtp_unconfigured(monkeypatch):
    """Force SMTP path to skip — observer reaches queue_email but the
    auto-send branch becomes a no-op."""
    monkeypatch.setattr("app.services.email_sender._smtp_configured",
                        lambda: False)


def _stub_queue_email(succeed: bool = True, exc: Exception | None = None):
    if exc is not None:
        return patch("app.services.email_service.queue_email", side_effect=exc)
    if succeed:
        return patch("app.services.email_service.queue_email",
                     return_value="b2-email-id-OK")
    return patch("app.services.email_service.queue_email",
                 side_effect=RuntimeError("smtp_down"))


# ── Builder tests — spec rule 5 compliance ────────────────────────────────

def test_b2_attachments_dsk_only(tmp_path, monkeypatch):
    """B2 builder attaches the DSK file ONLY. No description, no invoice,
    no AWB. Spec rule 5."""
    _patch_settings(monkeypatch, tmp_path)
    ap, audit = _seed_b2(tmp_path, batch_id="B_B2_DSK_ONLY")
    from app.services.dhl_reply_builder import build_dhl_b2_dsk_only_reply
    pkg = build_dhl_b2_dsk_only_reply(audit, audit["batch_id"])

    labels = [a["label"] for a in pkg["attachments"]]
    assert any(l.startswith("DSK:") for l in labels)
    assert all("Polish" not in l for l in labels)
    assert all("Invoice" not in l for l in labels)
    assert all("AWB Document" not in l for l in labels)
    assert len(pkg["attachments"]) == 1


def test_b2_cc_internal_only(tmp_path, monkeypatch):
    """B2 CC: exactly the three Estrella addresses; no agency, no Ganther."""
    _patch_settings(monkeypatch, tmp_path)
    ap, audit = _seed_b2(tmp_path, batch_id="B_B2_CC")
    from app.services.dhl_reply_builder import build_dhl_b2_dsk_only_reply
    pkg = build_dhl_b2_dsk_only_reply(audit, audit["batch_id"])

    cc_list = pkg["cc_list"]
    assert "info@estrellajewels.eu"     in cc_list
    assert "import@estrellajewels.eu"   in cc_list
    assert "account@estrellajewels.eu"  in cc_list
    assert "ciagarlak@ganther.com.pl"  not in cc_list
    assert "piotr@acspedycja.pl"       not in cc_list
    assert "biuro@acspedycja.pl"       not in cc_list
    assert "roman@acspedycja.pl"       not in cc_list


def test_b2_to_is_dhl(tmp_path, monkeypatch):
    _patch_settings(monkeypatch, tmp_path)
    ap, audit = _seed_b2(tmp_path, batch_id="B_B2_TO")
    from app.services.dhl_reply_builder import build_dhl_b2_dsk_only_reply
    pkg = build_dhl_b2_dsk_only_reply(audit, audit["batch_id"])
    assert "odprawacelna@dhl.com" in pkg["to_list"]


def test_b2_subject_is_thread_reply(tmp_path, monkeypatch):
    _patch_settings(monkeypatch, tmp_path)
    ap, audit = _seed_b2(tmp_path, batch_id="B_B2_SUBJ")
    from app.services.dhl_reply_builder import build_dhl_b2_dsk_only_reply
    pkg = build_dhl_b2_dsk_only_reply(audit, audit["batch_id"])
    assert pkg["subject"].startswith("Re:")
    assert "T#1WA2604290000028" in pkg["subject"]
    assert "1012178215" in pkg["subject"]


def test_b2_builder_missing_when_dsk_absent(tmp_path, monkeypatch):
    """If audit.dsk_filename is empty or file is gone, builder reports it
    in `missing` and produces no attachments. (Defensive — observer's gate
    catches this earlier.)"""
    _patch_settings(monkeypatch, tmp_path)
    ap, audit = _seed_b2(tmp_path, batch_id="B_B2_NO_DSK", with_dsk=False)
    from app.services.dhl_reply_builder import build_dhl_b2_dsk_only_reply
    pkg = build_dhl_b2_dsk_only_reply(audit, audit["batch_id"])
    assert pkg["missing"]
    assert pkg["attachments"] == []


# ── Observer DSK-gate tests ────────────────────────────────────────────────

def test_b2_skips_when_dsk_missing(tmp_path, monkeypatch):
    """Observer returns early without queueing when DSK absent."""
    _patch_settings(monkeypatch, tmp_path)
    _stub_smtp_unconfigured(monkeypatch)
    ap, _ = _seed_b2(tmp_path, batch_id="B_B2_SKIP", with_dsk=False)
    from app.services import active_shipment_monitor as asm

    with _stub_queue_email(succeed=True) as q:
        result = asm._ensure_dhl_dsk_transfer_reply(
            ap, json.loads(ap.read_text()))
    assert result["built"] is False
    q.assert_not_called()
    persisted = json.loads(ap.read_text())
    # Decision-trail field, not idempotency marker
    assert persisted.get("b2_dsk_skip_reason", {}).get("reason") == \
        "dsk_not_yet_generated"
    # Idempotency markers NOT set — the observer can re-fire next sweep
    drp = persisted.get("dhl_reply_package") or {}
    assert "build_started_at" not in drp
    assert "status"            not in drp


def test_b2_re_evaluates_after_dsk_generated(tmp_path, monkeypatch):
    """Observer skipped because DSK was missing; once DSK lands, next
    sweep fires the reply."""
    _patch_settings(monkeypatch, tmp_path)
    _stub_smtp_unconfigured(monkeypatch)
    ap, _ = _seed_b2(tmp_path, batch_id="B_B2_REEVAL", with_dsk=False)
    from app.services import active_shipment_monitor as asm

    with _stub_queue_email(succeed=True) as q:
        # First pass — skipped (no DSK)
        first = asm._ensure_dhl_dsk_transfer_reply(
            ap, json.loads(ap.read_text()))
        assert first["built"] is False
        assert q.call_count == 0

        # Operator generates DSK (simulate)
        a = json.loads(ap.read_text())
        dsk_dir = tmp_path / "dsk"
        dsk_path = dsk_dir / "DSK_late.pdf"
        dsk_path.write_bytes(b"%PDF DSK")
        a["dsk_filename"] = "DSK_late.pdf"
        a["dsk_path"]     = str(dsk_path)
        ap.write_text(json.dumps(a), encoding="utf-8")

        # Second pass — fires
        second = asm._ensure_dhl_dsk_transfer_reply(
            ap, json.loads(ap.read_text()))
        assert second["built"] is True
        assert q.call_count == 1


def test_b2_fires_when_dsk_present(tmp_path, monkeypatch):
    """Happy path: DSK on disk + DHL email received → email queued."""
    _patch_settings(monkeypatch, tmp_path)
    _stub_smtp_unconfigured(monkeypatch)
    ap, _ = _seed_b2(tmp_path, batch_id="B_B2_HAPPY")
    from app.services import active_shipment_monitor as asm

    captured: dict = {}
    def _capture(**kwargs):
        captured.update(kwargs)
        return "b2-email-id-HAPPY"

    with patch("app.services.email_service.queue_email", side_effect=_capture):
        result = asm._ensure_dhl_dsk_transfer_reply(
            ap, json.loads(ap.read_text()))

    assert result["built"] is True
    assert result["email_id"] == "b2-email-id-HAPPY"
    persisted = json.loads(ap.read_text())
    drp = persisted["dhl_reply_package"]
    assert drp["status"] == "queued"
    assert drp["build_started_at"]      # pre-marker preserved
    assert drp["email_id"] == "b2-email-id-HAPPY"
    # Captured email arguments — DSK only, internal CC only
    assert "DSK_" in captured.get("subject", "") or \
           captured.get("subject", "").startswith("Re:")
    assert "info@estrellajewels.eu"   in captured.get("cc", "")
    assert "ciagarlak@ganther.com.pl" not in captured.get("cc", "")


# ── Idempotency tests ──────────────────────────────────────────────────────

def test_b2_idempotent_under_sequential_calls(tmp_path, monkeypatch):
    """Second observer pass after success returns no-op."""
    _patch_settings(monkeypatch, tmp_path)
    _stub_smtp_unconfigured(monkeypatch)
    ap, _ = _seed_b2(tmp_path, batch_id="B_B2_SEQ")
    from app.services import active_shipment_monitor as asm

    with _stub_queue_email(succeed=True) as q:
        first  = asm._ensure_dhl_dsk_transfer_reply(
            ap, json.loads(ap.read_text()))
        second = asm._ensure_dhl_dsk_transfer_reply(
            ap, json.loads(ap.read_text()))

    assert first["built"] is True
    assert second["built"] is False
    assert q.call_count == 1


def test_b2_idempotent_under_parallel_calls(tmp_path, monkeypatch):
    """Two threads invoke observer concurrently; queue_email called exactly once."""
    _patch_settings(monkeypatch, tmp_path)
    _stub_smtp_unconfigured(monkeypatch)
    ap, _ = _seed_b2(tmp_path, batch_id="B_B2_PARA")
    from app.services import active_shipment_monitor as asm

    results = []
    with _stub_queue_email(succeed=True) as q:
        def runner():
            results.append(asm._ensure_dhl_dsk_transfer_reply(
                ap, json.loads(ap.read_text())))
        threads = [threading.Thread(target=runner) for _ in range(4)]
        for t in threads: t.start()
        for t in threads: t.join()

    fired = [r for r in results if r["built"]]
    assert len(fired) == 1
    assert q.call_count == 1


def test_b2_idempotent_under_crash_recovery(tmp_path, monkeypatch):
    """Pre-marker (build_started_at) blocks re-fire even when status is
    not yet set (simulates crash between queue_email and final write)."""
    _patch_settings(monkeypatch, tmp_path)
    _stub_smtp_unconfigured(monkeypatch)
    ap, _ = _seed_b2(tmp_path, batch_id="B_B2_CRASH")
    # Pre-set a build_started_at marker as if a prior sweep crashed mid-fire.
    a = json.loads(ap.read_text())
    a["dhl_reply_package"] = {"build_started_at": "2026-05-07T10:00:00+00:00"}
    ap.write_text(json.dumps(a), encoding="utf-8")

    from app.services import active_shipment_monitor as asm
    with _stub_queue_email(succeed=True) as q:
        result = asm._ensure_dhl_dsk_transfer_reply(
            ap, json.loads(ap.read_text()))

    assert result["built"] is False
    q.assert_not_called()


# ── Customs-value-freeze ───────────────────────────────────────────────────

def test_b2_customs_value_freeze(tmp_path, monkeypatch):
    """B2 path writes only whitelisted audit fields. verification,
    invoice_totals, totals, clearance_decision are byte-identical
    pre/post observer pass."""
    _patch_settings(monkeypatch, tmp_path)
    _stub_smtp_unconfigured(monkeypatch)
    ap, audit_pre = _seed_b2(tmp_path, batch_id="B_B2_FREEZE")
    pre = {
        "verification":       json.loads(json.dumps(audit_pre["verification"])),
        "invoice_totals":     json.loads(json.dumps(audit_pre["invoice_totals"])),
        "clearance_decision": json.loads(json.dumps(audit_pre["clearance_decision"])),
    }

    from app.services import active_shipment_monitor as asm
    with _stub_queue_email(succeed=True):
        asm._ensure_dhl_dsk_transfer_reply(ap, json.loads(ap.read_text()))

    audit_post = json.loads(ap.read_text())
    assert audit_post["verification"]       == pre["verification"]
    assert audit_post["invoice_totals"]     == pre["invoice_totals"]
    assert audit_post["clearance_decision"] == pre["clearance_decision"]


# ── Phase 3.2.1 — operator endpoint writes audit.dsk_path ─────────────────


def test_operator_endpoint_writes_dsk_path_alongside_filename(tmp_path, monkeypatch):
    """The operator's POST /api/v1/dsk/generate endpoint must write BOTH
    audit.dsk_filename AND audit.dsk_path. The B2 observer reads
    dsk_path; without this write, the observer skips even though DSK
    has been generated, and B2 never fires in production."""
    import json as _json
    from fastapi.testclient import TestClient
    from app.main import app
    from app.core.config import settings as real_settings

    # Point storage at tmp + DSK output dir (mirrors routes_dsk's
    # _DSK_OUTPUT_DIR resolution from settings.storage_root)
    monkeypatch.setattr(real_settings, "storage_root", tmp_path, raising=False)

    # Seed a Path B batch on disk so the endpoint can find it.
    batch_id = "B_DSK_PATH"
    batch_dir = tmp_path / "outputs" / batch_id
    batch_dir.mkdir(parents=True, exist_ok=True)
    audit = {
        "batch_id":    batch_id,
        "awb":         "1012178215",
        "tracking_no": "1012178215",
        "clearance_decision": {"clearance_path": "agency_clearance",
                               "total_value_usd": 5000.0},
        "invoice_totals": {"total_cif_usd": 5000.0},
        "dhl_email":   {"received": True, "ticket": "T#1WA2604290000028"},
        "dhl_ticket":  "T#1WA2604290000028",
    }
    audit_path = batch_dir / "audit.json"
    audit_path.write_text(_json.dumps(audit), encoding="utf-8")

    # Mock the generator so we don't need the real PDF template / pypdf
    # on the test path. The mock returns a real path to a synthetic file
    # so the audit.dsk_path the test asserts on points at a real file.
    fake_dsk_dir = tmp_path / "dsk"
    fake_dsk_dir.mkdir(parents=True, exist_ok=True)
    fake_filename = "DSK_1012178215_07-05-2026.pdf"
    fake_output_path = fake_dsk_dir / fake_filename
    fake_output_path.write_bytes(b"%PDF DSK")

    fake_result = {
        "generated":        True,
        "skip_reason":      None,
        "output_path":      str(fake_output_path),
        "awb_clean":        "1012178215",
        "awb_formatted":    "10 1217 8215",
        "date":             "07-05-2026 Warszawa",
        "filename":         fake_filename,
        "file_hash_sha256": "x" * 64,
        "version":          1,
        "regenerated":      False,
    }

    headers = {"X-API-Key": real_settings.api_key} if real_settings.api_key else {}
    with patch("dsk_generator.generate_dsk", return_value=fake_result):
        r = TestClient(app).post(
            "/api/v1/dsk/generate",
            json={
                "awb":              "1012178215",
                "carrier":          "DHL",
                "broker_required":  True,
                "batch_id":         batch_id,
            },
            headers=headers,
        )

    assert r.status_code == 200, r.text
    persisted = _json.loads(audit_path.read_text())

    # Existing contract — still pinned
    assert persisted["dsk_filename"] == fake_filename
    assert persisted["dsk_status"]   == "generated"

    # New contract — Phase 3.2.1
    assert "dsk_path" in persisted, (
        "audit.dsk_path must be written so the B2 observer can locate the DSK"
    )
    assert persisted["dsk_path"] == str(fake_output_path)
    assert Path(persisted["dsk_path"]).is_file()
