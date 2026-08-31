#!/usr/bin/env python3
"""T1 — verify that a real order actually FILLS.

TODO.md calls T1 "the single biggest unknown in the whole project": orders have
reached status `accepted`, but nothing has ever filled, so these are unproven:

  * are our limit prices close enough to the market to fill at all
  * does the fill payload have the shape our code expects
  * does filled_qty reconciliation survive a partial fill
  * does the exit loop correctly mark and close a real position

This submits ONE 1-lot SPY bull put spread with hand-picked, deliberately
conservative strikes, then watches it fill and reports the payload.

It bypasses strategy SELECTION only. Everything downstream is the production
path: AlpacaClient, usable_contracts, bull_put_spread, validate_mleg,
Executor.open_spread. No risk gate or swept parameter is read or changed, so
the backtested edge is untouched.

  python scripts/t1_fill_test.py            # plan only, submits nothing
  python scripts/t1_fill_test.py --live     # submit and watch the fill
  python scripts/t1_fill_test.py --close    # close whatever this script opened
"""
import argparse
import json
import logging
import sys
import time
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s",
                    datefmt="%H:%M:%S")

from agent import config, options as O
from agent.client import AlpacaClient, AlpacaError
from agent.executor import Executor
from agent.spreads import bull_put_spread, closing_order, validate_mleg
from agent.state import Store

UNDERLYING = "SPY"
QTY = 1                  # never more; this is a mechanics test, not a trade
TARGET_SHORT_DELTA = 0.10   # ~1.3s out — comfortably past the 0.9s the agent needs
WIDTH_STRIKES = 5        # in strike increments. config.WIDTH_STRIKES is [2,3,4,5,8];
                         # adjacent strikes give a ~$0.04 credit that will not fill.
POLL_SECONDS = 10
POLL_ATTEMPTS = 30       # 5 minutes


def die(msg):
    print(f"\n  REFUSING: {msg}\n")
    sys.exit(1)


def assert_dev_account():
    """Runs BEFORE AlpacaClient() — otherwise a comp account with no keys dies
    with 'credentials missing', which hides the real reason we are stopping."""
    if config.ACCOUNT != "dev":
        die(f"ACCOUNT={config.ACCOUNT!r}. This script is DEV-only. "
            "The competition account is not a test surface.")


def preflight(c):
    """Never trade a blocked account, and never one we did not expect."""
    acct = c.account()
    want = config.ACCOUNT_NUMBER
    if want and acct["account_number"] != want:
        die(f"connected to {acct['account_number']} but .env says {want}")
    if acct.get("trading_blocked") or acct.get("account_blocked"):
        die("account is blocked")
    if int(acct.get("options_trading_level") or 0) < 3:
        die(f"options level {acct.get('options_trading_level')} < 3; spreads not permitted")
    return acct


def pick_expiry(c, spot):
    """Same expiry preference as the agent: closest to TARGET_DTE."""
    today = date.today()
    exps = c.expirations(UNDERLYING,
                         (today + timedelta(days=config.MIN_DTE)).isoformat(),
                         (today + timedelta(days=config.MAX_DTE)).isoformat())
    if not exps:
        die("no expiry in the MIN_DTE..MAX_DTE window")
    return min((date.fromisoformat(e) for e in exps),
               key=lambda d: abs((d - today).days - config.TARGET_DTE))


def pick_legs(views, expiry, width):
    """Short put nearest TARGET_SHORT_DELTA, long put WIDTH_STRIKES increments below.

    Uses the same ladder-increment helper the strategy uses, so the width is
    expressed in real strike steps rather than assumed to be $1.
    """
    puts = sorted([v for v in views if v.kind == "P"], key=lambda v: v.strike)
    if len(puts) < 2:
        die(f"only {len(puts)} usable puts in the chain")
    inc = max(O.typical_width(O.strike_ladder(views, "P", expiry)), 0.5)
    short = min(puts, key=lambda v: abs(v.abs_delta - TARGET_SHORT_DELTA))
    target = short.strike - width * inc
    below = [v for v in puts if v.strike < short.strike]
    if not below:
        die("no put below the chosen short strike")
    long_ = min(below, key=lambda v: abs(v.strike - target))
    print(f"  ladder increment ${inc:.2f} -> target width ${width * inc:.2f}")
    return short, long_


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="actually submit")
    ap.add_argument("--close", action="store_true", help="close the test position")
    ap.add_argument("--mid", action="store_true",
                    help="price at the mid instead of the natural (lower fill odds)")
    ap.add_argument("--width", type=int, default=WIDTH_STRIKES,
                    help=f"spread width in strike increments (default {WIDTH_STRIKES}); "
                         "4 keeps max loss inside the 0.40%% per-trade budget")
    a = ap.parse_args()

    assert_dev_account()

    c = AlpacaClient()
    store = Store()
    ex = Executor(c, store, dry_run=not a.live)

    acct = preflight(c)
    clock = c.clock()
    print(f"\naccount   {acct['account_number']}  equity ${float(acct['equity']):,.0f}  "
          f"options level {acct['options_trading_level']}")
    print(f"market    is_open={clock['is_open']}  next_open={clock['next_open']}")

    # ---------------------------------------------------------------- close
    if a.close:
        pos = c.option_positions()
        if not pos:
            print("\n  no option positions to close.")
            return
        print(f"\n  {len(pos)} option leg(s) open:")
        for p_ in pos:
            print(f"    {p_['symbol']:<22} qty {p_['qty']:<6} avg {p_['avg_entry_price']:<8} "
                  f"upl {p_.get('unrealized_pl')}")
        if not a.live:
            print("\n  plan only — add --live to actually close.")
            return
        if not clock["is_open"]:
            die("market is CLOSED; a closing order cannot fill either.")
        # close_all_positions is the same call halt_everything uses
        res = c.close_all_positions(cancel_orders=True)
        print("\n  close_all_positions ->")
        print(json.dumps(res, indent=2, default=str)[:2000])
        time.sleep(5)
        print(f"\n  remaining option legs: {len(c.option_positions())}")
        return

    if a.live and not clock["is_open"]:
        die("market is CLOSED. An order would sit `accepted` and never fill — "
            "which is exactly the T1 ambiguity we are trying to remove. "
            f"Run this after {clock['next_open']}.")

    # same path cycle.py uses, with the same bar fallback
    spot = c.latest_trade(UNDERLYING)
    if not spot:
        snaps = c.stock_snapshots([UNDERLYING])
        spot = ((snaps.get(UNDERLYING) or {}).get("latestTrade") or {}).get("p")
    if not spot:
        bars = c.stock_bars([UNDERLYING], timeframe="1Day", limit=2)
        closes = [b["c"] for b in bars.get(UNDERLYING, [])]
        spot = closes[-1] if closes else None
    if not spot:
        die("could not determine spot price")
    spot = float(spot)

    expiry = pick_expiry(c, spot)
    chain = c.option_chain(UNDERLYING, exp=expiry.isoformat(),
                           strike_gte=spot * 0.85, strike_lte=spot * 1.02, kind="put")
    views = O.usable_contracts(chain)
    print(f"spot      ${spot:,.2f}   expiry {expiry} ({(expiry - date.today()).days} DTE)   "
          f"{len(views)} usable puts")

    short, long_ = pick_legs(views, expiry, a.width)
    spread = bull_put_spread(short, long_, qty=QTY)

    print(f"\n  SHORT  {short.symbol}  K={short.strike:<8.2f} d={short.delta:+.3f}  "
          f"bid {short.bid:.2f} / ask {short.ask:.2f}")
    print(f"  LONG   {long_.symbol}  K={long_.strike:<8.2f} d={long_.delta:+.3f}  "
          f"bid {long_.bid:.2f} / ask {long_.ask:.2f}")
    print(f"\n  {spread.describe()}")
    print(f"  net {spread.net_price:+.2f}/unit  max loss ${spread.total_max_loss():,.2f}  "
          f"width {spread.width}  {(spot - short.strike) / spot * 100:.1f}% OTM")

    budget = float(acct["equity"]) * config.RISK_PER_TRADE_PCT
    ml = spread.total_max_loss()
    if ml > budget:
        print(f"  NOTE: max loss ${ml:,.0f} exceeds the ${budget:,.0f} per-trade budget "
              f"({config.RISK_PER_TRADE_PCT:.2%}). Deliberate for this test; "
              f"use --width {max(2, a.width - 1)} to stay inside it.")

    # Fill probability is the whole point of T1, so default to the NATURAL price
    # (sell the short at its bid, buy the long at its ask) rather than the mid.
    # The mid is roughly a coin flip, and an unfilled order tells us nothing about
    # the payload shape or the reconciliation path. Giving up a few cents of edge
    # on one paper lot is the cheaper trade.
    natural = -(short.bid - long_.ask)          # negative == credit
    mid = spread.net_price
    limit = mid if a.mid else natural
    print(f"\n  mid credit     ${abs(mid):.2f}   (coin-flip fill)")
    print(f"  natural credit ${abs(natural):.2f}   (crosses the spread; fills)")
    print(f"  using          ${abs(limit):.2f}  <- {'mid' if a.mid else 'natural'}")
    if natural >= 0 and not a.mid:
        die(f"natural price is a ${natural:.2f} DEBIT, not a credit; "
            "the bid/ask is too wide to test with. Try --mid or another expiry.")

    body = spread.order(limit_price=limit,
                        client_order_id=spread.client_order_id("t1"))
    errs = validate_mleg(body)
    print(f"\n  validate_mleg: {'PASS' if not errs else 'FAIL ' + str(errs)}")
    if errs:
        die("the order body is invalid; not submitting")

    if not a.live:
        print("\n  plan only — nothing submitted. Re-run with --live once the market is open.")
        print(json.dumps(body, indent=2))
        return

    order, note = ex.open_spread(spread)
    print(f"\n  submitted: {note}")
    if not order or not order.get("id"):
        die(f"no order id returned: {order}")
    oid = order["id"]
    print(f"  order id {oid}   initial status {order.get('status')}")

    # ---- this is the part T1 exists to observe ----
    print(f"\n  watching for a fill (every {POLL_SECONDS}s, up to "
          f"{POLL_SECONDS * POLL_ATTEMPTS // 60} min)...")
    last = None
    for i in range(POLL_ATTEMPTS):
        time.sleep(POLL_SECONDS)
        o = c.get_order(oid)
        st, fq = o.get("status"), o.get("filled_qty")
        if (st, fq) != last:
            print(f"  [{i * POLL_SECONDS:>4}s] status={st:<12} filled_qty={fq} "
                  f"filled_avg_price={o.get('filled_avg_price')}")
            last = (st, fq)
        if st in ("filled", "canceled", "rejected", "expired"):
            break

    o = c.get_order(oid)
    print("\n" + "=" * 62)
    print(f"  FINAL STATUS: {o.get('status')}")
    print("=" * 62)
    print(json.dumps({k: o.get(k) for k in
                      ("id", "client_order_id", "status", "order_class", "type",
                       "limit_price", "qty", "filled_qty", "filled_avg_price",
                       "created_at", "filled_at", "canceled_at")}, indent=2))

    legs = o.get("legs") or []
    print(f"\n  legs in payload: {len(legs)}")
    for l in legs:
        print(f"    {l.get('symbol'):<22} {l.get('side'):<5} {l.get('position_intent'):<18} "
              f"status={l.get('status'):<10} filled_qty={l.get('filled_qty')} "
              f"@ {l.get('filled_avg_price')}")

    print(f"\n  broker option positions now: {len(c.option_positions())}")
    for p in c.option_positions():
        print(f"    {p['symbol']:<22} qty {p['qty']:<6} avg {p['avg_entry_price']:<8} "
              f"mv {p.get('market_value')}")

    if o.get("status") == "filled":
        print("\n  T1 RESOLVED: a real order filled. Payload shape recorded above.")
    elif o.get("status") == "partially_filled":
        print(f"\n  PARTIAL FILL — filled_qty={o.get('filled_qty')} of {o.get('qty')}. "
              "This is the reconciliation path TODO.md flags as untested.")
    else:
        print(f"\n  NOT FILLED (status {o.get('status')}). The limit price was probably "
              "not aggressive enough. T1 remains open.")

    print("\n  to close:  python scripts/t1_fill_test.py --close --live")


if __name__ == "__main__":
    main()
