# 03 — P&L Strategy & Risk Gates

The judging criterion is *"the project's P&L and **how effectively the strategy performs through its trading activity**."* Both halves matter. This page gives you a concrete, sized, gated strategy.

## 1. The strategy in one table

**Regime-gated defined-risk options book on liquid index ETFs and mega-caps.**

| Regime (deterministic classifier) | Structure | Direction | Typical DTE |
|---|---|---|---|
| IV rank > 0.60, range-bound, no catalyst | **Iron condor** (4-leg mleg) | delta-neutral | 2–7 |
| IV rank > 0.50, mild directional lean | **Credit vertical** on the favoured side | mildly directional | 2–7 |
| IV rank < 0.35, clear trend | **Debit vertical** in the trend direction | directional | 3–10 |
| Catalyst < 3 days, high conviction | **Long option** (small size) | directional | 1–5 |
| EVENT_RISK (earnings/corp action in window) | **no new positions** on that underlying | — | — |

### The classifier (no LLM)
```python
import math
from dataclasses import dataclass

@dataclass
class Regime:
    name: str
    iv_rank: float
    trend_z: float
    expected_move_pct: float
    reason: str

def classify(spot, atm_iv, iv_history, closes, dte, has_catalyst) -> Regime:
    # --- IV rank over the cached history (Feb 2024+) ---
    lo, hi = min(iv_history), max(iv_history)
    iv_rank = 0.5 if hi == lo else (atm_iv - lo) / (hi - lo)

    # --- trend: distance from SMA20, normalized by ATR-ish stdev ---
    sma20 = sum(closes[-20:]) / 20
    rets  = [closes[i] / closes[i-1] - 1 for i in range(1, len(closes))]
    sd    = (sum(r*r for r in rets[-20:]) / 20) ** 0.5
    trend_z = 0.0 if sd == 0 else (spot - sma20) / (sma20 * sd)

    em_pct = atm_iv * math.sqrt(dte / 365.0)
    trending = abs(trend_z) > 1.5

    if has_catalyst:
        return Regime("EVENT_RISK", iv_rank, trend_z, em_pct, "catalyst in window")
    if iv_rank > 0.60 and not trending:
        return Regime("HIGH_IV_RANGE", iv_rank, trend_z, em_pct,
                      f"iv_rank={iv_rank:.2f}, |trend_z|={abs(trend_z):.2f} < 1.5")
    if iv_rank > 0.50 and trending:
        return Regime("HIGH_IV_TREND", iv_rank, trend_z, em_pct, "elevated IV with trend")
    if iv_rank < 0.35 and trending:
        return Regime("LOW_IV_TREND", iv_rank, trend_z, em_pct, "cheap premium with trend")
    return Regime("LOW_IV_RANGE", iv_rank, trend_z, em_pct, "no edge — stand aside")
```
`LOW_IV_RANGE` → **do nothing**. An agent that knows when *not* to trade is a Creativity point, not a bug.

## 2. 🔴 Sizing — the maths that keeps you alive

Every position is **defined risk**, so sizing is just "how much max-loss am I willing to book".

```
ACCOUNT           = $100,000
RISK_PER_TRADE    = 0.40%  of equity  = $400 max loss
PORTFOLIO_HEAT    = 4.0%   of equity  = $4,000 total max loss across all open positions
MAX_PER_UNDERLYING= 1.2%   of equity  = $1,200
MAX_PER_EXPIRY    = 2.5%   of equity  = $2,500
MAX_CONCURRENT    = 10 positions
```

```python
import math

def size_position(equity, max_loss_per_unit, open_heat,
                  underlying_heat, expiry_heat, n_open):
    """Returns qty (0 = reject). max_loss_per_unit in dollars, e.g. (width - credit) * 100."""
    if n_open >= 10:
        return 0, "max concurrent positions (10)"
    if max_loss_per_unit <= 0:
        return 0, "undefined risk — reject"

    per_trade      = 0.0040 * equity            # $400
    heat_room      = 0.0400 * equity - open_heat
    underlying_room= 0.0120 * equity - underlying_heat
    expiry_room    = 0.0250 * equity - expiry_heat

    budget = min(per_trade, heat_room, underlying_room, expiry_room)
    if budget <= 0:
        return 0, "no risk budget remaining"

    qty = math.floor(budget / max_loss_per_unit)
    if qty < 1:
        return 0, f"position too large: max_loss {max_loss_per_unit} > budget {budget:.0f}"
    return qty, "ok"
```

### What this produces in practice
| Structure | Max loss/unit | Qty at $400 budget | Notional risk |
|---|---|---|---|
| $5-wide credit vertical, $1.35 credit | (5 − 1.35) × 100 = **$365** | 1 | $365 |
| $5-wide iron condor, $1.80 credit | (5 − 1.80) × 100 = **$320** | 1 | $320 |
| $10-wide credit vertical, $2.50 credit | **$750** | 0 → **rejected** | — |
| $2-wide debit vertical, $0.80 debit | **$80** | 5 | $400 |
| 1 long ATM SPY call @ $6.20 | **$620** | 0 → **rejected** | — |

⚠️ **Note what this does:** at 0.40%/trade a single long ATM index option is *too big*. That's correct — it forces you into spreads, which is where the interesting technology and the better theta profile are. If you want a long-option sleeve, use narrower/cheaper strikes or a separate smaller budget (e.g. 0.15% per catalyst trade).

**Fully deployed the book risks $4,000 = 4% of the account.** If every single position lost its maximum simultaneously — which for a delta-neutral condor book essentially cannot happen — you'd be down 4%. That's the shape of risk you want: bounded, explainable, and survivable.

## 3. 🔴 The complete risk gate stack

Run **in this order**. First failure rejects and is logged with the gate name.

```python
GATES = [
    # ── structural ──────────────────────────────────────────────
    "g_schema",            # proposal has every required field
    "g_mleg_valid",        # ≤4 legs, all shorts covered, GCD==1, no equity leg,
                           #   position_intent on every leg, day TIF, no extended_hours
    "g_sign_convention",   # credit structure ⇒ limit_price < 0; debit ⇒ > 0
    "g_structure_matches_view",  # neutral view ⇒ not a naked directional debit, etc.

    # ── market state ────────────────────────────────────────────
    "g_market_open",       # GET /v2/clock  is_open == true
    "g_not_near_close",    # no new positions after 15:30 ET
    "g_dte_bounds",        # 1 <= dte <= 10   (0DTE has NO Greeks — reject)
    "g_no_corporate_action",  # no split/div/merger inside the option's life

    # ── contract quality ───────────────────────────────────────
    "g_tradable",          # contract.tradable == true on every leg
    "g_open_interest",     # every leg open_interest >= 500
    "g_spread_width",      # every leg (ask-bid)/mid <= 0.15
    "g_greeks_present",    # delta/gamma/theta/vega not None on the short legs
    "g_iv_sane",           # 0.01 < IV < 5.0
    "g_qty_vs_oi",         # qty <= 5% of the thinnest leg's open interest

    # ── portfolio ───────────────────────────────────────────────
    "g_sizing",            # size_position() returns qty >= 1
    "g_concentration",     # per-underlying / per-expiry / per-direction caps
    "g_max_concurrent",    # <= 10 open positions
    "g_buying_power",      # cost basis <= 0.5 * options_buying_power
    "g_no_duplicate",      # not already holding this exact structure
    "g_net_delta",         # |portfolio net delta| <= 0.30 * equity/10000

    # ── circuit breakers ───────────────────────────────────────
    "g_daily_drawdown",    # today's P&L > -2% of equity
    "g_total_drawdown",    # equity > 94% of $100,000
    "g_order_rate",        # <= 12 orders per hour
    "g_kill_switch",       # manual/automatic halt not engaged
]
```

### Circuit breakers — the ones that save your submission
```python
DAILY_DD_LIMIT = 0.02     # -2% in a day
TOTAL_DD_LIMIT = 0.06     # -6% from the $100,000 start
STARTING_EQUITY = 100_000

def check_circuit_breakers(equity, last_equity, cli):
    """Returns (halted: bool, reason: str). Call at the TOP of every cycle."""
    daily = (equity - last_equity) / last_equity if last_equity else 0.0
    total = (equity - STARTING_EQUITY) / STARTING_EQUITY

    if daily <= -DAILY_DD_LIMIT:
        halt(cli, f"daily drawdown {daily:.2%} <= -{DAILY_DD_LIMIT:.0%}")
        return True, "daily_drawdown"
    if total <= -TOTAL_DD_LIMIT:
        halt(cli, f"total drawdown {total:.2%} <= -{TOTAL_DD_LIMIT:.0%}")
        return True, "total_drawdown"
    return False, ""

def halt(cli, reason):
    """1) stop new orders  2) cancel working orders  3) flatten  4) lock the account."""
    log_critical({"event": "CIRCUIT_BREAKER", "reason": reason})
    cli.run("order", "cancel-all")                                   # DELETE /v2/orders
    cli.run("position", "close-all")                                 # DELETE /v2/positions
    cli.api("PATCH", "/v2/account/configurations", {"suspend_trade": True})
    touch("./HALTED")                                                # loop refuses to start
```

🔴 **`suspend_trade: true` via `PATCH /v2/account/configurations` is a real, server-side kill switch.** Using Alpaca's own account configuration as your circuit breaker — rather than just a flag in your code — is a genuinely strong Technology Implementation detail, and it survives your process crashing.

## 4. Exit management (mandatory — options have no brackets)

```python
from datetime import time

def exit_decision(pos, snap, now_et, intent):
    """intent = the persisted TP/SL/time-stop for this position."""
    # 1) hard expiry-day policy — highest priority
    if pos.dte == 0:
        if now_et >= time(15, 30):
            return "CLOSE_MARKET", "expiry escalation 15:30 ET"
        if now_et >= time(14, 0):
            return "CLOSE_LIMIT", "expiry close 14:00 ET"

    pnl_pct = pos.unrealized_pl / abs(intent.max_gain) if intent.max_gain else 0.0

    # 2) profit target
    if intent.kind == "credit" and pnl_pct >= 0.50:
        return "CLOSE_LIMIT", "profit target: 50% of max gain"
    if intent.kind == "debit" and pnl_pct >= 0.75:
        return "CLOSE_LIMIT", "profit target: 75% of max gain"

    # 3) stop
    if intent.kind == "credit" and pos.unrealized_pl <= -1.5 * intent.credit_received:
        return "CLOSE_MARKET", "stop: -150% of credit"
    if intent.kind == "debit" and pnl_pct <= -0.60:
        return "CLOSE_MARKET", "stop: -60% of debit"

    # 4) delta breach on a short leg → ROLL (the sophisticated move)
    short_delta = max((abs(l.delta) for l in pos.short_legs if l.delta is not None),
                      default=0.0)
    if short_delta > 0.40:
        return "ROLL", f"short leg delta {short_delta:.2f} > 0.40"

    # 5) time stop
    if pos.dte <= intent.time_stop_dte:
        return "CLOSE_LIMIT", f"time stop at DTE {pos.dte}"

    # 6) IV collapse while short vega → take the win early
    if intent.kind == "credit" and snap.iv_rank < 0.25 and pos.unrealized_pl > 0:
        return "CLOSE_LIMIT", "IV collapsed; harvest early"

    return "HOLD", ""
```

**The ROLL branch is your differentiator.** When a short strike is threatened, roll the whole spread out/away in one atomic 4-leg `mleg` order (see `../05_options/02_multileg_mleg_orders.md` §5) rather than legging out. It's one API call, it's visibly sophisticated, and it makes a great 10-second demo clip.

## 5. Fill quality — how to actually get filled on options

Paper fills only when the order becomes marketable (`../02_alpaca_platform/03_paper_trading_environment.md` §4). Options spreads are wide. A limit at mid may never fill.

**Use a re-price ladder, not a single limit:**
```python
def price_ladder(mid, side, steps=4, aggression=0.25):
    """Walk from mid toward the far side of the spread in `steps` increments.
       side='debit'  → increase the price you'll pay
       side='credit' → decrease the credit you'll accept
    """
    sign = 1 if side == "debit" else -1
    return [round(mid + sign * aggression * i * abs(mid), 2) for i in range(steps + 1)]

# submit at ladder[0]; if unfilled after 45s, `alpaca order replace` at ladder[1]; etc.
# after the last step, cancel and log "no fill" — do NOT chase past the ladder.
```
Log every re-price. "We used a 4-step re-price ladder and filled 87% of intents within 3 minutes" is a concrete, credible operational metric for the slides.

## 6. Metrics to compute and report

From `GET /v2/account/portfolio_history` + your own trade ledger:

| Metric | Formula / source |
|---|---|
| **Total return** | `(final_equity − 100000) / 100000` |
| Realized P&L | sum of closed-trade P&L |
| Unrealized P&L | sum of `unrealized_pl` (should be ~0 if you flattened) |
| **Max drawdown** | `min(equity_t / running_max(equity) − 1)` |
| Trade count | closed positions |
| **Win rate** | wins / closed |
| Avg win / avg loss | — |
| **Expectancy** | `win_rate × avg_win − (1−win_rate) × avg_loss` |
| Profit factor | gross wins / gross losses |
| Sharpe (crude) | `mean(daily_ret) / std(daily_ret) × √252` — **label it as a 4-day estimate, not a real Sharpe** |
| Avg hold time | — |
| **Gates fired** | count per gate name from the audit log |
| **Proposal→execution funnel** | proposals / critic-passed / gate-passed / filled |
| Fill rate & avg re-prices | from the ladder log |
| Rate-limit headroom | min `X-RateLimit-Remaining` observed |

🔴 **The proposal→execution funnel is your best single slide.** Alpaca's own article reported "82 proposals submitted, 26 approved (32%)". Reproducing that funnel for options — and showing *which gate* rejected each one — proves the risk layer exists and works. It also inoculates you against the "did the LLM just place random trades?" question.

## 7. Honest reporting rules (do not skip these)

Put these in the write-up and the last slide:
- Paper trading is a simulation. It does **not** model market impact, information leakage, latency slippage, queue position, price improvement, **regulatory fees**, or **dividends**.
- Paper fills are matched against NBBO and **order size is not checked against available liquidity** — so real-world fills could be worse. *(Then say: "which is why we added an open-interest and spread-width liquidity gate.")*
- Options quotes on the free Basic plan come from the **indicative** feed, not real OPRA, and option trades are **15 minutes delayed**. *(Then say: "which is why our entries are timed off the underlying and our edge doesn't depend on quote precision.")*
- **4 trading days is not a statistically significant sample.** Say the number, then say what it does and doesn't prove.
- Greeks are Black-Scholes-derived, and Alpaca's contracts are American-style — so Greeks are approximations, especially for ITM puts and around ex-dividend dates.

Every one of these is a limitation that a judge from Alpaca **already knows about**. Naming them first converts each from a weakness into evidence that you read the documentation. Pretending they don't exist is the actual risk.

## 8. Tests to write (they're a scored artifact, not overhead)

```
tests/
├── test_mleg_validator.py       # 4-leg cap, uncovered shorts, GCD, equity legs, intents
├── test_sign_convention.py      # credit ⇒ negative limit_price
├── test_sizing.py               # budget caps, heat, per-underlying, per-expiry, rejects
├── test_circuit_breakers.py     # daily/total DD trigger and halt sequence
├── test_exit_decisions.py       # each branch: TP, stop, delta breach, time, expiry
├── test_greeks_defensive.py     # None Greeks ⇒ reject, never coerced to 0
├── test_liquidity_gates.py      # OI, spread%, qty-vs-OI
├── test_occ_symbology.py        # half-strikes, rounding, round-trip parse
├── test_regime_classifier.py    # each regime, and LOW_IV_RANGE ⇒ no trade
└── test_reconciliation.py       # orphan positions, orphan orders, missing intents
```
Ten test files, all cheap, all directly evidencing "risk gates" in the required write-up. `pytest` output in the video is a 5-second shot that buys real credibility.
