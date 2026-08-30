# 01 — Orders API (complete reference for an options agent)

Sources: `postorder.md` (full OpenAPI schema), `working-with-orders.md`, `orders-at-alpaca.md`, `options-trading.md`, `options-orders.md`, `options-level-3-trading.md`
Raw: `../09_raw_sources/alpaca_reference_md/postorder.md` and `../09_raw_sources/alpaca_docs_md/`

## 1. Endpoints

| Method | Path | Purpose | Ref |
|---|---|---|---|
| POST | `/v2/orders` | Create an order | `postorder` |
| GET | `/v2/orders` | List orders (filterable) | `getallorders-1` |
| GET | `/v2/orders/{order_id}` | Get by ID | `getorderbyorderid-1` |
| GET | `/v2/orders:by_client_order_id?client_order_id=` | Get by client order ID | `getorderbyclientorderid` |
| PATCH | `/v2/orders/{order_id}` | Replace an open order | `patchorderbyorderid-1` |
| DELETE | `/v2/orders/{order_id}` | Cancel one order | `deleteorderbyorderid-1` |
| DELETE | `/v2/orders` | Cancel **all** open orders | `deleteallorders-1` |

## 2. Order enums — the authoritative matrix

### `OrderType`
```
market | limit | stop | stop_limit | trailing_stop
```
Per asset class (from the spec description):
- **Equity:** market, limit, stop, stop_limit, trailing_stop
- **Options:** market, limit
- **Multileg options:** market, limit
- **Crypto:** market, limit, stop_limit

> ⚠️ **Conflict in Alpaca's own sources.** The OpenAPI spec says options = `market`/`limit` only. The **Options Trading** guide page says: *"`type` must be `market`, `limit`, `stop` or `stop_limit` (`stop` and `stop_limit` are only available for single-leg orders)"*. Alpaca's own skill file flags this disagreement and advises: **default to `limit`, let Alpaca reject rather than pre-blocking.** Treat `stop`/`stop_limit` on single-leg options as "probably works, verify empirically on the DEV account."

### `TimeInForce`
```
day | gtc | opg | cls | ioc | fok
```
Per asset class (spec):
- **Equity:** day, gtc, opg, cls, ioc, fok
- **Options:** **day**
- **Crypto:** gtc, ioc

> ⚠️ Same conflict: the spec says options = `day` only; the Options Trading page says *"`time_in_force` must be `day` or `gtc`"*. **Use `day`.** It is accepted by every source, and for a 5-day competition you *want* orders to expire daily rather than lingering — a stale GTC from Monday firing on Thursday is a real risk.

TIF semantics:
- `day` — valid the day it's live, Regular Trading Hours (09:30–16:00 ET) by default; auto-cancelled if unfilled at the close; queued to the next trading day if submitted after close.
- `gtc` — good until cancelled; non-marketable GTC limits are price-adjusted for corporate actions.
- `opg` / `cls` — opening / closing auction only (equity).
- `ioc` — immediate-or-cancel. `fok` — fill-or-kill.

### `OrderClass`
```
simple | bracket | oco | oto | mleg | ""
```
- **Equity:** simple (or ""), oco, oto, bracket
- **Options:** simple (or ""), **mleg** (required for multi-leg complex option strategies)
- **Crypto:** simple (or "")

⚠️ **bracket / oco / oto are EQUITIES ONLY.** You cannot attach a bracket (TP+SL) to an options order. Your agent must implement option exits itself — this is a real design constraint. See §7.

### `OrderSide`
```
buy | sell
```
> "Required for all order classes **except for `mleg`**." — in an mleg, each leg carries its own `side`.

### `PositionIntent`
```
buy_to_open | buy_to_close | sell_to_open | sell_to_close
```
Set this on every options order and every mleg leg. It disambiguates opening vs closing and is what a brokerage judge will look for.

### `OrderStatus` lifecycle
```
new → partially_filled → filled
new → canceled | expired | rejected
new → done_for_day
```
Plus: `accepted`, `pending_new`, `accepted_for_bidding`, `pending_cancel`, `pending_replace`, `replaced`, `stopped`, `suspended`, `calculated`, `held`.
Terminal states: `filled`, `canceled`, `expired`, `rejected`, `replaced`.

## 3. Order request body — key fields

| Field | Notes |
|---|---|
| `symbol` | Ticker, crypto pair (`BTC/USD`), or **OCC option symbol** (`AAPL250620C00200000`) |
| `qty` | String. Whole number for options. **Required for `mleg`** — "represents the number of units to trade of this strategy." Fractionable only for market+day equity. |
| `notional` | Dollar amount. **Must NOT be populated for options.** Market+day only, can't combine with `qty`, **cannot be replaced**. |
| `side` | buy/sell. Omit for `mleg`. |
| `type` | See matrix |
| `time_in_force` | See matrix |
| `limit_price` | Required for `limit`/`stop_limit`. **For `mleg`: positive = DEBIT, negative = CREDIT.** ← critical |
| `stop_price` | Required for `stop`/`stop_limit` |
| `trail_price` / `trail_percent` | `trailing_stop` only |
| `extended_hours` | **Must be `false` or absent for options.** Options have no extended hours. |
| `client_order_id` | Idempotency key, ≤128 chars. **Always set it.** Duplicate submissions with the same value are rejected → safe retries. |
| `order_class` | See matrix |
| `legs` | Array of `MLegOrderLeg`. **maxItems: 4.** |
| `position_intent` | See enum |
| `take_profit` / `stop_loss` | bracket/oco/oto only → equities only |
| `advanced_instructions` | Elite Smart Router (DMA/TWAP/VWAP). Equities. Not needed. |

### `MLegOrderLeg`
| Field | Required | Notes |
|---|---|---|
| `symbol` | ✅ | OCC option symbol |
| `ratio_qty` | ✅ | "proportional quantity of this leg in relation to the overall multi-leg order qty" |
| `side` | | buy/sell for this leg |
| `position_intent` | | buy_to_open / sell_to_open / buy_to_close / sell_to_close |

## 4. Options-specific validations (from `options-trading.md`, verbatim)

> Alpaca has implemented a series of validations to ensure the options order does not include attributes relevant to other asset classes. Some of these validations include:
> - Ensuring `qty` is a whole number
> - `Notional` must not be populated
> - `time_in_force` must be `day` or `gtc`
> - `extended_hours` must be `false` or not populated
> - `type` must be `market`, `limit`, `stop` or `stop_limit` (`stop` and `stop_limit` are only available for single-leg orders)

## 5. Ready-to-use payloads

### Buy a call (Level 2)
```json
{
  "symbol": "AAPL240119C00190000",
  "qty": "1",
  "side": "buy",
  "type": "limit",
  "limit_price": "5.10",
  "time_in_force": "day",
  "position_intent": "buy_to_open",
  "client_order_id": "agent-20260831-093012-aapl-c190"
}
```
Buying power needed: `execution_price × 100 × contracts`. At $5.10 → $510.

### Sell a cash-secured put (Level 1)
```json
{
  "symbol": "AAPL231201P00175000",
  "qty": "1", "side": "sell", "type": "market", "time_in_force": "day",
  "position_intent": "sell_to_open"
}
```
Requires `strike × 100 × contracts` = $17,500 buying power.

### Sell a covered call (Level 1)
```json
{
  "symbol": "AAPL231201C00195000",
  "qty": "2", "side": "sell", "type": "limit", "limit_price": "1.05",
  "time_in_force": "day", "position_intent": "sell_to_open"
}
```
Requires **200 shares** of AAPL held (2 contracts × 100).

### Long call (debit) spread — `mleg`
```json
{
  "order_class": "mleg", "qty": "1", "type": "limit",
  "limit_price": "1.00",           // POSITIVE = debit, you pay $1.00 × 100
  "time_in_force": "day",
  "legs": [
    {"symbol":"AAPL250117C00190000","ratio_qty":"1","side":"buy","position_intent":"buy_to_open"},
    {"symbol":"AAPL250117C00210000","ratio_qty":"1","side":"sell","position_intent":"sell_to_open"}
  ]
}
```

### Iron condor — `mleg`, 4 legs
```json
{
  "order_class": "mleg", "qty": "1", "type": "limit",
  "limit_price": "1.80",
  "time_in_force": "day",
  "legs": [
    {"symbol":"AAPL250117P00190000","ratio_qty":"1","side":"buy","position_intent":"buy_to_open"},
    {"symbol":"AAPL250117P00195000","ratio_qty":"1","side":"sell","position_intent":"sell_to_open"},
    {"symbol":"AAPL250117C00205000","ratio_qty":"1","side":"sell","position_intent":"sell_to_open"},
    {"symbol":"AAPL250117C00210000","ratio_qty":"1","side":"buy","position_intent":"buy_to_open"}
  ]
}
```
⚠️ An iron condor is normally a **credit** trade. If you intend to *receive* $1.80, `limit_price` should be **`"-1.80"`**. Alpaca's doc example shows `1.80` positive — treat the sign as something you must verify on your DEV account with a small order. See `../05_options/02_multileg_mleg_orders.md`.

### Roll a call spread (strikes) — single atomic mleg
```json
{
  "order_class": "mleg", "qty": "1", "type": "limit", "limit_price": "2.05",
  "time_in_force": "day",
  "legs": [
    {"symbol":"AAPL250117C00200000","ratio_qty":"1","side":"buy","position_intent":"buy_to_close"},
    {"symbol":"AAPL250117C00205000","ratio_qty":"1","side":"sell","position_intent":"sell_to_close"},
    {"symbol":"AAPL250117C00210000","ratio_qty":"1","side":"sell","position_intent":"sell_to_open"},
    {"symbol":"AAPL250117C00215000","ratio_qty":"1","side":"buy","position_intent":"buy_to_open"}
  ]
}
```

### Via CLI (raw API escape hatch — mleg has no named CLI command)
```bash
cat > /tmp/mleg.json <<'JSON'
{ "order_class":"mleg","qty":"1","type":"limit","limit_price":"1.00","time_in_force":"day",
  "legs":[{"symbol":"SPY260904C00650000","ratio_qty":"1","side":"buy","position_intent":"buy_to_open"},
          {"symbol":"SPY260904C00655000","ratio_qty":"1","side":"sell","position_intent":"sell_to_open"}]}
JSON
alpaca api POST /v2/orders < /tmp/mleg.json
```

### Via alpaca-py
```python
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import LimitOrderRequest, OptionLegRequest
from alpaca.trading.enums import OrderSide, TimeInForce, OrderClass, PositionIntent

tc = TradingClient(KEY, SECRET, paper=True)

req = LimitOrderRequest(
    qty=1,
    limit_price=1.00,                      # positive = debit
    time_in_force=TimeInForce.DAY,
    order_class=OrderClass.MLEG,
    legs=[
        OptionLegRequest(symbol="SPY260904C00650000", ratio_qty=1,
                         side=OrderSide.BUY,  position_intent=PositionIntent.BUY_TO_OPEN),
        OptionLegRequest(symbol="SPY260904C00655000", ratio_qty=1,
                         side=OrderSide.SELL, position_intent=PositionIntent.SELL_TO_OPEN),
    ],
)
order = tc.submit_order(req)
```

## 6. Error codes your agent must handle

From Alpaca's paper-trading skill guidance:

| Code | Meaning on `POST /v2/orders` | Agent action |
|---|---|---|
| **401** | Auth failure | **Stop.** Never retry with the same credentials. |
| **403** | **Insufficient buying power or shares** — *not* an auth failure | Show buying power, required notional, shortfall. Reduce qty or close positions. |
| **422** | Unrecognized input / non-tradable symbol / **market closed** | Check asset status; check `/v2/clock`. (`404` legitimately appears only on `GET /v2/assets/{id}`.) |
| **429** | Rate limited | Honor `Retry-After`, exponential backoff. Do **not** stack a second retry layer on top of the CLI's built-in retries. |
| timeout | Unknown | **Check whether the order was received by `client_order_id` before retrying.** |

## 7. 🔴 No brackets on options — how to implement exits

Because `bracket`/`oco`/`oto` are equities-only, an options agent must manage its own exits. Two workable patterns:

**Pattern A — Synthetic bracket in the agent (recommended)**
1. On entry fill, compute and persist `take_profit_price` and `stop_loss_price` (and a `time_stop` timestamp).
2. A monitor loop (every 1–15 min) reads positions + option snapshots.
3. When a threshold is hit, submit a closing order (`*_to_close` position intent).
4. On restart, rebuild the intended TP/SL from persisted state.

This is exactly what Alpaca's own reference architecture does:
> "Every 15 minutes, the position monitor checks Alpaca positions against stored TP/SL levels. Pure price checks, no LLM. If an active position is missing its bracket order, it gets rebuilt automatically."

**Pattern B — Resting single-leg limit exit**
On entry, immediately submit a `day` limit order to close at the profit target. Re-submit each morning. Stops still need the monitor loop (no stop-market safety net you can rely on for mleg).

⚠️ For an `mleg` position, the *legs* become individual positions. You close them either with a mirrored `mleg` order using `*_to_close` intents (preferred, atomic) or leg-by-leg (risks legging out at a bad price).

## 8. Idempotency — do this on every order

```bash
CLIENT_ORDER_ID="$(uuidgen)"
alpaca order submit --symbol AAPL --side buy --qty 10 --type market \
  --client-order-id "$CLIENT_ORDER_ID" --quiet
# later, recover it:
alpaca order get-by-client-id --client-order-id "$CLIENT_ORDER_ID"
```
Deterministic scheme that reads well in a decision log:
```
{agent}-{yyyymmddTHHMMSS}-{strategy}-{underlying}-{hash8}
e.g. condor-20260902T101500-ic-SPY-9f3ab12c
```

## 9. Order replace and cancel

- `PATCH /v2/orders/{id}` replaces an open order (new qty / limit / stop / TIF / client_order_id). Status goes `pending_replace` → `replaced`, and a **new order id** is created.
- `notional` orders **cannot be replaced** — cancel and resubmit.
- `DELETE /v2/orders` cancels **all** open orders with no confirmation. `alpaca order cancel-all` does the same instantly. Useful as a kill switch; dangerous by accident.
