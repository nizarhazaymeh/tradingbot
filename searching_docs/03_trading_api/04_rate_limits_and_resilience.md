# 04 — Rate Limits, Retries, Reconciliation & Resilience

This page is what turns a demo script into something a brokerage judge respects. Sources: `about-market-data-api.md`, Alpaca CLI README, `alpaca-skills` paper-trading + rate-limits skills.

## 1. Known limits

| Surface | Limit | Source |
|---|---|---|
| **Market Data historical (Basic)** | **200 requests / min** | `about-market-data-api.md` |
| Market Data historical (Algo Trader Plus) | 10,000 / min | same |
| Options websocket subscriptions (Basic) | **200 quotes** | same |
| Options websocket subscriptions (ATP) | 1,000 quotes | same |
| **Trading API** | **Not published.** ~200/min is "widely cited but not stated in Alpaca's current documentation — do not hard-code it." | alpaca-skills |

## 2. 🔴 Drive throttling from the response headers, not a constant

Every response carries:
```
X-RateLimit-Limit
X-RateLimit-Remaining
X-RateLimit-Reset
```

Correct pattern (adaptive, self-tuning):
```python
class RateGovernor:
    def __init__(self, floor=0.15):
        self.limit = None; self.remaining = None; self.reset = None
        self.floor = floor   # start slowing when <15% of budget remains

    def observe(self, headers):
        self.limit     = int(headers.get("X-RateLimit-Limit", 0) or 0)
        self.remaining = int(headers.get("X-RateLimit-Remaining", 0) or 0)
        self.reset     = int(headers.get("X-RateLimit-Reset", 0) or 0)

    def delay(self) -> float:
        if not self.limit:
            return 0.0
        frac = self.remaining / self.limit
        if frac > self.floor:
            return 0.0
        secs_to_reset = max(0, self.reset - int(time.time()))
        # spread whatever calls remain across the rest of the window
        return secs_to_reset / max(1, self.remaining)
```
Log `remaining/limit` on every call and put a chart of it in your slides. It is a *very* cheap way to demonstrate operational maturity.

## 3. Retry policy

**429 and 5xx:** exponential backoff, honor `Retry-After`.

**The Alpaca CLI already retries 429/5xx up to 3 times and respects `Retry-After`.** Alpaca's own guidance:
> "Do not add your own retry loop for rate limits. The CLI already retries 429 and 5xx responses up to three times and respects `Retry-After`. A second backoff layer on top of it turns one rate-limited call into a much longer stall. If a command still fails after the CLI's retries, surface the error and stop."

So: **one retry layer, in one place.** If you call the CLI, don't wrap it in retries. If you call the REST API directly, put the retries in your HTTP client.

## 4. 🔴 Idempotency & reconciliation — the ambiguous-failure problem

The dangerous case is not an error, it's a **timeout**: you don't know whether the order was accepted.

**Rule:** *never blind-retry an order.* Always:
```
1. Generate client_order_id BEFORE the first attempt. Persist it.
2. Submit with that client_order_id.
3. On timeout / unknown error:
      GET /v2/orders:by_client_order_id?client_order_id=<id>
      - found  → the order exists. Do not resubmit. Reconcile state.
      - 404    → safe to retry with the SAME client_order_id.
4. Duplicate submissions with the same client_order_id are rejected by the API.
```

`client_order_id` is ≤128 chars. Suggested deterministic scheme (readable in a decision log, and reproducible so a retry generates the same ID):
```
{strategy}-{utc_yyyymmddTHHMMSS}-{underlying}-{intent}-{sha8(payload)}
verticalcall-20260902T143005-SPY-open-9f3ab12c
```

## 5. Startup reconciliation (crash recovery)

Every time the agent starts — after a crash, a deploy, or a cron tick — reconcile before deciding anything:

```
1. GET /v2/clock                      → is the market open?
2. GET /v2/account                     → equity, options_buying_power, blocked flags
3. GET /v2/positions                   → what do I actually hold?
4. GET /v2/orders?status=open          → what's in flight?
5. Load persisted intents (TP/SL/time-stops per position)
6. Diff:
   - position with no persisted intent  → orphan. Flatten it or adopt with default exits. LOG LOUDLY.
   - persisted intent with no position   → already closed. Mark closed, record realized P&L.
   - open order not in my ledger         → orphan order. Cancel it.
7. Only then run the decision loop.
```

Alpaca's reference architecture does the same thing:
> "If an active position is missing its bracket order, it gets rebuilt automatically."

## 6. State durability

Options positions live for days; your agent will restart. Persist:

| What | Why |
|---|---|
| Every proposal (full structured object) | audit log + write-up material |
| Every order submitted, with `client_order_id` | idempotency + reconciliation |
| Per-position intended TP / SL / time-stop | you can't use brackets on options |
| Realized P&L ledger per closed trade | your results table |
| Daily `portfolio_history` snapshot | the equity curve |
| Rate-limit header samples | the ops chart |
| Every rejected proposal + the gate that rejected it | proves the risk layer works |

SQLite is sufficient and zero-ops. Alpaca's reference architecture uses exactly that (`market_snapshot` table, agents query one interface).

## 7. Failure modes to guard against explicitly

| Failure | Guard |
|---|---|
| Market closed but agent submits anyway | clock gate at top of loop |
| Data source returns stale/empty chain | staleness check on quote timestamps; abort the cycle rather than trade on nothing |
| Greeks missing (0DTE, zero bid/ask) | treat missing Greeks as a **reject**, not as zero |
| Option not tradable / delisted | check `tradable` on the contract before ordering |
| Partial fill leaves an unbalanced spread | reconcile `filled_qty`; if a spread is legged, immediately hedge or flatten |
| Runaway loop placing many orders | max-orders-per-hour counter; hard kill switch |
| Drawdown spiral | daily + total drawdown halts that call `PATCH /v2/account/configurations {"suspend_trade": true}` and `DELETE /v2/orders` |
| Credentials leaked to logs | scrub layer on every log write |
| Expiry converts to shares via auto-exercise | close all positions before expiry (see `02_positions_and_account.md` §4) |
| Corporate action mid-position | corporate-actions pre-trade gate |
| Cron overlaps itself (slow run) | lock file / advisory lock |

## 8. Observability for the demo

Emit one structured JSON line per decision. This *is* your demo's centre panel and your originality evidence:
```json
{"ts":"2026-09-02T14:30:05Z","cycle":412,"agent":"vol_regime","underlying":"SPY",
 "signal":{"iv_rank":0.71,"trend":"neutral","expected_move_pct":1.1},
 "proposal":{"strategy":"iron_condor","expiry":"2026-09-04","short_put":640,"long_put":635,
             "short_call":660,"long_call":665,"credit_target":-1.35,"max_loss":365},
 "gates":{"liquidity":"pass","oi":"pass","spread_width":"pass","concentration":"pass",
          "buying_power":"pass","corp_action":"pass","dte":"pass"},
 "decision":"submit","client_order_id":"ic-20260902T143005-SPY-9f3ab12c",
 "rate_limit":{"remaining":181,"limit":200}}
```
