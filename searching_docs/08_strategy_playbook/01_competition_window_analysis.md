# 01 — Competition Window Analysis

**The single most under-appreciated fact about this hackathon: you have ~5.2 trading days to generate a P&L that judges will score.** Everything about the strategy follows from that.

## 1. The window

| | UTC | ET |
|---|---|---|
| Kick-off | Fri 28 Aug 2026, 15:00 | Fri 28 Aug, **11:00** |
| Deadline | Fri 4 Sep 2026, 15:00 | Fri 4 Sep, **11:00** |

| Date | Day | Market | Usable trading time |
|---|---|---|---|
| Aug 28 | Fri | open | **11:00 → 16:00 ET** (~5h, and you'll spend most of it setting up) |
| Aug 29 | Sat | closed | — |
| Aug 30 | Sun | closed | — |
| Aug 31 | Mon | open | 09:30 → 16:00 (6.5h) — **month-end** |
| Sep 1 | Tue | open | 09:30 → 16:00 (6.5h) |
| Sep 2 | Wed | open | 09:30 → 16:00 (6.5h) |
| Sep 3 | Thu | open | 09:30 → 16:00 (6.5h) |
| Sep 4 | Fri | open | 09:30 → **11:00** (1.5h before deadline) |

**Total ≈ 33.5 market hours ≈ 5.2 trading days.**

No US market holiday inside the window — **Labor Day 2026 is Mon 7 Sep**, after the deadline.

⚠️ **Verify with the API on Day 1, don't trust this table:**
```bash
alpaca calendar --start 2026-08-28 --end 2026-09-08 > docs/competition_calendar.json
```

## 2. 🔴 Five consequences that should reshape your strategy

### C1 — Realistically you have 4 trading days of *agent* P&L, not 7
Aug 28 is kick-off + setup. If the COMP account goes live at the Aug 31 open, you get Aug 31 / Sep 1 / Sep 2 / Sep 3 in full plus 1.5h on Sep 4.

**Therefore: get the COMP account trading by the Aug 31 open.** Every hour you spend polishing the UI on Aug 30 is an hour of P&L you'll never get back. Build the trading loop *first*, the dashboard second.

### C2 — Slow strategies cannot work
A mean-reversion or trend-following idea with a 2–4 week horizon has no chance to express itself in 4 days. Anything with a holding period longer than the window is untestable.

**Therefore: holding periods of 1–3 days, and expiries inside or just past the window.**

### C3 — Theta is the dominant P&L term for anything you hold
Over 4 days:
- A long ATM weekly option with theta −$25/day bleeds **~$100/contract** even if the underlying goes nowhere.
- A credit spread with theta +$8/day earns **~$32/spread** if nothing goes wrong.

**Therefore: your book should be net POSITIVE theta.** That means credit structures (verticals, condors) as the core, with long options only as a small, fast, catalyst-driven sleeve.

### C4 — Expiries inside the window are a gift
SPY / QQQ / IWM carry **Mon / Wed / Fri** expirations. Inside the window that gives you expiries on:

| Expiry date | Day | Notes |
|---|---|---|
| Aug 28 | Fri | 0DTE at kick-off — **no Greeks** |
| Aug 31 | Mon | |
| Sep 2 | Wed | |
| Sep 4 | Fri | 0DTE at the deadline — **do not hold into it** |
| Sep 8 | Tue | (Mon Sep 7 is Labor Day) — first expiry *past* the deadline |
| Sep 11 | Fri | weekly |

That's **three or four complete short-dated cycles in 4 trading days** — enough for a theta strategy to actually produce a track record with a meaningful sample size (~15–40 closed positions), rather than one coin flip.

⚠️ Confirm the actual available expiries from the API; don't assume:
```bash
alpaca option contracts --underlying-symbol SPY \
  --expiration-date-gte 2026-08-28 --expiration-date-lte 2026-09-18 --limit 500 \
  | jq -r '.option_contracts[].expiration_date' | sort -u
```

### C5 — 🔴 Your final P&L is snapshotted while Sep 4 is still moving
Judges read your account **after** the 15:00 UTC deadline. The Sep 4 session is open from 09:30 ET (13:30 UTC) and doesn't close until 16:00 ET (20:00 UTC). So:

- If you leave an open position, the number a judge sees depends on where the market went *after* you stopped controlling it.
- Anything expiring Sep 4 will be **0DTE at the deadline**, with no Greeks and maximum gamma.
- Auto-exercise of ITM longs could convert your book into equity positions worth more than the account (see `../05_options/04_margin_bp_and_exercise_assignment.md` §6).

**Therefore, the endgame plan:**
```
Sep 3, 15:00 ET  → stop opening new positions
Sep 3, 15:30 ET  → close anything expiring Sep 4
Sep 4, 09:30 ET  → close ALL remaining positions
Sep 4, 10:00 ET  → account is flat; snapshot portfolio_history; freeze the number
Sep 4, 10:00-11:00 ET → submit
```
A **flat account with a clean, explainable realized P&L** is strictly better than an open book with an ambiguous mark. It also means your reported number cannot move between your submission and the judge's review — which is a real credibility advantage.

## 3. What a realistic P&L target looks like

Be honest with yourself about magnitude. On $100,000 over ~4 trading days with defined-risk options and disciplined sizing:

| Outcome | Return | Reads as |
|---|---|---|
| +3% to +8% | +$3k to +$8k | 🏆 Excellent, and *credible*. Clearly strategy-driven. |
| +0.5% to +3% | +$500 to +$3k | ✅ Solid. Positive, controlled, well-explained. Very competitive. |
| −1% to +0.5% | ~flat | ⚠️ Neutral. Win on the other three criteria. |
| −1% to −5% | small loss | ⚠️ Survivable **if** the equity curve is smooth and the risk gates visibly worked. |
| −10% or worse | big loss | ❌ Undermines everything. Suggests the risk layer didn't exist. |
| +30% or more | huge | ⚠️ **Suspicious to a brokerage panel.** On 4 days that's a lottery ticket, not a strategy. Judges score "how effectively the strategy performs through its trading activity" — one lucky trade doesn't. |

### 🔴 The key strategic insight
**Maximizing expected P&L and maximizing your score are not the same thing.**

P&L is 1 of 4 criteria. A +40% account from a single 0DTE gamble scores well on one criterion and *badly* on Creativity, Technology, and Presentation — because there's no strategy to present. Meanwhile a +2% account with 30 closed trades, a smooth equity curve, working risk gates, and a clear explanation scores well on **all four**.

**Optimize for a positive, controlled, explainable P&L.** Take the asymmetry: the downside of a blow-up costs you the whole submission; the upside of a huge number buys you one criterion you'd already have won with +3%.

## 4. Time budget: the honest version

168 hours wall-clock. Realistically for one person:

| Bucket | Hours | Notes |
|---|---|---|
| Setup + learning | 8 | Day 0–1. Cut this by using this study. |
| Core trading loop (data → decide → gate → execute) | 30 | **Priority 1.** Must be live by Aug 31 open. |
| Risk gates + tests | 12 | Priority 1. Non-negotiable. |
| Monitor / exit management | 10 | Priority 1. No brackets on options. |
| Dashboard / demo app | 14 | Priority 2. Streamlit is fastest. |
| Backtest + IV history | 8 | Priority 3. Good for slides. |
| MCP integration + transcript | 4 | Priority 2. |
| Video + slides + write-up | 12 | Priority 1. **Do not leave to Sep 4.** |
| Social posts (5) | 3 | Priority 2. Highest $/hour in the event. |
| Babysitting the live agent | 15 | Spread across the window. |
| Buffer / debugging | 25 | It will be consumed. |
| Sleep, life | ~27 | Yes, sleep. |

**Sequencing rule: nothing that isn't the trading loop happens before the loop is live.**

## 5. Market context to check on Day 1 (don't trade blind)

Your strategy is regime-dependent, so measure the regime before committing:
```bash
# Where is volatility? (VIX proxy via option IV, since Alpaca has no VIX quote on Basic)
alpaca data option chain --underlying-symbol SPY --jq '[.snapshots|to_entries[]|.value.impliedVolatility]|add/length'

# What's the recent realized range?
alpaca data bars --symbol SPY,QQQ,IWM --start 2026-07-01 --timeframe 1Day

# What's moving today?
alpaca data screener most-actives
alpaca data screener movers

# Any earnings/corporate actions in the window?
alpaca data corporate-actions --symbols SPY,QQQ,IWM,AAPL,NVDA,MSFT,AMZN,META,GOOGL,TSLA \
  --start 2026-08-28 --end 2026-09-18
```

**Then pick the strategy the regime supports:**
| Observed regime | Core strategy |
|---|---|
| High IV rank, no catalyst | **Iron condors** — delta-neutral, +theta |
| High IV rank, directional lean | **Credit verticals** on the favoured side |
| Low IV rank, clear trend | **Debit verticals** in the trend direction |
| High IV + a known event in the window | Stay small; condors *after* the event, not before |

⚠️ **Note the first week of September is historically a seasonally weak, sometimes volatile period for US equities, and Aug 31 is month-end (rebalancing flows).** Don't build a strategy that assumes a placid tape. Your risk gates matter more than your signal.

## 6. Milestone schedule (map to `04_7_day_build_plan.md`)

| When (ET) | Milestone |
|---|---|
| Aug 27 (today) | Register, enroll, Discord, install stack, create DEV account, read this study |
| Aug 28 11:00 | Attend kick-off. Note any partner prizes announced. |
| Aug 28 16:00 | Data layer working: chain + Greeks + snapshots pulling on DEV |
| Aug 29 EOD | First `mleg` order placed successfully on DEV. **Sign convention verified.** |
| Aug 30 EOD | Risk gates written + unit-tested. Full loop runs end-to-end on DEV. |
| **Aug 31 09:30** | 🔴 **COMP account live. Agent trading.** |
| Sep 1 EOD | Monitor/exit loop hardened. Dashboard v1 deployed. |
| Sep 2 EOD | Backtest + IV history done. MCP transcript captured. Slides drafted. |
| Sep 3 15:00 | **Stop opening.** Record the video. |
| Sep 3 15:30 | Close anything expiring Sep 4. |
| Sep 4 09:30 | **Flatten everything.** |
| Sep 4 10:00 | Final `portfolio_history`. Finish write-up. |
| Sep 4 12:00 | 🔴 **SUBMIT** (3 hours before the 15:00 UTC deadline) |
