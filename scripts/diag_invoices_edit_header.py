"""
Read-only diagnostic: probe wFirma invoices/edit HEADER field on proforma 465611619.

Operator-authorized 2026-05-06.
Edits a single header field only; restores immediately on success.
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
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        v = v.split("#", 1)[0].strip().strip('"').strip("'")
        os.environ.setdefault(k.strip(), v)

from app.services import wfirma_client as wf  # noqa: E402

PROFORMA_ID = "465611619"
PROBE       = "TEST_DIAGNOSTIC_HEADER_DO_NOT_KEEP"


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


def get_header_field(xml_text, tag):
    root = ET.fromstring(xml_text)
    inv = root.find(".//invoice")
    node = inv.find(tag)
    return (node.text or "") if node is not None else None


def edit_header(field_tag, new_value):
    body = f"""<?xml version="1.0" encoding="UTF-8"?>
<api>
  <invoices>
    <invoice>
      <{field_tag}>{wf._esc(new_value)}</{field_tag}>
    </invoice>
  </invoices>
</api>"""
    http, text = wf._http_request("POST", "invoices", "edit", body, id_suffix=PROFORMA_ID)
    code, desc = wf._parse_status(text)
    return {"http": http, "status": code, "desc": desc, "snippet": text[:400]}


def main():
    print("=== Step 1: Fetch proforma XML ===")
    xml1 = fetch_xml()

    # Try common header text fields wFirma uses on invoices
    for tag in ("description", "remarks", "comment", "notes"):
        val = get_header_field(xml1, tag)
        if val is not None:
            print(f"  found header field <{tag}> = {val!r}")
    # Pick the field to edit. <description> is the conventional one per
    # the user's task body.
    target_tag = "description"
    original = get_header_field(xml1, target_tag)
    if original is None:
        print(f"  <{target_tag}> not present on this proforma — wFirma will create it")
        original = ""
    print(f"  original {target_tag} = {original!r}")
    print()

    print("=== Step 2: Attempt header edit (PROBE) ===")
    a = edit_header(target_tag, PROBE)
    print(f"  http={a['http']} status={a['status']} desc={a['desc']}")
    print(f"  snippet: {a['snippet']}")
    print()

    print("=== Step 3: Re-fetch and check ===")
    xml2 = fetch_xml()
    new_val = get_header_field(xml2, target_tag) or ""
    changed = (new_val == PROBE)
    print(f"  {target_tag} now = {new_val!r}  changed={changed}")

    restored = True
    if changed:
        print()
        print("=== Step 4: Restore original value ===")
        r = edit_header(target_tag, original)
        print(f"  restore http={r['http']} status={r['status']} desc={r['desc']}")
        xml3 = fetch_xml()
        final_val = get_header_field(xml3, target_tag) or ""
        restored = (final_val == original)
        print(f"  final {target_tag} = {final_val!r}  restored={restored}")

    print()
    print("=== SUMMARY ===")
    print(f"  original value : {original!r}")
    print(f"  attempt status : {a['status']}  desc={a['desc']}")
    print(f"  header changed : {changed}")
    print(f"  was restored   : {restored}")
    if changed and restored:
        conclusion = "invoices/edit ALLOWED at header level on issued proforma — line edits separately blocked."
    elif changed and not restored:
        conclusion = "invoices/edit MUTATED but restore FAILED — manual intervention needed."
    else:
        conclusion = "invoices/edit BLOCKED entirely on issued proforma (header + line both rejected)."
    print(f"  conclusion     : {conclusion}")


if __name__ == "__main__":
    main()
