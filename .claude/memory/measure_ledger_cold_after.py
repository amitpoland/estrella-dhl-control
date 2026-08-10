#!/usr/bin/env python3
"""After-default-window cold/warm probe (read-only)."""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE = "http://127.0.0.1:47214"
ENV_PATH = Path(r"C:\PZ\.env")
OUT = Path(__file__).with_name("measure-ledger-cold-after.json")


def load_key() -> str:
    for line in ENV_PATH.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if s.startswith("API_KEY="):
            return s.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("API_KEY missing")


def get(path: str, params: dict) -> dict:
    qs = "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        BASE + path + qs,
        headers={"X-API-Key": load_key(), "Accept": "application/json"},
    )
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=180) as resp:
        raw = resp.read()
    elapsed = int((time.perf_counter() - t0) * 1000)
    data = json.loads(raw.decode("utf-8"))
    qs_body = data.get("query_stats") or {}
    keys = (
        "wfirma_wait_ms",
        "ej_ms",
        "ej_normalize_ms",
        "ej_aggregate_ms",
        "duration_ms",
        "cache_hit",
        "per_customer_wfirma_calls",
        "per_supplier_wfirma_calls",
        "refresh",
    )
    return {
        "path": path,
        "elapsed_ms": elapsed,
        "period": data.get("period"),
        "qs": {k: qs_body.get(k) for k in keys},
    }


def main() -> int:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    probes = []
    for label, path, params in (
        ("cold_default_clients", "/api/v1/ledgers/clients", {"limit": 15, "refresh": 1}),
        ("warm_default_clients", "/api/v1/ledgers/clients", {"limit": 15, "refresh": 0}),
        (
            "cold_explicit_ytd_clients",
            "/api/v1/ledgers/clients",
            {"from": f"{today[:4]}-01-01", "to": today, "limit": 15, "refresh": 1},
        ),
        (
            "cold_quarter_ap",
            "/api/v1/ledgers/payables-analysis.json",
            {
                "from": "2026-07-01",
                "to": today,
                "as_of": today,
                "status": "outstanding",
                "refresh": 1,
            },
        ),
        (
            "warm_quarter_ap",
            "/api/v1/ledgers/payables-analysis.json",
            {
                "from": "2026-07-01",
                "to": today,
                "as_of": today,
                "status": "outstanding",
                "refresh": 0,
            },
        ),
    ):
        res = get(path, params)
        probes.append({"label": label, **res})
        print(label, res["elapsed_ms"], res.get("period"), res["qs"])
    OUT.write_text(
        json.dumps(
            {"measured_at": datetime.now(timezone.utc).isoformat(), "probes": probes},
            indent=2,
        ),
        encoding="utf-8",
    )
    print("wrote", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
