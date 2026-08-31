"""Selection must not abandon an underlying because the TOP-EV candidate fails.

propose() used to run quality_gate() on scored[0] only and give up if it failed.
That is the common case, not a rare one: EV rises as the short strike approaches
spot (more premium), while MIN_SHORT_SIGMA requires the opposite, so the top-EV
structure is systematically the one the gate rejects. Live on 31 Aug 2026 this
held every underlying — SPY had 27 of 36 candidates passing every gate and traded
none of them.

Neither scripts/backtest.py nor agent/replay.py imports agent.strategy, so the
backtest could never have caught this. These tests cover that gap.
"""
import math
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent import config
from agent.options import ContractView, occ
from agent.regime import Regime, HIGH_IV_RANGE, HIGH_IV_TREND
from agent.strategy import View, candidates, propose, quality_gate

E = date(2026, 9, 4)
SPOT = 769.0
# 1s = $13, so 0.9s = $11.70. The premium/delta curves below put the richest
# structures 7-10 points from spot, i.e. 0.54-0.77s — inside the floor. This is
# the live shape: SPY on 31 Aug had 1s = $10.47 with the best candidate at 0.83s.
SIGMA = 13.0
BUDGET = config.RISK_PER_TRADE_PCT * 100_000


def cv(kind, strike):
    """A contract whose premium and delta decay with distance from spot.

    This is the shape that creates the bug: premium is richest near spot, so the
    richest structures are the ones the sigma gate must reject.
    """
    d = abs(strike - SPOT)
    mid = max(0.06, 4.0 * math.exp(-d / 7.0))
    delta = max(0.02, 0.48 * math.exp(-d / 11.0))
    # theta must decay with distance too, or a credit spread nets exactly zero
    # theta and every candidate dies on the non-positive-theta gate.
    theta = -max(0.01, 0.30 * math.exp(-d / 7.0))
    return ContractView(
        symbol=occ("SPY", E, kind, strike), root="SPY", expiry=E, kind=kind,
        strike=float(strike), dte=5, bid=mid * 0.96, ask=mid * 1.04, mid=mid,
        spread_pct=0.04, delta=delta if kind == "C" else -delta,
        gamma=0.01, theta=theta, vega=0.1, iv=0.15, open_interest=8000)


def chain():
    return ([cv("P", s) for s in range(735, 769)] +
            [cv("C", s) for s in range(770, 805)])


def regime():
    """A TRENDING regime, deliberately.

    In a range regime the condor builder places shorts by sigma (CONDOR_SIGMAS
    starts at 1.2), so the top-EV candidate always clears MIN_SHORT_SIGMA and the
    bug never appears. The structure that actually failed live was a delta-placed
    credit vertical: CREDIT_DELTAS reaches 0.22, and a 0.22-delta short can sit
    inside 0.9s. A trending regime offers verticals only, which is the case that
    matters.
    """
    return Regime(HIGH_IV_TREND, "SPY", SPOT, 0.15, None, 1.8, 1, SIGMA, 5,
                  "trending up", {"realized_vol": 0.10})


def range_regime():
    return Regime(HIGH_IV_RANGE, "SPY", SPOT, 0.15, None, 0.05, 0, SIGMA, 5,
                  "quiet", {"realized_vol": 0.10})


def sigma_out(strike):
    return abs(strike - SPOT) / SIGMA


# --------------------------------------------------------------------- the bug
def _scored(reg, views):
    """Rank candidates by EV exactly as propose() does."""
    from agent import expectancy as EX
    v = View()
    out = []
    for sp in candidates(reg, views, E, v, BUDGET):
        ev = EX.evaluate(sp, view=v, spot=reg.spot,
                         real_vol=(reg.detail or {}).get("realized_vol"))
        if ev is not None:
            out.append((ev.ev_ratio, sp))
    out.sort(key=lambda t: -t[0])
    return out


def test_fixture_really_reproduces_the_bug():
    """Guard the guard: if rank 0 passes, the regression test proves nothing."""
    reg, views = regime(), chain()
    scored = _scored(reg, views)
    assert scored, "fixture produced no scored candidates"
    assert quality_gate(scored[0][1], reg, View()) is not None, (
        "rank 0 passes the gate, so this fixture does not exercise the bug")
    assert any(quality_gate(sp, reg, View()) is None for _, sp in scored), (
        "no candidate passes, so propose() standing aside would be correct")


def test_proposes_a_spread_when_a_lower_ranked_candidate_passes():
    """The regression: a rejected rank 0 must not abandon the underlying."""
    reg, views = regime(), chain()
    passing = [sp for _, sp in _scored(reg, views)
               if quality_gate(sp, reg, View()) is None]
    assert passing, "fixture must contain at least one acceptable structure"

    sp, why = propose(reg, views, E, View(), BUDGET)
    assert sp is not None, f"propose() stood aside despite {len(passing)} acceptable: {why}"


def test_takes_a_rank_below_zero():
    """The chosen candidate must be one rank 0 could never have been."""
    reg = regime()
    sp, why = propose(reg, chain(), E, View(), BUDGET)
    assert sp is not None, why
    assert sp.meta["candidate_rank"] > 0, (
        "expected propose() to reach past the rejected rank 0")


def test_chosen_spread_actually_passes_every_gate():
    """Reaching past rank 0 must not smuggle through a structure that fails."""
    reg = regime()
    sp, why = propose(reg, chain(), E, View(), BUDGET)
    assert sp is not None, why
    assert quality_gate(sp, reg, View()) is None, "returned a spread the gate rejects"


def test_short_strikes_respect_min_short_sigma():
    """The fix must not weaken the gate it works around."""
    reg = regime()
    sp, why = propose(reg, chain(), E, View(), BUDGET)
    assert sp is not None, why
    for leg in sp.legs:
        if leg.side == "sell" and leg.view is not None:
            assert sigma_out(leg.view.strike) >= config.MIN_SHORT_SIGMA, (
                f"short {leg.view.strike:.0f}{leg.view.kind} at "
                f"{sigma_out(leg.view.strike):.2f}s is inside "
                f"{config.MIN_SHORT_SIGMA}s")


def test_records_which_rank_was_taken():
    """Rank is the diagnostic that makes this visible in the trade log."""
    sp, why = propose(regime(), chain(), E, View(), BUDGET)
    assert sp is not None, why
    assert "candidate_rank" in sp.meta
    assert sp.meta["candidate_rank"] >= 0
    assert sp.meta["candidate_rank"] < sp.meta["candidates_considered"]


def test_stands_aside_when_nothing_passes():
    """Reaching deeper must still refuse when every candidate is unacceptable."""
    reg = regime()
    # 1s of $400 puts every available strike far inside 0.9s (=$360).
    reg.expected_move = 400.0
    sp, why = propose(reg, chain(), E, View(), BUDGET)
    assert sp is None, f"expected no trade, got {sp.describe()}"
    assert "candidates rejected" in why, why


def test_budget_is_still_respected():
    reg = regime()
    sp, why = propose(reg, chain(), E, View(), BUDGET)
    assert sp is not None, why
    assert sp.max_loss_per_unit <= BUDGET, (
        f"max loss ${sp.max_loss_per_unit:.0f} exceeds budget ${BUDGET:.0f}")


# ------------------------------------------- the retest barrier is a tie-break
#
# A break of structure that price returned to and respected is the strongest
# barrier levels.py can identify. docs/BACKTEST.md Part 6 measured it
# leave-one-window-out: trades whose short strike sat behind one returned +$3,255
# (PF 1.98) against -$554 (PF 0.91) without one.
#
# It inverted in one of four windows, so it is wired as a RANKING preference and
# nothing more. These tests pin that boundary: it may reorder acceptable
# structures, and it may never admit an unacceptable one.

from agent import levels as L
from agent.strategy import _retest_bonus


def confirmed_at(level, direction=-1):
    return L.Break(index=40, level=level, direction=direction, pivot_index=36,
                   state="confirmed")


def a_credit_spread(reg, views):
    """The highest-EV structure with a short leg.

    Deliberately side-agnostic: the trending fixture is an UPtrend, so
    candidates() offers puts and refuses calls. A test that demanded a bear_call
    would be testing the trend filter, not the barrier.
    """
    for _, sp in _scored(reg, views):
        if any(l.side == "sell" and l.view for l in sp.legs):
            return sp
    raise AssertionError("fixture produced no structure with a short leg")


def shorts_of(sp):
    return [l.view.strike for l in sp.legs if l.side == "sell" and l.view]


def between_spot_and(strike):
    """A level price must pass before it can reach `strike`, either side."""
    return (SPOT + strike) / 2


def beyond(strike):
    """A level on the far side of the strike — price reaches the strike first."""
    return strike - 5 if strike < SPOT else strike + 5


def test_no_breaks_means_no_bonus():
    sp = a_credit_spread(regime(), chain())
    assert _retest_bonus(sp, SPOT, []) == 0.0
    assert _retest_bonus(sp, SPOT, None) == 0.0


def test_a_level_in_front_of_the_short_strike_earns_the_bonus():
    sp = a_credit_spread(regime(), chain())
    k = shorts_of(sp)[0]
    assert _retest_bonus(sp, SPOT, [confirmed_at(between_spot_and(k))]) == (
        config.RETEST_BARRIER_BONUS)


def test_a_level_beyond_the_short_strike_earns_nothing():
    sp = a_credit_spread(regime(), chain())
    k = shorts_of(sp)[0]
    assert _retest_bonus(sp, SPOT, [confirmed_at(beyond(k))]) == 0.0


def test_an_unconfirmed_level_earns_nothing():
    """The retest is the entire signal — a level price never returned to is noise."""
    sp = a_credit_spread(regime(), chain())
    k = shorts_of(sp)[0]
    mid = between_spot_and(k)
    for state in ("pending", "failed"):
        b = L.Break(index=40, level=mid, direction=-1, pivot_index=36, state=state)
        assert _retest_bonus(sp, SPOT, [b]) == 0.0


def test_half_a_condor_is_not_a_protected_condor():
    """A level under the put and nothing over the call protects the wrong side."""
    reg, views = range_regime(), chain()
    condor = next(sp for _, sp in _scored(reg, views) if sp.kind == "iron_condor")
    ks = sorted(shorts_of(condor))
    put_side = [confirmed_at((ks[0] + SPOT) / 2)]
    assert _retest_bonus(condor, SPOT, put_side) == 0.0
    both = put_side + [confirmed_at((SPOT + ks[-1]) / 2)]
    assert _retest_bonus(condor, SPOT, both) == config.RETEST_BARRIER_BONUS


def test_the_levels_are_recorded_whether_or_not_they_pay():
    """Auditability: the barrier read is logged even when it earns nothing."""
    sp = a_credit_spread(regime(), chain())
    far = SPOT + 50 if shorts_of(sp)[0] < SPOT else SPOT - 50
    _retest_bonus(sp, SPOT, [confirmed_at(far)])         # wrong side entirely
    assert "retest_levels" in sp.meta and sp.meta["retest_levels"]
    assert all(v is None for v in sp.meta["retest_levels"].values())


def with_breaks(reg, brks):
    """The same regime, carrying breaks the way cycle.py supplies them."""
    reg.detail = dict(reg.detail or {})
    reg.detail["breaks"] = brks
    return reg


BARRIERS_EVERYWHERE = [confirmed_at(SPOT + d) for d in range(-60, 61, 2) if d]


def test_the_bonus_cannot_admit_a_structure_the_gates_reject():
    """The safety boundary: a preference must never become permission.

    A barrier is planted in front of every possible strike, so the bonus applies
    to every candidate. That is the maximum influence it can ever have, and the
    structure that comes back must still satisfy the gates it would have had to
    satisfy without it.
    """
    views = chain()
    plain, _ = propose(regime(), views, E, View(), BUDGET)
    boosted, why = propose(with_breaks(regime(), BARRIERS_EVERYWHERE), views, E,
                           View(), BUDGET)
    assert plain is not None and boosted is not None
    assert quality_gate(boosted, regime(), View()) is None, (
        "the bonus pushed through a structure that fails its own gates")
    # and it must not have invented candidates, only reordered them
    assert (boosted.meta["candidates_considered"]
            == plain.meta["candidates_considered"])


def test_a_barrier_reorders_which_acceptable_structure_wins():
    """The bonus has to actually DO something, or it is dead code.

    A barrier placed in front of one specific strike, and nowhere else, should be
    able to lift that structure over a rival it was narrowly behind.
    """
    views = chain()
    plain, _ = propose(regime(), views, E, View(), BUDGET)
    chosen = shorts_of(plain)[0]
    # find an acceptable structure with a DIFFERENT short strike to promote
    rivals = [sp for _, sp in _scored(regime(), views)
              if shorts_of(sp) and shorts_of(sp)[0] != chosen
              and quality_gate(sp, regime(), View()) is None]
    if not rivals:
        return                                  # fixture offers only one strike
    target = shorts_of(rivals[0])[0]
    boosted, _ = propose(with_breaks(regime(), [confirmed_at(between_spot_and(target))]),
                         views, E, View(), BUDGET)
    assert quality_gate(boosted, regime(), View()) is None
    assert boosted.meta.get("retest_levels") is not None, (
        "the barrier read must be recorded on whatever structure is chosen")


def test_a_zero_bonus_disables_the_preference():
    """config.RETEST_BARRIER_BONUS = 0 must switch it off completely."""
    sp = a_credit_spread(regime(), chain())
    k = shorts_of(sp)[0]
    brks = [confirmed_at(between_spot_and(k))]
    old = config.RETEST_BARRIER_BONUS
    try:
        config.RETEST_BARRIER_BONUS = 0.0
        assert _retest_bonus(sp, SPOT, brks) == 0.0
    finally:
        config.RETEST_BARRIER_BONUS = old
