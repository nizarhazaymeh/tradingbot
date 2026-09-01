#!/usr/bin/env python3
"""Backtest the spot-crypto path. Does break-and-retest pay on 24/7 data?

agent/crypto.py trades a break of structure that price returned to and
respected. That pattern could not earn a place in options selection
(docs/BACKTEST.md Part 7) for a reason that does not apply here: a barrier is a
property of the entry, and premium selling is not directional. Spot is. So this
is the first test of what the pattern actually claims.

The harness walks daily bars forward one at a time. At each bar the strategy sees
ONLY bars up to and including it — signal() and evaluate_exit() are handed a
slice, never the full series — so nothing here could not have been decided live.
Fills are at the close of the signal bar, and exits at the close of the bar whose
range touched the level, which is optimistic on both sides and stated as such.

Baselines matter more than the strategy number. A long-only strategy in a rising
market makes money for reasons that have nothing to do with its signal, so the
comparison is against buy-and-hold over the identical window.

  python scripts/backtest_crypto.py
  python scripts/backtest_crypto.py --start 2024-01-01 --symbols BTC/USD,ETH/USD
"""
import argparse
import json
import statistics
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent import config, crypto as CR, levels as L
from agent.client import AlpacaClient


def fetch(c, symbols, start, end, timeframe="1Day"):
    out, token = {}, None
    for _ in range(50):
        r = c._data("/v1beta3/crypto/us/bars",
                    {"symbols": ",".join(symbols), "timeframe": timeframe,
                     "start": start, "end": end, "limit": 10000, "page_token": token})
        for sym, rows in (r.get("bars") or {}).items():
            out.setdefault(sym, []).extend(rows)
        token = r.get("next_page_token")
        if not token:
            break
    return {s: L.bars_from_api(rows) for s, rows in out.items()}


def run(symbol, bars, equity):
    """Walk forward. The strategy never sees a bar it would not have had."""
    trades, pos, warm = [], None, 60
    for i in range(warm, len(bars)):
        seen = bars[:i + 1]           # everything up to and including bar i
        price = bars[i].c

        if pos:
            # Resting orders fill the MOMENT price touches them, so both are
            # checked against the bar's range and not its close. Exiting at the
            # close instead made every stop look worse than -1R, which is not a
            # finding about the strategy, it is the harness marking a stop out at
            # wherever the day happened to end.
            #
            # A bar that touches both is genuinely ambiguous on daily data and is
            # resolved as the STOP, the same way crypto.evaluate_exit() resolves
            # it. Resolving it as the target would flatter every number here.
            action, reason = CR.HOLD, ""
            if bars[i].l <= pos["stop"]:
                action, reason, price = CR.CLOSE, "stop hit", pos["stop"]
            elif pos["target"] and bars[i].h >= pos["target"]:
                action, reason, price = CR.CLOSE, "target hit", pos["target"]
            else:
                action, reason = CR.evaluate_exit(pos, price, seen)
            if action == CR.CLOSE:
                pnl = (price - pos["entry"]) * pos["qty"]
                trades.append({"symbol": symbol, "entry": pos["entry"],
                               "exit": price, "qty": pos["qty"],
                               "pnl": round(pnl, 2),
                               "R": round(pnl / pos["risk"], 3) if pos["risk"] else 0,
                               "bars_held": i - pos["i"], "reason": reason})
                pos = None
            else:
                continue

        sig = CR.signal(symbol, seen)
        if not sig:
            continue
        qty, risk, notional = CR.size(sig, equity)
        if qty <= 0:
            continue
        pos = {"entry": sig.entry, "stop": sig.stop, "target": sig.target,
               "qty": qty, "risk": risk, "i": i,
               "opened_at": datetime.now(timezone.utc).isoformat()}
    return trades


def stat(trades):
    if not trades:
        return None
    p = [t["pnl"] for t in trades]
    w = [x for x in p if x > 0]
    l = [x for x in p if x <= 0]
    gp, gl = sum(w), abs(sum(l))
    return {"n": len(p), "net": round(sum(p), 2), "win": len(w) / len(p),
            "pf": round(gp / gl, 2) if gl else None,
            "exp": round(statistics.mean(p), 2),
            "R": round(statistics.mean([t["R"] for t in trades]), 3),
            "worst": round(min(p), 2)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default=",".join(config.CRYPTO_UNIVERSE))
    ap.add_argument("--start", default="2024-01-01")
    ap.add_argument("--equity", type=float, default=100_000.0)
    ap.add_argument("--out", default="docs/backtest_crypto.json")
    a = ap.parse_args()

    syms = [s.strip().upper() for s in a.symbols.split(",") if s.strip()]
    end = (datetime.now(timezone.utc) - timedelta(days=1)).date().isoformat()
    c = AlpacaClient()
    print(f"\nfetching {', '.join(syms)} daily bars {a.start} -> {end} ...")
    data = fetch(c, syms, a.start, end)

    print(f"\n{'='*94}")
    print("  SPOT CRYPTO — break of structure, confirmed on retest, long only")
    print(f"{'='*94}")
    print(f"  {'symbol':10} {'bars':>5} {'n':>4} {'win%':>6} {'net $':>10} "
          f"{'    PF':>7} {'R/trade':>8} {'worst':>9}")
    print(f"  {'-'*90}")

    all_trades, rows = [], []
    for s in syms:
        bars = data.get(s) or []
        if len(bars) < 80:
            print(f"  {s:10} {len(bars):>5}  too little history")
            continue
        t = run(s, bars, a.equity)
        all_trades += t
        st = stat(t)
        # buy-and-hold over the identical window, sized to the same notional cap
        bh_qty = (a.equity * config.CRYPTO_MAX_NOTIONAL_PCT) / bars[60].c
        bh = (bars[-1].c - bars[60].c) * bh_qty
        rows.append({"symbol": s, "bars": len(bars), "strategy": st,
                     "buy_hold_net": round(bh, 2),
                     "move_pct": round(bars[-1].c / bars[60].c - 1, 4)})
        if st:
            pf = f"{st['pf']:>7.2f}" if st["pf"] is not None else "      —"
            print(f"  {s:10} {len(bars):>5} {st['n']:>4} {st['win']*100:>5.0f}% "
                  f"{st['net']:>+10.0f} {pf} {st['R']:>+8.3f} {st['worst']:>+9.0f}")
        else:
            print(f"  {s:10} {len(bars):>5}    0  no signals fired")

    print(f"  {'-'*90}")
    tot = stat(all_trades)
    if tot:
        pf = f"{tot['pf']:>7.2f}" if tot["pf"] is not None else "      —"
        print(f"  {'ALL':10} {'':>5} {tot['n']:>4} {tot['win']*100:>5.0f}% "
              f"{tot['net']:>+10.0f} {pf} {tot['R']:>+8.3f} {tot['worst']:>+9.0f}")

    print(f"\n{'='*94}")
    print("  AGAINST BUY-AND-HOLD — a long-only strategy in a rising market")
    print("  makes money for reasons that are not its signal")
    print(f"{'='*94}")
    print(f"  {'symbol':10} {'window move':>13} {'strategy net':>14} "
          f"{'buy & hold':>13}  {'verdict'}")
    for r in rows:
        sn = r["strategy"]["net"] if r["strategy"] else 0.0
        v = "beats hold" if sn > r["buy_hold_net"] else "LOSES to hold"
        print(f"  {r['symbol']:10} {r['move_pct']*100:>12.1f}% {sn:>+14.0f} "
              f"{r['buy_hold_net']:>+13.0f}  {v}")

    Path(ROOT / a.out).write_text(json.dumps(
        {"start": a.start, "end": end, "equity": a.equity, "by_symbol": rows,
         "overall": tot, "trades": all_trades}, indent=2, default=str))
    print(f"\n  wrote {a.out}\n")


if __name__ == "__main__":
    main()
