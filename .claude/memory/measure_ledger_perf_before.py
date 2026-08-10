#!/usr/bin/env python3
"""Phase-1 MEASURE-ONLY ledger performance probe against local production.

Reads API_KEY from C:\\PZ\\.env (never prints secrets).
Writes JSON + markdown-friendly timings to stdout / report file.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE = "http://127.0.0.1:47213"
ENV_PATH = Path(r"C:\PZ\.env")
OUT_JSON = Path(__file__).with_name("measure-ledger-perf-before.json")
TIMEOUT_S = 180


def _load_api_key() -> str:
    if not ENV_PATH.exists():
        raise SystemExit(f"missing {ENV_PATH}")
    for line in ENV_PATH.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        if k.strip() == "API_KEY":
            val = v.strip().strip('"').strip("'")
            if val:
                return val
    raise SystemExit("API_KEY not found in env file")


def _get(path: str, api_key: str, params: dict | None = None) -> dict:
    qs = ""
    if params:
        qs = "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None and v != ""})
    url = BASE + path + qs
    req = urllib.request.Request(url, headers={"X-API-Key": api_key, "Accept": "application/json"})
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            raw = resp.read()
            status = resp.status
            headers = {k.lower(): v for k, v in resp.headers.items()}
    except urllib.error.HTTPError as e:
        raw = e.read() if e.fp else b""
        status = e.code
        headers = {k.lower(): v for k, v in (e.headers.items() if e.headers else [])}
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        body_preview = raw[:400].decode("utf-8", "replace")
        return {
            "ok": False,
            "url": url.split("?")[0],
            "qs": qs,
            "status": status,
            "elapsed_ms": elapsed_ms,
            "bytes": len(raw),
            "error_preview": body_preview[:200],
        }
    except Exception as e:
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        return {
            "ok": False,
            "url": url.split("?")[0],
            "qs": qs,
            "status": 0,
            "elapsed_ms": elapsed_ms,
            "bytes": 0,
            "error_preview": str(e)[:200],
        }
    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    text = raw.decode("utf-8", "replace")
    try:
        data = json.loads(text) if text else None
    except json.JSONDecodeError:
        data = None
    return {
        "ok": 200 <= status < 300,
        "url": url.split("?")[0],
        "qs": qs,
        "status": status,
        "elapsed_ms": elapsed_ms,
        "bytes": len(raw),
        "server_timing": headers.get("server-timing"),
        "data": data,
    }


def _summarize_clients(res: dict) -> dict:
    d = res.get("data") or {}
    rows = d.get("rows") or []
    avail = sum(1 for r in rows if r.get("balance_available"))
    return {
        "count": d.get("count", len(rows)),
        "rows": len(rows),
        "balance_available": avail,
        "period": d.get("period"),
        "first_contractor": (rows[0].get("contractor_id") if rows else None),
        "first_name": (rows[0].get("name") if rows else None),
    }


def _summarize_ma(res: dict) -> dict:
    d = res.get("data") or {}
    qs = d.get("query_stats") or {}
    customers = d.get("customers") or d.get("portfolio") or []
    if isinstance(customers, dict):
        # sometimes nested by currency
        n = sum(len(v) if isinstance(v, list) else 0 for v in customers.values())
    else:
        n = len(customers) if isinstance(customers, list) else None
    return {
        "query_stats": qs,
        "source_health": d.get("source_health"),
        "customer_or_row_count": n,
        "currencies": list((d.get("by_currency") or d.get("portfolios") or {}).keys())
        if isinstance(d.get("by_currency") or d.get("portfolios"), dict)
        else None,
        "top_keys": sorted(list(d.keys()))[:30] if isinstance(d, dict) else None,
    }


def _summarize_ap(res: dict) -> dict:
    d = res.get("data") or {}
    qs = d.get("query_stats") or {}
    suppliers = d.get("suppliers") or []
    return {
        "query_stats": qs,
        "source_health": d.get("source_health"),
        "suppliers": len(suppliers),
        "first_supplier": (suppliers[0].get("contractor_id") if suppliers else None),
        "first_name": (suppliers[0].get("supplier_name") if suppliers else None),
        "top_keys": sorted(list(d.keys()))[:30] if isinstance(d, dict) else None,
    }


def _summarize_stmt(res: dict) -> dict:
    d = res.get("data") or {}
    entries = 0
    for ccy, block in (d.get("entries_per_currency") or {}).items():
        if isinstance(block, list):
            entries += len(block)
    return {
        "contractor": (d.get("contractor") or {}).get("wfirma_contractor_id")
        or (d.get("contractor_meta") or {}).get("wfirma_contractor_id"),
        "currencies": list((d.get("totals_per_currency") or {}).keys()),
        "entries": entries,
        "warnings": len(d.get("warnings") or []),
        "period": d.get("period"),
    }


def main() -> int:
    api_key = _load_api_key()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    y = today[:4]
    ytd_from = f"{y}-01-01"
    ytd_to = today

    report: dict = {
        "measured_at": datetime.now(timezone.utc).isoformat(),
        "base": BASE,
        "head_note": "production NSSM 127.0.0.1:47213",
        "window": {"from": ytd_from, "to": ytd_to},
        "surfaces": {},
    }

    # 1) Client Balance limit=15 (AccClientBalance)
    r15 = _get("/api/v1/ledgers/clients", api_key, {
        "from": ytd_from, "to": ytd_to, "start": 0, "limit": 15,
    })
    s15 = _summarize_clients(r15) if r15.get("ok") else {}
    report["surfaces"]["client_balance_limit15"] = {
        "endpoint": "/api/v1/ledgers/clients",
        "params": {"limit": 15, "from": ytd_from, "to": ytd_to},
        "elapsed_ms": r15.get("elapsed_ms"),
        "status": r15.get("status"),
        "bytes": r15.get("bytes"),
        "summary": s15,
        "ok": r15.get("ok"),
        "error": r15.get("error_preview"),
    }

    # 1b) Client Balance limit=3 — N+1 scaling probe
    r3 = _get("/api/v1/ledgers/clients", api_key, {
        "from": ytd_from, "to": ytd_to, "start": 0, "limit": 3,
    })
    s3 = _summarize_clients(r3) if r3.get("ok") else {}
    report["surfaces"]["client_balance_limit3"] = {
        "endpoint": "/api/v1/ledgers/clients",
        "params": {"limit": 3, "from": ytd_from, "to": ytd_to},
        "elapsed_ms": r3.get("elapsed_ms"),
        "status": r3.get("status"),
        "bytes": r3.get("bytes"),
        "summary": s3,
        "ok": r3.get("ok"),
        "error": r3.get("error_preview"),
    }

    # 1c) Overview KPI path limit=100
    r100 = _get("/api/v1/ledgers/clients", api_key, {
        "from": ytd_from, "to": ytd_to, "start": 0, "limit": 100,
    })
    s100 = _summarize_clients(r100) if r100.get("ok") else {}
    report["surfaces"]["overview_kpi_limit100"] = {
        "endpoint": "/api/v1/ledgers/clients",
        "params": {"limit": 100, "from": ytd_from, "to": ytd_to},
        "elapsed_ms": r100.get("elapsed_ms"),
        "status": r100.get("status"),
        "bytes": r100.get("bytes"),
        "summary": s100,
        "ok": r100.get("ok"),
        "error": r100.get("error_preview"),
    }

    # 2) Client ledger landing = same as limit15 (already measured)
    # 3) Client ledger drill
    cid = s15.get("first_contractor") or s3.get("first_contractor")
    if cid:
        rst = _get(f"/api/v1/ledgers/clients/{urllib.parse.quote(cid)}/statement.json", api_key, {
            "from": ytd_from, "to": ytd_to,
        })
        report["surfaces"]["client_ledger_drill"] = {
            "endpoint": f"/api/v1/ledgers/clients/{{id}}/statement.json",
            "contractor_id": cid,
            "elapsed_ms": rst.get("elapsed_ms"),
            "status": rst.get("status"),
            "bytes": rst.get("bytes"),
            "summary": _summarize_stmt(rst) if rst.get("ok") else {},
            "ok": rst.get("ok"),
            "error": rst.get("error_preview"),
        }
    else:
        report["surfaces"]["client_ledger_drill"] = {"ok": False, "error": "no contractor"}

    # 4) Supplier ledger landing = payables-analysis
    rap = _get("/api/v1/ledgers/payables-analysis.json", api_key, {
        "from": ytd_from, "to": ytd_to, "as_of": ytd_to, "status": "outstanding",
    })
    sap = _summarize_ap(rap) if rap.get("ok") else {}
    report["surfaces"]["supplier_ledger_landing"] = {
        "endpoint": "/api/v1/ledgers/payables-analysis.json",
        "elapsed_ms": rap.get("elapsed_ms"),
        "status": rap.get("status"),
        "bytes": rap.get("bytes"),
        "summary": sap,
        "ok": rap.get("ok"),
        "error": rap.get("error_preview"),
    }

    # 5) Supplier drill
    sid = sap.get("first_supplier")
    if sid:
        rss = _get(f"/api/v1/ledgers/suppliers/{urllib.parse.quote(sid)}/statement.json", api_key, {
            "from": ytd_from, "to": ytd_to, "as_of": ytd_to,
        })
        report["surfaces"]["supplier_ledger_drill"] = {
            "endpoint": "/api/v1/ledgers/suppliers/{id}/statement.json",
            "contractor_id": sid,
            "elapsed_ms": rss.get("elapsed_ms"),
            "status": rss.get("status"),
            "bytes": rss.get("bytes"),
            "summary": _summarize_stmt(rss) if rss.get("ok") else {},
            "ok": rss.get("ok"),
            "error": rss.get("error_preview"),
            "note": "route re-fetches FULL bulk expenses+payments then filters to one contractor",
        }
    else:
        report["surfaces"]["supplier_ledger_drill"] = {"ok": False, "error": "no supplier"}

    # 6) Customer master list
    rcm = _get("/api/v1/customer-master", api_key, {"limit": 50})
    dcm = rcm.get("data") if isinstance(rcm.get("data"), dict) else {}
    # response shapes vary
    cm_rows = None
    if isinstance(rcm.get("data"), list):
        cm_rows = rcm["data"]
    elif isinstance(dcm, dict):
        cm_rows = dcm.get("customers") or dcm.get("rows") or dcm.get("items") or dcm.get("data")
    report["surfaces"]["customer_master_list"] = {
        "endpoint": "/api/v1/customer-master",
        "elapsed_ms": rcm.get("elapsed_ms"),
        "status": rcm.get("status"),
        "bytes": rcm.get("bytes"),
        "row_count": len(cm_rows) if isinstance(cm_rows, list) else None,
        "top_keys": sorted(list(dcm.keys()))[:20] if isinstance(dcm, dict) else type(rcm.get("data")).__name__,
        "ok": rcm.get("ok"),
        "error": rcm.get("error_preview"),
    }

    # 7) Supplier master list
    rsm = _get("/api/v1/suppliers", api_key, {"limit": 50})
    dsm = rsm.get("data") if isinstance(rsm.get("data"), dict) else {}
    sm_rows = None
    if isinstance(rsm.get("data"), list):
        sm_rows = rsm["data"]
    elif isinstance(dsm, dict):
        sm_rows = dsm.get("suppliers") or dsm.get("rows") or dsm.get("items") or dsm.get("data")
    report["surfaces"]["supplier_master_list"] = {
        "endpoint": "/api/v1/suppliers",
        "elapsed_ms": rsm.get("elapsed_ms"),
        "status": rsm.get("status"),
        "bytes": rsm.get("bytes"),
        "row_count": len(sm_rows) if isinstance(sm_rows, list) else None,
        "top_keys": sorted(list(dsm.keys()))[:20] if isinstance(dsm, dict) else type(rsm.get("data")).__name__,
        "ok": rsm.get("ok"),
        "error": rsm.get("error_preview"),
    }

    # 8) Management Analysis (AR bulk comparison)
    rma = _get("/api/v1/ledgers/management-analysis.json", api_key, {
        "from": ytd_from, "to": ytd_to, "as_of": ytd_to,
    })
    report["surfaces"]["management_analysis"] = {
        "endpoint": "/api/v1/ledgers/management-analysis.json",
        "elapsed_ms": rma.get("elapsed_ms"),
        "status": rma.get("status"),
        "bytes": rma.get("bytes"),
        "summary": _summarize_ma(rma) if rma.get("ok") else {},
        "ok": rma.get("ok"),
        "error": rma.get("error_preview"),
    }

    # N+1 evidence from timing ratios
    e3 = report["surfaces"]["client_balance_limit3"].get("elapsed_ms") or 0
    e15 = report["surfaces"]["client_balance_limit15"].get("elapsed_ms") or 0
    e100 = report["surfaces"]["overview_kpi_limit100"].get("elapsed_ms") or 0
    report["n_plus_one_evidence"] = {
        "limit3_ms": e3,
        "limit15_ms": e15,
        "limit100_ms": e100,
        "ms_per_client_approx_from_15": round(e15 / 15, 1) if e15 else None,
        "ms_per_client_approx_from_3": round(e3 / 3, 1) if e3 else None,
        "scales_with_limit": bool(e15 and e3 and e15 > e3 * 2),
        "code_path": "list_client_balances loops page and calls _build_statement_dict per client "
                     "(contractor preflight + invoices/find + payments/find)",
        "estimated_wfirma_calls_limit15": ">= 15*(1 preflight + >=1 invoices page + >=1 payments page)",
    }

    # Drop raw bodies to keep file small / no PII dump of statements
    OUT_JSON.write_text(json.dumps(report, indent=2), encoding="utf-8")
    # Print ONLY non-secret summary
    print(json.dumps({
        "wrote": str(OUT_JSON),
        "surfaces": {
            k: {
                "ok": v.get("ok"),
                "status": v.get("status"),
                "elapsed_ms": v.get("elapsed_ms"),
                "bytes": v.get("bytes"),
                "summary_keys": list((v.get("summary") or {}).keys()) if isinstance(v.get("summary"), dict) else None,
                "query_stats": (v.get("summary") or {}).get("query_stats") if isinstance(v.get("summary"), dict) else None,
                "row_count": v.get("row_count") or (v.get("summary") or {}).get("rows") or (v.get("summary") or {}).get("suppliers") or (v.get("summary") or {}).get("count"),
            }
            for k, v in report["surfaces"].items()
        },
        "n_plus_one_evidence": report["n_plus_one_evidence"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
