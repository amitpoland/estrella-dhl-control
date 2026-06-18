"""
test_vision_invoice_confirm.py — PR-2 operator confirmation workflow.

Pins ``vision_extractor.confirm_vision_invoice`` — the SOLE writer of
``operator_confirmed=true`` on ``audit["vision_invoice"]``. The machine extractor
(``_merge_vision_invoice`` / ``run_image_only_invoice_extraction``) only ever
writes ``operator_confirmed=false`` and is sticky against this flag; this module
proves the confirmation gate and its authority isolation:

  1. Confirm is the sole promotion path — no proposal ⇒ cannot confirm (409).
  2. operator_confirmed=true is written ONLY by confirm; lineage + snapshot kept.
  3. CIF / layer-3 accounting authority is byte-identical after confirm.
  4. A machine recheck CANNOT overwrite a confirmed proposal (sticky invariance).
  5. Supplier cross-validation is advisory (matched / unmatched), never blocks.
  6. wFirma / PZ stay blocked after confirm — confirmation alone creates no rows.

No AI / network — confirm reads an existing proposal, never re-extracts.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_SVC = Path(__file__).parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

from app.services import vision_extractor
from app.services import suppliers_db


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _proposal(**over) -> dict:
    """A realistic machine-written (operator_confirmed=false) proposal block."""
    vi = {
        "operator_confirmed": False,
        "status": "proposed",
        "source": "vision_llm",
        "supplier": "GLOBAL JEWELLERY LLC",
        "invoice_no": "INV-122",
        "currency": "USD",
        "fob_usd": 607.0,
        "confidence": 0.88,
        "extracted_at": "2026-06-17T00:00:00Z",
        "source_file": "inv_122.pdf",
        "source_page": 1,
        "line_items": [
            {"description": "GOLD RING 18K", "hsn": "71131900", "quantity": 2, "total_usd": 400.0},
            {"description": "GOLD PENDANT", "hsn": "71131900", "quantity": 1, "total_usd": 207.0},
        ],
        "itemization_unavailable": False,
    }
    vi.update(over)
    return vi


def _batch(tmp_path: Path, audit: dict) -> Path:
    out = tmp_path / "batch"
    (out / "source" / "invoices").mkdir(parents=True)
    (out / "audit.json").write_text(json.dumps(audit), encoding="utf-8")
    return out


def _read(out: Path) -> dict:
    return json.loads((out / "audit.json").read_text(encoding="utf-8"))


# ══════════════════════════════════════════════════════════════════════════════
# 1. Confirm is the sole promotion path
# ══════════════════════════════════════════════════════════════════════════════

def test_cannot_confirm_without_a_proposal(tmp_path):
    """No vision_invoice (or a ledger-only shell) ⇒ nothing to confirm (→ 409)."""
    out = _batch(tmp_path, {"rows": [], "invoice_totals": {}})
    res = vision_extractor.confirm_vision_invoice(out, "B1", confirmed_by="amit")
    assert res["ok"] is False
    assert res["reason"] == "no_proposal"
    assert "vision_invoice" not in _read(out)  # nothing minted


def test_ledger_only_block_is_not_a_proposal(tmp_path):
    """A block carrying only run history (no supplier/FOB/items) is not confirmable —
    confirming it would forge an operator_confirmed=true over empty content."""
    out = _batch(tmp_path, {"vision_invoice": {"operator_confirmed": False,
                                               "runs": [{"ts": "x"}],
                                               "attempted_signatures": {"a.pdf": "1"}}})
    res = vision_extractor.confirm_vision_invoice(out, "B1", confirmed_by="amit")
    assert res["ok"] is False and res["reason"] == "no_proposal"
    assert _read(out)["vision_invoice"]["operator_confirmed"] is False


def test_missing_operator_identity_is_rejected(tmp_path):
    out = _batch(tmp_path, {"vision_invoice": _proposal()})
    res = vision_extractor.confirm_vision_invoice(out, "B1", confirmed_by="   ")
    assert res["ok"] is False and res["reason"] == "missing_operator_identity"
    assert _read(out)["vision_invoice"]["operator_confirmed"] is False  # untouched


# ══════════════════════════════════════════════════════════════════════════════
# 2. operator_confirmed=true written ONLY by confirm; lineage + snapshot kept
# ══════════════════════════════════════════════════════════════════════════════

def test_confirm_promotes_and_records_lineage(tmp_path):
    out = _batch(tmp_path, {"vision_invoice": _proposal()})
    res = vision_extractor.confirm_vision_invoice(out, "B1", confirmed_by="Amit Operator")
    assert res["ok"] is True and res["operator_confirmed"] is True

    vi = _read(out)["vision_invoice"]
    assert vi["operator_confirmed"] is True
    assert vi["status"] == "confirmed"
    assert vi["source"] == "vision_llm"          # source preserved
    assert vi["confirmed_by"] == "Amit Operator"
    assert vi["confirmed_at"].endswith("Z")
    # Original machine values snapshotted for audit (confidence + extracted values).
    snap = vi["machine_original"]
    assert snap["confidence"] == 0.88
    assert snap["fob_usd"] == 607.0
    assert snap["supplier"] == "GLOBAL JEWELLERY LLC"
    assert len(snap["line_items"]) == 2


def test_machine_extractor_never_sets_operator_confirmed_true(tmp_path):
    """Source contract: the machine writer only ever produces operator_confirmed=false.
    The flag turning true is exclusively the confirm endpoint's job."""
    audit = {}
    clean = {"supplier": "X", "fob_usd": 500.0, "currency": "USD",
             "line_items": [], "itemization_unavailable": True, "confidence": 0.8}
    prov = {"extraction_method": "vision_llm", "model_attempt": "primary",
            "extraction_confidence": 0.8, "source_file": "x.pdf",
            "source_reason": "t", "validation_errors": [], "fields": clean}
    wrote = vision_extractor._merge_vision_invoice(audit, clean, prov)
    assert wrote is True
    assert audit["vision_invoice"]["operator_confirmed"] is False
    assert audit["vision_invoice"]["status"] == "proposed"


# ══════════════════════════════════════════════════════════════════════════════
# 3. CIF / layer-3 accounting authority byte-identical after confirm
# ══════════════════════════════════════════════════════════════════════════════

def test_confirm_does_not_touch_cif_or_layer3(tmp_path):
    audit = {
        "vision_invoice": _proposal(),
        "invoice_totals": {"total_fob_usd": 0, "total_cif_usd": 0},
        "rows": [],
        "awb_customs": {"value_usd": 732.0, "currency": "USD"},
        "clearance_decision": {"clearance_path": "self", "total_value_usd": 732.0},
        "customs_declaration": {"sad_invoice_value_usd": 732.0, "cn_code": "71131900"},
    }
    out = _batch(tmp_path, audit)
    before = _read(out)

    res = vision_extractor.confirm_vision_invoice(out, "B1", confirmed_by="amit")
    assert res["ok"] is True
    after = _read(out)

    for key in ("invoice_totals", "rows", "awb_customs",
                "clearance_decision", "customs_declaration"):
        assert after[key] == before[key], f"{key} must be byte-identical after confirm"


# ══════════════════════════════════════════════════════════════════════════════
# 4. Sticky invariance + idempotency
# ══════════════════════════════════════════════════════════════════════════════

def test_confirm_is_idempotent(tmp_path):
    out = _batch(tmp_path, {"vision_invoice": _proposal()})
    r1 = vision_extractor.confirm_vision_invoice(out, "B1", confirmed_by="amit")
    assert r1["ok"] is True and not r1.get("already_confirmed")
    first_at = _read(out)["vision_invoice"]["confirmed_at"]

    r2 = vision_extractor.confirm_vision_invoice(out, "B1", confirmed_by="someone-else")
    assert r2["ok"] is True and r2.get("already_confirmed") is True
    vi = _read(out)["vision_invoice"]
    assert vi["confirmed_by"] == "amit"          # original attestor preserved
    assert vi["confirmed_at"] == first_at        # not re-stamped


def test_machine_recheck_cannot_overwrite_confirmed(tmp_path, monkeypatch):
    """After confirm, a machine extraction run is a sticky no-op — it neither
    re-extracts nor reverts the operator-attested block."""
    out = _batch(tmp_path, {"vision_invoice": _proposal(),
                            "invoice_totals": {}, "rows": []})
    vision_extractor.confirm_vision_invoice(out, "B1", confirmed_by="amit")

    # Make a real image-only PDF present so the only thing stopping a write is the
    # operator_confirmed sticky guard, not the absence of candidates.
    (out / "source" / "invoices" / "inv_122.pdf").write_bytes(b"%PDF-1.4 fake")

    res = vision_extractor.run_image_only_invoice_extraction(out, "B1")
    assert res["ran"] is False
    assert "operator_confirmed" in res["reason"]

    vi = _read(out)["vision_invoice"]
    assert vi["operator_confirmed"] is True
    assert vi["confirmed_by"] == "amit"
    assert vi["fob_usd"] == 607.0


def test_merge_is_sticky_after_confirm(tmp_path):
    """Direct _merge_vision_invoice call against a confirmed block refuses to write."""
    out = _batch(tmp_path, {"vision_invoice": _proposal()})
    vision_extractor.confirm_vision_invoice(out, "B1", confirmed_by="amit")
    audit = _read(out)
    clean = {"supplier": "MACHINE WOULD-OVERWRITE", "fob_usd": 999.0,
             "currency": "USD", "line_items": [], "confidence": 0.95}
    prov = {"extraction_method": "vision_llm", "model_attempt": "primary",
            "extraction_confidence": 0.95, "source_file": "x.pdf",
            "source_reason": "t", "validation_errors": [], "fields": clean}
    wrote = vision_extractor._merge_vision_invoice(audit, clean, prov)
    assert wrote is False
    assert audit["vision_invoice"]["supplier"] == "GLOBAL JEWELLERY LLC"


# ══════════════════════════════════════════════════════════════════════════════
# 5. Supplier cross-validation — advisory, never blocks
# ══════════════════════════════════════════════════════════════════════════════

def test_supplier_crosscheck_matches_known_supplier(tmp_path):
    db = tmp_path / "suppliers.sqlite"
    suppliers_db.create_supplier(db, {
        "supplier_code": "GJ", "name": "Global Jewellery LLC",
        "country": "IN", "wfirma_id": "555111",
    })
    out = _batch(tmp_path, {"vision_invoice": _proposal()})
    res = vision_extractor.confirm_vision_invoice(
        out, "B1", confirmed_by="amit", suppliers_db_path=db)
    assert res["ok"] is True
    cc = res["supplier_crosscheck"]
    assert cc["checked"] is True and cc["matched"] is True
    assert cc["wfirma_id"] == "555111"
    # Stored advisory on the block too.
    assert _read(out)["vision_invoice"]["supplier_crosscheck"]["matched"] is True


def test_supplier_crosscheck_unmatched_does_not_block(tmp_path):
    db = tmp_path / "suppliers.sqlite"
    suppliers_db.init_db(db)  # empty master
    out = _batch(tmp_path, {"vision_invoice": _proposal()})
    res = vision_extractor.confirm_vision_invoice(
        out, "B1", confirmed_by="amit", suppliers_db_path=db)
    assert res["ok"] is True                       # confirm still succeeds
    assert res["operator_confirmed"] is True
    cc = res["supplier_crosscheck"]
    assert cc["checked"] is True and cc["matched"] is False
    assert cc["wfirma_id"] is None


# ══════════════════════════════════════════════════════════════════════════════
# 6. wFirma / PZ stay blocked after confirm (confirmation creates no rows)
# ══════════════════════════════════════════════════════════════════════════════

def test_confirm_creates_no_rows_pz_stays_blocked(tmp_path):
    """Honest remaining-blocker: confirming the proposal does NOT produce engine
    rows / pz_rows.json. PZ + wFirma remain blocked until the gated injection
    path ships — exactly the runbook Stage B state."""
    out = _batch(tmp_path, {"vision_invoice": _proposal(), "rows": [],
                            "invoice_totals": {}})
    vision_extractor.confirm_vision_invoice(out, "B1", confirmed_by="amit")
    after = _read(out)
    assert after["rows"] == []                       # no engine rows minted
    assert not (out / "pz_rows.json").exists()        # no PZ input produced
    assert "invoice_totals" in after and not after["invoice_totals"].get("total_fob_usd")
