# -*- coding: utf-8 -*-
"""Repair step for browser verification (scratch fixture storage only):
1. Match both products in wfirma_products (the 'register in wFirma' repair).
2. Add the buyer's EU VAT number to Customer Master (the WDT repair).
Mirrors the repair path the operator will perform on production data.
"""
import os
import sys
from pathlib import Path

SERVICE = Path(r"C:\PZ-wt-readiness\service")
sys.path.insert(0, str(SERVICE))

SCRATCH = Path(os.environ["STORAGE_ROOT"]).resolve()

from app.core.config import settings  # noqa: E402

assert Path(settings.storage_root).resolve() == SCRATCH

from app.services import customer_master_db as cmdb  # noqa: E402
from app.services import wfirma_db as wfdb  # noqa: E402

CLIENT = "BROWSER VERIFY CLIENT"
CONTRACTOR_ID = "195596259"

# upsert_product silently no-ops while _db_path is None — bind it first.
wfdb.init_wfirma_db(SCRATCH / "wfirma.db")

for i, pc in enumerate(("EJL/26-27/257-2", "EJL/26-27/257-4"), start=1):
    wfdb.upsert_product(
        product_code=pc,
        wfirma_product_id=str(100 + i),
        sync_status="matched",
    )
    print(f"matched {pc} -> wfirma_product_id={100 + i}")

cm_db = SCRATCH / "customer_master.sqlite"
cmdb.init_db(cm_db)
cmdb.upsert_customer(cm_db, cmdb.CustomerMaster(
    bill_to_contractor_id=CONTRACTOR_ID,
    bill_to_name=CLIENT,
    country="SK",
    vat_eu_number="SK2120999999",
    vat_eu_valid=True,
))
print("customer master: vat_eu_number=SK2120999999 vat_eu_valid=True")
