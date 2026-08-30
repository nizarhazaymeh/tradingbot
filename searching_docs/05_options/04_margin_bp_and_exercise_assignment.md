# 04 — Margin, Buying Power, Exercise & Assignment

Sources: `options-level-3-trading.md` (margin section), `options-trading.md`, `margin-and-short-selling.md`, `non-trade-activities-for-option-events.md`, `the-intraday-margin-rule.md`

## 1. Buying power fields

| Field on `/v2/account` | Meaning |
|---|---|
| `buying_power` | General buying power (margin-inclusive) |
| **`options_buying_power`** | 🔴 **The field options orders are validated against.** Read this one. |
| `cash` | Cash balance |
| `equity` | Total account value |
| `initial_margin` / `maintenance_margin` | Currently required margin |
| `multiplier` | 1 (cash) / 2 (Reg-T overnight) / 4 (intraday) |

## 2. Per-strategy buying power requirements

| Strategy | Requirement | Example |
|---|---|---|
| Buy call/put | `premium × 100 × qty` | $5.10 call → **$510** |
| Sell cash-secured put | `strike × 100 × qty` | $175 strike → **$17,500** |
| Sell covered call | **hold `100 × qty` shares** | 2 contracts → 200 shares |
| Debit spread (mleg) | ≈ net debit × 100 × qty (see cost basis below) | $1.00 debit → ~$100 |
| Credit spread (mleg) | universal-spread-rule margin + net price | $5-wide → ~$500 − credit |

## 3. 🔴 The "Universal Spread Rule" — Alpaca's margin model for multi-leg

Alpaca does **not** sum per-spread margins. It computes the **theoretical maximum loss of the whole portfolio**, per expiration.

Verbatim algorithm:
> 1. **Ignore Premiums** — "When calculating maintenance margin, do not factor in the premiums paid or received. Instead, focus on the intrinsic (exercise) payoffs."
> 2. **Model Each Option's Payoff** — "Each option is represented by a piecewise linear payoff function (PnL) based on the underlying price (p)."
> 3. **Combine Positions** — "To determine total payoff, sum the piecewise functions for all open positions."
> 4. **Find Theoretical Maximum Loss** — "Maintenance margin is based on the worst-case scenario for the portfolio… you determine the underlying price p that yields the lowest (most negative) net payoff. **The absolute value of this lowest point is the margin requirement.**"
> 5. **Different Expirations** — "For option positions with multiple expiration dates, calculate this theoretical maximum-loss approach separately for each expiration date, then use the **largest** resulting requirement across all expirations."

### Alpaca's worked example — why this is generous to you

Positions:
- Long AAPL call, strike 100
- Short AAPL call, strike 110
- Long AAPL call, strike 200
- Short AAPL call, strike 190

**Traditional (per-spread) method:**
- Spread 1 (credit): long 200C / short 190C → margin = `strike_diff × multiplier` = `10 × 100` = **$1,000**
- Spread 2 (debit): long 100C / short 110C → margin = **$0** (long strike below short)
- **Total = $1,000**

**Universal spread rule:** combining all four and evaluating the net piecewise payoff, the losses from one spread offset the other → net theoretical max loss = 0 →
- **Total = $0**

> "This 'universal spread rule' or piecewise-payoff approach better reflects the true risk when these positions are considered together. By recognizing how the different calls offset one another's exposures, the required margin is lower—benefiting the customer."

References cited by Alpaca: [CBOE Margin Manual](https://cdn.cboe.com/resources/membership/Margin_Manual.pdf), [SR-CBOE-2012-043](https://cdn.cboe.com/resources/regulation/rule_filings/margin_requirements/SR-CBOE-2012-043.pdf).

### 🔴 Why this matters for your strategy design
Portfolio-level margin netting means **offsetting structures on the same underlying and same expiry cost you almost nothing in margin.** Practical consequences:

1. You can hold **more defined-risk positions** on $100k than a naive per-spread calculation suggests.
2. **Same-expiry hedging is cheap.** If you're short a put spread and want to neutralize, adding an offsetting structure at the same expiry may *reduce* your margin requirement.
3. But: margin is computed **per expiration, taking the largest**. So spreading across many expirations does *not* net — it means your requirement is set by your single worst expiry. **Concentrating in one or two expiries is margin-efficient; scattering across five is not.**

➡️ **Actionable rule for the competition: pick ONE primary expiry per week and build the whole book at that expiry.** Margin-efficient, easier to reason about, easier to explain, and easier to flatten before the deadline.

## 4. Cost basis of an mleg order

> "The cost basis of a multi-leg (MLeg) order is the sum of: (1) the **maintenance margin** required for the combined positions (as determined by the universal spread rule), and (2) the **net price** (debit/credit) from buying or selling the option contracts."

Worked example (AAPL call credit spread: long 200C, short 190C):
| Component | Value |
|---|---|
| Maintenance margin (universal spread rule) | $1,000 |
| Long call premium paid | $10 |
| Short call premium received | $15 |
| Net price | **$5 credit** → treated as **−$5** for cost basis |
| × 100 multiplier | −$500 |
| **Cost basis charged** | **$1,000 − $500 = $500** |

So a $10-wide credit spread collecting $5 costs you $500 of buying power. Sizing follows directly:
```
max_loss_per_spread = (strike_width - net_credit) × 100
contracts = floor(risk_budget_dollars / max_loss_per_spread)
```

## 5. Exercise

**Endpoint:** `POST /v2/positions/{symbol_or_contract_id}/exercise` — **no body**.

Rules (verbatim):
> - "Contract holders may submit exercise instructions to Alpaca. Alpaca will process instructions and work with our clearing partner accordingly."
> - "**All available held shares of this option contract will be exercised.**" (all-or-nothing per contract symbol)
> - "By default, Alpaca will automatically exercise **in-the-money (ITM)** contracts at expiry."
> - "Exercise requests will be processed **immediately** once received."
> - 🔴 "**Exercise requests submitted between market close and midnight will be rejected**" — to avoid confusion about settlement timing.

CLI: `alpaca option exercise --symbol-or-id AAPL250620C00200000`

## 6. Expiration — the auto-exercise trap

> - "In the event no instruction is provided on an ITM contract, the Alpaca system will **exercise the contract as long as it is ITM by at least $0.01 USD**."
> - "Alpaca Operations has tooling and processes in place to identify accounts which pose a buying power risk with ITM contracts."
> - 🔴 "In the event the account does not have sufficient buying power to exercise an ITM position, **Alpaca will sell-out the position within 1 hour before expiry**."

### Why this is dangerous on a $100k account
Auto-exercise converts each ITM long call into **100 long shares**. On SPY around $650:
- 1 ITM call → $65,000 of stock
- 2 ITM calls → $130,000 — **more than your entire account**

Result: Alpaca liquidates within the hour before expiry, at whatever price the market offers, and your carefully-computed P&L becomes whatever the forced sell-out produced. Not a disaster, but not *your* decision either.

Short ITM options are worse: you get **assigned** and end up short 100 shares per contract (or long, for puts), with the associated margin.

### 🔴 The rule for your risk layer
```python
CLOSE_BY_ET      = time(14, 0)   # start closing at 14:00 ET on expiry day
ESCALATE_BY_ET   = time(15, 30)  # switch to market orders at 15:30 ET

def expiry_day_policy(position, now_et):
    if position.dte > 0:
        return None
    if now_et >= ESCALATE_BY_ET:
        return CloseOrder(position, order_type="market", reason="expiry-escalation")
    if now_et >= CLOSE_BY_ET:
        return CloseOrder(position, order_type="limit",
                          limit=marketable_limit(position), reason="expiry-close")
    return None
```
**Never let a position expire during the competition.** Write this as an explicit gate, unit-test it, and name it in the write-up. It's exactly the sort of operational detail Alpaca's Trading API team lead will appreciate.

## 7. Do Not Exercise (DNE)

> "To submit a Do-not-exercise (DNE) instruction, please **contact our support team**."

There is a reference endpoint (`POST .../dne`, `optiondonotexercise`) and a CLI command (`alpaca option do-not-exercise --symbol-or-id <contract>`), but the Trading API guide directs you to support. Don't build a strategy that depends on DNE.

## 8. Assignment

- **American style** → short options can be assigned **any time** before expiration.
- Early assignment risk spikes: deep ITM shorts, and short calls the day before an **ex-dividend** date (the holder exercises to capture the dividend).
- 🔴 "**Options assignments are not delivered through websocket events.** To check for assignment activity (non-trade activity, or NTA events), you'll need to **poll the REST API endpoints.** Websocket support for NTAs is not currently available."
- 🔴 On **paper**, NTAs sync at the **start of the following day** — balance and positions update instantly, but the activity record is delayed.

**Agent implication:** poll `/v2/account/activities` every ~5 minutes, and additionally detect assignment by watching for **unexpected equity positions** appearing in `/v2/positions`. That's the fast signal; the NTA is the audit trail.

Mitigation: avoid short options on underlyings with an ex-dividend date inside the position's life (use the corporate actions API — `../04_market_data/03_news_screeners_corporate_actions.md`).

## 9. Options NTA entry types

`non-trade-activities-for-option-events.md` — new NTA entry types for exercise, assignment, and expiry. **Schema unchanged**, so your existing activities parser works; you just need to handle the new `activity_type` values. Recent changelog entries also mention new identifier fields on options activity events (`2026-08-24-options-activity`).

## 10. Margin rules and PDT

- `margin-and-short-selling.md` — up to 4× intraday / 2× overnight buying power on margin accounts.
- `the-intraday-margin-rule.md`, `understanding-the-new-intraday-margin-rule.md`, `understanding-finras-new-intraday-margin-rule-and-the-end-of-pdt.md` — FINRA's newer intraday margin rule for non-leverage margin accounts and the end of PDT.
- With **$100,000** equity you are well above the $25,000 PDT threshold, so PDT is not a practical constraint here. Still read and log `daytrade_count` + `pattern_day_trader` from `/v2/account` — one line of code, and it shows diligence.
- `dtbp_check` and `pdt_check` are configurable in `/v2/account/configurations`.

## 11. Regulatory fees

`regulatory-fees.md` — options carry per-contract regulatory fees (ORF, OCC clearing, SEC/TAF on sells) on **live** accounts. **Paper does not simulate regulatory fees** (nor dividends). So paper P&L is slightly optimistic relative to live. State this in the write-up: it's an easy, honest credibility point that most entrants will miss.

Rough live cost for scale: ~$0.02–$0.15 per contract per side. A 4-leg iron condor = 8 contract-sides ≈ $0.50–$1.20 round trip per condor. Immaterial at your size, but knowing the number is what separates a trader from a coder.
