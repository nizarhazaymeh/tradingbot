"""Configuration. Everything comes from .env — nothing is hardcoded."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _s(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


def _f(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, "") or default)
    except ValueError:
        return default


def _i(key: str, default: int) -> int:
    try:
        return int(float(os.getenv(key, "") or default))
    except ValueError:
        return default


def _b(key: str, default: bool) -> bool:
    v = os.getenv(key, "").strip().lower()
    return default if not v else v in ("1", "true", "yes", "on")


# ---------------------------------------------------------------- accounts
# ACCOUNT=dev  -> sandbox (break things)
# ACCOUNT=comp -> the judged account. Guarded; see safety.py.
ACCOUNT = _s("ACCOUNT", "dev").lower()

if ACCOUNT == "comp":
    API_KEY = _s("COMP_ALPACA_API_KEY")
    SECRET_KEY = _s("COMP_ALPACA_SECRET_KEY")
    ACCOUNT_NUMBER = _s("COMP_ACCOUNT_NUMBER")
else:
    API_KEY = _s("ALPACA_API_KEY")
    SECRET_KEY = _s("ALPACA_SECRET_KEY")
    ACCOUNT_NUMBER = _s("DEV_ACCOUNT_NUMBER")

# Paper only. There is no live path in this codebase, by design.
TRADE_BASE = "https://paper-api.alpaca.markets"
DATA_BASE = "https://data.alpaca.markets"

# OPRA is not entitled on this account (403 "OPRA agreement is not signed").
OPTIONS_FEED = _s("ALPACA_OPTIONS_FEED", "indicative")
STOCK_FEED = _s("ALPACA_STOCK_FEED", "iex")

# ---------------------------------------------------------------- LLM
FEATHERLESS_API_KEY = _s("FEATHERLESS_API_KEY")
FEATHERLESS_BASE_URL = _s("FEATHERLESS_BASE_URL", "https://api.featherless.ai/v1")
FEATHERLESS_MODEL = _s("FEATHERLESS_MODEL", "zai-org/GLM-5.2")
LLM_MAX_TOKENS = _i("LLM_MAX_TOKENS", 700)
LLM_TIMEOUT = _i("LLM_TIMEOUT", 90)

# ---------------------------------------------------------------- universe
# Scanned 19 optionable names on 1 Sep for variance risk premium and chain depth.
# Eleven qualified; we were trading four, one of which (IBIT) had NEGATIVE VRP at
# -3.6% — implied volatility BELOW realised, so there was no premium to sell.
#
# The gain from expanding is diversification, not more risk. A premium-selling
# book's real danger is a correlated shock rather than any individual position,
# since each is defined-risk — so the same 4% heat budget spread across ten
# underlyings is meaningfully safer than across four.
#
# Measured VRP: META +10.5% AAPL +9.3% IWM +7.8% SMH +7.3% SPY +6.8%
#               MSFT +6.1% QQQ +6.0% TSLA +5.5% DIA +5.3% AMZN +4.9% GOOGL +4.4%
# Excluded for negative VRP: NVDA -9.4%, IBIT -3.6%, GLD -2.6%
# Excluded for no edge: AMD +0.1%.  Excluded for thin chains: XLF, XLE, TLT, NFLX.
# TSLA held back deliberately: 47% IV is genuine premium but the fattest tails
# in the set, and the EV model's normal-distribution assumption is weakest there.
#
# No earnings inside this window — mega-cap Q2 reports landed early August, and
# the next round is late October.
UNIVERSE = [s.strip().upper() for s in _s(
    "UNIVERSE", "SPY,QQQ,IWM,DIA,SMH,AAPL,MSFT,META,AMZN,GOOGL").split(",") if s.strip()]

# ------------------------------------------------------------------- crypto
# Two facts decide everything here.
#
# 1. Alpaca lists NO options on crypto spot. BTC/USD returns zero option
#    contracts, so the variance-risk-premium edge the rest of this agent runs on
#    does not exist here. What is left is direction. Crypto ETFs (IBIT, and BTC
#    the Grayscale trust) DO have options and are handled by the normal options
#    path — they are in UNIVERSE above, not here.
#
# 2. Spot has no long wing, so a position is not defined-risk the way a vertical
#    spread is. Sizing is therefore bounded twice: by the stop, and by notional.
#    CRYPTO_MAX_NOTIONAL_PCT is the one that matters — it is what the account
#    loses if the position goes to zero and the stop never fills, which is the
#    honest worst case for spot. See agent/crypto.py.
#
# OFF until the backtest justifies it. scripts/backtest_crypto.py is the
# measurement; docs/BACKTEST.md Part 8 is the result.
CRYPTO_ENABLED = _b("CRYPTO_ENABLED", False)
CRYPTO_UNIVERSE = [s.strip().upper() for s in
                   _s("CRYPTO_UNIVERSE", "BTC/USD,ETH/USD").split(",") if s.strip()]
CRYPTO_RISK_PER_TRADE_PCT = _f("CRYPTO_RISK_PER_TRADE_PCT", 0.004)   # if the stop fills
CRYPTO_MAX_NOTIONAL_PCT = _f("CRYPTO_MAX_NOTIONAL_PCT", 0.05)        # if it does not
CRYPTO_MAX_POSITIONS = _i("CRYPTO_MAX_POSITIONS", 2)
CRYPTO_MAX_HEAT_PCT = _f("CRYPTO_MAX_HEAT_PCT", 0.012)               # summed stop risk
CRYPTO_ATR_PERIOD = _i("CRYPTO_ATR_PERIOD", 14)
CRYPTO_STOP_BUFFER_ATR = _f("CRYPTO_STOP_BUFFER_ATR", 0.5)  # stop this far under the level
CRYPTO_MAX_STOP_ATR = _f("CRYPTO_MAX_STOP_ATR", 3.0)        # else the level is too far
CRYPTO_TARGET_R = _f("CRYPTO_TARGET_R", 2.0)
CRYPTO_MAX_SIGNAL_AGE = _i("CRYPTO_MAX_SIGNAL_AGE", 10)     # bars since the retest
CRYPTO_TIME_STOP_HOURS = _i("CRYPTO_TIME_STOP_HOURS", 240)  # 10 days

# ---------------------------------------------------------------- risk
STARTING_EQUITY = _f("STARTING_EQUITY", 100_000.0)
# Wider spreads measured better across all four regimes (PF 4.22 at $8 wide vs
# 2.99 at $5), because they collect proportionally more credit. At $400 the
# optimiser could never afford one, so the budget was raised enough to let it
# choose. Sizing still uses THEORETICAL max loss, not the observed average loss —
# an overnight gap can realise the full amount even though the exit loop
# historically capped losses near -$300.
RISK_PER_TRADE_PCT = _f("RISK_PER_TRADE_PCT", 0.0055)    # 0.55% -> $550
PORTFOLIO_HEAT_PCT = _f("PORTFOLIO_HEAT_PCT", 0.0400)    # 4.00% -> $4,000
MAX_PER_UNDERLYING_PCT = _f("MAX_PER_UNDERLYING_PCT", 0.0120)
# The per-expiry cap exists to stop concentration ACROSS expiries. But the
# deadline leaves exactly one usable expiry — anything later than 4 Sep is still
# open when the account is judged — so a cap below PORTFOLIO_HEAT_PCT just
# becomes a lower total limit. Observed live 1 Sep: deployment stalled at 2.5%
# with the 4% heat budget two-thirds unused. Aligned with the heat cap so heat
# is the single binding constraint.
MAX_PER_EXPIRY_PCT = _f("MAX_PER_EXPIRY_PCT", 0.0400)
# Raised with the universe: ten underlyings at two positions each is 20 possible,
# and the 4% heat cap is what should bind, not an arbitrary count that forces all
# the risk into a handful of names.
MAX_OPEN_POSITIONS = _i("MAX_OPEN_POSITIONS", 14)
# The heat cap limits RISK per underlying but not CORRELATION or churn. Observed
# live 1 Sep: three QQQ condors at nearly identical strikes — one bet taken three
# times, paying the bid/ask spread three times for no added diversification.
MAX_POSITIONS_PER_UNDERLYING = _i("MAX_POSITIONS_PER_UNDERLYING", 2)
MAX_ORDERS_PER_HOUR = _i("MAX_ORDERS_PER_HOUR", 12)

# How long an unfilled order may sit at the broker before the agent cancels it.
#
# Nothing used to cancel a working order — the only cancel in the codebase was
# inside a halt — so an mleg limit that never filled stayed until the session
# ended. That is not merely untidy. Alpaca rejects a new order that trades the
# OPPOSITE side of a contract a working order already touches:
#
#   403 potential wash trade detected ... opposite side market/stop order exists
#
# On 31 Aug a SPY condor sat unfilled at -0.34 from 20:44, and every later SPY
# condor overlapped its strikes, so the agent re-proposed and was re-rejected
# every cycle — spending its MAX_ORDERS_PER_HOUR budget on rejections while
# holding the strikes hostage. It had deadlocked itself out of an underlying.
#
# Longer than one cycle, so an order gets a full interval to fill on its own.
# Only orders with ZERO fills are cancelled; a partial fill is a real position
# and is left alone, the same way monitor.reconcile() never auto-acts on one.
ORDER_TTL_SEC = _i("ORDER_TTL_SEC", 420)        # 0 disables

# How many consecutive cycles a tracked structure must be absent from the broker
# before its row is retired.
#
# monitor.reconcile() has always computed ghosts exactly — tracked structures the
# broker holds NO leg of — and then only logged them. Nothing retired the row, so
# a structure that filled and later left the book stayed "open" forever, and
# g_no_duplicate refused to re-enter it. On 31 Aug an IWM bear_put that the
# broker had not held since 14:35 blocked every IWM proposal for the rest of the
# session, six rejections and counting. A restart does not help: the row is in
# SQLite, not in memory.
#
# Requiring consecutive cycles is what makes this safe against a race — a fill
# that has not yet appeared in /v2/positions reads as a ghost for one cycle. The
# streak is in memory, so a restart re-observes before acting, which is the
# direction we want to be wrong in.
#
# A partial is still never auto-acted on. Only FULL absence counts.
GHOST_RETIRE_CYCLES = _i("GHOST_RETIRE_CYCLES", 2)   # 0 disables

DAILY_DRAWDOWN_LIMIT = _f("DAILY_DRAWDOWN_LIMIT", 0.02)  # -2%
TOTAL_DRAWDOWN_LIMIT = _f("TOTAL_DRAWDOWN_LIMIT", 0.06)  # -6%

# ---------------------------------------------------------------- contracts
# Swept across 4 regimes. 2 DTE is not merely worse, it is destructive — gamma
# near expiry means a small adverse move blows through the short strike before
# any exit can react:
#   2 DTE -> 60% win, PF 0.29, -$1,085     4 DTE -> 80% win, PF 2.47, +$958
#   3 DTE -> 78% win, PF 2.46,   +$638     7 DTE -> 81% win, PF 1.85, +$745
MIN_DTE = _i("MIN_DTE", 3)          # 0-2 DTE excluded: no Greeks / unstable gamma
TARGET_DTE = _i("TARGET_DTE", 4)    # preferred holding window
MAX_DTE = _i("MAX_DTE", 10)
MIN_OPEN_INTEREST = _i("MIN_OPEN_INTEREST", 500)
MAX_SPREAD_PCT = _f("MAX_SPREAD_PCT", 0.15)     # (ask-bid)/mid
# A percentage-only spread test wrongly rejects cheap far-OTM wings: a 50% spread
# on a $0.04 option is 2 cents. Accept if EITHER the % limit OR this absolute
# cents limit is satisfied.
MAX_SPREAD_ABS = _f("MAX_SPREAD_ABS", 0.06)
MAX_QTY_VS_OI = _f("MAX_QTY_VS_OI", 0.05)
IV_MIN, IV_MAX = _f("IV_MIN", 0.01), _f("IV_MAX", 5.0)

# ---------------------------------------------------------------- regime
# When IV-rank history exists we use rank; otherwise implied-vs-realised.
IV_RANK_RICH = _f("IV_RANK_RICH", 0.60)
# IV rank needs a real range to mean anything. Below this many readings the
# regime classifier falls back to comparing implied against realised vol —
# a working proxy — instead of a rank invented from two data points.
MIN_IV_HISTORY = _i("MIN_IV_HISTORY", 20)
IV_RANK_CHEAP = _f("IV_RANK_CHEAP", 0.35)
IV_OVER_RV_RICH = _f("IV_OVER_RV_RICH", 1.10)   # implied >= 1.10x realised -> rich
IV_OVER_RV_CHEAP = _f("IV_OVER_RV_CHEAP", 0.95)
TREND_Z_MIN = _f("TREND_Z_MIN", 1.0)

# ---------------------------------------------------------------- structure
SHORT_DELTA_CONDOR = _f("SHORT_DELTA_CONDOR", 0.16)
# Delta ~= probability of finishing ITM, so delta 0.16 ~= the 1-sigma strike.
# Keep these consistent with MIN_SHORT_SIGMA or every proposal gets rejected.
SHORT_DELTA_CREDIT = _f("SHORT_DELTA_CREDIT", 0.16)
LONG_DELTA_DEBIT = _f("LONG_DELTA_DEBIT", 0.50)
SHORT_DELTA_DEBIT = _f("SHORT_DELTA_DEBIT", 0.28)
WING_STRIKES = _i("WING_STRIKES", 5)            # default wing width, in strike increments
# Search space the optimiser enumerates each cycle
WIDTH_STRIKES = [int(x) for x in _s("WIDTH_STRIKES", "2,3,4,5,8").split(",") if x.strip()]
CONDOR_SIGMAS = [float(x) for x in _s("CONDOR_SIGMAS", "1.0,1.25,1.5,1.75").split(",") if x.strip()]
# Iron condors profit from the underlying staying in a range. Backtesting across
# four market regimes (277 trades) showed they collapse when volatility is high:
#   realised vol ~10%  -> profit factor 1.3
#   realised vol ~21%  -> profit factor 0.9
#   realised vol ~46%  -> profit factor 0.28   (42% win rate)
# So we refuse to open condors above this realised-vol ceiling. Directional
# credit spreads, which do not need the price to sit still, are unaffected.
MAX_VOL_FOR_CONDOR = _f("MAX_VOL_FOR_CONDOR", 0.18)
# In elevated vol, push condor short strikes further out before giving up.
CONDOR_SIGMA_VOL_BOOST = _f("CONDOR_SIGMA_VOL_BOOST", 0.5)
CREDIT_DELTAS = [float(x) for x in _s("CREDIT_DELTAS", "0.10,0.14,0.18,0.22").split(",") if x.strip()]
DEBIT_LONG_DELTAS = [float(x) for x in _s("DEBIT_LONG_DELTAS", "0.40,0.50,0.60").split(",") if x.strip()]
MIN_CREDIT_RATIO = _f("MIN_CREDIT_RATIO", 0.04) # sanity floor only; EV is the real test

# ---------------------------------------------------------------- expectancy
# Vanilla spreads price at ~fair value, so the edge must come from our view
# disagreeing with the market's delta-implied probabilities.
MAX_VIEW_TILT = _f("MAX_VIEW_TILT", 0.35)       # max probability shift at full conviction
MIN_EV_RATIO = _f("MIN_EV_RATIO", 0.02)         # require EV >= 2% of capital at risk

# FLATTEN_AT closes the book before judging, so late trades are held for a
# fraction of the option's life while paying 100% of the round-trip bid/ask.
# The carry earned over the ACTUAL hold must beat that cost with margin.
HOLDING_COST_MULTIPLE = _f("HOLDING_COST_MULTIPLE", 1.5)
MIN_HOLDING_DAYS = _f("MIN_HOLDING_DAYS", 1.0)  # directional trades need time to work
MIN_SHORT_SIGMA = _f("MIN_SHORT_SIGMA", 0.90)   # short strike >= 0.9σ from spot

# OFF, by measurement. See docs/BACKTEST.md Part 7.
#
# A ranking preference for structures whose short strikes sit behind a level
# price broke, returned to, and respected (levels.retest_barrier). Part 6 found
# that property separates outcomes sharply as a trade FILTER — +$3,255 (PF 1.98)
# against -$554 (PF 0.91) — and it shipped at 0.005 as a tie-break instead,
# because the filter inverted in one of four windows.
#
# scripts/backtest_bonus.py then ran the real propose() over all four windows
# with the knob on and off. At 0.005 it changed the chosen structure in 0 of 47
# entries: the EV gaps between candidates are far larger than the bonus, so it
# never decided anything. The cheapest flip in the sample needs 0.026 and the
# median needs 0.254. Turned up far enough to bite, it LOSES:
#
#   0.005 / 0.010 / 0.020   0 entries changed        $0   inert
#   0.050                   4 entries changed     -$250
#   0.100                   5 entries changed     -$533
#   0.250                   7 entries changed     -$427
#
# So the honest setting is zero. A filter-level finding did not survive being
# expressed as a candidate-level preference — the barrier is largely a property
# of the ENTRY, and propose() only ever chooses between structures at one entry.
#
# Everything else about breaks stays live: they are computed, logged on every
# proposal as `retest_levels`, and passed to the LLM as context. Only the
# influence on selection is off. tests/test_strategy_selection.py pins this at 0
# so it cannot be turned on again without a measurement.
RETEST_BARRIER_BONUS = _f("RETEST_BARRIER_BONUS", 0.0)   # in EV-ratio points
CONSERVATIVE_SIGMA = _f("CONSERVATIVE_SIGMA", 1.6)  # wider condor when no regime edge
MAX_ABS_NET_DELTA = _f("MAX_ABS_NET_DELTA", 0.35)  # per-unit directional cap
MAX_PORTFOLIO_DELTA = _f("MAX_PORTFOLIO_DELTA", 3.0)  # aggregate, per $100k equity
# The strategy earns from time decay, so the BOOK must stay theta-positive.
# Directional debit spreads are theta-negative and legitimate in moderation, but
# observed live 1 Sep: two IWM bear_puts plus an IBIT bull_call dragged -$108/day
# against +$143/day of credit income, leaving net theta at +$36 — the carry that
# is supposed to pay for the bid/ask had been mostly spent on directional bets.
MIN_PORTFOLIO_THETA = _f("MIN_PORTFOLIO_THETA", 60.0)   # dollars/day per $100k
MAX_DEBIT_RATIO = _f("MAX_DEBIT_RATIO", 0.60)   # debit must be <= 60% of width

# ---------------------------------------------------------------- exits
# Swept across 4 market regimes (56 trades each). Closing winners EARLIER beat
# holding for more of the max gain — the last 15% of a credit spread's profit
# takes the most time and carries the most tail risk:
#   close at 25% -> 84% win, PF 2.92     close at 50% -> 80% win, PF 2.47
#   close at 35% -> 84% win, PF 3.04 ←   close at 80% -> 71% win, PF 1.68
TAKE_PROFIT_CREDIT = _f("TAKE_PROFIT_CREDIT", 0.35)   # % of max gain
# A debit spread's max gain is several multiples of its cost — IWM live 1 Sep:
# \$498 risked against a \$2,702 max gain. Taking profit at a % of MAX GAIN
# therefore demands a ~4x return and never fires, leaving the position to ride to
# expiry ungoverned. So debit exits are measured against the PREMIUM PAID, which
# is both the standard convention and actually reachable.
TAKE_PROFIT_DEBIT_MULT = _f("TAKE_PROFIT_DEBIT_MULT", 1.00)   # +100% of debit paid
TAKE_PROFIT_DEBIT = _f("TAKE_PROFIT_DEBIT", 0.75)             # legacy, unused
STOP_CREDIT_MULT = _f("STOP_CREDIT_MULT", 1.50)       # -150% of credit
STOP_DEBIT_PCT = _f("STOP_DEBIT_PCT", 0.60)
DELTA_BREACH = _f("DELTA_BREACH", 0.40)
TIME_STOP_DTE = _i("TIME_STOP_DTE", 1)

# ---- decay harvest ---------------------------------------------------------
# The strategy's whole thesis is "be short overpriced options". The exit rules
# enforced that for credit structures but not for debit ones: a long-premium
# spread had only a profit-multiple target and a DTE-1 time stop, so an ATM
# debit spread could sit at DTE 3 bleeding time value with no rule to sell it.
#
# HARVEST compares the market's mark against what the REMAINING TIME is worth
# priced at realised vol. When the market overpays for time we still hold, we
# sell it — the same trade we make on the short side, in the other direction.
# 🔴 OFF BY DEFAULT — the idea is sound and the evidence is not.
#
# Built on 1 Sep off one live case: two IWM bear put spreads, 80% time value,
# implied 20.8% against realised 11.7%, needing a 2.4-sigma fall to reach max
# value. Selling them was right and banked +$406. But one case is not evidence,
# so it was A/B'd over 120 historical debit structures across 12 expiry cycles
# (scripts/validate_harvest.py):
#
#   6 cycles  +$1,160   <- the window this was first measured on
#  12 cycles    -$276
#
# The first number was a window artifact: six weeks happened to include the one
# good cycle (24 Jul, +$1,514) and exclude the worst (12 Jun, -$1,518). Firing
# by cycle: 4 positive, 4 negative.
#
# Threshold sweeps do not rescue it. On an absolute floor only MIN_EDGE=150 is
# positive (+$592) and it fires 3 times in 120 — fitting a threshold to three
# samples, not finding an edge. On a relative floor every setting from 10% to
# 50% of the mark is WORSE than off. A trend veto was tried and made it worse
# still (see the note below).
#
# One caveat worth keeping: all 23 replay firings were bull_calls, so the
# structure that motivated the rule — a bear put spread — was never exercised
# historically. The rule is therefore unproven rather than disproven for that
# case. Unproven is still not a reason to run it on a live account.
#
# Set HARVEST_ENABLED=1 to turn it back on.
HARVEST_ENABLED = _b("HARVEST_ENABLED", False)
HARVEST_EDGE_MULT = _f("HARVEST_EDGE_MULT", 2.0)   # edge must beat 2x the exit cost
HARVEST_MIN_EDGE = _f("HARVEST_MIN_EDGE", 50.0)    # and be worth the ticket
HARVEST_MIN_EDGE_FRAC = _f("HARVEST_MIN_EDGE_FRAC", 0.0)  # and this share of the mark
# A trend veto was tried here and REJECTED. The reasoning was that a debit
# spread is bought on a directional thesis while harvest is pure vol arbitrage,
# so the rule should stand down while the trend still backs the position. A/B
# over 72 historical debit structures (scripts/validate_harvest.py) says the
# trend does not separate the good harvests from the bad ones:
#
#   harvest alone          +$1,160   fired 10 times
#   harvest + trend veto     +$518   fired  8 times
#
# The veto blocked the two cases it should have kept (SPY 21 Aug +$456, SPY
# 7 Aug +$186) and let through all four it should have stopped (28 Aug, -$996).
# Trend z-score was exactly the wrong discriminator. Left out rather than
# tuned, because there is no evidence it separates anything.

NO_NEW_AFTER_ET = _s("NO_NEW_AFTER_ET", "15:30")
FORCE_CLOSE_AFTER_ET = _s("FORCE_CLOSE_AFTER_ET", "14:00")
ESCALATE_CLOSE_AFTER_ET = _s("ESCALATE_CLOSE_AFTER_ET", "15:30")

# ---------------------------------------------------------------- runtime
# ---------------------------------------------------------------- deadline
# The competition is judged at a fixed moment, which is NOT a natural exit for a
# position. Two separate cutoffs:
#   FLATTEN_AT      close everything, unconditionally
#   NO_NEW_AFTER    stop opening anything that cannot be closed before FLATTEN_AT
# Without these the judges would mark an open, mid-move position, and anything
# expiring after the deadline would never reach its own time stop.
COMPETITION_DEADLINE = _s("COMPETITION_DEADLINE", "2026-09-04T11:00:00-04:00")

# Flatten THURSDAY afternoon, not Friday morning.
#
# Every position we can still open expires Fri 4 Sep, and the deadline is 11:00
# ET that same day — so a Friday flatten means closing a 0-DTE book in the first
# minutes of the session, the widest-spread moment of the week, on deadline
# morning. Priced at realised vol on 1 Sep, the difference is small and the risk
# is not:
#
#   flatten Thu 15:30   keeps $728 of the $827 still on the table
#   flatten Fri 09:35   keeps $823                     (+$95)
#
# and that $95 is paid for by carrying a 0-DTE book through one overnight gap.
# With the short strikes 0.7% away, that bet is worth +$20 at realised vol and
# -$168 at implied — nothing in expectation, against a $1-2k tail. It also
# requires the machine to survive Thursday night, and leaves any failed leg to
# be fixed inside the 85 minutes before judging.
#
# Thursday costs ~$95, locks the judged P&L a full day early, and makes Friday
# morning purely about submitting.
FLATTEN_AT = _s("FLATTEN_AT", "2026-09-03T15:30:00-04:00")
NO_NEW_AFTER = _s("NO_NEW_AFTER", "2026-09-02T15:30:00-04:00")

POLL_SECONDS = _i("POLL_SECONDS", 300)
DRY_RUN = _b("DRY_RUN", True)
# 🔴 The ledger MUST be per-account. A single shared file meant switching to
# ACCOUNT=comp read DEV's open positions: the monitor tried to manage legs the
# competition account did not hold, and its risk budget was consumed by
# positions belonging to another account, so every trade was rejected with
# "per_expiry budget $2". Observed live 1 Sep on the first COMP cycle.
STATE_DB = str(ROOT / "state" / f"agent-{ACCOUNT}.db")
LOG_DIR = ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)
# Console stays terse; the file keeps the full record. See agent/logsetup.py.
LOG_LEVEL = _s("LOG_LEVEL", "INFO").upper()
LOG_FILE = str(LOG_DIR / "agent.log")
LOG_FILE_MAX_MB = _i("LOG_FILE_MAX_MB", 5)
LOG_FILE_KEEP = _i("LOG_FILE_KEEP", 7)


# ---------------------------------------------------------------- notifications
# Read by agent/notifier.py. All optional: an empty token or host disables that
# channel silently, so the agent runs unchanged with none of these set.
# Off by default. Wiring the notifier in must not silently start sending mail
# from a config file that was inherited rather than chosen.
NOTIFY = _b("NOTIFY", False)
TELEGRAM_BOT_TOKEN = _s("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = _s("TELEGRAM_CHAT_ID")
SMTP_HOST = _s("SMTP_HOST")
SMTP_PORT = _i("SMTP_PORT", 587)
SMTP_USER = _s("SMTP_USER")
# Not _s(): that strips, and an App Password is displayed in 4 space-separated
# groups ("abcd efgh ijkl mnop"). Read raw so it is passed through verbatim.
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
EMAIL_FROM = _s("EMAIL_FROM")
EMAIL_TO = _s("EMAIL_TO")


def summary() -> dict:
    return {
        "account": ACCOUNT,
        "account_number": ACCOUNT_NUMBER,
        "key_set": bool(API_KEY),
        "universe": UNIVERSE,
        "options_feed": OPTIONS_FEED,
        "dry_run": DRY_RUN,
        "risk_per_trade": f"{RISK_PER_TRADE_PCT:.2%}",
        "portfolio_heat": f"{PORTFOLIO_HEAT_PCT:.2%}",
        "dte": f"{MIN_DTE}-{MAX_DTE}",
    }
