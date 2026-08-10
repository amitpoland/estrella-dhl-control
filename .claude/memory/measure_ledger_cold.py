#!/usr/bin/env python3
"""Cold-latency probe: wfirma_wait_ms vs ej_ms (read-only GETs).

Default BASE is instrumented local uvicorn. Pass --prod to hit NSSM :47213
(wall-clock only if prod lacks new query_stats fields).
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ENV_PATH = Path(r"C:\PZ\.env")
OUT_DIR = Path(__file__).resolve().parent
TIMEOUT_S = 180


def _load_api_key() -> str:
    for line in ENV_PATH.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        if k.strip() == "API_KEY":
            val = v.strip().strip('"').strip("'")
            if val:
                return val
    raise SystemExit("API_KEY not found")


def _get(base: str, path: str, api_key: str, params: dict | None = None) -> dict:
    qs = ""
    if params:
        qs = "?" + urllib.parse.urlencode(
            {k: v for k, v in params.items() if v is not None and v != ""}
        )
    url = base + path + qs
    req = urllib.request.Request(
        url, headers={"X-API-Key": api_key, "Accept": "application/json"}
    )
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            raw = resp.read()
            status = resp.status
    except urllib.error.HTTPError as e:
        raw = e.read() if e.fp else b""
        status = e.code
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        return {
            "ok": False,
            "path": path,
            "status": status,
            "elapsed_ms": elapsed_ms,
            "bytes": len(raw),
            "error_preview": raw[:240].decode("utf-8", "replace"),
        }
    except Exception as e:
        return {
            "ok": False,
            "path": path,
            "status": 0,
            "elapsed_ms": int((time.perf_counter() - t0) * 1000),
            "bytes": 0,
            "error_preview": str(e)[:200],
        }
    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    try:
        data = json.loads(raw.decode("utf-8", "replace")) if raw else None
    except json.JSONDecodeError:
        data = None
    qs_body = (data or {}).get("query_stats") or {}
    return {
        "ok": 200 <= status < 300,
        "path": path,
        "status": status,
        "elapsed_ms": elapsed_ms,
        "bytes": len(raw),
        "query_stats": qs_body,
        "period": (data or {}).get("period"),
        "count": (data or {}).get("count")
        or (data or {}).get("supplier_count")
        or (data or {}).get("customer_count"),
        "totals_hint": {
            k: (data or {}).get(k)
            for k in ("totals", "summary", "portfolio_totals")
            if (data or {}).get(k) is not None
        },
    }


def _timing_slice(label: str, res: dict) -> dict:
    qs = res.get("query_stats") or {}
    return {
        "label": label,
        "ok": res.get("ok"),
        "http_elapsed_ms": res.get("elapsed_ms"),
        "wfirma_wait_ms": qs.get("wfirma_wait_ms"),
        "ej_normalize_ms": qs.get("ej_normalize_ms"),
        "ej_aggregate_ms": qs.get("ej_aggregate_ms"),
        "ej_ms": qs.get("ej_ms"),
        "duration_ms": qs.get("duration_ms"),
        "route_wall_ms": qs.get("route_wall_ms"),
        "cache_hit": qs.get("cache_hit"),
        "coalesced": qs.get("coalesced"),
        "per_customer_wfirma_calls": qs.get("per_customer_wfirma_calls"),
        "per_supplier_wfirma_calls": qs.get("per_supplier_wfirma_calls"),
        "invoice_api_calls": qs.get("invoice_api_calls") or qs.get("expense_api_calls"),
        "payment_api_calls": qs.get("payment_api_calls"),
        "invoice_pages": qs.get("invoice_pages") or qs.get("expense_pages"),
        "payment_pages": qs.get("payment_pages"),
        "inv_page_wait_ms": qs.get("inv_page_wait_ms") or qs.get("exp_page_wait_ms"),
        "pay_page_wait_ms": qs.get("pay_page_wait_ms"),
        "invoices_normalized": qs.get("invoices_normalized") or qs.get("expenses_normalized"),
        "payments_normalized": qs.get("payments_normalized"),
        "period": res.get("period"),
        "count": res.get("count"),
        "bytes": res.get("bytes"),
        "error_preview": res.get("error_preview"),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:47214")
    ap.add_argument("--prod", action="store_true", help="use http://127.0.0.1:47213")
    ap.add_argument("--from", dest="date_from", default="")
    ap.add_argument("--to", dest="date_to", default="")
    ap.add_argument("--tag", default="instrumented")
    args = ap.parse_args()

    base = "http://127.0.0.1:47213" if args.prod else args.base
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    y = today[:4]
    df = args.date_from or f"{y}-01-01"
    dt = args.date_to or today
    api_key = _load_api_key()

    # Windows: this_month / quarter for decision evidence
    m = int(today[5:7])
    q_start_m = ((m - 1) // 3) * 3 + 1
    this_month_from = f"{y}-{m:02d}-01"
    quarter_from = f"{y}-{q_start_m:02d}-01"

    report: dict = {
        "measured_at": datetime.now(timezone.utc).isoformat(),
        "base": base,
        "tag": args.tag,
        "windows": {
            "ytd": (df, dt),
            "quarter": (quarter_from, dt),
            "this_month": (this_month_from, dt),
        },
        "probes": [],
    }

    def probe(label: str, path: str, params: dict) -> None:
        res = _get(base, path, api_key, params)
        report["probes"].append(_timing_slice(label, res))
        print(
            f"{label}: http={res.get('elapsed_ms')}ms "
            f"wfirma={ (res.get('query_stats') or {}).get('wfirma_wait_ms') } "
            f"ej={ (res.get('query_stats') or {}).get('ej_ms') } "
            f"cache={ (res.get('query_stats') or {}).get('cache_hit') } "
            f"ok={res.get('ok')}"
        )

    # Cold YTD (force refresh)
    probe(
        "cold_ar_clients_ytd",
        "/api/v1/ledgers/clients",
        {"from": df, "to": dt, "limit": 15, "refresh": 1},
    )
    probe(
        "cold_ar_ma_ytd",
        "/api/v1/ledgers/management-analysis.json",
        {"from": df, "to": dt, "as_of": dt, "refresh": 1},
    )
    probe(
        "cold_ap_payables_ytd",
        "/api/v1/ledgers/payables-analysis.json",
        {"from": df, "to": dt, "as_of": dt, "status": "outstanding", "refresh": 1},
    )

    # Warm (same window, no refresh — should hit TTL)
    probe(
        "warm_ar_clients_ytd",
        "/api/v1/ledgers/clients",
        {"from": df, "to": dt, "limit": 15, "refresh": 0},
    )
    probe(
        "warm_ap_payables_ytd",
        "/api/v1/ledgers/payables-analysis.json",
        {"from": df, "to": dt, "as_of": dt, "status": "outstanding", "refresh": 0},
    )

    # Narrower windows (cold) for decision evidence
    probe(
        "cold_ar_clients_quarter",
        "/api/v1/ledgers/clients",
        {"from": quarter_from, "to": dt, "limit": 15, "refresh": 1},
    )
    probe(
        "cold_ap_payables_quarter",
        "/api/v1/ledgers/payables-analysis.json",
        {
            "from": quarter_from,
            "to": dt,
            "as_of": dt,
            "status": "outstanding",
            "refresh": 1,
        },
    )
    probe(
        "cold_ar_clients_month",
        "/api/v1/ledgers/clients",
        {"from": this_month_from, "to": dt, "limit": 15, "refresh": 1},
    )
    probe(
        "cold_ap_payables_month",
        "/api/v1/ledgers/payables-analysis.json",
        {
            "from": this_month_from,
            "to": dt,
            "as_of": dt,
            "status": "outstanding",
            "refresh": 1,
        },
    )

    out_json = OUT_DIR / f"measure-ledger-cold-{args.tag}.json"
    out_json.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"wrote {out_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
