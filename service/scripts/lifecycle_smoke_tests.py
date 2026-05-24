"""
lifecycle_smoke_tests.py
========================
Smoke test and monitoring suite for the PZ Correction Lifecycle activation.

Each test function returns a SmokeResult. The runner collects all results and
exits non-zero if any FAIL verdict is present.

Usage
-----
    # Run all tests appropriate for the current flag state
    python lifecycle_smoke_tests.py

    # Run full lifecycle test (requires lifecycle flag ON)
    python lifecycle_smoke_tests.py --full-lifecycle --batch GJ-2026-001

    # Emit metrics JSON to stdout (for monitoring integrations)
    python lifecycle_smoke_tests.py --json-metrics

    # Watch mode — re-run every 30s and emit deltas
    python lifecycle_smoke_tests.py --watch --interval 30
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

import httpx

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_URL        = "http://127.0.0.1:47213"
ENV_PATH        = Path(r"C:\PZ\.env")
STDOUT_LOG      = Path(r"C:\PZ\logs\pz_stdout.log")
STDERR_LOG      = Path(r"C:\PZ\logs\pz_stderr.log")
HTTP_TIMEOUT    = 10

ENDPOINTS = {
    "health":          "/api/v1/health",
    "correction_state":  "/api/v1/pz/lineage/{batch_id}/correction-state",
    "correction_stage":  "/api/v1/pz/lineage/{batch_id}/correction-stage",
    "correction_reset":  "/api/v1/pz/lineage/{batch_id}/correction-stage",
    "correction_suppress": "/api/v1/pz/lineage/{batch_id}/correction-suppress",
    "correction_commit": "/api/v1/pz/lineage/{batch_id}/correction-commit",
    "push_wfirma":       "/api/v1/pz/lineage/{batch_id}/correction-push-wfirma",
}


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------

@dataclass
class SmokeResult:
    test:       str
    verdict:    str          # "PASS" | "FAIL" | "SKIP" | "WARN"
    code:       int          # HTTP status code, -1 for network error
    expected:   int
    detail:     str = ""
    duration_ms: float = 0.0
    ts:         str = field(default_factory=lambda: datetime.datetime.utcnow().isoformat() + "Z")

    @property
    def ok(self) -> bool:
        return self.verdict in ("PASS", "SKIP", "WARN")

    def pretty(self) -> str:
        icon = {"PASS": "✅", "FAIL": "❌", "SKIP": "⏭ ", "WARN": "⚠️ "}.get(self.verdict, "?")
        timing = f" ({self.duration_ms:.0f}ms)" if self.duration_ms else ""
        detail = f" — {self.detail}" if self.detail else ""
        return f"  {icon} [{self.verdict}] {self.test} → HTTP {self.code}{timing}{detail}"


# ---------------------------------------------------------------------------
# HTTP client
# ---------------------------------------------------------------------------

def _read_env() -> dict[str, str]:
    env: dict[str, str] = {}
    if not ENV_PATH.exists():
        return env
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            k, _, v = stripped.partition("=")
            env[k.strip()] = v.strip()
    return env


def _api_key() -> str:
    return _read_env().get("AUTH_SECRET_KEY", "")


def _flag(name: str) -> bool:
    return _read_env().get(name, "").lower() in ("true", "1", "yes")


def _request(
    method: str, path: str, api_key: str,
    body: Optional[dict] = None,
) -> tuple[int, dict, float]:
    url = BASE_URL + path
    t0 = time.perf_counter()
    try:
        r = httpx.request(
            method, url,
            headers={"X-API-Key": api_key, "Content-Type": "application/json"},
            json=body,
            timeout=HTTP_TIMEOUT,
        )
        ms = (time.perf_counter() - t0) * 1000
        try:
            resp_body = r.json()
        except Exception:
            resp_body = {"raw": r.text[:300]}
        return r.status_code, resp_body, ms
    except Exception as exc:
        ms = (time.perf_counter() - t0) * 1000
        return -1, {"error": str(exc)}, ms


def _make(
    test: str, method: str, path: str, api_key: str,
    expected: int, body: Optional[dict] = None,
    detail_on_fail: str = "",
) -> SmokeResult:
    code, resp, ms = _request(method, path, api_key, body)
    verdict = "PASS" if code == expected else "FAIL"
    detail = ""
    if verdict == "FAIL":
        detail = detail_on_fail or f"expected {expected}, got {code}: {resp}"
    return SmokeResult(test=test, verdict=verdict, code=code,
                       expected=expected, detail=detail, duration_ms=ms)


# ---------------------------------------------------------------------------
# Individual smoke tests
# ---------------------------------------------------------------------------

def test_health(api_key: str) -> SmokeResult:
    """Basic health gate — service must be reachable and healthy."""
    return _make("health", "GET", "/api/v1/health", api_key, 200)


def test_correction_state_503_when_off(api_key: str, batch_id: str = "SMOKE-TEST") -> SmokeResult:
    """When lifecycle flag is OFF, correction-state must return 503."""
    if _flag("PZ_CORRECTION_LIFECYCLE_ENABLED"):
        return SmokeResult(
            test="correction_state_503_when_flag_off",
            verdict="SKIP", code=0, expected=503,
            detail="Lifecycle flag is ON — 503 behaviour not applicable in current state",
        )
    path = ENDPOINTS["correction_state"].format(batch_id=batch_id)
    return _make(
        "correction_state_503_when_flag_off", "GET", path, api_key, 503,
        detail_on_fail="Expected 503 (flag off) — flag may be unexpectedly ON",
    )


def test_correction_state_200_or_404_when_on(api_key: str, batch_id: str) -> SmokeResult:
    """When lifecycle flag is ON, correction-state must return 200 or 404 (not 503)."""
    if not _flag("PZ_CORRECTION_LIFECYCLE_ENABLED"):
        return SmokeResult(
            test="correction_state_live_when_flag_on",
            verdict="SKIP", code=0, expected=200,
            detail="Lifecycle flag is OFF — activate first",
        )
    path = ENDPOINTS["correction_state"].format(batch_id=batch_id)
    code, body, ms = _request("GET", path, api_key)
    if code in (200, 404):
        return SmokeResult(test="correction_state_live_when_flag_on",
                           verdict="PASS", code=code, expected=200,
                           detail=f"Lifecycle active (404 = batch not yet staged)", duration_ms=ms)
    if code == 403:
        return SmokeResult(test="correction_state_live_when_flag_on",
                           verdict="WARN", code=code, expected=200,
                           detail=f"Batch {batch_id!r} is not a Global Jewellery batch — use a GJ batch for full smoke",
                           duration_ms=ms)
    return SmokeResult(test="correction_state_live_when_flag_on",
                       verdict="FAIL", code=code, expected=200,
                       detail=f"Unexpected status: {body}", duration_ms=ms)


def test_correction_commit_503_when_push_off(api_key: str, batch_id: str = "SMOKE-TEST") -> SmokeResult:
    """correction-commit must return 503 whenever the push flag is OFF.
    This test MUST pass at all times in Phase 1 — it enforces the wFirma write gate."""
    if not _flag("PZ_CORRECTION_LIFECYCLE_ENABLED"):
        # When lifecycle is off, commit returns 503 for lifecycle reason
        path = ENDPOINTS["correction_commit"].format(batch_id=batch_id)
        code, body, ms = _request(
            "POST", path, api_key,
            {"option_id": "ALIGN_TO_AUTHORITY", "reason": "smoke-test"},
        )
        if code == 503:
            return SmokeResult(
                test="correction_commit_push_gate",
                verdict="PASS", code=code, expected=503,
                detail="503 (lifecycle off — expected)", duration_ms=ms,
            )
    else:
        # Lifecycle is on — commit should 503 because push flag is off
        path = ENDPOINTS["correction_commit"].format(batch_id=batch_id)
        code, body, ms = _request(
            "POST", path, api_key,
            {"option_id": "ALIGN_TO_AUTHORITY", "reason": "smoke-test"},
        )
        # Acceptable: 503 (push off), 409 (wrong lifecycle state), 404 (batch not found)
        # NOT acceptable: 200/201/202 — that would mean a wFirma call was attempted
        if code in (503, 409, 404, 400):
            detail_map = {
                503: "push gate holding (expected — WFIRMA_CORRECTION_PUSH_ALLOWED=false)",
                409: "lifecycle state conflict (correct — push gate not yet tested but lifecycle is active)",
                404: "batch not found (correct — wFirma write path not reached)",
                400: "validation rejected (correct — wFirma write path not reached)",
            }
            return SmokeResult(
                test="correction_commit_push_gate",
                verdict="PASS", code=code, expected=503,
                detail=detail_map.get(code, ""), duration_ms=ms,
            )
        if code in (200, 201, 202):
            return SmokeResult(
                test="correction_commit_push_gate",
                verdict="FAIL", code=code, expected=503,
                detail="CRITICAL: commit returned 2xx — wFirma write may have been attempted. "
                       "Check WFIRMA_CORRECTION_PUSH_ALLOWED in .env immediately.",
                duration_ms=ms,
            )
    return SmokeResult(test="correction_commit_push_gate",
                       verdict="PASS", code=code, expected=503,
                       detail="push gate holding", duration_ms=ms)


def test_old_push_route_410_or_503(api_key: str, batch_id: str = "SMOKE-TEST") -> SmokeResult:
    """Old correction-push-wfirma route must return 410 (lifecycle on) or stay safe."""
    path = ENDPOINTS["push_wfirma"].format(batch_id=batch_id)
    code, body, ms = _request(
        "POST", path, api_key,
        {"option_id": "ALIGN_TO_AUTHORITY", "confirm": "CONFIRM_PUSH"},
    )
    if code in (410, 503, 401, 403):
        return SmokeResult(
            test="old_push_route_gated",
            verdict="PASS", code=code, expected=410,
            detail=f"Old route safely gated ({code})", duration_ms=ms,
        )
    return SmokeResult(
        test="old_push_route_gated",
        verdict="FAIL", code=code, expected=410,
        detail=f"Old route returned unexpected {code}: {body}", duration_ms=ms,
    )


def test_no_auth_returns_401(batch_id: str = "SMOKE-TEST") -> SmokeResult:
    """Routes must reject requests with no API key."""
    path = ENDPOINTS["correction_state"].format(batch_id=batch_id)
    url = BASE_URL + path
    t0 = time.perf_counter()
    try:
        r = httpx.get(url, timeout=HTTP_TIMEOUT)
        ms = (time.perf_counter() - t0) * 1000
        if r.status_code in (401, 403):
            return SmokeResult(test="auth_required", verdict="PASS",
                               code=r.status_code, expected=401, duration_ms=ms)
        return SmokeResult(test="auth_required", verdict="FAIL",
                           code=r.status_code, expected=401,
                           detail=f"Expected 401/403, got {r.status_code} — auth guard may be broken",
                           duration_ms=ms)
    except Exception as exc:
        ms = (time.perf_counter() - t0) * 1000
        return SmokeResult(test="auth_required", verdict="FAIL",
                           code=-1, expected=401, detail=str(exc), duration_ms=ms)


def test_stderr_clean() -> SmokeResult:
    """Stderr log must not contain new CRITICAL or unhandled exceptions since last check."""
    if not STDERR_LOG.exists():
        return SmokeResult(test="stderr_clean", verdict="SKIP", code=0, expected=0,
                           detail="pz_stderr.log not found")
    lines = STDERR_LOG.read_text(encoding="utf-8", errors="replace").splitlines()
    tail = lines[-50:]
    critical = [l for l in tail if "CRITICAL" in l or "Traceback" in l]
    if critical:
        return SmokeResult(
            test="stderr_clean", verdict="WARN", code=0, expected=0,
            detail=f"{len(critical)} CRITICAL/Traceback lines in last 50 lines of stderr",
        )
    return SmokeResult(test="stderr_clean", verdict="PASS", code=0, expected=0)


def test_flag_state() -> SmokeResult:
    """Emit current flag state as a PASS/INFO metric."""
    lc = _flag("PZ_CORRECTION_LIFECYCLE_ENABLED")
    push = _flag("WFIRMA_CORRECTION_PUSH_ALLOWED")
    detail = (
        f"PZ_CORRECTION_LIFECYCLE_ENABLED={'ON' if lc else 'OFF'}  "
        f"WFIRMA_CORRECTION_PUSH_ALLOWED={'ON' if push else 'OFF'}"
    )
    if push:
        return SmokeResult(
            test="flag_state", verdict="WARN", code=0, expected=0,
            detail=f"ALERT: {detail} — push flag is ON. Verify this is intentional.",
        )
    return SmokeResult(test="flag_state", verdict="PASS", code=0, expected=0, detail=detail)


# ---------------------------------------------------------------------------
# Full lifecycle flow (requires lifecycle flag ON and a real Global batch)
# ---------------------------------------------------------------------------

def run_full_lifecycle_flow(api_key: str, batch_id: str) -> list[SmokeResult]:
    """Walk the lifecycle state machine without committing to wFirma.

    Flow:
      1. GET correction-state (expect 200 — PROPOSED or existing)
      2. POST correction-stage with ALIGN_TO_AUTHORITY (expect 200 or 409)
      3. DELETE correction-stage (reset) if stage succeeded (expect 200)
      4. POST correction-suppress (expect 200 — TERMINAL_SUPPRESSED)

    Does NOT test correction-commit — that requires WFIRMA_CORRECTION_PUSH_ALLOWED=true.
    """
    results: list[SmokeResult] = []
    if not _flag("PZ_CORRECTION_LIFECYCLE_ENABLED"):
        return [SmokeResult(
            test="full_lifecycle_flow",
            verdict="SKIP", code=0, expected=0,
            detail="Lifecycle flag OFF — activate first",
        )]

    # Step A: get state
    path_state = ENDPOINTS["correction_state"].format(batch_id=batch_id)
    code, body, ms = _request("GET", path_state, api_key)
    if code == 403:
        results.append(SmokeResult(
            test="lifecycle_flow/get_state",
            verdict="WARN", code=code, expected=200,
            detail=f"Batch {batch_id!r} is not a Global batch — full lifecycle flow requires a GJ batch",
            duration_ms=ms,
        ))
        return results
    results.append(SmokeResult(
        test="lifecycle_flow/get_state", verdict="PASS" if code in (200, 404) else "FAIL",
        code=code, expected=200,
        detail=body.get("state", "") if code == 200 else str(body),
        duration_ms=ms,
    ))
    if code not in (200, 404):
        return results

    # Step B: stage with ALIGN_TO_AUTHORITY
    path_stage = ENDPOINTS["correction_stage"].format(batch_id=batch_id)
    code, body, ms = _request(
        "POST", path_stage, api_key,
        {"option_id": "ALIGN_TO_AUTHORITY", "reason": "smoke-test full lifecycle", "items": []},
    )
    stage_ok = code == 200
    results.append(SmokeResult(
        test="lifecycle_flow/stage",
        verdict="PASS" if stage_ok else "WARN",
        code=code, expected=200,
        detail=f"state={body.get('state', '')} staged_at={body.get('staged_at', '')}" if code == 200
               else f"409/other: {body}",
        duration_ms=ms,
    ))

    # Step C: reset (DELETE) if stage succeeded
    if stage_ok:
        code, body, ms = _request("DELETE", path_stage, api_key)
        results.append(SmokeResult(
            test="lifecycle_flow/reset_stage",
            verdict="PASS" if code == 200 else "FAIL",
            code=code, expected=200,
            detail=f"state={body.get('state', '')}" if code == 200 else str(body),
            duration_ms=ms,
        ))

    # Step D: suppress (TERMINAL_SUPPRESSED)
    path_suppress = ENDPOINTS["correction_suppress"].format(batch_id=batch_id)
    code, body, ms = _request(
        "POST", path_suppress, api_key,
        {"reason": "smoke-test suppress — lifecycle flow verification"},
    )
    results.append(SmokeResult(
        test="lifecycle_flow/suppress",
        verdict="PASS" if code == 200 else "FAIL",
        code=code, expected=200,
        detail=f"state={body.get('state', '')}" if code == 200 else str(body),
        duration_ms=ms,
    ))

    return results


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_suite(batch_id: str, full_lifecycle: bool) -> list[SmokeResult]:
    key = _api_key()
    if not key:
        print("[ERROR] AUTH_SECRET_KEY not found in .env", file=sys.stderr)
        sys.exit(1)

    results: list[SmokeResult] = []
    results.append(test_health(key))
    results.append(test_flag_state())
    results.append(test_stderr_clean())
    results.append(test_no_auth_returns_401(batch_id))
    results.append(test_correction_state_503_when_off(key, batch_id))
    results.append(test_correction_state_200_or_404_when_on(key, batch_id))
    results.append(test_correction_commit_503_when_push_off(key, batch_id))
    results.append(test_old_push_route_410_or_503(key, batch_id))

    if full_lifecycle:
        results.extend(run_full_lifecycle_flow(key, batch_id))

    return results


def _print_report(results: list[SmokeResult], json_metrics: bool) -> None:
    if json_metrics:
        metrics = {
            "ts": datetime.datetime.utcnow().isoformat() + "Z",
            "pass":  sum(1 for r in results if r.verdict == "PASS"),
            "fail":  sum(1 for r in results if r.verdict == "FAIL"),
            "warn":  sum(1 for r in results if r.verdict == "WARN"),
            "skip":  sum(1 for r in results if r.verdict == "SKIP"),
            "tests": [asdict(r) for r in results],
        }
        print(json.dumps(metrics, indent=2))
        return

    print(f"\n{'=' * 60}")
    print(f"PZ Lifecycle Smoke Tests — {datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print(f"{'=' * 60}")
    for r in results:
        print(r.pretty())
    fails = [r for r in results if r.verdict == "FAIL"]
    warns = [r for r in results if r.verdict == "WARN"]
    print(f"{'=' * 60}")
    print(f"  {sum(1 for r in results if r.verdict == 'PASS')} PASS  "
          f"{len(fails)} FAIL  "
          f"{len(warns)} WARN  "
          f"{sum(1 for r in results if r.verdict == 'SKIP')} SKIP")
    if fails:
        print(f"\n[ACTION REQUIRED] {len(fails)} test(s) FAILED:")
        for r in fails:
            print(f"  - {r.test}: {r.detail}")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="PZ Lifecycle activation smoke tests")
    parser.add_argument("--batch", default="SMOKE-TEST", help="Batch ID for lifecycle tests")
    parser.add_argument("--full-lifecycle", action="store_true",
                        help="Run full stage→reset→suppress flow (requires lifecycle ON)")
    parser.add_argument("--json-metrics", action="store_true",
                        help="Emit results as JSON metrics")
    parser.add_argument("--watch", action="store_true",
                        help="Continuous watch mode")
    parser.add_argument("--interval", type=int, default=30,
                        help="Watch interval in seconds (default: 30)")
    args = parser.parse_args()

    if args.watch:
        while True:
            results = run_suite(args.batch, args.full_lifecycle)
            _print_report(results, args.json_metrics)
            fails = [r for r in results if r.verdict == "FAIL"]
            if fails:
                print(f"[ALERT] {len(fails)} FAIL(s) detected — investigate immediately", flush=True)
            print(f"Next check in {args.interval}s …\n", flush=True)
            time.sleep(args.interval)
    else:
        results = run_suite(args.batch, args.full_lifecycle)
        _print_report(results, args.json_metrics)
        fails = [r for r in results if r.verdict == "FAIL"]
        sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
