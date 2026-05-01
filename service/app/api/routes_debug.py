from __future__ import annotations

"""
Debug endpoints — Guardian Agent observability layer.

GET  /api/v1/debug/pending      → ring buffers + active sessions + pending dict
GET  /api/v1/debug/health-full  → full 12-point system diagnostic (Guardian snapshot)
POST /api/v1/debug/post-pz-test → fire a test message to #PZ and report delivery
"""

import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends

from ..core.config import settings
from ..core.logging import get_logger
from ..core.security import require_api_key
from ..services import cliq_service
from ..services.batch_manager import manager as batch_manager

router = APIRouter(prefix="/api/v1/debug", tags=["debug"])
_auth  = Depends(require_api_key)
log    = get_logger(__name__)


# ── helpers ───────────────────────────────────────────────────────────────────

def _ok(detail: str = "") -> dict:
    return {"status": "ok", "detail": detail}

def _fail(detail: str, fix: str = "") -> dict:
    d: dict = {"status": "fail", "detail": detail}
    if fix:
        d["fix"] = fix
    return d

def _warn(detail: str) -> dict:
    return {"status": "warn", "detail": detail}


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
async def health_full() -> Dict[str, Any]:
    """
    Guardian Agent snapshot — all 12 diagnostic dimensions in one call.

    Steps:
      1  fastapi_running        → /api/v1/health responds
      2  public_domain          → Cloudflare tunnel alive
      3  routes_registered      → required routes present in OpenAPI
      4  sessions_endpoint      → /api/v1/batch/sessions returns valid JSON
      5  dashboard_html         → dashboard.html serves with HTTP 200
      6  bot_events             → ring buffer has recent events (informational)
      7  cliq_file_discovery    → OAuth token configured
      8  file_download          → OAuth Bearer token non-empty
      9  engine                 → engine dir exists + make verify status (cached)
     10  pz_posting             → last post_to_channel result
     11  output_files           → outputs/ directory exists, recent batches listed
     12  audit_reports          → Arial Unicode font available for Polish glyphs
    """
    from .routes_bot import LAST_BOT_EVENTS, LAST_PZ_POSTS, LAST_ERRORS, LAST_STAGE_EVENTS

    results: Dict[str, Any] = {}
    overall_ok = True

    # ── Step 1: FastAPI running ───────────────────────────────────────────────
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get("http://localhost:8000/api/v1/health")
        if r.status_code == 200 and r.json().get("status") == "ok":
            results["1_fastapi_running"] = _ok(f"engine={r.json().get('engine','?')}")
        else:
            results["1_fastapi_running"] = _fail(f"HTTP {r.status_code}", "Check uvicorn process and logs")
            overall_ok = False
    except Exception as e:
        results["1_fastapi_running"] = _fail(str(e), "Start: python3 -m uvicorn app.main:app --port 8000")
        overall_ok = False

    # ── Step 2: Public domain ─────────────────────────────────────────────────
    public_url = settings.fastapi_public_url.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.get(f"{public_url}/api/v1/health")
        if r.status_code == 200:
            results["2_public_domain"] = _ok(public_url)
        else:
            results["2_public_domain"] = _warn(f"{public_url} → HTTP {r.status_code} (tunnel may be down)")
    except Exception as e:
        results["2_public_domain"] = _warn(f"{public_url} unreachable: {e} — check Cloudflare tunnel")

    # ── Step 3: Routes registered ─────────────────────────────────────────────
    required_routes = [
        "/api/v1/health",
        "/api/v1/cliq/bot-event",
        "/api/v1/batch/sessions",
        "/api/v1/batch/start",
        "/api/v1/batch/add",
        "/api/v1/batch/submit",
        "/api/v1/debug/pending",
        "/api/v1/debug/health-full",
        "/api/v1/debug/post-pz-test",
    ]
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get("http://localhost:8000/openapi.json")
        registered = list(r.json().get("paths", {}).keys())
        missing = [rt for rt in required_routes if rt not in registered]
        if missing:
            results["3_routes_registered"] = _fail(
                f"Missing: {missing}",
                "Add app.include_router(...) in main.py"
            )
            overall_ok = False
        else:
            results["3_routes_registered"] = _ok(f"{len(registered)} routes total, all required present")
    except Exception as e:
        results["3_routes_registered"] = _fail(str(e))
        overall_ok = False

    # ── Step 4: Sessions endpoint ─────────────────────────────────────────────
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get("http://localhost:8000/api/v1/batch/sessions")
        if r.status_code == 200:
            d = r.json()
            results["4_sessions_endpoint"] = _ok(f"count={d.get('count', '?')}")
        else:
            results["4_sessions_endpoint"] = _fail(
                f"HTTP {r.status_code}: {r.text[:100]}",
                "Check batch_manager.all_summaries() for exceptions"
            )
            overall_ok = False
    except Exception as e:
        results["4_sessions_endpoint"] = _fail(str(e))
        overall_ok = False

    # ── Step 5: Dashboard HTML ────────────────────────────────────────────────
    # The route is session-protected, so an unauthenticated request correctly
    # returns HTTP 302 → /login.  We accept 200 OR 302 as passing.
    # We only fail on 404 (file missing) or 5xx (server error).
    # We also verify the static file exists on disk as a secondary check.
    _static_dir = Path(__file__).parent.parent / "static"
    _dash_file  = _static_dir / "dashboard.html"
    try:
        async with httpx.AsyncClient(
            timeout=5, follow_redirects=False
        ) as client:
            r = await client.get("http://localhost:8000/dashboard/dashboard.html")

        if r.status_code in (200, 302):
            disk_ok  = _dash_file.exists()
            disk_sz  = _dash_file.stat().st_size if disk_ok else 0
            if not disk_ok:
                results["5_dashboard_html"] = _fail(
                    f"Route returns {r.status_code} but static file missing on disk",
                    f"Restore: {_dash_file}"
                )
                overall_ok = False
            elif r.status_code == 302:
                results["5_dashboard_html"] = _ok(
                    f"Protected (302→/login as expected) — file on disk: {disk_sz:,} bytes"
                )
            else:
                results["5_dashboard_html"] = _ok(f"{disk_sz:,} bytes")
        elif r.status_code == 404:
            results["5_dashboard_html"] = _fail(
                "HTTP 404 — route not registered or static file missing",
                "Run: bash deploy-pz.sh and verify dashboard.html in app/static/"
            )
            overall_ok = False
        else:
            results["5_dashboard_html"] = _fail(
                f"HTTP {r.status_code}",
                "Unexpected error — check uvicorn logs"
            )
            overall_ok = False
    except Exception as e:
        results["5_dashboard_html"] = _fail(str(e))
        overall_ok = False

    # ── Step 6: Bot events (informational) ───────────────────────────────────
    recent_events = list(LAST_BOT_EVENTS)
    if recent_events:
        last = recent_events[-1]
        results["6_bot_events"] = _ok(
            f"{len(recent_events)} events in buffer; last={last.get('ts','')} "
            f"chat={last.get('chat_id','')}"
        )
    else:
        results["6_bot_events"] = _warn(
            "No bot events received since startup — normal if no file uploaded yet; "
            "if upload happened: check Deluge handler URL and API key"
        )

    # ── Step 7: Cliq OAuth config ────────────────────────────────────────────
    has_channel_webhook = bool(settings.cliq_channel_webhook_url)
    has_bot_token       = bool(settings.cliq_bot_token)
    has_refresh_token   = bool(settings.cliq_refresh_token)
    has_oauth_creds     = bool(settings.cliq_client_id and settings.cliq_client_secret)

    oauth_issues: List[str] = []
    if not has_channel_webhook: oauth_issues.append("CLIQ_CHANNEL_WEBHOOK_URL missing")
    if not has_bot_token:       oauth_issues.append("CLIQ_BOT_TOKEN missing")
    if not has_refresh_token:   oauth_issues.append("CLIQ_REFRESH_TOKEN missing (auto-refresh disabled)")
    if not has_oauth_creds:     oauth_issues.append("CLIQ_CLIENT_ID or CLIQ_CLIENT_SECRET missing")

    if oauth_issues:
        results["7_cliq_oauth_config"] = _warn("; ".join(oauth_issues))
    else:
        results["7_cliq_oauth_config"] = _ok("channel webhook + bot token + refresh token configured")

    # ── Step 8: OAuth Bearer token non-empty ─────────────────────────────────
    # We just check config — actual token validity is only provable on a live call
    if has_bot_token or has_refresh_token:
        results["8_file_download_token"] = _ok(
            "Bearer token source available "
            f"(bot_token={'yes' if has_bot_token else 'no'}, "
            f"refresh_token={'yes' if has_refresh_token else 'no'})"
        )
    else:
        results["8_file_download_token"] = _fail(
            "No OAuth token configured — file downloads will fail",
            "Set CLIQ_BOT_TOKEN or CLIQ_REFRESH_TOKEN + CLIQ_CLIENT_ID + CLIQ_CLIENT_SECRET in .env"
        )
        overall_ok = False

    # ── Step 9: Engine dir + health ──────────────────────────────────────────
    engine_dir = settings.engine_dir
    if engine_dir.exists():
        pz_proc = engine_dir / "pz_import_processor.py"
        audit_py = engine_dir / "audit_agent.py"
        missing_files = [str(f) for f in [pz_proc, audit_py] if not f.exists()]
        if missing_files:
            results["9_engine"] = _fail(f"Missing engine files: {missing_files}")
            overall_ok = False
        else:
            results["9_engine"] = _ok(f"engine_dir={engine_dir}, core files present")
    else:
        results["9_engine"] = _fail(f"engine_dir not found: {engine_dir}")
        overall_ok = False

    # ── Step 10: #PZ posting ─────────────────────────────────────────────────
    recent_posts = list(LAST_PZ_POSTS)
    if recent_posts:
        last_post = recent_posts[-1]
        if last_post.get("ok"):
            results["10_pz_posting"] = _ok(
                f"last post delivered=True at {last_post.get('ts','')} "
                f"stage={last_post.get('stage','')}"
            )
        else:
            results["10_pz_posting"] = _fail(
                f"Last post FAILED at {last_post.get('ts','')} preview={last_post.get('preview','')[:60]}",
                "Run POST /api/v1/debug/post-pz-test — check CLIQ_CHANNEL_WEBHOOK_URL"
            )
            overall_ok = False
    else:
        results["10_pz_posting"] = _warn(
            "No #PZ posts since startup — send POST /api/v1/debug/post-pz-test to verify channel"
        )

    # ── Step 11: Output files ────────────────────────────────────────────────
    output_root = settings.storage_root / "outputs"
    if output_root.exists():
        batch_dirs = sorted(output_root.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
        recent = []
        for bd in batch_dirs[:5]:
            if bd.is_dir():
                files = [f.name for f in bd.iterdir() if f.is_file()]
                recent.append({"batch": bd.name, "files": files})
        results["11_output_files"] = _ok(
            f"{len(batch_dirs)} batch dirs in {output_root}; "
            f"most recent: {recent[0] if recent else 'none'}"
        )
    else:
        results["11_output_files"] = _warn(
            f"Output dir not found: {output_root} — will be created on first run"
        )

    # ── Step 12: Audit PDF font (Polish glyphs) ───────────────────────────────
    font_candidates = [
        "/Library/Fonts/Arial Unicode.ttf",
        "/Library/Fonts/Arial Unicode MS.ttf",
        "/Library/Fonts/Arial.ttf",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    found_font = next((p for p in font_candidates if Path(p).exists()), None)
    if found_font:
        results["12_audit_font"] = _ok(f"Unicode TTF found: {found_font}")
    else:
        results["12_audit_font"] = _fail(
            "No Unicode TTF font found — Polish characters will render as ■ in audit PDFs",
            "Install: brew install --cask font-dejavu OR copy Arial Unicode.ttf to /Library/Fonts/"
        )
        overall_ok = False

    # ── Summary ───────────────────────────────────────────────────────────────
    fail_count = sum(1 for v in results.values() if isinstance(v, dict) and v.get("status") == "fail")
    warn_count = sum(1 for v in results.values() if isinstance(v, dict) and v.get("status") == "warn")

    return {
        "overall": "ok" if overall_ok else "degraded",
        "fail_count": fail_count,
        "warn_count": warn_count,
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
            "bot_debounce_seconds":  settings.bot_debounce_seconds,
            "channel_webhook_set":   has_channel_webhook,
            "bot_token_set":         has_bot_token,
            "refresh_token_set":     has_refresh_token,
            "oauth_creds_set":       has_oauth_creds,
        },
    }


@router.post("/clear-test-sessions", dependencies=[_auth])
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


@router.post("/post-pz-test", dependencies=[_auth])
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
