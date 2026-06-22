"""test_product_code_design_no_authority.py

Pins the product_code / design_no authority model for wFirma product
resolution (AWB 9158478722 class):

  * product_code (e.g. EJL/26-27/290-1) is the SOLE wFirma identity key —
    goods/find AND goods/add use product_code only.
  * design_no (e.g. JR02075-0.50) is the cross-document MATCHING/metadata key;
    it is surfaced alongside product_code but is NEVER sent to wFirma.
  * design_no is enriched (read-only) from packing_lines; a row without a
    design_no is flagged design_linkage="incomplete" and is NOT auto-created.

These tests lock the model so it can never regress to "search/create wFirma by
design_no" (the inverted model).
"""
from __future__ import annotations

import sys
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

_SVC = Path(__file__).resolve().parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

from app.services import wfirma_product_auto_register as war   # noqa: E402

_SRC = (_SVC / "app" / "services" / "wfirma_product_auto_register.py").read_text(encoding="utf-8")


def _inv(*pcs):
    return [{"product_code": pc, "description": f"PCS, 14KT Gold {pc}"} for pc in pcs]


def _pack(mapping):
    return [{"product_code": pc, "design_no": dn} for pc, dn in mapping.items()]


def _patches(inv_rows, pack_map):
    """Common patch set: invoice rows, packing design_no map, empty local DB."""
    return [
        patch("app.services.document_db.get_invoice_lines_for_batch", return_value=inv_rows),
        patch("app.services.packing_db._db_path", "x"),
        patch("app.services.packing_db.get_packing_lines_for_batch", return_value=_pack(pack_map)),
        patch("app.services.wfirma_db.get_product", return_value=None),
    ]


# ── goods/find uses product_code, never design_no ───────────────────────────

def test_goodsfind_uses_product_code_not_design_no():
    calls = []
    ps = _patches(
        _inv("EJL/26-27/290-1", "EJL/26-27/290-2"),
        {"EJL/26-27/290-1": "JR02075-0.50", "EJL/26-27/290-2": "JE03748"},
    )
    ps.append(patch("app.services.wfirma_client.get_product_by_code",
                    side_effect=lambda code: (calls.append(code) or None)))
    with ps[0], ps[1], ps[2], ps[3], ps[4]:
        res = war.ensure_products_for_batch("BATCH", dry_run=True)

    # wFirma searched by the EJL product_codes — NEVER by the design_no.
    assert "EJL/26-27/290-1" in calls and "EJL/26-27/290-2" in calls
    assert "JR02075-0.50" not in calls and "JE03748" not in calls
    # genuinely missing (searched by the right key, just not in wFirma yet)
    assert res["missing"] == 2 and res["pending_adoption"] == 0


def test_design_no_surfaced_as_metadata_with_linkage_flag():
    ps = _patches(
        _inv("EJL/26-27/290-1", "EJL/26-27/293-1"),
        {"EJL/26-27/290-1": "JR02075-0.50"},   # 293-1 has NO design_no in packing
    )
    ps.append(patch("app.services.wfirma_client.get_product_by_code", return_value=None))
    with ps[0], ps[1], ps[2], ps[3], ps[4]:
        res = war.ensure_products_for_batch("BATCH", dry_run=True)
    by = {r["product_code"]: r for r in res["results"]}
    # design_no carried as metadata next to product_code
    assert by["EJL/26-27/290-1"]["design_no"] == "JR02075-0.50"
    assert by["EJL/26-27/290-1"]["design_linkage"] == "linked"
    # missing design_no → incomplete linkage (item 6); still keyed on product_code
    assert by["EJL/26-27/293-1"]["design_no"] == ""
    assert by["EJL/26-27/293-1"]["design_linkage"] == "incomplete"


def test_missing_design_no_does_not_auto_create():
    # dry-run with no design_no must report missing, never create.
    created = []
    ps = _patches(_inv("EJL/26-27/293-1"), {})   # no packing design_no
    ps.append(patch("app.services.wfirma_client.get_product_by_code", return_value=None))
    ps.append(patch("app.services.wfirma_client.create_product",
                    side_effect=lambda **kw: created.append(kw)))
    with ps[0], ps[1], ps[2], ps[3], ps[4], ps[5]:
        res = war.ensure_products_for_batch("BATCH", dry_run=True)
    assert res["missing"] == 1 and res["created"] == 0
    assert created == []   # no wFirma create attempted in dry-run


# ── goods/add (create) uses product_code, never design_no ───────────────────

def test_create_and_add_uses_product_code_not_design_no():
    created = {}
    fake = MagicMock(); fake.wfirma_id = "999"; fake.name = "Pierscionek"; fake.unit = "szt."
    ps = _patches(_inv("EJL/26-27/290-1"), {"EJL/26-27/290-1": "JR02075-0.50"})
    ps += [
        patch("app.services.wfirma_client.get_product_by_code", return_value=None),
        patch("app.services.description_engine.get_description_block",
              return_value={"description_line": "Pierscionek", "name_pl": "Pierscionek",
                            "description_block": "block"}),
        patch("app.services.wfirma_client.find_vat_code_id", return_value="vat23"),
        patch("app.services.wfirma_client.create_product",
              side_effect=lambda **kw: (created.update(kw) or fake)),
        patch("app.services.wfirma_db.upsert_product", return_value="id"),
        patch.object(war.settings, "wfirma_create_product_allowed", True),
    ]
    with ExitStack() as stack:
        for p in ps:
            stack.enter_context(p)
        res = war.ensure_products_for_batch("BATCH", dry_run=False)
    # created in wFirma under the EJL product_code — NOT the design_no.
    assert created.get("product_code") == "EJL/26-27/290-1"
    assert created.get("product_code") != "JR02075-0.50"
    assert res["created"] == 1


# ── AWB 9158478722 fixture: 31 EJL codes searched by product_code ───────────

def test_awb_9158478722_all_searched_by_product_code_and_carry_design_no():
    codes = [f"EJL/26-27/{n}" for n in
             ("290-1", "290-2", "291-1", "291-2", "291-3", "291-4", "291-5",
              "292-1", "292-2", "292-3", "293-1")]
    pmap = {c: f"JR{i:05d}" for i, c in enumerate(codes)}
    calls = []
    ps = _patches(_inv(*codes), pmap)
    ps.append(patch("app.services.wfirma_client.get_product_by_code",
                    side_effect=lambda code: (calls.append(code) or None)))
    with ps[0], ps[1], ps[2], ps[3], ps[4]:
        res = war.ensure_products_for_batch("BATCH_9158478722", dry_run=True)
    # every lookup used the EJL product_code; no design_no ever used as the key
    assert sorted(calls) == sorted(codes)
    assert not any(c.startswith("JR0") for c in calls)
    # each result carries its design_no as metadata + linked
    assert all(r["design_no"].startswith("JR0") and r["design_linkage"] == "linked"
               for r in res["results"])


# ── Source guards ───────────────────────────────────────────────────────────

def test_source_identity_rule_product_code_only():
    # wFirma calls keyed on product_code
    assert "wfirma_client.get_product_by_code(product_code)" in _SRC
    assert "product_code = product_code" in _SRC          # create_product kwarg
    # design_no is carried but never handed to a wFirma call
    assert "design_no" in _SRC
    assert "get_product_by_code(design_no)" not in _SRC
    assert "create_product(\n            product_code = design_no" not in _SRC
