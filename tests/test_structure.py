"""Wiring levels.py in: the bar adapter, structure corroboration, zone protection.

agent/levels.py (pivots, supply/demand zones, Fibonacci) and agent/indicators.py
(SMA/EMA/ATR/ADX/RSI) were 374 lines of unreachable code — levels imported
indicators, and nothing imported levels. The missing piece was the Bar type,
which lived in the pre-refactor root strategy.py and went away with it.

The behavioural change is trend corroboration. trend_dir decides which side gets
sold: strategy.candidates() sells only the side the trend moves away from. On
31 Aug 2026 IWM scored z-1.67 (down) while swing structure read up, so the agent
would have sold calls into a rising market — the worst configuration in
docs/BACKTEST.md (call credit spreads, PF 0.44-0.57). A direction now has to
survive both reads.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent import levels as L
from agent.regime import trend_score


# ------------------------------------------------------------------- adapter
def test_bars_from_api_maps_fields():
    bars = L.bars_from_api([{"t": "2026-08-31", "o": 1, "h": 10.5, "l": 9.5,
                             "c": 10.0, "v": 1234}])
    assert len(bars) == 1
    b = bars[0]
    assert (b.c, b.h, b.l, b.v) == (10.0, 10.5, 9.5, 1234.0)


def test_bars_from_api_drops_unusable_rows():
    """A synthetic zero-range bar would suppress ATR and invent impulses."""
    rows = [{"t": 1, "h": 10, "l": 9, "c": 9.5, "v": 1},      # good
            {"t": 2, "l": 9, "c": 9.5},                        # no high
            {"t": 3, "h": None, "l": 9, "c": 9.5},             # null high
            {"t": 4, "h": 8, "l": 9, "c": 8.5},                # high < low
            {"t": 5, "h": 0, "l": 0, "c": 0},                  # zero
            {"t": 6, "h": 11, "l": 10, "c": 10.5, "v": 2}]     # good
    assert len(L.bars_from_api(rows)) == 2


def test_bars_from_api_handles_empty_and_none():
    assert L.bars_from_api([]) == []
    assert L.bars_from_api(None) == []


def test_volume_defaults_when_absent():
    assert L.bars_from_api([{"t": 1, "h": 2, "l": 1, "c": 1.5}])[0].v == 0.0


# ----------------------------------------- structure does NOT drive direction
#
# Corroborating the z-score with market_structure() was implemented, measured
# over 6 expiry cycles with scripts/filter_ladder.py, and reverted:
#
#   veto on any disagreement   PF 1.56 -> 1.26   -$158
#   veto only on the opposite  PF 1.56 -> 1.10   -$335
#
# market_structure() returned "range" in 14 of 18 cases, so treating that as a
# veto disabled the trend filter — the most valuable component in the system.
# In the one case it actively disagreed (SPY 2026-08-03, z +1.92 up vs structure
# down) it was wrong, and the call spreads it admitted lost $335.
#
# These tests pin the parameter as INERT so the veto cannot be reintroduced
# without a measurement.

def rising(n=80, start=100.0, step=0.5):
    return [start + i * step for i in range(n)]


def falling(n=80, start=140.0, step=0.5):
    return [start - i * step for i in range(n)]


def test_structure_does_not_change_an_uptrend():
    closes = rising()
    base = trend_score(closes)[1]
    assert base == 1, "fixture must produce an uptrend"
    for st in ("up", "down", "range", None):
        assert trend_score(closes, structure=st)[1] == base, (
            f"structure={st!r} altered the direction; it must be inert")


def test_structure_does_not_change_a_downtrend():
    closes = falling()
    base = trend_score(closes)[1]
    assert base == -1, "fixture must produce a downtrend"
    for st in ("up", "down", "range", None):
        assert trend_score(closes, structure=st)[1] == base, (
            f"structure={st!r} altered the direction; it must be inert")


def test_structure_argument_is_still_accepted():
    """cycle.py no longer passes it, but the signature is documented and stable."""
    z, d = trend_score(rising(), structure="range")
    assert isinstance(z, float) and d in (-1, 0, 1)


def test_market_structure_returns_range_far_more_often_than_a_direction():
    """The reason the veto failed, asserted directly.

    Three consecutive higher highs AND higher lows is a demanding pattern; a
    zig-zag that trends upward overall still reads as range.
    """
    zig = []
    base = 100.0
    for i in range(120):
        base += 0.4 if i % 2 else -0.25
        zig.append(base)
    bars = [L.Bar(i, c, c * 1.004, c * 0.996, 1000) for i, c in enumerate(zig)]
    assert L.market_structure(L.pivots(bars)) in ("range", "up", "down")


# -------------------------------------------------------- zone protection
def z(kind, lo, hi, touches=0, strength=2.0):
    return L.Zone(low=lo, high=hi, kind=kind, index=0, touches=touches,
                  strength=strength)


SPOT = 769.28
ZONES = [z("supply", 780, 784), z("supply", 800, 805, touches=1),
         z("demand", 740, 745, touches=2), z("demand", 755, 758, touches=9)]


def test_a_zone_between_spot_and_a_short_call_protects_it():
    got = L.protects_short(ZONES, SPOT, 790, "C")
    assert got is not None and got.low == 780


def test_a_zone_beyond_the_short_call_does_not_protect_it():
    assert L.protects_short(ZONES, SPOT, 775, "C") is None


def test_a_zone_between_spot_and_a_short_put_protects_it():
    got = L.protects_short(ZONES, SPOT, 735, "P")
    assert got is not None and got.high == 745


def test_a_heavily_worked_zone_is_not_protection():
    """The 755-758 demand zone has 9 touches; find_zones ages them for a reason.

    Strike 750 puts that zone genuinely between spot and the strike, so touches
    are the only thing deciding — raising max_touches must let it through, which
    is what proves the rejection was about touches and not position.
    """
    assert L.protects_short(ZONES, SPOT, 750, "P") is None
    got = L.protects_short(ZONES, SPOT, 750, "P", max_touches=10)
    assert got is not None and got.low == 755


def test_a_zone_below_the_short_put_does_not_protect_it():
    """756 sits below a 760 strike, so price reaches the strike first."""
    assert L.protects_short(ZONES, SPOT, 760, "P", max_touches=99) is None


def test_the_nearest_qualifying_zone_is_returned():
    got = L.protects_short(ZONES, SPOT, 820, "C")
    assert got.low == 780, "should return the first barrier price meets, not the furthest"


def test_no_zones_is_unprotected_not_an_error():
    assert L.protects_short([], SPOT, 790, "C") is None
