"""EVENT_RISK had never fired: classify() takes has_catalyst and nothing passed it.

With single names in the universe that is a real hole — the agent would sell a
4-DTE condor on AAPL the day before earnings, pricing a binary jump as if it
were diffusive variance risk premium.

Alpaca has no earnings calendar. The options market prices events itself, as a
kink in the IV term structure: the expiry that CONTAINS the event carries the
jump, the one after it does not. regime.event_priced() reads that kink.
"""
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent import config
from agent.options import ContractView, occ
from agent.regime import EVENT_RISK, HIGH_IV_RANGE, classify, event_priced


def test_a_flat_term_structure_is_not_an_event():
    """4 Sep 2026, all ten names: near/far read 0.89 - 1.09. None is an event."""
    for near, far in ((0.085, 0.091), (0.264, 0.281), (0.260, 0.241), (0.291, 0.268)):
        has, r = event_priced(near, far)
        assert not has, f"{near}/{far} = {r} must not read as an event"


def test_an_earnings_kink_is_an_event():
    """A single name in earnings week: the near weekly carries the jump."""
    has, r = event_priced(0.65, 0.32)
    assert has and r > 2.0


def test_the_threshold_is_the_config_value():
    just_under = config.EVENT_IV_RATIO - 0.01
    just_over = config.EVENT_IV_RATIO + 0.01
    assert not event_priced(just_under, 1.0)[0]
    assert event_priced(just_over, 1.0)[0]
    assert event_priced(2.0, 1.0, ratio=2.5)[0] is False, "explicit threshold honoured"


def test_missing_data_is_no_opinion_not_no_event():
    """A data hiccup must never be mistaken for a safe window."""
    for near, far in ((None, 0.3), (0.3, None), (0.0, 0.3), (0.3, 0.0), (None, None)):
        has, r = event_priced(near, far)
        assert has is False and r is None


# ------------------------------------------------ it reaches the classifier
E = date.today() + timedelta(days=4)


def cv(kind, strike, iv):
    return ContractView(symbol=occ("X", E, kind, strike), root="X", expiry=E, kind=kind,
                        strike=float(strike), dte=4, bid=1.0, ask=1.1, mid=1.05,
                        spread_pct=0.05, delta=0.5 if kind == "C" else -0.5,
                        gamma=0.01, theta=-0.2, vega=0.1, iv=iv, open_interest=9000)


def test_an_event_overrides_a_rich_regime():
    """Rich premium AND an event in window -> stand aside, not sell. The premium
    is rich BECAUSE of the event, which is the whole point."""
    views = [cv("C", 100, 0.60), cv("P", 100, 0.60)]
    calm = [100.0 + 0.3 * ((i % 3) - 1) for i in range(60)]
    without = classify("X", 100.0, views, calm, expiry=E)
    assert without.name == HIGH_IV_RANGE, "fixture must be rich without the event"
    with_ev = classify("X", 100.0, views, calm, expiry=E, has_catalyst=True,
                       catalyst_note="IV term structure 2.10x")
    assert with_ev.name == EVENT_RISK
    assert not with_ev.tradable
    assert "2.10x" in with_ev.reason
