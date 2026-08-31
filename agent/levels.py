"""Market structure: swing pivots, supply/demand zones, Fibonacci levels.

This is the part of the system that answers WHERE — where price is likely to
turn, so the strategy has real places to put an entry, a stop and targets
instead of deriving everything from a single ATR multiple.

Three ideas, all built on the same swing detection:

  pivots            the swing highs and lows that define structure
  zones             supply/demand — the base a big move launched from, which
                    tends to react again when price returns to it
  fibonacci         retracements of the last impulse (entries) and extensions
                    beyond it (targets)

Everything takes Bar(t, c, h, l, v) sequences, oldest first.
"""
from collections import namedtuple
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

from . import indicators as ind

# The contract every function here expects, oldest bar first. This lived in the
# pre-refactor root strategy.py; without it nothing could feed this module, which
# is why it sat unused.
Bar = namedtuple("Bar", "t c h l v")


def bars_from_api(rows: Sequence[dict]) -> List[Bar]:
    """Alpaca /v2/stocks/bars rows -> Bar sequence.

    Rows arrive as dicts with t/o/h/l/c/v. Bars missing a high or low are
    dropped rather than back-filled from the close: a synthetic zero-range bar
    would suppress the ATR and manufacture impulses that never happened.
    """
    out: List[Bar] = []
    for r in rows or []:
        try:
            h, l, c = float(r["h"]), float(r["l"]), float(r["c"])
        except (KeyError, TypeError, ValueError):
            continue
        if h <= 0 or l <= 0 or h < l:
            continue
        out.append(Bar(r.get("t"), c, h, l, float(r.get("v") or 0)))
    return out


# --------------------------------------------------------------------------- #
# Swing pivots
# --------------------------------------------------------------------------- #
@dataclass
class Pivot:
    index: int
    price: float
    kind: str  # "high" | "low"


def pivots(bars, left: int = 3, right: int = 3) -> List[Pivot]:
    """Swing points confirmed by `right` bars on the far side.

    A pivot is only real once `right` later bars have failed to exceed it, so
    the most recent `right` bars can never produce one. That lag is the price of
    not repainting — a pivot found here would still have been visible live.
    """
    out: List[Pivot] = []
    highs = [b.h for b in bars]
    lows = [b.l for b in bars]
    for i in range(left, len(bars) - right):
        window_h = highs[i - left:i + right + 1]
        window_l = lows[i - left:i + right + 1]
        if highs[i] == max(window_h) and highs[i] > max(highs[i - left:i] or [float("-inf")]):
            out.append(Pivot(i, highs[i], "high"))
        elif lows[i] == min(window_l) and lows[i] < min(lows[i - left:i] or [float("inf")]):
            out.append(Pivot(i, lows[i], "low"))
    return out


def market_structure(pv: List[Pivot]) -> str:
    """"up" (higher highs AND higher lows), "down", or "range"."""
    highs = [p.price for p in pv if p.kind == "high"][-3:]
    lows = [p.price for p in pv if p.kind == "low"][-3:]
    if len(highs) < 2 or len(lows) < 2:
        return "range"
    hh = highs[-1] > highs[-2]
    hl = lows[-1] > lows[-2]
    if hh and hl:
        return "up"
    if not hh and not hl:
        return "down"
    return "range"


# --------------------------------------------------------------------------- #
# Supply & demand zones
# --------------------------------------------------------------------------- #
@dataclass
class Zone:
    low: float
    high: float
    kind: str          # "demand" (support) | "supply" (resistance)
    index: int         # bar where the base sat
    touches: int = 0   # times price has returned since; 0 = fresh = strongest
    strength: float = 0.0  # size of the impulse that left it, in ATR

    @property
    def mid(self) -> float:
        return (self.low + self.high) / 2

    def contains(self, price: float, pad: float = 0.0) -> bool:
        return (self.low - pad) <= price <= (self.high + pad)


def find_zones(bars, atr_period: int = 14, impulse_atr: float = 1.8,
               base_max: int = 3, lookback: int = 300) -> List[Zone]:
    """Detect supply/demand zones from base-then-impulse patterns.

    The logic mirrors how these are drawn by hand: find a decisive move (an
    impulse of at least `impulse_atr` ATR), walk back to the quiet bars that
    preceded it (the base), and mark that base as the zone. Price returning
    there is returning to where the imbalance started.

    Zones are then aged: every later bar that trades back inside counts as a
    touch, because a zone that has already been worked twice rarely holds.
    """
    if len(bars) < atr_period * 3:
        return []
    closes = [b.c for b in bars]
    highs = [b.h for b in bars]
    lows = [b.l for b in bars]
    atr_s = ind.atr_series(highs, lows, closes, atr_period)

    start = max(atr_period * 2, len(bars) - lookback)
    zones: List[Zone] = []

    for i in range(start, len(bars)):
        a = atr_s[i]
        if not a:
            continue
        move = closes[i] - closes[i - 1]
        if abs(move) < impulse_atr * a:
            continue  # not decisive enough to leave an imbalance

        # Walk back over the quiet bars that formed the base.
        base_end = i - 1
        base_start = base_end
        for j in range(base_end, max(base_end - base_max, start) - 1, -1):
            if (highs[j] - lows[j]) <= a:      # a quiet bar belongs to the base
                base_start = j
            else:
                break

        z_low = min(lows[base_start:base_end + 1])
        z_high = max(highs[base_start:base_end + 1])
        if z_high <= z_low:
            continue
        zones.append(Zone(
            low=z_low, high=z_high,
            kind="demand" if move > 0 else "supply",
            index=base_start, strength=abs(move) / a,
        ))

    # Age them: how often has price traded back into each since it formed?
    for z in zones:
        for k in range(z.index + 2, len(bars)):
            if bars[k].l <= z.high and bars[k].h >= z.low:
                z.touches += 1

    # Merge overlapping same-kind zones so one area isn't counted three times.
    merged: List[Zone] = []
    for z in sorted(zones, key=lambda x: x.low):
        prev = merged[-1] if merged else None
        if prev and prev.kind == z.kind and z.low <= prev.high:
            prev.high = max(prev.high, z.high)
            prev.strength = max(prev.strength, z.strength)
            prev.touches = min(prev.touches, z.touches)
            prev.index = max(prev.index, z.index)
        else:
            merged.append(z)
    return merged


def nearest_zone(zones: List[Zone], price: float, kind: str,
                 below: bool) -> Optional[Zone]:
    """Closest zone of `kind` on one side of price (below=support, above=target)."""
    side = [z for z in zones if z.kind == kind
            and (z.high <= price if below else z.low >= price)]
    if not side:
        return None
    return max(side, key=lambda z: z.high) if below else min(side, key=lambda z: z.low)


# --------------------------------------------------------------------------- #
# Fibonacci
# --------------------------------------------------------------------------- #
RETRACEMENTS = (0.236, 0.382, 0.5, 0.618, 0.786)
EXTENSIONS = (1.272, 1.618, 2.0)


@dataclass
class Fib:
    low: float
    high: float
    retracements: dict = field(default_factory=dict)
    extensions: dict = field(default_factory=dict)

    @property
    def golden_low(self) -> float:
        return self.retracements[0.618]

    @property
    def golden_high(self) -> float:
        return self.retracements[0.5]

    def in_golden_pocket(self, price: float) -> bool:
        """The 0.5-0.618 band, where pullbacks in a trend most often end."""
        return self.golden_low <= price <= self.golden_high


def last_impulse(bars, pv: List[Pivot]) -> Optional[Tuple[float, float]]:
    """(low, high) of the most recent up-leg: last swing low -> the high after it."""
    lows = [p for p in pv if p.kind == "low"]
    highs = [p for p in pv if p.kind == "high"]
    if not lows or not highs:
        return None
    lo = lows[-1]
    after = [h for h in highs if h.index > lo.index]
    if after:
        hi = max(after, key=lambda p: p.price)
    else:
        tail = [b.h for b in bars[lo.index:]]
        if not tail:
            return None
        hi = Pivot(lo.index, max(tail), "high")
    if hi.price <= lo.price:
        return None
    return lo.price, hi.price


def fibonacci(low: float, high: float) -> Fib:
    """Retracements measured down from `high`, extensions projected above it."""
    span = high - low
    return Fib(
        low=low, high=high,
        retracements={r: high - span * r for r in RETRACEMENTS},
        extensions={e: low + span * e for e in EXTENSIONS},
    )


def protects_short(zones: List[Zone], spot: float, strike: float, kind: str,
                   max_touches: int = 3) -> Optional[Zone]:
    """The zone standing between spot and a short strike, if there is one.

    A short call is threatened only if price rises to its strike, so a supply
    zone between spot and that strike is a barrier price must break first. The
    mirror holds for a short put and a demand zone.

    Zones worked more than `max_touches` times are ignored — find_zones() ages
    them for exactly this reason, and a level that has already failed four times
    is not protection.

    Returns the zone, or None. This is a diagnostic: it is recorded against
    every entry so protection can be validated against realised outcomes before
    it is allowed to influence strike choice.
    """
    if kind == "C":
        cands = [z for z in zones if z.kind == "supply"
                 and spot < z.mid < strike and z.touches <= max_touches]
        return min(cands, key=lambda z: z.mid) if cands else None
    cands = [z for z in zones if z.kind == "demand"
             and strike < z.mid < spot and z.touches <= max_touches]
    return max(cands, key=lambda z: z.mid) if cands else None
