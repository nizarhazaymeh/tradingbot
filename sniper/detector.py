"""Pump.fun fresh-launch detector (Solana).

Subscribes to the pump.fun program's logs over a WebSocket RPC and decodes
the on-chain "create" event the moment a new token is minted — giving us the
token's name, symbol, mint address, and bonding curve within ~1 second of
launch.

This module is READ-ONLY. It detects and reports; it never spends anything.
The buy/sell logic lives elsewhere and is gated behind DRY_RUN + safety checks.

Run standalone to watch the firehose of new launches:
    python -m sniper.detector
"""
import asyncio
import base64
import json
import struct
from dataclasses import dataclass
from typing import AsyncIterator, Optional

import base58
import websockets

# The pump.fun bonding-curve program. New tokens are created here.
PUMP_FUN_PROGRAM = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"

# Anchor event discriminator (first 8 bytes of "Program data:") for CreateEvent.
# sha256("event:CreateEvent")[:8] — pump.fun's create event.
CREATE_EVENT_DISC = bytes([27, 114, 169, 77, 222, 235, 99, 118])


@dataclass
class Launch:
    name: str
    symbol: str
    uri: str
    mint: str
    bonding_curve: str
    creator: str
    signature: str


def _read_string(buf: bytes, off: int):
    """Borsh string: u32 little-endian length prefix + utf-8 bytes."""
    (length,) = struct.unpack_from("<I", buf, off)
    off += 4
    s = buf[off:off + length].decode("utf-8", errors="replace")
    return s, off + length


def _read_pubkey(buf: bytes, off: int):
    """32-byte pubkey -> base58 string."""
    raw = buf[off:off + 32]
    return base58.b58encode(raw).decode(), off + 32


def parse_create_event(data_b64: str) -> Optional[Launch]:
    """Decode a pump.fun CreateEvent from a 'Program data:' log line."""
    try:
        buf = base64.b64decode(data_b64)
    except Exception:
        return None
    if len(buf) < 8 or buf[:8] != CREATE_EVENT_DISC:
        return None
    try:
        off = 8
        name, off = _read_string(buf, off)
        symbol, off = _read_string(buf, off)
        uri, off = _read_string(buf, off)
        mint, off = _read_pubkey(buf, off)
        bonding_curve, off = _read_pubkey(buf, off)
        creator, off = _read_pubkey(buf, off)
        return Launch(name, symbol, uri, mint, bonding_curve, creator, signature="")
    except Exception:
        return None


async def watch_launches(ws_url: str) -> AsyncIterator[Launch]:
    """Yield a Launch for every new pump.fun token, as it is created."""
    sub = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "logsSubscribe",
        "params": [
            {"mentions": [PUMP_FUN_PROGRAM]},
            {"commitment": "processed"},
        ],
    }
    while True:  # reconnect loop — RPCs drop connections routinely
        try:
            async with websockets.connect(ws_url, ping_interval=20, max_size=None) as ws:
                await ws.send(json.dumps(sub))
                await ws.recv()  # subscription confirmation
                async for raw in ws:
                    msg = json.loads(raw)
                    try:
                        val = msg["params"]["result"]["value"]
                    except (KeyError, TypeError):
                        continue
                    sig = val.get("signature", "")
                    for line in val.get("logs", []):
                        if not line.startswith("Program data:"):
                            continue
                        launch = parse_create_event(line.split("Program data:", 1)[1].strip())
                        if launch:
                            launch.signature = sig
                            yield launch
                            break
        except Exception as e:
            print(f"[detector] connection dropped ({e}); reconnecting in 3s...")
            await asyncio.sleep(3)


async def _demo():
    # Public RPC works for a quick look but is rate-limited; use Helius for real.
    ws_url = "wss://api.mainnet-beta.solana.com"
    print(f"Watching pump.fun for fresh launches via {ws_url} ...\n")
    n = 0
    async for L in watch_launches(ws_url):
        n += 1
        print(f"#{n:>3}  {L.symbol:<10} {L.name[:24]:<24}  mint={L.mint}")
        if n >= 10:
            print("\n(stopping demo after 10 launches)")
            break


if __name__ == "__main__":
    asyncio.run(_demo())
