"""A position exists only when an order FILLS.

Observed live 1 Sep 2026: recording on submission created a phantom. The monitor
then tried to manage legs the broker did not hold, and the risk budget was
consumed by an order that might never fill. Reconciliation flagged it as
`partial` — some legs held (shared with a real position), some not.
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import date

from agent import monitor
from agent.options import occ
from agent.state import Store

E = date(2026, 9, 4)


def _legs(*specs):
    return [{"symbol": occ("SPY", E, k, s), "side": sd,
             "position_intent": "buy_to_open" if sd == "buy" else "sell_to_open",
             "ratio_qty": "1"} for k, s, sd in specs]


class _Spread:
    kind, underlying, expiry, qty = "iron_condor", "SPY", E, 1
    net_price, width = -0.50, 2.0
    is_credit, net_delta, net_theta = True, 0.0, 10.0
    max_gain_per_unit, meta = 50.0, {}

    def __init__(self, legs):
        self.legs = [type("L", (), {"payload": staticmethod(lambda d=d: d)})() for d in legs]

    def total_max_loss(self):
        return 150.0


def _store(tmp_path, legs):
    st = Store(str(tmp_path / "s.db"))
    st.open_position(signature="ic:test", spread=_Spread(legs), order={"id": "x"},
                     take_profit=17, stop_loss=75, time_stop_dte=1,
                     client_order_id="c")
    return st


def _broker(*syms):
    return [{"symbol": s, "asset_class": "us_option"} for s in syms]


def test_all_legs_held_is_clean(tmp_path):
    legs = _legs(("P", 753, "buy"), ("P", 755, "sell"),
                 ("C", 772, "sell"), ("C", 774, "buy"))
    st = _store(tmp_path, legs)
    rec = monitor.reconcile(st, _broker(*[l["symbol"] for l in legs]))
    assert rec["clean"], rec


def test_no_legs_held_is_a_ghost(tmp_path):
    legs = _legs(("P", 753, "buy"), ("P", 755, "sell"),
                 ("C", 772, "sell"), ("C", 774, "buy"))
    st = _store(tmp_path, legs)
    rec = monitor.reconcile(st, _broker())
    assert rec["ghosts"] and not rec["clean"]


def test_some_legs_held_is_not_clean(tmp_path):
    """The phantom case: put legs shared with a real position, calls never filled."""
    legs = _legs(("P", 753, "buy"), ("P", 755, "sell"),
                 ("C", 773, "sell"), ("C", 775, "buy"))
    st = _store(tmp_path, legs)
    rec = monitor.reconcile(st, _broker(occ("SPY", E, "P", 753), occ("SPY", E, "P", 755)))
    assert not rec["clean"], "a partially-held structure must never read as clean"


def test_broker_leg_we_never_recorded_is_an_orphan(tmp_path):
    legs = _legs(("P", 753, "buy"), ("P", 755, "sell"),
                 ("C", 772, "sell"), ("C", 774, "buy"))
    st = _store(tmp_path, legs)
    rec = monitor.reconcile(
        st, _broker(*[l["symbol"] for l in legs], occ("SPY", E, "C", 800)))
    assert occ("SPY", E, "C", 800) in rec["orphans"]
