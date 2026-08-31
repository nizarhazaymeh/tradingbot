"""The ledger must match the broker, and unfilled orders must not consume risk.

Two defects, both live on the DEV account on 31 Aug 2026:

  1. cycle.consider() records a position when an order is ACCEPTED, not filled.
     That is deliberate — a crash between submit and fill would otherwise leave a
     real position with no exit plan — but an order that never fills stayed on
     the books forever. Book.from_account() derives portfolio heat from tracked
     positions, so two cancelled orders held $572 of the $1,145 the agent
     believed was at risk: half of SPY's per-underlying cap, blocking real
     trades.

  2. reconcile() classified on symbol OVERLAP (`syms & held`), so a structure
     counted as live if any single leg matched. A cancelled SPY condor sharing
     775C/777C with a filled one was never flagged.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent import monitor


class FakeStore:
    def __init__(self, structures):
        # structures: {signature: [symbols]}
        self._s = structures

    def open_positions(self):
        return [{"signature": sig,
                 "legs_json": json.dumps([{"symbol": s} for s in syms])}
                for sig, syms in self._s.items()]


def held(*syms):
    return [{"symbol": s, "asset_class": "us_option"} for s in syms]


A = ["SPY_P750", "SPY_P746"]
B = ["SPY_C775", "SPY_C777"]
CONDOR = A + B


def test_clean_when_every_leg_is_held():
    r = monitor.reconcile(FakeStore({"one": CONDOR}), held(*CONDOR))
    assert r["clean"]
    assert r["ghosts"] == [] and r["partial"] == [] and r["orphans"] == []


def test_ghost_when_no_leg_is_held():
    r = monitor.reconcile(FakeStore({"one": CONDOR}), held())
    assert r["ghosts"] == ["one"]
    assert not r["clean"]


def test_partial_when_some_legs_are_held():
    """The regression: overlap treated this as live."""
    r = monitor.reconcile(FakeStore({"one": CONDOR}), held(*B))
    assert r["ghosts"] == [], "not a ghost — two legs really are held"
    assert r["partial"] == ["one"], "partial coverage must be flagged"
    assert not r["clean"]


def test_a_cancelled_near_duplicate_is_not_counted_as_live():
    """The exact live case: two condors sharing their call legs, one filled.

    Under overlap the cancelled one matched on 775C/777C and read as real, so its
    max-loss kept consuming portfolio heat.
    """
    store = FakeStore({"filled": CONDOR,
                       "cancelled": ["SPY_P751", "SPY_P747"] + B})
    r = monitor.reconcile(store, held(*CONDOR))
    assert "filled" not in r["ghosts"] and "filled" not in r["partial"]
    assert "cancelled" in r["partial"], (
        "the cancelled near-duplicate must not pass as fully live")
    assert not r["clean"]


def test_orphan_when_broker_holds_something_untracked():
    r = monitor.reconcile(FakeStore({"one": A}), held(*A, "SPY_C800"))
    assert r["orphans"] == ["SPY_C800"]
    assert not r["clean"]


def test_ghost_and_orphan_together():
    r = monitor.reconcile(FakeStore({"one": A}), held("QQQ_P700"))
    assert r["ghosts"] == ["one"]
    assert r["orphans"] == ["QQQ_P700"]


def test_counts_are_reported():
    r = monitor.reconcile(FakeStore({"one": CONDOR}), held(*CONDOR))
    assert r["broker_option_legs"] == 4
    assert r["tracked_structures"] == 1


def test_non_option_broker_rows_are_ignored():
    """Equity positions must not be mistaken for option legs."""
    rows = held(*CONDOR) + [{"symbol": "SPY", "asset_class": "us_equity"}]
    r = monitor.reconcile(FakeStore({"one": CONDOR}), rows)
    assert r["clean"], "an equity row was counted as an option orphan"
    assert r["broker_option_legs"] == 4


def test_empty_ledger_and_empty_broker_is_clean():
    r = monitor.reconcile(FakeStore({}), held())
    assert r["clean"] and r["tracked_structures"] == 0
