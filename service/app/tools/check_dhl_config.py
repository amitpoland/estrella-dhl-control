"""
check_dhl_config.py — DHL tracking credential diagnostic.

Run:
    python3 -m service.app.tools.check_dhl_config
    python3 -m service.app.tools.check_dhl_config --json

Prints PRESENCE + LENGTH only, never the credential value itself.

Output explains:
  - which .env file the loader read
  - whether each expected DHL key is set
  - which mode `get_tracking_mode()` resolves to
  - what the next operator action should be

This tool DOES NOT make any HTTP call to DHL. It is read-only.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Dict, Any, List


def _bootstrap() -> None:
    here = Path(__file__).resolve()
    repo_root = here.parents[3]
    service_dir = here.parents[2]
    for p in (str(repo_root), str(service_dir)):
        if p not in sys.path:
            sys.path.insert(0, p)


_bootstrap()


# ── DHL credential aliases ────────────────────────────────────────────────────
# Maps each canonical Settings field to the env keys it accepts. The loader
# (pydantic-settings) only consumes the FIRST entry per field; this list is
# used for diagnostic comparison so we can spot operator typos like
# DHL_API_KEY_TRACKING vs DHL_TRACKING_API_KEY.
EXPECTED_KEYS: List[Dict[str, Any]] = [
    {
        "field":   "dhl_tracking_api_key",
        "primary": "DHL_TRACKING_API_KEY",
        "aliases": ["DHL_TRACKING_API_KEY", "DHL_CLIENT_ID"],
        "purpose": "Unified API client_id (OAuth2)",
    },
    {
        "field":   "dhl_tracking_api_secret",
        "primary": "DHL_TRACKING_API_SECRET",
        "aliases": ["DHL_TRACKING_API_SECRET", "DHL_CLIENT_SECRET"],
        "purpose": "Unified API client_secret (OAuth2)",
    },
    {
        "field":   "dhl_tracking_api_status",
        "primary": "DHL_TRACKING_API_STATUS",
        "aliases": ["DHL_TRACKING_API_STATUS"],
        "purpose": "Mode flag: active | disabled | failed",
    },
    {
        "field":   "dhl_api_key",
        "primary": "DHL_API_KEY",
        "aliases": ["DHL_API_KEY"],
        "purpose": "Legacy DHL-API-Key header (only fallback)",
    },
]


def _scan_env_file(path: Path) -> Dict[str, int]:
    """Return {key: length_of_value} for keys in a dotenv file. No values returned."""
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


def _settings_view() -> Dict[str, Any]:
    """Return the loader's view of the relevant Settings fields, no secrets."""
    from app.core import config as cfg
    s = cfg.settings
    return {
        "dhl_tracking_api_key":    {"present": bool(s.dhl_tracking_api_key),    "len": len(s.dhl_tracking_api_key    or "")},
        "dhl_tracking_api_secret": {"present": bool(s.dhl_tracking_api_secret), "len": len(s.dhl_tracking_api_secret or "")},
        "dhl_tracking_api_status": {"present": bool(s.dhl_tracking_api_status), "value": s.dhl_tracking_api_status or ""},
        "dhl_api_key":             {"present": bool(s.dhl_api_key),             "len": len(s.dhl_api_key             or "")},
    }


def diagnose(env_path: Path) -> Dict[str, Any]:
    """Build the structured diagnostic report (no secret values)."""
    file_view  = _scan_env_file(env_path)
    settings_view = _settings_view()

    from app.services.tracking_service import get_tracking_mode
    mode = get_tracking_mode()

    # Per-field detection
    fields: List[Dict[str, Any]] = []
    for spec in EXPECTED_KEYS:
        primary = spec["primary"]
        present_in_file = file_view.get(primary, 0) > 0
        # Look for any alias that has a value
        alias_hit = None
        for a in spec["aliases"]:
            if file_view.get(a, 0) > 0:
                alias_hit = a
                break
        fields.append({
            "field":               spec["field"],
            "primary_env_key":     primary,
            "present_in_env_file": present_in_file,
            "primary_value_length": file_view.get(primary, 0),
            "alias_used":          alias_hit if (alias_hit and alias_hit != primary) else None,
            "loader_present":      settings_view[spec["field"]]["present"],
            "purpose":             spec["purpose"],
        })

    # Decide root cause
    key_present  = settings_view["dhl_tracking_api_key"]["present"]
    sec_present  = settings_view["dhl_tracking_api_secret"]["present"]
    status_value = settings_view["dhl_tracking_api_status"]["value"].lower()

    if not key_present and not sec_present and status_value in ("", "pending", "disabled"):
        root_cause = (
            "DHL_TRACKING_API_KEY and DHL_TRACKING_API_SECRET are absent or empty "
            "in the .env file. Set both, restart the server, then expect mode='active'."
        )
    elif not key_present and not sec_present and status_value == "active":
        root_cause = (
            "Status is 'active' but credentials are missing — this is inconsistent. "
            "Either set the credentials or change DHL_TRACKING_API_STATUS to 'disabled'."
        )
    elif (key_present and sec_present) and status_value != "active":
        root_cause = (
            f"Credentials are loaded but DHL_TRACKING_API_STATUS='{status_value}' (expected 'active'). "
            "Change to DHL_TRACKING_API_STATUS=active in .env and restart the server."
        )
    elif key_present and sec_present and status_value == "active":
        root_cause = "All preconditions met. If the dashboard still shows disabled, restart the server to pick up new env."
    else:
        root_cause = "Partial configuration — review the per-field table above."

    return {
        "env_file_path":        str(env_path),
        "env_file_present":     env_path.is_file(),
        "env_file_keys_total":  len(file_view),
        "fields":               fields,
        "loader_settings":      settings_view,
        "tracking_mode":        mode,
        "root_cause":           root_cause,
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="check_dhl_config")
    p.add_argument("--env", default=None, help="Path to .env file (defaults to service/.env)")
    p.add_argument("--json", action="store_true", help="Emit JSON")
    args = p.parse_args(argv)

    env_path = Path(args.env) if args.env else (Path(__file__).resolve().parents[3] / "service" / ".env")
    report = diagnose(env_path)

    if args.json:
        print(json.dumps(report, indent=2, default=str))
        return 0

    print("=" * 76)
    print(" DHL TRACKING CREDENTIAL DIAGNOSTIC (no secret values printed)")
    print("=" * 76)
    print(f"  .env path             : {report['env_file_path']}")
    print(f"  .env present          : {report['env_file_present']}")
    print(f"  total keys in .env    : {report['env_file_keys_total']}")
    print()
    print(f"  {'FIELD':28s} {'IN_ENV':>6s} {'LEN':>4s} {'LOADER':>7s} {'ALIAS':>10s}")
    print("  " + "-" * 70)
    for f in report["fields"]:
        print(f"  {f['field']:28s} {str(f['present_in_env_file']):>6s} "
              f"{f['primary_value_length']:>4d} {str(f['loader_present']):>7s} "
              f"{(f['alias_used'] or '-'):>10s}")
    print()
    print(f"  DHL_TRACKING_API_STATUS = {report['loader_settings']['dhl_tracking_api_status']['value']!r}")
    print(f"  get_tracking_mode()     = {report['tracking_mode']!r}")
    print()
    print("  ROOT CAUSE:")
    print(f"    {report['root_cause']}")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
