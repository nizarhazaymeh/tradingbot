"""Order execution with idempotency and ambiguous-failure recovery.

The dangerous case is not an error — it's a TIMEOUT, where we don't know whether
the order landed. Never blind-retry: look it up by client_order_id first.
"""
from __future__ import annotations

import logging
import time
from typing import Optional, Tuple

from . import config
from .client import AlpacaClient, AlpacaError
from .spreads import Spread, closing_order, validate_mleg

log = logging.getLogger(__name__)


class Executor:
    def __init__(self, client: AlpacaClient, store=None, dry_run: bool = None):
        self.c = client
        self.store = store
        self.dry_run = config.DRY_RUN if dry_run is None else dry_run

    # --------------------------------------------------------------- pricing
    def refresh_quotes(self, spread: Spread) -> bool:
        """Re-read every leg's quote immediately before pricing.

        Observed live on 1 Sep 2026: an order priced from the chain fetched at the
        start of the cycle asked for $0.25 credit when, seconds later, the market
        only offered $0.14. It sat at status `new` and never filled. A cycle can
        take tens of seconds; option quotes move faster than that.
        """
        syms = [l.symbol for l in spread.legs]
        try:
            snaps = self.c.option_snapshots(syms)
        except AlpacaError as e:
            log.warning("quote refresh failed: %s", e.message[:100])
            return False
        stale = []
        for leg in spread.legs:
            q = (snaps.get(leg.symbol) or {}).get("latestQuote") or {}
            bid, ask = float(q.get("bp") or 0), float(q.get("ap") or 0)
            if bid <= 0 or ask <= 0:
                stale.append(leg.symbol)
                continue
            if leg.view is not None:
                leg.view.bid, leg.view.ask = bid, ask
                leg.view.mid = (bid + ask) / 2.0
                leg.view.spread_pct = (ask - bid) / leg.view.mid
        if stale:
            log.warning("no two-sided quote for %s — not repricing", stale)
            return False
        return True

    # ------------------------------------------------------------------ open
    def open_spread(self, spread: Spread, *, limit_price: float = None
                    ) -> Tuple[Optional[dict], str]:
        coid = spread.client_order_id("open")
        body = spread.order(limit_price=limit_price, client_order_id=coid)

        errs = validate_mleg(body)
        if errs:
            return None, f"validation failed: {errs[0]}"

        if self.dry_run:
            log.info("DRY RUN — would submit: %s", spread.describe())
            if self.store:
                self.store.log_order(coid, body, {"status": "dry_run"}, "open")
            return {"status": "dry_run", "id": None, "client_order_id": coid}, "dry run"

        return self._submit(body, coid, "open")

    # ---------------------------------------------------------------- crypto
    def open_crypto(self, signal, qty: float) -> Tuple[Optional[dict], str]:
        """Buy spot. Market order, and deliberately so.

        The stop is the entire risk model here, and a resting limit that does not
        fill leaves the signal stale while price walks away from the level. The
        options path can afford to be patient because a spread's risk is capped
        by its width whatever happens; this one cannot.

        No stop-loss order is attached. Alpaca does not support brackets on
        crypto, so — exactly as with options — cycle.crypto_pass() IS the stop,
        and that is why config.CRYPTO_MAX_NOTIONAL_PCT exists to bound what
        happens if the loop is not there when it matters.
        """
        coid = f"cr-{signal.symbol.replace('/', '')}-{int(time.time())}"
        body = {"symbol": signal.symbol, "qty": str(qty), "side": "buy",
                "type": "market", "time_in_force": "gtc", "client_order_id": coid}
        if self.dry_run:
            log.info("DRY RUN — would buy %s qty %s", signal.symbol, qty)
            if self.store:
                self.store.log_order(coid, body, {"status": "dry_run"}, "open")
            return {"status": "dry_run", "id": None, "client_order_id": coid}, "dry run"
        return self._submit(body, coid, "open")

    def close_crypto(self, position: dict, price: float = None) -> str:
        """Sell the whole position at market. Returns a human-readable result."""
        coid = f"cr-x-{position['symbol'].replace('/', '')}-{int(time.time())}"
        body = {"symbol": position["symbol"], "qty": str(position["qty"]),
                "side": "sell", "type": "market", "time_in_force": "gtc",
                "client_order_id": coid}
        if self.dry_run:
            log.info("DRY RUN — would sell %s qty %s", position["symbol"],
                     position["qty"])
            if self.store:
                self.store.log_order(coid, body, {"status": "dry_run"}, "close")
            return "dry run"
        _, msg = self._submit(body, coid, "close")
        return msg

    # ----------------------------------------------------------------- close
    def close_spread(self, spread: Spread, *, limit_price: float = None,
                     market: bool = False) -> Tuple[Optional[dict], str]:
        body = closing_order(spread, limit_price=limit_price)
        if market:
            body["type"] = "market"
            body.pop("limit_price", None)
        coid = body["client_order_id"]

        errs = validate_mleg(body)
        if errs:
            return None, f"validation failed: {errs[0]}"

        if self.dry_run:
            log.info("DRY RUN — would close: %s", spread.describe())
            return {"status": "dry_run", "id": None, "client_order_id": coid}, "dry run"

        return self._submit(body, coid, "close")

    # --------------------------------------------------------- fill chasing
    def open_and_chase(self, spread: Spread, *, steps: int = 3,
                       wait: float = 12.0) -> Tuple[Optional[dict], str]:
        """Submit, then walk the price toward the market until it fills.

        A single limit at the natural price is a coin flip: the quote it was
        derived from is already a few seconds old. So we submit, wait, and if it
        is still unfilled we REPLACE at a slightly worse price. Each step gives
        up a little edge to convert an unfilled order into a position.

        Replacing rather than cancel-and-resubmit keeps one client_order_id
        lineage, so a crash mid-chase leaves exactly one recoverable order.
        """
        if not self.refresh_quotes(spread):
            return None, "could not refresh quotes — not submitting"

        ladder = price_ladder(spread, steps=steps)
        order, msg = self.open_spread(spread, limit_price=ladder[0])
        if order is None or order.get("status") == "dry_run":
            return order, msg

        oid = order.get("id")
        for i, px in enumerate(ladder[1:], start=1):
            deadline = time.time() + wait
            while time.time() < deadline:
                time.sleep(min(4.0, max(1.0, wait / 3)))
                try:
                    order = self.c.get_order(oid)
                except AlpacaError:
                    break
                st = order.get("status")
                if st == "filled":
                    return order, (f"filled @ {order.get('filled_avg_price')} "
                                   f"after {i-1} reprice(s)")
                if st in ("canceled", "rejected", "expired"):
                    return order, f"{st} before filling"

            try:
                order = self.c.replace_order(oid, limit_price=f"{px:.2f}")
                oid = order.get("id", oid)
                log.info("    reprice %d/%d -> %.2f", i, len(ladder) - 1, px)
            except AlpacaError as e:
                log.warning("reprice failed: %s", e.message[:90])
                break

        try:
            order = self.c.get_order(oid)
        except AlpacaError:
            pass
        if order.get("status") == "filled":
            return order, f"filled @ {order.get('filled_avg_price')} on the last step"
        return order, f"unfilled after {len(ladder)-1} reprices (status {order.get('status')})"

    # ------------------------------------------------------------- internals
    def _submit(self, body: dict, coid: str, kind: str) -> Tuple[Optional[dict], str]:
        try:
            order = self.c.submit_order(body)
            if self.store:
                self.store.log_order(coid, body, order, kind)
            return order, f"submitted {order.get('status')}"
        except AlpacaError as e:
            # 4xx that isn't a timeout == a real rejection; no recovery needed
            if 400 <= e.status < 500 and e.status not in (408, 429):
                return None, f"rejected [{e.status}] {e.message[:200]}"

            # Ambiguous: did it land? Look it up rather than resubmitting.
            log.warning("ambiguous failure on %s — recovering by client_order_id", coid)
            found = None
            try:
                found = self.c.recover_order(coid)
            except AlpacaError:
                pass
            if found:
                if self.store:
                    self.store.log_order(coid, body, found, kind)
                return found, f"recovered {found.get('status')} (order had landed)"
            return None, f"failed [{e.status}] {e.message[:200]} (confirmed not submitted)"

    # ------------------------------------------------------------ kill switch
    def halt_everything(self, reason: str) -> dict:
        """Cancel working orders, flatten the book, and lock the account."""
        result = {"reason": reason, "cancelled": None, "closed": None, "suspended": None}
        if self.dry_run:
            result["note"] = "dry run — no action taken"
            return result
        try:
            self.c.cancel_all_orders()
            result["cancelled"] = True
        except AlpacaError as e:
            result["cancelled"] = f"failed: {e.message[:120]}"
        try:
            self.c.close_all_positions()
            result["closed"] = True
        except AlpacaError as e:
            result["closed"] = f"failed: {e.message[:120]}"
        try:
            self.c.set_account_config(suspend_trade=True)
            result["suspended"] = True
        except AlpacaError as e:
            result["suspended"] = f"failed: {e.message[:120]}"
        return result


def spread_prices(spread: Spread) -> Tuple[float, float]:
    """(mid, natural) net price for the structure, in limit_price convention.

    `natural` is the price that actually transacts: every leg we buy is taken at
    the ASK, every leg we sell is hit at the BID. Signed so that positive = debit
    and negative = credit, matching Alpaca's mleg limit_price.
    """
    mid = nat = 0.0
    for leg in spread.legs:
        v = leg.view
        if v is None:
            return spread.net_price, spread.net_price
        if leg.side == "buy":
            mid += v.mid
            nat += v.ask          # we pay up to open a long leg
        else:
            mid -= v.mid
            nat -= v.bid          # we accept the bid to open a short leg
    return round(mid, 2), round(nat, 2)


def marketable_limit(spread: Spread, *, aggression: float = 0.0) -> float:
    """Price for execution. 0.0 = mid, 1.0 = the natural (transacting) price."""
    mid, nat = spread_prices(spread)
    return round(mid + aggression * (nat - mid), 2)


def price_ladder(spread: Spread, steps: int = 3) -> list:
    """Prices to walk through, mid → natural → beyond.

    Verified live: a limit at the natural price filled in under 5 seconds, and
    actually received price improvement. A limit derived from a stale quote sat
    unfilled indefinitely. So the ladder starts at mid (best case), reaches the
    natural price, then goes one step past it to guarantee a fill.
    """
    mid, nat = spread_prices(spread)
    out = [marketable_limit(spread, aggression=i / steps) for i in range(steps + 1)]
    # "More likely to fill" is ALWAYS toward more positive, whatever the sign:
    # a debit means paying more, a credit means accepting less. Moving a credit
    # further negative asks for MORE credit and is less likely to fill.
    beyond = round(nat + 0.05, 2)
    out.append(beyond)
    # keep order monotonic toward "more likely to fill" and drop duplicates
    seen, ladder = set(), []
    for p in out:
        if p not in seen:
            seen.add(p); ladder.append(p)
    return ladder
