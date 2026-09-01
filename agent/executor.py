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


def marketable_limit(spread: Spread, *, aggression: float = 0.0) -> float:
    """Price a spread for execution.

    aggression 0.0 = at mid; 1.0 = fully cross the spread. Used by the re-price
    ladder: start at mid, walk toward the far side until filled.
    """
    total_bid = total_ask = 0.0
    for leg in spread.legs:
        v = leg.view
        if v is None:
            return spread.net_price
        if leg.side == "buy":
            total_bid += v.bid
            total_ask += v.ask
        else:
            total_bid -= v.ask
            total_ask -= v.bid
    mid = (total_bid + total_ask) / 2.0
    far = total_ask
    price = mid + aggression * (far - mid)
    return round(price, 2)


def price_ladder(spread: Spread, steps: int = 4) -> list:
    """Successive prices to walk through: mid -> progressively more aggressive."""
    return [marketable_limit(spread, aggression=i / steps) for i in range(steps + 1)]
