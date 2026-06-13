"""
authority_startup.py — Authority drift detection startup service (R1)

R1: At startup, compute SHA-256 of registered authority modules and write advisory manifest.
Never blocks startup on error — wrap fully, log-and-continue pattern.

Design reference: designs/audit-drift-design.md v2 Part B (APPROVED)
"""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Dict

log = logging.getLogger(__name__)

# Authority Registry (same as authority_audit.py)
AUTHORITY_REGISTRY = {
    "name_normalization.py": {
        "role": "Name normalization authority",
        "path": "app/services/name_normalization.py"
    },
    "dhl_followup_status_projector.py": {
        "role": "DHL followup status projection authority",
        "path": "app/services/dhl_followup_status_projector.py"
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


def generate_startup_authority_manifest(storage_root: Path) -> Dict[str, Any]:
    """Generate SHA-256 manifest of authority module files at startup.

    Args:
        storage_root: Path to storage directory where manifest will be written

    Returns:
        Manifest dict with module hashes and metadata

    Raises:
        Exception: If critical error occurs (caller should catch and log-warn)
    """
    service_root = Path(__file__).parent.parent.parent  # Go up to service root

    manifest = {
        "format_version": "1.0",
        "generated_by": "authority_startup.py",
        "generated_at_startup": True,
        "modules": {}
    }

    for module_name, config in AUTHORITY_REGISTRY.items():
        module_path = service_root / config["path"]

        if module_path.exists():
            try:
                content = module_path.read_text(encoding="utf-8")
                sha256_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

                manifest["modules"][module_name] = {
                    "path": config["path"],
                    "role": config["role"],
                    "sha256": sha256_hash,
                    "size_bytes": len(content.encode("utf-8"))
                }

                log.debug("Authority module hashed: %s -> %s", module_name, sha256_hash[:8] + "...")

            except Exception as e:
                log.warning("Failed to hash authority module %s: %s", module_name, e)
                manifest["modules"][module_name] = {
                    "path": config["path"],
                    "role": config["role"],
                    "error": str(e)
                }
        else:
            log.warning("Authority module file not found: %s", module_path)
            manifest["modules"][module_name] = {
                "path": config["path"],
                "role": config["role"],
                "error": "File not found"
            }

    # Write manifest to storage
    manifest_path = storage_root / "authority_manifest.json"

    try:
        manifest_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8"
        )
        log.debug("Authority manifest written to: %s", manifest_path)
    except Exception as e:
        log.warning("Failed to write authority manifest to %s: %s", manifest_path, e)
        # Don't raise - this is advisory only

    return manifest