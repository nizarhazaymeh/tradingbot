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
            "qty_initial": 0.0, "protection": "poll", "stop": None,
            "targets": [], "tps_hit": 0}


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
    """Only the stop closes the WHOLE position; targets scale out instead."""
    if ss.get("stop") and price <= ss["stop"]:
        return "stop-loss"
    return None


def next_target(ss: dict, price: float) -> Optional[dict]:
    """The lowest unhit target price has now reached, if any."""
    for t in ss.get("targets", []):
        if not t.get("hit") and price >= t["price"]:
            return t
    return None


def manage_position(broker, symbol, price, plan, ss, params) -> None:
    """Scale out through TP1/TP2/TP3, then tighten the stop behind them.

    Each target closes its own slice. After `breakeven_after` targets the stop
    moves to entry, so the rest of the trade cannot lose; after `trail_after` it
    ratchets up with ATR, so a strong move is not capped by the last target.
    """
    tgt = next_target(ss, price)
    if tgt:
        frac = tgt["fraction"]
        want = ss["qty_initial"] * frac
        sold = 0.0
        if live_trading():
            remaining_targets = [t for t in ss["targets"] if not t.get("hit")]
            if len(remaining_targets) == 1:      # last one closes the remainder
                sold = broker.sell(symbol)
            else:
                sold = broker.sell_qty(symbol, want)
        else:
            sold = want
        tgt["hit"] = True
        ss["tps_hit"] += 1
        ss["qty"] = max(0.0, ss["qty"] - (sold or want))

        entry = ss["entry_price"] or price
        pnl = (price - entry) / entry * 100 if entry else 0.0
        log.info("[%s] %s hit @ %.4f — closed %.0f%% (%.8f), P/L %+.2f%%",
                 symbol, tgt["label"], price, frac * 100, sold or want, pnl)
        tradelog.record(config.TRADE_LOG, symbol=symbol, action=tgt["label"],
                        reason=tgt.get("basis", ""), price=f"{price:.6f}",
                        qty=f"{sold or want:.8f}", pnl_pct=f"{pnl:+.4f}",
                        mode=describe_mode(), protection=ss["protection"])
        notify(f"🎯 {tgt['label']} hit on {symbol} @ {price:.4f}\n"
               f"Closed {frac*100:.0f}% | Entry {entry:.4f} | P/L {pnl:+.2f}%",
               subject=f"{tgt['label']} — {symbol}")

        if ss["qty"] <= 0 or all(t.get("hit") for t in ss["targets"]):
            ss.update(_fresh_symbol_state())
            return

    # Tighten the stop behind whatever has already been banked.
    old_stop = ss.get("stop")
    if ss["tps_hit"] >= params.trail_after:
        ss["stop"] = strategy.trail_stop(ss["stop"], price, plan.atr, params)
    elif ss["tps_hit"] >= params.breakeven_after and ss.get("entry_price"):
        ss["stop"] = max(ss["stop"] or 0.0, ss["entry_price"])

    if ss.get("stop") and old_stop and ss["stop"] > old_stop:
        why = "trailing" if ss["tps_hit"] >= params.trail_after else "breakeven"
        log.info("[%s] Stop %.4f -> %.4f (%s)", symbol, old_stop, ss["stop"], why)
        if live_trading() and ss["qty"] > 0:
            broker.protect(symbol, ss["qty"], ss["stop"])


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
    log.info("Strategy: %s %d/%d + zones + fib | confluence >=%d/%d | ADX>=%.0f",
             params.ma_type.upper(), params.fast, params.slow,
             params.min_confluence, strategy.MAX_SCORE, params.adx_min)
    log.info("Exits: TP1/TP2/TP3 %.0f/%.0f/%.0f%% | stop %.1f-%.1f ATR | "
             "breakeven after TP%d, trail after TP%d",
             *[f * 100 for f in params.tp_fractions],
             params.min_stop_atr, params.max_stop_atr,
             params.breakeven_after, params.trail_after)
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

                plan = strategy.analyze(bars, htf, params)

                # Only the stop closes everything; targets scale out in
                # manage_position() below.
                exit_reason = None
                if ss["in_position"]:
                    exit_reason = risk_exit_reason(ss, price)
                    if not exit_reason and plan.signal == "SELL":
                        exit_reason = "sell-signal"

                held = (f" pos {ss['qty']:.4f} stop {ss['stop']:.4f} "
                        f"tp {ss['tps_hit']}/{len(ss['targets'])}"
                        if ss["in_position"] else "")
                log.info("%-9s %-4s %.4f %-4s score=%d/%d adx=%s%s%s%s",
                         sym, w["entry_tf"], price, plan.signal,
                         plan.score, strategy.MAX_SCORE,
                         f"{plan.adx:.0f}" if plan.adx is not None else "--",
                         held,
                         f" exit={exit_reason}" if exit_reason else "",
                         f" | {plan.blocked_by}" if plan.signal == "HOLD"
                         and not ss["in_position"] else "")

                if plan.signal == "BUY" and not ss["in_position"]:
                    if live and halted:
                        log.info("[%s] BUY signal ignored — %s", sym, halted)
                    else:
                        handle_entry(broker, sym, price, plan, ss, account)
                elif ss["in_position"]:
                    if exit_reason:
                        handle_exit(broker, sym, price, ss, exit_reason)
                    else:
                        manage_position(broker, sym, price, plan, ss, params)

                save_state(state)

            except broker.ERRORS as e:
                log.error("[%s] %s API error: %s", sym, broker.name, e)
            except Exception as e:
                log.exception("[%s] Unexpected error: %s", sym, e)

        time.sleep(config.POLL_SECONDS)


def handle_entry(broker, symbol, price, plan, ss, account):
    """Open a position and record the plan that will manage it."""
    stop = plan.stop
    targets = [{"price": t.price, "fraction": t.fraction, "label": t.label,
                "basis": t.basis, "hit": False} for t in plan.targets]
    risk_pct = (price - stop) / price * 100 if stop else 0.0
    tp_txt = "\n".join(
        f"{t.label}: {t.price:.4f} ({(t.price - price) / (price - stop):.1f}R, "
        f"close {t.fraction * 100:.0f}%) — {t.basis}" for t in plan.targets) if stop else ""
    msg = (f"📈 BUY {symbol} @ {price:.4f}   [score {plan.score}/{strategy.MAX_SCORE}]\n"
           f"SL: {stop:.4f} (-{risk_pct:.2f}%)\n{tp_txt}\n"
           f"Why: {', '.join(plan.reasons)}")

    if not live_trading():
        tag = "signal-only" if config.SIGNAL_ONLY else "paper"
        if not config.SIGNAL_ONLY:
            log.info("[PAPER] Would BUY %s of %s.", config.TRADE_QUOTE_AMOUNT, symbol)
            msg += "\n(paper mode — no order placed)"
        notify(msg, subject=f"BUY signal — {symbol}")
        qty = config.TRADE_QUOTE_AMOUNT / price if price else 0.0
        tradelog.record(config.TRADE_LOG, symbol=symbol, action="ENTRY",
                        reason=f"score {plan.score}", price=f"{price:.6f}",
                        notional=config.TRADE_QUOTE_AMOUNT, mode=tag, protection="poll")
        ss.update(in_position=True, entry_price=price, qty=qty, qty_initial=qty,
                  protection="poll", stop=stop, targets=targets, tps_hit=0)
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

    # A bracket carries ONE target, so multi-TP entries go in flat and get a
    # separate resting stop instead.
    result = broker.buy(symbol, notional, price,
                        stop_price=None if len(targets) > 1 else stop,
                        target_price=None if len(targets) > 1 else
                        (targets[0]["price"] if targets else None))
    entry = result["fill"] or price
    qty = result["qty"]
    if qty <= 0:
        log.error("[%s] Entry did not fill — nothing opened.", symbol)
        return

    protection = result["protection"]
    if protection != "bracket" and stop:
        if broker.protect(symbol, qty, stop):
            protection = "broker-stop"

    notify(msg + f"\n✅ Bought {qty:.6f} @ {entry:.4f} ({protection})",
           subject=f"BUY executed — {symbol}")
    tradelog.record(config.TRADE_LOG, symbol=symbol, action="ENTRY",
                    reason=f"score {plan.score}", price=f"{entry:.6f}",
                    qty=f"{qty:.8f}", notional=f"{notional:.2f}",
                    mode=describe_mode(), protection=protection)
    ss.update(in_position=True, entry_price=entry, qty=qty, qty_initial=qty,
              protection=protection, stop=stop, targets=targets, tps_hit=0)


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
