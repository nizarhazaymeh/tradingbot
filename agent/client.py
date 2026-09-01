"""Alpaca REST client — trading + market data, with first-class options support.

Retry/idempotency approach follows Alpaca's own guidance:
  * 429 / 5xx are retried with exponential backoff
  * order submission is NEVER blind-retried; we look it up by client_order_id
  * throttling is driven by X-RateLimit-* response headers, not a hardcoded ceiling
"""
from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

from . import config

log = logging.getLogger(__name__)

RETRY_STATUS = (429, 500, 502, 503, 504)


class AlpacaError(RuntimeError):
    def __init__(self, status: int, message: str, path: str = ""):
        self.status, self.message, self.path = status, message, path
        super().__init__(f"[{status}] {path} {message}")


class RateGovernor:
    """Slow down as the rate-limit budget drains, instead of waiting to be throttled."""

    def __init__(self, floor: float = 0.15):
        self.limit = self.remaining = self.reset = 0
        self.floor = floor
        self.min_remaining = None

    def observe(self, headers) -> None:
        try:
            self.limit = int(headers.get("X-RateLimit-Limit") or 0)
            self.remaining = int(headers.get("X-RateLimit-Remaining") or 0)
            self.reset = int(headers.get("X-RateLimit-Reset") or 0)
        except (TypeError, ValueError):
            return
        if self.limit:
            self.min_remaining = (
                self.remaining if self.min_remaining is None
                else min(self.min_remaining, self.remaining)
            )

    def pause(self) -> None:
        if not self.limit or self.remaining / self.limit > self.floor:
            return
        wait = max(0, self.reset - int(time.time())) / max(1, self.remaining)
        if 0 < wait < 30:
            log.warning("rate budget low (%s/%s) — pausing %.1fs",
                        self.remaining, self.limit, wait)
            time.sleep(wait)


class AlpacaClient:
    def __init__(self, key: str = None, secret: str = None, timeout: int = 30,
                 verify_account: str = None):
        self.key = key or config.API_KEY
        self.secret = secret or config.SECRET_KEY
        if not self.key or not self.secret:
            raise RuntimeError("Alpaca credentials missing — check .env and ACCOUNT=")
        self.timeout = timeout
        self.gov = RateGovernor()
        if verify_account:
            self.assert_account(verify_account)

    def assert_account(self, expected_number: str) -> dict:
        """Refuse to proceed unless the credentials belong to the expected account.

        Keys are generated per paper account, and Alpaca's dashboard issues them
        for whichever account is *active* — so it is easy to paste DEV keys into a
        COMP slot and never notice. Trading the wrong account would either
        contaminate the judged one or leave it empty at the deadline.
        """
        a = self.account()
        got = a.get("account_number")
        if got != expected_number:
            raise RuntimeError(
                f"ACCOUNT MISMATCH: these credentials belong to {got}, "
                f"but {expected_number} was expected. Refusing to continue.")
        return a

    # ------------------------------------------------------------------ http
    def _request(self, method: str, path: str, base: str = None,
                 params: dict = None, body: dict = None, retries: int = 3) -> Any:
        url = (base or config.TRADE_BASE) + path
        if params:
            clean = {k: v for k, v in params.items() if v is not None}
            if clean:
                url = f"{url}?{urllib.parse.urlencode(clean)}"

        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("APCA-API-KEY-ID", self.key)
        req.add_header("APCA-API-SECRET-KEY", self.secret)
        req.add_header("Accept", "application/json")
        if data:
            req.add_header("Content-Type", "application/json")

        self.gov.pause()
        last = None
        for attempt in range(1, retries + 1):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    self.gov.observe(resp.headers)
                    raw = resp.read().decode()
                    return json.loads(raw) if raw else {}
            except urllib.error.HTTPError as e:
                detail = e.read().decode(errors="replace")[:500]
                if e.code in RETRY_STATUS and attempt < retries:
                    wait = 2 ** attempt
                    log.warning("%s %s -> %s, retry in %ss", method, path, e.code, wait)
                    time.sleep(wait)
                    last = AlpacaError(e.code, detail, path)
                    continue
                raise AlpacaError(e.code, detail, path)
            except urllib.error.URLError as e:
                if attempt < retries:
                    time.sleep(2 ** attempt)
                    last = AlpacaError(0, str(e.reason), path)
                    continue
                raise AlpacaError(0, f"network: {e.reason}", path)
        raise last

    def _data(self, path: str, params: dict = None) -> Any:
        return self._request("GET", path, base=config.DATA_BASE, params=params)

    # --------------------------------------------------------------- account
    def account(self) -> dict:
        return self._request("GET", "/v2/account")

    def account_config(self) -> dict:
        return self._request("GET", "/v2/account/configurations")

    def set_account_config(self, **kw) -> dict:
        return self._request("PATCH", "/v2/account/configurations", body=kw)

    def portfolio_history(self, period="1W", timeframe="15Min") -> dict:
        return self._request("GET", "/v2/account/portfolio/history",
                             params={"period": period, "timeframe": timeframe,
                                     "intraday_reporting": "market_hours"})

    def activities(self, activity_types: str = None, page_size: int = 100) -> list:
        return self._request("GET", "/v2/account/activities",
                             params={"activity_types": activity_types,
                                     "page_size": page_size}) or []

    # ----------------------------------------------------------------- clock
    def clock(self) -> dict:
        return self._request("GET", "/v2/clock")

    def calendar(self, start: str, end: str) -> list:
        return self._request("GET", "/v2/calendar", params={"start": start, "end": end})

    # ------------------------------------------------------------- positions
    def positions(self) -> List[dict]:
        return self._request("GET", "/v2/positions") or []

    def option_positions(self) -> List[dict]:
        return [p for p in self.positions() if p.get("asset_class") == "us_option"]

    def close_position(self, symbol: str, qty: str = None, percentage: str = None) -> dict:
        params = {}
        if qty:
            params["qty"] = qty
        elif percentage:
            params["percentage"] = percentage
        return self._request("DELETE", f"/v2/positions/{urllib.parse.quote(symbol)}",
                             params=params or None)

    def close_all_positions(self, cancel_orders: bool = True) -> Any:
        return self._request("DELETE", "/v2/positions",
                             params={"cancel_orders": str(cancel_orders).lower()})

    # ---------------------------------------------------------------- orders
    def submit_order(self, body: dict) -> dict:
        """Submit once. Never blind-retried — see recover_order()."""
        return self._request("POST", "/v2/orders", body=body, retries=1)

    def recover_order(self, client_order_id: str) -> Optional[dict]:
        """After an ambiguous failure: did the order actually land?"""
        try:
            return self._request("GET", "/v2/orders:by_client_order_id",
                                 params={"client_order_id": client_order_id})
        except AlpacaError as e:
            if e.status in (404, 422):
                return None
            raise

    def orders(self, status: str = "open", limit: int = 100, nested: bool = True) -> List[dict]:
        return self._request("GET", "/v2/orders",
                             params={"status": status, "limit": limit,
                                     "nested": str(nested).lower()}) or []

    def get_order(self, order_id: str) -> dict:
        return self._request("GET", f"/v2/orders/{order_id}")

    def replace_order(self, order_id: str, *, limit_price: str = None,
                      qty: str = None, client_order_id: str = None) -> dict:
        """PATCH an open order. Returns a NEW order object with a new id.

        Used by the fill-chasing ladder: replacing keeps one order lineage, so a
        crash mid-chase leaves exactly one recoverable order rather than several.
        """
        body = {k: v for k, v in
                {"limit_price": limit_price, "qty": qty,
                 "client_order_id": client_order_id}.items() if v is not None}
        return self._request("PATCH", f"/v2/orders/{order_id}", body=body, retries=1)

    def cancel_order(self, order_id: str) -> None:
        self._request("DELETE", f"/v2/orders/{order_id}")

    def cancel_all_orders(self) -> Any:
        return self._request("DELETE", "/v2/orders")

    # ------------------------------------------------------- option contracts
    def option_contracts(self, underlying: str, *, exp_gte: str = None, exp_lte: str = None,
                         exp: str = None, kind: str = None, strike_gte: float = None,
                         strike_lte: float = None, limit: int = 1000,
                         page_token: str = None) -> dict:
        return self._request("GET", "/v2/options/contracts", params={
            "underlying_symbols": underlying,
            "status": "active",
            "expiration_date": exp,
            "expiration_date_gte": exp_gte,
            "expiration_date_lte": exp_lte,
            "type": kind,
            "strike_price_gte": strike_gte,
            "strike_price_lte": strike_lte,
            "limit": limit,
            "page_token": page_token,
        })

    def all_option_contracts(self, underlying: str, **kw) -> List[dict]:
        out, token = [], None
        while True:
            page = self.option_contracts(underlying, page_token=token, **kw)
            out.extend(page.get("option_contracts") or [])
            token = page.get("next_page_token") or page.get("page_token")
            if not token or len(out) > 8000:
                return out

    def expirations(self, underlying: str, exp_gte: str, exp_lte: str) -> List[str]:
        rows = self.all_option_contracts(underlying, exp_gte=exp_gte, exp_lte=exp_lte, limit=1000)
        return sorted({r["expiration_date"] for r in rows})

    # ---------------------------------------------------------- options data
    def option_chain(self, underlying: str, *, exp: str = None, exp_gte: str = None,
                     exp_lte: str = None, strike_gte: float = None, strike_lte: float = None,
                     kind: str = None, limit: int = 1000) -> Dict[str, dict]:
        """Whole chain in ONE call: quote + trade + Greeks + IV per contract."""
        out, token = {}, None
        while True:
            page = self._data(f"/v1beta1/options/snapshots/{urllib.parse.quote(underlying)}", {
                "feed": config.OPTIONS_FEED,
                "expiration_date": exp,
                "expiration_date_gte": exp_gte,
                "expiration_date_lte": exp_lte,
                "strike_price_gte": strike_gte,
                "strike_price_lte": strike_lte,
                "type": kind,
                "limit": limit,
                "page_token": token,
            })
            out.update(page.get("snapshots") or {})
            token = page.get("next_page_token")
            if not token or len(out) > 6000:
                return out

    def option_snapshots(self, symbols: List[str]) -> Dict[str, dict]:
        if not symbols:
            return {}
        res = self._data("/v1beta1/options/snapshots",
                         {"symbols": ",".join(symbols), "feed": config.OPTIONS_FEED})
        return res.get("snapshots") or {}

    # ------------------------------------------------------------ stock data
    def stock_snapshots(self, symbols: List[str]) -> Dict[str, dict]:
        if not symbols:
            return {}
        return self._data("/v2/stocks/snapshots",
                          {"symbols": ",".join(symbols), "feed": config.STOCK_FEED}) or {}

    # minutes per bar, used to derive a `start` when the caller omits one
    _TF_MINUTES = {"1Min": 1, "5Min": 5, "15Min": 15, "30Min": 30,
                   "1Hour": 60, "4Hour": 240, "1Day": 1440, "1Week": 10080}

    def stock_bars(self, symbols: List[str], timeframe="1Day", limit=200,
                   start: str = None, adjustment="all") -> Dict[str, list]:
        """Historical bars, batched across symbols.

        Alpaca returns ZERO bars when `start` is omitted, so we derive one from
        `limit` and the timeframe (with slack for weekends/holidays).
        """
        if start is None:
            from datetime import datetime, timedelta, timezone
            mins = self._TF_MINUTES.get(timeframe, 1440)
            span = timedelta(minutes=mins * limit)
            if mins >= 1440:                      # daily+: pad for non-trading days
                span *= 1.6
            else:                                 # intraday: ~6.5h of session per day
                span *= 3.7
            start = (datetime.now(timezone.utc) - span).strftime("%Y-%m-%d")

        out, token = {}, None
        while True:
            res = self._data("/v2/stocks/bars", {
                "symbols": ",".join(symbols), "timeframe": timeframe, "limit": 10000,
                "start": start, "adjustment": adjustment, "feed": config.STOCK_FEED,
                "page_token": token, "sort": "asc",
            })
            for sym, rows in (res.get("bars") or {}).items():
                out.setdefault(sym, []).extend(rows)
            token = res.get("next_page_token")
            if not token:
                break
        return {k: v[-limit:] for k, v in out.items()}

    def latest_trade(self, symbol: str) -> Optional[float]:
        res = self._data("/v2/stocks/trades/latest",
                         {"symbols": symbol, "feed": config.STOCK_FEED})
        t = (res.get("trades") or {}).get(symbol)
        return float(t["p"]) if t else None

    def news(self, symbols: List[str], limit: int = 20) -> List[dict]:
        res = self._data("/v1beta1/news", {"symbols": ",".join(symbols), "limit": limit,
                                           "exclude_contentless": "true"})
        return res.get("news") or []

    def corporate_actions(self, symbols: List[str], start: str, end: str) -> dict:
        return self._data("/v1beta1/corporate-actions",
                          {"symbols": ",".join(symbols), "start": start, "end": end}) or {}
