# 02 — Winning Architecture

## Part A — Alpaca's own reference blueprint (study it, then go beyond it)

The hackathon page links **"Multi-Agent AI Trading System — Learn how to build an AI trading system with Alpaca"** under section 03. That article is the closest thing to an official answer key.

Source: https://alpaca.markets/learn/building-a-multi-agent-ai-trading-system-on-alpaca (14 May 2026, by the CPO at CUSP Wealth)
Raw: `../09_raw_sources/alpaca_learn/multiagent_tutorial.txt`

### Its architecture
```
Alpaca Data (OHLCV) + Finnhub + yfinance + FRED
        ↓
   Regime-Aware Screener (S&P 500 universe)
        ↓
5 Research Agents (parallel, isolated)
        ↓
   Critic Agent → Investment Memo validation
        ↓
   Human Gate (APPROVE / REJECT / REVISE)
        ↓
   Risk Guard (deterministic Python)
        ↓
   Alpaca Execution → Position Monitor (every 15 min)
```
Universe: S&P 500 only · Holding period 2–28 days · long/short/paired · **$100K paper on Alpaca**.

### Its core thesis — specialization over generalization
> "One LLM with a broad prompt mixes momentum logic with macro logic. Signals dilute. The solution: building five isolated agents, each optimized for one strategic lens, reading different data, **with no visibility into each other's output** before a structured proposal is submitted."

| Agent | Strategic lens | Primary data |
|---|---|---|
| Momentum | Breakouts, relative strength | Price action, volume, RSI |
| Macro | Sector rotation, factor plays | FRED, yield curve, VIX |
| StatArb | Pairs, spread dislocations | Rolling correlation, dislocation scores |
| Contrarian | Oversold bounces, crowded unwinds | Sentiment, insider activity |
| Exotic | Calendar effects, earnings binary | Earnings calendar, volume patterns |

### Its structured proposal contract (every agent must return this shape)
```yaml
ticker: TICKER
direction: long
thesis: >
  Momentum breakout above 52-week resistance on above-average volume.
  Sector tailwind from defensive rotation. Insider buying in prior 30 days.
entry_conditions: open above resistance with volume > 1.3x 20-day average
exits:
  take_profit_pct: 8
  stop_loss_pct: 4
  time_stop_days: 7
macro_alignment: WITH
confidence_score: 0.72
```
> "`macro_alignment` is a **required** field, not optional context. During March 18 to April 5, WITH strategies averaged +1.62% vs AGAINST at +0.21%."

### The Critic Agent — the idea worth stealing
> "Before any proposal reaches the human gate, a separate critic agent reads it against the `investment_memo.yaml`. The governance document covers: S&P 500 only, no ETFs, no crypto, leverage capped at 1.0x, max single position 10%, required fields, holding period constraints."
> "The critic checks **structural validity**. It does not evaluate whether the trade will work. **The agent that generated the idea does not get to validate it.**"

Funnel: **82 proposals → 26 approved (32%)**.

### Risk Guard — deterministic, no LLM
```python
# execution/risk_guard.py (simplified — Alpaca's article)
def check_position_limits(proposal, portfolio_value, current_positions):
    position_pct = proposal['position_sizing_pct']
    if position_pct > 10.0:
        return False, "Exceeds max single position (10%)"
    sector = get_sector(proposal['ticker'])
    sector_exposure = sum(
        p['sizing_pct'] for p in current_positions
        if get_sector(p['ticker']) == sector
    )
    if sector_exposure + position_pct > 30.0:
        return False, "Exceeds max sector concentration (30%)"
    return True, "OK"
```
> "Position limit: 10% max. Sector concentration: 30% max. Leverage: 1.0x. Drawdown halts at **5% daily, 10% weekly, 15% total**. Risk checks run as **deterministic code, unit-tested, with no model in the loop**."

### Its data layer
> "Every morning at 06:30 ET, one bulk OHLCV pull covers all ~500 S&P 500 tickers."
```python
from alpaca.data.historical.stock import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
client = StockHistoricalDataClient(api_key=ALPACA_KEY, secret_key=ALPACA_SECRET)
request = StockBarsRequest(symbol_or_symbols=sp500_tickers, timeframe=TimeFrame.Day,
                           start=start_date, limit=252)
bars = client.get_stock_bars(request).df
```
> "Individual requests for the 500 tickers hit rate limits before the data finishes loading. **One batch request solves this.** Price-based metrics (returns, RSI, ATR, beta, rolling correlations) are all calculated directly from Alpaca OHLCV data. **No third-party analytics layer needed.**"
> "All four sources consolidate into a single **SQLite `market_snapshot` table**. Agents query one interface and never call data sources directly."

### Position monitoring
> "Every 15 minutes, the position monitor checks Alpaca positions against stored TP/SL levels. **Pure price checks, no LLM.** If an active position is missing its bracket order, it gets rebuilt automatically."

### Its reported results (18 days, S&P down 4.2%)
| Agent | Realized P&L | Trades | Avg/trade |
|---|---|---|---|
| Macro | +$1,046 | 7 | +1.89% |
| Momentum | +$413 | 5 | +1.11% |
| Exotic | +$141 | 4 | +1.21% |
| Contrarian | −$232 | 8 | −0.35% |
| StatArb | −$69 | 1 | −0.88% |

Win rate ~48% (12/25 closed). TP:SL ratios 2:1 to 2.7:1. Net gross exposure managed down from 63.6% to 0.82% as the market fell.

### 🔴🔴 THE OPENING — its own "what's next" section
> "**Long and short positions are already running. The next layer is OPTIONS, with a dedicated options agent in development.**"

**Alpaca published a reference architecture and explicitly said the options layer doesn't exist yet — then ran a hackathon requiring options.** The gap between that article and the hackathon requirement *is the brief*. Build the options agent that article says is still in development, and say so out loud in your presentation. That is the single strongest positioning available to you.

### Its stated regrets (free lessons)
> "What I would add from day one: **a regime gate for the Contrarian agent.** In trending markets, its weight should drop automatically. Discovering that through live losses is the slower way to learn it."
> "**Data source rate limits also need active monitoring from the start.** A FRED or Finnhub surprise at 07:00 ET, when the pipeline is already mid-run, is an expensive problem to debug under time pressure."

Build the regime gate in from day one, and build rate-limit monitoring in from day one. Both are cheap; both are things the author wishes they'd had.

---

## Part B — Your architecture: "Options Alpha Agents"

An options-native adaptation, designed against the real constraints in this study.

```
┌───────────────────────────────────────────────────────────────────────────┐
│ 0. UNIVERSE (once per day, 3 API calls)                                   │
│    screener most-actives ∩ assets[options_enabled]  → candidate list      │
│    + liquidity gate (open_interest, spread%, Greeks present)              │
│    + corporate-action exclusion                                            │
│    → ~8-15 underlyings, persisted to SQLite                               │
├───────────────────────────────────────────────────────────────────────────┤
│ 1. DATA LAYER (every cycle, batched — ~9 calls/min of a 200 budget)       │
│    stock snapshots (all underlyings, ONE call)                            │
│    option chain per underlying (1 call each: quotes+Greeks+IV, all strikes)│
│    news (batched), clock, positions, orders, activities                    │
│    → single SQLite `market_snapshot` table; agents read only from here     │
├───────────────────────────────────────────────────────────────────────────┤
│ 2. REGIME CLASSIFIER (deterministic, NO LLM)                              │
│    IV rank (from cached IV history, Feb-2024+)                            │
│    realized vol vs implied vol                                             │
│    trend: price vs 20/50 SMA, ATR-normalized                              │
│    expected move = spot × IV × √(dte/365)                                 │
│    → regime ∈ {HIGH_IV_RANGE, HIGH_IV_TREND, LOW_IV_TREND, LOW_IV_RANGE,  │
│                EVENT_RISK}                                                  │
├───────────────────────────────────────────────────────────────────────────┤
│ 3. SPECIALIST AGENTS (LLM, parallel, ISOLATED — 4 lenses)                 │
│    ┌──────────────┬──────────────────────────┬───────────────────────────┐│
│    │ VolHarvest   │ IV rank, term structure  │ condors, credit verticals ││
│    │ Directional  │ trend, momentum, breakout│ debit verticals           ││
│    │ Catalyst     │ news stream, corp actions│ long options, strangles   ││
│    │ Skew         │ put/call IV asymmetry    │ one-sided credit spreads  ││
│    └──────────────┴──────────────────────────┴───────────────────────────┘│
│    Each returns a STRUCTURED PROPOSAL (schema below). No agent sees        │
│    another's output. Each states regime_alignment: WITH | AGAINST.        │
├───────────────────────────────────────────────────────────────────────────┤
│ 4. CRITIC AGENT (LLM, separate — structural validity ONLY)                │
│    reads proposal against strategy_memo.yaml                              │
│    checks: required fields, regime alignment, thesis coherence,            │
│            duplicate exposure, structure matches stated view               │
│    ❗ does NOT judge whether the trade will work                            │
│    ❗ the proposing agent never validates its own proposal                  │
├───────────────────────────────────────────────────────────────────────────┤
│ 5. RISK GUARD (deterministic Python, unit-tested, NO LLM)  ← the core     │
│    mleg structural validator (4 legs, coverage, GCD, intents, sign)       │
│    liquidity gates (OI, spread%, qty vs OI, Greeks present)               │
│    sizing (max loss per position, portfolio heat)                          │
│    concentration (per underlying, per expiry, per direction)               │
│    buying-power check against options_buying_power                         │
│    DTE bounds (≥1, ≤10) · expiry-day force-close policy                   │
│    drawdown halts (daily / total) → kill switch                           │
├───────────────────────────────────────────────────────────────────────────┤
│ 6. EXECUTION (Alpaca CLI, idempotent)                                     │
│    --dry-run preview → audit log                                          │
│    alpaca api POST /v2/orders < intent.json   (mleg)                      │
│    client_order_id on every order                                          │
│    reconcile fills; handle partial fills                                    │
├───────────────────────────────────────────────────────────────────────────┤
│ 7. POSITION MONITOR (every cycle, deterministic, NO LLM)                   │
│    ❗ options have NO brackets — this loop IS the stop-loss                 │
│    profit target / stop / delta breach / time stop / expiry force-close    │
│    ROLL logic: mleg 4-leg atomic roll when short strike threatened         │
│    rebuild missing exit intents on restart                                  │
├───────────────────────────────────────────────────────────────────────────┤
│ 8. AUDIT + REPORTING                                                      │
│    one JSON line per decision (proposal, gates, verdict, order)            │
│    daily portfolio_history archive → equity curve                          │
│    rate-limit header samples → ops chart                                  │
│    rejected-proposal ledger → proves the risk layer works                  │
└───────────────────────────────────────────────────────────────────────────┘

MCP SERVER sits beside all of this: research, human oversight, and the agent's
own runtime API-doc lookups (search_alpaca_api_specs / get_alpaca_endpoint_docs).
```

### The structured proposal contract (options version)
```yaml
agent: vol_harvest
underlying: SPY
regime: HIGH_IV_RANGE
regime_alignment: WITH            # required field, not optional context
view:
  direction: neutral              # up | down | neutral
  magnitude: small                # small | medium | large
  horizon_days: 2
thesis: >
  IV rank 0.71 vs 60-day history; realized vol 11% vs implied 19%.
  No corporate actions or scheduled catalysts before the Sep 4 expiry.
  Price has held a 638-658 range for six sessions.
structure:
  type: iron_condor
  expiry: 2026-09-04
  dte: 2
  legs:
    - {symbol: SPY260904P00635000, side: buy,  intent: buy_to_open,  ratio: 1}
    - {symbol: SPY260904P00640000, side: sell, intent: sell_to_open, ratio: 1}
    - {symbol: SPY260904C00660000, side: sell, intent: sell_to_open, ratio: 1}
    - {symbol: SPY260904C00665000, side: buy,  intent: buy_to_open,  ratio: 1}
  net_price: -1.35                # NEGATIVE = credit
  max_loss_per_unit: 365
  qty: 2
exits:
  take_profit_pct_of_max_gain: 50
  stop_loss_pct_of_credit: 150
  delta_breach_threshold: 0.40
  time_stop_dte: 1
  hard_close: "2026-09-04T09:30:00-04:00"
greeks_at_entry:
  net_delta: -0.02
  net_theta: 18.40
  net_vega: -42.10
confidence_score: 0.68
```

### Why this architecture wins on each criterion

| Criterion | What in the architecture earns it |
|---|---|
| **P&L Performance** | +theta core, defined risk everywhere, drawdown halts, flat before the deadline, 15–40 closed trades = a real track record not a coin flip |
| **Technology Implementation** | Trading API (orders/positions/account/portfolio_history/activities/contracts/watchlists/clock/calendar) + Market Data API (chain/Greeks/IV/snapshots/news/screeners/corporate-actions) + **4-leg `mleg`** + MCP (scoped toolsets + self-documenting agent) + CLI (cron loop + idempotency + dry-run + raw-API mleg) + Alpaca Skills |
| **Creativity & Originality** | Options-native multi-agent with isolated lenses; a critic that only checks structure; regime gate built in from day one (the reference article's own regret); atomic 4-leg *rolling* as a management behaviour; an agent that reads its own API docs to self-correct |
| **Presentation & Execution** | Every decision is one readable JSON line; equity curve straight from Alpaca; rejected-proposal ledger visibly proves the risk layer; a dashboard showing gates passing and failing in real time |

### The one-sentence pitch
> "Alpaca published a multi-agent trading architecture and said the options layer was still in development. We built it — an options-native agent that classifies the volatility regime, has four isolated specialists propose defined-risk structures, lets a critic reject anything structurally invalid, passes survivors through deterministic risk gates, and executes 4-leg multi-leg orders through Alpaca's CLI on an unattended loop."

That's the "understandable in 30 seconds" opening lablab's guide asks for, and it puts your work in direct conversation with Alpaca's own published work.
