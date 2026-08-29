"""Trading strategy: confluence of trend, structure, supply/demand and Fibonacci.

No single method decides a trade. Each one votes, the votes are scored, and an
entry only happens when enough independent reasons line up:

    trend      fast MA crossed above slow, price above the long MA
    htf        the higher timeframe agrees
    structure  higher highs and higher lows
    demand     price is sitting on a fresh demand zone
    fibonacci  price is in the 0.5-0.618 pocket of the last impulse
    momentum   ADX says trending, RSI says not yet exhausted
    volume     participation above its own average

That scoring is also what places the exits. The stop goes under the structure
that would have to break for the idea to be wrong — a demand zone or swing low,
not an arbitrary percentage. The three targets are drawn from real resistance
(supply zones, Fibonacci extensions, prior swing highs), falling back to R
multiples only when structure offers nothing.

The bot is long-only (spot), so "SELL" means close, never short.
"""
from collections import namedtuple
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

import indicators as ind
import levels

# One market bar. `t` is epoch seconds of the bar's OPEN — needed to line a 1h
# series up against a 4h one, which bar counts alone can't do once market
# holidays and half-days make the ratio irregular. `v` is volume, used to
# confirm that a breakout carried real participation.
Bar = namedtuple("Bar", "t c h l v")


@dataclass
class Params:
    """Everything tunable, so the strategy can be changed without editing code."""
    fast: int = 9
    slow: int = 21
    ma_type: str = "ema"
    trend_ma: int = 200
    htf_trend_ma: int = 50
    adx_period: int = 14
    adx_min: float = 20.0
    atr_period: int = 14
    atr_stop_mult: float = 1.5
    reward_risk: float = 2.0
    cross_atr_frac: float = 0.10
    rsi_max: float = 75.0
    use_atr_stops: bool = True
    stop_loss_pct: float = 0.02
    take_profit_pct: float = 0.04
    # --- confluence ---
    min_confluence: int = 6          # of MAX_SCORE below; the only score gate
    zone_pad_atr: float = 0.5        # how near a zone still counts as "at" it
    require_trend: bool = True       # a crossover must still be the trigger
    # --- exits ---
    tp_fractions: Tuple[float, float, float] = (0.5, 0.3, 0.2)
    min_tp1_r: float = 1.0           # TP1 must pay at least this much risk
    max_stop_atr: float = 3.0        # never risk more than this many ATR
    min_stop_atr: float = 0.5        # nor less — anything tighter is noise
    breakeven_after: int = 1         # move stop to entry once TP-n is hit
    trail_after: int = 2             # start trailing once TP-n is hit


MAX_SCORE = 12


@dataclass
class Target:
    price: float
    fraction: float
    label: str
    basis: str


@dataclass
class Plan:
    """A complete trade idea: where to get in, where to get out, and why."""
    signal: str = "HOLD"
    entry: Optional[float] = None
    stop: Optional[float] = None
    targets: List[Target] = field(default_factory=list)
    score: int = 0
    atr: Optional[float] = None
    adx: Optional[float] = None
    structure: str = "range"
    reasons: List[str] = field(default_factory=list)   # confluence that fired
    misses: List[str] = field(default_factory=list)    # votes that did NOT fire
    blockers: List[str] = field(default_factory=list)  # hard disqualifiers

    @property
    def risk(self) -> float:
        return (self.entry - self.stop) if (self.entry and self.stop) else 0.0

    @property
    def blocked_by(self) -> str:
        return ", ".join(self.blockers or self.misses)

    def summary(self) -> str:
        if self.signal != "BUY" or not self.targets:
            return self.blocked_by or self.signal
        tps = " ".join(f"{t.label} {t.price:.4f}" for t in self.targets)
        return (f"entry {self.entry:.4f} SL {self.stop:.4f} {tps} "
                f"| score {self.score}/{MAX_SCORE} | {', '.join(self.reasons)}")


# Kept so existing callers/tests keep working.
Decision = Plan


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


def htf_bias(htf_bars, p: Params) -> Tuple[bool, str]:
    """Is the higher timeframe pointing up? (allowed, why-not)."""
    if not htf_bars or not p.htf_trend_ma:
        return True, ""
    closes, _, _ = split(htf_bars)
    series = _ma_series(closes, p.htf_trend_ma, p.ma_type)
    if series[-1] is None:
        return True, ""  # not enough HTF history — don't block on ignorance
    if closes[-1] <= series[-1]:
        return False, f"HTF below its {p.htf_trend_ma}MA"
    prior = next((v for v in reversed(series[:-1]) if v is not None), None)
    if prior is not None and series[-1] <= prior:
        return False, f"HTF {p.htf_trend_ma}MA not rising"
    return True, ""


# --------------------------------------------------------------------------- #
# Stop placement
# --------------------------------------------------------------------------- #
def choose_stop(entry, atr_v, zone, swing_low, p: Params) -> Tuple[float, str]:
    """Put the stop under whatever would have to break for the idea to be wrong.

    Structure first — the low of the demand zone, or the swing low that started
    the move — because that is the price at which the reason for the trade is
    gone. The ATR bounds then keep it sane: never so tight that ordinary noise
    takes us out, never so wide that one loss is unrecoverable.
    """
    floor = entry - p.max_stop_atr * atr_v
    ceil = entry - p.min_stop_atr * atr_v
    candidates = []
    if zone is not None:
        candidates.append((zone.low - 0.1 * atr_v, "below demand zone"))
    if swing_low is not None:
        candidates.append((swing_low - 0.1 * atr_v, "below swing low"))
    candidates.append((entry - p.atr_stop_mult * atr_v, f"{p.atr_stop_mult}xATR"))

    usable = [(s, why) for s, why in candidates if floor <= s <= ceil]
    if usable:
        return max(usable, key=lambda x: x[0])  # tightest defensible stop
    # Nothing structural fits the risk band — fall back to the ATR stop, clamped.
    stop = min(max(entry - p.atr_stop_mult * atr_v, floor), ceil)
    return stop, f"{p.atr_stop_mult}xATR (clamped)"


# --------------------------------------------------------------------------- #
# Target placement
# --------------------------------------------------------------------------- #
def choose_targets(entry, stop, atr_v, zones, fib, swing_highs, p: Params) -> List[Target]:
    """Three ascending exits, preferring real resistance over arithmetic.

    Structure is where price actually reacts, so supply zones, Fibonacci
    extensions and prior swing highs are collected first; R multiples only fill
    the gaps. TP1 is forced to pay at least `min_tp1_r` of risk, otherwise the
    trade is risking more than the first exit returns.
    """
    risk = entry - stop
    if risk <= 0:
        return []

    candidates: List[Tuple[float, str]] = []
    for z in zones:
        if z.kind == "supply" and z.low > entry:
            candidates.append((z.low, "supply zone"))
    if fib:
        for mult, price in sorted(fib.extensions.items()):
            if price > entry:
                candidates.append((price, f"fib {mult}"))
    for h in swing_highs:
        if h > entry:
            candidates.append((h, "swing high"))
    for r in (1.0, 2.0, 3.0):
        candidates.append((entry + r * risk, f"{r:g}R"))

    # Nearest first, and drop levels sitting on top of each other.
    candidates.sort(key=lambda x: x[0])
    picked: List[Tuple[float, str]] = []
    for price, basis in candidates:
        if price < entry + p.min_tp1_r * risk and not picked:
            continue  # TP1 must clear the minimum reward
        if picked and price - picked[-1][0] < 0.5 * atr_v:
            continue  # too close to the previous target to be a separate exit
        picked.append((price, basis))
        if len(picked) == 3:
            break

    while len(picked) < 3:  # pad with R multiples if structure ran out
        n = len(picked) + 1
        picked.append((entry + (n + 1) * risk, f"{n + 1}R"))

    return [Target(price, frac, f"TP{i + 1}", basis)
            for i, ((price, basis), frac) in enumerate(zip(picked, p.tp_fractions))]


# --------------------------------------------------------------------------- #
# Main entry point
# --------------------------------------------------------------------------- #
def analyze(bars, htf_bars=None, params: Optional[Params] = None) -> Plan:
    """Score every method on the latest CLOSED bar and build a trade plan."""
    p = params or Params()
    plan = Plan()
    need = max(p.slow + 2, p.trend_ma, p.atr_period * 2, p.adx_period * 3)
    if len(bars) < need:
        plan.blockers.append(f"warming up ({len(bars)}/{need} bars)")
        return plan

    closes, highs, lows = split(bars)
    price = closes[-1]
    plan.atr = ind.atr(highs, lows, closes, p.atr_period)
    plan.adx = ind.adx(highs, lows, closes, p.adx_period)
    atr_v = plan.atr or (price * 0.01)

    fast_s = _ma_series(closes, p.fast, p.ma_type)
    slow_s = _ma_series(closes, p.slow, p.ma_type)
    if any(s[-1] is None or s[-2] is None for s in (fast_s, slow_s)):
        plan.blockers.append("moving averages warming up")
        return plan

    crossed_up = fast_s[-2] <= slow_s[-2] and fast_s[-1] > slow_s[-1]
    crossed_down = fast_s[-2] >= slow_s[-2] and fast_s[-1] < slow_s[-1]

    # Exits are never filtered — if momentum turns, get out.
    if crossed_down:
        plan.signal = "SELL"
        plan.reasons.append("fast MA crossed below slow MA")
        return plan

    # ---- structure, zones, fibonacci ---- #
    pv = levels.pivots(bars)
    plan.structure = levels.market_structure(pv)
    zones = levels.find_zones(bars, atr_period=p.atr_period)
    demand = levels.nearest_zone(zones, price, "demand", below=True)
    impulse = levels.last_impulse(bars, pv)
    fib = levels.fibonacci(*impulse) if impulse else None
    swing_lows = [q.price for q in pv if q.kind == "low"]
    swing_highs = [q.price for q in pv if q.kind == "high"]
    pad = p.zone_pad_atr * atr_v

    # ---- score the confluence ---- #
    score = 0
    if crossed_up:
        score += 2
        plan.reasons.append("MA cross up")
    else:
        plan.misses.append("no MA cross")

    trend_s = _ma_series(closes, p.trend_ma, p.ma_type) if p.trend_ma else [None]
    if trend_s[-1] is not None and price > trend_s[-1]:
        score += 1
        plan.reasons.append(f"above {p.trend_ma}{p.ma_type.upper()}")
    elif trend_s[-1] is not None:
        plan.misses.append(f"below {p.trend_ma}{p.ma_type.upper()}")

    ok, why = htf_bias(htf_bars, p)
    if ok and htf_bars:
        score += 2
        plan.reasons.append("HTF trend up")
    elif not ok:
        plan.misses.append(why)

    if plan.structure == "up":
        score += 1
        plan.reasons.append("higher highs & lows")
    elif plan.structure == "down":
        plan.misses.append("structure down")

    if demand is not None and demand.contains(price, pad):
        score += 2
        plan.reasons.append(f"at {'fresh ' if demand.touches == 0 else ''}demand "
                            f"{demand.low:.4f}-{demand.high:.4f}")
    elif demand is not None and demand.touches == 0:
        score += 1
        plan.reasons.append("fresh demand below")

    if fib and fib.in_golden_pocket(price):
        score += 2
        plan.reasons.append("in fib 0.5-0.618 pocket")

    if plan.adx is not None and plan.adx >= p.adx_min:
        score += 1
        plan.reasons.append(f"ADX {plan.adx:.0f}")
    elif plan.adx is not None:
        plan.misses.append(f"ADX {plan.adx:.0f} < {p.adx_min:.0f}")

    rsi_v = ind.rsi(closes, 14)
    if rsi_v is not None and rsi_v <= p.rsi_max:
        score += 1
        plan.reasons.append(f"RSI {rsi_v:.0f}")
    elif rsi_v is not None:
        plan.misses.append(f"RSI {rsi_v:.0f} overbought")

    vols = [b.v for b in bars if b.v]
    if len(vols) >= 20 and bars[-1].v > (sum(vols[-20:]) / 20):
        score += 1
        plan.reasons.append("volume above average")

    plan.score = score

    # ---- decide ---- #
    # Only hard disqualifiers block. Everything else already spoke through the
    # score — blocking on it as well would double-penalise and make confluence
    # pointless, since a strong setup is allowed to carry one weak vote.
    if p.require_trend and not crossed_up:
        return plan
    if score < p.min_confluence:
        plan.blockers.append(f"confluence {score}/{MAX_SCORE} < {p.min_confluence}")
        return plan

    entry = price
    stop, basis = choose_stop(entry, atr_v, demand,
                              swing_lows[-1] if swing_lows else None, p)
    if stop >= entry:
        plan.blockers.append("no valid stop below entry")
        return plan

    plan.signal = "BUY"
    plan.entry = entry
    plan.stop = stop
    plan.reasons.append(f"stop {basis}")
    plan.targets = choose_targets(entry, stop, atr_v, zones, fib,
                                  swing_highs[-3:], p)
    return plan


def levels_for(price, atr_value, p: Params):
    """(stop, target) fallback for callers that just want the simple pair."""
    if p.use_atr_stops and atr_value:
        stop = price - p.atr_stop_mult * atr_value
        if stop <= 0 or stop >= price:
            stop = price * (1 - p.stop_loss_pct)
        return stop, price + p.reward_risk * (price - stop)
    return price * (1 - p.stop_loss_pct), price * (1 + p.take_profit_pct)


def trail_stop(current_stop, price, atr_value, p: Params):
    """Ratchet a stop upward by ATR. Never loosens."""
    if not atr_value:
        return current_stop
    return max(current_stop or 0.0, price - p.atr_stop_mult * atr_value)


sma = ind.sma


def generate_signal(closes, fast, slow, trend=0, buffer=0.0) -> str:
    """Close-only crossover, the original behaviour. Prefer `analyze()`."""
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
