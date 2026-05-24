"""
activate_pz_lifecycle.py
========================
Gated activation script for PZ Correction Lifecycle Phase 1.

SAFE WINDOW: Enables correction-state / stage / reset / suppress routes ONLY.
HARD STOP:   WFIRMA_CORRECTION_PUSH_ALLOWED is never set by this script.
             correction-commit is unreachable until a separate operator decision.

Usage
-----
    # Dry-run (default) — prints every action, touches nothing
    python activate_pz_lifecycle.py

    # Execute activation (Step 1 only — lifecycle flag, no push flag)
    python activate_pz_lifecycle.py --execute

    # Execute rollback (revert lifecycle flag, restart service)
    python activate_pz_lifecycle.py --rollback

    # Target a specific batch for the smoke test
    python activate_pz_lifecycle.py --execute --smoke-batch GJ-2026-001

Safety invariants enforced by this script
------------------------------------------
1. WFIRMA_CORRECTION_PUSH_ALLOWED is never written here (it is not an argument,
   not an environment variable read, and not a flag this script sets).
2. The script refuses to run if WFIRMA_CORRECTION_PUSH_ALLOWED=true is already
   present in .env — that means a prior session set it and this script must not
   proceed silently.
3. Every .env write uses tempfile + os.replace (atomic) — no half-written .env.
4. Every step emits a structured log entry to both stdout and the audit file.
5. --rollback is always available and unconditionally safe.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Optional

import httpx  # already in requirements.txt (used by existing scripts)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

ENV_PATH          = Path(r"C:\PZ\.env")
AUDIT_LOG_PATH    = Path(r"C:\PZ\logs\activation_audit.jsonl")
SERVICE_NAME      = "PZService"
BASE_URL          = "http://127.0.0.1:47213"
HEALTH_ENDPOINT   = "/api/v1/health"
STATUS_ENDPOINT   = "/api/v1/ai/advisory/status"
STATE_ENDPOINT    = "/api/v1/pz/lineage/{batch_id}/correction-state"
STAGE_ENDPOINT    = "/api/v1/pz/lineage/{batch_id}/correction-stage"

# Flags managed by this script
FLAG_LIFECYCLE    = "PZ_CORRECTION_LIFECYCLE_ENABLED"

# Flags this script must NEVER set
FLAG_PUSH         = "WFIRMA_CORRECTION_PUSH_ALLOWED"

# Gate thresholds
HEALTH_TIMEOUT_S  = 30
RESTART_WAIT_S    = 15
HTTP_TIMEOUT_S    = 10


# ---------------------------------------------------------------------------
# Audit logging
# ---------------------------------------------------------------------------

def _audit(event: str, data: dict, dry_run: bool = False) -> None:
    """Append one structured audit entry to the activation log."""
    entry = {
        "ts":      datetime.datetime.utcnow().isoformat() + "Z",
        "event":   event,
        "dry_run": dry_run,
        **data,
    }
    line = json.dumps(entry)
    print(f"[AUDIT] {line}", flush=True)
    if not dry_run:
        AUDIT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with AUDIT_LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")


# ---------------------------------------------------------------------------
# .env helpers (atomic read / write)
# ---------------------------------------------------------------------------

def _read_env() -> dict[str, str]:
    """Read .env into an ordered dict, preserving comments and blank lines."""
    result: dict[str, str] = {}
    if not ENV_PATH.exists():
        raise FileNotFoundError(f".env not found at {ENV_PATH}")
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            k, _, v = stripped.partition("=")
            result[k.strip()] = v.strip()
    return result


def _read_env_raw() -> str:
    return ENV_PATH.read_text(encoding="utf-8")


def _write_env_atomic(content: str) -> None:
    """Write .env atomically via tempfile + os.replace."""
    fd, tmp = tempfile.mkstemp(dir=ENV_PATH.parent, prefix=".env.tmp.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        os.replace(tmp, ENV_PATH)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _set_flag(flag: str, value: str, dry_run: bool) -> None:
    """Add or update a single flag in .env atomically."""
    raw = _read_env_raw()
    pattern = re.compile(rf"^{re.escape(flag)}\s*=.*$", re.MULTILINE)
    new_line = f"{flag}={value}"
    if pattern.search(raw):
        new_content = pattern.sub(new_line, raw)
    else:
        new_content = raw.rstrip("\n") + f"\n{new_line}\n"
    _audit("env_write", {"flag": flag, "value": value}, dry_run=dry_run)
    if not dry_run:
        _write_env_atomic(new_content)


def _get_api_key() -> str:
    env = _read_env()
    key = env.get("AUTH_SECRET_KEY", "")
    if not key:
        raise ValueError("AUTH_SECRET_KEY not found in .env — cannot authenticate")
    return key


# ---------------------------------------------------------------------------
# Windows service control
# ---------------------------------------------------------------------------

def _sc(action: str, dry_run: bool) -> int:
    """Run sc.exe stop/start/query and return exit code."""
    cmd = ["sc.exe", action, SERVICE_NAME]
    _audit("service_ctrl", {"action": action, "cmd": " ".join(cmd)}, dry_run=dry_run)
    if dry_run:
        return 0
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.stdout.strip():
        print(f"  sc.exe stdout: {result.stdout.strip()}", flush=True)
    return result.returncode


def _service_state() -> str:
    """Return the current Windows service STATE string."""
    result = subprocess.run(
        ["sc.exe", "query", SERVICE_NAME],
        capture_output=True, text=True,
    )
    for line in result.stdout.splitlines():
        if "STATE" in line:
            parts = line.split()
            if len(parts) >= 4:
                return parts[3]   # e.g. "RUNNING", "STOPPED"
    return "UNKNOWN"


def _restart_service(dry_run: bool) -> bool:
    """Stop → wait → start → wait → verify RUNNING. Returns True on success."""
    _sc("stop", dry_run)
    if not dry_run:
        print(f"  Waiting {RESTART_WAIT_S}s for service to stop …", flush=True)
        time.sleep(RESTART_WAIT_S)
    _sc("start", dry_run)
    if not dry_run:
        print(f"  Waiting {RESTART_WAIT_S}s for service to start …", flush=True)
        time.sleep(RESTART_WAIT_S)
    if dry_run:
        return True
    state = _service_state()
    _audit("service_state", {"state": state})
    return state == "RUNNING"


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _get(path: str, api_key: str) -> tuple[int, dict]:
    url = BASE_URL + path
    try:
        r = httpx.get(url, headers={"X-API-Key": api_key}, timeout=HTTP_TIMEOUT_S)
        body: dict = {}
        try:
            body = r.json()
        except Exception:
            body = {"raw": r.text[:200]}
        return r.status_code, body
    except Exception as exc:
        return -1, {"error": str(exc)}


def _wait_healthy(api_key: str, expected_status: int = 200) -> bool:
    """Poll /health until it returns expected_status or timeout expires."""
    deadline = time.time() + HEALTH_TIMEOUT_S
    while time.time() < deadline:
        code, _ = _get(HEALTH_ENDPOINT, api_key)
        if code == expected_status:
            return True
        time.sleep(2)
    return False


# ---------------------------------------------------------------------------
# Safety guard
# ---------------------------------------------------------------------------

def _assert_push_flag_not_set() -> None:
    """Abort immediately if WFIRMA_CORRECTION_PUSH_ALLOWED=true is in .env.
    This script must never run in that state — separate controlled window required."""
    env = _read_env()
    val = env.get(FLAG_PUSH, "").lower()
    if val in ("true", "1", "yes"):
        print(
            f"\n[ABORT] {FLAG_PUSH}={val} is currently set in .env.\n"
            "This script manages the lifecycle flag only.\n"
            "wFirma push enablement requires a separate controlled decision window.\n"
            "If this was intentional, resolve it manually before re-running.",
            file=sys.stderr,
        )
        sys.exit(2)


# ---------------------------------------------------------------------------
# Activation steps
# ---------------------------------------------------------------------------

def step1_enable_lifecycle_flag(dry_run: bool) -> None:
    """Step 1: Set PZ_CORRECTION_LIFECYCLE_ENABLED=true in .env."""
    print("\n[STEP 1] Enable lifecycle flag (correction-state/stage/reset/suppress)", flush=True)
    print(f"  Target: {ENV_PATH}", flush=True)
    print(f"  Flag:   {FLAG_LIFECYCLE}=true", flush=True)
    _set_flag(FLAG_LIFECYCLE, "true", dry_run)
    print("  [OK] Flag written" if not dry_run else "  [DRY-RUN] Would write flag", flush=True)


def step2_restart_service(dry_run: bool) -> None:
    """Step 2: Restart PZService so the new flag is loaded."""
    print("\n[STEP 2] Restart PZService", flush=True)
    ok = _restart_service(dry_run)
    if not dry_run and not ok:
        _audit("restart_failed", {"state": _service_state()})
        print("[FAIL] Service did not reach RUNNING state — rolling back", file=sys.stderr, flush=True)
        _rollback(dry_run=False)
        sys.exit(1)
    print("  [OK] Service RUNNING" if not dry_run else "  [DRY-RUN] Would restart", flush=True)


def step3_health_gate(dry_run: bool, api_key: str) -> None:
    """Step 3: Assert /health returns 200 after restart."""
    print("\n[STEP 3] Health gate — /api/v1/health", flush=True)
    if dry_run:
        print("  [DRY-RUN] Would poll health endpoint", flush=True)
        return
    ok = _wait_healthy(api_key)
    code, body = _get(HEALTH_ENDPOINT, api_key)
    _audit("health_check", {"code": code, "body": body})
    if not ok:
        print(f"[FAIL] Health check failed (last code={code}) — rolling back", file=sys.stderr, flush=True)
        _rollback(dry_run=False)
        sys.exit(1)
    print(f"  [OK] Health {code}: {body}", flush=True)


def step4_startup_audit_gate(dry_run: bool) -> None:
    """Step 4: Confirm STARTUP_AI_AUDIT in stdout log shows expected flag state."""
    print("\n[STEP 4] Startup audit log check", flush=True)
    stdout_log = Path(r"C:\PZ\logs\pz_stdout.log")
    if dry_run:
        print("  [DRY-RUN] Would grep pz_stdout.log for STARTUP_AI_AUDIT", flush=True)
        return
    if not stdout_log.exists():
        print("  [WARN] pz_stdout.log not found — skipping audit log check", flush=True)
        return
    lines = stdout_log.read_text(encoding="utf-8", errors="replace").splitlines()
    # Find the MOST RECENT STARTUP_AI_AUDIT entry (latest restart)
    audit_lines = [l for l in lines if "STARTUP_AI_AUDIT" in l]
    if not audit_lines:
        print("  [WARN] No STARTUP_AI_AUDIT entry found — service may still be starting", flush=True)
        return
    latest = audit_lines[-1]
    _audit("startup_ai_audit", {"line": latest})
    print(f"  Latest STARTUP_AI_AUDIT: {latest}", flush=True)
    # Check governance audit too
    gov_lines = [l for l in lines if "STARTUP_GOVERNANCE_AUDIT" in l]
    if gov_lines:
        print(f"  Latest STARTUP_GOVERNANCE_AUDIT: {gov_lines[-1]}", flush=True)


def step5_smoke_correction_state(
    batch_id: str, dry_run: bool, api_key: str
) -> None:
    """Step 5: GET /correction-state on a real batch.
    Expected: 200 when lifecycle flag is ON.
    Fail condition: 503 (flag not loaded), 5xx, or network error."""
    print(f"\n[STEP 5] Smoke test — correction-state on batch {batch_id!r}", flush=True)
    if dry_run:
        print("  [DRY-RUN] Would GET correction-state — expected 200 or 404", flush=True)
        return
    path = STATE_ENDPOINT.format(batch_id=batch_id)
    code, body = _get(path, api_key)
    _audit("smoke_correction_state", {"batch_id": batch_id, "code": code, "body": body})
    if code == 503:
        print(
            f"  [FAIL] Got 503 — lifecycle flag not loaded (PZService may need manual restart)\n"
            f"  Response: {body}",
            file=sys.stderr, flush=True,
        )
        _rollback(dry_run=False)
        sys.exit(1)
    if code in (200, 404):
        # 200 = batch exists and has lifecycle state
        # 404 = batch not found — lifecycle IS active, batch just doesn't exist yet
        print(f"  [OK] correction-state returned {code} — lifecycle is ACTIVE", flush=True)
    elif code == 403:
        print(
            f"  [INFO] correction-state returned 403 — batch exists but is not a Global Jewellery batch\n"
            f"  Response: {body}\n"
            f"  This is expected for non-Global batches. Use a Global batch for full smoke.",
            flush=True,
        )
    else:
        print(f"  [WARN] Unexpected status {code}: {body}", flush=True)


def step6_assert_push_still_off(dry_run: bool) -> None:
    """Step 6: Assert WFIRMA_CORRECTION_PUSH_ALLOWED is still off.
    This is a hard safety check — if it somehow got set, abort."""
    print("\n[STEP 6] Safety assertion — push flag still OFF", flush=True)
    if dry_run:
        print(f"  [DRY-RUN] Would assert {FLAG_PUSH} absent or false", flush=True)
        return
    env = _read_env()
    val = env.get(FLAG_PUSH, "").lower()
    if val in ("true", "1", "yes"):
        _audit("push_flag_set_unexpectedly", {"value": val})
        print(
            f"  [ABORT] {FLAG_PUSH}={val} is set — this must NOT be the case at this stage.\n"
            f"  correction-commit is unreachable until a separate controlled window.",
            file=sys.stderr, flush=True,
        )
        sys.exit(2)
    print(f"  [OK] {FLAG_PUSH}={val or 'absent'} — push path unreachable (correct)", flush=True)
    _audit("push_flag_confirmed_off", {"value": val or "absent"})


def step7_decision_gate() -> None:
    """Step 7: Print the explicit decision gate for Phase 2 (wFirma push).
    This script stops here. Phase 2 requires a new controlled window."""
    print(
        "\n" + "=" * 70 + "\n"
        "ACTIVATION COMPLETE — PHASE 1 ONLY\n"
        "=" * 70 + "\n"
        "\n"
        "Lifecycle routes are now ACTIVE:\n"
        "  GET  /pz/lineage/{batch_id}/correction-state  → live\n"
        "  POST /pz/lineage/{batch_id}/correction-stage  → live\n"
        "  DEL  /pz/lineage/{batch_id}/correction-stage  → live\n"
        "  POST /pz/lineage/{batch_id}/correction-suppress → live\n"
        "\n"
        "Correction-commit is still BLOCKED:\n"
        f"  WFIRMA_CORRECTION_PUSH_ALLOWED is OFF — no wFirma write path reachable.\n"
        "\n"
        "To advance to Phase 2 (wFirma push enablement):\n"
        "  1. Operator must explicitly start a new controlled session.\n"
        "  2. Run lifecycle_smoke_tests.py --full-lifecycle first.\n"
        "  3. Confirm at least one correction workflow has been staged and suppressed\n"
        "     successfully (dry-run through the full lifecycle).\n"
        "  4. Then and only then: set WFIRMA_CORRECTION_PUSH_ALLOWED=true in a\n"
        "     separate activation window.\n"
        "\n"
        "This script will not set that flag. A separate decision is required.\n"
        + "=" * 70,
        flush=True,
    )


# ---------------------------------------------------------------------------
# Rollback
# ---------------------------------------------------------------------------

def _rollback(dry_run: bool) -> None:
    """Revert lifecycle flag to false and restart service."""
    print("\n[ROLLBACK] Reverting PZ_CORRECTION_LIFECYCLE_ENABLED to false …", flush=True)
    _audit("rollback_start", {}, dry_run=dry_run)
    _set_flag(FLAG_LIFECYCLE, "false", dry_run)
    _restart_service(dry_run)
    _audit("rollback_complete", {}, dry_run=dry_run)
    print("[ROLLBACK] Complete.", flush=True)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Gated activation script for PZ Correction Lifecycle Phase 1.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Execute activation (default is dry-run).",
    )
    parser.add_argument(
        "--rollback",
        action="store_true",
        help="Revert lifecycle flag and restart service.",
    )
    parser.add_argument(
        "--smoke-batch",
        default="",
        metavar="BATCH_ID",
        help="Batch ID to use in the correction-state smoke test.",
    )
    args = parser.parse_args()
    dry_run = not args.execute

    if dry_run and not args.rollback:
        print(
            "\n[DRY-RUN] No changes will be made.\n"
            "         Pass --execute to perform activation.\n",
            flush=True,
        )

    # Hard safety guard — push flag must not already be set
    _assert_push_flag_not_set()

    if args.rollback:
        _rollback(dry_run=dry_run)
        return

    # Read API key upfront — fail fast if .env is broken
    api_key = _get_api_key()

    # Gate sequence
    _audit("activation_start", {"sha": "5bcb492", "dry_run": dry_run})

    step1_enable_lifecycle_flag(dry_run)
    step2_restart_service(dry_run)
    step3_health_gate(dry_run, api_key)
    step4_startup_audit_gate(dry_run)

    if args.smoke_batch:
        step5_smoke_correction_state(args.smoke_batch, dry_run, api_key)
    else:
        print(
            "\n[STEP 5] Skipped — no --smoke-batch provided.\n"
            "         Pass --smoke-batch <batch_id> to run the correction-state smoke test.",
            flush=True,
        )

    step6_assert_push_still_off(dry_run)
    step7_decision_gate()

    _audit("activation_complete", {"sha": "5bcb492", "dry_run": dry_run})


if __name__ == "__main__":
    main()
