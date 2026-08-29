"""Loads and validates configuration from the .env file."""
import os
from dotenv import load_dotenv

load_dotenv()


def _get_bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


# --- Alpaca credentials (https://app.alpaca.markets -> Home -> API Keys) ---
# Paper and live keys are separate accounts; ALPACA_PAPER picks the endpoint.
ALPACA_API_KEY = os.getenv("ALPACA_API_KEY", "").strip()
# ALPACA_SECRET_KEY is what the official `alpaca` CLI uses; accept either name
# so one .env serves both the CLI and this bot.
ALPACA_API_SECRET = (os.getenv("ALPACA_API_SECRET")
                     or os.getenv("ALPACA_SECRET_KEY") or "").strip()
ALPACA_PAPER = _get_bool("ALPACA_PAPER", True)
# "iex" is included free; "sip" (full consolidated tape) needs a paid plan.
ALPACA_FEED = os.getenv("ALPACA_FEED", "iex").strip().lower()

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

# --- Confluence: how many independent methods must agree before entering ---
# Votes: MA cross (2), above trend MA (1), HTF trend (2), structure (1),
# demand zone (2), fib golden pocket (2), ADX (1), RSI (1), volume (1) = 12.
MIN_CONFLUENCE = int(os.getenv("MIN_CONFLUENCE", "6"))
# How near a supply/demand zone still counts as "at" it, in ATR.
ZONE_PAD_ATR = float(os.getenv("ZONE_PAD_ATR", "0.5"))
# Require an MA crossover as the trigger (false = any high-scoring bar can enter).
REQUIRE_TREND = _get_bool("REQUIRE_TREND", True)

# --- Scaled exits: TP1 / TP2 / TP3 ---
# Fraction of the position closed at each target; must sum to 1.0.
TP1_PCT = float(os.getenv("TP1_PCT", "0.5"))
TP2_PCT = float(os.getenv("TP2_PCT", "0.3"))
TP3_PCT = float(os.getenv("TP3_PCT", "0.2"))
# TP1 must pay at least this multiple of the risk, else the trade isn't worth it.
MIN_TP1_R = float(os.getenv("MIN_TP1_R", "1.0"))
# Stop distance bounds, in ATR: never wider than the first, never tighter than
# the second (anything tighter is inside normal noise).
MAX_STOP_ATR = float(os.getenv("MAX_STOP_ATR", "3.0"))
MIN_STOP_ATR = float(os.getenv("MIN_STOP_ATR", "0.5"))
# Move the stop to breakeven / start trailing once this many targets are hit.
BREAKEVEN_AFTER = int(os.getenv("BREAKEVEN_AFTER", "1"))
TRAIL_AFTER = int(os.getenv("TRAIL_AFTER", "2"))


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
        min_confluence=MIN_CONFLUENCE, zone_pad_atr=ZONE_PAD_ATR,
        require_trend=REQUIRE_TREND,
        tp_fractions=(TP1_PCT, TP2_PCT, TP3_PCT), min_tp1_r=MIN_TP1_R,
        max_stop_atr=MAX_STOP_ATR, min_stop_atr=MIN_STOP_ATR,
        breakeven_after=BREAKEVEN_AFTER, trail_after=TRAIL_AFTER,
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
# Don't open a new position this close to the US closing bell — the stop and
# target would never get a chance to work. Also covers early-close half days.
MIN_MINUTES_TO_CLOSE = float(os.getenv("MIN_MINUTES_TO_CLOSE", "15"))
# Use only 09:30-16:00 ET bars. Extended-hours ETF bars are thin (hundreds of
# shares) and carry bad prints that wreck ATR and swing detection.
RTH_ONLY = _get_bool("RTH_ONLY", True)
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
    # Alpaca authenticates its MARKET DATA endpoints too, so keys are required
    # even in signal-only mode.
    if not ALPACA_API_KEY or not ALPACA_API_SECRET:
        raise SystemExit(
            "Missing ALPACA_API_KEY / ALPACA_API_SECRET. Generate them at "
            "https://app.alpaca.markets (Home -> API Keys) and put them in .env. "
            "Alpaca requires keys even for market data."
        )
    if ALPACA_FEED not in ("iex", "sip", "otc", "boats"):
        raise SystemExit(f'ALPACA_FEED must be iex/sip/otc/boats, got "{ALPACA_FEED}".')
    if FAST_SMA >= SLOW_SMA:
        raise SystemExit("FAST_SMA must be smaller than SLOW_SMA.")
    if MA_TYPE not in ("ema", "sma"):
        raise SystemExit(f'MA_TYPE must be "ema" or "sma", got "{MA_TYPE}".')
    if USE_ATR_STOPS and ATR_STOP_MULT <= 0:
        raise SystemExit("ATR_STOP_MULT must be positive when USE_ATR_STOPS=true.")
    if REWARD_RISK <= 0:
        raise SystemExit("REWARD_RISK must be positive.")
    if abs(TP1_PCT + TP2_PCT + TP3_PCT - 1.0) > 1e-6:
        raise SystemExit(
            f"TP1_PCT + TP2_PCT + TP3_PCT must sum to 1.0, got "
            f"{TP1_PCT + TP2_PCT + TP3_PCT:.3f}.")
    if MIN_STOP_ATR >= MAX_STOP_ATR:
        raise SystemExit("MIN_STOP_ATR must be smaller than MAX_STOP_ATR.")
    if not 0 <= MIN_CONFLUENCE <= 12:
        raise SystemExit("MIN_CONFLUENCE must be between 0 and 12.")
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
