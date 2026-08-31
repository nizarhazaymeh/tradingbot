"""A tracked structure the broker does not hold must not block re-entry forever.

monitor.reconcile() has always computed ghosts exactly — tracked structures the
broker holds NO leg of — and then only logged them. Nothing retired the row.

Live on 31 Aug 2026: an IWM bear_put filled at 14:35 and later left the book. Its
row stayed open, so risk.g_no_duplicate answered "already holding
bear_put:IWM260904P00284000/IWM260904P00292000" to every IWM proposal for the
rest of the session — six rejections and counting. Restarting the process does
not clear it, because the row is in SQLite rather than in memory. That is a
harder deadlock than the wash-trade one, which at least self-clears when the
broker cancels the blocking order.

The retirement is deliberately slow. A fill that has not yet surfaced in
/v2/positions reads as a ghost for one cycle, and one observation is not
evidence, so a structure must be absent on GHOST_RETIRE_CYCLES consecutive
cycles. The streak lives in memory so a restart re-observes first: being slow
costs a few minutes of a blocked structure, being fast costs a real position its
exit plan.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent import config, cycle


class FakeStore:
    def __init__(self):
        self.closed = []

    def close_position(self, sig, *, realized_pnl, reason, close_order_id=None):
        self.closed.append((sig, realized_pnl, reason))


def agent():
    a = cycle.Agent.__new__(cycle.Agent)
    a.store = FakeStore()
    a._ghost_streak = {}
    return a


# ----------------------------------------------------------- the streak rule
def test_one_sighting_is_not_enough():
    """A fill not yet visible in /v2/positions looks exactly like a ghost."""
    a = agent()
    assert a._retire_ghosts(["sig1"]) == []
    assert a.store.closed == []


def test_it_retires_after_the_configured_run_of_cycles():
    a = agent()
    for _ in range(config.GHOST_RETIRE_CYCLES - 1):
        assert a._retire_ghosts(["sig1"]) == []
    assert a._retire_ghosts(["sig1"]) == ["sig1"]
    assert [c[0] for c in a.store.closed] == ["sig1"]


def test_a_structure_that_reappears_resets_the_streak():
    """The position was there all along and the broker was briefly behind."""
    a = agent()
    a._retire_ghosts(["sig1"])
    a._retire_ghosts([])                       # reappeared
    assert a._ghost_streak == {}
    for _ in range(config.GHOST_RETIRE_CYCLES - 1):
        assert a._retire_ghosts(["sig1"]) == []
    assert a._retire_ghosts(["sig1"]) == ["sig1"]


def test_streaks_are_tracked_per_structure():
    a = agent()
    a._retire_ghosts(["old"])                  # old reaches 1
    for _ in range(config.GHOST_RETIRE_CYCLES - 2):
        a._retire_ghosts(["old", "new"])
    out = a._retire_ghosts(["old", "new"])
    assert "old" in out and "new" not in out


def test_a_retired_ghost_is_forgotten_not_retired_twice():
    a = agent()
    for _ in range(config.GHOST_RETIRE_CYCLES):
        a._retire_ghosts(["sig1"])
    assert len(a.store.closed) == 1
    a._retire_ghosts([])
    assert a._ghost_streak == {}


def test_zero_disables_it_and_clears_the_streak():
    old = config.GHOST_RETIRE_CYCLES
    try:
        a = agent()
        a._retire_ghosts(["sig1"])
        config.GHOST_RETIRE_CYCLES = 0
        assert a._retire_ghosts(["sig1"]) == []
        assert a.store.closed == []
        assert a._ghost_streak == {}
    finally:
        config.GHOST_RETIRE_CYCLES = old


def test_no_ghosts_is_not_an_error():
    a = agent()
    assert a._retire_ghosts([]) == []
    assert a._retire_ghosts(None) == []


# -------------------------------------------------------------- P&L honesty
def test_pnl_is_recorded_as_unknown_not_zero():
    """These legs can be shared between structures — the two SPY condors on
    31 Aug shared both put strikes — so fills cannot be attributed to one."""
    a = agent()
    for _ in range(config.GHOST_RETIRE_CYCLES):
        a._retire_ghosts(["sig1"])
    sig, pnl, reason = a.store.closed[0]
    assert pnl is None, "an unattributable P&L must not be recorded as a real zero"
    assert "unknown" in reason.lower()


def test_stats_excludes_unknown_pnl_from_the_win_rate():
    """A retired ghost must not be counted as a losing trade."""
    import tempfile
    from agent.state import Store
    s = Store(path=os.path.join(tempfile.mkdtemp(), "t.db"))
    cols = ("signature, kind, underlying, expiry, qty, legs_json, entry_price, "
            "is_credit, max_loss, max_gain, width, opened_at, status, realized_pnl")
    row = "'x', 'SPY', '2026-09-04', 1, '[]', -0.5, 1, 100, 50, 2, 'now', 'closed'"
    with s._conn() as c:
        c.execute(f"INSERT INTO positions ({cols}) VALUES ('win', {row}, 100.0)")
        c.execute(f"INSERT INTO positions ({cols}) VALUES ('ghost', {row}, NULL)")
    st = s.stats()
    assert st["closed_trades"] == 2
    assert st["closed_pnl_unknown"] == 1
    assert st["win_rate"] == 1.0, "the unknown must not count as a loss"
    assert st["realized_pnl"] == 100.0


# ------------------------------------------------------------------ wiring
def test_ghosts_are_retired_before_the_risk_book_is_built():
    """A retired row must stop consuming heat this cycle, not the next."""
    import inspect
    src = inspect.getsource(cycle.Agent.run_once)
    assert src.index("self._retire_ghosts(") < src.index("RK.Book.from_account(")


def test_retirement_runs_after_reconcile_which_identifies_the_ghosts():
    import inspect
    src = inspect.getsource(cycle.Agent.run_once)
    assert src.index("monitor.reconcile(") < src.index("self._retire_ghosts(")


def test_a_partial_is_still_never_auto_acted_on():
    """reconcile() separates partial from ghost; only ghosts are retired."""
    import inspect
    src = inspect.getsource(cycle.Agent._retire_ghosts)
    assert "partial" not in src.split('"""')[2], (
        "_retire_ghosts must only ever be handed reconcile()'s ghost list")
