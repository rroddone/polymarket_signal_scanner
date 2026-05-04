#!/usr/bin/env bash
# Automated harvest script — full ingest + analyze pipeline via main.py
# Designed to run via crontab: 0 */4 * * * /path/to/harvest.sh

export PROJECT_DIR="/Users/rromero/projects/polymarket_scanner"
export PYTHONUNBUFFERED=1   # force line-buffered output so logs reach the file immediately
cd "$PROJECT_DIR" || exit 1

LOCK_FILE="$PROJECT_DIR/harvest.lock"
LOG_FILE="$PROJECT_DIR/logs/automation.log"

mkdir -p "$PROJECT_DIR/logs"

# Prevent concurrent runs (cron overlap or manual + cron collision)
if [ -f "$LOCK_FILE" ]; then
    echo "=== $(date '+%Y-%m-%d %H:%M:%S') Skipped — already running ===" >> "$LOG_FILE"
    exit 0
fi

# Create lock; trap guarantees removal on any exit (normal, error, or signal)
touch "$LOCK_FILE"
trap "rm -f '$LOCK_FILE'" EXIT

source "$PROJECT_DIR/venv/bin/activate"

echo "" >> "$LOG_FILE"
echo "=== $(date '+%Y-%m-%d %H:%M:%S') Session Start ===" >> "$LOG_FILE"

python "$PROJECT_DIR/main.py" --harvest >> "$LOG_FILE" 2>&1

echo "=== $(date '+%Y-%m-%d %H:%M:%S') Session Complete ===" >> "$LOG_FILE"
