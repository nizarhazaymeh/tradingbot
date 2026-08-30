# 02 — Multi-leg (`mleg`) Orders: the complete guide

**This is your Technology Implementation differentiator.** Source: https://docs.alpaca.markets/us/docs/options-level-3-trading (+ `postorder` OpenAPI schema)
Raw: `../09_raw_sources/alpaca_docs_md/options-level-3-trading.md`

## 1. What an mleg order is

> "A multi-leg (MLeg) order is a single, combined order that includes multiple option contracts – calls, puts, or even shares—on the same underlying security. By bundling all legs together, the trade is executed as a single unit and each leg is associated with its own strike price, expiration date, or position type (long or short)."

> "MLeg orders are particularly useful because they allow traders to execute complex options or stock combinations in one streamlined process, avoiding the delay or slippage risk of placing each transaction separately. By handling multiple legs at once, traders gain better control over their target price, reduce the chance of partial fills that could distort the intended strategy, and simplify trade management."

Alpaca's own example: an iron condor placed as one mleg order "ensures they fill together or not at all. This reduces the risk of partial fills, which could otherwise leave the trader with unwanted market exposure or unbalanced positions."

## 2. The request shape

```json
{
  "order_class": "mleg",
  "qty": "1",
  "type": "limit",
  "limit_price": "0.6",
  "time_in_force": "day",
  "legs": [
    {"symbol":"AAPL250117P00200000","ratio_qty":"1","side":"buy","position_intent":"buy_to_open"},
    {"symbol":"AAPL250117C00250000","ratio_qty":"1","side":"buy","position_intent":"buy_to_open"}
  ]
}
```

| Field | Rule |
|---|---|
| `order_class` | must be `"mleg"` |
| `qty` | **Required.** "represents the number of units to trade of this strategy" — i.e. how many condors/spreads. |
| `type` | `market` or `limit` |
| `time_in_force` | `day` |
| `limit_price` | 🔴 **positive = DEBIT, negative = CREDIT** |
| `side` | **Omit at the top level.** Each leg carries its own side. |
| `legs[]` | **max 4 items** (`maxItems: 4`) |
| `legs[].symbol` | required, OCC option symbol |
| `legs[].ratio_qty` | required, "proportional quantity of this leg in relation to the overall multi-leg order qty" |
| `legs[].side` | `buy` / `sell` |
| `legs[].position_intent` | `buy_to_open` / `sell_to_open` / `buy_to_close` / `sell_to_close` |

## 3. 🔴 The five restrictions that will get your orders rejected

### R1 — Max 4 legs
`maxItems: 4` in the schema. Iron condors (4 legs) are the maximum complexity. No 6-leg butterflies-of-butterflies.

### R2 — Every leg must be COVERED WITHIN THE SAME mleg order
> "Starting on day zero of Options Level 3 trading, an MLeg order is accepted only if **all its legs are covered within the same MLeg order**. For example, an MLeg order containing **two short call legs would be rejected**, though submitting those short calls separately as single-leg orders is allowed. This restriction also impacts certain strategies, including **rolling a short contract or rolling a calendar spread**, since they would involve uncovered short legs within the same multi-leg order."

**What this rules out:**
- ❌ Two short calls in one mleg (e.g. a ratio spread 1×2)
- ❌ Naked short legs of any kind inside an mleg
- ❌ **Calendar spreads** (short near-dated + long far-dated — the short isn't covered by a same-expiry long)
- ❌ Rolling a naked short as one order

**What still works:**
- ✅ Vertical debit spreads (long + short, same expiry, long is protective)
- ✅ Vertical credit spreads (short + long, same expiry — long covers the short)
- ✅ Iron condors (put credit spread + call credit spread, each internally covered)
- ✅ Iron butterflies
- ✅ Straddles/strangles **long only** (both legs long = nothing to cover)
- ✅ Rolling a **spread** (Alpaca's own example — the closing legs are covered)

### R3 — No equity leg
> "MLeg orders that include an **equity leg are not supported at this time.** This means that combining an equity position with an options contract in a single order is not currently available for any trading strategy."

❌ No covered call as one mleg (buy 100 shares + sell 1 call). Do it as two separate orders.

### R4 — `ratio_qty` must be in simplest form (GCD = 1)
> "each leg's `leg_ratio` must be in its simplest form. In other words, the **greatest common divisor (GCD) among the `leg_ratio` values for the legs must be 1**."
> Wrong: Leg 1 `ratio = 4`, Leg 2 `ratio = 2` → "the system will reject this order. If a ratio must be 2:4, the user should enter it as 1:2 instead."

Rationale given: the parent `qty` already carries the scale; unsimplified ratios duplicate that information.

**Validate before submitting:**
```python
from math import gcd
from functools import reduce
def valid_ratios(ratios):
    return reduce(gcd, ratios) == 1
assert valid_ratios([1,1])      # ✅
assert valid_ratios([1,2])      # ✅
assert not valid_ratios([2,4])  # ❌ rejected — send [1,2] with double qty
```

### R5 — `stop` / `stop_limit` are single-leg only
Multileg supports `market` and `limit` only. No stop orders on an mleg. Combined with **no brackets on options**, this means **all mleg exits are managed by your agent**.

## 4. 🔴🔴 The debit/credit sign convention — the #1 bug you will hit

From the `postorder` OpenAPI schema, `limit_price`:
> "Required if type is `limit` or `stop_limit`. **In case of `mleg`, the `limit_price` parameter is expressed with the following notation:**
> - **A positive value indicates a DEBIT, representing a cost or payment to be made.**
> - **A negative value signifies a CREDIT, reflecting an amount to be received.**"

| Strategy | Net cash | Correct `limit_price` |
|---|---|---|
| Long call spread (debit) | you pay $1.00 | `"1.00"` |
| Long put spread (debit) | you pay $1.25 | `"1.25"` |
| **Call credit spread** | you receive $1.20 | **`"-1.20"`** |
| **Put credit spread** | you receive $1.35 | **`"-1.35"`** |
| **Iron condor** | you receive $1.80 | **`"-1.80"`** |
| Long strangle (debit) | you pay $0.60 | `"0.60"` |

⚠️ **Alpaca's own iron-condor example in the docs shows `"limit_price": "1.80"` (positive)** while an iron condor built from those legs (buy 190P, sell 195P, sell 205C, buy 210C) is a **credit** structure. Either the example is illustrative-only or the leg ordering implies something different.

**Do not guess. Verify on your DEV account on Day 1:**
```bash
# submit ONE credit spread with a clearly-negative limit_price and inspect the result
cat > /tmp/test_credit.json <<'JSON'
{"order_class":"mleg","qty":"1","type":"limit","limit_price":"-1.00","time_in_force":"day",
 "legs":[{"symbol":"<SHORT_CALL>","ratio_qty":"1","side":"sell","position_intent":"sell_to_open"},
         {"symbol":"<LONG_CALL_HIGHER_STRIKE>","ratio_qty":"1","side":"buy","position_intent":"buy_to_open"}]}
JSON
alpaca api POST /v2/orders < /tmp/test_credit.json
# then: did it accept? what does the filled order report? did cash INCREASE?
alpaca account get --jq '{cash, equity, options_buying_power}'
```
Record the answer in your repo as `docs/mleg_sign_convention.md`. **This single experiment is worth more than a day of guessing** — and documenting it is itself a Technology Implementation point.

## 5. Verified payload library

### Long call spread (debit) — Alpaca's own example
Buy lower-strike 190 call, sell higher-strike 210 call:
```json
{
  "order_class": "mleg", "qty": "1", "type": "limit",
  "limit_price": "1.00", "time_in_force": "day",
  "legs": [
    {"symbol":"AAPL250117C00190000","ratio_qty":"1","side":"buy","position_intent":"buy_to_open"},
    {"symbol":"AAPL250117C00210000","ratio_qty":"1","side":"sell","position_intent":"sell_to_open"}
  ]
}
```

### Long put spread (debit)
Buy higher-strike 210 put, sell lower-strike 190 put:
```json
{
  "order_class": "mleg", "qty": "1", "type": "limit",
  "limit_price": "1.25", "time_in_force": "day",
  "legs": [
    {"symbol":"AAPL250117P00210000","ratio_qty":"1","side":"buy","position_intent":"buy_to_open"},
    {"symbol":"AAPL250117P00190000","ratio_qty":"1","side":"sell","position_intent":"sell_to_open"}
  ]
}
```

### Iron condor (4 legs)
Put spread + call spread, betting on limited movement:
```json
{
  "order_class": "mleg", "qty": "1", "type": "limit",
  "limit_price": "1.80", "time_in_force": "day",
  "legs": [
    {"symbol":"AAPL250117P00190000","ratio_qty":"1","side":"buy","position_intent":"buy_to_open"},
    {"symbol":"AAPL250117P00195000","ratio_qty":"1","side":"sell","position_intent":"sell_to_open"},
    {"symbol":"AAPL250117C00205000","ratio_qty":"1","side":"sell","position_intent":"sell_to_open"},
    {"symbol":"AAPL250117C00210000","ratio_qty":"1","side":"buy","position_intent":"buy_to_open"}
  ]
}
```
(Verify the sign — see §4.)

### Roll a call spread — change strikes, one atomic order
```json
{
  "order_class": "mleg", "qty": "1", "type": "limit",
  "limit_price": "2.05", "time_in_force": "day",
  "legs": [
    {"symbol":"AAPL250117C00200000","ratio_qty":"1","side":"buy","position_intent":"buy_to_close"},
    {"symbol":"AAPL250117C00205000","ratio_qty":"1","side":"sell","position_intent":"sell_to_close"},
    {"symbol":"AAPL250117C00210000","ratio_qty":"1","side":"sell","position_intent":"sell_to_open"},
    {"symbol":"AAPL250117C00215000","ratio_qty":"1","side":"buy","position_intent":"buy_to_open"}
  ]
}
```

### Roll a call spread — change expiration
Close the `250117` legs, open `250124`:
```json
{
  "order_class": "mleg", "qty": "1", "type": "limit",
  "limit_price": "2.05", "time_in_force": "day",
  "legs": [
    {"symbol":"AAPL250117C00200000","ratio_qty":"1","side":"buy","position_intent":"buy_to_close"},
    {"symbol":"AAPL250117C00205000","ratio_qty":"1","side":"sell","position_intent":"sell_to_close"},
    {"symbol":"AAPL250124C00200000","ratio_qty":"1","side":"sell","position_intent":"sell_to_open"},
    {"symbol":"AAPL250124C00205000","ratio_qty":"1","side":"buy","position_intent":"buy_to_open"}
  ]
}
```

### Closing an mleg position (mirror the intents)
```json
{
  "order_class": "mleg", "qty": "1", "type": "limit",
  "limit_price": "1.80", "time_in_force": "day",
  "legs": [
    {"symbol":"AAPL250117C00190000","ratio_qty":"1","side":"sell","position_intent":"sell_to_close"},
    {"symbol":"AAPL250117C00210000","ratio_qty":"1","side":"buy","position_intent":"buy_to_close"}
  ]
}
```

## 6. Submitting mleg from each surface

### cURL
```bash
curl -X POST "$APIDOMAIN/v2/orders" \
  -H 'accept: application/json' -H 'content-type: application/json' \
  -H "Apca-Api-Key-Id: $APIKEY" -H "Apca-Api-Secret-Key: $SECRET" \
  -d @spread.json | jq -r
```

> ✅ **VERIFIED 2026-08-30 on CLI v0.0.14:** `alpaca order submit` **DOES** support multi-leg natively.
> Real flags present: `--legs string` ("list of order legs (<= 4)"), `--order-class string`,
> `--position-intent string`, `--client-order-id`, `--dry-run`.
> The help text confirms `--symbol` and `--side` are "Required for all order classes **except for mleg**".
> So you can use **either**:
> ```bash
> alpaca order submit --order-class mleg --qty 1 --type limit --limit-price -1.35 \
>   --time-in-force day --legs '<json array of legs>' --client-order-id "$(uuidgen)" --dry-run
> ```
> **or** the raw path `alpaca api POST /v2/orders < spread.json` (safer for complex payloads —
> no shell quoting of nested JSON). Use `--dry-run` first to see the exact request body the CLI builds.

### Alpaca CLI — 🔴 no named mleg command; use the raw API escape hatch
The CLI's `alpaca order submit` is generated from the OpenAPI spec, and the docs list `order_class` values `simple, mleg` for options — but there is **no documented `--legs` flag**. Use:
```bash
alpaca api POST /v2/orders < spread.json
```
Check whether your build supports it directly:
```bash
alpaca order submit --help | grep -iE 'leg|order-class'
alpaca --help-all | grep -iE 'mleg|leg'
```
**Either way this is a good thing for your submission** — "we drive multi-leg orders through `alpaca api POST /v2/orders`" is a legitimate, documented CLI usage that satisfies the CLI requirement while doing the most advanced order type on the platform.

### alpaca-py
```python
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import LimitOrderRequest, OptionLegRequest
from alpaca.trading.enums import OrderSide, TimeInForce, OrderClass, PositionIntent

tc = TradingClient(KEY, SECRET, paper=True)
order = tc.submit_order(LimitOrderRequest(
    qty=1, limit_price=1.00, time_in_force=TimeInForce.DAY,
    order_class=OrderClass.MLEG,
    legs=[
        OptionLegRequest(symbol="SPY260904C00650000", ratio_qty=1,
                         side=OrderSide.BUY,  position_intent=PositionIntent.BUY_TO_OPEN),
        OptionLegRequest(symbol="SPY260904C00655000", ratio_qty=1,
                         side=OrderSide.SELL, position_intent=PositionIntent.SELL_TO_OPEN),
    ],
))
```

### MCP server
Tool: **`place_option_order`** — "Options (single-leg or multi-leg)". Example prompt from Alpaca's docs:
> "Place a bull call spread using AAPL June 6th options: one with a 190.00 strike and the other with a 200.00 strike."
> "Place a bull call spread with SPY July 3rd options: sell one 5% above and buy one 3% below the current SPY price."

## 7. Pre-submit validator — copy this into your agent

```python
from math import gcd
from functools import reduce

def validate_mleg(payload: dict) -> list[str]:
    errs = []
    legs = payload.get("legs") or []

    if payload.get("order_class") != "mleg":
        errs.append("order_class must be 'mleg'")
    if not (2 <= len(legs) <= 4):
        errs.append(f"mleg needs 2-4 legs, got {len(legs)} (maxItems=4)")
    if "side" in payload:
        errs.append("do not set top-level 'side' on an mleg order")
    if not payload.get("qty"):
        errs.append("qty is required for mleg (number of strategy units)")
    if payload.get("time_in_force") != "day":
        errs.append("use time_in_force='day' for options")
    if payload.get("type") not in ("market", "limit"):
        errs.append("mleg supports only market|limit (no stop/stop_limit)")
    if payload.get("extended_hours"):
        errs.append("options do not support extended_hours")
    if payload.get("notional"):
        errs.append("notional must not be set for options")

    # R4: ratio GCD must be 1
    ratios = [int(l["ratio_qty"]) for l in legs if l.get("ratio_qty")]
    if ratios and reduce(gcd, ratios) != 1:
        errs.append(f"ratio_qty GCD must be 1, got {ratios} — simplify")

    # R3: no equity legs
    for l in legs:
        s = l.get("symbol", "")
        if len(s) < 15 or not (s[-9] in "CP"):
            errs.append(f"leg {s!r} does not look like an OCC option symbol (no equity legs allowed)")

    # R2: every short leg must be covered by a long leg of the same type & expiry
    def parse(sym):
        # ROOT + YYMMDD + C/P + 8-digit strike
        strike = int(sym[-8:]) / 1000
        kind   = sym[-9]
        expiry = sym[-15:-9]
        root   = sym[:-15]
        return root, expiry, kind, strike

    shorts = [parse(l["symbol"]) for l in legs if l.get("side") == "sell"]
    longs  = [parse(l["symbol"]) for l in legs if l.get("side") == "buy"]
    for root, exp, kind, k in shorts:
        covered = any(
            lr == root and le == exp and lk == kind and
            ((kind == "C" and lk_strike > k) or (kind == "P" and lk_strike < k))
            for lr, le, lk, lk_strike in longs
        )
        if not covered:
            errs.append(
                f"short leg {root}{exp}{kind}{k} is UNCOVERED within this mleg "
                f"— Alpaca rejects uncovered legs (no calendars, no ratio spreads)"
            )

    # position_intent present on every leg
    for l in legs:
        if l.get("position_intent") not in (
                "buy_to_open", "sell_to_open", "buy_to_close", "sell_to_close"):
            errs.append(f"leg {l.get('symbol')} missing/invalid position_intent")

    return errs
```
(Unit-test this. It's exactly the kind of "risk gate as deterministic, tested code" the write-up asks for.)

## 8. Cost basis of an mleg order

> "The **cost basis** of a multi-leg (MLeg) order is the **sum of**: (1) the **maintenance margin** required for the combined positions (as determined by the universal spread rule), and (2) the **net price** (debit/credit) from buying or selling the option contracts."

Worked example from the docs — AAPL call credit spread (long 200C, short 190C):
- Maintenance margin (universal spread rule): **$1,000**
- Long call premium paid: $10 → −$10
- Short call premium received: $15 → +$15
- Net price = +$5 **credit** → for cost-basis purposes it becomes **−$5**
- ×100 multiplier → −$500
- **Cost basis = $1,000 + (−$5 × 100) = $500**

So the amount charged to the customer for that mleg is **$500**.

➡️ Margin mechanics in detail: `04_margin_bp_and_exercise_assignment.md`.

## 9. Strategy feasibility under the mleg restrictions

| Strategy | Legs | mleg-able? | Why |
|---|---|---|---|
| Long call / put | 1 | n/a (simple) | ✅ |
| Bull call spread (debit) | 2 | ✅ | long lower strike covers short higher |
| Bear put spread (debit) | 2 | ✅ | long higher strike covers short lower |
| Bear call spread (credit) | 2 | ✅ | long higher strike covers short lower |
| Bull put spread (credit) | 2 | ✅ | long lower strike covers short higher |
| **Iron condor** | 4 | ✅ | both wings internally covered |
| **Iron butterfly** | 4 | ✅ | same |
| Long straddle / strangle | 2 | ✅ | both legs long, nothing to cover |
| **Short straddle / strangle** | 2 | ❌ | both legs naked → uncovered (R2) |
| **Calendar spread** | 2 | ❌ | short near-dated not covered by long far-dated (R2, stated explicitly) |
| **Ratio / backspread (1×2)** | 2 | ❌ | two short legs, and GCD issues (R2 + R4) |
| **Covered call as one order** | 2 | ❌ | equity leg not allowed (R3) |
| Butterfly (1-2-1) | 3 | ⚠️ | the 2 short middles must be covered by both wings — test it |
| Broken-wing condor | 4 | ⚠️ | test; asymmetric wings may fail the coverage check |

➡️ **Design conclusion: verticals and iron condors/butterflies are your mleg playground.** That's plenty — they're the structures that map cleanly onto a directional/neutral view, and they're all defined-risk, which your $100k account and your drawdown gates both want. See `05_strategy_cookbook.md`.
