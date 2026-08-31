#!/usr/bin/env python3
"""Entry point.

  python run.py once            one cycle, dry run (safe)
  python run.py once --live     one cycle, real orders on the configured account
  python run.py loop            continuous
  python run.py status          account + book + stats
  python run.py flatten         close everything (needs --live)
"""
import argparse
import json
import sys

from agent import config, logsetup
from agent.cycle import Agent

# Console + rotating file. Must happen before Agent() so nothing logs into the
# void, and before any handler basicConfig() might otherwise install.
LOG_PATH = logsetup.setup()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["once", "loop", "status", "flatten"])
    ap.add_argument("--live", action="store_true", help="actually place orders")
    ap.add_argument("--no-llm", action="store_true")
    ap.add_argument("--interval", type=int, default=None)
    ap.add_argument("--no-new", action="store_true", help="manage exits only")
    ap.add_argument("--rehearse", action="store_true",
                    help="pretend the market is open (dry-run only)")
    a = ap.parse_args()

    dry = not a.live
    if a.command == "status":
        ag = Agent(dry_run=True, use_llm=False)
        acct = ag.c.account()
        print(json.dumps({
            "config": config.summary(),
            "account": {k: acct.get(k) for k in
                        ("account_number", "status", "equity", "cash", "buying_power",
                         "options_buying_power", "options_trading_level")},
            "clock": ag.c.clock(),
            "broker_positions": len(ag.c.positions()),
            "open_orders": len(ag.c.orders(status="open")),
            "tracked": len(ag.store.open_positions()),
            "stats": ag.store.stats(),
        }, indent=2, default=str))
        return

    if a.command == "flatten":
        ag = Agent(dry_run=dry, use_llm=False)
        print(json.dumps(ag.ex.halt_everything("manual flatten"), indent=2))
        return

    if a.rehearse and a.live:
        sys.exit("refusing to combine --rehearse with --live")
    logsetup.banner(a.command, dry_run=dry)
    ag = Agent(dry_run=dry, use_llm=not a.no_llm, rehearse=a.rehearse)
    if LOG_PATH:
        print(f"logging to {LOG_PATH}")
    if dry:
        print("🟡 DRY RUN — no orders will be placed. Use --live to trade.\n")
    else:
        print(f"🔴 LIVE on account '{config.ACCOUNT}' ({config.ACCOUNT_NUMBER})\n")

    if a.command == "once":
        out = ag.run_once(allow_new=not a.no_new)
        print("\n" + json.dumps(out, indent=2, default=str))
    else:
        ag.run_forever(interval=a.interval)


if __name__ == "__main__":
    main()
