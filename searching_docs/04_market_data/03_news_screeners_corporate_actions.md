# 03 — News, Screeners, Corporate Actions & Crypto data

The "free alpha" endpoints most entrants never touch. All free on Basic.

## 1. News API — the natural LLM input

**Historical:** `GET /v1beta1/news` (`news-3.md`)
**Real-time:** `wss://stream.data.alpaca.markets/v1beta1/news` (`streaming-real-time-news.md`)

Params: `symbols`, `start`, `end`, `sort`, `include_content` (full article body), `exclude_contentless`, `limit`, `page_token`.

Response per article: `id`, `headline`, `author`, `created_at`, `updated_at`, `summary`, `content`, `url`, `images[]`, `symbols[]`, `source`.

```bash
alpaca data news --symbol NVDA,AAPL,SPY
```
```python
from alpaca.data.historical.news import NewsClient
from alpaca.data.requests import NewsRequest
NewsClient(KEY, SECRET).get_news(NewsRequest(
    symbols="NVDA,AMD", start=..., include_content=True, exclude_contentless=True, limit=50))
```

### Why it matters for an options agent
Options price **expected volatility**, and news is what changes expectations. The clean, defensible LLM role:

```
news + content  →  LLM  →  structured view
                             { direction: up|down|neutral,
                               magnitude: small|medium|large,
                               horizon_days: int,
                               confidence: 0..1,
                               catalyst: string,
                               rationale: string }
                                    ↓
                          deterministic mapper → options structure
```
Direction+magnitude+horizon maps mechanically to a structure (see `../05_options/05_strategy_cookbook.md`). **The LLM never picks strikes.** That separation is the single most defensible architectural choice you can make, and it's exactly what Alpaca's reference article advocates ("Risk checks run as deterministic code, unit-tested, with no model in the loop").

**Real-time stream** is how you make it *autonomous* rather than polled — a headline arrives, the agent wakes, forms a view, gates it, trades it. That's a genuinely strong demo moment for the video.

## 2. Screeners

| Endpoint | Path |
|---|---|
| Most active stocks | `GET /v1beta1/screener/stocks/most-actives?by=volume&top=50` |
| Top market movers | `GET /v1beta1/screener/{market_type}/movers?top=50` |

```bash
alpaca data screener most-actives
alpaca data screener movers
```

**Universe construction in 2 calls:**
```
1. GET /v1beta1/screener/stocks/most-actives?by=volume&top=50
2. GET /v2/assets?attributes=options_enabled&status=active
   → intersect → "today's most liquid names that have options"
```
Then filter by option-chain liquidity (open interest, spread width). This gives you a *dynamic, justified* universe instead of a hardcoded ticker list — a real Creativity/Originality point.

## 3. Corporate actions

**Market data (preferred):** `GET /v1beta1/corporate-actions` (`corporateactions-1.md`)
**Trading API (legacy):** `GET /v2/corporate_actions/announcements` — the docs point you at the newer endpoint.
**SSE:** `subscribetocorporateactionseventssse`

Types: cash dividends, stock dividends, forward/reverse splits, mergers, spin-offs, rights distributions, name/symbol changes, worthless removals, unit splits, redemptions.

```bash
alpaca data corporate-actions --symbols SPY,QQQ,AAPL,NVDA \
  --types forward_split,reverse_split,cash_dividend,merger --start 2026-08-28 --end 2026-10-01
```

### Why an options agent must check this
- A **split** adjusts strikes and contract multipliers. A position through a split is not the position you thought you had.
- A **special/large dividend** shifts put-call parity and raises early-assignment risk on short calls (the classic "assigned the day before ex-div" trap).
- A **merger** can freeze trading or convert the deliverable.
- Paper trading **does not simulate dividends** at all — so your paper P&L is silent about dividend effects that would matter live.

**Pre-trade gate:** reject any underlying with a corporate action dated inside the option's remaining life. Cheap, one call, and a very credible line in the write-up.

## 4. Crypto data (available, probably not needed)

| Endpoint | Path |
|---|---|
| Bars | `/v1beta3/crypto/{loc}/bars` |
| Quotes / trades / snapshots | `/v1beta3/crypto/{loc}/...` |
| **Latest orderbook** | `/v1beta3/crypto/{loc}/latest/orderbooks` |
| Stream | `wss://stream.data.alpaca.markets/v1beta3/crypto/{loc}` |

Crypto historical data is the **only market data that doesn't require authentication**.

```bash
alpaca data crypto bars --symbol BTC/USD --start 2026-08-01 --timeframe 1Hour
alpaca data crypto-orderbook --symbol BTC/USD
```

Crypto is **24/7** — which is tempting because the market is closed for most of your 7 days. But:
- ⚠️ **There are no options on crypto at Alpaca.** The hackathon requires options. Crypto trading cannot satisfy the options requirement.
- Legitimate use: a **weekend-active** component so your agent isn't idle Sat/Sun, or a crypto-vol input to your equity regime model. Frame it as a secondary module, never as the core.
- Note: crypto bars can show **0 volume/trade count** — Alpaca fills prices from quote midpoints when no trade occurred in the bar.

## 5. Other data endpoints

| Endpoint | Path | Ref |
|---|---|---|
| Forex latest rates | `/v1beta1/forex/latest/rates` | `latestrates-1` |
| Forex historical rates | `/v1beta1/forex/rates` | `rates-1` |
| Logos | `/v1beta1/logos/{symbol}` | `logos-5` |
| Fixed income latest quotes | `/v1beta1/fixedincome/latest/quotes` | `fixedincomelatestquotes` |
| Fixed income latest prices | `/v1beta1/fixedincome/latest/prices` | `fixedincomelatestprices` |

**Treasuries as a macro input:** `GET /v2/us_treasuries` (Trading API, `ustreasuries-1`) plus fixed-income quotes give you a yield-curve read without FRED. Alpaca's reference article uses FRED for exactly this — doing it with Alpaca's own endpoints instead is a nice "we used more of your platform" point.
