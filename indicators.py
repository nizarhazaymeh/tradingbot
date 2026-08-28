"""Technical indicators. Pure functions over plain lists — no dependencies.

Every series is oldest-first. Functions ending in `_series` return a value per
bar (aligned to the input, padded with None while warming up); the others
return just the latest value.

ATR/ADX use Wilder's smoothing, which is what charting packages plot — a plain
rolling mean gives visibly different numbers.
"""
from typing import List, Optional, Sequence


def sma(values: Sequence[float], period: int) -> float:
    if len(values) < period:
        raise ValueError("Not enough data for SMA")
    return sum(values[-period:]) / period


def sma_series(values: Sequence[float], period: int) -> List[Optional[float]]:
    out: List[Optional[float]] = [None] * len(values)
    if len(values) < period:
        return out
    total = sum(values[:period])
    out[period - 1] = total / period
    for i in range(period, len(values)):
        total += values[i] - values[i - period]
        out[i] = total / period
    return out


def ema_series(values: Sequence[float], period: int) -> List[Optional[float]]:
    """EMA seeded with the first `period` bars' SMA (standard convention)."""
    out: List[Optional[float]] = [None] * len(values)
    if len(values) < period:
        return out
    k = 2.0 / (period + 1)
    prev = sum(values[:period]) / period
    out[period - 1] = prev
    for i in range(period, len(values)):
        prev = values[i] * k + prev * (1 - k)
        out[i] = prev
    return out


def ema(values: Sequence[float], period: int) -> float:
    series = ema_series(values, period)
    if series[-1] is None:
        raise ValueError("Not enough data for EMA")
    return series[-1]


def true_range(highs: Sequence[float], lows: Sequence[float],
               closes: Sequence[float]) -> List[float]:
    """TR[i] = max(high-low, |high-prev_close|, |low-prev_close|).

    The gap terms are what make it useful for stops: an overnight gap in a
    stock or ETF shows up as real range, where high-low alone would hide it.
    """
    tr = [highs[0] - lows[0]]
    for i in range(1, len(closes)):
        prev = closes[i - 1]
        tr.append(max(highs[i] - lows[i], abs(highs[i] - prev), abs(lows[i] - prev)))
    return tr


def _wilder(values: Sequence[float], period: int) -> List[Optional[float]]:
    """Wilder's smoothing: seed with a mean, then prev + (x - prev)/period."""
    out: List[Optional[float]] = [None] * len(values)
    if len(values) < period:
        return out
    prev = sum(values[:period]) / period
    out[period - 1] = prev
    for i in range(period, len(values)):
        prev = prev + (values[i] - prev) / period
        out[i] = prev
    return out


def atr_series(highs, lows, closes, period: int = 14) -> List[Optional[float]]:
    return _wilder(true_range(highs, lows, closes), period)


def atr(highs, lows, closes, period: int = 14) -> Optional[float]:
    """Average True Range — the instrument's own volatility, in price units.

    Sizing stops in ATR instead of a fixed percentage is what lets one config
    fit both a 15m gold chart and a sleepy currency ETF.
    """
    s = atr_series(highs, lows, closes, period)
    return s[-1] if s else None


def adx_series(highs, lows, closes, period: int = 14) -> List[Optional[float]]:
    """Average Directional Index — trend STRENGTH, ignoring direction.

    Low ADX means the market is ranging, which is exactly where moving-average
    crossovers whipsaw. Gating entries on ADX is the main defence against that.
    """
    n = len(closes)
    out: List[Optional[float]] = [None] * n
    if n < period * 2:
        return out

    plus_dm, minus_dm = [0.0], [0.0]
    for i in range(1, n):
        up = highs[i] - highs[i - 1]
        down = lows[i - 1] - lows[i]
        plus_dm.append(up if (up > down and up > 0) else 0.0)
        minus_dm.append(down if (down > up and down > 0) else 0.0)

    tr_s = _wilder(true_range(highs, lows, closes), period)
    plus_s = _wilder(plus_dm, period)
    minus_s = _wilder(minus_dm, period)

    dx: List[Optional[float]] = [None] * n
    for i in range(n):
        if not tr_s[i] or plus_s[i] is None or minus_s[i] is None:
            continue
        pdi = 100 * plus_s[i] / tr_s[i]
        mdi = 100 * minus_s[i] / tr_s[i]
        denom = pdi + mdi
        dx[i] = 100 * abs(pdi - mdi) / denom if denom else 0.0

    valid = [(i, v) for i, v in enumerate(dx) if v is not None]
    if len(valid) < period:
        return out
    start = valid[period - 1][0]
    prev = sum(v for _, v in valid[:period]) / period
    out[start] = prev
    for i, v in valid[period:]:
        prev = prev + (v - prev) / period
        out[i] = prev
    return out


def adx(highs, lows, closes, period: int = 14) -> Optional[float]:
    s = adx_series(highs, lows, closes, period)
    return s[-1] if s else None


def rsi(closes: Sequence[float], period: int = 14) -> Optional[float]:
    """Relative Strength Index — used here only to veto buying into blow-offs."""
    if len(closes) <= period:
        return None
    gains = [max(closes[i] - closes[i - 1], 0.0) for i in range(1, len(closes))]
    losses = [max(closes[i - 1] - closes[i], 0.0) for i in range(1, len(closes))]
    g, l = _wilder(gains, period), _wilder(losses, period)
    if g[-1] is None or l[-1] is None:
        return None
    if l[-1] == 0:
        return 100.0
    rs = g[-1] / l[-1]
    return 100 - (100 / (1 + rs))
