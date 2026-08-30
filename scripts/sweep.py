#!/usr/bin/env python3
"""Parameter sweep across four market regimes.

Our take-profit level, DTE and strike distance were chosen by judgement. This
tests them against real historical option prices in calm, high-vol, selloff and
carry-unwind markets, so the config is measured rather than assumed.

Sweeps one dimension at a time; historical data is disk-cached so re-runs are fast.
"""
import sys, os, json, argparse, statistics, itertools
from datetime import date, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent import config, options as O, spreads as S, monitor
from agent.client import AlpacaClient
from agent.replay import Replayer

REGIMES = [
    ("calm/rising",  date(2026, 8, 28), 6),
    ("vol spike 46%", date(2025, 5, 2), 5),
    ("selloff -7.7%", date(2026, 4, 3), 5),
    ("carry unwind",  date(2024, 8, 30), 5),
]
UNDS = ["SPY", "QQQ", "IWM"]

c = AlpacaClient(); rp = Replayer(c)


def fridays(end, n):
    d = end
    while d.weekday() != 4:
        d -= timedelta(days=1)
    out = []
    for _ in range(n):
        out.append(d); d -= timedelta(days=7)
    return out


def run(*, dte, tp_credit, offset, width, kinds=("P",), condor=False):
    """Return every trade under one parameter set."""
    old_tp = config.TAKE_PROFIT_CREDIT
    config.TAKE_PROFIT_CREDIT = tp_credit
    rows = []
    try:
        for label, end, weeks in REGIMES:
            for expiry in fridays(end, weeks):
                entry = expiry - timedelta(days=dte)
                for und in UNDS:
                    try:
                        closes = rp.stock_closes(und, (entry-timedelta(days=6)).isoformat(),
                                                 rp.safe_end(expiry))
                    except Exception:
                        continue
                    spot = closes.get(entry.isoformat())
                    if not spot:
                        continue
                    lo, hi = int(spot*0.94), int(spot*1.06)
                    cand = {(k, float(st)): O.occ(und, expiry, k, st)
                            for k in ("C", "P") for st in range(lo, hi+1)}
                    try:
                        bars = rp.option_bars(list(cand.values()),
                                              (entry-timedelta(days=1)).isoformat(),
                                              rp.safe_end(expiry))
                    except Exception:
                        continue
                    cand = {k: v for k, v in cand.items() if v in bars}
                    strikes = sorted({s for _, s in cand})
                    if len(strikes) < 12:
                        continue
                    near = lambda t: min(strikes, key=lambda s: abs(s-t))

                    def cv(kind, strike):
                        sym = cand.get((kind, strike))
                        if not sym: return None
                        b = bars.get(sym, {}).get(entry.isoformat())
                        if not b or float(b["c"]) <= 0: return None
                        p = float(b["c"])
                        return O.ContractView(symbol=sym, root=und, expiry=expiry,
                                              kind=kind, strike=strike, dte=dte,
                                              bid=p*0.98, ask=p*1.02, mid=p,
                                              spread_pct=0.04,
                                              delta=0.2 if kind == "C" else -0.2,
                                              gamma=0.01, theta=-0.1, vega=0.1,
                                              iv=0.15, open_interest=5000)

                    builds = []
                    if condor:
                        spk, sck = near(spot*(1-offset)), near(spot*(1+offset))
                        legs = (cv("P", near(spk-width)), cv("P", spk),
                                cv("C", sck), cv("C", near(sck+width)))
                        if all(legs):
                            builds.append(S.iron_condor(*legs))
                    else:
                        for kind in kinds:
                            sk = near(spot*(1 + (-offset if kind == "P" else offset)))
                            lk = near(sk-width) if kind == "P" else near(sk+width)
                            sh, lg = cv(kind, sk), cv(kind, lk)
                            if sh and lg and sh.strike != lg.strike:
                                builds.append(S.bull_put_spread(sh, lg) if kind == "P"
                                              else S.bear_call_spread(sh, lg))
                    for sp in builds:
                        if sp.max_loss_per_unit <= 0 or abs(sp.net_price) <= 0.01:
                            continue
                        try:
                            r = rp.replay(sp, entry)
                            rows.append({"regime": label, "und": und, "pnl": r.final_pnl,
                                         "reason": r.exit_reason})
                        except Exception:
                            continue
    finally:
        config.TAKE_PROFIT_CREDIT = old_tp
    return rows


def stat(rows):
    p = [x["pnl"] for x in rows]
    if not p: return None
    w = [x for x in p if x > 0]; l = [x for x in p if x <= 0]
    gp, gl = sum(w), abs(sum(l))
    return {"n": len(p), "win": len(w)/len(p), "net": sum(p),
            "pf": (gp/gl if gl else 99), "exp": statistics.mean(p)}


def show(title, variants):
    print(f"\n{title}")
    print(f"  {'setting':22} {'n':>4} {'win%':>6} {'net $':>9} {'PF':>7} {'per trade':>10}")
    print("  " + "-"*62)
    best = None
    for label, rows in variants:
        s = stat(rows)
        if not s: continue
        star = ""
        if best is None or s["pf"] > best[1]["pf"]:
            best = (label, s)
        print(f"  {label:22} {s['n']:4} {s['win']*100:5.0f}% {s['net']:+9.0f} "
              f"{s['pf']:7.2f} {s['exp']:+10.2f}{star}")
    if best:
        print(f"  -> best: {best[0]} (PF {best[1]['pf']:.2f})")
    return best


ap = argparse.ArgumentParser()
ap.add_argument("--which", default="all",
                choices=["all", "tp", "dte", "offset", "width"])
a = ap.parse_args()

print("PARAMETER SWEEP — put credit spreads across 4 market regimes")
print(f"baseline: DTE {config.TARGET_DTE}, take-profit {config.TAKE_PROFIT_CREDIT:.0%}, "
      f"3% OTM, $5 wide\n")

if a.which in ("all", "tp"):
    show("TAKE-PROFIT LEVEL (when to close a winner)",
         [(f"close at {tp:.0%} of max", run(dte=4, tp_credit=tp, offset=0.03, width=5))
          for tp in (0.25, 0.35, 0.50, 0.65, 0.80)])

if a.which in ("all", "dte"):
    show("DAYS TO EXPIRY at entry",
         [(f"{d} DTE", run(dte=d, tp_credit=0.50, offset=0.03, width=5))
          for d in (2, 3, 4, 5, 7)])

if a.which in ("all", "offset"):
    show("STRIKE DISTANCE from spot",
         [(f"{o*100:.1f}% OTM", run(dte=4, tp_credit=0.50, offset=o, width=5))
          for o in (0.010, 0.020, 0.030, 0.040, 0.050)])

if a.which in ("all", "width"):
    show("SPREAD WIDTH",
         [(f"${w} wide", run(dte=4, tp_credit=0.50, offset=0.03, width=w))
          for w in (2, 3, 5, 8)])
