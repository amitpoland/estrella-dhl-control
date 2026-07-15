"""test_proforma_commercial_charge_authority.py — PR-6 (resolution-state model).

The ONE CommercialChargeAuthority resolves the freight + insurance subtotal from
the persisted draft snapshot (``service_charges_json``), honouring the operator's
EXPLICIT resolution. A zero amount is a valid commercial decision — never
automatically an error, never inferred from the amount, never recomputed at read.

Resolution states: calculated / manual_amount / customer_courier / waived /
not_applicable / unresolved.

Matrix:
  R-01  one premium formula (write-time only), cents-quantised
  R-02  same-currency freight + insurance sum to the subtotal
  R-03  cross-currency charge surfaced, NEVER converted or summed
  R-04  customer_courier with amount 0 is VALID + non-blocking (not unresolved)
  R-05  manually confirmed amount 0 is VALID
  R-06  waived / not_applicable zero is VALID
  R-07  ambiguous legacy zero (evidence, no resolution) is UNRESOLVED + excluded
  R-08  NO read-time recomputation — a saved zero stays zero even with evidence
  R-09  live Customer Master change does not alter a confirmed zero (authority is pure)
  R-10  writer persists resolution; add + update; invalid rejected
  R-11  Calculate action stamps resolution='calculated' + freezes evidence
  R-12  preview, wFirma and finance consume the SAME snapshot amount + resolution
  R-13  customs / cif untouched (source-grep)
  R-14  no second premium formula in services (source-grep)
  R-15  UI + preview read the authority, not an independent re-sum (source-grep)
"""
from __future__ import annotations

import json
import pathlib
import re
import sqlite3
from decimal import Decimal

import pytest

from app.services import commercial_charge_authority as cca
from app.services import customer_master as cm
from app.services import proforma_invoice_link_db as pildb

SERVICE_ROOT = pathlib.Path(__file__).resolve().parents[1]
SERVICES_DIR = SERVICE_ROOT / "app" / "services"
API_DIR = SERVICE_ROOT / "app" / "api"
STATIC_V2 = SERVICE_ROOT / "app" / "static" / "v2"


def _sub(charges, ccy="USD"):
    return cca.resolve_commercial_charges(ccy, charges)


# ── R-01 ─────────────────────────────────────────────────────────────────────
def test_one_premium_formula():
    assert cca.insurance_premium(1000, "0.0035", 5) == Decimal("5.00")
    assert cca.insurance_premium(2000, "0.0035", 5) == Decimal("7.00")
    assert cca.insurance_premium(1000, "0.0035") == Decimal("3.50")


# ── R-02 ─────────────────────────────────────────────────────────────────────
def test_same_currency_sum():
    r = _sub([
        {"charge_type": "freight", "amount": 100, "currency": "USD", "resolution": "manual_amount"},
        {"charge_type": "insurance", "amount": 18.79, "currency": "USD", "resolution": "calculated"},
    ])
    assert r["freight_total"] == 100.0
    assert r["insurance_total"] == 18.79
    assert r["service_charge_subtotal"] == 118.79
    assert r["unresolved_charges"] == []


# ── R-03 ─────────────────────────────────────────────────────────────────────
def test_cross_currency_surfaced_not_summed():
    r = _sub([
        {"charge_type": "freight", "amount": 100, "currency": "USD", "resolution": "manual_amount"},
        {"charge_type": "freight", "amount": 50, "currency": "PLN", "resolution": "manual_amount"},
    ])
    assert r["freight_total"] == 100.0
    assert r["service_charge_subtotal"] == 100.0
    assert len(r["cross_currency_charges"]) == 1
    assert r["cross_currency_charges"][0]["currency"] == "PLN"


# ── R-04 : customer_courier zero is valid + non-blocking ──────────────────────
def test_customer_courier_zero_is_valid():
    r = _sub([{"charge_type": "freight", "amount": 0, "currency": "USD",
               "resolution": "customer_courier"}])
    assert r["freight_total"] == 0.0
    assert r["unresolved_charges"] == []               # NOT unresolved
    rec = r["charges"][0]
    assert rec["billable"] is True and rec["resolution"] == "customer_courier"


# ── R-05 : manual zero is valid ───────────────────────────────────────────────
def test_manual_zero_is_valid():
    r = _sub([{"charge_type": "insurance", "amount": 0, "currency": "USD",
               "resolution": "manual_amount"}])
    assert r["insurance_total"] == 0.0
    assert r["unresolved_charges"] == []
    assert r["charges"][0]["billable"] is True


# ── R-06 : waived / not_applicable zero is valid ──────────────────────────────
@pytest.mark.parametrize("res", ["waived", "not_applicable"])
def test_waived_or_na_zero_is_valid(res):
    r = _sub([{"charge_type": "insurance", "amount": 0, "currency": "USD", "resolution": res}])
    assert r["insurance_total"] == 0.0
    assert r["unresolved_charges"] == []
    assert r["charges"][0]["resolution"] == res


# ── R-07 : ambiguous legacy zero is unresolved + excluded ─────────────────────
def test_ambiguous_legacy_zero_is_unresolved():
    r = _sub([{"charge_type": "insurance", "amount": 0, "currency": "USD",
               "formula_basis": {"rate_pct": "0.35", "sales_total": "1000"}}])
    assert r["insurance_total"] == 0.0                  # excluded from billable
    assert len(r["unresolved_charges"]) == 1
    assert r["unresolved_charges"][0]["charge_type"] == "insurance"


# ── R-08 : NO read-time recomputation ─────────────────────────────────────────
def test_no_read_time_recomputation():
    # calculated + amount 0 + full formula evidence → stays 0 (never recomputed).
    r = _sub([{"charge_type": "insurance", "amount": 0, "currency": "USD",
               "resolution": "calculated",
               "formula_basis": {"rate_pct": "0.35", "sales_total": "1000", "minimum_eur": "5"}}])
    assert r["insurance_total"] == 0.0
    assert r["unresolved_charges"] == []                # explicit calculated, not unresolved


# ── R-09 : live CM change cannot alter a confirmed zero ───────────────────────
def test_live_cm_change_does_not_alter_confirmed_zero():
    charge = {"charge_type": "insurance", "amount": 0, "currency": "USD",
              "resolution": "customer_courier"}
    before = _sub([dict(charge)])["insurance_total"]
    after = _sub([dict(charge)])["insurance_total"]
    assert before == after == 0.0
    # The resolver takes no Customer Master argument at all — structurally pure.
    import inspect
    params = inspect.signature(cca.resolve_commercial_charges).parameters
    assert set(params) == {"draft_currency", "service_charges"}


# ── writer fixtures ───────────────────────────────────────────────────────────
def _make_draft(tmp_path, currency="USD", charges_json="[]"):
    db = tmp_path / "proforma_links.sqlite3"
    draft, created = pildb.upsert_pending_draft(
        db, batch_id="SHIP_R", client_name="Test Client", currency=currency,
        exchange_rate=1.0, source_lines_json="[]", service_charges_json=charges_json)
    assert created
    with sqlite3.connect(str(db)) as conn:
        conn.execute("UPDATE proforma_drafts SET draft_state='draft', status='draft' WHERE id=?",
                     (draft.id,))
        conn.commit()
    return db, pildb.get_draft_by_id(db, draft.id)


def _charges(draft):
    return json.loads(draft.service_charges_json or "[]")


# ── R-10 : writer persists resolution; add + update; invalid rejected ─────────
def test_writer_persists_resolution(tmp_path):
    db, draft = _make_draft(tmp_path)
    out = pildb.add_draft_service_charge(
        db, draft.id, {"charge_type": "freight", "amount": 0, "currency": "USD",
                       "resolution": "customer_courier"},
        operator="op", expected_updated_at=draft.updated_at)
    c = _charges(out)[0]
    assert c["amount"] == 0.0 and c["resolution"] == "customer_courier"
    out2 = pildb.update_draft_service_charge(
        db, draft.id, c["charge_id"], {"resolution": "waived"},
        operator="op", expected_updated_at=out.updated_at)
    assert _charges(out2)[0]["resolution"] == "waived"
    with pytest.raises(ValueError):
        pildb.update_draft_service_charge(
            db, draft.id, c["charge_id"], {"resolution": "bogus"},
            operator="op", expected_updated_at=out2.updated_at)


# ── R-11 : Calculate action stamps 'calculated' + freezes evidence ────────────
def test_calculate_stamps_calculated_and_freezes(tmp_path):
    db, draft = _make_draft(tmp_path, "EUR")
    out = pildb.apply_customer_commercial_to_draft(
        db, draft.id, "Test Client", "C1",
        {"insurance_amount": 7.50,
         "insurance_formula_basis": {"sales_total": "1000", "rate_pct": "0.75"}},
        operator="op", expected_updated_at=draft.updated_at)
    ins = [c for c in _charges(out) if c["charge_type"] == "insurance"][0]
    assert ins["amount"] == 7.50
    assert ins["resolution"] == "calculated"
    assert ins["formula_basis"]["rate_pct"] == "0.75"


# ── R-12 : preview / wFirma / finance consume the same snapshot ───────────────
def test_all_consumers_agree(monkeypatch):
    """wFirma line builder and finance dual-write bill exactly the authority's
    same-currency billable subtotal — resolved-zeros and unresolved excluded."""
    from app.api import routes_proforma as rp
    from app.services import finance_dual_write as fdw

    snapshot = [
        {"charge_type": "freight", "amount": 100.0, "currency": "USD", "resolution": "manual_amount"},
        {"charge_type": "insurance", "amount": 0.0, "currency": "USD", "resolution": "waived"},
    ]
    authority = cca.resolve_commercial_charges("USD", snapshot)
    assert authority["service_charge_subtotal"] == 100.0

    # wFirma lines — stub the product mapping so mapped charges emit lines.
    monkeypatch.setattr(rp, "_c1f_mirror_good_id", lambda ct: "999")
    lines, _note = rp._build_service_charge_lines(snapshot, "USD")
    wfirma_total = sum(float(l.unit_price) for l in lines)
    assert wfirma_total == authority["service_charge_subtotal"]  # 100.0, waived-0 excluded

    # finance dual-write — issued_total_minor sums the same billable amounts.
    payload = fdw._build_payload(
        batch_id="B", client_name="C", currency="USD", full_number="PF/1",
        service_charges_json=json.dumps(snapshot))
    assert payload.issued_total_minor == int(round(authority["service_charge_subtotal"] * 100))


def test_unresolved_excluded_by_all_consumers(monkeypatch):
    """An ambiguous legacy zero (unresolved) is excluded from the authority
    subtotal AND from the wFirma lines AND from finance — no silent billing."""
    from app.api import routes_proforma as rp
    from app.services import finance_dual_write as fdw

    snapshot = [
        {"charge_type": "freight", "amount": 100.0, "currency": "USD", "resolution": "manual_amount"},
        {"charge_type": "insurance", "amount": 0.0, "currency": "USD",
         "resolution": "unresolved",
         "formula_basis": {"rate_pct": "0.35", "sales_total": "1000"}},
    ]
    authority = cca.resolve_commercial_charges("USD", snapshot)
    assert authority["service_charge_subtotal"] == 100.0
    assert len(authority["unresolved_charges"]) == 1

    monkeypatch.setattr(rp, "_c1f_mirror_good_id", lambda ct: "999")
    lines, note = rp._build_service_charge_lines(snapshot, "USD")
    assert sum(float(l.unit_price) for l in lines) == 100.0   # unresolved excluded
    assert "unresolved" in note                                # and surfaced in the note

    payload = fdw._build_payload(
        batch_id="B", client_name="C", currency="USD", full_number="PF/1",
        service_charges_json=json.dumps(snapshot))
    assert payload.issued_total_minor == 10000


# ── R-13 : customs separation ─────────────────────────────────────────────────
def test_customs_cif_not_coupled():
    src = (SERVICES_DIR / "commercial_charge_authority.py").read_text(encoding="utf-8")
    body = re.sub(r'^""".*?"""', "", src, count=1, flags=re.DOTALL)
    for f in ("import cif_resolver", "from .cif_resolver", "cif_resolver.",
              "customs_valuation", "cif_resolver("):
        assert f not in body, f"commercial authority must stay decoupled from customs ({f})"


# ── R-14 : one premium formula in services ────────────────────────────────────
def test_no_second_premium_formula():
    pat = re.compile(r"max\(\s*[\w.]*sales[\w.]*\s*\*\s*[\w.]*rate", re.IGNORECASE)
    offenders = [p.name for p in SERVICES_DIR.glob("*.py")
                 if p.name != "commercial_charge_authority.py"
                 and pat.search(p.read_text(encoding="utf-8"))]
    assert not offenders, f"second premium formula in: {offenders}"


# ── R-15 : UI + preview read the authority ────────────────────────────────────
def test_ui_and_preview_read_authority():
    jsx = (STATIC_V2 / "proforma-detail.jsx").read_text(encoding="utf-8")
    assert "commercial_charges" in jsx
    assert "liveDraft.service_charges || []).reduce" not in jsx
    doc = (STATIC_V2 / "estrella-doc-proforma.jsx").read_text(encoding="utf-8")
    assert "charges_total" in doc
    routes = (API_DIR / "routes_proforma.py").read_text(encoding="utf-8")
    assert '_snap_cc["service_charge_subtotal"]' in routes
    assert "_from_snapshot" in routes
    assert "RESOLUTION_UNRESOLVED" in routes


# ── R-16 : resolution endpoint upserts via the existing writer (end-to-end) ───
def test_resolution_endpoint_upserts(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app.core.config import settings
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    from app.main import app

    db_path = tmp_path / "proforma_links.db"
    pildb.init_db(db_path)
    draft, _ = pildb.upsert_pending_draft(
        db_path, batch_id="B-RES", client_name="TC", currency="USD",
        exchange_rate=None, source_lines_json="[]", service_charges_json="[]")
    with sqlite3.connect(str(db_path)) as con:
        con.execute("UPDATE proforma_drafts SET draft_state='draft', status='draft' WHERE id=?",
                    (draft.id,))
        con.commit()
    fresh = pildb.get_draft_by_id(db_path, draft.id)
    headers = {"X-API-KEY": settings.api_key or "test-key", "X-Operator": "alice"}

    with TestClient(app, raise_server_exceptions=True) as c:
        # No freight charge exists yet → the endpoint CREATES one carrying the
        # explicit 'client provides courier' decision (amount 0, valid).
        r = c.post(
            f"/api/v1/proforma/draft/{draft.id}/service-charge-resolution",
            json={"expected_updated_at": fresh.updated_at,
                  "charge_type": "freight", "resolution": "customer_courier"},
            headers=headers)
        assert r.status_code == 200, r.text
        # 'calculated' may NOT be set through this endpoint.
        d2 = pildb.get_draft_by_id(db_path, draft.id)
        r2 = c.post(
            f"/api/v1/proforma/draft/{draft.id}/service-charge-resolution",
            json={"expected_updated_at": d2.updated_at,
                  "charge_type": "insurance", "resolution": "calculated"},
            headers=headers)
        assert r2.status_code == 400

    charges = json.loads(pildb.get_draft_by_id(db_path, draft.id).service_charges_json)
    fr = [c for c in charges if c["charge_type"] == "freight"][0]
    assert fr["amount"] == 0.0 and fr["resolution"] == "customer_courier"
    res = cca.resolve_commercial_charges("USD", charges)
    assert res["freight_total"] == 0.0 and res["unresolved_charges"] == []


# ── R-17 : finance dual-write excludes an unresolved charge (review Fix A) ─────
def test_finance_skips_unresolved_even_with_stale_amount():
    """A charge reconsidered as 'unresolved' keeps a stale amount on the row; the
    wFirma document skips it, so finance must skip it too (no divergence)."""
    from app.services import finance_dual_write as fdw
    snapshot = [
        {"charge_type": "freight", "amount": 100.0, "currency": "USD", "resolution": "manual_amount"},
        # calculated-then-reconsidered: amount lingers but resolution is unresolved
        {"charge_type": "insurance", "amount": 150.0, "currency": "USD", "resolution": "unresolved"},
    ]
    payload = fdw._build_payload(
        batch_id="B", client_name="C", currency="USD", full_number="PF/1",
        service_charges_json=json.dumps(snapshot))
    # only the freight (100.00) is billed — the unresolved 150 is excluded.
    assert payload.issued_total_minor == 10000
    assert all(r.charge_type != "insurance" for r in payload.charges)


# ── R-18 : wFirma builder notes an INFERRED legacy-zero unresolved (Fix D) ────
def test_wfirma_builder_notes_inferred_legacy_unresolved(monkeypatch):
    from app.api import routes_proforma as rp
    monkeypatch.setattr(rp, "_c1f_mirror_good_id", lambda ct: "999")
    snapshot = [
        {"charge_type": "freight", "amount": 100.0, "currency": "USD", "resolution": "manual_amount"},
        # legacy zero, NO explicit resolution, but has insurance evidence → inferred unresolved
        {"charge_type": "insurance", "amount": 0.0, "currency": "USD",
         "formula_basis": {"rate_pct": "0.35", "sales_total": "1000"}},
    ]
    lines, note = rp._build_service_charge_lines(snapshot, "USD")
    assert sum(float(l.unit_price) for l in lines) == 100.0
    assert "unresolved" in note                       # surfaced in the posting note


# ── R-19 : generic add/patch endpoints reject 'calculated' provenance (Fix C) ─
def test_generic_endpoints_reject_calculated(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app.core.config import settings
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    from app.main import app

    db_path = tmp_path / "proforma_links.db"
    pildb.init_db(db_path)
    draft, _ = pildb.upsert_pending_draft(
        db_path, batch_id="B-CAL", client_name="TC", currency="USD",
        exchange_rate=None, source_lines_json="[]", service_charges_json="[]")
    with sqlite3.connect(str(db_path)) as con:
        con.execute("UPDATE proforma_drafts SET draft_state='draft', status='draft' WHERE id=?",
                    (draft.id,))
        con.commit()
    fresh = pildb.get_draft_by_id(db_path, draft.id)
    headers = {"X-API-KEY": settings.api_key or "test-key", "X-Operator": "alice"}
    with TestClient(app, raise_server_exceptions=True) as c:
        r = c.post(
            f"/api/v1/proforma/draft/{draft.id}/service-charges",
            json={"expected_updated_at": fresh.updated_at,
                  "charge": {"charge_type": "freight", "amount": 50, "currency": "USD",
                             "resolution": "calculated"}},
            headers=headers)
        assert r.status_code == 400 and "calculated" in r.text.lower()
