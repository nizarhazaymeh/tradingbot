#!/usr/bin/env python3
"""The full pipeline over two years of weekly expiries, net of transaction costs.

Every result in docs/BACKTEST.md Parts 1-8 rests on 19 entry dates. The
competition added 14 live trades. Neither can settle anything — the honest
reading of both is "provisional". This is the harness that stops that being true.

For every Friday expiry in the range, for every underlying, it runs the REAL
pipeline the live agent runs:

    regime.classify()  ->  strategy.propose()  ->  Replayer.replay()

using the historical chain with Greeks recovered by inverting Black-Scholes
(scripts/backtest_bonus.py), bars strictly up to the entry date, and the real
exit logic. Nothing is fixed-offset; the agent picks its own strikes by delta,
exactly as it does live.

Two things the earlier harnesses did not do:

  TRANSACTION COSTS. expectancy.round_trip_cost() is charged on every trade:
  every leg crossed twice at the full synthetic spread. The competition finding
  that "EV must be net of the bid/ask you cross twice" (9e0990b) applies to the
  history as well as the live gate, and gross numbers flatter everything.

  THE TREND FILTER A/B. Part 5 found the side filter blocks the better bucket on
  both sides over 19 dates — with a mechanism, since a downtrend is when put
  premium is richest. propose() is run twice per entry, TREND_SIDE_FILTER on and
  off, so the rule is judged on ~300 entries instead of 19.

  python scripts/backtest_full.py                       # 2024-08 -> 2026-08, SPY/QQQ/IWM
  python scripts/backtest_full.py --start 2025-09-01    # last year only
  python scripts/backtest_full.py --universe SPY,QQQ,IWM,DIA
"""
import argparse
import importlib.util
import json
import statistics
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent import config, expectancy as EX, options as O, regime as R, strategy as ST
from agent.client import AlpacaClient
from agent.replay import Replayer

_spec = importlib.util.spec_from_file_location("bb", ROOT / "scripts" / "backtest_bonus.py")
_bb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_bb)
build_views, market_context, sig = _bb.build_views, _bb.market_context, _bb.sig


def fridays_between(start: date, end: date):
    d = start
    while d.weekday() != 4:
        d += timedelta(days=1)
    while d <= end:
        yield d
        d += timedelta(days=7)


def propose_with(reg, views, expiry, budget, side_filter: bool):
    old = config.TREND_SIDE_FILTER
    config.TREND_SIDE_FILTER = side_filter
    try:
        return ST.propose(reg, views, expiry, ST.View(), budget)
    finally:
        config.TREND_SIDE_FILTER = old


def stat(rows, key="net"):
    if not rows:
        return None
    p = [r[key] for r in rows]
    w = [x for x in p if x > 0]
    l = [x for x in p if x <= 0]
    gp, gl = sum(w), abs(sum(l))
    return {"n": len(p), "net": round(sum(p), 2), "win": len(w) / len(p),
            "pf": round(gp / gl, 2) if gl else None,
            "exp": round(statistics.mean(p), 2),
            "worst": round(min(p), 2)}


def row(label, s, w=28):
    if not s:
        print(f"  {label:{w}} —")
        return
    pf = f"{s['pf']:>6.2f}" if s["pf"] is not None else "     —"
    print(f"  {label:{w}} {s['n']:>4} {s['win']*100:>4.0f}% {s['net']:>+9.0f} {pf} "
          f"{s['exp']:>+8.2f} {s['worst']:>+8.0f}")


def header(title):
    print(f"\n{'='*96}\n  {title}\n{'='*96}")
    print(f"  {'':28} {'n':>4} {'win%':>5} {'net $':>9} {'    PF':>6} {'/trade':>8} {'worst':>8}")
    print(f"  {'-'*92}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2024-08-01")
    ap.add_argument("--end", default=(date.today() - timedelta(days=8)).isoformat())
    ap.add_argument("--universe", default="SPY,QQQ,IWM")
    ap.add_argument("--dte", type=int, default=config.TARGET_DTE)
    ap.add_argument("--out", default="docs/backtest_full.json")
    a = ap.parse_args()

    unds = [u.strip().upper() for u in a.universe.split(",") if u.strip()]
    budget = config.RISK_PER_TRADE_PCT * 100_000
    rp = Replayer(AlpacaClient())
    expiries = list(fridays_between(date.fromisoformat(a.start), date.fromisoformat(a.end)))
    print(f"\n{len(expiries)} weekly expiries x {len(unds)} underlyings, {a.dte} DTE, "
          f"budget ${budget:,.0f}/trade")
    print("first run fetches from the API; re-runs are disk-cached under .cache/replay/\n")

    trades, aside, ab_rows, skipped = [], [], [], 0
    for n, expiry in enumerate(expiries, 1):
        entry = expiry - timedelta(days=a.dte)
        for und in unds:
            try:
                closes_map = rp.stock_closes(und, (entry - timedelta(days=6)).isoformat(),
                                             rp.safe_end(expiry))
                spot = closes_map.get(entry.isoformat())
                if not spot:
                    skipped += 1
                    continue
                lo, hi = int(spot * 0.94), int(spot * 1.06)
                cand = {(k, float(st)): O.occ(und, expiry, k, st)
                        for k in ("C", "P") for st in range(lo, hi + 1)}
                bars = rp.option_bars(list(cand.values()),
                                      (entry - timedelta(days=1)).isoformat(),
                                      rp.safe_end(expiry))
                cand = {k: v for k, v in cand.items() if v in bars}
                views = build_views(und, expiry, entry, spot, bars, cand)
                if len(views) < 12:
                    skipped += 1
                    continue
                closes, brks = market_context(rp, und, entry)
                if not closes:
                    skipped += 1
                    continue
                reg = R.classify(und, spot, views, closes, expiry=expiry, breaks=brks)
                rv = (reg.detail or {}).get("realized_vol") or 0.0

                sp_on, why_on = propose_with(reg, views, expiry, budget, True)
                sp_off, why_off = propose_with(reg, views, expiry, budget, False)

                def settle(sp):
                    if sp is None:
                        return None
                    r = rp.replay(sp, entry)
                    cost = EX.round_trip_cost(sp) * max(sp.qty, 1)
                    return {"und": und, "expiry": expiry.isoformat(), "entry": entry.isoformat(),
                            "year": str(entry.year), "kind": sp.kind,
                            "credit": bool(sp.is_credit), "regime": reg.name,
                            "trend_dir": reg.trend_dir, "iv": round(reg.iv, 4),
                            "rv": round(rv, 4), "qty": sp.qty,
                            "max_loss": round(r.max_loss, 2), "gross": r.final_pnl,
                            "cost": round(cost, 2), "net": round(r.final_pnl - cost, 2),
                            "exit": r.exit_reason[:40], "describe": sp.describe()}

                t_on = settle(sp_on)
                if t_on:
                    trades.append(t_on)
                else:
                    aside.append({"und": und, "entry": entry.isoformat(),
                                  "regime": reg.name, "why": why_on[:80]})
                # the A/B: only entries where the knob changed the outcome matter
                if sig(sp_on) != sig(sp_off):
                    t_off = settle(sp_off)
                    ab_rows.append({"und": und, "entry": entry.isoformat(),
                                    "regime": reg.name, "trend_dir": reg.trend_dir,
                                    "on": t_on, "off": t_off})
            except Exception as e:
                skipped += 1
                print(f"  {und} {entry}: skip ({type(e).__name__}: {str(e)[:50]})")
        print(f"  [{n:>3}/{len(expiries)}] {expiry}  trades so far {len(trades)}", end="\r")
    print(" " * 80, end="\r")

    # ------------------------------------------------------------------ report
    header(f"FULL PIPELINE — {len(trades)} trades, {len(aside)} stood aside, "
           f"{skipped} skipped for data")
    row("gross (no costs)", stat(trades, "gross"))
    row("NET of round-trip spread", stat(trades))
    tot_cost = sum(t["cost"] for t in trades)
    print(f"\n  transaction costs paid: ${tot_cost:,.0f} over {len(trades)} trades "
          f"(${tot_cost / max(len(trades), 1):,.0f} each)")

    header("BY YEAR (net)")
    for y in sorted({t["year"] for t in trades}):
        row(y, stat([t for t in trades if t["year"] == y]))

    header("CREDIT vs DEBIT (net) — the competition's lesson, at scale")
    row("credit structures", stat([t for t in trades if t["credit"]]))
    row("debit structures", stat([t for t in trades if not t["credit"]]))

    header("BY STRUCTURE (net)")
    for k in sorted({t["kind"] for t in trades}):
        row(k, stat([t for t in trades if t["kind"] == k]))

    header("BY REGIME (net)")
    for k in sorted({t["regime"] for t in trades}):
        row(k, stat([t for t in trades if t["regime"] == k]))

    header("BY UNDERLYING (net)")
    for u in unds:
        row(u, stat([t for t in trades if t["und"] == u]))

    header(f"TREND SIDE FILTER A/B — {len(ab_rows)} entries where the knob changed the pick")
    on = [r["on"] for r in ab_rows if r["on"]]
    off = [r["off"] for r in ab_rows if r["off"]]
    row("filter ON  (shipped)", stat(on))
    row("filter OFF", stat(off))
    on_net = sum(t["net"] for t in on)
    off_net = sum(t["net"] for t in off)
    print(f"\n  filter's net contribution over those entries: {on_net - off_net:+,.0f}")
    print(f"  (positive = the filter helped; negative = it cost money)")
    if ab_rows:
        by = defaultdict(lambda: {"on": 0.0, "off": 0.0, "n": 0})
        for r in ab_rows:
            k = "uptrend (blocks calls)" if r["trend_dir"] > 0 else "downtrend (blocks puts)"
            by[k]["n"] += 1
            by[k]["on"] += r["on"]["net"] if r["on"] else 0.0
            by[k]["off"] += r["off"]["net"] if r["off"] else 0.0
        print()
        for k, v in by.items():
            print(f"  {k:26} n={v['n']:>3}  on {v['on']:>+8.0f}  off {v['off']:>+8.0f}  "
                  f"filter {v['on'] - v['off']:>+8.0f}")

    Path(ROOT / a.out).write_text(json.dumps(
        {"start": a.start, "end": a.end, "universe": unds, "dte": a.dte,
         "trades": trades, "stood_aside": aside, "trend_ab": ab_rows},
        indent=1, default=str))
    print(f"\n  wrote {a.out}\n")


if __name__ == "__main__":
    main()
