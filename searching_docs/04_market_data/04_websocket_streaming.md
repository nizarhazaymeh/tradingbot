# 04 — WebSocket Streaming

Sources: `websocket-streaming.md`, `streaming-market-data.md`, `real-time-stock-pricing-data.md`, `real-time-option-data.md`, `streaming-real-time-news.md`, `real-time-crypto-pricing-data.md`

## 1. Endpoints

| Stream | URL | Format |
|---|---|---|
| **Stock data** | `wss://stream.data.alpaca.markets/v2/{feed}` — `iex` \| `sip` \| `delayed_sip` | JSON or msgpack |
| **Option data** | `wss://stream.data.alpaca.markets/v1beta1/{feed}` — `indicative` \| `opra` | 🔴 **msgpack only** |
| **Crypto data** | `wss://stream.data.alpaca.markets/v1beta3/crypto/{loc}` | JSON or msgpack |
| **News** | `wss://stream.data.alpaca.markets/v1beta1/news` | JSON or msgpack |
| **Trade updates (your orders)** | `wss://paper-api.alpaca.markets/stream` | JSON |

Sandbox variants exist under `stream.data.sandbox.alpaca.markets`.

## 2. Protocol

1. **Connect** → server sends `[{"T":"success","msg":"connected"}]`
2. **Authenticate**
   ```json
   {"action":"auth","key":"{KEY}","secret":"{SECRET}"}
   ```
   → `[{"T":"success","msg":"authenticated"}]`
   ⚠️ Requesting a feed you're not entitled to **fails at this step**.
3. **Subscribe**
   ```json
   {"action":"subscribe","trades":["AAPL"],"quotes":["AAPL","SPY"],"bars":["*"]}
   ```
   → server echoes a `subscription` message with your current subscription set.
4. **Unsubscribe** — same shape with `"action":"unsubscribe"`.

Message types (`T` field): `t` trade, `q` quote, `b` minute bar, `d` daily bar, `u` updated bar, `s` status, `c` corrections, `n` news, `error`, `success`, `subscription`.

Only **one connection per account per stream** on Basic (the connection limit). A second connection typically evicts or rejects the first — so don't run the agent and a debug script against the same stream simultaneously.

## 3. 🔴 Limits that matter

| Limit | Basic | Algo Trader Plus |
|---|---|---|
| **Option quote subscriptions** | **200** | 1,000 |
| Stock feed | IEX only | Full SIP |
| Concurrent connections | 1 | 1 |

**200 option-quote subscriptions is your real budget.** Spend it deliberately:
```
5 underlyings × 2 expiries × (10 calls + 10 puts) = 200 exactly
```
Better: subscribe only to the contracts you actually hold or are actively evaluating, and poll the chain for discovery. **Streaming for positions, polling for discovery** is the right split.

## 4. Trade updates stream — the right way to know your orders filled

`wss://paper-api.alpaca.markets/stream`

```json
{"action":"auth","key":"{KEY}","secret":"{SECRET}"}
{"action":"listen","data":{"streams":["trade_updates"]}}
```

Events: `new`, `fill`, `partial_fill`, `canceled`, `expired`, `replaced`, `rejected`, `pending_new`, `pending_cancel`, `pending_replace`, `order_replace_rejected`, `order_cancel_rejected`, `done_for_day`, `calculated`, `stopped`, `suspended`.

Each carries the full order object plus `event`, `timestamp`, `price`, `qty`, `position_qty`.

**This is far better than polling `/v2/orders`** — it's push, it costs no rate-limit budget, and it gives you `partial_fill` events immediately (remember paper produces random partial fills 10% of the time).

🔴 **But:** *options assignments/exercises/expiries (NTAs) are NOT delivered over websocket.* You must poll `/v2/account/activities` for those. There is no push for NTAs.

## 5. Practical architecture

```
┌─────────────────────────────────────────────────────────────┐
│ PUSH (websocket, no rate-limit cost)                        │
│  • trade_updates      → order/fill state machine            │
│  • news stream        → wake the agent on a catalyst        │
│  • option quotes (held positions only, ≤200 subs)          │
│  • stock quotes/bars (underlyings in the universe)         │
├─────────────────────────────────────────────────────────────┤
│ POLL (REST, budget 200/min)                                 │
│  • /v2/clock                    cache 60s                   │
│  • option chain per underlying   every 30–60s                │
│  • /v2/positions                 every cycle                 │
│  • /v2/account                   every cycle                 │
│  • /v2/account/activities        every 5 min (NTAs!)         │
│  • /v1beta1/corporate-actions    once per day                │
│  • portfolio_history             once per day (archive it)   │
└─────────────────────────────────────────────────────────────┘
```

## 6. Reliability

- **Always implement reconnect with backoff.** Networks drop; a 7-day agent will disconnect.
- **On reconnect, re-subscribe** — subscriptions are per-connection and are not restored.
- **On reconnect, reconcile** (see `../03_trading_api/04_rate_limits_and_resilience.md` §5) — you may have missed fills while disconnected. Never trust the stream as your only source of truth; the REST endpoints are authoritative.
- Handle the `error` message type explicitly; auth/entitlement errors are permanent and should not be retried in a tight loop.

## 7. SDK usage (recommended over raw websockets)

```python
from alpaca.data.live.option import OptionDataStream
from alpaca.data.live.stock  import StockDataStream
from alpaca.data.live.news   import NewsDataStream

opt = OptionDataStream(KEY, SECRET)          # handles msgpack for you
async def on_quote(q): ...
opt.subscribe_quotes(on_quote, "SPY260904C00650000")
opt.run()
```
The SDK handles msgpack (mandatory for options), auth, reconnection scaffolding, and message decoding. Hand-rolling the option stream in JSON **will not work** — the server only speaks msgpack there.
