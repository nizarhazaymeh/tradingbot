# 01 — Hackathon Facts (canonical reference)

**Primary sources**
- Official page: https://lablab.ai/ai-hackathons/alpaca-ai-trading-agents-hackathon
- Live page: https://lablab.ai/ai-hackathons/alpaca-ai-trading-agents-hackathon/live
- Local PDF: `../../Alpaca_Hackathon_Info.pdf`
- Sponsor landing: https://alpaca.markets/?utm_source=website&utm_medium=event&utm_campaign=lablab_hackathon
- Raw captures: `../09_raw_sources/lablab/hackathon_page_rendered.txt`, `hackathon_page_raw.html`

---

## 1. Identity

| Field | Value |
|---|---|
| Name | Alpaca AI Trading Agents Hackathon |
| Organizers | lablab.ai × Alpaca |
| Tagline | Code the next generation of algorithmic trading |
| Format | Online only — join from anywhere in the world |
| Dates | 28 August – 4 September 2026 (7 days) |
| Prize pool | $6,000 total |
| Team size | 1 to 6 people |
| Lead partner | Alpaca (AlpacaDB, Inc.) |
| Technology partners | "To be announced" — listed before kickoff. Partner prizes require the partner tech to be integrated. |

## 2. Positioning copy (verbatim from the event page)

> Build AI trading agents on Alpaca — autonomous agents and trading apps using Alpaca's Trading API, MCP server and CLI.

> Every participant builds on Alpaca's developer stack. Alpaca is a programmable brokerage: you plug in an API key and your app can place orders on US stocks, options, ETFs and crypto — Alpaca provides the brokerage infrastructure and APIs; you build the application.

> Projects for the hackathon are developed and tested using Alpaca's paper-trading environment.

## 3. The Challenge — "Options Alpha Agents"

Verbatim:

> Build an autonomous AI trading agent designed to generate P&L using Alpaca's trading platform. Develop a clear, testable trading strategy and demonstrate how your agent identifies opportunities, makes trading decisions, manages positions, and performs over the course of the competition. You may explore options, trading agents, portfolio income, or other approaches supported by Alpaca.

Note the five verbs the challenge statement asks you to *demonstrate*. Your demo and write-up should have a named section for each:
1. **identifies opportunities**
2. **makes trading decisions**
3. **manages positions**
4. **performs** (P&L over the competition)
5. (implicitly) has a **clear, testable strategy**

## 4. Core requirements (verbatim)

> - **Autonomous agents** — participants must build autonomous AI trading agents using Alpaca's Trading API.
> - **MCP or CLI** — projects must utilize either Alpaca's MCP server or its CLI tools.
> - **Options trading** — all strategies must incorporate options trading.

Tech chips shown on the page: `⚡ Trading API` `🔌 MCP Server` `⌨️ Alpaca CLI` `📄 Paper trading environment`

### Interpretation
- "MCP **or** CLI" — one is sufficient. Using both scores higher on Technology Implementation.
- "**all** strategies must incorporate options trading" — an equities-only agent with an options *sidecar* is weaker than an options-native agent. Options should be the primary instrument.
- "**autonomous**" — a human-in-the-loop approval gate is defensible as a *risk control* (Alpaca's own reference architecture uses one), but the agent must be able to run unattended. Show an unattended scheduled loop.

## 5. Account requirements (verbatim)

**During development — "Explore freely":**
> Sign up for Alpaca and open a paper trading account to explore the API, MCP server, and CLI, prototype your agent, and test strategies. Use any paper account you like during development.

**For judging — "Required for judging":**
> For your final submission, create a brand-new Alpaca paper trading account dedicated to this hackathon. Projects run on an existing or reused account will not be eligible for judging.

**Additional requirements:**
> - **Competition account starting balance** must be set to $100,000.
> - **One-page write-up** covering your AI logic, risk gates, and Alpaca infrastructure implementation.

### Practical consequence
Run **two accounts**:
- `DEV` paper account — thrash, break things, backtest, reset freely.
- `COMP` paper account — created fresh, $100,000 (the default), touched **only** by the final agent. Generate separate API keys for it. Note its account ID immediately.

See `../02_alpaca_platform/03_paper_trading_environment.md` for the exact account-creation steps and the caveat that **you cannot change a paper account's balance after creation** — you must create a new account instead.

## 6. Extra challenge — Social engagement (verbatim)

> Share your progress publicly on social media — **X and LinkedIn** — while you build. Share your process, your reasoning, and your setbacks. Tag both lablab.ai and Alpaca in your posts.
> You can submit up to **5 social media post links** with your final project submission.

Prize: 2 winning teams each get **$500 USD for the team** plus a **one-month Algo Trader Plus subscription for every team member**, provided individually.

Tag handles: X `@lablabai`, `@AlpacaHQ` · LinkedIn `lablab.ai`, `Alpaca`.

## 7. Partner descriptions of the four tools (verbatim from the page)

| Tool | Description |
|---|---|
| **Trading API** | "The programmable brokerage itself — the interface your app uses to place orders on US stocks, options, ETFs and crypto." |
| **MCP server** | "Lets an AI assistant — Claude, Cursor, VS Code, ChatGPT — interact with Alpaca's APIs through structured tools in the paper-trading environment." |
| **Alpaca CLI** | "The same trading functions from a terminal command, with structured JSON output. Built for long-running agent sessions, cron jobs and CI, where MCP is heavier than needed." |
| **Paper trading environment** | "Simulated funds with real market data. Free, no card required. Build and test without touching real money." |

That CLI sentence is a direct hint about how Alpaca wants you to architect the agent: **CLI for the unattended cron/CI loop, MCP for the interactive session.** Do both, and say so in the write-up.

## 8. "Build with Alpaca" — the official resource map

This is the accordion on the event page (sections 01–04), fully expanded with destination URLs:

### 01 — Start here
| Card | URL |
|---|---|
| Getting Started — *Introduction to Alpaca and your first API integration* | https://docs.alpaca.markets/us/docs/getting-started |

### 02 — Developer tools
| Card | Subtitle | URL |
|---|---|---|
| **Alpaca Skills** | Skills and resources for AI-powered development | https://github.com/alpacahq/alpaca-skills |
| **Trading API** | Programmatic trading and order execution | https://docs.alpaca.markets/us/docs/getting-started-with-trading-api |
| **Market Data API** | Real-time and historical market data | https://docs.alpaca.markets/us/docs/getting-started-with-alpaca-market-data |
| **Alpaca JS SDK** | JavaScript and TypeScript integration | https://github.com/alpacahq/alpaca-trade-api-js |
| **Alpaca Python SDK** | Python tools for trading and market data | https://github.com/alpacahq/alpaca-py |
| **Alpaca CLI** | Command-line access to Alpaca functionality | https://github.com/alpacahq/cli |

### 03 — AI & agent development
| Card | Subtitle | URL |
|---|---|---|
| **Trading MCP Server** | Connect AI assistants and agents to Alpaca | https://docs.alpaca.markets/us/docs/alpaca-mcp-server |
| **Multi-Agent AI Trading System** | Learn how to build an AI trading system with Alpaca | https://alpaca.markets/learn/building-a-multi-agent-ai-trading-system-on-alpaca |

### 04 — Documentation
| Card | Subtitle | URL |
|---|---|---|
| **Trading CLI Documentation** | CLI commands, workflows and usage | https://docs.alpaca.markets/us/docs/alpacas-cli |
| **SDKs & OpenAPI Specs** | Libraries and API specifications | https://docs.alpaca.markets/us/docs/sdks-and-tools |

> ⚠️ The "Multi-Agent AI Trading System" article is the closest thing to an official blueprint the organizers have published. Judges from Alpaca wrote/curated it. Read it and *visibly* build on its ideas while going beyond them (it explicitly says options are the *next* layer it hasn't built — that is your opening). Analysis in `../08_strategy_playbook/02_winning_architecture.md`.

## 9. Speakers, Mentors & Judges

| Name | Role | Org |
|---|---|---|
| Pawel Czech | CEO | NativelyAI / lablab.ai |
| Chiranjeev Shah | Technical Content Marketing Associate | Alpaca |
| Tony Lee | Chief Brokerage Officer | Alpaca |
| Grace Gao | Product Manager | Alpaca |
| Brandon Meyerowitz | Team Lead, Trading API | Alpaca |

Signal: the judging bench is heavy on **Alpaca Trading API product people**, not generic AI judges. They will notice whether you used the API well — correct order classes, idempotency keys, rate-limit handling, position intents. Sloppy API usage is visible to this panel in a way it wouldn't be to a generic panel.

## 10. Community channels

| Channel | URL |
|---|---|
| lablab.ai Discord | https://discord.gg/lablabai |
| lablab Discord (alt invite on page) | https://discord.gg/uP2TQVtkRj |
| lablab Twitch (kickoff livestream) | https://www.twitch.tv/lablabai |
| lablab X | https://x.com/lablabai |
| Alpaca X | https://twitter.com/AlpacaHQ |
| Alpaca Slack | https://alpaca.markets/slack |
| Alpaca Forum | https://forum.alpaca.markets/ |
| Alpaca support | support@alpaca.markets |

## 11. Disclosures (from the event page)

- Content is informational only, not investment advice.
- lablab and Alpaca are unaffiliated; each responsible for own liabilities.
- Projects are intended to use the paper-trading environment. Paper results are hypothetical.
- Securities brokerage by Alpaca Securities LLC (dba "Alpaca Clearing"), member FINRA/SIPC, subsidiary of AlpacaDB, Inc.
- Crypto by Alpaca Crypto LLC (FinCEN MSB, NMLS # 2160858) — not SIPC/FINRA member.
- Options: read *Characteristics and Risks of Standardized Options* — https://www.theocc.com/company-information/documents-and-archives/options-disclosure-document

## 12. Note on the source PDF

`Alpaca_Hackathon_Info.pdf` (compiled for Abdulla Tamimi) is accurate on all material points and lists the schedule in **GMT+3**. It states times as 6:00 PM Aug 28 → 6:00 PM Sep 4 GMT+3, which equals **15:00 UTC**, matching the live page. Its closing note that this event "has no connection to the AAA project" and would be "a separate, new project built from scratch" is consistent with the fresh-account rule.
