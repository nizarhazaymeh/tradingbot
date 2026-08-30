#!/usr/bin/env python3
"""Multi-cycle backtest: replay the agent's strategy over many past expiries.

Assumptions (stated plainly, because they matter):
  * daily bars only — no intraday movement, so exits trigger on closes
  * fills at the bar close, no bid/ask crossing modelled beyond a 2c synthetic
  * no commissions or regulatory fees (paper trading does not charge them either)
  * strikes chosen by % distance from spot, not by delta (historical Greeks are
    not available from the bars endpoint)
Treat this as a test of the LOGIC and a rough sense of the payoff shape, not a
precise performance claim.
"""
import sys, os, json, argparse, statistics
from datetime import date, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.client import AlpacaClient, AlpacaError
from agent import options as O, spreads as S, config
from agent.replay import Replayer

ap = argparse.ArgumentParser()
ap.add_argument("--underlyings", default="SPY,QQQ,IWM")
ap.add_argument("--weeks", type=int, default=8)
ap.add_argument("--dte", type=int, default=4)
ap.add_argument("--out", default="docs/backtest_results.json")
a = ap.parse_args()

c = AlpacaClient(); rp = Replayer(c)
YESTERDAY = date.today() - timedelta(days=1)

def fridays(n):
    d = YESTERDAY
    while d.weekday() != 4:
        d -= timedelta(days=1)
    out = []
    for _ in range(n):
        out.append(d); d -= timedelta(days=7)
    return sorted(out)

STRATS = [
    ("put_credit_1.5",  "P", -0.015, 5),
    ("put_credit_3.0",  "P", -0.030, 5),
    ("call_credit_1.5", "C",  0.015, 5),
    ("call_credit_3.0", "C",  0.030, 5),
    ("iron_condor_2.2", None, 0.022, 5),
]

rows = []
for und in [u.strip().upper() for u in a.underlyings.split(",")]:
    for expiry in fridays(a.weeks):
        entry = expiry - timedelta(days=a.dte)
        try:
            closes = rp.stock_closes(und, (entry-timedelta(days=6)).isoformat(),
                                     rp.safe_end(expiry))
        except Exception as e:
            print(f"  {und} {expiry}: skip ({type(e).__name__})"); continue
        spot = closes.get(entry.isoformat())
        if not spot:
            continue

        lo, hi = int(spot*0.94), int(spot*1.06)
        cand = {}
        for k in ("C","P"):
            for st in range(lo, hi+1):
                cand[(k,float(st))] = O.occ(und, expiry, k, st)
        try:
            bars = rp.option_bars(list(cand.values()),
                                  (entry-timedelta(days=1)).isoformat(), rp.safe_end(expiry))
        except Exception as e:
            print(f"  {und} {expiry}: skip ({type(e).__name__})"); continue
        cand = {k:v for k,v in cand.items() if v in bars}
        strikes = sorted({s for _,s in cand})
        if len(strikes) < 12:
            continue

        def near(t): return min(strikes, key=lambda s: abs(s-t))
        def cv(kind, strike):
            sym = cand.get((kind, strike))
            if not sym: return None
            b = bars.get(sym, {}).get(entry.isoformat())
            if not b or float(b["c"]) <= 0: return None
            p = float(b["c"])
            return O.ContractView(symbol=sym, root=und, expiry=expiry, kind=kind,
                                  strike=strike, dte=a.dte, bid=p*0.98, ask=p*1.02,
                                  mid=p, spread_pct=0.04,
                                  delta=0.2 if kind=="C" else -0.2, gamma=0.01,
                                  theta=-0.1, vega=0.1, iv=0.15, open_interest=5000)

        for name, kind, off, width in STRATS:
            try:
                if kind is None:
                    spk, sck = near(spot*(1-off)), near(spot*(1+off))
                    legs = (cv("P", near(spk-width)), cv("P", spk),
                            cv("C", sck), cv("C", near(sck+width)))
                    if not all(legs): continue
                    sp = S.iron_condor(*legs)
                else:
                    sk = near(spot*(1+off))
                    lk = near(sk-width) if kind=="P" else near(sk+width)
                    sh, lg = cv(kind, sk), cv(kind, lk)
                    if not sh or not lg or sh.strike == lg.strike: continue
                    sp = (S.bull_put_spread(sh,lg) if kind=="P"
                          else S.bear_call_spread(sh,lg))
                if sp.max_loss_per_unit <= 0 or abs(sp.net_price) <= 0.01:
                    continue
                r = rp.replay(sp, entry)
                rows.append({"underlying": und, "expiry": expiry.isoformat(),
                             "entry": entry.isoformat(), "strategy": name,
                             "entry_price": r.entry_price, "pnl": r.final_pnl,
                             "max_loss": r.max_loss, "max_gain": r.max_gain,
                             "exit_day": str(r.exit_day), "reason": r.exit_reason,
                             "held_to_expiry": r.held_to_expiry,
                             "spot_entry": spot,
                             "spot_expiry": closes.get(expiry.isoformat())})
            except Exception:
                continue
        print(f"  {und} {expiry}: {sum(1 for x in rows if x['expiry']==expiry.isoformat() and x['underlying']==und)} trades")

def stats(rs):
    if not rs: return {}
    p = [x["pnl"] for x in rs]
    w = [x for x in p if x > 0]; l = [x for x in p if x <= 0]
    gp, gl = sum(w), abs(sum(l))
    return {"trades": len(p), "net_pnl": round(sum(p),2),
            "win_rate": round(len(w)/len(p),3),
            "avg_win": round(statistics.mean(w),2) if w else 0,
            "avg_loss": round(statistics.mean(l),2) if l else 0,
            "best": round(max(p),2), "worst": round(min(p),2),
            "profit_factor": round(gp/gl,2) if gl else None,
            "expectancy": round(statistics.mean(p),2),
            "held_to_expiry": sum(1 for x in rs if x["held_to_expiry"])}

print(f"\n{'='*76}\nBACKTEST — {len(rows)} trades over {a.weeks} weekly cycles, {a.dte} DTE\n{'='*76}")
print(f"\n{'strategy':20} {'n':>4} {'win%':>6} {'net $':>9} {'avg win':>9} {'avg loss':>9} {'PF':>6}")
print("-"*76)
for name,_,_,_ in STRATS:
    s = stats([r for r in rows if r["strategy"]==name])
    if s: print(f"{name:20} {s['trades']:4} {s['win_rate']*100:5.0f}% {s['net_pnl']:+9.0f} "
                f"{s['avg_win']:+9.0f} {s['avg_loss']:+9.0f} {str(s['profit_factor']):>6}")
print("-"*76)
for und in [u.strip().upper() for u in a.underlyings.split(",")]:
    s = stats([r for r in rows if r["underlying"]==und])
    if s: print(f"{und:20} {s['trades']:4} {s['win_rate']*100:5.0f}% {s['net_pnl']:+9.0f} "
                f"{s['avg_win']:+9.0f} {s['avg_loss']:+9.0f} {str(s['profit_factor']):>6}")
o = stats(rows)
print("="*76)
print(f"{'OVERALL':20} {o.get('trades',0):4} {o.get('win_rate',0)*100:5.0f}% "
      f"{o.get('net_pnl',0):+9.0f} {o.get('avg_win',0):+9.0f} {o.get('avg_loss',0):+9.0f} "
      f"{str(o.get('profit_factor')):>6}")
print(f"\nexpectancy per trade: ${o.get('expectancy',0):+.2f}")
print(f"worst single trade  : ${o.get('worst',0):+.0f}")
print(f"held to expiry      : {o.get('held_to_expiry',0)} (the agent normally exits earlier)")

os.makedirs(os.path.dirname(a.out), exist_ok=True)
json.dump({"params": vars(a), "overall": o,
           "by_strategy": {n: stats([r for r in rows if r["strategy"]==n]) for n,_,_,_ in STRATS},
           "by_underlying": {u: stats([r for r in rows if r["underlying"]==u])
                             for u in [x.strip().upper() for x in a.underlyings.split(",")]},
           "trades": rows}, open(a.out,"w"), indent=2)
print(f"\nwrote {a.out}")
