# 03 — Submission Requirements & Checklist (exact formats)

Sources:
- Event page "What to submit" section
- https://lablab.ai/delivering-your-hackathon-solution
- https://lablab.ai/hackathon-rules

---

## 1. What the event page requires (verbatim)

**📋 Basic information**
- Project title
- Short description
- Long description
- Technology & category tags

**📸 Cover image and presentation**
- Cover image
- Video presentation
- Slide presentation

**💻 App hosting and repository**
- Public GitHub repository
- Demo application platform
- Application URL
- **Alpaca paper trading account ID**

> **Alpaca account ID — required for judging.** Your final submission must include the Alpaca paper trading account ID used for the hackathon. This allows the judging team to identify your trading activity and evaluate your P&L performance.

**Plus (from Additional requirements):**
- One-page write-up covering your AI logic, risk gates, and Alpaca infrastructure implementation

**Plus (optional, bonus prize):**
- Up to 5 social media post links

---

## 2. Exact format specs (from lablab's submission guide + Rule Book)

| Asset | Spec | Notes |
|---|---|---|
| **Project title** | Clear, descriptive | Rule Book: "Must be clear and descriptive." |
| **Short description** | **≤ 255 characters** | Concise summary capturing the essence |
| **Long description** | **≥ 100 words** | Problem, solution, target audience, unique features/benefits |
| **Technology & category tags** | Select accurately | "Proper categorization is essential" |
| **Cover image** | **PNG or JPG**, **16:9** aspect ratio | "Visually appealing image that stands out" |
| **Video presentation** | **MP4**, **max 5 minutes** | Rubric penalises **< 3 min**. Target **3:30–4:30**. Structure: intro → walk the PDF → showcase functionality |
| **Slide presentation** | **PDF** | 8–10 pages. 2–3 sentences per slide max |
| **GitHub repository** | **Public** | Private repo → judges can't review → lower score |
| **Demo platform** | **Streamlit, Replit, or Vercel** | These three are named explicitly |
| **Application URL** | Live, interactive | "Required for interactive evaluation" |
| **Alpaca account ID** | Paper account ID string | **Judging gate for P&L** |

> ⚠️ The lablab submission guide's GitHub bullet mentions an "IBM Bob report" — that is boilerplate carried over from a different sponsored event and does not apply here. The Alpaca-specific requirement is the **paper trading account ID**.

---

## 3. lablab's "Pro tips for a stellar submission" (verbatim list)

1. Highlight the Problem & Solution — start with the core issue your product resolves
2. Detail Your Product — how it functions and the technologies involved
3. Showcase User Interaction — a screen recording demonstrating user interaction is impactful
4. Discuss Market Scope — include TAM and SAM
5. Revenue Streams — highlight potential revenue sources
6. Analyze Competitors — strengths and weaknesses, emphasize your USP
7. Talk About Future Prospects — scalability and impact potentials
8. Brevity is Key — limit slides to 2–3 sentences each

---

## 4. Where to submit

Submit via the **"Submit" button on your team's dashboard** on the lablab.ai platform. (Getting Started guide, "Project Submission".)

**Manual submission fallback:** available for **6 hours post-hackathon** for those with valid reasons **and prior approval from organizers or mentors**. Do not rely on this — get approval in advance if you anticipate an issue.

---

## 5. The one-page write-up — required structure

The event page names the three things it must cover. Give each an explicit heading so a judge scanning it can tick all three:

```markdown
# <Project Name> — Technical Write-up

## 1. AI Logic
- Agent topology (what agents exist, what each one sees, what it decides)
- Model(s) used and why
- Signal generation: inputs → features → decision
- What is LLM-driven vs what is deterministic code, and why the split is where it is
- Structured decision contract (the schema every proposal must satisfy)

## 2. Risk Gates
- Position sizing rule + hard cap
- Max concurrent positions / max options buying power deployed
- Per-trade stop and profit targets; time stops
- Portfolio-level drawdown halts (daily / total)
- Concentration limits (per underlying, per expiry, per direction)
- Pre-trade validation (market open, contract tradable, Greeks sane, spread width)
- Kill switch and how it is triggered
- Which of these run as deterministic, unit-tested code with no model in the loop

## 3. Alpaca Infrastructure Implementation
- Trading API endpoints used (list them)
- Market Data API endpoints used (list them)
- Multi-leg (`mleg`) order construction, incl. debit/credit sign handling
- MCP server: how it's wired, which toolsets enabled
- Alpaca CLI: which commands drive the unattended loop, idempotency approach
- Alpaca Skills used
- Rate limit + retry + reconciliation strategy
- Paper account: fresh account, $100,000, account ID <ID>

## 4. Results
- Equity curve, P&L, win rate, avg win/loss, max drawdown, trade count
- Source: GET /v2/account/portfolio_history

## 5. Disclosure
(paper trading is simulated; not investment advice; options risk)
```

---

## 6. Final pre-submit checklist

**Account**
- [ ] Brand-new paper account created specifically for the hackathon
- [ ] Starting balance is exactly $100,000 (the default — verify via `GET /v2/account`)
- [ ] Account ID recorded and pasted into the submission form
- [ ] Fresh API keys generated for this account
- [ ] The DEV account was never used to place the submitted agent's trades

**Code**
- [ ] Repo is **public**
- [ ] Commits spread across all 7 days (not one big push)
- [ ] README with setup instructions a judge can follow in 5 minutes
- [ ] `.env.example` present, **no real keys committed** (grep the history!)
- [ ] LICENSE file (MIT — the prize terms say submissions must be "MIT-compliant")
- [ ] Tests for the risk gates exist and pass

**Demo**
- [ ] Deployed to Streamlit / Vercel / Replit
- [ ] URL loads from a cold browser with no auth
- [ ] Shows: live positions, decision log, equity curve, and the agent making a decision
- [ ] Doesn't crash when the market is closed

**Media**
- [ ] Cover image, PNG/JPG, 16:9
- [ ] Video, MP4, 3:00–5:00, shows the agent placing a real options order
- [ ] Slides, PDF, includes competitive analysis + TAM/SAM + revenue model
- [ ] One-page write-up (all 3 required sections)

**Text**
- [ ] Short description ≤255 chars
- [ ] Long description ≥100 words
- [ ] Tags: AI agents, algorithmic trading, options, MCP, Alpaca, Python, LLM, fintech

**Bonus**
- [ ] 5 social post URLs, on X and LinkedIn, tagging lablab.ai and Alpaca

**Timing**
- [ ] Submitted **before** Fri 4 Sep 2026 15:00 UTC — aim to submit by 12:00 UTC
