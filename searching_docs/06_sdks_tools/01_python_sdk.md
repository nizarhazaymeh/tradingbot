# 01 — Alpaca Python SDK (`alpaca-py`)

- Repo: https://github.com/alpacahq/alpaca-py (branch `master`, Apache 2.0)
- Docs: https://alpaca.markets/sdks/python/
- Doc page: https://docs.alpaca.markets/us/docs/sdks-and-tools
- Raw README: `../09_raw_sources/github/alpaca-py_README.md`

## 1. Install
```bash
pip install alpaca-py
pip install alpaca-py --upgrade
```

⚠️ **`alpaca-py` is the current SDK. `alpaca-trade-api` is the legacy one.** Don't mix them; the class names and request patterns are completely different. Tutorials from before ~2023 use the legacy SDK.

## 2. Client classes — pick by API and asset class

> "Alpaca-py has a lot of client classes. There is a client for each API and even asset class specific clients… This requires you to pick and choose clients based on your needs."

| Purpose | Class |
|---|---|
| **Trading** | `TradingClient` |
| Broker API | `BrokerClient` *(not needed here)* |
| **Stock historical data** | `StockHistoricalDataClient` |
| **Option historical data** | `OptionHistoricalDataClient` |
| Crypto historical data | `CryptoHistoricalDataClient` |
| News | `NewsClient` |
| **Stock live stream** | `StockDataStream` |
| **Option live stream** | `OptionDataStream` |
| Crypto live stream | `CryptoDataStream` |
| News live stream | `NewsDataStream` |

## 3. OOP request-object pattern

> "Alpaca-py uses a more OOP approach to submitting requests… To submit a request, you will most likely need to create a request object containing the desired request data. Generally, there is a unique request model for each method."

So: `submit_order(MarketOrderRequest(...))`, `get_stock_bars(StockBarsRequest(...))`, etc.

## 4. Trading — the calls your agent needs

```python
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (
    MarketOrderRequest, LimitOrderRequest, OptionLegRequest,
    GetOrdersRequest, GetOptionContractsRequest, ClosePositionRequest,
)
from alpaca.trading.enums import (
    OrderSide, TimeInForce, OrderClass, PositionIntent,
    QueryOrderStatus, AssetStatus, ContractType,
)

tc = TradingClient(API_KEY, SECRET_KEY, paper=True)   # paper=True → paper-api host

# --- account ---
acct = tc.get_account()
print(acct.id, acct.equity, acct.options_buying_power,
      acct.options_approved_level, acct.options_trading_level)

# --- clock / calendar ---
clock = tc.get_clock()
if not clock.is_open:
    print("closed until", clock.next_open)

# --- option contracts (build the universe) ---
contracts = tc.get_option_contracts(GetOptionContractsRequest(
    underlying_symbols=["SPY"],
    status=AssetStatus.ACTIVE,
    expiration_date_gte="2026-09-04",
    expiration_date_lte="2026-09-11",
    type=ContractType.CALL,
    strike_price_gte="600", strike_price_lte="700",
    limit=500,
))
for c in contracts.option_contracts:
    print(c.symbol, c.strike_price, c.open_interest, c.tradable)

# --- single-leg option order ---
o = tc.submit_order(LimitOrderRequest(
    symbol="SPY260904C00650000",
    qty=1,
    side=OrderSide.BUY,
    type="limit",
    limit_price=6.20,
    time_in_force=TimeInForce.DAY,
    position_intent=PositionIntent.BUY_TO_OPEN,
    client_order_id="agent-20260902T1430-SPY-c650",
))

# --- MULTI-LEG (mleg) option order ---
spread = tc.submit_order(LimitOrderRequest(
    qty=1,
    limit_price=1.00,                       # positive = DEBIT, negative = CREDIT
    time_in_force=TimeInForce.DAY,
    order_class=OrderClass.MLEG,
    legs=[
        OptionLegRequest(symbol="SPY260904C00650000", ratio_qty=1,
                         side=OrderSide.BUY,  position_intent=PositionIntent.BUY_TO_OPEN),
        OptionLegRequest(symbol="SPY260904C00655000", ratio_qty=1,
                         side=OrderSide.SELL, position_intent=PositionIntent.SELL_TO_OPEN),
    ],
    client_order_id="agent-20260902T1430-SPY-bullcall-650-655",
))

# --- positions ---
for p in tc.get_all_positions():
    print(p.symbol, p.asset_class, p.qty, p.avg_entry_price, p.unrealized_pl)

# --- orders ---
open_orders = tc.get_orders(GetOrdersRequest(status=QueryOrderStatus.OPEN))

# --- close / cancel ---
tc.close_position("SPY260904C00650000", ClosePositionRequest(qty="1"))
tc.cancel_orders()                                   # cancel ALL open orders
tc.exercise_options_position("SPY260904C00650000")

# --- portfolio history (your equity curve) ---
from alpaca.trading.requests import GetPortfolioHistoryRequest
hist = tc.get_portfolio_history(GetPortfolioHistoryRequest(period="1W", timeframe="15Min"))
```

> ⚠️ Class and parameter names occasionally shift between `alpaca-py` releases. **Verify against the installed version, not against this page:**
> ```python
> import alpaca, inspect
> print(alpaca.__version__)
> from alpaca.trading import requests as R
> print([n for n in dir(R) if "Option" in n or "Leg" in n])
> print(inspect.signature(R.LimitOrderRequest))
> ```
> This 20-second check on Day 1 saves an hour of guessing.

## 5. Market data — batched requests

```python
from alpaca.data.historical.stock  import StockHistoricalDataClient
from alpaca.data.historical.option import OptionHistoricalDataClient
from alpaca.data.requests import (
    StockBarsRequest, StockSnapshotRequest,
    OptionChainRequest, OptionSnapshotRequest,
)
from alpaca.data.timeframe import TimeFrame

sdc = StockHistoricalDataClient(API_KEY, SECRET_KEY)
odc = OptionHistoricalDataClient(API_KEY, SECRET_KEY)

# 🔴 ONE batched request for many symbols — do not loop per symbol
bars = sdc.get_stock_bars(StockBarsRequest(
    symbol_or_symbols=["SPY","QQQ","IWM","AAPL","NVDA"],
    timeframe=TimeFrame.Day, limit=252, adjustment="all",
)).df

snaps = sdc.get_stock_snapshot(StockSnapshotRequest(
    symbol_or_symbols=["SPY","QQQ","IWM"]))

# 🔴 THE call: whole chain + quotes + Greeks + IV in one request
chain = odc.get_option_chain(OptionChainRequest(
    underlying_symbol="SPY",
    expiration_date_gte="2026-09-04",
    expiration_date_lte="2026-09-04",
    strike_price_gte=600, strike_price_lte=700,
))
for sym, snap in chain.items():
    g = snap.greeks
    print(sym, snap.latest_quote.bid_price, snap.latest_quote.ask_price,
          g.delta if g else None, snap.implied_volatility)
```

Alpaca's own multi-agent article makes the batching point explicitly:
> "Individual requests for the 500 tickers hit rate limits before the data finishes loading. **One batch request solves this.**"

## 6. Live streaming

```python
from alpaca.data.live.option import OptionDataStream
from alpaca.data.live.stock  import StockDataStream
from alpaca.data.live.news   import NewsDataStream
from alpaca.trading.stream   import TradingStream

# option stream — msgpack is mandatory; the SDK handles it
opt = OptionDataStream(API_KEY, SECRET_KEY)
async def on_opt_quote(q): ...
opt.subscribe_quotes(on_opt_quote, "SPY260904C00650000")

# order/fill events — push, costs no rate-limit budget
ts = TradingStream(API_KEY, SECRET_KEY, paper=True)
async def on_trade_update(data):
    print(data.event, data.order.symbol, data.order.status, data.order.filled_qty)
ts.subscribe_trade_updates(on_trade_update)
ts.run()
```
🔴 The **option** stream is msgpack-only. Use `OptionDataStream`; a hand-rolled JSON websocket will not work.
🔴 Basic plan cap: **200 option quote subscriptions**.

## 7. Environment variables
```bash
APCA_API_KEY_ID=PK...
APCA_API_SECRET_KEY=...
APCA_API_BASE_URL=https://paper-api.alpaca.markets
```
(For the CLI and MCP server the names are `ALPACA_API_KEY` / `ALPACA_SECRET_KEY` — see `../02_alpaca_platform/02_accounts_and_auth.md` §2.)

## 8. Migration notes from `alpaca-trade-api`
- OOP request models replace keyword-soup method calls.
- Separate clients per API and asset class.
- Broker API support added.
- If you find a tutorial using `alpaca_trade_api.REST(...)`, it's the legacy SDK — translate it, don't install it alongside.
