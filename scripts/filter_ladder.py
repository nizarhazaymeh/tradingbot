#!/usr/bin/env python3
"""Apply the agent's admission filters to recorded backtest trades.

scripts/backtest.py runs all five strategies at every expiry unconditionally and
records every result. The filter ladder in docs/BACKTEST.md (naive -> +VRP ->
+trend) was computed outside the repo and could not be reproduced from committed
code. This is that computation, and it adds the stage this exists to measure:
does corroborating the z-score trend with swing structure help or hurt?

The live rule being modelled is strategy.candidates(): it sells only the side the
trend moves away from.

    direction  +1 (up)    -> no short calls
    direction  -1 (down)  -> no short puts
    direction   0         -> everything is admitted

Structure changes only what `direction` comes out as. regime.trend_score() now
requires the z-score and levels.market_structure() to agree before it reports a
direction at all.

No lookahead: bars are fetched strictly up to and including the entry date, so
every number here was available when the trade was opened.

  python scripts/filter_ladder.py
  python scripts/filter_ladder.py --in docs/backtest_aug2024.json
"""
import argparse
import json
import statistics
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent import config, levels as L
from agent.client import AlpacaClient, AlpacaError
from agent.regime import trend_score

CALL_STRATS = ("call_credit_1.5", "call_credit_3.0")
PUT_STRATS = ("put_credit_1.5", "put_credit_3.0")


def stats(rs):
    if not rs:
        return {"trades": 0, "net": 0.0, "win": None, "pf": None, "exp": 0.0}
    p = [x["pnl"] for x in rs]
    w = [x for x in p if x > 0]
    l = [x for x in p if x <= 0]
    gp, gl = sum(w), abs(sum(l))
    return {"trades": len(p), "net": round(sum(p), 2),
            "win": len(w) / len(p),
            "pf": round(gp / gl, 2) if gl else None,
            "exp": round(statistics.mean(p), 2)}


def row(label, s, base=None):
    win = f"{s['win']*100:4.0f}%" if s["win"] is not None else "   —"
    pf = f"{s['pf']:>5.2f}" if s["pf"] is not None else "    —"
    delta = ""
    if base and base["trades"]:
        d = s["net"] - base["net"]
        delta = f"  {d:+8.0f}"
    print(f"  {label:34} {s['trades']:>4} {win} {s['net']:>+9.0f} {pf} "
          f"{s['exp']:>+8.2f}{delta}")


def market_context(c, underlying, entry):
    """(z, z_direction, structure, corroborated_direction) as of `entry`.

    Uses only bars that had closed by the entry date.
    """
    start = (entry - timedelta(days=520)).isoformat()      # ~300 trading days
    res = c._data("/v2/stocks/bars", {
        "symbols": underlying, "timeframe": "1Day", "start": start,
        "end": entry.isoformat(), "limit": 10000, "adjustment": "all",
        "feed": config.STOCK_FEED})
    rows = (res.get("bars") or {}).get(underlying, [])
    rows = [r for r in rows if r["t"][:10] <= entry.isoformat()]
    ohlc = L.bars_from_api(rows)
    closes = [b.c for b in ohlc]
    if len(closes) < 60:
        return None
    z, zdir = trend_score(closes)
    try:
        struct = L.market_structure(L.pivots(ohlc))
    except Exception:
        struct = None
    _, cdir = trend_score(closes, structure=struct)
    return {"z": round(z, 2), "zdir": zdir, "structure": struct, "cdir": cdir}


def admitted(trade, direction, rule="side"):
    """Whether the trend filter admits this trade.

    Two rules, because the repo documents one and implements the other:

      "calls"  docs/BACKTEST.md's wording — "no short calls into an uptrend".
               Only ever excludes call spreads.
      "side"   what strategy.candidates() actually does — sells only the side
               the trend moves away from, so a downtrend also excludes puts.
    """
    if direction > 0 and trade["strategy"] in CALL_STRATS:
        return False
    if rule == "side" and direction < 0 and trade["strategy"] in PUT_STRATS:
        return False
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", default="docs/backtest_results.json")
    ap.add_argument("--vrp-exclude", default="QQQ",
                    help="underlyings the VRP filter drops (IV below realised in "
                         "the window); comma-separated, blank to skip")
    ap.add_argument("--rule", choices=("side", "calls"), default="side",
                    help='"side" = what candidates() does; "calls" = BACKTEST.md wording')
    ap.add_argument("--out", default="")
    a = ap.parse_args()

    data = json.loads((ROOT / a.src).read_text())
    trades = data["trades"]
    print(f"\n{a.src} — {len(trades)} recorded trades, "
          f"{data['params']['weeks']} cycles, {data['params']['dte']} DTE")

    # ---- market context per (underlying, entry), fetched once each ----
    c = AlpacaClient()
    keys = sorted({(t["underlying"], t["entry"]) for t in trades})
    print(f"\nfetching market context for {len(keys)} (underlying, entry) pairs...")
    ctx = {}
    for und, ent in keys:
        try:
            m = market_context(c, und, date.fromisoformat(ent))
        except AlpacaError as e:
            print(f"  {und} {ent}: skip ({e.status})")
            m = None
        if m:
            ctx[(und, ent)] = m

    print(f"\n{'':6} {'entry':12} {'z':>6} {'z-dir':>6} {'structure':>10} "
          f"{'corroborated':>13}  changed?")
    changed = 0
    for k in keys:
        m = ctx.get(k)
        if not m:
            continue
        flag = ""
        if m["zdir"] != m["cdir"]:
            flag = "  <- structure overruled"
            changed += 1
        print(f"  {k[0]:4} {k[1]:12} {m['z']:>6.2f} {m['zdir']:>6} "
              f"{str(m['structure']):>10} {m['cdir']:>13}{flag}")
    print(f"\n  structure changed the direction in {changed} of {len(ctx)} cases")

    def keep(ts, dirkey, rule=None):
        out = []
        for t in ts:
            m = ctx.get((t["underlying"], t["entry"]))
            if m is None:
                continue                       # no context -> cannot judge, drop
            if admitted(t, m[dirkey], rule or a.rule):
                out.append(t)
        return out

    ex = [u.strip().upper() for u in a.vrp_exclude.split(",") if u.strip()]
    naive = trades
    vrp = [t for t in naive if t["underlying"] not in ex]
    trend_z = keep(vrp, "zdir")
    trend_zs = keep(vrp, "cdir")

    print(f"\n{'='*92}")
    print(f"  {'stage':34} {'n':>4} {'win%':>5} {'net $':>9} {'  PF':>5} "
          f"{'per trade':>8}  {'vs naive':>8}")
    print(f"{'-'*92}")
    base = stats(naive)
    row("naive — every strategy, always", base)
    row(f"+ VRP filter (drops {'/'.join(ex) or 'nothing'})", stats(vrp), base)
    row(f"+ trend filter [{a.rule}] (z only)", stats(trend_z), base)
    row(f"+ trend filter [{a.rule}] (z+structure)", stats(trend_zs), base)
    other = "calls" if a.rule == "side" else "side"
    row(f"  (for comparison: rule={other})", stats(keep(vrp, "zdir", other)), base)
    print(f"{'='*92}")

    sz, szs = stats(trend_z), stats(trend_zs)
    print(f"\n  structure's marginal effect: {szs['net'] - sz['net']:+.0f} net, "
          f"{szs['trades'] - sz['trades']:+d} trades, "
          f"PF {sz['pf']} -> {szs['pf']}, "
          f"expectancy {sz['exp']:+.2f} -> {szs['exp']:+.2f}")

    # which trades differ, and how they did
    a_set = {id(t) for t in trend_z}
    only_z = [t for t in trend_z if id(t) not in {id(x) for x in trend_zs}]
    only_zs = [t for t in trend_zs if id(t) not in a_set]
    if only_z:
        s = stats(only_z)
        print(f"\n  admitted by z-score but NOT by structure: {s['trades']} trades, "
              f"{s['net']:+.0f} net ({s['exp']:+.2f}/trade)")
        for t in only_z:
            print(f"    {t['underlying']} {t['entry']} {t['strategy']:18} {t['pnl']:+8.0f}")
    if only_zs:
        s = stats(only_zs)
        print(f"\n  admitted by structure but NOT by z-score: {s['trades']} trades, "
              f"{s['net']:+.0f} net ({s['exp']:+.2f}/trade)")
        for t in only_zs:
            print(f"    {t['underlying']} {t['entry']} {t['strategy']:18} {t['pnl']:+8.0f}")

    if a.out:
        json.dump({"source": a.src, "context": {f"{k[0]}|{k[1]}": v for k, v in ctx.items()},
                   "ladder": {"naive": base, "vrp": stats(vrp),
                              "trend_z": sz, "trend_z_structure": szs}},
                  open(ROOT / a.out, "w"), indent=2)
        print(f"\n  wrote {a.out}")
    print()


if __name__ == "__main__":
    main()
