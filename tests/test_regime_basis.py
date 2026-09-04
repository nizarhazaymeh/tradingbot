"""Rich/cheap is decided by the variance risk premium, not by IV rank.

regime.classify() had the two the other way round, and nobody could tell:
iv_rank() needs MIN_IV_HISTORY readings, the agent had never run long enough to
accumulate them, so the "fallback" (IV vs realised) was the only branch that had
ever executed. Every backtest and every live trade was made on it.

When scripts/backfill_iv.py supplied the history on 4 Sep 2026, the "primary"
path lit up and contradicted the fallback on 8 of 10 underlyings — in the
direction that fights the strategy:

    AAPL  IV 26.6%  RV 18.3%  (1.45x)  rank 0.15
          ratio path: HIGH_IV_TREND  -> sell credit spreads
          rank  path: LOW_IV_TREND   -> buy debit spreads

Rank says where IV sits against its own history. The README's edge is where IV
sits against REALISED. In a calm market with IV at multi-month lows but still
above realised, those disagree, and the gap is what the EV model is built on.
"""
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent import config
from agent.options import ContractView, occ
from agent.regime import classify, HIGH_IV_RANGE, HIGH_IV_TREND, LOW_IV_RANGE, LOW_IV_TREND

E = date.today() + timedelta(days=4)


def cv(kind, strike, iv):
    return ContractView(symbol=occ("X", E, kind, strike), root="X", expiry=E, kind=kind,
                        strike=float(strike), dte=4, bid=1.0, ask=1.1, mid=1.05,
                        spread_pct=0.05, delta=0.5 if kind == "C" else -0.5,
                        gamma=0.01, theta=-0.2, vega=0.1, iv=iv, open_interest=9000)


def views(iv):
    return [cv("C", 100, iv), cv("P", 100, iv)]


def calm_closes(n=60, amp=0.3):
    """Realised vol ~5%: a flat series with a tiny wiggle, no trend."""
    return [100.0 + amp * ((i % 3) - 1) for i in range(n)]


def history_where_rank_is(target, n=None):
    """A 120-reading history built so that iv_rank(iv_now) lands near `target`."""
    n = n or max(config.MIN_IV_HISTORY, 30)
    lo, hi = 0.20, 0.60
    return [lo + (hi - lo) * i / (n - 1) for i in range(n)]


# ------------------------------------------------- the AAPL case, 4 Sep 2026
def test_a_wide_premium_is_rich_even_when_rank_says_cheap():
    """IV far above realised, but near the bottom of its own range.

    The ratio path sells premium here; the rank path would buy it. The strategy
    sells variance risk premium, so the ratio must win.
    """
    hist = history_where_rank_is(0.1)                # 0.20 .. 0.60
    iv = 0.22                                        # rank ~0.05: "cheap"
    reg = classify("X", 100.0, views(iv), calm_closes(), expiry=E, iv_history=hist)
    rv = reg.detail["realized_vol"]
    assert iv > rv * config.IV_OVER_RV_RICH, "fixture must have a wide premium"
    assert reg.iv_rank is not None and reg.iv_rank < config.IV_RANK_CHEAP, (
        "fixture must have rank saying cheap")
    assert reg.name in (HIGH_IV_RANGE, HIGH_IV_TREND), (
        f"a 1.5x+ premium must read rich regardless of rank; got {reg.name}: {reg.reason}")


def test_a_high_rank_does_not_make_a_thin_premium_rich():
    """The mirror: IV at the top of its range but BELOW realised. Nothing to sell."""
    hist = [0.05 + 0.10 * i / 29 for i in range(30)]   # 0.05 .. 0.15
    iv = 0.15                                          # rank 1.0: "rich"
    # realised vol well above 15%
    wild = [100.0 * (1 + 0.03 * (1 if i % 2 else -1)) for i in range(60)]
    reg = classify("X", 100.0, views(iv), wild, expiry=E, iv_history=hist)
    assert reg.iv_rank is not None and reg.iv_rank > config.IV_RANK_RICH
    assert reg.name in (LOW_IV_RANGE, LOW_IV_TREND), (
        f"IV below realised must not be rich just because rank is high; got {reg.name}")


def test_rank_is_still_recorded_and_reported():
    """It stops deciding, it does not disappear: the LLM and the log still get it."""
    hist = history_where_rank_is(0.5)
    reg = classify("X", 100.0, views(0.40), calm_closes(), expiry=E, iv_history=hist)
    assert reg.iv_rank is not None
    assert "rank" in reg.reason and "vs realised" in reg.reason


def test_rank_drives_only_when_realised_vol_is_unavailable():
    """Too few closes for realised vol -> rank is the only baseline, and it decides."""
    hist = history_where_rank_is(0.9)
    iv = 0.58                                          # near the top: rank ~0.95
    reg = classify("X", 100.0, views(iv), [100.0] * 5, expiry=E, iv_history=hist)
    assert reg.detail["realized_vol"] is None
    assert reg.name in (HIGH_IV_RANGE, HIGH_IV_TREND), reg.reason
    assert "rank" in reg.reason and "no realised-vol baseline" in reg.reason


def test_no_baseline_at_all_is_not_a_trade():
    reg = classify("X", 100.0, views(0.30), [100.0] * 5, expiry=E, iv_history=[])
    assert reg.name == LOW_IV_RANGE
    assert "no volatility baseline" in reg.reason


def test_the_behaviour_every_backtest_was_measured_on_is_unchanged():
    """With no history — the state every prior measurement was made in — the
    classification must be identical to what it was."""
    reg_none = classify("X", 100.0, views(0.30), calm_closes(), expiry=E, iv_history=[])
    reg_short = classify("X", 100.0, views(0.30), calm_closes(), expiry=E, iv_history=[0.3, 0.31])
    assert reg_none.name == reg_short.name == HIGH_IV_RANGE
    assert reg_none.iv_rank is None and reg_short.iv_rank is None
