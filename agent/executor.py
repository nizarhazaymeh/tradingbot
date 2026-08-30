"""Order execution with idempotency and ambiguous-failure recovery.

The dangerous case is not an error — it's a TIMEOUT, where we don't know whether
the order landed. Never blind-retry: look it up by client_order_id first.
"""
from __future__ import annotations

import logging
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
