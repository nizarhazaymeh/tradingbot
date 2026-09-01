"""Deterministic risk gates. No LLM touches anything in this file, by design.

Order of operations for every proposal:
    circuit_breakers()  ->  gate_spread()  ->  size_spread()
First failure rejects, and the failing gate is named in the audit log.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

from . import config
from .options import ContractView
from .spreads import Spread, validate_mleg

ET = ZoneInfo("America/New_York")


def now_et() -> datetime:
    return datetime.now(ET)


def _hhmm(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


@dataclass
class GateResult:
    passed: bool
    gate: str = ""
    reason: str = ""
    detail: dict = field(default_factory=dict)

    def __bool__(self) -> bool:
        return self.passed


PASS = GateResult(True)


def _fail(gate: str, reason: str, **detail) -> GateResult:
    return GateResult(False, gate, reason, detail)


# ----------------------------------------------------------- portfolio state
@dataclass
class Book:
    """What we currently have on, summarised for the gates."""
    equity: float
    last_equity: float
    options_buying_power: float
    open_positions: int = 0
    open_heat: float = 0.0                       # total max-loss at risk, dollars
    heat_by_underlying: Dict[str, float] = field(default_factory=dict)
    heat_by_expiry: Dict[str, float] = field(default_factory=dict)
    net_delta: float = 0.0
    net_theta: float = 0.0
    orders_last_hour: int = 0
    held_structures: set = field(default_factory=set)
    count_by_underlying: Dict[str, int] = field(default_factory=dict)
    short_strikes: Dict[str, set] = field(default_factory=dict)

    @classmethod
    def from_account(cls, account: dict, tracked: List[dict] = None) -> "Book":
        tracked = tracked or []
        b = cls(
            equity=float(account.get("equity") or 0),
            last_equity=float(account.get("last_equity") or account.get("equity") or 0),
            options_buying_power=float(account.get("options_buying_power") or 0),
            open_positions=len(tracked),
        )
        for t in tracked:
            loss = float(t.get("max_loss") or 0)
            b.open_heat += loss
            b.heat_by_underlying[t["underlying"]] = b.heat_by_underlying.get(t["underlying"], 0) + loss
            b.heat_by_expiry[t["expiry"]] = b.heat_by_expiry.get(t["expiry"], 0) + loss
            b.net_delta += float(t.get("net_delta") or 0)
            b.net_theta += float(t.get("net_theta") or 0)
            b.held_structures.add(t.get("signature", ""))
            u = t["underlying"]
            b.count_by_underlying[u] = b.count_by_underlying.get(u, 0) + 1
            for k in (t.get("short_strikes") or ()):
                b.short_strikes.setdefault(u, set()).add(k)
        return b


# --------------------------------------------------------- circuit breakers
def circuit_breakers(book: Book, *, halted_flag: bool = False) -> GateResult:
    """Account-level kill switches. Checked at the TOP of every cycle."""
    if halted_flag:
        return _fail("g_kill_switch", "HALTED file present — manual halt engaged")

    if book.last_equity > 0:
        daily = (book.equity - book.last_equity) / book.last_equity
        if daily <= -config.DAILY_DRAWDOWN_LIMIT:
            return _fail("g_daily_drawdown",
                         f"daily P&L {daily:.2%} <= -{config.DAILY_DRAWDOWN_LIMIT:.0%}",
                         daily_pct=daily)

    total = (book.equity - config.STARTING_EQUITY) / config.STARTING_EQUITY
    if total <= -config.TOTAL_DRAWDOWN_LIMIT:
        return _fail("g_total_drawdown",
                     f"total P&L {total:.2%} <= -{config.TOTAL_DRAWDOWN_LIMIT:.0%}",
                     total_pct=total)

    if book.orders_last_hour >= config.MAX_ORDERS_PER_HOUR:
        return _fail("g_order_rate",
                     f"{book.orders_last_hour} orders in the last hour "
                     f">= {config.MAX_ORDERS_PER_HOUR}")
    return PASS


# ----------------------------------------------------------------- crypto
def crypto_day_drawdown(equity: float, day_start_equity: Optional[float]) -> GateResult:
    """The daily drawdown breaker, for a market that has no daily close.

    circuit_breakers() compares equity against Alpaca's `last_equity`, which is
    the previous EQUITY-market close. For a 24/7 book that number is stale by up
    to three days across a weekend, and a stale baseline makes the breaker read
    a loss that already happened or miss one that is happening now.

    The crypto day boundary is UTC midnight — what exchanges settle on and what
    every funding calculation uses. `day_start_equity` comes from
    Store.equity_at(crypto.crypto_day_start()).

    No baseline means no opinion. Refusing to trade because the equity curve has
    not been recorded yet would halt a fresh install; the breaker simply does not
    fire until there is something to compare against.
    """
    if not day_start_equity or day_start_equity <= 0 or equity <= 0:
        return PASS
    daily = (equity - day_start_equity) / day_start_equity
    if daily <= -config.DAILY_DRAWDOWN_LIMIT:
        return _fail("g_crypto_day_drawdown",
                     f"crypto-day P&L {daily:.2%} since UTC midnight "
                     f"<= -{config.DAILY_DRAWDOWN_LIMIT:.0%}", daily_pct=daily)
    return PASS


def crypto_gates(*, equity: float, qty: float, risk: float, notional: float,
                 open_positions: int, open_risk: float, symbol: str,
                 held_symbols: set = None) -> GateResult:
    """Admission for a spot position. The notional cap is the important one.

    A vertical spread cannot lose more than its width no matter what happens
    overnight — the long wing is an arithmetic guarantee. Spot has no wing, so
    `risk` here is a PLAN that assumes the stop fills where it was placed, and
    crypto gaps through stops precisely when it matters.

    g_crypto_notional is what replaces the wing. It bounds the loss if the stop
    does not hold at all and the position goes to zero, which is the honest worst
    case for spot rather than a theoretical one. Every other gate here is
    ordinary book hygiene; that one is the reason the account still cannot be
    lost on a single trade.
    """
    if qty <= 0:
        return _fail("g_crypto_size", "position sizes to zero under the bounds")
    if symbol in (held_symbols or set()):
        return _fail("g_crypto_duplicate", f"already holding {symbol}")
    if open_positions >= config.CRYPTO_MAX_POSITIONS:
        return _fail("g_crypto_max_positions",
                     f"{open_positions} open >= {config.CRYPTO_MAX_POSITIONS}")
    if notional > equity * config.CRYPTO_MAX_NOTIONAL_PCT + 1e-6:
        return _fail("g_crypto_notional",
                     f"notional ${notional:,.0f} exceeds "
                     f"{config.CRYPTO_MAX_NOTIONAL_PCT:.1%} of ${equity:,.0f} — "
                     f"this is the bound that replaces a spread's long wing")
    if risk > equity * config.CRYPTO_RISK_PER_TRADE_PCT + 1e-6:
        return _fail("g_crypto_risk_per_trade",
                     f"planned risk ${risk:,.0f} exceeds "
                     f"{config.CRYPTO_RISK_PER_TRADE_PCT:.2%} of equity")
    if (open_risk + risk) > equity * config.CRYPTO_MAX_HEAT_PCT + 1e-6:
        return _fail("g_crypto_heat",
                     f"summed stop risk ${open_risk + risk:,.0f} exceeds "
                     f"{config.CRYPTO_MAX_HEAT_PCT:.2%} of equity")
    return PASS


# ------------------------------------------------------------- market timing
def market_gates(clock: dict, *, allow_new: bool = True) -> GateResult:
    """Whether this cycle may OPEN anything. Exits are managed regardless.

    allow_new=False previously fell through to PASS, so `run.py --no-new` did the
    opposite of its name: it permitted new positions AND skipped the near-close
    cutoff, because the cutoff was nested inside `if allow_new`. Observed live on
    31 Aug 2026 — a --no-new cycle opened a second SPY condor.
    """
    if not clock.get("is_open"):
        return _fail("g_market_open", f"market closed; next open {clock.get('next_open')}")
    if not allow_new:
        return _fail("g_no_new_requested", "new positions disabled for this cycle")
    now = now_et()
    cutoff = _hhmm(config.NO_NEW_AFTER_ET)
    if now.time() >= cutoff:
        return _fail("g_not_near_close",
                     f"past {config.NO_NEW_AFTER_ET} ET — no new positions")

    # The competition is judged at a fixed moment, which is not a natural exit
    # for any position. Stop opening once we are too close to it to manage a
    # trade to a sensible close.
    no_new, now_a = _aware(_iso(config.NO_NEW_AFTER)), _aware(now)
    if no_new and now_a and now_a >= no_new:
        return _fail("g_deadline_no_new",
                     f"past NO_NEW_AFTER {config.NO_NEW_AFTER} — too close to the "
                     f"competition deadline to open anything new")
    return PASS


def _iso(v: str):
    """Parse an ISO datetime from config; None if unset or malformed."""
    try:
        return datetime.fromisoformat(v)
    except (TypeError, ValueError):
        return None


def _aware(d) -> Optional[datetime]:
    """Normalise to an aware ET datetime, or None if it isn't a real datetime.

    Callers pass aware datetimes, naive ones (tests), and occasionally mocked
    clocks. Returning None lets the deadline checks skip cleanly rather than
    raising on a comparison.
    """
    if not isinstance(d, datetime):
        return None
    return d if d.tzinfo is not None else d.replace(tzinfo=ET)


def flatten_now(now: datetime = None) -> Optional[str]:
    """Past the flatten cutoff every position closes, regardless of P&L.

    Judges mark the account at a fixed time. An open, mid-move position makes the
    reported figure depend on where the market went after we stopped controlling
    it — and anything expiring after the deadline would never reach its own time
    stop. So the book is flattened first.
    """
    at = _iso(config.FLATTEN_AT)
    if at is None:
        return None
    now, at = _aware(now or now_et()), _aware(at)
    if now and at and now >= at:
        return (f"past FLATTEN_AT {config.FLATTEN_AT} — flattening the book "
                f"before the competition deadline")
    return None


# ------------------------------------------------------------ contract gates
def gate_contracts(spread: Spread, oi_map: Dict[str, int] = None) -> GateResult:
    """Per-leg quality. ContractView construction already enforced quote/Greeks/DTE."""
    oi_map = oi_map or {}
    for leg in spread.legs:
        v: Optional[ContractView] = leg.view
        if v is None:
            return _fail("g_greeks_present", f"{leg.symbol}: no contract view attached")
        if v.spread_pct > config.MAX_SPREAD_PCT and (v.ask - v.bid) > config.MAX_SPREAD_ABS:
            return _fail("g_spread_width",
                         f"{v.symbol}: bid/ask spread {v.spread_pct:.1%} "
                         f"(${v.ask - v.bid:.2f}) exceeds both limits")
        if not (config.MIN_DTE <= v.dte <= config.MAX_DTE):
            return _fail("g_dte_bounds", f"{v.symbol}: DTE {v.dte} outside "
                                         f"{config.MIN_DTE}-{config.MAX_DTE}")
        oi = oi_map.get(v.symbol, v.open_interest)
        if oi is not None:
            if oi < config.MIN_OPEN_INTEREST:
                return _fail("g_open_interest",
                             f"{v.symbol}: open interest {oi} < {config.MIN_OPEN_INTEREST}")
            if spread.qty > config.MAX_QTY_VS_OI * oi:
                return _fail("g_qty_vs_oi",
                             f"{v.symbol}: qty {spread.qty} > "
                             f"{config.MAX_QTY_VS_OI:.0%} of OI {oi}")
    return PASS


# -------------------------------------------------------------- structure
def gate_structure(spread: Spread) -> GateResult:
    body = spread.order()
    errs = validate_mleg(body)
    if errs:
        return _fail("g_mleg_valid", errs[0], all_errors=errs)

    if spread.max_loss_per_unit <= 0:
        return _fail("g_defined_risk", "structure has undefined or zero max loss")

    # sign convention: the price sign must match what the STRATEGY implies.
    # Verified live 2026-08-30: positive = debit, negative = credit.
    if spread.is_credit and spread.net_price >= 0:
        return _fail("g_sign_convention",
                     f"{spread.kind} is a CREDIT structure but limit_price is "
                     f"{spread.net_price:+.2f} — must be negative")
    if not spread.is_credit and spread.net_price <= 0:
        return _fail("g_sign_convention",
                     f"{spread.kind} is a DEBIT structure but limit_price is "
                     f"{spread.net_price:+.2f} — must be positive")

    # a credit wider than the spread width is impossible -> bad pricing data
    if spread.is_credit and abs(spread.net_price) >= spread.width:
        return _fail("g_pricing_sane",
                     f"credit ${abs(spread.net_price):.2f} >= width ${spread.width:.2f}")
    return PASS


# ---------------------------------------------------------------- portfolio
def gate_portfolio(spread: Spread, book: Book) -> GateResult:
    if book.open_positions >= config.MAX_OPEN_POSITIONS:
        return _fail("g_max_concurrent",
                     f"{book.open_positions} open >= {config.MAX_OPEN_POSITIONS}")

    sig = signature(spread)
    if sig in book.held_structures:
        return _fail("g_no_duplicate", f"already holding {sig}")

    # g_no_duplicate only catches an EXACT match, so nearly identical structures
    # at adjacent strikes slip through as separate "positions". That is one bet
    # taken N times, paying the spread N times.
    # A second structure must be genuinely different. Observed live 1 Sep: two SPY
    # condors opened with IDENTICAL short strikes [755, 773], and two QQQ condors
    # sharing [700]. That is one bet taken twice, paying the bid/ask twice, with
    # no added diversification — and the broker nets the overlapping legs.
    new_shorts = {round(l.view.strike, 2) for l in spread.legs
                  if l.side == "sell" and l.view is not None}
    existing = book.short_strikes.get(spread.underlying, set())
    clash = new_shorts & existing
    if clash:
        return _fail("g_distinct_strikes",
                     f"short strike(s) {sorted(clash)} already sold in "
                     f"{spread.underlying} — a duplicate bet, not diversification")

    held = book.count_by_underlying.get(spread.underlying, 0)
    if held >= config.MAX_POSITIONS_PER_UNDERLYING:
        return _fail("g_max_per_underlying",
                     f"already holding {held} position(s) in {spread.underlying}, "
                     f"cap {config.MAX_POSITIONS_PER_UNDERLYING} — adjacent strikes "
                     f"are the same bet, not diversification")

    cost = estimated_cost(spread)
    if cost > 0.5 * book.options_buying_power:
        return _fail("g_buying_power",
                     f"cost ${cost:,.0f} > 50% of options BP ${book.options_buying_power:,.0f}")

    # Portfolio-level directional exposure. Individual defined-risk spreads can
    # each be small yet all lean the same way; this caps the aggregate.
    projected = book.net_delta + spread.net_delta
    cap = config.MAX_PORTFOLIO_DELTA * (book.equity / 100_000.0)
    if abs(projected) > cap:
        return _fail("g_net_delta",
                     f"portfolio delta would be {projected:+.2f}, cap ±{cap:.2f} "
                     f"(current {book.net_delta:+.2f}, adding {spread.net_delta:+.2f})")

    # The book is paid by time decay, so a theta-NEGATIVE addition has to leave
    # enough carry behind it. Only such additions are policed: a theta-positive
    # structure always improves the book, and an absolute floor applied to every
    # trade would stop an empty book from ever opening its first position.
    if spread.net_theta < 0:
        theta_after = book.net_theta + spread.net_theta
        floor = config.MIN_PORTFOLIO_THETA * (book.equity / 100_000.0)
        if theta_after < floor:
            return _fail("g_portfolio_theta",
                         f"a theta-negative structure (${spread.net_theta:+.0f}/day) "
                         f"would leave portfolio theta at ${theta_after:+.0f}/day, "
                         f"below the ${floor:.0f} floor — the carry is what pays "
                         f"for the bid/ask")
    return PASS


def signature(spread: Spread) -> str:
    legs = "/".join(sorted(l.symbol for l in spread.legs))
    return f"{spread.kind}:{legs}"


def estimated_cost(spread: Spread) -> float:
    """Rough buying-power draw: max loss is the right proxy for defined-risk spreads."""
    return spread.total_max_loss()


# ------------------------------------------------------------------- sizing
def size_spread(spread: Spread, book: Book) -> GateResult:
    """Set spread.qty from the risk budget. Returns a failed gate if nothing fits."""
    per_unit = spread.max_loss_per_unit
    if per_unit <= 0:
        return _fail("g_sizing", "max loss per unit is zero/undefined")

    eq = book.equity
    und = spread.underlying
    exp = spread.expiry.isoformat()

    budgets = {
        "per_trade": config.RISK_PER_TRADE_PCT * eq,
        "portfolio_heat": config.PORTFOLIO_HEAT_PCT * eq - book.open_heat,
        "per_underlying": config.MAX_PER_UNDERLYING_PCT * eq - book.heat_by_underlying.get(und, 0.0),
        "per_expiry": config.MAX_PER_EXPIRY_PCT * eq - book.heat_by_expiry.get(exp, 0.0),
    }
    binding = min(budgets, key=budgets.get)
    budget = budgets[binding]

    if budget <= 0:
        return _fail("g_sizing", f"no risk budget left ({binding} exhausted)", **budgets)

    qty = math.floor(budget / per_unit)
    if qty < 1:
        return _fail("g_sizing",
                     f"one unit risks ${per_unit:,.0f} > {binding} budget ${budget:,.0f}",
                     per_unit=per_unit, budget=budget, binding=binding)

    spread.qty = qty
    return GateResult(True, "g_sizing", f"qty={qty} (bound by {binding})",
                      {"qty": qty, "binding": binding, "budget": budget,
                       "risk": qty * per_unit})


# ------------------------------------------------------------- full pipeline
def holding_days(expiry: date, now: datetime = None) -> float:
    """How long we will ACTUALLY hold, not how long the option lives.

    FLATTEN_AT closes the book before judging, so a position opened on 3 Sep with
    an 8 Sep expiry lives 5 days but is held for 1. It therefore captures roughly
    a fifth of the decay it was priced on, while paying 100% of the round-trip
    bid/ask — which does not scale with holding period. Trades opened late are
    EV-negative for that reason alone.
    """
    now_a = _aware(now or now_et())
    flat = _aware(_iso(config.FLATTEN_AT))
    end_by_expiry = _aware(datetime.combine(expiry, time(16, 0)))
    if now_a is None or end_by_expiry is None:
        return float(max((expiry - date.today()).days, 0))
    end = min(end_by_expiry, flat) if flat else end_by_expiry
    return max((end - now_a).total_seconds() / 86400.0, 0.0)


def gate_holding_period(spread: Spread, now: datetime = None) -> GateResult:
    """The carry earned over the ACTUAL hold must beat the round-trip spread.

    Without this the agent keeps opening structures in the final days whose
    modelled edge assumes holding to expiry — an edge the deadline will not let it
    collect.
    """
    from .expectancy import round_trip_cost

    days = holding_days(spread.expiry, now)
    if days <= 0:
        return _fail("g_holding_period", "no holding time left before the flatten")

    theta = spread.net_theta
    cost = round_trip_cost(spread) * max(spread.qty, 1)

    if theta <= 0:
        # A debit structure earns from direction, not carry, so the theta test does
        # not apply — but it still needs time for the move to arrive.
        if days < config.MIN_HOLDING_DAYS:
            return _fail("g_holding_period",
                         f"only {days:.1f} days before the flatten; a directional "
                         f"structure needs {config.MIN_HOLDING_DAYS:.1f}")
        return PASS

    expected = theta * days
    if expected < cost * config.HOLDING_COST_MULTIPLE:
        return _fail("g_holding_period",
                     f"carry over the real {days:.1f}-day hold is ${expected:,.0f}, "
                     f"under {config.HOLDING_COST_MULTIPLE:.1f}x the ${cost:,.0f} "
                     f"round-trip spread — the deadline closes this before the "
                     f"modelled edge is collected")
    return PASS


GATE_ORDER = ["g_structure", "g_contracts", "g_sizing", "g_portfolio"]


def evaluate(spread: Spread, book: Book, oi_map: Dict[str, int] = None) -> GateResult:
    """Run every gate in order. Mutates spread.qty on success."""
    for check in (gate_structure(spread),
                  gate_contracts(spread, oi_map),
                  gate_holding_period(spread)):
        if not check:
            return check

    sized = size_spread(spread, book)
    if not sized:
        return sized

    port = gate_portfolio(spread, book)
    if not port:
        return port

    return GateResult(True, "all", sized.reason, sized.detail)


# ------------------------------------------------------------- expiry policy
def expiry_action(dte: int, now: datetime = None) -> Optional[str]:
    """Never let a position expire. Returns 'close_limit' | 'close_market' | None."""
    if dte > 0:
        return None
    t = (now or now_et()).time()
    if t >= _hhmm(config.ESCALATE_CLOSE_AFTER_ET):
        return "close_market"
    if t >= _hhmm(config.FORCE_CLOSE_AFTER_ET):
        return "close_limit"
    return "close_limit"
