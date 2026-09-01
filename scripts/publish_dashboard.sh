#!/usr/bin/env bash
# Refresh public/dashboard.json and push it, so the demo URL shows the live book.
#
# The demo URL is a scored submission gate served by GitHub Pages from main, so
# it only changes when the JSON is COMMITTED — exporting locally does nothing
# for a judge. On 1 Sep the site showed $100,073 and 7 positions while the
# account was at $100,208 with 10.
#
# Deliberately conservative, because this pushes to a repo a teammate also uses:
#   * touches exactly one file, ever
#   * commits only when the FIGURES move, not when a quote ticks — the export
#     embeds live quotes, so a plain diff is always non-empty and would have
#     produced a commit every run (~190 over two days, burying real work)
#   * rebases with --autostash, and aborts cleanly if that conflicts
#   * every failure path exits 0 — this must never take the trading loop down
cd "$(dirname "$0")/.." || exit 0

MIN_INTERVAL="${DASH_MIN_INTERVAL:-900}"        # 15 minutes
STAMP="state/.dashboard_published"
PYTHON="${PYTHON:-/Users/karambalasmeh/.pyenv/versions/3.11.9/bin/python3}"
[ -x "$PYTHON" ] || PYTHON="$(command -v python3)"

now=$(date +%s)
last=0; last_fp=""
if [ -f "$STAMP" ]; then
  last=$(head -1 "$STAMP" 2>/dev/null || echo 0)
  last_fp=$(sed -n 2p "$STAMP" 2>/dev/null)
fi
[ $((now - last)) -lt "$MIN_INTERVAL" ] && exit 0

ACCOUNT=comp "$PYTHON" scripts/export_dashboard.py >/dev/null 2>&1 || exit 0

# Fingerprint = the numbers a judge actually reads.
fp=$("$PYTHON" - <<'PY' 2>/dev/null
import json
d = json.load(open("public/dashboard.json"))
a = d.get("account", {})
print(f"{round(float(a.get('equity', 0)), 2)}"
      f"|{a.get('open_positions')}|{a.get('closed_trades')}"
      f"|{round(float(a.get('realized_pnl') or 0), 2)}")
PY
)
[ -z "$fp" ] && exit 0
if [ "$fp" = "$last_fp" ]; then
  printf '%s\n%s\n' "$now" "$fp" > "$STAMP"
  git checkout -- public/dashboard.json 2>/dev/null   # drop the quote-only churn
  exit 0
fi

git add public/dashboard.json 2>/dev/null || exit 0
eq=${fp%%|*}
git commit -q -m "dashboard: refresh live figures (equity $eq)" -- public/dashboard.json 2>/dev/null || exit 0

git fetch -q origin main 2>/dev/null || exit 0
# --autostash: a human editing the repo leaves the tree dirty and a plain rebase
# refuses outright, which would mean never publishing while anyone is working.
if ! git rebase -q --autostash origin/main 2>/dev/null; then
  git rebase --abort 2>/dev/null
  echo "$(date '+%F %T') dashboard: rebase conflicted, left for a human" >&2
  exit 0
fi
if git push -q origin main 2>/dev/null; then
  echo "$(date '+%F %T') dashboard published (equity $eq)"
  printf '%s\n%s\n' "$now" "$fp" > "$STAMP"
fi
exit 0
