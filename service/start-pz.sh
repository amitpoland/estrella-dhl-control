#!/bin/bash
# ── PZ Service — start script ─────────────────────────────────────────────────
# Usage: bash start-pz.sh
# Stops any old instance, starts fresh, waits for health check.

set -euo pipefail

SERVICE_DIR="/Users/amitgupta/Downloads/CLI/service"
PYTHON="/usr/bin/python3"
LOG="/tmp/pz_service.log"
PID_FILE="/tmp/pz_service.pid"
PORT=8000
HEALTH_URL="http://localhost:${PORT}/api/v1/health"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " Estrella PZ Service — startup"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# ── Stop existing instance ────────────────────────────────────────────────────
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "🛑 Stopping old instance (PID $OLD_PID)..."
        kill "$OLD_PID" 2>/dev/null || true
        sleep 1
    fi
    rm -f "$PID_FILE"
fi
pkill -f "uvicorn app.main:app" 2>/dev/null || true
sleep 1

# ── Start server ──────────────────────────────────────────────────────────────
echo "🚀 Starting FastAPI on port ${PORT}..."
cd "$SERVICE_DIR"
"$PYTHON" -m uvicorn app.main:app \
    --host 0.0.0.0 \
    --port "$PORT" \
    --log-level info \
    >> "$LOG" 2>&1 &

SERVER_PID=$!
echo "$SERVER_PID" > "$PID_FILE"
echo "   PID: $SERVER_PID  |  Log: $LOG"

# ── Wait for health check ─────────────────────────────────────────────────────
echo -n "   Waiting for health check"
for i in $(seq 1 15); do
    sleep 1
    echo -n "."
    STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$HEALTH_URL" 2>/dev/null || echo "000")
    if [ "$STATUS" = "200" ]; then
        echo " OK"
        break
    fi
    if [ "$i" = "15" ]; then
        echo " TIMED OUT"
        echo "   Check logs: tail -50 $LOG"
        exit 1
    fi
done

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " PZ Service is running"
echo "   Local:  http://localhost:${PORT}/api/v1/health"
echo "   Public: https://pz.estrellajewels.eu/api/v1/health"
echo "   Dash:   https://pz.estrellajewels.eu/dashboard"
echo "   Log:    tail -f ${LOG}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
