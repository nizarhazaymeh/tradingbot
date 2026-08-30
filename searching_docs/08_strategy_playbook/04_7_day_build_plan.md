# 04 — The 7-Day Build Plan (hour by hour)

All times **ET** (market timezone). UTC = ET + 4. GMT+3 = ET + 7.

**Guiding rule: nothing that isn't the trading loop happens until the trading loop is live.**

---

## DAY 0 — Thu/Fri Aug 27–28 before kick-off (TODAY) · ~4h

| # | Task | Done |
|---|---|---|
| 1 | Register on lablab.ai, complete profile, **click Enroll** | ☐ |
| 2 | Join Discord https://discord.gg/lablabai — post in "Looking for a Team" if you want teammates | ☐ |
| 3 | Read `../00_EXECUTIVE_BRIEF.md` and `../05_options/02_multileg_mleg_orders.md` | ☐ |
| 4 | Sign up at Alpaca, create the **DEV** paper account, generate keys | ☐ |
| 5 | Install: `brew install alpacahq/tap/cli` · `pip install alpaca-py` · `uv` | ☐ |
| 6 | `alpaca profile login` → `alpaca doctor` → `alpaca clock` | ☐ |
| 7 | Wire the MCP server into Claude Code / Cursor; verify with `/mcp` | ☐ |
| 8 | `npx skills add alpacahq/alpaca-skills` (backtest + paper-trading + cli + mcp) | ☐ |
| 9 | **Verify options access:** `alpaca account get --jq '{options_approved_level,options_trading_level}'` | ☐ |
| 10 | **Pull a real chain:** `alpaca data option chain --underlying-symbol SPY \| head -50` | ☐ |
| 11 | Create the public GitHub repo, MIT LICENSE, README skeleton, `.env.example`, `.gitignore`. **First commit.** | ☐ |
| 12 | Run the five sanity checks in `../07_mcp_cli/03_mcp_vs_cli_decision.md` §7 | ☐ |
| 13 | Agree with your team: who is payee if you win; who owns video/slides | ☐ |
| 14 | **Social post #1** — "starting the Alpaca hackathon, here's my plan" (X + LinkedIn, tag both) | ☐ |

**Gate to pass before Day 1:** you can read a SPY option chain with Greeks from the terminal, and you know your options level.

---

## DAY 1 — Fri Aug 28 · kick-off day · ~10h

**11:00–11:45** — Attend the kick-off on Twitch. **Write down any technology-partner prizes announced** (partner prizes were "TBA before kickoff" — least-contested money in the event). Note anything said about judging.

**12:00** — Attend the Discord Q&A (16:00 UTC). Ask one sharp question; it makes you visible to the judges.

**12:30–16:00 — DATA LAYER (nothing else)**
```
✓ Universe builder: screener most-actives ∩ assets[options_enabled]
✓ Batched stock snapshots for the universe (ONE call)
✓ Option chain fetch per underlying, with server-side expiry/strike filters
✓ SQLite market_snapshot table — everything else reads only from here
✓ OCC symbology helpers + round-trip tests
✓ Rate-limit governor reading X-RateLimit-* headers
✓ contract_view() defensive parser (see ../05_options/03_greeks_and_iv.md §4)
```

**16:00–18:00 — 🔴 THE mleg SIGN EXPERIMENT**
On the **DEV** account, place one small credit spread with `limit_price` negative, and one debit spread positive. Record exactly what happens to `cash`, `equity`, `options_buying_power`, and what the filled order reports. Write `docs/mleg_sign_convention.md`.
**Do not skip this.** Getting the sign wrong on Day 4 costs you the competition.

**18:00–21:00 — IV HISTORY CACHE**
Backfill daily ATM IV for your universe from option history (available since **Feb 2024**) into SQLite. You need this for IV rank, and it's slow — start it early and let it run.

**Commit at least 6 times today.**

**Social post #2** — a screenshot of the chain + Greeks pulling from the terminal.

---

## DAY 2 — Sat Aug 29 · market closed · ~12h

Market is closed — this is your **pure build day**. Use it.

**Morning — REGIME CLASSIFIER + AGENTS**
```
✓ Deterministic regime classifier (IV rank, trend_z, expected move) + tests
✓ Structured proposal schema (pydantic) — the contract every agent must satisfy
✓ 4 specialist agents (VolHarvest / Directional / Catalyst / Skew), isolated
✓ Critic agent — structural validity ONLY, reads strategy_memo.yaml
```

**Afternoon — 🔴 RISK GUARD (the most important code you will write)**
```
✓ mleg structural validator (4-leg cap, coverage, GCD, intents, no equity legs)
✓ Liquidity gates (OI, spread%, qty-vs-OI, Greeks present)
✓ size_position() with per-trade / heat / per-underlying / per-expiry caps
✓ Circuit breakers (daily -2%, total -6%) + halt() incl. suspend_trade
✓ pytest for every one of the above
```
Copy the implementations from `03_pnl_strategy_and_risk_gates.md`.

**Evening — EXECUTION + AUDIT**
```
✓ CLI wrapper: dry-run → log → submit, with client_order_id
✓ One JSON line per decision (proposal + gate results + verdict + order)
✓ Reconciliation on startup (orphan positions/orders, missing intents)
✓ agent_cycle.sh + crontab + flock
```

**Social post #3** — the risk-gate test suite passing.

---

## DAY 3 — Sun Aug 30 · market closed · ~12h

**Morning — POSITION MONITOR**
```
✓ exit_decision(): TP / stop / delta breach / time stop / expiry force-close
✓ ROLL: build the atomic 4-leg mleg roll payload
✓ Persist exit intents; rebuild them on restart
✓ Price ladder for re-pricing unfilled limits
✓ Tests for every exit branch
```

**Afternoon — 🔴 FULL DRESS REHEARSAL ON DEV**
Run the complete loop end-to-end against the DEV account. Market is closed, so you're testing:
- clock gate correctly refuses to trade
- queued `day` orders behave as expected
- reconciliation handles a mid-run kill -9
- the audit log is readable by a human

Then **replay** a weekday's cached snapshot through the loop to exercise the trading path.

**Evening — CREATE THE COMPETITION ACCOUNT**
```
1. Dashboard → paper account number (upper left) → "Open New Paper Account"
2. Accept the DEFAULT $100,000. Name it HACKATHON-COMP.
3. Generate NEW API keys. Save the secret.
4. Verify: alpaca account get --jq '{id,equity,options_approved_level}'   → equity must be 100000
5. Record the account ID in README + write-up + a note to yourself
6. Commit docs/comp_account_preflight.txt
7. DO NOT place any test orders on it.
```

**Also tonight:** write the **first draft** of the one-page write-up. It's required, it's easy to forget, and writing it now surfaces gaps in the design while you can still fix them.

---

## DAY 4 — Mon Aug 31 · 🔴 GO LIVE · ~10h

**08:30–09:25 — pre-flight on COMP**
```bash
alpaca clock
alpaca calendar --start 2026-08-31 --end 2026-09-08
alpaca account get --jq '{id,equity,cash,options_buying_power,options_approved_level,trading_blocked}'
alpaca position list     # must be []
alpaca order list --status all   # must be []
pytest -q                # all green
```

**09:30 — 🔴 START THE CRON LOOP ON THE COMP ACCOUNT.**
From here on, every hour of market time is scoreable P&L.

**09:30–16:00 — babysit, don't rebuild**
- Watch the audit log. Fix *bugs*, not *strategy*.
- ⚠️ **lablab's #1 fatal mistake: "pivoting after hour 12."** If the strategy is sound but slow, let it run. Only intervene for genuine defects.
- Log every intervention in `docs/interventions.md` — it's honest and it's good material.
- Keep position sizes conservative on Day 1 of live trading. You can scale up on Sep 1–2 once you trust it.

**16:00–20:00 — DASHBOARD v1** (Streamlit is fastest, and lablab names it as an approved platform)
```
Panel 1: equity curve (portfolio_history)
Panel 2: open positions with live Greeks
Panel 3: decision log — the last 20 proposals with gate results
Panel 4: the proposal → critic → gates → filled funnel
Panel 5: regime indicator per underlying (IV rank, trend, expected move)
```
Deploy it. A local-only demo "scores as if it doesn't work."

**Social post #4** — the agent's first live options trade, with the decision log.

---

## DAY 5 — Tue Sep 1 · ~9h

**09:30–16:00** — agent runs. You:
- Harden anything that broke yesterday.
- Add the **MCP session transcript** (`docs/mcp_session_transcript.md`) — a real conversation where you interrogate the account in natural language, and where the agent uses `search_alpaca_api_specs` to answer its own question.
- Scale sizing to plan if the loop has been stable for a full session.

**16:00–21:00**
- **Backtest** using the `alpaca-trading-backtest` skill. Document assumptions and a benchmark. Even a rough result is worth a slide.
- Draft the **slide deck** (8–10 pages): problem · solution · architecture diagram · demo screenshot · **P&L results** · risk gates · **competitive analysis** · **TAM/SAM + revenue model** · roadmap · disclosure.

---

## DAY 6 — Wed Sep 2 · ~9h

**09:30–16:00** — agent runs. Polish the dashboard. Make the "golden path" a judge will follow bulletproof.

**16:00–22:00 — 🔴 RECORD THE VIDEO (early, so you can re-record)**
Target **3:30–4:30** (rubric penalises <3 min; 5 min is the cap). Script in `05_writeup_and_demo_templates.md`.
Shots you need:
1. The one-sentence pitch over the architecture diagram
2. Terminal: cron tick → regime classified → proposal → gates → **4-leg mleg order submitted**
3. Dashboard: positions with Greeks, decision log, funnel
4. MCP: natural-language conversation with the same account
5. `pytest` all green (5 seconds)
6. Equity curve + P&L stats
7. Business case + roadmap

**Social post #5** — the demo clip.

---

## DAY 7 — Thu Sep 3 · ~8h

**09:30–15:00** — final live session. Agent runs.

**15:00 — 🔴 STOP OPENING NEW POSITIONS.** Set the flag.

**15:30 — close everything expiring Sep 4.** Don't hold 0DTE into the deadline.

**16:00–23:00 — finalize everything**
- Finish the write-up (all 3 required sections + results + disclosure)
- Finalize slides → export **PDF**
- Cover image: **PNG/JPG, 16:9**
- Video: export **MP4**, watch it once end-to-end
- README: setup instructions a judge can follow in 5 minutes
- 🔴 `git log -p | grep -iE 'APCA|ALPACA_(API|SECRET)|PK[A-Z0-9]{16}'` — **no keys in history**
- Fill in the submission form fields but **don't submit yet**

---

## SUBMISSION DAY — Fri Sep 4 · deadline 11:00 ET / 15:00 UTC

| Time (ET) | Action |
|---|---|
| **09:30** | 🔴 **`alpaca position close-all`** — flatten the entire book |
| 09:45 | Verify: `alpaca position list` → `[]` |
| 10:00 | `alpaca account portfolio --period 1W --timeframe 15Min > docs/final_equity_curve.json` |
| 10:05 | Compute final metrics; paste into write-up + slides + long description |
| 10:15 | Screenshot the dashboard and the account overview |
| 10:30 | Final commit + push. Verify the repo is **public** in an incognito window. |
| 10:40 | Verify the demo URL loads in an incognito window |
| **11:00** | ⚠️ Absolute deadline. **Aim to have submitted by 10:45.** |

### Submission form — paste-ready checklist
- [ ] Project title
- [ ] Short description (**≤255 chars**)
- [ ] Long description (**≥100 words**) — include the final P&L number
- [ ] Technology & category tags
- [ ] Cover image (PNG/JPG, **16:9**)
- [ ] Video (**MP4**, 3–5 min)
- [ ] Slides (**PDF**)
- [ ] Public GitHub URL
- [ ] Demo platform + **Application URL**
- [ ] 🔴 **Alpaca paper trading account ID**
- [ ] One-page write-up
- [ ] **5 social media post links**

---

## Cut list — what to drop if you fall behind

Drop from the bottom up. Never drop from the top.

| Priority | Item | Droppable? |
|---|---|---|
| **P0** | Trading loop live on COMP by Aug 31 | ❌ never |
| **P0** | Risk gates + circuit breakers | ❌ never |
| **P0** | Multi-leg `mleg` orders working | ❌ never (options requirement) |
| **P0** | Video + slides + write-up + account ID | ❌ never (submission gates) |
| **P0** | Public repo, deployed demo URL | ❌ never |
| P1 | Position monitor / roll logic | ⚠️ simplify to close-only |
| P1 | MCP transcript | ⚠️ 30 min of work, keep it |
| P1 | 5 social posts | ⚠️ 3h for $500 + subscriptions — keep it |
| P2 | Backtest | ✅ droppable |
| P2 | 4 specialist agents | ✅ collapse to 2 |
| P2 | Dashboard panels 4–5 | ✅ droppable |
| P3 | IV history / IV rank | ✅ substitute a fixed IV threshold |
| P3 | Skew agent, Catalyst agent | ✅ droppable |

**If you have only 3 days of build time left, the minimum viable winner is:**
one regime classifier + one strategy (iron condor OR credit vertical) + the full risk gate stack + CLI cron execution + `mleg` orders + audit log + Streamlit dashboard + video. That's genuinely competitive.
