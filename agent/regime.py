"""Deterministic market-regime classification. No LLM.

The regime decides WHICH STRUCTURE is appropriate. The LLM only supplies a
directional view within that structure — it never chooses the structure itself.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional

from . import config
from .options import ContractView, atm_iv, expected_move, iv_rank

# Regime names
HIGH_IV_RANGE = "HIGH_IV_RANGE"      # calm + expensive options -> sell premium, neutral
HIGH_IV_TREND = "HIGH_IV_TREND"      # trending + expensive     -> credit spread with the trend
LOW_IV_TREND = "LOW_IV_TREND"        # trending + cheap         -> debit spread with the trend
LOW_IV_RANGE = "LOW_IV_RANGE"        # calm + cheap             -> no edge, stand aside
EVENT_RISK = "EVENT_RISK"            # catalyst in window       -> stand aside


@dataclass
class Regime:
    name: str
    underlying: str
    spot: float
    iv: float
    iv_rank: Optional[float]
    trend_z: float
    trend_dir: int                    # +1 up, -1 down, 0 flat
    expected_move: float
    dte: int
    reason: str
    detail: dict = field(default_factory=dict)

    @property
    def tradable(self) -> bool:
        return self.name in (HIGH_IV_RANGE, HIGH_IV_TREND, LOW_IV_TREND)

    def summary(self) -> str:
        rk = f"{self.iv_rank:.2f}" if self.iv_rank is not None else "n/a"
        return (f"{self.underlying} ${self.spot:.2f} | {self.name} | IV {self.iv:.1%} "
                f"(rank {rk}) | trend z{self.trend_z:+.2f} | 1σ ${self.expected_move:.2f} "
                f"| {self.reason}")


def _sma(vals: List[float], n: int) -> Optional[float]:
    return sum(vals[-n:]) / n if len(vals) >= n else None


def trend_score(closes: List[float], fast: int = 20, slow: int = 50,
                structure: str = None) -> tuple:
    """Distance from the fast SMA, normalised by recent volatility. Returns (z, direction).

    `structure` is accepted and deliberately IGNORED for direction. Corroborating
    the z-score with levels.market_structure() was measured over 6 expiry cycles
    and made results worse both ways it was tried:

      veto on any disagreement   PF 1.56 -> 1.26   -$158
      veto only on the opposite  PF 1.56 -> 1.10   -$335

    market_structure() needs three consecutive higher highs AND higher lows, so
    on daily bars it returns "range" 14 times in 18 — treating that as a veto
    disabled the trend filter, which is the most valuable component in the
    system. In the single case where it actively disagreed (SPY 2026-08-03, z
    +1.92 up vs structure down) it was wrong, and the two call spreads it
    admitted lost $335.

    Structure is still computed and still reaches the LLM as context; it just
    does not decide which side gets sold. Reproduce with
    scripts/filter_ladder.py.
    """
    if len(closes) < fast + 2:
        return 0.0, 0
    spot = closes[-1]
    sma_f = _sma(closes, fast)
    rets = [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes))]
    sd = statistics.pstdev(rets[-fast:]) if len(rets) >= fast else 0.0
    if not sma_f or sd <= 0:
        return 0.0, 0
    z = (spot - sma_f) / (sma_f * sd)

    sma_s = _sma(closes, slow)
    direction = 0
    if abs(z) > config.TREND_Z_MIN:
        direction = 1 if z > 0 else -1
    if sma_s:
        # require the slower average to agree before calling it a trend
        if direction > 0 and spot < sma_s:
            direction = 0
        if direction < 0 and spot > sma_s:
            direction = 0

    # Swing structure is a second, independent read of the same question, built
    # from higher-highs/higher-lows rather than a mean and a standard deviation.
    # A direction only survives if both agree.
    #
    # This matters because trend_dir decides WHICH SIDE gets sold:
    # strategy.candidates() sells only the side the trend moves away from. On
    # 31 Aug 2026 IWM scored z-1.67 (down) while structure read up — so the
    # agent would have sold calls into a rising market, the single worst
    # configuration in docs/BACKTEST.md (call credit spreads, PF 0.44-0.57).
    return z, direction


def realized_vol(closes: List[float], window: int = 20) -> Optional[float]:
    """Annualised realised volatility, for comparison against implied."""
    if len(closes) < window + 1:
        return None
    rets = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))][-window:]
    return statistics.pstdev(rets) * math.sqrt(252)


def classify(underlying: str, spot: float, views: List[ContractView], closes: List[float],
             *, expiry: date, iv_history: List[float] = None,
             has_catalyst: bool = False, catalyst_note: str = "",
             structure: str = None, breaks: list = None) -> Regime:
    dte = max((expiry - date.today()).days, 1)
    iv = atm_iv(views, spot, expiry) or 0.0
    rank = iv_rank(iv, iv_history or [])
    z, direction = trend_score(closes)
    em = expected_move(spot, iv, dte)
    rv = realized_vol(closes)

    # `breaks` rides in detail rather than becoming a field: it does not classify
    # the regime, it only tells strategy.propose() which strikes have a level in
    # front of them. Unlike `structure`, it is not inert — see
    # config.RETEST_BARRIER_BONUS.
    detail = {"realized_vol": rv, "iv_minus_rv": (iv - rv) if rv else None,
              "n_contracts": len(views), "n_closes": len(closes),
              "breaks": breaks or []}

    if has_catalyst:
        return Regime(EVENT_RISK, underlying, spot, iv, rank, z, direction, em, dte,
                      catalyst_note or "catalyst inside the option's life", detail)

    if iv <= 0 or not views:
        return Regime(LOW_IV_RANGE, underlying, spot, iv, rank, z, direction, em, dte,
                      "no usable option data", detail)

    # Without IV history we fall back to comparing implied against realised vol:
    # implied meaningfully above realised == premium is rich.
    if rank is not None:
        rich = rank > config.IV_RANK_RICH
        cheap = rank < config.IV_RANK_CHEAP
        basis = f"IV rank {rank:.2f}"
    elif rv:
        rich = iv > rv * config.IV_OVER_RV_RICH
        cheap = iv < rv * config.IV_OVER_RV_CHEAP
        basis = f"IV {iv:.1%} vs realised {rv:.1%} ({iv/rv:.2f}x)"
    else:
        rich = cheap = False
        basis = "no volatility baseline"

    trending = direction != 0

    if rich and not trending:
        return Regime(HIGH_IV_RANGE, underlying, spot, iv, rank, z, direction, em, dte,
                      f"{basis}, no trend (z{z:+.2f}) -> sell premium, delta-neutral", detail)
    if rich and trending:
        return Regime(HIGH_IV_TREND, underlying, spot, iv, rank, z, direction, em, dte,
                      f"{basis}, trend {'up' if direction > 0 else 'down'} "
                      f"-> credit spread with the trend", detail)
    if cheap and trending:
        return Regime(LOW_IV_TREND, underlying, spot, iv, rank, z, direction, em, dte,
                      f"{basis}, trend {'up' if direction > 0 else 'down'} "
                      f"-> debit spread with the trend", detail)
    return Regime(LOW_IV_RANGE, underlying, spot, iv, rank, z, direction, em, dte,
                  f"{basis}, no clear edge -> stand aside", detail)
