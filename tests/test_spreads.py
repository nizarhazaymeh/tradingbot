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


# ------------------------------------------------------------------- rolling
def test_roll_order_is_four_legs_with_correct_intents():
    from agent.spreads import roll_order, bull_put_spread
    from agent.options import ContractView

    def cv(strike, mid, delta):
        return ContractView(symbol=P(strike), root="SPY", expiry=E, kind="P",
                            strike=strike, dte=5, bid=mid*0.98, ask=mid*1.02, mid=mid,
                            spread_pct=0.04, delta=delta, gamma=0.01, theta=-0.2,
                            vega=0.1, iv=0.15, open_interest=5000)

    old = bull_put_spread(cv(760, 2.00, -0.45), cv(755, 1.20, -0.30))
    body = roll_order(old, cv(750, 0.90, -0.18), cv(745, 0.45, -0.10))

    assert len(body["legs"]) == 4
    intents = [l["position_intent"] for l in body["legs"]]
    assert intents.count("buy_to_close") == 1
    assert intents.count("sell_to_close") == 1
    assert intents.count("sell_to_open") == 1
    assert intents.count("buy_to_open") == 1
    assert validate_mleg(body) == []


def test_roll_refuses_four_leg_structures():
    from agent.spreads import roll_order, iron_condor
    from agent.options import ContractView
    import pytest

    def cv(kind, strike, mid):
        return ContractView(symbol=occ("SPY", E, kind, strike), root="SPY", expiry=E,
                            kind=kind, strike=strike, dte=5, bid=mid*0.98, ask=mid*1.02,
                            mid=mid, spread_pct=0.04, delta=0.15, gamma=0.01,
                            theta=-0.2, vega=0.1, iv=0.15, open_interest=5000)

    cond = iron_condor(cv("P", 745, 0.5), cv("P", 750, 0.9),
                       cv("C", 790, 0.9), cv("C", 795, 0.5))
    with pytest.raises(ValueError, match="2-leg"):
        roll_order(cond, cv("P", 740, 0.4), cv("P", 735, 0.2))


def test_find_roll_target_requires_real_improvement():
    from agent.strategy import find_roll_target
    from agent.options import ContractView

    def cv(strike, delta, mid=1.0):
        return ContractView(symbol=P(strike), root="SPY", expiry=E, kind="P",
                            strike=strike, dte=5, bid=mid*0.98, ask=mid*1.02, mid=mid,
                            spread_pct=0.04, delta=delta, gamma=0.01, theta=-0.2,
                            vega=0.1, iv=0.15, open_interest=5000)

    threatened = cv(760, -0.45)
    # a chain where nothing is meaningfully further out
    flat = [cv(759, -0.44), cv(758, -0.43)]
    assert find_roll_target(threatened, flat, E, width=5) is None

    # a chain with a genuinely safer strike
    good = [cv(s, -0.45 + (760 - s) * 0.03) for s in range(740, 761)]
    target = find_roll_target(threatened, good, E, width=5)
    assert target is not None
    new_short, new_long = target
    assert new_short.strike < threatened.strike
    assert abs(new_short.delta) < abs(threatened.delta)
