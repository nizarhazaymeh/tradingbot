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
| B5 | **One-page write-up** — must cover AI logic / risk gates / Alpaca infrastructure | Mahdi | ☐ |
| B6 | **Cover image**, PNG or JPG, 16:9 | Ali | ☐ |
| B7 | **Competition account ID in the submission** — `PA3BAT1OOEFE`. Without it, P&L is not scored at all | Mahdi | ☐ |
| B8 | **Short description** ≤255 chars · **Long description** ≥100 words · tags | Mahdi | ☐ |

---

## 🟠 TECHNICAL — not blocking, but this is where the risk is

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

### T2 — Exit logic never tested against a real position
`monitor.py` is covered by 9 unit tests using synthetic quotes. It has never
managed a position that actually exists. Since Alpaca does not support bracket
orders on options, **this loop is our only stop-loss** — if it misbehaves, a
position sits unprotected.

### T3 — IV rank is missing
The agent currently compares implied vol against *realised* vol as a proxy. The
better signal is IV **rank** (where today's IV sits within its own recent range),
which needs a history we don't have yet. `state.py` already records one IV
reading per underlying per day, so it will build up — but it will only be a few
days deep by Friday.

**Optional improvement:** backfill from option bars (available since Feb 2024).
Costs a lot of API calls; only worth doing if there's spare time.

### T4 — No backtest
The `alpaca-trading-backtest` skill is installed but unused. A backtest with
documented assumptions would strengthen the "clear, testable strategy" claim and
give us numbers for the slides beyond a few live days.

### T5 — MCP server installed but never actually used
It is registered and connected, and `07_mcp_cli/` documents it, but we have no
transcript of a real session. The judging criterion explicitly names the MCP
server. **Fix:** one genuine session where we interrogate the account in natural
language, saved to `docs/mcp_session_transcript.md`. ~30 minutes.

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
| P1 | T1, T2 — verify real fills and exits | ❌ effectively never |
| P1 | Demo website | ⚠️ required, but can be simple |
| P2 | T5 MCP transcript | ⚠️ 30 min, keep it |
| P2 | T8 equity curve export | ⚠️ cheap, keep it |
| P3 | T4 backtest | ✅ droppable |
| P3 | T3 IV rank backfill | ✅ droppable |
| P3 | Everything under "nice to have" | ✅ droppable |
