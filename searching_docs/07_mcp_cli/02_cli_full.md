# 02 — Alpaca CLI (complete reference)

- Repo: https://github.com/alpacahq/cli (Apache 2.0, Go)
- Doc page: https://docs.alpaca.markets/us/docs/alpacas-cli
- Launch blog: https://alpaca.markets/blog/alpaca-introduces-cli-for-trading-api/
- Agent skill: `.agents/skills/alpaca-cli/SKILL.md` in the repo
- Raw: `../09_raw_sources/github/cli_README.md`, `../09_raw_sources/github/skills/cli_SKILL.md`, `../09_raw_sources/alpaca_docs_md/alpacas-cli.md`

> ⚠️ **Alpha Preview** — "This CLI is under active development. Commands, flags, and output formats may change or be removed without notice between releases. Do not depend on current behavior in production workflows."
> The **installed binary is the source of truth**: `alpaca --help-all`.

## 1. 🔴 "Built For Agents" — why Alpaca gave you this

> "Alpaca CLI is designed for **AI agents, scripts, and automation pipelines**. It is **not** an interactive trading terminal: there are **no confirmation prompts**, 'are you sure?' dialogs, or interactive guardrails. **Every command executes immediately.**"

> "Destructive commands are truly destructive:
> - `alpaca position close-all` **liquidates your entire portfolio**
> - `alpaca order cancel-all` cancels every open order **without listing them first**
> - `alpaca locate create` requests shares for a short sale and **may incur locate fees**"

> "**Paper trading is the default. Live trading requires an explicit opt-in.**"

And from the hackathon event page, Alpaca's own framing:
> "The same trading functions from a terminal command, with structured JSON output. **Built for long-running agent sessions, cron jobs and CI, where MCP is heavier than needed.**"

➡️ That last line is a direct architectural hint: **CLI for the unattended cron loop, MCP for the interactive session.** Do both and say so.

## 2. Install
```bash
# Go
go install github.com/alpacahq/cli/cmd/alpaca@latest      # ensure ~/go/bin is on PATH
# Homebrew (macOS / Linux)
brew install alpacahq/tap/cli
# verify
alpaca version
alpaca doctor
```

## 3. Authentication

### OAuth (paper only)
```bash
alpaca profile login          # opens a browser; stores profile in ~/.config/alpaca/profiles/ at 0600
```
> "OAuth is currently **paper-only**. Live trading requires API keys."

### API keys
```bash
alpaca profile login --api-key                     # paper
alpaca profile login --api-key --live              # live
alpaca profile login --api-key --name prod --live  # named live profile
alpaca profile switch prod
alpaca profile list
alpaca profile logout <name>
```

### 🔴 Environment variables — the right choice for agents/CI
> "For scripts, CI, and agents, prefer environment variables so secrets do not touch disk."
```bash
export ALPACA_API_KEY=PK...
export ALPACA_SECRET_KEY=...
alpaca account get --quiet
```
> "Environment API keys **default to paper trading**."

### Credential lookup order
1. `ALPACA_API_KEY` **and** `ALPACA_SECRET_KEY`
2. Profile `access_token`
3. Profile `api_key` and `secret_key`

> "A **partial** environment bundle falls through to the active profile." ⚠️ So if you export only `ALPACA_API_KEY` and forget the secret, the CLI silently uses your *profile* — possibly a different account. **Always export both, together.**
> "OAuth tokens cannot be supplied through environment variables."

⚠️ **From the paper-trading-cli skill:** *"Set [the profile] via the `ALPACA_PROFILE` environment variable for the whole session — **never** with the `-p`/`--profile` flag."* (There's a flag-parsing caveat behind this.)

## 4. Configuration

| Variable | Description |
|---|---|
| `ALPACA_API_KEY` | API key. Must be set with `ALPACA_SECRET_KEY`. |
| `ALPACA_SECRET_KEY` | Secret key. Must be set with `ALPACA_API_KEY`. |
| `ALPACA_LIVE_TRADE` | 🔴 `true` routes to **live**. Anything else → paper. **Never set this.** |
| `ALPACA_PROFILE` | Profile name to use |
| `ALPACA_OUTPUT` | Default output format: `json` or `csv` |
| `ALPACA_CONFIG_DIR` | Config dir. Default `~/.config/alpaca` |
| `ALPACA_QUIET` | Suppress non-data output (warnings, hints, color) |
| `ALPACA_VERBOSE` | HTTP request summaries on stderr |
| `ALPACA_DEBUG` | HTTP request/response headers and bodies on stderr |
| `ALPACA_TRACE` | HTTP timing breakdown on stderr |

Global flags: `--csv` `--jq` `--profile` `--verbose` `--debug` `--trace` `--quiet` `--schema` `--timeout`

## 5. Commands

### Discoverability — the binary is the source of truth
```bash
alpaca --help-all                # FULL command tree with all flags
alpaca --help                    # top-level groups
alpaca order submit --help       # flags for one command
alpaca order list --schema       # response schema WITHOUT calling the API
```

### Top-level areas
- **Trading:** `order` `position` `option` `locate` `clock` `calendar`
- **Account & assets:** `account` `asset` `watchlist` `wallet` `corporate-action`
- **Market data:** `data` `data crypto` `data option` `data forex` `data index` `data meta` `data screener` `data news`
- **Utilities:** `profile` `api` `doctor` `update` `version` `completion`

### Account & portfolio
```bash
alpaca account get                  # equity, buying power
alpaca account config get
alpaca account config set
alpaca account activity list        # fills, dividends, transfers (and options NTAs)
alpaca account portfolio            # equity & P&L history  ← your equity curve
```

### Orders
```bash
alpaca order submit --symbol AAPL --side buy --qty 10 --type market
alpaca order submit --symbol AAPL --side buy --qty 10 --type limit --limit-price 185
alpaca order list                                  # default: open
alpaca order list --status all
alpaca order get --order-id <id>
alpaca order get-by-client-id --client-order-id <id>
alpaca order replace --order-id <id> --qty 20
alpaca order cancel --order-id <id>
alpaca order cancel-all
alpaca order submit ... --dry-run                  # PREVIEW without submitting
```

### Positions
```bash
alpaca position list
alpaca position get --symbol AAPL
alpaca position close --symbol AAPL
alpaca position close-all           # 🔴 liquidates everything, no confirmation
```

### 🔴 Options
```bash
alpaca option contracts --underlying-symbol AAPL
alpaca option get --symbol-or-id AAPL250620C00200000
alpaca option exercise --symbol-or-id <contract>
alpaca option do-not-exercise --symbol-or-id <contract>
```

### Market data — stocks
```bash
alpaca data bars --symbol AAPL --start 2025-01-01 --timeframe 1Day
alpaca data quotes --symbol AAPL --start 2025-06-01
alpaca data trades --symbol AAPL --start 2025-06-01
alpaca data latest-bar   --symbol AAPL
alpaca data latest-quote --symbol AAPL
alpaca data latest-trade --symbol AAPL
alpaca data snapshot     --symbol AAPL
alpaca data screener most-actives
alpaca data screener movers
```

### 🔴 Market data — options
```bash
alpaca data option chain         --underlying-symbol AAPL
alpaca data option snapshot      --symbol AAPL250620C00200000
alpaca data option latest-quotes --symbol AAPL250620C00200000
```

### Market data — crypto & other
```bash
alpaca data crypto bars --symbol BTC/USD --start 2025-01-01 --timeframe 1Day
alpaca data crypto latest-quotes --symbol BTC/USD,ETH/USD
alpaca data crypto snapshots --symbol BTC/USD
alpaca data crypto-orderbook --symbol BTC/USD
alpaca data news --symbol AAPL
alpaca data corporate-actions --symbols AAPL --types dividend
alpaca data forex rates --currency-pairs USD/EUR
alpaca clock
alpaca calendar
```

### Watchlists & assets
```bash
alpaca watchlist list
alpaca watchlist create --name "Tech Stocks" --symbols AAPL,MSFT,NVDA
alpaca watchlist get --watchlist-id <id>
alpaca watchlist add    --watchlist-id <id> --symbol GOOGL
alpaca watchlist remove --watchlist-id <id> --symbol GOOGL
alpaca watchlist delete --watchlist-id <id>
alpaca asset list
alpaca asset get --symbol AAPL
```

### 🔴 Raw API escape hatch — how you place multi-leg orders
```bash
alpaca api GET /v2/account
echo '{"symbol":"AAPL","qty":"1","side":"buy","type":"market","time_in_force":"day"}' \
  | alpaca api POST /v2/orders
```
> ✅ **VERIFIED 2026-08-30 on CLI v0.0.14:** `alpaca order submit` **DOES** support multi-leg natively.
> Real flags present: `--legs string` ("list of order legs (<= 4)"), `--order-class string`,
> `--position-intent string`, `--client-order-id`, `--dry-run`.
> The help text confirms `--symbol` and `--side` are "Required for all order classes **except for mleg**".
> So you can use **either**:
> ```bash
> alpaca order submit --order-class mleg --qty 1 --type limit --limit-price -1.35 \
>   --time-in-force day --legs '<json array of legs>' --client-order-id "$(uuidgen)" --dry-run
> ```
> **or** the raw path `alpaca api POST /v2/orders < spread.json` (safer for complex payloads —
> no shell quoting of nested JSON). Use `--dry-run` first to see the exact request body the CLI builds.

**There is no documented `--legs` flag on `alpaca order submit`.** Multi-leg orders go through the raw API path:
```bash
alpaca api POST /v2/orders < spread.json
```
Confirm what your build supports:
```bash
alpaca order submit --help | grep -iE 'leg|order-class'
alpaca --help-all | grep -iE 'mleg|leg'
```
This is a legitimate, documented CLI usage — it satisfies the CLI requirement *and* does the most advanced order type Alpaca offers. Say exactly that in the write-up.

## 6. Output

JSON on stdout by default.
```bash
alpaca position list
alpaca position list --csv
alpaca position list --jq '.[0].symbol'
alpaca position list --jq '[.[] | {symbol, qty, unrealized_pl}]'    # built-in jq, no external binary
alpaca order list --quiet
alpaca data bars --symbol AAPL --start 2020-01-01 --timeout 120
```

Operational commands (`version`, `doctor`, `profile`, `update`, `completion`, help) emit human-readable text. Exception: `alpaca update --check` emits JSON.

**Errors are JSON on stderr:**
```json
{"error":"rate limited","code":0,"status":429,"hint":"Rate limited. Reduce request frequency or add delays between calls."}
```

**Exit codes:**
| Code | Meaning |
|---|---|
| `0` | Success |
| `1` | API or general error |
| `2` | **Authentication error** |

➡️ Exit code 2 means "stop and re-authenticate", never "retry".

## 7. 🔴 Automation notes for agents

### Idempotency
> "For unattended order submission, pass `--client-order-id` so retries after ambiguous failures do not create duplicate orders."
```bash
client_order_id="$(uuidgen)"
alpaca order submit --symbol AAPL --side buy --qty 10 --type market \
  --client-order-id "$client_order_id" --quiet
```
`--client-order-id` accepts up to 128 characters. "the API rejects duplicate submissions with the same `client_order_id`, preventing accidental double-orders in retry logic."

### Dry run
```bash
alpaca order submit --symbol AAPL --side buy --qty 10 --type limit --limit-price 185.00 --dry-run
```

### 🔴 Retries — already built in, do NOT wrap it
> "The CLI retries **429 and 5xx** responses with exponential backoff up to **3 attempts**. `Retry-After` headers are respected."

And from the skill:
> "**Do not add your own retry loop for rate limits.** The CLI already retries 429 and 5xx responses up to three times and respects `Retry-After`. A second backoff layer on top of it turns one rate-limited call into a much longer stall. If a command still fails after the CLI's retries, surface the error and stop."

### MCP client whitelisting — read the warning
> "When using the CLI from an AI agent in Cursor or Claude, you can whitelist CLI commands to skip confirmation prompts. **Note that this removes a safety layer: an agent with whitelisted order commands can trade without human confirmation.**"

Whitelist read-only commands liberally; keep `order submit`, `position close-all`, `order cancel-all` behind your own gate.

## 8. Diagnostics
```bash
alpaca doctor                  # config + API connectivity
alpaca account get --verbose   # request summary on stderr
alpaca account get --trace     # DNS, TLS, TTFB, total timing
alpaca account get --debug     # headers and bodies
```
> "Credentials are always scrubbed from diagnostic output."

## 9. Shell completions & self-update
```bash
alpaca completion fish   # or bash / zsh / powershell
alpaca update            # check + prompt
alpaca update --yes      # non-interactive
alpaca update --check    # machine-readable
```
| Install method | Upgrade command |
|---|---|
| Go | `go install github.com/alpacahq/cli/cmd/alpaca@latest` |
| Homebrew | `brew upgrade alpacahq/tap/cli` |

## 10. Development (the CLI is OpenAPI-generated)
> "The CLI is driven by OpenAPI specs in `api/specs/*.json`. Do not edit generated files directly."
```bash
make build / test / lint / check / generate / spec-update / test-integration
```

## 11. Important considerations (verbatim)
> - **Paper trading is the default**: Live trading requires explicit opt-in via `--live` or `ALPACA_LIVE_TRADE=true`. Scripts that forget to opt in will hit paper, not live.
> - **No confirmation prompts**: `alpaca order cancel-all` and `alpaca position close-all` execute immediately.
> - **API key security**: Keep your API keys secure and never share them.
> - **Order execution risk**: Orders execute directly against Alpaca's Trading API.
> - **Rate limits**: Alpaca's API has rate limits per account.

## 12. Ready-to-use cron loop for the competition

`agent_cycle.sh` — the unattended path that satisfies "autonomous" + "CLI":
```bash
#!/usr/bin/env bash
set -euo pipefail
export ALPACA_API_KEY="${ALPACA_API_KEY:?}"      # COMP account
export ALPACA_SECRET_KEY="${ALPACA_SECRET_KEY:?}"
export ALPACA_QUIET=1
LOG=./logs/agent-$(date -u +%Y%m%d).jsonl

# 0. Market gate
if [ "$(alpaca clock --jq '.is_open')" != "true" ]; then
  echo "{\"ts\":\"$(date -u +%FT%TZ)\",\"event\":\"market_closed\"}" >> "$LOG"; exit 0
fi

# 1. Snapshot state
alpaca account get       --jq '{equity,cash,options_buying_power,daytrade_count}' > state/account.json
alpaca position list                                                              > state/positions.json
alpaca order list --status open                                                    > state/open_orders.json
alpaca account activity list --page-size 50                                        > state/activities.json

# 2. Decide (Python: reads state/, writes intents/*.json)
python -m agent.decide --state ./state --out ./intents --log "$LOG"

# 3. Execute — every intent carries its own client_order_id
for f in intents/*.json; do
  [ -e "$f" ] || continue
  alpaca api POST /v2/orders < "$f" >> "$LOG" 2>&1 || echo "FAILED: $f" >> "$LOG"
  mv "$f" "intents/done/$(basename "$f")"
done

# 4. Archive the equity curve
alpaca account portfolio --period 1W --timeframe 15Min > "state/portfolio_$(date -u +%FT%H%M).json"
```
```cron
# every 5 minutes during US market hours (adjust TZ), Mon-Fri
*/5 13-20 * * 1-5  cd /path/to/agent && ./agent_cycle.sh >> logs/cron.log 2>&1
```
⚠️ Add a lock file so a slow run can't overlap itself:
```bash
exec 9>/tmp/alpaca-agent.lock
flock -n 9 || { echo "already running"; exit 0; }
```

## 13. Support
- CLI issues: https://github.com/alpacahq/cli/issues
- Alpaca forum: https://forum.alpaca.markets/
- Slack: https://alpaca.markets/slack
