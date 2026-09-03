#!/usr/bin/env python3
"""Recover the realised P&L of positions retired as ghosts.

A ghost is a tracked structure the broker holds no leg of. cycle._retire_ghosts
closes the row with realized_pnl=None, because from reconcile()'s point of view
the position simply vanished and there is nothing to mark it against.

But usually it did not vanish — it was CLOSED, and the broker still has the fill.
On 3 Sep a SPY iron condor was closed at 09:30 ET at 0.40 against a -0.44 entry,
a real +$12, and the ledger recorded "P&L unknown". The judged figure comes from
account equity so nothing was mis-stated to the judges, but our own results table
reads the ledger, and an unknown is worse than a number we can recover.

Deliberately separate from the trading loop: this only ever writes realized_pnl
on rows that are already closed with NULL, so it cannot affect a live decision.
Run with --apply to write; default is a dry run.
"""
import sys, os, argparse, json, sqlite3
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agent import config
from agent.client import AlpacaClient

ap = argparse.ArgumentParser()
ap.add_argument("--apply", action="store_true", help="write the recovered values")
a = ap.parse_args()

con = sqlite3.connect(config.STATE_DB)
con.row_factory = sqlite3.Row
rows = con.execute("""select signature, kind, underlying, qty, entry_price, legs_json,
                             closed_at, close_reason
                      from positions
                      where closed_at is not null and realized_pnl is null""").fetchall()
if not rows:
    print("nothing to backfill — no closed row has a NULL realised P&L")
    sys.exit(0)

c = AlpacaClient()
orders = c.orders(status="all", limit=500)
print(f"{len(rows)} row(s) with unknown P&L, {len(orders)} broker orders to match against\n")

fixed = 0
for r in rows:
    legs = json.loads(r["legs_json"])
    want = {l["symbol"] for l in legs}
    # The closing fill is the one whose leg set matches and whose sides are the
    # mirror of ours. Match on the leg set and take the latest fill that is not
    # the opening order.
    cands = []
    for o in orders:
        syms = {l["symbol"] for l in (o.get("legs") or [])}
        if syms != want or not o.get("filled_avg_price"):
            continue
        opened_like = {(l["symbol"], l["side"]) for l in (o.get("legs") or [])}
        ours = {(l["symbol"], l["side"]) for l in legs}
        if opened_like == ours:
            continue                      # this is the OPEN, not the close
        cands.append(o)
    if not cands:
        print(f"  {r['signature'][:44]:46} no matching closing fill — left NULL")
        continue
    close = sorted(cands, key=lambda o: o.get("filled_at") or "")[-1]
    exit_px = float(close["filled_avg_price"])
    entry = float(r["entry_price"])
    qty = int(r["qty"])
    # entry_price is +debit / -credit per unit; the close is signed the same way
    # by Alpaca, so P&L = (exit - entry) for a debit and (entry - exit) inverted
    # falls out of the same expression once the close is expressed as we paid it.
    pnl = round((exit_px - entry) * 100 * qty, 2) if entry > 0 else \
          round((abs(entry) - exit_px) * 100 * qty, 2)
    print(f"  {r['kind']:12}{r['underlying']:6} qty {qty} entry {entry:+.2f} "
          f"exit {exit_px:+.2f} -> P&L {pnl:+8.2f}   ({(close.get('filled_at') or '')[:19]})")
    if a.apply:
        con.execute("update positions set realized_pnl=?, close_reason=? where signature=?",
                    (pnl, f"{r['close_reason']} | P&L recovered from broker fill",
                     r["signature"]))
        fixed += 1
if a.apply:
    con.commit()
    print(f"\n✅ wrote {fixed} row(s)")
else:
    print("\n(dry run — pass --apply to write)")
