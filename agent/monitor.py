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
from .risk import expiry_action, now_et

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


def evaluate_exit(position: dict, snaps: Dict[str, dict],
                  views: Dict[str, ContractView] = None,
                  now: datetime = None) -> ExitDecision:
    """Decide what to do with one open structure. Highest-urgency trigger wins."""
    import json
    now = now or now_et()
    views = views or {}
    expiry = date.fromisoformat(position["expiry"])
    dte = (expiry - now.date()).days

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
    target_pct = config.TAKE_PROFIT_CREDIT if is_credit else config.TAKE_PROFIT_DEBIT
    if max_gain > 0 and pnl >= target_pct * max_gain:
        return ExitDecision(CLOSE_LIMIT,
                            f"take profit: ${pnl:,.0f} >= {target_pct:.0%} of "
                            f"${max_gain:,.0f} max gain", urgency=70,
                            detail={"pnl": pnl, "max_gain": max_gain})

    # ---- 4. delta breach on a short leg -> roll ---------------------------
    legs = json.loads(position["legs_json"])
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

    ghost_sigs = [sig for sig, syms in tracked_by_sig.items() if not (syms & held)]
    orphan_syms = sorted(held - tracked_syms)

    return {
        "broker_option_legs": len(held),
        "tracked_structures": len(tracked_by_sig),
        "ghosts": ghost_sigs,          # we think we hold it; broker disagrees
        "orphans": orphan_syms,        # broker holds it; we have no exit plan
        "clean": not ghost_sigs and not orphan_syms,
    }
