# 07 — Risks & Failure Modes (pre-mortem)

Assume it's Sep 4 and the submission failed. Here is every way that happened, and the guard for each.

## 1. Submission-level failures (fatal, and entirely avoidable)

| # | Failure | Guard | Check by |
|---|---|---|---|
| 1 | Used the DEV account for the submission | Two accounts, different key files, COMP keys only in the cron env. Print the account ID in every log line. | Aug 30 |
| 2 | COMP account balance ≠ $100,000 | Accept the default on creation. **You cannot change it afterward** — you'd need a new account. Verify `equity == 100000` before the first trade. | Aug 30 |
| 3 | Forgot the account ID in the submission | Put it in README, write-up, slide 1, and the form. Four places. | Aug 30 |
| 4 | Repo still private | Verify in an **incognito window**, not your logged-in browser. | Sep 3 |
| 5 | Demo URL dead / crashes when market closed | Deploy early. Test in incognito. Make the dashboard render correctly with `is_open == false`. | Sep 3 |
| 6 | Video <3 min (rubric scores it a 2) or >5 min (over the cap) | Target 3:45. Time it. | Sep 2 |
| 7 | No options in the strategy | Options are the primary instrument, incl. at least one `mleg`. | Aug 29 |
| 8 | Neither MCP nor CLI used | Both, with evidence committed. | Aug 30 |
| 9 | Missed the deadline | Submit by 10:45 ET Sep 4. Manual submission needs **prior approval**. | Sep 4 |
| 10 | API keys committed to a public repo | `git log -p \| grep -iE 'APCA\|ALPACA_(API\|SECRET)\|PK[A-Z0-9]{16}'`. If a key leaked, **rotate immediately** — and if it was the COMP key, that account is compromised. | Sep 3 + daily |
| 11 | Not enrolled / not on Discord | Click Enroll. Join Discord. | Aug 27 |
| 12 | No MIT LICENSE (prize terms require MIT-compliant) | Add it Day 0. No copyleft dependencies. | Aug 27 |

## 2. Trading failures (these destroy the P&L score)

| # | Failure | Guard |
|---|---|---|
| 13 | **Blow-up: account down 15%+** | Circuit breakers at daily −2% / total −6% that cancel all orders, flatten, and set `suspend_trade: true`. Defined-risk structures only. 0.40% max loss per trade. |
| 14 | **Runaway loop places 200 orders** | Order-rate limiter (≤12/hour). `flock` so cron can't overlap. Kill-switch file the loop checks first. |
| 15 | **0DTE gamma blow-up on Sep 4** | Reject DTE = 0 at entry. Force-close on expiry day at 14:00 ET, market at 15:30 ET. Flatten everything at the Sep 4 open. |
| 16 | **Auto-exercise converts options into equity** worth more than the account | Alpaca auto-exercises ITM by ≥$0.01. Close every position before expiry. |
| 17 | **Wrong debit/credit sign** → orders rejected all week, or filled inverted | Verify empirically on DEV on Day 1. Enforce in a gate. `docs/mleg_sign_convention.md`. |
| 18 | **Naked short leg inside an mleg** → every order rejected | `validate_mleg()` coverage check before submit. |
| 19 | **Missing Greeks coerced to 0** → risk system thinks a position is delta-neutral when it isn't | Missing Greek ⇒ **reject**. Never `or 0`. |
| 20 | **Filled 2,000 contracts in an illiquid strike** because paper doesn't check liquidity | OI ≥ 500, spread ≤ 15%, qty ≤ 5% of OI. Also protects you from a gaming accusation. |
| 21 | **Unfilled limits all week** → no trades, no P&L | Price ladder with `alpaca order replace`. Log fill rate. |
| 22 | **Legged-out spread** after a partial fill | Reconcile `filled_qty` every cycle; hedge or flatten an unbalanced structure immediately. Paper produces random partial fills 10% of the time. |
| 23 | **Assignment on a short leg** you didn't notice | Poll `/v2/account/activities` every 5 min (**no websocket for NTAs**) *and* watch for unexpected equity positions. Avoid shorts with an ex-div inside the position's life. |
| 24 | **Corporate action mid-position** | Corporate-actions pre-trade gate. |
| 25 | **Traded while market closed** → 422s, or `day` orders queued to a day you didn't intend | Clock gate at the top of every cycle. |
| 26 | Over-concentrated in one underlying or one expiry | Per-underlying 1.2%, per-expiry 2.5%. Note margin is computed per-expiry taking the **largest** — concentrating in one expiry is margin-efficient, but cap the risk. |

## 3. Engineering failures

| # | Failure | Guard |
|---|---|---|
| 27 | **Rate-limited into uselessness** (200 calls/min on Basic) | Batch every multi-symbol request. `get_option_chain` = 1 call for a whole chain. Cache 30–60s. Governor driven by `X-RateLimit-*`. |
| 28 | **Double retry layers** turn one 429 into a long stall | The CLI already retries 429/5xx ×3 with `Retry-After`. **Don't wrap it.** |
| 29 | **Duplicate orders after a timeout** | `client_order_id` generated *before* the first attempt; on ambiguity, `GET /v2/orders:by_client_order_id` before retrying. |
| 30 | **Agent crashes, loses all exit intents** | Persist intents to SQLite. Startup reconciliation rebuilds them; orphan positions are flagged loudly. |
| 31 | **Websocket disconnects, missed fills** | Reconnect with backoff, **re-subscribe** (subscriptions are per-connection), then reconcile against REST. REST is authoritative. |
| 32 | **Option stream doesn't work** | It's **msgpack-only**. Use `OptionDataStream`, not a hand-rolled JSON client. |
| 33 | Connected to the `opra` feed on Basic → auth failure | Use `indicative`. |
| 34 | Exceeded 200 option-quote subscriptions | Stream only held positions; poll the chain for discovery. |
| 35 | **`alpaca-py` API changed** between versions | Verify with `inspect.signature()` on Day 1, not against a blog post. |
| 36 | **MCP tool names wrong** (V1 vs V2) | V2 is a full rewrite; none of the V1 tools exist. Restart the client, fresh session, use `/mcp` to list real tools. |
| 37 | Partial env var bundle → CLI silently uses a different profile | Always export `ALPACA_API_KEY` **and** `ALPACA_SECRET_KEY` together. |
| 38 | 🔴 **Accidentally traded LIVE** | Never set `ALPACA_LIVE_TRADE` or `ALPACA_PAPER_TRADE=false`. Assert `paper=True` at startup and refuse to run otherwise. Assert the base URL contains `paper-api`. |
| 39 | Cron overlapped itself on a slow cycle | `flock -n 9` at the top of the script. |
| 40 | Timezone bug (ET vs UTC vs GMT+3) | Store UTC everywhere; convert to ET only for market-hours logic. Use `zoneinfo`, never fixed offsets (EDT/EST). |
| 41 | Half-strike symbol built wrong (`637.5` → `00637499`) | `int(round(strike*1000))`. Round-trip test. |
| 42 | Volume-based signal broken by IEX-only data | IEX is ~2–3% of consolidated volume. Avoid volume signals, or normalize against IEX's own history. |

## 4. Process / people failures

| # | Failure | Guard |
|---|---|---|
| 43 | **Pivoted on Day 4** (lablab: "almost always fatal") | Lock the idea by end of Day 1. Only fix bugs after Aug 31. |
| 44 | **Spent Days 1–3 on the UI, trading loop live on Sep 3** | Loop first, always. Dashboard only after the loop is live. |
| 45 | **One giant commit on Sep 4** (judges read commit history) | Commit 5–10× per day from Day 0. |
| 46 | Left the video and write-up to Sep 4 | Video recorded Sep 2. Write-up drafted Aug 30. |
| 47 | Team disagreement over the single payee | Decide in writing on Day 0. Prizes go to **one individual**. |
| 48 | Missing tax docs → 90-day forfeiture | Have ID + bank details + W-8BEN info ready before results. |
| 49 | Nobody posted on social → lost $500 + subscriptions | Schedule the 5 posts on Day 0. |
| 50 | Ignored a late-announced technology-partner prize | **Re-read the event page after kick-off** — partners were TBA. |

## 5. The three that actually decide this

If you only guard three things:

1. **🔴 A fresh $100,000 paper account, live and trading by the Aug 31 open, whose ID is in the submission.** Everything about the P&L criterion depends on this and it's a one-time, irreversible setup.
2. **🔴 Circuit breakers that work, tested.** A blown-up account doesn't just lose the P&L criterion — it makes the whole submission read as unserious. Bounded downside is worth more than any signal.
3. **🔴 A flat account before the Sep 4 deadline, with the number frozen and explainable.** Removes 0DTE risk, auto-exercise risk, and the ambiguity of a judge marking an open position after you stopped controlling it.

## 6. Daily 5-minute health check

Run this every morning and paste the output into `docs/daily_health.md`:
```bash
#!/usr/bin/env bash
echo "=== $(date -u +%FT%TZ) ==="
alpaca clock
alpaca account get --jq '{id, equity, cash, options_buying_power, daytrade_count, trading_blocked, account_blocked}'
alpaca position list --jq 'length as $n | {open_positions: $n, total_unrealized: (map(.unrealized_pl|tonumber)|add)}'
alpaca order list --status open --jq 'length'
echo "--- gates fired yesterday ---"
jq -r 'select(.decision=="reject") | .gates | to_entries[] | select(.value!="pass") | .key' logs/agent-*.jsonl | sort | uniq -c | sort -rn
echo "--- min rate-limit headroom ---"
jq -r '.rate_limit.remaining // empty' logs/agent-*.jsonl | sort -n | head -1
echo "--- keys leaked? ---"
git log -p | grep -icE 'APCA|ALPACA_(API|SECRET)_KEY=|PK[A-Z0-9]{16}' || echo 0
echo "--- tests ---"
pytest -q 2>&1 | tail -3
```
