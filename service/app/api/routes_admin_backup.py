"""
routes_admin_backup.py — B7 Admin Backup Endpoints

POST /api/v1/admin/backup/run      — Run backup synchronously
GET  /api/v1/admin/backup/list     — List backup directories with summaries
POST /api/v1/admin/backup/validate — Validate specific backup by ID

All endpoints require admin role. Follows routes_admin.py auth pattern.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..auth.dependencies import require_admin
from ..core.config import settings
from ..services.backup_service import run_backup, prune_backups
from ..services.backup_validator import validate_backup

router = APIRouter(prefix="/api/v1/admin/backup", tags=["admin", "backup"])


class BackupValidateRequest(BaseModel):
    backup_id: str


@router.post("/run")
def backup_run(user: dict = Depends(require_admin)):
    """Run backup synchronously and return manifest summary."""
    try:
        manifest = run_backup()
        return {
            "success": True,
            "backup_id": manifest["backup_id"],
            "summary": manifest["summary"],
            "started_at": manifest["started_at"],
            "finished_at": manifest["finished_at"],
            "app_sha": manifest.get("app_sha"),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Backup failed: {e}")


@router.get("/list")
def backup_list(user: dict = Depends(require_admin)):
    """List backup directories with manifest summaries."""
    backup_root = Path(settings.backup_root)

    if not backup_root.exists():
        return {
            "backup_root": str(backup_root),
            "backups": []
        }

    backups = []

    for item in backup_root.iterdir():
        if not item.is_dir():
            continue

        manifest_path = item / "manifest.json"
        if not manifest_path.exists():
            continue

        try:
            with open(manifest_path, 'r', encoding='utf-8') as f:
                manifest = json.load(f)

            backups.append({
                "backup_id": item.name,
                "started_at": manifest.get("started_at"),
                "finished_at": manifest.get("finished_at"),
                "app_sha": manifest.get("app_sha"),
                "summary": manifest.get("summary", {}),
            })
        except Exception:
            # Skip corrupted manifests
            continue

    # Sort by backup_id (which is timestamp) descending
    backups.sort(key=lambda x: x["backup_id"], reverse=True)

    return {
        "backup_root": str(backup_root),
        "backups": backups
    }


@router.post("/validate")
def backup_validate(request: BackupValidateRequest, user: dict = Depends(require_admin)):
    """Validate specific backup by backup_id."""
    backup_root = Path(settings.backup_root)
    backup_dir = backup_root / request.backup_id

    if not backup_dir.exists() or not backup_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"Backup {request.backup_id} not found")

    try:
        result = validate_backup(str(backup_dir))
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Validation failed: {e}")


@router.post("/prune")
def backup_prune(dry_run: bool = False, user: dict = Depends(require_admin)):
    """Apply retention policy. Use dry_run=true to preview without deleting."""
    try:
        result = prune_backups(settings.backup_root, dry_run=dry_run)
        return {
            "success": True,
            "dry_run": dry_run,
            "result": result
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Prune failed: {e}")