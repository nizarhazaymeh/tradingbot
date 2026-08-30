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
