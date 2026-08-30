import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import date
from agent.spreads import validate_mleg, Leg, Spread
from agent.options import occ

E = date(2026, 9, 4)
C = lambda k: occ("SPY", E, "C", k)
P = lambda k: occ("SPY", E, "P", k)


def body(legs, **kw):
    b = {"order_class": "mleg", "qty": "1", "type": "limit",
         "limit_price": "-1.35", "time_in_force": "day", "legs": legs}
    b.update(kw)
    return b


def leg(sym, side, intent="", ratio=1):
    intent = intent or ("buy_to_open" if side == "buy" else "sell_to_open")
    return {"symbol": sym, "side": side, "position_intent": intent, "ratio_qty": str(ratio)}


def test_valid_bull_put_spread():
    assert validate_mleg(body([leg(P(750), "sell"), leg(P(745), "buy")])) == []


def test_valid_iron_condor():
    assert validate_mleg(body([
        leg(P(745), "buy"), leg(P(750), "sell"),
        leg(C(790), "sell"), leg(C(795), "buy")])) == []


def test_valid_long_strangle_both_legs_long():
    assert validate_mleg(body([leg(P(750), "buy"), leg(C(790), "buy")],
                              limit_price="0.60")) == []


def test_R1_too_many_legs():
    legs = [leg(P(740), "buy"), leg(P(745), "sell"), leg(P(750), "buy"),
            leg(C(790), "sell"), leg(C(795), "buy")]
    assert any("R1" in e for e in validate_mleg(body(legs)))


def test_R2_naked_short_rejected():
    errs = validate_mleg(body([leg(C(790), "sell"), leg(C(795), "sell")]))
    assert any("R2" in e for e in errs)


def test_R2_calendar_spread_rejected():
    """Short near-dated + long far-dated is NOT covered — Alpaca rejects it."""
    near = occ("SPY", date(2026, 9, 4), "C", 790)
    far = occ("SPY", date(2026, 9, 11), "C", 790)
    errs = validate_mleg(body([leg(near, "sell"), leg(far, "buy")]))
    assert any("R2" in e for e in errs)


def test_R2_debit_spread_is_covered():
    """Long call BELOW a short call IS covered — that's a bull call debit spread."""
    assert validate_mleg(body([leg(C(785), "buy"), leg(C(790), "sell")],
                              limit_price="2.44")) == []


def test_R2_ratio_spread_rejected():
    """1 long vs 2 short in the same bucket is uncovered."""
    errs = validate_mleg(body([leg(C(785), "buy", ratio=1), leg(C(790), "sell", ratio=2)]))
    assert any("R2" in e for e in errs)


def test_R2_debit_put_spread_is_covered():
    assert validate_mleg(body([leg(P(760), "buy"), leg(P(755), "sell")],
                              limit_price="1.80")) == []


def test_R3_equity_leg_rejected():
    errs = validate_mleg(body([leg("SPY", "buy"), leg(C(790), "sell")]))
    assert any("R3" in e for e in errs)


def test_R4_ratio_gcd_must_be_one():
    errs = validate_mleg(body([leg(P(750), "sell", ratio=2), leg(P(745), "buy", ratio=4)]))
    assert any("R4" in e for e in errs)


def test_R4_simplified_ratio_ok():
    assert validate_mleg(body([leg(P(750), "sell", ratio=1), leg(P(745), "buy", ratio=2)])) == []


def test_R5_gtc_rejected():
    errs = validate_mleg(body([leg(P(750), "sell"), leg(P(745), "buy")], time_in_force="gtc"))
    assert any("R5" in e for e in errs)


def test_R5_stop_type_rejected():
    errs = validate_mleg(body([leg(P(750), "sell"), leg(P(745), "buy")], type="stop_limit"))
    assert any("R5" in e for e in errs)


def test_R5_extended_hours_rejected():
    errs = validate_mleg(body([leg(P(750), "sell"), leg(P(745), "buy")], extended_hours=True))
    assert any("R5" in e for e in errs)


def test_top_level_side_rejected():
    errs = validate_mleg(body([leg(P(750), "sell"), leg(P(745), "buy")], side="buy"))
    assert any("top-level" in e for e in errs)


def test_missing_position_intent_rejected():
    bad = {"symbol": P(750), "side": "sell", "ratio_qty": "1"}
    errs = validate_mleg(body([bad, leg(P(745), "buy")]))
    assert any("position_intent" in e for e in errs)


def test_single_leg_rejected():
    assert any("R1" in e for e in validate_mleg(body([leg(P(750), "sell")])))
