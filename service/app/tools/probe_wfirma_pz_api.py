"""
probe_wfirma_pz_api.py — wFirma PZ endpoint reachability + auth probe.

Probes candidate modules WITHOUT writing any data. For modules that
support `find`, runs a tiny <page><limit>1</limit></page> query.
For `add` actions: never POSTs real data — sends an intentionally-incomplete
empty <api/> body to detect "schema/auth ok, payload bad" vs "endpoint
unknown / 404 / forbidden". This is the standard probing technique used
elsewhere in the codebase (see wfirma_client.probe_endpoint).

A live PZ creation requires explicit flag:
    --live-confirm-I-understand
which this probe tool does NOT support — that path lives in a separate
script. This file only reads / probes.

Hypothesis endpoints tested:
  1. warehouse_document_p_z/find   (preferred — already in _WAREHOUSE_MODULES)
  2. warehouse_document_p_z/add    (empty-body probe)
  3. warehouse_documents/find      (umbrella)
  4. warehouse_documents/add       (empty-body probe)
  5. pz/find                       (long-shot alias, expected NO)
  6. goods/find                    (sanity baseline — must be reachable)

Usage:
    python3 -m app.tools.probe_wfirma_pz_api
    python3 -m app.tools.probe_wfirma_pz_api --json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List


def _bootstrap() -> None:
    here = Path(__file__).resolve()
    repo_root = here.parents[3]
    service_dir = here.parents[2]
    for p in (str(repo_root), str(service_dir)):
        if p not in sys.path:
            sys.path.insert(0, p)


_bootstrap()


# ── Probe table (READ-ONLY) ───────────────────────────────────────────────────
# Each probe is one of:
#   kind="find"       — uses wfirma_client.probe_endpoint with a page-limit body
#   kind="add_empty"  — POSTs a minimal <api><module/></api> with NO data
#                       Goal: detect HTTP/auth path. Server should reject the
#                       payload (validation error), proving the endpoint exists.
#                       It MUST NOT cause a write because the body has no fields.
#   kind="alias"      — GET /find on a long-shot alias (e.g. "pz")

_PROBES: List[Dict[str, str]] = [
    {"module": "warehouse_document_p_z", "action": "find", "kind": "find"},
    {"module": "warehouse_document_p_z", "action": "add",  "kind": "add_empty"},
    {"module": "warehouse_documents",    "action": "find", "kind": "find"},
    {"module": "warehouse_documents",    "action": "add",  "kind": "add_empty"},
    {"module": "pz",                     "action": "find", "kind": "alias"},
    {"module": "goods",                  "action": "find", "kind": "find"},
]


def _empty_add_body(module: str) -> str:
    """Minimal payload — guaranteed to be rejected as invalid."""
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<api>\n  <{module}/>\n</api>'


def _interpret(http_status: int, wfirma_status: str, kind: str) -> Dict[str, Any]:
    """
    Map (HTTP, wFirma) → {reachable, auth_ok, write_risk, note}.

    Heuristics:
      - HTTP 0 → network failure, not reachable
      - HTTP 401/403 → reachable, auth failed
      - HTTP 404 → endpoint absent
      - HTTP 200 + wfirma OK → reachable + auth ok
      - HTTP 200 + wfirma ERROR/INPUT_ERROR → reachable + auth ok + payload rejected
        (this is the GOOD signal for an add_empty probe)
    """
    if http_status == 0:
        return {"reachable": False, "auth_ok": False, "write_risk": False,
                "note": "network/connection error"}
    if http_status in (401, 403):
        return {"reachable": True, "auth_ok": False, "write_risk": False,
                "note": f"HTTP {http_status} — credentials rejected"}
    if http_status == 404:
        return {"reachable": False, "auth_ok": True, "write_risk": False,
                "note": "HTTP 404 — endpoint not found"}
    if http_status >= 500:
        return {"reachable": True, "auth_ok": True, "write_risk": False,
                "note": f"HTTP {http_status} — server error"}

    # 2xx/4xx with parseable wFirma envelope
    if wfirma_status == "OK":
        # For add_empty this would mean a write happened — should not occur
        # with our intentionally empty body, but flag it.
        if kind == "add_empty":
            return {"reachable": True, "auth_ok": True, "write_risk": True,
                    "note": "OK on empty add body — possible accidental write, INVESTIGATE"}
        return {"reachable": True, "auth_ok": True, "write_risk": False,
                "note": "OK"}
    if wfirma_status in ("INPUT_ERROR", "ERROR", "ACTION_NOT_FOUND",
                         "NOT_FOUND", "PERMISSION_DENIED"):
        return {"reachable": wfirma_status != "ACTION_NOT_FOUND",
                "auth_ok": wfirma_status != "PERMISSION_DENIED",
                "write_risk": False,
                "note": f"wFirma status={wfirma_status} (expected for empty/probe body)"}
    return {"reachable": True, "auth_ok": True, "write_risk": False,
            "note": f"wFirma status={wfirma_status}"}


def run_probes() -> List[Dict[str, Any]]:
    """Execute all probes. Each probe captures its own exception."""
    from app.services import wfirma_client as wfc

    results: List[Dict[str, Any]] = []
    for probe in _PROBES:
        module, action, kind = probe["module"], probe["action"], probe["kind"]
        row: Dict[str, Any] = {
            "endpoint":      f"{module}/{action}",
            "kind":          kind,
            "reachable":     False,
            "auth_ok":       False,
            "http_status":   0,
            "wfirma_status": "",
            "write_risk":    False,
            "note":          "",
        }

        try:
            if kind == "add_empty":
                # Direct call — we want to see how the server reacts to an empty body
                http_status, response_text = wfc._http_request(
                    "POST", module, action, _empty_add_body(module),
                )
                wfirma_code, wfirma_desc = wfc._parse_status(response_text)
            else:
                # find / alias — use the existing probe_endpoint helper
                result = wfc.probe_endpoint(module, action)
                http_status   = result["http_status"]
                wfirma_code   = result["wfirma_status"]
                wfirma_desc   = result.get("error", "")

            interp = _interpret(http_status, wfirma_code, kind)
            row.update({
                "http_status":   http_status,
                "wfirma_status": wfirma_code or "(empty)",
                "reachable":     interp["reachable"],
                "auth_ok":       interp["auth_ok"],
                "write_risk":    interp["write_risk"],
                "note":          interp["note"] + (
                    f" — {wfirma_desc}" if wfirma_desc and wfirma_desc not in interp["note"] else ""
                ),
            })
        except Exception as exc:  # noqa: BLE001
            row["note"] = f"exception: {exc}"

        results.append(row)
    return results


def summarize(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Pick the most likely confirmed PZ endpoint, if any."""
    pz_find_ok = next(
        (r for r in results
         if r["endpoint"] == "warehouse_document_p_z/find" and r["reachable"] and r["auth_ok"]),
        None,
    )
    pz_add_reachable = next(
        (r for r in results
         if r["endpoint"] == "warehouse_document_p_z/add" and r["reachable"] and r["auth_ok"]),
        None,
    )

    confirmed = bool(pz_find_ok and pz_add_reachable and not pz_add_reachable["write_risk"])

    if confirmed:
        verdict = "CONFIRMED — warehouse_document_p_z/add is reachable + auth ok"
        recommendation = (
            "Use POST warehouse_document_p_z/add with the XML shape from "
            "build_wfirma_pz_payload.py. Run with --live-confirm-I-understand "
            "on a single low-risk line first."
        )
    elif pz_find_ok:
        verdict = "PARTIAL — find works, add probe inconclusive"
        recommendation = (
            "Module is reachable but the add path needs a real payload to verify. "
            "Recommend a manual single-line live test with --live-confirm-I-understand."
        )
    else:
        verdict = "NOT CONFIRMED — PZ endpoint not verified"
        recommendation = (
            "Do NOT attempt API write. Use wFirma CSV import (Magazyn → PZ → Importuj) "
            "as the production-safe path until the API endpoint is confirmed."
        )

    return {
        "verdict":          verdict,
        "confirmed":        confirmed,
        "recommendation":   recommendation,
    }


def _print_human(results: List[Dict[str, Any]], summary: Dict[str, Any]) -> None:
    width = 100
    print("=" * width)
    print(" wFirma PZ API probe — READ-ONLY (no real PZ created)")
    print("=" * width)
    header = f"  {'ENDPOINT':38s} {'KIND':10s} {'REACH':>5s} {'AUTH':>5s} {'HTTP':>5s} {'WFIRMA':>16s} {'RISK':>5s}  NOTE"
    print(header)
    print("  " + "-" * (width - 2))
    for r in results:
        reach = "✓" if r["reachable"] else "✗"
        auth  = "✓" if r["auth_ok"]   else "✗"
        risk  = "⚠"  if r["write_risk"] else "·"
        print(
            f"  {r['endpoint']:38s} {r['kind']:10s} {reach:>5s} {auth:>5s} "
            f"{r['http_status']:>5d} {r['wfirma_status']:>16s} {risk:>5s}  {r['note']}"
        )
    print()
    print(f"  VERDICT       : {summary['verdict']}")
    print(f"  CONFIRMED     : {summary['confirmed']}")
    print(f"  RECOMMENDATION: {summary['recommendation']}")
    print()


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="probe_wfirma_pz_api")
    p.add_argument("--json", action="store_true", help="Emit JSON output")
    args = p.parse_args(argv)

    results = run_probes()
    summary = summarize(results)

    if args.json:
        print(json.dumps({"results": results, "summary": summary}, indent=2, default=str))
    else:
        _print_human(results, summary)

    return 0


if __name__ == "__main__":
    sys.exit(main())
