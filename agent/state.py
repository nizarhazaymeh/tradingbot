"""SQLite persistence. The broker is the source of truth; this is our intent + audit log.

Critically: options cannot carry bracket orders, so the exit plan for every position
lives HERE and is rebuilt on restart. Losing this file means losing our stops.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS positions (
    signature        TEXT PRIMARY KEY,
    kind             TEXT NOT NULL,
    underlying       TEXT NOT NULL,
    expiry           TEXT NOT NULL,
    qty              INTEGER NOT NULL,
    legs_json        TEXT NOT NULL,
    entry_price      REAL NOT NULL,      -- +debit / -credit per unit
    is_credit        INTEGER NOT NULL,
    max_loss         REAL NOT NULL,      -- total dollars
    max_gain         REAL NOT NULL,
    width            REAL NOT NULL,
    net_delta        REAL,
    net_theta        REAL,
    take_profit      REAL,               -- dollars of P&L
    stop_loss        REAL,
    time_stop_dte    INTEGER,
    opened_at        TEXT NOT NULL,
    open_order_id    TEXT,
    client_order_id  TEXT,
    status           TEXT NOT NULL DEFAULT 'open',
    closed_at        TEXT,
    close_order_id   TEXT,
    realized_pnl     REAL,
    close_reason     TEXT,
    meta_json        TEXT
);
CREATE TABLE IF NOT EXISTS decisions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ts           TEXT NOT NULL,
    cycle        INTEGER,
    underlying   TEXT,
    regime       TEXT,
    view_json    TEXT,
    proposal     TEXT,
    decision     TEXT NOT NULL,          -- submit | reject | hold | close
    gate         TEXT,
    reason       TEXT,
    payload_json TEXT
);
CREATE TABLE IF NOT EXISTS iv_history (
    underlying TEXT NOT NULL,
    d          TEXT NOT NULL,
    atm_iv     REAL NOT NULL,
    PRIMARY KEY (underlying, d)
);
CREATE TABLE IF NOT EXISTS equity_snapshots (
    ts     TEXT PRIMARY KEY,
    equity REAL NOT NULL,
    cash   REAL,
    obp    REAL
);
CREATE TABLE IF NOT EXISTS orders_log (
    client_order_id TEXT PRIMARY KEY,
    ts              TEXT NOT NULL,
    order_id        TEXT,
    kind            TEXT,
    status          TEXT,
    body_json       TEXT
);
CREATE INDEX IF NOT EXISTS idx_pos_status ON positions(status);
CREATE INDEX IF NOT EXISTS idx_dec_ts ON decisions(ts);
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: str = None):
        self.path = path or config.STATE_DB
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.path, timeout=15)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ------------------------------------------------------------ positions
    def open_position(self, *, signature: str, spread, order: dict,
                      take_profit: float, stop_loss: float,
                      time_stop_dte: int, client_order_id: str) -> None:
        with self._conn() as c:
            c.execute("""INSERT OR REPLACE INTO positions
                (signature, kind, underlying, expiry, qty, legs_json, entry_price,
                 is_credit, max_loss, max_gain, width, net_delta, net_theta,
                 take_profit, stop_loss, time_stop_dte, opened_at, open_order_id,
                 client_order_id, status, meta_json)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?, 'open', ?)""",
                (signature, spread.kind, spread.underlying, spread.expiry.isoformat(),
                 spread.qty, json.dumps([l.payload() for l in spread.legs]),
                 spread.net_price, int(spread.is_credit),
                 spread.total_max_loss(), spread.max_gain_per_unit * spread.qty,
                 spread.width, spread.net_delta, spread.net_theta,
                 take_profit, stop_loss, time_stop_dte, utcnow(),
                 (order or {}).get("id"), client_order_id,
                 json.dumps(spread.meta, default=str)))

    def close_position(self, signature: str, *, realized_pnl: float,
                       reason: str, close_order_id: str = None) -> None:
        with self._conn() as c:
            c.execute("""UPDATE positions SET status='closed', closed_at=?,
                         realized_pnl=?, close_reason=?, close_order_id=?
                         WHERE signature=?""",
                      (utcnow(), realized_pnl, reason, close_order_id, signature))

    def open_positions(self) -> List[dict]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM positions WHERE status='open'").fetchall()
        return [dict(r) for r in rows]

    def closed_positions(self) -> List[dict]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM positions WHERE status='closed' "
                             "ORDER BY closed_at").fetchall()
        return [dict(r) for r in rows]

    def tracked_for_book(self) -> List[dict]:
        """Shape the open book the way risk.Book expects."""
        return [{"signature": p["signature"], "underlying": p["underlying"],
                 "expiry": p["expiry"], "max_loss": p["max_loss"],
                 "net_delta": p["net_delta"] or 0.0}
                for p in self.open_positions()]

    # ------------------------------------------------------------ decisions
    def log_decision(self, *, cycle: int, underlying: str, regime: str,
                     view: dict, proposal: str, decision: str,
                     gate: str = "", reason: str = "", payload: dict = None) -> None:
        with self._conn() as c:
            c.execute("""INSERT INTO decisions
                (ts, cycle, underlying, regime, view_json, proposal, decision,
                 gate, reason, payload_json) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (utcnow(), cycle, underlying, regime, json.dumps(view, default=str),
                 proposal, decision, gate, reason,
                 json.dumps(payload, default=str) if payload else None))

    def decisions(self, limit: int = 100) -> List[dict]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM decisions ORDER BY id DESC LIMIT ?",
                             (limit,)).fetchall()
        return [dict(r) for r in rows]

    def gate_counts(self) -> Dict[str, int]:
        with self._conn() as c:
            rows = c.execute("""SELECT gate, COUNT(*) n FROM decisions
                                WHERE decision='reject' AND gate!=''
                                GROUP BY gate ORDER BY n DESC""").fetchall()
        return {r["gate"]: r["n"] for r in rows}

    def funnel(self) -> Dict[str, int]:
        with self._conn() as c:
            rows = c.execute("SELECT decision, COUNT(*) n FROM decisions "
                             "GROUP BY decision").fetchall()
        return {r["decision"]: r["n"] for r in rows}

    # ------------------------------------------------------------ iv history
    def record_iv(self, underlying: str, d: date, iv: float) -> None:
        with self._conn() as c:
            c.execute("INSERT OR REPLACE INTO iv_history VALUES (?,?,?)",
                      (underlying, d.isoformat(), iv))

    def iv_history(self, underlying: str, limit: int = 120) -> List[float]:
        with self._conn() as c:
            rows = c.execute("""SELECT atm_iv FROM iv_history WHERE underlying=?
                                ORDER BY d DESC LIMIT ?""", (underlying, limit)).fetchall()
        return [r["atm_iv"] for r in rows]

    # ------------------------------------------------------------ equity
    def snapshot_equity(self, equity: float, cash: float = None, obp: float = None) -> None:
        with self._conn() as c:
            c.execute("INSERT OR REPLACE INTO equity_snapshots VALUES (?,?,?,?)",
                      (utcnow(), equity, cash, obp))

    def equity_curve(self) -> List[dict]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM equity_snapshots ORDER BY ts").fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------ orders
    def log_order(self, client_order_id: str, body: dict, order: dict = None,
                  kind: str = "open") -> None:
        with self._conn() as c:
            c.execute("""INSERT OR REPLACE INTO orders_log
                         VALUES (?,?,?,?,?,?)""",
                      (client_order_id, utcnow(), (order or {}).get("id"), kind,
                       (order or {}).get("status"), json.dumps(body)))

    def orders_since(self, iso_ts: str) -> int:
        """Real orders sent to the broker since iso_ts.

        Dry runs are excluded. Executor.open_spread() logs them here too, with
        status 'dry_run', so counting every row let a rehearsal consume the live
        MAX_ORDERS_PER_HOUR budget and trip the g_order_rate circuit breaker.
        Since `run.py once` is dry by default, rehearsing before a live session
        could halt the agent before it placed a single order.
        """
        with self._conn() as c:
            r = c.execute("""SELECT COUNT(*) n FROM orders_log
                             WHERE ts >= ? AND COALESCE(status,'') != 'dry_run'""",
                          (iso_ts,)).fetchone()
        return r["n"]

    # ------------------------------------------------------------ reporting
    def stats(self) -> dict:
        """`realized_pnl` NULL means UNKNOWN, not zero.

        A retired ghost has no attributable P&L — its legs may be shared with
        another structure, so per-symbol fills cannot be split between them. It
        used to be coerced to 0.0, which counted it as a losing trade and dragged
        the win rate down with a number nobody measured. Unknowns are now
        excluded from the rates and reported separately.
        """
        closed = self.closed_positions()
        pnls = [p["realized_pnl"] for p in closed if p["realized_pnl"] is not None]
        unknown = len(closed) - len(pnls)
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        return {
            "closed_trades": len(closed),
            "closed_pnl_unknown": unknown,
            "open_trades": len(self.open_positions()),
            "realized_pnl": round(sum(pnls), 2),
            "win_rate": round(len(wins) / len(pnls), 4) if pnls else None,
            "avg_win": round(sum(wins) / len(wins), 2) if wins else None,
            "avg_loss": round(sum(losses) / len(losses), 2) if losses else None,
            "funnel": self.funnel(),
            "gate_rejections": self.gate_counts(),
        }
