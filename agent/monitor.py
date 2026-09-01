"""Position monitoring and exits.

Alpaca does NOT support bracket/OCO orders on options — so this loop *is* the
stop-loss. If it stops running, positions sit unprotected. It therefore:
  * runs every cycle, before any new proposal is considered
  * rebuilds its exit plan from SQLite on restart
  * treats expiry day as non-negotiable (auto-exercise would convert options into
    equity worth more than the account)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple

from . import config
from .options import ContractView
from .risk import (expiry_action, now_et, flatten_now as RK_flatten,
                   holding_days as RK_holding_days)

log = logging.getLogger(__name__)

HOLD = "hold"
CLOSE_LIMIT = "close_limit"
CLOSE_MARKET = "close_market"
ROLL = "roll"


@dataclass
class ExitDecision:
    action: str
    reason: str
    urgency: int = 0          # higher wins when several triggers fire
    detail: dict = None

    def __bool__(self) -> bool:
        return self.action != HOLD


def mark_to_market(legs: List[dict], snaps: Dict[str, dict], qty: int) -> Optional[float]:
    """Current net value of the structure, per unit, signed like entry_price.

    Positive = it would cost you to close (a debit structure retains value).
    We value the *close*: buy back shorts at the ask, sell longs at the bid.
    """
    total = 0.0
    for leg in legs:
        snap = snaps.get(leg["symbol"])
        q = (snap or {}).get("latestQuote") or {}
        bid, ask = float(q.get("bp") or 0), float(q.get("ap") or 0)
        if bid <= 0 or ask <= 0:
            return None
        if leg["side"] == "buy":       # we are long -> we'd sell at the bid
            total += bid
        else:                          # we are short -> we'd buy back at the ask
            total -= ask
    return round(total, 4)


def unrealized_pnl(position: dict, snaps: Dict[str, dict]) -> Optional[float]:
    """Dollar P&L on an open structure."""
    import json
    legs = json.loads(position["legs_json"])
    now = mark_to_market(legs, snaps, position["qty"])
    if now is None:
        return None
    entry = position["entry_price"]          # +debit / -credit per unit
    # Entry cash flow was -entry. Closing now returns +now. P&L = now - entry.
    return round((now - entry) * 100 * position["qty"], 2)


def exit_cost(legs: List[dict], snaps: Dict[str, dict], qty: int) -> Optional[float]:
    """Dollars given up crossing the spread once, to get out."""
    total = 0.0
    for leg in legs:
        q = (snaps.get(leg["symbol"]) or {}).get("latestQuote") or {}
        bid, ask = float(q.get("bp") or 0), float(q.get("ap") or 0)
        if bid <= 0 or ask <= 0:
            return None
        total += (ask - bid) / 2.0 * int(leg.get("ratio_qty") or 1)
    return total * 100 * max(qty, 1)


def harvest_edge(position: dict, legs: List[dict], snaps: Dict[str, dict],
                 spot: float, realized_vol: float,
                 days: float) -> Optional[Tuple[float, float, float, float]]:
    """How much the market overpays for the time value we are still holding.

    Returns (mark_dollars, fair_dollars, edge, cost) or None if unpriceable.

    `fair` is the structure valued at REALISED vol over the remaining hold: what
    the rest of its life is worth if the underlying keeps moving the way it has
    actually been moving. `mark` is what the market will pay for it right now.
    Their difference is the same variance risk premium the entry logic hunts,
    measured on a position we already own.

    Sign convention follows mark_to_market: positive mark = we are long premium.
    """
    from .expectancy import fair_value
    if spot <= 0 or not realized_vol or realized_vol <= 0 or days <= 0:
        return None
    qty = position["qty"]
    mark = mark_to_market(legs, snaps, qty)
    if mark is None:
        return None
    fair = fair_value(legs, spot, realized_vol, days, qty)
    cost = exit_cost(legs, snaps, qty)
    if fair is None or cost is None:
        return None
    return (mark * 100 * qty, fair, mark * 100 * qty - fair, cost)


def evaluate_exit(position: dict, snaps: Dict[str, dict],
                  views: Dict[str, ContractView] = None,
                  now: datetime = None,
                  context: Dict[str, dict] = None) -> ExitDecision:
    """Decide what to do with one open structure. Highest-urgency trigger wins."""
    import json
    now = now or now_et()
    views = views or {}
    context = context or {}
    expiry = date.fromisoformat(position["expiry"])
    dte = (expiry - now.date()).days

    # ---- 0. competition deadline: overrides everything --------------------
    fl = RK_flatten(now)
    if fl:
        return ExitDecision(CLOSE_MARKET, fl, urgency=200,
                            detail={"deadline": True, "dte": dte})

    # ---- 1. expiry day: non-negotiable, highest urgency -------------------
    ea = expiry_action(dte, now)
    if ea:
        return ExitDecision(CLOSE_MARKET if ea == "close_market" else CLOSE_LIMIT,
                            f"expiry day (DTE {dte}) — never hold into expiration",
                            urgency=100, detail={"dte": dte})

    pnl = unrealized_pnl(position, snaps)
    if pnl is None:
        return ExitDecision(HOLD, "cannot mark — one or more legs have no two-sided quote",
                            detail={"stale": True})

    max_gain = position["max_gain"] or 0.0
    max_loss = position["max_loss"] or 0.0
    is_credit = bool(position["is_credit"])

    # ---- 2. stop loss -----------------------------------------------------
    if is_credit:
        credit = abs(position["entry_price"]) * 100 * position["qty"]
        if credit > 0 and pnl <= -config.STOP_CREDIT_MULT * credit:
            return ExitDecision(CLOSE_MARKET,
                                f"stop: P&L ${pnl:,.0f} <= -{config.STOP_CREDIT_MULT:.0%} "
                                f"of ${credit:,.0f} credit", urgency=90,
                                detail={"pnl": pnl, "credit": credit})
    else:
        debit = abs(position["entry_price"]) * 100 * position["qty"]
        if debit > 0 and pnl <= -config.STOP_DEBIT_PCT * debit:
            return ExitDecision(CLOSE_MARKET,
                                f"stop: P&L ${pnl:,.0f} <= -{config.STOP_DEBIT_PCT:.0%} "
                                f"of ${debit:,.0f} debit", urgency=90,
                                detail={"pnl": pnl, "debit": debit})

    # ---- 3. take profit ---------------------------------------------------
    if is_credit:
        # A credit spread's max gain IS the credit, so a % of it is meaningful.
        if max_gain > 0 and pnl >= config.TAKE_PROFIT_CREDIT * max_gain:
            return ExitDecision(CLOSE_LIMIT,
                                f"take profit: ${pnl:,.0f} >= "
                                f"{config.TAKE_PROFIT_CREDIT:.0%} of ${max_gain:,.0f} "
                                f"max gain", urgency=70,
                                detail={"pnl": pnl, "max_gain": max_gain})
    else:
        # A debit spread's max gain is several multiples of its cost, so a % of
        # max gain demands a return that never arrives. Measure against what we
        # actually paid.
        paid = abs(position["entry_price"]) * 100 * position["qty"]
        target = config.TAKE_PROFIT_DEBIT_MULT * paid
        if paid > 0 and pnl >= target:
            return ExitDecision(CLOSE_LIMIT,
                                f"take profit: ${pnl:,.0f} >= "
                                f"{config.TAKE_PROFIT_DEBIT_MULT:.0%} of the "
                                f"${paid:,.0f} paid", urgency=70,
                                detail={"pnl": pnl, "paid": paid})

    legs = json.loads(position["legs_json"])

    # ---- 3b. decay harvest ------------------------------------------------
    # Only meaningful for long premium: for a short structure "the market
    # overpays" is the reason to KEEP it, and the credit take-profit above
    # already governs that side.
    if config.HARVEST_ENABLED and context:
        ctx = context.get(position["underlying"]) or {}
        h = harvest_edge(position, legs, snaps, ctx.get("spot") or 0.0,
                         ctx.get("realized_vol") or 0.0,
                         RK_holding_days(expiry, now))
        if h:
            mark, fair, edge, cost = h
            if (mark > 0 and edge >= config.HARVEST_MIN_EDGE
                    and edge >= config.HARVEST_EDGE_MULT * cost):
                return ExitDecision(
                    CLOSE_LIMIT,
                    f"harvest: market pays ${mark:,.0f} for time worth ${fair:,.0f} "
                    f"at realised vol — ${edge:,.0f} edge vs ${cost:,.0f} to exit",
                    urgency=65,
                    detail={"mark": mark, "fair": fair, "edge": edge, "cost": cost})

    # ---- 4. delta breach on a short leg -> roll ---------------------------
    breached = []
    for leg in legs:
        if leg["side"] != "sell":
            continue
        v = views.get(leg["symbol"])
        if v and abs(v.delta) > config.DELTA_BREACH:
            breached.append((leg["symbol"], round(abs(v.delta), 3)))
    if breached:
        return ExitDecision(ROLL,
                            f"short leg delta breach {breached} > {config.DELTA_BREACH}",
                            urgency=60, detail={"breached": breached})

    # ---- 5. time stop -----------------------------------------------------
    if dte <= (position["time_stop_dte"] or config.TIME_STOP_DTE):
        return ExitDecision(CLOSE_LIMIT, f"time stop at DTE {dte}", urgency=50,
                            detail={"dte": dte, "pnl": pnl})

    return ExitDecision(HOLD, f"holding: P&L ${pnl:,.0f}, DTE {dte}",
                        detail={"pnl": pnl, "dte": dte})


def reconcile(store, broker_positions: List[dict]) -> dict:
    """Compare our intent ledger against the broker. The broker is the truth.

    Returns orphans in both directions so the caller can act loudly rather than
    silently trading on a wrong picture.
    """
    import json
    held = {p["symbol"] for p in broker_positions if p.get("asset_class") == "us_option"}
    tracked_syms, tracked_by_sig = set(), {}
    for pos in store.open_positions():
        syms = {l["symbol"] for l in json.loads(pos["legs_json"])}
        tracked_by_sig[pos["signature"]] = syms
        tracked_syms |= syms

    # Classified on FULL coverage, not overlap. `syms & held` treated a structure
    # as live if any single leg matched, so a cancelled near-duplicate sharing two
    # legs with a real position read as real — on 31 Aug a cancelled SPY condor
    # sharing 775C/777C with a filled one was never flagged.
    ghost_sigs, partial_sigs = [], []
    for sig, syms in tracked_by_sig.items():
        hit = syms & held
        if not hit:
            ghost_sigs.append(sig)
        elif hit != syms:
            partial_sigs.append(sig)
    orphan_syms = sorted(held - tracked_syms)

    return {
        "broker_option_legs": len(held),
        "tracked_structures": len(tracked_by_sig),
        "ghosts": ghost_sigs,          # we think we hold it; broker holds no leg
        "partial": partial_sigs,       # some legs held, some not — never auto-acted on
        "orphans": orphan_syms,        # broker holds it; we have no exit plan
        "clean": not ghost_sigs and not partial_sigs and not orphan_syms,
    }
