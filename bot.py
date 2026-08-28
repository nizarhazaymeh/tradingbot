"""Binance Spot trading bot — SMA crossover with risk management.

Run:  python bot.py

Modes (set in .env):
  SIGNAL_ONLY=true   -> read PUBLIC data, compute signals, send notifications,
                        place NO orders. Works with no API keys. (default, safest)
  SIGNAL_ONLY=false  -> can place real orders, gated by:
       USE_TESTNET=true     -> Binance Testnet (fake money)
       ENABLE_TRADING=false -> paper mode (logs only, no orders)

Risk management: every open position has a stop-loss and take-profit. When the
price crosses either threshold the bot exits (or, in signal-only mode, notifies).
"""
import json
import logging
import os
import time
from decimal import Decimal
from typing import Optional

from binance.client import Client
from binance.exceptions import BinanceAPIException

import config
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
# Exchange helpers
# --------------------------------------------------------------------------- #
def make_client() -> Client:
    return Client(config.API_KEY, config.API_SECRET, testnet=config.USE_TESTNET)


def get_symbol_filters(client: Client, symbol: str) -> dict:
    info = client.get_symbol_info(symbol)
    if info is None:
        raise SystemExit(f"Symbol {symbol} not found on this exchange/endpoint.")
    filters = {f["filterType"]: f for f in info["filters"]}
    step = float(filters.get("LOT_SIZE", {}).get("stepSize", "0.00000001"))
    min_notional = float(
        filters.get("NOTIONAL", filters.get("MIN_NOTIONAL", {})).get("minNotional", "0")
    )
    return {
        "step": step,
        "min_notional": min_notional,
        "base": info["baseAsset"],
        "quote": info["quoteAsset"],
    }


def round_step(quantity: float, step: float) -> float:
    """Round a quantity DOWN to the exchange lot-size step (avoids float drift)."""
    if step == 0:
        return quantity
    q = Decimal(str(quantity))
    s = Decimal(str(step))
    return float((q // s) * s)


def get_balance(client: Client, asset: str) -> float:
    bal = client.get_asset_balance(asset=asset)
    return float(bal["free"]) if bal else 0.0


def fetch_closes(client: Client, symbol: str, interval: str, limit: int) -> list:
    """Closing prices for the last `limit` CLOSED candles (public endpoint)."""
    klines = client.get_klines(symbol=symbol, interval=interval, limit=limit + 1)
    closed = klines[:-1]  # drop the still-forming candle
    return [float(k[4]) for k in closed]


# --------------------------------------------------------------------------- #
# Order placement (only reached when SIGNAL_ONLY=false and trading enabled)
# --------------------------------------------------------------------------- #
def place_buy(client: Client, symbol: str, quote_amount: float) -> float:
    log.info("Placing MARKET BUY: spend %.8f quote on %s", quote_amount, symbol)
    order = client.order_market_buy(symbol=symbol, quoteOrderQty=quote_amount)
    return _fill_price(order, quote_amount)


def place_sell(client: Client, symbol: str, quantity: float):
    log.info("Placing MARKET SELL: %.8f of %s", quantity, symbol)
    return client.order_market_sell(symbol=symbol, quantity=quantity)


def _fill_price(order: dict, quote_amount: float) -> float:
    """Average fill price from a market order response."""
    fills = order.get("fills") or []
    qty = sum(float(f["qty"]) for f in fills)
    cost = sum(float(f["qty"]) * float(f["price"]) for f in fills)
    return cost / qty if qty else 0.0


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


# --------------------------------------------------------------------------- #
# Main loop
# --------------------------------------------------------------------------- #
def run():
    config.validate()

    if config.SIGNAL_ONLY:
        mode = "SIGNAL-ONLY (no orders, notifications only)"
    elif not config.ENABLE_TRADING:
        mode = "PAPER (no orders sent)"
    elif config.USE_TESTNET:
        mode = "LIVE on TESTNET (fake money)"
    else:
        mode = "LIVE on REAL ACCOUNT (real money)"

    log.info("=" * 64)
    log.info("Binance SMA bot starting | Mode: %s", mode)
    log.info(
        "Symbols=%s Interval=%s SMA=%d/%d Spend=%s | SL=%.1f%% TP=%.1f%%",
        ",".join(config.SYMBOLS), config.INTERVAL, config.FAST_SMA, config.SLOW_SMA,
        config.TRADE_QUOTE_AMOUNT, config.STOP_LOSS_PCT * 100,
        config.TAKE_PROFIT_PCT * 100,
    )
    if not config.SIGNAL_ONLY and config.ENABLE_TRADING and not config.USE_TESTNET:
        log.warning("!! LIVE TRADING WITH REAL MONEY IS ACTIVE !!")
    log.info("=" * 64)

    client = make_client()
    filters = {sym: get_symbol_filters(client, sym) for sym in config.SYMBOLS}
    state = load_state()
    for sym in config.SYMBOLS:
        state.setdefault(sym, _fresh_symbol_state())
    needed = max(config.SLOW_SMA, config.TREND_SMA) + 2

    # Startup is not a trade action -> log only, no email.
    log.info(
        "Bot started on %s (%s) — mode: %s",
        ", ".join(config.SYMBOLS), config.INTERVAL, mode,
    )

    while True:
        for sym in config.SYMBOLS:
            try:
                ss = state[sym]
                closes = fetch_closes(client, sym, config.INTERVAL, needed)
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
                    handle_entry(client, sym, filters[sym], price, ss)

                # ----- EXIT -----
                elif exit_reason and ss["in_position"]:
                    handle_exit(client, sym, filters[sym], price, ss, exit_reason)

                save_state(state)

            except BinanceAPIException as e:
                log.error("[%s] Binance API error: %s", sym, e)
            except Exception as e:
                log.exception("[%s] Unexpected error: %s", sym, e)

        time.sleep(config.POLL_SECONDS)


def handle_entry(client, symbol, filters, price, state):
    msg = (
        f"📈 BUY signal on {symbol} @ {price:.4f}\n"
        f"Stop-loss: {price * (1 - config.STOP_LOSS_PCT):.4f} "
        f"| Take-profit: {price * (1 + config.TAKE_PROFIT_PCT):.4f}"
    )

    if config.SIGNAL_ONLY:
        notify(msg, subject=f"BUY signal — {symbol}")
        state.update(in_position=True, entry_price=price)
        return

    quote_bal = get_balance(client, filters["quote"])
    if quote_bal < config.TRADE_QUOTE_AMOUNT:
        log.warning("[%s] BUY signal but insufficient %s balance.", symbol, filters["quote"])
        return
    if not config.ENABLE_TRADING:
        log.info("[PAPER] Would BUY %s of %s.", config.TRADE_QUOTE_AMOUNT, symbol)
        notify(msg + "\n(paper mode — no order placed)", subject=f"BUY signal — {symbol}")
        state.update(in_position=True, entry_price=price)
        return

    fill = place_buy(client, symbol, config.TRADE_QUOTE_AMOUNT)
    entry = fill or price
    notify(msg + f"\n✅ Bought @ {entry:.4f}", subject=f"BUY executed — {symbol}")
    state.update(in_position=True, entry_price=entry)


def handle_exit(client, symbol, filters, price, state, reason):
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

    base_bal = get_balance(client, filters["base"])
    qty = round_step(base_bal, filters["step"])
    if qty <= 0:
        log.warning("[%s] EXIT signal but quantity rounds to 0.", symbol)
        state.update(in_position=False, entry_price=None)
        return
    place_sell(client, symbol, qty)
    notify(msg + f"\n✅ Sold {qty}", subject=f"EXIT executed ({reason}) — {symbol}")
    state.update(in_position=False, entry_price=None)


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        log.info("Stopped by user. Bye.")
