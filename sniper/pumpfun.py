"""Read pump.fun bonding-curve state: price and buyer momentum.

A pump.fun token's price is set by its bonding curve, not an order book.
The curve account stores virtual reserves; price = sol_reserves / token_reserves.
By polling it we can both price a position and measure whether real buyers are
flowing in (sol reserves rising) right after launch.

READ-ONLY.
"""
import base64
import json
import struct
import urllib.request
from dataclasses import dataclass
from typing import Optional


@dataclass
class CurveState:
    virtual_token_reserves: int
    virtual_sol_reserves: int
    real_token_reserves: int
    real_sol_reserves: int
    token_total_supply: int
    complete: bool

    @property
    def price(self) -> float:
        """Relative price (SOL per token, decimals uncancelled — fine for ratios)."""
        if self.virtual_token_reserves == 0:
            return 0.0
        return self.virtual_sol_reserves / self.virtual_token_reserves

    @property
    def sol_in_curve(self) -> float:
        """Real SOL deposited so far (a proxy for genuine buyer interest)."""
        return self.real_sol_reserves / 1e9


def _rpc(url, method, params):
    req = urllib.request.Request(
        url,
        data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read()).get("result")


def get_curve(rpc_http: str, bonding_curve: str) -> Optional[CurveState]:
    """Fetch and decode a bonding-curve account. None if unreadable yet."""
    info = _rpc(rpc_http, "getAccountInfo",
                [bonding_curve, {"encoding": "base64", "commitment": "processed"}])
    if not info or not info.get("value"):
        return None
    try:
        raw = base64.b64decode(info["value"]["data"][0])
        # 8-byte Anchor discriminator, then five u64 LE + one bool.
        off = 8
        vtok, vsol, rtok, rsol, supply = struct.unpack_from("<QQQQQ", raw, off)
        off += 40
        complete = bool(raw[off]) if off < len(raw) else False
        return CurveState(vtok, vsol, rtok, rsol, supply, complete)
    except Exception:
        return None
