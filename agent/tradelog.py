"""Append-only CSV journal of every entry and exit.

One row per event so a spreadsheet can reconstruct the run: entries have no
P/L, exits carry the realised result and why the position was closed.
"""
import csv
import logging
import os
from datetime import datetime, timezone

log = logging.getLogger("tradelog")

FIELDS = ["timestamp", "symbol", "action", "reason", "price", "qty",
          "notional", "pnl_pct", "pnl_usd", "mode", "protection"]


def record(path: str, **row) -> None:
    """Append one event. Never raises — a journal problem must not stop trading."""
    if not path:
        return
    try:
        row.setdefault("timestamp", datetime.now(timezone.utc).isoformat(timespec="seconds"))
        new_file = not os.path.exists(path) or os.path.getsize(path) == 0
        with open(path, "a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
            if new_file:
                w.writeheader()
            w.writerow({k: row.get(k, "") for k in FIELDS})
    except Exception as e:
        log.error("Could not write trade log %s: %s", path, e)
