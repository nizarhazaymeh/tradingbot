#!/usr/bin/env python3
"""End-to-end test of the two safety systems that have never actually fired.

  1. CIRCUIT BREAKER — does a drawdown really cancel orders, flatten the book,
     and lock the account server-side?
  2. CRASH RECOVERY  — after an unclean shutdown, does the agent notice that its
     ledger and the broker disagree, instead of trading on a wrong picture?

Runs against the DEV account only. Refuses to run against COMP.
"""
import json
import shutil
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent import config, monitor, risk as RK, spreads as S, options as O
from agent.client import AlpacaClient, AlpacaError
from agent.cycle import Agent, HALT_FILE
from agent.executor import Executor
from agent.state import Store

if config.ACCOUNT != "dev":
    sys.exit(f"refusing to run safety tests against ACCOUNT={config.ACCOUNT}")

OK, FAIL = "✅", "❌"
results = []


def check(name, passed, detail=""):
    results.append((name, passed, detail))
    print(f"  {OK if passed else FAIL} {name}" + (f"  — {detail}" if detail else ""))
    return passed


def banner(t):
    print(f"\n{'='*72}\n{t}\n{'='*72}")


# ══════════════════════════════════════════════════ 1. CIRCUIT BREAKER
banner("1. CIRCUIT BREAKER")

book_ok = RK.Book(equity=100_000, last_equity=100_000, options_buying_power=100_000)
check("no breaker on a flat account", bool(RK.circuit_breakers(book_ok)))

cases = [
    ("daily drawdown -2.1%", RK.Book(equity=97_900, last_equity=100_000,
                                     options_buying_power=100_000), "g_daily_drawdown"),
    ("daily drawdown -1.9% (under)", RK.Book(equity=98_100, last_equity=100_000,
                                             options_buying_power=100_000), None),
    ("total drawdown -6.5%", RK.Book(equity=93_500, last_equity=93_500,
                                     options_buying_power=100_000), "g_total_drawdown"),
    ("order rate limit", RK.Book(equity=100_000, last_equity=100_000,
                                 options_buying_power=100_000,
                                 orders_last_hour=config.MAX_ORDERS_PER_HOUR),
     "g_order_rate"),
]
for label, bk, expect in cases:
    r = RK.circuit_breakers(bk)
    if expect is None:
        check(label + " does NOT trip", bool(r))
    else:
        check(label + f" trips {expect}", (not r) and r.gate == expect,
              r.reason if not r else "")

# --- does the HALT actually reach Alpaca? -----------------------------------
print("\n  executing a real halt against the DEV account...")
c = AlpacaClient()
ex = Executor(c, dry_run=False)
before = c.account_config()
res = ex.halt_everything("SAFETY TEST — not a real drawdown")
check("halt cancelled orders", res.get("cancelled") is True, str(res.get("cancelled")))
check("halt flattened positions", res.get("closed") is True, str(res.get("closed")))
check("halt set suspend_trade", res.get("suspended") is True, str(res.get("suspended")))

after = c.account_config()
check("suspend_trade is TRUE on the account server-side",
      bool(after.get("suspend_trade")), f"suspend_trade={after.get('suspend_trade')}")

# --- does a suspended account actually block an order? ----------------------
try:
    spot = c.latest_trade("SPY")
    exp = date.today() + timedelta(days=(4 - date.today().weekday()) % 7 or 7)
    chain = c.option_chain("SPY", exp=exp.isoformat(),
                           strike_gte=spot * 0.97, strike_lte=spot * 1.03)
    views = O.usable_contracts(chain)
    sh = O.by_delta(views, 0.16, "P", exp)
    lo = O.wing(views, sh, 5) if sh else None
    if sh and lo and lo.strike < sh.strike:
        sp = S.bull_put_spread(sh, lo)
        try:
            c.submit_order(sp.order())
            check("suspended account REJECTS new orders", False, "order was accepted!")
        except AlpacaError as e:
            check("suspended account REJECTS new orders", True,
                  f"[{e.status}] {e.message[:70]}")
    else:
        check("suspended account REJECTS new orders", None, "skipped — no chain")
except Exception as e:
    print(f"     (order probe skipped: {type(e).__name__})")

# --- restore ---------------------------------------------------------------
c.set_account_config(suspend_trade=False)
restored = c.account_config()
check("suspend_trade restored to FALSE",
      not restored.get("suspend_trade"), f"suspend_trade={restored.get('suspend_trade')}")

# --- the HALTED file must block the loop -----------------------------------
HALT_FILE.write_text("safety test\n")
bk = RK.Book(equity=100_000, last_equity=100_000, options_buying_power=100_000)
r = RK.circuit_breakers(bk, halted_flag=True)
check("HALTED file blocks the cycle", (not r) and r.gate == "g_kill_switch")
HALT_FILE.unlink(missing_ok=True)
check("HALTED file cleaned up", not HALT_FILE.exists())


# ══════════════════════════════════════════════════ 2. CRASH RECOVERY
banner("2. CRASH RECOVERY")

tmp = Path(tempfile.mkdtemp()) / "crash.db"
store = Store(str(tmp))

E = date.today() + timedelta(days=5)
def mkview(kind, strike, mid):
    return O.ContractView(symbol=O.occ("SPY", E, kind, strike), root="SPY", expiry=E,
                          kind=kind, strike=strike, dte=5, bid=mid*0.97, ask=mid*1.03,
                          mid=mid, spread_pct=0.06, delta=-0.16 if kind == "P" else 0.16,
                          gamma=0.01, theta=-0.2, vega=0.1, iv=0.15, open_interest=5000)

spread = S.bull_put_spread(mkview("P", 755, 1.10), mkview("P", 750, 0.50))
legs = [l.payload() for l in spread.legs]

store.open_position(signature="bull_put:SPY-test", spread=spread,
                    order={"id": "fake"}, take_profit=30, stop_loss=90,
                    time_stop_dte=1, client_order_id="test-coid")
check("position persisted before the crash", len(store.open_positions()) == 1)

# --- simulate the crash: reopen the DB from scratch -------------------------
del store
store2 = Store(str(tmp))
check("ledger survives restart", len(store2.open_positions()) == 1,
      "exit plan recovered from disk")

pos = store2.open_positions()[0]
check("exit thresholds survived", pos["take_profit"] == 30 and pos["stop_loss"] == 90,
      f"TP={pos['take_profit']} SL={pos['stop_loss']}")

# --- broker disagrees: we think we hold it, broker has nothing --------------
rec = monitor.reconcile(store2, broker_positions=[])
check("GHOST detected (we hold it, broker does not)",
      len(rec["ghosts"]) == 1 and not rec["clean"], f"ghosts={rec['ghosts']}")

# --- broker holds something we never recorded ------------------------------
orphan_sym = O.occ("SPY", E, "C", 800)
rec = monitor.reconcile(store2, broker_positions=[
    {"symbol": legs[0]["symbol"], "asset_class": "us_option"},
    {"symbol": legs[1]["symbol"], "asset_class": "us_option"},
    {"symbol": orphan_sym, "asset_class": "us_option"},
])
check("ORPHAN detected (broker holds it, we have no exit plan)",
      rec["orphans"] == [orphan_sym], f"orphans={rec['orphans']}")

# --- fully matched -> clean -------------------------------------------------
rec = monitor.reconcile(store2, broker_positions=[
    {"symbol": legs[0]["symbol"], "asset_class": "us_option"},
    {"symbol": legs[1]["symbol"], "asset_class": "us_option"},
])
check("clean when ledger and broker agree", rec["clean"],
      f"tracked={rec['tracked_structures']} legs={rec['broker_option_legs']}")

# --- equity/audit history also survives ------------------------------------
store2.log_decision(cycle=1, underlying="SPY", regime="X", view={}, proposal="p",
                    decision="reject", gate="g_expectancy", reason="test")
store2.snapshot_equity(99_500)
del store2
store3 = Store(str(tmp))
check("audit log survives restart", store3.funnel().get("reject") == 1)
check("equity history survives restart", len(store3.equity_curve()) == 1)

shutil.rmtree(tmp.parent, ignore_errors=True)


# ══════════════════════════════════════════════════ SUMMARY
banner("SUMMARY")
passed = sum(1 for _, p, _ in results if p)
skipped = sum(1 for _, p, _ in results if p is None)
failed = [n for n, p, _ in results if p is False]
print(f"  {passed} passed, {len(failed)} failed" + (f", {skipped} skipped" if skipped else ""))
for n in failed:
    print(f"  {FAIL} {n}")
sys.exit(1 if failed else 0)
