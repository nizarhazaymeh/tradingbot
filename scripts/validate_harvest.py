#!/usr/bin/env python3
"""A/B the decay-harvest exit over past expiry cycles.

The rule went in on the strength of one live case (two IWM bear put spreads on
1 Sep). That is not evidence. This replays the SAME debit structures through the
SAME exit logic twice — once with HARVEST_ENABLED and once without — and reports
the difference in realised P&L.

Harvest only ever fires on long premium, so only debit structures are built.
Realised vol inside the replay is computed from closes strictly before each
step, so the rule cannot see the move it is about to be judged on.
"""
import sys, os, argparse
from datetime import date, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.client import AlpacaClient
from agent import options as O, spreads as S, config
from agent.replay import Replayer

ap = argparse.ArgumentParser()
ap.add_argument("--underlyings", default="SPY,QQQ,IWM")
ap.add_argument("--weeks", type=int, default=6)
ap.add_argument("--end", default="2026-08-28", help="last Friday expiry to test")
a = ap.parse_args()

c = AlpacaClient(); rp = Replayer(c)
last_fri = date.fromisoformat(a.end)
cycles = [(last_fri - timedelta(days=7*i)) for i in range(a.weeks)]

def build(und, entry, expiry):
    """Reconstruct the chain and build both debit verticals, as the agent would."""
    closes = rp.stock_closes(und, (entry - timedelta(days=5)).isoformat(),
                             rp.safe_end(expiry))
    spot = closes.get(entry.isoformat())
    if not spot:
        return []
    dte = (expiry - entry).days
    lo, hi = int(spot*0.94), int(spot*1.06)
    cand = {(k, float(s)): O.occ(und, expiry, k, s)
            for k in ("C", "P") for s in range(lo, hi+1)}
    bars = rp.option_bars(list(cand.values()), (entry-timedelta(days=1)).isoformat(),
                          rp.safe_end(expiry))
    cand = {k: v for k, v in cand.items() if v in bars}
    if not cand:
        return []

    def cv(kind, strike):
        sym = cand.get((kind, strike))
        if not sym: return None
        b = bars.get(sym, {}).get(entry.isoformat())
        if not b: return None
        p = float(b["c"])
        if p <= 0.05: return None
        return O.ContractView(symbol=sym, root=und, expiry=expiry, kind=kind,
                              strike=strike, dte=dte, bid=p*0.98, ask=p*1.02, mid=p,
                              spread_pct=0.04, delta=0.35 if kind=="C" else -0.35,
                              gamma=0.01, theta=-0.10, vega=0.1, iv=0.18,
                              open_interest=5000)

    atm = round(spot)
    out = []
    for width in (3, 5):
        # bear put: long the higher strike, short the lower  (debit, bearish)
        lp, sp_ = cv("P", float(atm)), cv("P", float(atm - width))
        if lp and sp_:
            out.append(("bear_put", S.bear_put_spread(lp, sp_, qty=2)))
        # bull call: long the lower strike, short the higher (debit, bullish)
        lc, sc = cv("C", float(atm)), cv("C", float(atm + width))
        if lc and sc:
            out.append(("bull_call", S.bull_call_spread(lc, sc, qty=2)))
    return out

rows = []
for expiry in cycles:
    entry = expiry - timedelta(days=3)          # Tuesday of that week
    for und in a.underlyings.split(","):
        try:
            built = build(und, entry, expiry)
        except Exception as e:
            print(f"  ! {und} {expiry}: {type(e).__name__}: {str(e)[:60]}")
            continue
        for kind, sp in built:
            res = {}
            for on in (True, False):
                config.HARVEST_ENABLED = on
                try:
                    r = rp.replay(sp, entry)
                    res[on] = (r.final_pnl, r.exit_reason or "held to expiry")
                except Exception as e:
                    res[on] = (None, f"{type(e).__name__}")
            if res[True][0] is None or res[False][0] is None:
                continue
            rows.append((und, expiry, kind, res[True][0], res[False][0], res[True][1]))
config.HARVEST_ENABLED = True

if not rows:
    sys.exit("no replayable structures — historical option bars may be unavailable")

print(f"\n{'und':5} {'expiry':11} {'structure':10} {'harvest ON':>11} "
      f"{'harvest OFF':>12} {'diff':>9}  exit taken")
print("-"*104)
on_t = off_t = 0.0
fired = 0
for und, exp, kind, on, off, why in rows:
    on_t += on; off_t += off
    d = on - off
    if d: fired += 1
    print(f"{und:5} {str(exp):11} {kind:10} {on:11,.0f} {off:12,.0f} {d:+9,.0f}  {why[:34]}")
print("-"*104)
n = len(rows)
print(f"{'TOTAL':5} {n:>3} structures        {on_t:11,.0f} {off_t:12,.0f} {on_t-off_t:+9,.0f}")
print(f"\nharvest changed the outcome on {fired} of {n}")
print(f"mean P&L per structure: ON ${on_t/n:,.0f}   OFF ${off_t/n:,.0f}")
w_on = sum(1 for r in rows if r[3] > 0); w_off = sum(1 for r in rows if r[4] > 0)
print(f"win rate:               ON {w_on/n:.0%}   OFF {w_off/n:.0%}")
