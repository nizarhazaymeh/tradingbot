"""SMA crossover trading bot with risk management — Binance or Alpaca.

Run:  python bot.py

Broker (set BROKER in .env):
  BROKER=binance  -> Binance Spot crypto (default)
  BROKER=alpaca   -> Alpaca US stocks + crypto (paper or live)

Modes (set in .env):
  SIGNAL_ONLY=true   -> read market data, compute signals, send notifications,
                        place NO orders. (default, safest)
  SIGNAL_ONLY=false  -> can place real orders, gated by:
       ENABLE_TRADING=false -> paper mode (logs only, no orders)
       USE_TESTNET=true     -> Binance Testnet (fake money)
       ALPACA_PAPER=true    -> Alpaca paper account (fake money)

Risk management: every open position has a stop-loss and take-profit. When the
price crosses either threshold the bot exits (or, in signal-only mode, notifies).
"""
import json
import logging
import os
import time
from typing import Optional

import config
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
    return {"in_position": False, "entry_price": None}


def load_state() -> dict:
    """State is keyed by symbol: {symbol: {in_position, entry_price}}."""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f:
                data = json.load(f)
            # Migrate the old single-symbol format ({in_position, entry_price}).
            if "in_position" in data:
                return {config.SYMBOL: data}
            return data
        except Exception:
            pass
    return {}


def save_state(state: dict) -> None:
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f)
    except Exception as e:
        log.error("Could not save state: %s", e)


# --------------------------------------------------------------------------- #
# Risk management
# --------------------------------------------------------------------------- #
def risk_exit_reason(entry: float, price: float) -> Optional[str]:
    """Return 'stop-loss' / 'take-profit' if a risk threshold is hit, else None."""
    if not entry:
        return None
    if config.STOP_LOSS_PCT > 0 and price <= entry * (1 - config.STOP_LOSS_PCT):
        return "stop-loss"
    if config.TAKE_PROFIT_PCT > 0 and price >= entry * (1 + config.TAKE_PROFIT_PCT):
        return "take-profit"
    return None


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


def real_money() -> bool:
    if config.SIGNAL_ONLY or not config.ENABLE_TRADING:
        return False
    return not (config.ALPACA_PAPER if config.BROKER == "alpaca" else config.USE_TESTNET)


# --------------------------------------------------------------------------- #
# Main loop
# --------------------------------------------------------------------------- #
def run():
    config.validate()
    mode = describe_mode()
    broker = get_broker()
    symbols = broker.prepare(config.SYMBOLS)

    log.info("=" * 64)
    log.info("SMA bot starting | Broker: %s | Mode: %s", broker.name, mode)
    log.info(
        "Symbols=%s Interval=%s SMA=%d/%d Spend=%s | SL=%.1f%% TP=%.1f%%",
        ",".join(symbols), config.INTERVAL, config.FAST_SMA, config.SLOW_SMA,
        config.TRADE_QUOTE_AMOUNT, config.STOP_LOSS_PCT * 100,
        config.TAKE_PROFIT_PCT * 100,
    )
    if real_money():
        log.warning("!! LIVE TRADING WITH REAL MONEY IS ACTIVE !!")
    log.info("=" * 64)

    state = load_state()
    for sym in symbols:
        state.setdefault(sym, _fresh_symbol_state())
    needed = max(config.SLOW_SMA, config.TREND_SMA) + 2

    while True:
        for sym in symbols:
            try:
                ss = state[sym]
                closes = broker.closes(sym, config.INTERVAL, needed)
                if len(closes) < 2:
                    log.warning("[%s] Not enough bars returned yet (%d).", sym, len(closes))
                    continue
                price = closes[-1]
                signal = generate_signal(
                    closes, config.FAST_SMA, config.SLOW_SMA,
                    trend=config.TREND_SMA, buffer=config.CROSS_BUFFER,
                )

                # Decide whether to exit (risk) or enter/exit (signal).
                exit_reason = None
                if ss["in_position"]:
                    exit_reason = risk_exit_reason(ss["entry_price"], price)
                    if not exit_reason and signal == "SELL":
                        exit_reason = "sell-signal"

                log.info(
                    "%-9s price=%.4f signal=%s in_position=%s entry=%s%s",
                    sym, price, signal, ss["in_position"], ss["entry_price"],
                    f" exit={exit_reason}" if exit_reason else "",
                )

                # ----- ENTRY -----
                if signal == "BUY" and not ss["in_position"]:
                    handle_entry(broker, sym, price, ss)

                # ----- EXIT -----
                elif exit_reason and ss["in_position"]:
                    handle_exit(broker, sym, price, ss, exit_reason)

                save_state(state)

            except broker.ERRORS as e:
                log.error("[%s] %s API error: %s", sym, broker.name, e)
            except Exception as e:
                log.exception("[%s] Unexpected error: %s", sym, e)

        time.sleep(config.POLL_SECONDS)


def handle_entry(broker, symbol, price, state):
    msg = (
        f"📈 BUY signal on {symbol} @ {price:.4f}\n"
        f"Stop-loss: {price * (1 - config.STOP_LOSS_PCT):.4f} "
        f"| Take-profit: {price * (1 + config.TAKE_PROFIT_PCT):.4f}"
    )

    if config.SIGNAL_ONLY:
        notify(msg, subject=f"BUY signal — {symbol}")
        state.update(in_position=True, entry_price=price)
        return

    if not config.ENABLE_TRADING:
        log.info("[PAPER] Would BUY %s of %s.", config.TRADE_QUOTE_AMOUNT, symbol)
        notify(msg + "\n(paper mode — no order placed)", subject=f"BUY signal — {symbol}")
        state.update(in_position=True, entry_price=price)
        return

    # Orders can't fill outside US market hours (crypto is always open).
    if not broker.market_open(symbol):
        log.info("[%s] BUY signal but the market is closed — skipping entry.", symbol)
        return
    if broker.cash(symbol) < config.TRADE_QUOTE_AMOUNT:
        log.warning("[%s] BUY signal but insufficient buying power.", symbol)
        return

    fill = broker.buy(symbol, config.TRADE_QUOTE_AMOUNT)
    entry = fill or price
    notify(msg + f"\n✅ Bought @ {entry:.4f}", subject=f"BUY executed — {symbol}")
    state.update(in_position=True, entry_price=entry)


def handle_exit(broker, symbol, price, state, reason):
    entry = state["entry_price"] or price
    pnl_pct = (price - entry) / entry * 100 if entry else 0.0
    msg = (
        f"📉 EXIT ({reason}) on {symbol} @ {price:.4f}\n"
        f"Entry: {entry:.4f} | P/L: {pnl_pct:+.2f}%"
    )

    if config.SIGNAL_ONLY:
        notify(msg, subject=f"EXIT ({reason}) — {symbol}")
        state.update(in_position=False, entry_price=None)
        return

    if not config.ENABLE_TRADING:
        log.info("[PAPER] Would SELL %s.", symbol)
        notify(msg + "\n(paper mode — no order placed)", subject=f"EXIT ({reason}) — {symbol}")
        state.update(in_position=False, entry_price=None)
        return

    if not broker.market_open(symbol):
        log.warning("[%s] EXIT signal but the market is closed — will retry.", symbol)
        return

    qty = broker.sell(symbol)
    if qty:
        notify(msg + f"\n✅ Sold {qty}", subject=f"EXIT executed ({reason}) — {symbol}")
    state.update(in_position=False, entry_price=None)


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        log.info("Stopped by user. Bye.")
