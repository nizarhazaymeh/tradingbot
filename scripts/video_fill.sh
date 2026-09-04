#!/usr/bin/env bash
# The broker's own record of the order cycle 68 submitted. Not our log — Alpaca's.
cd "$(dirname "$0")/.." || exit 1
./.venv/bin/python3 - <<'PY' 2>/dev/null
import sys; sys.path.insert(0, ".")
from agent.client import AlpacaClient
for o in AlpacaClient().orders(status="closed", limit=300, nested=True):
    legs = {l["symbol"] for l in (o.get("legs") or [])}
    if {"QQQ260904C00721000", "QQQ260904C00723000"} <= legs and o["submitted_at"].startswith("2026-09-01T14:20"):
        print(f"\n  order {o['id']}")
        print(f"  submitted  {o['submitted_at'][:19]}Z")
        print(f"  filled     {o['filled_at'][:19]}Z          status: {o['status'].upper()}")
        print(f"  limit      {o['limit_price']}   filled at {o['filled_avg_price']}   qty {o['filled_qty']}\n")
        for l in o["legs"]:
            print(f"    {l['side']:4}  {l['symbol']}   ${l['filled_avg_price']}")
        print()
PY
