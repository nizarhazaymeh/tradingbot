"""Alpaca broker adapter.

`get_broker()` returns the object bot.py drives, keeping strategy.py free of any
venue detail:

    name / ERRORS               label for logs; exceptions the loop should catch
    supports_brackets           broker-side stop-loss/take-profit available?
    prepare(symbols)            resolve + validate symbols, return the usable list
    closes(symbol, iv, n)       last n CLOSED bar closes, oldest first
    history(symbol, iv, n)      last n CLOSED bars as Bar(t, c, h, l)
    history_many(syms, iv, n)   same for many symbols, batched into one request
    entry_window_ok(sym, mins)  reason to skip an entry near the bell, else None
    account()                   {equity, cash, last_equity, daytrade_count, ...}
    positions(symbols)          {symbol: {qty, avg_entry_price}} for open positions
    is_dust(symbol, qty, price) is this residue too small to count as a position?
    market_open(symbol)         False when the venue is shut (US stock hours)
    buy(symbol, notional, ...)  -> {fill, qty, protection}
    sell_qty(symbol, qty)       sell one take-profit tranche
    protect(symbol, qty, stop)  park/replace a broker-side stop
    sell(symbol)                liquidate -> qty sold

"""
import logging
import uuid
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import Dict, List, Optional

import config
import risk
from alpaca_client import is_crypto
from strategy import Bar

log = logging.getLogger("broker")


ET = ZoneInfo("America/New_York")
RTH_OPEN = (9, 30)   # 09:30 ET
RTH_CLOSE = (16, 0)  # 16:00 ET


def _in_regular_hours(epoch_seconds: float) -> bool:
    """Is this bar inside the 09:30-16:00 ET session?

    Extended-hours bars for ETFs are thin — often a few hundred shares — and
    routinely carry bad prints. One 419.70 wick on a 409 stock is enough to
    wreck ATR, swing detection and every level derived from them.
    """
    t = datetime.fromtimestamp(epoch_seconds, timezone.utc).astimezone(ET)
    if t.weekday() >= 5:
        return False
    return RTH_OPEN <= (t.hour, t.minute) < RTH_CLOSE


def _drop_bad_prints(bars: List[Bar], max_range_mult: float = 5.0) -> List[Bar]:
    """Clamp wicks that dwarf the recent typical range.

    A print whose high/low is several times the median bar range is far more
    likely to be a bad tick than a real move, and it would otherwise become a
    swing pivot or blow out ATR. The bar is kept but its wick is trimmed, so
    the series stays continuous.
    """
    if len(bars) < 20:
        return bars
    ranges = sorted(x.h - x.l for x in bars)
    median = ranges[len(ranges) // 2]
    if median <= 0:
        return bars
    cap = median * max_range_mult
    out, fixed = [], 0
    for x in bars:
        if (x.h - x.l) > cap:
            body_hi = max(x.c, x.l)
            out.append(Bar(x.t, x.c, min(x.h, body_hi + cap), max(x.l, x.c - cap), x.v))
            fixed += 1
        else:
            out.append(x)
    if fixed:
        log.debug("Trimmed %d outlier bar(s) exceeding %.4f range", fixed, cap)
    return out


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
        """Validate symbols, converting any USDT-style crypto ticker to a pair."""
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

    def history_many(self, symbols: List[str], interval: str, limit: int):
        """Last `limit` CLOSED bars for every symbol.

        Over-fetches, because filtering to regular hours discards a large share
        of the raw bars (a 24h day yields only 6.5h of real session).
        """
        raw = self.client.get_bars_multi(
            symbols, interval,
            int((limit + 1) * (3.5 if config.RTH_ONLY else 1.0)))
        out = {}
        for sym, bars in raw.items():
            if len(bars) > limit:
                bars = bars[:-1]  # drop the still-forming bar
            series = [Bar(_epoch(b["t"]), float(b["c"]), float(b["h"]),
                          float(b["l"]), float(b.get("v") or 0))
                      for b in bars]
            if config.RTH_ONLY and not is_crypto(sym):
                series = [x for x in series if _in_regular_hours(x.t)]
            # Trim back to what was asked for — the over-fetch above is only
            # there to survive the session filter.
            out[sym] = _drop_bad_prints(series)[-limit:]
        return out

    def history(self, symbol: str, interval: str, limit: int):
        return self.history_many([symbol], interval, limit).get(symbol, [])

    def entry_window_ok(self, symbol: str, min_minutes: float) -> Optional[str]:
        """Reason to skip a NEW entry near the bell, else None.

        Opening a position minutes before the close means the stop and target
        never get a chance to work — and on an early-close day the bell comes
        three hours sooner than usual.
        """
        from alpaca_client import is_crypto
        if is_crypto(symbol) or not min_minutes:
            return None
        left = self.client.minutes_to_close()
        if left is not None and left < min_minutes:
            return f"only {left:.0f} min to the close (need {min_minutes:.0f})"
        return None

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
        cid = "bot-" + uuid.uuid4().hex[:24]
        if want_bracket:
            qty = risk.shares_for(notional, price)
            if qty >= 1:
                log.info("Placing BRACKET BUY: %d share(s) of %s "
                         "(stop %.2f / target %.2f)", qty, symbol, stop_price, target_price)
                order = self._place(lambda: self.client.submit_bracket_order(
                    symbol, "buy", qty, target_price, stop_price, client_order_id=cid), cid)
                if order is None:
                    return {"fill": 0.0, "qty": 0.0, "protection": "none"}
                return {"fill": self.client.fill_price(order),
                        "qty": float(qty), "protection": "bracket"}
            log.info("[%s] $%.2f buys less than one share at %.2f — using a "
                     "fractional order with bot-side exits instead.",
                     symbol, notional, price)

        log.info("Placing MARKET BUY: $%.2f notional on %s", notional, symbol)
        order = self._place(lambda: self.client.submit_market_order(
            symbol, "buy", notional=notional, client_order_id=cid), cid)
        if order is None:
            return {"fill": 0.0, "qty": 0.0, "protection": "none"}
        fill = self.client.fill_price(order)
        return {"fill": fill, "qty": (notional / fill) if fill else 0.0,
                "protection": "poll"}

    def _place(self, submit, client_order_id):
        """Submit once; if the response is lost, find out what actually happened.

        A network error after a successful POST is the dangerous case: blindly
        retrying would open a second position. Instead we look the order up by
        the id we sent, and only report failure if it truly never landed.
        """
        from alpaca_client import AlpacaError
        try:
            return submit()
        except AlpacaError as e:
            if e.status != 0:      # a real rejection — nothing was created
                raise
            log.warning("Order response lost (%s) — checking whether it landed.", e)
            existing = self.client.get_order_by_client_id(client_order_id)
            if existing:
                log.warning("It did: order %s is live. Not resubmitting.", existing.get("id"))
                return existing
            log.error("Order never reached Alpaca; skipping this entry.")
            return None

    def sell_qty(self, symbol: str, qty: float) -> float:
        """Sell part of a position (a take-profit tranche).

        Any resting stop is cancelled first: it still covers the OLD size, and
        leaving it would try to sell shares that are no longer there.
        """
        held = self.client.position_qty(symbol)
        qty = min(qty, held)
        if qty <= 0:
            return 0.0
        self.client.cancel_orders_for(symbol)
        from alpaca_client import is_crypto
        if not is_crypto(symbol):
            qty = float(int(qty)) or 0.0   # equities: whole shares
            if qty <= 0:
                return 0.0
        log.info("Selling %.8f of %s (partial)", qty, symbol)
        self.client.submit_market_order(symbol, "sell", qty=qty,
                                        client_order_id="bot-" + uuid.uuid4().hex[:24])
        return qty

    def protect(self, symbol: str, qty: float, stop_price: float) -> bool:
        """Park a broker-side stop for `qty` at `stop_price`, replacing any old one."""
        from alpaca_client import AlpacaError, is_crypto
        if is_crypto(symbol):
            return False  # Alpaca crypto has no stop orders; the loop covers it
        try:
            self.client.cancel_orders_for(symbol)
            qty = float(int(qty))
            if qty <= 0:
                return False
            self.client.submit_stop_order(symbol, qty, stop_price,
                                          client_order_id="bot-" + uuid.uuid4().hex[:24])
            log.info("[%s] Broker stop set: %.0f share(s) @ %.2f", symbol, qty, stop_price)
            return True
        except AlpacaError as e:
            log.warning("[%s] Could not place protective stop: %s", symbol, e)
            return False

    def sell(self, symbol: str) -> float:
        qty = self.client.position_qty(symbol)
        if qty <= 0:
            log.warning("[%s] EXIT signal but no open position at Alpaca.", symbol)
            return 0.0
        log.info("Closing position: %.8f of %s", qty, symbol)
        self.client.close_position(symbol)  # cancels resting bracket legs first
        return qty


def get_broker() -> "AlpacaBroker":
    """The trading venue. Alpaca only."""
    return AlpacaBroker()
