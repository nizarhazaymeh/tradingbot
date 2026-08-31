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
