"""Loads sniper configuration from the project .env."""
import os
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))


def _f(name, default):
    return float(os.getenv(name, default))


def _i(name, default):
    return int(os.getenv(name, default))


def _b(name, default):
    v = os.getenv(name)
    return default if v is None else v.strip().lower() in ("1", "true", "yes", "on")


RPC_HTTP = os.getenv("SOLANA_RPC_HTTP", "").strip()
RPC_WS = os.getenv("SOLANA_RPC_WS", "").strip()
WALLET_PRIVATE_KEY = os.getenv("WALLET_PRIVATE_KEY", "").strip()

DRY_RUN = _b("SNIPER_DRY_RUN", True)

BUY_AMOUNT_SOL = _f("BUY_AMOUNT_SOL", "0.03")
MAX_DAILY_SPEND_SOL = _f("MAX_DAILY_SPEND_SOL", "0.3")
MIN_SOL_RESERVE = _f("MIN_SOL_RESERVE", "0.01")
SLIPPAGE_PCT = _f("SLIPPAGE_PCT", "0.15")
PRIORITY_FEE_SOL = _f("PRIORITY_FEE_SOL", "0.0005")

# --- Cost model (keeps dry-run P/L honest; also applied to live estimates) ---
FEE_PCT = _f("PUMP_FEE_PCT", "0.01")                       # pump.fun swap fee, charged each way
DRY_RUN_SLIPPAGE_PCT = _f("DRY_RUN_SLIPPAGE_PCT", "0.05")  # simulated entry slippage (momentum buys fill above the observed price)

TAKE_PROFIT_X = _f("TAKE_PROFIT_X", "2.0")      # at this multiple, sell TP_SELL_PCT and trail the rest
TP_SELL_PCT = _f("TP_SELL_PCT", "0.5")          # fraction sold at TAKE_PROFIT_X (1.0 = full exit)
TAKE_PROFIT_USD = _f("TAKE_PROFIT_USD", "0.0")  # if >0, sell at this $ profit (overrides X)
TRAIL_PCT = _f("TRAIL_PCT", "0.20")             # trailing stop: sell if price drops this % from peak
MIN_CURVE_SOL = _f("MIN_CURVE_SOL", "5.0")      # survivor filter: coin must hold >= this real SOL
MIN_SCORE = _i("MIN_SCORE", "60")               # only buy coins ranked >= this (0-100)
# SNIPER_STOP_LOSS_PCT is preferred — plain STOP_LOSS_PCT collides with the
# Binance bot's variable of the same name in the shared .env.
STOP_LOSS_PCT = _f("SNIPER_STOP_LOSS_PCT", os.getenv("STOP_LOSS_PCT", "0.5"))
MAX_HOLD_SECONDS = _i("MAX_HOLD_SECONDS", "300")

MAX_CREATOR_HOLD_PCT = _f("MAX_CREATOR_HOLD_PCT", "0.20")
MIN_OTHER_HOLDERS = _i("MIN_OTHER_HOLDERS", "5")

# --- Observation window (don't buy blind at t=0; wait for real buyers) ---
OBSERVE_SECONDS = _i("OBSERVE_SECONDS", "25")     # watch this long before deciding
MIN_SOL_MOMENTUM = _f("MIN_SOL_MOMENTUM", "1.5")  # min real SOL bought in window to buy
MAX_CONCURRENT = _i("MAX_CONCURRENT", "3")        # max positions held at once
POLL_SECONDS = _f("SNIPER_POLL_SECONDS", "2")     # price poll interval
