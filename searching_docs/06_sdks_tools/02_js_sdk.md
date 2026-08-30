# 02 — Alpaca JS/TS SDK (`@alpacahq/alpaca-trade-api`)

- Repo: https://github.com/alpacahq/alpaca-trade-api-js (branch `master`)
- Listed on the hackathon page as **"Alpaca JS SDK — JavaScript and TypeScript integration"**
- Raw README (103 KB, includes generated API docs): `../09_raw_sources/github/alpaca-trade-api-js_README.md`

## 1. When to use this instead of Python

| Use JS if… | Use Python if… |
|---|---|
| Your demo is a **Next.js / Vercel** app (lablab names Vercel as an approved demo platform) | Your demo is **Streamlit** (also approved) |
| You want the agent and the UI in one deployable | You want pandas/numpy for indicators and IV history |
| Your team is stronger in TS | Your team is stronger in Python |

**Recommended for this hackathon:** **Python for the agent, and either Streamlit (Python) or a thin Next.js dashboard reading the agent's SQLite/JSON output.** The Python SDK has first-class `OptionChainRequest` and `OptionDataStream` support and the whole Alpaca options ecosystem (MCP server, Skills) is Python/Go. Use the JS SDK only if the team's skills point that way.

## 2. Install
```bash
npm install --save @alpacahq/alpaca-trade-api
# or
yarn add @alpacahq/alpaca-trade-api
```

## 3. Basic usage
```javascript
import Alpaca from "@alpacahq/alpaca-trade-api";

const alpaca = new Alpaca({
  keyId: process.env.ALPACA_API_KEY,
  secretKey: process.env.ALPACA_SECRET_KEY,
  paper: true,               // → paper-api.alpaca.markets
});

// account
const account = await alpaca.getAccount();
console.log(account.equity, account.options_buying_power);

// clock
const clock = await alpaca.getClock();

// single-leg option order
const order = await alpaca.createOrder({
  symbol: "SPY260904C00650000",
  qty: 1,
  side: "buy",
  type: "limit",
  limit_price: 6.2,
  time_in_force: "day",
  position_intent: "buy_to_open",
  client_order_id: `agent-${Date.now()}-SPY-c650`,
});

// positions / orders
const positions = await alpaca.getPositions();
const orders = await alpaca.getOrders({ status: "open" });

// market data (async generators)
for await (const bar of alpaca.getBarsV2("SPY", {
  start: "2026-08-01", timeframe: "1Day", limit: 100,
})) {
  console.log(bar);
}
```

## 4. Multi-leg (`mleg`) in JS

`createOrder` is a thin wrapper over `POST /v2/orders`, so pass the mleg fields directly:
```javascript
const spread = await alpaca.createOrder({
  order_class: "mleg",
  qty: 1,
  type: "limit",
  limit_price: 1.0,              // positive = DEBIT, negative = CREDIT
  time_in_force: "day",
  legs: [
    { symbol: "SPY260904C00650000", ratio_qty: 1, side: "buy",  position_intent: "buy_to_open" },
    { symbol: "SPY260904C00655000", ratio_qty: 1, side: "sell", position_intent: "sell_to_open" },
  ],
});
```
⚠️ If the SDK's typings reject `legs`/`order_class`, fall back to a raw `fetch`:
```javascript
await fetch("https://paper-api.alpaca.markets/v2/orders", {
  method: "POST",
  headers: {
    "APCA-API-KEY-ID": process.env.ALPACA_API_KEY,
    "APCA-API-SECRET-KEY": process.env.ALPACA_SECRET_KEY,
    "Content-Type": "application/json",
  },
  body: JSON.stringify(mlegPayload),
});
```
The REST API is the contract; the SDK is a convenience.

## 5. Streaming
```javascript
const ws = alpaca.data_stream_v2;                   // stocks
ws.onConnect(() => ws.subscribeForQuotes(["SPY"]));
ws.onStockQuote((q) => console.log(q));
ws.connect();

const trades = alpaca.trade_ws;                     // your order events
trades.onConnect(() => trades.subscribe(["trade_updates"]));
trades.onOrderUpdate((u) => console.log(u.event, u.order.symbol));
trades.connect();
```
⚠️ **Option data streaming support in the JS SDK is weaker than Python's** — the option stream is msgpack-only. If you need live option quotes, use Python for that component (or poll the chain over REST).

## 6. Notable gap for this hackathon

The **Alpaca MCP server** (Python, `uvx alpaca-mcp-server`) and the **Alpaca CLI** (Go) are language-agnostic — a Node agent can shell out to the CLI just as easily:
```javascript
import { execFile } from "node:child_process";
import { promisify } from "node:util";
const exec = promisify(execFile);
const { stdout } = await exec("alpaca", ["position", "list", "--quiet"]);
const positions = JSON.parse(stdout);
```
So choosing JS does **not** cost you the MCP-or-CLI requirement.
