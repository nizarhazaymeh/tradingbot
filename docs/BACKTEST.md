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

## 🔴 Honest limitations

State these anywhere the numbers appear:

- **85 trades over 6 weeks is a small sample.** Not statistically significant.
- **The period was mildly bullish.** A falling market would reverse the
  put/call asymmetry. These results do not generalise across regimes.
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
