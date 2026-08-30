# 01 — Options on Alpaca: fundamentals, levels, symbology, enablement

Sources: `options-trading.md`, `options-trading-overview.md`, `options-orders.md`, `options-level-3-trading.md`, `non-trade-activities-for-option-events.md`
Options FAQ: https://alpaca.markets/support/tag/options
OpenAPI: https://docs.alpaca.markets/reference

## 1. Enablement — paper is easy

> "In the **Paper** environment, options trading capability will be **enabled by default** — there's nothing you need to do!"
> "*Note, in production there will be a more robust experience to request options trading.*"

To disable: Trading Dashboard → Account → Configure.

The Trading Account model exposes `options_approved_level` and `options_trading_level`; Account Configuration exposes `max_options_trading_level` and lets you **downgrade** to a lower level (a different API handles upgrade requests on live accounts).

**Day 1 verification:**
```bash
alpaca account get --jq '{options_approved_level, options_trading_level}'
alpaca account config get
```

## 2. Trading levels

| Level | Supported trades | Validation |
|---|---|---|
| **0** | Options disabled | — |
| **1** | Sell a covered call · Sell a cash-secured put | Must own sufficient underlying shares · Must have sufficient options buying power |
| **2** | Level 1 **+** Buy a call · Buy a put | Sufficient options buying power |
| **3** | Levels 1–2 **+** Buy a call spread · Buy a put spread | Sufficient options buying power |

Multi-leg (`mleg`) trading is documented under **"Options Level 3 Trading"**. Note the Level 3 description names *debit* spreads ("buy a call spread", "buy a put spread"), and the mleg restrictions (§next page) require all legs covered within the order — which is consistent: **defined-risk spreads yes, naked shorts within an mleg no.**

⚠️ **Do not assume you have Level 3.** Read `options_approved_level` on Day 1 and design for what the account actually reports. If it's Level 2, your strategy is long calls/puts + Level 1 income trades, not condors. This is a 5-minute check that could save you 2 days.

## 3. Finding option-enabled underlyings

`GET /v2/assets` has an `attributes` query param. Symbols with option contracts have the attribute **`options_enabled`**.

> "Querying for symbols with the `options_enabled` attribute allows users to identify the universe of symbols with corresponding option contracts."

```bash
alpaca asset list --asset-class us_equity --status active --attributes options_enabled
```

## 4. Fetching contracts

`GET /v2/options/contracts?underlying_symbols=SPY`
`GET /v2/options/contracts/{symbol_or_id}`

🔴 **Defaults:** `expiration_date_lte` = **next weekend**, `limit` = **100**.
> "if `/v2/options/contracts` is called on Thursday, the response will include Thursday and Friday data. If called on a Saturday, the response will include Saturday, Sunday, Monday, Tuesday, Wednesday, Thursday, and Friday."

Always pass expiry bounds explicitly if you want anything beyond this week.

Response fields (each contract): `id`, `symbol`, `name`, `status`, `tradable`, `expiration_date`, `root_symbol`, `underlying_symbol`, `underlying_asset_id`, `type` (call/put), `style` (`american`), `strike_price`, `size` (100), **`open_interest`**, `open_interest_date`, `close_price`, `close_price_date`. Paginated via `page_token`.

**`open_interest` is free here** — this is the Trading API, not the metered market-data API. Use it as your primary liquidity filter.

```bash
alpaca option contracts --underlying-symbol SPY \
  --expiration-date-gte 2026-09-04 --expiration-date-lte 2026-09-11 \
  --type put --strike-price-gte 600 --strike-price-lte 660 --limit 500
```

## 5. OCC symbology

```
ROOT + YYMMDD + C|P + strike×1000 zero-padded to 8
```
| Contract | Symbol |
|---|---|
| AAPL 17 Jan 2025 $190 Call | `AAPL250117C00190000` |
| SPY 4 Sep 2026 $650 Call | `SPY260904C00650000` |
| SPY 4 Sep 2026 $637.50 Put | `SPY260904P00637500` |
| NVDA 19 Sep 2025 $168 Call | `NVDA250919C00168000` |

```python
def occ(root, expiry, kind, strike):
    return f"{root.upper()}{expiry:%y%m%d}{kind.upper()[0]}{int(round(strike*1000)):08d}"
```
⚠️ Use `round()`, not `int()` — `637.5*1000` can evaluate to `637499.999...`.

Prefer using the `symbol` returned by `/v2/options/contracts` over hand-building.

## 6. Contract mechanics

- **1 contract = 100 shares** of the underlying (`size: "100"`).
- **Style: `american`** — exercisable any time before expiration. So **short options carry early-assignment risk**, especially around ex-dividend dates and deep ITM.
- Expirations: weekly, monthly, and quarterly for major symbols. SPY/QQQ/IWM have **Mon/Wed/Fri** expirations.

## 7. Buying power math (memorize these)

| Trade | Buying power required |
|---|---|
| Buy a call/put | `premium × 100 × contracts` |
| Sell a cash-secured put | `strike × 100 × contracts` |
| Sell a covered call | must **hold `100 × contracts` shares** |
| Debit spread (mleg) | net debit × 100 × qty (roughly; see cost basis below) |
| Credit spread (mleg) | maintenance margin from the **universal spread rule** + net price |

From `options-orders.md`:
- Buy a call executed at $5.10 → needs **$510** buying power.
- Buy a put executed at $1.04 → needs **$104**.
- Sell a $175-strike cash-secured put, 1 contract → needs **$17,500**.
- Sell 2 covered calls → needs **200 shares** of the underlying held.

🔴 **Options orders are validated against `options_buying_power`, a separate field from `buying_power`.** Read it, don't assume.

### Sizing sanity check for a $100k account
| Strategy | Notional per unit | How many units fit in 2% risk ($2,000)? |
|---|---|---|
| Long 1 ATM SPY weekly call @ ~$6 | $600 | ~3 contracts |
| Cash-secured put, SPY $640 strike | **$64,000** | **less than 1** — a single CSP eats 64% of the account |
| $5-wide credit spread | ~$500 max loss | ~4 spreads |
| $5-wide iron condor | ~$400 max loss (after credit) | ~5 condors |

➡️ **Cash-secured puts on an index ETF are essentially un-sizeable on $100k.** This alone rules out the naive "sell CSPs for income" plan and pushes you toward **defined-risk spreads**, which are also where the interesting `mleg` technology lives. Two constraints pointing the same way.

## 8. Placing orders — the constraints

Options use the **same** `POST /v2/orders` endpoint. Validations:
- `qty` must be a **whole number**
- `notional` must **not** be populated
- `time_in_force` must be `day` or `gtc` (spec says `day` only — **use `day`**)
- `extended_hours` must be `false` or absent — **options have no extended hours**
- `type` must be `market`, `limit`, `stop`, or `stop_limit` — **`stop`/`stop_limit` are single-leg only** (spec says options are market/limit only; treat stops as verify-empirically)
- `order_class` must be `simple` or `mleg`
- 🔴 **`bracket`/`oco`/`oto` are equities-only — you cannot attach TP/SL to an options order**

## 9. Positions, activities, exercise, expiry

- The existing **Positions API** model works for options unchanged. Each mleg leg is its own position.
- The **FILL** trade-activity schema applies to options unchanged.
- New **NTA** entry types for **exercise, assignment, expiry** (`non-trade-activities-for-option-events.md`), same schema.
- 🔴 **Paper: NTAs sync at the start of the following day.** Balance/positions update instantly; the activity record appears tomorrow.
- 🔴 **Assignments are not delivered over websocket. Poll the REST activities endpoint.**

**Exercise:** `POST /v2/positions/{symbol_or_contract_id}/exercise`, no body. All held shares of that contract are exercised. Processed immediately. **Requests between market close and midnight are rejected.**

**Expiration:** Alpaca **auto-exercises ITM contracts ITM by ≥ $0.01**. If the account lacks buying power to exercise an ITM position, **Alpaca sells the position out within 1 hour before expiry**.

**DNE:** contact Alpaca support for Trading API.

➡️ Full treatment in `04_margin_bp_and_exercise_assignment.md`.

## 10. Feedback / spec links
- OpenAPI: https://docs.alpaca.markets/reference
- Options FAQ: https://alpaca.markets/support/tag/options
- Options API feedback form (linked from the docs): https://docs.google.com/forms/d/e/1FAIpQLScIYvKDJnKjXWESs6qxzpgk7pbvkt0IF1_nhv46t4o31-YOng/viewform
