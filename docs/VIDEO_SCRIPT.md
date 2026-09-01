# B3 — video shot list

**MP4 · 3:00–5:00 · target 3:45.** The rubric scores anything under 3 minutes a 2,
so pad the demo rather than the talking. Everything below is a command that works
in this repo today — no setup beyond a populated `.env`.

Record the terminal at a **large font** (18pt+). Judges watch on a laptop.

## Before you hit record

```sh
# 1. the market must be open, or the live beat has nothing to show
./.venv/bin/python run.py status | grep -A3 '"clock"'

# 2. clear the kill switch if a breaker fired earlier
ls HALTED && cat HALTED && rm HALTED

# 3. fresh dashboard so the demo page matches the terminal
./.venv/bin/python scripts/export_dashboard.py

# 4. have these open in tabs
#    - https://nizarhazaymeh.github.io/tradingbot/
#    - docs/WRITEUP.md
```

---

## 0:00–0:20 · The hook

**On screen:** slide 5 of `submission/slides.pdf` (the seven-stage table).

> "Most trading agents ask which way the market will move. Nobody answers that
> reliably. Ours asks a question that has an answer: is the market paying enough
> for this risk? The model gives an opinion. Code decides."

## 0:20–0:45 · The problem, and the measurement

**On screen:** slide 3 (0 of 60).

> "We measured before building. Sixty real SPY, QQQ and IWM spreads, scored with
> the market's own implied volatility. Zero were positive expected value. That's
> not a bug — that's an efficient market. So the edge had to come from somewhere
> real: the variance risk premium."

## 0:45–2:40 · 🔴 LIVE. This is the whole video.

Screen recording only, no slides. Run one cycle and narrate what scrolls past.

```sh
./.venv/bin/python run.py once --live
```

Point at each of these as it appears:

| Beat | What to say |
|---|---|
| `SPY … HIGH_IV_RANGE … IV 13.0% vs realised 10.1% (1.29x)` | "It classifies the regime first, in plain Python. Implied vol is 29% above realised — the premium is rich, so it's willing to sell." |
| `QQQ … no clear edge -> stand aside` | "QQQ is charging less than the real risk. It refuses to trade it. **Standing aside is the product.**" |
| `208 usable contracts (100 rejected)` | "It rejects contracts on spread width, open interest and missing Greeks before scoring anything." |
| `best acceptable EV of 36 candidates (rank 1)` | "36 structures scored by expected value. It takes the best one that *also* clears every risk gate — not just the best-scoring one." |
| `SUBMIT iron_condor SPY … CREDIT $0.46 \| maxloss $309` | "A four-leg iron condor, submitted as a single `mleg` order. Max loss $309 against a $550 per-trade budget." |
| order status → `filled` | "And it fills." |

Then the demo page — reload it live:

> "Same data, no credentials. The panel that matters is 'why we trade or skip' —
> market charges versus real risk, per underlying, every cycle."

## 2:40–3:05 · Risk

```sh
./.venv/bin/python -m pytest tests/ -q          # 108 passed
./.venv/bin/python scripts/test_safety.py       # 21/21
```

> "108 unit tests. And the halt path is tested against the live broker, not
> mocked — it cancels, flattens, sets `suspend_trade` on the account, and Alpaca
> then rejects a real order with a 403."

Show that 403 in `docs/SAFETY_TESTS.md`.

## 3:05–3:25 · Both Alpaca surfaces

```sh
./.venv/bin/python scripts/mcp_session.py | head -40
```

> "The hackathon asks for the MCP server or the CLI. We use both. The CLI drives
> the unattended loop — 23 requests a cycle, 2% of the rate budget. MCP is the
> oversight surface: 54 tools, 12 options-specific."

## 3:25–3:45 · Close

**On screen:** slide 9 (competitive analysis).

> "Rules-only bots can't read context. LLM-first agents can't be trusted with the
> order ticket. The differentiator isn't the model — it's the boundary. One
> schema-constrained view in, 22 deterministic gates before anything is sent.
> Paper account PA3BAT1OOEFE. Repo and demo are public."

---

## Do not

- **Don't** run `--rehearse` on camera. It prints `REHEARSAL MODE — pretending the
  market is open`, which on a recording looks like faked results.
- **Don't** show `.env`. It holds a live key, a secret and a Gmail App Password.
- **Don't** claim a return unless the account actually has one by then. Slide 8's
  numbers are a *logic* test on daily bars — say so, as the slide does.
- **Don't** cut the standing-aside beat to save time. It is the strongest thing in
  the demo and the easiest to mistake for the agent doing nothing.


---

## Added 1 Sep — the strongest 20 seconds you can show

The most persuasive thing in this project is not the P&L. It is that we measured
our own strategy and found it was losing money by design, then fixed it.

Show this on screen while you say it:

```
structure          risk   edge required   round-trip spread
iron condor SPY    $441   $8.82           $36.00
iron condor QQQ    $444   $8.88           $27.00
bear put    IWM    $356   $7.11           $9.00
```

Script:

> "Our expected-value model priced options at mid and ignored the bid/ask. So on
> the first live session, every single position had a round-trip spread larger
> than the edge we were demanding. We were losing money by design, not by bad
> luck. $68 of an $89 loss was execution cost. We now compute expected value net
> of the spread crossed twice — and the optimiser immediately started preferring
> narrower structures, because cost scales with leg count and edge does not."

Then, briefly:

> "Thirteen defects only appeared once real orders were involved. An exception
> between submitting an order and recording it left a live position with no stop
> attached. A shared ledger let one account read another's positions. A profit
> target on directional trades quietly demanded a four-times return. All of them
> are fixed, and all of them have tests."

Why this lands: every entrant will claim their agent works. Very few can show
what it got wrong and how they found out.
