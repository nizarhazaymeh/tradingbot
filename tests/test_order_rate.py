"""A dry run must not consume the live order-rate budget, nor engage the kill switch.

Both bugs surfaced while measuring T7 (rate-limit headroom) on 31 Aug 2026, and
both would have halted the live session:

  1. Executor.open_spread() logs dry-run orders to orders_log with
     status='dry_run'. Store.orders_since() counted every row, so rehearsing
     burned MAX_ORDERS_PER_HOUR (12) and tripped g_order_rate. `run.py once` is
     dry by default, so this was the normal path, not an edge case.

  2. When a breaker trips, cycle.py writes a HALTED file. That write was not
     guarded by dry_run, so the rehearsal in (1) left the file behind and
     g_kill_switch then blocked every LIVE cycle until it was deleted by hand.
"""
import inspect
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent import config, cycle
from agent.state import Store

PAST = "2000-01-01T00:00:00"


def store():
    return Store(path=os.path.join(tempfile.mkdtemp(), "t.db"))


def test_dry_run_orders_are_not_counted():
    s = store()
    for i in range(20):
        s.log_order(f"dry-{i}", {"qty": "1"}, {"status": "dry_run"}, "open")
    assert s.orders_since(PAST) == 0, "a rehearsal must not consume the live budget"


def test_real_orders_are_counted():
    s = store()
    for i, st in enumerate(["accepted", "new", "filled", "partially_filled"]):
        s.log_order(f"real-{i}", {"qty": "1"}, {"status": st}, "open")
    assert s.orders_since(PAST) == 4


def test_mixed_counts_only_the_real_ones():
    s = store()
    for i in range(15):
        s.log_order(f"dry-{i}", {}, {"status": "dry_run"}, "open")
    for i in range(3):
        s.log_order(f"real-{i}", {}, {"status": "accepted"}, "open")
    assert s.orders_since(PAST) == 3


def test_missing_status_still_counts():
    """An order whose submit response was lost is a real order, not a dry run.

    log_order() writes NULL status when `order` is None, which happens on a
    timeout — exactly when we least want to under-count.
    """
    s = store()
    s.log_order("unknown", {}, None, "open")
    assert s.orders_since(PAST) == 1


def test_rate_limit_stays_under_budget_at_the_configured_interval():
    """Measured 23 requests/cycle on 31 Aug 2026. Guard the headroom claim."""
    per_cycle = 23
    used = per_cycle * 60 / config.POLL_SECONDS
    assert used < 100, (
        f"{used:.0f} req/min at POLL_SECONDS={config.POLL_SECONDS} leaves too "
        "little of the 200/min budget for retries and exits")


def test_halt_file_write_is_guarded_by_dry_run():
    """A dry run must not be able to engage the persistent kill switch.

    Checked structurally rather than by running a cycle, which would need live
    credentials: the HALT_FILE write must sit inside a branch whose condition
    mentions dry_run.
    """
    import ast, textwrap

    tree = ast.parse(textwrap.dedent(inspect.getsource(cycle.Agent.run_once)))

    def guarded(node, inside_dry_run_branch=False):
        """True if every HALT_FILE.write_text is under a dry_run condition."""
        found, ok = [], []
        for child in ast.walk(node):
            if isinstance(child, ast.If):
                cond = ast.unparse(child.test)
                if "dry_run" in cond:
                    for sub in child.body + child.orelse:
                        for n in ast.walk(sub):
                            if _is_halt_write(n):
                                ok.append(n.lineno)
        for n in ast.walk(node):
            if _is_halt_write(n):
                found.append(n.lineno)
        return found, ok

    def _is_halt_write(n):
        return (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == "write_text"
                and isinstance(n.func.value, ast.Name)
                and n.func.value.id == "HALT_FILE")

    found, ok = guarded(tree)
    assert found, "no HALT_FILE.write_text found — did it move? update this test"
    assert set(found) == set(ok), (
        f"HALT_FILE.write_text at line(s) {sorted(set(found) - set(ok))} is not "
        "inside a dry_run branch — a rehearsal could engage the kill switch")
