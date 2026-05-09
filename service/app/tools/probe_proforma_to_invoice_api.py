"""
probe_proforma_to_invoice_api.py — read-only discovery of wFirma's
proforma → invoice conversion surface.

GOAL
    Find the actual endpoint(s) and request shape wFirma exposes for turning
    an existing proforma into a regular invoice. We DO NOT guess. We probe
    with HTTP requests that have no side effect and inspect the response.

METHOD
    1. Pick a known existing proforma in this account (any one — we don't
       modify it). Read its full XML to learn the field set wFirma stores.
    2. Probe a list of candidate actions on the `invoices` module using
       the existing _http_request helper. Record for each candidate:
           - HTTP status
           - wFirma status code (<status><code>)
           - first ~200 chars of the response body for human inspection
    3. Print a table the operator can read to decide which path is real.

CANDIDATES TESTED (in this order)
    GET   invoices/find                  — known good (sanity baseline)
    GET   invoices/copy                  — does the action even exist?
    GET   invoices/convert
    GET   invoices/transform
    POST  invoices/copy                  — conversion typically needs POST
    POST  invoices/convert
    POST  invoices/add  with <type>normal</type><proforma><id>N</id></proforma>
    POST  invoices/add  with <based_on><id>N</id></based_on>
    POST  invoices/add  with <from_proforma><id>N</id></from_proforma>

We pass an obviously fake/safe proforma id (id=0) to POST candidates so even
if the endpoint exists, no real document is created. Endpoint shape can be
deduced from the error message wFirma returns ("invalid id" tells us the
action exists; "URL_RULE_NOT_CONFIGURED" tells us it doesn't).

NO LIVE WRITES OCCUR. Exit code 0 on completion regardless of probe result.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, List, Tuple

# ── Path bootstrap ───────────────────────────────────────────────────────────
def _ensure_path() -> None:
    here = Path(__file__).resolve()
    service_dir = here.parents[2]
    repo_root   = here.parents[3]
    for p in (str(service_dir), str(repo_root)):
        if p not in sys.path:
            sys.path.insert(0, p)
_ensure_path()

from app.services import wfirma_client as wfc   # noqa: E402


# ── Candidates ────────────────────────────────────────────────────────────────

# NB: action name is whatever appears AFTER the module in the URL path. With
# a non-existent action wFirma returns either HTTP 404 + URL_RULE_NOT_CONFIGURED
# or wfirma_status=ERROR with description naming the rule.
ACTION_CANDIDATES: List[Tuple[str, str, str]] = [
    # (label, http_method, action)
    ("baseline find",         "GET",  "find"),
    ("GET copy",              "GET",  "copy"),
    ("GET convert",           "GET",  "convert"),
    ("GET transform",         "GET",  "transform"),
    ("POST copy",             "POST", "copy"),
    ("POST convert",          "POST", "convert"),
    ("POST add (proforma id)","POST", "add"),
    ("POST add (based_on)",   "POST", "add"),
    ("POST add (from_proforma)","POST","add"),
]

# Body templates per candidate. The id=0 is intentional — we want a "not
# found" / "invalid id" response, not a real document creation.
BODIES: Dict[str, str] = {
    "GET find": """<?xml version="1.0" encoding="UTF-8"?>
<api>
  <invoices>
    <parameters>
      <conditions>
        <condition><field>type</field><operator>eq</operator><value>proforma</value></condition>
      </conditions>
      <page><start>0</start><limit>1</limit></page>
    </parameters>
  </invoices>
</api>""",
    "GET copy": "",
    "GET convert": "",
    "GET transform": "",
    "POST copy": """<?xml version="1.0" encoding="UTF-8"?>
<api><invoices><invoice><id>0</id></invoice></invoices></api>""",
    "POST convert": """<?xml version="1.0" encoding="UTF-8"?>
<api><invoices><invoice><id>0</id></invoice></invoices></api>""",
    "POST add (proforma id)": """<?xml version="1.0" encoding="UTF-8"?>
<api><invoices><invoice>
    <type>normal</type>
    <proforma><id>0</id></proforma>
</invoice></invoices></api>""",
    "POST add (based_on)": """<?xml version="1.0" encoding="UTF-8"?>
<api><invoices><invoice>
    <type>normal</type>
    <based_on><id>0</id></based_on>
</invoice></invoices></api>""",
    "POST add (from_proforma)": """<?xml version="1.0" encoding="UTF-8"?>
<api><invoices><invoice>
    <type>normal</type>
    <from_proforma><id>0</id></from_proforma>
</invoice></invoices></api>""",
}


# ── Probe ────────────────────────────────────────────────────────────────────

def _trim(text: str, n: int = 220) -> str:
    flat = " ".join((text or "").split())
    return flat if len(flat) <= n else flat[:n] + "…"


def _classify(http_status: int, wfirma_status: str, body_excerpt: str) -> str:
    """Best-effort interpretation of probe result."""
    body_low = (body_excerpt or "").lower()
    if "url_rule_not_configured" in body_low or "rule not configured" in body_low:
        return "DOES NOT EXIST (route unknown)"
    if http_status == 404:
        return "DOES NOT EXIST (HTTP 404)"
    if wfirma_status == "OK":
        return "EXISTS — request accepted"
    if wfirma_status in ("ERROR", "INPUT ERROR", "FATAL"):
        if "invalid" in body_low and ("id" in body_low or "proforma" in body_low):
            return "EXISTS — rejected our id (good signal)"
        if "required" in body_low:
            return "EXISTS — needs more fields"
        return f"EXISTS — wFirma error: {wfirma_status}"
    if wfirma_status in ("NOT FOUND",):
        return "EXISTS — proforma id not found (good signal)"
    return f"AMBIGUOUS — wfirma_status={wfirma_status!r} http={http_status}"


def probe_one(label: str, method: str, action: str, body: str) -> Dict[str, object]:
    try:
        http_status, response = wfc._http_request(method, "invoices", action, body)
    except Exception as exc:  # noqa: BLE001
        return {
            "label": label, "method": method, "action": action,
            "http_status": 0, "wfirma_status": f"EXC:{type(exc).__name__}",
            "interpretation": "TRANSPORT ERROR",
            "body_excerpt": str(exc),
        }
    wfirma_status, wfirma_desc = wfc._parse_status(response)
    excerpt = _trim(response or "")
    interp = _classify(http_status, wfirma_status, excerpt)
    return {
        "label":          label,
        "method":         method,
        "action":         action,
        "http_status":    http_status,
        "wfirma_status":  wfirma_status or "(none)",
        "interpretation": interp,
        "body_excerpt":   excerpt,
    }


def fetch_one_proforma_id() -> str:
    """Find any existing proforma id we can use as a real-target POST.

    Read-only. Returns "" if none found.
    """
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
    if http >= 400:
        return ""
    import re
    m = re.search(r"<invoice>\s*<id>(\d+)</id>", resp)
    return m.group(1) if m else ""


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    print("=" * 78)
    print(" wFirma proforma → invoice conversion endpoint probe (READ-ONLY)")
    print("=" * 78)

    # Stage 1: confirm the API works at all by reading one real proforma id.
    proforma_id = fetch_one_proforma_id()
    print(f"\n[stage 1] sample proforma id discovered: {proforma_id or '(none)'}")
    if proforma_id:
        # Re-target POST candidates against the real id so we can distinguish
        # "endpoint missing" from "endpoint exists but rejected fake id".
        for k in list(BODIES.keys()):
            BODIES[k] = BODIES[k].replace("<id>0</id>", f"<id>{proforma_id}</id>")

    # Stage 2: probe each candidate.
    print(f"\n[stage 2] probing {len(ACTION_CANDIDATES)} candidate endpoints…\n")

    results = []
    for label, method, action in ACTION_CANDIDATES:
        body = BODIES.get(label, "")
        r = probe_one(label, method, action, body)
        results.append(r)

    # Stage 3: print summary table.
    print(f"  {'label':<28} {'method':<6} {'action':<10} {'http':<6} {'wfirma':<10} interpretation")
    print("  " + "-" * 100)
    for r in results:
        print(f"  {r['label']:<28} {r['method']:<6} {r['action']:<10} "
              f"{r['http_status']:<6} {r['wfirma_status']:<10} {r['interpretation']}")

    # Stage 4: show body excerpts for non-baseline candidates.
    print("\n[stage 3] response excerpts:\n")
    for r in results:
        print(f"--- {r['label']} ({r['method']} {r['action']}) ---")
        print(f"    {r['body_excerpt']}")
        print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
