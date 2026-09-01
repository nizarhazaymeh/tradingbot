"""Late trades are held for a fraction of the option's life but pay the full
round-trip bid/ask, because FLATTEN_AT closes the book before judging.

A position opened 3 Sep on an 8 Sep expiry lives 5 days and is held for 1. It
collects about a fifth of the decay it was priced on while paying 100% of the
spread — EV-negative for that reason alone, however good the option looked.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import date, datetime
from zoneinfo import ZoneInfo

from agent import config, risk as RK
from agent.options import ContractView, occ
from agent.spreads import bull_put_spread, bull_call_spread

ET = ZoneInfo("America/New_York")


def cv(kind, strike, mid, theta, dte=5, expiry=date(2026, 9, 8)):
    return ContractView(symbol=occ("SPY", expiry, kind, strike), root="SPY",
                        expiry=expiry, kind=kind, strike=strike, dte=dte,
                        bid=mid - 0.01, ask=mid + 0.01, mid=mid,
                        spread_pct=0.02 / mid, delta=-0.16 if kind == "P" else 0.16,
                        gamma=0.01, theta=theta, vega=0.1, iv=0.15,
                        open_interest=8000)


def credit(expiry=date(2026, 9, 8), theta_short=-0.30, theta_long=-0.05):
    return bull_put_spread(cv("P", 756, 0.85, theta_short, expiry=expiry),
                           cv("P", 751, 0.52, theta_long, expiry=expiry))


# ------------------------------------------------------------- holding_days
def test_holding_is_capped_by_the_flatten_not_the_expiry():
    """8 Sep expiry, but the book flattens 4 Sep — so the hold is ~1 day."""
    d = RK.holding_days(date(2026, 9, 8), datetime(2026, 9, 3, 10, 0, tzinfo=ET))
    assert 0.9 < d < 1.1, d


def test_holding_uses_expiry_when_it_comes_first():
    d = RK.holding_days(date(2026, 9, 3), datetime(2026, 9, 1, 10, 0, tzinfo=ET))
    assert 2.0 < d < 2.5, d


def test_holding_is_zero_after_the_flatten():
    assert RK.holding_days(date(2026, 9, 8),
                           datetime(2026, 9, 4, 12, 0, tzinfo=ET)) == 0.0


# --------------------------------------------------------------- the gate
def test_late_credit_trade_is_rejected():
    """Plenty of carry per day, but only a day to collect it."""
    sp = credit(); sp.qty = 1
    r = RK.gate_holding_period(sp, datetime(2026, 9, 4, 9, 0, tzinfo=ET))
    assert not r and r.gate == "g_holding_period"


def test_early_credit_trade_passes():
    sp = credit(expiry=date(2026, 9, 4)); sp.qty = 3
    r = RK.gate_holding_period(sp, datetime(2026, 9, 1, 10, 0, tzinfo=ET))
    assert r, r.reason


def test_no_holding_time_left_is_rejected():
    sp = credit(); sp.qty = 1
    r = RK.gate_holding_period(sp, datetime(2026, 9, 4, 14, 0, tzinfo=ET))
    assert not r and "no holding time" in r.reason


def test_directional_structure_uses_a_time_floor_not_carry():
    """A debit spread earns from direction, so the carry test cannot apply — but
    it still needs time for the move to arrive."""
    sp = bull_call_spread(cv("C", 764, 3.00, -0.40), cv("C", 769, 1.00, -0.15))
    sp.qty = 1
    assert sp.net_theta < 0
    late = RK.gate_holding_period(sp, datetime(2026, 9, 4, 9, 0, tzinfo=ET))
    assert not late and "directional" in late.reason
    early = RK.gate_holding_period(sp, datetime(2026, 9, 1, 10, 0, tzinfo=ET))
    assert early
