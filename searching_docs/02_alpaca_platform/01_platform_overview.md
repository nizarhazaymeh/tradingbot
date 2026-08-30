# 01 — Alpaca Platform Overview

Sources: https://docs.alpaca.markets/us/docs/getting-started · `about-alpaca` · `alpaca-api-platform` · https://alpaca.markets/
Raw: `../09_raw_sources/alpaca_docs_md/{getting-started,about-alpaca,alpaca-api-platform,additional-resources}.md`

## 1. What Alpaca is

Alpaca offers API-first solutions to trade stocks, options, ETFs and crypto. It is a **programmable brokerage**: you provide an API key, and your application can place real orders. Alpaca provides the brokerage infrastructure; you build the application.

- Securities brokerage: **Alpaca Securities LLC** (dba "Alpaca Clearing"), member FINRA/SIPC, wholly-owned subsidiary of **AlpacaDB, Inc.**
- Crypto: **Alpaca Crypto LLC**, FinCEN-registered MSB (NMLS # 2160858). Not SIPC/FINRA.
- Technology and services: AlpacaDB, Inc.

## 2. The four APIs

| API | For | Docs |
|---|---|---|
| **Trading API** | Individual & business trading — your own bots and algos. **← this is the hackathon's API** | https://docs.alpaca.markets/us/docs/trading-api |
| **Broker API** | Building brokerage services for *other people's* accounts (fintechs, apps) | https://docs.alpaca.markets/us/docs/about-broker-api |
| **Market Data API** | Real-time pricing + historical data for equities, options, crypto, news | https://docs.alpaca.markets/us/docs/about-market-data-api |
| **Connect API** | OAuth2 so third-party apps can act on behalf of Alpaca users | https://docs.alpaca.markets/us/docs/about-connect-api |

Also available: **FIX API** (FIX 4.2 order entry) — not relevant here.

> For this hackathon you need **Trading API + Market Data API** only. Broker API is a distractor; ignore it. (The MCP server even excludes Broker API endpoint docs by design.)

## 3. Trading API capabilities (marketing page summary)

> Trade stocks & crypto with Alpaca's easy to use Trading API. Up to 4X intraday & 2X overnight buying power. Short selling. Advanced order types.

Asset classes: US stocks & ETFs, **US options (single-leg and multi-leg)**, crypto, fixed income (treasuries/corporates), tokenized assets.

## 4. Documentation superpowers (use these — they save hours)

Two features of Alpaca's docs make it fully machine-readable:

### a) `llms.txt` — the complete doc index
```
https://docs.alpaca.markets/us/llms.txt        # US docs: 389 lines, every guide + every API reference
https://docs.alpaca.markets/llms.txt           # root index
```
Local copies: `../09_raw_sources/indexes/us_llms.txt`, `root_llms.txt`

### b) `.md` suffix on any doc URL returns clean markdown
```
https://docs.alpaca.markets/us/docs/options-trading      → HTML
https://docs.alpaca.markets/us/docs/options-trading.md   → markdown
https://docs.alpaca.markets/us/reference/postorder.md    → markdown incl. full OpenAPI schema
```

**This is how all 103 Alpaca docs in `../09_raw_sources/` were captured.** Reuse the pattern to pull any doc into your agent's context at runtime:
```bash
curl -sL "https://docs.alpaca.markets/us/docs/options-level-3-trading.md"
```

The MCP server also exposes doc-search tools (`search_alpaca_docs`, `fetch_alpaca_doc`, `search_alpaca_api_specs`, `list_alpaca_api_endpoints`, `get_alpaca_endpoint_docs`) so your agent can look up its own API reference mid-run. See `../07_mcp_cli/01_mcp_server_full.md`.

## 5. Key URLs

| Purpose | URL |
|---|---|
| Paper trading dashboard | https://app.alpaca.markets/paper/dashboard/overview |
| Sign up (Trading API) | https://app.alpaca.markets/signup |
| Login | https://app.alpaca.markets/account/login |
| Docs home | https://docs.alpaca.markets |
| API reference (OpenAPI) | https://docs.alpaca.markets/reference |
| Doc index for LLMs | https://docs.alpaca.markets/us/llms.txt |
| Market data plans | https://alpaca.markets/data |
| MCP server product page | https://alpaca.markets/mcp-server |
| Agentic / AI-first page | https://alpaca.markets/agentic |
| Options product page | https://alpaca.markets/options |
| Algo trading page | https://alpaca.markets/algotrading |
| Learn (tutorials/articles) | https://alpaca.markets/learn/ |
| Blog | https://alpaca.markets/blog/ |
| API status | https://status.alpaca.markets/ |
| GitHub org | https://github.com/alpacahq |
| Community forum | https://forum.alpaca.markets/ |
| Slack | https://alpaca.markets/slack |
| Postman workspace | https://www.postman.com/alpacamarkets/alpaca-public-workspace |
| Disclosures | https://alpaca.markets/disclosures |

## 6. Anything Alpaca supports that could differentiate you

Pulled from the doc index — features most entrants won't know exist:

| Feature | Doc | Why it could matter |
|---|---|---|
| **Multi-leg options (`mleg`)** | `options-level-3-trading` | Up to 4 legs, one atomic fill. The headline differentiator. |
| **Option Greeks & IV** on chain/snapshot | `optionchain`, `optionsnapshots` | Alpaca computes Black-Scholes Greeks for you. No third-party analytics needed. |
| **Screeners**: most actives, market movers | `mostactives-1`, `movers-1` | Free universe selection signal. |
| **Real-time news stream** | `streaming-real-time-news` | Event-driven options entries. |
| **Corporate actions API** | `corporateactions-1` | Avoid trading options through a split/dividend/merger. |
| **Portfolio history** | `getaccountportfoliohistory-1` | Your equity curve for the P&L slide, straight from the API. |
| **Account activities (incl. options NTAs)** | `account-activities`, `non-trade-activities-for-option-events` | Exercise/assignment/expiry events. |
| **Exercise / Do-Not-Exercise** | `optionexercise`, `optiondonotexercise` | Deliberate expiry management. |
| **Watchlists API** | `getwatchlists-1` | Persist your agent's universe server-side. |
| **`--dry-run` / order estimation** | CLI; `get-v1-trading-accounts-...-orders-estimation` | Preview before submit. |
| **24/5 trading + overnight session** | `245-trading-for-trading-api` | Equities only, not options. |
| **Elite Smart Router / DMA, TWAP, VWAP** | `alpaca-elite-smart-router` | Advanced equity order algos (`AdvancedInstructions`). Not for options. |
