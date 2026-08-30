# 02 — Accounts, Authentication & Base URLs

Sources: `authentication.md`, `getting-started-with-trading-api.md`, `account-plans.md`
Raw: `../09_raw_sources/alpaca_docs_md/`

## 1. Base URLs — get these right or nothing works

| Environment | Trading API | Market Data API |
|---|---|---|
| **Paper (you)** | `https://paper-api.alpaca.markets` | `https://data.alpaca.markets` |
| Live | `https://api.alpaca.markets` | `https://data.alpaca.markets` |
| Broker (live) | `https://broker-api.alpaca.markets` | `https://data.alpaca.markets` |
| Broker (sandbox) | `https://broker-api.sandbox.alpaca.markets` | `https://data.sandbox.alpaca.markets` |

⚠️ **Note the asymmetry: market data uses the SAME host (`data.alpaca.markets`) for paper and live.** Only the *trading* host changes. A very common bug is pointing market data at `paper-data...` (doesn't exist) or assuming paper keys can't read data (they can — with Basic entitlements).

Streaming hosts:
| Stream | URL |
|---|---|
| Stock data | `wss://stream.data.alpaca.markets/v2/{feed}` (`iex` or `sip`) |
| Option data | `wss://stream.data.alpaca.markets/v1beta1/{feed}` (`indicative` or `opra`) |
| Crypto data | `wss://stream.data.alpaca.markets/v1beta3/crypto/{loc}` |
| News | `wss://stream.data.alpaca.markets/v1beta1/news` |
| Trade updates (account events) | `wss://paper-api.alpaca.markets/stream` |

## 2. Authentication

### Legacy header auth (what you'll use)
```bash
curl -X GET "https://paper-api.alpaca.markets/v2/account" \
  -H "APCA-API-KEY-ID: {YOUR_API_KEY_ID}" \
  -H "APCA-API-SECRET-KEY: {YOUR_API_SECRET_KEY}"
```

### OAuth bearer (Connect API / CLI OAuth login)
```bash
curl -X GET "https://paper-api.alpaca.markets/v2/account" \
  -H "Authorization: Bearer {TOKEN}"
```
The Alpaca CLI's `alpaca profile login` uses OAuth and is **paper-only**. Live requires API keys.

### Environment variable names — three different conventions, don't mix them up

| Tool | Key var | Secret var | Base URL var |
|---|---|---|---|
| `alpaca-py` / legacy SDK | `APCA_API_KEY_ID` | `APCA_API_SECRET_KEY` | `APCA_API_BASE_URL` |
| **Alpaca CLI** | `ALPACA_API_KEY` | `ALPACA_SECRET_KEY` | (paper by default; `ALPACA_LIVE_TRADE=true` for live) |
| **Alpaca MCP server** | `ALPACA_API_KEY` | `ALPACA_SECRET_KEY` | (`ALPACA_PAPER_TRADE=true` default) |

Practical `.env` for this project — define both spellings:
```bash
# Alpaca — COMPETITION paper account
APCA_API_KEY_ID=PK...
APCA_API_SECRET_KEY=...
APCA_API_BASE_URL=https://paper-api.alpaca.markets
ALPACA_API_KEY=PK...
ALPACA_SECRET_KEY=...
ALPACA_PAPER_TRADE=true
# never set ALPACA_LIVE_TRADE
ALPACA_ACCOUNT_ID=<record it here for the submission>
```

## 3. Getting API keys

1. Sign up / log in: https://app.alpaca.markets/signup
2. Go to the **paper** dashboard: https://app.alpaca.markets/paper/dashboard/overview
3. API keys are in the right sidebar → **Generate**.
4. **The secret is shown once.** Copy it immediately.
5. Keys are **per paper account** — a new paper account needs new keys.

Anyone globally can create an Alpaca **Paper Only Account** with just an email. No card, no funding, no KYC.

## 4. Account model — the fields your agent must read

`GET /v2/account` (reference: `../09_raw_sources/alpaca_reference_md/getaccount-1.md`)

Fields that matter for an options agent:

| Field | Meaning |
|---|---|
| `id` | **The account ID you submit to the judges.** |
| `account_number` | Human-visible account number |
| `status` | `ACTIVE` expected |
| `equity` | Current total account value — your P&L numerator |
| `last_equity` | Previous close equity — for daily P&L |
| `cash` | Cash balance |
| `buying_power` | Total buying power (margin-inclusive) |
| **`options_buying_power`** | **The one that gates options orders.** Distinct from `buying_power`. |
| **`options_approved_level`** | Max level the account is approved for |
| **`options_trading_level`** | Current active level (can be ≤ approved) |
| `daytrade_count` | Day trades in the rolling window |
| `pattern_day_trader` | PDT flag |
| `multiplier` | Margin multiplier (1/2/4) |
| `shorting_enabled` | Whether short selling is on |
| `trading_blocked`, `account_blocked`, `transfers_blocked` | Must all be false |
| `initial_margin`, `maintenance_margin` | Margin currently required |
| `portfolio_value` | Alias of equity |

**Day 1 preflight your agent should run and log:**
```bash
alpaca account get --jq '{id, status, equity, cash, buying_power, options_buying_power, options_approved_level, options_trading_level, trading_blocked, multiplier, pattern_day_trader}'
```

## 5. Account configuration

`GET /v2/account/configurations` · `PATCH /v2/account/configurations`
(`getaccountconfig-1.md`, `patchaccountconfig-1.md`)

Notable settings:
- `max_options_trading_level` — shows the max; you can **downgrade** to a lower level via PATCH. A separate API handles *upgrade* requests on live accounts.
- `dtbp_check`, `trade_confirm_email`, `suspend_trade`, `no_shorting`, `fractional_trading`, `pdt_check`

`suspend_trade: true` is a legitimate **kill switch** for your agent — flip it and the account stops accepting orders. Worth wiring to your drawdown halt and mentioning in the write-up as a risk gate.

## 6. Options approval levels

From `options-trading.md`:

| Level | Supported trades | Validation |
|---|---|---|
| **0** | Options disabled | — |
| **1** | Sell covered call; sell cash-secured put | Must own sufficient underlying shares; must have sufficient options buying power |
| **2** | Level 1 + buy a call; buy a put | Sufficient options buying power |
| **3** | Levels 1–2 + buy a call spread; buy a put spread | Sufficient options buying power |

**In the Paper environment, options trading is enabled by default — nothing to request.** (Live has a more robust approval flow.)

Multi-leg (`mleg`) trading is described in Alpaca's docs as **Options Level 3**. Check your actual `options_approved_level` on Day 1 — build the strategy around what the account reports, not what you hope it is. See `../05_options/01_options_fundamentals_on_alpaca.md`.

## 7. Trading account plans

`account-plans.md` — for Trading API users the relevant plan axis is **market data** (Basic vs Algo Trader Plus), not trading. Trading itself is commission-free for US equities/options; options have per-contract regulatory fees on live (not simulated on paper).
