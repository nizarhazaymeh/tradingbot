#!/usr/bin/env python3
"""Recompute every closed position's realised P&L from the actual broker fills.

Two ways the ledger drifts from what really happened:

  1. A ghost retired by cycle._retire_ghosts is closed with realized_pnl=None,
     because to reconcile() the structure simply vanished. Usually it did not —
     it was closed, and the broker still has the fill.

  2. cycle.manage_open_positions records `pnl` (the mark-to-market estimate) and
     only overrides it with filled_avg_price when the fill is already known. An
     order still pending at that moment keeps the estimate for good.

Measured on 3 Sep, after the book went flat:

    ledger total          -$260.00
    fill-derived total    -$195.00
    broker equity          -$201.39   (the remaining ~$6 is OCC fees)

so the ledger overstated the loss by $65, with two QQQ condors wrong by ~$37
each. The judged figure is account equity, so nothing was mis-stated to the
judges — but the results table in the write-up reads the ledger.

Sign convention matches cycle.py: closing_order() mirrors every leg, so the
close prices out with the opposite sign, and P&L = (-exit - entry) * 100 * qty.
Reproduces the rows that were already fill-derived exactly, which is the check
that the convention is right.

Deliberately outside the trading loop: only writes realized_pnl on rows that are
already closed, and a dry run unless given --apply.
"""
import sys, os, argparse, json, sqlite3
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agent import config
from agent.client import AlpacaClient

ap = argparse.ArgumentParser()
ap.add_argument("--apply", action="store_true")
ap.add_argument("--tolerance", type=float, default=1.0,
                help="ignore differences smaller than this ($)")
a = ap.parse_args()

con = sqlite3.connect(config.STATE_DB)
con.row_factory = sqlite3.Row
rows = con.execute("""select signature, kind, underlying, qty, entry_price,
                             realized_pnl, legs_json, close_reason
                      from positions where closed_at is not null
                      order by closed_at""").fetchall()
if not rows:
    sys.exit("no closed positions")

c = AlpacaClient()
orders = c.orders(status="all", limit=500)

def matched(row):
    """(entry_fill, exit_fill) for a row, from orders on the exact same leg set."""
    legs = json.loads(row["legs_json"])
    want = {l["symbol"] for l in legs}
    ours = {(l["symbol"], l["side"]) for l in legs}
    opens, closes = [], []
    for o in orders:
        syms = {l["symbol"] for l in (o.get("legs") or [])}
        if syms != want or not o.get("filled_avg_price"):
            continue
        sides = {(l["symbol"], l["side"]) for l in (o.get("legs") or [])}
        (opens if sides == ours else closes).append(o)
    if not opens or not closes:
        return None, None
    key = lambda o: o.get("filled_at") or ""
    return (float(sorted(opens, key=key)[0]["filled_avg_price"]),
            float(sorted(closes, key=key)[-1]["filled_avg_price"]))

print(f"{'structure':26} {'ledger':>10} {'from fills':>11} {'diff':>9}")
print("-" * 60)
changed, led_tot, fill_tot = [], 0.0, 0.0
for r in rows:
    en, ex = matched(r)
    led = r["realized_pnl"]
    led_tot += led or 0.0
    if en is None:
        fill_tot += led or 0.0
        print(f"{r['kind'] + ':' + r['underlying']:26} {(led or 0):10,.2f} "
              f"{'unmatched':>11} {'-':>9}")
        continue
    fill = round((-ex - r["entry_price"]) * 100 * r["qty"], 2)
    fill_tot += fill
    diff = fill - (led or 0.0)
    print(f"{r['kind'] + ':' + r['underlying']:26} "
          f"{(led if led is not None else float('nan')):10,.2f} {fill:11,.2f} "
          f"{diff:+9,.2f}{'' if abs(diff) < a.tolerance else '  <-'}")
    if abs(diff) >= a.tolerance:
        changed.append((r["signature"], fill, r["close_reason"]))

print("-" * 60)
print(f"{'TOTAL':26} {led_tot:10,.2f} {fill_tot:11,.2f} {fill_tot - led_tot:+9,.2f}")
eq = float(c.account()["equity"])
print(f"\n  broker equity P&L {eq - config.STARTING_EQUITY:+,.2f}"
      f"   (fill-derived is off by {(eq - config.STARTING_EQUITY) - fill_tot:+,.2f}, "
      f"which should be fees)")
print(f"  {len(changed)} row(s) differ by >= ${a.tolerance:,.2f}")

if a.apply and changed:
    for sig, fill, reason in changed:
        note = " | P&L recomputed from broker fill"
        con.execute("update positions set realized_pnl=?, close_reason=? where signature=?",
                    (fill, (reason or "") + ("" if note in (reason or "") else note), sig))
    con.commit()
    print(f"\n✅ wrote {len(changed)} row(s)")
elif changed:
    print("\n(dry run — pass --apply to write)")
