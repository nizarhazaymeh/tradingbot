# 02 — Judging & Scoring: reverse-engineering the rubric

There are **two rubrics in play**. The event page publishes an Alpaca-specific one; lablab's Rule Book publishes a generic 1–5 scored one that its judges habitually use. Optimize for the union of both.

Sources:
- https://lablab.ai/ai-hackathons/alpaca-ai-trading-agents-hackathon (Judging criteria section)
- https://lablab.ai/hackathon-rules (Rule Book, scored rubric by Walaa Nasr)
- https://lablab.ai/guide/how-to-win-an-ai-hackathon (lablab's own strategy guide)
- https://lablab.ai/delivering-your-hackathon-solution (submission guide)

---

## A. Alpaca-specific criteria (event page, verbatim)

### 1. P&L Performance
> The trading performance of the submitted agent in the Alpaca paper trading environment. Judges will consider the project's P&L and how effectively the strategy performs through its trading activity.

**Decoded:** two sub-signals — *the number* and *the quality of the trading activity*. "How effectively the strategy performs through its trading activity" means a flat account with zero trades scores badly even if it didn't lose money, and a +40% account from one lucky 0DTE lottery ticket is *not* obviously a win to a panel of brokerage professionals. What scores is **a coherent strategy that traded, and whose P&L is explainable by the strategy**.

**How to win it:**
- Trade enough to produce a track record (target 20–60 closed positions over 5 days).
- Keep max drawdown small and *visible* — publish an equity curve from `GET /v2/account/portfolio_history`.
- Report risk-adjusted numbers, not just gross: win rate, avg win/avg loss, Sharpe-ish ratio, max DD, exposure.
- **Never** let the account end deeply negative. A modest, controlled positive P&L with a clean equity curve beats a volatile larger number.

### 2. Technology Implementation
> How effectively the project uses Alpaca's Trading API, MCP server, CLI, and other required technologies to build an autonomous trading agent.

**Decoded:** Note it lists **all three** — API, MCP, *and* CLI — even though the requirement says "MCP or CLI". The criterion rewards breadth.

**Checklist to max this out:**
- [ ] Trading API: orders, positions, account, account configurations, portfolio history, activities
- [ ] Multi-leg (`mleg`) options orders — the most advanced order class Alpaca has
- [ ] Market Data API: option chain + snapshots (Greeks/IV), stock bars, snapshots, news, screeners
- [ ] MCP server wired into an AI client, with `ALPACA_TOOLSETS` scoping shown
- [ ] Alpaca CLI driving the unattended cron loop with `--client-order-id` idempotency and `--dry-run` previews
- [ ] Alpaca Skills installed and referenced
- [ ] `GET /v2/clock` + `/v2/calendar` gating every action
- [ ] Rate-limit handling from `X-RateLimit-*` headers
- [ ] Correct `position_intent` on every leg
- [ ] Exercise / DNE handling for expiring ITM contracts

### 3. Creativity & Originality
> The originality of the concept, trading strategy, agent behavior, and overall approach to solving the challenge. Judges will value projects that demonstrate thoughtful and creative use of the technology.

**Decoded:** three separate axes — *concept*, *strategy*, *agent behaviour*. Most entrants will differentiate on concept only. Differentiate on **agent behaviour**: adversarial critics, regime gates, self-adjusting weights, an audit log the judge can read.

**Anti-patterns judges have seen 500 times:** "LLM reads news headlines and buys the stock", "sentiment score → market order", chatbot-wrapper-with-a-buy-button.

### 4. Presentation & Execution
> How clearly and effectively the project communicates its idea, demonstrates the agent in action, and presents the reasoning behind its trading strategy and results.

**Decoded:** "demonstrates the agent **in action**" — a screen recording of the agent actually deciding and placing an options order beats slides about the architecture.

### 5. Social Engagement (bonus prize only)
Quality and reach of public posts about the building process. Separate prize pool, does not affect the main placement.

---

## B. lablab's generic scored rubric (Rule Book)

Judges score 1–5 on each. Reproduced so you know what a "5" literally requires.

### 1. Presentation (PDF + video)
| Score | Requirement |
|---|---|
| 1 – Poor | No description of problem or gaps to fill. |
| 2 – Limited | Problem & solution not effectively communicated, difficult to understand. **Video < 3 min.** |
| 3 – Adequate | Communicates problem, solution, value proposition **in less than 5 min**. Missing market analysis / revenue. No future goals. |
| 4 – Strong | As above **plus** market analysis + marketing revenue + future goals & plans. |
| 5 – Excellent | Exceptional in every aspect. Flawlessly communicates problem/solution/value. Shows strengths and uniqueness through **competitive analysis**. |

➡️ **Actionable:** video must be **≥3 min and <5 min**. To score 5 you need an explicit **competitive analysis slide**.

### 2. Business value
| Score | Requirement |
|---|---|
| 1 | Little or no practical/commercial viability. |
| 2 | Uncertain market feasibility/scalability/revenue. Niche market. |
| 3 | Reasonable value, addresses market need, revenue potential, needs validation. |
| 4 | Clear market potential, large customer base, significant revenue, strong feasibility & scalability. |
| 5 | Potential to disrupt the industry or create a new market. Clear sustainable revenue generation. |

➡️ **Actionable:** the Alpaca criteria list omits Business Value, but the Rule Book judges score it. **Include a TAM/SAM + revenue model slide anyway.** Cheap insurance.

### 3. Application of technology
| Score | Requirement |
|---|---|
| 1 | No demo video, no demo link, no GitHub. |
| 2 | Demo video without full features; framework unclear; demo link broken; GitHub missing. |
| 3 | Demo video shows all features; demo link works with minor issues; GitHub partly available. |
| 4 | All features demoed; demo link well-executed and smooth; **GitHub available & well thought out**. |
| 5 | Exceptional application of AI tech across demo link, video & GitHub. Technical implementation flawless; surpasses expectations. |

### 4. Originality
| Score | Requirement |
|---|---|
| 1 | Exact copy of existing solutions. |
| 2 | Common idea, lacks differentiation. |
| 3 | Some unique idea (e.g. decreasing cost or time). |
| 4 | Unique perspective, unconventional methods, novel elements / creative combinations. |
| 5 | Transformative, completely new perspective, unprecedented. |

---

## C. lablab's own "How to Win" guide — the parts that matter here

From https://lablab.ai/guide/how-to-win-an-ai-hackathon

### Winning team composition
| Role | Responsibility |
|---|---|
| AI engineer (1–2) | API integration, prompt engineering, backend logic |
| Frontend / full-stack | Demo UI judges can actually click |
| Domain expert | Validates the problem is real and the solution fits |
| Pitch lead | Owns slide deck and video; presents to judges |

> "Solo participants can compete, but teams of 3–4 regularly outperform solos in the finals."

### Their prescribed video structure (adapt for this event)
- 0:00–0:30 — Problem statement and why it matters now
- 0:30–2:30 — Live demo of the working prototype
- 2:30–4:00 — Business case, market size, revenue model
- 4:00–5:00 — Team intro and future roadmap

*For this hackathon, replace part of the business block with the **P&L results block** — it's a scored criterion here and it's your only hard number. Recommended split in `../08_strategy_playbook/05_writeup_and_demo_templates.md`.*

### Their listed fatal mistakes
- **Pivoting after hour 12** — "almost always fatal"
- **Skipping the GitHub commits** — "judges check your repo; an empty repo with one final push raises red flags"
- **Building without deploying** — "a working local demo that can't be accessed by judges scores as if it doesn't work"
- **Over-engineering the AI layer** — "chaining 5 LLM calls when 1 would do adds latency and failure points"

➡️ **Actionable:** commit **many small commits spread across all 7 days**. Judges look at commit history as an authenticity signal. Do not squash a week of work into one push on Sep 4.

### Their problem-selection rules
1. Solvable with existing AI APIs (you're not training a model)
2. Working prototype achievable in the **first 24 hours**
3. There must be a real user
4. **The demo must be understandable in 30 seconds**

---

## D. The composite scorecard — grade yourself before submitting

| # | Item | Weight | Done? |
|---|---|---|---|
| 1 | Fresh paper account, $100k, account ID in submission | **gate** | ☐ |
| 2 | Options are the primary instrument, incl. multi-leg | **gate** | ☐ |
| 3 | MCP server used *and* CLI used | high | ☐ |
| 4 | Agent runs unattended on a schedule (cron/CI shown) | high | ☐ |
| 5 | Deterministic risk gates, unit-tested, no LLM in the loop | high | ☐ |
| 6 | Equity curve + P&L stats from portfolio_history | high | ☐ |
| 7 | Full decision audit log, human-readable | high | ☐ |
| 8 | Public GitHub, many commits across 7 days, real README | high | ☐ |
| 9 | Deployed demo URL (Streamlit/Vercel/Replit) that judges can click | high | ☐ |
| 10 | Video 3–5 min, demo in the middle, agent shown deciding + trading | high | ☐ |
| 11 | Slides PDF, 8–10 pages, incl. **competitive analysis** | med | ☐ |
| 12 | TAM/SAM + revenue model slide | med | ☐ |
| 13 | One-page write-up: AI logic / risk gates / Alpaca infra | **gate** | ☐ |
| 14 | Cover image PNG/JPG 16:9 | gate | ☐ |
| 15 | Short desc ≤255 chars, long desc ≥100 words, tags | gate | ☐ |
| 16 | 5 social posts tagging lablab.ai + Alpaca on X and LinkedIn | bonus | ☐ |
| 17 | Registered on lablab **and** Discord, Enroll clicked | **gate** | ☐ |
