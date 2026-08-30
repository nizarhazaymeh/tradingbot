# searching_docs — Alpaca AI Trading Agents Hackathon: complete study

> Compiled **2026-08-27** for the hackathon running **28 Aug – 4 Sep 2026**.
> **38 written documents** + **131 raw source files (3.2M)** with full provenance.

---

## 🆕 Update — Sat 29 Aug 2026

[`10_UPDATE_AUG29.md`](10_UPDATE_AUG29.md) — **lablab announced a technology partner** (Featherless AI, **$25 free credits**, promo `ALPACA26`, first-come-first-served; prize pool now **$6,300**), plus a full assessment of **`nizarhazaymeh/tradingbot`** as a possible baseline.

---

## ⏱️ Read in this order

| If you have… | Read |
|---|---|
| **5 minutes** | [`00_EXECUTIVE_BRIEF.md`](00_EXECUTIVE_BRIEF.md) — the hard facts, the 3 requirements, the 5 constraints that will bite you, your first 90 minutes |
| **30 minutes** | + [`01_hackathon/02_judging_and_scoring.md`](01_hackathon/02_judging_and_scoring.md) + [`08_strategy_playbook/01_competition_window_analysis.md`](08_strategy_playbook/01_competition_window_analysis.md) + [`08_strategy_playbook/04_7_day_build_plan.md`](08_strategy_playbook/04_7_day_build_plan.md) |
| **2 hours** | + all of `05_options/` and `08_strategy_playbook/` |
| **Before writing code** | [`05_options/02_multileg_mleg_orders.md`](05_options/02_multileg_mleg_orders.md) and [`02_alpaca_platform/04_market_data_plans_and_limits.md`](02_alpaca_platform/04_market_data_plans_and_limits.md). These two contain the constraints that dictate what is buildable. |

---

## 🚨 The five things most teams will get wrong

1. **Free options data is the "indicative" feed, not OPRA.** Quotes are derived, trades are **15 minutes delayed**, and historical option queries exclude the latest 15 minutes. → [`04_market_data/02_option_data.md`](04_market_data/02_option_data.md)
2. **`mleg` orders: max 4 legs, every short leg must be covered *inside the same order*.** No calendars, no ratio spreads, no naked shorts, no equity legs. → [`05_options/02_multileg_mleg_orders.md`](05_options/02_multileg_mleg_orders.md)
3. **`mleg` `limit_price`: positive = debit, negative = credit.** Alpaca's own iron-condor example appears to contradict this — **verify it on a dev account on Day 1.** → same file, §4
4. **0DTE options return NO Greeks** (Black-Scholes divides by days-to-expiry). Also none when bid or ask is 0, or deep OTM. **A missing Greek is a reject, never a zero.** → [`05_options/03_greeks_and_iv.md`](05_options/03_greeks_and_iv.md)
5. **`bracket`/`oco`/`oto` are equities-only — you cannot attach a stop-loss to an options order.** Your agent must manage every exit itself. → [`03_trading_api/01_orders_api.md`](03_trading_api/01_orders_api.md) §7

---

## 📂 Document map

### `00_EXECUTIVE_BRIEF.md`
One page. Facts, gates, constraints, window, first 90 minutes.

### `01_hackathon/` — every rule and requirement
| File | Contents |
|---|---|
| [`01_hackathon_facts.md`](01_hackathon/01_hackathon_facts.md) | Dates, challenge text verbatim, core requirements, account rules, the full **"Build with Alpaca" resource map with URLs**, judges & mentors, community channels |
| [`02_judging_and_scoring.md`](01_hackathon/02_judging_and_scoring.md) | Both rubrics (Alpaca's 4 criteria + lablab's 1–5 scored rubric), decoded; lablab's own "how to win" guidance; a **17-item composite scorecard** |
| [`03_submission_checklist.md`](01_hackathon/03_submission_checklist.md) | Exact formats (char limits, aspect ratios, file types, allowed demo platforms), the required write-up structure, final pre-submit checklist |
| [`04_registration_and_timeline.md`](01_hackathon/04_registration_and_timeline.md) | Step-by-step join, schedule in **UTC / GMT+3 / ET**, mentor strategy, market calendar for the window |
| [`05_prize_terms_and_payout.md`](01_hackathon/05_prize_terms_and_payout.md) | Prize breakdown, full prize terms, W-8BEN/30% withholding reality for non-US teams, the MIT-compliance requirement |
| [`06_rules_compliance_traps.md`](01_hackathon/06_rules_compliance_traps.md) | 12 hard gates, the ethical-conduct rule read in a *trading* context (which shortcuts get you disqualified), security hygiene |

### `02_alpaca_platform/` — accounts, auth, environment
| File | Contents |
|---|---|
| [`01_platform_overview.md`](02_alpaca_platform/01_platform_overview.md) | The 4 APIs, the `llms.txt` + `.md` doc superpowers, every key URL, differentiating features |
| [`02_accounts_and_auth.md`](02_alpaca_platform/02_accounts_and_auth.md) | **Base URLs** (note: market data uses the same host for paper and live), the 3 conflicting env-var conventions, the account fields your agent must read, options levels |
| [`03_paper_trading_environment.md`](02_alpaca_platform/03_paper_trading_environment.md) | 🔴 **Exact steps to create the competition account**, the paper **fill model** (partial fills, no liquidity check), what paper doesn't simulate, the NTA next-day delay |
| [`04_market_data_plans_and_limits.md`](02_alpaca_platform/04_market_data_plans_and_limits.md) | 🔴 Basic vs Algo Trader Plus, what "indicative" means, the 200 calls/min budget with a worked example, **which strategies the free tier makes impossible** |

### `03_trading_api/` — the execution surface
| File | Contents |
|---|---|
| [`01_orders_api.md`](03_trading_api/01_orders_api.md) | Complete enum matrices, options validations, **ready-to-use payloads** (single-leg, mleg, roll, close) in cURL/CLI/alpaca-py, error codes, **how to build exits without brackets**, idempotency |
| [`02_positions_and_account.md`](03_trading_api/02_positions_and_account.md) | Positions, `portfolio_history` (your equity curve), activities incl. options NTAs, exercise/expiry/assignment rules, watchlists, margin & PDT |
| [`03_assets_clock_calendar.md`](03_trading_api/03_assets_clock_calendar.md) | Clock/calendar gating, market sessions (**options are regular-hours only**), assets + `options_enabled`, option contracts (and its surprising **"next weekend" default**), corporate actions |
| [`04_rate_limits_and_resilience.md`](03_trading_api/04_rate_limits_and_resilience.md) | Header-driven throttling, single-retry-layer rule, **the ambiguous-failure reconciliation protocol**, startup reconciliation, state durability, 12 failure guards, observability |

### `04_market_data/` — the signal surface
| File | Contents |
|---|---|
| [`01_stock_data.md`](04_market_data/01_stock_data.md) | Endpoints, the snapshot endpoint (5 views per call), feeds, **why IEX distorts volume signals**, screeners |
| [`02_option_data.md`](04_market_data/02_option_data.md) | 🔴 **The option chain endpoint** (whole chain + Greeks + IV in one call), Indicative vs OPRA, data availability from Feb 2024, **OCC symbology with a correct builder**, free-tier cheat sheet |
| [`03_news_screeners_corporate_actions.md`](04_market_data/03_news_screeners_corporate_actions.md) | News as the clean LLM input, 2-call universe construction, why an options agent must check corporate actions, crypto (and why it can't satisfy the options requirement) |
| [`04_websocket_streaming.md`](04_market_data/04_websocket_streaming.md) | Protocol, **200-subscription budget**, the option stream is **msgpack-only**, trade-updates stream, push-vs-poll architecture, reconnect discipline |

### `05_options/` — 🔴 the core of the hackathon
| File | Contents |
|---|---|
| [`01_options_fundamentals_on_alpaca.md`](05_options/01_options_fundamentals_on_alpaca.md) | Levels 0–3, enablement, contract fetching, symbology, **buying-power math with a sizing sanity check that rules out cash-secured puts on $100k** |
| [`02_multileg_mleg_orders.md`](05_options/02_multileg_mleg_orders.md) | 🔴 **The 5 restrictions**, the debit/credit sign convention and how to verify it, a **verified payload library**, submitting from every surface, a **copy-paste pre-submit validator**, cost basis, **strategy feasibility table** |
| [`03_greeks_and_iv.md`](05_options/03_greeks_and_iv.md) | How Alpaca computes Greeks, **all the cases where they're missing**, defensive parsing code, using delta/theta/vega/gamma in strategy logic, IV rank, expected move |
| [`04_margin_bp_and_exercise_assignment.md`](05_options/04_margin_bp_and_exercise_assignment.md) | 🔴 **The Universal Spread Rule** (portfolio-level margin netting) with Alpaca's worked example, mleg cost basis, exercise rules, **the auto-exercise trap**, assignment polling |
| [`05_strategy_cookbook.md`](05_options/05_strategy_cookbook.md) | Every Alpaca-feasible strategy with payloads, **what's impossible and why**, a scored selection matrix, and **the recommended regime-gated core strategy** |

### `06_sdks_tools/`
| File | Contents |
|---|---|
| [`01_python_sdk.md`](06_sdks_tools/01_python_sdk.md) | `alpaca-py`: client classes, full working code for account/contracts/mleg/positions/chain/streams, the version-verification trick |
| [`02_js_sdk.md`](06_sdks_tools/02_js_sdk.md) | JS/TS SDK, when to choose it, mleg in JS + raw-fetch fallback, and why choosing JS doesn't cost you the MCP/CLI requirement |
| [`03_alpaca_skills.md`](06_sdks_tools/03_alpaca_skills.md) | The skills library, install commands, **what's inside the 43 KB Paper Trading skill** (an 8-phase agent architecture authored by Alpaca), its order matrix, its anti-pattern list |

### `07_mcp_cli/` — satisfying the core requirement
| File | Contents |
|---|---|
| [`01_mcp_server_full.md`](07_mcp_cli/01_mcp_server_full.md) | V1→V2 breaking changes, setup for **9 clients**, `ALPACA_TOOLSETS` as a security control, **the complete V2 tool list**, the underused **doc-lookup tools**, Alpaca's own example prompts, security notice |
| [`02_cli_full.md`](07_mcp_cli/02_cli_full.md) | "Built for agents", install, auth (incl. the **partial-env-bundle trap**), every command group, output/exit codes, idempotency, **built-in retry — don't wrap it**, and a **ready-to-run cron loop** |
| [`03_mcp_vs_cli_decision.md`](07_mcp_cli/03_mcp_vs_cli_decision.md) | Alpaca's own comparison, **the recommended split** (CLI = autonomous execution, MCP = research + oversight), where the LLM should live, evidence to commit, 30-minute setup, 5 Day-1 sanity checks |

### `08_strategy_playbook/` — how to actually win
| File | Contents |
|---|---|
| [`01_competition_window_analysis.md`](08_strategy_playbook/01_competition_window_analysis.md) | 🔴 **You have ~5.2 trading days** — the 5 consequences for strategy, expiries inside the window, **why your P&L is snapshotted mid-session on Sep 4**, realistic P&L targets, honest time budget |
| [`02_winning_architecture.md`](08_strategy_playbook/02_winning_architecture.md) | 🔴 **Alpaca's own reference architecture dissected** — including the line where it says *"the next layer is options, with a dedicated options agent in development"* — then the full 8-stage options-native architecture to build, with the proposal contract and the one-sentence pitch |
| [`03_pnl_strategy_and_risk_gates.md`](08_strategy_playbook/03_pnl_strategy_and_risk_gates.md) | 🔴 The strategy table, a working **regime classifier**, **sizing maths**, the **22-gate stack**, **circuit breakers using Alpaca's own `suspend_trade`**, exit management with the roll branch, fill-quality ladder, metrics to report, honest-reporting rules, 10 test files |
| [`04_7_day_build_plan.md`](08_strategy_playbook/04_7_day_build_plan.md) | Hour-by-hour, Day 0 → submission day, with a **cut list** for when you fall behind and the minimum viable winner |
| [`05_writeup_and_demo_templates.md`](08_strategy_playbook/05_writeup_and_demo_templates.md) | Fill-in-the-blanks: the required **one-page write-up**, a timed **video script**, the 10-slide deck, short/long descriptions, tags, cover image, README |
| [`06_social_engagement_plan.md`](08_strategy_playbook/06_social_engagement_plan.md) | The $500 + subscriptions prize, what "quality" means here, and **all 5 posts fully drafted** |
| [`07_risks_and_failure_modes.md`](08_strategy_playbook/07_risks_and_failure_modes.md) | **50 numbered failure modes** with guards, the 3 that actually decide it, a daily health-check script |

### `09_raw_sources/` — provenance
[`SOURCES.md`](09_raw_sources/SOURCES.md) — every URL, what it gave, its local file, **the capture techniques**, sources that couldn't be retrieved, and **the four documented conflicts between Alpaca's own sources**.

| Folder | Files |
|---|---|
| `alpaca_docs_md/` | 52 Alpaca guide pages as markdown |
| `alpaca_reference_md/` | 51 API reference pages with **full OpenAPI schemas** |
| `github/` | 5 READMEs + 5 SKILL.md files from alpacahq |
| `lablab/` | 9 lablab pages incl. the raw HTML that held the collapsed accordions |
| `alpaca_learn/` | 4 Alpaca Learn/Blog articles |
| `indexes/` | `llms.txt` doc indexes + the download manifests |

---

## 🔑 The one insight that positions this submission

Alpaca links a **"Multi-Agent AI Trading System"** article from the hackathon page as official guidance. That article's own closing section reads:

> "Long and short positions are already running. **The next layer is options, with a dedicated options agent in development.**"

Alpaca published a reference architecture, said the options layer didn't exist yet, and then ran a hackathon requiring options. **The gap between that article and the requirement is the brief.** Build the options agent it says is still in development, and say so in the first 20 seconds of your video.

Full analysis: [`08_strategy_playbook/02_winning_architecture.md`](08_strategy_playbook/02_winning_architecture.md)

---

## ✅ Do these today (Aug 27)

```bash
# 1. Register + enroll on lablab.ai, join https://discord.gg/lablabai
# 2. Create an Alpaca DEV paper account, generate keys
# 3. Install the whole stack
brew install alpacahq/tap/cli && alpaca profile login && alpaca doctor
pip install alpaca-py
claude mcp add alpaca --scope user --transport stdio uvx alpaca-mcp-server \
  --env ALPACA_API_KEY=$ALPACA_API_KEY --env ALPACA_SECRET_KEY=$ALPACA_SECRET_KEY
npx skills add alpacahq/alpaca-skills

# 4. Prove options access works
alpaca account get --jq '{options_approved_level, options_trading_level}'
alpaca data option chain --underlying-symbol SPY | head -40
alpaca calendar --start 2026-08-28 --end 2026-09-08

# 5. Create the public repo with an MIT LICENSE and make your first commit
```

Then read [`08_strategy_playbook/04_7_day_build_plan.md`](08_strategy_playbook/04_7_day_build_plan.md) and pin it.

---

*Nothing here is investment advice. Paper trading is a simulation; results are hypothetical and do not represent actual trading. Options involve significant risk and are not suitable for all investors — see [Characteristics and Risks of Standardized Options](https://www.theocc.com/company-information/documents-and-archives/options-disclosure-document). Alpaca disclosures: https://alpaca.markets/disclosures*
