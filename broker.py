"""Broker adapters — one strategy, two exchanges.

`get_broker()` returns an object with a small, uniform surface that bot.py
drives, so the SMA logic in strategy.py stays exchange-agnostic:

    name                      label for logs
    ERRORS                    exception types the main loop should catch
    prepare(symbols)          resolve/validate symbols, return the tradable list
    closes(symbol, iv, n)     last n CLOSED bar closes, oldest first
    cash()                    spendable quote currency
    market_open(symbol)       False when the venue is shut (US stock hours)
    buy(symbol, amount)       market buy for `amount` of quote -> avg fill price
    sell(symbol)              liquidate the position -> qty sold

Set BROKER=binance (default) or BROKER=alpaca in .env.
"""
import logging
from decimal import Decimal
from typing import List

import config

log = logging.getLogger("broker")


# --------------------------------------------------------------------------- #
# Binance
# --------------------------------------------------------------------------- #
class BinanceBroker:
    name = "Binance"

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

    def _balance(self, asset: str) -> float:
        bal = self.client.get_asset_balance(asset=asset)
        return float(bal["free"]) if bal else 0.0

    def cash(self, symbol: str) -> float:
        return self._balance(self.filters[symbol]["quote"])

    def market_open(self, symbol: str) -> bool:
        return True  # crypto is 24/7

    def buy(self, symbol: str, amount: float) -> float:
        log.info("Placing MARKET BUY: spend %.8f quote on %s", amount, symbol)
        order = self.client.order_market_buy(symbol=symbol, quoteOrderQty=amount)
        fills = order.get("fills") or []
        qty = sum(float(f["qty"]) for f in fills)
        cost = sum(float(f["qty"]) * float(f["price"]) for f in fills)
        return cost / qty if qty else 0.0

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


# --------------------------------------------------------------------------- #
# Alpaca
# --------------------------------------------------------------------------- #
class AlpacaBroker:
    name = "Alpaca"

    def __init__(self):
        from alpaca_client import AlpacaClient, AlpacaError

        self.ERRORS = (AlpacaError,)
        self.client = AlpacaClient(
            config.ALPACA_API_KEY,
            config.ALPACA_API_SECRET,
            paper=config.ALPACA_PAPER,
            feed=config.ALPACA_FEED,
        )

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
            except AlpacaError as e:
                if e.status == 404:
                    raise SystemExit(
                        f"Symbol {sym} not found on Alpaca. US stocks use plain "
                        f"tickers (AAPL); crypto uses pairs (BTC/USD)."
                    )
                log.warning("Could not verify %s: %s", sym, e)  # keep going
            resolved.append(sym)
        return resolved

    def closes(self, symbol: str, interval: str, limit: int) -> List[float]:
        return self.client.get_closes(symbol, interval, limit)

    def cash(self, symbol: str) -> float:
        from alpaca_client import is_crypto

        acct = self.client.get_account()
        # Crypto can't be bought on margin, so cash is the real constraint.
        key = "cash" if is_crypto(symbol) else "buying_power"
        return float(acct.get(key, acct.get("cash", 0)))

    def market_open(self, symbol: str) -> bool:
        return self.client.is_market_open(symbol)

    def buy(self, symbol: str, amount: float) -> float:
        log.info("Placing MARKET BUY: $%.2f notional on %s", amount, symbol)
        order = self.client.submit_market_order(symbol, "buy", notional=amount)
        return self.client.fill_price(order)

    def sell(self, symbol: str) -> float:
        qty = self.client.position_qty(symbol)
        if qty <= 0:
            log.warning("[%s] EXIT signal but no open position at Alpaca.", symbol)
            return 0.0
        log.info("Closing position: %.8f of %s", qty, symbol)
        self.client.close_position(symbol)
        return qty


def get_broker():
    """Instantiate the broker named by BROKER in .env."""
    return AlpacaBroker() if config.BROKER == "alpaca" else BinanceBroker()
