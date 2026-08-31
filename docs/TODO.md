# What's left — Options Alpha Agent

Last updated: **Mon 31 Aug 2026, pre-market**
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
| B1 | ✅ **Repo is PUBLIC** — verified by unauthenticated HTTP 200 and a token-free anonymous clone. Full 20-commit history scanned first: no credentials in any commit | **Nizar** | ✅ |
| B2 | ✅ **Live demo URL** — https://nizarhazaymeh.github.io/tradingbot/ · GitHub Pages from `main` root, serves `index.html` + `public/dashboard.json`, verified HTTP 200 unauthenticated. Ali can still ship the Streamlit version; this is the zero-infrastructure fallback | Ali / done | ✅ |
| B3 | **Video**, MP4, 3:00–5:00 (under 3 min scores a 2 on their rubric) | Mahdi | ☐ |
| B4 | ✅ **Slides** — [`submission/slides.pdf`](../submission/slides.pdf), 10 pages, 16:9. Includes the competitive analysis and TAM/SAM + revenue model that `02_judging_and_scoring.md` flags as scored-but-unlisted. Source is `submission/slides.html`; regenerate rather than editing the PDF | Mahdi | ✅ |
| B5 | ✅ **One-page write-up** — drafted at `docs/WRITEUP.md`; results table filled in after the window | Mahdi | ✅ |
| B6 | ✅ **Cover image** — [`submission/cover.png`](../submission/cover.png), 1920×1080, exactly 16:9 | Ali / done | ✅ |
| B7 | **Competition account ID in the submission** — `PA3BAT1OOEFE`. Without it, P&L is not scored at all. Now on slide 1 and in `WRITEUP.md`, but **the submission form itself still needs it** | Mahdi | ☐ form |
| B8 | ✅ **Descriptions drafted** at [`SUBMISSION_COPY.md`](SUBMISSION_COPY.md) — short 235 chars, long 276 words, tags, plus a list of claims to avoid. Mahdi to paste and fill the final numbers | Mahdi | ✅ draft |

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

**Tool ready:** `scripts/t1_fill_test.py` submits ONE 1-lot SPY vertical through
the production path (client → `usable_contracts` → `bull_put_spread` →
`validate_mleg` → `Executor.open_spread`), then polls until it fills and prints
the payload, per-leg fills and resulting positions. Strategy *selection* is
bypassed; no risk gate is read or changed.

```
python scripts/t1_fill_test.py --width 4            # plan, submits nothing
python scripts/t1_fill_test.py --width 4 --live     # submit + watch the fill
python scripts/t1_fill_test.py --close --live       # close it
```

It prices at the **natural** (short bid / long ask), not the mid. A mid limit is
roughly a coin flip and an unfilled order tells us nothing — which is how T1
stayed open. Costs about $0.05 on one paper lot. Guards: DEV-only, refuses while
the market is closed, checks the account is unblocked and options level 3.

### ✅ T9 — FIXED: the agent was standing aside on every underlying

Found while checking why candidate strikes sat too near spot. `propose()` ranked
candidates by expected value, then ran `quality_gate()` on `scored[0]` **only**
and abandoned the underlying if it failed. Candidates 2..N were never examined.

That is the common case, not a rare one: EV rises as the short strike moves
toward spot (that is where the premium is), while `MIN_SHORT_SIGMA` requires the
opposite. The two are anti-correlated, so the top-EV structure is systematically
the one the gate rejects.

Measured on the 2026-09-04 expiry, 31 Aug, before the fix:

| | Candidates | Passed every gate | Traded | Rank 0 rejected for | First acceptable |
|---|---|---|---|---|---|
| SPY | 36 | **27** | 0 | short 778C at 0.83σ | rank 1, −0.0059 EV |
| QQQ | 36 | **16** | 0 | short 727C at 0.70σ | rank 1, −0.0032 EV |
| IWM | 34 | 21 | 0 | (regime-dependent) | rank 0 |

A rehearsal cycle went **0 submits → 3**, and every short strike in the chosen
structures clears the floor it was previously failing (SPY 780C 1.02σ / 759P
0.98σ, QQQ 695P 1.52σ, IWM 302C 1.06σ / 290P 0.96σ). The gate is respected, not
weakened; all three fit the per-trade budget.

**The backtest could not have caught this** — neither `scripts/backtest.py` nor
`agent/replay.py` imports `agent/strategy.py`, so the selection path was never
exercised. The documented +$657 / PF 2.52 is therefore unaffected, but it also
validates payoff shape and exits, *not* live selection.
`tests/test_strategy_selection.py` (8 tests) closes that gap and asserts its own
premise, so it cannot silently go vacuous.

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

### ✅ T6 — FIXED: critic output now parses
`brain._extract_json()` had two confirmed failure modes, found by probing it with
the shapes reasoning models actually emit:

1. **Output cut off by `max_tokens` mid-object returned `None`.** GLM-5.2 spends
   output tokens thinking, so the JSON is often truncated. The fragment is valid
   up to the cut, so open strings, arrays and objects are now closed and the
   fields that did arrive are kept. Absent keys already fall back to defaults in
   both callers.
2. **It returned the FIRST top-level object.** Reasoning models emit scratch work
   first and the answer last, so the scratch pad was being read as the answer.
   `_extract_json` now takes `require_keys` and prefers the last object carrying
   them — `view()` passes `direction/confidence/magnitude`, `critic()` passes
   `approve/concerns`.

The second was the dangerous one. A critic replying `{"approve": false, ...}`
that failed to parse became `approve: True` in the fallback, so a **rejection was
silently discarded**. Truncation inside `"concerns":[...]` hit exactly that path,
because the old repair closed braces but not arrays.

`tests/test_brain_json.py` — 21 tests covering truncation (mid-object, mid-string,
dangling key, inside an array, nested), string escaping (braces inside strings,
escaped quotes, trailing backslash) and the non-repairs that must stay `None`.

### ✅ SAFETY — DONE: circuit breaker and crash recovery verified
`scripts/test_safety.py` — 21/21 passed. A real halt against the DEV account
cancelled orders, flattened the book, set `suspend_trade` server-side, and Alpaca
then **rejected a real order** with `403 "new orders are rejected by user
request"`. Crash recovery confirmed the exit plan survives an unclean restart,
and reconciliation detects both ghosts and orphans. See
[`SAFETY_TESTS.md`](SAFETY_TESTS.md).

### ✅ T7 — MEASURED: 2% of the rate budget
Instrumented `AlpacaClient._request` and ran three consecutive cycles.

| | |
|---|---|
| Requests per cycle | **23** (estimate was 25–30), identical across 3 cycles |
| Cycle wall time | 24–29s |
| `POLL_SECONDS` | 300 → 0.2 cycles/min |
| Sustained load | **5 of 200 req/min = 2%** |

Mix per cycle: 8× `/v2/options/contracts`, 4× `/v2/account`, 3× `/v2/stocks/snapshots`,
3× `/v2/stocks/bars`, 1× `/v2/clock`, 1× `/v2/positions`. `rate_remaining` never
moved off 199. The 6.5-hour concern was unfounded — there is ~40× headroom.

### 🔴 T10 — FIXED: a dry run could halt the live agent

Found while measuring T7. Two bugs, either of which would have halted the 16:30
session before it placed an order.

**1. Dry runs consumed the live order-rate budget.** `Executor.open_spread()`
logs dry-run orders to `orders_log` with `status='dry_run'`, but
`Store.orders_since()` counted every row. Rehearsing burned
`MAX_ORDERS_PER_HOUR` (12) and tripped `g_order_rate`. Since `run.py once` is dry
by default, this was the normal path.

**2. A dry run wrote the persistent kill switch.** On a breaker trip
`cycle.py` writes a `HALTED` file. `halt_everything()` correctly no-ops when dry,
but that write was unguarded — so the rehearsal in (1) left the file behind and
`g_kill_switch` then blocked every **live** cycle until it was deleted by hand.

Both fixed; `HALTED` is now gitignored too, since a committed one would halt the
agent from a fresh clone. `tests/test_order_rate.py` — 6 tests, 3 of which fail
against the old code.

**If you see `CIRCUIT BREAKER [g_kill_switch]` at 16:30:** check for a `HALTED`
file at the repo root and read it. It records which gate wrote it and when.

### ✅ T8 — DONE: equity curve archived
`scripts/export_equity_curve.py` fetches `/v2/account/portfolio/history` and
writes `docs/equity_curve.json`. Runs are **cumulative** — points are merged by
timestamp, so a daily run builds real history even though the API window slides.
Drops Alpaca's leading zero-equity placeholders (22 of them on this account),
which would otherwise wreck the drawdown maths and the chart.

Note this is a different curve from the one `export_dashboard.py` draws: that one
comes from local SQLite snapshots written by `cycle.observe()` and only exists
while the agent is running. This one is Alpaca's own record — continuous, and
more persuasive precisely because we did not compute it.

**Run it against COMP before submitting**; the artifact records `account_kind` so
the provenance is unambiguous.

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
| **Mon 31 Aug** | 16:30 local — `t1_fill_test.py --live` on DEV, watch the fill. Switch to COMP if clean. ✅ T6, T7, T8, T9, T10 done pre-market. |
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

| P2 | ~~T8 equity curve export~~ | ✅ done |

| P3 | T3 IV rank backfill | ✅ droppable |
| P3 | Everything under "nice to have" | ✅ droppable |
