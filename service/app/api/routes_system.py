"""
routes_system.py — Service version and deployment metadata.

Endpoints
---------
  GET /api/v1/system/version
       Returns the deploy marker SHA (canonical: C:\\PZ\\version.txt via Deploy-PZ)
       plus runtime environment mode. No authentication required — safe to expose.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from ..core.config import settings
from ..core.logging import get_logger
from ..services.diagnostics_capability_health import read_deploy_marker_sha

log    = get_logger(__name__)
router = APIRouter(prefix="/api/v1/system", tags=["system"])

_VERSION_FILE = settings.storage_root / "version.json"


@router.get("/version")
def get_version() -> JSONResponse:
    """
    Project deploy authority + runtime mode separately.

    ``deployed_sha`` / ``commit`` come from C:\\PZ\\version.txt (Deploy-PZ marker)
    when present. ``runtime_mode`` is settings.environment (dev/prod) and must
    not overload the deploy SHA field.
    Legacy storage/version.json remains a secondary fallback for deployed_at only.
    """
    deploy_sha, deploy_src = read_deploy_marker_sha()

    legacy_commit = ""
    deployed_at = "not deployed"
    try:
        data = json.loads(_VERSION_FILE.read_text(encoding="utf-8"))
        legacy_commit = str(data.get("commit") or "")
        deployed_at = data.get("deployed_at", "not deployed")
    except FileNotFoundError:
        pass
    except Exception as exc:
        log.warning("version.json read error: %s", exc)

    commit = deploy_sha or legacy_commit or "unknown"
    if not deploy_sha and not legacy_commit:
        # Dev launch with no marker — report unknown, not a fake release SHA
        commit = "unknown"
        deployed_at = deployed_at if deployed_at != "not deployed" else "not deployed"

    runtime_mode = settings.environment

    if deployed_at not in ("not deployed", "unknown"):
        try:
            dt = datetime.fromisoformat(deployed_at)
            short_date = dt.strftime("%Y-%m-%d %H:%M")
        except Exception:
            short_date = str(deployed_at)[:16]
        short = f"{commit[:12]} · {short_date}" if commit not in ("unknown", "dev") else commit
    else:
        short = commit[:12] if len(commit) > 12 else commit

    return JSONResponse({
        "commit": commit,
        "deployed_sha": deploy_sha or commit,
        "deploy_marker_source": deploy_src,
        "runtime_mode": runtime_mode,
        "deployed_at": deployed_at,
        "short": short,
        # Explicit: never confuse runtime mode with deploy identity
        "environment": runtime_mode,
    })
