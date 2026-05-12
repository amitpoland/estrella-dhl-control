from __future__ import annotations

import pathlib as _pathlib
import mimetypes as _mimetypes
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, Response

from .api.routes_pz import router
from .api.routes_dashboard import router as dashboard_router
from .api.routes_bot import router as bot_router, start_watcher
from .api.routes_batch import router as batch_router, on_auto_submit, on_session_expiry
from .api.routes_debug import router as debug_router
from .api.routes_upload import router as upload_router
from .api.routes_auth import router as auth_router
from .api.routes_admin import router as admin_router
from .api.routes_tracking import router as tracking_router
from .api.routes_learning import router as learning_router
from .api.routes_proposals import router as proposals_router
from .api.routes_dsk import router as dsk_router
from .api.routes_dhl_clearance import router as dhl_clearance_router
from .api.routes_agency import router as agency_router
from .api.routes_wfirma import router as wfirma_router
from .api.routes_analytics import router as analytics_router
from .api.routes_intelligence import router as intelligence_router
from .api.routes_action_proposals import router as action_proposals_router
from .api.routes_ai_bridge import router as ai_bridge_router
from .api.routes_monitor import router as monitor_router
from .api.routes_dhl_followup import router as dhl_followup_router
from .api.routes_dhl_documents import router as dhl_documents_router
from .api.routes_lifecycle import router as lifecycle_router
from .api.routes_intake import router as intake_router
from .api.routes_execute import router as execute_router
from .api.routes_system import router as system_router
from .api.routes_agents import router as agents_router
from .api.routes_packing import router as packing_router, dev_router as packing_dev_router
from .api.routes_sales import router as sales_router
from .api.routes_proforma import router as proforma_router
from .api.routes_proforma_adopt import router as proforma_adopt_router
from .api.routes_warehouse import router as warehouse_router
from .api.routes_warehouse_audit import router as warehouse_audit_router
from .api.routes_wfirma_capabilities import router as wfirma_capabilities_router
from .api.routes_wfirma_reservation import router as wfirma_reservation_router
from .api.routes_dhl_readiness import router as dhl_readiness_router
from .api.routes_batch_readiness import router as batch_readiness_router
from .api.routes_tracking_db import router as tracking_db_router
from .api.routes_correction_registry import router as correction_registry_router
from .api.routes_ledgers import router as ledgers_router
from .api.routes_carrier_webhook import router as carrier_webhook_router
from .api.routes_carrier_shadow import router as carrier_shadow_router
from .api.routes_carrier_actions import router as carrier_actions_router
from .api.routes_inventory import router as inventory_router
from .api.routes_inventory_writes import router as inventory_writes_router
from .api.routes_inventory_sample import router as inventory_sample_router
from .core.config import settings
from .core.logging import configure_logging, get_logger
from .services.batch_manager import manager as batch_manager
from .services.export_service import run_engine_health_check
from .services.packing_db   import init_packing_db
from .services.warehouse_db import init_warehouse_db
from .services.document_db  import init_document_db
from .services.wfirma_db    import init_wfirma_db
from .services.correction_registry import init_correction_registry
from .services.intake_lineage     import init_intake_lineage
from .services.proforma_service_charges_db import init as init_proforma_service_charges
from .auth.database import init_db
from .auth.dependencies import check_session_or_redirect

configure_logging()
log = get_logger(__name__)

# ── Auth DB path ──────────────────────────────────────────────────────────────
import pathlib as _pl
_auth_db = (
    _pl.Path(settings.auth_db_path)
    if settings.auth_db_path
    else settings.storage_root / "users.db"
)

# ── Pages that require no auth ────────────────────────────────────────────────
_PUBLIC_PATHS = {"/login", "/signup", "/forgot-password"}
# API prefixes that remain API-key authenticated (bot / webhook integrations)
_BOT_PREFIX = "/api/v1/cliq"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialise auth DB
    init_db(_auth_db)
    log.info("Auth DB ready: %s", _auth_db)

    # Initialise operational DBs (packing / warehouse / document / wfirma).
    # These back the packing-list, warehouse-scan, document-store, and wFirma
    # mapping routes. Failures here are fatal — the routes silently no-op if
    # any of these are skipped (wfirma_db.upsert_* returns "" when _db_path
    # is None, masking writes).
    _root = settings.storage_root
    _root.mkdir(parents=True, exist_ok=True)
    init_packing_db(_root   / "packing.db")
    init_warehouse_db(_root / "warehouse.db")
    init_document_db(_root  / "documents.db")
    init_wfirma_db(_root    / "wfirma.db")
    init_correction_registry(_root / "correction_registry.db")
    init_intake_lineage(_root / "intake_lineage.db")
    init_proforma_service_charges(_root / "proforma_links.db")
    log.info("Operational DBs ready under %s (packing / warehouse / documents / wfirma)", _root)

    log.info("Starting Estrella PZ Service  [env=%s]", settings.environment)
    log.info("Engine dir: %s", settings.engine_dir)

    await start_watcher()

    batch_manager.set_auto_submit_callback(on_auto_submit)
    batch_manager.set_expiry_callback(on_session_expiry)
    batch_manager.start_sweep()
    log.info(
        "Batch session manager started "
        "(session_timeout=%dmin, auto_submit=%dmin, auto_submit_if_ready=%s)",
        settings.batch_session_timeout_minutes,
        settings.batch_auto_submit_minutes,
        settings.batch_auto_submit_if_ready,
    )

    removed = batch_manager.clear_test_sessions()
    if removed:
        log.warning("Startup: removed %d test session(s): %s", len(removed), removed)

    if settings.run_verify_on_startup:
        log.info("Running engine health check (RUN_VERIFY_ON_STARTUP=true)…")
        ok, detail = run_engine_health_check()
        if ok:
            log.info("Engine health check passed.")
        else:
            log.error("Engine health check FAILED:\n%s", detail)

    # ── Dashboard Action V2 — route contract validator (warning-only) ──────
    try:
        from .services.dashboard_action_types import NormalizedState
        from .services.dashboard_action_registry import all_action_endpoints
        from .services.route_contract_validator import validate_endpoints
        sample = NormalizedState(
            batch_id="__startup_sample__",
            polish_desc_filename="sample.pdf",
            dsk_filename="sample_dsk.pdf",
            agency_queue_id="q-sample",
            dhl_reply_queue_id="q-sample-dhl",
            pz_pdf_filename="sample_pz.pdf",
            pz_xlsx_filename="sample_pz.xlsx",
        )
        broken = validate_endpoints(app, all_action_endpoints(sample))
        if broken:
            for b in broken:
                log.warning("ActionRegistry broken route: %s %s (%s) — action=%s",
                            b.method, b.endpoint, b.reason, b.action_id)
        else:
            log.info("ActionRegistry: %d endpoints validated, no broken routes.",
                     len(all_action_endpoints(sample)))
    except Exception as _arv_exc:
        log.warning("ActionRegistry startup validation skipped: %s", _arv_exc)

    yield
    log.info("Estrella PZ Service shutting down.")


app = FastAPI(
    title       = "Estrella PZ Service",
    description = "Landed cost processing engine for Estrella shipments.",
    version     = "1.0.0",
    lifespan    = lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins     = ["*"] if settings.environment == "dev" else [],
    allow_methods     = ["GET", "POST"],
    allow_headers     = ["*"],
    allow_credentials = True,
)

app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(router)
app.include_router(dashboard_router)
app.include_router(bot_router)
app.include_router(batch_router)
app.include_router(debug_router)
app.include_router(upload_router)
app.include_router(tracking_router)
app.include_router(learning_router)
app.include_router(proposals_router)
app.include_router(dsk_router)
app.include_router(dhl_clearance_router)
app.include_router(agency_router)
app.include_router(wfirma_router)
app.include_router(analytics_router)
app.include_router(intelligence_router)
app.include_router(action_proposals_router)
app.include_router(ai_bridge_router)
app.include_router(monitor_router)
app.include_router(dhl_followup_router)
app.include_router(dhl_documents_router)
app.include_router(lifecycle_router)
app.include_router(intake_router)
app.include_router(execute_router)
app.include_router(system_router)
app.include_router(agents_router)
app.include_router(packing_router)
app.include_router(packing_dev_router)
app.include_router(sales_router)
app.include_router(proforma_router)
app.include_router(proforma_adopt_router)
app.include_router(warehouse_router)
app.include_router(warehouse_audit_router)
app.include_router(wfirma_capabilities_router)
app.include_router(wfirma_reservation_router)
app.include_router(dhl_readiness_router)
app.include_router(batch_readiness_router)
app.include_router(tracking_db_router)  # /events/* before tracking_router's /{tracking_no}
app.include_router(correction_registry_router)
app.include_router(ledgers_router)
app.include_router(carrier_webhook_router)
app.include_router(carrier_shadow_router)   # static paths (shadow/log, status) before dynamic
app.include_router(carrier_actions_router)  # dynamic paths ({batch_id}/shipment)
app.include_router(inventory_router)        # GET /api/v1/inventory/stage2/aggregate (read-only)
app.include_router(inventory_writes_router) # POST /api/v1/inventory/pieces/{id}/location (Move stock; precheck-guarded)
app.include_router(inventory_sample_router) # POST /api/v1/inventory/pieces/{id}/sample-out + /sample-return (Phase B.1; precheck-guarded)


# ── Auth-aware static file serving ───────────────────────────────────────────
_static_dir = _pathlib.Path(__file__).parent / "static"


@app.get("/", include_in_schema=False)
def root_redirect() -> RedirectResponse:
    return RedirectResponse(url="/dashboard")


@app.get("/dashboard", include_in_schema=False)
def dashboard_root(request: Request) -> Response:
    user = check_session_or_redirect(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    return RedirectResponse(url="/dashboard/dashboard.html")


# ── Auth HTML page routes ─────────────────────────────────────────────────────

@app.get("/login", include_in_schema=False)
def login_page(request: Request) -> Response:
    # Already logged in → go to dashboard
    user = check_session_or_redirect(request)
    if user:
        return RedirectResponse(url="/dashboard")
    file_path = _static_dir / "login.html"
    content   = file_path.read_bytes()
    return Response(
        content=content, media_type="text/html",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@app.get("/signup", include_in_schema=False)
def signup_page(request: Request) -> Response:
    user = check_session_or_redirect(request)
    if user:
        return RedirectResponse(url="/dashboard")
    file_path = _static_dir / "signup.html"
    content   = file_path.read_bytes()
    return Response(
        content=content, media_type="text/html",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@app.get("/admin", include_in_schema=False)
def admin_redirect(request: Request) -> Response:
    return RedirectResponse(url="/admin/users", status_code=302)


@app.get("/admin/users", include_in_schema=False)
def admin_users_page(request: Request) -> Response:
    """Admin user management panel — requires admin role."""
    user = check_session_or_redirect(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    if user.get("role") != "admin":
        return RedirectResponse(url="/dashboard", status_code=302)
    file_path = _static_dir / "admin-users.html"
    content   = file_path.read_bytes()
    return Response(
        content=content, media_type="text/html",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@app.get("/forgot-password", include_in_schema=False)
def forgot_password_page() -> Response:
    file_path = _static_dir / "forgot-password.html"
    content   = file_path.read_bytes()
    return Response(
        content=content, media_type="text/html",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


# ── Chrome AutoFill helper files ─────────────────────────────────────────────
_chrome_autofill_dir = _pathlib.Path(settings.engine_dir) / "chrome_wfirma_autofill"


@app.get("/chrome_wfirma_autofill/{path:path}", include_in_schema=False)
def serve_chrome_autofill(path: str, request: Request) -> Response:
    """Serve the Chrome AutoFill README and script. Requires valid session cookie."""
    user = check_session_or_redirect(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    file_path = _chrome_autofill_dir / path
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail=f"chrome_wfirma_autofill/{path} not found")

    content = file_path.read_bytes()
    mime    = "text/markdown; charset=utf-8" if file_path.suffix == ".md" else (
              _mimetypes.guess_type(str(file_path))[0] or "application/octet-stream")
    return Response(content=content, media_type=mime,
                    headers={"Cache-Control": "public, max-age=3600"})


# ── Protected static dashboard files ─────────────────────────────────────────

@app.get("/dashboard/{path:path}", include_in_schema=False)
def serve_static(path: str, request: Request) -> Response:
    """Serve dashboard static files — requires valid session cookie."""
    user = check_session_or_redirect(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    file_path = _static_dir / path
    if not file_path.exists() or not file_path.is_file():
        file_path = _static_dir / "dashboard.html"

    content  = file_path.read_bytes()
    mime, _  = _mimetypes.guess_type(str(file_path))
    mime     = mime or "application/octet-stream"
    headers  = (
        {"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache"}
        if file_path.suffix == ".html"
        else {"Cache-Control": "public, max-age=3600"}
    )
    return Response(content=content, media_type=mime, headers=headers)
