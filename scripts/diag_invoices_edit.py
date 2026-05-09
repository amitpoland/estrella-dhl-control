"""
Read-only diagnostic: probe wFirma invoices/edit on proforma 465611619.

Rules (operator-authorized 2026-05-06):
  - One line only
  - TEST_DIAGNOSTIC_DO_NOT_KEEP as probe value
  - Restore correct line name immediately on success
  - No DB writes, no master changes, no delete, no convert
"""
from __future__ import annotations
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "service"))

# Load service/.env into os.environ so settings populate
import os
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
from app.services import document_db as ddb   # noqa: E402

PROFORMA_ID = "465611619"
PROBE_NAME  = "TEST_DIAGNOSTIC_DO_NOT_KEEP"


def fetch_proforma_xml(invoice_id: str) -> str:
    body = f"""<?xml version="1.0" encoding="UTF-8"?>
<api>
  <invoices>
    <parameters>
      <conditions>
        <condition><field>id</field><operator>eq</operator><value>{invoice_id}</value></condition>
      </conditions>
    </parameters>
  </invoices>
</api>"""
    http, text = wf._http_request("GET", "invoices", "find", body)
    if http >= 400:
        raise RuntimeError(f"invoices/find HTTP {http}: {text[:200]}")
    code, desc = wf._parse_status(text)
    if code != "OK":
        raise RuntimeError(f"invoices/find status={code}: {desc}")
    return text


def first_line_info(xml_text: str):
    root = ET.fromstring(xml_text)
    inv = root.find(".//invoice")
    contents = inv.find("invoicecontents")
    if contents is None:
        raise RuntimeError("no <invoicecontents> in proforma")
    line = contents.find("invoicecontent")
    if line is None:
        raise RuntimeError("no <invoicecontent> in proforma")
    line_id = (line.findtext("id") or "").strip()
    name    = (line.findtext("name") or "").strip()
    good_id = ""
    good_node = line.find("good")
    if good_node is not None:
        good_id = (good_node.findtext("id") or "").strip()
    # try to find product code on the line — wFirma typically inlines it
    code = (line.findtext("good_code") or "").strip()
    return {"line_id": line_id, "name": name, "good_id": good_id, "good_code": code}


def lookup_correct_name(good_code: str) -> str:
    if not good_code:
        return ""
    row = ddb.get_product_description(good_code)
    if row is None:
        return ""
    return (row.get("description_line") or "").strip()


def edit_attempt(*, with_url_id: bool, line_id: str, new_name: str):
    body = f"""<?xml version="1.0" encoding="UTF-8"?>
<api>
  <invoices>
    <invoice>
      {"" if with_url_id else f"<id>{PROFORMA_ID}</id>"}
      <invoicecontents>
        <invoicecontent>
          <id>{line_id}</id>
          <name>{wf._esc(new_name)}</name>
        </invoicecontent>
      </invoicecontents>
    </invoice>
  </invoices>
</api>"""
    suffix = PROFORMA_ID if with_url_id else None
    http, text = wf._http_request("POST", "invoices", "edit", body, id_suffix=suffix)
    code, desc = wf._parse_status(text)
    return {
        "shape":         "url-id" if with_url_id else "body-id",
        "http":          http,
        "wfirma_status": code,
        "desc":          desc,
        "snippet":       text[:300],
    }


def main():
    print("=== Step 1: Fetch proforma ===")
    xml1 = fetch_proforma_xml(PROFORMA_ID)
    info = first_line_info(xml1)
    correct_name = lookup_correct_name(info["good_code"])
    print(f"  line_id     : {info['line_id']}")
    print(f"  good_id     : {info['good_id']}")
    print(f"  good_code   : {info['good_code']}")
    print(f"  current name: {info['name']!r}")
    print(f"  correct name: {correct_name!r}")

    if not info["line_id"]:
        print("ABORT: no line id — cannot probe safely")
        return

    print()
    print("=== Step 2: body-id attempt ===")
    a1 = edit_attempt(with_url_id=False, line_id=info["line_id"], new_name=PROBE_NAME)
    print(f"  http={a1['http']} status={a1['wfirma_status']} desc={a1['desc']}")

    print()
    print("=== Step 2b: Re-fetch and check ===")
    after_a1 = first_line_info(fetch_proforma_xml(PROFORMA_ID))
    a1_changed = after_a1["name"] == PROBE_NAME
    print(f"  current name now: {after_a1['name']!r}  changed={a1_changed}")

    if a1_changed:
        print("  >>> Restoring immediately (body-id worked)")
        restore_target = correct_name or info["name"]
        r1 = edit_attempt(with_url_id=False, line_id=info["line_id"], new_name=restore_target)
        print(f"  restore http={r1['http']} status={r1['wfirma_status']}")

    print()
    print("=== Step 3: url-id attempt ===")
    a2 = edit_attempt(with_url_id=True, line_id=info["line_id"], new_name=PROBE_NAME)
    print(f"  http={a2['http']} status={a2['wfirma_status']} desc={a2['desc']}")

    print()
    print("=== Step 3b: Re-fetch and check ===")
    after_a2 = first_line_info(fetch_proforma_xml(PROFORMA_ID))
    a2_changed = after_a2["name"] == PROBE_NAME
    print(f"  current name now: {after_a2['name']!r}  changed={a2_changed}")

    restored = True
    if a2_changed:
        print("  >>> Restoring immediately (url-id worked)")
        restore_target = correct_name or info["name"]
        r2 = edit_attempt(with_url_id=True, line_id=info["line_id"], new_name=restore_target)
        print(f"  restore http={r2['http']} status={r2['wfirma_status']}")
        final = first_line_info(fetch_proforma_xml(PROFORMA_ID))
        restored = (final["name"] == restore_target)
        print(f"  final name: {final['name']!r}  restored={restored}")

    print()
    print("=== SUMMARY ===")
    if a1_changed:
        winner = "body-id"
    elif a2_changed:
        winner = "url-id"
    else:
        winner = "neither"
    print(f"  body-id changed line : {a1_changed}  (status={a1['wfirma_status']})")
    print(f"    body-id snippet    : {a1['snippet']}")
    print(f"  url-id  changed line : {a2_changed}  (status={a2['wfirma_status']})")
    print(f"    url-id  snippet    : {a2['snippet']}")
    print(f"  can edit line names  : {a1_changed or a2_changed}")
    print(f"  correct shape        : {winner}")
    print(f"  restored             : {restored}")


if __name__ == "__main__":
    main()
