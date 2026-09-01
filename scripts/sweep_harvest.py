#!/usr/bin/env python3
"""Sweep the harvest thresholds over past cycles. Reuses the replay disk cache."""
import sys, os, argparse
from datetime import date, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agent.client import AlpacaClient
from agent import options as O, spreads as S, config
from agent.replay import Replayer

ap = argparse.ArgumentParser()
ap.add_argument("--underlyings", default="SPY,QQQ,IWM")
ap.add_argument("--weeks", type=int, default=12)
ap.add_argument("--end", default="2026-08-28")
a = ap.parse_args()
c = AlpacaClient(); rp = Replayer(c)
cycles = [date.fromisoformat(a.end) - timedelta(days=7*i) for i in range(a.weeks)]

def build(und, entry, expiry):
    closes = rp.stock_closes(und, (entry-timedelta(days=5)).isoformat(), rp.safe_end(expiry))
    spot = closes.get(entry.isoformat())
    if not spot: return []
    dte=(expiry-entry).days; lo,hi=int(spot*0.94),int(spot*1.06)
    cand={(k,float(s)):O.occ(und,expiry,k,s) for k in ("C","P") for s in range(lo,hi+1)}
    bars=rp.option_bars(list(cand.values()),(entry-timedelta(days=1)).isoformat(),rp.safe_end(expiry))
    cand={k:v for k,v in cand.items() if v in bars}
    def cv(kind,strike):
        sym=cand.get((kind,strike))
        if not sym: return None
        b=bars.get(sym,{}).get(entry.isoformat())
        if not b: return None
        p=float(b["c"])
        if p<=0.05: return None
        return O.ContractView(symbol=sym,root=und,expiry=expiry,kind=kind,strike=strike,
            dte=dte,bid=p*0.98,ask=p*1.02,mid=p,spread_pct=0.04,
            delta=0.35 if kind=="C" else -0.35,gamma=0.01,theta=-0.10,vega=0.1,
            iv=0.18,open_interest=5000)
    atm=round(spot); out=[]
    for w in (3,5):
        lp,sp_=cv("P",float(atm)),cv("P",float(atm-w))
        if lp and sp_: out.append(S.bear_put_spread(lp,sp_,qty=2))
        lc,sc=cv("C",float(atm)),cv("C",float(atm+w))
        if lc and sc: out.append(S.bull_call_spread(lc,sc,qty=2))
    return out

work=[]
for expiry in cycles:
    entry=expiry-timedelta(days=3)
    for und in a.underlyings.split(","):
        try:
            for sp in build(und,entry,expiry): work.append((sp,entry))
        except Exception: pass
print(f"{len(work)} debit structures over {a.weeks} cycles\n")

def run():
    tot=0.0; fired=0
    for sp,entry in work:
        try: r=rp.replay(sp,entry)
        except Exception: continue
        tot+=r.final_pnl or 0
        if "harvest" in (r.exit_reason or ""): fired+=1
    return tot,fired

config.HARVEST_ENABLED=False
base,_=run()
print(f"{'edge_mult':>10} {'min_edge':>9} {'total P&L':>11} {'vs off':>9} {'fired':>6}")
print("-"*52)
print(f"{'OFF':>10} {'-':>9} {base:11,.0f} {0:9.0f} {0:6}")
config.HARVEST_ENABLED=True
best=None
config.HARVEST_EDGE_MULT=2.0; config.HARVEST_MIN_EDGE=50.0
print(f"\n{'edge/mark':>10} {'total P&L':>11} {'vs off':>9} {'fired':>6}")
print("-"*40)
print(f"{'OFF':>10} {base:11,.0f} {0:9.0f} {0:6}")
for frac in (0.0,0.10,0.15,0.20,0.25,0.30,0.40,0.50):
    config.HARVEST_MIN_EDGE_FRAC=frac
    t,f=run()
    print(f"{frac:10.0%} {t:11,.0f} {t-base:+9,.0f} {f:6}")
config.HARVEST_MIN_EDGE_FRAC=0.0
