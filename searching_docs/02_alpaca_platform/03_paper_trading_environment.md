# 03 — The Paper Trading Environment (read this before creating the competition account)

Source: https://docs.alpaca.markets/us/docs/paper-trading
Raw: `../09_raw_sources/alpaca_docs_md/paper-trading.md`

## 1. What paper trading is

> Paper trading is a real-time simulation environment where you can test your code… Paper trading works the same way as live trading end to end — except the order is not routed to a live exchange. Instead, the system simulates the order filling based on the real-time quotes.

Anyone globally can create a **Paper Only Account** with just an email address. Free, no card.

## 2. 🔴 CREATING THE COMPETITION ACCOUNT — exact steps

The hackathon requires a **brand-new** paper account with **exactly $100,000**. Here is the critical mechanic:

> Your initial paper trading account is created with **$100k balance as a default setting**.

> **You cannot change the account balance after it is created, unless you reset it.**

> We've updated the dashboard to allow you to **create and delete** paper accounts, rather than resetting them.
> To create a new paper account, click the **paper account number in the upper left corner** of the dashboard and select **"Open New Paper Account."**
> To delete an existing paper account, click the paper account number in the upper left corner, then go to **"Account Settings."** Locate the paper account you'd like to remove and click the **"Delete Account"** button next to it.
> **Don't forget to generate new API keys for any newly created account.**

### Procedure
1. Log in → paper dashboard: https://app.alpaca.markets/paper/dashboard/overview
2. Click the **paper account number, upper-left** → **"Open New Paper Account"**
3. Accept the **default $100,000** balance. Do not customize it.
4. Name it something obvious, e.g. `HACKATHON-COMP`.
5. **Generate new API keys** for this account. Save the secret (shown once).
6. Verify immediately:
   ```bash
   ALPACA_API_KEY=<comp key> ALPACA_SECRET_KEY=<comp secret> \
     alpaca account get --jq '{id, equity, cash, options_approved_level, options_trading_level}'
   ```
   `equity` must read `100000`.
7. **Record the `id`** — that's the account ID you submit.
8. Do **not** place any test orders on it. Test on the DEV account.

### Two-account setup
| Account | Name | Purpose |
|---|---|---|
| DEV | `HACKATHON-DEV` | Everything: backtests, broken code, exploratory orders, load tests. Delete and recreate freely. |
| COMP | `HACKATHON-COMP` | Created fresh. Only the final agent trades here. Its ID goes in the submission. |

**When to switch COMP on:** as early as you trust the agent, because P&L accrues over the whole window and you only have ~5.2 trading days. Recommended: DEV until end of Day 2, COMP live from the Aug 31 open. If you must recreate COMP later you lose accrued P&L days — so get it right the first time.

## 3. Paper vs Live — feature parity

| Feature | Paper | Live |
|---|---|---|
| Eligibility | ✅ | ✅ |
| API Access | ✅ | ✅ |
| Free IEX real-time data | ✅ | ✅ |
| MFA | ✅ | ✅ |
| Margin trading | ✅ | ✅ |
| Short selling | ✅ | ✅ |
| Premarket/after-hours trading | ✅ | ✅ |
| Borrow fees | ⛔️ (coming soon) | ✅ |

Options trading is **enabled by default in paper**.

## 4. 🔴 The paper fill model — exactly how your orders fill

This is the single most important technical section for a P&L-scored competition. Verbatim rules:

- **Orders are filled only when they become marketable.** A non-marketable buy limit will not fill until its limit price ≥ best ask; a non-marketable sell limit will not fill until limit ≤ best bid.
- **Your order quantity is NOT checked against NBBO quantities.** "You can submit and receive a fill for an order that is much larger than the actual available liquidity."
- **When orders are eligible to be filled, they receive partial fills for a random size 10% of the time.** If the remaining order price is still marketable, the remainder is re-evaluated for a subsequent fill.
- **All orders are matched against the best available current market price (NBBO).**

### What this means for your agent
1. **Limit orders in options are the correct default, but they will sit unfilled if you price them badly.** Because paper fills at NBBO when marketable, a limit at or through the ask fills essentially instantly; a limit at mid may never fill in a wide options market. Have a **re-price ladder**: submit at mid → if unfilled after N seconds, replace toward the ask in steps.
2. **Plan for partial fills.** 10% of eligible fills are partial with random size. Your position-tracking code must reconcile `filled_qty` vs `qty` on every poll, and your leg-balance logic must not assume an mleg filled whole. (An `mleg` order fills as a unit but can still partial-fill in units of the strategy.)
3. **Do NOT exploit the liquidity gap.** You *can* get a fill on 2,000 contracts of an illiquid strike. Doing so produces an impressive but fake P&L that a brokerage judging panel will immediately read as gaming. Add a **liquidity gate** to your risk layer instead — and make the gate a talking point:
   ```
   reject if open_interest < 500
   reject if (ask - bid) / mid > 0.15
   reject if qty > 0.05 * open_interest
   ```
   This turns a paper-trading weakness into a *credibility signal*.

## 5. What paper does NOT simulate

> Paper trading does not account for:
> - Market impact of your orders
> - Information leakage of your orders
> - Price slippage due to latency
> - Order queue position (for non-marketable limit orders)
> - Price improvement received
> - Regulatory fees
> - Dividends

Additional stated rules:
- Paper **does NOT simulate dividends**
- Paper **does NOT send order fill emails**
- **Market Data API works identically**

### Options-specific paper caveat (from `options-trading.md`)
> 🚧 On PAPER **NTAs are synced at the start of the following day**. While your balance and positions are updated instantly, NTAs on PAPER will be visible in the Activities endpoint only the next day.

NTAs = non-trade activities = **exercise, assignment, expiry** events. So:
- Your **balance and positions update instantly** on expiry/exercise.
- But the *activity record* for it appears in `/v2/account/activities` only the next day.
- ⚠️ **Consequence:** if a contract expires on Sep 4 (deadline day), the activity record may not exist before you submit. **Do not depend on NTAs for your P&L reporting.** Use `portfolio_history` and `positions` instead, and close positions rather than letting them expire into the deadline.

Also: **options assignments are not delivered over websocket.** You must poll the REST activities endpoint. Websocket support for NTAs does not exist.

## 6. Comparing to other simulators

Alpaca notes results differ from Quantopian/IBKR paper due to different fill prices, fill assumptions, liquidity assumptions, return calculation methodologies, and market data sources. Don't benchmark against another platform's paper numbers.

## 7. Paper trading pre-flight checklist for the COMP account

```bash
export ALPACA_API_KEY=<comp>; export ALPACA_SECRET_KEY=<comp>
alpaca doctor                                        # connectivity + config
alpaca account get --jq '{id,equity,cash,buying_power,options_buying_power,options_approved_level,options_trading_level,trading_blocked,account_blocked}'
alpaca clock                                         # is the market open?
alpaca calendar --start 2026-08-28 --end 2026-09-08   # confirm the real trading days
alpaca position list                                 # must be []
alpaca order list --status all                        # must be []
alpaca option contracts --underlying-symbol SPY --limit 5   # options access works
alpaca data option chain --underlying-symbol SPY      # options data works
```
Expected: `equity: "100000"`, empty positions, empty orders, options endpoints returning data.

**Screenshot this output and put it in the repo** as `docs/comp_account_preflight.txt` — it's evidence for the judges that the account was fresh at $100k.
