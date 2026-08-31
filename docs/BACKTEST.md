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

---

# Part 5 — Training a market-structure model on history

Run 31 Aug 2026 · `scripts/train_structure.py` · raw data
[`structure_dataset.json`](structure_dataset.json) ·
results [`structure_model.json`](structure_model.json)

`agent/levels.py` computes real market structure — swing pivots, supply/demand
zones, Fibonacci retracements. Part 4's Finding 1 killed one *hand-written* rule
built from it. That is not the same as showing structure carries no information,
so this asks history to choose the rule instead of us.

## Method

Every one of the 277 recorded trades is relabelled with the market context that
existed at its entry, rebuilt from bars **up to and including that date** — 57
(underlying, entry) contexts across 19 entry dates. Fourteen features:

| Structure (`levels.py`) | Trend & volatility |
|---|---|
| swing structure up / down | z-score signed toward the short strike |
| position in the 20-day range | realised vol, ADX, RSI, ATR % |
| Fibonacci golden pocket | condor flag |
| ATRs of room to the short strike | |
| a supply/demand zone in the way, its distance, its touches | |

A ridge regression predicts each trade's **return on risk** (`pnl / max_loss`),
scored **leave-one-window-out**. The regularisation strength *and* the admission
threshold are chosen by an inner leave-one-out on the three training windows, so
nothing about the held-out window touches the fit.

## Result — the model does not generalise

| Window | naive | shipped | learned |
|---|---:|---:|---:|
| Calm / rising | −$240 | **+$293** | −$441 |
| Vol spike 46% | −$695 | −$844 | **−$695** |
| Selloff −7.7% | **+$3,479** | +$2,322 | +$152 |
| Carry unwind | **+$157** | −$1,360 | −$346 |
| **Total** | **+$2,701** | +$411 | **−$1,330** |

Beat the shipped filter in **2 of 4** windows and lost to doing nothing entirely.
Fourteen parameters on 277 trades from 19 entry dates is the same arithmetic
Part 4 spelled out, and it fails the same way.

**Five coefficients kept a consistent sign across all four folds** — and that is
*not* evidence. With four windows, any two training sets share two thirds of
their trades, so the folds are not independent and a stable sign is close to
guaranteed. The fold P&L is the test; the coefficients are not.

## One-feature rules — the smallest thing that still counts as learning

Fit a single cut on three windows, measure on the fourth. Fifteen non-degenerate
rules; one survives, beating naive **on return-on-risk in all four folds**:

> **stand aside when `levels.market_structure()` reads "down"**
> 165 trades · 72% win · **+$2,836** · PF 1.70 · R **+0.037** (naive: +0.019)

Before believing it, look at what it excludes:

| Window | excluded (structure = "down") | kept |
|---|---:|---:|
| Calm / rising | −$975 · PF 0.45 | +$735 · PF 1.79 |
| Vol spike 46% | −$1,206 · PF 0.46 | +$511 · PF 1.42 |
| **Selloff −7.7%** | 🔴 **+$1,956 · PF 5.55** | +$1,523 · PF 18.11 |
| Carry unwind | +$90 · PF 1.07 | +$67 · PF 1.04 |

The excluded bucket is badly negative in two windows, roughly flat in one, and
**the single most profitable bucket in the fourth**. It clears the bar on
return-on-risk while giving up $1,956 of real money in the selloff, and it is the
best of fifteen rules searched — about what the luckiest of fifteen coin flips
looks like. **A hypothesis worth carrying into live data. Not a filter to ship.**

## 🔴 What training actually found — about a filter that already ships

The useful output was not a new model. Splitting the recorded trades by the
trend direction `regime.trend_score()` reports:

| | admitted by the trend filter | refused by it |
|---|---:|---:|
| **Call credit spreads** | 87 · 60% · **−$1,197** | 24 · 79% · **+$954** |
| **Put credit spreads** | 63 · 78% · +$899 | 48 · 75% · **+$1,067** |

**The filter blocks the better bucket on both sides.** Per window, the put-side
veto — *do not sell puts into a downtrend* — cost money in **3 of 4** windows
(+$659, +$154, +$479 refused; −$225 correctly refused once). The call-side veto
applied in only two windows and was right in one of them.

There is a mechanism, not just a correlation. **A downtrend is precisely when put
premium is richest** — spot falls, implied volatility spikes, and the variance
risk premium the agent exists to harvest is at its widest. The trend filter
refuses to sell exactly then. It is fighting the edge in the README.

This is the same wound Part 4's Finding 2 found from the other side, now measured
against the real `strategy.candidates()` rule rather than a QQQ stand-in: across
all four windows the directional filters turn **+$2,701 into +$411**.

**Caveat that keeps this from being an instruction to invert the filter:** 19 entry
dates. Three of the four windows are selloff-adjacent, and a market that falls
then stabilises rewards fading — which is what "sell puts into a downtrend" is.
The measured claim is *the veto's premise is unsupported here*, not *the opposite
veto works*.

## What this changes

Nothing, yet, and deliberately:

- **The structure model is not wired into the admission path.** It lost to doing
  nothing out-of-sample. `agent/levels.py` keeps its existing role — computed,
  logged, and passed to the LLM as context.
- **`regime.trend_score()` still ignores structure**, as Part 4 left it. This adds
  a second, independent reason.
- **The put-side trend veto is now a live question**, with a mechanism and 3-of-4
  windows behind it. Narrowing it is a strategy change worth making on more than
  19 entry dates, and every trade on the competition account is one more.

## Reproduce

```bash
python scripts/train_structure.py                    # model + rule search
python scripts/train_structure.py --features structure   # structure alone
python scripts/train_structure.py --mode rules --refresh # rebuild from the API
```

The per-trade feature dataset is committed, so re-runs need no API access.

---

# Part 6 — Break of structure, and the retest that confirms it

Run 31 Aug 2026 · `agent/levels.py` + `scripts/train_structure.py --features breaks`

Part 5 trained on pivots, zones and Fibonacci and found nothing that generalised.
Those describe *where* price has been. They never ask the question a price-action
trader actually asks: **has this level been tested since it broke, and did it
hold?**

## What was added

`levels.breaks()` finds every close through a confirmed swing pivot, then walks
forward to the first return to that level and rules on it:

| verdict | what happened |
|---|---|
| **confirmed** | price came back to the level and closed on the break side — it held |
| **failed** | price came back through and kept going — a false break, a trap |
| **pending** | price never returned inside `max_wait` bars |

Nothing repaints. A pivot needs `right` bars to exist, so a break of it cannot be
seen earlier than `right` bars after the swing, and the retest is judged on the
bar that touches the level. `test_a_break_is_never_reported_before_its_pivot_was_confirmed`
asserts that invariant directly.

This resolves far more often than `market_structure()`, which is the failure Part
4 diagnosed. Across the 57 entry contexts: **31 confirmed, 14 pending, 12 failed**
— against "range" in 28 of 57 for swing structure.

## Result — the first structural model that clears the shipped filter

Same leave-one-window-out harness as Part 5, same nested selection, seven
break/retest features:

| Window | naive | shipped | learned |
|---|---:|---:|---:|
| Calm / rising | −$240 | **+$293** | +$122 |
| Vol spike 46% | −$695 | −$844 | **−$695** |
| Selloff −7.7% | **+$3,479** | +$2,322 | +$2,292 |
| Carry unwind | +$157 | −$1,360 | **+$533** |
| **Total** | **+$2,701** | +$411 | **+$2,252** |

**Better than the shipped filter in 3 of 4 windows**, and 5.5× its total —
against Part 5's structure model, which managed 2 of 4 and −$1,330. Still short
of trading everything, which remains the number to beat.

## The rule worth having — position, not permission

The one-feature search returns one clear winner, and it is about **where to put
the strike**, not whether to trade:

> **`retest_barrier` — only sell a strike with a confirmed retested level in front of it**
> 131 trades · 78% win · **+$3,255** · PF 1.98 · R +0.061

| | with a barrier | without |
|---|---:|---:|
| All 277 trades | 131 · 78% · **+$3,255** · PF 1.98 | 146 · 62% · **−$554** · PF 0.91 |

It is the only rule found across Parts 5 and 6 that **beats trading everything on
net dollars while taking less than half the trades.** And the separation is
sharpest exactly where theory says it should be — in front of a short call, where
a reclaimed resistance level is the thing price must break to reach the strike:

| Strategy | behind a level | no level |
|---|---:|---:|
| **call credit 1.5%** | 25 · 80% · **+$1,711** · PF 3.11 | 32 · 44% · **−$1,353** · PF 0.46 |
| call credit 3.0% | 31 · 77% · −$32 · PF 0.97 | 23 · 57% · −$569 · PF 0.54 |
| put credit 3.0% | 34 · 85% · +$738 · PF 5.50 | 22 · 73% · +$220 · PF 1.45 |
| put credit 1.5% | 24 · 71% · +$275 · PF 1.50 | 31 · 74% · **+$733** · PF 2.15 |
| iron condor | 17 · 71% · +$563 · PF 1.97 | 38 · 63% · +$415 · PF 1.26 |

Note the second row of Part 5's finding closing here: those short calls are the
trades the **trend filter refuses**. A retested level is a better reason to sell
a call than the trend direction is.

## 🔴 Why it ships as a tie-break and not a gate

| Window | with a barrier | without |
|---|---:|---:|
| Calm / rising | +$203 · PF 1.22 | −$443 · PF 0.75 |
| Vol spike 46% | +$630 · PF 2.64 | −$1,325 · PF 0.57 |
| Selloff −7.7% | +$3,088 · PF 21.45 | +$391 · PF 2.06 |
| **Carry unwind** | 🔴 **−$666 · PF 0.64** | **+$823** · PF 1.63 |

**It inverts in the carry unwind.** Three windows for, one against, and one
strategy family (put credit 1.5%) against it too. On 19 entry dates that is a
good signal, not a proven one — and this repo has now reverted two structural
rules that looked good on one slice of this same data.

So it is wired in as a **ranking preference, not a filter**:

```python
config.RETEST_BARRIER_BONUS = 0.005   # EV-ratio points, tie-break only
```

`strategy._retest_bonus()` adds it when **every** short leg of a structure sits
behind a confirmed retested level — half a protected condor is an exposed condor.
The bonus reorders candidates that have already cleared the EV floor and all 22
risk gates; it can never admit one that has not.
`test_the_bonus_cannot_admit_a_structure_the_gates_reject` plants a barrier in
front of every strike in the chain and asserts the winner still passes its gates
and that no new candidate appeared. Setting the knob to `0` disables it entirely.

Both reads are recorded on every proposal — `zone_protection` (diagnostic, as
before) and `retest_levels` (which did influence ranking) — so live fills can be
scored against them.

## What runs live now

```
structure=up · 0/1 short strikes behind a zone · 1/1 behind a retested level
```

From `run.py once --rehearse` on 31 Aug 2026. Worth noting that the zone method
found nothing on any of the three underlyings while the retest method found a
level on two — zones need a base-then-impulse pattern that is simply rarer than a
broken swing.

The break direction and its retest verdict also reach the LLM as context
(`last_break`, `break_trend`), alongside the structure read it already got.

## Reproduce

```bash
python scripts/train_structure.py --features breaks
python -m pytest tests/test_structure.py tests/test_strategy_selection.py -q
```

---

# Part 7 — The bonus, measured through `propose()`: it never fires

Run 31 Aug 2026 · `scripts/backtest_bonus.py` · raw data
[`backtest_bonus.json`](backtest_bonus.json)

Part 6 measured the retest barrier as a **filter** — keep the trades whose short
strike sits behind a confirmed retested level, drop the rest — and got +$3,255
against −$554. It then shipped as something different: a 0.005 EV-ratio
**tie-break** inside `strategy.propose()`.

Those are not the same intervention. A filter changes which trades happen; a
tie-break changes which structure is chosen when a trade happens either way.
Part 6 never measured the thing that shipped. This does.

## The obstacle, and what it took to get past it

`scripts/backtest.py` has never imported `agent.strategy`. It builds five fixed
structures at fixed % offsets, so the entire selection layer — `candidates()`,
the EV ranking, `quality_gate()`, and now the bonus — was untestable against
history. `tests/test_strategy_selection.py` says so in its own docstring.

The reason is Greeks: `propose()` picks strikes by **delta**, and the historical
bars endpoint returns none.

`scripts/backtest_bonus.py` recovers them. For every contract with a bar on the
entry date it inverts Black-Scholes by bisection to find the volatility that
reproduces that close, then differentiates at that vol for delta, gamma, theta
and vega. Contracts priced at or below intrinsic have no solution and are dropped
rather than clamped — a fabricated vol would feed a fabricated delta straight
into strike selection, which is the one thing this harness exists to get right.

**The agent's real pipeline now runs against history**: `regime.classify()` on
bars up to the entry date, `strategy.propose()`, then `Replayer.replay()` through
the real exit logic. Twice per entry, identical but for the knob.

## Result — 0 of 47

| bonus | entries changed | net effect | |
|---:|---:|---:|---|
| 0.005 *(as shipped)* | **0** | $0 | inert |
| 0.010 | 0 | $0 | inert |
| 0.020 | 0 | $0 | inert |
| 0.050 | 4 | **−$250** | hurts |
| 0.100 | 5 | **−$533** | hurts |
| 0.250 | 7 | **−$427** | hurts |

**At the shipped value it changed nothing, anywhere, in any of the four windows.**
Bisecting the knob per entry: only 14 of 47 entries can be flipped at all, the
cheapest needs **0.026** — five times the shipped value — and the median needs
**0.254**, fifty times it. The EV gaps between candidates are simply much larger
than the bonus.

And every value large enough to bite lost money.

## Why the filter result did not survive the translation

A barrier is **not strike-specific**. A level between spot and a far strike also
sits between spot and every nearer strike on that side, so it can only favour a
rival *further out* than the incumbent — and the incumbent is usually already the
furthest, because `MIN_SHORT_SIGMA` pushes that way too. The barrier is largely a
property of the **entry**, while `propose()` only ever chooses between structures
*at* one entry. There is almost nothing for a tie-break to break.

Expressing Part 6's finding faithfully would need it as an entry-level gate —
stand aside when nothing stands in front of the strike — which is exactly the
form Part 6 rejected, because it inverted in the carry unwind.

## What changed

```python
config.RETEST_BARRIER_BONUS = 0.0     # was 0.005
```

The knob is off, with the sweep table recorded beside it in `config.py`.
`tests/test_strategy_selection.py` pins the default at zero, so turning it back on
requires editing a test — which requires a new measurement to justify. The
mechanism stays fully covered by tests against an explicit non-zero value, so it
works correctly if better evidence ever turns it on.

**Everything else about breaks stays live.** They are still computed, still
recorded on every proposal as `retest_levels`, still logged, and still passed to
the LLM as context. Only the influence on selection is off — the same place
`market_structure()` ended up in Part 4, reached the same way.

That is now three structural rules measured in this repo and three that did not
earn a decision: the structure veto (Part 4), the fitted structure model (Part 5),
and this. The pattern is consistent enough to state plainly: **structure reads are
informative in aggregate and unreliable as decisions on 19 entry dates.**

## Reproduce

```bash
python scripts/backtest_bonus.py --sweep
python scripts/backtest_bonus.py --window calm
```
