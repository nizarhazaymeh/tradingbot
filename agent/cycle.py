"""The agent's main loop. One cycle = observe -> reconcile -> manage -> propose -> execute.

Order matters: existing positions are managed BEFORE new ones are considered, and
circuit breakers run before anything else.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

from . import config
from . import brain, monitor, options as O, regime as R, risk as RK, spreads as S, strategy as ST
from .client import AlpacaClient, AlpacaError
from .executor import Executor
from . import crypto as CR
from . import levels as L
from .notifier import notify
from .state import Store, utcnow

log = logging.getLogger("agent")
HALT_FILE = Path(config.ROOT if hasattr(config, "ROOT") else ".") / "HALTED"


class Agent:
    def __init__(self, *, dry_run: bool = None, use_llm: bool = True,
                 rehearse: bool = False):
        # When trading the judged account, verify the credentials really belong
        # to it before any order can be built.
        expected = config.ACCOUNT_NUMBER if config.ACCOUNT == "comp" else None
        self.c = AlpacaClient(verify_account=expected)
        self.store = Store()
        self.ex = Executor(self.c, self.store, dry_run=dry_run)
        self.use_llm = use_llm
        # rehearse: pretend the market is open so the full pipeline can be
        # exercised outside session hours. NEVER combine with --live.
        self.rehearse = rehearse
        self.cycle_n = 0
        # signature -> consecutive cycles seen as a ghost. In memory on purpose:
        # a restart re-observes before retiring anything. See _retire_ghosts().
        self._ghost_streak: dict = {}

    # ------------------------------------------------------------- helpers
    def _halted(self) -> bool:
        return HALT_FILE.exists()

    def _orders_last_hour(self) -> int:
        since = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(timespec="seconds")
        return self.store.orders_since(since)

    def _pick_expiry(self, underlying: str) -> Optional[date]:
        """Nearest expiry inside [MIN_DTE, MAX_DTE]."""
        today = date.today()
        lo = (today + timedelta(days=config.MIN_DTE)).isoformat()
        hi = (today + timedelta(days=config.MAX_DTE)).isoformat()
        try:
            exps = self.c.expirations(underlying, lo, hi)
        except AlpacaError as e:
            log.warning("%s: expirations failed: %s", underlying, e.message[:120])
            return None
        candidates = [date.fromisoformat(e) for e in exps]
        candidates = [d for d in candidates
                      if config.MIN_DTE <= (d - today).days <= config.MAX_DTE]
        if not candidates:
            return None
        # prefer the expiry closest to TARGET_DTE, not simply the nearest —
        # very short DTE has unstable Greeks and violent gamma.
        return min(candidates, key=lambda d: abs((d - today).days - config.TARGET_DTE))

    def _clear_never_filled(self) -> list:
        """Close tracked rows whose opening order died without ever filling.

        cycle.consider() records a position the moment an order is ACCEPTED, not
        when it fills — deliberately, because a crash between submit and fill
        would otherwise leave a real position with no exit plan. The cost is that
        an order which never fills stays on the books forever.

        That is not cosmetic. Book.from_account() derives portfolio heat from
        tracked positions, so an unfilled structure consumes risk budget that is
        not at risk. On 31 Aug two cancelled orders held $572 of the $1,145 the
        agent believed was live, half of SPY's per-underlying cap.

        The broker's own order status settles it, so no guessing from symbol
        overlap: terminal status with filled_qty 0 means the position never
        existed. Anything still working is left alone.
        """
        cleared = []
        for pos in self.store.open_positions():
            oid = pos.get("open_order_id")
            if not oid:
                continue
            try:
                o = self.c.get_order(oid)
            except AlpacaError as e:
                log.warning("could not verify order %s for %s: [%s] %s",
                            str(oid)[:8], pos["signature"][:40], e.status, e.message[:60])
                continue
            if o.get("status") not in ("canceled", "expired", "rejected"):
                continue
            if float(o.get("filled_qty") or 0) > 0:
                continue          # partially filled: a real position, leave it
            self.store.close_position(pos["signature"], realized_pnl=0.0,
                                      reason=f"never filled (order {o.get('status')})",
                                      close_order_id=str(oid))
            cleared.append(pos["signature"])
            log.info("    cleared never-filled %s (order %s)",
                     pos["signature"][:52], o.get("status"))
        return cleared

    # ------------------------------------------------------------ crypto
    def _crypto_bars(self, symbol: str, limit: int = 400):
        r = self.c._data("/v1beta3/crypto/us/bars",
                         {"symbols": symbol, "timeframe": "1Day", "limit": limit,
                          "start": (date.today() - timedelta(days=limit + 60)).isoformat()})
        return L.bars_from_api((r.get("bars") or {}).get(symbol, []))

    def _crypto_price(self, symbol: str):
        r = self.c._data("/v1beta3/crypto/us/snapshots", {"symbols": symbol})
        snap = (r.get("snapshots") or {}).get(symbol) or {}
        q = snap.get("latestQuote") or {}
        bid, ask = float(q.get("bp") or 0), float(q.get("ap") or 0)
        if bid > 0 and ask > 0:
            return (bid + ask) / 2
        t = snap.get("latestTrade") or {}
        return float(t.get("p") or 0) or None

    def crypto_pass(self, equity: float, *, allow_new: bool = True) -> list:
        """The spot-crypto half. Exits first, then entries — like the options path.

        Runs regardless of /v2/clock: that gate is about the equity session and
        crypto has none. The daily-drawdown breaker is re-derived against UTC
        midnight instead of Alpaca's `last_equity`, which is an equity-market
        close and can be three days stale across a weekend.

        Nothing here can open a position that is not bounded twice — by the stop
        and by notional. See risk.crypto_gates().
        """
        out = []
        if not config.CRYPTO_ENABLED:
            return out

        day0 = self.store.equity_at(CR.crypto_day_start().isoformat())
        dd = RK.crypto_day_drawdown(equity, day0)
        held = self.store.open_crypto_positions()

        # ---- exits run even when the breaker has fired --------------------
        for pos in held:
            try:
                px = self._crypto_price(pos["symbol"])
                if not px:
                    continue
                bars = self._crypto_bars(pos["symbol"])
                action, reason = CR.evaluate_exit(pos, px, bars)
                if action != CR.CLOSE:
                    log.info("    crypto hold %s — %s", pos["symbol"], reason)
                    continue
                pnl = (px - float(pos["entry"])) * float(pos["qty"])
                msg = self.ex.close_crypto(pos, px)
                self.store.close_crypto(pos["symbol"], pos["opened_at"],
                                        exit_price=px, realized_pnl=round(pnl, 2),
                                        reason=reason)
                log.info("    crypto CLOSE %s @ %.2f P&L $%.0f — %s (%s)",
                         pos["symbol"], px, pnl, reason, msg)
                out.append({"symbol": pos["symbol"], "decision": "close",
                            "reason": reason, "pnl": round(pnl, 2)})
            except Exception as e:
                log.exception("crypto exit %s", pos["symbol"])
                out.append({"symbol": pos["symbol"], "decision": "error",
                            "reason": str(e)[:200]})

        if not dd:
            log.warning("    crypto: %s", dd.reason)
            out.append({"decision": "halt", "reason": dd.reason})
            return out
        if not allow_new:
            return out

        # ---- entries -----------------------------------------------------
        held = self.store.open_crypto_positions()
        held_syms = {p["symbol"] for p in held}
        open_risk = sum(float(p["risk"] or 0) for p in held)
        for sym in config.CRYPTO_UNIVERSE:
            try:
                bars = self._crypto_bars(sym)
                sig = CR.signal(sym, bars)
                if not sig:
                    out.append({"symbol": sym, "decision": "skip",
                                "reason": "no confirmed bullish break"})
                    continue
                qty, risk, notional = CR.size(sig, equity)
                gate = RK.crypto_gates(equity=equity, qty=qty, risk=risk,
                                       notional=notional, open_positions=len(held),
                                       open_risk=open_risk, symbol=sym,
                                       held_symbols=held_syms)
                if not gate:
                    log.info("    crypto REJECT [%s] %s", gate.gate, gate.reason)
                    out.append({"symbol": sym, "decision": "reject",
                                "gate": gate.gate, "reason": gate.reason})
                    continue
                order, msg = self.ex.open_crypto(sig, qty)
                log.info("    crypto SUBMIT %s qty %.6f (risk $%.0f / notional $%.0f)"
                         " -> %s", sig.summary(), qty, risk, notional, msg)
                if order and order.get("status") != "dry_run":
                    self.store.open_crypto(
                        symbol=sym, side=sig.side, qty=qty, entry=sig.entry,
                        stop=sig.stop, target=sig.target, risk=risk,
                        notional=notional, level=sig.level,
                        order_id=order.get("id"))
                    held_syms.add(sym)
                    open_risk += risk
                out.append({"symbol": sym, "decision": "submit", "reason": msg,
                            "signal": sig.summary(), "qty": qty, "risk": risk,
                            "notional": notional})
            except Exception as e:
                log.exception("crypto entry %s", sym)
                out.append({"symbol": sym, "decision": "error", "reason": str(e)[:200]})
        return out

    def _cancel_stale_orders(self) -> list:
        """Cancel working orders that have sat unfilled past config.ORDER_TTL_SEC.

        A working order is not free. Alpaca refuses any new order that takes the
        OPPOSITE side of a contract a live order already touches, so one stale
        mleg limit blocks every structure that overlaps its strikes — the agent
        re-proposes and is rejected 403 "potential wash trade detected" every
        cycle, burning its order budget and locking itself out of the underlying.

        Only orders with zero fills are cancelled. A partially filled order is a
        real position; cancelling it would strand the filled legs naked, so it is
        reported and left alone exactly as monitor.reconcile() leaves a partial.

        The cancelled row is not closed here. Its order becomes `canceled` with
        filled_qty 0, which is precisely what _clear_never_filled() already looks
        for, so the next cycle retires it and releases the risk budget.
        """
        ttl = config.ORDER_TTL_SEC
        if ttl <= 0:
            return []
        now = datetime.now(timezone.utc)
        cancelled = []
        for pos in self.store.open_positions():
            oid = pos.get("open_order_id")
            if not oid:
                continue
            try:
                o = self.c.get_order(oid)
            except AlpacaError as e:
                log.warning("could not verify order %s: [%s] %s",
                            str(oid)[:8], e.status, e.message[:60])
                continue
            if o.get("status") in ("filled", "canceled", "expired", "rejected"):
                continue
            if float(o.get("filled_qty") or 0) > 0:
                continue                    # partial fill: a real position
            sub = o.get("submitted_at") or o.get("created_at")
            if not sub:
                continue
            try:
                age = (now - datetime.fromisoformat(
                    str(sub).replace("Z", "+00:00"))).total_seconds()
            except ValueError:
                continue
            if age < ttl:
                continue
            try:
                self.c.cancel_order(str(oid))
            except AlpacaError as e:
                # 422 means it filled or died between the read and the cancel —
                # the broker is the truth and the next cycle will see it.
                log.warning("could not cancel %s: [%s] %s",
                            str(oid)[:8], e.status, e.message[:60])
                continue
            cancelled.append(pos["signature"])
            log.info("    cancelled stale order %s after %.0fs unfilled — %s",
                     str(oid)[:8], age, pos["signature"][:52])
        return cancelled

    def _retire_ghosts(self, ghosts: list) -> list:
        """Close tracked rows the broker has held no leg of for N cycles running.

        reconcile() has always identified these exactly and then only logged
        them, so the row lived forever and g_no_duplicate refused to re-enter the
        structure. On 31 Aug an IWM bear_put the broker had not held since 14:35
        blocked every IWM proposal for the rest of the session. Restarting does
        not clear it — the row is in SQLite.

        Two things keep this conservative:

        * A structure must be a ghost on `config.GHOST_RETIRE_CYCLES` CONSECUTIVE
          cycles. A fill that has not yet surfaced in /v2/positions reads as a
          ghost once, and one observation is not evidence.
        * The streak lives in memory, so a restart starts counting again. Being
          slow to retire costs a few minutes of a blocked structure; being fast
          costs a real position its exit plan.

        P&L is recorded as NULL, meaning UNKNOWN rather than zero. These legs can
        be shared between structures — the two SPY condors on 31 Aug shared both
        put strikes — so per-symbol fills cannot be attributed to one of them.
        Store.stats() excludes unknowns from the win rate rather than counting a
        fabricated loss.
        """
        n = config.GHOST_RETIRE_CYCLES
        if n <= 0:
            self._ghost_streak.clear()
            return []
        live = set(ghosts or [])
        for sig in list(self._ghost_streak):
            if sig not in live:
                del self._ghost_streak[sig]          # reappeared: streak broken
        retired = []
        for sig in live:
            self._ghost_streak[sig] = self._ghost_streak.get(sig, 0) + 1
            if self._ghost_streak[sig] < n:
                log.info("    ghost %s seen %d/%d cycles — not retiring yet",
                         sig[:52], self._ghost_streak[sig], n)
                continue
            self.store.close_position(
                sig, realized_pnl=None,
                reason=f"ghost: broker held no leg for {n} cycles (P&L unknown)")
            del self._ghost_streak[sig]
            retired.append(sig)
            log.warning("    RETIRED ghost %s — broker holds none of its legs", sig[:60])
        return retired

    def _structure(self, ohlc) -> tuple:
        """(market_structure, zones, fib, breaks) from daily bars — all best-effort.

        Structure is a second opinion on trend direction; zones say where price
        has previously turned; breaks say which levels price has already been
        given a chance to reclaim. Anything here failing must degrade to "no
        opinion" rather than stop a cycle, so the whole thing is guarded.
        """
        if len(ohlc) < 45:                      # find_zones needs atr_period*3
            return None, [], None, []
        try:
            pv = L.pivots(ohlc)
            struct = L.market_structure(pv)
            zones = L.find_zones(ohlc)
            imp = L.last_impulse(ohlc, pv)
            fib = L.fibonacci(*imp) if imp else None
            brks = L.breaks(ohlc)
            return struct, zones, fib, brks
        except Exception as e:                  # never let structure break a cycle
            log.warning("structure analysis failed: %s: %s", type(e).__name__, e)
            return None, [], None, []

    def _structure_context(self, reg, spot: float, zones, fib, structure,
                           brks=None) -> dict:
        """Structure as scalars the model can compare, not raw objects.

        Distances are in units of the 1-sigma expected move rather than dollars,
        because "3% away" means something different on IWM than on SPY, while
        "1.2 sigma" is the same statement about reachability on both.
        """
        sigma = reg.expected_move or 0.0
        ctx = {"structure": structure}

        def describe(zone, key):
            if not zone or not sigma:
                ctx[f"{key}_sigma"] = None
                return
            ctx[f"{key}_sigma"] = round(abs(zone.mid - spot) / sigma, 2)
            ctx[f"{key}_touches"] = zone.touches
            ctx[f"{key}_strength_atr"] = round(zone.strength, 1)

        describe(L.nearest_zone(zones, spot, "supply", below=False), "resistance")
        describe(L.nearest_zone(zones, spot, "demand", below=True), "support")

        if fib:
            ctx["in_golden_pocket"] = fib.in_golden_pocket(spot)

        # The last break of structure and whether its retest held. Direction here
        # is a second read on trend that resolves far more often than `structure`
        # does — but like `structure` it is context for the model, not a veto.
        last = (brks or [])[-1] if brks else None
        if last:
            ctx["last_break"] = {
                "direction": "up" if last.direction > 0 else "down",
                "retest": last.state,
                "level_sigma": (round((last.level - spot) / sigma, 2)
                                if sigma else None),
            }
            ctx["break_trend"] = L.break_trend(brks)
        return ctx

    def _chain(self, underlying: str, spot: float, expiry: date, span=0.10):
        chain = self.c.option_chain(underlying, exp=expiry.isoformat(),
                                    strike_gte=spot * (1 - span),
                                    strike_lte=spot * (1 + span))
        rejects: List[str] = []
        views = O.usable_contracts(chain, collect_rejects=rejects)
        return views, rejects

    # --------------------------------------------------------------- phases
    def observe(self) -> dict:
        acct = self.c.account()
        clock = self.c.clock()
        positions = self.c.positions()
        self.store.snapshot_equity(float(acct["equity"]), float(acct.get("cash") or 0),
                                   float(acct.get("options_buying_power") or 0))
        return {"account": acct, "clock": clock, "positions": positions}

    def manage_open_positions(self, snaps_cache: dict = None) -> List[dict]:
        """Exit management. Runs every cycle regardless of whether we're opening."""
        actions = []
        open_pos = self.store.open_positions()
        if not open_pos:
            return actions

        symbols = sorted({l["symbol"] for p in open_pos
                          for l in json.loads(p["legs_json"])})
        try:
            snaps = self.c.option_snapshots(symbols)
        except AlpacaError as e:
            log.error("cannot fetch snapshots for open positions: %s", e.message[:150])
            return actions

        views = {}
        for sym, snap in snaps.items():
            try:
                views[sym] = O.view(sym, snap, min_dte=0, max_dte=3650)
            except Exception:
                pass

        for p in open_pos:
            d = monitor.evaluate_exit(p, snaps, views)
            if not d:
                log.info("  hold %s — %s", p["signature"][:40], d.reason)
                continue

            log.warning("  EXIT %s -> %s (%s)", p["signature"][:40], d.action, d.reason)
            sp = self._rebuild_spread(p, views)
            if sp is None:
                actions.append({"signature": p["signature"], "action": d.action,
                                "reason": d.reason, "result": "could not rebuild spread"})
                continue

            # ROLL: close the threatened vertical and reopen it further out in a
            # single atomic 4-leg order, rather than legging out and back in.
            if d.action == monitor.ROLL:
                rolled, msg = self._try_roll(p, sp, views)
                if rolled:
                    actions.append({"signature": p["signature"], "action": "roll",
                                    "reason": d.reason, "result": msg})
                    self.store.log_decision(cycle=self.cycle_n, underlying=p["underlying"],
                                            regime="-", view={}, proposal=p["kind"],
                                            decision="roll", gate="roll", reason=d.reason,
                                            payload={"msg": msg})
                    continue
                log.info("    roll not possible (%s) — closing instead", msg)

            order, msg = self.ex.close_spread(
                sp, market=(d.action == monitor.CLOSE_MARKET))
            pnl = monitor.unrealized_pnl(p, snaps)
            if order and order.get("status") != "dry_run":
                # Prefer the price that ACTUALLY filled over our pre-trade estimate.
                # Verified live 1 Sep: a close priced at -1.24 filled at -1.80, so
                # the estimate understated the result by $168 on one position. The
                # reported P&L is what judges read; it should be the real number.
                realized = pnl or 0.0
                avg = order.get("filled_avg_price")
                if avg is not None:
                    try:
                        exit_px = float(avg)
                        # closing_order() mirrors every leg, so its fill price is the
                        # negative of the entry convention: P&L = -(exit) - entry
                        realized = round((-exit_px - p["entry_price"]) * 100 * p["qty"], 2)
                    except (TypeError, ValueError):
                        pass
                self.store.close_position(p["signature"], realized_pnl=realized,
                                          reason=d.reason,
                                          close_order_id=order.get("id"))
                if pnl is not None and abs(realized - pnl) > 5:
                    log.info("    realised $%.2f vs estimate $%.2f (fill was %s)",
                             realized, pnl, avg)
            self.store.log_decision(cycle=self.cycle_n, underlying=p["underlying"],
                                    regime="-", view={}, proposal=p["kind"],
                                    decision="close", gate=d.action, reason=d.reason,
                                    payload={"pnl": pnl, "msg": msg})
            actions.append({"signature": p["signature"], "action": d.action,
                            "reason": d.reason, "pnl": pnl, "result": msg})
        return actions

    def _try_roll(self, p: dict, sp: S.Spread,
                  views: Dict[str, O.ContractView]) -> tuple:
        """Roll a threatened 2-leg vertical further out. Returns (ok, message)."""
        if len(sp.legs) != 2:
            return False, "only 2-leg verticals can be rolled (a condor needs 8 legs)"

        short_leg = next((l for l in sp.legs if l.side == "sell"), None)
        if short_leg is None or short_leg.view is None:
            return False, "no short leg view"

        expiry = date.fromisoformat(p["expiry"])
        if (expiry - date.today()).days < config.MIN_DTE:
            return False, "too close to expiry to roll"

        try:
            spot = self.c.latest_trade(p["underlying"])
            chain = self.c.option_chain(p["underlying"], exp=expiry.isoformat(),
                                        strike_gte=spot * 0.90, strike_lte=spot * 1.10)
            fresh = O.usable_contracts(chain)
        except AlpacaError as e:
            return False, f"chain fetch failed: {e.message[:80]}"

        target = ST.find_roll_target(short_leg.view, fresh, expiry, width=sp.width)
        if target is None:
            return False, "no strike far enough out to be worth rolling to"
        new_short, new_long = target

        try:
            body = S.roll_order(sp, new_short, new_long)
        except ValueError as e:
            return False, str(e)

        errs = S.validate_mleg(body)
        if errs:
            return False, f"roll payload invalid: {errs[0]}"

        if self.ex.dry_run:
            log.info("    DRY RUN roll: %s -> %s (delta %.2f -> %.2f)",
                     short_leg.view.strike, new_short.strike,
                     abs(short_leg.view.delta), abs(new_short.delta))
            return True, (f"dry run: roll {short_leg.view.strike:.0f} -> "
                          f"{new_short.strike:.0f}")

        try:
            order = self.c.submit_order(body)
        except AlpacaError as e:
            return False, f"roll rejected [{e.status}] {e.message[:100]}"

        self.store.log_order(body["client_order_id"], body, order, "roll")
        self.store.close_position(p["signature"], realized_pnl=0.0,
                                  reason=f"rolled to {new_short.strike:.0f}",
                                  close_order_id=order.get("id"))
        return True, (f"rolled {short_leg.view.strike:.0f} -> {new_short.strike:.0f} "
                      f"(delta {abs(short_leg.view.delta):.2f} -> "
                      f"{abs(new_short.delta):.2f}), order {order.get('status')}")

    def _rebuild_spread(self, p: dict, views: Dict[str, O.ContractView]) -> Optional[S.Spread]:
        legs = []
        for l in json.loads(p["legs_json"]):
            legs.append(S.Leg(l["symbol"], l["side"], l["position_intent"],
                              int(l["ratio_qty"]), views.get(l["symbol"])))
        try:
            return S.Spread(kind=p["kind"], underlying=p["underlying"],
                            expiry=date.fromisoformat(p["expiry"]), legs=legs,
                            net_price=p["entry_price"], max_loss_per_unit=p["max_loss"] / p["qty"],
                            max_gain_per_unit=p["max_gain"] / p["qty"],
                            width=p["width"], qty=p["qty"])
        except Exception as e:
            log.error("rebuild failed for %s: %s", p["signature"], e)
            return None

    def consider(self, underlying: str, book: RK.Book, clock: dict) -> dict:
        """Full proposal pipeline for one underlying."""
        out = {"underlying": underlying, "decision": "hold", "reason": ""}

        expiry = self._pick_expiry(underlying)
        if not expiry:
            out["reason"] = f"no expiry in the {config.MIN_DTE}-{config.MAX_DTE} DTE window"
            self.store.log_decision(cycle=self.cycle_n, underlying=underlying, regime="-",
                                    view={}, proposal="", decision="hold", reason=out["reason"])
            return out

        snaps = self.c.stock_snapshots([underlying])
        spot = ((snaps.get(underlying) or {}).get("latestTrade") or {}).get("p")
        # 300 daily bars rather than 90: still one request, but find_zones() needs
        # real history behind it and its lookback is 300.
        bars = self.c.stock_bars([underlying], timeframe="1Day", limit=300)
        rows = bars.get(underlying, [])
        closes = [b["c"] for b in rows]
        if not spot and closes:
            spot = closes[-1]
        if not spot or len(closes) < 25:
            out["reason"] = "insufficient price history"
            return out

        # Swing structure, supply/demand zones and the last impulse. Highs and
        # lows were previously fetched and thrown away — only the close was read.
        ohlc = L.bars_from_api(rows)
        structure, zones, fib, brks = self._structure(ohlc)
        out["structure"] = structure

        views, rejects = self._chain(underlying, spot, expiry)
        iv_hist = self.store.iv_history(underlying)
        reg = R.classify(underlying, spot, views, closes, expiry=expiry,
                         iv_history=iv_hist, structure=structure, breaks=brks)

        if reg.iv > 0:
            self.store.record_iv(underlying, date.today(), reg.iv)

        out["regime"] = reg.name
        out["regime_summary"] = reg.summary()
        log.info("  %s", reg.summary())
        log.info("    %d usable contracts (%d rejected)", len(views), len(rejects))

        v = ST.NEUTRAL
        if self.use_llm and reg.tradable:
            news = []
            try:
                news = self.c.news([underlying], limit=6)
            except AlpacaError:
                pass
            v = brain.view(reg, news=news,
                           extra=self._structure_context(reg, spot, zones, fib,
                                                        structure, brks))
            log.info("    view: %s (conf %.2f) — %s", v.direction, v.confidence, v.thesis[:90])

        budget = config.RISK_PER_TRADE_PCT * book.equity
        sp, why = ST.propose(reg, views, expiry, view=v, budget=budget)
        out["view"] = asdict(v)

        if sp is None:
            out["reason"] = why
            self.store.log_decision(cycle=self.cycle_n, underlying=underlying,
                                    regime=reg.name, view=asdict(v), proposal="",
                                    decision="hold", reason=why)
            return out

        # Record, per short leg, whether a supply/demand zone stands between spot
        # and the strike. Diagnostic only — it does not influence selection yet.
        # Strike distance is already governed by MIN_SHORT_SIGMA and the EV test,
        # so letting an unvalidated structural preference push strikes around
        # would double-count distance. Logging it first means it can be checked
        # against realised outcomes before it is trusted with a decision.
        prot = {}
        for leg in sp.legs:
            if leg.side == "sell" and leg.view is not None:
                z = L.protects_short(zones, spot, leg.view.strike, leg.view.kind)
                prot[f"{leg.view.strike:.0f}{leg.view.kind}"] = (
                    {"low": z.low, "high": z.high, "touches": z.touches,
                     "strength_atr": round(z.strength, 1)} if z else None)
        if prot:
            sp.meta["zone_protection"] = prot
            sp.meta["structure"] = structure
            n_prot = sum(1 for v_ in prot.values() if v_)
            # retest_levels is set by strategy._retest_bonus() for the chosen
            # structure. Unlike zone_protection this one DID influence selection,
            # as a ranking tie-break — log both so the audit shows which.
            rt = sp.meta.get("retest_levels") or {}
            n_rt = sum(1 for v_ in rt.values() if v_)
            log.info("    structure=%s · %d/%d short strikes behind a zone · "
                     "%d/%d behind a retested level",
                     structure, n_prot, len(prot), n_rt, len(rt) or len(prot))

        gate = RK.evaluate(sp, book)
        out["proposal"] = sp.describe()

        if not gate:
            out.update(decision="reject", gate=gate.gate, reason=gate.reason)
            log.info("    REJECT [%s] %s", gate.gate, gate.reason)
            self.store.log_decision(cycle=self.cycle_n, underlying=underlying,
                                    regime=reg.name, view=asdict(v), proposal=sp.kind,
                                    decision="reject", gate=gate.gate, reason=gate.reason,
                                    payload={"describe": sp.describe()})
            return out

        # LLM critic — advisory only; deterministic gates already passed
        crit = {"approve": True, "note": "critic skipped"}
        if self.use_llm:
            crit = brain.critic({"kind": sp.kind, "describe": sp.describe(),
                                 "net_price": sp.net_price, "max_loss": sp.total_max_loss(),
                                 "net_delta": round(sp.net_delta, 3),
                                 "net_theta": round(sp.net_theta, 2)}, reg, v)
        if not crit.get("approve", True):
            out.update(decision="reject", gate="g_critic",
                       reason="critic: " + "; ".join(crit.get("concerns", []))[:200])
            log.info("    CRITIC REJECT: %s", out["reason"])
            self.store.log_decision(cycle=self.cycle_n, underlying=underlying,
                                    regime=reg.name, view=asdict(v), proposal=sp.kind,
                                    decision="reject", gate="g_critic", reason=out["reason"])
            return out

        # Refresh quotes and chase the fill: a single limit derived from a chain
        # fetched earlier in the cycle sits unfilled, as observed live 1 Sep.
        order, msg = self.ex.open_and_chase(sp)
        out.update(decision="submit", reason=msg, order=msg)
        log.info("    SUBMIT %s -> %s", sp.describe()[:70], msg)

        # RECORD FIRST, notify second. On 1 Sep a NameError between submission and
        # persistence left a live 4-leg condor with no exit plan — an orphan the
        # monitor could not manage. Nothing that can raise goes between the
        # submit and the store write.
        # Only a FILLED order is a position. Recording on submission creates a
        # phantom: the monitor then tries to manage legs the broker does not hold,
        # and the risk budget is consumed by an order that may never fill.
        # Observed live 1 Sep: an unfilled condor was tracked as open while the
        # broker held nothing.
        status = (order or {}).get("status")
        if order and status not in ("dry_run",) and status != "filled":
            oid = order.get("id")
            try:
                if oid:
                    self.c.cancel_order(oid)
                    log.info("    cancelled unfilled order %s (status %s)", oid[:8], status)
            except AlpacaError as e:
                log.warning("    could not cancel %s: %s", oid, e.message[:80])
            out.update(decision="unfilled", reason=msg)
            self.store.log_decision(cycle=self.cycle_n, underlying=underlying,
                                    regime=reg.name, view=asdict(v), proposal=sp.kind,
                                    decision="unfilled", gate="g_no_fill", reason=msg,
                                    payload={"describe": sp.describe()})
            return out

        if order and status == "filled":
            coid = order.get("client_order_id") or sp.client_order_id()
            # record the price that ACTUALLY filled, not our estimate
            avg = order.get("filled_avg_price")
            if avg is not None:
                try:
                    sp.net_price = round(float(avg), 2)
                except (TypeError, ValueError):
                    pass
            tp = config.TAKE_PROFIT_CREDIT if sp.is_credit else config.TAKE_PROFIT_DEBIT
            self.store.open_position(
                signature=RK.signature(sp), spread=sp, order=order,
                take_profit=tp * sp.max_gain_per_unit * sp.qty,
                stop_loss=(config.STOP_CREDIT_MULT if sp.is_credit else config.STOP_DEBIT_PCT)
                          * abs(sp.net_price) * 100 * sp.qty,
                time_stop_dte=config.TIME_STOP_DTE, client_order_id=coid)
            notify(f"{sp.describe()}\n{msg}",
                   subject=f"Opened {sp.kind} {sp.underlying}")

        self.store.log_decision(cycle=self.cycle_n, underlying=underlying, regime=reg.name,
                                view=asdict(v), proposal=sp.kind, decision="submit",
                                gate="all", reason=msg,
                                payload={"describe": sp.describe(), "fill": msg,
                                         "critic": crit})
        return out

    # ---------------------------------------------------------------- cycle
    def run_once(self, *, allow_new: bool = True) -> dict:
        self.cycle_n += 1
        started = utcnow()
        log.info("=" * 78)
        log.info("cycle %d | account=%s | dry_run=%s | %s",
                 self.cycle_n, config.ACCOUNT, self.ex.dry_run, started)

        obs = self.observe()
        acct, clock = obs["account"], obs["clock"]

        # Retire stale working orders first: a live order that will never fill
        # still blocks every overlapping structure at the broker. Cancelling here
        # means _clear_never_filled() sees it terminal on the next cycle.
        stale = self._cancel_stale_orders()

        # Drop never-filled rows BEFORE reconciling, so the picture reconcile
        # reports — and the heat the risk gates compute — reflects the broker.
        cleared = self._clear_never_filled()
        rec = monitor.reconcile(self.store, obs["positions"])
        rec["cleared_never_filled"] = cleared
        rec["cancelled_stale"] = stale
        # Retire ghosts AFTER reconcile — it is what identifies them — and before
        # the risk book is built, so a retired row stops consuming heat this
        # cycle rather than the next one.
        rec["retired_ghosts"] = self._retire_ghosts(rec.get("ghosts"))
        if not rec["clean"]:
            log.warning("RECONCILE: ghosts=%s partial=%s orphans=%s",
                        rec["ghosts"], rec.get("partial"), rec["orphans"])

        book = RK.Book.from_account(acct, self.store.tracked_for_book())
        book.orders_last_hour = self._orders_last_hour()

        cb = RK.circuit_breakers(book, halted_flag=self._halted())
        if not cb:
            log.critical("CIRCUIT BREAKER [%s]: %s", cb.gate, cb.reason)
            notify(f"HALTED [{cb.gate}]\n{cb.reason}\n"
                   f"account {config.ACCOUNT} ({config.ACCOUNT_NUMBER})\n"
                   f"equity ${book.equity:,.2f}",
                   subject=f"Agent HALTED — {cb.gate}")
            res = self.ex.halt_everything(cb.reason)
            # Only a real run may engage the persistent kill switch. halt_everything()
            # already no-ops when dry, but this write was unguarded — so a rehearsal
            # left a HALTED file behind and g_kill_switch then blocked every LIVE
            # cycle until someone deleted it by hand.
            if self.ex.dry_run:
                log.warning("dry run — not writing %s; a live cycle would halt here",
                            HALT_FILE.name)
            else:
                HALT_FILE.write_text(f"{utcnow()} {cb.gate}: {cb.reason}\n")
            self.store.log_decision(cycle=self.cycle_n, underlying="*", regime="-", view={},
                                    proposal="", decision="halt", gate=cb.gate,
                                    reason=cb.reason, payload=res)
            return {"cycle": self.cycle_n, "halted": True, "gate": cb.gate,
                    "reason": cb.reason, "action": res}

        exits = self.manage_open_positions()

        if self.rehearse:
            log.warning("REHEARSAL MODE — pretending the market is open")
            clock = dict(clock, is_open=True)
        mg = RK.market_gates(clock, allow_new=allow_new)
        results = []
        if not mg:
            log.info("no new positions: %s", mg.reason)
        else:
            for u in config.UNIVERSE:
                try:
                    results.append(self.consider(u, book, clock))
                    book = RK.Book.from_account(self.c.account(), self.store.tracked_for_book())
                    book.orders_last_hour = self._orders_last_hour()
                except AlpacaError as e:
                    log.error("%s: %s", u, e)
                    results.append({"underlying": u, "decision": "error",
                                    "reason": f"[{e.status}] {e.message[:150]}"})
                except Exception as e:
                    log.exception("%s: unexpected", u)
                    results.append({"underlying": u, "decision": "error", "reason": str(e)[:200]})

        # Crypto runs outside the equity-session gate entirely: `mg` is about
        # /v2/clock and crypto has no clock. Off by default — see
        # config.CRYPTO_ENABLED and docs/BACKTEST.md Part 8.
        crypto = self.crypto_pass(float(acct["equity"]), allow_new=allow_new)

        summary = {
            "cycle": self.cycle_n, "ts": started, "halted": False,
            "equity": float(acct["equity"]),
            "market_open": bool(clock.get("is_open")),
            "crypto": crypto,
            "reconcile": rec, "exits": exits, "considered": results,
            "open_positions": len(self.store.open_positions()),
            "rate_remaining": self.c.gov.remaining,
        }
        log.info("cycle %d done | equity $%s | open %d | submits %d",
                 self.cycle_n, acct["equity"], summary["open_positions"],
                 sum(1 for r in results if r.get("decision") == "submit"))
        return summary

    def run_forever(self, interval: int = None, *, allow_new: bool = True) -> None:
        """Cycle until stopped. `allow_new=False` manages exits only.

        run_once() was called with no arguments here, so allow_new defaulted to
        True on every cycle and `run.py loop --no-new` silently ignored the flag.
        market_gates() was fixed to honour it this morning; the loop never
        reached the gate with the right value. That is the exact path Friday
        needs — stop opening at 15:00 ET, keep managing exits.
        """
        interval = interval or config.POLL_SECONDS
        log.info("starting loop, interval %ss, allow_new=%s", interval, allow_new)
        while True:
            try:
                self.run_once(allow_new=allow_new)
            except KeyboardInterrupt:
                log.info("stopped by user")
                return
            except Exception:
                log.exception("cycle failed — continuing")
            time.sleep(interval)
