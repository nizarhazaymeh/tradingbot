# 01 — Alpaca MCP Server (complete reference)

- Repo: https://github.com/alpacahq/alpaca-mcp-server
- Doc page: https://docs.alpaca.markets/us/docs/alpaca-mcp-server
- Product page: https://alpaca.markets/mcp-server
- PyPI: `alpaca-mcp-server` · MCP registry name: `io.github.alpacahq/alpaca-mcp-server`
- Raw: `../09_raw_sources/github/alpaca-mcp-server_README.md`, `../09_raw_sources/alpaca_docs_md/alpaca-mcp-server.md`

> **This satisfies half of the "MCP or CLI" core requirement.** Use it *and* the CLI.

## 1. 🔴 V2 is a complete rewrite — none of the V1 tools exist

> "Alpaca MCP Server **v2** is here. This version is a complete rewrite built with **FastMCP and OpenAPI**. If you're upgrading from v1, please read the Upgrade Guide — tool names, parameters, and configuration have changed."

> "V2 is a complete rewrite… **None of the V1 tools exist in V2** — tool names, parameters, and schemas have changed. You cannot use V2 as a drop-in replacement."

| Aspect | V1 | V2 |
|---|---|---|
| Tool names | Hand-crafted | Spec-derived with overrides (names may overlap, **schemas differ**) |
| Parameters | Custom schemas | Aligned with Alpaca API specs |
| Configuration | `.env` + `init` command | **Env vars in MCP client config only** |
| Tool filtering | Not supported | `ALPACA_TOOLSETS` env var |

**Implications for you:**
1. **Do not reuse V1 config** — no `.env`, no `init` command.
2. **Clear tool caches** — restart your MCP client after switching.
3. **Start a fresh chat/session** — old conversations cache old tool names.
4. **Update custom instructions/rules** that name V1 tools.
5. Any tutorial or blog post older than V2 is wrong about tool names.

To pin V1: `uvx alpaca-mcp-server==1.x.x serve`.

## 2. Prerequisites
- **Python 3.10+**
- **`uv`** — https://docs.astral.sh/uv/getting-started/installation/
- Alpaca Trading API keys (free paper account)
- An MCP client

## 3. Setup — credentials go in ONE place: the client config

> "Add the server to your MCP client config, then restart the client. No `init` command, no `.env` files — credentials are set in **one place only**."

### Claude Code (recommended for this hackathon)
```bash
claude mcp add alpaca --scope user --transport stdio uvx alpaca-mcp-server \
  --env ALPACA_API_KEY=your_alpaca_api_key \
  --env ALPACA_SECRET_KEY=your_alpaca_secret_key
```
Verify with `/mcp` in the Claude Code CLI.

### Claude Desktop
`~/Library/Application Support/Claude/claude_desktop_config.json` (Mac) / `%APPDATA%\Claude\claude_desktop_config.json` (Windows):
```json
{
  "mcpServers": {
    "alpaca": {
      "command": "uvx",
      "args": ["alpaca-mcp-server"],
      "env": {
        "ALPACA_API_KEY": "your_alpaca_api_key",
        "ALPACA_SECRET_KEY": "your_alpaca_secret_key"
      }
    }
  }
}
```

### Cursor
Install from the [Cursor Directory](https://cursor.directory/mcp/alpaca), or `~/.cursor/mcp.json` with the same block as Claude Desktop.

### VS Code
`.vscode/mcp.json` in the project root:
```json
{
  "mcp": {
    "servers": {
      "alpaca": {
        "type": "stdio",
        "command": "uvx",
        "args": ["alpaca-mcp-server"],
        "env": {
          "ALPACA_API_KEY": "your_alpaca_api_key",
          "ALPACA_SECRET_KEY": "your_alpaca_secret_key"
        }
      }
    }
  }
}
```

### PyCharm
File → Settings → Tools → Model Context Protocol (MCP) → add server. Type `stdio`, command `uvx`, arguments `alpaca-mcp-server`, then set the two env vars.

### Antigravity CLI
`~/.gemini/antigravity-cli/mcp_config.json` (global) or `.agents/mcp_config.json` (workspace) — same block.

### Docker
```bash
git clone https://github.com/alpacahq/alpaca-mcp-server.git
cd alpaca-mcp-server
docker build -t mcp/alpaca:latest .
```
```json
{"mcpServers":{"alpaca":{"command":"docker","args":[
  "run","--rm","-i",
  "-e","ALPACA_API_KEY=your_key",
  "-e","ALPACA_SECRET_KEY=your_secret",
  "-e","ALPACA_PAPER_TRADE=true",
  "mcp/alpaca:latest"]}}}
```

### Claude Mobile / ChatGPT
> "Alpaca does **not** provide a hosted remote MCP server."
You must host it yourself on a cloud provider and add it as a custom connector.
Guide: https://alpaca.markets/learn/how-to-deploy-alpaca-mcp-server-remotely-on-claude-mobile-app
ChatGPT connectors: https://help.openai.com/en/articles/11487775-connectors-in-chatgpt

Postman MCP request: https://www.postman.com/alpacamarkets/alpaca-public-workspace/mcp-request/692f489b9b9778b831623e0f

## 4. Configuration — environment variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `ALPACA_API_KEY` | ✅ | — | Your Alpaca API key |
| `ALPACA_SECRET_KEY` | ✅ | — | Your Alpaca secret key |
| `ALPACA_PAPER_TRADE` | | **`true`** | Set to `false` for live trading |
| `ALPACA_TOOLSETS` | | all | Comma-separated list of toolsets to enable |
| `ALPACA_MCP_USER_AGENT` | | `APCA-MCP-TRADING/<ver>` | Set to `""` to opt out of usage telemetry |

🔴 **Paper is the default. Never set `ALPACA_PAPER_TRADE=false`.**

### Toolset filtering — `ALPACA_TOOLSETS`
```json
{"env":{"ALPACA_API_KEY":"...","ALPACA_SECRET_KEY":"...",
        "ALPACA_TOOLSETS":"account,trading,assets,options-data,stock-data,news"}}
```

| Toolset | Description |
|---|---|
| `account` | Account info, config, portfolio history, activities |
| `trading` | Orders, positions, exercise options |
| `watchlists` | Watchlist CRUD |
| `assets` | Asset lookup, option contracts, calendar, clock |
| `stock-data` | Stock bars, quotes, trades, snapshots, screeners |
| `crypto-data` | Crypto bars, quotes, trades, snapshots, orderbooks |
| **`options-data`** | Option bars, quotes, trades, snapshots, chain, exchange codes |
| `corporate-actions` | Corporate action announcements |
| `news` | News articles for stocks and crypto |
| `fixed-income-data` | Fixed income (bond/treasury) quotes |
| `locates` | Short-sale locate requests and quotes |

💡 **Show a scoped `ALPACA_TOOLSETS` in your submission.** Restricting the agent to exactly the toolsets it needs is a *security control* — it demonstrates you understand that an MCP-connected LLM can place trades. Recommended for an options agent:
```
ALPACA_TOOLSETS=account,trading,assets,options-data,stock-data,news,corporate-actions
```
(Note: dropping `crypto-data`, `watchlists`, `fixed-income-data`, `locates` reduces the context cost of tool schemas too.)

## 5. 🔴 Complete tool list (V2)

### Account & Portfolio
| Tool | Description |
|---|---|
| `get_account_info` | Balance, margin, and account status |
| `get_account_config` | Trading restrictions, margin settings, PDT checks |
| `update_account_config` | Update account configuration settings |
| `get_portfolio_history` | Equity and P/L over time |
| `get_account_activities` | Fills, dividends, transfers |
| `get_account_activities_by_type` | Activities filtered by type |

### Trading (Orders)
| Tool | Description |
|---|---|
| `get_orders` | Retrieve orders with filters |
| `get_order_by_id` | Single order by ID |
| `get_order_by_client_id` | Single order by client order ID |
| `replace_order_by_id` | Replace an existing open order |
| `cancel_order_by_id` | Cancel a specific order |
| `cancel_all_orders` | Cancel all open orders |
| `place_stock_order` | Stocks/ETFs (market, limit, stop, stop-limit, trailing-stop, brackets) |
| `place_crypto_order` | Crypto (market, limit, stop-limit) |
| **`place_option_order`** | **Options (single-leg or multi-leg)** ⭐ |

### Positions
| Tool | Description |
|---|---|
| `get_all_positions` | All current positions |
| `get_open_position` | Details for a specific position |
| `close_position` | Close a specific position |
| `close_all_positions` | Liquidate entire portfolio |
| `exercise_options_position` | Exercise a held option contract |
| `do_not_exercise_options_position` | Do-not-exercise instruction |

### Watchlists
`create_watchlist` · `get_watchlists` · `get_watchlist_by_id` · `update_watchlist_by_id` · `delete_watchlist_by_id` · `add_asset_to_watchlist_by_id` · `remove_asset_from_watchlist_by_id`

### Assets & Market Info
| Tool | Description |
|---|---|
| `get_all_assets` | List assets with optional filtering |
| `get_asset` | Detailed info for a specific asset |
| **`get_option_contracts`** | Option contracts for underlying symbol(s) |
| `get_option_contract` | Single option contract by symbol or ID |
| `get_calendar` | Market calendar for a date range |
| `get_clock` | Current market status and next open/close |
| `get_corporate_action_announcements` | Corporate action announcements |
| `get_corporate_action_announcement` | Single announcement by ID |

### Stock Data
`get_stock_bars` · `get_stock_quotes` · `get_stock_trades` · `get_stock_latest_bar` · `get_stock_latest_quote` · `get_stock_latest_trade` · `get_stock_snapshot` · `get_most_active_stocks` · `get_market_movers`

### Crypto Data
`get_crypto_bars` · `get_crypto_quotes` · `get_crypto_trades` · `get_crypto_latest_bar` · `get_crypto_latest_quote` · `get_crypto_latest_trade` · `get_crypto_snapshot` · `get_crypto_latest_orderbook`

### 🔴 Options Data
| Tool | Description |
|---|---|
| `get_option_bars` | Historical OHLCV bars |
| `get_option_trades` | Historical trades |
| `get_option_latest_trade` | Latest trade |
| `get_option_latest_quote` | Latest quote with bid/ask and exchange info |
| **`get_option_snapshot`** | **Snapshot with Greeks and IV** ⭐ |
| **`get_option_chain`** | **Full option chain for an underlying** ⭐ |
| `get_option_exchange_codes` | Exchange code → name mapping |

### Corporate Actions / News / Fixed Income / Locates
`get_corporate_actions` · `get_news` · `get_fixed_income_latest_quotes` · `get_locates` · `create_locate` · `get_locate` · `get_locate_quotes`

### 🔴 Documentation tools (underused — your agent can read its own API docs)
| Tool | Description |
|---|---|
| `search_alpaca_docs` | Search Alpaca documentation pages and guides |
| `fetch_alpaca_doc` | Fetch one Alpaca ReadMe documentation page by page ID |
| `search_alpaca_api_specs` | Search Alpaca API reference endpoints by topic, path, parameter, or schema term |
| `list_alpaca_api_endpoints` | List endpoints for one allowed Alpaca OpenAPI spec |
| `get_alpaca_endpoint_docs` | Fetch reference docs for one exact endpoint by method and path |

> "Docs are scoped to the **Trading API, Market Data API, and Authentication API** specs; **Broker API endpoint docs are intentionally excluded**."
> "If the ReadMe MCP lookup fails, tool responses include fallback links to Alpaca's public docs plus `llms.txt` and `llms-full.txt`."

💡 **A self-documenting agent is a genuine Creativity point:** when your agent hits an unfamiliar error or needs a parameter it doesn't know, it calls `search_alpaca_api_specs` / `get_alpaca_endpoint_docs` and fixes itself. Demo that.

## 6. Features summary (from the README)
- **Market data** — real-time quotes/trades/bars for stocks, crypto, options; historical data with flexible timeframes; **option Greeks and implied volatility**
- **Account management** — balances, buying power, account status, portfolio history
- **Order management** — market/limit/stop/stop-limit/trailing-stop for stocks/crypto/options; cancel individually or in bulk
- **Options trading** — search contracts by expiration/strike/type; place **single-leg or multi-leg** strategies; latest quotes, Greeks, IV
- **Crypto trading** — market/limit/stop-limit with GTC/IOC; quantity or notional
- **Position management** — view/close/liquidate; exercise option contracts
- **News** — filterable by ticker and date range
- **Market status** — open/close times, calendar, corporate actions
- **Watchlists** — create/update/manage
- **Asset search** — stocks, ETFs, crypto, options with filtering

## 7. Example prompts (verbatim from Alpaca) — use these in your demo video

**Option trading**
1. Show me available option contracts for AAPL expiring next month.
2. Get the latest quote for the AAPL250613C00200000 option.
3. Retrieve the option snapshot for the SPY250627P00400000 option.
4. Liquidate my position in 2 contracts of QQQ calls expiring next week.
5. Place a market order to buy 1 call option on AAPL expiring next Friday.
6. What are the option Greeks for the TSLA250620P00500000 option?
7. Find TSLA option contracts with strike prices within 5% of the current market price.
8. Get SPY call options expiring the week of June 16th, 2025, within 10% of market price.
9. **Place a bull call spread using AAPL June 6th options: one with a 190.00 strike and the other with a 200.00 strike.**
10. Exercise my NVDA call option contract NVDA250919C001680.

**Combined scenarios**
1. Get today's market clock and show me my buying power before placing a limit buy order for TSLA at $340.
2. **Place a bull call spread with SPY July 3rd options: sell one 5% above and buy one 3% below the current SPY price.**

**Market information** — note the caveat Alpaca attaches:
> "To access the latest 15-minute data, you need to subscribe to the [Algo Trader Plus Plan](https://alpaca.markets/data)."

## 8. Project structure (V2)
```
alpaca-mcp-server/
├── src/alpaca_mcp_server/
│   ├── cli.py                      ← CLI entry point
│   ├── server.py                   ← FastMCP server built from OpenAPI specs
│   ├── tool_registry.py            ← Tool names, descriptions, output risk classifications
│   ├── toolsets.py                 ← Toolset → operationId allowlists
│   ├── overrides.py                ← Hand-crafted tools for complex trading endpoints
│   ├── market_data_overrides.py    ← Hand-crafted tools for historical data
│   ├── readme_docs.py              ← Read-only proxy tools for Alpaca ReadMe docs
│   └── specs/{trading-api.json, market-data-api.json}
├── tests/{test_integrity.py, test_server_construction.py,
│          test_readme_integration.py, test_paper_integration.py}
├── scripts/sync-specs.sh           ← Download latest OpenAPI specs
├── AGENTS.md                       ← Instructions for coding agents
└── .github/workflows/ci.yml
```

Note `tool_registry.py` contains **"output risk classifications"** — Alpaca classifies its own tools by risk. Worth reading if you want to mirror that classification in your agent's approval logic.

## 9. Testing (mirror this in your repo)
```bash
# Core tests — no credentials needed
pytest tests/test_integrity.py tests/test_server_construction.py -v

# Integration tests — requires paper API keys
ALPACA_API_KEY=... ALPACA_SECRET_KEY=... pytest tests/ -m integration -v

# ReadMe docs integration tests
ALPACA_RUN_README_INTEGRATION=true pytest tests/test_readme_integration.py -v
```
Test layers: integrity (spec ↔ toolset ↔ names consistency, no network), server construction (mocked creds, verifies tool count), paper API integration (real calls), ReadMe integration.

## 10. Troubleshooting
| Problem | Fix |
|---|---|
| `uv`/`uvx` not found | Install uv, restart the terminal so it's on PATH |
| Credentials missing | Set `ALPACA_API_KEY`/`ALPACA_SECRET_KEY` in the client's `env` block |
| Client didn't pick up new config | **Restart the client** |
| HTTP port conflicts | With `--transport streamable-http`, change `--port` |

## 11. 🔴 Security notice (verbatim)
> "This server **can place real trades** and access your portfolio. Treat your API keys as sensitive credentials. **Review all actions proposed by the LLM carefully, especially for complex options strategies or multi-leg trades.**"

**HTTP transport:** defaults to localhost (127.0.0.1:8000). For remote access, bind `--host 0.0.0.0`, use SSH tunnelling (`ssh -L 8000:localhost:8000 user@server`), or a reverse proxy with authentication.

**Telemetry:** user-agent `APCA-MCP-TRADING/<version>` is sent to identify MCP usage; not shared with third parties. Opt out by setting `ALPACA_MCP_USER_AGENT=""`.

## 12. Support
- GitHub issues: https://github.com/alpacahq/alpaca-mcp-server/issues
- Email: support@alpaca.markets
