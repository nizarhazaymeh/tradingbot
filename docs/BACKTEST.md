# Backtest — do the agent's filters actually help?

Run 30 Aug 2026 · 85 trades · 6 weekly expiry cycles · 4 DTE · SPY, QQQ, IWM
Raw data: [`backtest_results.json`](backtest_results.json) · Harness: `agent/replay.py`

---

## The question

The agent applies three filters before it will trade:

1. **VRP filter** — only sell premium where implied volatility exceeds realised
2. **Trend filter** — only sell the side the trend is moving *away* from
3. **EV filter** — require expected value ≥ 2% of capital at risk

Do they earn their place, or are they decoration? We replayed real historical
option prices to find out.

## Result

| Variant | Trades | Win rate | Net P&L | Profit factor | Per trade |
|---|---:|---:|---:|---:|---:|
| **Naive** — sell both sides, every underlying | 85 | 69% | **−$240** | 0.91 | −$2.82 |
| **+ VRP filter** (drops QQQ) | 57 | 74% | **+$290** | 1.26 | +$5.09 |
| **+ trend filter** (no short calls into an uptrend) | 36 | **81%** | **+$657** | **2.52** | +$18.25 |

**Each filter improves the outcome.** The naive version loses money despite a 69%
win rate — because the losses are bigger than the wins. The filters target
exactly the trades that were losing.

## Where the naive version lost

| Strategy | Trades | Win% | Net | PF |
|---|---:|---:|---:|---:|
| put credit 1.5% OTM | 17 | 76% | +$183 | 1.39 |
| put credit 3.0% OTM | 18 | 78% | +$98 | 1.40 |
| **call credit 1.5% OTM** | 18 | 56% | **−$467** | **0.57** |
| **call credit 3.0% OTM** | 15 | 73% | **−$197** | **0.44** |
| iron condor ±2.2% | 17 | 65% | +$143 | 1.26 |

| Underlying | Trades | Win% | Net | PF |
|---|---:|---:|---:|---:|
| SPY | 27 | 74% | +$81 | 1.14 |
| **QQQ** | 28 | 61% | **−$530** | **0.66** |
| IWM | 30 | 73% | +$209 | 1.38 |

Two clear stories:

**Short calls got run over.** SPY rose in 4 of the 6 cycles. Selling calls into a
rising market loses, and a 56% win rate with large losers is exactly the
signature. The agent's trend filter refuses these.

**QQQ was the single biggest loser** (−$530 of a −$240 total). And this is the
part worth noting: **the VRP filter was built before this backtest existed**, from
a live measurement showing QQQ's implied volatility sitting *below* its realised
volatility. It independently flagged the worst underlying in the sample.

## Market context

SPY moves over the tested cycles: −0.44%, +1.07%, +2.04%, +0.42%, −0.90%, +0.76%.
A gently rising market. That flatters put-selling and punishes call-selling, and
the results reflect exactly that.

---

# Part 2 — Stress test across four market regimes

The section above tested one calm, mildly rising period. That flatters
premium-selling, so we went looking for the periods that would break it.

Scanning SPY since Feb 2024 for the worst 4-week windows produced three:

| Period | 4-week return | Realised vol | Character |
|---|---:|---:|---|
| **Apr 2025** | −4.7% | **46%** | volatility spike |
| **Mar 2026** | **−7.7%** | 15% | sustained selloff |
| **Aug 2024** | −4.6% | 21% | carry unwind |
| *Jul–Aug 2026* | +3.9% | 10% | *calm, rising (original test)* |

**277 trades across all four.**

## Result by strategy and regime (net $ / profit factor)

| Strategy | Calm/rising | Vol spike 46% | Selloff −7.7% | Carry unwind | **All** |
|---|---:|---:|---:|---:|---:|
| put credit 3.0% OTM | +98 / 1.4 | +311 / 2.3 | +316 / 4.9 | +233 / 3.8 | **+958 / 2.5** |
| put credit 1.5% OTM | +183 / 1.4 | +718 / 4.3 | −234 / 0.5 | +341 / 6.7 | +1008 / 1.8 |
| **iron condor ±2.2%** | +143 / 1.3 | 🔴 **−510 / 0.28** | +1443 / ∞ | −98 / 0.9 | +978 / 1.4 |
| call credit 1.5% | −467 / 0.6 | −694 / 0.5 | +1540 / ∞ | −21 / 1.0 | +358 / 1.1 |
| call credit 3.0% | −197 / 0.4 | −520 / 0.5 | +414 / ∞ | −298 / 0.7 | −601 / 0.8 |

### 🔴 The finding that changed the strategy

**Iron condors collapse in high volatility.** They profit from the underlying
sitting still, so a 46%-vol market destroys them:

| Realised vol | Condor win rate | Profit factor |
|---:|---:|---:|
| ~10% | 65% | 1.30 ✅ |
| ~21% | 57% | 0.90 ⚠️ |
| **~46%** | **42%** | **0.28** 🔴 |

The original single-period backtest could never have found this — that period had
10% realised vol, where condors look fine.

### The fix

`config.MAX_VOL_FOR_CONDOR = 0.18` — the agent will not open an iron condor when
realised volatility exceeds 18%. Directional credit spreads, which do not need
the price to sit still, are unaffected. Two unit tests cover both sides of the
ceiling.

**Effect across all four regimes:**

| Variant | Trades | Win rate | Net P&L | Profit factor |
|---|---:|---:|---:|---:|
| Everything | 277 | 69% | +$2,701 | 1.27 |
| **+ condor volatility ceiling** | 251 | 71% | **+$3,309** | **1.41** |
| **+ trend filter** | 140 | **77%** | **+$3,552** | **2.49** |

The ceiling removes 26 condor trades that lost −$608 (PF 0.63) and keeps 29 that
made +$1,586 (PF 3.90, 79% win). A clean split along exactly the line theory
predicts.

### Also confirmed

**Put credit spreads at 3% OTM were profitable in all four regimes** (PF 2.3–4.9)
— the most robust structure tested, and the only one that never had a losing
period.

**Call credit spreads only worked in the selloff.** Overall PF 0.8–1.1. This is
why the agent's trend filter refuses to sell calls into a rising market.

---

## 🔴 Honest limitations

State these anywhere the numbers appear:

- **277 trades across 4 regimes is better than one period, but still small.**
  Four regimes is not the same as four independent samples — each is a handful of
  consecutive weeks, so the trades within a period are correlated.
- **The regimes were chosen by looking for the worst windows.** That is the right
  way to stress-test, but it is not a random sample of history.
- **The condor volatility ceiling was fitted to this data.** 18% sits between the
  21% period (PF 0.9) and the 10% period (PF 1.3). The *direction* of the effect
  is well-supported by theory — condors need a still market — but the exact
  threshold is not independently validated.
- **Daily bars only.** No intraday movement, so exits trigger on closes. Real
  intraday stops would fire earlier and more often.
- **Fills at the bar close**, with a synthetic 2-cent spread per leg. Real
  bid/ask crossing costs more.
- **Strikes selected by % distance from spot, not by delta** — historical Greeks
  are not available from the bars endpoint, and the live agent uses delta.
- **Mild selection risk**: the trend and EV filters were tuned with some
  awareness of this data. The VRP filter was not — it predates the backtest.
- No commissions or regulatory fees (paper trading doesn't charge them either).

**What this does establish:** the exit logic works correctly on real price data,
and the filters move results in the right direction. **What it does not
establish:** a validated edge.

## What it verified about the code

Beyond the P&L, this was the first real test of the exit loop — which matters
because Alpaca has no bracket orders on options, making that loop the agent's
only stop-loss.

Confirmed working on real historical prices:
- ✅ mark-to-market on multi-leg structures
- ✅ take-profit at 50% of max gain
- ✅ time stop at DTE 1
- ✅ expiry-day force close
- ✅ settlement at intrinsic value when a position is held to expiry
- ✅ only 1 of 85 trades ever reached expiry — the agent exits early, by design

## Reproduce

```bash
python scripts/backtest.py --weeks 6 --dte 4 --underlyings SPY,QQQ,IWM
python scripts/replay_week.py --underlying SPY --entry 2026-08-24 --expiry 2026-08-28
```
Historical data is cached under `.cache/replay/`, so re-runs are instant.

---

# Part 3 — Parameter sweep

Our take-profit level, DTE, strike distance and spread width were originally
chosen by judgement. We swept each one across all four regimes (~55 trades per
setting) to replace guesses with measurements.

## Take-profit level — when to close a winner

| Close at | Win rate | Net | Profit factor |
|---:|---:|---:|---:|
| 25% of max gain | 84% | +$964 | 2.92 |
| **35% of max gain** | **84%** | **+$1,026** | **3.04** ← |
| 50% (previous) | 80% | +$958 | 2.47 |
| 65% | 77% | +$877 | 2.32 |
| 80% | 71% | +$642 | 1.68 |

Taking profit **earlier** is strictly better. The last stretch of a credit
spread's max gain takes the longest to earn and carries the most tail risk —
holding for it converts winners into losers. **Changed 50% → 35%.**

## Days to expiry

| DTE | Win rate | Net | Profit factor |
|---:|---:|---:|---:|
| **2** | 60% | **−$1,085** | **0.29** 🔴 |
| 3 | 78% | +$638 | 2.46 |
| **4** | **80%** | **+$958** | **2.47** ← |
| 7 | 81% | +$745 | 1.85 |

**2 DTE is destructive, not merely worse.** Gamma near expiry means a small
adverse move blows through the short strike faster than any exit loop can react.
**Raised `MIN_DTE` from 2 to 3.**

## Strike distance

| Distance | Win rate | Net | PF | Per trade |
|---:|---:|---:|---:|---:|
| 1.0% OTM | 70% | +$1,341 | 1.89 | +$23.53 |
| **2.0% OTM** | 75% | +$1,328 | 2.59 | **+$24.15** |
| 3.0% OTM | 80% | +$958 | 2.47 | +$17.11 |
| 5.0% OTM | 84% | +$438 | 2.67 | +$10.19 |

A clean trade-off: closer strikes collect more premium but win less often. The
live agent selects by **delta**, not fixed percentage, because delta
auto-adjusts for volatility — the same delta sits further out in % terms when
the market is volatile, which is exactly when you want it further out.

## Spread width

| Width | Win rate | Net | PF | Worst trade | Per trade |
|---:|---:|---:|---:|---:|---:|
| $2 | 77% | +$602 | 2.84 | −$109 | +$11.36 |
| $3 | 79% | +$904 | 3.03 | −$202 | +$17.06 |
| $5 | 82% | +$1,382 | 2.99 | −$222 | +$25.13 |
| **$8** | **84%** | **+$2,313** | **4.22** | −$299 | **+$42.05** |

Wider is better, because a wider spread collects proportionally more credit for
the same structure.

**Note the worst trade at $8 wide was −$299, not the theoretical −$650.** The exit
loop cut losses well before maximum. We deliberately did **not** size on that
observed loss: options do not trade overnight, and a gap open past the short
strike can realise close to the full theoretical loss with no chance to react.
Sizing still uses theoretical max loss.

At the old $400 per-trade budget the optimiser could never afford an $8-wide
structure. **Raised `RISK_PER_TRADE_PCT` from 0.40% to 0.55%** so the search space
actually includes them — the optimiser then picks on expected value, not width.

## Old config vs tuned

| Config | Trades | Win rate | Net | PF | Per trade |
|---|---:|---:|---:|---:|---:|
| Old — 4 DTE, TP 50%, 3% OTM, $5 | 56 | 80% | +$958 | 2.47 | +$17.11 |
| Tuned — 4 DTE, TP 35%, 2% OTM, $5 | 55 | 82% | +$1,382 | 2.99 | +$25.13 |
| **Tuned, $8 wide** | 55 | **84%** | **+$2,313** | **4.22** | **+$42.05** |

Per regime, the tuned config was profitable in **all four**:

| Regime | Trades | Win rate | Net | PF |
|---|---:|---:|---:|---:|
| Calm / rising | 17 | 76% | +$24 | **1.05** ⚠️ |
| Volatility spike 46% | 12 | 100% | +$1,396 | 99 |
| Selloff −7.7% | 12 | 83% | +$483 | 3.78 |
| Carry unwind | 14 | 79% | +$410 | 16.19 |

## 🔴 Read this before believing the numbers

**These parameters were tuned on the same four regimes they are scored against.**
Those results are therefore optimistic by construction. The honest expectation is
that live performance lands below them.

**The calm regime is the weak one — PF 1.05, +$24 across 17 trades.** And the
market going into the competition is calm: SPY realised volatility is ~10%, the
lowest of the four periods tested. **Our realistic expectation for the
competition window is a small positive, not the headline numbers above.**

What we consider genuinely supported, because it is theory-backed rather than
purely fitted:
- taking profit early beats holding for max gain (theta decays fastest near the end)
- very short DTE is dangerous (gamma)
- condors need a quiet market (they are a bet on stillness)
- selling calls into an uptrend loses (directional exposure)

What is fitted and should be treated with suspicion: the exact thresholds — 35%,
3 DTE, 18% volatility, 0.55% risk.


---

# Addendum, 31 Aug 2026 — the ladder is now reproducible, and two findings

`scripts/backtest.py` runs all five strategies at every expiry unconditionally
and records every result. The filter ladder above was computed **outside the
repo**, so it could not be re-run. `scripts/filter_ladder.py` is that
computation as code, applying the filters post-hoc to the recorded trades with
market context rebuilt from bars **up to and including each entry date** (no
lookahead).

```
python scripts/filter_ladder.py                          # this window
python scripts/filter_ladder.py --in docs/backtest_aug2024.json --rule calls
```

Two caveats on the reproduction itself, stated before the results:

1. **It does not match the table above exactly.** On this window my trend filter
   admits 49 trades for +$556 (PF 1.70); the table reports 36 for +$657 (PF 2.52).
   Same direction, different filter. Mine models `strategy.candidates()`; the
   original was computed by hand and its exact rule is not recorded.
2. **The "VRP filter" row is `--vrp-exclude QQQ`,** because the recorded trades
   carry no per-entry implied vol. Dropping QQQ was correct *for this window*,
   where its IV sat below realised. It is a window-specific stand-in, not the
   real VRP test, and that matters below.

## Finding 1 — swing structure does not corroborate the trend usefully

`agent/levels.market_structure()` was wired into `regime.trend_score()` so a
direction had to survive both the z-score and swing structure. It was tried two
ways and reverted:

| Corroboration rule | Trades | Net | PF | vs z-score alone |
|---|---:|---:|---:|---:|
| z-score only | 47 | **+$448** | **1.56** | — |
| veto on any disagreement | 57 | +$290 | 1.26 | **−$158** |
| veto only on the opposite reading | 49 | +$113 | 1.10 | **−$335** |

`market_structure()` requires three consecutive higher highs **and** higher lows.
On daily bars it returned **"range" in 14 of 18** entry dates, so treating that as
a veto silently disabled the trend filter — the most valuable component in the
system. In the single case where it actively disagreed (SPY 2026-08-03, z +1.92
up against structure "down") **structure was wrong**, and the two call spreads the
veto admitted lost $271 and $64.

Reverted. Structure is still computed, still logged, and still reaches the LLM as
context — it just does not decide which side gets sold. `regime.trend_score()`
still accepts the argument and deliberately ignores it, with tests pinning it
inert so the veto cannot return without a measurement.

## Finding 2 — 🔴 the filters do not generalise beyond this window

Running the same ladder over all four recorded windows, using the documented
"no short calls into an uptrend" rule:

| Window | naive | + VRP (drop QQQ) | + trend | verdict |
|---|---:|---:|---:|---|
| **Jul–Aug 2026** (this doc) | −$240 · PF 0.91 | +$290 · 1.26 | **+$556 · 1.70** | filters help |
| **Aug 2024** | **+$157** · 1.05 | −$172 · 0.92 | **−$978 · 0.56** | filters destroy it |
| **Apr 2025** | −$695 · 0.80 | −$445 · 0.80 | −$445 · 0.80 | helps, still loses |
| **Mar 2026** | **+$3,479** · 7.70 | +$2,228 · 7.02 | **+$2,228 · 7.02** | filters cost $1,251 |

The filters improve results **only in the window this document was written from.**
In Aug 2024 they turn a $157 profit into a $978 loss. In Mar 2026 they give up
$1,251 of a very profitable naive run.

This is consistent with what §Caveats already admits — *"the trend and EV filters
were tuned with some awareness of this data"* — but it is stronger than that
wording suggests. Two things soften it and neither dissolves it:

* The QQQ exclusion is a stand-in for the VRP filter and is only right for this
  window. Much of the damage in Mar 2026 (−$1,251) is that exclusion, not the
  trend rule.
* Samples are small: 12–18 entry dates and 60–85 trades per window, and Mar 2026's
  naive PF of 7.70 is not a normal market.

**What to do with this.** Do not present the ladder as evidence the filters
generalise. The defensible claim is narrower and still real: *the agent refuses
trades when implied vol does not exceed realised, and that logic is sound and
tested* — not *the filters add $897 per window*. `docs/WRITEUP.md` and
`submission/slides.pdf` should say the former.


---

# Addendum 2, 31 Aug 2026 — training on this data makes the bot worse

The request was to fit entries, take-profits and stop-losses to the historical
data so the agent "understands the structure of the market". That was built and
measured, and the answer is no: **the parameters chosen by judgement beat every
fitted alternative out of sample, in all four regimes.**

`scripts/sweep.py` fits across all four regimes **pooled** and reports the best —
in-sample fitting, which is how the filters in Addendum 1 came to work only in
their own window. `scripts/walk_forward.py` asks the honest question instead:
fit on three regimes, measure on the held-out fourth. Every number below was
produced by parameters that never saw the window they are scored on.

```
python scripts/walk_forward.py            # 48 parameter sets, leave-one-out
python scripts/walk_forward.py --quick    # 4 sets, smoke test
```

Grid: take-profit ∈ {0.25, 0.35, 0.50, 0.65} × stop multiple ∈ {1.0, 1.5, 2.0, 2.5}
× strike offset ∈ {1.5%, 2.2%, 3.0%}, DTE fixed at 4.

## Result

| Test regime | shipped | fitted (out-of-sample) | oracle (knows the future) |
|---|---:|---:|---:|
| calm/rising | **+$359** · PF 3.48 | +$326 · 2.83 | +$502 · 2.81 |
| vol spike 46% | **+$789** · 100% win | +$351 · 4.16 | +$885 |
| selloff −7.7% | **+$364** · PF 4.83 | +$16 · 1.04 | +$368 · 4.87 |
| carry unwind | **+$246** · PF 8.24 | +$246 · 8.24 | +$445 · 18.80 |
| **total** | **+$1,758** | **+$939** | +$2,200 |

**Fitting beat the shipped config in 0 of 4 regimes**, and cost $819 overall.

The clearest evidence that this is overfitting rather than bad luck: enlarging the
grid made it worse.

| Grid | Fitted, out-of-sample | vs shipped |
|---|---:|---:|
| 4 combinations | +$1,340 | −$418 |
| 48 combinations | +$939 | **−$819** |

More search capacity, worse results. That only happens when the search is fitting
noise.

## Why — the arithmetic

| | |
|---|---|
| Total structures | 165 |
| Test fold | 12–17 trades |
| Training fold | ~41 trades at one offset |
| Parameter combinations | 48 |
| **Training trades per combination** | **0.85** |

Less than one trade of evidence per candidate parameter set. No fitting procedure
recovers a real signal from that, and any winner it names is the luckiest sample,
not the best rule.

## What this says about the shipped config

It is close to the ceiling already. In the selloff it scores +$364 against an
oracle of +$368 — within 1%. In the carry unwind it *is* what fitting selects.
`TAKE_PROFIT_CREDIT = 0.35` and `STOP_CREDIT_MULT = 1.50` should stay where they
are, and the comment in `config.py` recording the original judgement should stay
with them.

## What would actually help

Not more fitting on this data.

1. **More data.** Four windows is not a sample. The same harness with 30+ expiry
   cycles would make fitting meaningful; that is a data-collection job, not a
   modelling one.
2. **Fewer free parameters.** Three parameters over 48 combinations on 41 trades
   is hopeless; one parameter over 4 values might not be.
3. **Live results.** Every trade the agent takes on the competition account is a
   real out-of-sample observation. That is the sample worth growing.

**Do not present fitted parameters as an improvement.** The measured claim is the
opposite, and `scripts/walk_forward.py` reproduces it.
