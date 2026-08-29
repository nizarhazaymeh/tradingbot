"""Multi-timeframe trading bot for Alpaca — US stocks, ETFs and crypto.

Run:  python bot.py

Each symbol carries its own timeframes, set in WATCHLIST:

    WATCHLIST=GLD@15m, FXE@1h:4h, FXB@1h:4h, UUP@1h:4h

    GLD@15m     gold on 15-minute bars, single timeframe
    FXE@1h:4h   euro: entries timed on 1h, trend bias taken from 4h

Modes (set in .env), safest first:
  SIGNAL_ONLY=true      -> compute signals + notify, place NO orders (default)
  ENABLE_TRADING=false  -> paper: track simulated positions, send no orders
  ALPACA_PAPER=true     -> real orders against Alpaca's paper account (fake money)
  ALPACA_PAPER=false    -> real orders with REAL money

Protection on an open position:
  bracket -> broker-side stop + target, live between polls and after a crash.
             Stocks and ETFs, whole shares only.
  poll    -> this loop checks the stop/target every POLL_SECONDS. Used for
             crypto and fractional sizes, and the only mode that can trail.
"""
import json
import logging
import os
import time
from typing import Optional

import config
import risk
import strategy
import tradelog
from broker import get_broker
from notifier import notify

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("bot")

STATE_FILE = os.path.join(os.path.dirname(__file__), "state.json")


# --------------------------------------------------------------------------- #
# Position state (persisted so a restart doesn't forget the entry or the stop)
# --------------------------------------------------------------------------- #
def _fresh_symbol_state() -> dict:
    return {"in_position": False, "entry_price": None, "qty": 0.0,
            "protection": "poll", "stop": None, "target": None}


def load_state() -> dict:
    data = {}
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f:
                data = json.load(f)
            if "in_position" in data:  # migrate the old single-symbol format
                data = {config.SYMBOL: data}
        except Exception:
            data = {}
    for sym, ss in list(data.items()):
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
    return not config.SIGNAL_ONLY and config.ENABLE_TRADING


def real_money() -> bool:
    return live_trading() and not config.ALPACA_PAPER


def describe_mode() -> str:
    if config.SIGNAL_ONLY:
        return "SIGNAL-ONLY (no orders, notifications only)"
    if not config.ENABLE_TRADING:
        return "PAPER (no orders sent)"
    return ("LIVE on Alpaca PAPER account (fake money)" if config.ALPACA_PAPER
            else "LIVE on Alpaca REAL ACCOUNT (real money)")


# --------------------------------------------------------------------------- #
# Risk gates
# --------------------------------------------------------------------------- #
def risk_exit_reason(ss: dict, price: float) -> Optional[str]:
    """Stop/target are absolute prices set at entry from ATR, not percentages."""
    if ss.get("stop") and price <= ss["stop"]:
        return "stop-loss"
    if ss.get("target") and price >= ss["target"]:
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
    pos = positions.get(symbol)
    held = pos and not broker.is_dust(symbol, pos["qty"], price)

    if held and not ss["in_position"]:
        entry = pos["avg_entry_price"] or price
        log.warning("[%s] Broker holds %.8f @ %.4f but local state was flat — "
                    "adopting the position.", symbol, pos["qty"], entry)
        ss.update(in_position=True, entry_price=entry, qty=pos["qty"],
                  protection="poll", stop=None, target=None)
        return

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


# --------------------------------------------------------------------------- #
# Main loop
# --------------------------------------------------------------------------- #
def run():
    config.validate()
    params = config.strategy_params()
    mode = describe_mode()
    broker = get_broker()
    live = live_trading()

    # prepare() may rewrite symbols (BTCUSDT -> BTC/USD); keep the watchlist aligned.
    resolved = broker.prepare([w["symbol"] for w in config.WATCHLIST])
    watch = [dict(w, symbol=s) for w, s in zip(config.WATCHLIST, resolved)]
    symbols = [w["symbol"] for w in watch]

    entry_bars = max(params.slow + 2, params.trend_ma,
                     params.atr_period * 2, params.adx_period * 3) + 5
    htf_bars_needed = max(params.htf_trend_ma + 5, 60)
    bars_per_tf = max(entry_bars, htf_bars_needed)

    # Which symbols need which timeframe — one batched request per timeframe.
    tf_groups = {}
    for w in watch:
        tf_groups.setdefault(w["entry_tf"], []).append(w["symbol"])
        if w["htf_tf"]:
            tf_groups.setdefault(w["htf_tf"], []).append(w["symbol"])
    tf_groups = {tf: sorted(set(s)) for tf, s in tf_groups.items()}

    log.info("=" * 72)
    log.info("Bot starting | Broker: %s | Mode: %s", broker.name, mode)
    for w in watch:
        log.info("  %-9s entry=%-5s trend=%-5s", w["symbol"], w["entry_tf"],
                 w["htf_tf"] or f'{params.trend_ma}{params.ma_type.upper()} (same tf)')
    log.info("Strategy: %s %d/%d | ADX>=%.0f | stop %.1fxATR(%d) | R:R 1:%.1f%s",
             params.ma_type.upper(), params.fast, params.slow, params.adx_min,
             params.atr_stop_mult, params.atr_period, params.reward_risk,
             " | trailing" if config.TRAIL_ATR else "")
    if config.RISK_PCT:
        log.info("Sizing: risk %.2f%% of equity per trade (cap %.0f%% of equity)",
                 config.RISK_PCT * 100, config.MAX_POSITION_PCT * 100)
    else:
        log.info("Sizing: fixed %s per trade", config.TRADE_QUOTE_AMOUNT)
    log.info("Rails: max daily loss %.1f%% | max %d open | brackets=%s | PDT guard=%s "
             "| no entries within %.0f min of the close",
             config.MAX_DAILY_LOSS_PCT * 100, config.MAX_OPEN_POSITIONS,
             config.USE_BRACKET_ORDERS and broker.supports_brackets,
             not config.ALLOW_PDT, config.MIN_MINUTES_TO_CLOSE)
    if real_money():
        log.warning("!! LIVE TRADING WITH REAL MONEY IS ACTIVE !!")
    log.info("=" * 72)

    state = load_state()
    for sym in symbols:
        state.setdefault(sym, _fresh_symbol_state())
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

        # One request per timeframe for the whole watchlist, not one per symbol:
        # 5 symbols x 2 timeframes is 2 requests instead of 10.
        cache = {}
        for tf, syms in tf_groups.items():
            try:
                cache[tf] = broker.history_many(syms, tf, bars_per_tf)
            except broker.ERRORS as e:
                log.error("Could not fetch %s bars: %s", tf, e)
                cache[tf] = {}

        for w in watch:
            sym = w["symbol"]
            try:
                ss = state[sym]
                bars = cache.get(w["entry_tf"], {}).get(sym) or []
                if len(bars) < 2:
                    log.warning("[%s] Not enough %s bars yet (%d).",
                                sym, w["entry_tf"], len(bars))
                    continue
                htf = cache.get(w["htf_tf"], {}).get(sym) if w["htf_tf"] else None
                price = bars[-1].c

                if live:
                    reconcile(broker, sym, ss, positions, price)

                d = strategy.analyze(bars, htf, params)

                # Broker-side brackets own the stop/target; polling them here
                # too would race the broker and double-exit.
                exit_reason = None
                if ss["in_position"]:
                    if ss["protection"] != "bracket":
                        if config.TRAIL_ATR:
                            new_stop = strategy.trail_stop(ss["stop"], price, d.atr, params)
                            if new_stop and new_stop != ss["stop"]:
                                log.info("[%s] Trailing stop %.4f -> %.4f",
                                         sym, ss["stop"] or 0.0, new_stop)
                                ss["stop"] = new_stop
                        exit_reason = risk_exit_reason(ss, price)
                    if not exit_reason and d.signal == "SELL":
                        exit_reason = "sell-signal"

                log.info("%-9s %-4s %.4f sig=%-4s adx=%s atr=%s pos=%s%s%s",
                         sym, w["entry_tf"], price, d.signal,
                         f"{d.adx:.0f}" if d.adx is not None else "--",
                         f"{d.atr:.4f}" if d.atr else "--",
                         ss["in_position"],
                         f" exit={exit_reason}" if exit_reason else "",
                         f" | held: {d.blocked_by}" if d.reasons and d.signal == "HOLD" else "")

                if d.signal == "BUY" and not ss["in_position"]:
                    if live and halted:
                        log.info("[%s] BUY signal ignored — %s", sym, halted)
                    else:
                        handle_entry(broker, sym, price, d, ss, account)
                elif exit_reason and ss["in_position"]:
                    handle_exit(broker, sym, price, ss, exit_reason)

                save_state(state)

            except broker.ERRORS as e:
                log.error("[%s] %s API error: %s", sym, broker.name, e)
            except Exception as e:
                log.exception("[%s] Unexpected error: %s", sym, e)

        time.sleep(config.POLL_SECONDS)


def handle_entry(broker, symbol, price, d, ss, account):
    stop, target = d.stop, d.target
    risk_pct = (price - stop) / price * 100 if stop else 0.0
    msg = (f"📈 BUY {symbol} @ {price:.4f}\n"
           f"Stop: {stop:.4f} (-{risk_pct:.2f}%) | Target: {target:.4f}\n"
           f"ADX {d.adx:.0f} | ATR {d.atr:.4f}" if stop and target else
           f"📈 BUY {symbol} @ {price:.4f}")

    if not live_trading():
        tag = "signal-only" if config.SIGNAL_ONLY else "paper"
        if not config.SIGNAL_ONLY:
            log.info("[PAPER] Would BUY %s of %s.", config.TRADE_QUOTE_AMOUNT, symbol)
            msg += "\n(paper mode — no order placed)"
        notify(msg, subject=f"BUY signal — {symbol}")
        tradelog.record(config.TRADE_LOG, symbol=symbol, action="ENTRY", reason="mtf-cross",
                        price=f"{price:.6f}", notional=config.TRADE_QUOTE_AMOUNT,
                        mode=tag, protection="poll")
        ss.update(in_position=True, entry_price=price,
                  qty=config.TRADE_QUOTE_AMOUNT / price if price else 0.0,
                  protection="poll", stop=stop, target=target)
        return

    if not broker.market_open(symbol):
        log.info("[%s] BUY signal but the market is closed — skipping entry.", symbol)
        return
    late = broker.entry_window_ok(symbol, config.MIN_MINUTES_TO_CLOSE)
    if late:
        log.info("[%s] BUY signal but %s — skipping entry.", symbol, late)
        return

    equity = float(account.get("equity") or 0)
    cash = float(account.get("cash") or 0)
    # Size against the ACTUAL stop distance, not a nominal percentage — that is
    # what makes "risk 1% of equity" mean the same thing on gold and on FXE.
    stop_distance_pct = ((price - stop) / price) if stop else config.STOP_LOSS_PCT
    notional = risk.size_notional(
        equity=equity, cash=cash, stop_loss_pct=stop_distance_pct,
        risk_pct=config.RISK_PCT, fixed_amount=config.TRADE_QUOTE_AMOUNT,
        max_position_pct=config.MAX_POSITION_PCT,
    )
    if notional < 1:
        log.warning("[%s] BUY signal but sized notional is $%.2f — skipping "
                    "(cash $%.2f, equity $%.2f).", symbol, notional, cash, equity)
        return

    result = broker.buy(symbol, notional, price, stop_price=stop, target_price=target)
    entry = result["fill"] or price
    prot = result["protection"]
    detail = ("broker-side stop/target attached" if prot == "bracket"
              else "bot-side stop/target (checked each poll)")
    notify(msg + f"\n✅ Bought {result['qty']:.6f} @ {entry:.4f} — {detail}",
           subject=f"BUY executed — {symbol}")
    tradelog.record(config.TRADE_LOG, symbol=symbol, action="ENTRY", reason="mtf-cross",
                    price=f"{entry:.6f}", qty=f"{result['qty']:.8f}",
                    notional=f"{notional:.2f}", mode=describe_mode(), protection=prot)
    ss.update(in_position=True, entry_price=entry, qty=result["qty"],
              protection=prot, stop=stop, target=target)


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
