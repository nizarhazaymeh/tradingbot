# 05 — Options Strategy Cookbook (Alpaca-feasible, with payloads)

Every strategy below is checked against Alpaca's real constraints: `mleg` max 4 legs, all legs covered within the order, no equity legs, GCD-1 ratios, `day` TIF, no extended hours, no brackets on options, indicative data feed, 0DTE has no Greeks.

Legend: **L** = required options level · **DR** = defined risk · ✅/❌ = mleg-able

---

## Tier 1 — Level 1 (income)

### 1.1 Covered call — L1, DR (capped upside)
Sell a call against 100 shares held.
```json
{"symbol":"AAPL231201C00195000","qty":"2","side":"sell","type":"limit",
 "limit_price":"1.05","time_in_force":"day","position_intent":"sell_to_open"}
```
Requires **200 shares** for 2 contracts. ❌ Cannot be one mleg (no equity legs) — buy shares first, then sell the call.
- **Window fit:** poor. Needs capital tied up in shares; 5 days of theta on one call is a tiny P&L.
- **Verdict:** skip as a primary strategy; fine as a demo of Level 1 capability.

### 1.2 Cash-secured put — L1
```json
{"symbol":"AAPL231201P00175000","qty":"1","side":"sell","type":"market",
 "time_in_force":"day","position_intent":"sell_to_open"}
```
Requires `strike × 100 × qty` = **$17,500** for one $175 put.
- 🔴 **Sizing killer.** One SPY $640 CSP = **$64,000** = 64% of your account on one position. Cannot be risk-managed on $100k.
- **Verdict:** ❌ not viable as a core strategy. Use small-priced underlyings only if you want it for demonstration.

---

## Tier 2 — Level 2 (directional, single-leg)

### 2.1 Long call / long put — L2
```json
{"symbol":"SPY260904C00650000","qty":"1","side":"buy","type":"limit",
 "limit_price":"6.20","time_in_force":"day","position_intent":"buy_to_open"}
```
Cost = `premium × 100 × qty`.
- **Pros:** simplest, unlimited upside, tiny capital, easy to explain.
- **Cons:** 🔴 **theta bleeds you** — a −$25/day theta loses $125 over the window even if you're right on direction but slow. Long vega means an IV crush kills you.
- **Window fit:** only with a *fast* thesis (news catalyst, 1–3 day horizon).
- **Verdict:** ✅ good as the "high-conviction catalyst" sleeve, sized small (≤0.5% of account each).

---

## Tier 3 — Level 3 / `mleg` (the differentiators)

### 3.1 Bull call spread (debit) — L3, DR ✅
Buy lower strike, sell higher strike, same expiry. Bullish.
```json
{"order_class":"mleg","qty":"1","type":"limit","limit_price":"1.00","time_in_force":"day",
 "legs":[
  {"symbol":"AAPL250117C00190000","ratio_qty":"1","side":"buy","position_intent":"buy_to_open"},
  {"symbol":"AAPL250117C00210000","ratio_qty":"1","side":"sell","position_intent":"sell_to_open"}]}
```
| | |
|---|---|
| Max loss | net debit × 100 × qty |
| Max gain | (width − debit) × 100 × qty |
| Breakeven | long strike + debit |
| Greeks | +delta, −theta (less than a naked long), ~vega-neutral |
| Best when | directional view, IV moderate/low |

### 3.2 Bear put spread (debit) — L3, DR ✅
Buy higher strike put, sell lower strike put. Bearish. Mirror of 3.1.
```json
{"order_class":"mleg","qty":"1","type":"limit","limit_price":"1.25","time_in_force":"day",
 "legs":[
  {"symbol":"AAPL250117P00210000","ratio_qty":"1","side":"buy","position_intent":"buy_to_open"},
  {"symbol":"AAPL250117P00190000","ratio_qty":"1","side":"sell","position_intent":"sell_to_open"}]}
```

### 3.3 Bull put spread (credit) — L3, DR ✅
Sell higher-strike put, buy lower-strike put. Mildly bullish / neutral. **Collects premium.**
```json
{"order_class":"mleg","qty":"1","type":"limit","limit_price":"-1.35","time_in_force":"day",
 "legs":[
  {"symbol":"SPY260904P00640000","ratio_qty":"1","side":"sell","position_intent":"sell_to_open"},
  {"symbol":"SPY260904P00635000","ratio_qty":"1","side":"buy","position_intent":"buy_to_open"}]}
```
🔴 Note the **negative** `limit_price` = credit. Verify the sign on DEV first (`02_multileg_mleg_orders.md` §4).

| | |
|---|---|
| Max gain | net credit × 100 × qty |
| Max loss | (width − credit) × 100 × qty |
| Breakeven | short strike − credit |
| Greeks | +delta (small), **+theta**, −vega |
| Best when | **IV rank high**, underlying above support, neutral-to-up |

### 3.4 Bear call spread (credit) — L3, DR ✅
Sell lower-strike call, buy higher-strike call. Mildly bearish / neutral.
```json
{"order_class":"mleg","qty":"1","type":"limit","limit_price":"-1.20","time_in_force":"day",
 "legs":[
  {"symbol":"SPY260904C00660000","ratio_qty":"1","side":"sell","position_intent":"sell_to_open"},
  {"symbol":"SPY260904C00665000","ratio_qty":"1","side":"buy","position_intent":"buy_to_open"}]}
```

### 3.5 Iron condor — L3, DR, 4 legs ✅ ⭐
Bull put spread + bear call spread. **Profits from the underlying staying in a range.**
```json
{"order_class":"mleg","qty":"1","type":"limit","limit_price":"-1.80","time_in_force":"day",
 "legs":[
  {"symbol":"SPY260904P00635000","ratio_qty":"1","side":"buy","position_intent":"buy_to_open"},
  {"symbol":"SPY260904P00640000","ratio_qty":"1","side":"sell","position_intent":"sell_to_open"},
  {"symbol":"SPY260904C00660000","ratio_qty":"1","side":"sell","position_intent":"sell_to_open"},
  {"symbol":"SPY260904C00665000","ratio_qty":"1","side":"buy","position_intent":"buy_to_open"}]}
```
| | |
|---|---|
| Max gain | net credit × 100 × qty |
| Max loss | (widest wing width − credit) × 100 × qty |
| Greeks | ~delta-neutral, **+theta (strong)**, −vega, −gamma |
| Best when | **IV rank high**, no catalyst, range-bound expectation |
| Legs | exactly 4 = **Alpaca's maximum**. |

**Construction rule using only free data:**
```python
import math
def build_condor(spot, atm_iv, dte, chain, *, sigma_mult=1.25, wing_width=5):
    em = spot * atm_iv * math.sqrt(dte / 365.0)     # 1-sigma expected move
    short_put  = round_to_strike(spot - sigma_mult * em)
    short_call = round_to_strike(spot + sigma_mult * em)
    return dict(long_put   = short_put  - wing_width,
                short_put  = short_put,
                short_call = short_call,
                long_call  = short_call + wing_width)
```
⚠️ The far wings are the contracts most likely to have **`null` Greeks** (deep OTM, non-convergent IV). Handle `None`.

### 3.6 Iron butterfly — L3, DR, 4 legs ✅
Short straddle at ATM + long wings. Higher credit, narrower profit zone than a condor. Same 4-leg shape; short put and short call at the **same** strike.

### 3.7 Long strangle / straddle — L3, DR (debit) ✅
Buy a call and a put. Both legs long → nothing to cover → **passes R2**.
```json
{"order_class":"mleg","qty":"1","type":"limit","limit_price":"0.60","time_in_force":"day",
 "legs":[
  {"symbol":"AAPL250117P00200000","ratio_qty":"1","side":"buy","position_intent":"buy_to_open"},
  {"symbol":"AAPL250117C00250000","ratio_qty":"1","side":"buy","position_intent":"buy_to_open"}]}
```
(This is Alpaca's own example payload from the mleg docs.)
- Profits from a large move in **either** direction; loses to time and IV crush.
- **Window fit:** good for a *known binary catalyst* inside the window. Bad otherwise — double theta.

### 3.8 Roll a spread — L3, 4 legs ✅
Close and reopen atomically. Two variants documented by Alpaca: roll strikes, roll expiration. See `02_multileg_mleg_orders.md` §5.

**This is a great demo moment**: "when the short strike is threatened, the agent *rolls* the spread out and up in a single atomic order rather than legging out." One API call, visibly sophisticated.

---

## Tier 4 — NOT possible on Alpaca (know these so you don't waste a day)

| Strategy | Blocked by |
|---|---|
| **Short straddle / strangle** (naked) | R2 — both legs uncovered inside the mleg. *(Could be done as two separate single-leg orders if your level allows, but Level 3 as documented covers debit spreads; naked shorts are not in the level table.)* |
| **Calendar spread** | R2 — Alpaca states explicitly that rolling a calendar spread involves uncovered short legs |
| **Diagonal spread** | Same as calendar |
| **Ratio / backspread (1×2)** | R2 (two shorts) + R4 (GCD) |
| **Covered call as one order** | R3 — no equity legs |
| **Collar as one order** | R3 — needs an equity leg |
| **Jade lizard, broken-wing variants** | ⚠️ likely R2 coverage failures — test if you want them |
| **Anything with 5+ legs** | `maxItems: 4` |
| **Crypto options** | Alpaca has no crypto options |
| **0DTE delta-based selection** | No Greeks on 0DTE |

---

## Strategy selection matrix for THIS competition

Scored against the actual constraints: 5.2 trading days, $100k, indicative options data, no brackets, defined risk mandatory.

| Strategy | Capital eff. | Theta | 5-day fit | Data needs | mleg | Score |
|---|---|---|---|---|---|---|
| **Iron condor (IV-rank gated)** | ★★★★★ | +++ | ★★★★★ | IV, spot, chain | ✅ 4 legs | **A+** |
| **Credit vertical (put/call)** | ★★★★★ | ++ | ★★★★★ | IV, delta, trend | ✅ | **A+** |
| **Debit vertical (directional)** | ★★★★ | − | ★★★★ | trend, delta | ✅ | **A** |
| **Roll-on-threat management** | — | — | ★★★★★ | position + chain | ✅ | **A** (as a *behaviour*) |
| Long call/put on catalyst | ★★★★ | −−− | ★★★ | news, IV | n/a | **B+** |
| Long strangle on binary event | ★★★ | −−− | ★★ | event calendar | ✅ | **B** |
| Covered call | ★ | + | ★ | — | ❌ | **C** |
| Cash-secured put | ✗ | + | ✗ | — | n/a | **D** (unsizeable) |
| 0DTE anything | ★★ | ±±± | ★ | no Greeks | — | **D** (data-blocked) |

### 🏆 Recommended core: a **regime-gated premium-selling book with a directional sleeve**

```
IV rank of the underlying  →  which structure the agent picks
────────────────────────────────────────────────────────────
IV rank > 0.60 & no catalyst & range-bound  →  IRON CONDOR       (delta-neutral, +theta)
IV rank > 0.50 & mild directional lean      →  CREDIT VERTICAL   (that side)
IV rank < 0.35 & strong directional signal  →  DEBIT VERTICAL    (cheap premium)
Strong catalyst < 3 days, high conviction   →  LONG OPTION       (small size)
Short strike threatened (delta > 0.40)      →  ROLL the spread
Position at +50% of max gain                →  CLOSE early
Position at −150% of credit received        →  CLOSE (stop)
DTE == 0                                    →  CLOSE by 14:00 ET, market by 15:30 ET
```

This single table is:
- **Testable** (the challenge asks for "a clear, testable trading strategy")
- **Explainable in 30 seconds** (lablab's demo rule)
- **Uses the most advanced Alpaca order class** (4-leg mleg)
- **Uses free data only** (chain + Greeks + IV, all Basic-tier)
- **Defined-risk on every position** (survivable drawdown)
- **Positive theta on the majority of the book** — which is the right sign for a 5-day window

➡️ Sizing, risk gates and the full decision loop: `../08_strategy_playbook/03_pnl_strategy_and_risk_gates.md`

---

## Exit management (mandatory — no brackets on options)

Because `bracket`/`oco`/`oto` are equities-only, every exit is your code's job:

| Exit trigger | Threshold | Action |
|---|---|---|
| Profit target | +50% of max gain (credit) / +75% of max gain (debit) | close via mirrored mleg with `*_to_close` intents |
| Stop | −150% of credit received / −60% of debit paid | close |
| Delta breach | short leg \|delta\| > 0.40 | **roll** out/away, or close |
| Time stop | DTE == 1 | close regardless of P&L |
| Expiry day | 14:00 ET → limit; 15:30 ET → market | force close |
| IV collapse | IV rank drops below 0.25 while short vega | take profit early |
| Portfolio drawdown halt | daily −2% / total −6% | `DELETE /v2/orders` + flatten + `suspend_trade: true` |

Persist the intended thresholds per position, and rebuild them on restart — see `../03_trading_api/04_rate_limits_and_resilience.md` §5.

---

## Underlying selection

Prefer **high-liquidity index ETFs and mega-caps** — the indicative feed is least distorted where real OPRA volume is largest, and open interest is deep:

**Tier A (start here):** SPY, QQQ, IWM
**Tier B:** AAPL, MSFT, NVDA, AMZN, META, GOOGL, TSLA, AMD
**Tier C (only with liquidity checks):** anything from `most-actives` ∩ `options_enabled`

Liquidity gates (all free):
```
contract.tradable == True
contract.open_interest >= 500          # from /v2/options/contracts
(ask - bid) / mid <= 0.15              # from the chain
greeks is not None                     # implies a real two-sided market
qty <= 0.05 * open_interest            # don't pretend to be the whole market
no corporate action inside the option's life
```

SPY/QQQ/IWM have **Mon/Wed/Fri** expirations — giving you expiries on **Aug 28, Aug 31, Sep 2, Sep 4** inside the competition window. That's four distinct short-dated cycles in 5 trading days, which is what makes a theta strategy actually generate a track record in that time. ⚠️ Confirm the available expiries from `/v2/options/contracts`, don't assume.
