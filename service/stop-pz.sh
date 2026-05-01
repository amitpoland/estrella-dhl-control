#!/bin/bash
# ── PZ Service — stop script ──────────────────────────────────────────────────
# Usage: bash stop-pz.sh

PID_FILE="/tmp/pz_service.pid"

if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if kill -0 "$PID" 2>/dev/null; then
        echo "Stopping PZ Service (PID $PID)..."
        kill "$PID"
        rm -f "$PID_FILE"
        echo "Stopped."
    else
        echo "PID $PID not running. Cleaning up."
        rm -f "$PID_FILE"
    fi
else
    pkill -f "uvicorn app.main:app" 2>/dev/null && echo "Stopped." || echo "PZ Service was not running."
fi
