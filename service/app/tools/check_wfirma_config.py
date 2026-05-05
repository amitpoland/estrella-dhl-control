"""
check_wfirma_config.py — wFirma credential and endpoint diagnostic.

Run:
    python3 -m app.tools.check_wfirma_config
    python3 -m app.tools.check_wfirma_config --json
    python3 -m app.tools.check_wfirma_config --config-only

Prints PRESENCE + LENGTH only. Secret values are NEVER printed.

10 checks:
  Config (1-5):
    1. WFIRMA_APP_KEY
    2. WFIRMA_ACCESS_KEY
    3. WFIRMA_SECRET_KEY
    4. WFIRMA_COMPANY_ID
    5. WFIRMA_WAREHOUSE_ID

  Live read-only API (6-10, skipped if config incomplete):
    6. contractors/find  — auth: api_key_headers
    7. goods/find        — auth: api_key_headers
    8. warehouses/find   — auth: api_key_headers
    9. vat_codes/find    — auth: api_key_headers (probe reachability)
   10. vat_code_23_id    — auth: api_key_headers (resolve VAT 23 → ID)

This tool NEVER calls write endpoints.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _bootstrap() -> None:
    here = Path(__file__).resolve()
    repo_root = here.parents[3]   # …/CLI/
    service_dir = here.parents[2]  # …/CLI/service/
    for p in (str(repo_root), str(service_dir)):
        if p not in sys.path:
            sys.path.insert(0, p)


_bootstrap()


# ── Config field specs ────────────────────────────────────────────────────────

_CONFIG_SPECS: List[Dict[str, Any]] = [
    {
        "field":   "wfirma_access_key",
        "env_key": "WFIRMA_ACCESS_KEY",
        "purpose": "accessKey header — from wFirma Ustawienia → Bezpieczeństwo → Klucze API",
        "required": True,
    },
    {
        "field":   "wfirma_secret_key",
        "env_key": "WFIRMA_SECRET_KEY",
        "purpose": "secretKey header — shown once at key creation time",
        "required": True,
    },
    {
        "field":   "wfirma_app_key",
        "env_key": "WFIRMA_APP_KEY",
        "purpose": "appKey header — issued per integration at wfirma.pl/kontakt/1#appKey",
        "required": True,
    },
    {
        "field":   "wfirma_company_id",
        "env_key": "WFIRMA_COMPANY_ID",
        "purpose": "company_id URL parameter — required for every request",
        "required": True,
    },
    {
        "field":   "wfirma_warehouse_id",
        "env_key": "WFIRMA_WAREHOUSE_ID",
        "purpose": "warehouse ID for reservation creation (optional for read-only)",
        "required": False,
    },
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _scan_env_file(path: Path) -> Dict[str, int]:
    """Return {key: value_length} for every key found in .env. No values returned."""
    if not path.is_file():
        return {}
    out: Dict[str, int] = {}
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key:
            out[key] = len(val)
    return out


def _run_config_checks(file_view: Dict[str, int]) -> Tuple[List[Dict[str, Any]], bool]:
    """
    Returns (config_checks, all_required_present).
    Secret values are never included.
    """
    from app.core import config as cfg
    s = cfg.settings

    checks: List[Dict[str, Any]] = []
    required_ok = True

    for spec in _CONFIG_SPECS:
        field_val = getattr(s, spec["field"], None)
        loader_present = bool(field_val)
        loader_len = len(field_val) if isinstance(field_val, str) else 0

        file_len = file_view.get(spec["env_key"], 0)

        checks.append({
            "check":          spec["env_key"],
            "field":          spec["field"],
            "present":        loader_present,
            "len":            loader_len,
            "in_env_file":    file_len > 0,
            "env_file_len":   file_len,
            "required":       spec["required"],
            "purpose":        spec["purpose"],
        })
        if spec["required"] and not loader_present:
            required_ok = False

    return checks, required_ok


def _run_live_checks(warehouse_id: Optional[str]) -> Tuple[List[Dict[str, Any]], Optional[str], bool]:
    """
    Run 5 live read-only API checks.
    Returns (live_checks, vat_code_23_id, warehouse_exists).
    Never raises — each check captures its own exception.
    """
    from app.services import wfirma_client as wfc

    live_checks: List[Dict[str, Any]] = []
    vat_code_23_id: Optional[str] = None
    warehouse_exists = False

    # Check 6 — contractors/find
    try:
        result = wfc.probe_endpoint("contractors", "find")
        live_checks.append({
            "check":        "contractors/find",
            "ok":           result["ok"],
            "http_status":  result["http_status"],
            "wfirma_status": result["wfirma_status"],
            "info":         "reachable" if result["ok"] else result["error"],
            "auth_mode":    "api_key_headers",
        })
    except Exception as exc:  # noqa: BLE001
        live_checks.append({
            "check": "contractors/find", "ok": False, "http_status": 0,
            "wfirma_status": "ERROR", "info": str(exc), "auth_mode": "api_key_headers",
        })

    # Check 7 — goods/find
    try:
        result = wfc.probe_endpoint("goods", "find")
        live_checks.append({
            "check":        "goods/find",
            "ok":           result["ok"],
            "http_status":  result["http_status"],
            "wfirma_status": result["wfirma_status"],
            "info":         "reachable" if result["ok"] else result["error"],
            "auth_mode":    "api_key_headers",
        })
    except Exception as exc:  # noqa: BLE001
        live_checks.append({
            "check": "goods/find", "ok": False, "http_status": 0,
            "wfirma_status": "ERROR", "info": str(exc), "auth_mode": "api_key_headers",
        })

    # Check 8 — warehouses/find
    try:
        warehouses = wfc.list_warehouses()
        if warehouse_id:
            warehouse_exists = any(w["id"] == warehouse_id for w in warehouses)
            info = f"found {len(warehouses)} warehouse(s); WFIRMA_WAREHOUSE_ID match={warehouse_exists}"
        else:
            info = f"found {len(warehouses)} warehouse(s); WFIRMA_WAREHOUSE_ID not set"
        live_checks.append({
            "check":        "warehouses/find",
            "ok":           True,
            "http_status":  200,
            "wfirma_status": "OK",
            "info":         info,
            "auth_mode":    "api_key_headers",
            "warehouses":   warehouses,
        })
    except Exception as exc:  # noqa: BLE001
        live_checks.append({
            "check": "warehouses/find", "ok": False, "http_status": 0,
            "wfirma_status": "ERROR", "info": str(exc), "auth_mode": "api_key_headers",
        })

    # Check 9 — vat_codes/find (reachability probe)
    try:
        result = wfc.probe_endpoint("vat_codes", "find")
        live_checks.append({
            "check":        "vat_codes/find",
            "ok":           result["ok"],
            "http_status":  result["http_status"],
            "wfirma_status": result["wfirma_status"],
            "info":         "reachable" if result["ok"] else result["error"],
            "auth_mode":    "api_key_headers",
        })
    except Exception as exc:  # noqa: BLE001
        live_checks.append({
            "check": "vat_codes/find", "ok": False, "http_status": 0,
            "wfirma_status": "ERROR", "info": str(exc), "auth_mode": "api_key_headers",
        })

    # Check 10 — resolve VAT code "23" → vat_code_23_id
    try:
        vat_id = wfc.find_vat_code_id_live(23)
        vat_code_23_id = vat_id
        ok = vat_id is not None
        live_checks.append({
            "check":        "vat_code_23_id",
            "ok":           ok,
            "http_status":  200,
            "wfirma_status": "OK" if ok else "NOT_FOUND",
            "info":         f"id={vat_id}" if ok else "VAT code 23 not found in wFirma",
            "auth_mode":    "api_key_headers",
            "vat_code_23_id": vat_id,
        })
    except Exception as exc:  # noqa: BLE001
        live_checks.append({
            "check": "vat_code_23_id", "ok": False, "http_status": 0,
            "wfirma_status": "ERROR", "info": str(exc), "auth_mode": "api_key_headers",
        })

    return live_checks, vat_code_23_id, warehouse_exists


# ── Main diagnostic ───────────────────────────────────────────────────────────

def diagnose(env_path: Path, config_only: bool = False) -> Dict[str, Any]:
    """Build the structured diagnostic report. No secret values included."""
    file_view = _scan_env_file(env_path)

    config_checks, config_ok = _run_config_checks(file_view)

    # Warehouse ID for live check 8 comparison
    warehouse_id: Optional[str] = None
    try:
        from app.core import config as cfg
        warehouse_id = cfg.settings.wfirma_warehouse_id or None
    except Exception:  # noqa: BLE001
        pass

    live_checks: List[Dict[str, Any]] = []
    vat_code_23_id: Optional[str] = None
    warehouse_exists = False
    skip_reason: Optional[str] = None

    if config_only:
        skip_reason = "config_only flag set"
    elif not config_ok:
        skip_reason = "required config missing — set WFIRMA_ACCESS_KEY, WFIRMA_SECRET_KEY, WFIRMA_APP_KEY, WFIRMA_COMPANY_ID first"
    else:
        live_checks, vat_code_23_id, warehouse_exists = _run_live_checks(warehouse_id)

    live_ok = all(c["ok"] for c in live_checks) if live_checks else None

    return {
        "env_file_path":    str(env_path),
        "env_file_present": env_path.is_file(),
        "env_file_keys":    len(file_view),
        "config_checks":    config_checks,
        "config_ok":        config_ok,
        "live_checks":      live_checks,
        "live_ok":          live_ok,
        "live_skipped":     skip_reason is not None,
        "live_skip_reason": skip_reason,
        "vat_code_23_id":   vat_code_23_id,
        "warehouse_id":     warehouse_id,
        "warehouse_exists": warehouse_exists,
    }


def _print_human(report: Dict[str, Any]) -> None:
    width = 76
    print("=" * width)
    print(" WFIRMA CONFIG DIAGNOSTIC  (no secret values printed)")
    print("=" * width)
    print(f"  .env path          : {report['env_file_path']}")
    print(f"  .env present       : {report['env_file_present']}")
    print(f"  total keys in .env : {report['env_file_keys']}")
    print()

    # Config checks
    print(f"  {'CHECK':30s} {'PRESENT':>7s} {'LEN':>4s} {'IN_FILE':>7s} {'REQ':>4s}")
    print("  " + "-" * (width - 2))
    for c in report["config_checks"]:
        req_marker = " *" if c["required"] else ""
        print(
            f"  {c['check']:30s} {str(c['present']):>7s} {c['len']:>4d} "
            f"{str(c['in_env_file']):>7s} {req_marker}"
        )
    config_status = "OK" if report["config_ok"] else "MISSING REQUIRED FIELDS"
    print(f"\n  Config: {config_status}")
    print()

    # Live checks
    if report["live_skipped"]:
        print(f"  Live checks SKIPPED: {report['live_skip_reason']}")
    else:
        print(f"  {'LIVE CHECK':30s} {'OK':>5s} {'HTTP':>5s} {'STATUS':>15s}  INFO")
        print("  " + "-" * (width - 2))
        for c in report["live_checks"]:
            tick = "✓" if c["ok"] else "✗"
            print(
                f"  {c['check']:30s} {tick:>5s} {c['http_status']:>5d} "
                f"{c['wfirma_status']:>15s}  {c['info']}"
            )
        print()
        live_status = "ALL OK" if report["live_ok"] else "FAILURES DETECTED"
        print(f"  Live checks: {live_status}")

    print()
    print(f"  vat_code_23_id   : {report['vat_code_23_id'] or '(not resolved)'}")
    print(f"  warehouse_id     : {report['warehouse_id'] or '(not set)'}")
    print(f"  warehouse_exists : {report['warehouse_exists']}")
    print()


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="check_wfirma_config")
    p.add_argument("--env", default=None, help="Path to .env file")
    p.add_argument("--json", action="store_true", help="Emit JSON output")
    p.add_argument("--config-only", action="store_true", help="Skip live API checks")
    args = p.parse_args(argv)

    env_path = (
        Path(args.env)
        if args.env
        else Path(__file__).resolve().parents[3] / "service" / ".env"
    )
    report = diagnose(env_path, config_only=args.config_only)

    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        _print_human(report)

    return 0


if __name__ == "__main__":
    sys.exit(main())
