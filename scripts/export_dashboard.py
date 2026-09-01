#!/usr/bin/env python3
"""Write public/dashboard.json — the single file the demo website reads.

Deliberately decoupled: the dashboard has no Alpaca credentials and cannot place
or cancel anything. It only reads this file.
"""
import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
# The PUBLIC dashboard must show the account judges will score, not the sandbox.
# This MUST run before agent.config is imported: config resolves ACCOUNT (and
# therefore the credentials and ledger path) at import time.
os.environ["ACCOUNT"] = os.environ.get("DASHBOARD_ACCOUNT", "comp")

from agent import config, options as O, regime as R          # noqa: E402
from agent.client import AlpacaClient, AlpacaError           # noqa: E402
from agent.state import Store                                # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "public" / "dashboard.json"


def plain_english(pos: dict) -> str:
    """Describe a position the way a non-trader would understand it."""
    legs = json.loads(pos["legs_json"])
    strikes = sorted({O.parse_occ(l["symbol"])[3] for l in legs})
    u = pos["underlying"]
    kind = pos["kind"]
    if kind == "iron_condor" and len(strikes) == 4:
        return f"Profits if {u} stays between ${strikes[1]:.0f} and ${strikes[2]:.0f}"
    if kind == "bull_put":
        return f"Profits if {u} stays above ${max(strikes):.0f}"
    if kind == "bear_call":
        return f"Profits if {u} stays below ${min(strikes):.0f}"
    if kind == "bull_call":
        return f"Profits if {u} rises above ${min(strikes):.0f}"
    if kind == "bear_put":
        return f"Profits if {u} falls below ${max(strikes):.0f}"
    return f"{u} {kind.replace('_', ' ')}"


def max_drawdown(curve):
    peak, worst = None, 0.0
    for p in curve:
        e = p["equity"]
        peak = e if peak is None else max(peak, e)
        if peak:
            worst = min(worst, e / peak - 1.0)
    return worst


def build() -> dict:
    store = Store()
    c = AlpacaClient()

    try:
        acct = c.account()
        equity = float(acct["equity"])
    except AlpacaError:
        acct, equity = {}, config.STARTING_EQUITY

    curve = [{"ts": r["ts"], "equity": r["equity"]} for r in store.equity_curve()]
    if not curve:
        curve = [{"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                  "equity": equity}]

    stats = store.stats()
    start = config.STARTING_EQUITY

    # --- per-underlying market read: what the market charges vs the real risk ---
    market = []
    for u in config.UNIVERSE:
        try:
            snap = c.stock_snapshots([u])
            spot = ((snap.get(u) or {}).get("latestTrade") or {}).get("p")
            bars = c.stock_bars([u], timeframe="1Day", limit=90)
            closes = [b["c"] for b in bars.get(u, [])]
            if not spot and closes:
                spot = closes[-1]
            exps = c.expirations(u, date.today().isoformat(),
                                 (date.today().replace(day=min(28, date.today().day)) ).isoformat())
            views = O.usable_contracts(
                c.option_chain(u, strike_gte=spot * 0.92, strike_lte=spot * 1.08))
            iv = O.atm_iv(views, spot) or 0.0
            rv = R.realized_vol(closes) or 0.0
            edge = iv - rv
            market.append({
                "underlying": u, "spot": round(spot, 2),
                "implied_vol": round(iv, 4), "realized_vol": round(rv, 4),
                "premium_edge": round(edge, 4),
                "verdict": "trade" if edge > 0.01 else "stand aside",
                "reason": ("market charges more than the real risk" if edge > 0.01
                           else "market charges LESS than the real risk"),
            })
        except Exception as e:
            market.append({"underlying": u, "error": str(e)[:120]})

    # --- open positions, in human terms ---
    positions = []
    for p in store.open_positions():
        positions.append({
            "id": p["signature"], "kind": p["kind"], "underlying": p["underlying"],
            "description": f"{p['underlying']} {p['kind'].replace('_', ' ')}",
            "opened_at": p["opened_at"], "qty": p["qty"],
            "credit_received": round(abs(p["entry_price"]) * 100 * p["qty"], 2)
                               if p["is_credit"] else 0.0,
            "cost_paid": 0.0 if p["is_credit"]
                         else round(abs(p["entry_price"]) * 100 * p["qty"], 2),
            "max_loss": round(p["max_loss"], 2),
            "unrealized_pnl": None,
            "expiry": p["expiry"],
            "days_to_expiry": (date.fromisoformat(p["expiry"]) - date.today()).days,
            "plain_english": plain_english(p),
        })

    # --- decision log ---
    decisions = []
    for d in store.decisions(limit=25):
        decisions.append({
            "ts": d["ts"], "underlying": d["underlying"],
            "decision": d["decision"], "gate": d["gate"] or "",
            "reason": (d["reason"] or "")[:160],
            "regime": d["regime"] or "",
        })

    funnel = store.funnel()
    return {
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "account": {
            "account_id": config.ACCOUNT_NUMBER,
            "environment": config.ACCOUNT,
            "equity": round(equity, 2),
            "starting_equity": start,
            "total_pnl": round(equity - start, 2),
            "total_pnl_pct": round((equity - start) / start, 5),
            "max_drawdown_pct": round(max_drawdown(curve), 5),
            "open_positions": len(positions),
            "closed_trades": stats["closed_trades"],
            "win_rate": stats["win_rate"],
            "realized_pnl": stats["realized_pnl"],
        },
        "equity_curve": curve,
        "market": market,
        "positions": positions,
        "decisions": decisions,
        "funnel": {
            "considered": sum(funnel.values()),
            "rejected": funnel.get("reject", 0),
            "submitted": funnel.get("submit", 0),
            "held": funnel.get("hold", 0),
            "closed": funnel.get("close", 0),
        },
        "gate_rejections": stats["gate_rejections"],
        "disclaimer": ("Paper trading simulation. Not investment advice. "
                       "Options involve significant risk."),
    }


if __name__ == "__main__":
    OUT.parent.mkdir(parents=True, exist_ok=True)
    data = build()
    OUT.write_text(json.dumps(data, indent=2, default=str))
    print(f"wrote {OUT}  ({OUT.stat().st_size:,} bytes)")
    a = data["account"]
    print(f"  account {a['account_id']} | equity ${a['equity']:,.2f} "
          f"({a['total_pnl_pct']:+.2%}) | open {a['open_positions']} "
          f"| closed {a['closed_trades']}")
    for m in data["market"]:
        if "error" in m:
            print(f"  {m['underlying']}: ERROR {m['error']}")
        else:
            print(f"  {m['underlying']}: charges {m['implied_vol']:.1%} vs risk "
                  f"{m['realized_vol']:.1%} -> {m['premium_edge']:+.1%} {m['verdict']}")
