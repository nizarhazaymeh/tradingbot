# SMA Trading Bot — Binance & Alpaca

A simple, safe-by-default trading bot using a moving-average (SMA) crossover
strategy. It runs against either broker, selected with `BROKER` in `.env`:

| `BROKER` | Market | Endpoint |
|---|---|---|
| `binance` (default) | Spot crypto | Binance / Binance Testnet |
| `alpaca` | US stocks **and** crypto | `paper-api.alpaca.markets` / `api.alpaca.markets` |

`strategy.py` is shared — only the execution layer (`broker.py`) differs.

> ⚠️ **Trading is risky. This bot can lose money. Test on the Testnet first and
> never trade more than you can afford to lose.**

## How it works

- Every `POLL_SECONDS` it fetches recent candles for `SYMBOL`.
- It computes a fast and slow SMA on closed candles.
- **Golden cross** (fast crosses above slow) → BUY (open position).
- **Death cross** (fast crosses below slow) → SELL.
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
| `SYMBOL` | `BTCUSDT` (Binance), `AAPL` or `BTC/USD` (Alpaca) |
| `TRADE_QUOTE_AMOUNT` | Quote currency to spend per BUY (e.g. 15 USDT) |
| `INTERVAL` | Candle size: `1m`, `5m`, `1h`, `4h`, `1d`... |
| `FAST_SMA` / `SLOW_SMA` | SMA periods (fast must be < slow) |
| `POLL_SECONDS` | How often to re-check the market |
| `USE_TESTNET` | Binance: `true` = testnet, `false` = live |
| `ENABLE_TRADING` | `false` = paper, `true` = send real orders |
| `BROKER` | `binance` or `alpaca` |
| `ALPACA_API_KEY` / `ALPACA_API_SECRET` | Alpaca credentials |
| `ALPACA_PAPER` | `true` = paper account (fake money), `false` = real money |
| `ALPACA_FEED` | `iex` (free) or `sip` (paid) |

## Customizing the strategy

Edit `strategy.py`. As long as `generate_signal()` returns `"BUY"`, `"SELL"`,
or `"HOLD"`, the rest of the bot works unchanged.

## Disclaimer

This is educational software provided as-is, with no warranty. You are solely
responsible for any trades it makes and any losses incurred.
