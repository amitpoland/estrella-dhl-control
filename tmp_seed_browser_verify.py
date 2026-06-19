# -*- coding: utf-8 -*-
"""Seed scratch storage for browser verification of the proforma readiness
single-authority campaign.  STORAGE_ROOT env var must point at the scratch
dir BEFORE this script runs.  Mirrors the fixtures in
service/tests/test_proforma_readiness_single_authority.py.

Creates:
  Draft "#32-shape": status=approved, ambiguous design (1 design_no -> 2
      product_codes), 0 wfirma_products matches, SK buyer with blank EU VAT
      (WDT context)  -> Approved + blockers (the production invalid state).
  Draft "#33-shape": status=post_failed, same blockers.

Inventory state IS seeded via legal engine transitions so the only
blockers are the 3 repairable classes (ambiguity / product mapping / VAT).
"""
import json
import os
import sqlite3
import sys
import uuid
from pathlib import Path

SERVICE = Path(r"C:\PZ-wt-readiness\service")
sys.path.insert(0, str(SERVICE))

SCRATCH = Path(os.environ["STORAGE_ROOT"]).resolve()

from app.core.config import settings  # noqa: E402

assert Path(settings.storage_root).resolve() == SCRATCH, (
    f"settings.storage_root={settings.storage_root!r} != STORAGE_ROOT={SCRATCH!r}"
)

from app.services import customer_master_db as cmdb  # noqa: E402
from app.services import document_db as ddb  # noqa: E402
from app.services import inventory_state_engine as ise  # noqa: E402
from app.services import packing_db as pdb  # noqa: E402
from app.services import proforma_invoice_link_db as pildb  # noqa: E402
from app.services import warehouse_db as wdb  # noqa: E402
from app.services import wfirma_db as wfdb  # noqa: E402

BATCH = "BATCH_BROWSER_VERIFY"
CLIENT = "BROWSER VERIFY CLIENT"
DESIGN = "J4007R08118-0.6"
CODE_A = "EJL/26-27/257-2"
CODE_B = "EJL/26-27/257-4"
CONTRACTOR_ID = "195596259"

pdb.init_packing_db(SCRATCH / "packing.db")
ddb.init_document_db(SCRATCH / "documents.db")
wfdb.init_wfirma_db(SCRATCH / "wfirma.db")
pildb.init_db(SCRATCH / "proforma_links.db")
wdb.init_warehouse_db(SCRATCH / "warehouse.db")

out = SCRATCH / "outputs" / BATCH
(out / "source").mkdir(parents=True, exist_ok=True)
(out / "audit.json").write_text(
    json.dumps({"batch_id": BATCH, "tracking_no": BATCH, "awb": BATCH,
                "carrier": "DHL", "timeline": []}),
    encoding="utf-8",
)


def packing_row(product_code, design_no, pos):
    return {
        "batch_id": BATCH,
        "invoice_no": "INV/BROWSER",
        "invoice_line_position": pos,
        "product_code": product_code,
        "design_no": design_no,
        "bag_id": "", "tray_id": "", "item_type": "RNG",
        "uom": "PCS", "quantity": 1.0, "gross_weight": 0.0,
        "net_weight": 0.0, "metal": "", "karat": "", "stone_type": "",
        "remarks": "", "extracted_confidence": 1.0,
        "requires_manual_review": False, "pack_sr": float(pos),
        "unit_price": 50.0, "total_value": 50.0,
    }


rows = [packing_row(CODE_A, DESIGN, 1), packing_row(CODE_B, DESIGN, 2)]
pdb.upsert_packing_lines(rows)

# Stock readiness: legal path None -> PURCHASE_TRANSIT -> WAREHOUSE_STOCK
for row in rows:
    scan = pdb._compute_scan_code(row)
    for to_state in (ise.PURCHASE_TRANSIT, ise.WAREHOUSE_STOCK):
        ise.transition(
            scan_code=scan, to_state=to_state,
            product_code=row["product_code"], design_no=DESIGN,
            batch_id=BATCH, operator="browser-verify-seed",
        )

sd = ddb.store_sales_document(
    batch_id=BATCH,
    document_id=str(uuid.uuid4()),
    data={"client_name": CLIENT, "client_ref": "REF-BROWSER",
          "sales_doc_no": "SO-BROWSER"},
)
ddb.store_sales_packing_lines(sd, BATCH, [{
    "client_name": CLIENT,
    "client_ref": "REF-BROWSER",
    "product_code": pc,
    "design_no": DESIGN,
    "bag_id": "", "quantity": 1.0, "remarks": "",
    "unit_price": 100.0, "total_value": 100.0,
    "currency": "EUR", "price_source": "packing_list",
} for pc in (CODE_A, CODE_B)])

wfdb.upsert_customer(
    client_name=CLIENT,
    wfirma_customer_id="7",
    country="BG",
    vat_id="",
    match_status="matched",
)
# NOTE: products deliberately NOT matched in wfirma_products.

cm_db = SCRATCH / "customer_master.sqlite"
cmdb.init_db(cm_db)
cmdb.upsert_customer(cm_db, cmdb.CustomerMaster(
    bill_to_contractor_id=CONTRACTOR_ID,
    bill_to_name=CLIENT,
    country="SK",
    vat_eu_number=None,
    vat_eu_valid=None,
))


def line(product_code):
    return {"line_id": str(uuid.uuid4()), "product_code": product_code,
            "name_pl": "Pierscionek zloty", "unit_price": 100.0,
            "quantity": 1.0, "currency": "EUR"}


def seed_draft(status, clone_generation):
    db = SCRATCH / "proforma_links.db"
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
            (BATCH, CLIENT, status, "EUR", status,
             None, "",
             "[]", json.dumps([line(CODE_A), line(CODE_B)]), "[]",
             clone_generation, 1),
        )
        conn.commit()
        return cur.lastrowid


d32 = seed_draft("approved", 0)      # 32-shape: Approved + blockers
d33 = seed_draft("post_failed", 1)   # 33-shape: post_failed + blockers

print(json.dumps({"draft32_id": d32, "draft33_id": d33,
                  "batch": BATCH, "client": CLIENT,
                  "storage": str(SCRATCH)}))
