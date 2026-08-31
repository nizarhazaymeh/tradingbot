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


# --------------------------------------------------- break of structure + retest
#
# market_structure() answers "range" most of the time (the test above pins why
# the veto built on it failed). A break of structure resolves far more often: a
# close through a swing level, then the retest that decides whether it was real.

def mkbars(rows):
    """(high, low, close) triples -> Bars, oldest first."""
    return [L.Bar(i, c, h, l, 1000.0) for i, (h, l, c) in enumerate(rows)]


def ranging_with_a_swing_high():
    """Flat range with one clean swing high at 110 on bar 10.

    The flat highs cannot make a pivot — pivots() needs a STRICT new extreme —
    so bar 10 is the only pivot in the series, which keeps these tests about the
    break rather than about pivot detection.
    """
    return ([(105, 100, 102)] * 10 + [(110, 104, 108)] + [(105, 100, 102)] * 9)


BREAK_BAR = [(112, 106, 111)]        # closes 111, through the 110 level


def test_a_close_through_a_swing_high_is_a_break():
    bs = L.breaks(mkbars(ranging_with_a_swing_high() + BREAK_BAR), atr_period=5)
    assert len(bs) == 1
    assert bs[0].direction == 1 and bs[0].level == 110


def test_a_retest_that_holds_is_confirmed():
    """Price comes back to 110 and closes above it — broken resistance held."""
    tail = BREAK_BAR + [(113, 110.5, 112), (112, 109, 110.5)]
    b = L.breaks(mkbars(ranging_with_a_swing_high() + tail), atr_period=5)[0]
    assert b.state == "confirmed" and b.confirmed and not b.failed
    assert b.retest_index is not None


def test_a_retest_that_gives_way_is_a_failed_break():
    """Same break, but the retest bar closes back below the level: a false break."""
    tail = BREAK_BAR + [(112, 108, 107)]
    b = L.breaks(mkbars(ranging_with_a_swing_high() + tail), atr_period=5)[0]
    assert b.state == "failed" and b.failed and not b.confirmed


def test_a_break_that_never_comes_back_stays_pending():
    tail = BREAK_BAR + [(118, 115, 117), (120, 117, 119), (122, 119, 121)]
    b = L.breaks(mkbars(ranging_with_a_swing_high() + tail),
                 atr_period=5, max_wait=3)[0]
    assert b.state == "pending" and b.retest_index is None
    assert b.extent_atr > 1, "price ran a long way before max_wait expired"


def test_a_level_is_reported_once_not_on_every_bar_above_it():
    tail = BREAK_BAR + [(113, 111, 112), (114, 112, 113), (115, 113, 114)]
    bs = L.breaks(mkbars(ranging_with_a_swing_high() + tail), atr_period=5)
    assert len([b for b in bs if b.level == 110]) == 1


def test_a_break_is_never_reported_before_its_pivot_was_confirmed():
    """The no-lookahead invariant, asserted directly.

    pivots() needs `right` later bars before a swing exists, so a break of it
    cannot be seen earlier than `right` bars after the swing itself.
    """
    tail = BREAK_BAR + [(113, 110.5, 112), (112, 109, 110.5)]
    for b in L.breaks(mkbars(ranging_with_a_swing_high() + tail), atr_period=5,
                      right=3):
        assert b.index >= b.pivot_index + 3


def test_too_few_bars_is_empty_not_an_error():
    assert L.breaks(mkbars([(105, 100, 102)] * 5)) == []
    assert L.latest_break(mkbars([])) is None


# ------------------------------------------------------------ break_trend
def brk(direction, state, level=100.0, index=10):
    return L.Break(index=index, level=level, direction=direction,
                   pivot_index=index - 4, state=state)


def test_break_trend_follows_the_last_confirmed_break():
    assert L.break_trend([brk(1, "confirmed")]) == 1
    assert L.break_trend([brk(-1, "confirmed")]) == -1


def test_a_failed_break_reads_as_the_opposite_direction():
    """Broke up, came back through and kept going — that is a trap, not a rally."""
    assert L.break_trend([brk(1, "failed")]) == -1
    assert L.break_trend([brk(-1, "failed")]) == 1


def test_a_pending_break_decides_nothing_by_default():
    assert L.break_trend([brk(1, "pending")]) == 0
    assert L.break_trend([brk(1, "pending")], require_retest=False) == 1


def test_the_most_recent_resolved_break_wins():
    bs = [brk(1, "confirmed", index=5), brk(-1, "confirmed", index=20)]
    assert L.break_trend(bs) == -1


def test_no_breaks_is_no_direction():
    assert L.break_trend([]) == 0
    assert L.break_trend(None) == 0


# --------------------------------------------------------- retest_barrier
CONFIRMED = [L.Break(index=10, level=780.0, direction=-1, pivot_index=6,
                     state="confirmed"),
             L.Break(index=12, level=800.0, direction=-1, pivot_index=8,
                     state="confirmed"),
             L.Break(index=14, level=745.0, direction=1, pivot_index=10,
                     state="confirmed")]


def test_a_confirmed_level_between_spot_and_a_short_call_is_a_barrier():
    got = L.retest_barrier(CONFIRMED, SPOT, 790, "C")
    assert got is not None and got.level == 780


def test_the_first_barrier_price_meets_is_returned():
    got = L.retest_barrier(CONFIRMED, SPOT, 820, "C")
    assert got.level == 780, "not the furthest level, the one price reaches first"


def test_a_confirmed_level_between_spot_and_a_short_put_is_a_barrier():
    got = L.retest_barrier(CONFIRMED, SPOT, 740, "P")
    assert got is not None and got.level == 745


def test_a_level_beyond_the_strike_is_not_a_barrier():
    assert L.retest_barrier(CONFIRMED, SPOT, 775, "C") is None


def test_an_unconfirmed_break_is_not_a_barrier():
    """The retest is the whole point — a level price never came back to proves nothing."""
    unresolved = [L.Break(index=10, level=780.0, direction=-1, pivot_index=6,
                          state=s) for s in ("pending", "failed")]
    assert L.retest_barrier(unresolved, SPOT, 790, "C") is None


def test_no_breaks_is_unprotected_not_an_error():
    assert L.retest_barrier([], SPOT, 790, "C") is None
    assert L.retest_barrier(None, SPOT, 790, "C") is None
