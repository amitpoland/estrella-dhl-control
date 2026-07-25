"""test_document_reconciler_2b.py — Campaign-2 · Phase 2B (service unit).

Pins document_reconciler.build_manual_link_preview: the read-only pre-link
preview against an OPERATOR-SPECIFIED remote id. Delegates comparison to the
A1 authority; produces an opaque full-plan drift hash; exposes NO internal ids.

All I/O is injected — no real DB or wFirma call.
"""
from __future__ import annotations

import ast
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from app.services import document_reconciler as dr
from app.services.proforma_to_invoice import FinalInvoicePlan, LineItem

_MODULE = (Path(__file__).resolve().parent.parent
           / "app" / "services" / "document_reconciler.py")
_FIXED = lambda: datetime(2026, 7, 19, 12, 0, 0, tzinfo=timezone.utc)


def _plan(*, contractor_id="9001", currency="EUR", total="306.00",
          series_id="15827921", price="306.00"):
    return FinalInvoicePlan(
        type="normal", contractor_id=contractor_id, currency=currency,
        price_currency_exchange=None, paymentmethod="przelew",
        paymentdate="2026-05-15", date="2026-06-08", description="x",
        series_id=series_id, company_account_id="194483",
        translation_language_id=None, contractor_receiver_id=None,
        contents=[LineItem("RING", "42", "szt.", "1.0000", price, "228")],
        source_proforma_id="467236963", source_proforma_number="PROF 92/2026",
        expected_total=Decimal(total),
    )


def _actual_xml(*, contractor_id="9001", currency="EUR", total="306.00",
                inv_id="500001", price="306.00"):
    return (
        "<api><invoices><invoice>"
        f"<id>{inv_id}</id><type>normal</type>"
        f"<currency>{currency}</currency><total>{total}</total>"
        f"<contractor><id>{contractor_id}</id></contractor>"
        "<invoicecontents><invoicecontent><name>RING</name>"
        "<good><id>42</id></good><unit>szt.</unit>"
        f"<unit_count>1.0000</unit_count><price>{price}</price>"
        "<vat_code><id>228</id></vat_code></invoicecontent></invoicecontents>"
        "</invoice></invoices></api>"
    )


def _draft(*, proforma_id="467236963"):
    return SimpleNamespace(wfirma_proforma_id=proforma_id,
                           wfirma_invoice_id=None, id=1)


def _run(draft, plan, xml, *, remote_id="500001", document_type="invoice", **over):
    kw = dict(
        remote_document_id=remote_id,
        document_type=document_type,
        db_path="UNUSED",
        load_draft=lambda db, i: draft,
        build_expected_plan=lambda d: (plan, "SRCHASH"),
        fetch_actual_xml=lambda rid: xml,
        now=_FIXED,
    )
    kw.update(over)
    return dr.build_manual_link_preview(1, **kw)


# ── happy path ────────────────────────────────────────────────────────────────

def test_preview_clean_match():
    r = _run(_draft(), _plan(), _actual_xml())
    assert r["status"] == "preview_available"
    assert r["reconciliation_available"] is True
    assert r["clean"] is True
    assert r["gaps"] == []
    assert r["comparison_version"] == dr.COMPARISON_VERSION_2B
    assert r["preview_hash"]                       # present + non-empty
    assert r["candidate_summary"]["line_count"] == 1
    assert r["candidate_summary"]["currency"] == "EUR"


def test_preview_forwards_gaps_from_a1():
    r = _run(_draft(), _plan(contractor_id="9001"), _actual_xml(contractor_id="9999"))
    assert r["clean"] is False
    assert r["gap_summary"]["total"] >= 1
    assert r["gaps"][0]["field"] == "contractor_id"


# ── uses the OPERATOR-SPECIFIED remote id, not draft.wfirma_invoice_id ─────────

def test_preview_fetches_the_specified_remote_id():
    seen = {}
    def _fetch(rid):
        seen["rid"] = rid
        return _actual_xml()
    _run(_draft(), _plan(), None, remote_id="777001", fetch_actual_xml=_fetch)
    assert seen["rid"] == "777001"


# ── no local authority (no source proforma) ───────────────────────────────────

def test_no_local_authority_without_proforma():
    def _boom(*a, **k):
        raise AssertionError("must not build/fetch without a source proforma")
    r = _run(_draft(proforma_id=None), _plan(), _actual_xml(),
             build_expected_plan=_boom, fetch_actual_xml=_boom)
    assert r["status"] == "no_local_authority"
    assert r["reconciliation_available"] is False
    assert r["gaps"] == []


def test_no_local_authority_when_draft_absent():
    r = _run(None, _plan(), _actual_xml(), load_draft=lambda db, i: None)
    assert r["status"] == "no_local_authority"


# ── drift hash: covers the FULL plan + the remote snapshot + the remote id ────

def test_preview_hash_stable_for_same_inputs():
    a = _run(_draft(), _plan(), _actual_xml())
    b = _run(_draft(), _plan(), _actual_xml())
    assert a["preview_hash"] == b["preview_hash"]


def test_preview_hash_changes_on_remote_drift():
    a = _run(_draft(), _plan(), _actual_xml(total="306.00"))
    b = _run(_draft(), _plan(), _actual_xml(total="400.00"))
    assert a["preview_hash"] != b["preview_hash"]


def test_preview_hash_changes_on_plan_drift():
    a = _run(_draft(), _plan(series_id="15827921"), _actual_xml())
    b = _run(_draft(), _plan(series_id="99999999"), _actual_xml())
    assert a["preview_hash"] != b["preview_hash"]


def test_preview_hash_changes_on_line_price_drift():
    # W-5: the hash must cover line-level fields, not just a description subset.
    a = _run(_draft(), _plan(price="306.00"), _actual_xml(price="306.00"))
    b = _run(_draft(), _plan(price="310.00"), _actual_xml(price="306.00"))
    assert a["preview_hash"] != b["preview_hash"]


def test_preview_hash_changes_on_remote_id():
    a = _run(_draft(), _plan(), _actual_xml(), remote_id="500001")
    b = _run(_draft(), _plan(), _actual_xml(), remote_id="500002")
    assert a["preview_hash"] != b["preview_hash"]


# ── W-3: no internal ids / raw XML in the candidate summary ───────────────────

def test_candidate_summary_has_no_internal_ids():
    r = _run(_draft(), _plan(), _actual_xml())
    cs = r["candidate_summary"]
    for banned in ("series_id", "company_account_id", "contractor_id",
                   "contractor_receiver_id", "good_id"):
        assert banned not in cs
    assert set(cs.keys()) == {"currency", "expected_total", "line_count"}


# ── delegation + purity static guards ─────────────────────────────────────────

def test_preview_delegates_to_a1_comparator(monkeypatch):
    called = {"n": 0}
    real = dr.compare_invoice_plan
    def _spy(plan, xml):
        called["n"] += 1
        return real(plan, xml)
    monkeypatch.setattr(dr, "compare_invoice_plan", _spy)
    _run(_draft(), _plan(), _actual_xml())
    assert called["n"] == 1          # the sole comparison authority is used


def test_module_has_no_api_import():
    src = _MODULE.read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            mod = getattr(node, "module", "") or ""
            names = " ".join(a.name for a in getattr(node, "names", []))
            assert "routes_" not in mod and "routes_" not in names
            assert not mod.startswith("app.api") and ".api." not in mod


def test_module_never_writes():
    """No DB/wFirma/audit write primitives in the reconciler (read-only)."""
    src = _MODULE.read_text(encoding="utf-8")
    for banned in ("INSERT ", "UPDATE ", "persist_", "record_invoice_identity",
                   "invoices/add", "invoices/edit"):
        assert banned not in src
