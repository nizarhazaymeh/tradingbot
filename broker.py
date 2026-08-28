"""Broker adapters — one strategy, two venues.

`get_broker()` returns an object with a uniform surface that bot.py drives, so
strategy.py stays venue-agnostic:

    name / ERRORS               label for logs; exceptions the loop should catch
    supports_brackets           broker-side stop-loss/take-profit available?
    prepare(symbols)            resolve + validate symbols, return the usable list
    closes(symbol, iv, n)       last n CLOSED bar closes, oldest first
    history(symbol, iv, n)      last n CLOSED bars as Bar(t, c, h, l)
    account()                   {equity, cash, last_equity, daytrade_count, ...}
    positions(symbols)          {symbol: {qty, avg_entry_price}} for open positions
    is_dust(symbol, qty, price) is this residue too small to count as a position?
    market_open(symbol)         False when the venue is shut (US stock hours)
    buy(symbol, notional, ...)  -> {fill, qty, protection}
    sell(symbol)                liquidate -> qty sold

Alpaca is the default (BROKER=alpaca). Binance remains available for crypto,
but has no equity/PDT/bracket concepts, so those rails simply don't engage.
"""
import logging
from decimal import Decimal
from typing import Dict, List, Optional

import config
import risk
from strategy import Bar

log = logging.getLogger("broker")


def _epoch(value) -> float:
    """RFC-3339 string or epoch-ms int -> epoch seconds."""
    if isinstance(value, (int, float)):
        return float(value) / 1000.0 if value > 1e11 else float(value)
    try:
        from datetime import datetime
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


# --------------------------------------------------------------------------- #
# Alpaca — US stocks + crypto
# --------------------------------------------------------------------------- #
class AlpacaBroker:
    name = "Alpaca"
    supports_brackets = True

    def __init__(self):
        from alpaca_client import AlpacaClient, AlpacaError

        self.ERRORS = (AlpacaError,)
        self.client = AlpacaClient(
            config.ALPACA_API_KEY,
            config.ALPACA_API_SECRET,
            paper=config.ALPACA_PAPER,
            feed=config.ALPACA_FEED,
        )
        self._pos_key: Dict[str, str] = {}  # BTCUSD -> BTC/USD

    def prepare(self, symbols: List[str]) -> List[str]:
        """Normalise Binance-style tickers (BTCUSDT -> BTC/USD) and check them."""
        from alpaca_client import AlpacaError, normalize_symbol

        resolved = []
        for raw in symbols:
            sym = normalize_symbol(raw)
            if sym != raw:
                log.info("Symbol %s -> %s (Alpaca settles crypto in USD)", raw, sym)
            try:
                asset = self.client.get_asset(sym)
                if not asset.get("tradable", True):
                    raise SystemExit(f"Symbol {sym} is not tradable on Alpaca.")
                if not asset.get("fractionable", True) and not config.USE_BRACKET_ORDERS:
                    log.info("%s is not fractionable — orders round to whole shares.", sym)
            except AlpacaError as e:
                if e.status == 404:
                    raise SystemExit(
                        f"Symbol {sym} not found on Alpaca. US stocks use plain "
                        f"tickers (AAPL); crypto uses pairs (BTC/USD)."
                    )
                log.warning("Could not verify %s: %s", sym, e)  # keep going
            self._pos_key[self.client._position_symbol(sym)] = sym
            resolved.append(sym)
        return resolved

    def closes(self, symbol: str, interval: str, limit: int) -> List[float]:
        return self.client.get_closes(symbol, interval, limit)

    def history(self, symbol: str, interval: str, limit: int):
        """Last `limit` CLOSED bars, oldest first."""
        bars = self.client.get_bars(symbol, interval, limit + 1)
        if len(bars) > limit:
            bars = bars[:-1]  # drop the still-forming bar
        return [Bar(_epoch(b["t"]), float(b["c"]), float(b["h"]), float(b["l"]))
                for b in bars]

    def account(self) -> dict:
        return self.client.get_account()

    def positions(self, symbols: List[str]) -> Dict[str, dict]:
        out = {}
        for pos in self.client.list_positions() or []:
            sym = self._pos_key.get(pos.get("symbol"), pos.get("symbol"))
            if sym in symbols:
                out[sym] = {
                    "qty": float(pos.get("qty", 0)),
                    "avg_entry_price": float(pos.get("avg_entry_price", 0)),
                }
        return out

    def is_dust(self, symbol: str, qty: float, price: float) -> bool:
        return qty <= 0

    def market_open(self, symbol: str) -> bool:
        return self.client.is_market_open(symbol)

    def buy(self, symbol, notional, price, stop_price=None, target_price=None) -> dict:
        """Market entry. Uses a bracket order when Alpaca allows one.

        Bracket = broker-side stop-loss + take-profit that stay live between
        polls. Alpaca only allows it on stocks, and only for WHOLE shares, so
        a too-small order falls back to a fractional entry policed by the loop.
        """
        from alpaca_client import is_crypto

        want_bracket = (
            config.USE_BRACKET_ORDERS and self.supports_brackets
            and not is_crypto(symbol) and stop_price and target_price
        )
        if want_bracket:
            qty = risk.shares_for(notional, price)
            if qty >= 1:
                log.info("Placing BRACKET BUY: %d share(s) of %s "
                         "(stop %.2f / target %.2f)", qty, symbol, stop_price, target_price)
                order = self.client.submit_bracket_order(
                    symbol, "buy", qty, target_price, stop_price)
                return {"fill": self.client.fill_price(order),
                        "qty": float(qty), "protection": "bracket"}
            log.info("[%s] $%.2f buys less than one share at %.2f — using a "
                     "fractional order with bot-side exits instead.",
                     symbol, notional, price)

        log.info("Placing MARKET BUY: $%.2f notional on %s", notional, symbol)
        order = self.client.submit_market_order(symbol, "buy", notional=notional)
        fill = self.client.fill_price(order)
        return {"fill": fill, "qty": (notional / fill) if fill else 0.0,
                "protection": "poll"}

    def sell(self, symbol: str) -> float:
        qty = self.client.position_qty(symbol)
        if qty <= 0:
            log.warning("[%s] EXIT signal but no open position at Alpaca.", symbol)
            return 0.0
        log.info("Closing position: %.8f of %s", qty, symbol)
        self.client.close_position(symbol)  # cancels resting bracket legs first
        return qty


# --------------------------------------------------------------------------- #
# Binance — spot crypto
# --------------------------------------------------------------------------- #
class BinanceBroker:
    name = "Binance"
    supports_brackets = False  # no broker-side OCO wired up here

    def __init__(self):
        from binance.client import Client
        from binance.exceptions import BinanceAPIException

        self.ERRORS = (BinanceAPIException,)
        self.client = Client(config.API_KEY, config.API_SECRET,
                             testnet=config.USE_TESTNET)
        self.filters = {}

    def prepare(self, symbols: List[str]) -> List[str]:
        for sym in symbols:
            info = self.client.get_symbol_info(sym)
            if info is None:
                raise SystemExit(f"Symbol {sym} not found on this exchange/endpoint.")
            f = {x["filterType"]: x for x in info["filters"]}
            self.filters[sym] = {
                "step": float(f.get("LOT_SIZE", {}).get("stepSize", "0.00000001")),
                "min_notional": float(
                    f.get("NOTIONAL", f.get("MIN_NOTIONAL", {})).get("minNotional", "0")
                ),
                "base": info["baseAsset"],
                "quote": info["quoteAsset"],
            }
        return symbols

    def closes(self, symbol: str, interval: str, limit: int) -> List[float]:
        klines = self.client.get_klines(symbol=symbol, interval=interval, limit=limit + 1)
        return [float(k[4]) for k in klines[:-1]]  # drop the forming candle

    def history(self, symbol: str, interval: str, limit: int):
        """Last `limit` CLOSED candles, oldest first."""
        raw = self.client.get_klines(symbol=symbol, interval=interval, limit=limit + 1)
        return [Bar(_epoch(k[0]), float(k[4]), float(k[2]), float(k[3]))
                for k in raw[:-1]]

    def _balance(self, asset: str) -> float:
        bal = self.client.get_asset_balance(asset=asset)
        return float(bal["free"]) if bal else 0.0

    def account(self) -> dict:
        """Spot has no equity/PDT concept — report quote cash so the rails
        that need equity stay inert rather than firing on bad data."""
        quote = self.filters[config.SYMBOLS[0]]["quote"] if self.filters else "USDT"
        cash = self._balance(quote)
        return {"equity": cash, "cash": cash, "last_equity": cash,
                "buying_power": cash, "daytrade_count": 0, "status": "ACTIVE"}

    def positions(self, symbols: List[str]) -> Dict[str, dict]:
        out = {}
        for sym in symbols:
            qty = self._balance(self.filters[sym]["base"])
            if qty > 0:
                out[sym] = {"qty": qty, "avg_entry_price": 0.0}
        return out

    def is_dust(self, symbol: str, qty: float, price: float) -> bool:
        """Leftover crypto below the exchange minimum isn't a real position."""
        return qty * price < max(self.filters[symbol]["min_notional"], 1e-8)

    def market_open(self, symbol: str) -> bool:
        return True  # crypto is 24/7

    def buy(self, symbol, notional, price, stop_price=None, target_price=None) -> dict:
        log.info("Placing MARKET BUY: spend %.8f quote on %s", notional, symbol)
        order = self.client.order_market_buy(symbol=symbol, quoteOrderQty=notional)
        fills = order.get("fills") or []
        qty = sum(float(f["qty"]) for f in fills)
        cost = sum(float(f["qty"]) * float(f["price"]) for f in fills)
        return {"fill": (cost / qty) if qty else 0.0, "qty": qty, "protection": "poll"}

    def sell(self, symbol: str) -> float:
        step = self.filters[symbol]["step"]
        raw = self._balance(self.filters[symbol]["base"])
        qty = float((Decimal(str(raw)) // Decimal(str(step))) * Decimal(str(step))) \
            if step else raw
        if qty <= 0:
            log.warning("[%s] EXIT signal but quantity rounds to 0.", symbol)
            return 0.0
        log.info("Placing MARKET SELL: %.8f of %s", qty, symbol)
        self.client.order_market_sell(symbol=symbol, quantity=qty)
        return qty


def get_broker():
    """Instantiate the broker named by BROKER in .env."""
    return BinanceBroker() if config.BROKER == "binance" else AlpacaBroker()
