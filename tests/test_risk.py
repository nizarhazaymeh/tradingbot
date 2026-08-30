import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import date, datetime, time
import pytest

from agent import config
from agent.risk import (Book, circuit_breakers, size_spread, gate_structure,
                        gate_portfolio, evaluate, expiry_action, signature)
from agent.options import ContractView, occ
from agent.spreads import iron_condor, bull_put_spread, bull_call_spread

E = date(2026, 9, 4)


def cv(kind, strike, *, mid=1.0, delta=0.15, dte=5, oi=5000, spread_pct=0.05):
    sym = occ("SPY", E, kind, strike)
    return ContractView(symbol=sym, root="SPY", expiry=E, kind=kind, strike=strike, dte=dte,
                        bid=mid * 0.95, ask=mid * 1.05, mid=mid, spread_pct=spread_pct,
                        delta=delta if kind == "C" else -delta, gamma=0.01, theta=-0.2,
                        vega=0.1, iv=0.15, open_interest=oi)


def condor(credit_target=0.67):
    return iron_condor(cv("P", 751, mid=0.52), cv("P", 756, mid=0.85),
                       cv("C", 781, mid=0.53), cv("C", 785, mid=0.20))


def book(**kw):
    d = dict(equity=100_000, last_equity=100_000, options_buying_power=100_000)
    d.update(kw)
    return Book(**d)


# ------------------------------------------------------------ circuit breakers
def test_breaker_daily_drawdown_trips():
    b = book(equity=97_900, last_equity=100_000)      # -2.1%
    r = circuit_breakers(b)
    assert not r and r.gate == "g_daily_drawdown"


def test_breaker_daily_drawdown_ok_just_under():
    assert circuit_breakers(book(equity=98_500, last_equity=100_000))


def test_breaker_total_drawdown_trips():
    b = book(equity=93_000, last_equity=93_000)       # -7% from 100k start
    r = circuit_breakers(b)
    assert not r and r.gate == "g_total_drawdown"


def test_breaker_order_rate():
    r = circuit_breakers(book(orders_last_hour=config.MAX_ORDERS_PER_HOUR))
    assert not r and r.gate == "g_order_rate"


def test_breaker_kill_switch():
    r = circuit_breakers(book(), halted_flag=True)
    assert not r and r.gate == "g_kill_switch"


# ------------------------------------------------------------------- sizing
def test_sizing_respects_per_trade_budget():
    sp = condor()                                     # max loss $433/unit
    r = size_spread(sp, book())                       # budget 0.40% * 100k = $400
    assert not r and r.gate == "g_sizing"             # one unit is too big


def test_sizing_allows_smaller_structure():
    sp = bull_call_spread(cv("C", 769, mid=3.00), cv("C", 771, mid=2.00))
    r = size_spread(sp, book())                       # $100/unit -> $400 budget -> 4
    assert r and sp.qty == 4


def test_sizing_bound_by_portfolio_heat():
    sp = bull_call_spread(cv("C", 769, mid=3.00), cv("C", 771, mid=2.00))
    r = size_spread(sp, book(open_heat=3_950))        # only $50 of heat left
    assert not r


def test_sizing_bound_by_per_underlying():
    sp = bull_call_spread(cv("C", 769, mid=3.00), cv("C", 771, mid=2.00))
    r = size_spread(sp, book(heat_by_underlying={"SPY": 1_150}))   # $50 left of $1,200
    assert not r


def test_sizing_bound_by_per_expiry():
    sp = bull_call_spread(cv("C", 769, mid=3.00), cv("C", 771, mid=2.00))
    r = size_spread(sp, book(heat_by_expiry={E.isoformat(): 2_480}))
    assert not r


# ---------------------------------------------------------------- structure
def test_structure_gate_passes_valid_condor():
    assert gate_structure(condor())


def test_structure_gate_catches_wrong_sign():
    sp = condor()
    sp.net_price = abs(sp.net_price)                  # credit priced as debit
    r = gate_structure(sp)
    assert not r and r.gate == "g_sign_convention"


def test_structure_gate_catches_impossible_credit():
    sp = condor()
    sp.net_price = -(sp.width + 1)
    r = gate_structure(sp)
    assert not r and r.gate == "g_pricing_sane"


# ---------------------------------------------------------------- portfolio
def test_portfolio_gate_max_concurrent():
    r = gate_portfolio(condor(), book(open_positions=config.MAX_OPEN_POSITIONS))
    assert not r and r.gate == "g_max_concurrent"


def test_portfolio_gate_no_duplicate():
    sp = condor()
    r = gate_portfolio(sp, book(held_structures={signature(sp)}))
    assert not r and r.gate == "g_no_duplicate"


def test_portfolio_gate_buying_power():
    sp = condor(); sp.qty = 200
    r = gate_portfolio(sp, book(options_buying_power=1_000))
    assert not r and r.gate == "g_buying_power"


# ------------------------------------------------------------ expiry policy
def test_expiry_none_when_dte_positive():
    assert expiry_action(3) is None


def test_expiry_limit_then_market():
    assert expiry_action(0, datetime(2026, 9, 4, 10, 0)) == "close_limit"
    assert expiry_action(0, datetime(2026, 9, 4, 14, 30)) == "close_limit"
    assert expiry_action(0, datetime(2026, 9, 4, 15, 45)) == "close_market"


# ------------------------------------------------------------------ pipeline
def test_evaluate_end_to_end_rejects_oversized_condor():
    r = evaluate(condor(), book())
    assert not r and r.gate == "g_sizing"


def test_evaluate_end_to_end_accepts_sized_spread():
    sp = bull_call_spread(cv("C", 769, mid=3.00), cv("C", 771, mid=2.00))
    r = evaluate(sp, book())
    assert r and sp.qty >= 1 and r.detail["risk"] <= 400.01


def test_evaluate_rejects_illiquid_contract():
    sp = bull_call_spread(cv("C", 769, mid=3.00, oi=10), cv("C", 771, mid=2.00, oi=10))
    r = evaluate(sp, book())
    assert not r and r.gate == "g_open_interest"


def test_evaluate_rejects_wide_spread():
    sp = bull_call_spread(cv("C", 769, mid=3.00, spread_pct=0.40),
                          cv("C", 771, mid=2.00))
    r = evaluate(sp, book())
    assert not r and r.gate == "g_spread_width"


def test_evaluate_rejects_0dte():
    sp = bull_call_spread(cv("C", 769, mid=3.00, dte=0), cv("C", 771, mid=2.00, dte=0))
    r = evaluate(sp, book())
    assert not r and r.gate == "g_dte_bounds"


def test_portfolio_delta_gate_blocks_stacking():
    # long .55 delta call / short .25 delta call -> +0.30 net delta per unit
    sp = bull_call_spread(cv("C", 769, mid=3.00, delta=0.55),
                          cv("C", 771, mid=2.00, delta=0.25))
    sp.qty = 1
    assert abs(sp.net_delta - 0.30) < 1e-6
    r = gate_portfolio(sp, book(net_delta=2.9))       # 2.9 + 0.30 > 3.0 cap
    assert not r and r.gate == "g_net_delta"


def test_portfolio_delta_gate_allows_offsetting():
    sp = bull_call_spread(cv("C", 769, mid=3.00, delta=0.55),
                          cv("C", 771, mid=2.00, delta=0.25))
    sp.qty = 1
    assert gate_portfolio(sp, book(net_delta=-2.0))   # offsets existing short delta
