"""SUPERVISED single live trade — proof run before autonomous mode.

Does ONE real buy + sell on the next coin that passes safety + momentum, then
exits. Reports both transaction links and the real SOL P/L from the wallet
balance delta. This is how we verify live execution actually works before
letting main.py run on its own.

    python -m sniper.test_live

Requires the burner wallet to be funded. Spends real SOL (one BUY_AMOUNT_SOL).
"""
import asyncio
import json
import urllib.request

from solders.keypair import Keypair

from sniper import config, executor
from sniper.detector import watch_launches
from sniper.safety import check_token
from sniper.pumpfun import get_curve
from sniper.main import observe, manage  # reuse the same logic


def get_balance_sol(pubkey: str) -> float:
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "getBalance",
                          "params": [pubkey]}).encode()
    req = urllib.request.Request(config.RPC_HTTP, data=payload,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())["result"]["value"] / 1e9


async def run():
    kp = Keypair.from_base58_string(config.WALLET_PRIVATE_KEY)
    pub = str(kp.pubkey())
    bal = get_balance_sol(pub)
    print(f"Wallet {pub}\nBalance: {bal:.5f} SOL")

    need = config.BUY_AMOUNT_SOL + 0.01  # buy + fee/rent headroom
    if bal < need:
        print(f"\n✋ NOT FUNDED ENOUGH. Need >= {need:.3f} SOL to test "
              f"(buy {config.BUY_AMOUNT_SOL} + fees). Deposit and re-run.")
        return

    print(f"\nLIVE single-trade test. Will spend {config.BUY_AMOUNT_SOL} SOL on the "
          f"next coin passing safety + {config.MIN_SOL_MOMENTUM} SOL momentum.\n")

    async for L in watch_launches(config.RPC_WS):
        v = check_token(config.RPC_HTTP, L.mint, L.bonding_curve,
                        config.MAX_CREATOR_HOLD_PCT, config.MIN_OTHER_HOLDERS)
        if not v.ok:
            continue
        print(f"WATCH {L.symbol} — observing {config.OBSERVE_SECONDS}s...")
        decided, entry, sol_added, score, rank = await observe(L.mint, L.bonding_curve)
        if not decided:
            print(f"  weak ({sol_added:.2f} SOL, rank {rank}) — waiting for the next one")
            continue
        print(f"  PICKED — rank {rank}, score {score}/100")

        # ---- BUY ----
        print(f"\n>>> BUYING {L.symbol} for {config.BUY_AMOUNT_SOL} SOL ...")
        try:
            sig = await asyncio.to_thread(executor.buy, L.mint, config.BUY_AMOUNT_SOL)
        except Exception as e:
            print("BUY FAILED:", e); return
        print("BUY sent:", executor.solscan(sig))

        # ---- MANAGE + SELL ---- (reuses main.manage: TP/SL/timeout, then sells)
        await manage(L.symbol, L.mint, L.bonding_curve, entry)

        # ---- RESULT ----
        await asyncio.sleep(3)
        new_bal = get_balance_sol(pub)
        print(f"\n=== RESULT ===\nBalance: {bal:.5f} -> {new_bal:.5f} SOL "
              f"(net {new_bal - bal:+.5f} SOL, incl. fees)")
        return


if __name__ == "__main__":
    asyncio.run(run())
