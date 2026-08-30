import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import date, datetime
from agent.monitor import (evaluate_exit, unrealized_pnl, mark_to_market,
                           HOLD, CLOSE_LIMIT, CLOSE_MARKET, ROLL)
from agent.options import ContractView, occ

E = date(2026, 9, 10)
NOW = datetime(2026, 9, 3, 11, 0)


def q(bid, ask):
    return {"latestQuote": {"bp": bid, "ap": ask}}


def pos(entry=-0.67, is_credit=1, qty=1, max_gain=67.0, max_loss=433.0, expiry=E):
    legs = [{"symbol": occ("SPY", expiry, "P", 751), "side": "buy", "position_intent": "buy_to_open", "ratio_qty": "1"},
            {"symbol": occ("SPY", expiry, "P", 756), "side": "sell", "position_intent": "sell_to_open", "ratio_qty": "1"}]
    return {"signature": "x", "legs_json": json.dumps(legs), "entry_price": entry,
            "is_credit": is_credit, "qty": qty, "max_gain": max_gain, "max_loss": max_loss,
            "expiry": expiry.isoformat(), "time_stop_dte": 1}


P751 = occ("SPY", E, "P", 751)
P756 = occ("SPY", E, "P", 756)


def test_mark_to_market_credit_decay_is_profit():
    # entered at -0.67 credit; now worth -0.20 to close -> profit
    snaps = {P751: q(0.05, 0.07), P756: q(0.22, 0.26)}
    p = unrealized_pnl(pos(), snaps)
    assert p > 0


def test_take_profit_fires_at_50pct():
    snaps = {P751: q(0.02, 0.04), P756: q(0.28, 0.30)}   # ~-0.28 to close
    d = evaluate_exit(pos(), snaps, now=NOW)
    assert d.action == CLOSE_LIMIT and "take profit" in d.reason


def test_stop_fires_on_big_loss():
    # credit 0.67 ($67); need pnl <= -1.5*67 = -$100.5
    snaps = {P751: q(0.10, 0.12), P756: q(1.90, 1.95)}   # ~-1.85 to close
    d = evaluate_exit(pos(), snaps, now=NOW)
    assert d.action == CLOSE_MARKET and "stop" in d.reason


def test_hold_when_nothing_triggers():
    snaps = {P751: q(0.20, 0.22), P756: q(0.80, 0.84)}
    d = evaluate_exit(pos(), snaps, now=NOW)
    assert d.action == HOLD


def test_expiry_day_beats_everything():
    today = NOW.date()
    p = pos(expiry=today)
    snaps = {occ("SPY", today, "P", 751): q(0.20, 0.22),
             occ("SPY", today, "P", 756): q(0.80, 0.84)}
    d = evaluate_exit(p, snaps, now=NOW)
    assert d.action in (CLOSE_LIMIT, CLOSE_MARKET) and d.urgency == 100


def test_expiry_escalates_to_market_late():
    today = NOW.date()
    p = pos(expiry=today)
    snaps = {occ("SPY", today, "P", 751): q(0.20, 0.22),
             occ("SPY", today, "P", 756): q(0.80, 0.84)}
    d = evaluate_exit(p, snaps, now=datetime(2026, 9, 3, 15, 45))
    assert d.action == CLOSE_MARKET


def test_delta_breach_triggers_roll():
    snaps = {P751: q(0.20, 0.22), P756: q(0.80, 0.84)}
    v = ContractView(symbol=P756, root="SPY", expiry=E, kind="P", strike=756, dte=7,
                     bid=0.8, ask=0.84, mid=0.82, spread_pct=0.05, delta=-0.55,
                     gamma=0.01, theta=-0.2, vega=0.1, iv=0.15)
    d = evaluate_exit(pos(), snaps, views={P756: v}, now=NOW)
    assert d.action == ROLL


def test_time_stop_at_dte_1():
    p = pos(expiry=date(2026, 9, 4))     # NOW is 9/3 -> DTE 1
    snaps = {occ("SPY", date(2026,9,4), "P", 751): q(0.20, 0.22),
             occ("SPY", date(2026,9,4), "P", 756): q(0.80, 0.84)}
    d = evaluate_exit(p, snaps, now=NOW)
    assert d.action == CLOSE_LIMIT and "time stop" in d.reason


def test_stale_quote_holds_rather_than_guessing():
    snaps = {P751: q(0, 0), P756: q(0.80, 0.84)}
    d = evaluate_exit(pos(), snaps, now=NOW)
    assert d.action == HOLD and "cannot mark" in d.reason
