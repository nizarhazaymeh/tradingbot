#!/usr/bin/env python3
"""Can the bot predict where price goes? Measured properly, on real sample size.

The README opens by refusing this question: "Most trading agents ask 'which way
will the market go?' — a question nobody answers reliably." Four measurements in
docs/BACKTEST.md agree, but every one of them was made on 19 entry dates, which
is not enough to conclude anything on its own.

Direction is different. Predicting it needs no option chain, so the sample is
every trading day rather than every expiry the agent traded — ~4,600 observations
instead of 19. This is the one claim in the repo that CAN be settled.

WHAT IS PREDICTED
    the sign of the forward 4-day return (config.TARGET_DTE), the horizon the
    agent actually holds over.

HOW IT IS VALIDATED
    Walk-forward by calendar year. To predict any day in year Y the model is
    fitted only on data strictly before Y, so no future information exists
    anywhere in a reported number. Features come from bars up to and including
    the prediction day.

THE ONLY BASELINE THAT MATTERS
    "always predict up". Equities rise most of the time, so a model that learns
    nothing at all still scores ~54%. Accuracy alone is meaningless here — the
    question is whether it beats the base rate, and by enough to pay for costs.

  python scripts/predict_direction.py
  python scripts/predict_direction.py --horizon 1 --symbols SPY
"""
import argparse
import json
import math
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent import config, indicators as ind, levels as L
from agent.client import AlpacaClient

FEATURES = ["ret1", "ret5", "ret20", "dist20", "dist50", "dist200", "rsi", "adx",
            "atr_pct", "range_pos", "rvol", "vol_ratio", "ma_stack"]


def build(bars, horizon):
    """One row per day: features from the past, label from the future."""
    closes = [b.c for b in bars]
    highs = [b.h for b in bars]
    lows = [b.l for b in bars]
    vols = [b.v for b in bars]
    atr_s = ind.atr_series(highs, lows, closes, 14)
    s20, s50, s200 = (ind.sma_series(closes, n) for n in (20, 50, 200))

    rows = []
    for i in range(200, len(bars) - horizon):
        atr = atr_s[i]
        if not atr or atr <= 0 or not s200[i]:
            continue
        c = closes[i]
        win = closes[max(0, i - 20):i + 1]
        hi, lo = max(highs[i - 19:i + 1]), min(lows[i - 19:i + 1])
        rets = [closes[j] / closes[j - 1] - 1 for j in range(i - 19, i + 1)]
        avg_v = statistics.mean(vols[i - 19:i + 1]) or 1.0
        stack = 1.0 if (s20[i] > s50[i] > s200[i]) else (
            -1.0 if (s20[i] < s50[i] < s200[i]) else 0.0)
        f = {
            "ret1": closes[i] / closes[i - 1] - 1,
            "ret5": closes[i] / closes[i - 5] - 1,
            "ret20": closes[i] / closes[i - 20] - 1,
            "dist20": (c - s20[i]) / atr,
            "dist50": (c - s50[i]) / atr,
            "dist200": (c - s200[i]) / atr,
            "rsi": ind.rsi(closes[:i + 1], 14) or 50.0,
            "adx": ind.adx(highs[:i + 1], lows[:i + 1], closes[:i + 1], 14) or 0.0,
            "atr_pct": atr / c,
            "range_pos": (c - lo) / (hi - lo) if hi > lo else 0.5,
            "rvol": statistics.pstdev(rets) * math.sqrt(252),
            "vol_ratio": vols[i] / avg_v,
            "ma_stack": stack,
        }
        fwd = closes[i + horizon] / c - 1
        rows.append({"t": bars[i].t[:10] if isinstance(bars[i].t, str) else str(bars[i].t),
                     "f": f, "y": 1 if fwd > 0 else 0, "fwd": fwd})
    return rows


# ------------------------------------------------------------------ logistic
def fit(rows, lam=1.0, iters=800, lr=0.5):
    X = [[r["f"][c] for c in FEATURES] for r in rows]
    y = [r["y"] for r in rows]
    d = len(FEATURES)
    mu = [statistics.mean(col) for col in zip(*X)]
    sd = [statistics.pstdev(col) or 1.0 for col in zip(*X)]
    Z = [[(v - m) / s for v, m, s in zip(x, mu, sd)] for x in X]
    b, b0 = [0.0] * d, 0.0
    n = len(Z)
    for _ in range(iters):
        gb, g0 = [0.0] * d, 0.0
        for zi, yi in zip(Z, y):
            p = 1.0 / (1.0 + math.exp(-max(-30, min(30, sum(w * v for w, v in zip(b, zi)) + b0))))
            e = p - yi
            for j in range(d):
                gb[j] += e * zi[j]
            g0 += e
        b = [w - lr * (gb[j] / n + lam * w / n) for j, w in enumerate(b)]
        b0 -= lr * g0 / n
    return {"mu": mu, "sd": sd, "b": b, "b0": b0}


def predict(m, r):
    z = [(r["f"][c] - mu) / sd for c, mu, sd in zip(FEATURES, m["mu"], m["sd"])]
    return 1.0 / (1.0 + math.exp(-max(-30, min(30,
                  sum(w * v for w, v in zip(m["b"], z)) + m["b0"]))))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default="SPY,QQQ,IWM")
    ap.add_argument("--horizon", type=int, default=config.TARGET_DTE)
    ap.add_argument("--out", default="docs/predict_direction.json")
    a = ap.parse_args()

    syms = [s.strip().upper() for s in a.symbols.split(",") if s.strip()]
    c = AlpacaClient()
    print(f"\nfetching {', '.join(syms)} daily bars ...")
    rows = []
    for s in syms:
        r = c._data("/v2/stocks/bars", {"symbols": s, "timeframe": "1Day",
                                        "start": "2015-01-01", "end": "2026-08-31",
                                        "limit": 10000, "adjustment": "all",
                                        "feed": config.STOCK_FEED})
        bars = L.bars_from_api((r.get("bars") or {}).get(s, []))
        got = build(bars, a.horizon)
        for g in got:
            g["sym"] = s
        rows += got
        print(f"  {s}: {len(bars)} bars -> {len(got)} labelled observations")

    rows.sort(key=lambda r: r["t"])
    years = sorted({r["t"][:4] for r in rows})
    print(f"\n  {len(rows)} observations, {years[0]}-{years[-1]}, "
          f"horizon {a.horizon} trading days")

    print(f"\n{'='*94}")
    print("  WALK-FORWARD BY YEAR — each year predicted by a model fitted only on")
    print("  data from BEFORE it. Compared against 'always predict up'.")
    print(f"{'='*94}")
    print(f"  {'year':6} {'n':>5} {'base rate':>10} {'model acc':>10} "
          f"{'edge':>8} {'n up-calls':>11} {'up-call acc':>12}")
    print(f"  {'-'*90}")

    folds, all_pred = [], []
    for y in years:
        train = [r for r in rows if r["t"][:4] < y]
        test = [r for r in rows if r["t"][:4] == y]
        if len(train) < 500 or len(test) < 50:
            continue
        m = fit(train)
        base = sum(r["y"] for r in test) / len(test)
        preds = [(predict(m, r), r) for r in test]
        acc = sum(1 for p, r in preds if (p >= 0.5) == bool(r["y"])) / len(preds)
        ups = [(p, r) for p, r in preds if p >= 0.5]
        up_acc = (sum(r["y"] for _, r in ups) / len(ups)) if ups else float("nan")
        edge = acc - max(base, 1 - base)
        all_pred += preds
        folds.append({"year": y, "n": len(test), "base": round(base, 4),
                      "acc": round(acc, 4), "edge": round(edge, 4)})
        print(f"  {y:6} {len(test):>5} {base:>9.1%} {acc:>9.1%} {edge:>+8.1%} "
              f"{len(ups):>11} {up_acc:>11.1%}")

    print(f"  {'-'*90}")
    if folds:
        mb = statistics.mean(f["base"] for f in folds)
        ma_ = statistics.mean(f["acc"] for f in folds)
        me = statistics.mean(f["edge"] for f in folds)
        beat = sum(1 for f in folds if f["edge"] > 0)
        print(f"  {'MEAN':6} {'':>5} {mb:>9.1%} {ma_:>9.1%} {me:>+8.1%}")
        print(f"\n  beat the majority-class baseline in {beat} of {len(folds)} years")

    # does confidence mean anything? a real signal should sharpen with conviction
    print(f"\n{'='*94}")
    print("  CONFIDENCE BUCKETS — a real edge gets MORE accurate as it gets surer")
    print(f"{'='*94}")
    print(f"  {'p(up)':16} {'n':>6} {'actual up rate':>16} {'mean fwd return':>17}")
    print(f"  {'-'*90}")
    buckets = [(0.0, 0.40), (0.40, 0.45), (0.45, 0.50), (0.50, 0.55),
               (0.55, 0.60), (0.60, 1.01)]
    for lo, hi in buckets:
        sel = [(p, r) for p, r in all_pred if lo <= p < hi]
        if len(sel) < 30:
            continue
        up = sum(r["y"] for _, r in sel) / len(sel)
        fwd = statistics.mean(r["fwd"] for _, r in sel)
        print(f"  {f'{lo:.2f} - {hi:.2f}':16} {len(sel):>6} {up:>15.1%} {fwd:>+16.2%}")

    Path(ROOT / a.out).write_text(json.dumps(
        {"horizon": a.horizon, "symbols": syms, "n": len(rows), "folds": folds},
        indent=2))
    print(f"\n  wrote {a.out}\n")


if __name__ == "__main__":
    main()
