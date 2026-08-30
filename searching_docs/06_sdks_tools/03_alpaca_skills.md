# 03 — Alpaca Skills (agent skills library)

- Repo: https://github.com/alpacahq/alpaca-skills (Apache 2.0)
- Launch blog: https://alpaca.markets/blog/alpaca-launches-skills-library-for-ai-agents/ (17 June 2026)
- Press: https://www.crowdfundinsider.com/2026/06/286394-alpaca-introduces-open-source-resource-to-enhance-how-ai-agents-interact-with-trading-infrastructure/
- Listed on the hackathon page as **card #1 under "02 Developer tools"**
- Raw: `../09_raw_sources/github/alpaca-skills_README.md` and `../09_raw_sources/github/skills/*_SKILL.md`

## 1. What Alpaca Skills are

> "Open agent skills for Alpaca's Trading API and Broker API. Each skill is a `SKILL.md` file with step-by-step instructions your AI coding assistant follows when you ask it to complete a task, such as running a historical backtest, onboarding Broker API accounts, moving money, placing orders, or consuming real-time events."

> "Skills provide shared instructions, guardrails, and reporting standards so agents produce more consistent results across runs."

**Why this matters for the hackathon:** it's the *first* card Alpaca put in the Developer Tools section. Installing and using these skills is the cheapest, most direct way to signal "we used Alpaca's agent tooling as intended" on the Technology Implementation criterion. It also gives you Alpaca's own opinions about guardrails — which you can lift straight into your risk-gate design and your write-up.

## 2. Prerequisites

```bash
# Alpaca CLI (skills are CLI-backed)
brew install alpacahq/tap/cli
# or
go install github.com/alpacahq/cli/cmd/alpaca@latest

# credentials
alpaca profile login              # OAuth, paper
# or
export ALPACA_API_KEY=...  ALPACA_SECRET_KEY=...
```

## 3. Install

### Recommended — Skills CLI
```bash
npx skills add alpacahq/alpaca-skills                                    # interactive
npx skills add alpacahq/alpaca-skills --list                             # preview available skills
npx skills add alpacahq/alpaca-skills --skill alpaca-trading-backtest    # one specific skill
```

### Manual
| Agent | Path |
|---|---|
| **Claude Code** | copy into `~/.claude/skills/` |
| **Cursor** | copy or symlink into `.cursor/skills/` (project) or your user skills dir |
| Other | reference the `SKILL.md` path directly in your agent prompt |

```bash
mkdir -p .cursor/skills
cp -r alpaca-skills/skills/trading-api/backtest .cursor/skills/alpaca-trading-backtest
```

## 4. Available skills

### 🔴 Trading API skills — these are the ones you want
| Name | Path | Title |
|---|---|---|
| `alpaca-trading-backtest` | `skills/trading-api/backtest/` | **Trading API Backtesting** |
| `alpaca-trading-paper-trading` | `skills/trading-api/paper-trading/` | **Paper Trading** |
| `alpaca-trading-paper-trading-cli` | `skills/trading-api/paper-trading-cli/` | **Paper Trading (CLI)** |
| `alpaca-trading-paper-trading-mcp` | `skills/trading-api/paper-trading-mcp/` | **Paper Trading (MCP Server)** |

### Broker API skills — not needed for this hackathon
`alpaca-broker-integration`, `alpaca-broker-account-onboarding`, `alpaca-broker-funding-transfers`, `alpaca-broker-journals`, `alpaca-broker-trading-orders`, `alpaca-broker-market-data`, `alpaca-broker-sse-events`, `alpaca-broker-reconciliation-idempotency`, `alpaca-broker-rate-limits-resilience`, `alpaca-broker-money-precision`

Naming convention: `alpaca-<product-scope>-<skill-name>`, scope is `trading` or `broker` (never `api`).

Plus: the CLI repo ships its own skill at `.agents/skills/alpaca-cli/SKILL.md` — "for structured installation, authentication, and usage guidance."

## 5. What's actually inside the Paper Trading skill (43 KB)

Its structure — worth mining for your own architecture:

```
0  - How your AI agent should use this skill
1  - Prerequisites
2  - Gather inputs (required / per-asset-class constraints / optional / strategy confirmation checklist)
3  - Source-of-truth references
4  - Workflow
     Phase 1: Strategy Confirmation
     Phase 2: Configuration Agreement
     Phase 3: Paper Account Verification
     Phase 4: Order Preview
     Phase 5: Order Submission
     Phase 6: Post-Submission Monitoring
     Phase 7: Portfolio Impact Assessment
     Phase 8: Deployment Guidance
5  - Execution rules (environment safety / confirmation behavior / idempotency /
     rate limiting / asset class rules / error handling)
6  - Output contract (in-chat response after submission / run folder artifacts)
7  - Validation and tests
8  - Disclosures, safety, and data handling
9  - Anti-patterns
10 - Related files
```

That 8-phase workflow is a **ready-made agent architecture**, authored by Alpaca. Adopting its phase names in your own agent (and saying so) is a direct hit on Technology Implementation.

### Configuration knobs the skill defines
| Knob | Default |
|---|---|
| `confirmation_mode` — require explicit yes before each order | `ON` |
| `max_position_pct` — max % of portfolio in a single position | None |
| `max_order_value` — hard cap on single order notional | None |
| `client_order_id` — idempotency key, ≤128 chars | auto-generated |
| `output_format` | JSON (`--csv`, `--jq`) |

### The order matrix it publishes
| Asset class | Types | TIF | Order classes |
|---|---|---|---|
| US equity | market, limit, stop, stop_limit, trailing_stop | day, gtc, opg, cls, ioc, fok | simple, bracket, oco, oto |
| **US options** | market, limit, stop, stop_limit (**stop types single-leg only**) | day, gtc | **simple, mleg** |
| Crypto | market, limit, stop_limit | gtc, ioc (stop_limit is gtc-only; ioc only for market/limit) | simple |

Plus the cross-cutting constraints it lists verbatim:
> - **Extended hours** requires `limit` type with `day` or `gtc` TIF. Every other type and TIF is rejected outright.
> - **Trailing stop** accepts only `day` and `gtc`.
> - **Notional** orders are market-type with `day` TIF only, cannot be combined with `qty`, and **cannot be replaced** — cancel and resubmit instead.
> - **Bracket, OCO, and OTO** classes require `day` or `gtc`, do not support extended hours, and are **equities-only**.
> - **Options** do not support extended hours at all. Multi-leg strategies use the `mleg` order class with **up to 4 legs**, and `stop`/`stop_limit` types are single-leg only.

### 🔴 It also flags the docs conflict honestly
> "Alpaca's own sources disagree on the options row, so treat it as guidance rather than a hard gate. The OpenAPI spec's `TimeInForce`/`OrderType` descriptions say options are `market`/`limit` with `day` only; the Options Trading page and the Placing Orders matrix both allow `gtc` and both allow `stop`/`stop_limit` on single-leg orders. The two product pages agree with each other against the spec blob, so this table follows them. Your agent still defaults to `day` as the conservative choice and lets Alpaca reject rather than pre-blocking an order that the matrix permits."

**Use exactly this policy: default to `day` + `limit`, and let Alpaca reject rather than pre-blocking.**

### Its anti-patterns list (adopt these as your own rules)
> - NEVER submit orders to a live trading environment. This skill is paper-only.
> - NEVER ask for API keys or secrets in chat.
> - NEVER print credentials, tokens, account numbers, or profile details in plain text.
> - NEVER skip the order preview — always show it, regardless of confirmation mode.
> - NEVER retry a failed order submission without first checking if the original was received (use `client_order_id`).
> - NEVER give investment advice, recommend specific securities, or imply a strategy is suitable, profitable, or low-risk.
> - NEVER assume the paper account has specific features enabled (options, crypto, margin) without checking the account endpoint.
> - NEVER hide order parameters, defaults, or execution assumptions.
> - NEVER treat paper trading results as proof or prediction of live performance.
> - NEVER auto-submit orders in a loop without user awareness.
> - NEVER assume market hours — always check the clock/calendar endpoint.
> - NEVER mix paper and live credentials in the same session.
> - NEVER place orders for asset classes you haven't confirmed you want to trade.

## 6. The Backtesting skill

`alpaca-trading-backtest` — "Trading API Backtesting… for reproducible strategy research with benchmarks and documented assumptions."

Per the launch blog: the **first release** of the library was the Backtesting Skill, "for reproducible strategy research with benchmarks and documented assumptions." Alpaca plans to expand into "trading execution, market data analysis, research automation, and agent-native features."

**Why you want this:** the challenge says "develop a clear, **testable** trading strategy." A backtest — even a short one over Feb-2024-onward option data — with documented assumptions and a benchmark, produced via Alpaca's own skill, is a strong answer to both *testable* and *Technology Implementation*. And it gives you numbers for the slides beyond the 5-day live result.

## 7. Recommended install for this hackathon

```bash
npx skills add alpacahq/alpaca-skills --skill alpaca-trading-backtest
npx skills add alpacahq/alpaca-skills --skill alpaca-trading-paper-trading
npx skills add alpacahq/alpaca-skills --skill alpaca-trading-paper-trading-cli
npx skills add alpacahq/alpaca-skills --skill alpaca-trading-paper-trading-mcp
```
Then in the repo README, state which skills you used and what each contributed. Commit the skill directory (or a note of the pinned commit) so a judge can reproduce your setup.

## 8. Disclosure requirement

The skills mandate a disclosure in every session summary/report:
> "**Important disclosure:** This material is for informational, educational, and research purposes only. It is not investment advice, a recommendation, an offer, or a solicitation to buy or sell securities, options, cryptocurrencies, or any other financial product. All investing and trading involve risk, including possible loss of principal. Paper trading is simulated and may differ from live trading in fills, market impact, liquidity, fees, latency, and other factors. Review Alpaca's disclosures at https://alpaca.markets/disclosures."

Put this in your README, your demo footer, and the last slide.
