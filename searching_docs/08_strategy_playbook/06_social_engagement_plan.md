# 06 — Social Engagement Plan (the highest-ROI 3 hours in the event)

## 1. The prize

| Item | Detail |
|---|---|
| Winners | **2 teams** |
| Cash | **$500 USD per winning team** |
| In-kind | **1-month Algo Trader Plus for every team member** (list price $99/mo each — the OPRA options feed) |
| Judged on | "Quality and reach of your public posts about your building process" |
| Submission | **Up to 5 social media post links** with your final project |
| Platforms | **X and LinkedIn** |
| Tags | Must tag **both lablab.ai and Alpaca** |

Verbatim from the event page:
> "Share your progress publicly on social media — **X and LinkedIn** — while you build. Share your process, your reasoning, and your setbacks. Tag both lablab.ai and Alpaca in your posts."

**Why this is the best expected value in the event:** 2 of maybe 30–60 teams win it, most entrants won't post 5 substantive updates, and it costs ~3 hours total. Compare that to the marginal effort of moving from 4th to 3rd place on the main leaderboard.

## 2. Handles to tag

| Platform | lablab.ai | Alpaca |
|---|---|---|
| **X** | `@lablabai` | `@AlpacaHQ` |
| **LinkedIn** | `lablab.ai` (company page) | `Alpaca` (company page) |

Hashtags: `#AlpacaHackathon` `#lablabai` `#AITrading` `#OptionsTrading` `#MCP` `#AIagents` `#algotrading` `#buildinpublic`

## 3. 🔴 What "quality" means here

Note the exact wording: *"Share your process, your **reasoning**, and your **setbacks**."* Alpaca is not asking for marketing. They're asking for a genuine build log. That's a strong hint about what wins:

| ✅ Wins | ❌ Loses |
|---|---|
| A specific technical finding, with a screenshot | "Excited to be participating! 🚀" |
| An honest setback and how you fixed it | Only posting when things go well |
| A real number (P&L, gate rejection count, fill rate) | Vague claims of success |
| Something that teaches other participants | Pure self-promotion |
| Clean terminal/dashboard screenshots | Blurry phone photos of a screen |
| Both platforms, adapted per platform | Copy-pasting the same text to both |

**The single best move:** post a genuine technical discovery that other participants can use. It gets engagement (reach), it demonstrates depth (quality), and Alpaca's own team notices. You have several such discoveries already available in this study.

## 4. The 5 posts — drafted

### Post #1 — Day 0 (Aug 27–28): The plan
> Starting the @AlpacaHQ × @lablabai AI Trading Agents Hackathon today.
>
> The brief: an autonomous options-trading agent on Alpaca's Trading API, using their MCP server or CLI.
>
> One thing jumped out reading Alpaca's own multi-agent architecture writeup — it ends with "the next layer is options, with a dedicated options agent in development."
>
> So that's what I'm building. 7 days.
>
> Plan 🧵
> 1/ deterministic volatility-regime classifier
> 2/ isolated LLM specialists proposing defined-risk structures
> 3/ a critic that only checks structural validity
> 4/ unit-tested risk gates, no model in the loop
> 5/ 4-leg multi-leg orders via the CLI on a cron loop
>
> #AlpacaHackathon #AITrading

📸 Attach: your architecture sketch (even hand-drawn — authenticity reads well).

---

### Post #2 — Day 1 (Aug 28): A real technical finding
> Day 1 of the @AlpacaHQ × @lablabai hackathon. First real finding, and it's one every options-agent team is going to hit:
>
> On Alpaca's free Basic data plan, **0DTE options return NO Greeks.**
>
> Why: they compute Greeks with Black-Scholes, and days-to-expiry sits in the denominator. DTE = 0 → division by zero → no delta, no theta, nothing.
>
> Same for deeply OTM strikes — the IV solver caps at 100 iterations and won't converge when vega → 0.
>
> If you're selecting strikes by delta, your universe silently goes empty on expiry days.
>
> Fix: gate DTE ≥ 1, and treat a missing Greek as a *reject*, never as a zero. A `None` delta coerced to 0.0 tells your risk system "no directional exposure" — the most dangerous possible wrong answer.
>
> 📄 docs.alpaca.markets/us/docs/market-data-faq
>
> #AlpacaHackathon #OptionsTrading

📸 Attach: terminal output showing a chain where the 0DTE column has null Greeks.

---

### Post #3 — Day 2 (Aug 29): A setback, honestly
> Day 2. Burned two hours on something worth writing down.
>
> Alpaca's multi-leg (`mleg`) option orders use a **sign convention on `limit_price`**:
> → positive = DEBIT (you pay)
> → negative = CREDIT (you receive)
>
> I had an iron condor — a credit structure — priced positive. Rejected, and for a while I couldn't see why.
>
> Two other `mleg` rules I now have in a validator:
> • max **4 legs**
> • **every short leg must be covered inside the same order** — so two short calls in one mleg is rejected, and calendar spreads aren't possible as a single mleg at all
> • `ratio_qty` values must have GCD = 1 (send 1:2, not 2:4)
>
> Wrote a `validate_mleg()` that checks all of it before anything hits the API. Should have written it first.
>
> Setbacks are part of the build. 🤷
>
> @AlpacaHQ @lablabai #AlpacaHackathon

📸 Attach: the validator code, or the rejection error next to the fix.

---

### Post #4 — Day 4 (Aug 31): First live trade
> The agent is live on a fresh $100k Alpaca paper account. First autonomous options position just went in.
>
> What happened, end to end, with no human in the loop:
> 1️⃣ cron tick → market open confirmed via /v2/clock
> 2️⃣ regime classifier: SPY IV rank 0.71, |trend_z| 0.8 → HIGH_IV_RANGE
> 3️⃣ VolHarvest specialist proposed an iron condor at ±1.25σ expected move
> 4️⃣ critic passed it; 22 risk gates ran; all passed
> 5️⃣ sized to $320 max loss (0.32% of equity)
> 6️⃣ submitted as **one atomic 4-leg `mleg` order** via `alpaca api POST /v2/orders`
>
> Elapsed: 4.2 seconds. Every step is one line in the audit log.
>
> The part I'm most pleased with isn't the trade — it's that 3 proposals were *rejected* in the same cycle, and the log says exactly which gate killed each one.
>
> @AlpacaHQ @lablabai #AlpacaHackathon #algotrading

📸 Attach: the decision log JSON + the filled order.

---

### Post #5 — Day 6 (Sep 2): Results + demo
> 5 days of autonomous options trading on @AlpacaHQ paper. Numbers, good and bad:
>
> 📈 Return: <X>%
> 📉 Max drawdown: <X>%
> 🔁 <N> closed positions · <X>% win rate
> 🚫 <N> proposals rejected by risk gates (<X>% approval rate)
> ⚡ <X>% fill rate, avg <N> re-prices
>
> What worked: positive-theta credit structures in a 5-day window. Theta is the dominant term when you don't have time to be right slowly.
>
> What didn't: <honest thing>.
>
> Built on Alpaca's Trading API + Market Data API (the option chain endpoint returns quotes AND Greeks for every strike in one call — genuinely great), MCP server for research and oversight, and the CLI for the unattended cron loop.
>
> 🎥 Demo: <link>
> 💻 Code: <link>
>
> Thanks @lablabai and @AlpacaHQ for a genuinely well-designed brief.
>
> #AlpacaHackathon #AITrading #OptionsTrading

📸 Attach: the 60-second demo clip + equity curve.

## 5. Platform adaptation

**X:** thread format. Lead with the finding, not the preamble. One idea per post. Screenshots on post 1 of the thread.

**LinkedIn:** longer prose, more context, no thread. Open with the finding as a one-line hook, then a blank line, then the detail. LinkedIn rewards a specific technical insight far more than "excited to announce". Tag the company pages, not personal profiles.

## 6. Practical rules

- **Post from a real account with a history.** A brand-new zero-follower account reads as farming and undermines "reach".
- **Space them out** — Day 0, 1, 2, 4, 6. Five posts on Sep 4 defeats the "while you build" framing.
- **Save every URL immediately** into `docs/social_posts.md`. You need them in the submission form and you will not want to hunt for them at 10:30 on Sep 4.
- **Reply to comments.** Engagement is part of "reach", and it's how Alpaca's team ends up in your replies.
- **Cross-post to the lablab Discord** — the community channel. Not a submitted link, but it builds the reach that gets your X post seen.
- **Don't buy engagement.** The Rule Book: "gaming the voting system… will lead to immediate disqualification."
- **Every post needs both tags.** A post missing the Alpaca tag or the lablab tag may not count.

## 7. Tracking file

`docs/social_posts.md`:
```markdown
| # | Date | Platform | URL | Topic | Impressions | Engagements |
|---|------|----------|-----|-------|-------------|-------------|
| 1 | Aug 27 | X        |     | The plan |  |  |
| 1 | Aug 27 | LinkedIn |     | The plan |  |  |
| 2 | Aug 28 | X        |     | 0DTE has no Greeks |  |  |
| 3 | Aug 29 | X        |     | mleg sign convention (setback) |  |  |
| 4 | Aug 31 | X        |     | First live autonomous trade |  |  |
| 5 | Sep 2  | X        |     | Results + demo |  |  |
```
Fill in the metrics before submitting — "quality and **reach**" means they may look at numbers. Submit the 5 highest-performing links.
