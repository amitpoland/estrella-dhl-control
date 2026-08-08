"""Permanent pins: Incoterm hierarchy + early wFirma product converge.

Covers:
  * resolve_incoterm: draft → CM default → unset (never invents DAP)
  * CM default_incoterm seeds blank editable drafts; locked drafts untouched
  * readiness dedupes warehouse+§3 duplicate mapping blockers
  * repair hint for create-disabled is NOT sales-price
  * converge_products_for_batch: exists→reuse (mirror), missing→blocked when
    flag off, create once when flag on + PL/EN ready
  * idempotent re-run / no duplicate invent
"""
from __future__ import annotations

import inspect
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import patch

import pytest

from app.services.commercial_authority import (
    resolve_incoterm,
    seed_blank_draft_incoterms,
)
from app.services import customer_master_db as cmdb
from app.services import document_db as ddb
from app.services import proforma_invoice_link_db as pildb
from app.services import reservation_db as rdb
from app.services import wfirma_db as wfdb
from app.services import wfirma_product_auto_register as wfar


# ── Incoterm resolver ───────────────────────────────────────────────────────

def test_resolve_incoterm_hierarchy_never_invents():
    assert resolve_incoterm("dap", "EXW") == {"value": "DAP", "source": "draft"}
    assert resolve_incoterm(None, "exw") == {"value": "EXW", "source": "customer_master"}
    assert resolve_incoterm("", "") == {"value": None, "source": "unset"}
    assert resolve_incoterm(None, None) == {"value": None, "source": "unset"}
    assert resolve_incoterm("", None)["value"] is None


@pytest.fixture()
def storage(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    monkeypatch.setenv("PZ_STORAGE_ROOT", str(tmp_path))
    from app.core.config import settings
    monkeypatch.setattr(settings, "storage_root", tmp_path, raising=False)
    monkeypatch.setattr(settings, "wfirma_create_product_allowed", False, raising=False)
    ddb.init_document_db(tmp_path / "documents.db")
    pildb.init_db(tmp_path / "proforma_links.db")
    cmdb.init_db(tmp_path / "customer_master.sqlite")
    rdb.init_reservation_db(tmp_path / "reservation_queue.db")
    wfdb.init_wfirma_db(tmp_path / "wfirma.db")
    return tmp_path


def _mk_cm(storage: Path, contractor_id: str, *, default_incoterm: Optional[str] = "DAP"):
    c = cmdb.CustomerMaster(
        bill_to_contractor_id=contractor_id,
        bill_to_name="Test Client Sp. z o.o.",
        country="PL",
        default_incoterm=default_incoterm,
    )
    cmdb.upsert_customer(storage / "customer_master.sqlite", c)


def _seed_invoice_lines(documents_db: Path, batch_id: str,
                        rows: List[Tuple[str, str]]) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(str(documents_db)) as con:
        for i, (pc, desc) in enumerate(rows):
            con.execute(
                """INSERT INTO invoice_lines
                   (id, document_id, batch_id, invoice_no, line_position,
                    product_code, description, quantity, unit_price, total_value,
                    currency, hs_code, created_at, gross_weight, net_weight,
                    rate_usd, amount_usd, hsn_code)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (str(uuid.uuid4()), "doc-1", batch_id, "EJL/26-27/493",
                 i + 1, pc, desc, 1.0, 100.0, 100.0,
                 "EUR", "", now, 0.0, 0.0,
                 100.0, 100.0, ""),
            )


def test_seed_blank_incoterm_from_cm_editable_only(storage):
    _mk_cm(storage, "C-100", default_incoterm="EXW")
    d, created = pildb.auto_create_draft_from_sales_packing(
        storage / "proforma_links.db",
        batch_id="BATCH_INC_TEST",
        client_name="Test Client Sp. z o.o.",
        currency="EUR",
        lines=[{
            "product_code": "EJL/26-27/493-1",
            "design_no": "JR00001",
            "qty": 1, "unit_price": 10.0, "currency": "EUR",
        }],
        operator="test",
        client_contractor_id="C-100",
    )
    assert created
    # Birth may already seed EXW — clear to exercise the repair helper
    with sqlite3.connect(str(storage / "proforma_links.db")) as con:
        con.execute(
            "UPDATE proforma_drafts SET draft_state='editing', incoterm=NULL WHERE id=?",
            (d.id,),
        )
    d = pildb.get_draft_by_id(storage / "proforma_links.db", d.id)
    assert not (d.incoterm or "").strip()

    res = seed_blank_draft_incoterms(
        "BATCH_INC_TEST",
        proforma_db=storage / "proforma_links.db",
        operator="test",
    )
    assert len(res["seeded"]) == 1
    assert res["seeded"][0]["incoterm"] == "EXW"
    d2 = pildb.get_draft_by_id(storage / "proforma_links.db", d.id)
    assert d2.incoterm == "EXW"


def test_seed_skips_posted_drafts(storage):
    _mk_cm(storage, "C-100", default_incoterm="DAP")
    d, created = pildb.auto_create_draft_from_sales_packing(
        storage / "proforma_links.db",
        batch_id="BATCH_POSTED_INC",
        client_name="Posted Client",
        currency="EUR",
        lines=[{
            "product_code": "EJL/26-27/493-1",
            "design_no": "JR00001",
            "qty": 1, "unit_price": 10.0, "currency": "EUR",
        }],
        operator="test",
        client_contractor_id="C-100",
    )
    assert created
    with sqlite3.connect(str(storage / "proforma_links.db")) as con:
        # Both columns required — read shim remaps draft_state='posted' back
        # to 'draft' when legacy status is still 'draft'.
        con.execute(
            "UPDATE proforma_drafts SET status='posted', draft_state='posted', "
            "incoterm=NULL WHERE id=?",
            (d.id,),
        )
    res = seed_blank_draft_incoterms(
        "BATCH_POSTED_INC",
        proforma_db=storage / "proforma_links.db",
        operator="test",
    )
    assert res["seeded"] == []
    assert any(s.get("reason") == "locked_state" for s in res["skipped"])
    d2 = pildb.get_draft_by_id(storage / "proforma_links.db", d.id)
    assert not (d2.incoterm or "").strip()


def test_seed_does_not_overwrite_saved_draft_incoterm(storage):
    _mk_cm(storage, "C-100", default_incoterm="DAP")
    d, created = pildb.auto_create_draft_from_sales_packing(
        storage / "proforma_links.db",
        batch_id="BATCH_SAVED_INC",
        client_name="Saved Client",
        currency="EUR",
        lines=[{
            "product_code": "EJL/26-27/493-1",
            "design_no": "JR00001",
            "qty": 1, "unit_price": 10.0, "currency": "EUR",
        }],
        operator="test",
        client_contractor_id="C-100",
    )
    assert created
    pildb.update_draft_fields(
        storage / "proforma_links.db", d.id,
        {"incoterm": "FOB"},
        operator="test",
        expected_updated_at=d.updated_at,
    )
    res = seed_blank_draft_incoterms(
        "BATCH_SAVED_INC",
        proforma_db=storage / "proforma_links.db",
        operator="test",
    )
    assert res["seeded"] == []
    d2 = pildb.get_draft_by_id(storage / "proforma_links.db", d.id)
    assert d2.incoterm == "FOB"


def test_birth_seeds_cm_default_incoterm(storage):
    _mk_cm(storage, "C-200", default_incoterm="CIP")
    d, created = pildb.auto_create_draft_from_sales_packing(
        storage / "proforma_links.db",
        batch_id="BATCH_BIRTH_INC",
        client_name="Birth Client",
        currency="EUR",
        lines=[{
            "product_code": "EJL/26-27/493-2",
            "design_no": "JR00002",
            "qty": 1, "unit_price": 20.0, "currency": "EUR",
        }],
        operator="test",
        client_contractor_id="C-200",
    )
    assert created
    assert d.incoterm == "CIP"


# ── Readiness blocker dedupe + repair hints ──────────────────────────────────

def test_repair_hint_create_disabled_not_sales_price():
    from app.api.routes_proforma import _repair_hint_for_blocker
    hint = _repair_hint_for_blocker(
        "wfirma_create_product_allowed is false — operator must enable "
        "WFIRMA_CREATE_PRODUCT_ALLOWED to create"
    )
    assert "sales price" not in hint.lower()
    assert "WFIRMA_CREATE_PRODUCT_ALLOWED" in hint


def test_repair_hint_stale_authority_not_sales_price():
    from app.api.routes_proforma import _repair_hint_for_blocker
    hint = _repair_hint_for_blocker(
        "STALE_AUTHORITY_REFUSED — non-authority description source"
    )
    assert "sales price" not in hint.lower()


def test_readiness_skips_duplicate_warehouse_unresolved_blocker():
    from app.api import routes_proforma as rp
    src = inspect.getsource(rp._derive_draft_readiness)
    assert "unresolved in wfirma_products" in src
    assert "not matched in wfirma_products" in src


# ── Product converge: reuse / block / create once ────────────────────────────

class _FakeGood:
    def __init__(self, wid: str, name: str = "Pierścionek", unit: str = "szt."):
        self.wfirma_id = wid
        self.name = name
        self.unit = unit
        self.code = ""


def test_converge_reuses_existing_wfirma_product_into_mirror(storage, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "wfirma_create_product_allowed", False, raising=False)

    batch_id = "BATCH_REUSE"
    _seed_invoice_lines(storage / "documents.db", batch_id, [
        ("EJL/26-27/493-1", "PCS, 14KT Gold RING"),
    ])
    ddb.upsert_product_description(
        product_code="EJL/26-27/493-1",
        item_type="RING",
        name_pl="Pierścionek złoty",
        description_pl="Pierścionek złoty",
        material_pl="złoto",
        purpose_pl="biżuteria",
        description_block="Pierścionek złoty",
        description_en="Gold ring",
        description_line="Pierścionek złoty",
    )

    with patch("app.services.wfirma_client.get_product_by_code",
               return_value=_FakeGood("999001")):
        res = wfar.converge_products_for_batch(
            batch_id, operator="test", auto_adopt_exact=True,
        )

    assert any(r.get("status") == "existing_mapped" for r in res["results"])
    assert res.get("auto_adopted") or res["existing_mapped"] >= 1
    mirror = rdb.get_mirror_product(
        storage / "reservation_queue.db", "EJL/26-27/493-1",
    )
    assert mirror is not None
    assert (mirror.get("wfirma_id") or "").strip() == "999001"

    with patch("app.services.wfirma_client.get_product_by_code",
               return_value=_FakeGood("999001")), \
         patch("app.services.wfirma_client.create_product") as m_create:
        res2 = wfar.converge_products_for_batch(
            batch_id, operator="test", auto_adopt_exact=True,
        )
    m_create.assert_not_called()
    assert any(r.get("status") == "existing_mapped" for r in res2["results"])


def test_converge_blocked_when_create_flag_off_and_missing(storage, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "wfirma_create_product_allowed", False, raising=False)

    batch_id = "BATCH_BLOCK"
    _seed_invoice_lines(storage / "documents.db", batch_id, [
        ("EJL/26-27/493-9", "PCS, 14KT Gold RING"),
    ])
    ddb.upsert_product_description(
        product_code="EJL/26-27/493-9",
        item_type="RING",
        name_pl="Pierścionek",
        description_pl="Pierścionek",
        material_pl="złoto",
        purpose_pl="biżuteria",
        description_block="Pierścionek",
        description_en="Ring",
        description_line="Pierścionek",
    )

    with patch("app.services.wfirma_client.get_product_by_code", return_value=None), \
         patch("app.services.wfirma_client.create_product") as m_create:
        res = wfar.converge_products_for_batch(batch_id, operator="test")

    m_create.assert_not_called()
    assert res["blocked"] >= 1
    assert any("wfirma_create_product_allowed" in (r.get("error") or "")
               for r in res["results"])
    assert any("wfirma_create_product_allowed" in br
               for br in (res.get("blocked_reasons") or []))


def test_converge_create_once_when_allowed_and_pl_en_ready(storage, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "wfirma_create_product_allowed", True, raising=False)

    batch_id = "BATCH_CREATE"
    _seed_invoice_lines(storage / "documents.db", batch_id, [
        ("EJL/26-27/493-3", "PCS, 14KT Gold RING"),
    ])
    ddb.upsert_product_description(
        product_code="EJL/26-27/493-3",
        item_type="RING",
        name_pl="Pierścionek złoty 14K",
        description_pl="Pierścionek złoty 14K",
        material_pl="złoto",
        purpose_pl="biżuteria",
        description_block="Pierścionek złoty 14K",
        description_en="14K gold ring",
        description_line="Pierścionek złoty 14K",
    )

    created = _FakeGood("888001", name="Pierścionek złoty 14K")
    with patch("app.services.wfirma_client.get_product_by_code", return_value=None), \
         patch("app.services.wfirma_client.create_product", return_value=created) as m_create, \
         patch("app.services.wfirma_client.find_vat_code_id", return_value=1):
        res = wfar.converge_products_for_batch(batch_id, operator="test")
        res2 = wfar.converge_products_for_batch(batch_id, operator="test")

    assert m_create.call_count == 1
    assert res["created"] >= 1
    assert any(r.get("status") == "existing_mapped" for r in res2["results"])
    mirror = rdb.get_mirror_product(
        storage / "reservation_queue.db", "EJL/26-27/493-3",
    )
    assert (mirror or {}).get("wfirma_id") == "888001"
    pm = rdb.get_product_master(storage / "reservation_queue.db", "EJL/26-27/493-3")
    assert pm is not None
    assert pm.get("status") == "mapped"


def test_converge_blocks_create_without_pl_en(storage, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "wfirma_create_product_allowed", True, raising=False)

    batch_id = "BATCH_NODESC"
    _seed_invoice_lines(storage / "documents.db", batch_id, [
        ("EJL/26-27/493-8", "PCS RING"),
    ])

    with patch("app.services.wfirma_client.get_product_by_code", return_value=None), \
         patch("app.services.wfirma_client.create_product") as m_create:
        res = wfar.converge_products_for_batch(batch_id, operator="test")

    m_create.assert_not_called()
    assert res["blocked"] >= 1
    assert any("canonical PL/EN" in (r.get("error") or "") for r in res["results"])


def test_adopt_exact_refuses_invented_id(storage):
    res = wfar.adopt_exact_product_code("NO-SUCH-CODE")
    assert res["ok"] is False
    assert "refuse invent" in (res.get("error") or "")
