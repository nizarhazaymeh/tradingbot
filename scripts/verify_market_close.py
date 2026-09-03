#!/usr/bin/env python3
"""Verify that a MARKET multi-leg close actually fills at the broker.

FLATTEN_AT closes the book with monitor.CLOSE_MARKET, which becomes an mleg
order with type="market". Every close this agent has ever executed used
type="limit" — so the one path the competition deadline depends on had never
been exercised against the live broker. The docs permit market on mleg; the docs
also said the CLI has no --legs flag and that OPRA was available, and both were
wrong. This asks Alpaca instead.

Runs the REAL path: cycle._rebuild_spread -> executor.close_spread(market=True).
DEV only — it refuses to touch the competition account.
"""
import sys, os, argparse, json, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agent import config

if config.ACCOUNT == "comp":
    sys.exit("refusing to run against ACCOUNT=comp — this submits a real closing order")

from agent.client import AlpacaClient
from agent.cycle import Agent
from agent import options as O

ap = argparse.ArgumentParser()
ap.add_argument("--live", action="store_true", help="actually submit the market close")
a = ap.parse_args()

ag = Agent()
c = ag.c
held = {p["symbol"] for p in c.positions() if p.get("asset_class") == "us_option"}
tracked = ag.store.open_positions()
print(f"account {c.account()['account_number']} ({config.ACCOUNT})")
print(f"  {len(held)} option legs held, {len(tracked)} structures tracked\n")

# pick a fully-held tracked structure, smallest first so the test is cheap
cands = []
for p in tracked:
    legs = json.loads(p["legs_json"])
    if {l["symbol"] for l in legs} <= held:
        cands.append((abs(p["max_loss"] or 0), p))
if not cands:
    sys.exit("no fully-held tracked structure to test with")
cands.sort(key=lambda x: x[0])
_, pos = cands[0]
print(f"target: {pos['kind']} {pos['underlying']} exp {pos['expiry']} qty {pos['qty']} "
      f"entry {pos['entry_price']:+.2f}  (max loss ${abs(pos['max_loss'] or 0):,.0f})")

syms = [l["symbol"] for l in json.loads(pos["legs_json"])]
snaps = c.option_snapshots(syms)
views = {}
for s, snap in snaps.items():
    try:
        views[s] = O.view(s, snap, min_dte=0, max_dte=3650)
    except Exception:
        pass
sp = ag._rebuild_spread(pos, views)
if sp is None:
    sys.exit("could not rebuild the spread — cannot test the real path")

from agent.spreads import closing_order, validate_mleg
body = closing_order(sp)
body["type"] = "market"
body.pop("limit_price", None)
print("\nthe order the flatten would send:")
print(json.dumps({k: v for k, v in body.items() if k != "legs"}, indent=2))
for l in body["legs"]:
    print(f"    {l['side']:4} {l['symbol']}  ratio {l.get('ratio_qty')} "
          f"intent={l.get('position_intent')}")
errs = validate_mleg(body)
print(f"\nlocal validation: {'PASS' if not errs else errs}")

if not a.live:
    print("\nplan only — add --live to submit and see what Alpaca says.")
    sys.exit(0)

if ag.ex.dry_run:
    # --live gates THIS script; the executor obeys config.DRY_RUN, which defaults
    # true on dev. Without this the executor returns its {"status": "dry_run",
    # "id": None} stub, nothing reaches the broker, and the test silently proves
    # nothing.
    sys.exit("executor is in DRY_RUN — re-run with DRY_RUN=false to actually submit")

print("\nsubmitting...")
order, msg = ag.ex.close_spread(sp, market=True)
print(f"  close_spread -> {msg}")
if order is None:
    print(f"  ❌ REJECTED: {msg}")
    print("\n  This is the flatten's path. If market mleg is rejected, FLATTEN_AT")
    print("  cannot close the book and the escalation must use limit orders.")
    sys.exit(1)
if not order.get("id"):
    sys.exit(f"no order id returned ({order.get('status')}) — nothing to poll")
print(f"  submitted id={order.get('id')} status={order.get('status')}")
for _ in range(20):
    time.sleep(3)
    o = c.get_order(order["id"])
    st = o.get("status")
    print(f"  {st}  filled {o.get('filled_qty')}/{o.get('qty')} "
          f"avg {o.get('filled_avg_price')}")
    if st in ("filled", "canceled", "rejected", "expired"):
        break
print(f"\n  final: {st}")
print("  ✅ MARKET mleg close works — the flatten path is verified"
      if st == "filled" else f"  ⚠️ ended {st} — investigate before relying on the flatten")
