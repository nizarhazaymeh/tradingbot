# 03 — Greeks & Implied Volatility on Alpaca

Sources: `market-data-faq.md` (Options section), `optionchain.md`, `optionsnapshots.md`

## 1. What Alpaca gives you, free

Alpaca **computes Greeks server-side** and returns them on the option **chain** and **snapshot** endpoints:

```json
"greeks": {
  "delta": 0.5321,
  "gamma": 0.0184,
  "theta": -0.0412,
  "vega":  0.1103,
  "rho":   0.0221
},
"impliedVolatility": 0.3372405712050441
```

> "Greeks and implied volatility are not always available for all contracts. **The issue is not the data plan**, but rather how Alpaca calculates these values."

✅ **Greeks are available on the free Basic plan.** This is a big deal — you do not need to build a pricing engine, and you don't need a paid options analytics vendor. One `get_option_chain` call gives you every strike's delta/gamma/theta/vega/rho plus IV.

## 2. How they're computed

- Model: **Black-Scholes**
- Library: [gopriceoptions](https://github.com/jasonmerecki/gopriceoptions)
- IV is solved iteratively using **Vega** (Newton-Raphson style):
  > "Make an initial guess for volatility (σ₀, e.g., 20%). Calculate the theoretical price and the option's Vega at that guess. Update the guess. Repeat until the difference between guesses is close to zero."
- **Maximum 100 iterations.**

⚠️ Note: Alpaca uses **Black-Scholes**, but Alpaca's contracts are **American style** (early exercise possible). Black-Scholes prices European options. For non-dividend-paying underlyings and calls this is a small error; for ITM puts and around ex-dividend dates on short calls it understates early-exercise value. It's fine for signal generation; don't present it as a precise valuation.

## 3. 🔴 When Greeks are MISSING — all four conditions must hold

> For the calculations to have results, the following data is required:
> - **non-zero bid & ask price** for the latest quote for the contract symbol
> - **latest (SIP) trade for the underlying** symbol
> - the contract **expiration is after today**
> - the calculated **implied volatility is valid**

### Case 1: 0DTE — no Greeks, guaranteed
> "One thing to note in particular is that **contracts with 0DTE (i.e., that expire on the current day) won't have Greeks**. Why? The Black-Scholes model includes a factor with 'days to expiry' in the denominator. If that is 0, the result is division by 0 and is undefined, so Greeks cannot be calculated."

**Impact on this hackathon:** two Fridays inside the competition window (Aug 28, Sep 4) and SPY/QQQ Mon/Wed expiries mean **you will encounter 0DTE contracts on Aug 28, Aug 31, Sep 2 and Sep 4**. Any strategy that selects strikes by delta will silently find nothing on those days unless you handle it.

**Options:**
- (a) Exclude DTE=0 from the universe (simplest, safest — recommended).
- (b) Compute your own Greeks for 0DTE using IV borrowed from the next expiry.
- (c) Use a Greeks-free selection rule for 0DTE (e.g. strike distance in % of spot, or expected-move multiples).

### Case 2: deep OTM — solver doesn't converge
> "Deeply out-of-the-money (OTM) options are highly sensitive to tiny changes in price, making the calculation of an option's value highly unstable. As expiration approaches or an option gets deep OTM the option's sensitivity to volatility (Vega) approaches zero. This creates a mathematical divide-by-zero or flat-derivative scenario where numerical solvers fail to converge on an answer."

**Impact:** the far wings of an iron condor are exactly the contracts most likely to return `null` Greeks. Your condor construction code must tolerate `None` on the protective legs.

### Case 3: one-sided or zero quote — no Greeks
A contract with a zero bid (nobody wants it) returns no Greeks.

💡 **Turn this into a feature:** "has Greeks" ≈ "has a two-sided, non-zero quote" ≈ "is tradable with a real market". Use Greeks-presence as a **free liquidity filter**, layered on top of `open_interest` from `/v2/options/contracts`.

## 4. 🔴 Defensive code — never default a missing Greek to zero

```python
from dataclasses import dataclass

@dataclass
class ContractView:
    symbol: str
    bid: float
    ask: float
    mid: float
    spread_pct: float
    delta: float
    gamma: float
    theta: float
    vega: float
    iv: float
    dte: int

class Unusable(Exception): pass

def contract_view(symbol, snap, dte, *, max_spread_pct=0.15) -> ContractView:
    q = (snap or {}).get("latestQuote") or {}
    bid = q.get("bp") or 0.0
    ask = q.get("ap") or 0.0
    if bid <= 0 or ask <= 0:
        raise Unusable(f"{symbol}: one-sided/zero quote (bid={bid} ask={ask})")

    mid = (bid + ask) / 2.0
    spread_pct = (ask - bid) / mid
    if spread_pct > max_spread_pct:
        raise Unusable(f"{symbol}: spread {spread_pct:.1%} > {max_spread_pct:.0%}")

    if dte <= 0:
        raise Unusable(f"{symbol}: 0DTE — Alpaca returns no Greeks")

    g = (snap or {}).get("greeks") or {}
    missing = [k for k in ("delta", "gamma", "theta", "vega") if g.get(k) is None]
    if missing:
        raise Unusable(f"{symbol}: missing Greeks {missing} (likely deep OTM / non-convergent IV)")

    iv = (snap or {}).get("impliedVolatility")
    if iv is None or not (0.01 < iv < 5.0):
        raise Unusable(f"{symbol}: implausible IV {iv!r}")

    return ContractView(symbol, bid, ask, mid, spread_pct,
                        g["delta"], g["gamma"], g["theta"], g["vega"], iv, dte)
```

**Rule: a missing Greek is a REJECT, not a zero.** A `None` delta coerced to `0.0` reads as "no directional exposure" — which is the most dangerous possible wrong answer for a risk system.

## 5. Using the Greeks in strategy logic

### Strike selection by delta (the standard approach)
| Structure | Typical short-leg delta | Rationale |
|---|---|---|
| Credit spread short leg | 0.15 – 0.30 | ~70–85% probability OTM at expiry |
| Iron condor short legs | 0.10 – 0.20 each | ~80–90% per side |
| Debit spread long leg | 0.45 – 0.60 | near-ATM, best gamma-per-dollar |
| Debit spread short leg | 0.20 – 0.30 | caps cost, defines width |

Delta ≈ probability of finishing ITM (a rough but useful approximation for short-dated options).

```python
def pick_short_leg(chain_views, target_delta=0.20, kind="P"):
    cands = [v for v in chain_views if v.symbol[-9] == kind]
    return min(cands, key=lambda v: abs(abs(v.delta) - target_delta))
```

### Theta — your friend on credit, your enemy on debit
`theta` is per-day P&L decay. On a **5-day competition**:
- A credit spread with theta +$8/day earns ~$40 over the window if the underlying cooperates.
- A long option with theta −$25/day bleeds ~$125 over the window even if the underlying is flat.

➡️ **In a 5-day window with no time to be right slowly, theta is the dominant term for long options.** This pushes toward defined-risk *credit* structures or *short-dated directional* structures with a fast thesis — not "buy a call and wait".

### Vega — your IV exposure
`vega` is P&L per 1 vol-point move in IV. Long options are long vega (want IV up); credit spreads are short vega (want IV down). If you enter when IV is elevated and it mean-reverts, short-vega structures gain independently of direction.

### Gamma — how fast delta changes
High gamma near expiry = your delta flips fast = position risk is non-linear. Combined with "0DTE has no Greeks", the practical rule is: **stay at DTE ≥ 1, ideally 2–7, for anything delta-based.**

### IV Rank / IV Percentile
Alpaca gives you **current IV**, not IV rank. Compute rank yourself from option history (available since **Feb 2024**):
```python
def iv_rank(iv_now, iv_history):
    lo, hi = min(iv_history), max(iv_history)
    return 0.0 if hi == lo else (iv_now - lo) / (hi - lo)

def iv_percentile(iv_now, iv_history):
    return sum(1 for x in iv_history if x < iv_now) / len(iv_history)
```
Rule of thumb: **IV rank > 0.5 → prefer selling premium (credit spreads, condors). IV rank < 0.3 → prefer buying premium (debit spreads).**

Since your window is 5 days and option history starts Feb 2024, build the IV history from **daily ATM IV of the ~30-day expiry** over the last 60–120 trading days. Cache it in SQLite on Day 1 so you're not recomputing it every cycle.

### Expected move — the cleanest condor-width rule
```python
import math
def expected_move(spot, iv, dte_days):
    """1-sigma expected move over dte_days, from annualized IV."""
    return spot * iv * math.sqrt(dte_days / 365.0)

# place short strikes ~1.0-1.5 sigma out, long strikes 1 strike further
```
Uses only spot + IV, both free, and works even where Greeks are missing.

## 6. What to show the judges

A live table in your demo showing, for the contracts your agent is looking at:
`symbol | dte | bid | ask | spread% | delta | theta | vega | IV | IV-rank | open_interest | gate result`

...with rejected rows greyed out and the failing gate named. That single panel demonstrates:
- you're using Market Data API deeply (Greeks, IV, chain)
- you have real risk gates
- you understood the free-tier data limits

Cheap to build, and it directly serves three of the four judging criteria.
