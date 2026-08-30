"""Expected-value test for defined-risk option spreads.

A fixed "credit must be >= 12% of width" rule of thumb is wrong: it comes from
30-45 DTE trades and rejects everything at short DTE. The principled test is
whether the premium actually compensates for the probability-weighted loss.

We use delta as a probability proxy (standard practice: |delta| ~= P(finish ITM))
and integrate the payoff across the three outcome regions of a vertical spread.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def prob_itm(spot: float, strike: float, iv: float, dte_days: int,
             kind: str, r: float = 0.0) -> Optional[float]:
    """True risk-neutral P(finish in the money) = N(d2) for calls, N(-d2) for puts.

    Delta is N(d1), which is NOT the same thing: for OTM options delta
    systematically OVERSTATES P(ITM) by roughly the sigma*sqrt(T) shift. Using
    delta as a probability makes every spread look worse than it is, so we
    compute d2 directly wherever spot/IV/DTE are available.
    """
    if spot <= 0 or strike <= 0 or iv <= 0 or dte_days <= 0:
        return None
    t = dte_days / 365.0
    vol_t = iv * math.sqrt(t)
    if vol_t <= 0:
        return None
    d1 = (math.log(spot / strike) + (r + 0.5 * iv * iv) * t) / vol_t
    d2 = d1 - vol_t
    return _norm_cdf(d2) if kind.upper().startswith("C") else _norm_cdf(-d2)

from . import config
from .options import ContractView
from .spreads import Spread


def tilt_from_view(view, spread_kind: str, short_kind: str) -> float:
    """How far to shift market-implied probabilities toward our own view.

    Delta-implied probabilities assume the market is correctly priced — and our
    measurements confirm every vanilla spread is priced at or just below fair
    value once you cross the bid-ask. So a spread is only worth trading when our
    view DISAGREES with the market by enough to cover that cost.

    Returns a multiplier applied to the short strike's ITM probability:
      < 1.0  our view says that strike is LESS likely to be breached
      > 1.0  more likely
    """
    if view is None:
        return 1.0
    bias = getattr(view, "bias", 0)
    if bias == 0:
        return 1.0
    conf = max(0.0, min(1.0, getattr(view, "confidence", 0.5)))
    strength = max(0.0, (conf - 0.55) / 0.45)          # 0 at conf .55, 1 at conf 1.0
    tilt = strength * config.MAX_VIEW_TILT
    if strength <= 0:
        return 1.0

    # Which direction hurts this structure?
    #   short PUT  is breached by a move DOWN
    #   short CALL is breached by a move UP
    hurt_by = -1 if short_kind == "P" else 1
    return (1.0 + tilt) if bias == hurt_by else (1.0 - tilt)


@dataclass
class Expectancy:
    ev_per_unit: float          # dollars
    ev_ratio: float             # EV / max_loss
    p_max_profit: float
    p_partial: float
    p_max_loss: float
    breakeven: Optional[float]

    def summary(self) -> str:
        return (f"EV ${self.ev_per_unit:+.2f}/unit ({self.ev_ratio:+.1%} of risk) | "
                f"P(win) {self.p_max_profit:.0%} P(partial) {self.p_partial:.0%} "
                f"P(maxloss) {self.p_max_loss:.0%}")


def _p_itm(v: ContractView, spot: Optional[float],
           real_vol: Optional[float] = None) -> float:
    """P(finish ITM) under the REAL-WORLD measure.

    Key point: if you compute probabilities with the market's own implied vol,
    every option is fair by construction and EV is always ~0 minus the bid-ask.
    The documented edge in index options is the variance risk premium — implied
    vol persistently exceeds subsequently realised vol. So we PRICE with implied
    vol (that is the premium we actually receive) but compute PROBABILITIES with
    realised vol (that is how the underlying actually behaves).

    The gap between the two IS the edge, and it shows up honestly in the EV.
    """
    vol = real_vol if (real_vol and real_vol > 0) else v.iv
    if spot:
        p = prob_itm(spot, v.strike, vol, v.dte, v.kind)
        if p is not None:
            return min(max(p, 0.0), 1.0)
    return min(max(abs(v.delta), 0.0), 1.0)


def _vertical_ev(short: ContractView, long_: ContractView, credit: float,
                 width: float, tilt: float = 1.0,
                 spot: Optional[float] = None,
                 real_vol: Optional[float] = None) -> Expectancy:
    """EV of a credit vertical, in premium units (per share, x100 for dollars).

    Three regions at expiry:
      * beyond the short strike      -> keep the full credit
      * between short and long       -> partial loss, average ~ width/2
      * beyond the long strike       -> max loss = width - credit
    """
    p_short_itm = min(max(_p_itm(short, spot, real_vol) * tilt, 0.0), 1.0)
    p_long_itm = min(max(_p_itm(long_, spot, real_vol) * tilt, 0.0), 1.0)
    p_long_itm = min(p_long_itm, p_short_itm)          # long is further OTM

    p_max_loss = p_long_itm
    p_partial = max(p_short_itm - p_long_itm, 0.0)
    p_max_profit = max(1.0 - p_short_itm, 0.0)

    ev = (p_max_profit * credit
          + p_partial * (credit - width / 2.0)
          + p_max_loss * (credit - width))

    max_loss = max(width - credit, 1e-9)
    return Expectancy(ev_per_unit=round(ev * 100, 2),
                      ev_ratio=ev / max_loss,
                      p_max_profit=p_max_profit, p_partial=p_partial,
                      p_max_loss=p_max_loss,
                      breakeven=(short.strike - credit if short.kind == "P"
                                 else short.strike + credit))


def _debit_ev(long_: ContractView, short: ContractView, debit: float,
              width: float, tilt: float = 1.0,
              spot: Optional[float] = None,
              real_vol: Optional[float] = None) -> Expectancy:
    """EV of a debit vertical. Wins when the underlying moves through the strikes."""
    # For a debit spread the tilt works the other way: our view making the move
    # MORE likely raises the chance both strikes finish ITM.
    inv = (2.0 - tilt) if tilt != 1.0 else 1.0
    p_long_itm = min(max(_p_itm(long_, spot, real_vol) * inv, 0.0), 1.0)
    p_short_itm = min(max(_p_itm(short, spot, real_vol) * inv, 0.0), p_long_itm)

    p_max_profit = p_short_itm                          # both strikes ITM
    p_partial = max(p_long_itm - p_short_itm, 0.0)
    p_max_loss = max(1.0 - p_long_itm, 0.0)

    ev = (p_max_profit * (width - debit)
          + p_partial * (width / 2.0 - debit)
          + p_max_loss * (-debit))

    return Expectancy(ev_per_unit=round(ev * 100, 2),
                      ev_ratio=ev / max(debit, 1e-9),
                      p_max_profit=p_max_profit, p_partial=p_partial,
                      p_max_loss=p_max_loss,
                      breakeven=(long_.strike + debit if long_.kind == "C"
                                 else long_.strike - debit))


def evaluate(spread: Spread, view=None, spot: float = None,
             real_vol: float = None) -> Optional[Expectancy]:
    """Expected value for a whole structure. Returns None if Greeks are missing."""
    legs = [l for l in spread.legs if l.view is not None]
    if len(legs) != len(spread.legs):
        return None

    if spread.kind in ("bull_put", "bear_call"):
        short = next(l.view for l in spread.legs if l.side == "sell")
        long_ = next(l.view for l in spread.legs if l.side == "buy")
        t = tilt_from_view(view, spread.kind, short.kind)
        return _vertical_ev(short, long_, abs(spread.net_price), spread.width, t, spot, real_vol)

    if spread.kind in ("bull_call", "bear_put"):
        long_ = next(l.view for l in spread.legs if l.side == "buy")
        short = next(l.view for l in spread.legs if l.side == "sell")
        t = tilt_from_view(view, spread.kind, long_.kind)
        return _debit_ev(long_, short, abs(spread.net_price), spread.width, t, spot, real_vol)

    if spread.kind in ("iron_condor", "iron_butterfly"):
        puts = sorted([l.view for l in spread.legs if l.view.kind == "P"],
                      key=lambda v: v.strike)
        calls = sorted([l.view for l in spread.legs if l.view.kind == "C"],
                       key=lambda v: v.strike)
        if len(puts) != 2 or len(calls) != 2:
            return None
        long_put, short_put = puts[0], puts[1]
        short_call, long_call = calls[0], calls[1]
        credit = abs(spread.net_price)

        # split the credit across the two wings in proportion to their risk
        put_w = short_put.strike - long_put.strike
        call_w = long_call.strike - short_call.strike
        total_w = put_w + call_w or 1.0
        put_credit = credit * (put_w / total_w)
        call_credit = credit * (call_w / total_w)

        pe = _vertical_ev(short_put, long_put, put_credit, put_w,
                          tilt_from_view(view, spread.kind, "P"), spot, real_vol)
        ce = _vertical_ev(short_call, long_call, call_credit, call_w,
                          tilt_from_view(view, spread.kind, "C"), spot, real_vol)

        ev = (pe.ev_per_unit + ce.ev_per_unit) / 100.0
        max_loss = max(max(put_w, call_w) - credit, 1e-9)
        p_loss = pe.p_max_loss + ce.p_max_loss
        p_partial = pe.p_partial + ce.p_partial
        return Expectancy(ev_per_unit=round(ev * 100, 2),
                          ev_ratio=ev / max_loss,
                          p_max_profit=max(1.0 - p_loss - p_partial, 0.0),
                          p_partial=p_partial, p_max_loss=p_loss,
                          breakeven=None)
    return None
