# EXECUTIVE BRIEF — Alpaca AI Trading Agents Hackathon
### Everything that matters, on one page. Read this first.

> Compiled 2026-08-27. Hackathon starts **tomorrow**.
> Sources: `Alpaca_Hackathon_Info.pdf`, lablab.ai event page, docs.alpaca.markets, alpacahq GitHub.
> Full source list: [`09_raw_sources/SOURCES.md`](09_raw_sources/SOURCES.md)

---

## 1. The hard facts

| Item | Value |
|---|---|
| Event | Alpaca AI Trading Agents Hackathon (lablab.ai × Alpaca) |
| Tagline | "Code the next generation of algorithmic trading" |
| Challenge name | **Options Alpha Agents** |
| Format | 100% online |
| Kick-off | **Fri 28 Aug 2026, 15:00 UTC** (18:00 GMT+3 / 11:00 ET) |
| Submission deadline | **Fri 4 Sep 2026, 15:00 UTC** (18:00 GMT+3 / 11:00 ET) |
| Total build time | **7 days / 168 hours** |
| Prize pool | **$6,000** — 1st $2,500 · 2nd $1,500 · 3rd $1,000 |
| Bonus | 2 teams × $500 + 1-month Algo Trader Plus per member (social engagement) |
| Team size | 1–6 people |
| Sponsor / payer | AlpacaDB, Inc. |

## 2. The three non-negotiable requirements

Miss any one of these and you cannot win:

1. **Autonomous AI trading agent** built on Alpaca's **Trading API** — it must make trading decisions on its own.
2. **Must use Alpaca's MCP server OR Alpaca CLI** (either one satisfies it; using both is stronger).
3. **The strategy must incorporate options trading.** Not stocks-only. Options are mandatory.

## 3. The submission-killer rules

| Rule | Detail |
|---|---|
| 🔴 **Brand-new paper account** | Final submission MUST use a paper account created *for this hackathon*. Reused/old accounts = **not judged**. |
| 🔴 **Exactly $100,000 starting balance** | The default for a new Alpaca paper account. Do not change it. |
| 🔴 **Account ID in submission** | Judges read your P&L directly from the account ID. Omit it → no P&L score. |
| 🔴 **Public GitHub repo** | Private repo = judges can't review = lower score. |
| 🔴 **One-page write-up** | Must cover: AI logic + risk gates + how you used Alpaca infrastructure. |
| 🔴 **Live demo URL** | Must be reachable. lablab expects Streamlit / Replit / Vercel. |
| ⚠️ **Register in BOTH places** | lablab.ai platform **and** the lablab Discord. Both required. |
| ⚠️ **18+ only**, MIT-compliant original code, no Alpaca employees/family. |

## 4. How you are scored (4 criteria, Alpaca-specific)

| Criterion | What judges actually look at | Your lever |
|---|---|---|
| **P&L Performance** | Realized + unrealized P&L on your paper account over ~5.2 trading days | Only criterion that is a *number*. Risk-managed positive P&L. See `08_strategy_playbook/03`. |
| **Technology Implementation** | Depth of Trading API + MCP + CLI use | Use **all three** + Market Data API + multi-leg options. |
| **Creativity & Originality** | Novel strategy + novel agent behaviour | Not "GPT wrapper picks a stock". See `08_strategy_playbook/02`. |
| **Presentation & Execution** | Video, slides, clarity of reasoning | 4-min video, demo in the middle. See `08_strategy_playbook/05`. |

lablab's *generic* rubric additionally scores **Business Value** on a 1–5 scale — include TAM/SAM + a revenue model even though the Alpaca-specific list omits it. (`01_hackathon/02_judging_and_scoring.md`)

## 5. The five constraints that will bite you (discovered in the docs)

These are the technical facts that separate a working agent from a broken one:

1. **Free options data = "indicative" feed, not OPRA.** Quotes are *derived*, trades are **delayed 15 minutes**, and historical options data excludes **the latest 15 minutes**. Your agent must not assume real-time OPRA prices. → `04_market_data/02_option_data.md`
2. **Multi-leg (`mleg`) orders: max 4 legs, and every leg must be covered *within the same order*.** Two short calls in one mleg = rejected. No equity leg in an mleg. → `05_options/02_multileg_mleg_orders.md`
3. **`mleg` `limit_price` sign convention: positive = debit, negative = credit.** Get this backwards on an iron condor and the order is nonsense. → `05_options/02`
4. **0DTE options have NO Greeks.** Black-Scholes divides by days-to-expiry. Also no Greeks when bid or ask is 0. → `05_options/03_greeks_and_iv.md`
5. **Options TIF = `day` (spec) / `day`+`gtc` (product docs) — sources conflict.** Options have **no extended hours**, ever. `stop`/`stop_limit` are single-leg only. → `03_trading_api/01_orders_api.md`

## 6. Competition window reality check

Kick-off Fri 28 Aug 11:00 ET → deadline Fri 4 Sep 11:00 ET.

| Date | Day | Trading time available |
|---|---|---|
| Aug 28 | Fri | 11:00 ET → 16:00 ET (partial) |
| Aug 29–30 | Sat/Sun | closed |
| Aug 31 | Mon | full |
| Sep 1 | Tue | full |
| Sep 2 | Wed | full |
| Sep 3 | Thu | full |
| Sep 4 | Fri | 09:30 ET → 11:00 ET (partial) |

**≈ 5.2 trading days.** No US market holiday falls inside the window (Labor Day 2026 = Sep 7, after the deadline).

Strategic consequence: **you have almost no time for a slow-mean-reversion strategy to work.** Short-dated options and a high trade count are how you generate a P&L signal in 5 days — but they are also how you blow up. The playbook resolves this tension. → `08_strategy_playbook/01_competition_window_analysis.md`

## 7. Where the free money is

The **social engagement bonus** is the single highest expected-value item in the whole event:
- 2 teams × ($500 + Algo Trader Plus for every member)
- Judged on "quality and reach of your public posts"
- Up to **5 post links** submitted
- Almost nobody does this properly. It costs ~2 hours total.
→ `08_strategy_playbook/06_social_engagement_plan.md`

## 8. Your first 90 minutes (do this before kick-off)

1. Register on lablab.ai → complete profile → **click Enroll** on the event page.
2. Join Discord: https://discord.gg/lablabai
3. Create an Alpaca account → open a **development** paper account (not the competition one yet).
4. Install the stack:
   ```bash
   brew install alpacahq/tap/cli          # Alpaca CLI
   alpaca profile login                    # OAuth, paper
   alpaca doctor                           # verify
   claude mcp add alpaca --scope user --transport stdio uvx alpaca-mcp-server \
     --env ALPACA_API_KEY=... --env ALPACA_SECRET_KEY=...
   npx skills add alpacahq/alpaca-skills   # Alpaca Skills
   pip install alpaca-py
   ```
5. Smoke-test options access:
   ```bash
   alpaca clock
   alpaca option contracts --underlying-symbol SPY
   alpaca data option chain --underlying-symbol SPY
   ```
6. Read `08_strategy_playbook/04_7_day_build_plan.md` and pin the hour-by-hour plan.

## 9. Document map

| Folder | What's in it |
|---|---|
| `01_hackathon/` | Every rule, date, prize term, rubric, submission requirement |
| `02_alpaca_platform/` | Accounts, auth, base URLs, paper environment, data plans |
| `03_trading_api/` | Orders, positions, assets, clock, rate limits, error codes |
| `04_market_data/` | Stock/option/news data, feeds, websockets |
| `05_options/` | **The core.** Levels, symbology, mleg, Greeks, margin, strategy cookbook |
| `06_sdks_tools/` | Python SDK, JS SDK, Alpaca Skills |
| `07_mcp_cli/` | MCP server (all tools), CLI (all commands), which to use when |
| `08_strategy_playbook/` | Window analysis, architecture, risk gates, 7-day plan, templates, social plan |
| `09_raw_sources/` | 130 raw source files + full URL provenance |
