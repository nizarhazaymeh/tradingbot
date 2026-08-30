# UPDATE — Sat 29 Aug 2026

Two things changed since the Aug 27 study: **lablab announced a technology partner**, and I've assessed **nizarhazaymeh/tradingbot** as a possible baseline.

⏰ **Time remaining: ~4.2 trading days.** Today (Sat) and tomorrow are closed. Mon Aug 31 · Tue Sep 1 · Wed Sep 2 · Thu Sep 3 · Fri Sep 4 (09:30–11:00 ET only). Deadline **Fri 4 Sep 15:00 UTC / 11:00 ET / 18:00 GMT+3**.

---

## PART 1 — What lablab added (diffed against the Aug 27 capture)

### 🔴 Technology partner: Featherless AI — **$25 free credits per participant**

| Item | Detail |
|---|---|
| What | Serverless inference for **40,000+ open-source models**, OpenAI-compatible, no GPUs to manage |
| Credits | **$25 per participant** |
| Promo code | **`ALPACA26`** — applied automatically at checkout |
| Access | 🔴 **First-come, first-served** |
| Validity | Pay-per-request, active until credits run out |
| Base URL | `https://api.featherless.ai/v1` |
| Example model | `zai-org/GLM-5.2` |
| Auth | `Authorization: Bearer $FEATHERLESS_API_KEY` (key format `fw-...`) |
| Plan perks | No model size limit · context up to **256K** · 1 secure agent sandbox |
| Setup guide | `09_raw_sources/lablab/Hackathon-Setup-Guide-ALPACA26.pdf` (8 pages) |
| Models catalog | https://featherless.ai/models · Docs: https://featherless.ai/docs |

**Redeem today** — "first-come, first-served" with an unstated cap.

Steps: redeem `ALPACA26` → profile (top right) → **API Keys** → create key → export it. Never commit it.

The guide also shows plugging Featherless into **Claude Code** (as an LLM gateway) or **opencode** (`/connect` → Other → base URL + key), and an Agents → Marketplace with one-click sandboxes (Open WebUI, SillyTavern, coding agents).

Troubleshooting from the guide: `401` = bad key · `403` = **model is gated, open its page and click "Unlock Model"** · `500` = unsupported parameter · `503` = cold model or full capacity, retry ×3 then ping Discord.

### 🔴 Prize pool: $6,000 → **$6,300**

| Rank | Was | Now |
|---|---|---|
| 🥇 1st | $2,500 | **$2,500 + $300 in Featherless credits** |
| 🥈 2nd | $1,500 | $1,500 |
| 🥉 3rd | $1,000 | $1,000 |

Social engagement prize unchanged: 2 teams × ($500 + 1-month Algo Trader Plus per member).

Recall the standing rule: *"To be eligible for partner prizes, the relevant partner technology must be integrated into a project submitted under the hackathon challenge."*

### Other changes
- New page section: **"Submitted concepts, prototypes and pitches"** — submissions are now visible. Worth a look at what others are building.
- Event banner image was swapped.
- Everything else — challenge text, core requirements, account rules, judging criteria, schedule — **unchanged**.

### What this means for your architecture
The recommended design already keeps the LLM out of the execution path (it produces a *view*; deterministic code picks strikes and sizes). That fits Featherless well:

- Run the **specialist agents** and the **critic** on Featherless open-source models. $25 of pay-per-request inference is plenty for 4 days of a low-token-per-call agent.
- It gives you a legitimate **partner-technology integration** to name in the submission.
- Keep a fallback provider configured — if Featherless has a cold model or you exhaust credits mid-run, the agent must not stop trading. Wrap inference behind one interface with a retry-then-fallback path.

---

## PART 2 — Assessment: `nizarhazaymeh/tradingbot` as a baseline

**Repo:** https://github.com/nizarhazaymeh/tradingbot · 16 files · **2,858 lines of Python** · 8 commits
**Dependencies:** `python-dotenv` only — everything else is stdlib (`urllib`). Zero-install, which is genuinely nice.

### What it is

A **classical technical-analysis bot for US equities/ETFs** on Alpaca. Well-built, honestly documented, and clearly written by someone who understands trading.

| Module | LOC | Purpose |
|---|---|---|
| `alpaca_client.py` | 490 | REST client: account, clock, assets, bars (batched), positions, orders, brackets |
| `bot.py` | 476 | Main loop, position management, reconciliation, entry/exit handling |
| `strategy.py` | 396 | 12-point confluence scoring → `Plan` with stop + TP1/TP2/TP3 |
| `broker.py` | 313 | Broker abstraction, RTH filtering, bad-print removal, order placement |
| `backtest.py` | 246 | Replays the same `strategy.analyze()` on an expanding window |
| `config.py` | 235 | Env config |
| `levels.py` | 221 | Pivots, market structure, supply/demand zones, Fibonacci |
| `indicators.py` | 153 | SMA/EMA/ATR/ADX/RSI (hand-rolled, Wilder smoothing) |
| `risk.py` | 120 | Sizing, daily loss, account blocks, PDT guard |
| `test_alpaca.py` / `notifier.py` / `tradelog.py` | 208 | Connectivity test, Telegram+email, CSV journal |

**Strategy:** EMA/SMA crossover confirmed across two timeframes, scored on 12 confluence points (MA cross 2, trend MA 1, higher-TF 2, structure 1, demand zone 2, Fibonacci pocket 2, ADX 1, RSI 1, volume 1), needing ≥6. Structure-based stops bounded by ATR. Scaled exits: TP1 close 50% → stop to breakeven; TP2 close 30% → start trailing; TP3 close 20%.

**Universe:** `GLD@15m, FXE@1h:4h, FXB@1h:4h, FXY@1h:4h, UUP@1h:4h` — gold and currency ETF proxies.

**Measured result (author's own backtest, 51 trades):** **−0.15% mean**. Three of five symbols profitable; FXB −1.91% and FXE −0.90% drag it negative. The README says so plainly: *"Progress, not victory… Treat this as a framework that now has the right shape — not as a validated edge."*

### 🔴 The three hackathon gates it fails

I grepped the entire codebase. These are absences, not weaknesses:

| Gate | Status | Evidence |
|---|---|---|
| **Options trading** (core requirement: *"all strategies must incorporate options trading"*) | ❌ **Zero** | No `/v2/options`, no `mleg`, no Greeks, no strikes, no expirations. `grep -rinE 'option\|mleg\|greek\|strike\|expir'` → **no matches** |
| **MCP server or CLI** (core requirement) | ❌ **Neither** | Direct `urllib` REST calls. `grep -rinE 'mcp\|subprocess\|uvx'` → **no matches** |
| **Autonomous *AI* agent** (core requirement) | ❌ **No AI at all** | `requirements.txt` is one line: `python-dotenv==1.0.1`. No LLM, no model, no inference. It is a deterministic TA bot. |

Three further mismatches:

4. **Bracket orders are the core protection mechanism** — and `bracket`/`oco`/`oto` are **equities-only** on Alpaca. You cannot attach a stop-loss to an options order. The protection architecture (`USE_BRACKET_ORDERS`, `submit_bracket_order`) does not transfer.
5. **Wrong universe.** GLD/FXE/FXB/FXY/UUP have thin options chains. An options agent wants SPY/QQQ/IWM and mega-caps — deep open interest, tight spreads, Mon/Wed/Fri expiries.
6. **Backtested slightly negative** on the instruments it targets. P&L is a judged criterion.

### 🔴 The commit timeline — read this before deciding anything

```
2026-08-28 21:20 +0300  Initial commit: trading bot
2026-08-28 22:02 +0300  Add Alpaca broker support (US stocks + crypto)
2026-08-28 22:12 +0300  Focus on Alpaca trading; remove the pump.fun sniper
2026-08-29 02:40 +0300  Multi-timeframe strategy with ATR risk; gold and currency watchlist
2026-08-29 13:23 +0300  Batch market data, make order submission idempotent, guard the closing bell
2026-08-29 13:42 +0300  Fix market data fetching against the live API; record real backtest results
2026-08-29 13:49 +0300  Finish the cleanup: Alpaca only, no Binance, no sniper remnants
2026-08-29 15:49 +0300  Confluence strategy: supply/demand, Fibonacci, and scaled TP1/TP2/TP3 exits
```

**The hackathon kicked off Aug 28 at 18:00 +0300. The first commit is 21:20 +0300 — three hours after kick-off. The latest is from today.**

So this is not a pre-existing personal project; it was started during the hackathon and is being actively developed right now. That's *fine* for eligibility (nothing here is stale reused work), but it raises a different question you need to settle before writing a line of code:

**Is Nizar entering this hackathon himself?**

- **If yes** → two submissions sharing a codebase is an originality problem. The Rule Book: *"Submissions must be original"*, and *"plagiarism… will lead to immediate disqualification."* Judges see both repos.
- **The clean fix** → **add him to your team.** Teams are **1–6 people**. One team, one submission, one codebase, no conflict — and you gain the person who wrote it. Prizes are paid to one designated individual, so agree that in writing now.
- **If he genuinely isn't entering** → get written permission (a message is enough), add an MIT `LICENSE`, and credit him in the README. Prize terms require submissions be **MIT-compliant**.

Settle this today. It costs one conversation and it protects the whole submission.

### What's actually reusable

Good news: the **infrastructure is solid and worth keeping**. The problem is that the reusable parts are the plumbing, not the parts you're scored on.

| Verdict | Modules | Why |
|---|---|---|
| ✅ **Keep almost as-is (~35%)** | `alpaca_client.py` HTTP layer · `risk.py` · `tradelog.py` · `notifier.py` · `config.py` · `indicators.py` · `levels.py` | Genuinely good: retries 429/5xx with exponential backoff, **deliberately does not retry order submission** (looks it up by `client_order_id` instead — exactly the right ambiguous-failure protocol), RTH filtering, bad-print removal, batched bars, PDT guard, account-block checks, `last_equity`-based daily loss. This is 2–3 days of work you don't repeat. |
| 🔧 **Rewrite (~40%)** | `strategy.py` · `bot.py` exit management · `broker.py` order layer · `backtest.py` | The *shape* survives — `analyze() → Plan(signal, stop, targets)` is a good contract, and scaled TP1/TP2/TP3 maps well onto spreads. But the content is equity-crossover logic, and exits must move from broker-side brackets to agent-managed closes. |
| ➕ **Build new (~25%)** | Options chain + Greeks layer · `mleg` construction + validator · IV rank / regime classifier · LLM layer (Featherless) · MCP + CLI integration | This is the hackathon. None of it exists in the repo. |

**Honest saving: roughly 1.5–2 days out of the ~4.2 you have left.** That is real and worth taking.

### 🔴 Recommendation

**Use it as an infrastructure baseline, not as a strategy baseline.**

Fork it, keep the client/risk/journal/indicator layers, and replace the trading brain. Concretely:

```
KEEP        alpaca_client.py    → extend with /v2/options/contracts + option chain + mleg POST
KEEP        risk.py             → extend with options gates (OI, spread%, DTE, Greeks present)
KEEP        indicators.py       → feeds the regime classifier (ATR, ADX, RSI already there)
KEEP        levels.py           → supply/demand zones become CONDOR STRIKE selection. This is
                                  a genuinely nice fit — the zones already find support and
                                  resistance; that is exactly where short strikes belong.
KEEP        tradelog.py         → your audit trail
KEEP        config.py, notifier.py

REWRITE     strategy.py         → regime classifier + structure selection (condor / credit
                                  vertical / debit vertical) instead of MA crossover
REWRITE     bot.py exits        → brackets don't exist for options; the monitor loop IS the stop
REPLACE     WATCHLIST           → SPY, QQQ, IWM + 3-5 mega-caps

NEW         options.py          → chain fetch, Greeks parsing (defensive!), OCC symbology
NEW         mleg.py             → payload builder + the validator (4 legs, coverage, GCD, sign)
NEW         brain.py            → Featherless LLM: view generation + critic
NEW         agent_cycle.sh      → the Alpaca CLI cron loop
NEW         .mcp.json           → MCP server config, toolsets scoped
```

**The one thing to protect against:** don't let the existing code pull you toward "keep the crossover strategy and bolt options on". The strategy is the scored part and it backtests negative on its current instruments. Take the plumbing, leave the brain.

### Revised plan for the days you have left

| When | Do |
|---|---|
| **Today (Sat, market closed)** | Settle the Nizar/team question. Redeem `ALPACA26`. Fork the repo. Create the **fresh $100k COMP paper account** (see `02_alpaca_platform/03_paper_trading_environment.md`). Extend `alpaca_client.py` with options endpoints. **Verify the mleg debit/credit sign on the DEV account.** |
| **Sun Aug 30 (closed)** | Regime classifier + structure selection + `mleg.py` + validator + risk gates + tests. Wire Featherless. Full dry run. |
| **🔴 Mon Aug 31 09:30 ET** | **COMP account live.** Every hour from here is scored P&L. |
| Tue Sep 1 – Wed Sep 2 | Harden. Dashboard. MCP transcript. **Record the video Wed.** |
| Thu Sep 3 15:00 ET | Stop opening. Close anything expiring Sep 4. |
| Fri Sep 4 09:30 ET | Flatten everything. Submit by 10:45 ET. |

Detail in `08_strategy_playbook/04_7_day_build_plan.md` — compress Days 2–3 into this weekend.
