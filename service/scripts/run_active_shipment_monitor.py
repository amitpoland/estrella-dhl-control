#!/usr/bin/env python3
"""
run_active_shipment_monitor.py — cron entrypoint for the active shipment sweeper.

Designed to run every 10 minutes via launchd / cron. Hits the local service
endpoint instead of importing in-process so it goes through the same auth +
import_result validation path as a manual run.

Usage:
    python3 scripts/run_active_shipment_monitor.py
    python3 scripts/run_active_shipment_monitor.py --force         # include terminal
    python3 scripts/run_active_shipment_monitor.py --base http://localhost:8000

Sample crontab line (every 10 min):
    */10 * * * * /usr/bin/python3 /Users/amitgupta/Downloads/CLI/service/scripts/run_active_shipment_monitor.py >> /tmp/monitor.log 2>&1
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone


def main() -> int:
    p = argparse.ArgumentParser(description="Run the active shipment monitor.")
    p.add_argument("--base",    default="http://localhost:8000", help="Service base URL")
    p.add_argument("--force",   action="store_true",             help="Include terminal shipments")
    p.add_argument("--quiet",   action="store_true",             help="Suppress per-action log output")
    p.add_argument("--api-key", default=os.getenv("API_KEY", ""),
                   help="X-API-Key for the PZ service (falls back to API_KEY env var)")
    args = p.parse_args()

    api_key = args.api_key
    if not api_key:
        print(
            "[monitor] ERROR: API_KEY is required but not set. "
            "Pass --api-key <key> or set the API_KEY environment variable.",
            file=sys.stderr,
        )
        return 2

    url = f"{args.base.rstrip('/')}/api/v1/monitor/active-shipments/run"
    if args.force:
        url += "?force=true"

    req = urllib.request.Request(url, method="POST", headers={"X-API-Key": api_key})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"[monitor] HTTP {e.code} — {e.read().decode('utf-8', errors='replace')[:200]}",
              file=sys.stderr)
        return 2
    except Exception as e:
        print(f"[monitor] request failed: {e}", file=sys.stderr)
        return 3

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    summary = (
        f"[monitor {ts}] scanned={data.get('scanned',0)} "
        f"active={data.get('active',0)} actions={len(data.get('actions') or [])}"
    )
    print(summary)

    if not args.quiet:
        for a in (data.get("actions") or []):
            bits = [a.get("batch_id", "?")]
            if a.get("awb"):
                bits.append(f"awb={a['awb']}")
            if a.get("status"):
                bits.append(f"status={a['status']}")
            if a.get("applied_cache", {}).get("applied"):
                ap = a["applied_cache"]
                bits.append(f"applied(advanced={ap.get('advanced_status') or '-'})")
            if a.get("dispatched_task"):
                bits.append(f"dispatched={a['dispatched_task'][:8]}...")
            elif a.get("reused_task"):
                bits.append(f"reused={a['reused_task'][:8]}...")
            sla = a.get("sla", {})
            if sla.get("dhl_email_overdue"):
                bits.append("⚠ DHL email overdue")
            if sla.get("dhl_reply_overdue"):
                bits.append("⚠ DHL reply overdue")
            if sla.get("required_actions"):
                bits.append(f"need: {','.join(sla['required_actions'])}")
            if a.get("error"):
                bits.append(f"ERROR: {a['error']}")
            print("  " + " | ".join(bits))
    return 0


if __name__ == "__main__":
    sys.exit(main())
