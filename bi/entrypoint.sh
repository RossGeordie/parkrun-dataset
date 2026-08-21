#!/bin/bash
set -euo pipefail
export SUPERSET_ENV=production
echo "[entrypoint] db upgrade..."
superset db upgrade
echo "[entrypoint] admin ensure..."
superset fab create-admin \
  --username admin \
  --firstname Admin \
  --lastname User \
  --email admin@parkrun.local \
  --password "${SUPERSET_ADMIN_PASSWORD:-change-me}" || echo "[entrypoint] admin exists, continuing"
echo "[entrypoint] seed parkrun datasource/charts if present..."
[ -f /app/seed_bi.py ] && (python /app/seed_bi.py || echo "[entrypoint] seed warn") || true
echo "[entrypoint] launching web server..."
exec superset run -h 0.0.0.0 -p 8088
