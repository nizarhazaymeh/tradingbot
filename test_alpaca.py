"""Verify the Alpaca connection end to end. Places NO orders.

Run:  python test_alpaca.py

Checks, in order: credentials -> account -> market clock -> historical bars
-> latest price -> open positions. Any failure prints what to fix.
"""
import logging
import sys

import config
from alpaca_client import AlpacaClient, AlpacaError, normalize_symbol, to_timeframe

logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")


def main() -> int:
    print("=" * 62)
    print("Alpaca connection test")
    print("=" * 62)

    if not config.ALPACA_API_KEY or not config.ALPACA_API_SECRET:
        print("\n✗ No Alpaca credentials found in .env\n")
        print("  1. Sign up / log in at https://app.alpaca.markets")
        print("  2. Home -> API Keys -> Generate New Key (the secret shows ONCE)")
        print("  3. Add to .env:")
        print("       ALPACA_API_KEY=your_key_id")
        print("       ALPACA_API_SECRET=your_secret_key")
        print("       ALPACA_PAPER=true")
        return 1

    endpoint = "paper-api.alpaca.markets" if config.ALPACA_PAPER else "api.alpaca.markets"
    print(f"Endpoint : {endpoint}")
    print(f"Key ID   : {config.ALPACA_API_KEY[:6]}…{config.ALPACA_API_KEY[-3:]}")
    print(f"Data feed: {config.ALPACA_FEED}")

    client = AlpacaClient(
        config.ALPACA_API_KEY, config.ALPACA_API_SECRET,
        paper=config.ALPACA_PAPER, feed=config.ALPACA_FEED,
    )

    # ---- 1. account -------------------------------------------------- #
    try:
        acct = client.get_account()
    except AlpacaError as e:
        print(f"\n✗ Authentication failed: {e}")
        if e.status in (401, 403):
            print("  Paper and live keys are NOT interchangeable — check that")
            print(f"  ALPACA_PAPER={config.ALPACA_PAPER} matches where you made the key.")
        return 1

    print("\n✓ Connected")
    print(f"  account       {acct.get('account_number')}  status={acct.get('status')}")
    print(f"  equity        ${float(acct.get('equity', 0)):,.2f}")
    print(f"  cash          ${float(acct.get('cash', 0)):,.2f}")
    print(f"  buying power  ${float(acct.get('buying_power', 0)):,.2f}")
    if acct.get("trading_blocked"):
        print("  ⚠ trading is BLOCKED on this account")

    # ---- 2. clock ---------------------------------------------------- #
    clock = client.get_clock()
    state = "OPEN" if clock.get("is_open") else "CLOSED"
    print(f"\n✓ US market {state}  (next open {clock.get('next_open')})")

    # ---- 3. data + positions per symbol ------------------------------ #
    ok = True
    for w in config.WATCHLIST:
        sym = normalize_symbol(w["symbol"])
        tfs = [w["entry_tf"]] + ([w["htf_tf"]] if w["htf_tf"] else [])
        label = f"{w['symbol']} -> {sym}" if sym != w["symbol"] else sym
        print(f"\n--- {label}  ({' + '.join(tfs)}) ---")
        try:
            for tf in tfs:
                closes = client.get_closes(sym, tf, 5)
                if not closes:
                    print(f"  ⚠ no bars returned for {to_timeframe(tf)}")
                    ok = False
                    continue
                print(f"  {to_timeframe(tf):>7}: "
                      + ", ".join(f"{c:,.2f}" for c in closes))
            print(f"  latest price: {client.get_latest_price(sym):,.2f}")
            pos = client.get_position(sym)
            print(f"  position: {pos['qty']} @ {float(pos['avg_entry_price']):,.2f} "
                  f"(P/L ${float(pos['unrealized_pl']):,.2f})" if pos else "  position: flat")
        except AlpacaError as e:
            print(f"  ✗ {e}")
            ok = False

    print("\n" + "=" * 62)
    print("✓ All checks passed." if ok else "⚠ Connected, but some data checks failed.")
    print("Next: run  python bot.py")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
