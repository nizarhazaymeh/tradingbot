"""Trading strategy: multi-timeframe MA crossover with ATR risk and a chop filter.

Why this shape — the previous version was a bare SMA 9/21 crossover with a fixed
2% stop and 4% target, and it lost to buy & hold. Three things were wrong:

  1. A crossover fires constantly in a sideways market. Most of those are noise.
     -> ADX gates entries on trend STRENGTH, and an entry only counts if the MAs
        separate by a meaningful fraction of ATR.
  2. A fixed 2% stop means nothing across instruments. 2% is a rounding error on
     gold intraday and an enormous move on a currency ETF.
     -> Stops and targets are sized in ATR, so one config fits every symbol.
  3. Counter-trend entries. A 1h buy signal against a falling 4h trend is a
     losing trade waiting to happen.
     -> A higher timeframe supplies the bias; entries must agree with it.

The bot is long-only (spot), so "SELL" means close, never short.
"""
from collections import namedtuple
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

import indicators as ind

# One market bar. `t` is epoch seconds of the bar's OPEN — needed to line a 1h
# series up against a 4h one, which bar counts alone can't do once market
# holidays and half-days make the ratio irregular.
Bar = namedtuple("Bar", "t c h l")


@dataclass
class Params:
    """Everything the strategy needs, so it can be tuned without touching code."""
    fast: int = 9
    slow: int = 21
    ma_type: str = "ema"          # "ema" (responsive) or "sma"
    trend_ma: int = 200           # trend filter ON THE ENTRY TIMEFRAME (0 = off)
    htf_trend_ma: int = 50        # trend filter on the higher timeframe (0 = off)
    adx_period: int = 14
    adx_min: float = 20.0         # below this the market is ranging -> no entries
    atr_period: int = 14
    atr_stop_mult: float = 1.5    # stop = entry - mult * ATR
    reward_risk: float = 2.0      # target = entry + rr * (entry - stop)
    cross_atr_frac: float = 0.10  # close must clear the slow MA by this * ATR
    rsi_max: float = 75.0         # don't buy a blow-off top (0 = off)
    use_atr_stops: bool = True    # False -> fall back to fixed percentages
    stop_loss_pct: float = 0.02   # used only when use_atr_stops is False
    take_profit_pct: float = 0.04


@dataclass
class Decision:
    signal: str = "HOLD"                     # BUY / SELL / HOLD
    stop: Optional[float] = None
    target: Optional[float] = None
    atr: Optional[float] = None
    adx: Optional[float] = None
    reasons: List[str] = field(default_factory=list)

    @property
    def blocked_by(self) -> str:
        return ", ".join(self.reasons)


def _ma_series(values: Sequence[float], period: int, ma_type: str):
    return (ind.ema_series if ma_type == "ema" else ind.sma_series)(values, period)


def split(bars: Sequence[Bar]):
    """Bars -> parallel (closes, highs, lows) lists."""
    return [b.c for b in bars], [b.h for b in bars], [b.l for b in bars]


def htf_at(htf_bars: Sequence[Bar], when: float) -> List[Bar]:
    """The higher-timeframe bars CLOSED at or before `when`.

    Slicing by timestamp is what keeps a backtest honest: at 10:00 the strategy
    may only see 4h bars that had already closed by 10:00, never the one still
    forming around it.
    """
    cut = 0
    for i, b in enumerate(htf_bars):
        if b.t <= when:
            cut = i + 1
        else:
            break
    return list(htf_bars[:cut])


def htf_bias(htf_bars, params: Params) -> Tuple[bool, str]:
    """Is the higher timeframe pointing up? (allowed, why-not).

    Two conditions: price above the HTF trend MA, and that MA actually rising.
    The slope check is what rejects a flat market sitting just above its average.
    """
    if not htf_bars or not params.htf_trend_ma:
        return True, ""
    closes, _, _ = split(htf_bars)
    series = _ma_series(closes, params.htf_trend_ma, params.ma_type)
    if series[-1] is None:
        return True, ""  # not enough HTF history yet — don't block on ignorance
    if closes[-1] <= series[-1]:
        return False, f"HTF price {closes[-1]:.4f} below its {params.htf_trend_ma}MA"
    prior = next((v for v in reversed(series[:-1]) if v is not None), None)
    if prior is not None and series[-1] <= prior:
        return False, f"HTF {params.htf_trend_ma}MA is not rising"
    return True, ""


def analyze(bars, htf_bars=None, params: Optional[Params] = None) -> Decision:
    """Decide on the latest CLOSED bar of `bars` (oldest first, (c,h,l) tuples).

    `htf_bars` is the same shape on a higher timeframe; pass None for a
    single-timeframe symbol, and the entry-timeframe trend MA carries the load.
    """
    p = params or Params()
    d = Decision()
    need = max(p.slow + 2, p.trend_ma, p.atr_period * 2, p.adx_period * 3)
    if len(bars) < need:
        d.reasons.append(f"warming up ({len(bars)}/{need} bars)")
        return d

    closes, highs, lows = split(bars)
    d.atr = ind.atr(highs, lows, closes, p.atr_period)
    d.adx = ind.adx(highs, lows, closes, p.adx_period)

    fast_s = _ma_series(closes, p.fast, p.ma_type)
    slow_s = _ma_series(closes, p.slow, p.ma_type)
    if fast_s[-1] is None or slow_s[-1] is None or fast_s[-2] is None or slow_s[-2] is None:
        d.reasons.append("moving averages still warming up")
        return d

    crossed_up = fast_s[-2] <= slow_s[-2] and fast_s[-1] > slow_s[-1]
    crossed_down = fast_s[-2] >= slow_s[-2] and fast_s[-1] < slow_s[-1]
    price = closes[-1]

    # Exits are never filtered — if momentum turns, get out.
    if crossed_down:
        d.signal = "SELL"
        d.reasons.append("fast MA crossed below slow MA")
        return d

    if not crossed_up:
        return d  # HOLD

    # ---- entry filters, cheapest and most decisive first ----
    ok, why = htf_bias(htf_bars, p)
    if not ok:
        d.reasons.append(why)

    if p.trend_ma:
        trend_s = _ma_series(closes, p.trend_ma, p.ma_type)
        if trend_s[-1] is not None and price <= trend_s[-1]:
            d.reasons.append(f"price below its {p.trend_ma}{p.ma_type.upper()}")

    if p.adx_min and d.adx is not None and d.adx < p.adx_min:
        d.reasons.append(f"ADX {d.adx:.1f} < {p.adx_min:.0f} (market is ranging)")

    # NOT the gap between the two MAs: at a crossover they are equal by
    # definition, so that test can never pass. What separates a real breakout
    # from noise is how decisively PRICE has cleared the slow MA.
    if p.cross_atr_frac and d.atr:
        edge = price - slow_s[-1]
        need_edge = p.cross_atr_frac * d.atr
        if edge < need_edge:
            d.reasons.append(
                f"price only {edge:.4f} above slow MA, needs {need_edge:.4f} "
                f"({p.cross_atr_frac:g} ATR)")

    if p.rsi_max:
        r = ind.rsi(closes, 14)
        if r is not None and r > p.rsi_max:
            d.reasons.append(f"RSI {r:.0f} > {p.rsi_max:.0f} (overbought)")

    if d.reasons:
        return d  # HOLD, with the reasons recorded for the log

    d.signal = "BUY"
    d.stop, d.target = levels(price, d.atr, p)
    return d


def levels(price: float, atr_value: Optional[float], p: Params):
    """(stop, target) for an entry at `price`.

    ATR-based when available, so risk scales with the instrument's own
    volatility; otherwise the fixed percentages.
    """
    if p.use_atr_stops and atr_value:
        stop = price - p.atr_stop_mult * atr_value
        if stop <= 0 or stop >= price:
            stop = price * (1 - p.stop_loss_pct)
        return stop, price + p.reward_risk * (price - stop)
    return price * (1 - p.stop_loss_pct), price * (1 + p.take_profit_pct)


def trail_stop(current_stop, price, atr_value, p: Params):
    """Ratchet a stop upward by ATR. Never loosens — returns the higher of the two."""
    if not atr_value or not p.use_atr_stops:
        return current_stop
    candidate = price - p.atr_stop_mult * atr_value
    return max(current_stop or 0.0, candidate)


# Kept so older callers/tests keep working.
sma = ind.sma


def generate_signal(closes, fast, slow, trend=0, buffer=0.0) -> str:
    """Close-only crossover, the pre-ATR behaviour. Prefer `analyze()`."""
    need = max(slow + 1, trend)
    if len(closes) < need:
        return "HOLD"
    f_prev, s_prev = ind.sma(closes[:-1], fast), ind.sma(closes[:-1], slow)
    f_now, s_now = ind.sma(closes, fast), ind.sma(closes, slow)
    if f_prev <= s_prev and f_now > s_now:
        if trend and closes[-1] <= ind.sma(closes, trend):
            return "HOLD"
        if buffer and f_now <= s_now * (1 + buffer):
            return "HOLD"
        return "BUY"
    if f_prev >= s_prev and f_now < s_now:
        return "SELL"
    return "HOLD"
