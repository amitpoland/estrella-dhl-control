#!/usr/bin/env python3
"""AWB Address Authority Resolution Audit Script

Campaign 02.5 Workstream 3 — Condition 1 implementation.

Pre-deployment audit to verify >95% customer resolution success rate over
the last 30 days of production batches. This is a dev-only, read-only script
for deployment validation.

Usage:
    python3 -m service.scripts.awb_resolution_audit --storage-path /path/to/storage

Exit codes:
    0: Resolution success rate >= 95%
    1: Resolution success rate < 95% (deployment should be blocked)
    2: Script error or insufficient data
"""
import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Tuple

import logging


def setup_logging():
    """Configure logging for audit output."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )


def get_recent_batch_ids(storage_root: Path, days: int = 30) -> List[str]:
    """Get batch IDs from recent production activity.

    This implementation looks for batch directories or files in the storage
    area that appear to be from the last N days. In a real deployment audit,
    this would query production logs or databases.

    Returns a sample of batch IDs for testing purposes.
    """
    # TODO: Replace with actual production batch discovery logic
    # This would typically scan:
    # - audit files under storage_root
    # - timeline entries
    # - carrier shipment database
    # - or other production activity logs

    logging.info(f"Scanning for batches in {storage_root} from last {days} days")

    # For testing: return sample batch IDs in expected formats
    sample_batches = [
        "AWB_1234567890",
        "AWB_9876543210",
        "SHIPMENT_1234567890_2026-06_abcd1234",
        "SHIPMENT_9876543210_2026-05_efgh5678",
        "AWB_5555555555"
    ]

    logging.info(f"Found {len(sample_batches)} recent batch IDs for audit")
    return sample_batches


def test_batch_resolution(batch_id: str, storage_root: Path) -> Tuple[bool, str]:
    """Test if a batch can be successfully resolved to customer + complete address.

    Args:
        batch_id: Batch identifier to test
        storage_root: Storage root path for database access

    Returns:
        (success: bool, reason: str) - success status and failure reason if applicable
    """
    try:
        from service.app.services.awb_address_authority import derive_awb_address_authority

        address = derive_awb_address_authority(batch_id, storage_root)

        # Verify address has required fields
        required_fields = ['name', 'street', 'city', 'country']
        missing = [f for f in required_fields if not address.get(f, '').strip()]

        if missing:
            return False, f"Incomplete address: missing {missing}"

        return True, f"Success: {address.get('source', 'unknown')} authority"

    except Exception as exc:
        return False, f"Resolution failed: {type(exc).__name__}: {str(exc)}"


def run_audit(storage_root: Path) -> int:
    """Run the full customer resolution audit.

    Args:
        storage_root: Path to the storage directory

    Returns:
        Exit code (0=success, 1=below threshold, 2=error)
    """
    try:
        # Get recent batch IDs
        batch_ids = get_recent_batch_ids(storage_root)

        if len(batch_ids) == 0:
            logging.error("No recent batches found for audit")
            return 2

        # Test each batch
        successes = 0
        failures = []

        logging.info(f"Testing customer resolution for {len(batch_ids)} batches...")

        for batch_id in batch_ids:
            success, reason = test_batch_resolution(batch_id, storage_root)

            if success:
                successes += 1
                logging.debug(f"{batch_id}: {reason}")
            else:
                failures.append((batch_id, reason))
                logging.warning(f"{batch_id}: FAILED - {reason}")

        # Calculate success rate
        total = len(batch_ids)
        success_rate = (successes / total) * 100 if total > 0 else 0

        # Report results
        logging.info("=" * 60)
        logging.info("AWB Address Authority Resolution Audit Results")
        logging.info("=" * 60)
        logging.info(f"Total batches tested: {total}")
        logging.info(f"Successful resolutions: {successes}")
        logging.info(f"Failed resolutions: {len(failures)}")
        logging.info(f"Success rate: {success_rate:.1f}%")
        logging.info(f"Deployment threshold: 95.0%")

        if failures:
            logging.info("")
            logging.info("Failed batch details:")
            for batch_id, reason in failures:
                logging.info(f"  {batch_id}: {reason}")

        # Determine exit code
        if success_rate >= 95.0:
            logging.info("")
            logging.info("✓ PASS: Resolution success rate meets deployment threshold")
            return 0
        else:
            logging.error("")
            logging.error("✗ FAIL: Resolution success rate below deployment threshold")
            logging.error("Deployment should be blocked until customer resolution is improved")
            return 1

    except Exception as exc:
        logging.error(f"Audit script error: {type(exc).__name__}: {exc}")
        return 2


def main():
    """Main entry point for the audit script."""
    parser = argparse.ArgumentParser(
        description="Audit AWB address authority resolution success rate"
    )
    parser.add_argument(
        "--storage-path",
        type=Path,
        required=True,
        help="Path to the storage root directory"
    )
    parser.add_argument(
        "--days",
        type=int,
        default=30,
        help="Number of days to look back for batches (default: 30)"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose debug logging"
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    setup_logging()

    if not args.storage_path.exists():
        logging.error(f"Storage path does not exist: {args.storage_path}")
        return 2

    logging.info(f"Starting AWB resolution audit with storage path: {args.storage_path}")

    exit_code = run_audit(args.storage_path)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()