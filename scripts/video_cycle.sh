#!/usr/bin/env bash
# Print one real cycle from the 1 Sep live session, cleaned for the camera.
#
# Cycle 68, 17:20 local (14:20 UTC), dev paper account, dry_run=False. Chosen
# because a single cycle has every beat the video needs: a rich regime the risk
# budget REFUSES, a rich regime that SUBMITS, and a stand-aside where implied vol
# barely exceeds realised. Nothing is edited out — the LLM-unavailable lines are
# kept on purpose; see docs/video/NARRATION.md for how to say them.
#
#   ./scripts/video_cycle.sh            # print, then pause between sections
#   ./scripts/video_cycle.sh --nopause  # print straight through
cd "$(dirname "$0")/.." || exit 1
LOG="${LOG:-logs/agent.log}"
# anchor on the timestamp too: the loop was restarted that day and cycle
# numbers reset, so there is more than one "cycle 68" in the file
S=$(grep -n "2026-09-01 17:20:.*cycle 68 | account=dev" "$LOG" | head -1 | cut -d: -f1)
E=$(awk -v s="$S" -F: 'NR>s && /cycle 68 done/ {print NR; exit}' "$LOG")
[ -n "$S" ] && [ -n "$E" ] || { echo "cycle 68 not found in $LOG"; exit 1; }

pause() { [ "$1" = "--nopause" ] || read -r -s -n1 -p ""; echo; }

clean() { sed -E 's/^2026-09-01 //; s/ (INFO|WARNING) +[a-z.]+:[0-9]+ +/  /'; }

sed -n "${S},${E}p" "$LOG" | clean | awk -v np="$1" '
  /RECONCILE/                       { print; print ""; next }
  /hold /                            { print; next }
  /cycle 68 done/                    { print ""; print; next }
  /\$ .* \| (HIGH|LOW)_IV/           { print ""; print; next }
  { print }
'
