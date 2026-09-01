"""The competition is judged at a fixed moment, which is not a natural exit.

Two cutoffs protect against that:
  NO_NEW_AFTER  stop opening what cannot be managed to a sensible close
  FLATTEN_AT    close everything, so the judged figure is realised and cannot
                drift after we stop controlling it
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from agent import config, monitor, risk as RK
from agent.options import occ

ET = ZoneInfo("America/New_York")
OPEN = {"is_open": True, "next_open": None}


def at(y, m, d, hh, mm):
    return datetime(y, m, d, hh, mm, tzinfo=ET)


# ------------------------------------------------------------- flatten_now
def test_no_flatten_before_the_cutoff():
    assert RK.flatten_now(at(2026, 9, 4, 9, 30)) is None
    assert RK.flatten_now(at(2026, 9, 3, 15, 59)) is None


def test_flatten_after_the_cutoff():
    r = RK.flatten_now(at(2026, 9, 4, 9, 40))
    assert r and "FLATTEN_AT" in r


def test_flatten_tolerates_a_naive_datetime():
    assert RK.flatten_now(datetime(2026, 9, 4, 9, 40)) is not None


def test_flatten_disabled_when_unset(monkeypatch):
    monkeypatch.setattr(config, "FLATTEN_AT", "")
    assert RK.flatten_now(at(2026, 9, 4, 12, 0)) is None


# --------------------------------------------------------- no new positions
def test_new_positions_blocked_past_the_deadline_cutoff(monkeypatch):
    monkeypatch.setattr(RK, "now_et", lambda: at(2026, 9, 3, 15, 45))
    monkeypatch.setattr(config, "NO_NEW_AFTER_ET", "23:59")   # isolate the date rule
    r = RK.market_gates(OPEN, allow_new=True)
    assert not r and r.gate == "g_deadline_no_new"


def test_new_positions_allowed_before_it(monkeypatch):
    monkeypatch.setattr(RK, "now_et", lambda: at(2026, 9, 1, 11, 0))
    assert RK.market_gates(OPEN, allow_new=True)


# ------------------------------------------------- monitor obeys the deadline
def _pos(expiry):
    legs = [{"symbol": occ("SPY", expiry, "P", 750), "side": "buy",
             "position_intent": "buy_to_open", "ratio_qty": "1"},
            {"symbol": occ("SPY", expiry, "P", 755), "side": "sell",
             "position_intent": "sell_to_open", "ratio_qty": "1"}]
    return {"signature": "x", "kind": "bull_put", "underlying": "SPY",
            "legs_json": json.dumps(legs), "entry_price": -0.60, "is_credit": 1,
            "qty": 1, "max_gain": 60.0, "max_loss": 440.0,
            "expiry": expiry.isoformat(), "time_stop_dte": 1}


def _snaps(expiry, bid=0.20, ask=0.24):
    return {occ("SPY", expiry, "P", 750): {"latestQuote": {"bp": bid, "ap": ask}},
            occ("SPY", expiry, "P", 755): {"latestQuote": {"bp": bid + 0.5,
                                                          "ap": ask + 0.5}}}


def test_deadline_closes_a_healthy_position():
    """A position that would otherwise be held must still close at the deadline."""
    exp = date(2026, 9, 11)                      # expires well after the deadline
    d = monitor.evaluate_exit(_pos(exp), _snaps(exp), now=at(2026, 9, 4, 9, 40))
    assert d.action == monitor.CLOSE_MARKET
    assert d.urgency == 200                       # outranks every other trigger
    assert "FLATTEN_AT" in d.reason


def test_position_held_normally_before_the_deadline():
    exp = date(2026, 9, 11)
    d = monitor.evaluate_exit(_pos(exp), _snaps(exp), now=at(2026, 9, 2, 11, 0))
    assert d.action == monitor.HOLD


def test_deadline_outranks_expiry_day():
    """Both fire; the deadline wins because it is unconditional."""
    exp = date(2026, 9, 4)
    d = monitor.evaluate_exit(_pos(exp), _snaps(exp), now=at(2026, 9, 4, 9, 40))
    assert d.urgency == 200 and "FLATTEN_AT" in d.reason
