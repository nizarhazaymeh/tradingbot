#!/usr/bin/env python3
"""Pre-submission check against the COMPETITION account.

Two failure modes this exists to catch, both silent:

  * Submitting DEV artifacts. docs/equity_curve.json and public/dashboard.json
    are generated from whichever account .env points at. A curve exported from
    DEV looks identical to a real one apart from the account_kind field.
  * A competition account that is not fresh. The rules require a new paper
    account starting at exactly $100,000, never used for testing. If it has
    prior activity, the P&L judges read is not the agent's.

Read-only unless --regenerate is passed. Never edits .env — that holds secrets
and is a human edit.

  ACCOUNT=comp python scripts/comp_preflight.py
  ACCOUNT=comp python scripts/comp_preflight.py --regenerate
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent import config
from agent.client import AlpacaClient, AlpacaError

EXPECTED_START = 100_000.0
FAILS, WARNS = [], []


def check(ok, label, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  — {detail}" if detail else ""))
    if not ok:
        FAILS.append(label)
    return ok


def warn(label, detail=""):
    print(f"  WARN  {label}" + (f"  — {detail}" if detail else ""))
    WARNS.append(label)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--regenerate", action="store_true",
                    help="rebuild dashboard.json and equity_curve.json from this account")
    a = ap.parse_args()

    print(f"\nACCOUNT={config.ACCOUNT!r}\n")

    if config.ACCOUNT != "comp":
        print("  This must run against the competition account.\n"
              "  Set ACCOUNT=comp in .env (or prefix the command) and re-run.\n")
        sys.exit(1)

    # ---- credentials ----
    check(bool(config.API_KEY), "COMP_ALPACA_API_KEY is set")
    check(bool(config.SECRET_KEY), "COMP_ALPACA_SECRET_KEY is set")
    check(bool(config.ACCOUNT_NUMBER), "COMP_ACCOUNT_NUMBER is set",
          config.ACCOUNT_NUMBER or "empty")
    if FAILS:
        print("\n  Fill these in from the competition account's dashboard, then re-run.\n")
        sys.exit(1)

    try:
        c = AlpacaClient()
        acct = c.account()
    except (AlpacaError, RuntimeError) as e:
        print(f"\n  Could not reach the account: {e}\n")
        sys.exit(1)

    print()
    check(acct["account_number"] == config.ACCOUNT_NUMBER,
          "connected account matches COMP_ACCOUNT_NUMBER",
          f"{acct['account_number']} vs {config.ACCOUNT_NUMBER}")
    check(acct["status"] == "ACTIVE", "account is ACTIVE", acct["status"])
    check(not acct.get("trading_blocked"), "trading not blocked")
    check(int(acct.get("options_trading_level") or 0) >= 3,
          "options level >= 3 (spreads permitted)",
          str(acct.get("options_trading_level")))

    # ---- freshness ----
    print()
    equity = float(acct["equity"])
    hist = c.portfolio_history(period="1M", timeframe="1D")
    base = float(hist.get("base_value") or 0)
    check(abs(base - EXPECTED_START) < 1.0,
          f"base value is ${EXPECTED_START:,.0f}", f"${base:,.2f}")

    acts = c.activities(activity_types="FILL")
    if acts:
        warn(f"{len(acts)} historical FILL activities on this account",
             "expected 0 before the agent trades — is this really a fresh account?")
    else:
        check(True, "no prior fills — account is unused")

    n_pos, n_ord = len(c.positions()), len(c.orders(status="open"))
    print(f"        equity ${equity:,.2f} · {n_pos} positions · {n_ord} open orders")

    # ---- artifacts ----
    print()
    for rel, key in [("docs/equity_curve.json", "account_kind"),
                     ("public/dashboard.json", None)]:
        p = ROOT / rel
        if not p.exists():
            warn(f"{rel} does not exist yet")
            continue
        try:
            d = json.loads(p.read_text())
        except json.JSONDecodeError:
            warn(f"{rel} is not valid JSON")
            continue
        acct_in_file = d.get("account") if isinstance(d.get("account"), str) \
                       else (d.get("account") or {}).get("account_id")
        kind = d.get(key) if key else (d.get("account") or {}).get("environment")
        ok = acct_in_file == config.ACCOUNT_NUMBER
        check(ok, f"{rel} was exported from COMP",
              f"holds {acct_in_file} ({kind})")

    if a.regenerate:
        print("\n  regenerating artifacts from this account...")
        for script in ("scripts/export_dashboard.py", "scripts/export_equity_curve.py"):
            r = subprocess.run([sys.executable, str(ROOT / script)],
                               capture_output=True, text=True, cwd=ROOT)
            print(f"    {script}: {'ok' if r.returncode == 0 else 'FAILED'}")
            if r.returncode:
                print("      " + (r.stderr.strip().splitlines() or ["?"])[-1])

    # ---- verdict ----
    print()
    if FAILS:
        print(f"  {len(FAILS)} check(s) failed:")
        for f in FAILS:
            print(f"    - {f}")
    if WARNS:
        print(f"  {len(WARNS)} warning(s):")
        for w in WARNS:
            print(f"    - {w}")
    if not FAILS and not WARNS:
        print("  All checks passed.")
    if not a.regenerate and not FAILS:
        print("\n  Re-run with --regenerate to rebuild the demo and curve from COMP.")
    print()
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
