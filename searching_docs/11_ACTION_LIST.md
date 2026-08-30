# 11 — THE ACTION LIST (start here)

📅 **Today: Sat 29 Aug.** Market closed today + tomorrow.
⏰ **Deadline: Fri 4 Sep, 11:00 ET / 18:00 GMT+3.**
📈 **Trading days left: Mon 31 · Tue 1 · Wed 2 · Thu 3 · Fri 4 (90 min only) = ~4.2 days.**
🎯 **The one date that matters: your agent must be LIVE on Monday 31 Aug at 09:30 ET.**

---

## PART A — The 3 requirements, and how the app meets each

The hackathon has exactly 3 hard requirements. Everything you build maps to one of them.

| # | Requirement (their words) | What you build | Where it lives |
|---|---|---|---|
| **1** | *"participants must build **autonomous AI trading agents** using Alpaca's Trading API"* | A cron loop that runs unattended every 5 min. An **LLM (Featherless)** produces a *view* → deterministic code turns it into a trade. | `brain.py` + `agent_cycle.sh` |
| **2** | *"projects must utilize either Alpaca's **MCP server or its CLI** tools"* | **Both.** CLI drives the unattended loop. MCP is the research + human-oversight surface. | `agent_cycle.sh` + `.mcp.json` |
| **3** | *"**all strategies must incorporate options trading**"* | Options are the *only* instrument. Iron condors + credit/debit verticals as **4-leg `mleg` orders**. | `options.py` + `mleg.py` |

Plus 5 submission gates that are not about code:

| Gate | Action |
|---|---|
| **Fresh paper account, exactly $100,000** | Create a NEW one. $100k is the default. Never test on it. |
| **Account ID in the submission** | Judges read your P&L from it. Put it in 4 places. |
| **Public GitHub repo** | Public from day one, many small commits. |
| **One-page write-up** | Must cover: AI logic · risk gates · Alpaca infrastructure. |
| **Live demo URL** | Streamlit / Vercel / Replit. Must load for a judge. |

---

## PART B — The architecture in one picture

```
   ┌──────────────────────────────────────────────────────────────┐
   │  EVERY 5 MINUTES (cron + Alpaca CLI)                         │
   └──────────────────────────────────────────────────────────────┘
                              │
   1. IS THE MARKET OPEN?  ───┤  alpaca clock          → if no, stop
                              │
   2. GET DATA             ───┤  option chain (quotes + Greeks + IV)
                              │  stock snapshots, news
                              │
   3. CLASSIFY THE REGIME  ───┤  plain Python, NO AI
                              │  IV rank + trend + expected move
                              │  → HIGH_IV_RANGE / TREND / LOW_IV / EVENT
                              │
   4. FORM A VIEW          ───┤  🤖 LLM (Featherless)
                              │  returns: direction, magnitude, horizon,
                              │           confidence, thesis
                              │  ❗ it NEVER picks strikes or sizes
                              │
   5. PICK THE STRUCTURE   ───┤  plain Python, NO AI
                              │  neutral + high IV  → IRON CONDOR
                              │  lean   + high IV  → CREDIT VERTICAL
                              │  trend  + low IV   → DEBIT VERTICAL
                              │  → chooses strikes from Greeks + zones
                              │
   6. RISK GATES           ───┤  plain Python, unit-tested, NO AI
                              │  mleg valid? liquid? sized? concentrated?
                              │  drawdown ok? → PASS or REJECT (logged)
                              │
   7. EXECUTE              ───┤  alpaca api POST /v2/orders  (4-leg mleg)
                              │  with --client-order-id (no double orders)
                              │
   8. MANAGE OPEN TRADES   ───┤  ❗ options have NO bracket orders
                              │  so THIS loop is your stop-loss
                              │  +50% profit → close · -150% → close
                              │  short delta > 0.40 → ROLL
                              │  expiry day → force close
                              │
   9. LOG EVERYTHING       ───┤  one JSON line per decision
                              └─────────────────────────────────────────
```

**The key idea:** the LLM has *one* job — read the market and say what it thinks will happen. Everything that touches money is deterministic, tested Python. That's what makes it auditable, and it's what the judges (Alpaca's own Trading API team) will respect.

---

## PART C — The steps, in order

### 🔴 TODAY — Sat 29 Aug (~6 hours)

**STEP 1 — Settle the team question** ⏱️ 10 min
Message Nizar: *is he entering the hackathon himself?*
- **If yes** → add him to your team (teams are 1–6). One team, one repo, no originality problem.
- **If no** → get written permission, add an MIT `LICENSE`, credit him in the README.
- Also agree now: **who receives the prize money** (paid to one person, not a team).

**STEP 2 — Get the free LLM credits** ⏱️ 15 min
lablab's partner **Featherless AI** gives **$25 per participant**, **first-come first-served**.
```
Promo code : ALPACA26
Base URL   : https://api.featherless.ai/v1
Model      : zai-org/GLM-5.2
Auth       : Authorization: Bearer fw-...
```
Redeem → profile (top right) → **API Keys** → create → `export FEATHERLESS_API_KEY=fw-...`
It's OpenAI-compatible, so the standard `openai` python client works by just changing `base_url`.
⚠️ Do this **first** — "first-come, first-served" with no stated cap.

**STEP 3 — Create your two Alpaca accounts** ⏱️ 20 min
| Account | Purpose |
|---|---|
| **DEV** | Break things. Test orders. Verify the mleg sign. Never submitted. |
| **COMP** | 🔴 Brand new. **$100,000 default — don't change it.** Only the final agent trades here. |

Dashboard → click the paper account number (top-left) → **"Open New Paper Account"** → generate **new API keys** for each.
Then verify and **save the output**:
```bash
alpaca account get --jq '{id, equity, options_approved_level, options_trading_level}'
# equity MUST read 100000. Write down the `id` — that's your submission field.
```
⚠️ You **cannot change the balance after creation**. Get it right once.

**STEP 4 — Install the tooling** ⏱️ 20 min
```bash
brew install alpacahq/tap/cli && alpaca profile login && alpaca doctor
pip install alpaca-py openai python-dotenv
claude mcp add alpaca --scope user --transport stdio uvx alpaca-mcp-server \
  --env ALPACA_API_KEY=$ALPACA_API_KEY \
  --env ALPACA_SECRET_KEY=$ALPACA_SECRET_KEY \
  --env ALPACA_TOOLSETS="account,trading,assets,options-data,stock-data,news"
npx skills add alpacahq/alpaca-skills
```
Prove options access works:
```bash
alpaca data option chain --underlying-symbol SPY | head -30
```

**STEP 5 — Fork the repo and strip it** ⏱️ 45 min
```
KEEP    alpaca_client.py  risk.py  indicators.py  levels.py  tradelog.py  config.py  notifier.py
DELETE  strategy.py (the MA-crossover brain)  backtest.py (for now)
GUT     bot.py  →  keep the loop skeleton, delete crossover + bracket logic
CHANGE  WATCHLIST → SPY, QQQ, IWM, AAPL, NVDA
```
Make it **public**, add **MIT LICENSE**, commit. Then commit 5–10× a day from here — judges read commit history.

**STEP 6 — 🔴 THE SIGN EXPERIMENT (most important 30 min of the weekend)** ⏱️ 30 min
On the **DEV** account, place one small credit spread with a **negative** `limit_price` and one debit spread with **positive**. Record what fills, and whether `cash` goes up or down.
```bash
alpaca api POST /v2/orders < test_credit_spread.json
alpaca account get --jq '{cash, equity, options_buying_power}'
```
Alpaca's docs say positive = debit, negative = credit — **but their own iron-condor example contradicts it.** Settle it empirically now. Save as `docs/mleg_sign_convention.md`.
Getting this wrong on Wednesday costs you the competition.

**STEP 7 — Build the options data layer** ⏱️ 2–3 h
New file `options.py`:
- fetch option chain (1 call = all strikes + quotes + **Greeks** + IV)
- OCC symbology builder (`SPY260904C00650000`)
- **defensive parser** — a missing Greek is a **REJECT, never a 0**
- liquidity filter: open interest ≥ 500, spread ≤ 15%, `tradable == true`
⚠️ **0DTE options return NO Greeks** (Black-Scholes divides by days-to-expiry). Gate `DTE ≥ 1`.

---

### 🔴 TOMORROW — Sun 30 Aug (~8 hours)

**STEP 8 — The regime classifier** ⏱️ 2 h — *plain Python, no AI*
IV rank + trend + expected move → one of: `HIGH_IV_RANGE`, `HIGH_IV_TREND`, `LOW_IV_TREND`, `LOW_IV_RANGE`, `EVENT_RISK`.
`LOW_IV_RANGE` → **do nothing**. An agent that knows when not to trade is a feature.

**STEP 9 — `mleg.py`: build + validate the orders** ⏱️ 2 h
Payload builder for iron condor / credit vertical / debit vertical, plus a validator enforcing:
- max **4 legs**
- **every short leg covered inside the same order** (no calendars, no naked shorts)
- `ratio_qty` GCD = 1
- `position_intent` on every leg
- `time_in_force: day`, no `extended_hours`
- correct debit/credit sign

**STEP 10 — Risk gates + tests** ⏱️ 2 h — *the thing you'll be judged on*
```
per trade      0.40% of equity max loss  ($400)
portfolio      4.0% total heat           ($4,000)
per underlying 1.2%    per expiry 2.5%   max 10 open positions
circuit breaker: daily -2% / total -6% → cancel all, flatten, suspend_trade
```
Write `pytest` tests for each. This is direct evidence for the required write-up.

**STEP 11 — The brain (Featherless)** ⏱️ 1.5 h
```python
from openai import OpenAI
client = OpenAI(base_url="https://api.featherless.ai/v1",
                api_key=os.environ["FEATHERLESS_API_KEY"])
# returns STRUCTURED JSON only: direction, magnitude, horizon_days, confidence, thesis
```
Plus a **critic** call that checks structural validity only. Keep a fallback provider — if Featherless is cold or credits run out, the agent must not stop.

**STEP 12 — Full dry run** ⏱️ 1.5 h
Run the whole loop end-to-end on DEV with `--dry-run`. Kill it mid-cycle and confirm it recovers. Check the audit log is readable.

---

### 🔴 MONDAY 31 AUG, 09:30 ET — GO LIVE

**STEP 13 — Start the cron loop on the COMP account.**
From this moment, every market hour is scored P&L.
Then: **fix bugs, don't change strategy.** lablab's own guide says pivoting late is "almost always fatal."

**STEP 14 — Build the dashboard** (Mon afternoon, ~4 h)
Streamlit. 4 panels: equity curve · open positions with Greeks · decision log · the proposal→gates→filled funnel. **Deploy it** — a local-only demo scores as if it doesn't work.

---

### Tue 1 – Wed 2 Sep

**STEP 15** — Harden. Capture an **MCP session transcript** (`docs/mcp_session_transcript.md`).
**STEP 16** — 🔴 **Record the video on Wednesday**, not Friday. Target **3:30–4:30** (under 3 min scores a 2). Demo in the middle.
**STEP 17** — Slides (PDF, 8–10 pages). Must include a **competitive analysis** slide and a **TAM/SAM + revenue** slide.

---

### Thu 3 Sep

**STEP 18** — 15:00 ET: **stop opening new positions.** 15:30 ET: close anything expiring Friday.
**STEP 19** — Finish the write-up (AI logic / risk gates / Alpaca infrastructure) + cover image (PNG, 16:9).
**STEP 20** — Check for leaked keys: `git log -p | grep -iE 'APCA|ALPACA_(API|SECRET)|PK[A-Z0-9]{16}'`

---

### Fri 4 Sep — SUBMIT

| Time (ET) | Action |
|---|---|
| **09:30** | `alpaca position close-all` — **flatten everything** |
| 09:45 | Verify `alpaca position list` → `[]` |
| 10:00 | `alpaca account portfolio --period 1W` → final numbers |
| 10:30 | Final push. Verify repo + demo URL in an **incognito window**. |
| **10:45** | 🔴 **SUBMIT** (deadline is 11:00 — do not cut it close) |

Submission form: title · short desc (≤255 chars) · long desc (≥100 words) · tags · cover image (16:9) · video (MP4) · slides (PDF) · GitHub URL · demo URL · 🔴 **Alpaca account ID** · write-up · **5 social post links**

---

## PART D — Do these 5 things in the next hour

1. ☐ Message Nizar about the team
2. ☐ Redeem Featherless `ALPACA26` (first-come, first-served)
3. ☐ Create the COMP paper account, verify `equity = 100000`, **write down the ID**
4. ☐ `brew install alpacahq/tap/cli && alpaca doctor`
5. ☐ Fork the repo, make it public, add MIT LICENSE, first commit

## PART E — Don't forget the free money

**Social posts: 2 teams win $500 + Algo Trader Plus for every member.** Costs ~3 hours total, 5 posts, tag `@AlpacaHQ` + `@lablabai` on X and LinkedIn. Most teams won't do it properly.
Drafts are ready in `08_strategy_playbook/06_social_engagement_plan.md` — **post #1 today.**
