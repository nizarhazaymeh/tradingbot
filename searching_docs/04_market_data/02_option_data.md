# 02 — Option Market Data (the core data page)

Sources: `historical-option-data.md`, `real-time-option-data.md`, `about-market-data-api.md`, `market-data-faq.md`, references `option*.md`

## 1. Endpoints

| Endpoint | Path | Ref | Notes |
|---|---|---|---|
| **Option chain** | `/v1beta1/options/snapshots/{underlying_symbol}` | `optionchain` | 🔴 **The most valuable single call.** |
| Snapshots (by contract) | `/v1beta1/options/snapshots?symbols=` | `optionsnapshots` | |
| Historical bars | `/v1beta1/options/bars?symbols=` | `optionbars` | |
| Historical trades | `/v1beta1/options/trades?symbols=` | `optiontrades` | 15-min delayed on Basic |
| Latest trades | `/v1beta1/options/trades/latest?symbols=` | `optionlatesttrades` | |
| Latest quotes | `/v1beta1/options/quotes/latest?symbols=` | `optionlatestquotes` | |
| Condition codes | `/v1beta1/options/meta/conditions/{ticktype}` | `optionmetaconditions` | |
| Exchange codes | `/v1beta1/options/meta/exchanges` | `optionmetaexchanges` | |

Note the version: options market data is **`v1beta1`**, not `v2`.

## 2. 🔴 The option chain endpoint — use this, not N snapshot calls

> "The option chain endpoint provides the **latest trade, latest quote, and greeks** for each contract symbol of the underlying symbol."

One request → every strike and expiry for an underlying, each with quote, trade, Greeks, and IV.

```bash
alpaca data option chain --underlying-symbol SPY
```
```python
from alpaca.data.historical.option import OptionHistoricalDataClient
from alpaca.data.requests import OptionChainRequest

c = OptionHistoricalDataClient(KEY, SECRET)
chain = c.get_option_chain(OptionChainRequest(
    underlying_symbol="SPY",
    expiration_date_gte="2026-09-04",
    expiration_date_lte="2026-09-04",
    type="call",
    strike_price_gte=600, strike_price_lte=700,
))
```

**Filter server-side** (`expiration_date*`, `strike_price_gte/lte`, `type`, `root_symbol`, `feed`, `limit`, `page_token`, `updated_since`) — a full SPY chain is enormous. `updated_since` is useful for incremental polling.

### Response shape
```json
{
  "snapshots": {
    "AAPL250117C00190000": {
      "latestTrade": {"t":"...","p":5.10,"s":3,"x":"W","c":["I"]},
      "latestQuote": {"t":"...","bp":5.05,"bs":10,"ap":5.15,"as":8,"bx":"C","ax":"C"},
      "greeks": {"delta":0.5321,"gamma":0.0184,"theta":-0.0412,"vega":0.1103,"rho":0.0221},
      "impliedVolatility": 0.3372405712050441,
      "dailyBar": {...}, "minuteBar": {...}, "prevDailyBar": {...}
    }
  },
  "next_page_token": null
}
```

## 3. 🔴 Data sources: Indicative vs OPRA

| Source | What you get |
|---|---|
| **Indicative** (free / Basic) | "a free derivative of the original OPRA feed: **the quotes are not actual OPRA quotes, they're just indicative derivatives.** The trades are also derivatives and **they're delayed by 15 minutes**." |
| **OPRA** (Algo Trader Plus) | The real consolidated BBO of OPRA. Subscribed users only. |

Plus, on Basic: **"Historical data limitation: latest 15 minutes"** — historical options queries exclude the most recent 15 minutes.

### What to do about it
1. **Use quotes and Greeks (real-time-ish, derived), not trades (15-min delayed).**
2. **Time entries off the UNDERLYING**, which is real-time (IEX) — then read the option quote to price the structure.
3. **Never build an edge that depends on quote precision.** Wide spreads, multi-day holds, defined-risk structures.
4. **Do not connect to the `opra` websocket feed on Basic** — auth will fail. Use `indicative`.
5. **State this limitation in your write-up.** Explaining that you designed around an indicative feed is a *strong* Technology Implementation signal to Alpaca judges — it proves you read the docs.

## 4. Data availability

> "Currently we only offer historical option data **since February 2024**."

~2.5 years of option history. Enough for IV-rank computation and a modest backtest; not enough to claim statistical significance. Be honest about it.

## 5. 🔴 Greeks & Implied Volatility — how Alpaca computes them, and when they're missing

Alpaca computes Greeks **server-side using Black-Scholes**, specifically the [gopriceoptions](https://github.com/jasonmerecki/gopriceoptions) package. **Availability is not gated by data plan** — you get Greeks on the free Basic plan.

Greeks returned: `delta`, `gamma`, `theta`, `vega`, `rho`. Plus `impliedVolatility`.

### Required conditions — ALL must hold, or Greeks are absent
> - non-zero **bid & ask** price for the latest quote for the contract symbol
> - latest **(SIP) trade for the underlying** symbol
> - the contract **expiration is after today**
> - the calculated **implied volatility is valid**

### 🔴 Consequence 1: 0DTE contracts have NO Greeks
> "contracts with 0DTE (i.e., that expire on the current day) won't have Greeks. Why? The Black-Scholes model includes a factor with 'days to expiry' in the denominator. If that is 0, the result is division by 0 and is undefined."

**This kills any 0DTE strategy that needs delta.** If you want 0DTE exposure you must compute your own Greeks (feasible — you have IV from other expiries, spot, strike, and rate) or use a Greeks-free rule.

### 🔴 Consequence 2: deep OTM contracts often have no Greeks
> "Alpaca calculations have a maximum of **100 iterations**. If the calculated price does not converge with the actual option price in that time, then no implied volatility is calculated."
> "Deeply out-of-the-money (OTM) options are highly sensitive to tiny changes in price… As expiration approaches or an option gets deep OTM the option's sensitivity to volatility (Vega) approaches zero. This creates a mathematical divide-by-zero or flat-derivative scenario where numerical solvers fail to converge."

So the far wings of an iron condor may return `null` Greeks. Your code must handle `None`.

### 🔴 Consequence 3: a zero bid or zero ask kills the Greeks
Illiquid strikes with no bid return no Greeks. **This is actually a useful free liquidity filter:** "has Greeks" ≈ "has a two-sided quote".

### Defensive pattern
```python
def usable(snap) -> bool:
    q = snap.get("latestQuote") or {}
    bid, ask = q.get("bp") or 0, q.get("ap") or 0
    if bid <= 0 or ask <= 0:
        return False
    mid = (bid + ask) / 2
    if mid <= 0 or (ask - bid) / mid > 0.15:      # spread gate
        return False
    g = snap.get("greeks")
    if not g or g.get("delta") is None:            # 0DTE / non-convergent
        return False
    iv = snap.get("impliedVolatility")
    if iv is None or not (0.01 < iv < 5.0):        # sanity band
        return False
    return True
```
**Never** default a missing Greek to 0 — a missing delta silently becomes "no directional exposure" and your risk math is then wrong in the most dangerous direction.

## 6. Real-time option stream

```
wss://stream.data.alpaca.markets/v1beta1/{feed}       # feed = indicative | opra
wss://stream.data.sandbox.alpaca.markets/v1beta1/{feed}
```
> "Substitute `indicative` or `opra` for `{feed}` depending on your subscription. Any attempt to access a data feed not available for your subscription will result in an error during authentication."

🔴 **The option stream is msgpack-only:**
> "Unlike the stock and crypto stream, the option stream is only available in [msgpack](https://msgpack.org) format. The SDKs are using this format automatically."

So use `OptionDataStream` from `alpaca-py` rather than a hand-rolled JSON websocket client.

Subscription limit on Basic: **200 quotes**. That's ~200 contracts — enough for 4–5 underlyings' near-the-money strikes across two expiries. Budget it deliberately; don't subscribe to a whole chain.

Channels: `trades` (`t`), `quotes` (`q`), plus greeks/underlying channels where available.

## 7. OCC option symbology — how to build a contract symbol

```
AAPL  250117 C 00190000
│     │      │ │
│     │      │ └── strike × 1000, zero-padded to 8 digits
│     │      └──── C(all) or P(ut)
│     └─────────── expiry YYMMDD
└───────────────── root symbol, padded to 6 chars with spaces in the raw OCC form
                   (Alpaca uses the unpadded form)
```
Examples:
| Contract | Symbol |
|---|---|
| AAPL 17 Jan 2025 $190 Call | `AAPL250117C00190000` |
| SPY 4 Sep 2026 $650 Call | `SPY260904C00650000` |
| SPY 4 Sep 2026 $640 Put | `SPY260904P00640000` |
| TSLA 20 Jun 2025 $500 Put | `TSLA250620P00500000` |
| NVDA 19 Sep 2025 $168 Call | `NVDA250919C00168000` |

Builder:
```python
def occ(root: str, expiry: "datetime.date", kind: str, strike: float) -> str:
    return f"{root.upper()}{expiry:%y%m%d}{kind.upper()[0]}{int(round(strike*1000)):08d}"

occ("SPY", date(2026,9,4), "C", 650)    # 'SPY260904C00650000'
occ("SPY", date(2026,9,4), "P", 637.5)  # 'SPY260904P00637500'
```
⚠️ Half-strikes: 637.5 → `00637500`. Always `round(strike*1000)`, never truncate — floating point will bite you (`637.5*1000 = 637499.9999` in some paths).

**Better: don't build symbols by hand.** Query `/v2/options/contracts` and use the `symbol` it returns. Only hand-build when you need to look up a specific known strike.

## 8. Free-tier options data cheat sheet

| Want | Use | Free? |
|---|---|---|
| All strikes + quotes + Greeks + IV for an underlying | **option chain** (1 call) | ✅ |
| Greeks / IV for specific contracts | option snapshots | ✅ |
| Real-time-ish bid/ask | latest quotes (indicative) | ✅ |
| Actual prints | historical/latest trades | ✅ but **15-min delayed** |
| OHLCV per contract | option bars | ✅ (excl. last 15 min) |
| Open interest | **`/v2/options/contracts`** (Trading API, not market data) | ✅ |
| Real NBBO | OPRA feed | ❌ requires Algo Trader Plus |
| Greeks on 0DTE | — | ❌ compute yourself |
| Option history before Feb 2024 | — | ❌ doesn't exist |
