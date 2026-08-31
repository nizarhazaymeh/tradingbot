"""IV rank must say "unknown" rather than invent a number (T3).

regime.classify() only uses the implied-vs-realised-vol fallback when iv_rank()
returns None. The old implementation returned 0.5 whenever min == max, so the
first recorded reading silently switched the classifier off a working proxy and
onto a fabricated rank:

  * 1 reading  -> 0.5, which is neither > IV_RANK_RICH nor < IV_RANK_CHEAP, so
    every underlying classified as LOW_IV_RANGE "no clear edge" forever.
  * 2 readings -> exactly 0.0 or 1.0, a maximally confident signal from two
    data points.

Observed live on 31 Aug 2026: SPY at implied/realised 1.29x and IWM at 1.35x
both fell to "no clear edge" once one IV reading existed. With the fix they
classify HIGH_IV_RANGE and HIGH_IV_TREND again.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent import config
from agent.options import iv_rank

N = config.MIN_IV_HISTORY


def varied(n, lo=0.10, step=0.004):
    return [lo + i * step for i in range(n)]


def test_no_history_is_unknown():
    assert iv_rank(0.13, []) is None


def test_one_reading_is_unknown():
    """The regression: this used to return 0.5."""
    assert iv_rank(0.13, [0.13]) is None


def test_two_readings_are_unknown():
    """This used to return a confident 0.0 or 1.0 from two points."""
    assert iv_rank(0.13, [0.13, 0.19]) is None
    assert iv_rank(0.19, [0.13, 0.19]) is None


def test_below_the_minimum_is_unknown():
    assert iv_rank(0.13, varied(N - 1)) is None


def test_at_the_minimum_is_known():
    r = iv_rank(0.13, varied(N))
    assert r is not None
    assert 0.0 <= r <= 1.0


def test_degenerate_range_is_unknown_even_with_enough_readings():
    """A flat series has no range to rank against, however long it is."""
    assert iv_rank(0.13, [0.13] * (N + 10)) is None


def test_ranks_at_the_extremes_and_middle():
    h = varied(N)                      # lo .. lo + (N-1)*step
    lo, hi = min(h), max(h)
    assert iv_rank(lo, h) == 0.0
    assert iv_rank(hi, h) == 1.0
    mid = (lo + hi) / 2
    assert abs(iv_rank(mid, h) - 0.5) < 1e-9


def test_clamped_outside_the_historical_range():
    h = varied(N)
    assert iv_rank(min(h) - 0.05, h) == 0.0
    assert iv_rank(max(h) + 0.05, h) == 1.0


def test_a_known_rank_still_drives_rich_and_cheap():
    """Guard the thresholds the classifier compares against."""
    h = varied(N)
    lo, hi = min(h), max(h)
    assert iv_rank(hi, h) > config.IV_RANK_RICH
    assert iv_rank(lo, h) < config.IV_RANK_CHEAP


def test_unknown_rank_lets_the_classifier_reach_the_fallback():
    """The behaviour that actually broke: with an unknown rank, classify() must
    use implied-vs-realised and be able to report a rich regime."""
    from datetime import date, timedelta
    from agent.options import ContractView, occ
    from agent.regime import classify, HIGH_IV_RANGE

    E = date.today() + timedelta(days=4)

    def cv(kind, strike, iv):
        return ContractView(symbol=occ("SPY", E, kind, strike), root="SPY", expiry=E,
                            kind=kind, strike=float(strike), dte=4, bid=1.0, ask=1.1,
                            mid=1.05, spread_pct=0.05,
                            delta=0.5 if kind == "C" else -0.5,
                            gamma=0.01, theta=-0.2, vega=0.1, iv=iv, open_interest=9000)

    views = [cv("C", 769, 0.30), cv("P", 769, 0.30)]
    closes = [700 + (i % 3) for i in range(60)]        # low realised vol, no trend
    reg = classify("SPY", 769.0, views, closes, expiry=E, iv_history=[0.30])
    assert reg.iv_rank is None, "one reading must not produce a rank"
    assert "vs realised" in reg.reason, f"fallback not used: {reg.reason}"
    assert reg.name == HIGH_IV_RANGE, f"rich premium not detected: {reg.name}"
