# Options Alpha Agent — Technical Write-up

**Alpaca AI Trading Agents Hackathon** · lablab.ai × Alpaca · 28 Aug – 4 Sep 2026
**Alpaca paper trading account ID: `PA3BAT1OOEFE`**  (UUID `98f497d2-e669-422b-878c-a5642bcd7cf1`) (fresh account, $100,000 start)
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
| 6 | Risk gates — 29 deterministic checks | ❌ |
| 7 | Execution — 4-leg `mleg` order via `POST /v2/orders` | ❌ |

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

**A rule we built, measured, and switched off.** The variance risk premium is a
claim about prices, not about which side we are on, so it should govern selling
as well as buying. It did not: credit structures had a take-profit against max
gain, but a long-premium structure had only a profit multiple of the debit paid
and a DTE-1 time stop.

On 1 Sep that gap appeared live. The agent held two IWM bear put spreads at
DTE 3 whose long strikes (290, 291) had been pinned by a 290.39 spot. About 80%
of their $1,236 value was time value, and IWM implied vol was 20.8% against
11.7% realised — we were long options priced at nearly twice the volatility the
index was delivering, precisely the trade the entry logic exists to refuse, and
no exit rule would sell them.

So we wrote one. `monitor.harvest_edge()` values the remaining life of a
structure at *realised* vol with a Black-Scholes mark and compares that to what
the market will pay now; when the market overpays for time we still hold, we
sell. It fired on both positions and realised **+$406**, and correctly left the
six short-premium structures alone.

**Then we tested it properly, and it did not hold up.** One case is not
evidence, so we A/B'd the same structures through the same exit logic with the
rule on and off, over 120 historical debit structures across 12 expiry cycles
(`scripts/validate_harvest.py`, realised vol computed only from closes *before*
each step so the rule cannot see the move it is judged on):

| Window | Harvest on | Harvest off | Difference |
|---|---|---|---|
| 6 cycles | $2,634 | $1,474 | **+$1,160** |
| 12 cycles | −$150 | $126 | **−$276** |

The encouraging number was a window artifact. Six weeks happened to include the
one good cycle (24 Jul, +$1,514) and exclude the worst (12 Jun, −$1,518); by
cycle the rule was positive four times and negative four times. Threshold
sweeps did not rescue it — on an absolute floor only one setting was positive,
and it fired 3 times in 120, which is fitting a threshold to three samples. On a
relative floor, every setting from 10% to 50% of the position's mark was *worse*
than off. A trend veto, on the theory that a debit spread is bought on a
directional thesis, made it worse still: it blocked the two cases it should have
kept and let through all four it should have stopped.

**So it ships disabled** (`HARVEST_ENABLED=False`). The +$406 it realised was
correct on that position's own merits and stands; what we could not show is that
the generalisation makes money. One caveat we kept in the code: all 23 replay
firings were bull call spreads, so the structure that motivated the rule — a
bear put spread — was never exercised historically. The rule is unproven for
that case rather than disproven. Unproven is still not a reason to run it on a
live account.

We are including this because it is the most honest thing in the project: the
machinery it introduced (`bs_price`, `fair_value`) is what let us price the
deadline decision below, and the discipline that killed it is the same
discipline that found the strategy in the first place.

**Topology.** Each cycle, per underlying:

| Stage | Component | LLM? |
|---|---|---|
| 1 | Regime classification — IV vs realised vol, trend z-score, expected move | ❌ |
| 2 | Directional view — direction, magnitude, confidence, thesis | ✅ |
| 3 | Candidate enumeration — ~37 structures across deltas, widths, sides | ❌ |
| 4 | Expected-value scoring — N(d₂) probabilities under realised vol, tilted by the view | ❌ |
| 5 | Critic — structural coherence check | ✅ |
| 6 | Risk gates — 29 deterministic checks | ❌ |
| 7 | Execution — 4-leg `mleg` order via `POST /v2/orders` | ❌ |

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

**The same test, applied to exits.** The variance risk premium is a claim about
*prices*, not about which side we happen to be on — so it should govern selling
as well as buying. It did not, at first. Credit structures had a take-profit
measured against max gain, but a long-premium structure had only a profit
multiple of the debit paid and a DTE-1 time stop. Nothing covered the case that
actually appeared.

On 1 Sep the agent held two IWM bear put spreads at DTE 3 whose long strikes
(290, 291) had been pinned by a 290.39 spot. About 80% of their $1,236 value was
time value, and IWM implied vol was 20.8% against 11.7% realised. We were long
options priced at nearly twice the volatility the index was actually delivering
— precisely the trade the entry logic exists to refuse — and no exit rule would
sell them.

`monitor.harvest_edge()` closes the asymmetry. It values the remaining life of a
structure at *realised* vol via a Black-Scholes mark and compares that to what
the market will pay right now. When the market overpays for time we still hold,
we sell it — the same trade as the short side, in the other direction. It fires
only on long premium, because for a credit structure an overpriced mark is the
reason to *keep* collecting. It must clear twice the cost of getting out, since a
wide market can swallow the whole edge.

Live, that afternoon:

| Structure | Market pays | Worth at realised vol | Edge | Cost to exit |
|---|---|---|---|---|
| `bear_put:IWM` ×4 | $828 | $683 | **$145** | $32 |
| `bear_put:IWM` ×3 | $516 | $347 | **$169** | $4 |

Both filled within a minute, realising **+$406**. The six short-premium
structures in the book were correctly left alone.

One honest note on the arithmetic. Valuing the book at a flat spot suggested $994
would decay away, which overstates the case: it assumes IWM never falls.
`fair_value` credits that possibility, and the defensible edge was $306. We acted
on the smaller number.

## 2. Risk Gates

All gates are plain Python, unit-tested, with no model in the loop. First failure
rejects, and the failing gate is named in the audit log.

| Layer | Checks |
|---|---|
| **Structural** | `mleg` validity (≤4 legs, per-expiry long ≥ short coverage, ratio GCD = 1, no equity legs, `position_intent` on every leg, `day` TIF, no extended hours); debit/credit sign matches the strategy; credit cannot exceed spread width |
| **Market state** | market open; no new positions after 15:30 ET; 3 ≤ DTE ≤ 10 (0-2 DTE rejected: no Greeks at 0DTE, destructive gamma below 3) |
| **Contract quality** | tradable; open interest ≥ 500; bid/ask spread within a % *or* absolute-cents limit; Greeks present; 0.01 < IV < 5.0; order qty ≤ 5% of open interest |
| **Expectancy** | EV ≥ 2% of capital at risk, under realised-vol probabilities |
| **Portfolio** | 0.55% max loss per trade · 4.0% total heat · 1.2% per underlying · 2.5% per expiry · ≤10 concurrent · cost ≤ 50% of options buying power · portfolio delta within ±3.0 per $100k · no duplicate structures |
| **Circuit breakers** | daily −2%, total −6% → cancel all orders, flatten the book, and set `suspend_trade` on the Alpaca account |
| **Competition deadline** | `NO_NEW_AFTER` 2 Sep 15:30 ET stops opening; `FLATTEN_AT` 3 Sep 15:30 ET closes everything unconditionally, at higher priority than any other exit |

**Exits are our responsibility.** Alpaca does not support bracket/OCO orders on
options, so the monitor loop *is* the stop-loss: +35% of max gain (credit) or
+100% of the debit paid; −150% of credit or −60% of debit; short-leg
|delta| > 0.40 → roll; time stop at DTE 1; and on expiry day a forced close —
limit from 14:00 ET, market from 15:30 ET. That last rule is not optional: Alpaca auto-exercises ITM
options, which would convert a $400 spread into six-figure equity exposure.

**Deadline policy.** The competition is judged at a fixed moment, which is not a
natural exit for any position. From 2 Sep the only expiries inside our 3–10 DTE
window are 8 Sep and later — all of which would still be open when the account is
marked, making the reported figure depend on where the market went after we
stopped controlling it. Two cutoffs prevent that: we stop opening on 2 Sep at
15:30 ET, and flatten the entire book on 3 Sep at 15:30 ET. The flatten outranks
every other exit trigger, so even a healthy position closes. The reported P&L is
therefore realised and cannot drift.

**Why Thursday and not Friday.** Judging is Friday 11:00 ET and every position we
can still open expires that same day, so a Friday flatten meant closing a 0-DTE
book in the first minutes of the session — the widest-spread moment of the week —
on deadline morning. Priced against the live book at realised vol, flattening
Thursday 15:30 keeps $728 of the $827 still on the table against $823 for Friday
09:35. That $95 of carry is paid for by holding a 0-DTE book through one
overnight gap with the nearest short strikes 0.67% away: +$20 of expected value
at realised vol, −$168 at implied. Nothing in expectation, against a $1–2k tail
— and holding also makes the judged figure depend on a laptop staying awake
overnight. We buy the certainty for $95.

**The deadline gate that was not strict enough — and what it cost.** Moving the
flatten forward created a second-order problem we got wrong. Any structure opened
near the end is held for a fraction of its life, so `gate_holding_period` requires
the carry earned over the *actual* hold to beat the round-trip spread. For a
credit structure that is the right test. For a debit structure there is no carry
to measure, so it fell through to a floor: at least `MIN_HOLDING_DAYS` (1.0) of
holding.

That floor tested the wrong quantity, and the market collected on it. On 2 Sep at
14:12 and 15:29 the agent bought two IWM bear put spreads expiring 8 Sep. Both
passed: each had a ~1.05-day hold against a 1.0-day floor. But one day of holding
is most of a two-day option and **17% of a six-day one**, at the same price per
day of theta. A debit structure pays for the entire life up front, so buying six
days to use one is a guaranteed loss of the difference before direction is even
considered.

They cost $1,036 and were worth $536 by Thursday morning. That single mistake —
**−$500** — turned a +$384 realised book into −$53 of equity.

The fix is to ask the question the floor was standing in for. `option_life_days()`
measures the *contract's* remaining life, as distinct from `holding_days()`, which
measures ours; the two diverge exactly when it matters. A theta-negative structure
must now get at least `MIN_LIFE_FRACTION` (50%) of the life it is paying for.
Replayed against the two real entries:

| Opened | Hold | Option life | Used | Verdict |
|---|---|---|---|---|
| Wed 14:12 | 1.05d | 6.08d | 17% | rejected |
| Wed 15:29 | 1.00d | 6.02d | 17% | rejected |

Credit structures stay exempt and stay judged on carry: selling time and buying
it back early collects a share of the decay, so the life-fraction argument is
specific to having paid up front.

The lesson we would carry into any future version of this: a threshold expressed
in absolute units (one day, fifty dollars) silently changes meaning as the thing
it measures changes scale. Both of the two real losses in this project came from
that — this one, and the harvest rule's dollar edge floor.

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

**Alpaca CLI** — used to establish behaviour we could not get from the docs, not
to execute. `alpaca` v0.0.14 was inspected directly to confirm that `--legs`,
`--order-class`, `--position-intent` and `--dry-run` are real flags (our own
notes had claimed `--legs` did not exist), and to establish that it defaults to
`--feed opra`, which returns 403 on a free account. Both findings are recorded in
`docs/FINDINGS.md` and both changed the agent.

**To be exact about which surface does what:** every one of the 14 orders in the
results above was submitted over the REST API — `POST /v2/orders` from
`agent/client.py`, with our own `RateGovernor` reading `X-RateLimit-*` headers.
Nothing in `agent/` shells out to the CLI; there is no `subprocess` import in the
package. Earlier drafts of this write-up, the slides and the README all said the
CLI drove the unattended loop and that we relied on its built-in retry. That was
wrong on both counts and is corrected here rather than left to a judge reading
`client.py` to discover. The hackathon requires the MCP server *or* the CLI; the
MCP server is the surface genuinely wired in, with a reproducible transcript.

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

From `GET /v2/account/portfolio_history` on account **PA3BAT1OOEFE**. The book
went flat on 3 Sep, before the deadline, so this figure is realised and cannot
drift.

| Metric | Value |
|---|---|
| Starting equity | $100,000.00 |
| Final equity | **$99,798.61** |
| Total return | **−0.20%** (−$201.39) |
| Max drawdown | −0.24% |
| Closed positions | 14 |
| Win rate | 9/14 (64%) |
| Realised P&L, from fills | −$195.00 (the −$6.39 balance is OCC clearing fees) |
| Proposal → gate → filled funnel | 384 considered → 126 rejected → 14 filled |
| Positions open at the deadline | **0** |

**We finished down 0.20%, and the reason is worth stating plainly.** Nine of
fourteen trades won. Every winner was small, because a credit spread's maximum
gain is the credit. The loss came from two trades:

| Trade | P&L | Why |
|---|---|---|
| `bear_put:IWM` ×4, 8 Sep expiry | −$316 | bought 6 days of option, allowed to hold 1 |
| `bear_put:IWM` ×4, 8 Sep expiry | −$312 | same |

−$628 from two positions the agent should never have opened, against +$433 from
the other twelve. Both were admitted by the hole in `gate_holding_period`
described in §2: they cleared a 1.0-day holding floor while using 17% of the
life they paid for. The gate that now rejects them was written after they had
already lost the money.

Both were closed by the stop loss, at −60% of the debit, before the deadline
flatten needed to act. The risk framework did what it was built to do — it
bounded a bad entry. It just could not un-make it.

The drawdown figure is the one we would point at: **−0.24% peak-to-trough on a
$100k account**, across 14 option structures in five sessions, with zero
positions open when the account was marked. The strategy's own thesis was
correct where it was applied — the twelve credit structures that respected the
holding rule returned +$433 with a 75% win rate. It was applied twice to
structures that could not benefit from it, and that cost more than everything
else earned.

**What we did with that after the book went flat.** Fourteen trades cannot settle
whether a strategy works, so on 4 Sep we ran the real pipeline — the same
`classify() → propose() → replay()` the live agent runs, strikes chosen by delta,
the bid/ask charged twice on every trade — over **109 weekly expiries from Aug
2024 to Aug 2026** (`scripts/backtest_full.py`, `docs/BACKTEST.md` Part 10). The
agent as it traded this week was **+$109 gross and −$3,940 net** over 157 trades:
break-even before costs, and costs were $26 a trade. The losses had three sources,
each with a mechanism and each corroborated by an earlier independent sample: iron
condors (four legs pay twice the spread for a credit that is not twice as large),
debit verticals (the strategy sells variance premium; a debit buys it — the two
trades above were not bad luck), and short calls (index variance premium lives in
puts; the optimiser was choosing calls 69 to 1 in the no-trend regime, a model
artifact). With those three families switched off, the same two years return
**+$424 net over 49 trades, 90% win, worst trade −$86**, positive in every year.
That result is in-sample by construction and small, and Part 10 says so plainly;
the out-of-sample test is every fill from here. **The code on `main` reflects it**
— `CONDORS_ENABLED`, `DEBIT_VERTICALS_ENABLED` and `CREDIT_SIDES` default off,
off and puts-only, each pinned by a test — so the repository now describes a
narrower agent than the one that produced the figures above. The account that was
judged traded the version described in §1–§3. The same discipline that found the
strategy, and that killed the harvest rule, is what changed it.

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
