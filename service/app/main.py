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
from .api.routes_admin_backup import router as admin_backup_router
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
from .api.routes_orchestrator import router as orchestrator_router
from .api.routes_dhl_followup import router as dhl_followup_router
from .api.routes_dhl_followup_status import router as dhl_followup_status_router
from .api.routes_dhl_documents import router as dhl_documents_router
from .api.routes_lifecycle import router as lifecycle_router
from .api.routes_intake import router as intake_router
from .api.routes_execute import router as execute_router
from .api.routes_ai_advisory import router as ai_advisory_router
from .api.routes_mdi import router as mdi_router
from .api.routes_search import router as search_router
from .api.routes_inbox import router as inbox_router
from .api.routes_intelligence_graph import router as intelligence_graph_router
from .api.routes_workflow_intelligence import router as workflow_intelligence_router  # Phase 9
from .api.routes_operations_intelligence import router as operations_intelligence_router  # Phase 10
from .api.routes_settings import router as settings_router
from .api.routes_system import router as system_router
from .api.routes_deploy_status import router as deploy_status_router
from .api.routes_agents import router as agents_router
from .api.routes_packing import router as packing_router, dev_router as packing_dev_router
from .api.routes_packing_resolution import router as packing_resolution_router
from .api.routes_contractor_projection import router as contractor_projection_router
from .api.routes_sales import router as sales_router
from .api.routes_proforma import router as proforma_router
from .api.routes_proforma_adopt import router as proforma_adopt_router
from .api.routes_warehouse import router as warehouse_router
from .api.routes_warehouse_audit import router as warehouse_audit_router
from .api.routes_warehouse_receipt import router as warehouse_receipt_router
from .api.routes_wfirma_capabilities import router as wfirma_capabilities_router
from .api.routes_wfirma_reservation import router as wfirma_reservation_router
from .api.routes_wfirma_contractors import router as wfirma_contractors_router
from .api.routes_reservations import router as reservations_router
from .api.routes_dhl_readiness import router as dhl_readiness_router
from .api.routes_batch_readiness import router as batch_readiness_router
from .api.routes_tracking_db import router as tracking_db_router
from .api.routes_correction_registry import router as correction_registry_router
from .api.routes_ledgers import router as ledgers_router
from .api.routes_carrier_webhook import router as carrier_webhook_router
from .api.routes_webhooks_wfirma import router as webhooks_wfirma_router
from .api.routes_webhooks_wfirma_status import router as webhooks_wfirma_status_router
from .api.routes_accounting import router as accounting_router
from .api.routes_wfirma_sync_pull import router as wfirma_sync_pull_router
from .api.routes_carrier_shadow import router as carrier_shadow_router
from .api.routes_carrier_actions import router as carrier_actions_router
from .api.routes_inventory import router as inventory_router
from .api.routes_inventory_writes import router as inventory_writes_router
from .api.routes_inventory_sample import router as inventory_sample_router
from .api.routes_inventory_returns import router as inventory_returns_router
from .api.routes_admin_runtime_flags import router as admin_runtime_flags_router
from .api.routes_admin_dhl_clearance import router as admin_dhl_clearance_router
from .api.routes_description_admin import router as description_admin_router
from .api.routes_customer_master import router as customer_master_router
from .api.routes_suppliers import router as suppliers_router
from .api.routes_client_addresses import router as client_addresses_router
from .api.routes_client_carrier_accounts import router as client_carrier_accounts_router
from .api.routes_master_data import (
    hs_router as md_hs_router,
    units_router as md_units_router,
    pl_router as md_pl_router,
    incoterms_router as md_incoterms_router,
    vat_router as md_vat_router,
    fx_router as md_fx_router,
    carriers_config_router as md_carriers_config_router,
    designs_router as md_designs_router,
    audit_router as md_audit_router,
)
from .api.routes_box_types import box_types_router  # Phase D: box_types CRUD (WF4.5)
from .api.routes_master_jewelry import (
    metals_router      as mj_metals_router,
    stones_router      as mj_stones_router,
    warehouses_router  as mj_warehouses_router,
)
from .api.routes_finance_postings import router as finance_postings_router
from .api.routes_supplier_invoice_ocr import router as supplier_invoice_ocr_router
from .core.config import settings
from .core.logging import configure_logging, get_logger
from .services.batch_manager import manager as batch_manager
from .services.export_service import run_engine_health_check
from .services.packing_db   import init_packing_db
from .services.warehouse_db import init_warehouse_db
from .services.warehouse_receipt_db import init_warehouse_receipt_db
from .services.document_db  import init_document_db
from .services.wfirma_db    import init_wfirma_db
from .services.correction_registry import init_correction_registry
from .services.intake_lineage     import init_intake_lineage
from .services.proforma_service_charges_db import init as init_proforma_service_charges
from .services.tracking_db  import init_tracking_db  # Phase 7.1: enables /search?q=<AWB>
from .services.supplier_invoice_db import init_db as init_supplier_invoice_db
# Governance constants — import at module level so assert_no_overlap() runs at startup.
# If any action appears in both SAFE_AUTONOMOUS and HUMAN_APPROVAL_REQUIRED sets, this
# raises AssertionError immediately, preventing the service from starting with a
# governance violation.
from .services.governance_constants import (  # noqa: F401
    SAFE_AUTONOMOUS_ACTIONS,
    HUMAN_APPROVAL_REQUIRED_ACTIONS,
    assert_no_overlap,
)
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


_PLACEHOLDER_SECRET = "change-me-in-production-use-a-random-32-byte-hex"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Production security assertions ─────────────────────────────────────
    if settings.environment == "prod":
        if not settings.api_key:
            raise RuntimeError(
                "STARTUP BLOCKED: API_KEY must be set in production. "
                "Generate with: python3 -c \"import secrets; print(secrets.token_hex(32))\""
            )
        if not settings.auth_secret_key or settings.auth_secret_key == _PLACEHOLDER_SECRET:
            raise RuntimeError(
                "STARTUP BLOCKED: AUTH_SECRET_KEY must be set to a random secret in production. "
                "Generate with: python3 -c \"import secrets; print(secrets.token_hex(32))\""
            )

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
    init_warehouse_receipt_db(_root / "warehouse_receipt.db")  # WAREHOUSE authority: qty confirmation
    init_document_db(_root  / "documents.db")
    init_wfirma_db(_root    / "wfirma.db")
    init_correction_registry(_root / "correction_registry.db")
    init_intake_lineage(_root / "intake_lineage.db")
    init_proforma_service_charges(_root / "proforma_links.db")
    init_tracking_db(_root  / "tracking_events.db")  # Phase 7.1: AWB search coverage
    init_supplier_invoice_db(_root / "supplier_invoice_ocr.sqlite")  # Supplier invoice OCR review drafts
    # Product Master canonical-identity registry (PR-1 Foundation).
    # Write-only at this stage — store_invoice_lines projects every
    # minted product_code into product_master. Consumers are NOT
    # switched in this PR; failure is non-fatal so service still
    # boots if reservation_queue.db is unavailable.
    try:
        from .services.reservation_db import init_reservation_db
        init_reservation_db(_root / "reservation_queue.db")
    except Exception as _rdb_init_exc:
        log.warning(
            "reservation_queue.db init failed at startup (non-fatal): %s",
            _rdb_init_exc,
        )
    log.info("Operational DBs ready under %s (packing / warehouse / documents / wfirma / tracking / reservation)", _root)

    # ── W-5 / P0: replay persisted DHL self-clearance runtime flags ──────
    # Restores operator-set flag values onto in-memory `settings` so that
    # NSSM service restarts do not silently revert kill switches. The
    # admin endpoint writes a JSON store at storage_root; we read it back
    # here. Safe to call when the store is absent (returns {}).
    try:
        from .api.routes_admin_runtime_flags import load_persisted_flags_into_settings
        restored = load_persisted_flags_into_settings()
        if restored:
            log.info(
                "DHL self-clearance runtime flags restored from store: %s",
                {k: v for k, v in restored.items()},
            )
    except Exception as exc:  # pragma: no cover — never block startup
        log.warning("runtime_flag_replay_failed reason=%s", exc)

    # ── W-5 P2 ignition (Model C, ADR-019) ─────────────────────────────────
    # Boot-replay completion signal — sweep's P2 ignition branch is a no-op
    # until this fires, preventing stale-flag dispatch during the lifespan
    # startup window (design doc §8 R-C10).
    try:
        from .services.active_shipment_monitor import mark_startup_replay_complete
        mark_startup_replay_complete()
    except Exception as exc:  # pragma: no cover — never block startup
        log.warning("p2_sweep_startup_marker_failed reason=%s", exc)

    # ── Governance flag audit at startup ────────────────────────────────────
    # wfirma_create_* flags are env-var-only — they do NOT persist to the
    # runtime flag store and silently revert on NSSM restart.  Emit their
    # live values so operators can detect an accidental revert (e.g. a .env
    # edit that was not applied, or a restart that cleared a prior setting).
    _dangerous_flags = {
        "wfirma_create_invoice_allowed":  getattr(settings, "wfirma_create_invoice_allowed", False),
        "wfirma_create_pz_allowed":       getattr(settings, "wfirma_create_pz_allowed", False),
        "wfirma_create_proforma_allowed": getattr(settings, "wfirma_create_proforma_allowed", False),
        "wfirma_create_product_allowed":  getattr(settings, "wfirma_create_product_allowed", True),
        "wfirma_edit_product_allowed":    getattr(settings, "wfirma_edit_product_allowed",   True),
        "wfirma_create_customer_allowed": getattr(settings, "wfirma_create_customer_allowed", False),
    }
    _true_flags = [k for k, v in _dangerous_flags.items() if v]
    if _true_flags:
        log.warning(
            "STARTUP_GOVERNANCE_AUDIT: the following wFirma write flags are TRUE "
            "(env-var-only, not persisted to runtime store — verify .env is intentional): %s",
            _true_flags,
        )
    else:
        log.info("STARTUP_GOVERNANCE_AUDIT: all wFirma write flags are FALSE (safe defaults).")

    # ── AI execution flag audit at startup ──────────────────────────────────
    # AI flags are env-var-only and default OFF.  Any TRUE value means a live
    # LLM call may be attempted at runtime.  Emit the live values so operators
    # can detect an accidental enable (e.g. a .env edit applied on a dev box
    # but not intended for this deployment, or an NSSM restart that re-read a
    # stale .env).
    _ai_flags = {
        "ai_parser_enabled":       getattr(settings, "ai_parser_enabled",       False),
        "ai_advisory_llm_enabled": getattr(settings, "ai_advisory_llm_enabled", False),
        "ai_cowork_enabled":       getattr(settings, "ai_cowork_enabled",        False),
        "ai_fallback_enabled":     getattr(settings, "ai_fallback_enabled",      False),
    }
    _ai_enabled = [k for k, v in _ai_flags.items() if v]
    if _ai_enabled:
        log.warning(
            "STARTUP_AI_AUDIT: the following AI execution flags are TRUE "
            "(env-var-only — verify .env is intentional): %s",
            _ai_enabled,
        )
    else:
        log.info("STARTUP_AI_AUDIT: all AI execution flags are OFF (safe defaults).")

    # ── Authority drift detection startup (R1 — Campaign 02.5 Phase 4) ─────
    # Generate startup authority manifest if flag is ON. Advisory only, never blocks startup.
    if settings.authority_drift_detection:
        try:
            from .services.authority_startup import generate_startup_authority_manifest
            authority_manifest_result = generate_startup_authority_manifest(_root)
            module_count = len(authority_manifest_result.get("modules", {}))
            error_count = len([m for m in authority_manifest_result.get("modules", {}).values() if "error" in m])
            log.info(
                "STARTUP_AUTHORITY_MANIFEST: generated manifest with %d modules (%d errors) written to %s",
                module_count, error_count, _root / "authority_manifest.json"
            )
        except Exception as _auth_manifest_exc:  # never block startup
            log.warning("STARTUP_AUTHORITY_MANIFEST: generation failed (non-fatal): %s", _auth_manifest_exc)
    else:
        log.info("STARTUP_AUTHORITY_AUDIT: authority_drift_detection=False, no manifest generated")

    log.info("Starting Estrella PZ Service  [env=%s]", settings.environment)
    log.info("Engine dir: %s", settings.engine_dir)

    await start_watcher()

    batch_manager.set_auto_submit_callback(on_auto_submit)
    batch_manager.set_expiry_callback(on_session_expiry)
    batch_manager.start_sweep()

    # ── DHL orchestrator (Phase 1) — gated by DHL_ORCH_ENABLED ─────────────
    # Default OFF.  Even when ON, the loop honours DHL_ORCH_SHADOW_MODE
    # (default True) and every AUTO_* sub-flag (all default False).
    try:
        from .services import dhl_orchestrator as _orch
        _orch.start_loop()
    except Exception as _orch_exc:  # never block startup
        log.warning("dhl_orchestrator startup failed (non-fatal): %s", _orch_exc)

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

    # ── Master Bootstrap: series catalog (disk-first, stale-refresh) ────────
    # 1. init_series_cache — set the disk persistence path.
    # 2. load_cache_from_disk — populate in-memory cache from last-saved file
    #    so series dropdowns work immediately even when wFirma is unreachable.
    # 3. If cache is absent or stale (>24 h), trigger a live wFirma refresh.
    # All steps are non-fatal: failures are warned, never block startup.
    # GOVERNANCE: series.refresh_from_wfirma → SAFE_AUTONOMOUS.
    try:
        from .services import wfirma_dictionary_cache as _wdc
        _wdc.init_series_cache(_root / "series_cache.json")
        _disk_hit = _wdc.load_cache_from_disk()
        if _disk_hit:
            log.info(
                "startup_series_bootstrap: loaded from disk cache; "
                "is_stale=%s cache_age_hours=%s",
                _wdc.is_cache_stale(),
                _wdc.get_dictionaries().get("cache_age_hours"),
            )
        if _wdc.is_cache_stale() and settings.series_bootstrap_enabled:
            _series_result = _wdc.refresh_from_wfirma()
        elif _wdc.is_cache_stale() and not settings.series_bootstrap_enabled:
            log.info(
                "startup_series_bootstrap: cache is stale but "
                "SERIES_BOOTSTRAP_ENABLED=false — skipping live wFirma fetch"
            )
            _series_result = None
        else:
            _series_result = None  # fresh cache path handled in else below
        if _series_result is not None:
            _src = _series_result.get("source_state", {})
            log.info(
                "startup_series_bootstrap: live refresh completed; "
                "invoice_series_source=%s proforma_series_source=%s "
                "invoice_count=%d proforma_count=%d",
                _src.get("invoice_series", "unknown"),
                _src.get("proforma_series", "unknown"),
                len(_series_result.get("invoice_series", [])),
                len(_series_result.get("proforma_series", [])),
            )
        elif not _wdc.is_cache_stale():
            log.info(
                "startup_series_bootstrap: disk cache is fresh, skipping live fetch"
            )
    except Exception as _series_exc:  # pragma: no cover — never block startup
        log.warning("startup_series_bootstrap_failed reason=%s", _series_exc)

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

    # ── wFirma webhook scheduler (Phase 2A.1) ─────────────────────────────────
    # Polls for RECEIVED events every 30s, fetches XML, stores immutable snapshots.
    # Non-fatal: missing apscheduler or DB error logs a warning and continues.
    try:
        from .services.wfirma_webhook_scheduler import start_wfirma_scheduler
        start_wfirma_scheduler(_root)
    except Exception as _wfirma_sched_exc:
        log.warning("wfirma_webhook_scheduler startup failed (non-fatal): %s", _wfirma_sched_exc)

    yield
    log.info("Estrella PZ Service shutting down.")

    # ── wFirma webhook scheduler clean shutdown ────────────────────────────────
    try:
        from .services.wfirma_webhook_scheduler import stop_wfirma_scheduler
        stop_wfirma_scheduler()
    except Exception as _wfirma_stop_exc:
        log.warning("wfirma_webhook_scheduler stop failed (non-fatal): %s", _wfirma_stop_exc)

    # ── DHL orchestrator clean shutdown ────────────────────────────────────
    try:
        from .services import dhl_orchestrator as _orch
        await _orch.stop_loop()
    except Exception as _orch_exc:
        log.warning("dhl_orchestrator stop_loop failed (non-fatal): %s", _orch_exc)


app = FastAPI(
    title       = "Estrella PZ Service",
    description = "Landed cost processing engine for Estrella shipments.",
    version     = "1.0.0",
    lifespan    = lifespan,
)

# Wildcard origins and allow_credentials=True are mutually exclusive per the CORS spec.
# Dev: wildcard origins, no credentials (browser will reject credentialed+wildcard anyway).
# Prod: explicit public URL only, credentials allowed.
_cors_origins = (
    ["*"]
    if settings.environment == "dev"
    else [settings.fastapi_public_url]
)
app.add_middleware(
    CORSMiddleware,
    allow_origins     = _cors_origins,
    allow_methods     = ["GET", "POST"],
    allow_headers     = ["*"],
    allow_credentials = settings.environment == "prod",
)

app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(admin_backup_router)
app.include_router(description_admin_router)
app.include_router(router)
app.include_router(dashboard_router)
# Alias mount: also expose the dashboard router under /api/v1/dashboard/*.
# The dashboard router already carries its own "/dashboard" prefix, so this
# include yields /api/v1/dashboard/* pointing at the SAME handlers with the
# SAME auth dependency (require_api_key — session-cookie aware). This is
# required because the V2 pages (shipment-v2.html) and V1 dashboard.html call
# /api/v1/dashboard/...; without this alias those calls 404 (root cause of the
# Sprint-03 #389 "Shipment not found" smoke failure). The original /dashboard/*
# paths are preserved, and the app-level /dashboard/{path:path} static
# catch-all is NOT in this router, so static serving is unaffected. Resolution
# is pinned by the route-contract test in test_shipment_v2_contract.py.
app.include_router(dashboard_router, prefix="/api/v1")
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
app.include_router(orchestrator_router)
app.include_router(dhl_followup_router)
app.include_router(dhl_followup_status_router)
app.include_router(dhl_documents_router)
app.include_router(lifecycle_router)
app.include_router(intake_router)
app.include_router(execute_router)
app.include_router(ai_advisory_router)
app.include_router(mdi_router)              # Phase 4: master-data intelligence (advisory, no writes)
app.include_router(search_router)           # Phase 7: natural-language search (deterministic, no writes)
app.include_router(inbox_router)            # Sprint 2B.1: global inbox aggregator (read-only; require_api_key)
app.include_router(intelligence_graph_router)     # Phase 8: intelligence graph (batch_id-centered, read-only)
app.include_router(workflow_intelligence_router)      # Phase 9: workflow intelligence (multi-signal, read-only)
app.include_router(operations_intelligence_router)    # Phase 10: operations intelligence (cross-batch, read-only)
app.include_router(system_router)
app.include_router(deploy_status_router)
app.include_router(agents_router)
app.include_router(packing_router)
app.include_router(packing_dev_router)
app.include_router(packing_resolution_router)
app.include_router(contractor_projection_router)  # PR-2: contractor-at-birth backfill + blocks
app.include_router(sales_router)
app.include_router(proforma_router)
app.include_router(proforma_adopt_router)
app.include_router(warehouse_router)
app.include_router(warehouse_audit_router)
app.include_router(warehouse_receipt_router)  # WAREHOUSE authority: receipt qty confirmation
# reservations_router (prefix /api/v1) MUST be registered BEFORE
# wfirma_capabilities_router: the latter owns the catch-all
# PUT /api/v1/wfirma/products/{product_code:path}, which otherwise shadows this
# router's POST /api/v1/wfirma/products/sync-by-codes and yields 405. Registering
# the concrete POST route first makes the match unambiguous (C-1b.1 regression).
app.include_router(reservations_router)
app.include_router(wfirma_capabilities_router)
app.include_router(wfirma_reservation_router)
app.include_router(wfirma_contractors_router)   # Phase 3B: contractor scan API + status
app.include_router(dhl_readiness_router)
app.include_router(batch_readiness_router)
app.include_router(tracking_db_router)  # /events/* before tracking_router's /{tracking_no}
app.include_router(correction_registry_router)
app.include_router(ledgers_router)
app.include_router(carrier_webhook_router)
app.include_router(webhooks_wfirma_router)
app.include_router(webhooks_wfirma_status_router)
app.include_router(accounting_router)
app.include_router(wfirma_sync_pull_router)
app.include_router(carrier_shadow_router)   # static paths (shadow/log, status) before dynamic
app.include_router(carrier_actions_router)  # dynamic paths ({batch_id}/shipment)
app.include_router(inventory_router)        # GET /api/v1/inventory/stage2/aggregate (read-only)
app.include_router(inventory_writes_router) # POST /api/v1/inventory/pieces/{id}/location (Move stock; precheck-guarded)
app.include_router(inventory_sample_router) # POST /api/v1/inventory/pieces/{id}/sample-out + /sample-return (Phase B.1; precheck-guarded)
app.include_router(inventory_returns_router)# POST /api/v1/inventory/pieces/{id}/return-from-client + /return-to-producer + /return-from-producer (Phase B.2; precheck-guarded)
app.include_router(admin_runtime_flags_router)  # W-5 / P0: DHL self-clearance runtime flag admin (X-API-Key)
app.include_router(admin_dhl_clearance_router)  # W-5 / P2 ignition (Model C): admin override route for proactive dispatch (X-API-Key, ADR-019)
app.include_router(customer_master_router)      # PR 2C.3a: customer master CRUD (X-API-Key)
app.include_router(client_addresses_router)         # MasterData-1: per-client shipping addresses
app.include_router(client_carrier_accounts_router)  # MasterData-1: per-client carrier accounts
app.include_router(suppliers_router)                # MasterData-B4: suppliers registry (local CRUD; X-API-Key)
app.include_router(md_hs_router)                    # MasterData-B5: HS codes (local CRUD; X-API-Key)
app.include_router(md_units_router)                 # MasterData-B5: Units (local CRUD; X-API-Key)
app.include_router(md_pl_router)                    # MasterData-B5: Product local augmentation (local CRUD; X-API-Key)
app.include_router(md_incoterms_router)             # MasterData-B7: Incoterms registry (local CRUD; X-API-Key)
app.include_router(md_vat_router)                   # MasterData-B7: VAT config (local; READ-ONLY w.r.t. wFirma invoicing)
app.include_router(md_fx_router)                    # MasterData-B8: FX rates (REFERENCE-ONLY; NOT a PZ override path)
app.include_router(md_carriers_config_router)       # MasterData-B9: Carrier config (LOCAL, NON-SECRET; runtime untouched)
app.include_router(md_designs_router)                # B-MD2 (MDOC): Designs master (LOCAL, additive; product_identity_engine read-only consumer)
app.include_router(md_audit_router)                  # Phase 1: unified master-data audit (read-only query surface)
app.include_router(mj_metals_router)                 # Phase 3: metals master (LOCAL valuation reference)
app.include_router(mj_stones_router)                 # Phase 3: stones master (LOCAL catalog, cert reference only)
app.include_router(mj_warehouses_router)             # Phase 3: warehouses master (LOCAL stock-location authority)
app.include_router(box_types_router)                 # Phase D: box_types master (WF4.5 / Path-DOC outbound label packaging)
app.include_router(finance_postings_router)         # Phase 6F.3: read-only breakdown endpoint (no writes, no posting/settlement/FX/wFirma coupling; init_db lazy-on-call)
app.include_router(settings_router)                # Phase 7: company profile (seller identity + bank details)
app.include_router(supplier_invoice_ocr_router)    # Supplier invoice OCR: extraction drafts + operator review (no wFirma write)


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

    file_path = (_chrome_autofill_dir / path).resolve()
    try:
        file_path.relative_to(_chrome_autofill_dir.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid path")
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail=f"chrome_wfirma_autofill/{path} not found")

    content = file_path.read_bytes()
    mime    = "text/markdown; charset=utf-8" if file_path.suffix == ".md" else (
              _mimetypes.guess_type(str(file_path))[0] or "application/octet-stream")
    return Response(content=content, media_type=mime,
                    headers={"Cache-Control": "public, max-age=3600"})


# ── Atlas-V2 design shell — /v2/* (Sprint 1, same auth gate as /dashboard/) ──

_v2_static_dir = _static_dir / "v2"

@app.get("/v2", include_in_schema=False)
def serve_v2_index_redirect() -> Response:
    return RedirectResponse(url="/v2/index.html", status_code=302)

@app.get("/v2/{path:path}", include_in_schema=False)
def serve_v2_static(path: str, request: Request) -> Response:
    """Serve Atlas-V2 design shell — identical session gate to /dashboard/.

    /v2/ is NOT an open surface: unauth in prod → /login redirect (same as /dashboard/).
    Source files live in service/app/static/v2/ (Sprint 1 shell + 23 jsx).
    """
    if settings.environment != "dev":
        import hmac as _hmac  # noqa: PLC0415
        raw_key = request.headers.get("X-API-Key") or request.headers.get("x-api-key")
        api_key_ok = (bool(raw_key) and bool(settings.api_key)
                      and _hmac.compare_digest(raw_key.encode("utf-8"), settings.api_key.encode("utf-8")))
        if not api_key_ok:
            user = check_session_or_redirect(request)
            if not user:
                return RedirectResponse(url="/login", status_code=302)

    file_path = _v2_static_dir / (path or "index.html")
    if not file_path.exists() or not file_path.is_file():
        # Asset paths (have a file extension: .js, .jsx, .css, .html, …) must 404
        # so that <script onerror="..."> fallback handlers fire correctly.
        # Extension-free paths are SPA routes → serve index.html.
        import pathlib as _pathlib  # noqa: PLC0415
        if _pathlib.PurePosixPath(path).suffix:
            return Response(status_code=404)
        file_path = _v2_static_dir / "index.html"

    content = file_path.read_bytes()
    mime, _ = _mimetypes.guess_type(str(file_path))
    # Python mimetypes has no entry for .jsx; browsers with strict MIME checking
    # refuse to execute application/octet-stream scripts → blank screen.
    if file_path.suffix == ".jsx":
        mime = "text/javascript"
    mime    = mime or "application/octet-stream"
    headers = (
        {"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache"}
        if file_path.suffix in (".html", ".js", ".jsx", ".css")
        else {"Cache-Control": "public, max-age=3600"}
    )
    return Response(content=content, media_type=mime, headers=headers)


# ── Protected static dashboard files ─────────────────────────────────────────

@app.get("/dashboard/{path:path}", include_in_schema=False)
def serve_static(path: str, request: Request) -> Response:
    """Serve dashboard static files — requires valid session cookie (prod) or no auth (dev).

    Fix #387 (corrected): gate dev bypass on settings.environment, NOT on api_key.
    - settings.environment == 'dev'  -> no auth required (local dev only).
    - settings.environment == 'prod' -> session cookie required; X-API-Key accepted as
      an ADDITIONAL auth method if api_key is configured (currently it is not, so
      prod falls through to session check — identical to original prod behaviour).

    Root cause of prior breakage: `if settings.api_key:` was used as the gate, but
    api_key is empty in BOTH dev and prod (.env has no API_KEY), so the gate was
    always False and auth was bypassed in production. The correct discriminant is
    settings.environment (Literal['dev','prod']), which is 'dev' locally and 'prod'
    in C:\\PZ\\.env via ENVIRONMENT=prod.
    """
    if settings.environment != "dev":
        # Production (or any non-dev env): require session OR valid API key
        import hmac as _hmac  # noqa: PLC0415
        raw_key = request.headers.get("X-API-Key") or request.headers.get("x-api-key")
        api_key_ok = (bool(raw_key) and bool(settings.api_key)
                      and _hmac.compare_digest(raw_key.encode("utf-8"), settings.api_key.encode("utf-8")))
        if not api_key_ok:
            user = check_session_or_redirect(request)
            if not user:
                return RedirectResponse(url="/login", status_code=302)
    # else: dev mode (environment == 'dev') — no auth required for local browser verify

    file_path = _static_dir / path
    if not file_path.exists() or not file_path.is_file():
        file_path = _static_dir / "dashboard.html"

    content  = file_path.read_bytes()
    mime, _  = _mimetypes.guess_type(str(file_path))
    mime     = mime or "application/octet-stream"
    headers  = (
        {"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache"}
        if file_path.suffix in (".html", ".js")
        else {"Cache-Control": "public, max-age=3600"}
    )
    return Response(content=content, media_type=mime, headers=headers)
