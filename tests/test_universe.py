"""The universe must be diversified and free of negative-VRP names.

A premium-selling book's real danger is a correlated shock, not any single
defined-risk position — so the same heat budget spread across more underlyings is
safer, not riskier. And a name whose implied vol sits BELOW its realised vol has
no premium to sell: IBIT was in the universe at -3.6% VRP on 1 Sep.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agent import config


def test_universe_is_diversified():
    assert len(config.UNIVERSE) >= 8, (
        "too few underlyings concentrates the heat budget into a handful of names")


def test_measured_negative_vrp_names_are_excluded():
    """These were measured with implied BELOW realised on 1 Sep."""
    for sym in ("IBIT", "NVDA", "GLD"):
        assert sym not in config.UNIVERSE, f"{sym} had negative VRP when measured"


def test_no_duplicates():
    assert len(config.UNIVERSE) == len(set(config.UNIVERSE))


def test_position_count_does_not_bind_before_heat():
    """With N underlyings at 2 each, the count cap must not be the constraint —
    heat should be, so risk is spread rather than forced into few names."""
    possible = len(config.UNIVERSE) * config.MAX_POSITIONS_PER_UNDERLYING
    assert config.MAX_OPEN_POSITIONS < possible, (
        "count cap is above what the universe can supply, so it is inert")
    heat_supports = int(config.PORTFOLIO_HEAT_PCT * 100_000 /
                        (config.RISK_PER_TRADE_PCT * 100_000))
    assert config.MAX_OPEN_POSITIONS >= heat_supports, (
        f"count cap {config.MAX_OPEN_POSITIONS} bites before the heat budget "
        f"({heat_supports} full-size positions), wasting risk appetite")
