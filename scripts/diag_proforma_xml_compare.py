"""
Inspection-only: render the current 12-line Juliany invoices/add payload
and diff its per-line field set against the persisted 1-line proforma
on wFirma. Reads only — no live writes.
"""
from __future__ import annotations
import os, sys, xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "service"))
env_path = ROOT / "service" / ".env"
if env_path.exists():
    for raw in env_path.read_text().splitlines():
        ln = raw.strip()
        if not ln or ln.startswith("#") or "=" not in ln: continue
        k, _, v = ln.partition("=")
        v = v.split("#", 1)[0].strip().strip('"').strip("'")
        os.environ.setdefault(k.strip(), v)

from app.core.config import settings
from app.services import document_db as ddb, packing_db as pdb
from app.services import warehouse_db as wdb, wfirma_db as wfdb
from app.services import wfirma_client as wf
from app.api import routes_proforma as rp

storage = Path(getattr(settings, "storage_root"))
ddb.init_document_db(storage / "documents.db")
pdb.init_packing_db(storage / "packing.db")
wdb.init_warehouse_db(storage / "warehouse.db")
wfdb.init_wfirma_db(storage / "wfirma.db")

BATCH  = "SHIPMENT_3369800350_2026-05_e31a0999"
CLIENT = "Juliany EOOD"
WID    = "465611619"

# Build today's request + XML
preview = rp._build_preview(BATCH, CLIENT)
req     = rp._build_proforma_request(preview)
xml     = wf._build_proforma_xml(req)

print(f"Preview line count       : {len(preview.get('lines', []))}")
print(f"Request line count       : {len(req.lines)}")

# Validate XML well-formedness + structural shape
try:
    root = ET.fromstring(xml)
    api_kids = [c.tag for c in root]
    invoices = root.find("invoices")
    invoice  = invoices.find("invoice") if invoices is not None else None
    contents = invoice.find("invoicecontents") if invoice is not None else None
    sent_lines = contents.findall("invoicecontent") if contents is not None else []
    print(f"XML invoicecontent count : {len(sent_lines)}")
    nesting_ok = (
        api_kids == ["invoices"]
        and len(invoices.findall("invoice")) == 1
        and len(invoice.findall("invoicecontents")) == 1
    )
    print(f"XML nesting valid        : {nesting_ok}  api_children={api_kids} "
          f"invoices={len(invoices.findall('invoice'))} "
          f"invoicecontents={len(invoice.findall('invoicecontents'))}")

    sent_field_sets = [tuple(sorted(c.tag for c in ic)) for ic in sent_lines]
    distinct_shapes = Counter(sent_field_sets)
    print(f"Per-line field shapes    : {dict(distinct_shapes)}")
    print(f"  Sent fields per line   : {sorted({c.tag for ic in sent_lines for c in ic})}")
except ET.ParseError as exc:
    print(f"XML PARSE ERROR: {exc}")

# Persisted line on wFirma
persisted_xml = wf.fetch_invoice_xml(WID)
prooot = ET.fromstring(persisted_xml)
inv = prooot.find(".//invoice")
ics = inv.findall(".//invoicecontent")
print(f"\nwFirma actual line count : {len(ics)}")
if ics:
    fields = []
    for c in ics[0]:
        if list(c):
            fields.append(f"{c.tag}/{[g.tag for g in c]}")
        else:
            fields.append(c.tag)
    print(f"  Persisted fields       : {sorted(fields)}")

# Diff
sent_set = {c.tag for ic in sent_lines for c in ic}
persisted_set = {c.tag for c in ics[0]} if ics else set()
missing = sorted(persisted_set - sent_set)
print(f"\nFields on persisted line but NOT in create XML:")
for f in missing:
    sample = (ics[0].findtext(f) or "").strip()
    sub_kids = [g.tag for g in ics[0].find(f)] if ics[0].find(f) is not None and list(ics[0].find(f)) else []
    sub_str = f"  sub_kids={sub_kids}" if sub_kids else f"  text={sample[:60]!r}"
    print(f"  - <{f}>{sub_str}")

print("\n── Sample sent XML (first 600 chars) ──")
print(xml[:600])
print("...")
print("── Sample sent invoicecontent block ──")
if sent_lines:
    print(ET.tostring(sent_lines[0], encoding="unicode"))
