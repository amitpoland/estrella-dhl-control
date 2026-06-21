"""test_sales_draft_workflow_completion.py — Sales Draft Workflow Completion.

Pins the in-page workflow-completion campaign (Phases A–E) so the operator can
run Sales → Proforma → Reservation without leaving the Sales page:

  Phase A — Direct customer resolution: assign a Customer-Master contractor to a
            blocked sales document and immediately re-run projection/sync so the
            draft is born and the open block resolves (no re-intake).
  Phase B — Customer-first layout: editable Buyer / Ship-to / Payment controls
            render ABOVE the lines (source-contract).
  Phase C — Invoice description authority: lines carry the customer-facing
            invoice line-name authority (wFirma goods name), so the editor,
            preview and generated invoice agree.
  Phase D — Freight authority: blocked freight suggestion is actionable inline.
  Phase E — Reservation save: the create entry is reachable again and any block
            carries a concrete remedy.

Local-DB only. No wFirma API / SMTP / DHL surfaces are exercised.

Run: python -m pytest tests/test_sales_draft_workflow_completion.py -q
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from app.core.config import settings
from app.services import document_db as ddb
from app.services import proforma_invoice_link_db as pildb
from app.services import customer_master_db as cmdb
from app.services import wfirma_db as wfdb
from app.services.customer_master_db import CustomerMaster

CID_ACME = "182241571"
CID_NEW = "501502503"
HTML = (Path(__file__).resolve().parents[1] / "app" / "static"
        / "shipment-detail.html")
ROUTES_CP = (Path(__file__).resolve().parents[1] / "app" / "api"
             / "routes_contractor_projection.py")
ROUTES_PF = (Path(__file__).resolve().parents[1] / "app" / "api"
             / "routes_proforma.py")
DOC_DB = (Path(__file__).resolve().parents[1] / "app" / "services"
          / "document_db.py")


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def storage(tmp_path) -> Path:
    ddb.init_document_db(tmp_path / "documents.db")
    pildb.init_db(tmp_path / "proforma_links.db")
    cmdb.init_db(tmp_path / "customer_master.sqlite")
    wfdb.init_wfirma_db(tmp_path / "wfirma.db")
    with patch.object(settings, "storage_root", tmp_path):
        yield tmp_path


@pytest.fixture()
def proforma_db(storage) -> Path:
    return storage / "proforma_links.db"


@pytest.fixture()
def client(storage):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.auth.dependencies import require_admin, get_current_user
    from app.core.security import require_api_key
    app.dependency_overrides[require_admin] = lambda: {
        "id": "test-admin", "username": "admin", "role": "admin",
    }
    app.dependency_overrides[require_api_key] = lambda: {"id": "test-admin"}
    app.dependency_overrides[get_current_user] = lambda: {
        "id": "test-admin", "role": "admin",
    }
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c, storage
    app.dependency_overrides.clear()


def _add_customer(storage: Path, cid: str, name: str) -> None:
    cmdb.upsert_customer(
        storage / "customer_master.sqlite",
        CustomerMaster(bill_to_contractor_id=cid, bill_to_name=name, country="PL"),
    )


def _register_sales_packing_doc(batch_id: str, *, cid: str = "") -> str:
    return ddb.register_document(
        batch_id=batch_id, document_type="sales_packing_list",
        file_name="sales_pl.xlsx", source="intake",
        client_contractor_id=cid,
    ) or ""


def _store_sales_doc(batch_id: str, ship_doc_id: str, *, client_name: str = "",
                     cid: str = "") -> str:
    return ddb.store_sales_document(
        batch_id=batch_id, document_id=ship_doc_id,
        data={"client_name": client_name, "document_type": "sales_packing_list",
              "client_contractor_id": cid},
    )


def _line(product_code: str = "PC-1", client_name: str = "", **kw) -> dict:
    row = {"client_name": client_name, "product_code": product_code,
           "design_no": "D1", "quantity": 1.0, "unit_price": 10.0,
           "total_value": 10.0, "currency": "EUR"}
    row.update(kw)
    return row


def _seed_blocked_doc(batch_id: str) -> str:
    """A sales document with no client_name and no contractor → contractor_missing."""
    ship = _register_sales_packing_doc(batch_id, cid="")
    sd_id = _store_sales_doc(batch_id, ship, client_name="", cid="")
    ddb.store_sales_packing_lines(sd_id, batch_id, [_line(client_name="")])
    return sd_id


def _seed_draft_with_lines(proforma_db: Path, batch_id: str, lines_json: str,
                           client_name: str = "ACME") -> int:
    with sqlite3.connect(str(proforma_db)) as conn:
        pildb._ensure_drafts_table(conn)
        now = pildb._now_utc_iso()
        cur = conn.execute(
            "INSERT INTO proforma_drafts (batch_id, client_name, status, "
            "currency, draft_state, draft_version, source_lines_json, "
            "editable_lines_json, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (batch_id, client_name, "draft", "EUR", "editing", 1, "[]",
             lines_json, now, now),
        )
        return int(cur.lastrowid)


# ══════════════════════════════════════════════════════════════════════════════
# Phase A — data layer: set_sales_document_contractor
# ══════════════════════════════════════════════════════════════════════════════

class TestPhaseADataLayer:
    def test_set_contractor_writes_doc_and_lines(self, storage):
        b = "B-SETC-1"
        sd_id = _seed_blocked_doc(b)
        res = ddb.set_sales_document_contractor(b, sd_id, CID_ACME)
        assert res["sales_documents_updated"] == 1
        assert res["sales_lines_updated"] == 1
        assert res["previous_contractor_id"] == ""   # was a contractor_missing doc
        row = next(r for r in ddb.get_sales_documents(b) if r["id"] == sd_id)
        assert row["client_contractor_id"] == CID_ACME
        assert all(ln["client_contractor_id"] == CID_ACME
                   for ln in ddb.get_sales_packing_lines(b))

    def test_set_contractor_discloses_previous_on_overwrite(self, storage):
        b = "B-SETC-OW"
        sd_id = _seed_blocked_doc(b)
        ddb.set_sales_document_contractor(b, sd_id, "OLD-CID")
        res = ddb.set_sales_document_contractor(b, sd_id, CID_ACME)
        assert res["previous_contractor_id"] == "OLD-CID"  # overwrite disclosed
        row = next(r for r in ddb.get_sales_documents(b) if r["id"] == sd_id)
        assert row["client_contractor_id"] == CID_ACME

    def test_set_contractor_scoped_to_one_document(self, storage):
        b = "B-SETC-2"
        sd_a = _seed_blocked_doc(b)
        sd_b = _seed_blocked_doc(b)
        ddb.set_sales_document_contractor(b, sd_a, CID_ACME)
        # The other document is untouched.
        row_b = next(r for r in ddb.get_sales_documents(b) if r["id"] == sd_b)
        assert (row_b["client_contractor_id"] or "") == ""

    def test_set_contractor_empty_args_noop(self, storage):
        b = "B-SETC-3"
        sd_id = _seed_blocked_doc(b)
        assert ddb.set_sales_document_contractor(b, sd_id, "") == {
            "sales_documents_updated": 0, "sales_lines_updated": 0,
            "previous_contractor_id": "",
        }

    def test_set_contractor_same_value_still_reports_previous(self, storage):
        b = "B-SETC-SAME"
        sd_id = _seed_blocked_doc(b)
        ddb.set_sales_document_contractor(b, sd_id, CID_ACME)
        res = ddb.set_sales_document_contractor(b, sd_id, CID_ACME)
        # Re-assigning the same value still fires the UPDATE and discloses the
        # prior value (route layer derives overwrote_existing=False from this).
        assert res["previous_contractor_id"] == CID_ACME
        assert res["sales_documents_updated"] == 1


# ══════════════════════════════════════════════════════════════════════════════
# Phase A — route: assign + regenerate draft, block resolves
# ══════════════════════════════════════════════════════════════════════════════

class TestPhaseAAssignRoute:
    def test_assign_repairs_block_and_births_draft(self, client, storage, proforma_db):
        cli, _ = client
        b = "B-ASSIGN-1"
        sd_id = _seed_blocked_doc(b)
        # First sync (via backfill) records the contractor_missing block.
        cli.post(f"/api/v1/admin/contractor-projection/backfill/{b}")
        blocks = pildb.list_draft_birth_blocks(proforma_db, b)
        assert len(blocks) == 1 and blocks[0]["code"] == "contractor_missing"

        # Operator picks a Customer Master customer and assigns it.
        _add_customer(storage, CID_ACME, "ACME CORP")
        r = cli.post(
            f"/api/v1/admin/contractor-projection/assign/{b}",
            json={"sales_document_id": sd_id, "contractor_id": CID_ACME},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["canonical_name"] == "ACME CORP"
        assert body["assigned"]["sales_documents_updated"] == 1

        # Block resolved + draft born under the canonical name — no re-intake.
        assert body["open_blocks"] == []
        assert pildb.list_draft_birth_blocks(proforma_db, b) == []
        drafts = pildb.list_drafts_for_batch(proforma_db, b)
        assert len(drafts) == 1
        assert drafts[0].client_name == "ACME CORP"
        assert drafts[0].client_contractor_id == CID_ACME

    def test_assign_overwrite_discloses_previous(self, client, storage, proforma_db):
        cli, _ = client
        b = "B-ASSIGN-OW"
        # client_unresolved: a contractor is set at intake but has no CM record.
        ship = _register_sales_packing_doc(b, cid="OLD-CID")
        sd_id = _store_sales_doc(b, ship, client_name="", cid="OLD-CID")
        ddb.store_sales_packing_lines(sd_id, b, [_line(client_name="")])
        _add_customer(storage, CID_ACME, "ACME CORP")
        r = cli.post(
            f"/api/v1/admin/contractor-projection/assign/{b}",
            json={"sales_document_id": sd_id, "contractor_id": CID_ACME},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["overwrote_existing"] is True
        assert body["previous_contractor_id"] == "OLD-CID"
        assert body["open_blocks"] == []

    def test_assign_idempotent_double_call(self, client, storage, proforma_db):
        cli, _ = client
        b = "B-ASSIGN-IDEM"
        sd_id = _seed_blocked_doc(b)
        _add_customer(storage, CID_ACME, "ACME CORP")
        payload = {"sales_document_id": sd_id, "contractor_id": CID_ACME}
        r1 = cli.post(f"/api/v1/admin/contractor-projection/assign/{b}", json=payload)
        r2 = cli.post(f"/api/v1/admin/contractor-projection/assign/{b}", json=payload)
        assert r1.status_code == 200 and r2.status_code == 200, (r1.text, r2.text)
        # Re-assigning the same contractor must not spawn a second draft.
        drafts = pildb.list_drafts_for_batch(proforma_db, b)
        assert len(drafts) == 1
        assert pildb.list_draft_birth_blocks(proforma_db, b) == []

    def test_assign_rejects_contractor_without_cm_record(self, client, storage):
        cli, _ = client
        b = "B-ASSIGN-2"
        sd_id = _seed_blocked_doc(b)
        r = cli.post(
            f"/api/v1/admin/contractor-projection/assign/{b}",
            json={"sales_document_id": sd_id, "contractor_id": CID_NEW},
        )
        assert r.status_code == 400, r.text
        assert "Customer Master" in r.json()["detail"]

    def test_assign_rejects_unknown_sales_document(self, client, storage):
        cli, _ = client
        b = "B-ASSIGN-3"
        _seed_blocked_doc(b)
        _add_customer(storage, CID_ACME, "ACME CORP")
        r = cli.post(
            f"/api/v1/admin/contractor-projection/assign/{b}",
            json={"sales_document_id": "does-not-exist", "contractor_id": CID_ACME},
        )
        assert r.status_code == 404, r.text

    def test_assign_rejects_path_traversal(self, client):
        cli, _ = client
        r = cli.post(
            "/api/v1/admin/contractor-projection/assign/evil..seg",
            json={"sales_document_id": "x", "contractor_id": "y"},
        )
        assert r.status_code == 400, r.text

    def test_assign_rejects_empty_sales_document_id(self, client, storage):
        cli, _ = client
        b = "B-ASSIGN-E1"
        _add_customer(storage, CID_ACME, "ACME CORP")
        r = cli.post(
            f"/api/v1/admin/contractor-projection/assign/{b}",
            json={"sales_document_id": "  ", "contractor_id": CID_ACME},
        )
        assert r.status_code == 400, r.text

    def test_assign_rejects_empty_contractor_id(self, client, storage):
        cli, _ = client
        b = "B-ASSIGN-E2"
        sd_id = _seed_blocked_doc(b)
        r = cli.post(
            f"/api/v1/admin/contractor-projection/assign/{b}",
            json={"sales_document_id": sd_id, "contractor_id": ""},
        )
        assert r.status_code == 400, r.text


# ══════════════════════════════════════════════════════════════════════════════
# Phase C — invoice line-name authority enrichment
# ══════════════════════════════════════════════════════════════════════════════

class TestPhaseCInvoiceNameEnrichment:
    def test_enrich_uses_wfirma_goods_name_when_registered(self, storage):
        from app.api.routes_proforma import _enrich_invoice_line_names
        wfdb.upsert_product("PCX", wfirma_product_id="g-1",
                            product_name="Gold Ring 14K / Pierścionek")
        lines = [{"product_code": "PCX", "name_pl": "ignored"}]
        _enrich_invoice_line_names(lines)
        assert lines[0]["invoice_line_name"] == "Gold Ring 14K / Pierścionek"
        assert lines[0]["invoice_line_name_source"] == "wfirma_goods"

    def test_enrich_pending_when_not_registered(self, storage):
        from app.api.routes_proforma import _enrich_invoice_line_names
        lines = [{"product_code": "UNREG", "name_pl": "Local label"}]
        _enrich_invoice_line_names(lines)
        assert lines[0]["invoice_line_name"] == ""
        assert lines[0]["invoice_line_name_source"] == "pending_registration"

    def test_enrich_handles_blank_product_code(self, storage):
        from app.api.routes_proforma import _enrich_invoice_line_names
        lines = [{"product_code": "", "name_pl": "x"}]
        _enrich_invoice_line_names(lines)
        assert lines[0]["invoice_line_name_source"] == "pending_registration"

    def test_draft_get_includes_invoice_line_name(self, client, storage, proforma_db):
        cli, _ = client
        wfdb.upsert_product("PCX", wfirma_product_id="g-2",
                            product_name="Diamond Pendant")
        # Seed a draft with one registered + one unregistered line.
        with sqlite3.connect(str(proforma_db)) as conn:
            pildb._ensure_drafts_table(conn)
            now = pildb._now_utc_iso()
            cur = conn.execute(
                "INSERT INTO proforma_drafts (batch_id, client_name, status, "
                "currency, draft_state, draft_version, source_lines_json, "
                "editable_lines_json, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                ("B-CDRAFT", "ACME", "draft", "EUR", "editing", 1, "[]",
                 '[{"product_code":"PCX","qty":1},{"product_code":"UNREG","qty":1}]',
                 now, now),
            )
            draft_id = int(cur.lastrowid)
        r = cli.get(f"/api/v1/proforma/draft/{draft_id}")
        assert r.status_code == 200, r.text
        lines = r.json()["draft"]["editable_lines"]
        reg = next(l for l in lines if l["product_code"] == "PCX")
        unreg = next(l for l in lines if l["product_code"] == "UNREG")
        assert reg["invoice_line_name"] == "Diamond Pendant"
        assert reg["invoice_line_name_source"] == "wfirma_goods"
        assert unreg["invoice_line_name"] == ""
        assert unreg["invoice_line_name_source"] == "pending_registration"

    def test_preview_shows_wfirma_goods_name_when_registered(self, client, storage, proforma_db):
        cli, _ = client
        wfdb.upsert_product("PCX", wfirma_product_id="g-3", product_name="Gold Ring 14K")
        draft_id = _seed_draft_with_lines(
            proforma_db, "B-PREV-1",
            '[{"product_code":"PCX","qty":1,"unit_price":10}]')
        r = cli.get(f"/api/v1/proforma/draft/{draft_id}/preview.html")
        assert r.status_code == 200, r.text
        # The printable preview shows the customer-facing wFirma goods name.
        assert "Gold Ring 14K" in r.text

    def test_preview_falls_back_to_bilingual_when_unregistered(self, client, storage, proforma_db):
        cli, _ = client
        draft_id = _seed_draft_with_lines(
            proforma_db, "B-PREV-2",
            '[{"product_code":"UNREG","qty":1,"unit_price":10,'
            '"description_pl":"Pierscionek","description_en":"Ring"}]')
        r = cli.get(f"/api/v1/proforma/draft/{draft_id}/preview.html")
        assert r.status_code == 200, r.text
        # Not registered → falls back to the bilingual customs sentence.
        assert "Pierscionek" in r.text or "Ring" in r.text


# ══════════════════════════════════════════════════════════════════════════════
# Backend source contracts (no external surfaces, endpoint present)
# ══════════════════════════════════════════════════════════════════════════════

class TestBackendSourceContracts:
    def test_assign_endpoint_present_and_local_only(self):
        src = ROUTES_CP.read_text(encoding="utf-8")
        assert '@router.post("/assign/{batch_id}")' in src
        assert "set_sales_document_contractor" in src
        # Repair surface must stay local-DB only.
        start = src.index("def assign_contractor_to_blocked_record(")
        body = src[start:start + 4000]
        for forbidden in ("requests.", "httpx.", "wfirma_client",
                          "smtplib", "send_email", "queue_email"):
            assert forbidden not in body, f"assign must not reference {forbidden!r}"

    def test_set_contractor_helper_present(self):
        assert "def set_sales_document_contractor(" in DOC_DB.read_text(encoding="utf-8")

    def test_invoice_name_enrichment_present_on_both_surfaces(self):
        src = ROUTES_PF.read_text(encoding="utf-8")
        assert "def _enrich_invoice_line_names(" in src
        # Used by both the editor GET and the printable preview.
        assert src.count("_enrich_invoice_line_names(") >= 3  # def + 2 call sites


# ══════════════════════════════════════════════════════════════════════════════
# Frontend source contracts (shipment-detail.html)
# ══════════════════════════════════════════════════════════════════════════════

class TestFrontendContracts:
    @pytest.fixture(scope="class")
    def html(self) -> str:
        return HTML.read_text(encoding="utf-8")

    # Phase A — resolver wired into the blocked panel
    def test_phase_a_blocked_resolver_present(self, html):
        assert "function ProformaBlockedRecordResolver(" in html
        assert "/api/v1/admin/contractor-projection/assign/" in html
        assert "<ProformaBlockedRecordResolver" in html
        assert "proforma-blocked-assign-btn-" in html
        assert "proforma-blocked-search-input-" in html

    # Phase B — customer controls ABOVE the lines
    def test_phase_b_customer_controls_above_lines(self, html):
        i_summary = html.index('data-testid="draft-customer-authority-summary"')
        i_billto = html.index('testid="draft-bill-to-picker-top"')
        i_overrides = html.index('data-testid="draft-overrides-summary"')
        i_lines = html.index('data-testid="draft-lines-table"')
        i_charges = html.index('data-testid="draft-charges-table"')
        assert i_summary < i_billto < i_lines, "Bill-to picker must precede lines"
        assert i_billto < i_overrides < i_lines, (
            "order within the customer block: Bill-to picker → Buyer/Ship-to/"
            "Payment overrides, both above lines")
        assert i_lines < i_charges, "lines still precede service charges"

    def test_phase_b_overrides_not_duplicated(self, html):
        # The move must not leave a duplicate overrides block behind.
        assert html.count('data-testid="draft-overrides-summary"') == 1
        assert html.count('testid="draft-bill-to-picker-top"') == 1

    # Phase C — line renderer surfaces the invoice authority, honestly labelled
    def test_phase_c_invoice_authority_renderer(self, html):
        assert "line.invoice_line_name" in html
        assert "invoice (wFirma)" in html
        assert "pending registration" in html

    # Phase D — freight block is persistent + actionable
    def test_phase_d_freight_block_actionable(self, html):
        assert "setFreightBlock" in html
        assert 'data-testid="freight-block-reason"' in html
        assert "freight_fixed_amount_" in html

    # Phase E — reservation save entry reconnected + remedy map
    def test_phase_e_reservation_save_and_remedy(self, html):
        assert "function ReservationSavePanel(" in html
        assert "<ReservationSavePanel" in html
        assert "reservation-save-btn-" in html
        assert "RESERVATION_REMEDIES" in html
        assert "function reservationRemedy(" in html
