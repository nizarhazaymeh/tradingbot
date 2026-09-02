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
    """One position. Crypto quantities are fractional, so they are not cast to
    int the way an option contract count can be."""
    ac = p.get("asset_class") or ""
    raw = float(p.get("qty") or 0)
    q = f"{raw:+.6f}".rstrip("0").rstrip(".") if ac == "crypto" else f"{int(raw):+d}"
    upl = p.get("unrealized_pl")
    tag = "CRYPTO " if ac == "crypto" else ""
    return (f"{tag}{p['symbol']} qty {q} @ {p.get('avg_entry_price')}"
            + (f" upl {float(upl):+.0f}" if upl not in (None, "") else ""))


def snapshot(c):
    # ALL positions, not just options. c.option_positions() filters to
    # asset_class == "us_option", so a spot-crypto fill would have opened and
    # closed without ever being reported — the watcher could not see the thing
    # it was explicitly asked to watch for.
    pos = {p["symbol"]: p for p in c.positions()}
    orders = {o["id"]: o for o in c.orders(status="all", limit=60)}
    acct = c.account()
    return pos, orders, acct


_last_known_open = [True]


def market_is_open(c) -> bool:
    """Last KNOWN state when the clock is unreachable, not a fixed default.

    Returning True on failure was wrong in both directions: during an outage it
    announced "MARKET OPEN" at 19:12 ET and switched to fast polling, so a
    network fault made the watcher poll harder and talk more. Holding the last
    known answer means an outage changes cadence not at all.
    """
    try:
        _last_known_open[0] = bool(c.clock().get("is_open"))
    except Exception:
        pass
    return _last_known_open[0]


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
    fail_streak = 0
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
            fail_streak = 0
        except (AlpacaError, OSError) as e:
            fail_streak += 1
            # Report the first failure and then every 20th, not all of them. A
            # sustained outage produced 45 identical notifications in 30 minutes
            # on 1 Sep and buried a real position close in the middle of them.
            if fail_streak == 1 or fail_streak % 20 == 0:
                say(f"ERROR poll failed (x{fail_streak}): {type(e).__name__}: {e}")
            # Recreating AlpacaClient was tried and does nothing: it only holds
            # keys and calls urllib, so it resets no resolver state. 45 rebuilds
            # in a row on 1 Sep all failed. When a long-lived process loses name
            # resolution while the machine is fine, only a new process fixes it —
            # so back off hard and say plainly that a restart is needed.
            time.sleep(min(a.interval * fail_streak, 300))
            if fail_streak == 10:
                say("ERROR name resolution has failed 10 times in a row. The "
                    "machine is probably fine — this process is not. Restart the "
                    "watcher; recreating the client does not help.")
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
            # Our code sets a descriptive client_order_id on the ORIGINAL
            # order, but executor.py walks the price ladder via
            # PATCH /v2/orders/{id} (replace_order), and Alpaca issues a fresh
            # bare-UUID coid for each replacement object even though it is the
            # same logical order being reprice — confirmed live on 2 Sep, a DIA
            # condor that replaced -0.36 -> -0.33 -> filled -0.30, all ours.
            # `replaces` links a replacement back to the order it superseded;
            # only an order with NO replaces link and a UUID coid is a genuine
            # external submission.
            is_replacement = bool(o.get("replaces"))
            who = ("ours (reprice)" if is_replacement else
                  "EXTERNAL" if _is_uuid(o.get("client_order_id")) else "ours")
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
