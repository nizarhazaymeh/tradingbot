#!/usr/bin/env python3
"""Emit one line per account event: fills, opens, closes, order status, halts.

Built because positions changed on 31 Aug 2026 with no record of what did it.
The audit trail only covers what the AGENT does; anything acting on the account
through the dashboard, the app or another program is invisible to it. This
watches the broker instead of the code, so an external action is reported the
same as one of ours.

Every line is an event. Nothing is printed when nothing changes, except a
periodic heartbeat so silence can be told apart from a dead watcher.

Errors are emitted, never swallowed: a watcher that goes quiet because the
network died looks exactly like a quiet market.

  python scripts/watch.py                 # 30s polling
  python scripts/watch.py --interval 15
"""
import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent import config
from agent.client import AlpacaClient, AlpacaError

HALT_FILE = ROOT / "HALTED"


def say(*parts):
    """One event, flushed immediately so a supervisor sees it now."""
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"[{ts}Z] " + " ".join(str(p) for p in parts), flush=True)


def leg_line(p):
    q = int(float(p.get("qty") or 0))
    upl = p.get("unrealized_pl")
    return (f"{p['symbol']} qty {q:+d} @ {p.get('avg_entry_price')}"
            + (f" upl {float(upl):+.0f}" if upl not in (None, "") else ""))


def snapshot(c):
    pos = {p["symbol"]: p for p in c.option_positions()}
    orders = {o["id"]: o for o in c.orders(status="all", limit=60)}
    acct = c.account()
    return pos, orders, acct


def market_is_open(c) -> bool:
    """Best-effort: an unreachable clock counts as open, so a network blip
    cannot silently drop the watcher into its slow overnight cadence during a
    session."""
    try:
        return bool(c.clock().get("is_open"))
    except Exception:
        return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", type=int, default=30)
    ap.add_argument("--heartbeat", type=int, default=20,
                    help="emit a heartbeat every N polls (0 to disable)")
    ap.add_argument("--closed-interval", type=int, default=600,
                    help="poll interval while the market is closed (default 600)")
    ap.add_argument("--equity-threshold", type=float, default=25.0,
                    help="minimum equity move worth reporting (default 25)")
    a = ap.parse_args()

    c = AlpacaClient()
    say(f"WATCHING account={config.ACCOUNT} ({config.ACCOUNT_NUMBER}) "
        f"every {a.interval}s")

    try:
        pos, orders, acct = snapshot(c)
    except (AlpacaError, OSError) as e:
        say(f"ERROR initial snapshot failed: {e}")
        pos, orders, acct = {}, {}, {}

    say(f"START {len(pos)} option leg(s) open, equity ${float(acct.get('equity') or 0):,.2f}")
    for p in pos.values():
        say("  HOLDING", leg_line(p))

    last_reported_equity = float(acct.get("equity") or 0)
    seen_halt = HALT_FILE.exists()
    if seen_halt:
        say("HALT FILE PRESENT —", HALT_FILE.read_text().strip()[:120])

    n = 0
    closed_streak = 0
    while True:
        # Nothing can fill outside the session, so polling every 30s overnight
        # burns API calls and emits heartbeats with no information in them.
        # Positions are still checked, just far less often — an assignment or an
        # external action would still be caught, one interval later.
        if market_is_open(c):
            if closed_streak:
                say("MARKET OPEN — resuming normal cadence")
                closed_streak = 0
            time.sleep(a.interval)
        else:
            if not closed_streak:
                say(f"MARKET CLOSED — slowing to {a.closed_interval}s, "
                    f"heartbeats suppressed")
            closed_streak += 1
            time.sleep(a.closed_interval)
        n += 1
        try:
            npos, norders, nacct = snapshot(c)
        except (AlpacaError, OSError) as e:
            say(f"ERROR poll failed: {type(e).__name__}: {e}")
            continue

        # ---- positions ----
        for sym in sorted(set(npos) - set(pos)):
            say("OPENED  ", leg_line(npos[sym]))
        for sym in sorted(set(pos) - set(npos)):
            say("CLOSED  ", leg_line(pos[sym]))
        for sym in sorted(set(npos) & set(pos)):
            oq, nq = pos[sym].get("qty"), npos[sym].get("qty")
            if oq != nq:
                say(f"RESIZED  {sym} qty {oq} -> {nq}")

        # ---- orders ----
        for oid in sorted(set(norders) - set(orders),
                          key=lambda i: norders[i].get("created_at") or ""):
            o = norders[oid]
            legs = o.get("legs") or []
            # our code always sets a descriptive client_order_id; a bare UUID
            # means the order came from Alpaca's own endpoint or dashboard
            who = "EXTERNAL" if _is_uuid(o.get("client_order_id")) else "ours"
            say(f"ORDER NEW {o.get('order_class')} {o.get('status')} "
                f"{o.get('side') or ''} qty={o.get('qty')} "
                f"limit={o.get('limit_price')} legs={len(legs)} "
                f"{legs[0]['symbol'] if legs else o.get('symbol','')} [{who}] "
                f"coid={o.get('client_order_id')}")
        for oid in sorted(set(norders) & set(orders)):
            was, now = orders[oid].get("status"), norders[oid].get("status")
            if was != now:
                o = norders[oid]
                legs = o.get("legs") or []
                say(f"ORDER    {was} -> {now}  filled_qty={o.get('filled_qty')} "
                    f"avg={o.get('filled_avg_price')} "
                    f"{legs[0]['symbol'] if legs else o.get('symbol','')}")

        # ---- equity ----
        # Only moves worth a notification. An open option position marks against
        # the bid/ask every poll, so a $1 floor reported pure flicker: two SPY
        # legs oscillated +$2/-$2 between consecutive polls and buried the
        # OPENED/CLOSED lines this exists to surface. Compared against the last
        # REPORTED equity, not the last poll, so a slow drift still accumulates
        # into one line instead of never crossing the threshold.
        ne = float(nacct.get("equity") or 0)
        if last_reported_equity and abs(ne - last_reported_equity) >= a.equity_threshold:
            say(f"EQUITY   ${last_reported_equity:,.2f} -> ${ne:,.2f}  "
                f"({ne-last_reported_equity:+.2f})")
            last_reported_equity = ne

        # ---- halt ----
        now_halt = HALT_FILE.exists()
        if now_halt and not seen_halt:
            say("HALTED   kill switch appeared —", HALT_FILE.read_text().strip()[:120])
        elif seen_halt and not now_halt:
            say("HALT CLEARED")
        seen_halt = now_halt

        pos, orders, acct = npos, norders, nacct

        if a.heartbeat and not closed_streak and n % a.heartbeat == 0:
            say(f"heartbeat: {len(pos)} leg(s), equity ${ne:,.2f}, poll #{n}")


def _is_uuid(s: str) -> bool:
    """Alpaca generates a bare UUID when the close came from its own endpoint or
    dashboard; our code always sets a descriptive client_order_id."""
    s = str(s or "")
    parts = s.split("-")
    return len(parts) == 5 and len(parts[0]) == 8 and all(
        ch in "0123456789abcdef-" for ch in s.lower())


if __name__ == "__main__":
    main()
