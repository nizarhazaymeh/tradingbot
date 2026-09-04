# The video — narration over the real log

**Why this and not the shot list.** `VIDEO_SCRIPT.md` needs a live cycle that
submits and fills. It cannot be recorded today: `NO_NEW_AFTER` blocks new
entries, §7 of the submit page says do not trade Friday, and `--rehearse` is
banned on camera. So this narrates the **real** cycle 68 from the 1 Sep live
session — `dry_run=False`, real orders, the fill confirmed from Alpaca's own
record. Nothing is edited out. Rough and present beats polished and absent.

**Runtime 3:31 (rubric floor is 3:00).** The rubric scores anything under 3:00 a 2. Do not cut.

## Setup (5 minutes)

```sh
# terminal at 18pt+, dark theme, full screen. Judges watch on a laptop.
cd ~/Desktop/bot
./scripts/video_cycle.sh --nopause     # rehearse once: this is the centrepiece
./scripts/video_fill.sh                # the broker's fill record
open submission/slides.pdf             # slides 5, 3, 9 ready
open https://nizarhazaymeh.github.io/tradingbot/
```

Record with QuickTime → File → New Screen Recording. One take is fine.

## Two things to say accurately, because they are on screen

- **"paper account"**, not "the competition account". Cycle 68 ran on the dev paper
  account. The competition account traded the same code the same day; its log is
  on a teammate's machine. Both are Alpaca paper. Say "a paper account".
- **The LLM lines.** `no FEATHERLESS_API_KEY — skipping LLM` is visible three
  times. Do not scroll past it fast. It is the design working: with no model, the
  agent carries on with no opinion. Say so — line 3 of the narration below.

---

## 0:00 – 0:30 · Hook + measurement  (slides 5, then 3)

> Most trading agents ask which way the market will move. Nobody answers that
> reliably. Ours asks a question that has an answer: is the market paying enough
> for this specific risk?
>
> We measured before we built. Sixty real SPY, QQQ and IWM spreads, priced with
> the market's own implied volatility — **zero** were positive expected value.
> That's not a bug; that's an efficient market. So the edge had to be real: the
> variance risk premium. We price with implied vol, score probability with
> realised vol, and trade only the gap.

## 0:30 – 2:15 · The cycle  (terminal: `./scripts/video_cycle.sh`)

Run it. Press a key to advance each block. Point at the line as you say it.

**Block 1 — reconcile and the book** (0:30–0:50)

> This is one real cycle from Tuesday's live session — cycle 68, 5:20 in the
> afternoon, on a paper account, `dry_run=False`.
>
> First it reconciles against the broker. **The broker is the truth**, not our
> database — it's looking for positions we think we hold and don't, and the
> reverse. Then it marks every open position and runs the exit logic on each.
> Options on Alpaca have no bracket orders, so **this loop is the stop-loss.**

**Block 2 — SPY: rich, and refused** (0:50–1:15)

> SPY. Implied vol 13.1 percent, realised 6.8 — the market is charging nearly
> twice the volatility it's delivering. Rich. The regime says sell premium.
>
> 200 usable contracts, 100 rejected before scoring — spread width, open
> interest, missing Greeks.
>
> Notice: the language model wasn't available this cycle. The view defaults to
> **neutral, no opinion**, and the agent carries on. That's the design — the model
> only ever offers an opinion; code decides. Take the model away and nothing
> touching money changes.
>
> And then — **rejected**. The best structure risks $151 and the per-underlying
> budget has $66 left. Rich regime, good structure, and the risk gates said no.
> That's twenty-nine deterministic checks, and this is one of them doing its job.

**Block 3 — QQQ: submit** (1:15–1:40)

> QQQ. Implied 18.7 against realised 12.7 — 1.47 times. Trend is down, so it
> will only sell the side the trend is moving away from: calls.
>
> 239 candidates. It scores every one by expected value under realised vol, and
> takes the best one that **also** clears every gate — not just the top scorer.
>
> **Submit.** Bear call spread, short the 721, long the 723, twenty-seven cents
> credit, two lots. Max loss $346 against a per-trade budget of about $400. A
> single multi-leg order over Alpaca's REST API.

**Block 4 — IWM refused, IBIT stands aside** (1:40–2:15)

> IWM — also rich, 1.68 times, trend down. **Refused**: the per-expiry budget is
> nearly spent. It won't stack risk into one Friday.
>
> IBIT. Implied 39.1, realised 38.4. **One-point-oh-two times.** The market is
> charging almost exactly the real risk — there's no premium to sell. It stands
> aside.
>
> **Standing aside is the product.** Four underlyings, all with something to
> trade, one order. Equity $100,237, eight open, one submitted.

## 2:15 – 2:35 · The fill  (terminal: `./scripts/video_fill.sh`)

> That's our log. This is Alpaca's. Same order — submitted 14:20:40, **filled
> 14:31:39**, eleven minutes later, at exactly the limit: sold the 721 call at
> 84 cents, bought the 723 at 57. Twenty-seven cents credit. It fills.

## 2:35 – 2:55 · Dashboard + tests  (browser, then terminal)

Reload the dashboard.

> Same data, no credentials, public URL. The panel that matters is *why we trade
> or skip* — market price versus real risk, per underlying, every cycle.

```sh
./.venv/bin/python -m pytest tests/ -q
```

> 319 tests. The risk gates are the product, and every one of them is pinned.

## 2:55 – 3:20 · Close  (slide 9)

> Rules-only bots can't read context. LLM-first agents can't be trusted with the
> order ticket. The differentiator isn't the model — it's the boundary. One
> schema-constrained opinion in; twenty-nine deterministic gates before anything
> is sent; and a strategy we backtested against ourselves, found losing on
> costs, and narrowed to what actually worked.
>
> Paper account P-A-3-B-A-T-1-O-O-E-F-E. Repo and demo are public. Thank you.

---

## If you have 20 more seconds

Between the fill and the dashboard, the strongest thing in the project
(`VIDEO_SCRIPT.md`, "Added 1 Sep"). Show `docs/BACKTEST.md` Part 10's first table.

> After the book went flat we ran the real pipeline over two years and a hundred
> and nine expiries, net of the bid-ask crossed twice. The agent as it traded this
> week: break-even before costs, **minus $3,940 after.** Three structure families
> were losing — condors, debits, short calls — each for a reason we can name. With
> them off: plus $424, ninety percent win rate, worst trade $86. That's small and
> it's in-sample, and we say so. But every entrant will tell you their agent
> works. We can show you what ours got wrong and how we found out.

## Do not

- Don't run `--rehearse` on camera. Don't run `run.py once --live` — the deadline
  gate will print `past NO_NEW_AFTER` and nothing else.
- Don't show `.env`.
- Don't say "the competition account" over cycle 68. Say "a paper account".
- Don't cut the IBIT stand-aside to save time.
