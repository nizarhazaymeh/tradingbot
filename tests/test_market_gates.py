"""--no-new must actually stop the agent opening positions.

market_gates() nested the near-close cutoff inside `if allow_new`, so
allow_new=False fell through to PASS. `run.py --no-new` therefore did the
opposite of its name twice over: it permitted new positions, and it disabled the
NO_NEW_AFTER_ET cutoff as well.

Observed live on 31 Aug 2026 — a `run.py once --live --no-new` cycle opened a
second SPY iron condor while the first was still open. It did not fill, so the
bug cost nothing, but on Friday the plan is to stop opening at 15:00 ET and
flatten at 09:30, and --no-new is how that would be done.
"""
import os
import sys
from datetime import time as dtime
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent import config, risk as RK

OPEN = {"is_open": True, "next_open": "2026-09-01T09:30:00-04:00"}
SHUT = {"is_open": False, "next_open": "2026-09-01T09:30:00-04:00"}


def test_no_new_blocks_opening():
    """The regression."""
    g = RK.market_gates(OPEN, allow_new=False)
    assert not g, "allow_new=False must block new positions"
    assert g.gate == "g_no_new_requested"


def test_allow_new_passes_during_the_session():
    with patch.object(RK, "now_et") as n:
        n.return_value.time.return_value = dtime(11, 0)
        assert RK.market_gates(OPEN, allow_new=True)


def test_closed_market_blocks_regardless():
    for allow in (True, False):
        g = RK.market_gates(SHUT, allow_new=allow)
        assert not g and g.gate == "g_market_open"


def test_near_close_cutoff_still_fires():
    """The cutoff must not be skippable — it was, whenever allow_new was False."""
    with patch.object(RK, "now_et") as n:
        n.return_value.time.return_value = dtime(15, 45)      # past 15:30
        g = RK.market_gates(OPEN, allow_new=True)
        assert not g and g.gate == "g_not_near_close"


def test_no_new_is_not_a_way_to_bypass_the_cutoff():
    """Both reasons to block are blocks; neither cancels the other."""
    with patch.object(RK, "now_et") as n:
        n.return_value.time.return_value = dtime(15, 45)
        g = RK.market_gates(OPEN, allow_new=False)
        assert not g, "must still block after the cutoff with --no-new"


def test_before_the_cutoff_allow_new_passes():
    with patch.object(RK, "now_et") as n:
        cutoff = config.NO_NEW_AFTER_ET
        hh, mm = (int(x) for x in cutoff.split(":"))
        n.return_value.time.return_value = dtime(hh, max(0, mm - 5))
        assert RK.market_gates(OPEN, allow_new=True)


# --------------------------------------------------- the loop path, not just the gate
def test_run_forever_passes_allow_new_through():
    """market_gates() honouring allow_new is useless if the loop never sends it.

    run_forever() called self.run_once() with no arguments, so allow_new
    defaulted to True on every cycle and `run.py loop --no-new` silently ignored
    the flag. The gate was fixed this morning; the loop never reached it with the
    right value. Friday's plan depends on exactly this path — stop opening at
    15:00 ET while still managing exits.

    Asserted on the signature and the call site rather than by running a cycle,
    which would need live credentials.
    """
    import inspect
    from agent.cycle import Agent

    sig = inspect.signature(Agent.run_forever)
    assert "allow_new" in sig.parameters, "run_forever lost its allow_new parameter"

    src = inspect.getsource(Agent.run_forever)
    assert "run_once(allow_new=allow_new)" in src, (
        "run_forever calls run_once without forwarding allow_new, so --no-new "
        "is silently ignored in loop mode")


def test_run_py_forwards_no_new_to_the_loop():
    """The CLI half of the same bug."""
    from pathlib import Path
    src = Path(__file__).resolve().parent.parent / "run.py"
    text = src.read_text()
    assert "run_forever(interval=a.interval, allow_new=not a.no_new)" in text, (
        "run.py does not forward --no-new to run_forever")
