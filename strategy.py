"""Trading strategy: simple moving-average (SMA) crossover.

Signal logic:
  - BUY  when the fast SMA crosses ABOVE the slow SMA (golden cross)
  - SELL when the fast SMA crosses BELOW the slow SMA (death cross)
  - HOLD otherwise

Swap this file out to change the bot's behaviour; the rest of the
code only depends on `generate_signal` returning "BUY"/"SELL"/"HOLD".
"""
from typing import List


def sma(values: List[float], period: int) -> float:
    """Simple moving average of the last `period` values."""
    if len(values) < period:
        raise ValueError("Not enough data for SMA")
    return sum(values[-period:]) / period


def generate_signal(
    closes: List[float],
    fast: int,
    slow: int,
    trend: int = 0,
    buffer: float = 0.0,
) -> str:
    """Return BUY / SELL / HOLD based on an SMA crossover, with optional filters.

    We compare the SMA on the latest closed candle vs. the previous one
    to detect the moment of a crossover (not just which is higher).

    Filters (both improve signal quality — see backtest.py):
      trend  > 0  -> only BUY when price is above the `trend`-period SMA
                     (stay out of downtrends).
      buffer > 0  -> only BUY when fast SMA beats slow by this fraction
                     (e.g. 0.001 = 0.1%), ignoring tiny noise crossovers.
    """
    need = max(slow + 1, trend)
    if len(closes) < need:
        return "HOLD"

    prev = closes[:-1]
    curr = closes

    fast_prev, slow_prev = sma(prev, fast), sma(prev, slow)
    fast_curr, slow_curr = sma(curr, fast), sma(curr, slow)

    crossed_up = fast_prev <= slow_prev and fast_curr > slow_curr
    crossed_down = fast_prev >= slow_prev and fast_curr < slow_curr

    if crossed_up:
        price = closes[-1]
        if trend and price <= sma(curr, trend):
            return "HOLD"  # below long-term trend -> skip
        if buffer and fast_curr <= slow_curr * (1 + buffer):
            return "HOLD"  # crossover too weak
        return "BUY"
    if crossed_down:
        return "SELL"
    return "HOLD"
