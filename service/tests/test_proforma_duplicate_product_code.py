"""
test_proforma_duplicate_product_code.py — duplicate / over-bill product_code guard.

AUTHORITY (rules 1-5, with the data-model correction surfaced during the audit)
-------------------------------------------------------------------------------
A ``product_code`` (invoice_no + line position) identifies one PURCHASE INVOICE
LINE — a lot that legitimately holds several pieces / design_no values. So a
product_code MAY appear on multiple draft lines; that is only a billing-integrity
failure when the TOTAL billed quantity exceeds the available packing quantity
(rule 2: the packing-line quantity is the split authority). An OVER-bill is the
double-bill risk and is the hard blocker (rule 4). Mere duplication WITHIN the
available quantity (a mixed lot — the norm for EJL/26-27/299) is legitimate and
must NOT block, or every real shipment would be wrongly blocked.

`_analyze_product_code_billing` classifies; it never auto-corrects/merges/picks
(rule 5). Pure-function tests — no DB/app fixtures.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from unittest.mock import patch

import pytest

from app.api.routes_proforma import (
    _analyze_product_code_billing,
    _derive_draft_readiness,
)


def _line(pc, design, qty, line_id=None):
    return {"product_code": pc, "design_no": design, "qty": qty, "line_id": line_id}


def _by_pc(entries):
    return {e["product_code"]: e for e in entries}


# ── unique product_codes pass ────────────────────────────────────────────────

def test_unique_product_codes_within_available_pass():
    lines = [_line("A-1", "D1", 1), _line("A-2", "D2", 1)]
    avail = {"A-1": 1, "A-2": 1}
    out = _analyze_product_code_billing(lines, avail)
    assert out == []                      # single-line, not over → nothing surfaced


# ── duplication WITHIN available is legitimate (mixed lot) — no block ─────────

def test_duplicate_same_pc_within_available_is_not_over_billed():
    """Two pieces of one invoice line, both available → surfaced, NOT over-billed."""
    lines = [_line("A-2", "JR04929", 1), _line("A-2", "JR05671", 1)]
    avail = {"A-2": 2}                    # lot has 2 pieces available
    e = _by_pc(_analyze_product_code_billing(lines, avail))["A-2"]
    assert e["over_billed"] is False
    assert e["billed_qty"] == 2 and e["available_qty"] == 2
    assert e["line_count"] == 2


def test_same_pc_different_design_within_available_not_blocked():
    """Different design_no under one product_code is the mixed-lot norm — allowed
    when within available quantity."""
    lines = [_line("A-2", "JR04929", 1), _line("A-2", "J3806R00973", 1)]
    avail = {"A-2": 2}
    e = _by_pc(_analyze_product_code_billing(lines, avail))["A-2"]
    assert e["over_billed"] is False
    assert e["design_nos"] == ["J3806R00973", "JR04929"]


# ── OVER-bill is the hard-blocker case (rule 4) ──────────────────────────────

def test_duplicate_same_pc_same_design_over_available_blocks():
    """Same product_code + same design billed twice but only 1 available → over."""
    lines = [_line("A-9", "JR04929", 1), _line("A-9", "JR04929", 1)]
    avail = {"A-9": 1}
    e = _by_pc(_analyze_product_code_billing(lines, avail))["A-9"]
    assert e["over_billed"] is True
    assert e["billed_qty"] == 2 and e["available_qty"] == 1


def test_duplicate_same_pc_different_design_over_available_blocks():
    lines = [_line("A-2", "JR04929", 1), _line("A-2", "J3806R00973", 1)]
    avail = {"A-2": 1}                    # lot only has 1 piece, but 2 billed
    e = _by_pc(_analyze_product_code_billing(lines, avail))["A-2"]
    assert e["over_billed"] is True


def test_single_line_quantity_exceeds_available_blocks():
    """Over-bill from one line with qty > available (not a duplicate, still over)."""
    lines = [_line("A-5", "D1", 5)]
    avail = {"A-5": 3}
    e = _by_pc(_analyze_product_code_billing(lines, avail))["A-5"]
    assert e["over_billed"] is True and e["billed_qty"] == 5 and e["available_qty"] == 3


def test_split_quantity_allowed_up_to_available_then_blocks_when_exceeded():
    """Split across lines is allowed only up to the available quantity (rule 2)."""
    avail = {"A-10": 3}
    ok = _by_pc(_analyze_product_code_billing(
        [_line("A-10", "D1", 1), _line("A-10", "D2", 2)], avail))["A-10"]
    assert ok["over_billed"] is False     # 3 billed == 3 available
    over = _by_pc(_analyze_product_code_billing(
        [_line("A-10", "D1", 2), _line("A-10", "D2", 2)], avail))["A-10"]
    assert over["over_billed"] is True    # 4 billed > 3 available


# ── evidence + hygiene ───────────────────────────────────────────────────────

def test_finding_carries_line_evidence():
    lines = [_line("A-2", "D1", 1, line_id="6"), _line("A-2", "D2", 1, line_id="7")]
    e = _by_pc(_analyze_product_code_billing(lines, {"A-2": 2}, {"A-2": "EJL/26-27/299"}))["A-2"]
    assert e["invoice_no"] == "EJL/26-27/299"
    assert {l["line_id"] for l in e["lines"]} == {"6", "7"}
    assert {l["idx"] for l in e["lines"]} == {0, 1}


def test_blank_product_code_ignored():
    out = _analyze_product_code_billing([_line("", "D1", 1), _line("", "D2", 1)], {})
    assert out == []


def test_overbilled_entries_listed_first():
    lines = [_line("OK-1", "D1", 1), _line("OK-1", "D2", 1),
             _line("BAD-1", "D3", 2), _line("BAD-1", "D4", 2)]
    out = _analyze_product_code_billing(lines, {"OK-1": 2, "BAD-1": 1})
    assert out[0]["product_code"] == "BAD-1" and out[0]["over_billed"] is True


# ── the real EJL/26-27/299 Draft #34 mixed lots — every lot within available ──

def test_ejl299_draft34_mixed_lots_no_over_bill():
    """The 5 duplicated product_codes on Draft #34 each bill exactly their
    available packing quantity → all surfaced, NONE over-billed → 0 blockers."""
    lines = (
        [_line("EJL/26-27/299-6", d, 1) for d in ("JP02298", "JP02890")] +
        [_line("EJL/26-27/299-9", d, 1) for d in ("JR04929", "JR04832", "JR04929")]
    )
    avail = {"EJL/26-27/299-6": 2, "EJL/26-27/299-9": 3}   # = available packing qty
    out = _analyze_product_code_billing(lines, avail)
    assert all(not e["over_billed"] for e in out)
    assert {e["product_code"] for e in out} == {"EJL/26-27/299-6", "EJL/26-27/299-9"}


# ── FAIL-CLOSED: over-bill guard must block when packing data is unreadable ───
#
# Regression for the fail-OPEN hole. Section 5 of `_derive_draft_readiness`
# reads packing quantities (via a packing read it owns) to decide over-bill.
# If that read fails (DB locked / unavailable / transient) the over-bill check
# CANNOT evaluate. The guard must then fail CLOSED — add a precautionary blocker
# so approve/post/convert is gated — not degrade to a warning the operator never
# sees (warnings render in the UI only when !ready). This mirrors the preview /
# VAT derivation failures in the same function, which already `_add(...)` on
# exception. (The read is owned by section 5 precisely so an unreadable DB
# surfaces as a failure here, rather than being swallowed into an empty
# authority snapshot that would mislabel every line as "0 available → over".)

_BATCH      = "BATCH_OVERBILL_FAILCLOSED"
_CLIENT     = "OVERBILL_FAILCLOSED_CLIENT"
_PRECAUTION = "over-bill guard could not evaluate"
# Patch the function on its ORIGIN module. Section 5 of `_derive_draft_readiness`
# does a local `from ..services import packing_db as _pkdb` and then calls
# `_pkdb.get_packing_lines_for_batch(...)` — attribute access on the module
# object at call time — so patching the attribute on `app.services.packing_db`
# is the correct target. If that local import is ever changed to bind the
# function name directly, this target must move to the routes module.
_PKDB_FN    = "app.services.packing_db.get_packing_lines_for_batch"


@pytest.fixture()
def storage(tmp_path):
    """Minimal storage root with every DB the readiness gate touches, plus the
    batch audit.json so the (unrelated) preview gates degrade gracefully."""
    from app.services import packing_db as pdb
    from app.services import document_db as ddb
    from app.services import wfirma_db as wfdb
    from app.services import proforma_invoice_link_db as pildb

    pdb.init_packing_db(tmp_path / "packing.db")
    ddb.init_document_db(tmp_path / "documents.db")
    wfdb.init_wfirma_db(tmp_path / "wfirma.db")
    pildb.init_db(tmp_path / "proforma_links.db")

    out = tmp_path / "outputs" / _BATCH / "source"
    out.mkdir(parents=True, exist_ok=True)
    (tmp_path / "outputs" / _BATCH / "audit.json").write_text(
        json.dumps({"batch_id": _BATCH, "tracking_no": _BATCH, "awb": _BATCH,
                    "carrier": "DHL", "timeline": []}),
        encoding="utf-8")
    return tmp_path


def _seed_overbilled_draft(storage) -> int:
    """A draft billing 5 pcs of product_code OVR-1 (an over-bill against any
    packing quantity < 5). The qty is what `_analyze_product_code_billing`
    sums, so the draft *would* over-bill if packing were readable."""
    db = storage / "proforma_links.db"
    line = {"line_id": str(uuid.uuid4()), "product_code": "OVR-1",
            "design_no": "D1", "name_pl": "Pierścionek złoty",
            "unit_price": 100.0, "qty": 5.0, "quantity": 5.0, "currency": "EUR"}
    with sqlite3.connect(str(db)) as conn:
        cur = conn.execute(
            """INSERT INTO proforma_drafts
                 (batch_id, client_name, status, currency, draft_state,
                  wfirma_proforma_id, wfirma_proforma_fullnumber,
                  source_lines_json, editable_lines_json, service_charges_json,
                  clone_generation, draft_version, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'),datetime('now'))""",
            (_BATCH, _CLIENT, "draft", "EUR", "draft", None, "",
             "[]", json.dumps([line]), "[]", 0, 1),
        )
        conn.commit()
        return cur.lastrowid


def _readiness(storage, draft_id: int, *, intent: str = "approve"):
    from app.core.config import settings
    from app.services import proforma_invoice_link_db as pildb
    with patch.object(settings, "storage_root", storage):
        draft = pildb.get_draft_by_id(storage / "proforma_links.db", draft_id)
        assert draft is not None
        return _derive_draft_readiness(draft, intent=intent)


@pytest.mark.parametrize("intent", ["approve", "post", "convert"])
def test_overbill_guard_fails_closed_when_packing_unreadable(storage, intent):
    """Packing read raises → readiness FAILS CLOSED: a precautionary blocker is
    added (not merely a warning) so the lifecycle write is gated even though the
    guard could not compute the over-bill. Pinned for ALL three write intents —
    section 5 is intent-independent and the production defect (an over-billed
    draft approved, then POSTED) materialises on post/convert, not just approve."""
    draft_id = _seed_overbilled_draft(storage)

    def _boom(_batch):
        raise sqlite3.OperationalError("database is locked")

    with patch(_PKDB_FN, _boom):
        result = _readiness(storage, draft_id, intent=intent)

    # Fail-closed: blocked, and the precautionary blocker is present…
    assert result["ready"] is False, result
    prec = [b for b in result["blockers"] if _PRECAUTION in b["reason"]]
    assert prec, result["blockers"]
    # …as a BLOCKER, not merely a warning the operator never sees.
    assert any(_PRECAUTION in r for r in result["blocking_reasons"]), result
    assert not any(_PRECAUTION in w for w in result["warnings"]), result["warnings"]
    # Every blocker carries an exact repair action (Lesson M).
    assert prec[0]["repair_action"].strip()
    # The guard genuinely could not classify (no structured over-bill data) and
    # did NOT mislabel the failure as a real "0 available → over-billed" verdict.
    assert result["duplicate_product_codes"] == [], result["duplicate_product_codes"]
    assert not any("but only" in r and "over-billed across" in r
                   for r in result["blocking_reasons"]), result["blocking_reasons"]
    # The diagnostic warning is still emitted for the audit trail.
    assert any("duplicate product_code guard unavailable" in w
               for w in result["warnings"]), result["warnings"]


def test_overbill_guard_uses_real_blocker_when_packing_readable(storage):
    """Contrast: when packing IS readable the precautionary blocker must NOT
    appear — the precaution is specific to the unreadable-packing failure path,
    so it cannot over-block. A genuine over-bill instead surfaces the real
    over-bill blocker computed from live packing quantities."""
    draft_id = _seed_overbilled_draft(storage)

    def _ok(_batch):
        # 3 available but the draft bills 5 → genuine, live-computed over-bill.
        return [{"product_code": "OVR-1", "design_no": "D1",
                 "quantity": 3.0, "invoice_no": "INV/OVR"}]

    with patch(_PKDB_FN, _ok):
        result = _readiness(storage, draft_id, intent="approve")

    # The precautionary (could-not-evaluate) blocker must be ABSENT.
    assert not any(_PRECAUTION in r for r in result["blocking_reasons"]), result
    # The real over-bill blocker is present, computed from live packing qty.
    assert any("but only" in r and "over-billed across" in r
               for r in result["blocking_reasons"]), result["blocking_reasons"]
    by_pc = {d["product_code"]: d for d in result["duplicate_product_codes"]}
    assert by_pc.get("OVR-1", {}).get("over_billed") is True, \
        result["duplicate_product_codes"]
