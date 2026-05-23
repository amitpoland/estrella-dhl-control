from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ── API auth ──────────────────────────────────────────────────────────────
    api_key: str = ""                       # empty = auth disabled (dev only)
    environment: Literal["dev", "prod"] = "dev"

    # ── Session / JWT auth ────────────────────────────────────────────────────
    # Generate with: python3 -c "import secrets; print(secrets.token_hex(32))"
    auth_secret_key: str = "change-me-in-production-use-a-random-32-byte-hex"
    auth_db_path: str = ""   # defaults to storage_root/users.db if empty

    # ── Storage ───────────────────────────────────────────────────────────────
    storage_root: Path = Path(__file__).parent.parent / "storage"
    output_retention_days: int = 30
    max_upload_bytes: int = 20 * 1024 * 1024    # 20 MB per file

    # ── Engine ────────────────────────────────────────────────────────────────
    engine_dir: Path = Path(__file__).parent.parent.parent.parent.resolve()  # …/CLI/
    run_verify_on_startup: bool = False
    strict_match: bool = False          # global gate: block on any False verification
    # ── Bootstrap flags ───────────────────────────────────────────────────────
    # series_bootstrap_enabled: env SERIES_BOOTSTRAP_ENABLED=false disables the
    # startup live series refresh from wFirma. Useful when wFirma credentials
    # are not available in a given environment (e.g. CI, staging sandbox).
    # Default True (live refresh on stale cache) — set False to skip live fetch.
    series_bootstrap_enabled: bool = True

    # ── Audit hardening (feature-flagged) ─────────────────────────────────────
    # When True (env: AUDIT_HARDENING_ENABLED=1), audit_scoring.score_batch
    # emits the categorical `status` taxonomy (VERIFIED / PARTIAL /
    # NOT_VERIFIED / BLOCKED) on top of the legacy numeric score and
    # risk_level, and applies hard-link force-zero for confirmed CIF /
    # invoice-ref mismatches. Defaults to False so production batches run
    # on the legacy scoring path until ops sign-off.
    #
    # Note: audit_scoring.py reads the env var directly (it has no service
    # dependency) — this Settings field mirrors the same env var so the
    # canonical configuration lives in one place.
    audit_hardening_enabled: bool = False

    # ── Zoho WorkDrive TrueSync (optional mirror — not used for PZ upload) ───────
    # Kept for reference / convenience mirror only. Never used as upload or
    # success condition for PZ output.
    workdrive_sync_root: str = ""

    # ── Zoho WorkDrive direct upload (REST API — primary cloud path) ──────────
    # Set these via .env. Obtain via Zoho Self Client (api-console.zoho.in).
    # Scope: WorkDrive.files.CREATE,WorkDrive.files.READ,WorkDrive.files.ALL
    workdrive_client_id:      str = Field(default="")
    workdrive_client_secret:  str = Field(default="")
    workdrive_refresh_token:  str = Field(default="")
    # myfolder_id of the WorkDrive user (MYSPACE_LIBRARY root). Pre-discovered:
    workdrive_myfolder_id:    str = Field(default="")
    # Optional: override upload root to a specific subfolder inside MYSPACE_LIBRARY
    workdrive_parent_id:      str = Field(default="")
    workdrive_token_url:      str = Field(
        default="https://accounts.zoho.in/oauth/v2/token"
    )
    workdrive_api_url:        str = Field(
        default="https://workdrive.zoho.in"
    )

    # ── Delivery ──────────────────────────────────────────────────────────────
    fastapi_public_url: str = "http://localhost:8000"  # external URL for file links
    resend_cooldown_seconds: int = 30       # idempotency window between resends
    bot_debounce_seconds:    int = 10       # wait for all files before processing

    # ── Zoho Cliq ─────────────────────────────────────────────────────────────
    cliq_webhook_url: str = ""              # bot chat incoming webhook (slash-cmd ack only)
    cliq_channel_webhook_url: str = ""      # #PZ channel webhook (zapikey fallback)
    cliq_mode: Literal["webhook", "oauth"] = "webhook"
    # OAuth fields
    cliq_base_url: str = "https://cliq.zoho.in/api/v2"
    cliq_bot_token: str = ""
    cliq_refresh_token: str = ""
    cliq_client_id: str = ""
    cliq_client_secret: str = ""
    cliq_default_target_type: Literal["bot", "chat", "user"] = "bot"
    cliq_default_target_id: str = ""
    # ── #PZ channel target (production results) ───────────────────────────────
    cliq_channel_name:    str = "pz"
    cliq_channel_id:      str = "O190928000006027001"
    cliq_channel_chat_id: str = "CT_1207130307962030566_60014108075"
    cliq_channel_api_url: str = "https://cliq.zoho.in/company/60014108075/api/v2/channelsbyname/pz/message"

    # ── AI customs parser (fallback only — XML is source of truth) ──────────
    anthropic_api_key:   Optional[str] = Field(default=None)
    ai_parser_model:     str           = Field(default="claude-sonnet-4-6")
    ai_parser_enabled:   bool          = Field(default=False)

    # ── AI advisory budget controls (all disabled by default — see api-fallback-policy.md) ──
    # Phase 2 LLM advisory — must be explicitly enabled via .env; never True in code defaults.
    ai_advisory_llm_enabled:        bool          = Field(default=False)
    ai_fallback_enabled:            bool          = Field(default=False)
    ai_advisory_max_tokens_per_call: int          = Field(default=1000)
    ai_advisory_budget_usd_per_day: float         = Field(default=1.0)
    ai_advisory_cache_ttl_seconds:  int           = Field(default=300)
    # Advisory model — haiku is mandatory for cost control; opus requires operator approval.
    ai_advisory_model:              str           = Field(default="claude-haiku-4-5-20251001")

    # ── Carrier tracking API credentials ─────────────────────────────────────
    dhl_api_key:         Optional[str] = Field(default=None)
    fedex_client_id:     Optional[str] = Field(default=None)
    fedex_client_secret: Optional[str] = Field(default=None)

    # ── DHL Shipment Tracking Unified API (OAuth2 client-credentials) ─────────
    # Status gate — controls whether live API calls are allowed.
    # Values: "pending" (default) | "active"
    #
    # When "pending":  tracking service returns fallback immediately.
    #                  No HTTP request is made to DHL under any circumstance.
    # When "active":   unified OAuth2 call is attempted; legacy key is fallback.
    #
    # TODO: When DHL approves the API app:
    #   1. Set DHL_TRACKING_API_STATUS=active in .env
    #   2. Set DHL_TRACKING_API_KEY and DHL_TRACKING_API_SECRET
    #   3. Restart service — no code changes required
    dhl_tracking_api_key:    Optional[str] = Field(default=None)
    dhl_tracking_api_secret: Optional[str] = Field(default=None)
    dhl_tracking_api_status: str           = Field(default="pending")

    # ── DHL customs email routing (P2 Slice A — proactive dispatch) ───────────
    # Authoritative recipient + CC for proactive customs dispatch emails.
    # Resolved at queue time, never read from operator-supplied request body.
    # Empty string means "not configured":
    #   - dev/local/test → falls back to dev-null@localhost (test sink)
    #   - any other environment → queue aborts with 500 (fail loud)
    dhl_customs_email: str = Field(default="")
    dhl_customs_cc:    str = Field(default="")

    # ── Phase 2.3 — Path A auto-queue at Departed origin ──────────────────────
    # Default-False feature flag. When True, the active_shipment_monitor sweep
    # auto-creates + auto-approves + auto-queues the proactive customs dispatch
    # email (A2a) on the first Departed-origin tracking event for any Path A
    # (dhl_self_clearance) shipment that passes the eleven-check validation
    # gate. Spec ref: docs/dhl_clearance_paths.md hard rules 9, 11, 12 and the
    # Tracking-driven triggers section. SECURITY review required all twelve
    # hard guarantees from the pre-implementation security pass be encoded.
    enable_path_a_auto_queue: bool = Field(default=False)

    # ── W-5 / P2 ignition (Model C) ── gate-flip for legacy _ensure_path_a_auto_queue
    # Default False: new coordinator-based P2 ignition (sweep → dispatch_proactive)
    # is the primary path. Legacy _ensure_path_a_auto_queue stays in code but is
    # NOT invoked unless this flag is explicitly flipped True (rollback escape valve
    # only — never both paths simultaneously).
    # See ADR-019 §"Gate-flip migration" and design doc
    # docs/operational-memory/dhl-selfclearance/02b_P2_IGNITION_SWITCH_DESIGN.md §P0-PREC1.
    dhl_selfclearance_legacy_path_a_queue_enabled: bool = Field(
        default=False,
    )

    # ── Zoho Mail (OAuth2 with refresh-token rotation) ────────────────────────
    # All values come from .env — never hardcode.
    # Required for /api/v1/dhl/scan-inbox to perform a backend mailbox search.
    # When refresh_token + client_id + client_secret are set, access_token is
    # auto-refreshed when expired; the static ZOHO_MAIL_API_TOKEN is optional
    # bootstrap-only and never written back.
    zoho_mail_api_token:     Optional[str] = Field(default=None)
    zoho_mail_refresh_token: Optional[str] = Field(default=None)
    zoho_client_id:          Optional[str] = Field(default=None)
    zoho_client_secret:      Optional[str] = Field(default=None)
    zoho_accounts_base:      str           = Field(default="https://accounts.zoho.eu")
    # NOTE: The Estrella mailbox (account 2261204000000002002) is hosted on Zoho's
    # India data centre. The .eu and .com API bases reject its tokens with
    # 401 INVALID_OAUTHTOKEN. zmail.zoho.in is empirically verified as correct.
    # Override via ZOHO_MAIL_API_BASE env var if the mailbox region ever changes.
    zoho_mail_api_base:      str           = Field(default="https://zmail.zoho.in/api")
    zoho_mail_account_id:    Optional[str] = Field(default=None)

    # ── Email scan routing ────────────────────────────────────────────────────
    # "auto"        → use Zoho REST API when creds present, else AI Bridge
    # "bridge_only" → always route to AI Bridge regardless of credentials
    # "api_only"    → always use Zoho REST; never fall back to bridge
    email_scan_mode: str = Field(default="auto")

    # Email Evidence V2 — default ON. Set EMAIL_EVIDENCE_V2=0 to disable (rollback).
    # When ON, ingestion writes to the local evidence store, uses since-cursor for
    # Zoho REST searches, and routes via the processor pipeline.
    email_evidence_v2: bool = Field(default=True)

    # ── SMTP send (Zoho App Password) ─────────────────────────────────────────
    # Required for actual outgoing email delivery via /api/v1/email-queue/{id}/send.
    # Without these, the send endpoint returns "smtp_not_configured" and the
    # queue entry stays at status=pending. Generate a Zoho App Password at
    #   https://accounts.zoho.in/home#security/app_passwords
    # Default to smtppro.zoho.in (paid Zoho Workplace). Free accounts use
    # smtp.zoho.in — override via SMTP_HOST in .env if needed.
    smtp_host:     str = Field(default="smtppro.zoho.in")
    smtp_port:     int = Field(default=465)
    smtp_user:     Optional[str] = Field(default=None)
    smtp_password: Optional[str] = Field(default=None)
    smtp_use_ssl:  bool = Field(default=True)
    # Read-receipt headers (Disposition-Notification-To / Return-Receipt-To /
    # X-Confirm-Reading-To). When enabled, every outgoing email asks the
    # recipient's MUA to send a read confirmation back to email_read_receipt_to
    # (defaults to the sender identity if blank).
    email_read_receipt_enabled: bool = Field(default=False)
    email_read_receipt_to:      str  = Field(default="")
    # MCP send fallback — total attachment-size cap (bytes). Above this,
    # MCP send refuses (PDFs too heavy via tool-call args). Default 200KB.
    mcp_send_max_attachment_bytes: int = Field(default=200_000)

    # ── wFirma API (3-header key auth — Basic Auth deprecated 2023-07-02) ───────
    # Source: wFirma → Ustawienia → Bezpieczeństwo → Aplikacje → Klucze API
    # All fields default to "" so the app starts safely without wFirma configured.
    # wfirma_capabilities.get_capabilities() reports api_configured=False when empty.
    wfirma_access_key:              str  = Field(default="")
    wfirma_secret_key:              str  = Field(default="")
    wfirma_app_key:                 str  = Field(default="")
    wfirma_company_id:              str  = Field(default="")
    wfirma_warehouse_id:            str  = Field(default="")
    wfirma_warehouse_module_enabled: bool = Field(default=False)
    wfirma_create_product_allowed:  bool = Field(default=False)
    wfirma_create_customer_allowed: bool = Field(default=False)
    wfirma_create_proforma_allowed: bool = Field(default=False)
    wfirma_edit_product_allowed:    bool = Field(default=False)
    wfirma_edit_invoice_allowed:    bool = Field(default=False)
    wfirma_sync_customers_allowed:  bool = Field(default=False)
    # B0 (MDOC-cache): controls local-only persistence of wFirma contractors
    # into the suppliers table via POST /api/v1/suppliers/sync-from-wfirma.
    # Reads wFirma; never writes to wFirma. When False, the route returns a
    # dry-run plan (preview) and refuses to mutate suppliers.sqlite.
    wfirma_sync_suppliers_allowed:  bool = Field(default=False)
    wfirma_delete_invoice_allowed:  bool = Field(default=False)
    wfirma_create_pz_allowed:       bool = Field(default=False)
    # Manual Proforma → final invoice conversion gate. Off by default;
    # operator flips to true only for the conversion run, then back.
    wfirma_create_invoice_allowed:  bool = Field(default=False)
    wfirma_supplier_contractor_id:  str  = Field(default="")

    # ── Carrier subsystem (DHL Express outbound shipping) ────────────────────
    # Status gate — controls carrier API adapter selection.
    # "pending" (default): all carrier routes return 503; no API calls possible.
    # "shadow":            DhlExpressShadowAdapter used; responses are simulated.
    # "live":              DhlExpressLiveAdapter used; requires allowlist entry.
    carrier_api_status: str = Field(default="pending")

    # PLT (Paperless Trade) gate — independent of carrier_api_status.
    carrier_plt_status: str = Field(default="pending")

    # Comma-separated batch_ids allowed for live carrier calls.
    # Empty = no live calls permitted even when carrier_api_status=live.
    carrier_live_allowlist: str = Field(default="")

    # DHL Express API credentials — all None by default (no live capability).
    dhl_express_api_key:        Optional[str] = Field(default=None)
    dhl_express_api_secret:     Optional[str] = Field(default=None)
    dhl_express_api_url:        str           = Field(default="https://express.api.dhl.com")
    dhl_express_account_number: Optional[str] = Field(default=None)

    # DHL webhook HMAC secret. None = webhook endpoint returns 503 (never silently open).
    dhl_webhook_secret: Optional[str] = Field(default=None)

    # Carrier file storage root. None = defaults to storage_root / "carrier" at runtime.
    carrier_storage_root: Optional[Path] = Field(default=None)

    # ── Cliq bot batch collection ─────────────────────────────────────────────
    # Expire an incomplete (missing files) session after N minutes of inactivity
    batch_session_timeout_minutes: int = 30
    # Auto-submit a READY session after N minutes of inactivity (no /submit needed)
    batch_auto_submit_minutes: int = 20
    # Fire processing immediately when the batch reaches ready state (all files present)
    batch_auto_submit_if_ready: bool = False
    # Allow synthetic test user IDs (user456, test, demo) — disabled in production
    debug_allow_test_sessions: bool = False
    # Re-enable old Cliq BatchManager flow (POST /batch/start, /add, /submit, /cancel,
    # /sessions) — disabled by default now that the Shipment Batch model is canonical.
    # Set DEBUG_ALLOW_OLD_BATCH_FLOW=true in .env only for backward-compat testing.
    debug_allow_old_batch_flow: bool = False

    # Developer workflow bypass (EJ_DEV_WORKFLOW_BYPASS).
    # When True: proforma PREVIEW routes downgrade missing-customer-authority
    # from a hard blocker to a non-blocking warning, so developers can inspect
    # draft line structures before all wFirma customer mappings are established.
    # NEVER bypasses: wFirma create (proforma, invoice, PZ), fiscal gates,
    # ZC429/export gates, or any write operation.  Default False = production-safe.
    ej_dev_workflow_bypass: bool = False

    # ── DHL self-clearance program (W-5 / P0 scaffolding — ADR-010, ADR-012..016) ──
    # Phase-scoped live flags (default OFF — ADR-010). Restartless-flippable
    # via POST /api/v1/admin/runtime-flags/self-clearance once P0 ships.
    #
    # Asymmetry notes:
    #   • p3_tracker_paused is a kill switch (no shadow equivalent meaningful).
    #   • p5_pz_trigger_enabled is an inner gate (no shadow equivalent — shadow
    #     vs live is governed by p5_live_enabled).
    dhl_selfclearance_p2_live_enabled:        bool = Field(default=False)
    dhl_selfclearance_p2_shadow_mode:         bool = Field(default=True)
    dhl_selfclearance_p3_live_enabled:        bool = Field(default=False)
    dhl_selfclearance_p3_shadow_mode:         bool = Field(default=True)
    dhl_selfclearance_p3_tracker_paused:      bool = Field(default=False)
    dhl_selfclearance_p4_live_enabled:        bool = Field(default=False)
    dhl_selfclearance_p4_shadow_mode:         bool = Field(default=True)
    dhl_selfclearance_p5_live_enabled:        bool = Field(default=False)
    dhl_selfclearance_p5_shadow_mode:         bool = Field(default=True)
    dhl_selfclearance_p5_pz_trigger_enabled:  bool = Field(default=False)

    # ── DHL orchestrator (Phase 1) ─────────────────────────────────────────
    # Controlled DHL shipment orchestration engine.  Default state: OFF +
    # shadow.  Even with master enabled, individual action flags must be
    # explicitly turned on; AUTO_SEND_* flags remain false until a separate
    # operator decision.  See services/dhl_orchestrator.py for semantics.
    dhl_orch_enabled:                  bool = Field(default=False)
    dhl_orch_shadow_mode:              bool = Field(default=True)
    dhl_orch_tick_interval_sec:        int  = Field(default=600)
    dhl_orch_auto_refresh_tracking:    bool = Field(default=False)
    dhl_orch_auto_monitor_sweep:       bool = Field(default=False)
    dhl_orch_auto_email_ingest:        bool = Field(default=False)
    dhl_orch_auto_refresh_proposals:   bool = Field(default=False)
    dhl_orch_auto_build_packages:      bool = Field(default=False)
    dhl_orch_auto_send_agency:         bool = Field(default=False)
    dhl_orch_auto_send_dhl_reply:      bool = Field(default=False)
    # Phase B2 — agency advance pack (pre-arrival, side-channel)
    dhl_orch_auto_send_agency_advance: bool = Field(default=False)
    # Phase B3 — DHL follow-up SLA (post-arrival)
    dhl_orch_auto_send_dhl_followup:   bool = Field(default=False)
    dhl_orch_tracking_cooldown_min:    int  = Field(default=30)
    dhl_orch_monitor_cooldown_min:     int  = Field(default=30)
    dhl_orch_email_ingest_cooldown_min: int = Field(default=60)
    dhl_orch_proposals_cooldown_min:   int  = Field(default=10)

    # Classifier confidence thresholds (literal identifiers — phases quote verbatim)
    dhl_selfclearance_p4_classifier_min_confidence:  float = Field(default=0.85)
    dhl_selfclearance_p5_classifier_min_confidence:  float = Field(default=0.95)

    # Follow-up scheduler (ADR-014 policy)
    dhl_selfclearance_followup_working_interval_sec:  int = Field(default=7200)
    dhl_selfclearance_followup_offhours_interval_sec: int = Field(default=21600)
    dhl_selfclearance_followup_working_hours_window:  str = Field(default="08:00-16:00 CET")
    dhl_selfclearance_followup_livelock_budget_hours: int = Field(default=168)

    # Path A clearance value threshold. Reading site lives in clearance_decision.py;
    # this exposes it as config so an operator can override via the admin endpoint.
    dhl_selfclearance_value_threshold_usd:    int = Field(default=2500)

    # ── Phase 6F.5 — Dual-write finance postings (feature-flagged, default OFF) ─
    # When ``finance_dual_write_enabled`` is True, the /post proforma route
    # invokes a SEPARATE write to ``finance_postings.sqlite`` AFTER the legacy
    # ``mark_post_succeeded`` commit returns. The dual-write is failure-isolated:
    # any exception is swallowed and logged at WARNING — it never rolls back
    # the legacy commit and never alters the /post response.
    #
    # When ``finance_dual_write_shadow`` is True (and dual-write is enabled),
    # the hook computes the full payload + sha1 idempotency keys and logs at
    # INFO ``finance_dual_write_shadow ...``, but does NOT call create_charge
    # or create_posting. Use shadow mode to validate payloads in production
    # before flipping to real persistence.
    #
    # Both default to False. Production deploys must verify these are unset
    # or false in the NSSM env block before any operator-driven activation.
    # Approval package: tasks/phase-6f-5-dual-write-approval-package.md
    finance_dual_write_enabled:  bool = Field(default=False)
    finance_dual_write_shadow:   bool = Field(default=False)


settings = Settings()
