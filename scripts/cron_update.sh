#!/usr/bin/env bash
#
# Weekly COT refresh + conditional email. Run from cron. Configure via the environment
# (set these in the crontab, not here):
#   COTDATA_STORE   required — path to the cotdata store.
#   COTDATA_UPDATE  optional — the cotdata-update binary (default: whatever is on PATH).
#
set -euo pipefail

: "${COTDATA_STORE:?set COTDATA_STORE to the cotdata store path}"
COTDATA_UPDATE="${COTDATA_UPDATE:-cotdata-update}"
STATUS_FILE="$COTDATA_STORE/status.json"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # cotmetrics repo root

_cot_date() {
    [ -f "$STATUS_FILE" ] && jq -r '.newest_data.cot_legacy // "None"' "$STATUS_FILE" 2>/dev/null || echo "None"
}

OLD_DATE="$(_cot_date)"
echo "Previous newest COT date: $OLD_DATE"

echo "Running $COTDATA_UPDATE --cot-all..."
"$COTDATA_UPDATE" --cot-all

NEW_DATE="$(_cot_date)"
echo "New newest COT date: $NEW_DATE"

# Email only when the report date actually advanced.
if [ "$OLD_DATE" != "$NEW_DATE" ] && [ "$NEW_DATE" != "None" ] && [ "$NEW_DATE" != "null" ]; then
    echo "New data detected. Sending email report..."
    bash "$REPO_DIR/scripts/generate-weekly-report-email.sh"
else
    echo "No new data. Skipping email report."
fi
