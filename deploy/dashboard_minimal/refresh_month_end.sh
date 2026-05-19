#!/usr/bin/env bash
set -euo pipefail

cd /opt/trex-dashboard
export PYTHONPATH=/opt/trex-dashboard/app/src

LOCK_FILE=/opt/trex-dashboard/.refresh.lock
TS=$(date -u +%Y%m%dT%H%M%SZ)
LOG=/opt/trex-dashboard/refresh-month-end-$TS.log
STATUS_FILE=/opt/trex-dashboard/data/dashboard/refresh_status.json
CURRENT_STEP="starting"
STARTED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "Another refresh is already running, skipping month-end job."
  exit 0
fi

write_status() {
  local status="$1"
  local message="$2"
  local finished_at
  finished_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  /opt/trex-dashboard/.venv/bin/python - "$STATUS_FILE" "$status" "$message" "$LOG" "$STARTED_AT" "$finished_at" "$CURRENT_STEP" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
path.parent.mkdir(parents=True, exist_ok=True)
payload = {
    "status": sys.argv[2],
    "message": sys.argv[3],
    "log_file": sys.argv[4],
    "started_at": sys.argv[5],
    "finished_at": sys.argv[6],
    "job_type": "month_end",
    "current_step": sys.argv[7],
}
path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
PY
}

on_error() {
  write_status "failed" "Ay sonu refresh basarisiz oldu: ${CURRENT_STEP}"
}

trap on_error ERR

cleanup_logs() {
  find /opt/trex-dashboard -maxdepth 1 -type f -name 'refresh-*.log' | sort | head -n -8 | xargs -r rm -f
}

run() {
  CURRENT_STEP="$*"
  echo "[$(date -u)] $*"
  "$@"
}

write_status "running" "Ay sonu refresh calisiyor."

{
  echo "[$(date -u)] month-end refresh start"
  run /opt/trex-dashboard/.venv/bin/python -m bist_factor_backtest.cli refresh-dashboard \
    --output-dir /opt/trex-dashboard/data/dashboard \
    --registry-file /opt/trex-dashboard/data/universe/bist_sanayi_investing_registry.csv
  cleanup_logs
  echo "[$(date -u)] month-end refresh done"
} >> "$LOG" 2>&1

write_status "success" "Ay sonu refresh basariyla tamamlandi."
