"""The decay-harvest exit.

The strategy is built on one claim: options are priced at implied vol but the
underlying moves at realised vol, and the gap is the edge. The exit rules
enforced that for structures we SOLD and not for ones we BOUGHT — so a long
premium spread could sit near expiry bleeding time value with no rule to sell
it, which is the same mistake the entry logic exists to avoid.

Harvest closes the asymmetry: sell what the market overpays for, whichever side
of it we happen to be on.
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import date, datetime
from zoneinfo import ZoneInfo

from agent import config, monitor
from agent.expectancy import bs_price, fair_value

ET = ZoneInfo("America/New_York")
NOW = datetime(2026, 9, 1, 12, 0, tzinfo=ET)

# The fair values below are computed over a fixed remaining hold, so pin the
# deadline that defines it.
def setup_function():
    config.FLATTEN_AT = "2026-09-04T09:35:00-04:00"
    # The rule ships OFF (its edge did not survive a 12-cycle A/B — see the note
    # in config.py). These tests exercise the logic, so they enable it
    # explicitly rather than depending on the shipped default either way.
    config.HARVEST_ENABLED = True
    config.HARVEST_MIN_EDGE = 50.0
    config.HARVEST_EDGE_MULT = 2.0
    config.HARVEST_MIN_EDGE_FRAC = 0.0


def quote(bid, ask):
    return {"latestQuote": {"bp": bid, "ap": ask}}


def legs(long_strike, short_strike):
    return [{"symbol": f"IWM260904P00{int(long_strike*1000):06d}", "side": "buy",
             "ratio_qty": 1},
            {"symbol": f"IWM260904P00{int(short_strike*1000):06d}", "side": "sell",
             "ratio_qty": 1}]


def position(**kw):
    p = {"underlying": "IWM", "expiry": "2026-09-04", "qty": 4,
         "entry_price": 1.50, "is_credit": 0, "max_gain": 3400.0,
         "max_loss": 600.0, "time_stop_dte": 0, "signature": "bear_put:IWM",
         "kind": "bear_put", "legs_json": json.dumps(legs(291, 283))}
    p.update(kw)
    return p


# ------------------------------------------------------------- the pricer
def test_bs_price_matches_the_atm_approximation():
    """ATM value ~= 0.4 * S * vol * sqrt(t)."""
    got = bs_price(100, 100, 0.20, 30, "C")
    approx = 0.4 * 100 * 0.20 * (30 / 365) ** 0.5
    assert abs(got - approx) < 0.05, (got, approx)


def test_put_call_parity_holds_at_zero_rates():
    c = bs_price(100, 95, 0.2, 30, "C")
    p = bs_price(100, 95, 0.2, 30, "P")
    assert abs((c - p) - 5.0) < 1e-9


def test_expired_option_is_worth_intrinsic():
    assert bs_price(90, 100, 0.2, 0, "P") == 10
    assert bs_price(90, 100, 0.2, 0, "C") == 0


def test_fair_value_signs_longs_and_shorts_like_a_mark():
    """A debit spread is worth a positive amount; reverse it and it goes negative."""
    v = fair_value(legs(291, 283), 290.4, 0.117, 2.8, qty=4)
    rev = [{**l, "side": "sell" if l["side"] == "buy" else "buy"} for l in legs(291, 283)]
    assert v > 0
    assert abs(fair_value(rev, 290.4, 0.117, 2.8, qty=4) + v) < 1e-6


# -------------------------------------------------------------- the rule
def snaps_at(long_mid, short_mid, half_spread=0.02):
    l, s = legs(291, 283)
    return {l["symbol"]: quote(long_mid - half_spread, long_mid + half_spread),
            s["symbol"]: quote(short_mid - half_spread, short_mid + half_spread)}


def test_harvests_a_long_premium_spread_the_market_overpays_for():
    """The live 1 Sep case: IWM implied 20.8% against realised 11.7%."""
    ctx = {"IWM": {"spot": 290.4, "realized_vol": 0.117}}
    d = monitor.evaluate_exit(position(), snaps_at(2.33, 0.41), {}, now=NOW, context=ctx)
    assert d.action == monitor.CLOSE_LIMIT
    assert "harvest" in d.reason and d.urgency == 65


def test_holds_when_the_market_is_not_overpaying():
    """Same structure, but priced at realised vol — no edge, so no reason to act."""
    ctx = {"IWM": {"spot": 290.4, "realized_vol": 0.117}}
    fair_long = bs_price(290.4, 291, 0.117, 2.8, "P")
    fair_short = bs_price(290.4, 283, 0.117, 2.8, "P")
    d = monitor.evaluate_exit(position(), snaps_at(fair_long, fair_short), {},
                              now=NOW, context=ctx)
    assert d.action == monitor.HOLD, d.reason


def test_does_not_harvest_a_short_premium_structure():
    """For a credit spread an overpriced mark is the reason to KEEP collecting."""
    short_first = [{**legs(291, 283)[0], "side": "sell"},
                   {**legs(291, 283)[1], "side": "buy"}]
    p = position(legs_json=json.dumps(short_first), is_credit=1, entry_price=-1.50)
    ctx = {"IWM": {"spot": 290.4, "realized_vol": 0.117}}
    d = monitor.evaluate_exit(p, snaps_at(2.33, 0.41), {}, now=NOW, context=ctx)
    assert "harvest" not in d.reason


def test_edge_must_beat_the_cost_of_getting_out():
    """A wide market can swallow the whole edge — then harvesting is a donation."""
    ctx = {"IWM": {"spot": 290.4, "realized_vol": 0.117}}
    narrow = monitor.evaluate_exit(position(), snaps_at(2.33, 0.41, 0.02), {},
                                   now=NOW, context=ctx)
    wide = monitor.evaluate_exit(position(), snaps_at(2.33, 0.41, 0.45), {},
                                 now=NOW, context=ctx)
    assert "harvest" in narrow.reason
    assert "harvest" not in wide.reason, wide.reason


def test_tiny_edges_are_left_alone():
    ctx = {"IWM": {"spot": 290.4, "realized_vol": 0.117}}
    p = position(qty=1)          # same edge per unit, 1/4 the dollars
    d = monitor.evaluate_exit(p, snaps_at(2.33, 0.41), {}, now=NOW, context=ctx)
    assert "harvest" not in d.reason


def test_rule_is_inert_without_context():
    """No spot/vol -> the rule cannot run, and must not block the other exits."""
    d = monitor.evaluate_exit(position(), snaps_at(2.33, 0.41), {}, now=NOW)
    assert "harvest" not in d.reason


def test_stop_loss_still_outranks_harvest():
    ctx = {"IWM": {"spot": 290.4, "realized_vol": 0.117}}
    p = position(entry_price=10.0)        # paid $10, now worth ~$1.92 -> deep loss
    d = monitor.evaluate_exit(p, snaps_at(2.33, 0.41), {}, now=NOW, context=ctx)
    assert d.urgency == 90 and "stop" in d.reason


def test_ships_disabled():
    """The default must stay off until there is evidence for it."""
    import importlib
    from agent import config as fresh
    importlib.reload(fresh)
    assert fresh.HARVEST_ENABLED is False
