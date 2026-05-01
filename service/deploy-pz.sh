#!/bin/bash
# ── PZ Service — deploy script ────────────────────────────────────────────────
# Syncs updated code from Downloads/CLI into the Library/Application Support
# location used by the launchd auto-start agent, then restarts the agent.
#
# Usage:
#   bash deploy-pz.sh          # sync + restart launchd agent
#   bash deploy-pz.sh --no-restart  # sync only, no restart

set -euo pipefail

SRC_APP="/Users/amitgupta/Downloads/CLI/service/app"
SRC_ENV="/Users/amitgupta/Downloads/CLI/service/.env"
SRC_ENGINE_DIR="/Users/amitgupta/Downloads/CLI"
DEST_BASE="/Users/amitgupta/Library/Application Support/estrellajewels"
VENV_SITE="${DEST_BASE}/venv/lib/python3.9/site-packages"
PLIST="/Users/amitgupta/Library/LaunchAgents/eu.estrellajewels.pz-service.plist"

NO_RESTART=false
if [[ "${1:-}" == "--no-restart" ]]; then NO_RESTART=true; fi

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " PZ Service — deploy"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# ── 1. Sync app package ───────────────────────────────────────────────────────
echo "📦 Syncing app package..."
rsync -a --delete "${SRC_APP}/" "${VENV_SITE}/app/"
echo "   ✓ app/ → ${VENV_SITE}/app/"

# ── 2. Sync .env ──────────────────────────────────────────────────────────────
echo "🔑 Syncing .env..."
cp "${SRC_ENV}" "${DEST_BASE}/.env"
echo "   ✓ .env synced"

# ── 3. Ensure storage dir exists in TCC-safe location ────────────────────────
STORAGE_SRC="${SRC_APP}/storage"
STORAGE_DEST="${DEST_BASE}/storage"
if [ -d "${STORAGE_SRC}" ] && [ ! -d "${STORAGE_DEST}" ]; then
    rsync -a "${STORAGE_SRC}/" "${STORAGE_DEST}/"
    echo "   ✓ storage/ initialised → ${STORAGE_DEST}"
else
    mkdir -p "${STORAGE_DEST}/outputs" "${STORAGE_DEST}/incoming" "${STORAGE_DEST}/working"
fi

# ── 4. Sync engine files ──────────────────────────────────────────────────────
echo "⚙️  Syncing engine files..."
for f in pz_import_processor.py pz_pdf_export.py pz_dual_export.py golden_constants.py audit_agent.py audit_pdf.py audit_scoring.py correction_engine.py learning_agent.py escalation.py pz_calculator.py; do
    if [ -f "${SRC_ENGINE_DIR}/${f}" ]; then
        cp "${SRC_ENGINE_DIR}/${f}" "${VENV_SITE}/${f}"
        echo "   ✓ ${f}"
    else
        echo "   ⚠ ${f} — not found in source, skipping"
    fi
done

# ── 5. Restart launchd agent ──────────────────────────────────────────────────
if $NO_RESTART; then
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo " Sync complete (no restart requested)"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    exit 0
fi

echo "🔄 Restarting launchd agent..."
launchctl unload "${PLIST}" 2>/dev/null || true
sleep 1
launchctl load "${PLIST}"

# ── 6. Health check ───────────────────────────────────────────────────────────
echo -n "   Waiting for health check"
for i in $(seq 1 20); do
    sleep 1
    echo -n "."
    STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/api/v1/health 2>/dev/null || echo "000")
    if [ "$STATUS" = "200" ]; then
        echo " OK"
        break
    fi
    if [ "$i" = "20" ]; then
        echo " TIMED OUT"
        echo "   Check: tail -30 /tmp/pz_service.log"
        exit 1
    fi
done

HEALTH=$(curl -s http://localhost:8000/api/v1/health)
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " PZ Service deployed"
echo "   Health: ${HEALTH}"
echo "   Log:    tail -f /tmp/pz_service.log"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
