#!/usr/bin/env python3
"""
authority_audit.py — Standalone Authority Audit Tool (Campaign 02.5 Part A)

Standalone CLI for authority module integrity checks:
- Authority inventory (4-module registry with roles)
- Bypass detection (forbidden imports, coupling violations)
- Duplicate-authority detection (orphaned implementations)
- Consumer validation (proper wiring to authority modules)
- CI-friendly report (structured JSON, non-zero exit on violation)
- Pinned manifest generation (--write-manifest for reviewable diffs)

Usage:
    python authority_audit.py                    # Run audit, report violations
    python authority_audit.py --write-manifest  # Regenerate pinned manifest

Exit codes:
    0 = No violations found
    1 = Authority violations detected
    2 = Script error (missing files, etc.)

Design reference: designs/audit-drift-design.md v2 (APPROVED)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


# Authority Registry (4 modules per approved design)
AUTHORITY_REGISTRY = {
    "name_normalization.py": {
        "role": "Name normalization authority",
        "path": "app/services/name_normalization.py",
        "public_functions": [
            "packing_contractor_normalise_name",
            "proforma_normalize_client_name",
            "customer_resolution_normalize_name",
            "suppliers_db_normalise_name",
            "wfirma_auto_resolve_normalise_name",
            "master_data_normalise_name",
            "wfirma_sync_normalise_name"
        ],
        "forbidden_imports": ["smtplib", "email_service", "queue_email", "requests", "routes_"],
        "consumers": [
            "packing_contractor_resolver.py",
            "customer_resolution_authority.py",
            "routes_proforma.py",  # Uses delegates
            "customer_master_db.py",
            "suppliers_db.py"
        ]
    },
    "dhl_followup_status_projector.py": {
        "role": "DHL followup status projection authority",
        "path": "app/services/dhl_followup_status_projector.py",
        "public_functions": [
            "project_automation_status",
            "project_shipment_rows"
        ],
        "forbidden_imports": ["smtplib", "email_service", "queue_email", "requests"],
        "consumers": [
            "routes_dhl_followup_status.py"  # The main consumer of DHL projections
        ]
    },
    "awb_address_authority.py": {
        "role": "AWB address resolution authority",
        "path": "app/services/awb_address_authority.py",
        "public_functions": [
            "derive_awb_address_authority_with_fallback"
        ],
        "forbidden_imports": ["smtplib", "email_service", "queue_email", "requests"],
        "consumers": [
            "routes_carrier_actions.py"  # Primary AWB address consumer
        ]
    },
    "tracking_db.py": {
        "role": "Tracking deduplication authority",
        "path": "app/services/tracking_db.py",
        "public_functions": [
            "record_event",  # Contains the dedup logic
            "get_events_for_batch"
        ],
        "forbidden_imports": ["smtplib", "email_service", "queue_email", "requests"],
        "consumers": [
            "routes_carrier_webhook.py"  # Webhook consumer of tracking events
        ],
        "dedup_columns": [
            "batch_id", "awb", "stage", "event_time",
            "source_ref", "email_message_id", "direction"
        ]
    }
}


class AuthorityAuditor:
    """Authority module integrity auditor."""

    def __init__(self, service_root: Path):
        self.service_root = Path(service_root)
        self.violations: List[Dict[str, Any]] = []

    def audit_all(self) -> Dict[str, Any]:
        """Run complete authority audit suite."""
        print("Running authority audit...")

        # Registry integrity
        missing_modules = self._audit_registry_integrity()

        # Bypass detection
        purity_violations = self._audit_purity_isolation()

        # Duplicate authority detection
        duplicate_violations = self._audit_duplicate_implementations()

        # Consumer validation
        consumer_violations = self._audit_consumer_wiring()

        # Dedup contract validation
        dedup_violations = self._audit_dedup_contracts()

        total_violations = (
            len(missing_modules) + len(purity_violations) +
            len(duplicate_violations) + len(consumer_violations) +
            len(dedup_violations)
        )

        report = {
            "status": "PASS" if total_violations == 0 else "FAIL",
            "total_violations": total_violations,
            "registry_integrity": {
                "status": "PASS" if len(missing_modules) == 0 else "FAIL",
                "missing_modules": missing_modules
            },
            "purity_isolation": {
                "status": "PASS" if len(purity_violations) == 0 else "FAIL",
                "violations": purity_violations
            },
            "duplicate_detection": {
                "status": "PASS" if len(duplicate_violations) == 0 else "FAIL",
                "violations": duplicate_violations
            },
            "consumer_validation": {
                "status": "PASS" if len(consumer_violations) == 0 else "FAIL",
                "violations": consumer_violations
            },
            "dedup_contracts": {
                "status": "PASS" if len(dedup_violations) == 0 else "FAIL",
                "violations": dedup_violations
            }
        }

        return report

    def _audit_registry_integrity(self) -> List[str]:
        """Check that all registered authority modules exist."""
        print("  Checking registry integrity...")
        missing = []

        for module_name, config in AUTHORITY_REGISTRY.items():
            module_path = self.service_root / config["path"]
            if not module_path.exists():
                missing.append(f"Missing authority module: {module_path} ({config['role']})")

        return missing

    def _audit_purity_isolation(self) -> List[str]:
        """Check that authority modules don't import forbidden dependencies."""
        print("  Checking purity isolation...")
        violations = []

        for module_name, config in AUTHORITY_REGISTRY.items():
            module_path = self.service_root / config["path"]
            if not module_path.exists():
                continue

            try:
                content = module_path.read_text(encoding="utf-8")

                for forbidden in config["forbidden_imports"]:
                    if self._contains_import(content, forbidden):
                        violations.append(
                            f"{module_name}: forbidden import '{forbidden}' violates Lesson E isolation"
                        )
            except Exception as e:
                violations.append(f"{module_name}: could not read file - {e}")

        return violations

    def _contains_import(self, content: str, forbidden_pattern: str) -> bool:
        """Check if content contains a forbidden import pattern."""
        lines = content.split('\n')
        for line in lines:
            line = line.strip()
            if (line.startswith(f'import {forbidden_pattern}') or
                line.startswith(f'from {forbidden_pattern}') or
                f'import {forbidden_pattern}' in line or
                f'from {forbidden_pattern}' in line):
                return True
        return False

    def _audit_duplicate_implementations(self) -> List[str]:
        """Check for duplicate authority implementations outside registry."""
        print("  Checking duplicate implementations...")
        violations = []

        # Check for duplicate str.maketrans tables with diacritic keys
        diacritic_keys = ["ł", "Ł", "ø", "Ø", "æ", "Æ", "å", "Å", "ß", "þ", "Þ", "ð", "Ð"]

        for py_file in (self.service_root / "app").rglob("*.py"):
            if py_file.name == "name_normalization.py":
                continue

            try:
                content = py_file.read_text(encoding="utf-8")
                if "str.maketrans" in content:
                    for key in diacritic_keys:
                        if key in content:
                            violations.append(
                                f"{py_file.relative_to(self.service_root)}: "
                                f"duplicate str.maketrans with diacritic key '{key}'"
                            )
                            break
            except Exception:
                pass

        # Check for legacy normalization function definitions
        legacy_functions = [
            "_normalize_name", "_normalize_client_name",
            "normalise_name", "normalise_client_name", "_norm"
        ]

        # Known allowed delegates (one-line functions that call authority)
        allowed_delegates = {
            "packing_contractor_resolver.py",
            "customer_resolution_authority.py",
            "proforma_draft_builder.py",
            "wfirma_auto_resolve.py",
            "customer_master_db.py",
            "suppliers_db.py",
            "wfirma_sync_v2.py",
            "routes_proforma.py",
            "agency_sad_decision.py",
            "master_data_intelligence.py",
            "sales_linkage.py",
            "wfirma_customer_auto_resolve.py",
            "wfirma_customer_sync.py",
            "wfirma_reservation.py"
        }

        for py_file in (self.service_root / "app").rglob("*.py"):
            if py_file.name in ["name_normalization.py"] + list(allowed_delegates):
                continue

            try:
                content = py_file.read_text(encoding="utf-8")
                for func in legacy_functions:
                    if f"def {func}(" in content:
                        violations.append(
                            f"{py_file.relative_to(self.service_root)}: "
                            f"duplicate normalization function '{func}'"
                        )
            except Exception:
                pass

        return violations

    def _audit_consumer_wiring(self) -> List[str]:
        """Check that consumers properly wire to authority modules."""
        print("  Checking consumer wiring...")
        violations = []

        for module_name, config in AUTHORITY_REGISTRY.items():
            authority_path = self.service_root / config["path"]
            if not authority_path.exists():
                continue

            # Check that declared consumers actually import the authority
            for consumer_file in config.get("consumers", []):
                consumer_path = None

                # Try different possible locations for consumer
                possible_paths = [
                    self.service_root / "app" / "api" / consumer_file,
                    self.service_root / "app" / "services" / consumer_file,
                    self.service_root / "app" / consumer_file
                ]

                for path in possible_paths:
                    if path.exists():
                        consumer_path = path
                        break

                if not consumer_path:
                    violations.append(
                        f"{module_name}: declared consumer '{consumer_file}' not found"
                    )
                    continue

                try:
                    content = consumer_path.read_text(encoding="utf-8")
                    authority_module = module_name.replace('.py', '')

                    # Check for import of authority module (including conditional imports)
                    import_patterns = [
                        f"from ..services import {authority_module}",
                        f"from app.services import {authority_module}",
                        f"import {authority_module}",
                        f"from ..services.{authority_module} import",  # Conditional import
                        f"from app.services.{authority_module} import"
                    ]

                    has_import = any(pattern in content for pattern in import_patterns)
                    if not has_import:
                        violations.append(
                            f"{consumer_file}: missing import of authority module '{authority_module}'"
                        )

                except Exception:
                    violations.append(
                        f"{consumer_file}: could not validate wiring to '{module_name}'"
                    )

        return violations

    def _audit_dedup_contracts(self) -> List[str]:
        """Check tracking deduplication SQL contracts."""
        print("  Checking dedup contracts...")
        violations = []

        # Special handling for tracking_db.py dedup contract
        if "tracking_db.py" in AUTHORITY_REGISTRY:
            config = AUTHORITY_REGISTRY["tracking_db.py"]
            tracking_path = self.service_root / config["path"]

            if tracking_path.exists():
                try:
                    content = tracking_path.read_text(encoding="utf-8")

                    required_columns = config.get("dedup_columns", [])
                    missing_columns = []

                    for col in required_columns:
                        # Look for SQL WHERE clause patterns (including without spaces)
                        if not (f"{col}=?" in content or f"{col} = ?" in content or f"{col} IS ?" in content):
                            missing_columns.append(col)

                    if missing_columns:
                        violations.append(
                            f"tracking_db.py: missing dedup columns in SQL: {missing_columns}"
                        )

                except Exception as e:
                    violations.append(f"tracking_db.py: could not validate dedup contract - {e}")

        return violations

    def generate_pinned_manifest(self) -> Dict[str, Any]:
        """Generate SHA-256 manifest of authority module files."""
        print("Generating authority manifest...")

        manifest = {
            "format_version": "1.0",
            "generated_by": "authority_audit.py",
            "modules": {}
        }

        for module_name, config in AUTHORITY_REGISTRY.items():
            module_path = self.service_root / config["path"]

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
                except Exception as e:
                    manifest["modules"][module_name] = {
                        "path": config["path"],
                        "role": config["role"],
                        "error": str(e)
                    }
            else:
                manifest["modules"][module_name] = {
                    "path": config["path"],
                    "role": config["role"],
                    "error": "File not found"
                }

        return manifest


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Authority module integrity audit tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python authority_audit.py                    # Run audit
  python authority_audit.py --write-manifest  # Regenerate manifest

Exit codes:
  0 = No violations
  1 = Authority violations detected
  2 = Script error
        """
    )

    parser.add_argument(
        "--write-manifest",
        action="store_true",
        help="Regenerate pinned manifest file (service/app/authority_manifest_pinned.json)"
    )

    parser.add_argument(
        "--service-root",
        type=Path,
        default=Path(__file__).parent.parent,
        help="Path to service root directory (default: ../)"
    )

    args = parser.parse_args()

    try:
        auditor = AuthorityAuditor(args.service_root)

        if args.write_manifest:
            # Generate and write pinned manifest
            manifest = auditor.generate_pinned_manifest()
            manifest_path = args.service_root / "app" / "authority_manifest_pinned.json"

            manifest_path.write_text(
                json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8"
            )

            print(f"Pinned manifest written to: {manifest_path}")

            # Also print summary
            module_count = len([m for m in manifest["modules"].values() if "sha256" in m])
            error_count = len([m for m in manifest["modules"].values() if "error" in m])

            print(f"Manifest summary: {module_count} modules hashed, {error_count} errors")

            return 0

        else:
            # Run audit
            report = auditor.audit_all()

            # Print human-readable summary
            if report["status"] == "PASS":
                print("Authority audit: PASS")
                print(f"   Registry: {len(AUTHORITY_REGISTRY)} modules validated")
                print("   Purity: No forbidden imports")
                print("   Duplicates: No orphaned implementations")
                print("   Consumers: All properly wired")
                print("   Contracts: All dedup constraints satisfied")
                return 0
            else:
                print(f"Authority audit: FAIL ({report['total_violations']} violations)")

                # Print violations by category
                for category, details in report.items():
                    if category in ["status", "total_violations"]:
                        continue

                    if details["status"] == "FAIL":
                        print(f"\n{category}:")

                        if category == "registry_integrity":
                            for violation in details["missing_modules"]:
                                print(f"   - {violation}")
                        else:
                            for violation in details.get("violations", []):
                                print(f"   - {violation}")

                # Print structured JSON for CI tools
                print("\n" + "="*60)
                print("STRUCTURED REPORT (for CI tools):")
                print(json.dumps(report, indent=2))

                return 1

    except Exception as e:
        print(f"Script error: {e}")
        return 2


if __name__ == "__main__":
    sys.exit(main())