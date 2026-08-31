"""A working order that will never fill must not be left at the broker.

Nothing in the codebase cancelled a working order — the only cancel was inside a
halt — so an mleg limit that did not fill sat there until the session ended.

That is not untidy, it is a deadlock. Alpaca rejects any new order that takes the
OPPOSITE side of a contract a live order already touches:

    403 potential wash trade detected ... opposite side market/stop order exists

Live on 31 Aug 2026 a SPY iron condor sat unfilled at -0.34 from 20:44. Every
later SPY condor overlapped its strikes, so cycle after cycle the agent proposed
one, was rejected 403, and spent an order from its MAX_ORDERS_PER_HOUR budget to
learn nothing. It had locked itself out of the underlying, and only a restart of
the process was ever going to clear it — which it did not, because the order
lives at the broker, not in the agent.

The related half is that price_ladder() computes five rungs and cycle.py has only
ever submitted ladder[0], the least aggressive one. Rungs 1-4 are unused, so
there is no re-pricing either: an order is placed once, passively, forever.
Cancelling on a TTL means the next cycle re-proposes at a fresh price, which is
the conservative half of what the ladder was for.
"""
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent import config, cycle
from agent.client import AlpacaError


def ago(seconds):
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()


class FakeStore:
    def __init__(self, rows):
        self.rows = rows

    def open_positions(self):
        return self.rows


class FakeClient:
    def __init__(self, orders, fail_cancel=False):
        self.orders = orders
        self.cancelled = []
        self.fail_cancel = fail_cancel

    def get_order(self, oid):
        if oid not in self.orders:
            raise AlpacaError(404, "not found", "/v2/orders")
        return self.orders[oid]

    def cancel_order(self, oid):
        if self.fail_cancel:
            raise AlpacaError(422, "order is not cancelable", "/v2/orders")
        self.cancelled.append(oid)


def agent_with(orders, rows, fail_cancel=False):
    """An Agent with its broker and store replaced — __init__ needs credentials."""
    a = cycle.Agent.__new__(cycle.Agent)
    a.c = FakeClient(orders, fail_cancel=fail_cancel)
    a.store = FakeStore(rows)
    return a


def pos(sig, oid):
    return {"signature": sig, "open_order_id": oid}


def order(status="new", filled="0", age=900):
    return {"status": status, "filled_qty": filled, "submitted_at": ago(age)}


# ------------------------------------------------------------------ the fix
def test_a_stale_unfilled_order_is_cancelled():
    a = agent_with({"o1": order(age=config.ORDER_TTL_SEC + 60)}, [pos("sig1", "o1")])
    assert a._cancel_stale_orders() == ["sig1"]
    assert a.c.cancelled == ["o1"]


def test_a_young_order_is_left_alone():
    """It gets a full cycle to fill on its own before anyone interferes."""
    a = agent_with({"o1": order(age=max(config.ORDER_TTL_SEC - 60, 1))},
                   [pos("sig1", "o1")])
    assert a._cancel_stale_orders() == []
    assert a.c.cancelled == []


def test_a_partially_filled_order_is_never_cancelled():
    """Cancelling one would strand the filled legs naked.

    monitor.reconcile() refuses to auto-act on a partial for the same reason.
    """
    a = agent_with({"o1": order(status="partially_filled", filled="1", age=99999)},
                   [pos("sig1", "o1")])
    assert a._cancel_stale_orders() == []
    assert a.c.cancelled == []


def test_a_terminal_order_is_not_touched():
    for status in ("filled", "canceled", "expired", "rejected"):
        a = agent_with({"o1": order(status=status, age=99999)}, [pos("sig1", "o1")])
        assert a._cancel_stale_orders() == [], status
        assert a.c.cancelled == [], status


def test_zero_ttl_disables_it():
    old = config.ORDER_TTL_SEC
    try:
        config.ORDER_TTL_SEC = 0
        a = agent_with({"o1": order(age=99999)}, [pos("sig1", "o1")])
        assert a._cancel_stale_orders() == []
        assert a.c.cancelled == []
    finally:
        config.ORDER_TTL_SEC = old


# --------------------------------------------------------------- robustness
def test_a_position_with_no_order_id_is_skipped():
    a = agent_with({}, [{"signature": "sig1", "open_order_id": None}])
    assert a._cancel_stale_orders() == []


def test_an_unreadable_order_does_not_stop_the_cycle():
    """One broker hiccup must not prevent the rest of the book being cleaned."""
    a = agent_with({"o2": order(age=99999)},
                   [pos("bad", "missing"), pos("good", "o2")])
    assert a._cancel_stale_orders() == ["good"]


def test_a_cancel_that_races_a_fill_is_survived():
    """422 means it filled or died between the read and the cancel.

    The broker is the truth and the next cycle sees the real status, so this must
    not be reported as cancelled and must not raise.
    """
    a = agent_with({"o1": order(age=99999)}, [pos("sig1", "o1")], fail_cancel=True)
    assert a._cancel_stale_orders() == []


def test_a_malformed_timestamp_is_skipped_not_crashed():
    bad = {"status": "new", "filled_qty": "0", "submitted_at": "not-a-date"}
    a = agent_with({"o1": bad}, [pos("sig1", "o1")])
    assert a._cancel_stale_orders() == []


def test_created_at_is_used_when_submitted_at_is_absent():
    o = {"status": "new", "filled_qty": "0", "created_at": ago(99999)}
    a = agent_with({"o1": o}, [pos("sig1", "o1")])
    assert a._cancel_stale_orders() == ["sig1"]


# ------------------------------------------------------------------ wiring
def test_the_ttl_is_longer_than_one_cycle():
    """An order must get a full interval to fill before the TTL can bite."""
    assert config.ORDER_TTL_SEC > config.POLL_SECONDS


def test_run_once_cancels_before_it_clears():
    """Order matters: cancel marks the order terminal, _clear_never_filled()
    then retires the row and releases the risk budget on the next cycle."""
    import inspect
    src = inspect.getsource(cycle.Agent.run_once)
    # match the CALLS, not prose: the comment above the cancel names the clear
    assert (src.index("self._cancel_stale_orders()")
            < src.index("self._clear_never_filled()"))
