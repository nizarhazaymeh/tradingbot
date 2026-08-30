# 04 — Market Data: plans, feeds and the limits that shape your strategy

Sources: `about-market-data-api.md`, `market-data-faq.md`, `historical-option-data.md`, `real-time-option-data.md`, `paper-trading.md`
Raw: `../09_raw_sources/alpaca_docs_md/`

> ⚠️ **This is the most strategically important page in the whole study.** Your free-tier data entitlements dictate which options strategies are even *implementable*. Read it before designing the strategy.

## 1. The two Trading-API plans

> The **Basic** plan serves as the default option for both Paper and Live trading accounts… this plan only includes limited real-time data: for equities **only the IEX exchange**, for options **only the indicative feed**.

### Equities

| | Basic (free) | Algo Trader Plus |
|---|---|---|
| Pricing | **Free** | **$99 / month** |
| Real-time coverage | **IEX only** | Full SIP (CTA + UTP, 100% of volume) |
| Historical API calls | **200 / min** | 10,000 / min |

### Options

| | Basic (free) | Algo Trader Plus |
|---|---|---|
| Securities coverage | US Options Securities | US Options Securities |
| Real-time market coverage | **Indicative Pricing Feed** | **OPRA Feed** |
| Websocket subscriptions | **200 quotes** | 1,000 quotes |
| Historical data limitation | **latest 15 minutes** (excluded) | no restriction |
| Historical API calls | **200 / min** | 10,000 / min |

Data sources: equities from CTA (NYSE) + UTP (Nasdaq); options directly from OPRA.

> 💡 The **social engagement bonus prize includes a 1-month Algo Trader Plus subscription per team member** — i.e. the $99/mo OPRA-feed plan. That's a second reason the social posts are worth doing.

## 2. 🔴 What "Indicative feed" actually means

From `historical-option-data.md`:

| Source | Description |
|---|---|
| **Indicative** | "Indicative Pricing Feed is a free derivative of the original OPRA feed: **the quotes are not actual OPRA quotes, they're just indicative derivatives.** The trades are also derivatives and **they're delayed by 15 minutes**." |
| **OPRA** | The consolidated BBO feed of OPRA — highest bid / lowest offer across options markets. **Only available to subscribed users.** |

### The three concrete consequences for your agent

**1. Your option quotes are approximations, not the real NBBO.**
Do not build a strategy whose edge is sub-penny quote precision, microstructure, or crossing the spread by a tick. Build one whose edge survives a few cents of quote error. Wide risk/reward ratios, not scalping.

**2. Option trades are 15 minutes delayed, and historical option data excludes the latest 15 minutes.**
So `get_option_trades` / `alpaca data option trades` will not show you what just printed. Rely on **quotes + snapshots + Greeks**, and on **underlying** (equity) data for timing.

**3. Your fills come from a different source than your quotes.**
Paper fills are simulated against NBBO (`paper-trading.md`), while your *view* of options prices is indicative. Small divergences between your expected fill and your actual fill are normal and expected. Log both and don't chase the difference.

### Access errors
> Any attempt to access a data feed not available for your subscription will result in an error during authentication.

If you connect to `wss://stream.data.alpaca.markets/v1beta1/opra` on Basic, auth fails. Use `indicative`.

## 3. Rate limits

- **200 historical market-data API calls per minute** on Basic. This is a hard planning constraint.
- Trading API limits are not published as a number. Alpaca's own skill guidance:
  > "Drive throttling from the response headers rather than a hard-coded ceiling. Every response carries `X-RateLimit-Limit`, `X-RateLimit-Remaining`, and `X-RateLimit-Reset`; your agent slows down as `Remaining` approaches zero instead of waiting to be throttled. A figure of 200 requests per minute is widely cited for the Trading API but is not stated in Alpaca's current documentation, so do not hard-code it."

### Budgeting your 200 calls/min

A naive agent that polls the option chain for 30 underlyings every minute will be rate-limited immediately. Design pattern that fits:

| Pattern | Cost |
|---|---|
| ❌ Per-symbol loop over 500 tickers | 500 calls → instantly throttled |
| ✅ **One batched multi-symbol request** | 1 call. Bars, quotes, snapshots all accept comma-separated `symbols`. |
| ✅ `get_option_chain(underlying)` | **1 call returns the entire chain** with latest trade, latest quote, and Greeks for every strike. Use this instead of N snapshot calls. |
| ✅ Screener (`most-actives`, `movers`) for universe selection | 1 call |
| ✅ Cache the chain for 30–60s | cuts calls by 30–60× |

Alpaca's own multi-agent article makes exactly this point:
> "Individual requests for the 500 tickers hit rate limits before the data finishes loading. **One batch request solves this.**"

**Concrete budget for a 5-underlying options agent on a 1-minute loop:**
```
1  × clock                             (cache 60s → ~1/min)
1  × stock snapshots (5 symbols batched)
5  × option chain (1 per underlying)    ← the expensive part
1  × positions
1  × orders
= ~9 calls/min → 4.5% of budget. Room for 20 underlyings.
```

## 4. Data availability windows

| Data | Earliest available |
|---|---|
| **Historical option data** | **since February 2024** only |
| Historical stock data | 6+ years (2016+) |
| Historical crypto data | varies by pair |
| News | multi-year |

⚠️ **Options history starts Feb 2024.** Any backtest of an options strategy has ~2.5 years of data at most, and only ~1.5 years of it includes a real volatility regime change. Don't over-fit; and be honest about this limitation in your write-up — Alpaca's judges know it.

## 5. Bar aggregation rules (matters for indicator correctness)

Only **minute** and **daily** bars are built from trades. Everything else is aggregated from those:
- Open = open of the first bar
- High = max of bars' highs
- Low = min of bars' lows
- Close = close of the last bar
- Volume = sum of volumes
- Trade count = sum of trade counts
- VWAP = volume-weighted average of the bars' VWAPs

So a `1Hour` bar is built from minute bars, and a `1Week` bar from daily bars. If your indicator needs true tick-level OHLC, use minute bars and aggregate yourself.

## 6. Paper accounts and data entitlement

> As an Alpaca **Paper Only Account** holder, you are only entitled to receive and make use of **IEX market data**.

If your Alpaca account is paper-only (no live brokerage account), equities real-time = IEX. IEX is roughly 2–3% of US consolidated volume, so:
- IEX **last trade** can lag or differ from the consolidated last trade.
- IEX **bars** are IEX-only volume — volume-based signals (relative volume, volume breakouts) are distorted.
- ⚠️ **Greeks need the latest SIP trade for the underlying** (see below) — that's computed server-side by Alpaca, so Greeks are fine even on Basic. But *your own* underlying price reads are IEX.

**Mitigation:** for the underlying price, prefer the **option chain's implied underlying** or the **snapshot** endpoint over raw IEX trades, and treat volume-based signals with suspicion. Say so in the write-up — it shows you understood your data.

## 7. Summary table: what you can and can't build on the free tier

| Strategy family | Feasible on Basic? | Why |
|---|---|---|
| Delta-neutral vol arb needing true NBBO | ❌ | Indicative quotes aren't real NBBO |
| Options market making / spread capture | ❌ | Same |
| 0DTE gamma scalping | ⚠️ hard | 0DTE has **no Greeks**; 15-min trade delay |
| Short-dated directional spreads (debit/credit verticals) | ✅ | Needs only chain + Greeks + underlying trend |
| Iron condors / range-bound premium selling | ✅ | Needs IV + expected-range estimate |
| IV-rank / IV-percentile mean reversion | ✅ | Chain gives IV; compute rank from history (Feb 2024+) |
| Event-driven (earnings, news) options | ✅ | News stream + corporate actions API |
| Covered calls / cash-secured puts | ✅ | Level 1; simplest and safest |
| Calendar spreads | ⚠️ | `mleg` rejects uncovered legs — see `../05_options/02` |
| Volume-breakout on the underlying | ⚠️ | IEX volume is a fraction of consolidated |

➡️ The strategy recommendation built on this analysis is in `../08_strategy_playbook/03_pnl_strategy_and_risk_gates.md`.
