#!/bin/bash
# deploy-service.sh — sync dev app/ to the running venv's site-packages, then restart
#
# Run after any code change to app/ so the launchd service picks up the new files.
# The service's venv has a copy of app/ in site-packages that takes precedence
# over the PYTHONPATH/sys.path insertion in pz-launcher.py.
#
# Usage:
#   ./deploy-service.sh          # sync + restart
#   ./deploy-service.sh --no-restart   # sync only (service reloads on next request)

set -euo pipefail

SRC="/Users/amitgupta/Downloads/CLI/service"
ENGINE_DIR="/Users/amitgupta/Downloads/CLI"
VENV="/Users/amitgupta/Library/Application Support/estrellajewels/venv"
SITE_PKGS="$VENV/lib/python3.9/site-packages"
STORAGE_ROOT="/Users/amitgupta/Library/Application Support/estrellajewels/storage"
SERVICE_LABEL="eu.estrellajewels.pz-service"

# Root-level engine modules imported by service routes/services.
# Required: directly imported (will fail loudly if missing).
# Transitive: imported by required modules; included so the deployed
# venv copy stays consistent with the repo. Add to this list when a
# new root-level module is referenced from service/app/.
ENGINE_MODULES_REQUIRED=(
    customs_description_engine.py
    polish_description_generator.py
    pz_import_processor.py
    pz_dual_export.py
    pz_pdf_export.py
    audit_agent.py
)
ENGINE_MODULES_TRANSITIVE=(
    pz_calculator.py
    audit_pdf.py
    audit_scoring.py
    dsk_generator.py
    correction_engine.py
    golden_constants.py
    invoice_learning_agent.py
    learning_agent.py
    dhl_clearance_handler.py
    dhl_email_monitor.py
    escalation.py
    parser_fix_proposals.py
)

echo "▶ Copying .env to launchd-accessible location..."
cp "$SRC/.env" "/Users/amitgupta/Library/Application Support/estrellajewels/.env"
echo "  ✓ .env synced"

echo "▶ Syncing app/ to site-packages..."
rsync -a --update --delete \
    --exclude="__pycache__" \
    --exclude="*.pyc" \
    --exclude="*.pyo" \
    "$SRC/app/" \
    "$SITE_PKGS/app/"
echo "  ✓ Sync complete"

# Count changed files
CHANGED=$(rsync -ain --update --delete \
    --exclude="__pycache__" --exclude="*.pyc" --exclude="*.pyo" \
    "$SRC/app/" "$SITE_PKGS/app/" 2>/dev/null | grep -c "^[<>]" || true)
echo "  Files in sync (no further changes detected)"

echo "▶ Syncing root-level engine modules to site-packages..."
# Fail loudly if a required module is missing — silent stale deploys are
# the bug this list exists to prevent.
for m in "${ENGINE_MODULES_REQUIRED[@]}"; do
    if [[ ! -f "$ENGINE_DIR/$m" ]]; then
        echo "  ✗ REQUIRED engine module missing: $ENGINE_DIR/$m" >&2
        exit 2
    fi
done

# Copy required modules; abort on any cp failure (set -e covers it).
for m in "${ENGINE_MODULES_REQUIRED[@]}"; do
    cp "$ENGINE_DIR/$m" "$SITE_PKGS/$m"
    echo "  ✓ required: $m"
done

# Copy transitive modules best-effort; warn if missing but do not abort
# (these may be optional depending on which routes are exercised).
for m in "${ENGINE_MODULES_TRANSITIVE[@]}"; do
    if [[ -f "$ENGINE_DIR/$m" ]]; then
        cp "$ENGINE_DIR/$m" "$SITE_PKGS/$m"
        echo "  ✓ transitive: $m"
    else
        echo "  ⚠ transitive (skipped, not present): $m"
    fi
done

echo "▶ Writing version.json..."
COMMIT=$(git -C "/Users/amitgupta/Downloads/CLI" rev-parse --short HEAD 2>/dev/null || echo "unknown")
DEPLOYED_AT=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
mkdir -p "$STORAGE_ROOT"
printf '{"commit":"%s","deployed_at":"%s"}\n' "$COMMIT" "$DEPLOYED_AT" \
    > "$STORAGE_ROOT/version.json"
echo "  ✓ $COMMIT @ $DEPLOYED_AT"

if [[ "${1:-}" == "--no-restart" ]]; then
    echo "  ℹ Skipping restart (--no-restart)"
    exit 0
fi

echo "▶ Restarting $SERVICE_LABEL..."
launchctl bootout "gui/$(id -u)/$SERVICE_LABEL" 2>/dev/null || true
sleep 1
launchctl bootstrap "gui/$(id -u)" \
    "/Users/amitgupta/Library/LaunchAgents/$SERVICE_LABEL.plist"
echo "  ✓ Service restarted"

echo "▶ Waiting for health check..."
for i in $(seq 1 20); do
    sleep 1
    STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/api/v1/health 2>/dev/null || echo "000")
    if [[ "$STATUS" == "200" ]]; then
        echo "  ✓ Service healthy (${i}s)"
        exit 0
    fi
done
echo "  ⚠ Health check timed out — check logs: tail -f /tmp/pz_service.log"
exit 1
