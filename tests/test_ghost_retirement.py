"""A failed read must not retire a real position.

client.positions() returns `self._request(...) or []`, so a failed or thin
response is indistinguishable from an empty book. reconcile() then classifies
every tracked structure as a ghost, and _retire_ghosts() closes them after
GHOST_RETIRE_CYCLES.

That happened on 1 Sep 2026. During a 30-minute name-resolution outage the
position list came back empty for consecutive cycles, and two REAL structures
were retired — QQQ 727/729 at 18:29:56 and QQQ 720/723 at 18:56:25. The broker
still held all four legs, one of them at +$212. They lost their exit plans, so
no take-profit or stop-loss would ever run on them, and g_no_duplicate would
not re-enter them either.

The distinction the code now makes: an empty broker response while the ledger
holds open rows is an unverified read, not a flattened account.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent import config


class FakeStore:
    def __init__(self):
        self.closed = []

    def close_position(self, sig, *, realized_pnl=None, reason=None, **kw):
        self.closed.append((sig, reason))


class Stub:
    """Just enough Agent for _retire_ghosts, which touches only these."""
    def __init__(self):
        self.store = FakeStore()
        self._ghost_streak = {}

    _retire_ghosts = None       # bound below


from agent.cycle import Agent                                    # noqa: E402
Stub._retire_ghosts = Agent._retire_ghosts


SIGS = ["bear_call:QQQ727/QQQ729", "bear_call:QQQ720/QQQ723"]


def test_zero_broker_legs_with_tracked_rows_retires_nothing():
    """The regression: an unverified read must not close real positions."""
    a = Stub()
    for _ in range(config.GHOST_RETIRE_CYCLES + 3):
        assert a._retire_ghosts(SIGS, broker_legs=0, tracked=2) == []
    assert a.store.closed == [], "a failed read retired a real position"


def test_the_streak_is_not_advanced_by_an_unverified_read():
    """A skipped cycle must not count toward retirement later."""
    a = Stub()
    a._retire_ghosts(SIGS, broker_legs=0, tracked=2)      # unverified
    assert a._ghost_streak == {}, "unverified cycles left a streak behind"


def test_a_genuine_ghost_still_retires():
    """The feature must survive the guard: broker holds OTHER legs, not these."""
    a = Stub()
    for i in range(config.GHOST_RETIRE_CYCLES):
        out = a._retire_ghosts(SIGS[:1], broker_legs=4, tracked=3)
    assert len(out) == 1, f"a real ghost was not retired: {out}"
    assert a.store.closed and "ghost" in a.store.closed[0][1]


def test_reappearing_breaks_the_streak():
    a = Stub()
    a._retire_ghosts(SIGS[:1], broker_legs=4, tracked=3)
    assert a._ghost_streak
    a._retire_ghosts([], broker_legs=4, tracked=3)        # reappeared
    assert a._ghost_streak == {}


def test_zero_broker_legs_with_no_tracked_rows_is_fine():
    """A genuinely flat account with a genuinely empty ledger is not suspicious."""
    a = Stub()
    assert a._retire_ghosts([], broker_legs=0, tracked=0) == []


def test_disabled_by_config_clears_everything():
    a = Stub()
    a._ghost_streak = {"x": 1}
    old = config.GHOST_RETIRE_CYCLES
    try:
        config.GHOST_RETIRE_CYCLES = 0
        assert a._retire_ghosts(SIGS, broker_legs=4, tracked=2) == []
        assert a._ghost_streak == {}
    finally:
        config.GHOST_RETIRE_CYCLES = old
