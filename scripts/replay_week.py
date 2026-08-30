#!/usr/bin/env python3
"""Replay real spreads through the agent's exit logic over a past expiry cycle."""
import sys, os, argparse
from datetime import date, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.client import AlpacaClient
from agent import options as O, spreads as S
from agent.replay import Replayer

ap = argparse.ArgumentParser()
ap.add_argument("--underlying", default="SPY")
ap.add_argument("--entry", default="2026-08-24")
ap.add_argument("--expiry", default="2026-08-28")
a = ap.parse_args()

ENTRY, EXPIRY, UND = (date.fromisoformat(a.entry), date.fromisoformat(a.expiry),
                      a.underlying)
c = AlpacaClient(); rp = Replayer(c)

closes = rp.stock_closes(UND, (ENTRY - timedelta(days=5)).isoformat(),
                         rp.safe_end(EXPIRY))
spot_entry = closes.get(ENTRY.isoformat())
spot_exp = closes.get(EXPIRY.isoformat())
dte = (EXPIRY - ENTRY).days
print(f"{UND}: ${spot_entry:.2f} on {ENTRY}  ->  ${spot_exp:.2f} on {EXPIRY}  "
      f"({(spot_exp/spot_entry-1)*100:+.2f}%, {dte} DTE)\n")

# Expired contracts are NOT returned by /v2/options/contracts (it lists active
# ones only), so construct the OCC symbols directly and let the bars endpoint
# tell us which actually existed and traded.
lo, hi = int(spot_entry*0.93), int(spot_entry*1.07)
by_strike = {}
for k in ("C", "P"):
    for strike in range(lo, hi + 1):
        by_strike[(k, float(strike))] = O.occ(UND, EXPIRY, k, strike)
syms = list(by_strike.values())
print(f"probing {len(syms)} candidate contracts for {EXPIRY}...")
bars = rp.option_bars(syms, (ENTRY-timedelta(days=1)).isoformat(),
                      rp.safe_end(EXPIRY))
traded = {k: v for k, v in by_strike.items() if v in bars}
by_strike = traded
print(f"  -> {len(by_strike)} actually traded")
def px(sym):
    b = bars.get(sym, {}).get(ENTRY.isoformat())
    return float(b["c"]) if b else None

def cview(kind, strike):
    sym = by_strike.get((kind, strike))
    if not sym: return None
    p = px(sym)
    if p is None or p <= 0: return None
    return O.ContractView(symbol=sym, root=UND, expiry=EXPIRY, kind=kind, strike=strike,
                          dte=dte, bid=p*0.98, ask=p*1.02, mid=p, spread_pct=0.04,
                          delta=0.2 if kind=="C" else -0.2, gamma=0.01, theta=-0.1,
                          vega=0.1, iv=0.15, open_interest=5000)

strikes = sorted({s for (_, s) in by_strike})
if not strikes:
    sys.exit("no historical option bars for that expiry")
def nearest(target): return min(strikes, key=lambda s: abs(s-target))

results = []
# a spread at several distances from spot, both sides
for label, kind, offset, width in [
    ("put credit  1.5% OTM", "P", -0.015, 5),
    ("put credit  3.0% OTM", "P", -0.030, 5),
    ("call credit 1.5% OTM", "C",  0.015, 5),
    ("call credit 3.0% OTM", "C",  0.030, 5),
]:
    sk = nearest(spot_entry*(1+offset))
    lk = nearest(sk - width) if kind=="P" else nearest(sk + width)
    short, long_ = cview(kind, sk), cview(kind, lk)
    if not short or not long_ or short.strike == long_.strike:
        print(f"  skip {label}: no data"); continue
    sp = S.bull_put_spread(short, long_) if kind=="P" else S.bear_call_spread(short, long_)
    if sp.max_loss_per_unit <= 0: continue
    try:
        r = rp.replay(sp, ENTRY)
        results.append((label, r))
    except Exception as e:
        print(f"  skip {label}: {e}")

# an iron condor too
spk, sck = nearest(spot_entry*0.978), nearest(spot_entry*1.022)
lp, sp_, sc, lc = (cview("P", nearest(spk-5)), cview("P", spk),
                   cview("C", sck), cview("C", nearest(sck+5)))
if all([lp, sp_, sc, lc]):
    cond = S.iron_condor(lp, sp_, sc, lc)
    try: results.append(("iron condor ±2.2%", rp.replay(cond, ENTRY)))
    except Exception as e: print("  skip condor:", e)

print(f"\n{'structure':22} {'entry':>7} {'exit day':>11} {'P&L':>9} {'outcome':>7}  exit reason")
print("-"*104)
total = 0.0
for label, r in results:
    total += r.final_pnl
    out = "WIN" if r.final_pnl > 0 else "LOSS" if r.final_pnl < 0 else "FLAT"
    print(f"{label:22} {r.entry_price:+7.2f} {str(r.exit_day):>11} "
          f"{r.final_pnl:+9.0f} {out:>7}  {r.exit_reason[:44]}")

wins = sum(1 for _, r in results if r.final_pnl > 0)
print(f"\n{len(results)} structures | {wins} wins | net ${total:+.0f}")
print("\nday-by-day for the first structure:")
if results:
    for s in results[0][1].steps:
        print(f"   {s.day} DTE{s.dte}  {UND} ${s.underlying_price or 0:7.2f}  "
              f"mark {s.mark:+6.2f}  P&L ${s.pnl:+7.0f}  -> {s.action}"
              + (f" ({s.reason[:40]})" if s.action != "hold" else ""))
