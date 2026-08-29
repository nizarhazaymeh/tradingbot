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
import uuid
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


_TF_MINUTES = {"Min": 1, "T": 1, "Hour": 60, "H": 60,
               "Day": 1440, "D": 1440, "Week": 10080, "W": 10080,
               "Month": 43200, "M": 43200}


def timeframe_minutes(timeframe: str) -> int:
    """"15Min" -> 15, "4Hour" -> 240, "1Day" -> 1440."""
    num = "".join(c for c in timeframe if c.isdigit()) or "1"
    unit = "".join(c for c in timeframe if c.isalpha())
    return int(num) * _TF_MINUTES.get(unit, 60)


def lookback_start(timeframe: str, limit: int, crypto: bool = False) -> str:
    """A `start` date far enough back to contain `limit` bars.

    Alpaca REQUIRES an explicit start: without one the bars endpoints default to
    a window that is empty outside market hours, so every request comes back
    with nothing. Stocks only print bars ~6.5h a day, 5 days a week, so the
    calendar span needed is roughly 5x the raw bar time — doubled here for
    holidays, with a floor for short requests.
    """
    from datetime import datetime, timedelta, timezone
    span = timeframe_minutes(timeframe) * max(limit, 1) * (1.0 if crypto else 5.0)
    days = min((span / 1440.0) * 2 + 5, 365 * 5)
    return (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()


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

    def minutes_to_close(self) -> Optional[float]:
        """Minutes until the US session closes, or None if shut / unknown.

        Reads `next_close` off the clock, so early-close days (13:00 half days)
        are handled without a separate calendar call.
        """
        clock = self.get_clock()
        if not clock.get("is_open"):
            return None
        try:
            from datetime import datetime
            now = datetime.fromisoformat(str(clock["timestamp"]).replace("Z", "+00:00"))
            close = datetime.fromisoformat(str(clock["next_close"]).replace("Z", "+00:00"))
            return (close - now).total_seconds() / 60.0
        except Exception:
            return None

    def get_asset(self, symbol: str) -> dict:
        """Asset metadata — tradability, fractionability, min order size."""
        return self._request("GET", "/v2/assets/" + urllib.parse.quote(symbol, safe=""))

    # ------------------------------------------------------------------ #
    # Market data
    # ------------------------------------------------------------------ #
    PAGE_MAX = 10000  # data points per response

    def _bars_request(self, path, params, what=""):
        """One bars call, with a SIP -> IEX fallback if the feed is refused."""
        try:
            return self._request("GET", path, base=DATA, params=params)
        except AlpacaError as e:
            # SIP needs a data subscription; drop to the free IEX feed rather
            # than leaving the bot blind. IEX is thinner (it sees only IEX's own
            # volume), which hurts low-volume ETFs like FXB.
            if e.status == 403 and params.get("feed") == "sip":
                log.warning("SIP feed refused%s (%s) — falling back to IEX.",
                            what, e.message[:80])
                params["feed"] = "iex"
                return self._request("GET", path, base=DATA, params=params)
            raise

    def get_bars_multi(self, symbols: List[str], interval: str,
                       limit: int, max_pages: int = 40) -> Dict[str, List[dict]]:
        """Bars for several symbols, oldest first, keyed by symbol.

        Fetched ONE SYMBOL AT A TIME, deliberately. The endpoint does accept a
        comma-separated list, but multi-symbol responses fill symbol-by-symbol:
        with `limit` set you get the whole first symbol and nothing else, and
        without it you must merge many pages (11 requests for a 4h batch of 4
        symbols — worse than 4 single-symbol calls). Per-symbol is both simpler
        and cheaper here, and a full watchlist costs ~10 requests per cycle
        against a 200/min budget.
        """
        timeframe = to_timeframe(interval)
        out: Dict[str, List[dict]] = {}
        for sym in symbols:
            crypto = is_crypto(sym)
            path = "/v1beta3/crypto/us/bars" if crypto else "/v2/stocks/bars"
            params = {"symbols": sym, "timeframe": timeframe, "sort": "desc",
                      "limit": min(self.PAGE_MAX, max(limit, 1)),
                      # Alpaca REQUIRES an explicit start: without one the window
                      # is empty outside market hours and nothing comes back.
                      "start": lookback_start(timeframe, limit, crypto=crypto)}
            if not crypto:
                params.update({"feed": self.feed, "adjustment": "raw"})

            collected, token, pages = [], None, 0
            while pages < max_pages and len(collected) < limit:
                if token:
                    params["page_token"] = token
                payload = self._bars_request(path, params, f" for {sym}")
                collected.extend((payload.get("bars") or {}).get(sym) or [])
                pages += 1
                token = payload.get("next_page_token")
                if not token:
                    break
            # Newest-first from the API -> trim, then flip to oldest-first,
            # which is what every indicator expects.
            out[sym] = list(reversed(collected[:limit]))
        return out

    def get_bars(self, symbol: str, interval: str, limit: int) -> List[dict]:
        """The most recent `limit` bars for one symbol, oldest first."""
        return self.get_bars_multi([symbol], interval, limit).get(symbol, [])

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
    def _submit(self, body: dict) -> dict:
        """POST an order exactly once, tagged with a unique client_order_id.

        Order submission is deliberately NOT retried. A retry after a lost
        response would place a SECOND position — far worse than a failed order.
        The client_order_id makes the attempt traceable, so a caller that loses
        the response can ask `get_order_by_client_id` what actually happened
        (and the bot's reconciliation pass catches an orphan either way).
        """
        body = dict(body)
        body.setdefault("client_order_id", "bot-" + uuid.uuid4().hex[:24])
        return self._request("POST", "/v2/orders", body=body, retries=1)

    def get_order_by_client_id(self, client_order_id: str) -> Optional[dict]:
        """Look an order up by the id we generated — for resolving a lost POST."""
        try:
            return self._request("GET", "/v2/orders:by_client_order_id",
                                 params={"client_order_id": client_order_id})
        except AlpacaError as e:
            if e.status == 404:
                return None
            raise

    def submit_market_order(
        self,
        symbol: str,
        side: str,
        notional: Optional[float] = None,
        qty: Optional[float] = None,
        client_order_id: Optional[str] = None,
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
        if client_order_id:
            body["client_order_id"] = client_order_id
        if notional is not None:
            body["notional"] = str(round(notional, 2))
        else:
            body["qty"] = str(qty)
        return self._submit(body)

    def submit_bracket_order(
        self,
        symbol: str,
        side: str,
        qty: int,
        take_profit_price: float,
        stop_loss_price: float,
        client_order_id: Optional[str] = None,
    ) -> dict:
        """Market entry with broker-side take-profit and stop-loss legs.

        The exit legs live on Alpaca's side as an OCO pair, so the position stays
        protected between polls — and even if this bot stops running.

        Constraints (Alpaca): stocks only (crypto has no bracket support) and
        WHOLE shares only (bracket is incompatible with fractional trading).
        """
        if is_crypto(symbol):
            raise AlpacaError(422, "Alpaca does not support bracket orders for crypto.")
        body = {
            "symbol": symbol,
            "side": side,
            "type": "market",
            "time_in_force": "day",
            "order_class": "bracket",
            "qty": str(int(qty)),
            "take_profit": {"limit_price": f"{take_profit_price:.2f}"},
            "stop_loss": {"stop_price": f"{stop_loss_price:.2f}"},
        }
        if client_order_id:
            body["client_order_id"] = client_order_id
        return self._submit(body)

    def list_orders(self, status: str = "open", symbols: Optional[str] = None) -> List[dict]:
        """Orders by status ("open", "closed", "all")."""
        return self._request("GET", "/v2/orders",
                             params={"status": status, "symbols": symbols})

    def cancel_order(self, order_id: str) -> None:
        self._request("DELETE", f"/v2/orders/{order_id}")

    def cancel_orders_for(self, symbol: str) -> int:
        """Cancel every open order on `symbol`; returns how many were cancelled.

        Needed before a manual exit, otherwise a leftover bracket leg would sit
        there trying to sell shares the position no longer has.
        """
        cancelled = 0
        for order in self.list_orders(status="open") or []:
            if order.get("symbol") not in (symbol, self._position_symbol(symbol)):
                continue
            try:
                self.cancel_order(order["id"])
                cancelled += 1
            except AlpacaError as e:
                # 422 = already filled or cancelled; nothing to do.
                if e.status != 422:
                    raise
        return cancelled

    def close_position(self, symbol: str) -> dict:
        """Liquidate the whole position (simpler than computing a sell qty)."""
        self.cancel_orders_for(symbol)  # clear any resting bracket legs first
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
