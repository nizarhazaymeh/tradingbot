"""Loads and validates configuration from the .env file."""
import os
from dotenv import load_dotenv

load_dotenv()


def _get_bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


API_KEY = os.getenv("BINANCE_API_KEY", "").strip()
API_SECRET = os.getenv("BINANCE_API_SECRET", "").strip()

# --- Broker selection: "binance" (crypto) or "alpaca" (US stocks + crypto) ---
BROKER = os.getenv("BROKER", "binance").strip().lower()

# --- Alpaca credentials (https://app.alpaca.markets -> Home -> API Keys) ---
# Paper and live keys are separate accounts; ALPACA_PAPER picks the endpoint.
ALPACA_API_KEY = os.getenv("ALPACA_API_KEY", "").strip()
ALPACA_API_SECRET = os.getenv("ALPACA_API_SECRET", "").strip()
ALPACA_PAPER = _get_bool("ALPACA_PAPER", True)
# "iex" is included free; "sip" (full consolidated tape) needs a paid plan.
ALPACA_FEED = os.getenv("ALPACA_FEED", "iex").strip().lower()

USE_TESTNET = _get_bool("USE_TESTNET", True)
ENABLE_TRADING = _get_bool("ENABLE_TRADING", False)

# One or more symbols, comma-separated, e.g. "BTCUSDT,SOLUSDT".
SYMBOLS = [s.strip().upper() for s in os.getenv("SYMBOL", "BTCUSDT").split(",") if s.strip()]
SYMBOL = SYMBOLS[0] if SYMBOLS else "BTCUSDT"  # kept for backwards compatibility
TRADE_QUOTE_AMOUNT = float(os.getenv("TRADE_QUOTE_AMOUNT", "15"))
INTERVAL = os.getenv("INTERVAL", "1h").strip()

FAST_SMA = int(os.getenv("FAST_SMA", "9"))
SLOW_SMA = int(os.getenv("SLOW_SMA", "21"))

# Signal-quality filters (0 = off). See backtest.py for why these help.
TREND_SMA = int(os.getenv("TREND_SMA", "200"))      # only BUY above this SMA
CROSS_BUFFER = float(os.getenv("CROSS_BUFFER", "0.001"))  # min crossover margin

POLL_SECONDS = int(os.getenv("POLL_SECONDS", "60"))

# Signal-only mode: compute & notify signals using PUBLIC data, never trade.
# Works even with no API keys. Safest mode.
SIGNAL_ONLY = _get_bool("SIGNAL_ONLY", True)

# --- Risk management (fractions: 0.02 = 2%) ---
STOP_LOSS_PCT = float(os.getenv("STOP_LOSS_PCT", "0.02"))
TAKE_PROFIT_PCT = float(os.getenv("TAKE_PROFIT_PCT", "0.04"))

# --- Telegram notifications ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

# --- Email notifications (SMTP) ---
SMTP_HOST = os.getenv("SMTP_HOST", "").strip()
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "").strip()
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "").strip()
EMAIL_FROM = os.getenv("EMAIL_FROM", "").strip()
EMAIL_TO = os.getenv("EMAIL_TO", "").strip()


def validate() -> None:
    """Fail fast with a clear message if config is wrong."""
    if BROKER not in ("binance", "alpaca"):
        raise SystemExit(f'BROKER must be "binance" or "alpaca", got "{BROKER}".')

    if BROKER == "alpaca":
        # Alpaca authenticates its MARKET DATA endpoints too, so keys are
        # required even in signal-only mode.
        if not ALPACA_API_KEY or not ALPACA_API_SECRET:
            raise SystemExit(
                "Missing ALPACA_API_KEY / ALPACA_API_SECRET. Generate them at "
                "https://app.alpaca.markets (Home -> API Keys) and put them in .env. "
                "Alpaca requires keys even for market data."
            )
        if ALPACA_FEED not in ("iex", "sip", "otc", "boats"):
            raise SystemExit(f'ALPACA_FEED must be iex/sip/otc/boats, got "{ALPACA_FEED}".')
    else:
        # Keys are only required when we actually touch the account (trading or
        # reading balances). Signal-only mode uses public data and needs nothing.
        if not SIGNAL_ONLY and (not API_KEY or not API_SECRET):
            raise SystemExit(
                "Missing BINANCE_API_KEY / BINANCE_API_SECRET. "
                "Copy .env.example to .env and fill them in (or set SIGNAL_ONLY=true)."
            )
    if FAST_SMA >= SLOW_SMA:
        raise SystemExit("FAST_SMA must be smaller than SLOW_SMA.")
    if TRADE_QUOTE_AMOUNT <= 0:
        raise SystemExit("TRADE_QUOTE_AMOUNT must be positive.")
