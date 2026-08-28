# Multi-Timeframe Trading Bot — Gold, Currencies & Crypto

A safe-by-default trading bot: moving-average crossovers confirmed across two
timeframes, gated by trend strength, with risk sized in ATR. It runs against
either broker, selected with `BROKER` in `.env`:

| `BROKER` | Market | Endpoint |
|---|---|---|
| `alpaca` (default) | US stocks **and** crypto | `paper-api.alpaca.markets` / `api.alpaca.markets` |
| `binance` | Spot crypto | Binance / Binance Testnet |

`strategy.py` is shared — only the execution layer (`broker.py`) differs.

## What it trades

**Alpaca has no spot forex and no physical gold** — only US equities, ETFs,
options and crypto. Gold and currencies are traded through the standard liquid
ETF proxies, which are ordinary Alpaca equities:

| Exposure | Ticker | Tracks | Alternatives |
|---|---|---|---|
| Gold | `GLD` | Spot gold bullion | `IAU`, `GLDM` (cheaper fees) |
| Euro | `FXE` | EUR/USD | |
| Pound | `FXB` | GBP/USD | |
| Yen | `FXY` | JPY/USD | |
| Swiss franc | `FXF` | CHF/USD | |
| Aussie | `FXA` | AUD/USD | |
| US dollar | `UUP` | USD index | `UDN` (inverse) |

These trade **US market hours only** (09:30–16:00 ET) — not 24/5 like real FX.
The bot skips entries when the market is closed.

## Timeframes

Each symbol carries its own, set in `WATCHLIST` as `SYMBOL@ENTRY_TF[:HIGHER_TF]`:

```
WATCHLIST=GLD@15m, FXE@1h:4h, FXB@1h:4h, FXY@1h:4h, UUP@1h:4h
```

- `GLD@15m` — gold on 15-minute bars, single timeframe.
- `FXE@1h:4h` — entries timed on 1h, but only in the direction of the 4h trend.

With no higher timeframe, the entry-timeframe `TREND_SMA` filter carries the
load instead.

> ⚠️ **Trading is risky. This bot can lose money. Test on the Testnet first and
> never trade more than you can afford to lose.**

## How it works

- Every `POLL_SECONDS` it fetches recent bars for each `WATCHLIST` symbol,
  on that symbol's own timeframes.
- It computes the signal (see [The strategy](#the-strategy)).
- **BUY** on a confirmed crossover that passes every filter.
- **SELL** when the fast MA crosses back below the slow one.
- **Risk management:** every open position has a **stop-loss** and
  **take-profit**; whichever is hit first closes the position.
- **Notifications:** every entry/exit is pushed to Telegram and/or email.

## Modes (safest first)

| `SIGNAL_ONLY` | `ENABLE_TRADING` | `USE_TESTNET` | Behaviour |
|---|---|---|---|
| `true` | — | — | **Default.** Notify signals only. No orders. No API key needed. |
| `false` | `false` | — | Paper: track positions + notify, send no orders. |
| `false` | `true` | `true` | Place **real** orders on Testnet / Alpaca paper (fake money). |
| `false` | `true` | `false` | Place **real** orders on your live account. |

For Alpaca the fake-money switch is `ALPACA_PAPER` rather than `USE_TESTNET`.

## Risk controls

Position sizing, account rails and the exit mechanism are separate from the
strategy — `strategy.py` decides *whether* to trade, `risk.py` decides *how
much* and *whether it's allowed*.

**Sizing.** With `RISK_PCT` set, each trade is sized so that being stopped out
costs exactly that fraction of equity:

```
notional = equity * RISK_PCT / STOP_LOSS_PCT
```

So 1% risk on a 2% stop deploys 50% of equity — which is why the result is then
capped by `MAX_POSITION_PCT` and by available cash. Leave `RISK_PCT=0` to keep
the fixed `TRADE_QUOTE_AMOUNT`.

**How a position is protected.** Two mechanisms, best first:

| Protection | When | Behaviour |
|---|---|---|
| `bracket` | Alpaca **stocks**, whole shares, `USE_BRACKET_ORDERS=true` | Stop-loss + take-profit live on Alpaca's side as an OCO pair. Active between polls, and even if this bot dies. |
| `poll` | crypto, or when the order is smaller than one share | The loop checks stop/target every `POLL_SECONDS`. A gap between polls is not covered. |

Alpaca does not support bracket orders for crypto, and brackets are
incompatible with fractional shares — so a $15 order on a $230 stock
automatically falls back to `poll`. The active mode is logged and journaled.

**Account rails**, checked before every new entry (exits are never blocked):

- `MAX_DAILY_LOSS_PCT` — pause new entries once the day is down this much,
  measured against Alpaca's `last_equity` (previous close).
- `MAX_OPEN_POSITIONS` — cap on concurrent positions.
- **PDT guard** — accounts under $25k are limited to 3 day trades per 5
  sessions; a 4th flags the account for 90 days. The bot refuses that trade
  unless `ALLOW_PDT=true`.
- Broker-side `trading_blocked` / non-`ACTIVE` status.

**Reconciliation.** The broker is the source of truth, not `state.json`. Each
cycle the bot compares them: a filled bracket or a manual close is detected and
journaled as an exit, and a position opened outside the bot is adopted rather
than ignored.

**Journal.** Every entry and exit appends a row to `TRADE_LOG` (`trades.csv`)
with price, qty, notional, P/L, mode and protection type.

### Notifications
- **Telegram:** create a bot via [@BotFather](https://t.me/BotFather) for the
  token; get your chat id from [@userinfobot](https://t.me/userinfobot). Fill in
  `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID`.
- **Email:** set the `SMTP_*` and `EMAIL_*` vars. For Gmail use an
  [App Password](https://support.google.com/accounts/answer/185833), not your
  login password.

Both are optional — configure either, both, or neither (console logs always show signals).

## Setup

```bash
cd ~/Desktop/bot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env       # then edit .env with your keys
```

## Getting API keys

### Alpaca (stocks + crypto)
1. Sign up at [app.alpaca.markets](https://app.alpaca.markets) — a paper account
   is created for you automatically, no funding or approval needed.
2. **Home → API Keys → Generate New Key.** The secret is shown **once**.
3. Put them in `.env`:
   ```
   BROKER=alpaca
   ALPACA_API_KEY=your_key_id
   ALPACA_API_SECRET=your_secret_key
   ALPACA_PAPER=true
   SYMBOL=AAPL,TSLA        # or BTC/USD for crypto
   ```
4. Verify the connection (places no orders):
   ```bash
   python test_alpaca.py
   ```

Notes:
- Paper and live keys are **separate accounts** and are not interchangeable —
  `ALPACA_PAPER` must match where the key was generated.
- Alpaca authenticates its **market data** endpoints too, so keys are required
  even with `SIGNAL_ONLY=true`.
- `ALPACA_FEED=iex` is the free real-time feed; `sip` needs a paid data plan.
- Binance-style crypto tickers are auto-converted (`BTCUSDT` → `BTC/USD`),
  since Alpaca settles crypto in USD.
- US stocks only trade during market hours; the bot skips entries when the
  market is closed. Crypto trades 24/7.

### Binance Testnet (recommended first)
1. Go to https://testnet.binance.vision/ and log in with GitHub.
2. Generate an HMAC API key + secret.
3. Put them in `.env` and keep `USE_TESTNET=true`.

### Live account
1. In Binance → API Management, create a key.
2. **Enable "Spot Trading" ONLY. Do NOT enable Withdrawals.**
3. Restrict the key to your IP address if possible.
4. Set `USE_TESTNET=false` in `.env`.

## Running

```bash
python bot.py
```

The bot starts in the **safest** mode:
- `USE_TESTNET=true` → fake money
- `ENABLE_TRADING=false` → paper mode (logs signals, sends no orders)

### Going from paper → real orders
1. Run in paper mode and watch the logs until you trust the signals.
2. Flip `ENABLE_TRADING=true` (still on testnet) to test real order placement.
3. Only after that, set `USE_TESTNET=false` to trade live funds.

## Configuration (`.env`)

| Variable | Meaning |
|---|---|
| `SYMBOL` | Fallback symbol list when `WATCHLIST` is empty |
| `TRADE_QUOTE_AMOUNT` | Quote currency to spend per BUY (e.g. 15 USDT) |
| `INTERVAL` | Fallback candle size when `WATCHLIST` is empty |
| `FAST_SMA` / `SLOW_SMA` | SMA periods (fast must be < slow) |
| `POLL_SECONDS` | How often to re-check the market |
| `USE_TESTNET` | Binance: `true` = testnet, `false` = live |
| `ENABLE_TRADING` | `false` = paper, `true` = send real orders |
| `BROKER` | `binance` or `alpaca` |
| `ALPACA_API_KEY` / `ALPACA_API_SECRET` | Alpaca credentials |
| `ALPACA_PAPER` | `true` = paper account (fake money), `false` = real money |
| `ALPACA_FEED` | `iex` (free) or `sip` (paid) |
| `WATCHLIST` | `SYMBOL@ENTRY_TF[:HIGHER_TF]`, comma separated |
| `MA_TYPE` | `ema` or `sma` |
| `ADX_MIN` | Trend-strength gate; below this, no entries |
| `USE_ATR_STOPS` | ATR-based stop/target instead of fixed percentages |
| `ATR_STOP_MULT` | Stop distance in ATR |
| `REWARD_RISK` | Target as a multiple of the risk |
| `CROSS_ATR_FRAC` | How decisively price must clear the slow MA |
| `HTF_TREND_MA` | Trend MA period on the higher timeframe |
| `RSI_MAX` | Refuse entries above this RSI |
| `TRAIL_ATR` | Ratchet the stop up by ATR (poll-protected only) |
| `RISK_PCT` | Risk per trade as a fraction of equity (`0` = fixed amount) |
| `MAX_POSITION_PCT` | Ceiling on one position, as a fraction of equity |
| `MAX_DAILY_LOSS_PCT` | Pause new entries after this daily drawdown |
| `MAX_OPEN_POSITIONS` | Max concurrent positions |
| `USE_BRACKET_ORDERS` | Broker-side stop/target when possible |
| `ALLOW_PDT` | `false` = refuse trades that could flag pattern-day-trader |
| `TRADE_LOG` | CSV journal path |

## The strategy

The original version — a bare SMA 9/21 crossover with a fixed 2% stop and 4%
target — lost to buy & hold. Three things were wrong, and each has a fix:

| Problem | Fix |
|---|---|
| Crossovers fire constantly in a sideways market, and most are noise | **ADX gate** — no entries below `ADX_MIN`, where price is ranging |
| A fixed 2% stop means nothing across instruments: it's a rounding error on gold intraday and an enormous move on a currency ETF | **ATR stops** — `stop = entry − ATR_STOP_MULT × ATR`, so risk scales with each instrument's own volatility |
| A 1h buy against a falling 4h trend is a losing trade waiting to happen | **Higher-timeframe bias** — entries must agree with the 4h trend |

Plus a decisiveness test: a crossover only counts if the close clears the slow
MA by `CROSS_ATR_FRAC × ATR`. Note this is deliberately *not* the gap between
the two MAs — at a crossover they are equal by definition, so that test can
never pass.

Position sizing pairs with this: `RISK_PCT` sizes against the **actual ATR stop
distance**, so "risk 1% of equity" means the same thing on gold and on FXE.

### Measured effect

1000 × 1h bars of BTC and SOL with a 4h trend filter, 2bps slippage per side
(crypto stands in for gold/FX here — see the caveat below):

| | Trades | Win rate | Return | Max DD | Profit factor |
|---|---|---|---|---|---|
| **New (MTF + ATR)** | 7 | 60% | **+6.87%** | **−1.61%** | — |
| Old (SMA + fixed %) | 7 | 35% | −1.15% | −4.93% | 0.49 / 1.97 |

**Read this cautiously.** Seven trades is far too small a sample to be
conclusive, and the parameters were chosen on this same data. `ATR_STOP_MULT=1.5`
and `REWARD_RISK=2.0` were picked because their *neighbourhood* was uniformly
profitable, not because they were the single best cell — the top cell
(`1.0×ATR`, `1:3`) was an isolated spike, which is the classic overfitting trap.
Both strategies still trail buy & hold in a strong bull market, which is normal
for a stop-based long-only system. Re-run the comparison on GLD and the FX ETFs
once your keys are in, before trusting any of it.

### Backtesting

```bash
python backtest.py --compare              # new vs old, every WATCHLIST symbol
python backtest.py --bars 2000            # more history
python backtest.py --slippage 0.0005      # harsher cost assumption
```

The backtester calls the same `strategy.analyze()` the live bot calls, on an
expanding window. Higher-timeframe bars are sliced by timestamp, so the
strategy only ever sees HTF bars that had already closed — no lookahead.

### Customizing

Edit `strategy.py`. `analyze()` returns a `Decision` with a signal plus the
stop and target it wants; the rest of the bot works off that.

Test a change before trading it:

```bash
python backtest.py --candles 1000 --trend 200 --buffer 0.001
```

The backtester replays the same bars the live bot would trade on, checks
stop-loss/take-profit against each bar's high/low, and compares the result
against buy & hold.

## Disclaimer

This is educational software provided as-is, with no warranty. You are solely
responsible for any trades it makes and any losses incurred.
