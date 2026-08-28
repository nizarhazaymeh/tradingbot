"""Live on-chain execution — real pump.fun buy/sell.

Approach (key never leaves this machine):
  1. Ask PumpPortal's trade-local API to BUILD an unsigned swap transaction.
  2. Sign it locally with our burner keypair (solders).
  3. Send the signed bytes through our own Helius RPC.

PumpPortal builds the (fragile, version-sensitive) pump.fun instruction so we
don't hand-roll it; but it never sees our private key — it only gets our public
key and returns an unsigned transaction for us to sign.

A bug here spends real SOL. Everything is gated behind DRY_RUN in main.py and a
hard daily cap. This module itself refuses to run without a key.
"""
import json
import urllib.request

from solders.keypair import Keypair
from solders.transaction import VersionedTransaction

from sniper import config

TRADE_LOCAL_URL = "https://pumpportal.fun/api/trade-local"


def _keypair() -> Keypair:
    if not config.WALLET_PRIVATE_KEY:
        raise RuntimeError("WALLET_PRIVATE_KEY is empty — cannot sign live trades.")
    return Keypair.from_base58_string(config.WALLET_PRIVATE_KEY)


def _build_tx(pubkey: str, action: str, mint: str, amount, denominated_in_sol: bool):
    """Ask PumpPortal to build an unsigned swap tx. Returns raw tx bytes."""
    body = json.dumps({
        "publicKey": pubkey,
        "action": action,                       # "buy" | "sell"
        "mint": mint,
        "amount": amount,                        # SOL (buy) or token amount / "100%" (sell)
        "denominatedInSol": "true" if denominated_in_sol else "false",
        "slippage": int(config.SLIPPAGE_PCT * 100),
        "priorityFee": config.PRIORITY_FEE_SOL,
        "pool": "pump",
    }).encode()
    req = urllib.request.Request(TRADE_LOCAL_URL, data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        if r.status != 200:
            raise RuntimeError(f"trade-local HTTP {r.status}")
        return r.read()


def _send_signed(tx_bytes: bytes, kp: Keypair) -> str:
    """Sign the built tx with our key and broadcast via Helius. Returns signature."""
    unsigned = VersionedTransaction.from_bytes(tx_bytes)
    signed = VersionedTransaction(unsigned.message, [kp])
    raw = bytes(signed)
    import base64
    payload = json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "sendTransaction",
        "params": [base64.b64encode(raw).decode(),
                   {"encoding": "base64", "skipPreflight": True, "maxRetries": 3}],
    }).encode()
    req = urllib.request.Request(config.RPC_HTTP, data=payload,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        res = json.loads(r.read())
    if "error" in res:
        raise RuntimeError(f"sendTransaction error: {res['error']}")
    return res["result"]


def buy(mint: str, sol_amount: float) -> str:
    """Buy `sol_amount` SOL worth of `mint`. Returns the tx signature."""
    kp = _keypair()
    tx = _build_tx(str(kp.pubkey()), "buy", mint, sol_amount, denominated_in_sol=True)
    return _send_signed(tx, kp)


def sell(mint: str, percent: str = "100%") -> str:
    """Sell `percent` of our `mint` holdings (default all). Returns the tx signature."""
    kp = _keypair()
    tx = _build_tx(str(kp.pubkey()), "sell", mint, percent, denominated_in_sol=False)
    return _send_signed(tx, kp)


def solscan(sig: str) -> str:
    return f"https://solscan.io/tx/{sig}"
