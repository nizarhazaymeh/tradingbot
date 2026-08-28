"""Backtester — replays real historical candles through the bot's strategy.

It mirrors the LIVE bot's decision logic (SMA crossover entry, fixed
stop-loss / take-profit, sell-signal exit) so the results reflect what the
bot would actually have done. Stop-loss and take-profit are checked against
each candle's HIGH/LOW (intra-candle), like a real fill — not just closes.

Usage:
    python backtest.py                 # uses SYMBOL + params from .env
    python backtest.py --candles 1000  # how many historical candles (max 1000)
    python backtest.py --trend 200     # only BUY when price > 200-SMA (trend filter)
    python backtest.py --buffer 0.001  # require fast SMA to beat slow by 0.1%

Data comes from whichever broker BROKER points at, so the bars are the same
ones the live bot would trade on. Alpaca requires API keys even for market data.
"""
import argparse
import statistics

import config
from broker import get_broker
from strategy import sma, generate_signal


def backtest(bars, fast, slow, sl_pct, tp_pct, trend=0, buffer=0.0):
    """Replay the strategy over `bars` = [(close, high, low), ...].

    Returns (trades, equity_curve). Each trade is a dict with entry/exit/pnl.
    """
    closes = [b[0] for b in bars]
    trades = []
    equity = 1.0
    equity_curve = [1.0]

    in_position = False
    entry_price = 0.0
    need = max(slow + 1, trend)

    for i in range(need, len(bars)):
        window = closes[: i + 1]
        close, high, low = bars[i]
        signal = generate_signal(window, fast, slow)

        # Optional confirmation filters applied to the BUY signal.
        if signal == "BUY":
            if trend and close <= sma(window, trend):
                signal = "HOLD"  # below long-term trend -> skip
            elif buffer and sma(window, fast) <= sma(window, slow) * (1 + buffer):
                signal = "HOLD"  # crossover too weak

        if in_position:
            sl_price = entry_price * (1 - sl_pct)
            tp_price = entry_price * (1 + tp_pct)
            exit_price = exit_reason = None

            # Intra-candle: if both touched, assume the stop fills first.
            if sl_pct > 0 and low <= sl_price:
                exit_price, exit_reason = sl_price, "stop-loss"
            elif tp_pct > 0 and high >= tp_price:
                exit_price, exit_reason = tp_price, "take-profit"
            elif signal == "SELL":
                exit_price, exit_reason = close, "sell-signal"

            if exit_price is not None:
                pnl = (exit_price - entry_price) / entry_price
                equity *= 1 + pnl
                trades.append({
                    "entry": entry_price, "exit": exit_price,
                    "pnl": pnl, "reason": exit_reason,
                })
                in_position = False

        elif signal == "BUY":
            in_position = True
            entry_price = close

        equity_curve.append(equity)

    return trades, equity_curve


def max_drawdown(curve):
    peak = curve[0]
    worst = 0.0
    for v in curve:
        peak = max(peak, v)
        worst = min(worst, (v - peak) / peak)
    return worst


def report(symbol, bars, interval, trades, curve):
    n = len(trades)
    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    total_return = (curve[-1] - 1) * 100
    buy_hold = (bars[-1][0] - bars[0][0]) / bars[0][0] * 100

    print(f"\n=== {symbol}  ({len(bars)} x {interval} candles) ===")
    print(f"  Trades:        {n}")
    if n:
        win_rate = len(wins) / n * 100
        avg_win = statistics.mean([t['pnl'] for t in wins]) * 100 if wins else 0
        avg_loss = statistics.mean([t['pnl'] for t in losses]) * 100 if losses else 0
        print(f"  Win rate:      {win_rate:.1f}%  ({len(wins)}W / {len(losses)}L)")
        print(f"  Avg win:       {avg_win:+.2f}%   Avg loss: {avg_loss:+.2f}%")
    print(f"  Strategy P/L:  {total_return:+.2f}%")
    print(f"  Buy & hold:    {buy_hold:+.2f}%   <- doing nothing")
    print(f"  Max drawdown:  {max_drawdown(curve) * 100:.2f}%")
    edge = total_return - buy_hold
    verdict = "BEATS" if edge > 0 else "LOSES TO"
    print(f"  => Strategy {verdict} buy & hold by {abs(edge):.2f} pts")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--candles", type=int, default=1000,
               help="how many historical bars (Alpaca allows up to 10000)")
    p.add_argument("--trend", type=int, default=0, help="long-SMA trend filter period")
    p.add_argument("--buffer", type=float, default=0.0, help="min crossover margin, e.g. 0.001")
    args = p.parse_args()

    config.validate()
    broker = get_broker()
    symbols = broker.prepare(config.SYMBOLS)

    print(f"Data: {broker.name} | Strategy: SMA {config.FAST_SMA}/{config.SLOW_SMA} | "
          f"SL {config.STOP_LOSS_PCT*100:.0f}% TP {config.TAKE_PROFIT_PCT*100:.0f}%"
          + (f" | trend>{args.trend}SMA" if args.trend else "")
          + (f" | buffer {args.buffer*100:.2f}%" if args.buffer else ""))

    for symbol in symbols:
        bars = broker.history(symbol, config.INTERVAL, args.candles)
        if len(bars) < config.SLOW_SMA + 2:
            print(f"\n{symbol}: not enough data."); continue
        trades, curve = backtest(
            bars, config.FAST_SMA, config.SLOW_SMA,
            config.STOP_LOSS_PCT, config.TAKE_PROFIT_PCT,
            trend=args.trend, buffer=args.buffer,
        )
        report(symbol, bars, config.INTERVAL, trades, curve)


if __name__ == "__main__":
    main()
