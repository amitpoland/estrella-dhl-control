#!/usr/bin/env python3
"""
extract_name_corpus.py — Dev-only script to extract real contractor/customer/supplier names
from local SQLite stores into a JSON corpus for name normalization testing.

Read-only script — NEVER writes to the database stores.
The output corpus stays LOCAL (not committed) to avoid PII exposure.

Usage:
    python service/scripts/extract_name_corpus.py

Output:
    - Summary statistics printed to stdout
    - JSON corpus written to service/scripts/name_corpus_extracted.json (git-ignored)
    - Parity divergences reported if any found
"""
import json
import sqlite3
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple

# Add the service directory to Python path to import the name normalization functions
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from app.services import name_normalization
except ImportError:
    print("ERROR: Could not import name_normalization module")
    print("Make sure you're running from the service directory")
    sys.exit(1)

# Storage paths (read-only)
STORAGE_ROOT = Path(__file__).parent.parent.parent / "storage"
CUSTOMER_MASTER_DB = STORAGE_ROOT / "customer_master.sqlite"
SUPPLIERS_DB = STORAGE_ROOT / "suppliers.sqlite"
WFIRMA_CUSTOMERS_DB = STORAGE_ROOT / "wfirma_customers.sqlite"
PACKING_RESOLUTIONS_DB = STORAGE_ROOT / "packing_resolutions.sqlite"

# Output file
OUTPUT_FILE = Path(__file__).parent / "name_corpus_extracted.json"


def extract_customer_names() -> Set[str]:
    """Extract customer names from customer_master.sqlite."""
    names = set()
    if not CUSTOMER_MASTER_DB.exists():
        print(f"INFO: {CUSTOMER_MASTER_DB} does not exist, skipping customer names")
        return names

    try:
        with sqlite3.connect(CUSTOMER_MASTER_DB) as conn:
            cursor = conn.execute("SELECT bill_to_name, ship_to_name FROM customers WHERE bill_to_name IS NOT NULL OR ship_to_name IS NOT NULL")
            for row in cursor.fetchall():
                bill_to, ship_to = row
                if bill_to and bill_to.strip():
                    names.add(bill_to.strip())
                if ship_to and ship_to.strip():
                    names.add(ship_to.strip())
    except Exception as e:
        print(f"WARNING: Could not extract customer names: {e}")

    return names


def extract_supplier_names() -> Set[str]:
    """Extract supplier names from suppliers.sqlite."""
    names = set()
    if not SUPPLIERS_DB.exists():
        print(f"INFO: {SUPPLIERS_DB} does not exist, skipping supplier names")
        return names

    try:
        with sqlite3.connect(SUPPLIERS_DB) as conn:
            cursor = conn.execute("SELECT name FROM suppliers WHERE name IS NOT NULL")
            for row in cursor.fetchall():
                name = row[0]
                if name and name.strip():
                    names.add(name.strip())
    except Exception as e:
        print(f"WARNING: Could not extract supplier names: {e}")

    return names


def extract_wfirma_customer_names() -> Set[str]:
    """Extract wFirma customer names from wfirma_customers.sqlite."""
    names = set()
    if not WFIRMA_CUSTOMERS_DB.exists():
        print(f"INFO: {WFIRMA_CUSTOMERS_DB} does not exist, skipping wFirma customer names")
        return names

    try:
        with sqlite3.connect(WFIRMA_CUSTOMERS_DB) as conn:
            cursor = conn.execute("SELECT client_name FROM wfirma_customers WHERE client_name IS NOT NULL")
            for row in cursor.fetchall():
                name = row[0]
                if name and name.strip():
                    names.add(name.strip())
    except Exception as e:
        print(f"WARNING: Could not extract wFirma customer names: {e}")

    return names


def extract_contractor_names() -> Set[str]:
    """Extract contractor names from packing_resolutions.sqlite."""
    names = set()
    if not PACKING_RESOLUTIONS_DB.exists():
        print(f"INFO: {PACKING_RESOLUTIONS_DB} does not exist, skipping contractor names")
        return names

    try:
        with sqlite3.connect(PACKING_RESOLUTIONS_DB) as conn:
            cursor = conn.execute("SELECT contractor_name FROM packing_contractor_resolution WHERE contractor_name IS NOT NULL")
            for row in cursor.fetchall():
                name = row[0]
                if name and name.strip():
                    names.add(name.strip())
    except Exception as e:
        print(f"WARNING: Could not extract contractor names: {e}")

    return names


def check_normalization_parity(names: List[str]) -> Tuple[int, List[Dict]]:
    """
    Run all seven normalization functions over the corpus and check for parity.

    Returns:
        (divergence_count, divergence_list)
    """
    divergences = []

    for name in names:
        try:
            # Run all seven functions
            results = {
                'customer_resolution': name_normalization.customer_resolution_normalize_name(name),
                'proforma': name_normalization.proforma_normalize_client_name(name),
                'suppliers_db': name_normalization.suppliers_db_normalize_name(name),
                'wfirma_auto_resolve': name_normalization.wfirma_auto_resolve_normalize_name(name),
                'master_data': name_normalization.master_data_norm(name),
                'packing_contractor': name_normalization.packing_contractor_normalise_name(name),
                'wfirma_sync': name_normalization.wfirma_sync_normalise_client_name(name),
            }

            # Check for interesting divergences (different outputs)
            unique_outputs = set(results.values())
            if len(unique_outputs) > 1:
                divergences.append({
                    'input': name,
                    'outputs': results,
                    'unique_count': len(unique_outputs)
                })
        except Exception as e:
            divergences.append({
                'input': name,
                'error': str(e),
                'unique_count': -1
            })

    return len(divergences), divergences


def main():
    """Extract names and generate corpus."""
    print("Extracting names from local SQLite stores...")
    print(f"Storage root: {STORAGE_ROOT}")

    # Extract from all sources
    customer_names = extract_customer_names()
    supplier_names = extract_supplier_names()
    wfirma_names = extract_wfirma_customer_names()
    contractor_names = extract_contractor_names()

    # Combine all names
    all_names = customer_names | supplier_names | wfirma_names | contractor_names
    name_list = sorted(list(all_names))

    # Statistics
    print(f"\nExtraction Summary:")
    print(f"  Customer Master names:   {len(customer_names)}")
    print(f"  Supplier names:          {len(supplier_names)}")
    print(f"  wFirma customer names:   {len(wfirma_names)}")
    print(f"  Contractor names:        {len(contractor_names)}")
    print(f"  Total unique names:      {len(all_names)}")

    if not all_names:
        print("\nWARNING: No names found in any database. Check that:")
        print("  1. You're running from a worktree with local storage")
        print("  2. The SQLite files exist and contain data")
        print("  3. Table schemas match expected structure")
        return

    # Check normalization parity
    print(f"\nRunning parity analysis over {len(name_list)} names...")
    divergence_count, divergences = check_normalization_parity(name_list)

    print(f"  Normalization divergences: {divergence_count}")
    if divergence_count > 0:
        print(f"  First 5 divergences:")
        for i, div in enumerate(divergences[:5]):
            if 'error' in div:
                print(f"    {i+1}. ERROR on '{div['input']}': {div['error']}")
            else:
                print(f"    {i+1}. '{div['input']}' -> {div['unique_count']} unique outputs")
                for func, output in div['outputs'].items():
                    print(f"        {func}: '{output}'")

    # Build corpus
    corpus = {
        'metadata': {
            'extracted_at': str(Path(__file__).stat().st_mtime),
            'source_counts': {
                'customer_master': len(customer_names),
                'suppliers': len(supplier_names),
                'wfirma_customers': len(wfirma_names),
                'contractors': len(contractor_names),
                'total_unique': len(all_names)
            },
            'normalization_divergences': divergence_count
        },
        'names': name_list,
        'divergences': divergences if divergence_count <= 20 else divergences[:20]  # Cap for file size
    }

    # Write corpus (LOCAL only, not committed)
    try:
        with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
            json.dump(corpus, f, indent=2, ensure_ascii=False)
        print(f"\nCorpus written to: {OUTPUT_FILE}")
        print(f"File size: {OUTPUT_FILE.stat().st_size:,} bytes")
        print("\nNOTE: This file is LOCAL only and should NOT be committed (contains PII)")
    except Exception as e:
        print(f"\nERROR: Could not write corpus file: {e}")
        return

    # Summary
    if divergence_count == 0:
        print(f"\n✓ SUCCESS: All {len(name_list)} names produced consistent normalization results")
    else:
        print(f"\n⚠  PARTIAL: {divergence_count} names showed normalization divergences")
        print("   This is expected given the different normalization behaviors")
        print("   Check divergences for any unexpected patterns")


if __name__ == "__main__":
    main()