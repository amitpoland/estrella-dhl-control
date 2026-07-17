#!/usr/bin/env python
"""
review_launch.py — safety-gated, non-production launcher for GATE-6 review.

Purpose
-------
Serve an EXACT git commit of the EJ Dashboard service in a review environment that
CANNOT reach any live third-party service — DHL (Express + tracking), wFirma, Zoho
Cliq / WorkDrive / Mail, SMTP, or Anthropic — using isolated storage, so an operator
can browser-verify user-visible behaviour (e.g. PR #940 transport authority) safely.

It is generic: point --app-dir at any extracted tree, --commit at its SHA. #940 is
the first consumer.

Safety model (fail-closed)
--------------------------
Before importing the application it force-neutralises every live-service credential
and write flag in the process environment, forces the carrier adapter to SHADOW with
an empty allowlist, disables the wFirma startup refresh, and REFUSES TO START if:
  * the resolved storage root is (or is inside) a known live/production storage root, or
  * a live credential / live carrier status survives neutralisation (defensive assert), or
  * --app-dir / --storage-root are missing or invalid.

The server then runs IN THIS PROCESS via ``uvicorn.run`` (no subprocess), so the
preview manager owns exactly the process that serves the review — no orphaned server.

It writes ``<storage-root>/version.json`` = {"commit", "deployed_at"} so
``GET /api/v1/system/version`` reports the served commit (fingerprint).

This launcher NEVER writes a credential to any repository file and NEVER reads a
production .env (it sets os.environ, which pydantic-settings ranks above any .env).
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path

# ── Env keys (mirror service/app/core/config.py) ──────────────────────────────
# EVERY external-service credential / token / outbound webhook URL that could let
# the review server reach a real third party. Forced to "" (falsy → each client
# refuses) so a host-set value or a .env cannot leak in. Keep in sync with
# service/app/core/config.py — a field here that is missing from config is
# harmless; a config credential missing HERE is a live-write leak.
_LIVE_CREDENTIAL_KEYS = (
    # DHL Express (booking) + DHL tracking (read)
    "DHL_EXPRESS_API_KEY", "DHL_EXPRESS_API_SECRET", "DHL_EXPRESS_ACCOUNT_NUMBER",
    "DHL_API_KEY", "DHL_TRACKING_API_KEY", "DHL_TRACKING_API_SECRET",
    # wFirma
    "WFIRMA_ACCESS_KEY", "WFIRMA_SECRET_KEY", "WFIRMA_APP_KEY", "WFIRMA_COMPANY_ID",
    # Zoho Cliq (posts to the production #PZ channel)
    "CLIQ_WEBHOOK_URL", "CLIQ_CHANNEL_WEBHOOK_URL", "CLIQ_BOT_TOKEN",
    "CLIQ_REFRESH_TOKEN", "CLIQ_CLIENT_ID", "CLIQ_CLIENT_SECRET",
    # Zoho WorkDrive (file upload)
    "WORKDRIVE_CLIENT_ID", "WORKDRIVE_CLIENT_SECRET", "WORKDRIVE_REFRESH_TOKEN",
    # Zoho Mail
    "ZOHO_MAIL_API_TOKEN", "ZOHO_MAIL_REFRESH_TOKEN", "ZOHO_CLIENT_ID",
    "ZOHO_CLIENT_SECRET",
    # SMTP (outbound email)
    "SMTP_USER", "SMTP_PASSWORD",
    # Anthropic + AI Cowork (LLM calls — cost + data egress)
    "ANTHROPIC_API_KEY", "ANTHROPIC_ADMIN_API_KEY", "ANTHROPIC_API_KEY_ID",
    "AI_COWORK_API_KEY",
    # FedEx (tracking OAuth — read egress, not carrier-shadow-gated)
    "FEDEX_CLIENT_ID", "FEDEX_CLIENT_SECRET",
    # Inbound webhook HMAC secrets
    "DHL_WEBHOOK_SECRET", "WFIRMA_WEBHOOK_KEY",
)
# Write flags that must be OFF for a review server.
_WRITE_FLAG_KEYS = (
    "WFIRMA_CREATE_PRODUCT_ALLOWED",
    "WFIRMA_CREATE_CUSTOMER_ALLOWED",
    "WFIRMA_CREATE_PROFORMA_ALLOWED",
    "WFIRMA_CREATE_PZ_ALLOWED",
    "WFIRMA_CREATE_INVOICE_ALLOWED",
    "WFIRMA_EDIT_INVOICE_ALLOWED",
    "WFIRMA_EDIT_PRODUCT_ALLOWED",
    "WFIRMA_CORRECTION_PUSH_ALLOWED",
    "WFIRMA_DELETE_INVOICE_ALLOWED",
    "WFIRMA_SYNC_CUSTOMERS_ALLOWED",
)
_TRUE = {"1", "true", "yes", "on"}


def _is_truthy(val: str | None) -> bool:
    return bool(val) and val.strip().lower() in _TRUE


# Canonical production layout (service/docs + prod-runtime-ops-facts): NSSM serves
# from C:\PZ. Also the other permanent non-production trees (writing review data into
# them would pollute integration/verify). Refused UNCONDITIONALLY — the guard must not
# depend on the operator's shell having STORAGE_ROOT set (NSSM sets it on the service
# process, not on a hand-opened shell).
_PRODUCTION_ROOTS = (
    r"C:\PZ", r"C:\PZ\storage", r"C:\PZ\app", r"C:\PZ\app\storage",
    r"C:\PZ-main", r"C:\PZ-active", r"C:\PZ-verify", r"C:\PZ-archive",
)


def _norm(p: Path) -> str:
    """Case/'/'-normalised absolute string for robust Windows path comparison."""
    return os.path.normcase(os.path.normpath(str(p.resolve())))


def _live_storage_roots() -> list[Path]:
    """Known production/live storage roots that review storage must never touch.

    Extends service/tests/conftest.py:_LIVE_ROOTS with the hardcoded production
    tree (so the guard holds even without STORAGE_ROOT in the shell) plus whatever
    STORAGE_ROOT the host had set before this launcher runs.
    """
    here = Path(__file__).resolve()
    repo_root = here.parents[2]  # …/service/scripts/review_launch.py → repo root
    roots = [
        (repo_root / "service" / "app" / "storage").resolve(),
        (repo_root / "service" / "storage").resolve(),
    ]
    for prod in _PRODUCTION_ROOTS:
        try:
            roots.append(Path(prod).resolve())
        except OSError:
            pass
    host_sr = os.environ.get("STORAGE_ROOT", "").strip()
    if host_sr:
        try:
            roots.append(Path(host_sr).resolve())
        except OSError:
            pass
    return roots


def _refuse(msg: str) -> "NoReturn":  # type: ignore[name-defined]
    sys.stderr.write(f"\n[review_launch] REFUSED (fail-closed): {msg}\n")
    raise SystemExit(2)


def _assert_isolated_storage(storage_root: Path) -> None:
    sr = storage_root.resolve()
    sr_n = _norm(sr)
    for live in _live_storage_roots():
        live_n = _norm(live)
        # Case-insensitive overlap: equal, or one is a path-prefix of the other.
        if (sr_n == live_n
                or sr_n.startswith(live_n + os.sep)
                or live_n.startswith(sr_n + os.sep)):
            _refuse(
                f"storage root {sr} overlaps a live/production root {live}. "
                "Choose an isolated path outside the repo (e.g. under C:\\PZ-wt\\)."
            )


def _neutralise_and_configure(storage_root: Path, api_key: str) -> None:
    """Force the process env into a provably review-safe state, then assert it."""
    # 1. Force-clear every live credential (empty string ⇒ downstream 'if not key' fails).
    for k in _LIVE_CREDENTIAL_KEYS:
        os.environ[k] = ""
    # 2. Force every write flag OFF.
    for k in _WRITE_FLAG_KEYS:
        os.environ[k] = "false"
    # 3. Carrier: SHADOW adapter (mock, no HTTP) + empty allowlist ⇒ no live booking possible.
    os.environ["CARRIER_API_STATUS"] = "shadow"
    os.environ["CARRIER_PLT_STATUS"] = "shadow"
    os.environ["CARRIER_LIVE_ALLOWLIST"] = ""
    # 4. No wFirma call on startup; no AI execution paths.
    os.environ["SERIES_BOOTSTRAP_ENABLED"] = "false"
    os.environ["AI_COWORK_ENABLED"] = "false"
    os.environ["AI_PARSER_ENABLED"] = "false"
    # 5. Isolated storage + non-production auth key + dev-tier (no prod-secret enforcement).
    #    A FRESH JWT secret invalidates any production-issued session cookie.
    os.environ["STORAGE_ROOT"] = str(storage_root)
    os.environ["API_KEY"] = api_key
    os.environ["AUTH_SECRET_KEY"] = "rev_jwt_" + secrets.token_urlsafe(24)
    os.environ["ENVIRONMENT"] = "dev"

    # 6. DEFENSIVE ASSERT — refuse if anything survived neutralisation.
    for k in _LIVE_CREDENTIAL_KEYS:
        if os.environ.get(k, "").strip():
            _refuse(f"live credential {k} is still set after neutralisation")
    for k in _WRITE_FLAG_KEYS:
        if _is_truthy(os.environ.get(k)):
            _refuse(f"write flag {k} is still truthy after neutralisation")
    for k in ("CARRIER_API_STATUS", "CARRIER_PLT_STATUS"):
        if os.environ.get(k) != "shadow":
            _refuse(f"{k} is not 'shadow'")
    if os.environ.get("CARRIER_LIVE_ALLOWLIST", "").strip():
        _refuse("CARRIER_LIVE_ALLOWLIST is not empty")


def _warn_if_commit_unverified(app_dir: Path, commit: str) -> None:
    """Cross-check --commit against the tree's git HEAD when possible (advisory)."""
    import subprocess
    try:
        head = subprocess.run(
            ["git", "-C", str(app_dir), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        head = None
    if head is None or head.returncode != 0:
        sys.stderr.write(
            f"[review_launch] NOTE: --app-dir {app_dir} is not a git tree "
            f"(extracted archive); served commit '{commit}' is caller-asserted, "
            "not git-verified.\n")
        return
    actual = head.stdout.strip()
    if not actual.startswith(commit) and not commit.startswith(actual[:len(commit)]):
        sys.stderr.write(
            f"[review_launch] WARNING: --commit '{commit}' does not match tree HEAD "
            f"'{actual}'. version.json/fingerprint will be MISLEADING.\n")


def _write_version(storage_root: Path, commit: str) -> None:
    storage_root.mkdir(parents=True, exist_ok=True)
    (storage_root / "version.json").write_text(
        json.dumps(
            {
                "commit": commit,
                "deployed_at": datetime.now(timezone.utc).isoformat(),
                "channel": "gate6-review",
            }
        ),
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Safety-gated GATE-6 review launcher.")
    p.add_argument("--app-dir", required=True,
                   help="Absolute path to the extracted tree's 'service' dir.")
    p.add_argument("--storage-root", required=True,
                   help="Isolated review storage dir (must NOT overlap a live root).")
    p.add_argument("--commit", required=True, help="Served git SHA (for version.json).")
    p.add_argument("--port", type=int, default=8137)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--api-key", default=os.environ.get("REVIEW_API_KEY", ""),
                   help="Non-production API key. Generated if omitted.")
    p.add_argument("--print-config", action="store_true",
                   help="Validate + print the review config as JSON and exit (no serve).")
    args = p.parse_args(argv)

    app_dir = Path(args.app_dir).resolve()
    if not (app_dir / "app" / "main.py").is_file():
        _refuse(f"--app-dir {app_dir} does not contain app/main.py")

    storage_root = Path(args.storage_root).resolve()
    _assert_isolated_storage(storage_root)

    api_key = args.api_key.strip() or ("rev_" + secrets.token_urlsafe(24))
    _neutralise_and_configure(storage_root, api_key)
    _write_version(storage_root, args.commit)

    key_fp = "sha256:" + __import__("hashlib").sha256(api_key.encode()).hexdigest()[:16]
    config = {
        "served_commit": args.commit,
        "app_dir": str(app_dir),
        "storage_root": str(storage_root),
        "host": args.host,
        "port": args.port,
        "review_api_key_fingerprint": key_fp,
        "carrier_api_status": os.environ["CARRIER_API_STATUS"],
        "carrier_live_allowlist_empty": os.environ["CARRIER_LIVE_ALLOWLIST"] == "",
        "live_credentials_present": any(
            os.environ.get(k, "").strip() for k in _LIVE_CREDENTIAL_KEYS
        ),
        "write_flags_on": [k for k in _WRITE_FLAG_KEYS if _is_truthy(os.environ.get(k))],
    }
    sys.stderr.write("[review_launch] review-safe config:\n"
                     + json.dumps(config, indent=2) + "\n")
    # The raw key goes to STDERR ONLY (never a repo file) so the operator can capture it.
    sys.stderr.write(f"[review_launch] REVIEW_API_KEY={api_key}\n")
    # Best-effort served-commit verification: if --app-dir is a git tree, compare
    # HEAD to --commit; an extracted archive has no .git → warn it is unverified.
    _warn_if_commit_unverified(app_dir, args.commit)

    if args.print_config:
        print(json.dumps(config))
        return 0

    # Serve IN-PROCESS so the preview manager owns the actual server process.
    sys.path.insert(0, str(app_dir))
    import uvicorn  # noqa: E402  (import after env is locked down)

    uvicorn.run("app.main:app", host=args.host, port=args.port, reload=False,
                log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
