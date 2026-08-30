# 05 — Write-up, Video & Slide Templates (fill in the blanks)

Reminder of the formats (`../01_hackathon/03_submission_checklist.md`):
cover image PNG/JPG **16:9** · video **MP4 ≤5 min** (rubric penalises <3 min) · slides **PDF** · short desc **≤255 chars** · long desc **≥100 words**

---

## A. The required one-page write-up

The event page requires it to cover **AI logic**, **risk gates**, and **Alpaca infrastructure implementation**. Use those exact headings so a scanning judge can tick all three.

```markdown
# <PROJECT NAME> — Technical Write-up
Alpaca AI Trading Agents Hackathon · lablab.ai × Alpaca · 28 Aug – 4 Sep 2026
Alpaca paper trading account ID: **<ACCOUNT_ID>**   |   Repo: <URL>   |   Demo: <URL>

## 1. AI Logic
**Topology.** A deterministic regime classifier feeds four isolated LLM specialists
(VolHarvest, Directional, Catalyst, Skew). Each sees the same market snapshot through
a different lens and cannot see the others' output. Each returns a structured proposal
against a fixed schema, including a required `regime_alignment` field. A separate
Critic agent then checks structural validity only — the agent that generated an idea
never validates it.

**Where the model is, and is not.** The LLM produces a *view* (direction, magnitude,
horizon, confidence, thesis). It never picks strikes, never sizes a position, and never
touches the order payload. A deterministic mapper converts view → options structure, and
a deterministic Risk Guard approves or rejects. This split is deliberate: model output is
non-deterministic and unauditable; risk decisions must be neither.

**Models used:** <model> for the specialists, <model> for the critic. Prompts are
version-controlled in `prompts/`.

**Proposal contract:** `<paste the YAML schema>`

## 2. Risk Gates
All gates are plain Python, unit-tested, with no model in the loop.

| Layer | Gates |
|---|---|
| Structural | mleg validity (≤4 legs, every short covered in-order, ratio GCD=1, no equity leg, position_intent per leg), debit/credit sign convention, structure-matches-view |
| Market state | market open, no new positions after 15:30 ET, 1 ≤ DTE ≤ 10 (0DTE rejected — Alpaca returns no Greeks), no corporate action inside the option's life |
| Contract quality | tradable, open_interest ≥ 500, (ask−bid)/mid ≤ 15%, Greeks present, 0.01 < IV < 5.0, qty ≤ 5% of open interest |
| Portfolio | 0.40% max loss per trade, 4.0% portfolio heat, 1.2% per underlying, 2.5% per expiry, ≤10 concurrent, cost basis ≤ 50% of options_buying_power, net-delta band |
| Circuit breakers | daily −2%, total −6% → cancel all orders, flatten, and `PATCH /v2/account/configurations {"suspend_trade": true}` |
| Exit (no brackets on options) | +50% of max gain (credit) / +75% (debit); −150% of credit / −60% of debit; short-leg |delta| > 0.40 → atomic 4-leg roll; time stop at DTE 1; hard close on expiry day at 14:00 ET, market at 15:30 ET |

Funnel over the competition: **<N> proposals → <N> critic-passed → <N> gate-passed →
<N> filled**. Gate rejection counts by name are in `logs/`. Tests: `pytest` — <N> tests, all passing.

## 3. Alpaca Infrastructure Implementation
**Trading API:** `POST /v2/orders` (incl. `order_class: mleg`, up to 4 legs),
`GET/PATCH/DELETE /v2/orders`, `/v2/orders:by_client_order_id`, `/v2/positions`,
`DELETE /v2/positions`, `/v2/positions/{id}/exercise`, `/v2/account`,
`/v2/account/configurations`, `/v2/account/portfolio/history`, `/v2/account/activities`,
`/v2/options/contracts`, `/v2/assets?attributes=options_enabled`, `/v2/clock`, `/v2/calendar`,
`/v2/watchlists`.

**Market Data API:** option chain (`/v1beta1/options/snapshots/{underlying}` — quotes,
trades and **Greeks/IV** for every strike in one call), option snapshots, stock snapshots
(batched), stock bars, news, screeners (`most-actives`, `movers`), corporate actions.

**Multi-leg orders:** all spreads and condors are submitted as single atomic `mleg` orders.
We verified Alpaca's debit/credit sign convention empirically on a separate development
account before going live (`docs/mleg_sign_convention.md`) and enforce it in a gate.

**MCP server:** `uvx alpaca-mcp-server` wired into <client>, scoped with
`ALPACA_TOOLSETS=account,trading,assets,options-data,stock-data,news,corporate-actions`
as a least-privilege control. Used for research, human oversight, and — notably — the
agent's own runtime API-documentation lookups via `search_alpaca_api_specs` and
`get_alpaca_endpoint_docs`, letting it self-correct on unfamiliar API errors.
Transcript: `docs/mcp_session_transcript.md`.

**Alpaca CLI:** drives the unattended execution loop (`scripts/agent_cycle.sh`, cron every
5 minutes with `flock`). State snapshots via `alpaca account get / position list /
order list / account activity list`; every order previewed with `--dry-run` into the audit
log, then submitted with a deterministic `--client-order-id` for idempotency; multi-leg
payloads via `alpaca api POST /v2/orders`. Equity curve archived nightly with
`alpaca account portfolio`. We rely on the CLI's built-in 429/5xx retry and deliberately
do not stack a second backoff layer on top of it.

**Alpaca Skills:** `alpaca-trading-paper-trading`, `-cli`, `-mcp`, and
`alpaca-trading-backtest` installed; we adopted the skills' 8-phase workflow, its
anti-pattern list, and its `day`-TIF-by-default policy for options.

**Resilience:** rate limiting driven from `X-RateLimit-Remaining/Limit/Reset` headers rather
than a hard-coded ceiling; startup reconciliation of orphan positions, orphan orders and
missing exit intents; NTAs polled from `/v2/account/activities` because options
assignments are not delivered over websocket.

## 4. Results (paper trading, <N> trading days)
| Metric | Value |
|---|---|
| Starting equity | $100,000.00 |
| Final equity | $<X> |
| Total return | <X>% |
| Realized P&L | $<X> |
| Max drawdown | <X>% |
| Closed positions | <N> |
| Win rate | <X>% |
| Avg win / avg loss | $<X> / $<X> |
| Expectancy per trade | $<X> |
| Fill rate | <X>% (avg <N> re-prices) |

Source: `GET /v2/account/portfolio_history`, archived daily in `docs/`. Account was
flattened before the deadline so the reported figure is realized and cannot drift.

## 5. Limitations & Disclosure
Paper trading is a simulation and does not model market impact, information leakage,
latency slippage, order-queue position, price improvement, regulatory fees, or dividends.
Paper fills are matched against NBBO and order size is not validated against available
liquidity — which is why we added explicit open-interest and spread-width gates. Options
quotes on the free Basic plan come from Alpaca's **indicative** feed, not real OPRA, and
option trades are delayed 15 minutes; our entries are therefore timed off the underlying and
our edge does not depend on quote precision. Greeks are Black-Scholes-derived and Alpaca's
contracts are American-style, so Greeks are approximations. <N> trading days is not a
statistically significant sample.

This material is for informational, educational, and research purposes only. It is not
investment advice, a recommendation, an offer, or a solicitation to buy or sell securities,
options, cryptocurrencies, or any other financial product. All investing and trading involve
risk, including possible loss of principal. Options involve significant risk and are not
suitable for all investors; long options can expire worthless and short options can lose more
than the premium received. Read *Characteristics and Risks of Standardized Options*:
https://www.theocc.com/company-information/documents-and-archives/options-disclosure-document
Alpaca disclosures: https://alpaca.markets/disclosures
```

---

## B. Video script (target 3:45)

lablab's rubric: **<3 min scores a 2.** 5 min is the cap. **3:30–4:30 is the target.**
Their prescribed structure is problem → demo → business → team/roadmap; here the P&L block replaces part of the business block because it's a scored criterion.

| Time | Content | On screen |
|---|---|---|
| **0:00–0:20** | **The hook.** "Alpaca published a multi-agent trading architecture and said the options layer was still in development. We built it." | Architecture diagram |
| 0:20–0:45 | **The problem.** An LLM with a broad prompt dilutes signals and can't be audited. Options add structural constraints a generic agent will get wrong — 4-leg caps, coverage rules, sign conventions, missing Greeks on 0DTE. | 3 bullets |
| **0:45–2:30** | **🔴 LIVE DEMO — the agent working.** ① cron tick, regime classified, IV rank printed ② four specialists propose, critic rejects one ③ risk gates run, one gate fires and rejects ④ **a 4-leg iron condor submitted as one `mleg` order** ⑤ dashboard: positions with live Greeks, decision log, funnel ⑥ short-strike threatened → **atomic 4-leg roll** ⑦ MCP: ask the account a question in natural language | Screen recording. No slides here. |
| 2:30–2:50 | **Risk gates.** `pytest` all green. The rejected-proposal ledger. The circuit breaker halting via `suspend_trade`. | Terminal + code |
| **2:50–3:15** | **🔴 RESULTS.** Equity curve. Return, max DD, trade count, win rate, expectancy. Account ID on screen. "The account was flattened before the deadline — this number is realized." | Equity curve chart |
| 3:15–3:35 | **Business case.** Target user, TAM/SAM, revenue model, competitive analysis, why this needs AI. | 1 slide |
| 3:35–3:45 | **Roadmap + team + disclosure.** | 1 slide |

### Recording notes
- **Record on Sep 2, not Sep 4.** You will need to re-record.
- Blur/crop anything showing API keys, the MCP config env block, or `~/.config/alpaca/profiles/`.
- Show the **account ID** on screen — it's the judging key.
- Increase terminal font size. Judges watch these on laptops.
- Record audio separately if your mic is poor; clarity beats production value ("Judges reward clarity over production value").

---

## C. Slide deck (8–10 pages, PDF, 2–3 sentences each)

| # | Slide | Must contain |
|---|---|---|
| 1 | **Title** | Project name, one-line pitch, team, **Alpaca account ID** |
| 2 | **Problem** | Why generic LLM trading agents fail; why options make it harder |
| 3 | **Solution** | The one-sentence pitch + the 8-stage architecture diagram |
| 4 | **How it decides** | Regime classifier → 4 isolated specialists → critic → gates. Show the proposal schema. |
| 5 | **🔴 Risk gates** | The gate table + circuit breakers + the proposal→execution funnel with rejection counts |
| 6 | **🔴 Alpaca stack** | Trading API + Market Data API + **4-leg mleg** + MCP (scoped toolsets) + CLI (cron/idempotency) + Skills. Name specific endpoints. |
| 7 | **🔴 Results** | Equity curve + metrics table. Be honest. Note the account was flattened. |
| 8 | **🔴 Competitive analysis** | vs. retail algo platforms / vs. copy-trading / vs. a bare MCP + chat session. Your USP. **(Rubric requires this for a 5 on Presentation.)** |
| 9 | **🔴 Business value** | Target user, TAM/SAM figure, revenue model (SaaS tiers / per-account fee / marketplace). **(Rubric scores this separately.)** |
| 10 | **Roadmap + disclosure** | Next: OPRA feed, more regimes, live-capital gating, backtest depth. Full disclosure text. |

---

## D. Text fields

### Short description (≤255 characters)
```
An autonomous options-trading agent on Alpaca: a deterministic volatility-regime
classifier routes four isolated LLM specialists into defined-risk multi-leg structures,
gated by unit-tested risk controls and executed as atomic 4-leg mleg orders via the CLI.
```
(238 chars — verify with `python -c "print(len(open('short.txt').read().strip()))"`)

### Long description (≥100 words) — skeleton
```
<PROJECT> is an autonomous AI options-trading agent built on Alpaca's Trading API,
MCP server and CLI. Alpaca's own published multi-agent trading architecture noted that
its options layer was still in development; this project builds that layer.

A deterministic classifier measures each underlying's IV rank, trend and expected move to
label a volatility regime. Four isolated LLM specialists — VolHarvest, Directional,
Catalyst and Skew — each propose a defined-risk options structure through a fixed schema,
without seeing one another's output. A separate critic agent rejects structurally invalid
proposals; the agent that produced an idea never validates it. Survivors pass through
a unit-tested Risk Guard covering multi-leg structural validity (Alpaca's 4-leg cap and
in-order coverage rules), contract liquidity, position sizing, portfolio concentration and
daily/total drawdown circuit breakers that halt trading via Alpaca's own
account-configuration endpoint.

Execution runs unattended: the Alpaca CLI drives a cron loop that previews every order with
--dry-run, submits with a deterministic client_order_id for idempotency, and places
multi-leg spreads and iron condors as single atomic mleg orders. Because Alpaca does not
support bracket orders on options, the agent manages its own exits, including atomic
four-leg rolls when a short strike is threatened. Every decision is written as one
JSON line, giving a complete, readable audit trail.

Over <N> trading days on a fresh $100,000 paper account (ID <ACCOUNT_ID>), the agent
placed <N> positions and returned <X>% with a <X>% maximum drawdown.
```

### Tags
`AI agents` · `algorithmic trading` · `options trading` · `Alpaca` · `MCP` ·
`Model Context Protocol` · `LLM` · `Python` · `fintech` · `quantitative finance` ·
`risk management` · `autonomous agents` · `multi-agent systems` · `paper trading`

---

## E. Cover image (PNG/JPG, 16:9)

Simplest high-impact composition: the architecture diagram on the left, the equity curve on the right, project name across the top, "Alpaca AI Trading Agents Hackathon 2026" small at the bottom. 1920×1080.

Free path: build it as an HTML page and screenshot at 1920×1080, or use the dashboard itself as the backdrop with a title overlay.

---

## F. README (judges open this first)

```markdown
# <PROJECT NAME>
> One-line pitch.

🏆 Alpaca AI Trading Agents Hackathon (lablab.ai × Alpaca), 28 Aug – 4 Sep 2026
📊 **Alpaca paper trading account ID: `<ACCOUNT_ID>`**  (fresh account, $100,000 start)
🔗 Live demo: <URL>  ·  📄 Write-up: [docs/WRITEUP.md](docs/WRITEUP.md)  ·  🎥 Video: <URL>

## Results
| Metric | Value |
|---|---|
| Total return | <X>% |
| Max drawdown | <X>% |
| Closed positions | <N> |
| Win rate | <X>% |

## Quickstart (5 minutes)
```bash
git clone <repo> && cd <repo>
cp .env.example .env      # add your Alpaca PAPER keys
pip install -r requirements.txt
brew install alpacahq/tap/cli
pytest -q                 # verify the risk gates
python -m agent.decide --dry-run   # one cycle, no orders placed
streamlit run dashboard/app.py
```

## Architecture
<diagram>

## How the Alpaca stack is used
- **Trading API** — …
- **Market Data API** — …
- **Multi-leg (`mleg`) orders** — …
- **MCP server** — …
- **Alpaca CLI** — …
- **Alpaca Skills** — …

## Risk gates
<table>

## Repo layout
<tree>

## Disclosure
<full disclosure text>

## License
MIT
```

**Commit the README on Day 0 and grow it daily.** lablab's guide: *"judges check your repo; an empty repo with one final push raises red flags."*
