"""Structure selection: regime + directional view -> a concrete, priced spread.

This is deterministic code. The LLM supplies only a *view* (direction/conviction);
every strike, width and price is chosen here by rule, from Greeks and expected move.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Optional

from . import config
from . import expectancy as EX
from . import options as O
from . import spreads as S
from .regime import (Regime, HIGH_IV_RANGE, HIGH_IV_TREND, LOW_IV_TREND,
                     LOW_IV_RANGE, EVENT_RISK)


@dataclass
class View:
    """What the LLM is allowed to decide. Nothing else."""
    direction: str = "neutral"        # up | down | neutral
    magnitude: str = "small"          # small | medium | large
    horizon_days: int = 3
    confidence: float = 0.5
    thesis: str = ""
    source: str = "default"

    @property
    def bias(self) -> int:
        return {"up": 1, "down": -1}.get(self.direction, 0)


NEUTRAL = View(source="neutral-default")


def _increment(views: List[O.ContractView], kind: str, expiry: date) -> float:
    return max(O.typical_width(O.strike_ladder(views, kind, expiry)), 0.5)


def _ladder_width(views: List[O.ContractView], kind: str, expiry: date) -> float:
    return _increment(views, kind, expiry) * config.WING_STRIKES


def widest_that_fits(budget: float, builder, *, increment: float,
                     max_strikes: int = None, min_strikes: int = 2):
    """Try wing widths from wide to narrow; return the widest structure whose
    one-unit max loss fits inside `budget`.

    Wider wings collect more premium but risk more. Rather than fail outright when
    the default width is too big, we step down until one fits — so a tight risk
    budget produces a smaller trade instead of no trade.
    """
    max_strikes = max_strikes or config.WING_STRIKES
    best_oversized = None
    for n in range(max_strikes, min_strikes - 1, -1):
        sp = builder(increment * n)
        if sp is None:
            continue
        if sp.max_loss_per_unit <= budget:
            sp.meta["wing_strikes"] = n
            return sp
        best_oversized = best_oversized or sp
    return None


def build_iron_condor(reg: Regime, views: List[O.ContractView], expiry: date,
                      sigma_mult: float = 1.25, budget: float = None) -> Optional[S.Spread]:
    em = reg.expected_move
    short_put = O.by_strike(views, reg.spot - sigma_mult * em, "P", expiry)
    short_call = O.by_strike(views, reg.spot + sigma_mult * em, "C", expiry)
    if not short_put or not short_call:
        return None

    def build(width: float):
        lp = O.wing(views, short_put, width)
        lc = O.wing(views, short_call, width)
        if not lp or not lc:
            return None
        if lp.strike >= short_put.strike or lc.strike <= short_call.strike:
            return None
        return S.iron_condor(lp, short_put, short_call, lc)

    inc = _increment(views, "C", expiry)
    sp = (widest_that_fits(budget, build, increment=inc) if budget
          else build(inc * config.WING_STRIKES))
    if sp is None:
        return None
    sp.meta.update(regime=reg.name, sigma_mult=sigma_mult,
                   short_deltas=[round(short_put.delta, 3), round(short_call.delta, 3)])
    return sp


def build_credit_vertical(reg: Regime, views: List[O.ContractView], expiry: date,
                          bias: int, budget: float = None) -> Optional[S.Spread]:
    """Sell premium on the side the trend is moving AWAY from."""
    kind = "P" if bias > 0 else "C"
    short = O.by_delta(views, config.SHORT_DELTA_CREDIT, kind, expiry)
    if not short:
        return None

    def build(width: float):
        long_ = O.wing(views, short, width)
        if not long_:
            return None
        if bias > 0:
            if long_.strike >= short.strike:
                return None
            return S.bull_put_spread(short, long_)
        if long_.strike <= short.strike:
            return None
        return S.bear_call_spread(short, long_)

    inc = _increment(views, kind, expiry)
    sp = (widest_that_fits(budget, build, increment=inc) if budget
          else build(inc * config.WING_STRIKES))
    if sp is None:
        return None
    sp.meta.update(regime=reg.name, short_delta=round(short.delta, 3))
    return sp


def build_debit_vertical(reg: Regime, views: List[O.ContractView], expiry: date,
                         bias: int) -> Optional[S.Spread]:
    """Pay a little for directional exposure when options are cheap."""
    kind = "C" if bias > 0 else "P"
    long_ = O.by_delta(views, config.LONG_DELTA_DEBIT, kind, expiry)
    short = O.by_delta(views, config.SHORT_DELTA_DEBIT, kind, expiry)
    if not long_ or not short or long_.symbol == short.symbol:
        return None

    if bias > 0:
        if short.strike <= long_.strike:
            return None
        sp = S.bull_call_spread(long_, short)
    else:
        if short.strike >= long_.strike:
            return None
        sp = S.bear_put_spread(long_, short)

    sp.meta.update(regime=reg.name,
                   long_delta=round(long_.delta, 3), short_delta=round(short.delta, 3))
    return sp


def find_roll_target(old_short: O.ContractView, views: List[O.ContractView],
                     expiry: date, *, width: float,
                     min_delta_improvement: float = 0.10) -> Optional[tuple]:
    """Pick a further-OTM strike to roll a threatened short leg to.

    Requires a meaningful delta improvement — rolling to a strike barely further
    out just pays the spread twice for almost no protection.
    """
    kind = old_short.kind
    target_delta = max(config.SHORT_DELTA_CREDIT,
                       abs(old_short.delta) - min_delta_improvement)
    new_short = O.by_delta(views, target_delta, kind, expiry)
    if not new_short:
        return None
    # must actually be further out of the money than what we hold
    if kind == "P" and new_short.strike >= old_short.strike:
        return None
    if kind == "C" and new_short.strike <= old_short.strike:
        return None
    if abs(new_short.delta) > abs(old_short.delta) - min_delta_improvement / 2:
        return None
    new_long = O.wing(views, new_short, width)
    if not new_long:
        return None
    if kind == "P" and new_long.strike >= new_short.strike:
        return None
    if kind == "C" and new_long.strike <= new_short.strike:
        return None
    return new_short, new_long


def quality_gate(sp: S.Spread, reg: Regime = None, view: "View" = None) -> Optional[str]:
    """Reject structures whose risk/reward or exposure is not worth taking."""
    if sp.width <= 0:
        return "zero width"

    # Short strikes must sit outside the expected move. A short leg inside 1σ is
    # a coin flip dressed up as an income trade — especially at low DTE.
    if reg and reg.expected_move > 0:
        for leg in sp.legs:
            if leg.side != "sell" or leg.view is None:
                continue
            sigma_out = abs(leg.view.strike - reg.spot) / reg.expected_move
            if sigma_out < config.MIN_SHORT_SIGMA:
                return (f"short {leg.view.strike:.0f}{leg.view.kind} is only "
                        f"{sigma_out:.2f}σ from spot (need {config.MIN_SHORT_SIGMA:.1f}σ)")

    # Cap directional exposure per unit — a "credit spread" with huge delta is
    # really a naked directional bet.
    per_unit_delta = sp.net_delta / max(sp.qty, 1)
    if abs(per_unit_delta) > config.MAX_ABS_NET_DELTA:
        return (f"net delta {per_unit_delta:+.2f}/unit exceeds "
                f"±{config.MAX_ABS_NET_DELTA}")
    ratio = abs(sp.net_price) / sp.width
    if sp.is_credit:
        if ratio < config.MIN_CREDIT_RATIO:
            return (f"credit ${abs(sp.net_price):.2f} is only {ratio:.0%} of "
                    f"${sp.width:.0f} width (need {config.MIN_CREDIT_RATIO:.0%})")
        if sp.net_theta <= 0:
            return f"credit structure with non-positive theta ({sp.net_theta:+.2f})"
    else:
        if ratio > config.MAX_DEBIT_RATIO:
            return (f"debit ${sp.net_price:.2f} is {ratio:.0%} of ${sp.width:.0f} width "
                    f"(max {config.MAX_DEBIT_RATIO:.0%})")
    if sp.max_gain_per_unit <= 0:
        return "no upside"

    # ---- the real test: positive expected value ---------------------------
    # Priced with implied vol (the premium we receive), probabilities computed
    # with realised vol (how the underlying actually behaves). The gap is the
    # variance risk premium — that is the edge, and it must clear our threshold.
    rv = (reg.detail or {}).get("realized_vol") if reg else None
    ev = EX.evaluate(sp, view=view, spot=(reg.spot if reg else None), real_vol=rv)
    if ev is None:
        return "cannot compute expected value (missing Greeks)"
    sp.meta["expectancy"] = {
        "ev_per_unit": ev.ev_per_unit, "ev_ratio": round(ev.ev_ratio, 4),
        "p_win": round(ev.p_max_profit, 3), "p_max_loss": round(ev.p_max_loss, 3),
        "implied_vol": round(reg.iv, 4) if reg else None,
        "realized_vol": round(rv, 4) if rv else None,
        "vrp": round((reg.iv - rv), 4) if (reg and rv) else None,
    }
    if ev.ev_ratio < config.MIN_EV_RATIO:
        return (f"expected value {ev.ev_ratio:+.2%} of risk < required "
                f"{config.MIN_EV_RATIO:.0%} (P(win) {ev.p_max_profit:.0%}, "
                f"VRP {(reg.iv - rv):+.1%})" if (reg and rv) else
                f"expected value {ev.ev_ratio:+.2%} < {config.MIN_EV_RATIO:.0%}")
    return None


def candidates(reg: Regime, views: List[O.ContractView], expiry: date,
               view: View, budget: float) -> List[S.Spread]:
    """Enumerate every structure the regime permits, across deltas and widths.

    Rather than build one structure and hope it clears the bar, we generate the
    whole feasible set and let expected value choose. This is what turns the
    agent from a rule-follower into an optimiser.
    """
    out: List[S.Spread] = []
    inc_c = _increment(views, "C", expiry)
    inc_p = _increment(views, "P", expiry)
    widths = [n for n in config.WIDTH_STRIKES]

    def keep(sp):
        if sp and sp.width > 0 and sp.max_loss_per_unit <= (budget or float("inf")):
            out.append(sp)

    # Condors need a quiet market. See config.MAX_VOL_FOR_CONDOR — they lose
    # badly above it, so above the ceiling we simply do not offer them.
    rv = (reg.detail or {}).get("realized_vol") or 0.0
    condors_allowed = rv <= config.MAX_VOL_FOR_CONDOR
    neutral_ok = reg.name in (HIGH_IV_RANGE, LOW_IV_RANGE) and condors_allowed
    trend_ok = reg.name in (HIGH_IV_TREND, LOW_IV_TREND)
    bias = reg.trend_dir or view.bias

    # --- iron condors, several distances and widths ---------------------
    if neutral_ok:
        for sig in config.CONDOR_SIGMAS:
            sput = O.by_strike(views, reg.spot - sig * reg.expected_move, "P", expiry)
            scall = O.by_strike(views, reg.spot + sig * reg.expected_move, "C", expiry)
            if not sput or not scall:
                continue
            for n in widths:
                lp = O.wing(views, sput, inc_p * n)
                lc = O.wing(views, scall, inc_c * n)
                if not lp or not lc:
                    continue
                if lp.strike >= sput.strike or lc.strike <= scall.strike:
                    continue
                sp = S.iron_condor(lp, sput, scall, lc)
                sp.meta.update(sigma_mult=sig, wing_strikes=n)
                keep(sp)

    # --- credit verticals on both sides ----------------------------------
    for kind in ("P", "C"):
        if trend_ok and bias:
            # only sell the side the trend moves away from
            if (bias > 0 and kind == "C") or (bias < 0 and kind == "P"):
                continue
        for d in config.CREDIT_DELTAS:
            short = O.by_delta(views, d, kind, expiry)
            if not short:
                continue
            for n in widths:
                long_ = O.wing(views, short, (inc_p if kind == "P" else inc_c) * n)
                if not long_:
                    continue
                if kind == "P" and long_.strike >= short.strike:
                    continue
                if kind == "C" and long_.strike <= short.strike:
                    continue
                sp = (S.bull_put_spread(short, long_) if kind == "P"
                      else S.bear_call_spread(short, long_))
                sp.meta.update(short_delta=round(short.delta, 3), wing_strikes=n)
                keep(sp)

    # --- debit verticals when the view is directional --------------------
    if bias and reg.name in (LOW_IV_TREND, HIGH_IV_TREND):
        kind = "C" if bias > 0 else "P"
        for dl in config.DEBIT_LONG_DELTAS:
            long_ = O.by_delta(views, dl, kind, expiry)
            if not long_:
                continue
            for n in widths:
                inc = inc_c if kind == "C" else inc_p
                target = long_.strike + inc * n if kind == "C" else long_.strike - inc * n
                short = O.by_strike(views, target, kind, expiry)
                if not short or short.symbol == long_.symbol:
                    continue
                if kind == "C" and short.strike <= long_.strike:
                    continue
                if kind == "P" and short.strike >= long_.strike:
                    continue
                sp = (S.bull_call_spread(long_, short) if kind == "C"
                      else S.bear_put_spread(long_, short))
                sp.meta.update(long_delta=round(long_.delta, 3), wing_strikes=n)
                keep(sp)

    return out


def propose(reg: Regime, views: List[O.ContractView], expiry: date,
            view: View = NEUTRAL, budget: float = None) -> tuple:
    """Regime + view -> (best spread | None, explanation).

    The regime decides which structure FAMILIES are eligible; expected value
    decides which specific structure to trade.
    """
    if reg.name == EVENT_RISK:
        return None, f"{reg.name}: {reg.reason}"
    if not views:
        return None, "no usable contracts"

    pool = candidates(reg, views, expiry, view, budget or float("inf"))
    if not pool:
        rv = (reg.detail or {}).get("realized_vol") or 0.0
        if rv > config.MAX_VOL_FOR_CONDOR and reg.name in (HIGH_IV_RANGE, LOW_IV_RANGE):
            return None, (f"{reg.name}: realised vol {rv:.1%} > "
                          f"{config.MAX_VOL_FOR_CONDOR:.0%} ceiling — condors are "
                          f"unreliable in high vol and no directional structure qualifies")
        return None, f"{reg.name}: no feasible structure fits the risk budget"

    rv = (reg.detail or {}).get("realized_vol")
    scored = []
    for sp in pool:
        ev = EX.evaluate(sp, view=view, spot=reg.spot, real_vol=rv)
        if ev is None:
            continue
        scored.append((ev.ev_ratio, ev, sp))
    if not scored:
        return None, "could not compute expected value for any candidate"

    scored.sort(key=lambda t: t[0], reverse=True)
    best_ratio, best_ev, best = scored[0]
    best.meta["candidates_considered"] = len(scored)

    bad = quality_gate(best, reg, view)
    if bad:
        return None, (f"best of {len(scored)} candidates rejected: {bad}")

    best.meta.update(view_direction=view.direction, view_confidence=view.confidence,
                     view_source=view.source,
                     why=f"best EV of {len(scored)} candidates: {best_ev.summary()}")
    return best, best.meta["why"]


def _legacy_single_build(reg, views, expiry, view, budget):
    if reg.name == HIGH_IV_RANGE:
        sp = build_iron_condor(reg, views, expiry, budget=budget)
        why = "high IV + no trend -> delta-neutral iron condor"
    elif reg.name == LOW_IV_RANGE:
        # No volatility edge from the regime label — but the ECONOMICS may still
        # be acceptable. Try a deliberately wider condor (further OTM, higher win
        # probability) and let the credit-ratio and sigma gates decide. If the
        # premium does not compensate for the risk, quality_gate() rejects it.
        sp = build_iron_condor(reg, views, expiry,
                               sigma_mult=config.CONSERVATIVE_SIGMA, budget=budget)
        why = (f"no regime edge -> conservative {config.CONSERVATIVE_SIGMA}σ condor, "
               f"economics must justify it")
    elif reg.name == HIGH_IV_TREND:
        bias = reg.trend_dir or view.bias or 1
        sp = build_credit_vertical(reg, views, expiry, bias, budget=budget)
        why = f"high IV + trend -> credit vertical, bias {'up' if bias > 0 else 'down'}"
    elif reg.name == LOW_IV_TREND:
        bias = reg.trend_dir or view.bias
        if bias == 0:
            return None, "low IV but no directional bias"
        sp = build_debit_vertical(reg, views, expiry, bias)
        why = f"low IV + trend -> debit vertical, bias {'up' if bias > 0 else 'down'}"
    else:
        return None, f"unhandled regime {reg.name}"

    if sp is None:
        return None, f"{why} — could not assemble legs from the chain"

    bad = quality_gate(sp, reg, view)
    if bad:
        return None, f"{why} — rejected: {bad}"

    sp.meta.update(view_direction=view.direction, view_confidence=view.confidence,
                   view_source=view.source, why=why)
    return sp, why
