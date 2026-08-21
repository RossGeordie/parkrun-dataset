#!/usr/bin/env bash
# cron_parkrun.sh — CT-307 parkrun scraper invoker (cron entry point)
# Usage: cron_parkrun.sh [mode]   mode default: new
# Loads /opt/ct307/.env, runs ALL enabled parks from the registry.
set -euo pipefail
cd /opt/ct307
MODE="${1:-new}"
set -a; . ./.env; set +a
mkdir -p /opt/ct307/logs
LOG="/opt/ct307/logs/cron_$(date +%Y%m%d_%H%M%S)_${MODE}.log"
echo "[$(date -Is)] cron_parkrun start mode=${MODE}"
/usr/bin/python3 -u /opt/ct307/parkrun_pipeline.py scrape --mode "${MODE}" 2>&1 | tee -a "${LOG}"
echo "[$(date -Is)] cron_parkrun done mode=${MODE}"
