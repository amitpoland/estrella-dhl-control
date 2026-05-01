#!/bin/bash
# launchd-wrapper.sh — called by launchd, spawns uvicorn in a clean shell context
# This bypasses the Aqua-session C-extension sandbox restriction.

export HOME="/Users/amitgupta"
export PATH="/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

cd /Users/amitgupta/Downloads/CLI/service

exec /usr/bin/python3 -m uvicorn app.main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --log-level info
