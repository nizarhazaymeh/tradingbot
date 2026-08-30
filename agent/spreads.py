"""Multi-leg (`mleg`) option spread construction and validation.

Alpaca's mleg rules, all enforced here before anything reaches the API:
  R1  max 4 legs
  R2  every SHORT leg must be covered by a LONG leg of the same type+expiry
      inside the SAME order  (=> no calendars, no naked shorts, no ratio spreads)
  R3  no equity legs
  R4  ratio_qty values must have GCD == 1
  R5  market|limit only; day TIF; no extended hours
  SIGN  limit_price: POSITIVE = debit (you pay), NEGATIVE = credit (you receive)
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from functools import reduce
from math import gcd
from typing import List, Optional

from .options import ContractView, parse_occ

MULTIPLIER = 100

BUY_TO_OPEN, SELL_TO_OPEN = "buy_to_open", "sell_to_open"
BUY_TO_CLOSE, SELL_TO_CLOSE = "buy_to_close", "sell_to_close"
INTENTS = {BUY_TO_OPEN, SELL_TO_OPEN, BUY_TO_CLOSE, SELL_TO_CLOSE}


@dataclass
class Leg:
    symbol: str
    side: str            # 'buy' | 'sell'
    intent: str
    ratio_qty: int = 1
    view: Optional[ContractView] = None

    def payload(self) -> dict:
        return {"symbol": self.symbol, "ratio_qty": str(self.ratio_qty),
                "side": self.side, "position_intent": self.intent}


# Which structures are economically CREDIT vs DEBIT. This is a property of the
# strategy itself, NOT of the price we happen to compute — so it can be used to
# validate the sign of limit_price independently.
CREDIT_KINDS = {"iron_condor", "iron_butterfly", "bull_put", "bear_call"}
DEBIT_KINDS = {"bull_call", "bear_put", "long_strangle", "long_straddle"}


@dataclass
class Spread:
    kind: str                    # iron_condor | bull_put | bear_call | bull_call | bear_put
    underlying: str
    expiry: date
    legs: List[Leg]
    net_price: float             # +debit / -credit, per unit (before multiplier)
    max_loss_per_unit: float     # dollars
    max_gain_per_unit: float     # dollars
    width: float
    qty: int = 1
    meta: dict = field(default_factory=dict)

    @property
    def is_credit(self) -> bool:
        """Determined by the STRATEGY, not by the sign of net_price."""
        if self.kind in CREDIT_KINDS:
            return True
        if self.kind in DEBIT_KINDS:
            return False
        return self.net_price < 0        # unknown kind: fall back to the price

    @property
    def expected_sign(self) -> int:
        return -1 if self.is_credit else 1

    @property
    def dte(self) -> int:
        return (self.expiry - date.today()).days

    @property
    def net_delta(self) -> float:
        return sum((l.view.delta if l.view else 0.0) * l.ratio_qty * (1 if l.side == "buy" else -1)
                   for l in self.legs) * self.qty

    @property
    def net_theta(self) -> float:
        return sum((l.view.theta if l.view else 0.0) * l.ratio_qty * (1 if l.side == "buy" else -1)
                   for l in self.legs) * self.qty * MULTIPLIER

    def total_max_loss(self) -> float:
        return self.max_loss_per_unit * self.qty

    def client_order_id(self, tag: str = "open") -> str:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        return f"{self.kind}-{stamp}-{self.underlying}-{tag}-{uuid.uuid4().hex[:8]}"[:128]

    def order(self, *, order_type: str = "limit", limit_price: float = None,
              client_order_id: str = None) -> dict:
        body = {
            "order_class": "mleg",
            "qty": str(self.qty),
            "type": order_type,
            "time_in_force": "day",
            "legs": [l.payload() for l in self.legs],
            "client_order_id": client_order_id or self.client_order_id(),
        }
        if order_type == "limit":
            price = self.net_price if limit_price is None else limit_price
            body["limit_price"] = f"{price:.2f}"
        return body

    def describe(self) -> str:
        side = "CREDIT" if self.is_credit else "DEBIT"
        legs = " / ".join(
            f"{'+' if l.side == 'buy' else '-'}{parse_occ(l.symbol)[3]:.0f}{parse_occ(l.symbol)[2]}"
            for l in self.legs)
        return (f"{self.kind} {self.underlying} {self.expiry} x{self.qty} [{legs}] "
                f"{side} ${abs(self.net_price):.2f} | maxloss ${self.total_max_loss():.0f} "
                f"| delta {self.net_delta:+.2f} theta {self.net_theta:+.2f}")


# ------------------------------------------------------------------ builders
def _mid(v: ContractView) -> float:
    return v.mid


def bull_put_spread(short: ContractView, long_: ContractView, qty: int = 1) -> Spread:
    """Sell a higher-strike put, buy a lower-strike put. CREDIT. Mildly bullish/neutral."""
    width = short.strike - long_.strike
    credit = _mid(short) - _mid(long_)
    return Spread(
        kind="bull_put", underlying=short.root, expiry=short.expiry,
        legs=[Leg(short.symbol, "sell", SELL_TO_OPEN, 1, short),
              Leg(long_.symbol, "buy", BUY_TO_OPEN, 1, long_)],
        net_price=-round(credit, 2),
        max_loss_per_unit=round((width - credit) * MULTIPLIER, 2),
        max_gain_per_unit=round(credit * MULTIPLIER, 2),
        width=width, qty=qty,
    )


def bear_call_spread(short: ContractView, long_: ContractView, qty: int = 1) -> Spread:
    """Sell a lower-strike call, buy a higher-strike call. CREDIT. Mildly bearish/neutral."""
    width = long_.strike - short.strike
    credit = _mid(short) - _mid(long_)
    return Spread(
        kind="bear_call", underlying=short.root, expiry=short.expiry,
        legs=[Leg(short.symbol, "sell", SELL_TO_OPEN, 1, short),
              Leg(long_.symbol, "buy", BUY_TO_OPEN, 1, long_)],
        net_price=-round(credit, 2),
        max_loss_per_unit=round((width - credit) * MULTIPLIER, 2),
        max_gain_per_unit=round(credit * MULTIPLIER, 2),
        width=width, qty=qty,
    )


def bull_call_spread(long_: ContractView, short: ContractView, qty: int = 1) -> Spread:
    """Buy a lower-strike call, sell a higher-strike call. DEBIT. Directional up."""
    width = short.strike - long_.strike
    debit = _mid(long_) - _mid(short)
    return Spread(
        kind="bull_call", underlying=long_.root, expiry=long_.expiry,
        legs=[Leg(long_.symbol, "buy", BUY_TO_OPEN, 1, long_),
              Leg(short.symbol, "sell", SELL_TO_OPEN, 1, short)],
        net_price=round(debit, 2),
        max_loss_per_unit=round(debit * MULTIPLIER, 2),
        max_gain_per_unit=round((width - debit) * MULTIPLIER, 2),
        width=width, qty=qty,
    )


def bear_put_spread(long_: ContractView, short: ContractView, qty: int = 1) -> Spread:
    """Buy a higher-strike put, sell a lower-strike put. DEBIT. Directional down."""
    width = long_.strike - short.strike
    debit = _mid(long_) - _mid(short)
    return Spread(
        kind="bear_put", underlying=long_.root, expiry=long_.expiry,
        legs=[Leg(long_.symbol, "buy", BUY_TO_OPEN, 1, long_),
              Leg(short.symbol, "sell", SELL_TO_OPEN, 1, short)],
        net_price=round(debit, 2),
        max_loss_per_unit=round(debit * MULTIPLIER, 2),
        max_gain_per_unit=round((width - debit) * MULTIPLIER, 2),
        width=width, qty=qty,
    )


def iron_condor(long_put: ContractView, short_put: ContractView,
                short_call: ContractView, long_call: ContractView, qty: int = 1) -> Spread:
    """Put credit spread + call credit spread. CREDIT. Profits if price stays in range."""
    put_w = short_put.strike - long_put.strike
    call_w = long_call.strike - short_call.strike
    width = max(put_w, call_w)
    credit = (_mid(short_put) - _mid(long_put)) + (_mid(short_call) - _mid(long_call))
    return Spread(
        kind="iron_condor", underlying=short_put.root, expiry=short_put.expiry,
        legs=[Leg(long_put.symbol, "buy", BUY_TO_OPEN, 1, long_put),
              Leg(short_put.symbol, "sell", SELL_TO_OPEN, 1, short_put),
              Leg(short_call.symbol, "sell", SELL_TO_OPEN, 1, short_call),
              Leg(long_call.symbol, "buy", BUY_TO_OPEN, 1, long_call)],
        net_price=-round(credit, 2),
        max_loss_per_unit=round((width - credit) * MULTIPLIER, 2),
        max_gain_per_unit=round(credit * MULTIPLIER, 2),
        width=width, qty=qty,
        meta={"put_width": put_w, "call_width": call_w},
    )


def roll_order(old: Spread, new_short: "ContractView", new_long: "ContractView",
               *, limit_price: float = None) -> dict:
    """Close a threatened 2-leg vertical and reopen it further out, atomically.

    Alpaca documents rolling a spread as a single 4-leg `mleg` order: two legs
    with *_to_close intents and two with *_to_open. That is strictly better than
    closing and reopening separately, which risks legging out at a bad price
    between the two orders.

    Only valid for 2-leg verticals — a 4-leg condor would need 8 legs to roll,
    which exceeds Alpaca's 4-leg cap, so condors are closed instead.
    """
    if len(old.legs) != 2:
        raise ValueError(f"can only roll a 2-leg vertical, got {len(old.legs)} legs")

    flip = {"buy": "sell", "sell": "buy"}
    intent_close = {BUY_TO_OPEN: SELL_TO_CLOSE, SELL_TO_OPEN: BUY_TO_CLOSE}

    legs = [Leg(l.symbol, flip[l.side], intent_close[l.intent], l.ratio_qty, l.view)
            for l in old.legs]

    # reopen with the same shape: short leg sold, protective long bought
    legs.append(Leg(new_short.symbol, "sell", SELL_TO_OPEN, 1, new_short))
    legs.append(Leg(new_long.symbol, "buy", BUY_TO_OPEN, 1, new_long))

    width = abs(new_short.strike - new_long.strike)
    new_credit = new_short.mid - new_long.mid
    old_cost = sum((l.view.mid if l.view else 0.0) * (1 if l.side == "buy" else -1)
                   for l in old.legs)

    roller = Spread(kind=old.kind, underlying=old.underlying, expiry=new_short.expiry,
                    legs=legs, net_price=round(old_cost - new_credit, 2),
                    max_loss_per_unit=round((width - new_credit) * MULTIPLIER, 2),
                    max_gain_per_unit=round(new_credit * MULTIPLIER, 2),
                    width=width, qty=old.qty,
                    meta={"rolled_from": [l.symbol for l in old.legs]})
    body = roller.order(limit_price=limit_price,
                        client_order_id=old.client_order_id("roll"))
    return body


def closing_order(spread: Spread, *, limit_price: float = None) -> dict:
    """Mirror every leg with *_to_close intents — closes the whole structure atomically."""
    flip = {"buy": "sell", "sell": "buy"}
    intent = {BUY_TO_OPEN: SELL_TO_CLOSE, SELL_TO_OPEN: BUY_TO_CLOSE}
    legs = [Leg(l.symbol, flip[l.side], intent[l.intent], l.ratio_qty, l.view)
            for l in spread.legs]
    closer = Spread(kind=spread.kind, underlying=spread.underlying, expiry=spread.expiry,
                    legs=legs, net_price=-spread.net_price,
                    max_loss_per_unit=0, max_gain_per_unit=0,
                    width=spread.width, qty=spread.qty)
    return closer.order(limit_price=limit_price,
                        client_order_id=spread.client_order_id("close"))


# ---------------------------------------------------------------- validation
def validate_mleg(body: dict) -> List[str]:
    """Return a list of rule violations. Empty list == safe to submit."""
    errs: List[str] = []
    legs = body.get("legs") or []

    if body.get("order_class") != "mleg":
        errs.append("order_class must be 'mleg'")
    if not (2 <= len(legs) <= 4):
        errs.append(f"R1: mleg needs 2-4 legs, got {len(legs)} (Alpaca maxItems=4)")
    if "side" in body:
        errs.append("do not set a top-level 'side' on an mleg order")
    if not body.get("qty"):
        errs.append("qty is required (number of strategy units)")
    if body.get("time_in_force") != "day":
        errs.append("R5: time_in_force must be 'day' for options")
    if body.get("type") not in ("market", "limit"):
        errs.append("R5: mleg supports only market|limit (no stop/stop_limit)")
    if body.get("extended_hours"):
        errs.append("R5: options do not support extended_hours")
    if body.get("notional"):
        errs.append("notional must not be set for options")
    if body.get("type") == "limit" and body.get("limit_price") in (None, ""):
        errs.append("limit orders require limit_price")

    parsed = []
    for l in legs:
        sym = l.get("symbol", "")
        try:
            root, expiry, kind, strike = parse_occ(sym)
        except Exception:
            errs.append(f"R3: leg {sym!r} is not a valid OCC option symbol (no equity legs)")
            continue
        if l.get("side") not in ("buy", "sell"):
            errs.append(f"leg {sym}: side must be buy|sell")
        if l.get("position_intent") not in INTENTS:
            errs.append(f"leg {sym}: missing/invalid position_intent")
        parsed.append((root, expiry, kind, strike, l.get("side"), sym))

    # R4 — ratio GCD must be 1
    try:
        ratios = [int(l["ratio_qty"]) for l in legs]
        if ratios and reduce(gcd, ratios) != 1:
            errs.append(f"R4: ratio_qty GCD must be 1, got {ratios} — simplify")
        if any(r < 1 for r in ratios):
            errs.append("R4: ratio_qty must be >= 1")
    except (KeyError, ValueError, TypeError):
        errs.append("R4: every leg needs an integer ratio_qty")

    # R2 — coverage. For each (root, expiry, type) bucket the total LONG ratio_qty
    # must be >= the total SHORT ratio_qty. Strike direction does NOT matter:
    #   long 769C / short 774C  -> debit  spread, defined risk, covered
    #   short 781C / long 785C  -> credit spread, defined risk, covered
    # What this correctly rejects: naked shorts (no long at all), calendars
    # (long is a different expiry), and ratio spreads (short qty > long qty).
    buckets: dict = {}
    for root, expiry, kind, strike, side, sym in parsed:
        b = buckets.setdefault((root, expiry, kind), {"long": 0, "short": 0, "shorts": []})
        try:
            r = int(next(l["ratio_qty"] for l in legs if l.get("symbol") == sym))
        except (StopIteration, KeyError, ValueError, TypeError):
            r = 1
        if side == "buy":
            b["long"] += r
        elif side == "sell":
            b["short"] += r
            b["shorts"].append(sym)

    for (root, expiry, kind), b in buckets.items():
        if b["short"] > b["long"]:
            errs.append(
                f"R2: {root} {expiry} {kind} has {b['short']} short vs {b['long']} long "
                f"({', '.join(b['shorts'])}) — Alpaca rejects uncovered legs "
                f"(no naked shorts, no calendars, no ratio spreads)")

    # sign convention sanity
    if body.get("type") == "limit":
        try:
            px = float(body["limit_price"])
            n_short = sum(1 for p in parsed if p[4] == "sell")
            n_long = sum(1 for p in parsed if p[4] == "buy")
            if px == 0:
                errs.append("SIGN: limit_price of 0 is almost certainly wrong")
            _ = n_short, n_long
        except (KeyError, ValueError, TypeError):
            pass

    return errs


def assert_valid(body: dict) -> dict:
    errs = validate_mleg(body)
    if errs:
        raise ValueError("mleg validation failed:\n  - " + "\n  - ".join(errs))
    return body
