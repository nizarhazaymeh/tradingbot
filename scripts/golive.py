#!/usr/bin/env python3
"""Staged go-live. Run this at the open instead of improvising.

Five stages, each gated on the previous one. Nothing touches the COMPETITION
account until a real fill has been observed on DEV.

    python scripts/golive.py                 # stage 1 only: preflight, read-only
    python scripts/golive.py --stage 2       # fill test on DEV (submits 1 order)
    python scripts/golive.py --stage 3       # close the test position
    python scripts/golive.py --stage 4       # preflight the COMP account
    python scripts/golive.py --stage 5       # start the agent on COMP

Stage 5 is the only irreversible one and it asks for typed confirmation.
"""
import argparse
import json
import os
import subprocess
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

ET = ZoneInfo("America/New_York")
LOCAL = ZoneInfo("Asia/Amman")
OK, BAD, WARN = "✅", "❌", "⚠️ "


def hdr(t):
    print(f"\n{'='*70}\n{t}\n{'='*70}")


def line(ok, label, detail=""):
    mark = OK if ok is True else (BAD if ok is False else WARN)
    print(f"  {mark} {label}" + (f"  — {detail}" if detail else ""))
    return ok


def now_str():
    return (f"{datetime.now(LOCAL):%H:%M} local / "
            f"{datetime.now(ET):%H:%M} ET")


# ─────────────────────────────────────────────────────── stage 1: preflight
def stage1():
    hdr(f"STAGE 1 — PREFLIGHT (read-only)   {now_str()}")
    ok = True

    from agent import config
    from agent.client import AlpacaClient

    line(config.ACCOUNT == "dev", f"ACCOUNT={config.ACCOUNT}",
         "must be 'dev' for the fill test")
    ok &= config.ACCOUNT == "dev"

    r = subprocess.run([sys.executable, "-m", "pytest", "tests/", "-q"],
                       cwd=ROOT, capture_output=True, text=True)
    tests_ok = r.returncode == 0
    passed = [l for l in r.stdout.splitlines() if "passed" in l]
    line(tests_ok, "test suite", passed[-1].strip() if passed else "see output")
    ok &= tests_ok

    c = AlpacaClient()
    clock = c.clock()
    is_open = bool(clock.get("is_open"))
    line(is_open, "market open",
         f"next open {clock.get('next_open')}" if not is_open else "trading now")

    a = c.account()
    line(a["status"] == "ACTIVE", f"DEV account {a['account_number']} ACTIVE")
    line(int(a.get("options_trading_level") or 0) >= 3,
         f"options level {a.get('options_trading_level')}", "need 3 for multi-leg")
    line(not a.get("trading_blocked") and not a.get("account_blocked"),
         "account not blocked")
    cfg = c.account_config()
    line(not cfg.get("suspend_trade"), "suspend_trade is OFF",
         "a leftover halt would silently block everything")
    ok &= not cfg.get("suspend_trade")

    halted = (ROOT / "HALTED").exists()
    line(not halted, "no HALTED file")
    ok &= not halted

    line(True, "positions", str(len(c.positions())))
    line(True, "open orders", str(len(c.orders(status='open'))))
    line(True, "equity", f"${float(a['equity']):,.2f}")

    # data path
    spot = c.latest_trade("SPY")
    line(bool(spot), "SPY quote", f"${spot}")
    from agent import options as O
    exp = c.expirations("SPY", date.today().isoformat(),
                        (date.today() + timedelta(days=10)).isoformat())
    line(bool(exp), "expiries available", ", ".join(exp[:4]))
    # must test an expiry the agent would actually trade, i.e. one inside
    # [MIN_DTE, MAX_DTE] — a nearer expiry is rejected by the DTE gate and would
    # show 0 usable contracts for the wrong reason.
    tradable = [e for e in exp
                if config.MIN_DTE <= (date.fromisoformat(e) - date.today()).days
                <= config.MAX_DTE]
    line(bool(tradable), f"expiries inside the {config.MIN_DTE}-{config.MAX_DTE} DTE window",
         ", ".join(tradable) or "NONE — agent cannot trade")
    ok &= bool(tradable)
    if tradable and spot:
        target = min(tradable, key=lambda e: abs(
            (date.fromisoformat(e) - date.today()).days - config.TARGET_DTE))
        dte = (date.fromisoformat(target) - date.today()).days
        chain = c.option_chain("SPY", exp=target,
                               strike_gte=spot*0.96, strike_lte=spot*1.04)
        v = O.usable_contracts(chain)
        line(len(v) > 10, f"usable contracts with Greeks ({target}, {dte} DTE)",
             str(len(v)))
        ok &= len(v) > 10

    print()
    if ok and is_open:
        print("  → READY. Next: python scripts/golive.py --stage 2")
    elif ok:
        print("  → All checks pass but the market is closed. Wait for the open.")
    else:
        print(f"  → {BAD} Fix the failures above before proceeding.")
    return ok and is_open


# ──────────────────────────────────────────────── stage 2: real fill on DEV
def stage2(width):
    hdr(f"STAGE 2 — FILL TEST ON DEV (submits 1 order)   {now_str()}")
    print("  Submits ONE 1-lot SPY vertical priced to fill, then watches it.\n")
    r = subprocess.run([sys.executable, "scripts/t1_fill_test.py",
                        "--width", str(width), "--live"], cwd=ROOT)
    if r.returncode != 0:
        print(f"\n  {BAD} fill test failed — do NOT proceed to COMP")
        return False

    from agent.client import AlpacaClient
    c = AlpacaClient()
    filled = [o for o in c.orders(status="all", limit=50)
              if o.get("status") == "filled"]
    pos = c.option_positions()
    line(bool(filled), "at least one order FILLED", f"{len(filled)} filled")
    line(bool(pos), "position exists at the broker", f"{len(pos)} option legs")
    if pos:
        for p in pos:
            print(f"      {p['symbol']}  qty {p['qty']}  "
                  f"avg ${p['avg_entry_price']}  P&L ${p['unrealized_pl']}")
    print()
    if filled and pos:
        print("  → T1 CLEARED. Next: python scripts/golive.py --stage 3 (close it)")
        return True
    print(f"  → {WARN}no fill yet. Wait, then re-check with --stage 2 --check-only")
    return False


# ──────────────────────────────────────────────── stage 3: close the test
def stage3():
    hdr(f"STAGE 3 — CLOSE THE TEST POSITION   {now_str()}")
    r = subprocess.run([sys.executable, "scripts/t1_fill_test.py",
                        "--close", "--live"], cwd=ROOT)
    from agent.client import AlpacaClient
    c = AlpacaClient()
    time.sleep(3)
    pos = c.option_positions()
    line(not pos, "DEV option positions closed", f"{len(pos)} remaining")
    print()
    print("  → Next: python scripts/golive.py --stage 4")
    return not pos


# ──────────────────────────────────────────── stage 4: COMP account preflight
def stage4():
    hdr(f"STAGE 4 — COMPETITION ACCOUNT PREFLIGHT   {now_str()}")
    from dotenv import dotenv_values
    env = dotenv_values(ROOT / ".env")
    key, sec = env.get("COMP_ALPACA_API_KEY"), env.get("COMP_ALPACA_SECRET_KEY")
    num = env.get("COMP_ACCOUNT_NUMBER")

    if not key or not sec:
        print(f"  {BAD} COMP keys are not in .env yet.\n")
        print("  Do this in the Alpaca dashboard:")
        print("    1. switch to the account whose number is PA3BAT1OOEFE")
        print("    2. Home -> API Keys -> Generate New Keys")
        print("    3. paste them into .env as:")
        print("         COMP_ALPACA_API_KEY=...")
        print("         COMP_ALPACA_SECRET_KEY=...")
        print("    4. re-run: python scripts/golive.py --stage 4")
        return False

    from agent.client import AlpacaClient
    c = AlpacaClient(key=key, secret=sec)
    a = c.account()
    ok = True
    ok &= line(a["account_number"] == num,
               f"account number matches ({a['account_number']})",
               f"expected {num}")
    eq = float(a["equity"])
    ok &= line(abs(eq - 100_000) < 0.01, f"equity is exactly $100,000",
               f"${eq:,.2f}")
    ok &= line(int(a.get("options_trading_level") or 0) >= 3,
               f"options level {a.get('options_trading_level')}")
    ok &= line(a["status"] == "ACTIVE", "ACTIVE")
    ok &= line(not a.get("trading_blocked"), "not blocked")
    pos, orders = c.positions(), c.orders(status="all", limit=20)
    ok &= line(not pos, "no positions (account is pristine)", f"{len(pos)}")
    ok &= line(not orders, "no order history (never traded)", f"{len(orders)}")
    cfg = c.account_config()
    ok &= line(not cfg.get("suspend_trade"), "suspend_trade OFF")

    print(f"\n  account id (for the submission form): {a['id']}")
    print(f"  account number:                       {a['account_number']}")
    print()
    if ok:
        print("  → COMP is clean and ready. Next: python scripts/golive.py --stage 5")
    else:
        print(f"  → {BAD} do not go live until the above is resolved")
    return ok


# ─────────────────────────────────────────────── stage 5: start on COMP
def stage5(interval):
    hdr(f"STAGE 5 — START THE AGENT ON THE COMPETITION ACCOUNT   {now_str()}")
    print("  This is the account judges will score. From here, its P&L is your result.\n")
    print(f"  cycle interval: {interval}s")
    print("  stop with Ctrl-C; positions stay open and are managed on restart\n")
    reply = input('  type "GO LIVE" to start: ').strip()
    if reply != "GO LIVE":
        print("  aborted.")
        return False
    env = {**os.environ, "ACCOUNT": "comp", "DRY_RUN": "false"}
    print("\n  starting...\n")
    os.execve(sys.executable,
              [sys.executable, "run.py", "loop", "--live", "--interval", str(interval)],
              env)


ap = argparse.ArgumentParser()
ap.add_argument("--stage", type=int, default=1, choices=[1, 2, 3, 4, 5])
ap.add_argument("--width", type=int, default=4)
ap.add_argument("--interval", type=int, default=300)
a = ap.parse_args()

try:
    ok = {1: lambda: stage1(), 2: lambda: stage2(a.width), 3: lambda: stage3(),
          4: lambda: stage4(), 5: lambda: stage5(a.interval)}[a.stage]()
except KeyboardInterrupt:
    print("\ninterrupted")
    sys.exit(130)
sys.exit(0 if ok else 1)
