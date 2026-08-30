"""Options layer: OCC symbology, defensive contract parsing, strike selection.

Two hard-won rules encoded here:
  1. A missing Greek means "unusable contract" — NEVER coerce it to 0.
     (Alpaca returns no Greeks for 0DTE, zero-bid, and deep-OTM contracts.)
  2. 0DTE is always rejected: Black-Scholes divides by days-to-expiry.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple

from . import config


# --------------------------------------------------------------- symbology
def occ(root: str, expiry: date, kind: str, strike: float) -> str:
    """Build an OCC option symbol.  SPY + 2026-09-04 + C + 650 -> SPY260904C00650000"""
    return f"{root.upper()}{expiry:%y%m%d}{kind.upper()[0]}{int(round(strike * 1000)):08d}"


def parse_occ(symbol: str) -> Tuple[str, date, str, float]:
    """Inverse of occ(). Returns (root, expiry, 'C'|'P', strike)."""
    strike = int(symbol[-8:]) / 1000.0
    kind = symbol[-9].upper()
    expiry = datetime.strptime(symbol[-15:-9], "%y%m%d").date()
    return symbol[:-15], expiry, kind, strike


def dte_of(symbol: str, today: date = None) -> int:
    return (parse_occ(symbol)[1] - (today or date.today())).days


# ------------------------------------------------------------- contract view
class Unusable(Exception):
    """Raised when a contract fails a data-quality check. Always a reject, never a zero."""


@dataclass
class ContractView:
    symbol: str
    root: str
    expiry: date
    kind: str            # 'C' | 'P'
    strike: float
    dte: int
    bid: float
    ask: float
    mid: float
    spread_pct: float
    delta: float
    gamma: float
    theta: float
    vega: float
    iv: float
    open_interest: Optional[int] = None

    @property
    def abs_delta(self) -> float:
        return abs(self.delta)


def view(symbol: str, snap: dict, *, today: date = None,
         open_interest: int = None,
         max_spread_pct: float = None,
         min_dte: int = None, max_dte: int = None) -> ContractView:
    """Parse one chain snapshot into a validated ContractView, or raise Unusable."""
    max_spread_pct = config.MAX_SPREAD_PCT if max_spread_pct is None else max_spread_pct
    min_dte = config.MIN_DTE if min_dte is None else min_dte
    max_dte = config.MAX_DTE if max_dte is None else max_dte

    root, expiry, kind, strike = parse_occ(symbol)
    dte = (expiry - (today or date.today())).days

    if dte < min_dte:
        raise Unusable(f"{symbol}: DTE {dte} < {min_dte} (0DTE has no Greeks)")
    if dte > max_dte:
        raise Unusable(f"{symbol}: DTE {dte} > {max_dte}")

    q = (snap or {}).get("latestQuote") or {}
    bid = float(q.get("bp") or 0.0)
    ask = float(q.get("ap") or 0.0)
    if bid <= 0 or ask <= 0:
        raise Unusable(f"{symbol}: one-sided quote (bid={bid} ask={ask})")
    if ask < bid:
        raise Unusable(f"{symbol}: crossed quote")

    mid = (bid + ask) / 2.0
    spread_abs = ask - bid
    spread_pct = spread_abs / mid
    # Cheap wings legitimately show wide PERCENTAGE spreads while costing pennies
    # in absolute terms, so either test passing is enough.
    if spread_pct > max_spread_pct and spread_abs > config.MAX_SPREAD_ABS:
        raise Unusable(f"{symbol}: spread {spread_pct:.1%} (${spread_abs:.2f}) "
                       f"> {max_spread_pct:.0%} and > ${config.MAX_SPREAD_ABS:.2f}")

    g = (snap or {}).get("greeks") or {}
    missing = [k for k in ("delta", "gamma", "theta", "vega") if g.get(k) is None]
    if missing:
        raise Unusable(f"{symbol}: missing Greeks {missing}")

    iv = (snap or {}).get("impliedVolatility")
    if iv is None or not (config.IV_MIN < float(iv) < config.IV_MAX):
        raise Unusable(f"{symbol}: implausible IV {iv!r}")

    if open_interest is not None and open_interest < config.MIN_OPEN_INTEREST:
        raise Unusable(f"{symbol}: open interest {open_interest} < {config.MIN_OPEN_INTEREST}")

    return ContractView(
        symbol=symbol, root=root, expiry=expiry, kind=kind, strike=strike, dte=dte,
        bid=bid, ask=ask, mid=mid, spread_pct=spread_pct,
        delta=float(g["delta"]), gamma=float(g["gamma"]),
        theta=float(g["theta"]), vega=float(g["vega"]),
        iv=float(iv), open_interest=open_interest,
    )


def usable_contracts(chain: Dict[str, dict], *, today: date = None,
                     oi_map: Dict[str, int] = None,
                     collect_rejects: list = None) -> List[ContractView]:
    """Filter a raw chain down to contracts we're willing to trade."""
    oi_map = oi_map or {}
    out = []
    for sym, snap in (chain or {}).items():
        try:
            out.append(view(sym, snap, today=today, open_interest=oi_map.get(sym)))
        except Unusable as e:
            if collect_rejects is not None:
                collect_rejects.append(str(e))
        except Exception as e:  # malformed symbol / payload
            if collect_rejects is not None:
                collect_rejects.append(f"{sym}: parse error {e}")
    return out


# --------------------------------------------------------- strike selection
def by_delta(views: List[ContractView], target: float, kind: str,
             expiry: date = None) -> Optional[ContractView]:
    """Pick the contract whose |delta| is closest to `target`."""
    pool = [v for v in views if v.kind == kind.upper()[0]]
    if expiry:
        pool = [v for v in pool if v.expiry == expiry]
    return min(pool, key=lambda v: abs(v.abs_delta - target), default=None)


def by_strike(views: List[ContractView], strike: float, kind: str,
              expiry: date = None) -> Optional[ContractView]:
    pool = [v for v in views if v.kind == kind.upper()[0]]
    if expiry:
        pool = [v for v in pool if v.expiry == expiry]
    return min(pool, key=lambda v: abs(v.strike - strike), default=None)


def wing(views: List[ContractView], short: ContractView, width: float) -> Optional[ContractView]:
    """The protective long leg `width` points further OTM than `short`."""
    target = short.strike + width if short.kind == "C" else short.strike - width
    return by_strike(views, target, short.kind, short.expiry)


def strike_ladder(views: List[ContractView], kind: str, expiry: date) -> List[float]:
    return sorted({v.strike for v in views if v.kind == kind.upper()[0] and v.expiry == expiry})


def typical_width(ladder: List[float]) -> float:
    """Most common gap between adjacent strikes — the natural spread width."""
    if len(ladder) < 2:
        return 5.0
    gaps = [round(b - a, 2) for a, b in zip(ladder, ladder[1:]) if b > a]
    return max(set(gaps), key=gaps.count) if gaps else 5.0


# ------------------------------------------------------------- math helpers
def expected_move(spot: float, iv: float, dte: int) -> float:
    """1-sigma expected move over `dte` calendar days. Free — needs only spot + IV."""
    return spot * iv * math.sqrt(max(dte, 1) / 365.0)


def atm_iv(views: List[ContractView], spot: float, expiry: date = None) -> Optional[float]:
    pool = [v for v in views if expiry is None or v.expiry == expiry]
    if not pool:
        return None
    nearest = min(pool, key=lambda v: abs(v.strike - spot))
    same = [v for v in pool if abs(v.strike - nearest.strike) < 1e-6]
    return sum(v.iv for v in same) / len(same)


def iv_rank(iv_now: float, history: List[float]) -> Optional[float]:
    if not history:
        return None
    lo, hi = min(history), max(history)
    return 0.5 if hi <= lo else max(0.0, min(1.0, (iv_now - lo) / (hi - lo)))
