from __future__ import annotations

"""
Debug endpoints — Guardian Agent observability layer.

GET  /api/v1/debug/pending      → ring buffers + active sessions + pending dict
GET  /api/v1/debug/health-full  → capability-aware system diagnostic (required-only overall)
POST /api/v1/debug/post-pz-test → fire a test message to #PZ and report delivery
"""

import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, Request

from ..core.config import settings
from ..core.logging import get_logger
from ..core.security import require_api_key, require_api_key_privileged
from ..services import cliq_service
from ..services.batch_manager import manager as batch_manager
from ..services.diagnostics_capability_health import (
    REQ_DEPRECATED,
    REQ_NOT_APPLICABLE,
    REQ_OPTIONAL,
    REQ_REQUIRED,
    STATUS_DEPRECATED,
    STATUS_FAIL,
    STATUS_NOT_APPLICABLE,
    STATUS_NOT_CONFIGURED,
    STATUS_OK,
    STATUS_WARN,
    aggregate_checks,
    classify_http_reachability,
    make_check,
    openapi_paths_from_app,
    probe_backup_freshness,
    probe_pdf_unicode_font,
    read_deploy_marker_sha,
)
# storage_health is a stdlib-only utility with no path back to this module, so
# eager module-level import is safe and avoids a lazy-first-import race: FastAPI
# runs the sync storage/* endpoints in a threadpool, and a lazy import here meant
# two concurrent first-touches saw the half-initialised module in sys.modules and
# raised "partially initialized module ... (circular import)". (BUG 2)
from ..utils.storage_health import scan_locks, storage_health_snapshot

router = APIRouter(prefix="/api/v1/debug", tags=["debug"])
_auth  = Depends(require_api_key)
# H-R5 (#502): mutating/side-effect debug actions are privileged.
# Read-only diagnostics (GET pending / health-full / storage/*) keep _auth.
_privileged = Depends(require_api_key_privileged)
log    = get_logger(__name__)


# ── helpers (legacy aliases — prefer make_check with requirement class) ───────

def _ok(detail: str = "") -> dict:
    return make_check(status=STATUS_OK, requirement=REQ_OPTIONAL, detail=detail)

def _fail(detail: str, fix: str = "") -> dict:
    return make_check(status=STATUS_FAIL, requirement=REQ_OPTIONAL, detail=detail, fix=fix)

def _warn(detail: str) -> dict:
    return make_check(status=STATUS_WARN, requirement=REQ_OPTIONAL, detail=detail)


@router.get("/pending", dependencies=[_auth])
async def debug_pending() -> Dict[str, Any]:
    """
    Return a snapshot of live bot pipeline state:
    - active_sessions  : sessions currently in batch_manager
    - bot_pending      : chats in the debounce accumulator
    - last_bot_events  : last 20 /bot-event calls
    - last_stage_events: last 20 pipeline stage transitions
    - last_pz_posts    : last 20 post_to_channel() calls
    - last_errors      : last 20 errors
    """
    # Import ring buffers lazily to avoid circular import
    from .routes_bot import (
        LAST_BOT_EVENTS,
        LAST_STAGE_EVENTS,
        LAST_PZ_POSTS,
        LAST_ERRORS,
        _pending,
    )

    sessions = batch_manager.all_summaries()

    return {
        "active_sessions":   sessions,
        "bot_pending":       {
            chat_id: {
                "message_text": v.get("message_text", "")[:80],
                "last_seen_ago_s": round(__import__("time").monotonic() - v["last_seen"], 1),
                "processing": v.get("processing", False),
            }
            for chat_id, v in _pending.items()
        },
        "last_bot_events":   list(LAST_BOT_EVENTS),
        "last_stage_events": list(LAST_STAGE_EVENTS),
        "last_pz_posts":     list(LAST_PZ_POSTS),
        "last_errors":       list(LAST_ERRORS),
        "counts": {
            "pending_chats":   len(_pending),
            "active_sessions": len(sessions),
            "bot_events_seen": len(LAST_BOT_EVENTS),
            "stage_events":    len(LAST_STAGE_EVENTS),
            "pz_posts":        len(LAST_PZ_POSTS),
            "errors":          len(LAST_ERRORS),
        },
    }


@router.get("/health-full", dependencies=[_auth])
async def health_full(request: Request) -> Dict[str, Any]:
    """
    Capability-aware Guardian snapshot.

    Each check carries requirement ∈ {required, optional, deprecated, not_applicable}
    and status ∈ {ok, warn, fail, not_configured, deprecated, not_applicable}.
    Global ``overall`` / fail_count count REQUIRED failures only.
    """
    from .routes_bot import LAST_BOT_EVENTS, LAST_PZ_POSTS, LAST_ERRORS, LAST_STAGE_EVENTS

    results: Dict[str, Any] = {}
    # Prefer the request's own base URL (production :47213); never hardcode :8000.
    local_base = str(request.base_url).rstrip("/")
    api_headers = {"X-API-Key": settings.api_key} if settings.api_key else {}

    # ── 1: FastAPI running (REQUIRED) — in-process first ─────────────────────
    try:
        import pz_import_processor  # noqa: F401
        engine_import = "ok"
    except ImportError as e:
        engine_import = f"import error: {e}"

    in_process_ok = engine_import == "ok"
    http_detail = ""
    http_status: Optional[int] = None
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(f"{local_base}/api/v1/health")
        http_status = r.status_code
        st, msg = classify_http_reachability(r.status_code, expect_auth=True)
        http_detail = msg
        if r.status_code == 200:
            try:
                body = r.json()
                http_detail = f"{msg}; engine={body.get('engine', '?')}"
            except Exception:
                pass
    except Exception as e:
        http_detail = f"self-probe unreachable via {local_base}: {e}"
        st = STATUS_WARN

    if in_process_ok:
        results["1_fastapi_running"] = make_check(
            status=STATUS_OK,
            requirement=REQ_REQUIRED,
            detail=(
                f"in-process healthy (engine import ok); "
                f"HTTP self-probe {http_detail or 'skipped'}"
            ),
            evidence={"base": local_base, "http_status": http_status},
        )
    else:
        results["1_fastapi_running"] = make_check(
            status=STATUS_FAIL,
            requirement=REQ_REQUIRED,
            detail=f"in-process engine import failed: {engine_import}",
            fix="Verify engine_dir sync (Lesson J) and PZService AppDirectory",
        )

    # ── 2: Public domain (REQUIRED reachability) ─────────────────────────────
    public_url = (settings.fastapi_public_url or "").rstrip("/")
    if not public_url:
        results["2_public_domain"] = make_check(
            status=STATUS_WARN,
            requirement=REQ_REQUIRED,
            detail="fastapi_public_url not configured",
        )
    else:
        try:
            async with httpx.AsyncClient(timeout=8) as client:
                r = await client.get(f"{public_url}/api/v1/health")
            st, msg = classify_http_reachability(r.status_code, expect_auth=True)
            results["2_public_domain"] = make_check(
                status=st if st != STATUS_WARN or r.status_code in (401, 403, 200) else st,
                requirement=REQ_REQUIRED,
                detail=f"{public_url} → {msg}",
                evidence={"http_status": r.status_code},
            )
            # Expected protected auth is OK for required reachability
            if r.status_code in (401, 403, 200) or 300 <= r.status_code < 400:
                results["2_public_domain"]["status"] = STATUS_OK
        except Exception as e:
            results["2_public_domain"] = make_check(
                status=STATUS_FAIL,
                requirement=REQ_REQUIRED,
                detail=f"{public_url} unreachable: {e}",
                fix="Check Cloudflare tunnel / DNS / TLS — not an auth misconfiguration",
            )

    # ── 3: Routes registered (REQUIRED core set) ─────────────────────────────
    required_routes = [
        "/api/v1/health",
        "/api/v1/debug/pending",
        "/api/v1/debug/health-full",
        "/api/v1/system/version",
    ]
    try:
        registered = openapi_paths_from_app(request.app)
        missing = [rt for rt in required_routes if rt not in registered]
        if missing:
            results["3_routes_registered"] = make_check(
                status=STATUS_FAIL,
                requirement=REQ_REQUIRED,
                detail=f"Missing core routes: {missing}",
                fix="Add app.include_router(...) in main.py",
            )
        else:
            results["3_routes_registered"] = make_check(
                status=STATUS_OK,
                requirement=REQ_REQUIRED,
                detail=f"{len(set(registered))} route paths; core set present (in-process)",
            )
    except Exception as e:
        results["3_routes_registered"] = make_check(
            status=STATUS_FAIL,
            requirement=REQ_REQUIRED,
            detail=str(e),
        )

    # ── 4: Sessions endpoint (DEPRECATED BatchManager) ───────────────────────
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(
                f"{local_base}/api/v1/batch/sessions",
                headers=api_headers,
            )
        if r.status_code == 410:
            results["4_sessions_endpoint"] = make_check(
                status=STATUS_DEPRECATED,
                requirement=REQ_DEPRECATED,
                detail="HTTP 410 — old Cliq BatchManager flow disabled (expected)",
                evidence={"http_status": 410},
            )
        elif r.status_code == 200 and settings.debug_allow_old_batch_flow:
            d = r.json()
            results["4_sessions_endpoint"] = make_check(
                status=STATUS_OK,
                requirement=REQ_DEPRECATED,
                detail=f"legacy flow re-enabled; count={d.get('count', '?')}",
            )
        else:
            results["4_sessions_endpoint"] = make_check(
                status=STATUS_DEPRECATED,
                requirement=REQ_DEPRECATED,
                detail=f"HTTP {r.status_code} — treated as deprecated BatchManager surface",
            )
    except Exception as e:
        results["4_sessions_endpoint"] = make_check(
            status=STATUS_DEPRECATED,
            requirement=REQ_DEPRECATED,
            detail=f"probe skipped/failed ({e}); BatchManager remains deprecated",
        )

    # ── 5: Dashboard HTML (OPTIONAL — V2 is frontend authority) ──────────────
    _static_dir = Path(__file__).parent.parent / "static"
    _dash_file = _static_dir / "dashboard.html"
    disk_ok = _dash_file.exists()
    disk_sz = _dash_file.stat().st_size if disk_ok else 0
    if disk_ok:
        results["5_dashboard_html"] = make_check(
            status=STATUS_OK,
            requirement=REQ_OPTIONAL,
            detail=f"V1 dashboard.html on disk ({disk_sz:,} bytes); V2 is canonical UI",
        )
    else:
        results["5_dashboard_html"] = make_check(
            status=STATUS_WARN,
            requirement=REQ_OPTIONAL,
            detail="dashboard.html missing on disk (V2 may still be healthy)",
            fix=f"Restore if V1 shell still needed: {_dash_file}",
        )

    # ── 6: Bot events (OPTIONAL) ─────────────────────────────────────────────
    recent_events = list(LAST_BOT_EVENTS)
    if recent_events:
        last = recent_events[-1]
        results["6_bot_events"] = make_check(
            status=STATUS_OK,
            requirement=REQ_OPTIONAL,
            detail=(
                f"{len(recent_events)} events in buffer; last={last.get('ts', '')} "
                f"chat={last.get('chat_id', '')}"
            ),
        )
    else:
        results["6_bot_events"] = make_check(
            status=STATUS_NOT_CONFIGURED,
            requirement=REQ_OPTIONAL,
            detail="No bot events since startup — optional Cliq intake idle",
        )

    # ── 7: Cliq OAuth config (OPTIONAL) ──────────────────────────────────────
    has_channel_webhook = bool(settings.cliq_channel_webhook_url)
    has_bot_token = bool(settings.cliq_bot_token)
    has_refresh_token = bool(settings.cliq_refresh_token)
    has_oauth_creds = bool(settings.cliq_client_id and settings.cliq_client_secret)

    oauth_issues: List[str] = []
    if not has_channel_webhook:
        oauth_issues.append("CLIQ_CHANNEL_WEBHOOK_URL missing")
    if not has_bot_token:
        oauth_issues.append("CLIQ_BOT_TOKEN missing")
    if not has_refresh_token:
        oauth_issues.append("CLIQ_REFRESH_TOKEN missing")
    if not has_oauth_creds:
        oauth_issues.append("CLIQ_CLIENT_ID/SECRET missing")

    if oauth_issues:
        results["7_cliq_oauth_config"] = make_check(
            status=STATUS_NOT_CONFIGURED,
            requirement=REQ_OPTIONAL,
            detail="; ".join(oauth_issues),
        )
    else:
        results["7_cliq_oauth_config"] = make_check(
            status=STATUS_OK,
            requirement=REQ_OPTIONAL,
            detail="channel webhook + bot token + refresh token configured",
        )

    # ── 8: File download token (OPTIONAL) ────────────────────────────────────
    if has_bot_token or has_refresh_token:
        results["8_file_download_token"] = make_check(
            status=STATUS_OK,
            requirement=REQ_OPTIONAL,
            detail=(
                "Bearer token source available "
                f"(bot_token={'yes' if has_bot_token else 'no'}, "
                f"refresh_token={'yes' if has_refresh_token else 'no'})"
            ),
        )
    else:
        results["8_file_download_token"] = make_check(
            status=STATUS_NOT_CONFIGURED,
            requirement=REQ_OPTIONAL,
            detail="No Cliq OAuth token — file download optional; core platform unaffected",
        )

    # ── 9: Engine (REQUIRED) ─────────────────────────────────────────────────
    engine_dir = settings.engine_dir
    if engine_dir.exists():
        pz_proc = engine_dir / "pz_import_processor.py"
        audit_py = engine_dir / "audit_agent.py"
        missing_files = [str(f) for f in [pz_proc, audit_py] if not f.exists()]
        if missing_files:
            results["9_engine"] = make_check(
                status=STATUS_FAIL,
                requirement=REQ_REQUIRED,
                detail=f"Missing engine files: {missing_files}",
                fix="Run Lesson J engine sync via Deploy-PZ",
            )
        else:
            results["9_engine"] = make_check(
                status=STATUS_OK,
                requirement=REQ_REQUIRED,
                detail=f"engine_dir={engine_dir}, core files present",
            )
    else:
        results["9_engine"] = make_check(
            status=STATUS_FAIL,
            requirement=REQ_REQUIRED,
            detail=f"engine_dir not found: {engine_dir}",
        )

    # ── 10: #PZ posting (OPTIONAL) ───────────────────────────────────────────
    recent_posts = list(LAST_PZ_POSTS)
    if recent_posts:
        last_post = recent_posts[-1]
        if last_post.get("ok"):
            results["10_pz_posting"] = make_check(
                status=STATUS_OK,
                requirement=REQ_OPTIONAL,
                detail=(
                    f"last post delivered=True at {last_post.get('ts', '')} "
                    f"stage={last_post.get('stage', '')}"
                ),
            )
        else:
            results["10_pz_posting"] = make_check(
                status=STATUS_WARN,
                requirement=REQ_OPTIONAL,
                detail=(
                    f"Last optional #PZ post FAILED at {last_post.get('ts', '')} "
                    f"preview={last_post.get('preview', '')[:60]}"
                ),
                fix="Optional: POST /api/v1/debug/post-pz-test when Cliq notify is in use",
            )
    else:
        results["10_pz_posting"] = make_check(
            status=STATUS_NOT_CONFIGURED,
            requirement=REQ_OPTIONAL,
            detail="No #PZ posts since startup — optional notification idle",
        )

    # ── 11: Output files (REQUIRED dir presence) ─────────────────────────────
    output_root = settings.storage_root / "outputs"
    if output_root.exists():
        batch_dirs = sorted(output_root.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
        recent = []
        for bd in batch_dirs[:5]:
            if bd.is_dir():
                files = [f.name for f in bd.iterdir() if f.is_file()]
                recent.append({"batch": bd.name, "files": files})
        results["11_output_files"] = make_check(
            status=STATUS_OK,
            requirement=REQ_REQUIRED,
            detail=(
                f"{len(batch_dirs)} batch dirs in {output_root}; "
                f"most recent: {recent[0] if recent else 'none'}"
            ),
        )
    else:
        results["11_output_files"] = make_check(
            status=STATUS_WARN,
            requirement=REQ_REQUIRED,
            detail=f"Output dir not found: {output_root} — created on first run",
        )

    # ── 12: Audit PDF font via renderer authority (REQUIRED) ─────────────────
    font_ok, font_detail, font_fix = probe_pdf_unicode_font()
    results["12_audit_font"] = make_check(
        status=STATUS_OK if font_ok else STATUS_FAIL,
        requirement=REQ_REQUIRED,
        detail=font_detail,
        fix=font_fix,
    )

    # ── 13: Backup freshness (OPTIONAL / WARN) ───────────────────────────────
    results["13_backup_freshness"] = probe_backup_freshness(Path(settings.backup_root))

    # ── Deploy version projection (informational, not a scored check) ────────
    deploy_sha, deploy_src = read_deploy_marker_sha()
    results["14_deploy_version"] = make_check(
        status=STATUS_OK if deploy_sha else STATUS_WARN,
        requirement=REQ_OPTIONAL,
        detail=(
            f"deployed_sha={deploy_sha or 'missing'} (source={deploy_src}); "
            f"runtime_mode={settings.environment}"
        ),
        evidence={"deployed_sha": deploy_sha, "source": deploy_src, "runtime_mode": settings.environment},
    )

    summary = aggregate_checks(results)
    return {
        **summary,
        "checks": results,
        "ring_buffer_sizes": {
            "bot_events":   len(list(LAST_BOT_EVENTS)),
            "stage_events": len(list(LAST_STAGE_EVENTS)),
            "pz_posts":     len(list(LAST_PZ_POSTS)),
            "errors":       len(list(LAST_ERRORS)),
        },
        "config": {
            "environment":           settings.environment,
            "engine_dir":            str(settings.engine_dir),
            "storage_root":          str(settings.storage_root),
            "fastapi_public_url":    settings.fastapi_public_url,
            "local_probe_base":      local_base,
            "bot_debounce_seconds":  settings.bot_debounce_seconds,
            "channel_webhook_set":   has_channel_webhook,
            "bot_token_set":         has_bot_token,
            "refresh_token_set":     has_refresh_token,
            "oauth_creds_set":       has_oauth_creds,
            "deployed_sha":          deploy_sha,
            "deploy_marker_source":  deploy_src,
        },
    }


@router.post("/clear-test-sessions", dependencies=[_privileged])
async def clear_test_sessions(force: bool = False) -> Dict[str, Any]:
    """
    Remove sessions with synthetic/test user keys (user456, test, demo, …).
    Pass ?force=true to wipe ALL sessions regardless of key type.
    """
    if force:
        count = batch_manager.clear_all_sessions()
        return {"status": "ok", "cleared": count, "mode": "force_all"}
    removed = batch_manager.clear_test_sessions()
    return {
        "status":  "ok",
        "cleared": len(removed),
        "mode":    "test_only",
        "batch_ids": removed,
    }


@router.get("/storage/health", dependencies=[_auth])
def storage_health() -> Dict[str, Any]:
    """
    Full storage health snapshot.

    Returns a structured report covering:
    - outputs/ directory classification (real, test, quarantine, anomalous batches)
    - .audit.lock probe (lock_files_found, actively_held, releasable)
    - ok=False if test_batches > 0 (live storage pollution) or actively_held > 0

    Quarantine and anomalous dirs generate warnings but do not set ok=False.

    This endpoint is read-only and makes no writes.
    """
    return storage_health_snapshot(settings.storage_root)


@router.get("/storage/locks", dependencies=[_auth])
def storage_locks() -> Dict[str, Any]:
    """
    Scan all .audit.lock files in outputs/ and report their flock status.

    Each file is probed non-destructively (opened read-only, LOCK_EX|LOCK_NB).
    - releasable   → lock file exists but flock is not held (safe to ignore)
    - actively_held → flock held by another OS process (possible stuck worker)

    macOS / same-process caveat: actively_held=True only detects locks held by
    OTHER OS processes (e.g. a crashed uvicorn worker). Threads in the same
    process always appear releasable.
    """
    outputs_dir = settings.storage_root / "outputs"
    return scan_locks(outputs_dir)


@router.post("/post-pz-test", dependencies=[_privileged])
async def post_pz_test() -> Dict[str, Any]:
    """
    Fire a test message to #PZ and return whether delivery succeeded.
    Use this to verify the channel webhook is alive without triggering a real batch.
    """
    from datetime import datetime, timezone
    ts   = datetime.now(timezone.utc).isoformat()
    text = f"🧪 PZ test message — {ts}\nIf you see this in #PZ, the channel webhook is working."

    log.info("debug/post-pz-test: sending test message to #PZ")
    ok = await cliq_service.post_to_channel(text)
    log.info("debug/post-pz-test: delivered=%s", ok)

    return {
        "delivered": ok,
        "timestamp": ts,
        "preview":   text[:120],
        "channel":   "pz",
    }
