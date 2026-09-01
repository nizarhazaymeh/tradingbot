"""Spot crypto: the directional half of the agent, and a different risk model.

WHY THIS IS A SEPARATE MODULE, NOT A NEW `underlying`

The options agent sells variance risk premium: implied volatility exceeds
subsequently realised volatility, and that gap is the edge. Alpaca lists no
options on crypto spot — `BTC/USD` returns zero option contracts — so none of
that transfers. What is left is direction, which the rest of this repo has spent
four backtests establishing it cannot predict reliably.

So this module makes two things explicit rather than pretending otherwise:

  1. The signal is a BREAK OF STRUCTURE that price returned to and respected.
     levels.breaks() already computes it. It could not earn a place in options
     selection (docs/BACKTEST.md Part 7) for a specific reason — a barrier is a
     property of the entry, and premium selling is not directional, so there was
     nothing for it to decide. Spot IS directional. This is the pattern's natural
     home, and the first place it can express what it actually says.

  2. RISK IS BOUNDED DIFFERENTLY, AND LESS WELL. A vertical spread's long wing
     caps the loss at the width, arithmetically, whatever the market does
     overnight. Spot has no wing. A stop is a PLAN, not a guarantee: crypto gaps
     through stops, and there is no auction to stop it. So sizing is bounded
     twice —

       by the stop      qty = risk_dollars / (entry - stop)
       by the notional  qty <= MAX_NOTIONAL_PCT of equity

     The notional cap is what replaces the wing. It is the answer to "what if the
     stop does not hold": at CRYPTO_MAX_NOTIONAL_PCT the position going to zero
     costs that much of the account and no more. The README's claim that the
     account cannot blow up survives only because of that second bound.

Long only. Alpaca does not support shorting spot crypto, so a bearish break is
an exit signal, never an entry.

Everything takes levels.Bar sequences, oldest first — the same contract the rest
of the technical layer uses, and /v1beta3/crypto/us/bars rows feed it unchanged.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

from . import config, indicators as ind, levels as L

LONG = "long"

# exit actions, mirroring monitor.py's vocabulary
HOLD = "hold"
CLOSE = "close"


@dataclass
class Signal:
    symbol: str
    side: str                 # always LONG — see the module docstring
    entry: float
    stop: float               # invalidation: below the level price reclaimed
    target: float
    level: float              # the broken-and-retested level itself
    atr: float
    reason: str
    detail: dict = field(default_factory=dict)

    @property
    def risk_per_unit(self) -> float:
        return max(self.entry - self.stop, 0.0)

    @property
    def reward_per_unit(self) -> float:
        return max(self.target - self.entry, 0.0)

    @property
    def rr(self) -> float:
        return self.reward_per_unit / self.risk_per_unit if self.risk_per_unit else 0.0

    def summary(self) -> str:
        return (f"{self.symbol} {self.side} @ {self.entry:,.2f} "
                f"stop {self.stop:,.2f} target {self.target:,.2f} "
                f"({self.rr:.1f}R) — {self.reason}")


def signal(symbol: str, bars: List[L.Bar]) -> Optional[Signal]:
    """A confirmed bullish break of structure, or None.

    The entry condition is deliberately narrow: the most recent break must be
    upward AND confirmed, meaning price came back to the level it broke and
    closed above it. A pending break is a candle; a failed one is a trap. Only a
    level the market has been handed a chance to reject and did not counts.

    The stop goes below that level, not at an arbitrary ATR multiple, because the
    level IS the thesis — if price closes back under it the reason for being long
    has gone. The buffer keeps the stop out of the noise that a retest generates
    by definition.
    """
    if len(bars) < 60:
        return None
    highs = [b.h for b in bars]
    lows = [b.l for b in bars]
    closes = [b.c for b in bars]
    atr = ind.atr(highs, lows, closes, config.CRYPTO_ATR_PERIOD)
    if not atr or atr <= 0:
        return None

    brks = L.breaks(bars, atr_period=config.CRYPTO_ATR_PERIOD)
    if not brks:
        return None
    last = brks[-1]
    if last.direction <= 0 or not last.confirmed:
        return None

    # Stale structure is not structure. A break confirmed forty bars ago has been
    # overtaken by whatever happened since.
    age = len(bars) - 1 - last.index
    if age > config.CRYPTO_MAX_SIGNAL_AGE:
        return None

    entry = closes[-1]
    stop = last.level - config.CRYPTO_STOP_BUFFER_ATR * atr
    if stop >= entry:
        return None                      # price already back under the level
    risk = entry - stop
    if risk > config.CRYPTO_MAX_STOP_ATR * atr:
        return None                      # too far from the level to size sanely
    target = entry + config.CRYPTO_TARGET_R * risk

    return Signal(symbol=symbol, side=LONG, entry=entry, stop=stop, target=target,
                  level=last.level, atr=atr,
                  reason=(f"bullish break of {last.level:,.2f} confirmed on retest "
                          f"{age} bars ago"),
                  detail={"break_index": last.index, "retest_index": last.retest_index,
                          "extent_atr": last.extent_atr, "age_bars": age})


def size(signal: Signal, equity: float) -> tuple:
    """(qty, risk_dollars, notional) under BOTH bounds. qty 0 means do not trade.

    Bound 1 — the stop. Standard risk-per-trade sizing: the planned loss is
    CRYPTO_RISK_PER_TRADE_PCT of equity if the stop fills where it is placed.

    Bound 2 — the notional. What bound 1 cannot do is survive a gap, and crypto
    gaps hardest exactly when a stop matters. Capping notional means a position
    that goes to ZERO — the true worst case for spot, not a theoretical one —
    costs CRYPTO_MAX_NOTIONAL_PCT of the account. This is the wing a spread has
    and spot does not, and it is why the whole account still cannot be lost on
    one trade.

    Crypto is fractionable, so qty is not rounded to whole units; it is floored to
    a sane precision instead.
    """
    if equity <= 0 or signal.risk_per_unit <= 0 or signal.entry <= 0:
        return 0.0, 0.0, 0.0
    by_stop = (equity * config.CRYPTO_RISK_PER_TRADE_PCT) / signal.risk_per_unit
    by_notional = (equity * config.CRYPTO_MAX_NOTIONAL_PCT) / signal.entry
    qty = round(min(by_stop, by_notional), 6)
    if qty <= 0:
        return 0.0, 0.0, 0.0
    return qty, round(qty * signal.risk_per_unit, 2), round(qty * signal.entry, 2)


def evaluate_exit(position: dict, price: float, bars: List[L.Bar] = None,
                  now: datetime = None) -> tuple:
    """(action, reason). The stop is checked FIRST and unconditionally.

    Order matters. A bar that trades through both the stop and the target is
    ambiguous on daily data, and resolving it in favour of the target would
    flatter every backtest that uses this function. The loss is assumed.
    """
    stop = float(position.get("stop") or 0)
    target = float(position.get("target") or 0)
    entry = float(position.get("entry") or 0)

    if stop and price <= stop:
        return CLOSE, f"stop {stop:,.2f} hit at {price:,.2f}"
    if target and price >= target:
        return CLOSE, f"target {target:,.2f} reached at {price:,.2f}"

    # Structure invalidated: the thesis was a level holding, and it stopped.
    if bars:
        brks = L.breaks(bars, atr_period=config.CRYPTO_ATR_PERIOD)
        if brks and brks[-1].direction < 0 and brks[-1].confirmed:
            return CLOSE, (f"bearish break of {brks[-1].level:,.2f} confirmed — "
                           f"the long thesis is gone")

    opened = position.get("opened_at")
    if opened and config.CRYPTO_TIME_STOP_HOURS:
        try:
            t0 = datetime.fromisoformat(str(opened).replace("Z", "+00:00"))
            age_h = ((now or datetime.now(timezone.utc)) - t0).total_seconds() / 3600
            if age_h >= config.CRYPTO_TIME_STOP_HOURS:
                return CLOSE, f"time stop at {age_h:.0f}h"
        except ValueError:
            pass

    pnl = (price - entry) * float(position.get("qty") or 0)
    return HOLD, f"holding: P&L ${pnl:,.0f}, {price:,.2f} vs stop {stop:,.2f}"


# --------------------------------------------------------------- day boundary
def crypto_day_start(now: datetime = None) -> datetime:
    """UTC midnight — the only day boundary a 24/7 market has.

    risk.circuit_breakers() measures the daily drawdown against Alpaca's
    `last_equity`, which is the previous EQUITY-market close. That number is
    meaningless for a market that never closed: at 03:00 UTC on a Sunday it is
    two days stale, and a 24/7 book can have moved a long way inside it.

    Crypto exchanges settle on UTC midnight and so does every funding calculation
    in the industry, so that is the boundary used here.
    """
    n = now or datetime.now(timezone.utc)
    return n.replace(hour=0, minute=0, second=0, microsecond=0)
