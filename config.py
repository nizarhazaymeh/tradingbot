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

# --- Broker selection: "alpaca" (US stocks + crypto) or "binance" (crypto) ---
BROKER = os.getenv("BROKER", "alpaca").strip().lower()

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


# --------------------------------------------------------------------------- #
# Watchlist — per-symbol timeframes
# --------------------------------------------------------------------------- #
# Format:  SYMBOL@ENTRY_TF[:HIGHER_TF], comma separated.
#   GLD@15m        -> gold, 15-minute bars, single timeframe
#   FXE@1h:4h      -> euro, entries on 1h, trend bias taken from 4h
# Leave WATCHLIST empty to fall back to SYMBOL + INTERVAL above.
WATCHLIST_RAW = os.getenv("WATCHLIST", "").strip()


def _parse_watchlist(raw: str):
    entries = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        htf = ""
        if "@" in item:
            sym, tf = item.split("@", 1)
            if ":" in tf:
                tf, htf = tf.split(":", 1)
        else:
            sym, tf = item, INTERVAL
        entries.append({
            "symbol": sym.strip().upper(),
            "entry_tf": tf.strip() or INTERVAL,
            "htf_tf": htf.strip(),
        })
    return entries


WATCHLIST = _parse_watchlist(WATCHLIST_RAW) or [
    {"symbol": s, "entry_tf": INTERVAL, "htf_tf": ""} for s in SYMBOLS
]
# Keep SYMBOLS in step so validation and logging see the real universe.
SYMBOLS = [w["symbol"] for w in WATCHLIST]
SYMBOL = SYMBOLS[0] if SYMBOLS else "GLD"


# --------------------------------------------------------------------------- #
# Strategy tuning (see strategy.py for what each filter is defending against)
# --------------------------------------------------------------------------- #
MA_TYPE = os.getenv("MA_TYPE", "ema").strip().lower()   # "ema" or "sma"
# Trend filter on the HIGHER timeframe (0 = off).
HTF_TREND_MA = int(os.getenv("HTF_TREND_MA", "50"))
# Trend strength gate: below ADX_MIN the market is ranging and crossovers whipsaw.
ADX_PERIOD = int(os.getenv("ADX_PERIOD", "14"))
ADX_MIN = float(os.getenv("ADX_MIN", "20"))
# ATR-based risk: stop = entry - ATR_STOP_MULT*ATR, target = entry + REWARD_RISK*risk.
USE_ATR_STOPS = _get_bool("USE_ATR_STOPS", True)
ATR_PERIOD = int(os.getenv("ATR_PERIOD", "14"))
ATR_STOP_MULT = float(os.getenv("ATR_STOP_MULT", "1.5"))
REWARD_RISK = float(os.getenv("REWARD_RISK", "2.0"))
# A crossover only counts if the MAs separate by this fraction of ATR.
CROSS_ATR_FRAC = float(os.getenv("CROSS_ATR_FRAC", "0.10"))
# Refuse to buy above this RSI (0 = off).
RSI_MAX = float(os.getenv("RSI_MAX", "75"))
# Ratchet the stop up by ATR as price advances (poll-protected positions only).
TRAIL_ATR = _get_bool("TRAIL_ATR", False)


def strategy_params():
    """Build the strategy Params from this config (imported lazily to avoid a cycle)."""
    from strategy import Params
    return Params(
        fast=FAST_SMA, slow=SLOW_SMA, ma_type=MA_TYPE,
        trend_ma=TREND_SMA, htf_trend_ma=HTF_TREND_MA,
        adx_period=ADX_PERIOD, adx_min=ADX_MIN,
        atr_period=ATR_PERIOD, atr_stop_mult=ATR_STOP_MULT,
        reward_risk=REWARD_RISK, cross_atr_frac=CROSS_ATR_FRAC,
        rsi_max=RSI_MAX, use_atr_stops=USE_ATR_STOPS,
        stop_loss_pct=STOP_LOSS_PCT, take_profit_pct=TAKE_PROFIT_PCT,
    )

# Signal-only mode: compute & notify signals using PUBLIC data, never trade.
# Works even with no API keys. Safest mode.
SIGNAL_ONLY = _get_bool("SIGNAL_ONLY", True)

# --- Risk management (fractions: 0.02 = 2%) ---
STOP_LOSS_PCT = float(os.getenv("STOP_LOSS_PCT", "0.02"))
TAKE_PROFIT_PCT = float(os.getenv("TAKE_PROFIT_PCT", "0.04"))

# --- Position sizing ---
# RISK_PCT > 0 sizes each trade so that hitting the stop-loss costs this
# fraction of account equity (e.g. 0.01 = risk 1% per trade). It overrides
# the fixed TRADE_QUOTE_AMOUNT. 0 = keep using the fixed amount.
RISK_PCT = float(os.getenv("RISK_PCT", "0"))
# Hard ceiling on a single position, as a fraction of equity.
MAX_POSITION_PCT = float(os.getenv("MAX_POSITION_PCT", "0.25"))

# --- Account-level safety rails ---
# Stop opening new trades once the day is down this fraction of equity.
MAX_DAILY_LOSS_PCT = float(os.getenv("MAX_DAILY_LOSS_PCT", "0.05"))
MAX_OPEN_POSITIONS = int(os.getenv("MAX_OPEN_POSITIONS", "5"))
# Attach broker-side stop-loss/take-profit legs (Alpaca stocks only, whole
# shares only). Protects the position between polls, even if the bot dies.
USE_BRACKET_ORDERS = _get_bool("USE_BRACKET_ORDERS", True)
# Accounts under $25k are capped at 3 day trades per 5 sessions (FINRA PDT).
# False = refuse a trade that would trip the rule.
ALLOW_PDT = _get_bool("ALLOW_PDT", False)

# --- Trade journal ---
TRADE_LOG = os.getenv("TRADE_LOG", "trades.csv").strip()

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
    if MA_TYPE not in ("ema", "sma"):
        raise SystemExit(f'MA_TYPE must be "ema" or "sma", got "{MA_TYPE}".')
    if USE_ATR_STOPS and ATR_STOP_MULT <= 0:
        raise SystemExit("ATR_STOP_MULT must be positive when USE_ATR_STOPS=true.")
    if REWARD_RISK <= 0:
        raise SystemExit("REWARD_RISK must be positive.")
    if not WATCHLIST:
        raise SystemExit("WATCHLIST (or SYMBOL) is empty — nothing to trade.")
    if TRADE_QUOTE_AMOUNT <= 0:
        raise SystemExit("TRADE_QUOTE_AMOUNT must be positive.")
    if RISK_PCT and not 0 < RISK_PCT < 1:
        raise SystemExit("RISK_PCT must be between 0 and 1 (e.g. 0.01 = 1%).")
    if RISK_PCT and STOP_LOSS_PCT <= 0:
        raise SystemExit("RISK_PCT sizing needs STOP_LOSS_PCT > 0 to size against.")
    if not 0 < MAX_POSITION_PCT <= 1:
        raise SystemExit("MAX_POSITION_PCT must be between 0 and 1.")
    if MAX_DAILY_LOSS_PCT and not 0 < MAX_DAILY_LOSS_PCT < 1:
        raise SystemExit("MAX_DAILY_LOSS_PCT must be between 0 and 1.")
