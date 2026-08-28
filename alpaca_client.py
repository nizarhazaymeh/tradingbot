"""Minimal Alpaca REST client — US stocks and crypto, paper or live.

Auth is just two headers (no request signing, unlike Binance):
    APCA-API-KEY-ID / APCA-API-SECRET-KEY

Endpoints:
    paper trading   https://paper-api.alpaca.markets
    live trading    https://api.alpaca.markets
    market data     https://data.alpaca.markets   (same host for both)

Paper and live credentials are SEPARATE — a live key will not work against
the paper endpoint, or vice versa. Generate them at https://app.alpaca.markets
(Home -> API Keys); the secret is shown only once.

Standard library only (urllib), matching notifier.py — no new dependencies.
"""
import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

log = logging.getLogger("alpaca")

TRADE_PAPER = "https://paper-api.alpaca.markets"
TRADE_LIVE = "https://api.alpaca.markets"
DATA = "https://data.alpaca.markets"

# Binance-style interval -> Alpaca timeframe, so .env INTERVAL keeps working.
_TIMEFRAMES = {
    "1m": "1Min", "3m": "3Min", "5m": "5Min", "15m": "15Min", "30m": "30Min",
    "1h": "1Hour", "2h": "2Hour", "4h": "4Hour", "6h": "6Hour", "12h": "12Hour",
    "1d": "1Day", "3d": "3Day", "1w": "1Week", "1M": "1Month",
}


def to_timeframe(interval: str) -> str:
    """Map a Binance-style interval ("1h") to an Alpaca timeframe ("1Hour").

    Already-Alpaca values ("15Min", "1Day") pass through untouched.
    """
    return _TIMEFRAMES.get(interval, interval)


def is_crypto(symbol: str) -> bool:
    """Alpaca crypto pairs carry a slash (BTC/USD); stocks do not (AAPL)."""
    return "/" in symbol


def normalize_symbol(symbol: str) -> str:
    """Accept Binance-style crypto tickers and convert them to Alpaca pairs.

    BTCUSDT -> BTC/USD, ETHUSD -> ETH/USD, AAPL -> AAPL (unchanged).
    Alpaca settles crypto in USD, so a USDT pair maps onto the USD pair.
    """
    s = symbol.strip().upper()
    if "/" in s:
        return s
    for quote in ("USDT", "USDC", "USD"):
        # Only treat it as crypto if a real base remains (avoids mangling
        # a stock ticker that merely ends in these letters).
        if s.endswith(quote) and len(s) > len(quote) + 1:
            return f"{s[:-len(quote)]}/USD"
    return s


class AlpacaError(RuntimeError):
    """An error response from the Alpaca API (mirrors BinanceAPIException)."""

    def __init__(self, status: int, message: str):
        super().__init__(f"HTTP {status}: {message}")
        self.status = status
        self.message = message


class AlpacaClient:
    """Thin wrapper over the Alpaca trading + market data REST APIs."""

    def __init__(
        self,
        key: str,
        secret: str,
        paper: bool = True,
        feed: str = "iex",
        timeout: int = 20,
    ):
        if not key or not secret:
            raise AlpacaError(401, "Missing ALPACA_API_KEY / ALPACA_API_SECRET.")
        self.key = key
        self.secret = secret
        self.paper = paper
        self.feed = feed  # "iex" is free; "sip" needs a paid data subscription.
        self.timeout = timeout
        self.trade_base = TRADE_PAPER if paper else TRADE_LIVE

    # ------------------------------------------------------------------ #
    # HTTP
    # ------------------------------------------------------------------ #
    def _request(
        self,
        method: str,
        path: str,
        base: Optional[str] = None,
        params: Optional[dict] = None,
        body: Optional[dict] = None,
        retries: int = 3,
    ) -> Any:
        url = (base or self.trade_base) + path
        if params:
            clean = {k: v for k, v in params.items() if v is not None}
            url = f"{url}?{urllib.parse.urlencode(clean)}"

        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("APCA-API-KEY-ID", self.key)
        req.add_header("APCA-API-SECRET-KEY", self.secret)
        req.add_header("Accept", "application/json")
        if data:
            req.add_header("Content-Type", "application/json")

        last_err = None
        for attempt in range(1, retries + 1):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    raw = resp.read().decode()
                    return json.loads(raw) if raw else {}
            except urllib.error.HTTPError as e:
                detail = e.read().decode(errors="replace")[:400]
                # 429 = rate limited (200 req/min on the free plan), 5xx = transient.
                if e.code in (429, 500, 502, 503, 504) and attempt < retries:
                    wait = 2 ** attempt
                    log.warning("Alpaca %s %s -> %s, retrying in %ss",
                                method, path, e.code, wait)
                    time.sleep(wait)
                    last_err = AlpacaError(e.code, detail)
                    continue
                raise AlpacaError(e.code, detail)
            except urllib.error.URLError as e:
                if attempt < retries:
                    time.sleep(2 ** attempt)
                    last_err = AlpacaError(0, str(e.reason))
                    continue
                raise AlpacaError(0, f"Network error: {e.reason}")
        raise last_err  # pragma: no cover - loop always returns or raises

    # ------------------------------------------------------------------ #
    # Account / status
    # ------------------------------------------------------------------ #
    def get_account(self) -> dict:
        """Account snapshot: cash, equity, buying_power, status, ..."""
        return self._request("GET", "/v2/account")

    def get_clock(self) -> dict:
        """Market clock: {"is_open": bool, "next_open": ..., "next_close": ...}."""
        return self._request("GET", "/v2/clock")

    def is_market_open(self, symbol: str) -> bool:
        """Crypto trades 24/7; stocks only during US market hours."""
        if is_crypto(symbol):
            return True
        return bool(self.get_clock().get("is_open"))

    def get_asset(self, symbol: str) -> dict:
        """Asset metadata — tradability, fractionability, min order size."""
        return self._request("GET", "/v2/assets/" + urllib.parse.quote(symbol, safe=""))

    # ------------------------------------------------------------------ #
    # Market data
    # ------------------------------------------------------------------ #
    def get_bars(self, symbol: str, interval: str, limit: int) -> List[dict]:
        """The most recent `limit` bars, oldest first.

        Sorted descending server-side (so we get the LATEST bars rather than
        the oldest available) and reversed here.
        """
        timeframe = to_timeframe(interval)
        if is_crypto(symbol):
            path, params = "/v1beta3/crypto/us/bars", {}
        else:
            path, params = "/v2/stocks/bars", {"feed": self.feed, "adjustment": "raw"}
        params.update({"symbols": symbol, "timeframe": timeframe,
                       "limit": limit, "sort": "desc"})

        payload = self._request("GET", path, base=DATA, params=params)
        bars = (payload.get("bars") or {}).get(symbol) or []
        return list(reversed(bars))  # oldest -> newest

    def get_closes(self, symbol: str, interval: str, limit: int) -> List[float]:
        """Closing prices of the last `limit` CLOSED bars.

        Fetches one extra bar and drops the newest, which is still forming —
        same convention as the Binance path in bot.py.
        """
        bars = self.get_bars(symbol, interval, limit + 1)
        if len(bars) > limit:
            bars = bars[:-1]
        return [float(b["c"]) for b in bars]

    def get_latest_price(self, symbol: str) -> float:
        """Latest trade price."""
        if is_crypto(symbol):
            payload = self._request("GET", "/v1beta3/crypto/us/latest/trades",
                                    base=DATA, params={"symbols": symbol})
            trade = (payload.get("trades") or {}).get(symbol) or {}
        else:
            path = f"/v2/stocks/{urllib.parse.quote(symbol)}/trades/latest"
            payload = self._request("GET", path, base=DATA, params={"feed": self.feed})
            trade = payload.get("trade") or {}
        if "p" not in trade:
            raise AlpacaError(404, f"No recent trade for {symbol}")
        return float(trade["p"])

    # ------------------------------------------------------------------ #
    # Positions
    # ------------------------------------------------------------------ #
    @staticmethod
    def _position_symbol(symbol: str) -> str:
        """Positions are keyed without the slash: BTC/USD -> BTCUSD."""
        return symbol.replace("/", "")

    def list_positions(self) -> List[dict]:
        return self._request("GET", "/v2/positions")

    def get_position(self, symbol: str) -> Optional[dict]:
        """The open position for `symbol`, or None if flat."""
        try:
            return self._request(
                "GET", "/v2/positions/" + urllib.parse.quote(
                    self._position_symbol(symbol), safe=""),
            )
        except AlpacaError as e:
            if e.status == 404:
                return None
            raise

    def position_qty(self, symbol: str) -> float:
        pos = self.get_position(symbol)
        return float(pos["qty"]) if pos else 0.0

    # ------------------------------------------------------------------ #
    # Orders
    # ------------------------------------------------------------------ #
    def submit_market_order(
        self,
        symbol: str,
        side: str,
        notional: Optional[float] = None,
        qty: Optional[float] = None,
    ) -> dict:
        """Place a market order by dollar amount (`notional`) or units (`qty`)."""
        if (notional is None) == (qty is None):
            raise ValueError("Pass exactly one of notional= or qty=.")
        body = {
            "symbol": symbol,
            "side": side,
            "type": "market",
            # Crypto rejects "day"; stocks reject "gtc" on market orders.
            "time_in_force": "gtc" if is_crypto(symbol) else "day",
        }
        if notional is not None:
            body["notional"] = str(round(notional, 2))
        else:
            body["qty"] = str(qty)
        return self._request("POST", "/v2/orders", body=body)

    def close_position(self, symbol: str) -> dict:
        """Liquidate the whole position (simpler than computing a sell qty)."""
        return self._request(
            "DELETE", "/v2/positions/" + urllib.parse.quote(
                self._position_symbol(symbol), safe=""),
        )

    def get_order(self, order_id: str) -> dict:
        return self._request("GET", f"/v2/orders/{order_id}")

    def fill_price(self, order: dict, tries: int = 5, delay: float = 1.0) -> float:
        """Average fill price, polling briefly since market fills are async."""
        price = order.get("filled_avg_price")
        if price:
            return float(price)
        order_id = order.get("id")
        for _ in range(tries):
            time.sleep(delay)
            try:
                fresh = self.get_order(order_id)
            except AlpacaError:
                break
            if fresh.get("filled_avg_price"):
                return float(fresh["filled_avg_price"])
        return 0.0
