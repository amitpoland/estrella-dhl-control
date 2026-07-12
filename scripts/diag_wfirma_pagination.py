"""
Read-only diagnostic: probe several wFirma contractors/find pagination
shapes to find one that advances past the first 20 rows. Operator-
authorised 2026-05-06; no writes; no condition-side mutations.

Targets: two contractors confirmed real via search_customer that do NOT
show up in the default page-1 list_contractors_page() return. The concrete
contractor ids/names are supplied by the operator out-of-band (kept out of
this public source); fill TARGET_IDS below before re-running.
"""
from __future__ import annotations
import os, sys, xml.etree.ElementTree as ET
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

from app.services import wfirma_client as wf

# Fill with the real contractor ids to probe (operator-supplied, out-of-band).
# Left empty in source so no real contractor ids live in this public repo.
TARGET_IDS: set[str] = set()


def parse_ids(xml_text):
    root = ET.fromstring(xml_text)
    contractors = root.find("contractors")
    if contractors is None: return []
    out = []
    for c in contractors.findall("contractor"):
        wid = (c.findtext("id") or "").strip()
        name = (c.findtext("name") or "").strip()
        if wid and wid != "0" and name:
            out.append((wid, name))
    return out


def probe(label, body):
    print(f"\n── {label}")
    http, text = wf._http_request("GET", "contractors", "find", body)
    code, desc = wf._parse_status(text)
    rows = parse_ids(text)
    print(f"  http={http}  status={code}  desc={desc[:80] if desc else ''}")
    print(f"  rows: {len(rows)}  ids: {[r[0] for r in rows][:5]}…{[r[0] for r in rows][-3:] if len(rows) > 5 else ''}")
    hits = [r for r in rows if r[0] in TARGET_IDS]
    if hits:
        print(f"  ✓ TARGETS FOUND: {hits}")
    return rows


# Shape 1: baseline (current) — <page><start>0</start><limit>50</limit></page>
probe("S1 baseline page/start/limit",
      """<?xml version="1.0" encoding="UTF-8"?>
<api><contractors><parameters>
  <conditions/>
  <page><start>0</start><limit>50</limit></page>
</parameters></contractors></api>""")

# Shape 2: page+limit at parameters root (no <start>)
probe("S2 page=2 + limit=20 at root",
      """<?xml version="1.0" encoding="UTF-8"?>
<api><contractors><parameters>
  <page>2</page><limit>20</limit>
</parameters></contractors></api>""")

# Shape 3: same as S2 but explicit empty conditions
probe("S3 page=2 + limit=50 + empty conditions",
      """<?xml version="1.0" encoding="UTF-8"?>
<api><contractors><parameters>
  <conditions/>
  <page>2</page><limit>50</limit>
</parameters></contractors></api>""")

# Shape 4: id-condition: id > last_seen_id (sorted naturally?)
probe("S4 conditions id gt last_visible (44980520)",
      """<?xml version="1.0" encoding="UTF-8"?>
<api><contractors><parameters>
  <conditions>
    <condition><field>id</field><operator>gt</operator><value>44980520</value></condition>
  </conditions>
</parameters></contractors></api>""")

# Shape 5: id range with order asc + limit
probe("S5 id gt + order id asc + limit 100",
      """<?xml version="1.0" encoding="UTF-8"?>
<api><contractors><parameters>
  <conditions>
    <condition><field>id</field><operator>gt</operator><value>44980520</value></condition>
  </conditions>
  <order><field>id</field><order>asc</order></order>
  <page><start>0</start><limit>100</limit></page>
</parameters></contractors></api>""")

# Shape 6: name condition for Juliany (sanity — confirms find works on conditions)
probe("S6 sanity: name like Juliany",
      """<?xml version="1.0" encoding="UTF-8"?>
<api><contractors><parameters>
  <conditions>
    <condition><field>name</field><operator>like</operator><value>%Juliany%</value></condition>
  </conditions>
</parameters></contractors></api>""")

# Shape 7: no parameters at all (just <contractors/>) — what wFirma defaults to
probe("S7 no parameters",
      """<?xml version="1.0" encoding="UTF-8"?>
<api><contractors/></api>""")

# Shape 8: order asc + huge limit + no conditions (sort+slice)
probe("S8 order asc + limit 500",
      """<?xml version="1.0" encoding="UTF-8"?>
<api><contractors><parameters>
  <conditions/>
  <order><field>id</field><order>asc</order></order>
  <page><start>0</start><limit>500</limit></page>
</parameters></contractors></api>""")
