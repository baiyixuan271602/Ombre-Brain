#!/bin/sh
# Render wrapper for Ombre Brain.
# 1) restore buckets from GitHub snapshot
# 2) start background backup loop
# 3) hand over to the original entrypoint

export OMBRE_PORT="${PORT:-${OMBRE_PORT:-10000}}"
echo "[render-hook] OMBRE_PORT=$OMBRE_PORT"

echo "[render-hook] restoring buckets from backup..."
python3 /app/deploy_files/render_restore.py || true

echo "[render-hook] starting backup loop..."
python3 /app/deploy_files/render_backup_loop.py &

echo "[render-hook] handing over to entrypoint"
exec /app/entrypoint.sh
