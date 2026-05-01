#!/usr/bin/env bash
# verify.sh — PZ Import Processor gate script
# =============================================
# Runs the full required verification sequence before any live batch.
# Exit code 0 = all checks passed, safe to proceed.
# Exit code 1 = something failed — DO NOT generate a PZ until fixed.
#
# Usage:
#   ./verify.sh            # fast gate only (unit + format, no PDFs)
#   ./verify.sh --full     # fast gate + full golden PDF pipeline

set -euo pipefail

PYTHON="python3"
TEST="test_pz_regression.py"
FULL=0

for arg in "$@"; do
    [[ "$arg" == "--full" ]] && FULL=1
done

SEP="──────────────────────────────────────────────────────"

echo ""
echo "$SEP"
echo "  PZ Import Processor — pre-batch verification"
echo "$SEP"

# ── Step 1: fast gate (always runs) ──────────────────────────────────────────
echo ""
echo "  [1/2] Fast regression (unit + format, no PDFs)..."
echo ""
if $PYTHON "$TEST"; then
    echo ""
    echo "  ✅  Fast gate passed."
else
    echo ""
    echo "  ✗   Fast gate FAILED. Parser or formula regression detected."
    echo "      Do not process any live batch until this is fixed."
    echo "$SEP"
    echo ""
    exit 1
fi

# ── Step 2: full golden pipeline (opt-in via --full) ─────────────────────────
if [[ $FULL -eq 1 ]]; then
    echo ""
    echo "  [2/2] Full golden regression (PDF pipeline, shipment 039–044)..."
    echo ""
    if $PYTHON "$TEST" --e2e; then
        echo ""
        echo "  ✅  Full golden regression passed."
    else
        echo ""
        echo "  ✗   Full golden regression FAILED."
        echo "      End-to-end output has drifted from shipment 039–044 reference."
        echo "      Review failures above. Do not process any live batch until fixed."
        echo "$SEP"
        echo ""
        exit 1
    fi
else
    echo ""
    echo "  [2/2] Full golden regression — SKIPPED (use --full to run)"
fi

echo ""
echo "$SEP"
echo "  All checks passed. Safe to generate PZ for new batch."
echo "$SEP"
echo ""
echo "  Example:"
echo "    $PYTHON pz_import_processor.py \\"
echo "        --invoices ./new_batch/ \\"
echo "        --zc429    ./new_batch/ZC429_xxx_PL.pdf"
echo ""
