"""
workdrive_uploader.py — Upload PZ output files directly to Zoho WorkDrive REST API.

Replaces the TrueSync-based approach (workdrive_sync.py) which syncs to a
separate namespace not accessible via the WorkDrive REST API.

This module uploads files directly to MYSPACE_LIBRARY so Claude MCP can
immediately find them, create share links, and post them to Cliq.

Required .env vars:
    WORKDRIVE_REFRESH_TOKEN   — Zoho OAuth refresh token with WorkDrive scope
    WORKDRIVE_CLIENT_ID       — Zoho OAuth client ID (Self Client)
    WORKDRIVE_CLIENT_SECRET   — Zoho OAuth client secret
    WORKDRIVE_PARENT_ID       — WorkDrive folder ID to upload into (MYSPACE_LIBRARY root
                                 or a specific subfolder; defaults to myfolder_id)

Optional .env vars:
    WORKDRIVE_MYFOLDER_ID     — myfolder_id of the user (auto-discovered if not set)
    WORKDRIVE_TOKEN_URL       — OAuth token endpoint (default: accounts.zoho.in)
    WORKDRIVE_API_URL         — WorkDrive API base (default: workdrive.zoho.in)

Setup (one-time, 2 minutes):
    1. Go to https://api-console.zoho.in/  →  Add Client  →  Self Client
    2. Scope: WorkDrive.files.CREATE,WorkDrive.files.READ,WorkDrive.files.ALL
    3. Click Generate Code → set duration 10 min
    4. Exchange for tokens:
         POST https://accounts.zoho.in/oauth/v2/token
           grant_type=authorization_code&code=<code>
           &client_id=<id>&client_secret=<secret>
           &redirect_uri=https://www.zoho.in
    5. Copy refresh_token into .env as WORKDRIVE_REFRESH_TOKEN
"""
from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import requests

log = logging.getLogger(__name__)

# ── OAuth token cache (in-process, refresh automatically) ───────────────────

_token_cache: Dict[str, Any] = {"access_token": None, "expires_at": 0.0}
_wd_lock = threading.Lock()


def _get_access_token() -> Optional[str]:
    """Return a valid WorkDrive access token, refreshing if needed."""
    now = time.time()
    with _wd_lock:
        if _token_cache["access_token"] and _token_cache["expires_at"] > now + 60:
            return _token_cache["access_token"]

    refresh_token = os.environ.get("WORKDRIVE_REFRESH_TOKEN", "")
    client_id = os.environ.get("WORKDRIVE_CLIENT_ID", "")
    client_secret = os.environ.get("WORKDRIVE_CLIENT_SECRET", "")
    token_url = os.environ.get(
        "WORKDRIVE_TOKEN_URL", "https://accounts.zoho.in/oauth/v2/token"
    )

    if not all([refresh_token, client_id, client_secret]):
        log.warning(
            "[workdrive_uploader] missing OAuth credentials "
            "(WORKDRIVE_REFRESH_TOKEN / CLIENT_ID / CLIENT_SECRET)"
        )
        return None

    try:
        resp = requests.post(
            token_url,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": client_id,
                "client_secret": client_secret,
            },
            timeout=15,
        )
        data = resp.json()
    except Exception as exc:
        log.error("[workdrive_uploader] token refresh failed: %s", exc)
        return None

    if "access_token" not in data:
        log.error("[workdrive_uploader] token refresh error: %s", data.get("error", "unknown"))
        return None

    with _wd_lock:
        _token_cache["access_token"] = data["access_token"]
        _token_cache["expires_at"] = now + int(data.get("expires_in", 3600))
    log.info("[workdrive_uploader] access token refreshed OK")
    return data["access_token"]


# ── Folder creation / resolution ─────────────────────────────────────────────

def _ensure_folder(parent_id: str, folder_name: str, token: str) -> Optional[str]:
    """
    Find or create a subfolder named `folder_name` under `parent_id`.
    Returns the folder resource_id, or None on failure.
    """
    api_base = os.environ.get("WORKDRIVE_API_URL", "https://workdrive.zoho.in")
    headers = {"Authorization": f"Bearer {token}"}

    # List existing children to find the folder
    try:
        resp = requests.get(
            f"{api_base}/api/v1/files/{parent_id}/files",
            headers=headers,
            params={"filter[type]": "folder"},
            timeout=15,
        )
        data = resp.json()
        for item in data.get("data", []):
            if item.get("attributes", {}).get("name") == folder_name:
                return item["id"]
    except Exception as exc:
        log.warning("[workdrive_uploader] folder list failed: %s", exc)

    # Create the folder
    try:
        resp = requests.post(
            f"{api_base}/api/v1/files",
            headers={**headers, "Content-Type": "application/vnd.api+json"},
            json={
                "data": {
                    "attributes": {
                        "name": folder_name,
                        "parent_id": parent_id,
                    },
                    "type": "files",
                }
            },
            timeout=15,
        )
        data = resp.json()
        folder_id = data.get("data", {}).get("id")
        if folder_id:
            log.info("[workdrive_uploader] created folder '%s' → %s", folder_name, folder_id)
            return folder_id
        log.error("[workdrive_uploader] folder create returned: %s", data)
    except Exception as exc:
        log.error("[workdrive_uploader] folder create failed: %s", exc)

    return None


def _resolve_batch_folder(batch_id: str, token: str) -> Optional[str]:
    """
    Ensure the path MYSPACE_LIBRARY/PZ/2026/04/BATCH_<batch_id>/ exists and
    return the folder resource_id for the batch folder.
    """
    # Determine parent: explicit env var or MYSPACE root (myfolder_id)
    root_id = os.environ.get("WORKDRIVE_PARENT_ID") or os.environ.get("WORKDRIVE_MYFOLDER_ID")
    if not root_id:
        log.error("[workdrive_uploader] WORKDRIVE_PARENT_ID not set")
        return None

    api_base = os.environ.get("WORKDRIVE_API_URL", "https://workdrive.zoho.in")
    headers = {"Authorization": f"Bearer {token}"}

    # Parse year/month from batch_id (SHIPMENT_XXXXXXXXX_YYYY-MM_...)
    parts = batch_id.split("_")
    year_month = None
    for p in parts:
        if len(p) == 7 and "-" in p:  # "2026-04"
            year_month = p
            break

    year, month = (year_month.split("-") if year_month else ("2026", "04"))

    # Walk/create: PZ → year → month → BATCH_<batch_id>
    current = root_id
    for folder_name in ["PZ", year, month, f"BATCH_{batch_id}"]:
        current = _ensure_folder(current, folder_name, token)
        if not current:
            log.error("[workdrive_uploader] could not resolve/create folder '%s'", folder_name)
            return None

    return current


# ── File upload ───────────────────────────────────────────────────────────────

def upload_file(file_path: Path, folder_id: str, token: str) -> Optional[str]:
    """
    Upload a single file to WorkDrive folder. Returns resource_id or None.
    """
    api_base = os.environ.get("WORKDRIVE_API_URL", "https://workdrive.zoho.in")
    headers = {"Authorization": f"Bearer {token}"}

    try:
        with open(file_path, "rb") as fh:
            resp = requests.post(
                f"{api_base}/api/v1/upload",
                headers=headers,
                data={"parent_id": folder_id, "override-name-exist": "true"},
                files={"content": (file_path.name, fh, _mime(file_path))},
                timeout=60,
            )
        data = resp.json()
        resource_id = (
            data.get("data", [{}])[0].get("attributes", {}).get("resource_id")
            or data.get("data", [{}])[0].get("id")
        )
        if resource_id:
            log.info("[workdrive_uploader] uploaded %s → %s", file_path.name, resource_id)
            return resource_id
        log.error("[workdrive_uploader] upload response: %s", data)
    except Exception as exc:
        log.error("[workdrive_uploader] upload failed %s: %s", file_path.name, exc)

    return None


def _mime(path: Path) -> str:
    ext = path.suffix.lower()
    return {
        ".pdf":  "application/pdf",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xls":  "application/vnd.ms-excel",
    }.get(ext, "application/octet-stream")


# ── Public API ────────────────────────────────────────────────────────────────

def is_configured() -> bool:
    """True if WorkDrive direct upload credentials are present in env."""
    return bool(
        os.environ.get("WORKDRIVE_REFRESH_TOKEN")
        and os.environ.get("WORKDRIVE_CLIENT_ID")
        and os.environ.get("WORKDRIVE_CLIENT_SECRET")
        and (os.environ.get("WORKDRIVE_PARENT_ID") or os.environ.get("WORKDRIVE_MYFOLDER_ID"))
    )


def upload_pz_outputs(
    batch_id: str,
    pdf_path: Path,
    xlsx_path: Path,
) -> Dict[str, Any]:
    """
    Upload PDF and XLSX to WorkDrive MYSPACE_LIBRARY/PZ/{year}/{month}/BATCH_{batch_id}/.

    Returns:
    {
        "success": bool,
        "pdf_resource_id": str | None,
        "xlsx_resource_id": str | None,
        "batch_folder_id": str | None,
        "error": str | None,
    }
    """
    result: Dict[str, Any] = {
        "success": False,
        "pdf_resource_id": None,
        "xlsx_resource_id": None,
        "batch_folder_id": None,
        "error": None,
    }

    if not is_configured():
        result["error"] = "workdrive_direct_upload_not_configured"
        log.info("[workdrive_uploader] not configured — skip direct upload")
        return result

    token = _get_access_token()
    if not token:
        result["error"] = "workdrive_token_refresh_failed"
        return result

    # Resolve (create if needed) the batch folder
    folder_id = _resolve_batch_folder(batch_id, token)
    if not folder_id:
        result["error"] = "batch_folder_creation_failed"
        return result

    result["batch_folder_id"] = folder_id

    # Upload PDF
    if pdf_path and pdf_path.is_file():
        result["pdf_resource_id"] = upload_file(pdf_path, folder_id, token)

    # Upload XLSX
    if xlsx_path and xlsx_path.is_file():
        result["xlsx_resource_id"] = upload_file(xlsx_path, folder_id, token)

    result["success"] = bool(
        result["pdf_resource_id"] and result["xlsx_resource_id"]
    )
    if not result["success"]:
        result["error"] = "one_or_more_uploads_failed"

    return result
