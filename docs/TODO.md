# What's left — Options Alpha Agent

Last updated: **Sun 30 Aug 2026, evening**
Deadline: **Fri 4 Sep 2026, 11:00 ET / 18:00 GMT+3**

| Team | Owner |
|---|---|
| Mahdi | agent, integration, submission |
| Nizar | repo, review |
| Ali | demo website → see [`DEMO_SPEC_FOR_ALI.md`](DEMO_SPEC_FOR_ALI.md) |

---

## 🔴 BLOCKERS — submission is rejected or unscored without these

| # | Item | Owner | Status |
|---|---|---|---|
| B1 | **Make the repo PUBLIC** — Settings → General → bottom → Change visibility. Judges cannot see a private repo; lablab says it "may lower your overall score" | **Nizar** | ☐ |
| B2 | **Live demo URL** — must load for a judge with no login | **Ali** | ☐ |
| B3 | **Video**, MP4, 3:00–5:00 (under 3 min scores a 2 on their rubric) | Mahdi | ☐ |
| B4 | **Slides**, PDF, 8–10 pages | Mahdi | ☐ |
| B5 | ✅ **One-page write-up** — drafted at `docs/WRITEUP.md`; results table filled in after the window | Mahdi | ✅ |
| B6 | **Cover image**, PNG or JPG, 16:9 | Ali | ☐ |
| B7 | **Competition account ID in the submission** — `PA3BAT1OOEFE`. Without it, P&L is not scored at all | Mahdi | ☐ |
| B8 | **Short description** ≤255 chars · **Long description** ≥100 words · tags | Mahdi | ☐ |

---

## 🟠 TECHNICAL — not blocking, but this is where the risk is

### ✅ T2 — DONE: exit logic verified on real historical data
Built `agent/replay.py` — replays real option prices through the live
`monitor.evaluate_exit()`. 85 trades over 6 expiry cycles. Take-profit, time
stop, expiry force-close, mark-to-market and intrinsic settlement all confirmed
working. See [`BACKTEST.md`](BACKTEST.md).

### ✅ T4 — DONE: backtest complete
Naive strategy loses (−$240, PF 0.91); each of the agent's filters improves it,
reaching +$657 / PF 2.52 / 81% win rate. Caveats documented honestly.

### T1 — 🔴 No order has ever actually filled
**This is the single biggest unknown in the whole project.**

Orders were *accepted* by Alpaca (status `accepted`), but the market has been
closed all weekend, so nothing has filled. Accepted ≠ filled.

Unverified until a real fill happens:
- whether our limit prices are close enough to the market to fill at all
- whether the fill payload has the shape our code expects
- whether `filled_qty` reconciliation works on a partial fill
  (Alpaca's paper environment produces random partial fills ~10% of the time)
- whether the exit loop correctly marks and closes a real position

**Plan:** Monday 09:30 ET — run live on the **DEV** account, watch real fills,
fix whatever breaks, then switch to COMP.

### T3 — IV rank is missing
The agent currently compares implied vol against *realised* vol as a proxy. The
better signal is IV **rank** (where today's IV sits within its own recent range),
which needs a history we don't have yet. `state.py` already records one IV
reading per underlying per day, so it will build up — but it will only be a few
days deep by Friday.

**Optional improvement:** backfill from option bars (available since Feb 2024).
Costs a lot of API calls; only worth doing if there's spare time.

### ✅ T5 — DONE: MCP session recorded
`scripts/mcp_session.py` drives the MCP server over stdio via JSON-RPC and
records a real, reproducible session — 54 tools discovered (12 options-specific),
account state, clock, option chain with Greeks, contracts, positions, the agent
looking up its own API docs, and news. Saved to
[`mcp_session_transcript.md`](mcp_session_transcript.md).

Also documented there: Alpaca's MCP server wraps every response in a security
envelope marking tool output as untrusted, and classifies news/docs output as
`external_text` (prompt-injection risk). Our architecture already defends against
this — the LLM's output is schema-constrained and consumed only as a probability
tilt, so it cannot pick strikes or place orders.

### T6 — Critic sometimes returns unparsable output
`brain.critic()` occasionally fails to return JSON (GLM-5.2 is a reasoning model
and spends tokens thinking). It falls back to "approve", which is safe because
the deterministic gates still run — but it means the critic is not always doing
its job.

### T7 — Rate-limit headroom untested under load
The governor reads `X-RateLimit-*` headers and throttles correctly in testing,
but we have never run a full session with 3 underlyings on a 5-minute loop for
6.5 hours. Budget is 200 requests/min; a cycle uses roughly 25–30.

### T8 — Equity curve export not wired
`portfolio_history` is available via the client but nothing archives it to disk
daily. That curve is the single most persuasive artifact for the P&L criterion.

---

## 🟡 NICE TO HAVE — only if time allows

- News-driven entries (Alpaca's real-time news stream is free and unused)
- Rolling a threatened spread (the `ROLL` branch is decided but not executed —
  it currently closes instead)
- More underlyings beyond SPY/QQQ/IWM
- Multiple expiries simultaneously
- Telegram alerts (`notifier.py` is inherited and working, just not wired in)

---

## Schedule

| Day | Focus |
|---|---|
| **Mon 31 Aug** | 16:30 local — go live on DEV, watch real fills (T1, T2). Switch to COMP if clean. |
| **Tue 1 Sep** | Demo website (Ali). Fix whatever Monday exposed. MCP transcript (T5). |
| **Wed 2 Sep** | 🔴 Record video + slides. Do NOT leave this to Friday. |
| **Thu 3 Sep** | 15:00 ET stop opening new positions. Write-up, cover image, final checks. |
| **Fri 4 Sep** | 09:30 ET flatten everything. Submit by **10:45 ET / 17:45 local**. |

---

## Cut list — drop from the bottom if we fall behind

| Priority | Item | Droppable? |
|---|---|---|
| P0 | Agent live and trading on COMP | ❌ never |
| P0 | Risk gates working | ❌ never |
| P0 | B1–B8 (all submission blockers) | ❌ never |
| P1 | T1 — verify a real fill (T2 exits now verified via replay) | ❌ effectively never |
| P1 | Demo website | ⚠️ required, but can be simple |

| P2 | T8 equity curve export | ⚠️ cheap, keep it |

| P3 | T3 IV rank backfill | ✅ droppable |
| P3 | Everything under "nice to have" | ✅ droppable |
