#!/usr/bin/env bash
# Restart the live loop if it is not running. Safe to run repeatedly.
#
# The loop is a foreground python process: it dies with its terminal and does not
# survive the machine sleeping. That matters most on Fri 4 Sep, when FLATTEN_AT
# closes the book before judging — if nothing is running at 09:35 ET the book
# stays open and the judged figure drifts with the market.
#
# ---------------------------------------------------------------------------
# Three faults found on 2 Sep, all of which made this file look like a safety
# net without being one:
#
# 1. THE GUARD MATCHED THE WRONG PROCESS. `pgrep -f "run.py loop"` matches ANY
#    loop, and run.py takes the account from the ACCOUNT env var rather than a
#    flag, so a dev loop on the same machine satisfied the check and the comp
#    loop was never started. On 2 Sep a dev loop had been running since the 1st
#    while comp had 10 positions open and nothing managing them. The guard is now
#    a per-account pidfile, validated against the live process table so a stale
#    file cannot mask a dead loop.
#
# 2. THE INTERPRETER WAS ANOTHER MACHINE'S. PYTHON was pinned to
#    /Users/karambalasmeh/.pyenv/... which does not exist here, so it silently
#    fell through to `command -v python3`. That happens to work, but "happens to"
#    is not what this file is for. The repo venv is tried first now.
#
# 3. IT WOULD RESTART INTO A LOOP THAT CANNOT TRADE. With no credentials for the
#    target account it started a process that failed immediately, every five
#    minutes, logging into a file nobody reads. It now checks first and says so.
# ---------------------------------------------------------------------------
cd "$(dirname "$0")/.." || exit 1

ACCOUNT="${ACCOUNT:-comp}"
INTERVAL="${INTERVAL:-300}"
PIDFILE="state/loop-$ACCOUNT.pid"
LOG="logs/$ACCOUNT-live-$(date +%Y%m%d).log"
mkdir -p logs state

# launchd runs this with PATH=/usr/bin:/bin:/usr/sbin:/sbin, which excludes
# pyenv and any venv, so the interpreter is resolved explicitly here.
for cand in "$PWD/.venv/bin/python3" "$HOME/.pyenv/shims/python3" "$(command -v python3)"; do
  if [ -x "$cand" ]; then PYTHON="$cand"; break; fi
done
[ -n "$PYTHON" ] || { echo "$(date '+%F %T') no usable python3"; exit 1; }

say() { echo "$(date '+%F %T') $*"; }

# The demo URL is only as live as the last commit of public/dashboard.json.
# Rate-limited internally; safe to call every time the watchdog fires.
./scripts/publish_dashboard.sh || true

# --- is OUR loop alive? pidfile + a real check against the process table ------
running() {
  [ -f "$PIDFILE" ] || return 1
  local pid; pid=$(cat "$PIDFILE" 2>/dev/null) || return 1
  [ -n "$pid" ] || return 1
  ps -p "$pid" -o command= 2>/dev/null | grep -q "run.py loop" || return 1
  return 0
}

if running; then
  say "loop already running for ACCOUNT=$ACCOUNT (pid $(cat "$PIDFILE"))"
  exit 0
fi

# --- refuse to restart into an account we have no keys for --------------------
if ! ACCOUNT="$ACCOUNT" "$PYTHON" -c "
import sys; sys.path.insert(0, '.')
from agent import config
sys.exit(0 if config.API_KEY and config.SECRET_KEY else 1)
" 2>/dev/null; then
  say "REFUSING to start: no credentials for ACCOUNT=$ACCOUNT — set them in .env"
  exit 1
fi

say "loop not running for ACCOUNT=$ACCOUNT — starting with $PYTHON"
ACCOUNT="$ACCOUNT" DRY_RUN=false nohup "$PYTHON" run.py loop --live \
  --interval "$INTERVAL" >> "$LOG" 2>&1 &
echo $! > "$PIDFILE"
sleep 6
if running; then
  say "started pid $(cat "$PIDFILE")"
else
  say "FAILED to start — tail of $LOG:"
  tail -5 "$LOG"
  rm -f "$PIDFILE"
  exit 1
fi
