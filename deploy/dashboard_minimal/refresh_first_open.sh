#!/usr/bin/env bash
set -euo pipefail

cd /opt/trex-dashboard
export PYTHONPATH=/opt/trex-dashboard/app/src

LOCK_FILE=/opt/trex-dashboard/.refresh.lock
TS=$(date -u +%Y%m%dT%H%M%SZ)
LOG=/opt/trex-dashboard/refresh-first-open-$TS.log
STATUS_FILE=/opt/trex-dashboard/data/dashboard/refresh_status.json
STATE_FILE=/opt/trex-dashboard/data/dashboard/month_start_refresh_state.json
CURRENT_STEP="starting"
STARTED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "Another refresh is already running, skipping first-open job."
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
    "job_type": "first_open",
    "current_step": sys.argv[7],
}
path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
PY
}

current_month_local() {
  TZ=Europe/Istanbul date +%Y-%m
}

already_completed_month() {
  local current_month
  current_month="$(current_month_local)"
  /opt/trex-dashboard/.venv/bin/python - "$STATE_FILE" "$current_month" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
current_month = sys.argv[2]
if not path.exists():
    print("no")
    raise SystemExit(0)
try:
    payload = json.loads(path.read_text(encoding="utf-8"))
except Exception:
    print("no")
    raise SystemExit(0)
print("yes" if payload.get("last_completed_month") == current_month else "no")
PY
}

mark_completed_month() {
  local current_month
  current_month="$(current_month_local)"
  /opt/trex-dashboard/.venv/bin/python - "$STATE_FILE" "$current_month" <<'PY'
import json
import sys
from datetime import datetime, UTC
from pathlib import Path

path = Path(sys.argv[1])
path.parent.mkdir(parents=True, exist_ok=True)
payload = {
    "last_completed_month": sys.argv[2],
    "updated_at": datetime.now(UTC).isoformat(),
}
path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
PY
}

on_error() {
  write_status "failed" "Ilk acilis gunu refresh basarisiz oldu: ${CURRENT_STEP}"
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

write_status "running" "Ay basi sabah refresh calisiyor."

{
  echo "[$(date -u)] month-start refresh start"
  if [ "$(already_completed_month)" = "yes" ]; then
    echo "[$(date -u)] current month already refreshed, skipping duplicate run"
    cleanup_logs
    write_status "skipped" "Bu ay icin sabah refresh zaten tamamlanmis, tekrar calistirilmadi."
    exit 0
  fi
  TRADE_DATE=$(TZ=Europe/Istanbul date +%F)
  run /opt/trex-dashboard/.venv/bin/python -m bist_factor_backtest.cli capture-first-open-prices \
    --config /opt/trex-dashboard/config.formula_research_momentum.yaml \
    --trade-date "$TRADE_DATE"
  run /opt/trex-dashboard/.venv/bin/python -m bist_factor_backtest.cli refresh-dashboard \
    --output-dir /opt/trex-dashboard/data/dashboard \
    --registry-file /opt/trex-dashboard/data/universe/bist_sanayi_investing_registry.csv \
    --skip-price-load \
    --skip-network-loaders
  mark_completed_month
  cleanup_logs
  echo "[$(date -u)] month-start refresh done"
} >> "$LOG" 2>&1

write_status "success" "Ay basi sabah refresh basariyla tamamlandi."
