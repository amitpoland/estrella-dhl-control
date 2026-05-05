"""
routes_system.py — Service version and deployment metadata.

Endpoints
---------
  GET /api/v1/system/version
       Returns the git commit hash and deploy timestamp written by
       deploy-service.sh. No authentication required — safe to expose.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from ..core.config import settings
from ..core.logging import get_logger

log    = get_logger(__name__)
router = APIRouter(prefix="/api/v1/system", tags=["system"])

_VERSION_FILE = settings.storage_root / "version.json"


@router.get("/version")
def get_version() -> JSONResponse:
    """
    Return commit hash and deploy timestamp.

    Written by deploy-service.sh. Falls back gracefully when the file is
    absent (first run before a deploy, or direct uvicorn launch from dev).
    """
    try:
        data        = json.loads(_VERSION_FILE.read_text())
        commit      = data.get("commit", "unknown")
        deployed_at = data.get("deployed_at", "unknown")
    except FileNotFoundError:
        commit      = "dev"
        deployed_at = "not deployed"
    except Exception as exc:
        log.warning("version.json read error: %s", exc)
        commit      = "unknown"
        deployed_at = "unknown"

    # Short display string shown in the UI footer: commit · YYYY-MM-DD HH:MM
    if deployed_at not in ("not deployed", "unknown"):
        try:
            dt         = datetime.fromisoformat(deployed_at)
            short_date = dt.strftime("%Y-%m-%d %H:%M")
        except Exception:
            short_date = deployed_at[:16]
        short = f"{commit} · {short_date}"
    else:
        short = commit

    return JSONResponse({
        "commit":      commit,
        "deployed_at": deployed_at,
        "short":       short,
    })
