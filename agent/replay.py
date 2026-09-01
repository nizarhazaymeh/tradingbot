"""Replay harness: run the agent's ENTRY and EXIT logic over historical option data.

This exists because the live market is closed most of the time we are building,
and the exit loop is the agent's only stop-loss (Alpaca has no bracket orders on
options). Waiting for a live session to discover a bug there is not acceptable.

What it does:
  * picks a past expiry cycle
  * reconstructs the chain at entry from historical option bars
  * builds a spread exactly as the live agent would
  * walks forward day by day, marking the position to market
  * runs the REAL monitor.evaluate_exit() at each step
  * records what actually happened at expiry

What it does NOT model: intraday movement, bid/ask at the moment of exit,
partial fills, or queue position. Bars are daily closes. Treat results as a
sanity check on the LOGIC, not as a performance backtest.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from . import config, monitor, regime as R, spreads as S
from .client import AlpacaClient, AlpacaError
from .options import ContractView, parse_occ

log = logging.getLogger(__name__)


@dataclass
class ReplayStep:
    day: date
    dte: int
    underlying_price: Optional[float]
    mark: float                 # cost to close, per unit
    pnl: float                  # dollars
    action: str
    reason: str


@dataclass
class ReplayResult:
    spread_kind: str
    underlying: str
    expiry: date
    entry_day: date
    entry_price: float
    max_loss: float
    max_gain: float
    steps: List[ReplayStep] = field(default_factory=list)
    exit_day: Optional[date] = None
    exit_reason: str = ""
    final_pnl: float = 0.0
    held_to_expiry: bool = False

    def summary(self) -> str:
        outcome = "WIN" if self.final_pnl > 0 else "LOSS" if self.final_pnl < 0 else "FLAT"
        return (f"{self.underlying} {self.spread_kind} {self.entry_day}->{self.exit_day} "
                f"{outcome} ${self.final_pnl:+.0f} "
                f"(max gain ${self.max_gain:.0f} / max loss ${self.max_loss:.0f}) "
                f"— {self.exit_reason}")


class Replayer:
    def __init__(self, client: AlpacaClient = None, cache_dir: str = None):
        self.c = client or AlpacaClient(timeout=90)
        self._bar_cache: Dict[str, Dict[str, dict]] = {}
        self.cache_dir = Path(cache_dir) if cache_dir else (
            Path(__file__).resolve().parent.parent / ".cache" / "replay")
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _cached(self, key: str, fetch):
        """Disk-cache historical data. It never changes, so this is always safe."""
        import hashlib
        f = self.cache_dir / (hashlib.sha1(key.encode()).hexdigest()[:20] + ".json")
        if f.exists():
            try:
                return json.loads(f.read_text())
            except Exception:
                pass
        val = fetch()
        try:
            f.write_text(json.dumps(val))
        except Exception:
            pass
        return val

    # ------------------------------------------------------------------ data
    def option_bars(self, symbols: List[str], start: str, end: str,
                    timeframe: str = "1Day") -> Dict[str, Dict[str, dict]]:
        """{symbol: {YYYY-MM-DD: bar}} — note this endpoint rejects a `feed` param."""
        key = f"obars|{timeframe}|{start}|{end}|{','.join(sorted(symbols))}"

        def fetch():
            out: Dict[str, Dict[str, dict]] = {}
            CHUNK = 40
            for i in range(0, len(symbols), CHUNK):
                batch = symbols[i:i + CHUNK]
                token = None
                for _ in range(200):
                    for attempt in range(3):
                        try:
                            res = self.c._data("/v1beta1/options/bars", {
                                "symbols": ",".join(batch), "timeframe": timeframe,
                                "start": start, "end": end, "limit": 10000,
                                "page_token": token})
                            break
                        except AlpacaError:
                            raise
                        except Exception:
                            if attempt == 2:
                                raise
                            time.sleep(2 * (attempt + 1))
                    for sym, rows in (res.get("bars") or {}).items():
                        d = out.setdefault(sym, {})
                        for r in rows:
                            d[r["t"][:10]] = r
                    token = res.get("next_page_token")
                    if not token:
                        break
            return out

        return self._cached(key, fetch)

    @staticmethod
    def safe_end(end: date | str) -> str:
        """Clamp a data request so it never reaches into today (see replay())."""
        d = date.fromisoformat(end) if isinstance(end, str) else end
        return min(d, date.today() - timedelta(days=1)).isoformat()

    def stock_closes(self, underlying: str, start: str, end: str) -> Dict[str, float]:
        def fetch():
            for attempt in range(3):
                try:
                    res = self.c._data("/v2/stocks/bars", {
                        "symbols": underlying, "timeframe": "1Day", "start": start,
                        "end": end, "limit": 10000, "adjustment": "all",
                        "feed": config.STOCK_FEED})
                    return {r["t"][:10]: r["c"]
                            for r in (res.get("bars") or {}).get(underlying, [])}
                except AlpacaError:
                    raise
                except Exception:
                    if attempt == 2:
                        raise
                    time.sleep(2 * (attempt + 1))
        return self._cached(f"sbars|{underlying}|{start}|{end}", fetch)

    # -------------------------------------------------------------- marking
    @staticmethod
    def _mark(spread: S.Spread, bars: Dict[str, Dict[str, dict]], day: str) -> Optional[float]:
        """Net cost to CLOSE the structure, per unit, using that day's closes."""
        total = 0.0
        for leg in spread.legs:
            bar = bars.get(leg.symbol, {}).get(day)
            if bar is None:
                return None
            px = float(bar["c"])
            total += px if leg.side == "buy" else -px
        return round(total, 4)

    @staticmethod
    def _intrinsic(spread: S.Spread, underlying_px: float) -> float:
        """Value at expiry — what the structure is actually worth when it settles."""
        total = 0.0
        for leg in spread.legs:
            _, _, kind, strike = parse_occ(leg.symbol)
            val = (max(underlying_px - strike, 0.0) if kind == "C"
                   else max(strike - underlying_px, 0.0))
            total += val if leg.side == "buy" else -val
        return round(total, 4)

    # --------------------------------------------------------------- replay
    def replay(self, spread: S.Spread, entry_day: date, *,
               entry_price: float = None) -> ReplayResult:
        """Walk a structure forward day by day through the real exit logic."""
        syms = [l.symbol for l in spread.legs]
        start = (entry_day - timedelta(days=2)).isoformat()
        # On the free plan historical option data excludes the most recent 15
        # minutes, and requesting a window that reaches into today returns
        # 403 "OPRA agreement is not signed". Never ask past yesterday.
        end = min(spread.expiry, date.today() - timedelta(days=1)).isoformat()

        bars = self.option_bars(syms, start, end)
        closes = self.stock_closes(spread.underlying, start, end)
        # Realised vol needs ~20 prior sessions, and `start` is only two days
        # before entry — so a separate, longer history purely for volatility.
        # Without this the harvest rule stays inert through the whole replay.
        vol_closes = self.stock_closes(spread.underlying,
                                       (entry_day - timedelta(days=150)).isoformat(),
                                       end)

        entry = entry_price if entry_price is not None else self._mark(spread, bars,
                                                                      entry_day.isoformat())
        if entry is None:
            raise ValueError(f"no option bars on {entry_day} for {syms}")

        qty = spread.qty
        max_loss = spread.max_loss_per_unit * qty
        max_gain = spread.max_gain_per_unit * qty

        # the position row the monitor expects, exactly as state.py would store it
        pos = {
            "signature": "replay", "kind": spread.kind, "underlying": spread.underlying,
            "expiry": spread.expiry.isoformat(), "qty": qty,
            "legs_json": json.dumps([l.payload() for l in spread.legs]),
            "entry_price": entry, "is_credit": int(spread.is_credit),
            "max_loss": max_loss, "max_gain": max_gain,
            "time_stop_dte": config.TIME_STOP_DTE,
        }

        result = ReplayResult(spread.kind, spread.underlying, spread.expiry, entry_day,
                              entry, max_loss, max_gain)

        day = entry_day + timedelta(days=1)
        while day <= spread.expiry:
            ds = day.isoformat()
            mark = self._mark(spread, bars, ds)
            if mark is None:
                day += timedelta(days=1)
                continue

            dte = (spread.expiry - day).days
            pnl = round((mark - entry) * 100 * qty, 2)

            # feed the REAL exit logic synthetic quotes built from the day's close
            snaps = {}
            for leg in spread.legs:
                bar = bars.get(leg.symbol, {}).get(ds)
                px = float(bar["c"])
                snaps[leg.symbol] = {"latestQuote": {"bp": max(px - 0.02, 0.01),
                                                     "ap": px + 0.02}}
            noon = datetime(day.year, day.month, day.day, 12, 0)

            # The harvest rule needs spot and realised vol, and is inert without
            # them — so replaying with no context silently skipped it entirely.
            # Realised vol is computed from closes strictly BEFORE this day, so
            # the replay cannot see the move it is about to be judged on.
            context = {}
            prior = [vol_closes[k] for k in sorted(vol_closes) if k < ds]
            rv = R.realized_vol(prior) if len(prior) >= 21 else None
            spot_ds = closes.get(ds) or vol_closes.get(ds)
            if rv and spot_ds:
                tz, _dir = R.trend_score(prior) if len(prior) >= 52 else (0.0, 0)
                context[spread.underlying] = {"spot": float(spot_ds),
                                              "realized_vol": rv, "trend_z": tz}
            d = monitor.evaluate_exit(pos, snaps, {}, now=noon, context=context)

            result.steps.append(ReplayStep(day, dte, closes.get(ds), mark, pnl,
                                           d.action, d.reason))
            if d.action != monitor.HOLD:
                result.exit_day, result.exit_reason, result.final_pnl = day, d.reason, pnl
                return result
            day += timedelta(days=1)

        # never exited -> settle at intrinsic value on the expiry close
        settle_px = closes.get(spread.expiry.isoformat())
        if settle_px:
            intrinsic = self._intrinsic(spread, settle_px)
            result.final_pnl = round((intrinsic - entry) * 100 * qty, 2)
        elif result.steps:
            result.final_pnl = result.steps[-1].pnl
        result.exit_day = spread.expiry
        result.exit_reason = "held to expiry (settled at intrinsic value)"
        result.held_to_expiry = True
        return result
