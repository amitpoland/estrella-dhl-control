"""
Read-only diagnostic: probe wFirma invoices/edit with FULL invoicecontent
restate on proforma 465611619, line 1495642083. Operator-authorized 2026-05-06.
"""
from __future__ import annotations
import os, sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "service"))
env_path = ROOT / "service" / ".env"
if env_path.exists():
    for raw in env_path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line: continue
        k, _, v = line.partition("=")
        v = v.split("#", 1)[0].strip().strip('"').strip("'")
        os.environ.setdefault(k.strip(), v)

from app.services import wfirma_client as wf  # noqa: E402
from app.services import document_db as ddb   # noqa: E402

PROFORMA_ID = "465611619"
LINE_ID     = "1495642083"
GOOD_ID     = "48611875"
PROBE       = "TEST_DIAGNOSTIC_FULL_LINE_DO_NOT_KEEP"


def fetch_xml():
    body = f"""<?xml version="1.0" encoding="UTF-8"?>
<api>
  <invoices>
    <parameters>
      <conditions>
        <condition><field>id</field><operator>eq</operator><value>{PROFORMA_ID}</value></condition>
      </conditions>
    </parameters>
  </invoices>
</api>"""
    http, text = wf._http_request("GET", "invoices", "find", body)
    if http >= 400:
        raise RuntimeError(f"find HTTP {http}")
    return text


def extract_line(xml_text, line_id):
    root = ET.fromstring(xml_text)
    for ic in root.iter("invoicecontent"):
        if (ic.findtext("id") or "").strip() == line_id:
            return ic
    raise RuntimeError(f"line {line_id} not found")


def line_summary(ic_elem):
    out = {}
    for child in ic_elem:
        if list(child):
            sub = {sc.tag: (sc.text or "").strip() for sc in child}
            out[child.tag] = sub
        else:
            out[child.tag] = (child.text or "").strip()
    return out


def serialize_line_with_name(ic_elem, new_name):
    # Clone + replace <name>
    cloned = ET.fromstring(ET.tostring(ic_elem))
    name_node = cloned.find("name")
    if name_node is None:
        name_node = ET.SubElement(cloned, "name")
    name_node.text = new_name
    return ET.tostring(cloned, encoding="unicode")


def attempt_edit(ic_elem, new_name):
    line_xml = serialize_line_with_name(ic_elem, new_name)
    body = f"""<?xml version="1.0" encoding="UTF-8"?>
<api>
  <invoices>
    <invoice>
      <invoicecontents>
        {line_xml}
      </invoicecontents>
    </invoice>
  </invoices>
</api>"""
    http, text = wf._http_request("POST", "invoices", "edit", body, id_suffix=PROFORMA_ID)
    code, desc = wf._parse_status(text)
    return {"http": http, "status": code, "desc": desc, "snippet": text[:500]}


def lookup_correct_name(good_code):
    if not good_code: return ""
    row = ddb.get_product_description(good_code)
    return (row.get("description_line") or "").strip() if row else ""


def main():
    print("=== Step 1: Fetch + extract line ===")
    xml1 = fetch_xml()
    ic = extract_line(xml1, LINE_ID)
    before = line_summary(ic)
    print("  fields present on line:")
    for k, v in before.items():
        print(f"    {k:20} = {v!r}")

    # Try to recover product code so we can fetch correct description_line
    good_code = ""
    if "good" in before and isinstance(before["good"], dict):
        good_code = before["good"].get("code", "") or ""
    correct = lookup_correct_name(good_code)
    print(f"\n  good_code: {good_code!r}")
    print(f"  correct customs-grade description_line: {correct!r}")
    print()

    print("=== Step 2: Probe edit (full line restated, name=PROBE) ===")
    a = attempt_edit(ic, PROBE)
    print(f"  http={a['http']} status={a['status']} desc={a['desc']}")
    print(f"  snippet: {a['snippet']}")
    print()

    print("=== Step 3: Re-fetch ===")
    xml2 = fetch_xml()
    ic_after = extract_line(xml2, LINE_ID)
    after_name = (ic_after.findtext("name") or "").strip()
    changed = (after_name == PROBE)
    print(f"  line name now: {after_name!r}  changed={changed}")

    restored = True
    if changed:
        print()
        print("=== Step 4: Restore ===")
        restore_target = correct or before.get("name", "")
        if not restore_target:
            print("  WARNING: no restore target available — leaving as PROBE; manual fix needed")
            restored = False
        else:
            r = attempt_edit(ic_after, restore_target)
            print(f"  restore http={r['http']} status={r['status']} desc={r['desc']}")
            xml3 = fetch_xml()
            final = (extract_line(xml3, LINE_ID).findtext("name") or "").strip()
            restored = (final == restore_target)
            print(f"  final name: {final!r}  restored={restored}")

    print()
    print("=== SUMMARY ===")
    print(f"  line before name : {before.get('name')!r}")
    print(f"  attempt status   : {a['status']}  desc={a['desc']!r}")
    print(f"  line changed     : {changed}")
    print(f"  was restored     : {restored}")
    if changed and restored:
        verdict = "Full-line restate WORKS — Option A viable (refresh-line-names route can be built)."
    elif changed and not restored:
        verdict = "Mutation accepted but RESTORE FAILED — manual cleanup needed."
    elif a['status'] == "OK" and not changed:
        verdict = "wFirma accepted call but did NOT honor the name change — line names appear frozen post-issuance."
    else:
        verdict = "Full-line restate REJECTED — Option B (cancel + reissue) is the path."
    print(f"  verdict          : {verdict}")


if __name__ == "__main__":
    main()
