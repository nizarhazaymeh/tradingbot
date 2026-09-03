#!/usr/bin/env bash
# Persistent supervisor: call watchdog.sh forever, every INTERVAL seconds.
#
# Replaces StartInterval, which does not reliably fire. On 3 Sep the job showed
#
#   runs = 1
#   pended nondemand spawn = interval
#
# after 29 minutes with StartInterval=300 — launchd had deferred the spawn and
# never ran it. A periodic "nondemand" spawn is advisory; launchd is free to
# defer it under power management, and it did. That left the loop with no
# restart path on the day FLATTEN_AT had to fire.
#
# A long-lived process with KeepAlive is a much stronger contract: if this exits
# for any reason, launchd starts it again. The sleep is inside our process, so
# nothing external decides whether the next check happens.
cd "$(dirname "$0")/.." || exit 1
INTERVAL="${INTERVAL:-300}"
echo "$(date '+%F %T') supervisor up (pid $$, interval ${INTERVAL}s, ACCOUNT=${ACCOUNT:-comp})"
while true; do
  ./scripts/watchdog.sh || echo "$(date '+%F %T') watchdog returned $?"
  sleep "$INTERVAL"
done
