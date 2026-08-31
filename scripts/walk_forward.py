#!/usr/bin/env python3
"""Walk-forward parameter fitting: does training on history actually help?

scripts/sweep.py fits parameters across all four regimes POOLED and reports the
best. That is in-sample fitting, and docs/BACKTEST.md's addendum shows where it
leads: the resulting filters improve results only in the window they were fitted
on, turning +$157 into -$978 in Aug 2024.

This asks the question that matters instead. For each market regime, fit the
exit and entry parameters on the OTHER THREE, then evaluate the winner on the
held-out one. Leave-one-out, so every number reported for a window was produced
by parameters that never saw it.

Three results per fold:

  shipped     the config as committed — the honest baseline
  fitted      best on the training folds, measured out-of-sample on the test fold
  oracle      best on the TEST fold itself — unreachable, and the gap between
              oracle and fitted is the cost of not knowing the future

If `fitted` does not beat `shipped` out-of-sample, training does not help and
the parameters should stay where judgement put them.

  python scripts/walk_forward.py                      # default grid
  python scripts/walk_forward.py --quick              # small grid, for a smoke test
"""
import argparse
import itertools
import json
import statistics
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent import config, options as O, spreads as S
from agent.client import AlpacaClient
from agent.replay import Replayer

# Same four regimes sweep.py uses, so results are comparable.
REGIMES = [
    ("calm/rising",   date(2026, 8, 28), 6),
    ("vol spike 46%", date(2025, 5, 2),  5),
    ("selloff -7.7%", date(2026, 4, 3),  5),
    ("carry unwind",  date(2024, 8, 30), 5),
]
UNDS = ["SPY", "QQQ", "IWM"]
DTE = 4                       # fixed: changing it moves the entry date and the fetch

GRID = {
    "tp_credit": [0.25, 0.35, 0.50, 0.65],
    "stop_mult": [1.00, 1.50, 2.00, 2.50],
    "offset":    [0.015, 0.022, 0.030],
}
QUICK = {"tp_credit": [0.35, 0.50], "stop_mult": [1.50, 2.50], "offset": [0.022]}

SHIPPED = {"tp_credit": config.TAKE_PROFIT_CREDIT,
           "stop_mult": config.STOP_CREDIT_MULT,
           "offset": 0.022}


def fridays(end, n):
    d = end
    while d.weekday() != 4:
        d -= timedelta(days=1)
    out = []
    for _ in range(n):
        out.append(d)
        d -= timedelta(days=7)
    return out


def stat(pnls):
    if not pnls:
        return None
    w = [p for p in pnls if p > 0]
    l = [p for p in pnls if p <= 0]
    gp, gl = sum(w), abs(sum(l))
    return {"n": len(pnls), "net": round(sum(pnls), 2),
            "win": len(w) / len(pnls),
            "pf": round(gp / gl, 2) if gl else None,
            "exp": round(statistics.mean(pnls), 2)}


def score(s):
    """Rank by expectancy per trade, not net.

    Net rewards whichever parameter set happened to take more trades. Expectancy
    asks whether each trade was worth taking, which is the question a parameter
    should answer. A set with under 8 trades is not ranked at all.
    """
    if not s or s["n"] < 8:
        return -1e9
    return s["exp"]


def build_universe(rp, quick=False):
    """Every (regime, underlying, expiry, offset) -> spread, built once.

    Exit parameters do not change which structure is opened, only when it is
    closed, so the structures are built once and replayed many times.
    """
    offsets = (QUICK if quick else GRID)["offset"]
    out = []
    for label, end, weeks in REGIMES:
        for expiry in fridays(end, weeks):
            entry = expiry - timedelta(days=DTE)
            for und in UNDS:
                try:
                    closes = rp.stock_closes(und, (entry - timedelta(days=6)).isoformat(),
                                             rp.safe_end(expiry))
                except Exception:
                    continue
                spot = closes.get(entry.isoformat())
                if not spot:
                    continue
                lo, hi = int(spot * 0.94), int(spot * 1.06)
                cand = {(k, float(st)): O.occ(und, expiry, k, st)
                        for k in ("C", "P") for st in range(lo, hi + 1)}
                try:
                    bars = rp.option_bars(list(cand.values()),
                                          (entry - timedelta(days=1)).isoformat(),
                                          rp.safe_end(expiry))
                except Exception:
                    continue
                cand = {k: v for k, v in cand.items() if v in bars}
                strikes = sorted({s for _, s in cand})
                if len(strikes) < 12:
                    continue

                def near(t):
                    return min(strikes, key=lambda s: abs(s - t))

                def cv(kind, strike):
                    sym = cand.get((kind, strike))
                    if not sym:
                        return None
                    b = bars.get(sym, {}).get(entry.isoformat())
                    if not b or float(b["c"]) <= 0:
                        return None
                    p = float(b["c"])
                    return O.ContractView(symbol=sym, root=und, expiry=expiry, kind=kind,
                                          strike=strike, dte=DTE, bid=p * 0.98,
                                          ask=p * 1.02, mid=p, spread_pct=0.04,
                                          delta=0.2 if kind == "C" else -0.2, gamma=0.01,
                                          theta=-0.1, vega=0.1, iv=0.15,
                                          open_interest=5000)

                for off in offsets:
                    sk = near(spot * (1 - off))
                    lk = near(sk - 5)
                    sh, lg = cv("P", sk), cv("P", lk)
                    if not sh or not lg or sh.strike == lg.strike:
                        continue
                    sp = S.bull_put_spread(sh, lg)
                    if sp.max_loss_per_unit <= 0 or abs(sp.net_price) <= 0.01:
                        continue
                    out.append({"regime": label, "und": und, "expiry": expiry,
                                "entry": entry, "offset": off, "spread": sp})
    return out


def evaluate(rp, universe, tp_credit, stop_mult, offset):
    """PnL per regime under one parameter set."""
    old = (config.TAKE_PROFIT_CREDIT, config.STOP_CREDIT_MULT)
    config.TAKE_PROFIT_CREDIT = tp_credit
    config.STOP_CREDIT_MULT = stop_mult
    by_regime = {}
    try:
        for row in universe:
            if row["offset"] != offset:
                continue
            try:
                r = rp.replay(row["spread"], row["entry"])
            except Exception:
                continue
            by_regime.setdefault(row["regime"], []).append(r.final_pnl)
    finally:
        config.TAKE_PROFIT_CREDIT, config.STOP_CREDIT_MULT = old
    return by_regime


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--out", default="docs/walk_forward.json")
    a = ap.parse_args()
    grid = QUICK if a.quick else GRID

    rp = Replayer(AlpacaClient())
    print("\nbuilding trade universe (first run fetches; then disk-cached)...")
    universe = build_universe(rp, quick=a.quick)
    print(f"  {len(universe)} structures across {len(REGIMES)} regimes, "
          f"{len(set(r['offset'] for r in universe))} offset(s)")
    if not universe:
        sys.exit("no structures built — check data access")

    combos = list(itertools.product(grid["tp_credit"], grid["stop_mult"], grid["offset"]))
    print(f"\nevaluating {len(combos)} parameter sets over every regime...")
    results = {}
    for i, (tp, sm, off) in enumerate(combos, 1):
        results[(tp, sm, off)] = evaluate(rp, universe, tp, sm, off)
        print(f"  [{i:>3}/{len(combos)}] tp={tp:.2f} stop={sm:.2f} off={off:.3f}", end="\r")
    print(" " * 70, end="\r")

    regimes = [r[0] for r in REGIMES]

    def pooled(combo, keys):
        p = []
        for k in keys:
            p += results[combo].get(k, [])
        return stat(p)

    print(f"\n{'='*104}")
    print("  LEAVE-ONE-REGIME-OUT — parameters fitted on three, measured on the fourth")
    print(f"{'='*104}")
    print(f"  {'test regime':16} {'source':9} {'tp':>5} {'stop':>5} {'off':>6} "
          f"{'n':>4} {'win%':>5} {'net':>8} {'  PF':>6} {'per trade':>10}")
    print(f"  {'-'*100}")

    summary = []
    for test in regimes:
        train = [r for r in regimes if r != test]
        fitted = max(combos, key=lambda c: score(pooled(c, train)))
        oracle = max(combos, key=lambda c: score(pooled(c, [test])))
        shipped = (SHIPPED["tp_credit"], SHIPPED["stop_mult"], SHIPPED["offset"])
        if shipped not in results:
            shipped = min(combos, key=lambda c: (abs(c[0] - SHIPPED["tp_credit"]),
                                                 abs(c[1] - SHIPPED["stop_mult"]),
                                                 abs(c[2] - SHIPPED["offset"])))
        rows = [("shipped", shipped), ("fitted", fitted), ("oracle", oracle)]
        for name, combo in rows:
            s = pooled(combo, [test])
            if not s:
                print(f"  {test:16} {name:9} — no trades")
                continue
            win = f"{s['win']*100:4.0f}%"
            pf = f"{s['pf']:>6.2f}" if s["pf"] is not None else "     —"
            mark = "  <-" if name == "fitted" else ""
            print(f"  {test:16} {name:9} {combo[0]:>5.2f} {combo[1]:>5.2f} {combo[2]:>6.3f} "
                  f"{s['n']:>4} {win} {s['net']:>+8.0f} {pf} {s['exp']:>+10.2f}{mark}")
        sh, fi = pooled(shipped, [test]), pooled(fitted, [test])
        if sh and fi:
            summary.append({"regime": test, "shipped": sh, "fitted": fi,
                            "fitted_params": fitted, "shipped_params": shipped,
                            "oracle": pooled(oracle, [test]), "oracle_params": oracle})
        print(f"  {'-'*100}")

    print(f"\n{'='*104}")
    print("  VERDICT — did fitting beat the shipped config out-of-sample?")
    print(f"{'='*104}")
    wins = 0
    for r in summary:
        d_net = r["fitted"]["net"] - r["shipped"]["net"]
        d_exp = r["fitted"]["exp"] - r["shipped"]["exp"]
        better = d_exp > 0
        wins += better
        print(f"  {r['regime']:16} net {d_net:>+8.0f}   per-trade {d_exp:>+7.2f}   "
              f"{'fitting helped' if better else 'fitting HURT or tied'}")
    print(f"\n  fitting beat the shipped config in {wins} of {len(summary)} regimes")
    if summary:
        tot_sh = sum(r["shipped"]["net"] for r in summary)
        tot_fi = sum(r["fitted"]["net"] for r in summary)
        tot_or = sum(r["oracle"]["net"] for r in summary)
        print(f"  totals — shipped {tot_sh:+.0f} · fitted {tot_fi:+.0f} · "
              f"oracle {tot_or:+.0f} (unreachable)")
        print(f"  cost of not knowing the future: {tot_or - tot_fi:+.0f}")

    Path(ROOT / a.out).write_text(json.dumps(
        {"grid": grid, "dte": DTE, "shipped": SHIPPED,
         "folds": [{**r, "fitted_params": list(r["fitted_params"]),
                    "shipped_params": list(r["shipped_params"]),
                    "oracle_params": list(r["oracle_params"])} for r in summary]},
        indent=2, default=str))
    print(f"\n  wrote {a.out}\n")


if __name__ == "__main__":
    main()
