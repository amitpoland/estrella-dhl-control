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
    workdrive_client_id:      str = Field(default="", env="WORKDRIVE_CLIENT_ID")
    workdrive_client_secret:  str = Field(default="", env="WORKDRIVE_CLIENT_SECRET")
    workdrive_refresh_token:  str = Field(default="", env="WORKDRIVE_REFRESH_TOKEN")
    # myfolder_id of the WorkDrive user (MYSPACE_LIBRARY root). Pre-discovered:
    workdrive_myfolder_id:    str = Field(default="", env="WORKDRIVE_MYFOLDER_ID")
    # Optional: override upload root to a specific subfolder inside MYSPACE_LIBRARY
    workdrive_parent_id:      str = Field(default="", env="WORKDRIVE_PARENT_ID")
    workdrive_token_url:      str = Field(
        default="https://accounts.zoho.in/oauth/v2/token", env="WORKDRIVE_TOKEN_URL"
    )
    workdrive_api_url:        str = Field(
        default="https://workdrive.zoho.in", env="WORKDRIVE_API_URL"
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
    anthropic_api_key:   Optional[str] = Field(default=None, env="ANTHROPIC_API_KEY")
    ai_parser_model:     str           = Field(default="claude-sonnet-4-6", env="AI_PARSER_MODEL")
    ai_parser_enabled:   bool          = Field(default=False, env="AI_PARSER_ENABLED")

    # ── Carrier tracking API credentials ─────────────────────────────────────
    dhl_api_key:         Optional[str] = Field(default=None, env="DHL_API_KEY")
    fedex_client_id:     Optional[str] = Field(default=None, env="FEDEX_CLIENT_ID")
    fedex_client_secret: Optional[str] = Field(default=None, env="FEDEX_CLIENT_SECRET")

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
    dhl_tracking_api_key:    Optional[str] = Field(default=None, env="DHL_TRACKING_API_KEY")
    dhl_tracking_api_secret: Optional[str] = Field(default=None, env="DHL_TRACKING_API_SECRET")
    dhl_tracking_api_status: str           = Field(default="pending", env="DHL_TRACKING_API_STATUS")

    # ── DHL customs email routing (P2 Slice A — proactive dispatch) ───────────
    # Authoritative recipient + CC for proactive customs dispatch emails.
    # Resolved at queue time, never read from operator-supplied request body.
    # Empty string means "not configured":
    #   - dev/local/test → falls back to dev-null@localhost (test sink)
    #   - any other environment → queue aborts with 500 (fail loud)
    dhl_customs_email: str = Field(default="", env="DHL_CUSTOMS_EMAIL")
    dhl_customs_cc:    str = Field(default="", env="DHL_CUSTOMS_CC")

    # ── Phase 2.3 — Path A auto-queue at Departed origin ──────────────────────
    # Default-False feature flag. When True, the active_shipment_monitor sweep
    # auto-creates + auto-approves + auto-queues the proactive customs dispatch
    # email (A2a) on the first Departed-origin tracking event for any Path A
    # (dhl_self_clearance) shipment that passes the eleven-check validation
    # gate. Spec ref: docs/dhl_clearance_paths.md hard rules 9, 11, 12 and the
    # Tracking-driven triggers section. SECURITY review required all twelve
    # hard guarantees from the pre-implementation security pass be encoded.
    enable_path_a_auto_queue: bool = Field(default=False, env="ENABLE_PATH_A_AUTO_QUEUE")

    # ── Zoho Mail (OAuth2 with refresh-token rotation) ────────────────────────
    # All values come from .env — never hardcode.
    # Required for /api/v1/dhl/scan-inbox to perform a backend mailbox search.
    # When refresh_token + client_id + client_secret are set, access_token is
    # auto-refreshed when expired; the static ZOHO_MAIL_API_TOKEN is optional
    # bootstrap-only and never written back.
    zoho_mail_api_token:     Optional[str] = Field(default=None, env="ZOHO_MAIL_API_TOKEN")
    zoho_mail_refresh_token: Optional[str] = Field(default=None, env="ZOHO_MAIL_REFRESH_TOKEN")
    zoho_client_id:          Optional[str] = Field(default=None, env="ZOHO_CLIENT_ID")
    zoho_client_secret:      Optional[str] = Field(default=None, env="ZOHO_CLIENT_SECRET")
    zoho_accounts_base:      str           = Field(default="https://accounts.zoho.eu", env="ZOHO_ACCOUNTS_BASE")
    zoho_mail_api_base:      str           = Field(default="https://mail.zoho.eu/api", env="ZOHO_MAIL_API_BASE")
    zoho_mail_account_id:    Optional[str] = Field(default=None, env="ZOHO_MAIL_ACCOUNT_ID")

    # ── Email scan routing ────────────────────────────────────────────────────
    # "auto"        → use Zoho REST API when creds present, else AI Bridge
    # "bridge_only" → always route to AI Bridge regardless of credentials
    # "api_only"    → always use Zoho REST; never fall back to bridge
    email_scan_mode: str = Field(default="auto", env="EMAIL_SCAN_MODE")

    # Email Evidence V2 — default ON. Set EMAIL_EVIDENCE_V2=0 to disable (rollback).
    # When ON, ingestion writes to the local evidence store, uses since-cursor for
    # Zoho REST searches, and routes via the processor pipeline.
    email_evidence_v2: bool = Field(default=True, env="EMAIL_EVIDENCE_V2")

    # ── SMTP send (Zoho App Password) ─────────────────────────────────────────
    # Required for actual outgoing email delivery via /api/v1/email-queue/{id}/send.
    # Without these, the send endpoint returns "smtp_not_configured" and the
    # queue entry stays at status=pending. Generate a Zoho App Password at
    #   https://accounts.zoho.in/home#security/app_passwords
    # Default to smtppro.zoho.in (paid Zoho Workplace). Free accounts use
    # smtp.zoho.in — override via SMTP_HOST in .env if needed.
    smtp_host:     str = Field(default="smtppro.zoho.in", env="SMTP_HOST")
    smtp_port:     int = Field(default=465,               env="SMTP_PORT")
    smtp_user:     Optional[str] = Field(default=None,    env="SMTP_USER")
    smtp_password: Optional[str] = Field(default=None,    env="SMTP_PASSWORD")
    smtp_use_ssl:  bool = Field(default=True,             env="SMTP_USE_SSL")
    # Read-receipt headers (Disposition-Notification-To / Return-Receipt-To /
    # X-Confirm-Reading-To). When enabled, every outgoing email asks the
    # recipient's MUA to send a read confirmation back to email_read_receipt_to
    # (defaults to the sender identity if blank).
    email_read_receipt_enabled: bool = Field(default=False, env="EMAIL_READ_RECEIPT_ENABLED")
    email_read_receipt_to:      str  = Field(default="",    env="EMAIL_READ_RECEIPT_TO")
    # MCP send fallback — total attachment-size cap (bytes). Above this,
    # MCP send refuses (PDFs too heavy via tool-call args). Default 200KB.
    mcp_send_max_attachment_bytes: int = Field(default=200_000, env="MCP_SEND_MAX_ATTACHMENT_BYTES")

    # ── wFirma API (3-header key auth — Basic Auth deprecated 2023-07-02) ───────
    # Source: wFirma → Ustawienia → Bezpieczeństwo → Aplikacje → Klucze API
    # All fields default to "" so the app starts safely without wFirma configured.
    # wfirma_capabilities.get_capabilities() reports api_configured=False when empty.
    wfirma_access_key:              str  = Field(default="",    env="WFIRMA_ACCESS_KEY")
    wfirma_secret_key:              str  = Field(default="",    env="WFIRMA_SECRET_KEY")
    wfirma_app_key:                 str  = Field(default="",    env="WFIRMA_APP_KEY")
    wfirma_company_id:              str  = Field(default="",    env="WFIRMA_COMPANY_ID")
    wfirma_warehouse_id:            str  = Field(default="",    env="WFIRMA_WAREHOUSE_ID")
    wfirma_warehouse_module_enabled: bool = Field(default=False, env="WFIRMA_WAREHOUSE_MODULE_ENABLED")
    wfirma_create_product_allowed:  bool = Field(default=False, env="WFIRMA_CREATE_PRODUCT_ALLOWED")
    wfirma_create_customer_allowed: bool = Field(default=False, env="WFIRMA_CREATE_CUSTOMER_ALLOWED")
    wfirma_create_proforma_allowed: bool = Field(default=False, env="WFIRMA_CREATE_PROFORMA_ALLOWED")
    wfirma_edit_product_allowed:    bool = Field(default=False, env="WFIRMA_EDIT_PRODUCT_ALLOWED")
    wfirma_edit_invoice_allowed:    bool = Field(default=False, env="WFIRMA_EDIT_INVOICE_ALLOWED")
    wfirma_sync_customers_allowed:  bool = Field(default=False, env="WFIRMA_SYNC_CUSTOMERS_ALLOWED")
    wfirma_delete_invoice_allowed:  bool = Field(default=False, env="WFIRMA_DELETE_INVOICE_ALLOWED")
    wfirma_create_pz_allowed:       bool = Field(default=False, env="WFIRMA_CREATE_PZ_ALLOWED")
    # Manual Proforma → final invoice conversion gate. Off by default;
    # operator flips to true only for the conversion run, then back.
    wfirma_create_invoice_allowed:  bool = Field(default=False, env="WFIRMA_CREATE_INVOICE_ALLOWED")
    wfirma_supplier_contractor_id:  str  = Field(default="",    env="WFIRMA_SUPPLIER_CONTRACTOR_ID")

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

    # ── Carrier DHL Express live adapter (DL-F1) ──────────────────────────────
    # DHL MyDHL API credentials. The live adapter is selected by the
    # action route factory only when ALL of:
    #   * carrier_dhl_live_enabled is True
    #   * dhl_express_api_status is "sandbox" or "production"
    #   * username + password + account_number are non-empty
    # Otherwise the factory falls back to DHLExpressStubAdapter so dev /
    # CI / unconfigured environments stay offline. Misconfiguration NEVER
    # raises; the worst case is "stub when you wanted live", surfaced via
    # the dashboard.
    dhl_express_api_username:    str = Field(default="",  env="DHL_EXPRESS_API_USERNAME")
    dhl_express_api_password:    str = Field(default="",  env="DHL_EXPRESS_API_PASSWORD")
    dhl_express_account_number:  str = Field(default="",  env="DHL_EXPRESS_ACCOUNT_NUMBER")
    # Three-state lifecycle gate (mirrors dhl_tracking_api_status):
    #   "pending"     — DHL has not approved this account; no live calls.
    #   "sandbox"     — calls https://express.api.dhl.com/mydhlapi/test
    #   "production"  — calls https://express.api.dhl.com/mydhlapi
    dhl_express_api_status:      str  = Field(default="pending", env="DHL_EXPRESS_API_STATUS")
    # Master kill-switch. Symmetrical to carrier_dhl_webhook_enabled.
    # When False the route factory unconditionally selects the stub
    # regardless of any other setting. Operators flip this last, after
    # credentials and status are validated in shadow mode.
    carrier_dhl_live_enabled:    bool = Field(default=False, env="CARRIER_DHL_LIVE_ENABLED")

    # ── Carrier DHL webhook ingestion (DL-E1) ─────────────────────────────────
    # Master switch. When False, both /api/v1/carrier/webhook/* endpoints
    # return HTTP 503 webhook_disabled. The router is mounted regardless so
    # the endpoints are discoverable, but they remain inert until an
    # operator explicitly flips this flag.
    carrier_dhl_webhook_enabled: bool = False
    # Comma-separated CIDR list. Empty means "no IP check" (dev only).
    # When non-empty, the events endpoint rejects requests whose source
    # IP is outside every listed range with HTTP 403.
    carrier_dhl_webhook_ip_allowlist: str = ""
    # Hard cap on the size of the inbound shipments[] array on a single
    # push. Defends against an oversized payload exhausting the 5-second
    # DHL response budget.
    carrier_dhl_webhook_max_shipments_per_push: int = 200


settings = Settings()
