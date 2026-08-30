# Verified findings (tested against the live Alpaca API)

All confirmed on the DEV paper account `PA349BYK6I13`, 2026-08-30.

## 1. 🔴 mleg sign convention — SETTLED

Alpaca's docs state positive = debit / negative = credit, but their own iron-condor
**example** shows a positive price for what is normally a credit structure. We tested both.

| Structure | limit_price sent | Result |
|---|---|---|
| Iron condor (credit, $0.67) | **`-0.67`** | ✅ `accepted`, `order_class: mleg`, 4 legs |
| Bull call spread (debit, $2.44) | **`+2.44`** | ✅ `accepted` |

**Conclusion: POSITIVE = DEBIT (you pay), NEGATIVE = CREDIT (you receive).**
The docs are right; their example is just illustrative. Enforced in `agent/spreads.py`.

## 2. 🔴 mleg coverage rule — corrected

Our first validator required a short leg's protective long to be *further OTM*.
**That was wrong** and rejected valid debit spreads.

The real rule: for each `(root, expiry, call/put)` bucket, **total LONG ratio_qty must be
>= total SHORT ratio_qty**. Strike direction is irrelevant — both of these are covered,
defined-risk structures:

```
long 769C / short 774C   -> bull call DEBIT spread   ✅ covered
short 781C / long 785C   -> bear call CREDIT spread  ✅ covered
```

Correctly still rejected: naked shorts (no long at all), calendars (long in a different
expiry), ratio spreads (short qty > long qty). 18 unit tests cover this.

## 3. OPRA is not entitled — use `indicative`

```
GET /v1beta1/options/snapshots/SPY?feed=opra
-> 403  {"error": "OPRA agreement is not signed"}
```
`feed=indicative` works and returns full Greeks + IV. ⚠️ The **Alpaca CLI defaults to
`--feed opra`**, so every options data call must pass `--feed indicative` explicitly.

## 4. Greeks availability — matches the documented rules exactly

A raw SPY chain query returned `delta: 0, iv: null` — those were **deep-ITM** strikes
(420 when SPY is 769), where the IV solver cannot converge. At the money: **42/42
contracts returned full Greeks.**

On a real 216-contract chain, our filters kept **154** and rejected **62**, all for
legitimate reasons:
```
SPY260904C00817000: one-sided quote (bid=0.0 ask=0.01)
SPY260904C00799000: spread 66.7% > 15%
SPY260904C00805000: spread 28.6% > 15%
```
This confirms the rule now hard-coded in `agent/options.py`:
**a missing Greek means "unusable contract" — never coerce it to 0.**

## 5. SPY has DAILY expiries

```
2026-08-31, 09-01, 09-02, 09-03, 09-04, 09-08, 09-09, 09-10, 09-11
```
Better than the Mon/Wed/Fri assumed in the original study — this gives **4-5 complete
theta cycles inside the competition window** instead of 2-3.

## 6. Rate limit confirmed: 200/min

`X-RateLimit-Limit: 200`, `X-RateLimit-Remaining` decrements per call. `agent/client.py`
throttles from these headers rather than a hard-coded ceiling.

## 7. Account facts

| | DEV | COMP |
|---|---|---|
| Number | `PA349BYK6I13` | `PA3BAT1OOEFE` |
| UUID | `89253ffc-f556-435b-b9d6-66b667264304` | *(pending — generate keys at go-live)* |
| Equity | $100,000 | $100,000 |
| Options level | **3** (mleg unlocked) | **3** |
| Options buying power | $100,000 | $100,000 |
| Multiplier | 4 | 4 |

## 8. Live market snapshot (2026-08-30)

SPY **$769.28** · ATM IV **11.6%** (low) · 1σ expected move to Sep 4 = **$10.46**
SPY strike increments are **$1**.

Sample condor built from live data:
```
+751P / -756P / -781C / +785C   credit $0.67   max loss $433
delta -0.01   theta +$15.08/day   win zone $756-781 (3.2% wide)
```
