# 02 — Positions, Account, Portfolio History & Activities

Sources: `working-with-positions.md`, `working-with-account.md`, `account-activities.md`, `non-trade-activities-for-option-events.md`, `position-average-entry-price-calculation.md`, plus references.

## 1. Positions endpoints

| Method | Path | Purpose | Ref |
|---|---|---|---|
| GET | `/v2/positions` | All open positions | `getallopenpositions` |
| GET | `/v2/positions/{symbol_or_asset_id}` | One position | `getopenposition-1` |
| DELETE | `/v2/positions` | **Close ALL positions** (liquidate) | `deleteallopenpositions-1` |
| DELETE | `/v2/positions/{symbol_or_asset_id}` | Close one position (`?qty=` or `?percentage=`) | `deleteopenposition-1` |
| POST | `/v2/positions/{symbol_or_contract_id}/exercise` | **Exercise an option** (no body) | `optionexercise` |
| POST | `/v2/positions/{symbol_or_contract_id}/dne` | Do-Not-Exercise | `optiondonotexercise` |

> "The existing Positions API model will work with options contracts. There is not expected to be a change to this model." — `options-trading.md`

Each option **leg** of an `mleg` order becomes its own position, keyed by its OCC symbol.

### Fields you care about
`symbol`, `asset_class` (`us_option`), `qty`, `side` (`long`/`short`), `avg_entry_price`, `market_value`, `cost_basis`, `unrealized_pl`, `unrealized_plpc`, `unrealized_intraday_pl`, `current_price`, `lastday_price`, `change_today`, `qty_available`.

Note `asset_class` — filter on `us_option` to separate your options book from any equity hedge.

### Average entry price
`position-average-entry-price-calculation.md` documents how `avg_entry_price` is derived. Relevant when you scale into a position: the reported average is Alpaca's, and your own P&L math should use it rather than recomputing from fills, so your numbers match what the judges see.

## 2. Account & portfolio history

| Method | Path | Purpose |
|---|---|---|
| GET | `/v2/account` | Balances, buying power, options level |
| GET | `/v2/account/configurations` | Trading config |
| PATCH | `/v2/account/configurations` | Update config (incl. `suspend_trade` kill switch) |
| GET | `/v2/account/portfolio/history` | **Equity curve** |
| GET | `/v2/account/activities` | All activities |
| GET | `/v2/account/activities/{activity_type}` | Filtered activities |

### 🔴 `portfolio_history` is your P&L slide
`getaccountportfoliohistory-1` returns time-series arrays: `timestamp[]`, `equity[]`, `profit_loss[]`, `profit_loss_pct[]`, `base_value`, `timeframe`.

Params: `period` (e.g. `1W`, `1M`), `timeframe` (`1Min`, `5Min`, `15Min`, `1H`, `1D`), `date_start`, `date_end`, `extended_hours`, `intraday_reporting`, `pnl_reset`.

```bash
alpaca account portfolio --period 1W --timeframe 15Min > docs/equity_curve.json
```
Then plot it for the demo and the slides. This is the single most persuasive artifact you can produce for the P&L criterion, because it comes straight from Alpaca and the judges can reproduce it from your account ID.

**Do this every day of the competition** and commit the JSON — it also proves your agent was trading continuously, not just on the last day.

## 3. Account activities — including options events

`account-activities.md`: "provides access to a historical record of transaction activities that have impacted your account."

Two families:
- **TAs (trade activities)** — `FILL` etc. The existing FILL schema applies to options unchanged.
- **NTAs (non-trade activities)** — including new options-specific entry types for **exercise, assignment, and expiry** (`non-trade-activities-for-option-events.md`). Schema unchanged, new entry types.

### 🔴 Two paper-environment gotchas
1. > "On PAPER **NTAs are synced at the start of the following day**. While your balance and positions are updated instantly, NTAs on PAPER will be visible in the Activities endpoint only the next day."
2. > "Options assignments are **not** delivered through websocket events. To check for assignment activity (NTA events), you'll need to **poll the REST API** endpoints. Websocket support for NTAs is not currently available."

**Consequences:**
- Never rely on NTAs for same-day reporting. Use `positions` + `portfolio_history`.
- Your agent must **poll** activities to notice assignment; there is no push.
- Anything expiring on **Sep 4** will have no activity record before the 15:00 UTC deadline. Close it, don't expire it.

## 4. Exercise, assignment, expiry (the rules)

From `options-trading.md`:

**Exercise**
- `POST /v2/positions/{symbol_or_contract_id}/exercise`, no body.
- **All available held shares of that contract are exercised** — it's all-or-nothing per contract symbol.
- Processed immediately once received.
- **Requests submitted between market close and midnight are rejected** (to avoid settlement-date confusion).

**Expiration**
- With no instruction, Alpaca **auto-exercises ITM contracts ITM by ≥ $0.01**.
- Alpaca Ops monitors accounts that pose a buying-power risk from ITM contracts.
- **If the account lacks buying power to exercise an ITM position, Alpaca will sell out the position within 1 hour before expiry.**

**Do Not Exercise**
- To submit DNE, **contact Alpaca support** (there is a `POST .../dne` reference endpoint, but the guide says contact support for Trading API).

**Assignment**
- Short options can be assigned; American-style can be assigned any time before expiration.
- Not pushed over websocket — poll.

### Agent implication
Auto-exercise of ITM longs converts an option position into **100 shares per contract**, consuming huge buying power and completely changing your risk profile. On a $100k account, auto-exercising 10 ITM SPY calls at strike 650 would need $650,000 — Alpaca would instead sell them out within the hour before expiry.

**Rule for your risk layer: close every option position before expiry.** Concretely:
```
if days_to_expiry == 0 and position is open:
    submit closing order at 14:00 ET at the latest
if days_to_expiry == 0 and unfilled by 15:30 ET:
    escalate: market order to close
```
Document this as an explicit risk gate. It is exactly the kind of operational detail the Alpaca judges will recognize.

## 5. Assets, and identifying option-enabled underlyings

`GET /v2/assets` supports an `attributes` query param. Symbols that have option contracts carry the attribute **`options_enabled`**.

> "Querying for symbols with the `options_enabled` attribute allows users to identify the universe of symbols with corresponding option contracts."

```bash
alpaca asset list --asset-class us_equity --status active --attributes options_enabled
```
This is the correct way to build your tradable universe rather than hardcoding tickers.

Also check per-asset: `tradable`, `fractionable`, `shortable`, `easy_to_borrow`, `marginable`, `exchange`.

## 6. Watchlists — persist your universe server-side

| Method | Path |
|---|---|
| GET/POST | `/v2/watchlists` |
| GET/PUT/DELETE | `/v2/watchlists/{id}` |
| POST/DELETE | `/v2/watchlists/{id}` (add/remove asset) |
| by name | `/v2/watchlists:by_name?name=` |

```bash
alpaca watchlist create --name "agent-universe" --symbols SPY,QQQ,IWM,AAPL,NVDA
```
Cheap way to show Trading API breadth, and it makes your universe inspectable by a judge with your account ID.

## 7. Margin, buying power and the intraday margin rule

- `margin-and-short-selling.md` — up to 4× intraday / 2× overnight buying power on margin accounts; short selling requires margin + locatable shares.
- `options_buying_power` is a **separate field** from `buying_power`. Options orders are validated against it.
- `the-intraday-margin-rule.md`, `understanding-the-new-intraday-margin-rule.md`, `understanding-finras-new-intraday-margin-rule-and-the-end-of-pdt.md` — FINRA's newer intraday margin rule and the end of PDT for non-leverage margin accounts.
- With a **$100,000** account you are far above the $25,000 PDT threshold, so pattern-day-trader restrictions are not a practical constraint for this competition. Still read `daytrade_count` and `pattern_day_trader` from `/v2/account` and log them — it costs one line and demonstrates diligence.
- For multi-leg options, maintenance margin uses the **universal spread rule** (worst-case piecewise payoff), which is *more* favourable than summing per-spread requirements. Details in `../05_options/04_margin_bp_and_exercise_assignment.md`.

## 8. Regulatory fees
`regulatory-fees.md` — options carry per-contract regulatory fees on **live**. Paper does **not** simulate regulatory fees. So your paper P&L is slightly optimistic vs live. Mention this in the write-up; it's an easy credibility point.
