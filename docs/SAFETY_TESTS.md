# Safety system verification

Run: `python scripts/test_safety.py` · **21/21 passed** · 30 Aug 2026 · DEV account

These are the two systems that had never actually fired. Both are now verified
end-to-end, including against the live Alpaca API.

---

## 1. Circuit breaker

### Trigger logic
| Scenario | Expected | Result |
|---|---|---|
| Flat account | no trip | ✅ |
| Daily P&L −2.1% | trips `g_daily_drawdown` | ✅ |
| Daily P&L −1.9% | does **not** trip | ✅ |
| Total P&L −6.5% | trips `g_total_drawdown` | ✅ |
| 12 orders in an hour | trips `g_order_rate` | ✅ |
| `HALTED` file present | trips `g_kill_switch` | ✅ |

### 🔴 The halt actually reaches Alpaca
A real halt was executed against the DEV account:

| Step | Result |
|---|---|
| Cancel all working orders | ✅ |
| Flatten every position | ✅ |
| `PATCH /v2/account/configurations {"suspend_trade": true}` | ✅ |
| Read back `suspend_trade` from the account | ✅ `true` |
| **Submit a real option order while suspended** | ✅ **rejected by Alpaca** |
| Restore `suspend_trade: false` | ✅ |

The rejection came back from the broker, not from our code:

```
HTTP 403  {"code": 40310000, "message": "new orders are rejected by user request"}
```

**This is the important part.** The kill switch is enforced server-side by Alpaca.
If our process is killed, hangs, or is restarted by someone who does not know it
was halted, the account still refuses orders. A flag in our own memory would not
survive any of those.

---

## 2. Crash recovery

Alpaca does not support bracket or OCO orders on options, so the agent's exit
plan — take-profit, stop, time stop — lives in our SQLite ledger. If that plan is
lost in a crash, open positions sit unprotected. This tests that it is not.

| Check | Result |
|---|---|
| Position persisted before the crash | ✅ |
| Ledger survives an unclean restart | ✅ |
| Exit thresholds (TP / SL) recovered intact | ✅ |
| Audit log survives restart | ✅ |
| Equity history survives restart | ✅ |

### Reconciliation — the broker is the source of truth

On startup the agent compares its ledger against the broker and reports
disagreement in **both** directions rather than silently trading on a wrong
picture:

| Situation | Detected as | Result |
|---|---|---|
| We think we hold it, broker has nothing | **ghost** | ✅ |
| Broker holds it, we have no exit plan for it | **orphan** | ✅ |
| Ledger and broker agree | **clean** | ✅ |

An orphan is the dangerous one: a live position with no stop attached and nothing
watching it. The agent flags it loudly at the top of the cycle instead of
proceeding as if the book were what it expected.

---

## What is still unverified

**A real fill.** Every order the agent has submitted was `accepted` while the
market was closed; none has filled. Still untested against a live fill:

- whether our limit prices are close enough to the market to fill
- the exact shape of a fill payload
- partial-fill reconciliation (Alpaca's paper environment produces random partial
  fills roughly 10% of the time)

That is Monday's first task, and it runs on the DEV account before anything
touches the competition account.
