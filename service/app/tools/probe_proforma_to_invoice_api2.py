"""
probe_proforma_to_invoice_api2.py — round 2.

Round 1 established:
  - invoices/copy, invoices/convert, invoices/transform → ACTION NOT FOUND
  - invoices/add silently ignores <proforma>/<based_on>/<from_proforma>
    wrapper tags; it always validates as a fresh add.

Round 2 questions:
  1. Does wFirma expose a "settle / mark paid / link to invoice" action on
     the proforma itself? (e.g. invoices/settle, invoices/markpaid,
     invoices/finalize, invoices/issue)
  2. What does a real existing proforma XML record actually contain — is
     there a <final_invoice_id> / <related> / <type>final</type> hint?
  3. Does <type>normal</type> on /add accept a reference field of any kind?

Read-only. No documents are created.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Tuple

def _ensure_path() -> None:
    here = Path(__file__).resolve()
    service_dir = here.parents[2]
    repo_root   = here.parents[3]
    for p in (str(service_dir), str(repo_root)):
        if p not in sys.path:
            sys.path.insert(0, p)
_ensure_path()

from app.services import wfirma_client as wfc   # noqa: E402


# ── Action probes (more candidates) ──────────────────────────────────────────

EXTRA_ACTIONS: List[Tuple[str, str, str]] = [
    # (label, method, action)
    ("GET settle",            "GET",  "settle"),
    ("GET finalize",          "GET",  "finalize"),
    ("GET issue",             "GET",  "issue"),
    ("GET markpaid",          "GET",  "markpaid"),
    ("GET markaspaid",        "GET",  "markaspaid"),
    ("GET pay",               "GET",  "pay"),
    ("GET close",             "GET",  "close"),
    ("GET book",              "GET",  "book"),
    ("GET realize",           "GET",  "realize"),
    ("GET clone",             "GET",  "clone"),
    ("GET duplicate",         "GET",  "duplicate"),
    ("GET fromproforma",      "GET",  "fromproforma"),
]


def _trim(text: str, n: int = 220) -> str:
    flat = " ".join((text or "").split())
    return flat if len(flat) <= n else flat[:n] + "…"


def main() -> int:
    print("=" * 78)
    print(" wFirma round-2 probe — settlement-style actions")
    print("=" * 78)

    # ── Stage A: probe extra actions ────────────────────────────────────────
    print(f"\n[stage A] probing {len(EXTRA_ACTIONS)} settlement-style actions…\n")
    print(f"  {'label':<22} {'method':<6} {'action':<14} {'http':<6} {'wfirma':<22}")
    print("  " + "-" * 80)
    for label, method, action in EXTRA_ACTIONS:
        try:
            http, resp = wfc._http_request(method, "invoices", action, "")
        except Exception as exc:  # noqa: BLE001
            print(f"  {label:<22} {method:<6} {action:<14} 0      EXC:{type(exc).__name__}")
            continue
        wcode, _ = wfc._parse_status(resp)
        print(f"  {label:<22} {method:<6} {action:<14} {http:<6} {wcode:<22}")

    # ── Stage B: read one proforma in full ──────────────────────────────────
    body = """<?xml version="1.0" encoding="UTF-8"?>
<api>
  <invoices>
    <parameters>
      <conditions>
        <condition><field>type</field><operator>eq</operator><value>proforma</value></condition>
      </conditions>
      <page><start>0</start><limit>1</limit></page>
    </parameters>
  </invoices>
</api>"""
    http, resp = wfc._http_request("GET", "invoices", "find", body)
    print(f"\n[stage B] full proforma XML (one record, last issued):\n")
    if http >= 400:
        print(f"  HTTP {http} — could not read")
    else:
        # Print roughly first 4 KB so we can see the field set wFirma stores.
        print(resp[:4000])
        print("…(truncated)…" if len(resp) > 4000 else "")

    # ── Stage C: scan for relationship fields in the response ───────────────
    interesting = [
        "final_invoice", "related_invoice", "linked_invoice",
        "based_on", "from_proforma", "proforma_id",
        "parent_id", "parent_invoice", "settlement",
        "is_paid", "paid", "settled", "issued", "realized",
        "type",
    ]
    print(f"\n[stage C] scanning proforma XML for relationship hints:\n")
    found = []
    for token in interesting:
        if f"<{token}" in resp:
            # Pull a small snippet for that tag
            i = resp.find(f"<{token}")
            snippet = resp[i:i+200].replace("\n", " ")
            found.append((token, _trim(snippet, 140)))
    if not found:
        print("  (no relationship-suggesting tags present)")
    for name, snip in found:
        print(f"  • {name:<20} → {snip}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
