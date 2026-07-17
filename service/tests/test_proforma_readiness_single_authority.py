"""test_proforma_readiness_single_authority.py

Campaign regression: proforma readiness split-authority fix.

Defect (production Drafts #32/#33): the approval/posting flow and the
blocking-reasons flow used different readiness authority, producing the
invalid state "Approved + Blocking Reasons". Draft #32 was Approved while
carrying an ambiguous design_no (J4007R08118-0.6 → EJL/26-27/257-2 and
EJL/26-27/257-4), 2 products unmatched in wfirma_products, and a blank
buyer EU VAT under WDT. Draft #33 was post_failed with the same blockers.

Fix: ``_derive_draft_readiness(draft, intent=...)`` is the SINGLE backend
readiness gate consulted by approve (422), post (400 blocked, before any
wFirma call), and convert preview/execute (blocked before the live fetch).

The 9 required regressions (10 test functions):
  1. ambiguous design_no cannot approve
  2. missing wfirma_products mapping cannot approve
  3. approved draft with newly discovered blockers cannot post
  4. approved (issued) draft with blockers cannot convert (preview + execute)
  5. WDT EU buyer without VAT blocks BEFORE the wFirma API call
  6. operator product selection clears the ambiguity blocker
  7. wFirma product mapping repair clears the missing-product blocker
  8. existing wfirma_proforma_id duplicate guard still works (409)
  9. Draft #32-shaped fixture reproduces the issue and passes after repair
 10. Draft #33-shaped fixture (post_failed) stays blocked, retry-safe,
     no duplicate wFirma document

Safety gates honoured: no historical posted documents edited, no draft
status reset without audit trail, no VAT-mode bypass, duplicate guard /
posting lock / approval gate / WFIRMA_CREATE_PROFORMA_ALLOWED untouched.
"""
from __future__ import annotations

import json
import sqlite3
import sys
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

_engine_candidates = [
    Path(__file__).parent.parent.parent / "engine",
    Path(__file__).parent.parent.parent.parent / "engine",
]
for _p in _engine_candidates:
    if _p.exists() and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
        break


BATCH         = "BATCH_READINESS_AUTH_TEST"
CLIENT        = "READINESS_CLIENT"
DESIGN        = "J4007R08118-0.6"
CODE_A        = "EJL/26-27/257-2"
CODE_B        = "EJL/26-27/257-4"
CONTRACTOR_ID = "195596259"

AMBIG_TEXT    = "maps to multiple product_codes"
PRODUCT_TEXT  = "not matched in wfirma_products"
WDT_TEXT      = "WDT (intra-EU 0%) requires the buyer's EU VAT number"

APPROVE_TOKEN = "YES_APPROVE_LOCAL_PROFORMA_DRAFT"
POST_TOKEN    = "YES_POST_LOCAL_PROFORMA_DRAFT_TO_WFIRMA"
CONVERT_TOKEN = "YES_CREATE_FINAL_INVOICE_FROM_PROFORMA"


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def storage(tmp_path):
    from app.services import packing_db as pdb
    from app.services import document_db as ddb
    from app.services import wfirma_db as wfdb
    from app.services import proforma_invoice_link_db as pildb

    pdb.init_packing_db(tmp_path / "packing.db")
    ddb.init_document_db(tmp_path / "documents.db")
    wfdb.init_wfirma_db(tmp_path / "wfirma.db")
    pildb.init_db(tmp_path / "proforma_links.db")

    out = tmp_path / "outputs" / BATCH
    (out / "source").mkdir(parents=True, exist_ok=True)
    audit = {"batch_id": BATCH, "tracking_no": BATCH,
             "awb": BATCH, "carrier": "DHL", "timeline": []}
    (out / "audit.json").write_text(json.dumps(audit), encoding="utf-8")

    return tmp_path


@pytest.fixture()
def client(storage):
    from app.core.config import settings
    from app.main import app
    with patch.object(settings, "storage_root", storage):
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c, storage


def _auth():
    from app.core.config import settings
    return {"X-API-KEY": settings.api_key or "test-key"}


def _op_headers():
    return {"X-Operator": "test-op", **_auth()}


# ── seed helpers ──────────────────────────────────────────────────────────────

def _packing_row(product_code: str, design_no: str, pos: int) -> dict:
    return {
        "batch_id":              BATCH,
        "invoice_no":            "INV/TEST",
        "invoice_line_position": pos,
        "product_code":          product_code,
        "design_no":             design_no,
        "bag_id": "", "tray_id": "", "item_type": "RNG",
        "uom": "PCS", "quantity": 1.0, "gross_weight": 0.0,
        "net_weight": 0.0, "metal": "", "karat": "", "stone_type": "",
        "remarks": "", "extracted_confidence": 1.0,
        "requires_manual_review": False, "pack_sr": float(pos),
        "unit_price": 50.0, "total_value": 50.0,
    }


def _seed_sales(product_codes: list, design_no: str = None):
    """Sales document + one sales packing line per product code."""
    from app.services import document_db as ddb
    sd = ddb.store_sales_document(
        batch_id=BATCH,
        document_id=str(uuid.uuid4()),
        data={"client_name": CLIENT, "client_ref": "REF-TEST",
              "sales_doc_no": "SO-TEST"},
    )
    ddb.store_sales_packing_lines(sd, BATCH, [{
        "client_name":  CLIENT,
        "client_ref":   "REF-TEST",
        "product_code": pc,
        "design_no":    design_no or pc,
        "bag_id": "", "quantity": 1.0, "remarks": "",
        "unit_price": 100.0, "total_value": 100.0,
        "currency": "EUR", "price_source": "packing_list",
    } for pc in product_codes])


def _seed_wf_customer():
    from app.services import wfirma_db as wfdb
    wfdb.upsert_customer(
        client_name=CLIENT,
        wfirma_customer_id="7",
        country="BG",
        vat_id="",
        match_status="matched",
    )


def _match_product(product_code: str, wfirma_product_id: str = "99"):
    from app.services import wfirma_db as wfdb
    wfdb.upsert_product(
        product_code=product_code,
        wfirma_product_id=wfirma_product_id,
        sync_status="matched",
    )


def _seed_cm(storage: Path, vat_eu_number=None, vat_eu_valid=None):
    """Customer Master record: SK buyer → derived VAT context = WDT.
    Exact bill_to_name match makes Customer Master the identity authority."""
    from app.services import customer_master_db as cmdb
    db = storage / "customer_master.sqlite"
    cmdb.init_db(db)
    cmdb.upsert_customer(db, cmdb.CustomerMaster(
        bill_to_contractor_id=CONTRACTOR_ID,
        bill_to_name=CLIENT,
        country="SK",
        vat_eu_number=vat_eu_number,
        vat_eu_valid=vat_eu_valid,
    ))


def _line(product_code: str, name_pl: str = "Pierścionek złoty",
          unit_price: float = 100.0, design_no: str = "") -> dict:
    return {"line_id": str(uuid.uuid4()), "product_code": product_code,
            "design_no": design_no,
            "name_pl": name_pl, "unit_price": unit_price,
            "quantity": 1.0, "currency": "EUR"}


def _seed_draft(
    storage: Path,
    editable_lines: list,
    status: str = "draft",
    draft_state: str = "draft",
    wfirma_proforma_id=None,
) -> int:
    db = storage / "proforma_links.db"
    with sqlite3.connect(str(db)) as conn:
        cur = conn.execute(
            """
            INSERT INTO proforma_drafts
              (batch_id, client_name, status, currency, draft_state,
               wfirma_proforma_id, wfirma_proforma_fullnumber,
               source_lines_json, editable_lines_json, service_charges_json,
               clone_generation, draft_version,
               created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'),datetime('now'))
            """,
            (BATCH, CLIENT, status, "EUR", draft_state,
             wfirma_proforma_id, "",
             "[]", json.dumps(editable_lines), "[]", 0, 1),
        )
        conn.commit()
        return cur.lastrowid


def _seed_clean_context(matched: bool = True):
    """Unambiguous packing + sales + wFirma customer (+ product match)."""
    from app.services import packing_db as pdb
    pdb.upsert_packing_lines([_packing_row(CODE_A, CODE_A, 1)])
    _seed_sales([CODE_A])
    _seed_wf_customer()
    if matched:
        _match_product(CODE_A)


def _seed_ambiguous_context(matched: bool = True):
    """One design_no mapping to TWO product_codes (Draft #32 shape)."""
    from app.services import packing_db as pdb
    pdb.upsert_packing_lines([
        _packing_row(CODE_A, DESIGN, 1),
        _packing_row(CODE_B, DESIGN, 2),
    ])
    _seed_sales([CODE_A, CODE_B], design_no=DESIGN)
    _seed_wf_customer()
    if matched:
        _match_product(CODE_A, "991")
        _match_product(CODE_B, "992")


def _approve(c, draft_id: int):
    return c.post(
        f"/api/v1/proforma/draft/{draft_id}/approve",
        json={"expected_updated_at": "", "confirm_token": APPROVE_TOKEN},
        headers=_op_headers(),
    )


def _post_to_wfirma(c, draft_id: int):
    """POST with the create-proforma flag ON and a spy on the live wFirma
    write — returns (response, create_spy)."""
    from app.core.config import settings
    create_spy = MagicMock(name="create_proforma_draft")
    with patch.object(settings, "wfirma_create_proforma_allowed", True), \
         patch("app.services.wfirma_client.create_proforma_draft", create_spy):
        r = c.post(
            f"/api/v1/proforma/draft/{draft_id}/post",
            json={"expected_updated_at": "", "confirm_token": POST_TOKEN},
            headers=_op_headers(),
        )
    return r, create_spy


def _readiness(c, draft_id: int, intent: str = "approve") -> dict:
    r = c.get(f"/api/v1/proforma/draft/{draft_id}/readiness",
              params={"intent": intent}, headers=_auth())
    assert r.status_code == 200, r.text
    return r.json()


def _draft_events(storage: Path, draft_id: int) -> list:
    db = storage / "proforma_links.db"
    with sqlite3.connect(str(db)) as conn:
        rows = conn.execute(
            "SELECT event FROM proforma_draft_events WHERE draft_id=?",
            (draft_id,),
        ).fetchall()
    return [r[0] for r in rows]


def _draft_row(storage: Path, draft_id: int) -> dict:
    db = storage / "proforma_links.db"
    with sqlite3.connect(str(db)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT status, wfirma_proforma_id FROM proforma_drafts WHERE id=?",
            (draft_id,),
        ).fetchone()
    return dict(row)


# ── 1. Ambiguous design_no cannot approve ────────────────────────────────────

def test_ambiguous_design_no_blocks_approve(client):
    # #684 billed-line reconciliation: batch-level ambiguity only blocks when
    # a BILLED line cannot be pinned to a valid product_code. A line that
    # bills the ambiguous design without a resolved product_code is the
    # genuine Draft-#32 hazard shape under the current authority.
    #
    # KNOWN-FAILING (chip task_81ea7aea): this test currently fails NOT
    # because of the seed shape but because the readiness gate is fail-open —
    # _derive_draft_readiness reads preview.get("ambiguous_design_codes") at
    # top level while the key only exists nested at
    # preview["design_product_bridge"]["ambiguous_design_codes"], so the
    # AMBIG blocker class can never fire. Goes green with the one-line
    # nested-key fix (verified 12/12). See test-baseline.md.
    c, storage = client
    _seed_ambiguous_context()
    draft_id = _seed_draft(storage, [_line(CODE_A), _line(CODE_B),
                                     _line("", design_no=DESIGN)])

    r = _approve(c, draft_id)
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert "Approval blocked by readiness gate" in detail, detail
    assert AMBIG_TEXT in detail, detail
    assert DESIGN in detail, detail

    # Refusal is audited (no silent block).
    assert "readiness_blocked" in _draft_events(storage, draft_id)


# ── 2. Missing wfirma_products mapping cannot approve ────────────────────────

def test_missing_wfirma_product_blocks_approve(client):
    c, storage = client
    _seed_clean_context(matched=False)
    draft_id = _seed_draft(storage, [_line(CODE_A)])

    r = _approve(c, draft_id)
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert PRODUCT_TEXT in detail, detail
    assert CODE_A in detail, detail  # exact missing product listed


# ── 3. Approved draft with newly discovered blockers cannot post ─────────────

def test_approved_draft_with_new_blockers_cannot_post(client):
    c, storage = client
    # Draft was approved earlier; the wfirma_products mapping is missing
    # NOW (e.g. removed / never synced) — post must force revalidation.
    _seed_clean_context(matched=False)
    draft_id = _seed_draft(storage, [_line(CODE_A)],
                           status="approved", draft_state="approved")

    r, create_spy = _post_to_wfirma(c, draft_id)
    assert r.status_code == 400, r.text
    body = r.json()
    assert body["status"] == "blocked", body
    assert body["readiness_intent"] == "post", body
    joined = " | ".join(body["blocking_reasons"])
    assert PRODUCT_TEXT in joined, joined
    create_spy.assert_not_called()

    # Lesson M: every blocker carries an exact repair action.
    assert body["blockers"], body
    assert all((b.get("repair_action") or "").strip() for b in body["blockers"])

    # Refusal audited; draft state unchanged (no reset without audit trail).
    assert "readiness_blocked" in _draft_events(storage, draft_id)
    row = _draft_row(storage, draft_id)
    assert row["status"] == "approved", row
    assert not (row["wfirma_proforma_id"] or ""), row


# ── 4. Issued draft with blockers cannot convert (preview + execute) ─────────

def test_issued_draft_with_blockers_cannot_convert(client):
    c, storage = client
    from app.core.config import settings
    _seed_clean_context(matched=False)
    draft_id = _seed_draft(storage, [_line(CODE_A)],
                           status="issued", draft_state="issued",
                           wfirma_proforma_id="555000111")

    fetch_spy = MagicMock(name="fetch_invoice_xml")
    with patch("app.services.wfirma_client.fetch_invoice_xml", fetch_spy):
        # Read-only preview is blocked by the same authority.
        rp = c.get(f"/api/v1/proforma/to-invoice-preview/{BATCH}/{CLIENT}",
                   headers=_auth())
        assert rp.status_code == 200, rp.text
        pbody = rp.json()
        assert pbody["status"] == "blocked", pbody
        assert pbody["readiness_intent"] == "convert", pbody
        assert any(PRODUCT_TEXT in br for br in pbody["blocking_reasons"]), pbody

        # Execute path: gate fires BEFORE the live wFirma fetch.
        with patch.object(settings, "wfirma_create_invoice_allowed", True):
            rx = c.post(
                f"/api/v1/proforma/to-invoice/{BATCH}/{CLIENT}",
                json={"confirm": CONVERT_TOKEN},
                headers=_op_headers(),
            )
        assert rx.status_code == 200, rx.text
        xbody = rx.json()
        assert xbody["status"] == "blocked", xbody
        assert xbody["readiness_intent"] == "convert", xbody
        assert any(PRODUCT_TEXT in br for br in xbody["blocking_reasons"]), xbody

    fetch_spy.assert_not_called()
    assert "readiness_blocked" in _draft_events(storage, draft_id)


# ── 5. WDT EU buyer without VAT blocks BEFORE the wFirma API call ────────────

def test_wdt_buyer_without_eu_vat_blocks_before_wfirma_call(client):
    c, storage = client
    _seed_clean_context(matched=True)
    _seed_cm(storage, vat_eu_number=None)   # SK buyer, blank vat_eu_number
    draft_id = _seed_draft(storage, [_line(CODE_A)],
                           status="approved", draft_state="approved")

    ready = _readiness(c, draft_id, intent="post")
    assert any(WDT_TEXT in br for br in ready["blocking_reasons"]), ready

    r, create_spy = _post_to_wfirma(c, draft_id)
    assert r.status_code == 400, r.text
    body = r.json()
    assert body["status"] == "blocked", body
    assert any(WDT_TEXT in br for br in body["blocking_reasons"]), body
    create_spy.assert_not_called()

    # Repair action must say "add the VAT number", never "change vat_mode".
    wdt_blockers = [b for b in body["blockers"] if WDT_TEXT in b["reason"]]
    assert wdt_blockers, body
    assert "Do NOT change" in wdt_blockers[0]["repair_action"]


# ── 6. Operator product selection clears the ambiguity blocker ───────────────

def test_operator_selection_clears_ambiguity_blocker(client):
    # #684: the ambiguity blocker fires only for a billed-but-unpinned
    # design (see test 1) — seed one line billing DESIGN without a
    # resolved product_code so the operator-selection flow has a genuine
    # blocker to clear.
    c, storage = client
    _seed_ambiguous_context()
    draft_id = _seed_draft(storage, [_line(CODE_A), _line(CODE_B),
                                     _line("", design_no=DESIGN)])

    before = _readiness(c, draft_id, intent="approve")
    assert any(AMBIG_TEXT in br for br in before["blocking_reasons"]), before
    assert DESIGN in before["ambiguous_designs"], before
    assert sorted(before["ambiguous_designs"][DESIGN]) == [CODE_A, CODE_B]

    r = c.post(
        f"/api/v1/proforma/draft/{draft_id}/resolve-ambiguity",
        json={"design_no": DESIGN, "product_code": CODE_A},
        headers=_op_headers(),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True, body
    assert not any(AMBIG_TEXT in br
                   for br in body["readiness"]["blocking_reasons"]), body
    assert body["readiness"]["resolved_designs"][DESIGN]["product_code"] == CODE_A

    # Persisted: a fresh readiness read stays clear of the ambiguity class.
    after = _readiness(c, draft_id, intent="approve")
    assert not any(AMBIG_TEXT in br for br in after["blocking_reasons"]), after

    # Selection audited.
    assert "ambiguity_resolved" in _draft_events(storage, draft_id)


# ── 7. wFirma product mapping repair clears the missing-product blocker ──────

def test_product_mapping_repair_clears_missing_product_blocker(client):
    c, storage = client
    _seed_clean_context(matched=False)
    draft_id = _seed_draft(storage, [_line(CODE_A)])

    before = _readiness(c, draft_id, intent="approve")
    assert any(PRODUCT_TEXT in br for br in before["blocking_reasons"]), before

    _match_product(CODE_A)   # operator registers the mapping

    after = _readiness(c, draft_id, intent="approve")
    assert not any(PRODUCT_TEXT in br for br in after["blocking_reasons"]), after


# ── 8. Existing wfirma_proforma_id duplicate guard still works ───────────────

def test_duplicate_wfirma_proforma_id_guard_intact(client):
    c, storage = client
    _seed_clean_context(matched=True)
    draft_id = _seed_draft(storage, [_line(CODE_A)],
                           status="approved", draft_state="approved",
                           wfirma_proforma_id="123456789")

    r, create_spy = _post_to_wfirma(c, draft_id)
    assert r.status_code == 409, r.text
    assert "already has wfirma_proforma_id" in r.json()["detail"], r.text
    create_spy.assert_not_called()


# ── 9. Draft #32-shaped fixture: reproduces, then passes after repair ─────────

def test_draft32_shape_reproduces_and_repairs(client):
    """Draft #32: Approved + ambiguous design_no + 2 unmatched products +
    WDT buyer with blank EU VAT. The invalid state must be unreachable for
    new approvals and un-postable for the existing one; all three repairs
    clear their blocker classes."""
    c, storage = client
    _seed_ambiguous_context(matched=False)        # 2 products NOT matched
    _seed_cm(storage, vat_eu_number=None)          # WDT, blank EU VAT
    # #684: the third line bills DESIGN without a resolved product_code —
    # the genuine ambiguity shape under billed-line reconciliation.
    unpinned = _line("", design_no=DESIGN)
    lines = [_line(CODE_A), _line(CODE_B), unpinned]
    draft_id = _seed_draft(storage, lines,
                           status="approved", draft_state="approved")

    # Reproduce: approve re-validation refuses…
    ra = _approve(c, draft_id)
    assert ra.status_code == 422, ra.text
    detail = ra.json()["detail"]
    assert AMBIG_TEXT in detail and PRODUCT_TEXT in detail, detail
    assert WDT_TEXT in detail, detail

    # …and post is blocked with no wFirma call.
    rp, create_spy = _post_to_wfirma(c, draft_id)
    assert rp.status_code == 400, rp.text
    joined = " | ".join(rp.json()["blocking_reasons"])
    assert AMBIG_TEXT in joined and PRODUCT_TEXT in joined and WDT_TEXT in joined
    create_spy.assert_not_called()

    # Repair 1 — operator resolves the design ambiguity.
    r1 = c.post(
        f"/api/v1/proforma/draft/{draft_id}/resolve-ambiguity",
        json={"design_no": DESIGN, "product_code": CODE_A},
        headers=_op_headers(),
    )
    assert r1.status_code == 200, r1.text

    # Repair 1b — the resolution NEVER edits draft lines (route contract);
    # the operator applies the chosen product_code to the unpinned line.
    unpinned["product_code"] = CODE_A
    db = storage / "proforma_links.db"
    with sqlite3.connect(str(db)) as conn:
        conn.execute(
            "UPDATE proforma_drafts SET editable_lines_json=? WHERE id=?",
            (json.dumps(lines), draft_id),
        )
        conn.commit()

    # Repair 2 — both products registered in wfirma_products.
    _match_product(CODE_A, "991")
    _match_product(CODE_B, "992")

    # Repair 3 — buyer EU VAT added to Customer Master (no vat_mode change).
    _seed_cm(storage, vat_eu_number="SK2020000000", vat_eu_valid=True)

    after = _readiness(c, draft_id, intent="approve")
    reasons = after["blocking_reasons"]
    assert not any(AMBIG_TEXT in br for br in reasons), reasons
    assert not any(PRODUCT_TEXT in br for br in reasons), reasons
    assert not any(WDT_TEXT in br for br in reasons), reasons


# ── 10. Draft #33-shaped fixture: post_failed stays blocked, retry-safe ──────

def test_draft33_post_failed_blocked_retry_safe_no_duplicate(client):
    """Draft #33: post_failed with unresolved blockers. Retry must be safe:
    blocked response, exact repair actions, no wFirma call, no duplicate
    document, status untouched (no reset without audit trail)."""
    c, storage = client
    _seed_ambiguous_context(matched=False)
    _seed_cm(storage, vat_eu_number=None)
    draft_id = _seed_draft(storage, [_line(CODE_A), _line(CODE_B)],
                           status="post_failed", draft_state="post_failed")

    for _attempt in (1, 2):   # retry twice — idempotently blocked
        r, create_spy = _post_to_wfirma(c, draft_id)
        assert r.status_code == 400, r.text
        body = r.json()
        assert body["status"] == "blocked", body
        assert body["blockers"], body
        assert all((b.get("repair_action") or "").strip()
                   for b in body["blockers"]), body
        create_spy.assert_not_called()

    row = _draft_row(storage, draft_id)
    assert row["status"] == "post_failed", row          # no silent reset
    assert not (row["wfirma_proforma_id"] or ""), row   # no duplicate created


# ── Frontend contract: PzApi envelope unwrap (browser-verified 2026-06-12) ──
# PzApi._get wraps every response as {ok, data}; the readiness object
# (ready / blockers / ambiguous_designs) lives under .data. Storing the
# wrapper directly made ready/blockers undefined: the panel showed
# "0 blocking reasons" and ready===false checks never fired, so buttons
# were NOT gated. Found in browser verification — pin the unwrap.

_V2_DIR = Path(__file__).parent.parent / "app" / "static" / "v2"


def test_detail_page_unwraps_readiness_envelope():
    src = (_V2_DIR / "proforma-detail.jsx").read_text(encoding="utf-8")
    # the buggy direct-store of the {ok,data} wrapper must not come back
    assert "setReadinessApprove(r || null)" not in src
    assert "setReadinessPost(r || null)" not in src
    # both intents unwrap .data and treat a failed call as null
    assert src.count("(r && r.ok && r.data) ? r.data : null") >= 2


def test_pz_api_readiness_returns_wrapped_envelope():
    src = (_V2_DIR / "pz-api.js").read_text(encoding="utf-8")
    assert "getDraftReadiness" in src
    # _get is the {ok,data}-wrapping caller — the unwrap above depends on it
    assert "getDraftReadiness: (draftId, intent) =>" in src
    assert "/readiness?intent=" in src
