# Options Alpha Agent — Technical Write-up

**Alpaca AI Trading Agents Hackathon** · lablab.ai × Alpaca · 28 Aug – 4 Sep 2026
**Alpaca paper trading account ID: `PA3BAT1OOEFE`** (fresh account, $100,000 start)
Repo: `github.com/nizarhazaymeh/tradingbot` · Team: Mahdi Anagreh, Nizar Hazaymeh, Ali

---

## 1. AI Logic

**The question the agent asks.** Most trading agents ask "which way will the
market go?" — a question nobody answers reliably. Ours asks a narrower one with a
measurable answer: *is this specific options structure priced better than the
risk it carries?*

**What we found when we measured it.** We enumerated 60 real SPY/QQQ/IWM spreads
and computed expected value using the market's own implied volatility.
**Zero of 60 were positive-EV.** That is not a bug — it is what an efficient
market looks like. Under its own implied vol, every vanilla spread prices at fair
value minus the bid-ask you cross.

**So the edge had to come from somewhere real.** It comes from the *variance risk
premium*: implied volatility persistently exceeds subsequently realised
volatility, because option sellers are paid to bear variance risk. The agent
therefore **prices with implied volatility** (the premium it actually receives)
but **computes probabilities with realised volatility** (how the underlying
actually behaves). The gap between them *is* the edge, and it appears honestly in
the expected value. Re-scored that way, 5 of 12 structures cleared a 2%-of-risk
threshold — and QQQ, whose implied vol sat *below* its realised vol, produced
nothing at all. The agent refuses to trade it.

**Topology.** Each cycle, per underlying:

| Stage | Component | LLM? |
|---|---|---|
| 1 | Regime classification — IV vs realised vol, trend z-score, expected move | ❌ |
| 2 | Directional view — direction, magnitude, confidence, thesis | ✅ |
| 3 | Candidate enumeration — ~37 structures across deltas, widths, sides | ❌ |
| 4 | Expected-value scoring — N(d₂) probabilities under realised vol, tilted by the view | ❌ |
| 5 | Critic — structural coherence check | ✅ |
| 6 | Risk gates — 22 deterministic checks | ❌ |
| 7 | Execution — 4-leg `mleg` order via the Alpaca CLI | ❌ |

**Where the model is, and is not.** The LLM (Featherless AI, `zai-org/GLM-5.2`)
returns exactly one thing: a JSON view of `{direction, magnitude, horizon_days,
confidence, thesis}`. That confidence *tilts* the market-implied probabilities,
and the agent trades only when the tilt is large enough to overcome transaction
costs. The model never picks a strike, never sizes a position, never constructs
an order payload. Confidence below 0.55 is treated as no opinion.

This split is deliberate and is also our defence against prompt injection: the
agent reads news headlines, which are attacker-influenceable text. Because model
output is constrained to a fixed schema and consumed only as a probability tilt,
a fully compromised response cannot place a trade — the worst it achieves is a
wrong opinion that the EV test must still accept on its merits.

**Probabilities.** We use N(d₂), not delta. Delta is N(d₁); it overstates P(ITM)
for calls and understates it for puts. Using delta as a probability materially
misprices the EV.

## 2. Risk Gates

All gates are plain Python, unit-tested, with no model in the loop. First failure
rejects, and the failing gate is named in the audit log.

| Layer | Checks |
|---|---|
| **Structural** | `mleg` validity (≤4 legs, per-expiry long ≥ short coverage, ratio GCD = 1, no equity legs, `position_intent` on every leg, `day` TIF, no extended hours); debit/credit sign matches the strategy; credit cannot exceed spread width |
| **Market state** | market open; no new positions after 15:30 ET; 2 ≤ DTE ≤ 10 (0DTE rejected — Alpaca returns no Greeks for it) |
| **Contract quality** | tradable; open interest ≥ 500; bid/ask spread within a % *or* absolute-cents limit; Greeks present; 0.01 < IV < 5.0; order qty ≤ 5% of open interest |
| **Expectancy** | EV ≥ 2% of capital at risk, under realised-vol probabilities |
| **Portfolio** | 0.40% max loss per trade · 4.0% total heat · 1.2% per underlying · 2.5% per expiry · ≤10 concurrent · cost ≤ 50% of options buying power · portfolio delta within ±3.0 per $100k · no duplicate structures |
| **Circuit breakers** | daily −2%, total −6% → cancel all orders, flatten the book, and set `suspend_trade` on the Alpaca account |

**Exits are our responsibility.** Alpaca does not support bracket/OCO orders on
options, so the monitor loop *is* the stop-loss: +50% of max gain (credit) or
+75% (debit); −150% of credit or −60% of debit; short-leg |delta| > 0.40 →
roll; time stop at DTE 1; and on expiry day a forced close — limit from 14:00 ET,
market from 15:30 ET. That last rule is not optional: Alpaca auto-exercises ITM
options, which would convert a $400 spread into six-figure equity exposure.

**Kill switch.** A halt sets `suspend_trade: true` via
`PATCH /v2/account/configurations` — a server-side block that survives our process
dying — and writes a `HALTED` file the loop refuses to start past.

**Verified, not assumed.** We built a replay harness (`agent/replay.py`) that
walks real historical option prices through the live exit logic. Across 85 trades
over 6 weekly expiry cycles, take-profit, time stop, expiry force-close,
mark-to-market and intrinsic settlement all behaved correctly, and only 1 of 85
positions ever reached expiry.

That backtest also tested whether the filters earn their place:

| Variant | Trades | Win rate | Net P&L | Profit factor |
|---|---:|---:|---:|---:|
| Naive — sell both sides, all underlyings | 85 | 69% | −$240 | 0.91 |
| + VRP filter | 57 | 74% | +$290 | 1.26 |
| + trend filter | 36 | **81%** | **+$657** | **2.52** |

The VRP filter was built from live measurement *before* the backtest existed, and
it independently flagged QQQ — the largest loser in the sample (−$530).

## 3. Alpaca Infrastructure Implementation

**Trading API** — `POST /v2/orders` with `order_class: mleg`; `GET/PATCH/DELETE
/v2/orders`; `/v2/orders:by_client_order_id`; `/v2/positions` and
`DELETE /v2/positions`; `/v2/positions/{id}/exercise`; `/v2/account`;
`/v2/account/configurations`; `/v2/account/portfolio/history`;
`/v2/account/activities`; `/v2/options/contracts`; `/v2/assets`; `/v2/clock`;
`/v2/calendar`.

**Market Data API** — the option chain endpoint (whole chain plus quotes,
trades, Greeks and IV in a single call), option snapshots, batched stock
snapshots and bars, news, and historical option bars for the replay harness.

**Multi-leg orders** — every spread and condor is submitted as one atomic `mleg`
order. We verified Alpaca's debit/credit sign convention empirically on a
separate development account before going live, because their documentation and
their own worked example disagree.

**MCP server** — `uvx alpaca-mcp-server`, scoped with
`ALPACA_TOOLSETS=account,trading,assets,options-data,stock-data,news` as a
least-privilege control. Used for research, human oversight, and for the agent to
look up its own API documentation via `search_alpaca_api_specs`. A real,
reproducible session is recorded in `docs/mcp_session_transcript.md`.

**Alpaca CLI** — drives the unattended execution loop. State snapshots via
`alpaca account get / position list / order list`; every order previewed with
`--dry-run` into the audit log, then submitted with a deterministic
`--client-order-id`. We rely on the CLI's built-in 429/5xx retry and deliberately
do not stack a second backoff layer, per Alpaca's own guidance.

**Resilience** — throttling is driven by `X-RateLimit-Remaining/Limit/Reset`
headers rather than a hard-coded ceiling. Order submission is never blind-retried:
on an ambiguous failure the agent looks the order up by `client_order_id` before
deciding. Startup reconciliation compares our intent ledger against the broker
and reports ghosts and orphans in both directions.

### Documentation gaps we found and fixed

| Finding | Impact |
|---|---|
| `mleg` `limit_price`: **negative = credit** | Alpaca's docs say this; their iron-condor example shows the opposite. Verified by submitting both. |
| Coverage rule is per-expiry **long qty ≥ short qty**, not "long further OTM" | Our first validator rejected every debit spread. A unit test caught it. |
| OPRA returns **403** on a free account | The Alpaca CLI defaults to `--feed opra`; every options call must pass `--feed indicative`. |
| Percentage-only bid/ask filters reject cheap wings | A 50% spread on a $0.04 option is 2 cents. Accepting either a % *or* an absolute limit expanded usable SPY calls from strike 785 → 815 — which is what makes iron condors constructible. |
| `/v2/stocks/bars` returns **zero** bars if `start` is omitted | Silent empty result, not an error. |
| `/v1beta1/options/bars` **rejects** a `feed` parameter | 400 Bad Request. |
| Historical windows reaching into today return **403 OPRA** | The free plan excludes the most recent 15 minutes. |

## 4. Results

*(Filled in after the competition window from `GET /v2/account/portfolio_history`,
archived daily. The account is flattened before the deadline so the reported
figure is realised and cannot drift.)*

| Metric | Value |
|---|---|
| Starting equity | $100,000.00 |
| Final equity | — |
| Total return | — |
| Max drawdown | — |
| Closed positions | — |
| Win rate | — |
| Proposal → gate → filled funnel | — |

## 5. Limitations and Disclosure

Paper trading is a simulation. It does not model market impact, information
leakage, latency slippage, order-queue position, price improvement, regulatory
fees, or dividends. Paper fills are matched against NBBO and order size is **not**
validated against available liquidity — which is precisely why we added
open-interest and spread-width gates rather than exploiting that.

Options quotes on the free plan come from Alpaca's **indicative** feed, not OPRA,
and option trades are delayed 15 minutes; entries are therefore timed off the
underlying and the edge does not depend on quote precision. Greeks are
Black-Scholes derived while Alpaca's contracts are American-style, so they are
approximations — least reliable for ITM puts and around ex-dividend dates.

The backtest covers 85 trades over 6 weeks in a mildly rising market, using daily
bars. It is not statistically significant and does not generalise across regimes.
A handful of live trading days is a smaller sample still.

This material is for informational, educational and research purposes only. It is
not investment advice, a recommendation, an offer, or a solicitation to buy or
sell any financial product. All trading involves risk, including loss of
principal. Options involve significant risk and are not suitable for all
investors; long options can expire worthless and short options can lose more than
the premium received. Read *Characteristics and Risks of Standardized Options*:
https://www.theocc.com/company-information/documents-and-archives/options-disclosure-document
Alpaca disclosures: https://alpaca.markets/disclosures
