"""Risk controls: position sizing and account-level safety rails.

Kept separate from the strategy on purpose — `strategy.py` decides *whether*
to trade, this module decides *how much* and *whether we're allowed to*.
"""
import logging
from typing import Optional, Tuple

log = logging.getLogger("risk")

PDT_EQUITY_FLOOR = 25_000.0  # FINRA pattern-day-trader threshold
PDT_MAX_DAY_TRADES = 3       # per rolling 5 business days, under the floor


def _f(account: dict, key: str, default: float = 0.0) -> float:
    try:
        return float(account.get(key) or default)
    except (TypeError, ValueError):
        return default


# --------------------------------------------------------------------------- #
# Sizing
# --------------------------------------------------------------------------- #
def size_notional(
    equity: float,
    cash: float,
    stop_loss_pct: float,
    risk_pct: float,
    fixed_amount: float,
    max_position_pct: float,
) -> float:
    """How many dollars to put into one trade.

    With RISK_PCT set, size so that being stopped out costs exactly that
    fraction of equity:

        loss_at_stop = notional * stop_loss_pct  =  equity * risk_pct
        =>  notional = equity * risk_pct / stop_loss_pct

    So a 1% risk on a 2% stop puts 50% of equity to work — which is why the
    result is then capped by MAX_POSITION_PCT and by available cash.
    """
    if risk_pct > 0 and stop_loss_pct > 0:
        notional = equity * risk_pct / stop_loss_pct
    else:
        notional = fixed_amount

    cap = equity * max_position_pct
    notional = min(notional, cap, cash)
    return max(0.0, round(notional, 2))


def shares_for(notional: float, price: float) -> int:
    """Whole shares affordable at `price` (bracket orders can't be fractional)."""
    if price <= 0:
        return 0
    return int(notional // price)


# --------------------------------------------------------------------------- #
# Account-level rails
# --------------------------------------------------------------------------- #
def daily_pnl(account: dict) -> Tuple[float, float]:
    """(dollars, fraction) of P/L today, measured from the previous close.

    Alpaca's `last_equity` is equity at the last market close, which is exactly
    the baseline a daily-loss limit should measure against.
    """
    equity = _f(account, "equity")
    last = _f(account, "last_equity")
    if not last:
        return 0.0, 0.0
    delta = equity - last
    return delta, delta / last


def daily_loss_breached(account: dict, max_daily_loss_pct: float) -> Optional[str]:
    """Reason string if today's drawdown exceeds the limit, else None."""
    if not max_daily_loss_pct:
        return None
    dollars, frac = daily_pnl(account)
    if frac <= -abs(max_daily_loss_pct):
        return (f"daily loss limit hit: {frac * 100:+.2f}% (${dollars:,.2f}), "
                f"limit {max_daily_loss_pct * 100:.1f}%")
    return None


def account_blocked(account: dict) -> Optional[str]:
    """Reason string if the broker itself has restricted the account."""
    if account.get("trading_blocked"):
        return "account has trading_blocked=true at the broker"
    if account.get("account_blocked"):
        return "account is blocked at the broker"
    status = account.get("status")
    if status and status != "ACTIVE":
        return f"account status is {status}, not ACTIVE"
    return None


def pdt_blocked(account: dict, allow_pdt: bool) -> Optional[str]:
    """Reason string if opening a trade risks a pattern-day-trader violation.

    Under $25k equity, a 4th day trade in 5 business days flags the account and
    freezes it for 90 days. We stop at 3 unless ALLOW_PDT=true.
    """
    if allow_pdt:
        return None
    equity = _f(account, "equity")
    if equity >= PDT_EQUITY_FLOOR:
        return None
    count = int(_f(account, "daytrade_count"))
    if account.get("pattern_day_trader"):
        return (f"account is flagged as a pattern day trader with equity "
                f"${equity:,.2f} < ${PDT_EQUITY_FLOOR:,.0f}")
    if count >= PDT_MAX_DAY_TRADES:
        return (f"{count} day trades used in the last 5 sessions and equity "
                f"${equity:,.2f} < ${PDT_EQUITY_FLOOR:,.0f} — "
                f"another round trip today could flag PDT (set ALLOW_PDT=true to override)")
    return None
