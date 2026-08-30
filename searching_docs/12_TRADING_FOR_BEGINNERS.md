# 12 — Trading & Options, explained from zero

Written for someone who has never traded. Read once, refer back as needed.

---

## 1. The basics

**Stock** — a small piece of a company. Own it, and you own a fraction of that business.

**ETF** — a basket of many stocks that trades like a single stock.
- **SPY** = the 500 biggest US companies in one basket. Currently **~$769**.
- **QQQ** = the 100 biggest tech companies.
- These are what we'll trade. They're the most liquid things on the market — meaning it's always easy to buy and sell.

**Paper trading** — a full simulation. Real prices, real market, **fake money**. That's what the whole competition runs on. You cannot lose real money.

---

## 2. What an option is

> An **option** is a contract that gives you the **right — but not the obligation** — to buy or sell 100 shares at a fixed price, before a deadline.

Four things define every option:

| Term | Meaning |
|---|---|
| **Underlying** | Which stock/ETF it's based on (e.g. SPY) |
| **Strike price** | The fixed price in the contract (e.g. $775) |
| **Expiration** | The deadline (e.g. Sep 4) |
| **Premium** | What the contract costs to buy |

**1 contract = 100 shares.** So a premium quoted as "$3.00" actually costs **$300**.

### The two types

| | You buy it when you think… | It gives you the right to… |
|---|---|---|
| **CALL** | price goes **UP** ↑ | **buy** at the strike |
| **PUT** | price goes **DOWN** ↓ | **sell** at the strike |

### A worked example

SPY is $769. You buy a **CALL, strike $775, expiring Sep 4**, premium $3.00 → costs **$300**.

| What SPY does | Your result |
|---|---|
| Rises to $790 | Contract is worth ~$1,500 → **+$1,200 profit** |
| Rises to $778 | Contract is worth ~$300 → roughly break even |
| Stays at $769 | Expires **worthless** → **−$300, you lose everything** |

**This is the problem with simply buying options: you can very easily lose 100% of what you paid.**

---

## 3. 🔴 The single most important concept: time decay

**Options lose value every single day, automatically, as the deadline approaches.**

Think of an option like an ice cube. Every day some of it melts, whether or not anything else happens.

That gives you two ways to play:

| | |
|---|---|
| **BUY** options | Time works **against** you. You need to be right, and right **soon**. |
| **SELL** options | Time works **for** you. You profit if nothing dramatic happens. |

**Why this decides our whole strategy:** the competition is only **~4.5 trading days**. That is not enough time to be right slowly. So we want time working *for* us, not against us.

---

## 4. 🔴 Spreads — how we never blow up

Buying or selling a single option is dangerous. A **spread** fixes that.

> A **spread** = you buy one option **and** sell another at the same time.
> This caps your maximum profit **and** — crucially — caps your maximum loss.

### Example: a "put credit spread"

SPY is $769. You do both of these as one order:
- **SELL** a put at strike $750 → you *collect* $2.00
- **BUY** a put at strike $745 → you *pay* $1.00

Net: you **collect $1.00** = **$100** in your pocket immediately.

| What SPY does by expiry | Your result |
|---|---|
| Stays above $750 (most likely) | Keep the whole **+$100** ✅ |
| Falls to $748 | Small loss |
| Falls below $745 | Lose the maximum: **−$400** |

**Maximum profit: $100. Maximum loss: $400. Both known before you enter.**

Notice what you're betting on: not that SPY goes up — just that it **doesn't crash**. You win in three of four scenarios: up, sideways, or slightly down.

**This is why every trade our agent makes will be a spread.** The loss is always capped, always known in advance. The account cannot blow up.

### Iron condor — two spreads at once

Place a put spread *below* the price and a call spread *above* it. Now you profit as long as SPY **stays in a range**.

```
        LOSE          WIN (keep the money)          LOSE
  ────────────┃━━━━━━━━━━━━━━━━━━━━━━━━━━━━┃────────────
             $745        SPY $769         $790
```
Perfect when you expect a calm market. Uses 4 options at once — which is the most advanced order type Alpaca supports, and a big part of our technology score.

---

## 5. The Greeks — just risk measurements

Don't be intimidated. They're four numbers Alpaca calculates **for free** and hands to us.

| Greek | Plain English | Why we care |
|---|---|---|
| **Delta** | How much the option moves when the stock moves $1. Also ≈ **the probability it finishes profitable.** | Delta 0.20 ≈ a 20% chance. We pick strikes by this. |
| **Theta** | How much money time decay gives/costs you **per day** | We want this **positive** — it's our income |
| **Vega** | Sensitivity to volatility changes | Tells us if we profit when markets calm down |
| **Gamma** | How fast delta changes | High gamma = risk gets unstable fast |

Real numbers from our account today:
```
SPY $765 call, expiring Sep 4:   delta 0.667   theta −0.46   IV 12.5%
```
Reading that: it moves 67¢ per $1 SPY move · it loses $46/day to time · implied volatility is 12.5%.

---

## 6. Implied Volatility (IV) — the price of fear

**IV = how much movement the market *expects*.** It's the main driver of how expensive options are.

| IV | Options are | Best move |
|---|---|---|
| **High** (market scared) | expensive | **SELL** spreads — collect fat premiums |
| **Low** (market calm) | cheap | **BUY** spreads — pay little for exposure |

**Right now SPY IV is ~12.5% — that is LOW.** The market is calm. We'll measure this properly before choosing, but low IV currently tilts us toward *buying* spreads rather than selling them.

---

## 7. Our strategy, in plain English

> Every 5 minutes, the agent checks whether the market is **calm** or **trending**.
> Then it places an options **spread** matched to that condition.
> Every trade has a **capped, known loss** — never more than ~$400 (0.4% of the account).
> It closes winners at +50%, cuts losers early, and never holds anything into expiry.

| Market condition | What the agent does |
|---|---|
| Calm + expensive options | **Iron condor** — profit if price stays in a range |
| Slight direction + expensive options | **Credit spread** — collect premium |
| Clear trend + cheap options | **Debit spread** — pay a little for a directional bet |
| No clear signal | **Nothing.** Sitting out is a valid decision. |

---

## 8. Words you'll hear us use

| Term | Meaning |
|---|---|
| **Position** | A trade you currently hold |
| **P&L** | Profit and Loss — how much you've made or lost |
| **Realized / Unrealized** | Locked in (closed) / still floating (open) |
| **Leg** | One option inside a spread. An iron condor has 4 legs. |
| **Multi-leg / `mleg`** | An order that places all legs at once, as one unit |
| **Strike** | The fixed price in the contract |
| **Expiry / DTE** | Deadline / Days To Expiration |
| **ITM / OTM** | In the money (profitable now) / Out of the money (not yet) |
| **Premium** | The price of an option |
| **Credit / Debit** | You receive money / You pay money |
| **Bid / Ask** | What buyers offer / what sellers want. The gap is the "spread" (different meaning!) |
| **Liquidity** | How easy it is to trade. High = good. |
| **Open Interest** | How many contracts exist. High = liquid. |
| **Drawdown** | How far the account has fallen from its peak |
| **Buying power** | How much you can deploy |
| **Fill** | Your order actually executed |
| **Slippage** | Getting a slightly worse price than expected |
| **Underlying** | The stock/ETF the option is based on |
| **0DTE** | Expires today. Very risky. We avoid it. |
