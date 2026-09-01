#!/usr/bin/env bash
# Restart the live loop if it is not running. Safe to run repeatedly.
#
# The loop is a foreground python process: it dies with its terminal and does not
# survive the machine sleeping. That matters most on Fri 4 Sep, when FLATTEN_AT
# closes the book before judging — if nothing is running at 09:35 ET the book
# stays open and the judged figure drifts with the market.
#
# launchd runs this with a minimal PATH (/usr/bin:/bin:/usr/sbin:/sbin) which does
# NOT include pyenv, so a bare `python3` resolves to the system interpreter
# without our dependencies. The path below is pinned for that reason.
cd "$(dirname "$0")/.." || exit 1

PYTHON="${PYTHON:-/Users/karambalasmeh/.pyenv/versions/3.11.9/bin/python3}"
[ -x "$PYTHON" ] || PYTHON="$(command -v python3)"

LOG="logs/comp-live-$(date +%Y%m%d).log"
mkdir -p logs

if pgrep -f "run.py loop" > /dev/null; then
  echo "$(date '+%F %T') loop already running (pid $(pgrep -f 'run.py loop' | head -1))"
  exit 0
fi

echo "$(date '+%F %T') loop not running — starting with $PYTHON"
ACCOUNT=comp DRY_RUN=false nohup "$PYTHON" run.py loop --live --interval 300 \
  >> "$LOG" 2>&1 &
sleep 6
if pgrep -f "run.py loop" > /dev/null; then
  echo "$(date '+%F %T') started pid $(pgrep -f 'run.py loop' | head -1)"
else
  echo "$(date '+%F %T') FAILED to start — tail of $LOG:"
  tail -5 "$LOG"
fi
