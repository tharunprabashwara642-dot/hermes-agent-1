#!/bin/bash
# Tharun AI Assistant — startup script
# - Seeds /opt/data/config.yaml from the example on first boot only,
#   so it never clobbers a config you've already customized.
# - Runs the agent in --serve mode.
# - If the Python process itself dies for any reason, it is restarted
#   automatically instead of letting the container exit — the agent loop's
#   own error-recovery already keeps individual tasks from crashing it,
#   this is just an extra outer safety net.

set -u  # (intentionally no `set -e`: we want to handle failures ourselves, not exit on them)

mkdir -p /opt/data

if [ ! -f /opt/data/config.yaml ]; then
  echo "[start.sh] No config.yaml found, seeding default config at /opt/data/config.yaml"
  cp /app/config.example.yaml /opt/data/config.yaml
fi

echo "[start.sh] Starting Tharun AI Assistant..."

while true; do
  python3 /app/main.py --serve
  exit_code=$?
  echo "[start.sh] Agent process exited with code $exit_code. Restarting in 5s..."
  sleep 5
done
