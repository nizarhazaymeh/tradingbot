"""Quick live test: catch a few fresh launches and run the safety gate on each."""
import asyncio
from sniper import config
from sniper.detector import watch_launches
from sniper.safety import check_token


async def main():
    n = 0
    async for L in watch_launches(config.RPC_WS):
        n += 1
        v = check_token(config.RPC_HTTP, L.mint, L.bonding_curve,
                        config.MAX_CREATOR_HOLD_PCT, config.MIN_OTHER_HOLDERS)
        verdict = "PASS ✓" if v.ok else "REJECT ✗"
        print(f"\n#{n} {L.symbol} ({L.name[:20]}) -> {verdict}")
        for r in v.reasons:
            print(f"    reject: {r}")
        for note in v.notes:
            print(f"    note:   {note}")
        if n >= 5:
            break


if __name__ == "__main__":
    asyncio.run(main())
