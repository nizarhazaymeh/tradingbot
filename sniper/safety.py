"""Safety gate — decide whether a freshly-launched token is worth touching.

Fresh pump.fun tokens are guilty until proven innocent: ~98% are rugs,
honeypots, or dev-bundled dumps. This module runs cheap on-chain checks and
returns a verdict. A token that fails ANY hard check is never bought.

These checks reduce risk; they do NOT make sniping safe. A token can pass
every check here and still rug 10 seconds later. There is no honeypot check
that fully protects you on a brand-new launch.

All checks are READ-ONLY RPC calls.
"""
import json
import time
import urllib.request
from dataclasses import dataclass, field
from typing import List


@dataclass
class Verdict:
    ok: bool
    reasons: List[str] = field(default_factory=list)   # why it failed
    notes: List[str] = field(default_factory=list)     # info / soft flags


def _rpc(url: str, method: str, params: list):
    req = urllib.request.Request(
        url,
        data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read()).get("result")


def check_token(rpc_http: str, mint: str, bonding_curve: str,
                max_creator_hold_pct: float, min_other_holders: int) -> Verdict:
    """Run the safety checks against a mint. Returns a Verdict."""
    v = Verdict(ok=True)

    # --- 1. Mint authority & freeze authority (the big honeypot tells) ---
    try:
        # Fresh mints take a beat to be queryable; retry at 'processed' commitment.
        info = None
        for _ in range(6):
            info = _rpc(rpc_http, "getAccountInfo",
                        [mint, {"encoding": "jsonParsed", "commitment": "processed"}])
            if info and info.get("value"):
                break
            time.sleep(0.5)
        parsed = info["value"]["data"]["parsed"]["info"]
        mint_auth = parsed.get("mintAuthority")
        freeze_auth = parsed.get("freezeAuthority")
        supply = int(parsed.get("supply", 0))

        # Freeze authority set = they can freeze YOUR tokens so you can't sell.
        # This is the classic honeypot. Hard fail.
        if freeze_auth:
            v.ok = False
            v.reasons.append("freeze authority is set (can freeze your tokens — honeypot risk)")

        # Mint authority set = they can print unlimited new supply and dump.
        # pump.fun tokens normally have this revoked; if set, hard fail.
        if mint_auth:
            v.ok = False
            v.reasons.append("mint authority still set (can mint infinite supply)")
    except Exception as e:
        v.ok = False
        v.reasons.append(f"could not read mint account ({e})")
        return v  # without this we can't assess anything else

    # --- 2. Holder concentration (excluding the bonding curve itself) ---
    try:
        largest = _rpc(rpc_http, "getTokenLargestAccounts",
                       [mint, {"commitment": "processed"}]) or {}
        accounts = largest.get("value", [])
        # The bonding curve legitimately holds the un-bought supply at launch,
        # so we exclude it and look at how concentrated the REST is.
        non_curve = [a for a in accounts if a.get("address") != bonding_curve]
        other_holders = sum(1 for a in non_curve if int(a.get("amount", 0)) > 0)

        if supply > 0 and non_curve:
            top = max(int(a.get("amount", 0)) for a in non_curve)
            top_pct = top / supply
            if top_pct > max_creator_hold_pct:
                v.ok = False
                v.reasons.append(
                    f"top non-curve holder owns {top_pct*100:.0f}% "
                    f"(>{max_creator_hold_pct*100:.0f}% — dev dump risk)"
                )
            v.notes.append(f"top holder {top_pct*100:.1f}%, {other_holders} other holders")

        if other_holders < min_other_holders:
            v.notes.append(f"only {other_holders} holders so far (very fresh / thin)")
    except Exception as e:
        v.notes.append(f"holder check inconclusive ({e})")

    return v
