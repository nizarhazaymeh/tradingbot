"""Backtester — replays real bars through the live bot's decision logic.

It calls the SAME `strategy.analyze()` the bot calls, on an expanding window,
so a result here reflects what the bot would actually have done. Higher-timeframe
bars are sliced by timestamp, so at any moment the strategy only sees HTF bars
that had already closed — no lookahead.

Usage:
    python backtest.py                      # every WATCHLIST symbol, its own timeframes
    python backtest.py --bars 1500          # how much history per symbol
    python backtest.py --compare            # new strategy vs the old SMA/fixed-% one
    python backtest.py --slippage 0.0005    # per-side cost assumption

Stops and targets are checked against each bar's HIGH/LOW, like a real fill.
When both are touched inside one bar, the stop is assumed to fill first.
"""
import argparse
import statistics
from typing import List, Optional

import config
import strategy
from broker import get_broker
from strategy import Bar


# --------------------------------------------------------------------------- #
# Engines
# --------------------------------------------------------------------------- #
def run_new(bars: List[Bar], htf: Optional[List[Bar]], params, slippage: float):
    """Replay the multi-timeframe ATR strategy."""
    warmup = max(params.slow + 2, params.trend_ma,
                 params.atr_period * 2, params.adx_period * 3) + 2
    trades, equity, curve = [], 1.0, [1.0]
    in_pos = False
    entry = stop = target = 0.0

    for i in range(warmup, len(bars)):
        bar = bars[i]
        window = bars[:i + 1]
        htf_window = strategy.htf_at(htf, bar.t) if htf else None
        d = strategy.analyze(window, htf_window, params)

        if in_pos:
            exit_price = reason = None
            if stop and bar.l <= stop:            # stop first if both are touched
                exit_price, reason = stop, "stop-loss"
            elif target and bar.h >= target:
                exit_price, reason = target, "take-profit"
            elif d.signal == "SELL":
                exit_price, reason = bar.c, "sell-signal"

            if exit_price is not None:
                fill = exit_price * (1 - slippage)
                pnl = (fill - entry) / entry
                equity *= 1 + pnl
                trades.append({"entry": entry, "exit": fill, "pnl": pnl, "reason": reason})
                in_pos = False

        elif d.signal == "BUY":
            entry = bar.c * (1 + slippage)
            stop, target = d.stop, d.target
            in_pos = True

        curve.append(equity)
    return trades, curve


def run_old(bars: List[Bar], slippage: float):
    """The previous behaviour: SMA crossover, fixed 2% stop / 4% target."""
    closes = [b.c for b in bars]
    fast, slow = config.FAST_SMA, config.SLOW_SMA
    sl, tp = config.STOP_LOSS_PCT, config.TAKE_PROFIT_PCT
    warmup = max(slow + 2, config.TREND_SMA) + 2
    trades, equity, curve = [], 1.0, [1.0]
    in_pos, entry = False, 0.0

    for i in range(warmup, len(bars)):
        bar = bars[i]
        sig = strategy.generate_signal(closes[:i + 1], fast, slow,
                                       trend=config.TREND_SMA, buffer=config.CROSS_BUFFER)
        if in_pos:
            stop, target = entry * (1 - sl), entry * (1 + tp)
            exit_price = reason = None
            if sl and bar.l <= stop:
                exit_price, reason = stop, "stop-loss"
            elif tp and bar.h >= target:
                exit_price, reason = target, "take-profit"
            elif sig == "SELL":
                exit_price, reason = bar.c, "sell-signal"
            if exit_price is not None:
                fill = exit_price * (1 - slippage)
                pnl = (fill - entry) / entry
                equity *= 1 + pnl
                trades.append({"entry": entry, "exit": fill, "pnl": pnl, "reason": reason})
                in_pos = False
        elif sig == "BUY":
            entry, in_pos = bar.c * (1 + slippage), True
        curve.append(equity)
    return trades, curve


# --------------------------------------------------------------------------- #
# Stats
# --------------------------------------------------------------------------- #
def max_drawdown(curve):
    peak, worst = curve[0], 0.0
    for v in curve:
        peak = max(peak, v)
        worst = min(worst, (v - peak) / peak)
    return worst


def stats(bars, trades, curve):
    wins = [t["pnl"] for t in trades if t["pnl"] > 0]
    losses = [t["pnl"] for t in trades if t["pnl"] <= 0]
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    return {
        "trades": len(trades),
        "win_rate": (len(wins) / len(trades) * 100) if trades else 0.0,
        "avg_win": statistics.mean(wins) * 100 if wins else 0.0,
        "avg_loss": statistics.mean(losses) * 100 if losses else 0.0,
        "ret": (curve[-1] - 1) * 100,
        "buy_hold": (bars[-1].c - bars[0].c) / bars[0].c * 100,
        "dd": max_drawdown(curve) * 100,
        "pf": (gross_win / gross_loss) if gross_loss else float("inf") if gross_win else 0.0,
        "expectancy": (statistics.mean([t["pnl"] for t in trades]) * 100) if trades else 0.0,
    }


def show(label, s):
    pf = "inf" if s["pf"] == float("inf") else f"{s['pf']:.2f}"
    print(f"  {label:<12} {s['trades']:>4}  {s['win_rate']:>5.1f}%  "
          f"{s['ret']:>+8.2f}%  {s['dd']:>7.2f}%  {pf:>6}  {s['expectancy']:>+7.2f}%")


# --------------------------------------------------------------------------- #
def main():
    p = argparse.ArgumentParser()
    p.add_argument("--bars", type=int, default=1000,
                   help="history per symbol (Alpaca allows up to 10000)")
    p.add_argument("--compare", action="store_true",
                   help="also run the old SMA + fixed-%% strategy for reference")
    p.add_argument("--slippage", type=float, default=0.0002,
                   help="per-side cost as a fraction (0.0002 = 2bps)")
    args = p.parse_args()

    config.validate()
    params = config.strategy_params()
    broker = get_broker()
    resolved = broker.prepare([w["symbol"] for w in config.WATCHLIST])
    watch = [dict(w, symbol=s) for w, s in zip(config.WATCHLIST, resolved)]

    print(f"Data: {broker.name} | {params.ma_type.upper()} {params.fast}/{params.slow} "
          f"| ADX>={params.adx_min:.0f} | stop {params.atr_stop_mult}xATR({params.atr_period}) "
          f"| R:R 1:{params.reward_risk} | slippage {args.slippage*100:.3f}%/side")

    totals = {"new": [], "old": []}
    for w in watch:
        sym, tf, htf_tf = w["symbol"], w["entry_tf"], w["htf_tf"]
        bars = broker.history(sym, tf, args.bars)
        htf = broker.history(sym, htf_tf, max(args.bars // 3, 120)) if htf_tf else None

        need = max(params.slow + 2, params.trend_ma) + 10
        if len(bars) < need:
            print(f"\n{sym}: only {len(bars)} {tf} bars, need {need} — skipping.")
            continue

        label = f"{sym} {tf}" + (f" (trend {htf_tf})" if htf_tf else "")
        print(f"\n=== {label}  —  {len(bars)} bars"
              + (f", {len(htf)} HTF bars" if htf else "") + " ===")
        print(f"  {'strategy':<12} {'trades':>4}  {'win':>6}  {'return':>9}  "
              f"{'maxDD':>8}  {'PF':>6}  {'expect':>8}")

        t_new, c_new = run_new(bars, htf, params, args.slippage)
        s_new = stats(bars, t_new, c_new)
        show("new (MTF)", s_new)
        totals["new"].append(s_new)

        if args.compare:
            t_old, c_old = run_old(bars, args.slippage)
            s_old = stats(bars, t_old, c_old)
            show("old (SMA)", s_old)
            totals["old"].append(s_old)

        print(f"  {'buy & hold':<12} {'-':>4}  {'-':>6}  {s_new['buy_hold']:>+8.2f}%")

    for name in ("new", "old"):
        rows = totals[name]
        if len(rows) > 1:
            print(f"\n{name.upper()} across {len(rows)} symbols: "
                  f"total trades {sum(r['trades'] for r in rows)}, "
                  f"mean return {statistics.mean(r['ret'] for r in rows):+.2f}%, "
                  f"mean maxDD {statistics.mean(r['dd'] for r in rows):.2f}%")


if __name__ == "__main__":
    main()
