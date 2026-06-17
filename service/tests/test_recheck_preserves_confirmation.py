"""test_recheck_preserves_confirmation.py — #646 regression (#570-class lost update).

``recheck_batch`` reads the audit ONCE at the top (unguarded) and writes the whole
object back seconds later, after reparsing. If an operator confirms the advisory
``vision_invoice`` proposal (``operator_confirmed=true``) inside that read→write
window, a whole-object write would silently revert the confirmation — exactly the
#570-class lost-update pattern. ``confirm_vision_invoice`` is the SOLE writer of
``operator_confirmed``; recheck must never author that key.

This module pins the merge-not-replace fix on two surfaces:

  * ``routes_dashboard._persist_recheck`` — overlays the on-disk authoritative
    ``vision_invoice`` under the per-batch lock immediately before writing, so a
    confirmation that landed in the window survives; recheck-owned keys
    (clearance_decision, invoice_totals, rows, CIF, recheck) still persist from
    recheck's own snapshot.
  * ``vision_extractor.run_image_only_invoice_extraction`` — its advisory write is
    now an atomic guard+overlay under the same lock: it aborts if a confirmation
    landed mid-run, and otherwise overlays ONLY ``vision_invoice`` onto fresh disk.

Categories: (1) confirm survives recheck, (2) stale snapshot cannot revert a
confirmation, (3) confirm→recheck→confirm idempotency with original timestamp,
(4) layer isolation — recheck-owned keys persist, only vision_invoice overlaid,
(5) mid-run concurrent confirm aborts the advisory extraction write.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_SVC = Path(__file__).parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

from app.api.routes_dashboard import _persist_recheck, _RECHECK_DISK_AUTHORITATIVE_KEYS
from app.services import vision_extractor


_CONFIRMED_VI = {
    "supplier": "GLOBAL JEWELLERY LLC",
    "invoice_no": "INV-122",
    "currency": "USD",
    "fob_usd": 700.0,
    "line_items": [{"description": "GOLD RING 18K", "total_usd": 400.0}],
    "confidence": 0.88,
    "operator_confirmed": True,
    "status": "confirmed",
    "confirmed_by": "Test Operator",
    "confirmed_at": "2026-06-17T10:00:00Z",
}

_STALE_VI = {
    # The pre-confirmation machine proposal recheck still carries in memory.
    "supplier": "GLOBAL JEWELLERY LLC",
    "invoice_no": "INV-122",
    "currency": "USD",
    "fob_usd": 700.0,
    "line_items": [{"description": "GOLD RING 18K", "total_usd": 400.0}],
    "confidence": 0.88,
    "operator_confirmed": False,
    "status": "proposed",
}


def _seed(tmp_path: Path, audit: dict) -> Path:
    out = tmp_path / "outputs" / "B-646"
    out.mkdir(parents=True, exist_ok=True)
    p = out / "audit.json"
    p.write_text(json.dumps(audit), encoding="utf-8")
    return p


# ── 1 + 2. Confirm survives recheck; stale snapshot cannot revert it ──────────

def test_persist_recheck_preserves_confirmation_over_stale_snapshot(tmp_path):
    # On disk: operator already confirmed (the confirm landed in the window).
    audit_path = _seed(tmp_path, {"batch_id": "B-646", "vision_invoice": dict(_CONFIRMED_VI)})

    # In memory: recheck's stale snapshot still has the unconfirmed proposal.
    snapshot = {"batch_id": "B-646", "vision_invoice": dict(_STALE_VI),
                "recheck": {"last_mode": "all"}}
    _persist_recheck(audit_path, "B-646", snapshot)

    on_disk = json.loads(audit_path.read_text(encoding="utf-8"))
    vi = on_disk["vision_invoice"]
    # The confirmation and its lineage survived the recheck write.
    assert vi["operator_confirmed"] is True
    assert vi["status"] == "confirmed"
    assert vi["confirmed_by"] == "Test Operator"
    assert vi["confirmed_at"] == "2026-06-17T10:00:00Z"
    # recheck still persisted its own block.
    assert on_disk["recheck"]["last_mode"] == "all"


def test_persist_recheck_overlays_vision_invoice_into_the_in_memory_snapshot(tmp_path):
    # The in-memory snapshot object itself must end up carrying the disk-authoritative
    # vision_invoice (it is written verbatim), not the stale block it came in with.
    audit_path = _seed(tmp_path, {"vision_invoice": dict(_CONFIRMED_VI)})
    snapshot = {"vision_invoice": dict(_STALE_VI)}
    _persist_recheck(audit_path, "B-646", snapshot)
    assert snapshot["vision_invoice"]["operator_confirmed"] is True


def test_vision_invoice_is_the_disk_authoritative_key(tmp_path):
    # Guards the constant the fix keys off — if vision_invoice ever drops out of
    # the overlay set, the #646 race reopens silently.
    assert "vision_invoice" in _RECHECK_DISK_AUTHORITATIVE_KEYS


# ── 4. Layer isolation — recheck-owned keys persist, only vision_invoice overlaid

def test_persist_recheck_keeps_recheck_owned_keys_from_snapshot(tmp_path):
    # Disk holds the confirmed proposal AND an OLD clearance/totals snapshot.
    audit_path = _seed(tmp_path, {
        "vision_invoice": dict(_CONFIRMED_VI),
        "awb_customs": {"value_usd": 732.0},
        "clearance_decision": {"status": "OLD"},
        "invoice_totals": {"total_fob_usd": 0},
        "rows": [],
    })
    # recheck recomputed clearance/totals/rows — it OWNS those keys and must win.
    snapshot = {
        "vision_invoice": dict(_STALE_VI),
        "awb_customs": {"value_usd": 732.0},
        "clearance_decision": {"status": "RESOLVED"},
        "invoice_totals": {"total_fob_usd": 700.0},
        "rows": [{"line": 1}],
        "recheck": {"last_mode": "all"},
    }
    _persist_recheck(audit_path, "B-646", snapshot)

    on_disk = json.loads(audit_path.read_text(encoding="utf-8"))
    # vision_invoice came from disk (confirmation preserved)…
    assert on_disk["vision_invoice"]["operator_confirmed"] is True
    # …but every recheck-owned key persisted from recheck's fresh snapshot.
    assert on_disk["clearance_decision"]["status"] == "RESOLVED"
    assert on_disk["invoice_totals"]["total_fob_usd"] == 700.0
    assert on_disk["rows"] == [{"line": 1}]
    assert on_disk["awb_customs"]["value_usd"] == 732.0  # CIF unchanged
    assert on_disk["recheck"]["last_mode"] == "all"


def test_persist_recheck_writes_snapshot_when_disk_has_no_vision_invoice(tmp_path):
    # No confirmation on disk → nothing to preserve; recheck's snapshot persists.
    audit_path = _seed(tmp_path, {"awb_customs": {"value_usd": 732.0}})
    snapshot = {"awb_customs": {"value_usd": 732.0}, "clearance_decision": {"status": "RESOLVED"}}
    _persist_recheck(audit_path, "B-646", snapshot)
    on_disk = json.loads(audit_path.read_text(encoding="utf-8"))
    assert on_disk["clearance_decision"]["status"] == "RESOLVED"
    assert "vision_invoice" not in on_disk


# ── 3. Idempotency — confirm → recheck → confirm again ────────────────────────

def test_confirm_recheck_confirm_is_idempotent_with_original_timestamp(tmp_path):
    # Seed an unconfirmed advisory proposal, then operator confirms it.
    audit_path = _seed(tmp_path, {"batch_id": "B-646", "vision_invoice": dict(_STALE_VI)})
    out_dir = audit_path.parent

    first = vision_extractor.confirm_vision_invoice(out_dir, "B-646", confirmed_by="Test Operator")
    assert first["ok"] is True and first["operator_confirmed"] is True
    confirmed_at = json.loads(audit_path.read_text(encoding="utf-8"))["vision_invoice"]["confirmed_at"]
    assert confirmed_at

    # recheck fires with a STALE in-memory snapshot (unconfirmed) — must not revert.
    snapshot = {"batch_id": "B-646", "vision_invoice": dict(_STALE_VI), "recheck": {"last_mode": "all"}}
    _persist_recheck(audit_path, "B-646", snapshot)
    assert json.loads(audit_path.read_text(encoding="utf-8"))["vision_invoice"]["operator_confirmed"] is True

    # Second confirm is a no-op: already_confirmed, original timestamp preserved.
    second = vision_extractor.confirm_vision_invoice(out_dir, "B-646", confirmed_by="Someone Else")
    assert second["ok"] is True
    assert second.get("already_confirmed") is True
    assert second["confirmed_at"] == confirmed_at
    assert second["confirmed_by"] == "Test Operator"  # original attester, not the 2nd caller


# ── 5. Mid-run concurrent confirm aborts the advisory extraction write ────────

def _make_image_only_pdf(path: Path) -> None:
    fitz = pytest.importorskip("fitz")
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.draw_rect(fitz.Rect(40, 40, 555, 800), color=(0, 0, 0), fill=(0.85, 0.85, 0.85))
    doc.save(str(path))
    doc.close()


def test_extraction_aborts_when_confirmation_lands_mid_run(tmp_path, monkeypatch):
    """A confirm landing AFTER the orchestrator's top read but BEFORE its write must
    not be clobbered. The orchestrator re-reads fresh under the lock and aborts."""
    pytest.importorskip("fitz")
    from app.services import ai_gateway

    out = tmp_path / "outputs" / "B-646"
    (out / "source" / "invoices").mkdir(parents=True)
    audit_path = out / "audit.json"
    # Top-read state: unconfirmed, no engine parse → extraction will proceed.
    audit_path.write_text(json.dumps({"invoice_totals": {}, "rows": []}), encoding="utf-8")
    _make_image_only_pdf(out / "source" / "invoices" / "inv_122.pdf")

    good = json.dumps({
        "supplier": "GLOBAL JEWELLERY LLC", "invoice_no": "INV-122", "currency": "USD",
        "fob_usd": 700.0, "itemization_available": True,
        "line_items": [{"description": "GOLD RING 18K", "quantity": 2, "total": 400}],
        "confidence": 0.88, "source_page": 1,
    })

    monkeypatch.setattr(ai_gateway, "is_available", lambda: True)

    def fake_call_vision(**kwargs):
        # Simulate a concurrent operator confirm landing on disk DURING extraction,
        # i.e. after the orchestrator's initial read and before its guarded write.
        cur = json.loads(audit_path.read_text(encoding="utf-8"))
        cur["vision_invoice"] = {
            "supplier": "OPERATOR ATTESTED", "fob_usd": 700.0,
            "line_items": [{"description": "GOLD RING 18K", "total_usd": 400.0}],
            "operator_confirmed": True, "status": "confirmed",
            "confirmed_by": "Test Operator", "confirmed_at": "2026-06-17T10:00:00Z",
        }
        audit_path.write_text(json.dumps(cur), encoding="utf-8")
        return good

    monkeypatch.setattr(ai_gateway, "call_vision", fake_call_vision)

    res = vision_extractor.run_image_only_invoice_extraction(out, "B-646")
    assert res["wrote"] is False
    assert "operator confirmed" in res["reason"].lower()

    # The operator's confirmation survived — the advisory write did not revert it.
    vi = json.loads(audit_path.read_text(encoding="utf-8"))["vision_invoice"]
    assert vi["operator_confirmed"] is True
    assert vi["supplier"] == "OPERATOR ATTESTED"
    assert vi["confirmed_by"] == "Test Operator"
