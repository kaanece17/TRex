#!/usr/bin/env bash
set -euo pipefail

if [ "$(TZ=Europe/Istanbul date -d tomorrow +%d)" != "01" ]; then
  echo "Not last day of month in Europe/Istanbul, skipping."
  exit 0
fi

exec /opt/trex-dashboard/refresh_month_end.sh
