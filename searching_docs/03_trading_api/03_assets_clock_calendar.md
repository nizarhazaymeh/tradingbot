# 03 — Assets, Clock, Calendar & Market Hours

## 1. Clock — always check before acting

`GET /v2/clock` (`clock-1.md`, legacy `legacyclock.md`)

Returns: `timestamp`, `is_open`, `next_open`, `next_close`.

```bash
alpaca clock
```
```python
clock = trading_client.get_clock()
if not clock.is_open:
    log(f"market closed; next open {clock.next_open}")
```

**Alpaca's own anti-pattern list says:** *"NEVER assume market hours — always check the clock/calendar endpoint before submitting time-sensitive orders."*

Your agent's main loop should start with a clock check and short-circuit when closed. This also prevents your Streamlit demo from crashing when a judge opens it on a weekend.

## 2. Calendar — the authoritative trading-day list

`GET /v2/calendar?start=&end=` (`calendar-2.md`, legacy `legacycalendar.md`)

Returns per day: `date`, `open`, `close`, and session times. **This is where early closes and holidays live.** Do not hardcode a holiday list.

```bash
alpaca calendar --start 2026-08-28 --end 2026-09-08
```

Run this on Day 1 and commit the output as `docs/competition_calendar.json`. It's the ground truth for your window analysis (`../01_hackathon/04_registration_and_timeline.md`).

## 3. Market sessions

| Session | Window (ET) | Days | Requirement |
|---|---|---|---|
| Overnight | 20:00 – 04:00 | Sun–Fri | `extended_hours: true`, `limit` type, `day`/`gtc` TIF. Not all assets eligible — check the asset record. |
| Pre-market | 04:00 – 09:30 | Mon–Fri | same |
| **Regular** | **09:30 – 16:00** | Mon–Fri | — |
| After-hours | 16:00 – 20:00 | Mon–Fri | same |

🔴 **Options trade regular hours only (09:30–16:00 ET). Options do not support extended hours at all.**
Crypto is 24/7 with no extended-hours concept.

See `245-trading-for-trading-api.md` for the 24/5 equity session details.

## 4. Assets

| Method | Path | Ref |
|---|---|---|
| GET | `/v2/assets` | `get-v2-assets-1` |
| GET | `/v2/assets/{symbol_or_asset_id}` | `get-v2-assets-symbol_or_asset_id` |

Query params include `status`, `asset_class`, `exchange`, `attributes`.

Key attribute: **`options_enabled`** — identifies underlyings that have option contracts. Use it to build the universe.

Per-asset flags: `tradable`, `marginable`, `shortable`, `easy_to_borrow`, `fractionable`, `maintenance_margin_requirement`, `attributes[]`.

`GET /v2/assets/{symbol}` is the one place a **404** is legitimate (unknown symbol). On `POST /v2/orders`, an unrecognized symbol returns **422**, not 404.

## 5. Option contracts (the options equivalent of /assets)

| Method | Path | Ref |
|---|---|---|
| GET | `/v2/options/contracts?underlying_symbols=` | `get-options-contracts` |
| GET | `/v2/options/contracts/{symbol_or_id}` | `get-option-contract-symbol_or_id` |

🔴 **Defaults that will surprise you:**
> The default params are:
> - `expiration_date_lte`: **Next weekend**
> - `limit`: **100**

> "if `/v2/options/contracts` is called on Thursday, the response will include Thursday and Friday data. If called on a Saturday, the response will include Saturday, Sunday, Monday, Tuesday, Wednesday, Thursday, and Friday."

So **if you don't pass `expiration_date_gte`/`expiration_date_lte`, you only get contracts expiring by the coming weekend.** For anything beyond the current week, set the dates explicitly.

Filters available: `underlying_symbols`, `status`, `expiration_date`, `expiration_date_gte`, `expiration_date_lte`, `root_symbol`, `type` (call/put), `style`, `strike_price_gte`, `strike_price_lte`, `limit`, `page_token`, plus `ppind`.

### Response object
```json
{
  "id": "6e58f870-fe73-4583-81e4-b9a37892c36f",
  "symbol": "AAPL240119C00100000",
  "name": "AAPL Jan 19 2024 100 Call",
  "status": "active",
  "tradable": true,
  "expiration_date": "2024-01-19",
  "root_symbol": "AAPL",
  "underlying_symbol": "AAPL",
  "underlying_asset_id": "b0b6dd9d-8b9b-48a9-ba46-b9d54906e415",
  "type": "call",
  "style": "american",
  "strike_price": "100",
  "size": "100",
  "open_interest": "6168",
  "open_interest_date": "2024-01-12",
  "close_price": "85.81",
  "close_price_date": "2024-01-12"
}
```
Paginated via `page_token` / `limit`.

**`open_interest` is here and it's free** — use it as your liquidity gate (see `../02_alpaca_platform/03_paper_trading_environment.md` §4). `tradable` must be `true`.

```bash
alpaca option contracts --underlying-symbol SPY \
  --expiration-date-gte 2026-09-04 --expiration-date-lte 2026-09-18 \
  --type call --strike-price-gte 600 --strike-price-lte 700 --limit 200
```

## 6. Corporate actions — don't trade options through a split

| Endpoint | Ref |
|---|---|
| `GET /v1beta1/corporate-actions` (market data) | `corporateactions-1` |
| `GET /v2/corporate_actions/announcements` (trading, legacy) | `get-v2-corporate_actions-announcements-1` |

Types: cash dividends, stock dividends, splits, reverse splits, mergers, spin-offs, rights, name changes.

**Why an options agent cares:** a split or special dividend changes contract terms and strike adjustments; a merger can freeze or convert a contract. Add a pre-trade gate: *reject any underlying with a corporate action inside the option's remaining life.* One API call, big credibility.

```bash
alpaca data corporate-actions --symbols SPY,QQQ,AAPL --types forward_split,reverse_split,cash_dividend
```
