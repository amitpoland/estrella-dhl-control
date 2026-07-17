"""
test_proforma_fullnumber_phase9.py — Phase 9:
persist wFirma Proforma fullnumber after posting a local draft.

Coverage:
  1. _extract_fullnumber priority (<fullnumber> > <full_number> > <number>)
  2. ProformaResult carries wfirma_invoice_number when verify_xml has it
  3. ProformaResult falls back to the create-response <invoice> node
  4. Empty fullnumber when no field present (post still succeeds)
  5. Phase 5 post route persists fullnumber into the draft row
  6. record_proforma_issued accepts and stores wfirma_proforma_fullnumber
  7. Phase 5 post route forwards fullnumber into record_proforma_issued
  8. Phase 8 PDF filename uses the persisted fullnumber
  9. fetch_invoice_xml is NOT called twice (no second wFirma round-trip)
"""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.services import audit_persist
from app.services import proforma_invoice_link_db as pildb
from app.services import wfirma_client
from app.services import wfirma_db as wfdb


# ── Helpers ────────────────────────────────────────────────────────────────

def _auth_headers(operator: str = "alice"):
    return {
        "X-API-KEY":  settings.api_key or "test-key",
        "X-Operator": operator,
    }


@pytest.fixture()
def client(tmp_path, monkeypatch) -> TestClient:
    from app.main import app
    monkeypatch.setattr(settings, "wfirma_create_proforma_allowed", True)
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


def _seed_approved(db: Path, *, currency="EUR"):
    d, _ = pildb.auto_create_draft_from_sales_packing(
        db, batch_id="B1", client_name="ACME", currency=currency,
        lines=[
            {"product_code": "RNG-100", "design_no": "D100",
             "qty": 2, "unit_price": 25.50, "currency": currency},
        ],
        operator="intake",
    )
    return pildb.approve_draft(
        db, d.id, "alice", d.updated_at,
        confirm_token=pildb.APPROVE_CONFIRM_TOKEN,
    )


def _stub_route_lookups(monkeypatch):
    from app.api import routes_proforma as rp

    # Single-readiness-authority gate stub (split-authority fix): these
    # tests pin fullnumber persistence mechanics, not readiness — that has
    # dedicated no-stub coverage in
    # test_proforma_readiness_single_authority.py. Shape mirrors the real
    # _derive_draft_readiness return exactly (Lesson A).
    def _stub_readiness(draft, *, intent):
        return {
            "ready":             True,
            "intent":            intent,
            "draft_id":          int(draft.id),
            "draft_status":      draft.status,
            "blockers":          [],
            "blocking_reasons":  [],
            "warnings":          [],
            "ambiguous_designs": {},
            "resolved_designs":  {},
            "vat_resolution":    None,
            "duplicate_product_codes": [],
            "product_authority_available": True,
        }
    monkeypatch.setattr(rp, "_derive_draft_readiness", _stub_readiness)

    # client_contractor_id kwarg added by the CM-selection authority chain —
    # accept it like the real signature (stale-lambda TypeError otherwise).
    monkeypatch.setattr(rp, "_resolve_customer",
                        lambda name, batch_id=None, client_contractor_id="": {
        "ambiguous": False, "candidates": [],
        "customer": {
            "name": name, "country": "PL", "vat_id": "PL1234567890",
            "ship_to_mode": "same_as_bill_to",
            "ship_to_wfirma_customer_id": "",
        },
        "wfirma_customer_id": "WF-CUST-1",
        "normalized_name": name.upper(),
    })
    # C-3g: good-id resolution is mirror-only — stub the mirror helper
    # (the retired wfdb.get_product cache fallback is no longer consulted).
    monkeypatch.setattr(rp, "_c1f_mirror_good_id", lambda code: f"WFP-{code}")
    monkeypatch.setattr(
        wfirma_client, "decide_proforma_vat_context",
        lambda **kw: {"context": "domestic", "vat_code": "23",
                       "reason": "stubbed"},
    )
    monkeypatch.setattr(
        wfirma_client, "resolve_vat_code_id_for_context", lambda c: "VAT-23",
    )
    monkeypatch.setattr(
        wfirma_client, "fetch_contractor_by_id",
        lambda cid: type("R", (), {"ok": True, "error": None})(),
    )


# ── 1. _extract_fullnumber priority ─────────────────────────────────────────

@pytest.mark.parametrize("xml,expected", [
    ("<invoice><fullnumber>PROF 92/2026</fullnumber><number>92</number></invoice>",
     "PROF 92/2026"),
    ("<invoice><full_number>PROF 92/2026</full_number><number>92</number></invoice>",
     "PROF 92/2026"),
    # Bare <number> only — last-resort fallback
    ("<invoice><number>92</number></invoice>",
     "92"),
    # Empty body — empty string
    ("<invoice></invoice>",
     ""),
])
def test_extract_fullnumber_priority(xml, expected):
    node = ET.fromstring(xml)
    assert wfirma_client._extract_fullnumber(node) == expected


def test_extract_fullnumber_when_both_present_picks_fullnumber():
    """Pin the priority explicitly: <fullnumber> beats <number> even
    when both are non-empty and the <number> is more specific-looking."""
    xml = (
        "<invoice>"
          "<fullnumber>PROF 92/2026</fullnumber>"
          "<number>EXTRA-999</number>"
        "</invoice>"
    )
    node = ET.fromstring(xml)
    assert wfirma_client._extract_fullnumber(node) == "PROF 92/2026"


def test_extract_fullnumber_when_full_number_present_beats_bare_number():
    xml = (
        "<invoice>"
          "<full_number>PROF 92/2026</full_number>"
          "<number>92</number>"
        "</invoice>"
    )
    node = ET.fromstring(xml)
    assert wfirma_client._extract_fullnumber(node) == "PROF 92/2026"


def test_extract_fullnumber_handles_none():
    assert wfirma_client._extract_fullnumber(None) == ""


def test_extract_fullnumber_strips_whitespace():
    xml = "<invoice><fullnumber>  PROF 92/2026  </fullnumber></invoice>"
    node = ET.fromstring(xml)
    assert wfirma_client._extract_fullnumber(node) == "PROF 92/2026"


# ── 2-4. ProformaResult carries fullnumber from create_proforma_draft ──────

def _xml_create_response(invoice_id="9001", *, with_fullnumber=False,
                          with_number=False):
    fullnumber_xml = (
        "<fullnumber>PROF 92/2026</fullnumber>" if with_fullnumber else ""
    )
    number_xml = "<number>92</number>" if with_number else ""
    return (
        '<api>'
          '<invoices><invoice>'
            f'<id>{invoice_id}</id>'
            f'{fullnumber_xml}'
            f'{number_xml}'
            '<type>proforma</type>'
          '</invoice></invoices>'
          '<status><code>OK</code></status>'
        '</api>'
    )


def _xml_verify_response(invoice_id="9001", line_count=1, *,
                          full_number_value="PROF 92/2026",
                          fullnumber_tag="fullnumber",
                          vat_code_id="VAT-23"):
    """Build a wFirma invoices/get response with N persisted lines, all
    carrying the matching VAT code so create_proforma_draft accepts."""
    contents = ""
    for i in range(line_count):
        contents += (
            "<invoicecontent>"
              f"<good><id>WFP-RNG-100</id></good>"
              f"<vat_code><id>{vat_code_id}</id></vat_code>"
              f"<count>1</count><price>1.00</price>"
            "</invoicecontent>"
        )
    fullnumber_xml = (
        f"<{fullnumber_tag}>{full_number_value}</{fullnumber_tag}>"
        if full_number_value else ""
    )
    return (
        '<api><invoice>'
          f'<id>{invoice_id}</id>'
          f'{fullnumber_xml}'
          '<type>proforma</type>'
          f'<invoicecontents>{contents}</invoicecontents>'
        '</invoice><status><code>OK</code></status></api>'
    )


def _build_min_request(line_count=1):
    """Smallest valid ProformaRequest for create_proforma_draft."""
    return wfirma_client.ProformaRequest(
        client_name="ACME", client_zip="", client_city="",
        lines=[
            wfirma_client.ReservationLine(
                product_code="RNG-100",
                wfirma_good_id="WFP-RNG-100",
                product_name="D100",
                qty=1.0, unit_price=1.0,
                unit="szt.", currency="EUR",
            )
            for _ in range(line_count)
        ],
        currency="EUR",
        wfirma_contractor_id="WF-CUST-1",
        vat_code_id="VAT-23",
    )


def test_create_response_fullnumber_carried_via_verify(monkeypatch):
    """Verify-after-create XML carries <fullnumber> → ProformaResult
    surfaces it as wfirma_invoice_number. No second fetch needed."""
    create_xml = _xml_create_response("9001")
    verify_xml = _xml_verify_response("9001")

    fetch_calls = {"n": 0}

    def _fake_http(method, module, action, body=""):
        if method == "POST" and module == "invoices" and action == "add":
            return 200, create_xml
        # Should NOT be called for invoices/get because verify is
        # routed via fetch_invoice_xml below.
        raise AssertionError(f"unexpected call: {method} {module}/{action}")

    def _fake_fetch_invoice_xml(invoice_id):
        fetch_calls["n"] += 1
        return verify_xml

    monkeypatch.setattr(wfirma_client, "_http_request", _fake_http)
    monkeypatch.setattr(wfirma_client, "fetch_invoice_xml",
                         _fake_fetch_invoice_xml)

    result = wfirma_client.create_proforma_draft(_build_min_request())
    assert result.ok                    is True
    assert result.wfirma_invoice_id     == "9001"
    assert result.wfirma_invoice_number == "PROF 92/2026"
    # Phase 9 promise: NO second wFirma fetch beyond the verify call.
    assert fetch_calls["n"] == 1


def test_create_response_falls_back_to_create_xml(monkeypatch):
    """Verify XML lacks fullnumber; create XML has it. The result must
    still surface the create-response value."""
    create_xml = _xml_create_response("9001", with_fullnumber=True)
    # Verify-XML deliberately bare (no fullnumber)
    verify_xml = _xml_verify_response("9001", full_number_value="")

    monkeypatch.setattr(
        wfirma_client, "_http_request",
        lambda *a, **kw: (200, create_xml),
    )
    monkeypatch.setattr(
        wfirma_client, "fetch_invoice_xml", lambda _id: verify_xml,
    )
    result = wfirma_client.create_proforma_draft(_build_min_request())
    assert result.wfirma_invoice_number == "PROF 92/2026"


def test_create_response_no_fullnumber_anywhere_returns_empty(monkeypatch):
    """Neither response has fullnumber/full_number/number → empty
    string. Posting must still succeed."""
    create_xml = _xml_create_response("9001")           # bare id only
    verify_xml = _xml_verify_response("9001", full_number_value="")
    monkeypatch.setattr(
        wfirma_client, "_http_request",
        lambda *a, **kw: (200, create_xml),
    )
    monkeypatch.setattr(
        wfirma_client, "fetch_invoice_xml", lambda _id: verify_xml,
    )
    result = wfirma_client.create_proforma_draft(_build_min_request())
    assert result.ok                    is True
    assert result.wfirma_invoice_id     == "9001"
    assert result.wfirma_invoice_number == ""


def test_create_response_only_bare_number_is_used(monkeypatch):
    """If only <number> is present, it's used as last-resort fallback."""
    create_xml = _xml_create_response("9001", with_number=True)
    verify_xml = _xml_verify_response("9001", full_number_value="")
    monkeypatch.setattr(
        wfirma_client, "_http_request",
        lambda *a, **kw: (200, create_xml),
    )
    monkeypatch.setattr(
        wfirma_client, "fetch_invoice_xml", lambda _id: verify_xml,
    )
    result = wfirma_client.create_proforma_draft(_build_min_request())
    assert result.wfirma_invoice_number == "92"


def test_create_response_does_not_call_wfirma_a_second_time(monkeypatch):
    """The Phase 9 enrichment MUST reuse the verify-after-create XML.
    No second invoices/get round-trip is allowed."""
    create_xml = _xml_create_response("9001")
    verify_xml = _xml_verify_response("9001")
    fetch_calls = {"n": 0}
    monkeypatch.setattr(
        wfirma_client, "_http_request",
        lambda *a, **kw: (200, create_xml),
    )
    def _verify(_id):
        fetch_calls["n"] += 1
        return verify_xml
    monkeypatch.setattr(wfirma_client, "fetch_invoice_xml", _verify)
    wfirma_client.create_proforma_draft(_build_min_request())
    assert fetch_calls["n"] == 1, (
        "fetch_invoice_xml must be called EXACTLY once (for the "
        "verify-after-create check). Phase 9 must not add a second call."
    )


# ── 5. Phase 5 post route persists fullnumber into draft row ───────────────

def test_phase5_post_persists_fullnumber(client, tmp_path, monkeypatch):
    db = tmp_path / "proforma_links.db"
    d = _seed_approved(db)
    _stub_route_lookups(monkeypatch)
    monkeypatch.setattr(
        wfirma_client, "create_proforma_draft",
        lambda req: wfirma_client.ProformaResult(
            ok=True,
            wfirma_invoice_id="WF-9001",
            wfirma_invoice_number="PROF 92/2026",
        ),
    )
    r = client.post(
        f"/api/v1/proforma/draft/{d.id}/post",
        json={"expected_updated_at": d.updated_at,
              "confirm_token": pildb.POST_CONFIRM_TOKEN},
        headers=_auth_headers(),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["wfirma_proforma_id"]         == "WF-9001"
    assert body["wfirma_proforma_fullnumber"] == "PROF 92/2026"
    # Persisted on the draft row.
    fresh = pildb.get_draft_by_id(db, d.id)
    assert fresh.wfirma_proforma_fullnumber == "PROF 92/2026"


def test_phase5_post_with_empty_fullnumber_still_succeeds(client, tmp_path, monkeypatch):
    """If wFirma gave us no fullnumber, posting must NOT fail — it just
    persists empty and the dashboard / PDF filename fall back."""
    db = tmp_path / "proforma_links.db"
    d = _seed_approved(db)
    _stub_route_lookups(monkeypatch)
    monkeypatch.setattr(
        wfirma_client, "create_proforma_draft",
        lambda req: wfirma_client.ProformaResult(
            ok=True, wfirma_invoice_id="WF-NN",
            wfirma_invoice_number="",
        ),
    )
    r = client.post(
        f"/api/v1/proforma/draft/{d.id}/post",
        json={"expected_updated_at": d.updated_at,
              "confirm_token": pildb.POST_CONFIRM_TOKEN},
        headers=_auth_headers(),
    )
    assert r.status_code == 200, r.text
    fresh = pildb.get_draft_by_id(db, d.id)
    assert fresh.draft_state             == "posted"
    assert fresh.wfirma_proforma_id      == "WF-NN"
    assert fresh.wfirma_proforma_fullnumber == ""


# ── 6. record_proforma_issued accepts fullnumber ──────────────────────────

def test_record_proforma_issued_accepts_fullnumber(tmp_path):
    """The audit-persist helper accepts the new optional parameter and
    stores it both on the entry and in the timeline event detail."""
    audit_path = tmp_path / "audit.json"
    audit_path.write_text(json.dumps({"timeline": [], "proforma_issued": []}))
    res = audit_persist.record_proforma_issued(
        audit_path,
        batch_id="B1", client_name="ACME",
        wfirma_proforma_id="WF-9001",
        wfirma_proforma_fullnumber="PROF 92/2026",
        line_count=1, currency="EUR", operator="alice",
    )
    assert res["appended"] is True
    saved = json.loads(audit_path.read_text())
    issued = saved["proforma_issued"]
    assert len(issued) == 1
    assert issued[0]["wfirma_proforma_id"]         == "WF-9001"
    assert issued[0]["wfirma_proforma_fullnumber"] == "PROF 92/2026"
    # Timeline event also carries it.
    timeline = saved.get("timeline") or []
    pi_events = [e for e in timeline if e.get("event") == "proforma_issued"]
    assert pi_events
    detail = pi_events[-1].get("detail") or {}
    assert detail.get("wfirma_proforma_fullnumber") == "PROF 92/2026"


def test_record_proforma_issued_legacy_caller_still_works(tmp_path):
    """Pre-Phase-9 callers omit wfirma_proforma_fullnumber. The helper
    must continue to accept and default to empty string."""
    audit_path = tmp_path / "audit.json"
    audit_path.write_text(json.dumps({"timeline": [], "proforma_issued": []}))
    res = audit_persist.record_proforma_issued(
        audit_path,
        batch_id="B1", client_name="ACME",
        wfirma_proforma_id="WF-OLD",
        line_count=1, currency="EUR", operator="alice",
        # NB: no fullnumber kwarg
    )
    assert res["appended"] is True
    issued = json.loads(audit_path.read_text())["proforma_issued"]
    assert issued[0]["wfirma_proforma_fullnumber"] == ""


# ── 7. Phase 5 post route forwards fullnumber to record_proforma_issued ───

def test_phase5_post_forwards_fullnumber_to_audit(client, tmp_path, monkeypatch):
    db = tmp_path / "proforma_links.db"
    d = _seed_approved(db)
    _stub_route_lookups(monkeypatch)
    monkeypatch.setattr(
        wfirma_client, "create_proforma_draft",
        lambda req: wfirma_client.ProformaResult(
            ok=True, wfirma_invoice_id="WF-9001",
            wfirma_invoice_number="PROF 92/2026",
        ),
    )
    captured = {}
    def _fake_record(audit_path, **kwargs):
        captured.update(kwargs)
        return {"appended": True}
    monkeypatch.setattr(
        "app.services.audit_persist.record_proforma_issued", _fake_record,
    )
    r = client.post(
        f"/api/v1/proforma/draft/{d.id}/post",
        json={"expected_updated_at": d.updated_at,
              "confirm_token": pildb.POST_CONFIRM_TOKEN},
        headers=_auth_headers(),
    )
    assert r.status_code == 200, r.text
    assert captured.get("wfirma_proforma_fullnumber") == "PROF 92/2026"
    assert captured.get("wfirma_proforma_id")         == "WF-9001"


# ── 8. Phase 8 PDF filename uses the persisted fullnumber ─────────────────

def test_phase8_pdf_filename_uses_fullnumber(client, tmp_path, monkeypatch):
    """End-to-end: Phase-9 persisted fullnumber flows into Phase-8
    Content-Disposition. Confirms the two phases cooperate."""
    db = tmp_path / "proforma_links.db"
    d = _seed_approved(db)
    _stub_route_lookups(monkeypatch)
    monkeypatch.setattr(
        wfirma_client, "create_proforma_draft",
        lambda req: wfirma_client.ProformaResult(
            ok=True, wfirma_invoice_id="WF-9001",
            wfirma_invoice_number="PROF 92/2026",
        ),
    )
    # Post the draft
    r = client.post(
        f"/api/v1/proforma/draft/{d.id}/post",
        json={"expected_updated_at": d.updated_at,
              "confirm_token": pildb.POST_CONFIRM_TOKEN},
        headers=_auth_headers(),
    )
    assert r.status_code == 200

    # Now hit the PDF endpoint. fetch_invoice_pdf is stubbed to return
    # plain bytes; we only care about the filename header.
    # The route treats < 200 bytes as a broken wFirma response (Lesson-G
    # blank-PDF guard → 502) — pad the fake body past the floor.
    monkeypatch.setattr(
        wfirma_client, "fetch_invoice_pdf",
        lambda invoice_id: b"%PDF-1.4\n" + b"%fake-padding\n" * 20 + b"%%EOF\n",
    )
    fresh = pildb.get_draft_by_id(db, d.id)
    assert fresh.wfirma_proforma_fullnumber == "PROF 92/2026"
    pdf = client.get(
        f"/api/v1/proforma/{fresh.batch_id}/{fresh.client_name}/document.pdf",
        headers=_auth_headers(),
    )
    assert pdf.status_code == 200
    cd = pdf.headers.get("content-disposition", "")
    # Slashes are sanitised by the route.
    assert "PROF 92_2026.pdf" in cd
    # Sanity: not the wfirma-id fallback.
    assert "proforma-WF-9001.pdf" not in cd
