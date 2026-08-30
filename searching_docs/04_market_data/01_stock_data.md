# 01 — Stock / Equity Market Data

Sources: `historical-stock-data-1.md`, `real-time-stock-pricing-data.md`, `historical-api.md`, `market-data-faq.md`, references `stock*.md`

Base: `https://data.alpaca.markets` (same host for paper and live)

## 1. Historical endpoints

| Endpoint | Path | Ref |
|---|---|---|
| Historical bars (multi-symbol) | `/v2/stocks/bars?symbols=` | `stockbars` |
| Historical bars (single) | `/v2/stocks/{symbol}/bars` | `stockbarsingle-1` |
| Latest bars | `/v2/stocks/bars/latest?symbols=` | `stocklatestbars-1` |
| Historical quotes | `/v2/stocks/quotes?symbols=` | `stockquotes-1` |
| Latest quotes | `/v2/stocks/quotes/latest?symbols=` | `stocklatestquotes-1` |
| Historical trades | `/v2/stocks/trades?symbols=` | `stocktrades-1` |
| Latest trades | `/v2/stocks/trades/latest?symbols=` | `stocklatesttrades-1` |
| **Snapshots** | `/v2/stocks/snapshots?symbols=` | `stocksnapshots-1` |
| Historical auctions | `/v2/stocks/auctions?symbols=` | `stockauctions-1` |
| Condition codes | `/v2/stocks/meta/conditions/{ticktype}` | `stockmetaconditions-1` |
| Exchange codes | `/v2/stocks/meta/exchanges` | `stockmetaexchanges-1` |

**Always prefer the multi-symbol form.** One call for 100 symbols beats 100 calls — and you only have 200 calls/min.

## 2. Snapshot — the highest-value single call

`GET /v2/stocks/snapshots?symbols=AAPL,MSFT,SPY` returns per symbol, in one response:
- `latestTrade`
- `latestQuote`
- `minuteBar`
- `dailyBar`
- `prevDailyBar`

That's five data views for the price of one request. For an options agent that needs the underlying's current price, today's range, and yesterday's close, this is the correct endpoint.

```bash
alpaca data snapshot --symbol SPY,QQQ,IWM,AAPL,NVDA
```

## 3. Timeframes

`1Min`, `5Min`, `15Min`, `30Min`, `1Hour`, `4Hour`, `1Day`, `1Week`, `1Month` — and arbitrary multiples (`3Min`, `2Hour`, …).

⚠️ **Only minute and daily bars are built from trades.** Everything else is aggregated (see `../02_alpaca_platform/04_market_data_plans_and_limits.md` §5). If your indicator needs exact intraday OHLC, pull `1Min` and aggregate yourself.

## 4. Feeds

| `feed` | Availability | Notes |
|---|---|---|
| `iex` | **Basic / free** | IEX exchange only, real-time |
| `sip` | Algo Trader Plus | Full consolidated tape (CTA + UTP) |
| `delayed_sip` | Basic | SIP delayed 15 minutes |
| `boats`, `overnight` | special | |

Default feed if unspecified is `iex` on Basic.

🔴 **IEX is ~2–3% of consolidated volume.** Practical impact on an options agent:
- Latest trade price can differ slightly from the consolidated last.
- **Volume is IEX-only volume** → relative-volume and volume-breakout signals are distorted. Either avoid volume signals or normalize against IEX's own history (compare today's IEX volume to the 20-day average of *IEX* volume, never to a consolidated figure from elsewhere).
- `delayed_sip` gives you *accurate* consolidated data 15 minutes late. For a **daily** or **hourly** strategy that's often better than real-time IEX. Consider using `delayed_sip` for features and `iex` only for the execution-time price check.

## 5. Request parameters

`symbols` (comma-separated), `timeframe`, `start`, `end`, `limit`, `adjustment` (`raw`|`split`|`dividend`|`all`), `asof`, `feed`, `currency`, `page_token`, `sort` (`asc`|`desc`).

**Use `adjustment=all`** for any historical series you compute indicators from, otherwise splits will create fake gaps.

Pagination: responses include `next_page_token`; loop until null.

## 6. Screeners — free universe selection

| Endpoint | Path | Ref |
|---|---|---|
| Most active stocks | `/v1beta1/screener/stocks/most-actives` | `mostactives-1` |
| Top market movers | `/v1beta1/screener/{market_type}/movers` | `movers-1` |

```bash
alpaca data screener most-actives
alpaca data screener movers
```
Params: `by` (`volume` | `trades`), `top` (count).

These are a *free signal* most entrants ignore. "Most active" is a decent proxy for where options liquidity is today, and "movers" is a ready-made momentum candidate list. Combine with the `options_enabled` asset attribute to get "liquid names that have options" in two API calls.

## 7. News

| Endpoint | Path | Ref |
|---|---|---|
| Historical news | `/v1beta1/news` | `news-3` |
| Real-time news stream | `wss://stream.data.alpaca.markets/v1beta1/news` | `streaming-real-time-news` |

Params: `symbols`, `start`, `end`, `sort`, `include_content`, `exclude_contentless`, `limit`, `page_token`.

```bash
alpaca data news --symbol AAPL,NVDA
```
This is the natural LLM input: headlines + content → a structured view/conviction, which then selects an options structure. Free on Basic.

## 8. Logos & metadata
`/v1beta1/logos/{symbol}` (`logos-5`) — company logos. Purely cosmetic, but it makes a Streamlit demo look finished in 10 minutes of work.

## 9. Corporate actions
`/v1beta1/corporate-actions` (`corporateactions-1`) — see `../03_trading_api/03_assets_clock_calendar.md` §6.

## 10. Websocket streaming (stocks)
`wss://stream.data.alpaca.markets/v2/{feed}` — see `04_websocket_streaming.md`.
