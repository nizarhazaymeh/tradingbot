"""SMA crossover trading bot with risk management — Alpaca (default) or Binance.

Run:  python bot.py

Broker (set BROKER in .env):
  BROKER=alpaca   -> Alpaca US stocks + crypto, paper or live (default)
  BROKER=binance  -> Binance Spot crypto

Modes (set in .env), safest first:
  SIGNAL_ONLY=true      -> compute signals + notify, place NO orders (default)
  ENABLE_TRADING=false  -> paper: track simulated positions, send no orders
  ALPACA_PAPER=true     -> real orders against Alpaca's paper account (fake money)
  ALPACA_PAPER=false    -> real orders with real money

Protection on an open position, in order of preference:
  bracket -> broker-side stop-loss + take-profit, live between polls and even
             if this process dies. Alpaca stocks, whole shares only.
  poll    -> this loop checks stop-loss/take-profit every POLL_SECONDS.
             The fallback for crypto and fractional share sizes.
"""
import json
import logging
import os
import time
from typing import Optional

import config
import risk
import tradelog
from broker import get_broker
from notifier import notify
from strategy import generate_signal

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("bot")

STATE_FILE = os.path.join(os.path.dirname(__file__), "state.json")


# --------------------------------------------------------------------------- #
# Position state (persisted so a restart doesn't forget the entry price)
# --------------------------------------------------------------------------- #
def _fresh_symbol_state() -> dict:
    return {"in_position": False, "entry_price": None, "qty": 0.0, "protection": "poll"}


def load_state() -> dict:
    """State is keyed by symbol: {symbol: {in_position, entry_price, qty, protection}}."""
    data = {}
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f:
                data = json.load(f)
            # Migrate the old single-symbol format ({in_position, entry_price}).
            if "in_position" in data:
                data = {config.SYMBOL: data}
        except Exception:
            data = {}
    for sym, ss in data.items():
        merged = _fresh_symbol_state()
        merged.update(ss)
        data[sym] = merged
    return data


def save_state(state: dict) -> None:
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        log.error("Could not save state: %s", e)


# --------------------------------------------------------------------------- #
# Modes
# --------------------------------------------------------------------------- #
def live_trading() -> bool:
    """True when orders actually reach the broker."""
    return not config.SIGNAL_ONLY and config.ENABLE_TRADING


def real_money() -> bool:
    if not live_trading():
        return False
    return not (config.ALPACA_PAPER if config.BROKER == "alpaca" else config.USE_TESTNET)


def describe_mode() -> str:
    if config.SIGNAL_ONLY:
        return "SIGNAL-ONLY (no orders, notifications only)"
    if not config.ENABLE_TRADING:
        return "PAPER (no orders sent)"
    if config.BROKER == "alpaca":
        return ("LIVE on Alpaca PAPER account (fake money)" if config.ALPACA_PAPER
                else "LIVE on Alpaca REAL ACCOUNT (real money)")
    return ("LIVE on Binance TESTNET (fake money)" if config.USE_TESTNET
            else "LIVE on Binance REAL ACCOUNT (real money)")


# --------------------------------------------------------------------------- #
# Risk gates
# --------------------------------------------------------------------------- #
def risk_exit_reason(entry: float, price: float) -> Optional[str]:
    """'stop-loss' / 'take-profit' if a threshold is hit, else None."""
    if not entry:
        return None
    if config.STOP_LOSS_PCT > 0 and price <= entry * (1 - config.STOP_LOSS_PCT):
        return "stop-loss"
    if config.TAKE_PROFIT_PCT > 0 and price >= entry * (1 + config.TAKE_PROFIT_PCT):
        return "take-profit"
    return None


def entry_blocked(account: dict, open_count: int) -> Optional[str]:
    """Account-level reason to refuse a NEW position (exits are never blocked)."""
    return (
        risk.account_blocked(account)
        or risk.daily_loss_breached(account, config.MAX_DAILY_LOSS_PCT)
        or risk.pdt_blocked(account, config.ALLOW_PDT)
        or (f"already holding {open_count} positions "
            f"(MAX_OPEN_POSITIONS={config.MAX_OPEN_POSITIONS})"
            if open_count >= config.MAX_OPEN_POSITIONS else None)
    )


# --------------------------------------------------------------------------- #
# Broker reconciliation — the broker is the source of truth, not state.json
# --------------------------------------------------------------------------- #
def reconcile(broker, symbol, ss, positions, price):
    """Align local state with what the broker actually holds.

    Two drift cases matter: a bracket order firing (or a manual close) leaves us
    thinking we hold something we don't, and a partially-filled or manually
    opened position leaves us blind to real exposure.
    """
    pos = positions.get(symbol)
    held = pos and not broker.is_dust(symbol, pos["qty"], price)

    if held and not ss["in_position"]:
        entry = pos["avg_entry_price"] or price
        log.warning("[%s] Broker holds %.8f @ %.4f but local state was flat — "
                    "adopting the position.", symbol, pos["qty"], entry)
        ss.update(in_position=True, entry_price=entry, qty=pos["qty"],
                  protection="poll")
        return None

    if ss["in_position"] and not held:
        entry = ss["entry_price"] or price
        pnl = (price - entry) / entry * 100 if entry else 0.0
        why = "bracket order filled" if ss["protection"] == "bracket" else "closed at the broker"
        log.info("[%s] Position gone (%s) — recording exit @ %.4f (P/L %+.2f%%)",
                 symbol, why, price, pnl)
        tradelog.record(config.TRADE_LOG, symbol=symbol, action="EXIT", reason=why,
                        price=f"{price:.6f}", qty=f"{ss['qty']:.8f}",
                        pnl_pct=f"{pnl:+.4f}", mode=describe_mode(),
                        protection=ss["protection"])
        notify(f"📉 EXIT ({why}) on {symbol} @ {price:.4f}\n"
               f"Entry: {entry:.4f} | P/L: {pnl:+.2f}%",
               subject=f"EXIT ({why}) — {symbol}")
        ss.update(_fresh_symbol_state())
    return None


# --------------------------------------------------------------------------- #
# Main loop
# --------------------------------------------------------------------------- #
def run():
    config.validate()
    mode = describe_mode()
    broker = get_broker()
    symbols = broker.prepare(config.SYMBOLS)
    live = live_trading()

    log.info("=" * 68)
    log.info("SMA bot starting | Broker: %s | Mode: %s", broker.name, mode)
    log.info("Symbols=%s Interval=%s SMA=%d/%d | SL=%.1f%% TP=%.1f%%",
             ",".join(symbols), config.INTERVAL, config.FAST_SMA, config.SLOW_SMA,
             config.STOP_LOSS_PCT * 100, config.TAKE_PROFIT_PCT * 100)
    if config.RISK_PCT:
        log.info("Sizing: risk %.2f%% of equity per trade (cap %.0f%% of equity)",
                 config.RISK_PCT * 100, config.MAX_POSITION_PCT * 100)
    else:
        log.info("Sizing: fixed %s per trade", config.TRADE_QUOTE_AMOUNT)
    log.info("Rails: max daily loss %.1f%% | max %d open | brackets=%s | PDT guard=%s",
             config.MAX_DAILY_LOSS_PCT * 100, config.MAX_OPEN_POSITIONS,
             config.USE_BRACKET_ORDERS and broker.supports_brackets,
             not config.ALLOW_PDT)
    if real_money():
        log.warning("!! LIVE TRADING WITH REAL MONEY IS ACTIVE !!")
    log.info("=" * 68)

    state = load_state()
    for sym in symbols:
        state.setdefault(sym, _fresh_symbol_state())
    needed = max(config.SLOW_SMA, config.TREND_SMA) + 2
    halted = None

    while True:
        account, positions = {}, {}
        if live:
            try:
                account = broker.account()
                positions = broker.positions(symbols)
            except broker.ERRORS as e:
                log.error("Could not refresh account/positions: %s", e)
                time.sleep(config.POLL_SECONDS)
                continue

            block = entry_blocked(account, len(positions))
            if block and block != halted:
                log.warning("New entries paused — %s", block)
                notify(f"⛔ New entries paused: {block}", subject="Trading paused")
            elif halted and not block:
                log.info("Entry conditions cleared — trading resumed.")
            halted = block

        for sym in symbols:
            try:
                ss = state[sym]
                closes = broker.closes(sym, config.INTERVAL, needed)
                if len(closes) < 2:
                    log.warning("[%s] Not enough bars returned yet (%d).", sym, len(closes))
                    continue
                price = closes[-1]

                if live:
                    reconcile(broker, sym, ss, positions, price)

                signal = generate_signal(
                    closes, config.FAST_SMA, config.SLOW_SMA,
                    trend=config.TREND_SMA, buffer=config.CROSS_BUFFER,
                )

                # Broker-side brackets own the stop/target; polling them here
                # too would race the broker and double-exit.
                exit_reason = None
                if ss["in_position"]:
                    if ss["protection"] != "bracket":
                        exit_reason = risk_exit_reason(ss["entry_price"], price)
                    if not exit_reason and signal == "SELL":
                        exit_reason = "sell-signal"

                log.info("%-9s price=%.4f signal=%s pos=%s entry=%s prot=%s%s",
                         sym, price, signal, ss["in_position"], ss["entry_price"],
                         ss["protection"] if ss["in_position"] else "-",
                         f" exit={exit_reason}" if exit_reason else "")

                if signal == "BUY" and not ss["in_position"]:
                    if live and halted:
                        log.info("[%s] BUY signal ignored — %s", sym, halted)
                    else:
                        handle_entry(broker, sym, price, ss, account)
                elif exit_reason and ss["in_position"]:
                    handle_exit(broker, sym, price, ss, exit_reason)

                save_state(state)

            except broker.ERRORS as e:
                log.error("[%s] %s API error: %s", sym, broker.name, e)
            except Exception as e:
                log.exception("[%s] Unexpected error: %s", sym, e)

        time.sleep(config.POLL_SECONDS)


def handle_entry(broker, symbol, price, ss, account):
    stop_price = price * (1 - config.STOP_LOSS_PCT)
    target_price = price * (1 + config.TAKE_PROFIT_PCT)
    msg = (f"📈 BUY signal on {symbol} @ {price:.4f}\n"
           f"Stop-loss: {stop_price:.4f} | Take-profit: {target_price:.4f}")

    if not live_trading():
        tag = "signal-only" if config.SIGNAL_ONLY else "paper"
        if not config.SIGNAL_ONLY:
            log.info("[PAPER] Would BUY %s of %s.", config.TRADE_QUOTE_AMOUNT, symbol)
            msg += "\n(paper mode — no order placed)"
        notify(msg, subject=f"BUY signal — {symbol}")
        tradelog.record(config.TRADE_LOG, symbol=symbol, action="ENTRY", reason="sma-cross",
                        price=f"{price:.6f}", notional=config.TRADE_QUOTE_AMOUNT,
                        mode=tag, protection="poll")
        ss.update(in_position=True, entry_price=price,
                  qty=config.TRADE_QUOTE_AMOUNT / price if price else 0.0,
                  protection="poll")
        return

    # Orders can't fill outside US market hours (crypto is always open).
    if not broker.market_open(symbol):
        log.info("[%s] BUY signal but the market is closed — skipping entry.", symbol)
        return

    equity = float(account.get("equity") or 0)
    cash = float(account.get("cash") or 0)
    notional = risk.size_notional(
        equity=equity, cash=cash, stop_loss_pct=config.STOP_LOSS_PCT,
        risk_pct=config.RISK_PCT, fixed_amount=config.TRADE_QUOTE_AMOUNT,
        max_position_pct=config.MAX_POSITION_PCT,
    )
    if notional < 1:
        log.warning("[%s] BUY signal but sized notional is $%.2f — skipping "
                    "(cash $%.2f, equity $%.2f).", symbol, notional, cash, equity)
        return

    result = broker.buy(symbol, notional, price,
                        stop_price=stop_price, target_price=target_price)
    entry = result["fill"] or price
    prot = result["protection"]
    detail = ("broker-side stop/target attached" if prot == "bracket"
              else "bot-side stop/target (checked each poll)")
    notify(msg + f"\n✅ Bought {result['qty']:.6f} @ {entry:.4f} — {detail}",
           subject=f"BUY executed — {symbol}")
    tradelog.record(config.TRADE_LOG, symbol=symbol, action="ENTRY", reason="sma-cross",
                    price=f"{entry:.6f}", qty=f"{result['qty']:.8f}",
                    notional=f"{notional:.2f}", mode=describe_mode(), protection=prot)
    ss.update(in_position=True, entry_price=entry, qty=result["qty"], protection=prot)


def handle_exit(broker, symbol, price, ss, reason):
    entry = ss["entry_price"] or price
    pnl_pct = (price - entry) / entry * 100 if entry else 0.0
    msg = (f"📉 EXIT ({reason}) on {symbol} @ {price:.4f}\n"
           f"Entry: {entry:.4f} | P/L: {pnl_pct:+.2f}%")

    if not live_trading():
        tag = "signal-only" if config.SIGNAL_ONLY else "paper"
        if not config.SIGNAL_ONLY:
            log.info("[PAPER] Would SELL %s.", symbol)
            msg += "\n(paper mode — no order placed)"
        notify(msg, subject=f"EXIT ({reason}) — {symbol}")
        tradelog.record(config.TRADE_LOG, symbol=symbol, action="EXIT", reason=reason,
                        price=f"{price:.6f}", qty=f"{ss['qty']:.8f}",
                        pnl_pct=f"{pnl_pct:+.4f}", mode=tag, protection=ss["protection"])
        ss.update(_fresh_symbol_state())
        return

    if not broker.market_open(symbol):
        log.warning("[%s] EXIT signal but the market is closed — will retry.", symbol)
        return

    qty = broker.sell(symbol)
    if qty:
        notify(msg + f"\n✅ Sold {qty}", subject=f"EXIT executed ({reason}) — {symbol}")
        tradelog.record(config.TRADE_LOG, symbol=symbol, action="EXIT", reason=reason,
                        price=f"{price:.6f}", qty=f"{qty:.8f}",
                        pnl_pct=f"{pnl_pct:+.4f}", mode=describe_mode(),
                        protection=ss["protection"])
    ss.update(_fresh_symbol_state())


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        log.info("Stopped by user. Bye.")
