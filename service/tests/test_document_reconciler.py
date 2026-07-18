"""test_document_reconciler.py — Campaign-2 A2 Step 1.

Pins the read-only reconciliation authority document_reconciler.build_reconciliation:
exact match, mismatch classification, no-local-authority, determinism, delegation
to the canonical A1 comparator, and a static write-guard (no DB/wFirma/audit writes).

All I/O is injected so no real DB or wFirma call happens.
"""
from __future__ import annotations

import ast
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services import document_reconciler as dr
from app.services import document_comparator as dc
from app.services.document_comparator import compare_invoice_plan
from app.services.proforma_to_invoice import FinalInvoicePlan, LineItem

_MODULE = (Path(__file__).resolve().parent.parent
           / "app" / "services" / "document_reconciler.py")
_FIXED = lambda: datetime(2026, 7, 18, 12, 0, 0, tzinfo=timezone.utc)


# ── builders (mirror the A1 comparator tests) ────────────────────────────────

def _plan(*, contractor_id="9001", currency="EUR", total="306.00", receiver_id=""):
    return FinalInvoicePlan(
        type="normal", contractor_id=contractor_id, currency=currency,
        price_currency_exchange=None, paymentmethod="przelew",
        paymentdate="2026-05-15", date="2026-06-08", description="x",
        series_id="15827921", company_account_id="194483",
        translation_language_id=None,
        contractor_receiver_id=(receiver_id or None),
        contents=[LineItem("RING", "42", "szt.", "1.0000", "306.00", "228")],
        source_proforma_id="467236963", source_proforma_number="PROF 92/2026",
        expected_total=Decimal(total),
    )


def _actual_xml(*, contractor_id="9001", currency="EUR", total="306.00",
                inv_id="500001"):
    return (
        "<api><invoices><invoice>"
        f"<id>{inv_id}</id><type>normal</type>"
        f"<currency>{currency}</currency><total>{total}</total>"
        f"<contractor><id>{contractor_id}</id></contractor>"
        "<invoicecontents><invoicecontent><name>RING</name>"
        "<good><id>42</id></good><unit>szt.</unit>"
        "<unit_count>1.0000</unit_count><price>306.00</price>"
        "<vat_code><id>228</id></vat_code></invoicecontent></invoicecontents>"
        "</invoice></invoices></api>"
    )


def _draft(*, invoice_id="500001"):
    return SimpleNamespace(wfirma_invoice_id=invoice_id,
                           wfirma_proforma_id="467236963", id=1)


def _run(draft, plan, xml, **over):
    kw = dict(
        db_path="UNUSED",
        load_draft=lambda db, i: draft,
        build_expected_plan=lambda d: (plan, "SRCHASH"),
        fetch_actual_xml=lambda iid: xml,
        now=_FIXED,
    )
    kw.update(over)
    return dr.build_reconciliation(1, **kw)


# ── exact match ───────────────────────────────────────────────────────────────

def test_exact_match_reconciled_clean():
    r = _run(_draft(), _plan(), _actual_xml())
    assert r["status"] == "reconciled"
    assert r["reconciliation_available"] is True
    assert r["clean"] is True
    assert r["gaps"] == []
    assert r["gap_summary"]["total"] == 0
    assert r["gap_summary"]["has_blocking"] is False
    assert r["remote_document_id"] == "500001"
    assert r["local_source_hash"] == "SRCHASH"
    assert r["comparison_version"] == dr.COMPARISON_VERSION


# ── mismatch classification ──────────────────────────────────────────────────

def test_mismatch_classified():
    r = _run(_draft(), _plan(contractor_id="9001"), _actual_xml(contractor_id="9999"))
    assert r["status"] == "reconciled"
    assert r["clean"] is False
    assert r["gap_summary"]["total"] >= 1
    g = r["gaps"][0]
    assert g["field"] == "contractor_id"
    assert g["severity"] in {"info", "warning", "critical"}
    assert g["resolution_policy"] in {"none", "local_projection_repair",
                                      "approval_required", "blocked"}
    assert g["evidence_quality"] in {"exact_remote_snapshot",
                                     "current_master_projection", "not_verifiable"}
    assert "contractor mismatch" in g["message"]
    assert r["gap_summary"]["has_blocking"] is True


# ── no local authority ───────────────────────────────────────────────────────

def test_no_local_authority_when_no_invoice_id():
    r = _run(_draft(invoice_id=None), _plan(), _actual_xml())
    assert r["status"] == "no_local_authority"
    assert r["reconciliation_available"] is False
    assert r["gaps"] == []          # never fabricate gaps
    assert "remote_snapshot_hash" not in r


def test_no_local_authority_when_draft_missing():
    r = _run(None, _plan(), _actual_xml(), load_draft=lambda db, i: None)
    assert r["status"] == "no_local_authority"
    assert r["reconciliation_available"] is False


def test_no_local_authority_does_not_build_plan_or_fetch():
    """When there is no local authority, neither the planner nor the actual
    fetch may run (no wFirma read for an ownerless case)."""
    def _boom(*a, **k):
        raise AssertionError("must not be called for no_local_authority")
    r = _run(_draft(invoice_id=None), _plan(), _actual_xml(),
             build_expected_plan=_boom, fetch_actual_xml=_boom)
    assert r["status"] == "no_local_authority"


# ── determinism / idempotency ────────────────────────────────────────────────

def test_deterministic_idempotent_output():
    d, p, x = _draft(), _plan(contractor_id="9001"), _actual_xml(contractor_id="9999")
    r1 = _run(d, p, x)
    r2 = _run(d, p, x)
    assert r1 == r2                                   # fixed clock → fully identical
    # and the stable fields are hash-deterministic regardless of clock
    assert r1["remote_snapshot_hash"] == r2["remote_snapshot_hash"]
    assert r1["local_source_hash"] == r2["local_source_hash"]
    assert [g["message"] for g in r1["gaps"]] == [g["message"] for g in r2["gaps"]]


# ── delegation to the canonical A1 comparator (no second authority) ──────────

def test_delegates_to_canonical_comparator_symbol():
    assert dr.compare_invoice_plan is dc.compare_invoice_plan


def test_gaps_match_canonical_comparator_output():
    plan, xml = _plan(contractor_id="9001"), _actual_xml(contractor_id="9999", currency="USD")
    r = _run(_draft(), plan, xml)
    canonical = compare_invoice_plan(plan, xml)
    assert [g["field"] for g in r["gaps"]] == [g.field for g in canonical.gaps]
    assert [g["message"] for g in r["gaps"]] == [g.message for g in canonical.gaps]


# ── static write-guard: no DB / wFirma / audit / filesystem writes ───────────

def test_write_guard_no_forbidden_io():
    src = _MODULE.read_text(encoding="utf-8")
    forbidden = [
        "INSERT", "UPDATE ", "DELETE FROM", ".execute(", ".executemany(",
        ".commit(", "_http_request", "invoices/add", "invoices/edit",
        "invoices/delete", "log_event", "record_", "mark_", "write_json",
        "write_text", "open(", ".write(", "put(", "post(",
    ]
    hits = [tok for tok in forbidden if tok in src]
    assert not hits, f"document_reconciler.py contains write/IO tokens: {hits}"


def test_write_guard_no_write_calls_ast():
    tree = ast.parse(_MODULE.read_text(encoding="utf-8"))
    bad = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
            if n.func.attr in {"execute", "executemany", "commit", "write",
                               "writelines"}:
                bad.append(n.func.attr)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and \
                n.func.id in {"open", "eval", "exec"}:
            bad.append(n.func.id)
    assert not bad, f"forbidden write/IO call(s): {sorted(set(bad))}"
