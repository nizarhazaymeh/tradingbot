#!/usr/bin/env python3
"""Backtest the retest-barrier bonus AS WIRED — through strategy.propose().

docs/BACKTEST.md Part 6 measured the barrier as a hard FILTER: keep the trades
whose short strike sits behind a confirmed retested level, drop the rest. That is
not what ships. What ships is config.RETEST_BARRIER_BONUS, a 0.005 EV-ratio
tie-break inside strategy.propose() that can only REORDER candidates which have
already cleared the EV floor and every quality gate.

Those are different interventions and there is no reason to expect the same
number. A filter changes WHICH TRADES HAPPEN; a tie-break changes WHICH STRUCTURE
is chosen when a trade happens either way. This measures the second one.

  THE OBSTACLE. scripts/backtest.py never imports agent.strategy — it builds five
  fixed structures at fixed % offsets. It cannot test propose(), because propose()
  selects strikes by DELTA and the historical bars endpoint returns no Greeks.
  tests/test_strategy_selection.py says so in its docstring.

  THE FIX. Greeks are recovered from the prices themselves. For every contract
  with a bar on the entry date we solve Black-Scholes for the implied volatility
  that reproduces its close, then differentiate at that vol for delta, gamma,
  theta and vega. That turns a historical chain into something propose() can
  actually run against — the whole strategy layer becomes backtestable.

For each (underlying, expiry) the agent's real pipeline runs twice, identically
except for the knob:

    bonus OFF (0.000)  ->  propose() -> spread A
    bonus ON  (0.005)  ->  propose() -> spread B

When A and B are the same structure the bonus changed nothing and the entry is
recorded as untouched. When they differ, BOTH are replayed through the real exit
logic and the difference is the bonus's actual contribution.

  python scripts/backtest_bonus.py                 # all four regime windows
  python scripts/backtest_bonus.py --window calm   # one window
"""
import argparse
import json
import math
import statistics
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent import config, levels as L, options as O, regime as R, strategy as ST
from agent.client import AlpacaClient, AlpacaError
from agent.replay import Replayer

WINDOWS = [
    ("calm/rising",   date(2026, 8, 28), 6),
    ("vol spike 46%", date(2025, 5, 2),  5),
    ("selloff -7.7%", date(2026, 4, 3),  5),
    ("carry unwind",  date(2024, 8, 30), 5),
]
UNDS = ["SPY", "QQQ", "IWM"]
DTE = 4
RATE = 0.0          # r=0: over 4 days the carry is immaterial next to the spread


# ------------------------------------------------------- Black-Scholes, inverted
def _cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _pdf(x):
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def bs_price(spot, strike, iv, t, kind):
    if t <= 0 or iv <= 0:
        return max(spot - strike, 0.0) if kind == "C" else max(strike - spot, 0.0)
    vt = iv * math.sqrt(t)
    d1 = (math.log(spot / strike) + (RATE + 0.5 * iv * iv) * t) / vt
    d2 = d1 - vt
    if kind == "C":
        return spot * _cdf(d1) - strike * math.exp(-RATE * t) * _cdf(d2)
    return strike * math.exp(-RATE * t) * _cdf(-d2) - spot * _cdf(-d1)


def implied_vol(price, spot, strike, t, kind, lo=0.01, hi=5.0):
    """Bisection. Robust where Newton is not — near-zero vega on far OTM wings.

    Returns None when the price cannot be produced by any volatility, which
    happens for prices at or below intrinsic. Those contracts are dropped rather
    than clamped: a fabricated vol would feed a fabricated delta into strike
    selection, which is the one thing this harness exists to get right.
    """
    intrinsic = max(spot - strike, 0.0) if kind == "C" else max(strike - spot, 0.0)
    if price <= intrinsic + 1e-6 or t <= 0:
        return None
    if bs_price(spot, strike, hi, t, kind) < price:
        return None
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        if bs_price(spot, strike, mid, t, kind) < price:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def greeks(spot, strike, iv, t, kind):
    """(delta, gamma, theta_per_day, vega_per_point) at the solved vol."""
    vt = iv * math.sqrt(t)
    d1 = (math.log(spot / strike) + (RATE + 0.5 * iv * iv) * t) / vt
    d2 = d1 - vt
    delta = _cdf(d1) if kind == "C" else _cdf(d1) - 1.0
    gamma = _pdf(d1) / (spot * vt)
    theta_yr = -(spot * _pdf(d1) * iv) / (2 * math.sqrt(t))
    vega = spot * _pdf(d1) * math.sqrt(t)
    return delta, gamma, theta_yr / 365.0, vega / 100.0


# ------------------------------------------------------------------- the chain
def build_views(und, expiry, entry, spot, bars, strikes_by_kind):
    """Historical bars -> ContractViews with Greeks propose() can select on."""
    t = max((expiry - entry).days, 1) / 365.0
    out = []
    for (kind, strike), sym in strikes_by_kind.items():
        bar = bars.get(sym, {}).get(entry.isoformat())
        if not bar:
            continue
        px = float(bar["c"])
        if px <= 0.01:
            continue
        iv = implied_vol(px, spot, strike, t, kind)
        if iv is None or not (0.02 < iv < 3.0):
            continue
        d, g, th, v = greeks(spot, strike, iv, t, kind)
        out.append(O.ContractView(
            symbol=sym, root=und, expiry=expiry, kind=kind, strike=float(strike),
            dte=(expiry - entry).days, bid=px * 0.98, ask=px * 1.02, mid=px,
            spread_pct=0.04, delta=d, gamma=g, theta=th, vega=v, iv=iv,
            open_interest=5000))
    return out


def fridays(end, n):
    d = end
    while d.weekday() != 4:
        d -= timedelta(days=1)
    out = []
    for _ in range(n):
        out.append(d)
        d -= timedelta(days=7)
    return out


def market_context(rp, und, entry):
    """Bars up to and including the entry date -> (closes, breaks). No lookahead."""
    res = rp.c._data("/v2/stocks/bars", {
        "symbols": und, "timeframe": "1Day",
        "start": (entry - timedelta(days=520)).isoformat(),
        "end": entry.isoformat(), "limit": 10000, "adjustment": "all",
        "feed": config.STOCK_FEED})
    rows = [r for r in (res.get("bars") or {}).get(und, [])
            if r["t"][:10] <= entry.isoformat()]
    ohlc = L.bars_from_api(rows)
    if len(ohlc) < 60:
        return None, None
    try:
        brks = L.breaks(ohlc)
    except Exception:
        brks = []
    return [b.c for b in ohlc], brks


def propose_at(reg, views, expiry, budget, bonus):
    old = config.RETEST_BARRIER_BONUS
    config.RETEST_BARRIER_BONUS = bonus
    try:
        return ST.propose(reg, views, expiry, ST.View(), budget)
    finally:
        config.RETEST_BARRIER_BONUS = old


def sig(sp):
    if sp is None:
        return None
    return (sp.kind, tuple(sorted((l.symbol, l.side) for l in sp.legs)), sp.qty)


def stat(pnls):
    if not pnls:
        return None
    w = [p for p in pnls if p > 0]
    l = [p for p in pnls if p <= 0]
    gp, gl = sum(w), abs(sum(l))
    return {"n": len(pnls), "net": round(sum(pnls), 2), "win": len(w) / len(pnls),
            "pf": round(gp / gl, 2) if gl else None,
            "exp": round(statistics.mean(pnls), 2)}


SWEEP = [0.0, 0.005, 0.010, 0.020, 0.050, 0.100, 0.250]


def min_flip_bonus(reg, views, expiry, budget, base_sig):
    """The smallest bonus that changes the selection, by bisection on the knob.

    Reported because "the bonus did nothing" is only half an answer. The other
    half is HOW FAR it was from doing something — a knob that needs 50x its
    shipped value to matter is not conservatively tuned, it is switched off.
    """
    lo, hi = 0.0, 1.0
    if sig(propose_at(reg, views, expiry, budget, hi)[0]) == base_sig:
        return None                      # even an absurd bonus changes nothing
    for _ in range(24):
        mid = 0.5 * (lo + hi)
        if sig(propose_at(reg, views, expiry, budget, mid)[0]) == base_sig:
            lo = mid
        else:
            hi = mid
    return hi


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--window", default="", help="substring of one window label")
    ap.add_argument("--bonus", type=float, default=None,
                    help="override the ON value (default: config)")
    ap.add_argument("--sweep", action="store_true",
                    help="sweep the knob instead of testing one value")
    ap.add_argument("--out", default="docs/backtest_bonus.json")
    a = ap.parse_args()

    on_value = a.bonus if a.bonus is not None else config.RETEST_BARRIER_BONUS
    budget = config.RISK_PER_TRADE_PCT * 100_000
    rp = Replayer(AlpacaClient())
    wins = [w for w in WINDOWS if a.window.lower() in w[0].lower()]

    print(f"\n{'='*100}")
    print(f"  RETEST BONUS, AS WIRED — propose() run twice per entry, "
          f"bonus 0.000 vs {on_value:.3f}")
    print(f"{'='*100}")
    print(f"  Greeks are solved from the historical option prices (Black-Scholes")
    print(f"  inverted per contract), because propose() selects strikes by delta.")
    print(f"  {'entry':22} {'chosen with bonus OFF':32} {'effect':>28}")
    print(f"  {'-'*96}")

    rows, skipped, ctxs = [], 0, []
    for label, end, weeks in wins:
        for expiry in fridays(end, weeks):
            entry = expiry - timedelta(days=DTE)
            for und in UNDS:
                try:
                    closes_map = rp.stock_closes(
                        und, (entry - timedelta(days=6)).isoformat(),
                        rp.safe_end(expiry))
                except Exception:
                    skipped += 1
                    continue
                spot = closes_map.get(entry.isoformat())
                if not spot:
                    skipped += 1
                    continue
                lo, hi = int(spot * 0.94), int(spot * 1.06)
                cand = {(k, float(st)): O.occ(und, expiry, k, st)
                        for k in ("C", "P") for st in range(lo, hi + 1)}
                try:
                    bars = rp.option_bars(list(cand.values()),
                                          (entry - timedelta(days=1)).isoformat(),
                                          rp.safe_end(expiry))
                except Exception:
                    skipped += 1
                    continue
                cand = {k: v for k, v in cand.items() if v in bars}
                views = build_views(und, expiry, entry, spot, bars, cand)
                if len(views) < 12:
                    skipped += 1
                    continue

                closes, brks = market_context(rp, und, entry)
                if not closes:
                    skipped += 1
                    continue

                # The real classifier, on data that existed at entry.
                reg = R.classify(und, spot, views, closes, expiry=expiry,
                                 breaks=brks)
                off, why_off = propose_at(reg, views, expiry, budget, 0.0)
                on, why_on = propose_at(reg, views, expiry, budget, on_value)
                ctxs.append({"label": label, "und": und, "entry": entry,
                             "expiry": expiry, "reg": reg, "views": views,
                             "base": off})

                tag = f"{und} {entry}"
                if off is None and on is None:
                    print(f"  {tag:22} {'(stood aside)':32} "
                          f"{why_off[:28]:>28}")
                    continue
                if sig(off) == sig(on):
                    print(f"  {tag:22} {off.kind + ' ' + off.describe()[:26]:32} "
                          f"{'unchanged':>28}")
                    continue

                # The bonus moved the selection. Replay both.
                try:
                    r_off = rp.replay(off, entry) if off else None
                    r_on = rp.replay(on, entry) if on else None
                except Exception as e:
                    print(f"  {tag:22} {'CHANGED':32} "
                          f"{'replay failed: ' + type(e).__name__:>28}")
                    continue
                p_off = r_off.final_pnl if r_off else 0.0
                p_on = r_on.final_pnl if r_on else 0.0
                rows.append({"window": label, "underlying": und,
                             "entry": entry.isoformat(), "expiry": expiry.isoformat(),
                             "off": off.describe() if off else None,
                             "on": on.describe() if on else None,
                             "pnl_off": p_off, "pnl_on": p_on,
                             "delta": round(p_on - p_off, 2)})
                mark = "  <-" if p_on > p_off else ""
                print(f"  {tag:22} {(off.kind if off else '—')[:32]:32} "
                      f"{f'CHANGED  {p_off:+.0f} -> {p_on:+.0f}':>28}{mark}")

    print(f"  {'-'*96}")
    changed = len(rows)
    print(f"\n  the bonus changed the chosen structure {changed} time(s)"
          f"{f' ({skipped} entries skipped for data)' if skipped else ''}")
    if not changed:
        print("\n  With no selection changed, the bonus had NO effect on this sample.")
        print("  That is a real result: a 0.005 tie-break is smaller than the EV gaps")
        print("  between candidates here, so it never decided anything.\n")
    else:
        off_t = [r["pnl_off"] for r in rows]
        on_t = [r["pnl_on"] for r in rows]
        s_off, s_on = stat(off_t), stat(on_t)
        print(f"\n{'='*100}")
        print("  ONLY THE ENTRIES IT CHANGED — everything else is identical by construction")
        print(f"{'='*100}")
        print(f"  {'':10} {'n':>4} {'win%':>6} {'net $':>10} {'    PF':>7} {'per trade':>11}")
        for name, s in (("bonus OFF", s_off), ("bonus ON", s_on)):
            pf = f"{s['pf']:>7.2f}" if s["pf"] is not None else "      —"
            print(f"  {name:10} {s['n']:>4} {s['win']*100:>5.0f}% {s['net']:>+10.0f} "
                  f"{pf} {s['exp']:>+11.2f}")
        d = s_on["net"] - s_off["net"]
        print(f"\n  net effect of the bonus: {d:+.0f} over {changed} changed entries "
              f"({d/changed:+.2f} each)")
        by = {}
        for r in rows:
            by.setdefault(r["window"], []).append(r["delta"])
        print("\n  by window:")
        for w, ds in by.items():
            print(f"    {w:16} {len(ds):>2} changed   {sum(ds):>+8.0f}")

    sweep_out = []
    if a.sweep:
        print(f"\n{'='*100}")
        print("  KNOB SWEEP — how large does the bonus have to be before it decides anything?")
        print(f"{'='*100}")
        print(f"  {'bonus':>8} {'entries changed':>16} {'net effect $':>14}  {'verdict':30}")
        print(f"  {'-'*96}")
        for b in SWEEP:
            ch, delta = 0, 0.0
            for c in ctxs:
                if c["base"] is None:
                    continue
                alt, _ = propose_at(c["reg"], c["views"], c["expiry"], budget, b)
                if sig(alt) == sig(c["base"]):
                    continue
                ch += 1
                try:
                    pa = rp.replay(c["base"], c["entry"]).final_pnl
                    pb = rp.replay(alt, c["entry"]).final_pnl if alt else 0.0
                except Exception:
                    continue
                delta += pb - pa
            verdict = ("inert — never decides" if ch == 0 else
                       f"{'helps' if delta > 0 else 'hurts'}")
            print(f"  {b:>8.3f} {ch:>16} {delta:>+14.0f}  {verdict:30}")
            sweep_out.append({"bonus": b, "changed": ch, "net": round(delta, 2)})

        flips = [min_flip_bonus(c["reg"], c["views"], c["expiry"], budget,
                                sig(c["base"]))
                 for c in ctxs if c["base"] is not None]
        real = sorted(f for f in flips if f is not None)
        print(f"\n  smallest bonus that would change each entry's choice:")
        if real:
            print(f"    {len(real)} of {len(flips)} entries are flippable at all; "
                  f"median {statistics.median(real):.3f}, min {real[0]:.3f}")
            print(f"    shipped value is {config.RETEST_BARRIER_BONUS:.3f} — "
                  f"{'below' if real[0] > config.RETEST_BARRIER_BONUS else 'above'} "
                  f"the cheapest flip in the sample")
        else:
            print(f"    none — no entry changes at any bonus up to 1.0")

    Path(ROOT / a.out).write_text(json.dumps(
        {"bonus": on_value, "dte": DTE, "changed": changed, "rows": rows,
         "sweep": sweep_out}, indent=2))
    print(f"\n  wrote {a.out}\n")


if __name__ == "__main__":
    main()
