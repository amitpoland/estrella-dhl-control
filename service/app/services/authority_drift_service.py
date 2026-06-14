"""
authority_drift_service.py — Authority drift detection service (R2 + Phase 4)

R2: Compare live authority module hashes vs pinned manifest.
Phase 4: Emit structured alerts to audit logging when drift detected.

Design reference: designs/audit-drift-design.md v2 Part B (APPROVED)
"""
from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

log = logging.getLogger(__name__)

# Authority Registry (same as authority_audit.py and authority_startup.py)
AUTHORITY_REGISTRY = {
    "name_normalization.py": {
        "role": "Name normalization authority",
        "path": "app/services/name_normalization.py"
    },
    "dhl_followup_authority.py": {
        "role": "DHL follow-up authority (4-state advisory)",
        "path": "app/services/dhl_followup_authority.py"
    },
    "awb_address_authority.py": {
        "role": "AWB address resolution authority",
        "path": "app/services/awb_address_authority.py"
    },
    "tracking_db.py": {
        "role": "Tracking deduplication authority",
        "path": "app/services/tracking_db.py"
    }
}

# Drift severity mapping per design
DRIFT_SEVERITY_MAP = {
    "missing_manifest": "MEDIUM",
    "missing_module": "HIGH",
    "hash_mismatch": "HIGH",
    "multiple_modules_drifted": "CRITICAL",
    "hash_compute_error": "LOW"
}


def check_authority_drift() -> Dict[str, Any]:
    """R2: Check authority module drift against pinned manifest.

    Returns:
        Drift report dict with status, modules, and drift details
    """
    from ..core.config import settings

    service_root = Path(__file__).parent.parent.parent  # Go up to service root
    pinned_manifest_path = service_root / "app" / "authority_manifest_pinned.json"

    # Load pinned manifest
    if not pinned_manifest_path.exists():
        return {
            "drift_detected": True,
            "drift_type": "missing_manifest",
            "error": f"Pinned manifest not found: {pinned_manifest_path}",
            "modules": {}
        }

    try:
        pinned_manifest = json.loads(pinned_manifest_path.read_text(encoding="utf-8"))
    except Exception as e:
        return {
            "drift_detected": True,
            "drift_type": "manifest_read_error",
            "error": f"Failed to read pinned manifest: {e}",
            "modules": {}
        }

    # Generate live hashes
    live_modules = {}
    drift_count = 0
    module_errors = []

    for module_name, config in AUTHORITY_REGISTRY.items():
        module_path = service_root / config["path"]
        pinned_data = pinned_manifest.get("modules", {}).get(module_name, {})
        expected_hash = pinned_data.get("sha256")

        if not module_path.exists():
            live_modules[module_name] = {
                "status": "missing",
                "error": "Module file not found",
                "expected_hash": expected_hash
            }
            drift_count += 1
            module_errors.append(f"Missing module: {module_name}")
            continue

        try:
            content = module_path.read_text(encoding="utf-8")
            live_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

            if expected_hash and live_hash != expected_hash:
                live_modules[module_name] = {
                    "status": "drift",
                    "expected_hash": expected_hash,
                    "actual_hash": live_hash,
                    "size_bytes": len(content.encode("utf-8"))
                }
                drift_count += 1
                module_errors.append(f"Hash mismatch: {module_name}")
            else:
                live_modules[module_name] = {
                    "status": "ok",
                    "hash": live_hash,
                    "size_bytes": len(content.encode("utf-8"))
                }

        except Exception as e:
            live_modules[module_name] = {
                "status": "error",
                "error": str(e),
                "expected_hash": expected_hash
            }
            module_errors.append(f"Hash computation error: {module_name}")

    # Determine drift type and severity
    drift_detected = drift_count > 0
    drift_type = None

    if drift_detected:
        if drift_count > 1:
            drift_type = "multiple_modules_drifted"
        elif any(m["status"] == "missing" for m in live_modules.values()):
            drift_type = "missing_module"
        elif any(m["status"] == "drift" for m in live_modules.values()):
            drift_type = "hash_mismatch"
        elif any(m["status"] == "error" for m in live_modules.values()):
            drift_type = "hash_compute_error"

    return {
        "drift_detected": drift_detected,
        "drift_type": drift_type,
        "drift_count": drift_count,
        "total_modules": len(AUTHORITY_REGISTRY),
        "modules": live_modules,
        "errors": module_errors,
        "pinned_manifest_path": str(pinned_manifest_path),
        "checked_at": datetime.now(timezone.utc).isoformat()
    }


def emit_drift_alert(drift_report: Dict[str, Any], operator_email: str = "system") -> None:
    """Phase 4: Emit structured alert to audit logging when drift detected.

    Args:
        drift_report: Result from check_authority_drift()
        operator_email: Email of user who triggered the check
    """
    if not drift_report.get("drift_detected"):
        return  # No alert needed for clean state

    # Determine severity
    drift_type = drift_report.get("drift_type", "unknown")
    severity = DRIFT_SEVERITY_MAP.get(drift_type, "MEDIUM")

    # Build alert record
    alert_record = {
        "alert_type": "authority_drift_detected",
        "severity": severity,
        "correlation_id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "root_service": "estrella_pz_service",
        "operator_email": operator_email,
        "drift_summary": {
            "drift_type": drift_type,
            "drift_count": drift_report.get("drift_count", 0),
            "total_modules": drift_report.get("total_modules", 0),
            "errors": drift_report.get("errors", [])
        },
        "replay_payload": {
            "modules": drift_report.get("modules", {}),
            "pinned_manifest_path": drift_report.get("pinned_manifest_path"),
            "checked_at": drift_report.get("checked_at")
        }
    }

    # Emit to audit logging infrastructure
    try:
        # Use existing audit logger (find the pattern used elsewhere)
        audit_logger = logging.getLogger("audit")
        audit_logger.warning(
            "AUTHORITY_DRIFT_ALERT: %s severity=%s drift_type=%s modules_affected=%d correlation_id=%s",
            alert_record["alert_type"],
            severity,
            drift_type,
            drift_report.get("drift_count", 0),
            alert_record["correlation_id"]
        )

        # Also log the full structured record for replay
        log.info("Authority drift alert emitted: %s", json.dumps(alert_record, indent=2))

    except Exception as e:
        log.error("Failed to emit authority drift alert: %s", e)
        raise  # Re-raise so caller knows alerting failed