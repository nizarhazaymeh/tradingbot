"""Pump.fun sniper — orchestrator.

Pipeline per fresh launch:
  detect -> safety gate -> OBSERVE for momentum -> (dry-run) buy -> manage -> sell

DRY_RUN=true (default) simulates every buy/sell against the real bonding-curve
price and spends NOTHING. Flip SNIPER_DRY_RUN=false in .env only after you've
watched it behave and understand it will likely lose money.

Run:  python -m sniper.main
"""
import asyncio
import csv
import json
import logging
import os
import time
import urllib.request
from collections import deque
from datetime import datetime, timezone

import notifier  # reuse the project's email/console notifier
from sniper import config, executor
from sniper.detector import watch_launches
from sniper.safety import check_token
from sniper.pumpfun import get_curve

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-5s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("sniper")

TRADES_CSV = os.path.join(os.path.dirname(__file__), "trades.csv")

# --- shared runtime state ---
spent_today = 0.0          # SOL committed today (simulated in dry-run)
spend_day = None           # UTC date the daily budget belongs to
open_positions = 0
seen = set()               # mints already handled (dedupe)
_seen_order = deque()      # insertion order, so `seen` stays bounded
stats = {"trades": 0, "wins": 0, "pnl_sol": 0.0}  # session running total
_tasks = set()             # strong refs to per-launch tasks (bare create_task can be GC'd)


async def notify_async(text: str, subject: str) -> None:
    """notifier.notify blocks (SMTP retries can take ~80s) — never call it on the
    event loop, or every open position stops polling its stop-loss meanwhile."""
    await asyncio.to_thread(notifier.notify, text, subject=subject)


def budget_allows_buy() -> bool:
    """True if today's budget has room for one more buy. Resets at UTC midnight."""
    global spent_today, spend_day
    today = datetime.now(timezone.utc).date()
    if spend_day != today:
        if spend_day is not None and spent_today > 0:
            log.info("New UTC day — daily spend counter reset (was %.3f SOL)", spent_today)
        spend_day, spent_today = today, 0.0
    return spent_today + config.BUY_AMOUNT_SOL <= config.MAX_DAILY_SPEND_SOL


def mark_seen(mint: str) -> None:
    seen.add(mint)
    _seen_order.append(mint)
    if len(_seen_order) > 20_000:
        seen.discard(_seen_order.popleft())


async def curve_async(bonding_curve):
    """get_curve without stalling the event loop (urllib is blocking)."""
    return await asyncio.to_thread(get_curve, config.RPC_HTTP, bonding_curve)


async def sell_with_retry(symbol: str, mint: str, percent: str = "100%", attempts: int = 3):
    """Live sell with retries — a failed sell means tokens stranded in the wallet."""
    last = None
    for i in range(1, attempts + 1):
        try:
            return await asyncio.to_thread(executor.sell, mint, percent)
        except Exception as e:
            last = e
            log.warning("SELL %s attempt %d/%d failed: %s", symbol, i, attempts, e)
            if i < attempts:
                await asyncio.sleep(2 * i)
    raise last


def record_trade(symbol, mint, rank, score, reason, entry, exit_price, pnl_sol, px):
    """Append the closed trade to trades.csv; return a session-stats summary line."""
    stats["trades"] += 1
    if pnl_sol > 0:
        stats["wins"] += 1
    stats["pnl_sol"] += pnl_sol
    try:
        is_new = not os.path.exists(TRADES_CSV)
        with open(TRADES_CSV, "a", newline="") as f:
            w = csv.writer(f)
            if is_new:
                w.writerow(["time_utc", "symbol", "mint", "rank", "score", "reason",
                            "entry", "exit", "mult", "pnl_sol", "pnl_usd", "dry_run"])
            mult = exit_price / entry if entry else 0.0
            w.writerow([datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        symbol, mint, rank, score, reason,
                        f"{entry:.6e}", f"{exit_price:.6e}", f"{mult:.3f}",
                        f"{pnl_sol:+.5f}",
                        f"{pnl_sol * px:+.2f}" if px > 0 else "",
                        config.DRY_RUN])
    except Exception as e:
        log.warning("could not write trades.csv: %s", e)
    losses = stats["trades"] - stats["wins"]
    usd = f" (~${stats['pnl_sol'] * px:+.2f})" if px > 0 else ""
    return (f"Session: {stats['trades']} trades, {stats['wins']}W/{losses}L, "
            f"{stats['pnl_sol']:+.4f} SOL{usd}")


def score_launch(start, last, sol_added):
    """Rank a candidate 0-100 from the signals we have, return (score, letter).

    Three components:
      momentum  (50 pts) — real SOL of buyers in the window (10 SOL = full marks)
      liquidity (30 pts) — SOL parked in the curve = real interest (30 SOL = full)
      price rise(20 pts) — how much it climbed while we watched (+50% = full)
    """
    momentum = min(max(sol_added, 0.0) / 10.0, 1.0) * 50
    liquidity = min(last.sol_in_curve / 30.0, 1.0) * 30
    rise = (last.price / start.price - 1) if start.price else 0
    rise_pts = min(max(rise, 0) / 0.5, 1.0) * 20
    score = round(momentum + liquidity + rise_pts)
    rank = ("S" if score >= 80 else "A" if score >= 65 else
            "B" if score >= 50 else "C" if score >= 35 else "D")
    return score, rank


async def observe(mint, bonding_curve):
    """Watch the curve for OBSERVE_SECONDS; return (decision, entry, sol_added, score, rank)."""
    start = await curve_async(bonding_curve)
    if not start:
        return False, 0.0, 0.0, 0, "D"
    sol0 = start.sol_in_curve
    deadline = time.monotonic() + config.OBSERVE_SECONDS
    last = start
    while time.monotonic() < deadline:
        await asyncio.sleep(config.POLL_SECONDS)
        c = await curve_async(bonding_curve)
        if not c:
            continue
        last = c
        if c.complete:  # graduated already — too fast for us
            break
    sol_added = last.sol_in_curve - sol0
    # Buy only if: real buyers piled in, price rising, AND the coin has already
    # attracted real money (survivor filter — filters out dead-on-arrival launches).
    # A graduated curve is un-buyable through the pump pool — never "decide" on one.
    decided = (not last.complete
               and sol_added >= config.MIN_SOL_MOMENTUM
               and last.price >= start.price
               and last.sol_in_curve >= config.MIN_CURVE_SOL)
    score, rank = score_launch(start, last, sol_added)
    return decided, last.price, sol_added, score, rank


def wallet_balance_sol() -> float:
    """Live SOL balance of the burner wallet. Returns -1 if unreadable."""
    try:
        from solders.keypair import Keypair
        pub = str(Keypair.from_base58_string(config.WALLET_PRIVATE_KEY).pubkey())
        payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "getBalance",
                              "params": [pub]}).encode()
        req = urllib.request.Request(config.RPC_HTTP, data=payload,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=8) as r:
            return json.loads(r.read())["result"]["value"] / 1e9
    except Exception:
        return -1.0


def sol_usd() -> float:
    """Current SOL price in USD (Binance public ticker). 0.0 if unavailable."""
    try:
        r = urllib.request.urlopen(
            "https://api.binance.com/api/v3/ticker/price?symbol=SOLUSDT", timeout=8)
        return float(json.loads(r.read())["price"])
    except Exception:
        return 0.0


async def manage(symbol, mint, bonding_curve, entry_price, rank="?", score=0):
    """Hold the (simulated) position until an exit rule fires, then report.

    Exit ladder:
      1. hard stop-loss from entry
      2. partial take-profit at TAKE_PROFIT_X (sell TP_SELL_PCT, ride the rest)
      3. trailing stop from the peak once in profit
      4. optional fixed $ target (TAKE_PROFIT_USD, overrides the X target)
      5. graduation or MAX_HOLD_SECONDS timeout
    """
    deadline = time.monotonic() + config.MAX_HOLD_SECONDS
    reason, exit_price = "timeout", entry_price
    peak = entry_price          # highest price seen — the trailing stop rides this up
    sold_frac = 0.0             # fraction of the position banked at take-profit
    realized_sol = 0.0          # P/L locked in by the partial sell
    tag = "[DRY-RUN] " if config.DRY_RUN else ""
    px = await asyncio.to_thread(sol_usd)
    while time.monotonic() < deadline:
        await asyncio.sleep(config.POLL_SECONDS)
        c = await curve_async(bonding_curve)
        if not c or c.price == 0:
            continue
        exit_price = c.price
        peak = max(peak, exit_price)

        # 1) Hard stop from entry — cut losers fast.
        if exit_price <= entry_price * (1 - config.STOP_LOSS_PCT):
            reason = "stop-loss"; break
        # 2) Partial take-profit at TAKE_PROFIT_X — bank some, let the rest run.
        #    (Skipped when a fixed $ target is set; that overrides the X target.)
        if (config.TAKE_PROFIT_USD <= 0 and config.TAKE_PROFIT_X > 0 and sold_frac == 0
                and exit_price >= entry_price * config.TAKE_PROFIT_X):
            frac = min(max(config.TP_SELL_PCT, 0.0), 1.0)
            if frac >= 1.0:
                reason = "take-profit"; break
            if not config.DRY_RUN:
                try:
                    await sell_with_retry(symbol, mint, f"{int(frac * 100)}%")
                except Exception as e:
                    log.error("PARTIAL SELL FAILED %s: %s", symbol, e)
                    frac = 0.0  # nothing actually sold; keep managing the full position
            if frac > 0:
                sold_frac = frac
                realized_sol = config.BUY_AMOUNT_SOL * frac * (exit_price / entry_price - 1)
                pmsg = (f"{tag}TP HIT {symbol} @ {exit_price / entry_price:.2f}x — "
                        f"sold {frac * 100:.0f}%, banked {realized_sol:+.4f} SOL, "
                        f"trailing the rest")
                log.info(pmsg)
                await notify_async(pmsg, subject=f"{tag}TP hit — {symbol}")
            continue
        # 3) Trailing stop — once in profit, ride the pump; exit on a pullback from peak.
        if config.TRAIL_PCT > 0 and exit_price > entry_price \
                and exit_price <= peak * (1 - config.TRAIL_PCT):
            reason = "trailing-stop"; break
        # 4) Optional fixed $ target (off by default so winners can run).
        if config.TAKE_PROFIT_USD > 0 and px > 0:
            if config.BUY_AMOUNT_SOL * (exit_price / entry_price - 1) * px >= config.TAKE_PROFIT_USD:
                reason = "take-profit"; break
        if c.complete:
            reason = "graduated"; break

    # Sell the remainder — real on-chain when live, simulated in dry-run.
    sig_line = ""
    if not config.DRY_RUN:
        try:
            sig = await sell_with_retry(symbol, mint, "100%")
            sig_line = f"\ntx: {executor.solscan(sig)}"
        except Exception as e:
            log.error("SELL FAILED %s: %s", symbol, e)
            sig_line = f"\n⚠️ SELL FAILED after retries: {e} — you may still hold these tokens, check the wallet!"

    mult = exit_price / entry_price if entry_price else 0
    remaining = config.BUY_AMOUNT_SOL * (1 - sold_frac)
    # Costs: pump.fun fee on the way in and out, plus two priority fees.
    # Without this, dry-run stats flatter the strategy vs. what live would pay.
    fees = (config.BUY_AMOUNT_SOL * config.FEE_PCT * (1 + mult)
            + 2 * config.PRIORITY_FEE_SOL)
    pnl_sol = realized_sol + remaining * (mult - 1) - fees
    usd_str = f"  (~${pnl_sol * px:+.2f})" if px > 0 else ""
    banked = f", {sold_frac * 100:.0f}% banked at TP" if sold_frac else ""
    stats_line = record_trade(symbol, mint, rank, score, reason,
                              entry_price, exit_price, pnl_sol, px)
    msg = (
        f"{tag}SOLD {symbol} ({reason})\n"
        f"Entry {entry_price:.3e} -> Exit {exit_price:.3e}  ({mult:.2f}x{banked})\n"
        f"P/L: {pnl_sol:+.4f} SOL{usd_str} on {config.BUY_AMOUNT_SOL} SOL (est.)\n"
        f"{stats_line}\n"
        f"mint: {mint}{sig_line}"
    )
    log.info(msg.replace("\n", " | "))
    await notify_async(msg, subject=f"{tag}SOLD {symbol} ({reason})")


async def handle(launch):
    """Full pipeline for one launch. Runs concurrently per coin."""
    global spent_today, open_positions
    if launch.mint in seen:
        return
    mark_seen(launch.mint)

    # Gate 1: capacity / budget
    if open_positions >= config.MAX_CONCURRENT:
        return
    if not budget_allows_buy():
        return

    # Gate 2: safety (blocking RPC calls -> off the event loop)
    v = await asyncio.to_thread(
        check_token, config.RPC_HTTP, launch.mint, launch.bonding_curve,
        config.MAX_CREATOR_HOLD_PCT, config.MIN_OTHER_HOLDERS)
    if not v.ok:
        log.info("SKIP %s (safety): %s", launch.symbol, "; ".join(v.reasons))
        return

    # Gate 3: observe for real momentum
    log.info("WATCH %s — observing %ss for buyers...", launch.symbol, config.OBSERVE_SECONDS)
    decided, entry, sol_added, score, rank = await observe(launch.mint, launch.bonding_curve)
    if not decided:
        log.info("PASS  %s [rank %s, %d/100] — weak (%.2f SOL in window, need %.2f)",
                 launch.symbol, rank, score, sol_added, config.MIN_SOL_MOMENTUM)
        return
    # Rank gate: only buy the best — skip anything below the minimum score.
    if score < config.MIN_SCORE:
        log.info("PASS  %s [rank %s, %d/100] — below min score %d",
                 launch.symbol, rank, score, config.MIN_SCORE)
        return

    # Live balance guard: never spend into the fee reserve, or we can't SELL.
    if not config.DRY_RUN:
        bal = await asyncio.to_thread(wallet_balance_sol)
        if 0 <= bal < config.BUY_AMOUNT_SOL + config.MIN_SOL_RESERVE:
            log.warning("Balance %.4f SOL too low (need %.4f buy + %.4f reserve) — skipping",
                        bal, config.BUY_AMOUNT_SOL, config.MIN_SOL_RESERVE)
            return

    # Re-check capacity/budget: gate 1 ran BEFORE the observe window, and other
    # coins observed in parallel may have bought meanwhile. No await between this
    # check and the reservation below, so it can't race.
    if open_positions >= config.MAX_CONCURRENT or not budget_allows_buy():
        log.info("PASS  %s — capacity/budget filled while observing", launch.symbol)
        return

    # Dry-run fills at the observed price, which flatters the strategy — a real
    # momentum buy fills above it. Simulate that. (Live re-anchors after the buy.)
    if config.DRY_RUN and config.DRY_RUN_SLIPPAGE_PCT > 0:
        entry *= 1 + config.DRY_RUN_SLIPPAGE_PCT

    # Buy — real on-chain when live, simulated in dry-run.
    spent_today += config.BUY_AMOUNT_SOL
    open_positions += 1
    tag = "[DRY-RUN] " if config.DRY_RUN else ""
    sig_line = ""
    if not config.DRY_RUN:
        try:
            sig = await asyncio.to_thread(executor.buy, launch.mint, config.BUY_AMOUNT_SOL)
            sig_line = f"\ntx: {executor.solscan(sig)}"
        except Exception as e:
            log.error("BUY FAILED %s: %s", launch.symbol, e)
            spent_today -= config.BUY_AMOUNT_SOL
            open_positions -= 1
            return
        # Re-anchor entry to the REAL post-buy price (fixes miscalibrated stop-loss).
        await asyncio.sleep(1.5)  # let the buy settle on-chain
        c = await curve_async(launch.bonding_curve)
        if c and c.price > 0:
            entry = c.price
    buymsg = (f"{tag}BUY {launch.symbol}  [rank {rank}, score {score}/100]\n"
              f"{sol_added:.2f} SOL of buyers in {config.OBSERVE_SECONDS}s\n"
              f"Spending {config.BUY_AMOUNT_SOL} SOL @ {entry:.3e}\nmint: {launch.mint}{sig_line}")
    log.info(buymsg.replace("\n", " | "))
    await notify_async(buymsg, subject=f"{tag}BUY {launch.symbol} [{rank}]")
    try:
        await manage(launch.symbol, launch.mint, launch.bonding_curve, entry,
                     rank=rank, score=score)
    finally:
        open_positions -= 1


async def run():
    mode = "DRY-RUN (no real SOL)" if config.DRY_RUN else "!! LIVE — REAL SOL !!"
    log.info("=" * 60)
    log.info("Pump.fun sniper starting | %s", mode)
    log.info("buy=%s SOL  daily_cap=%s (resets at UTC midnight)  observe=%ss  need=%s SOL momentum",
             config.BUY_AMOUNT_SOL, config.MAX_DAILY_SPEND_SOL, config.OBSERVE_SECONDS,
             config.MIN_SOL_MOMENTUM)
    log.info("exits: TP %sx (sell %.0f%%, trail rest)  trail=%.0f%%  SL=%.0f%%  max_hold=%ss",
             config.TAKE_PROFIT_X, config.TP_SELL_PCT * 100, config.TRAIL_PCT * 100,
             config.STOP_LOSS_PCT * 100, config.MAX_HOLD_SECONDS)
    log.info("costs: fee=%.1f%%/side  priority=%.4f SOL/tx%s",
             config.FEE_PCT * 100, config.PRIORITY_FEE_SOL,
             f"  sim-slippage={config.DRY_RUN_SLIPPAGE_PCT * 100:.0f}%" if config.DRY_RUN else "")
    log.info("trade log: %s", TRADES_CSV)
    log.info("=" * 60)
    async for launch in watch_launches(config.RPC_WS):
        # Keep a strong reference — a bare create_task can be garbage-collected
        # mid-flight, silently killing an open position's management loop.
        t = asyncio.create_task(handle(launch))  # don't block the firehose
        _tasks.add(t)
        t.add_done_callback(_tasks.discard)


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        log.info("Stopped.")
