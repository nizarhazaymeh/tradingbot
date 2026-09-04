#!/usr/bin/env python3
"""Backfill the IV history so regime.classify() can use its primary path.

Every live regime line the agent has ever logged reads `rank n/a`. The reason is
mechanical: options.iv_rank() refuses to answer with fewer than MIN_IV_HISTORY
(20) readings — correctly, since a rank built from two points is a coin flip
dressed as a signal — and state.record_iv() writes one reading per underlying
per trading day. So the classifier's primary path cannot run until the agent has
been up for a month, and it has never been up for a month. It has fallen back to
the IV/RV ratio on every cycle it has ever run.

This recovers the missing readings from historical option bars. For each past
trading day it picks the expiry the live agent would have picked (closest to
TARGET_DTE inside MIN_DTE..MAX_DTE), inverts Black-Scholes on the closing prices
of the strikes bracketing spot, and stores the mean as that day's ATM IV — the
same inversion scripts/backtest_bonus.py uses to recover Greeks.

It never overwrites a reading the live agent recorded itself: those come from
the real quote feed at midday and are better than a close-based inversion.

  python scripts/backfill_iv.py                  # UNIVERSE, last 120 trading days
  python scripts/backfill_iv.py --days 60 --dry-run
  ACCOUNT=comp python scripts/backfill_iv.py     # a different account's ledger
"""
import argparse
import importlib.util
import statistics
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent import config, options as O
from agent.client import AlpacaClient
from agent.replay import Replayer
from agent.state import Store

_spec = importlib.util.spec_from_file_location("bb", ROOT / "scripts" / "backtest_bonus.py")
_bb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_bb)
implied_vol = _bb.implied_vol


def target_expiry(d: date):
    """The Friday the live agent would pick on day d — see cycle._pick_expiry()."""
    best = None
    for k in range(config.MIN_DTE, config.MAX_DTE + 1):
        e = d + timedelta(days=k)
        if e.weekday() != 4:
            continue
        if best is None or abs(k - config.TARGET_DTE) < abs((best - d).days - config.TARGET_DTE):
            best = e
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--universe", default=",".join(config.UNIVERSE))
    ap.add_argument("--days", type=int, default=120, help="trading days to backfill")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--overwrite", action="store_true",
                    help="replace readings the live agent recorded (default: keep them)")
    a = ap.parse_args()

    unds = [u.strip().upper() for u in a.universe.split(",") if u.strip()]
    rp = Replayer(AlpacaClient())
    store = Store()
    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=int(a.days * 1.6) + 10)      # calendar span for N trading days
    print(f"\nbackfilling ATM IV for {', '.join(unds)} — {a.days} trading days to {end}"
          f"{'  (DRY RUN)' if a.dry_run else ''}\n")

    total_written = 0
    for und in unds:
        closes = rp.stock_closes(und, start.isoformat(), end.isoformat())
        days = sorted(closes)[-a.days:]
        have = set()
        if not a.overwrite:
            with store._conn() as c:
                have = {r["d"] for r in c.execute(
                    "SELECT d FROM iv_history WHERE underlying=?", (und,)).fetchall()}

        # group days by the expiry they would target, one bars fetch per expiry
        by_exp = defaultdict(list)
        for ds in days:
            if ds in have:
                continue
            e = target_expiry(date.fromisoformat(ds))
            if e:
                by_exp[e].append(ds)

        written, failed = 0, 0
        for e, dlist in sorted(by_exp.items()):
            spots = [closes[ds] for ds in dlist]
            # a wide net, because single names trade in $2.50 or $5 increments and
            # the two integer strikes around spot usually do not exist for them
            lo, hi = int(min(spots) * 0.97), int(max(spots) * 1.03) + 1
            syms = {(k, float(st)): O.occ(und, e, k, st)
                    for k in ("C", "P") for st in range(lo, hi + 1)}
            try:
                bars = rp.option_bars(list(syms.values()), min(dlist), rp.safe_end(e))
            except Exception as ex:
                failed += len(dlist)
                print(f"  {und} exp {e}: fetch failed ({type(ex).__name__})")
                continue
            for ds in dlist:
                d = date.fromisoformat(ds)
                spot = closes[ds]
                t = max((e - d).days, 1) / 365.0
                ivs = []
                for kind in ("C", "P"):
                    # the nearest strike on each side of spot that actually has a
                    # bar that day — whatever increment the name trades in
                    traded = sorted(st for (k, st), sym in syms.items()
                                    if k == kind and ds in bars.get(sym, {}))
                    below = [st for st in traded if st <= spot][-1:]
                    above = [st for st in traded if st > spot][:1]
                    for st in below + above:
                        bar = bars[syms[(kind, st)]][ds]
                        iv = implied_vol(float(bar["c"]), spot, st, t, kind)
                        if iv and 0.03 < iv < 2.0:
                            ivs.append(iv)
                if len(ivs) < 2:
                    failed += 1
                    continue
                atm = statistics.mean(ivs)
                if not a.dry_run:
                    store.record_iv(und, d, atm)
                written += 1
        kept = len([ds for ds in days if ds in have])
        hist = store.iv_history(und)
        rank_now = O.iv_rank(hist[0], hist) if hist else None
        print(f"  {und}: wrote {written:>3}, kept {kept:>2} live readings, "
              f"{failed:>2} unrecoverable  ->  history {len(hist):>3} readings, "
              f"rank of latest {f'{rank_now:.2f}' if rank_now is not None else 'n/a'}")
        total_written += written

    print(f"\n  {total_written} readings {'would be ' if a.dry_run else ''}written to "
          f"{store.path if hasattr(store, 'path') else 'the store'}")
    print(f"  iv_rank() needs {config.MIN_IV_HISTORY}; classify() uses it when available\n")


if __name__ == "__main__":
    main()
