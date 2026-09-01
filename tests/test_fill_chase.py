"""Fill chasing. Verified live 1 Sep 2026: a limit derived from a chain fetched
earlier in the cycle sat at status `new` and never filled, because the quote it
came from was seconds stale. A limit at the natural price filled in under 5s.
"""
import sys, os, pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import date
from unittest.mock import MagicMock

from agent import executor as X, spreads as S
from agent.options import ContractView, occ

E = date(2026, 9, 4)


def cv(kind, strike, bid, ask):
    mid = (bid + ask) / 2
    return ContractView(symbol=occ("SPY", E, kind, strike), root="SPY", expiry=E,
                        kind=kind, strike=strike, dte=3, bid=bid, ask=ask, mid=mid,
                        spread_pct=(ask - bid) / mid, delta=-0.16 if kind == "P" else 0.16,
                        gamma=0.01, theta=-0.2, vega=0.1, iv=0.15, open_interest=5000)


def credit_spread():
    return S.bull_put_spread(cv("P", 754, 0.50, 0.54), cv("P", 750, 0.16, 0.20))


def debit_spread():
    return S.bull_call_spread(cv("C", 764, 3.00, 3.10), cv("C", 769, 0.90, 1.00))


# ---------------------------------------------------------------- pricing
def test_natural_price_transacts_for_a_credit():
    """Sell at the bid, buy at the ask — the price that actually fills."""
    mid, nat = X.spread_prices(credit_spread())
    # short 754 bid 0.50, long 750 ask 0.20 -> natural credit 0.30 -> -0.30
    assert nat == pytest.approx(-0.30, abs=0.01)
    assert nat > mid, "natural must accept LESS credit than mid"


def test_natural_price_transacts_for_a_debit():
    mid, nat = X.spread_prices(debit_spread())
    # long 764 ask 3.10, short 769 bid 0.90 -> natural debit 2.20
    assert nat == pytest.approx(2.20, abs=0.01)
    assert nat > mid, "natural must pay MORE than mid"


def test_ladder_is_monotonic_toward_fill_for_credit():
    lad = X.price_ladder(credit_spread())
    assert lad == sorted(lad), "a credit ladder must accept progressively less"
    assert len(set(lad)) == len(lad), "no duplicate rungs"


def test_ladder_is_monotonic_toward_fill_for_debit():
    lad = X.price_ladder(debit_spread())
    assert lad == sorted(lad), "a debit ladder must pay progressively more"


def test_ladder_last_rung_goes_past_natural():
    for sp in (credit_spread(), debit_spread()):
        _, nat = X.spread_prices(sp)
        assert X.price_ladder(sp)[-1] > nat


# ------------------------------------------------------------ quote refresh
def test_refresh_quotes_updates_the_views():
    sp = credit_spread()
    c = MagicMock()
    c.option_snapshots.return_value = {
        l.symbol: {"latestQuote": {"bp": 1.00, "ap": 1.10}} for l in sp.legs}
    ex = X.Executor(c, dry_run=True)
    assert ex.refresh_quotes(sp)
    for l in sp.legs:
        assert l.view.bid == 1.00 and l.view.ask == 1.10


def test_refresh_quotes_refuses_a_one_sided_quote():
    """A zero bid means no real market; repricing off it would be fiction."""
    sp = credit_spread()
    c = MagicMock()
    snaps = {l.symbol: {"latestQuote": {"bp": 1.00, "ap": 1.10}} for l in sp.legs}
    snaps[sp.legs[0].symbol] = {"latestQuote": {"bp": 0, "ap": 0.05}}
    c.option_snapshots.return_value = snaps
    ex = X.Executor(c, dry_run=True)
    assert not ex.refresh_quotes(sp)


def test_chase_refuses_to_submit_on_stale_quotes():
    sp = credit_spread()
    c = MagicMock()
    c.option_snapshots.return_value = {
        l.symbol: {"latestQuote": {"bp": 0, "ap": 0}} for l in sp.legs}
    ex = X.Executor(c, dry_run=False)
    order, msg = ex.open_and_chase(sp)
    assert order is None and "refresh" in msg
    c.submit_order.assert_not_called()
