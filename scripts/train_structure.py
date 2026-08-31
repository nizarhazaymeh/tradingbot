#!/usr/bin/env python3
"""Train a market-structure model on historical trades — and test whether it generalises.

`agent/levels.py` computes real market structure: swing pivots, supply/demand
zones, Fibonacci retracements. Commit 20b4856 wired one hand-written rule from it
into the trend filter (structure must corroborate the z-score) and 65b79fb
reverted it — the rule lost money. But one hand-written rule failing is not
evidence that structure carries no information. It is evidence that *that rule*
was wrong.

This asks the question properly: let history choose the rule.

  1. Rebuild the market context at every entry date in the four recorded backtest
     windows, using ONLY bars that had closed by that date. No lookahead.
  2. Turn structure into numbers: where price sits in its range, how many ATRs of
     room the short strike has, whether a supply/demand zone stands between spot
     and that strike, how worked that zone is, swing structure, Fibonacci pocket.
  3. Fit a ridge regression predicting each trade's return-on-risk (pnl divided
     by max loss) from those numbers, and derive an admission threshold.
  4. Score it LEAVE-ONE-WINDOW-OUT. Every number reported for a window comes from
     a model that never saw that window — the regularisation strength and the
     admission threshold are chosen on the training windows too, by an inner
     leave-one-out, so nothing about the test fold leaks into the fit.

Three rows per fold:

  naive     every recorded trade — what no filter at all produces
  shipped   the agent as committed: trend-z side filter + condor vol ceiling
  learned   the structure model, fitted on the other three windows

If `learned` does not beat `shipped` out-of-sample, structure does not earn a
place in the admission path, and this script is the evidence for leaving it out.

WHAT IT FOUND (docs/BACKTEST.md, Part 5). The model lost: naive +$2,701, shipped
+$411, learned -$1,330, beating shipped in 2 of 4 windows. Fourteen parameters on
277 trades from 19 entry dates cannot be fitted, and it is not wired in.

The useful output came from the baseline, not the model. Split by the direction
regime.trend_score() reports, the shipped trend veto blocks the better bucket on
both sides -- refused call spreads made +$954 against -$1,197 admitted, refused
put spreads +$1,067 -- and there is a mechanism: a downtrend is when put premium
is richest, so the veto refuses to sell exactly where the variance risk premium
is widest. 19 entry dates is not enough to act on. It is enough to stop calling
the filter well-supported.

  python scripts/train_structure.py                 # full run (fetches, then cached)
  python scripts/train_structure.py --features structure   # structure alone, no trend/vol
  python scripts/train_structure.py --refresh       # rebuild the dataset from the API
"""
import argparse
import json
import math
import statistics
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent import config, indicators as ind, levels as L
from agent.client import AlpacaClient, AlpacaError
from agent.regime import realized_vol, trend_score

# The four recorded windows, labelled as docs/BACKTEST.md and walk_forward.py do.
WINDOWS = [
    ("calm/rising",   "docs/backtest_results.json"),
    ("vol spike 46%", "docs/backtest_apr2025.json"),
    ("selloff -7.7%", "docs/backtest_mar2026.json"),
    ("carry unwind",  "docs/backtest_aug2024.json"),
]

# strategy name -> (offset from spot, threatened side)
STRATS = {
    "put_credit_1.5":  (-0.015, "P"),
    "put_credit_3.0":  (-0.030, "P"),
    "call_credit_1.5": (0.015,  "C"),
    "call_credit_3.0": (0.030,  "C"),
    "iron_condor_2.2": (0.022,  "IC"),
}

# Structure only — everything here comes out of agent/levels.py or the bar range.
STRUCTURE_FEATURES = [
    "struct_up",         # levels.market_structure() == "up"
    "struct_down",       # ... == "down"          ("range" is the omitted baseline)
    "range_pos",         # where spot sits in its 20-day high/low range, 0..1
    "golden",            # spot inside the 0.5-0.618 pocket of the last impulse
    "barrier_atr",       # ATRs of room between spot and the short strike
    "protected",         # a supply/demand zone stands in the way of the short strike
    "protect_dist_atr",  # how far away that zone is, in ATRs (0 when none)
    "protect_touches",   # times price has already worked it (0 = fresh = strongest)
]
# Trend and volatility — the filters the agent already ships, as continuous inputs.
TREND_FEATURES = [
    "threat_trend",      # z-score signed so POSITIVE means trending INTO the short strike
    "rv20",              # realised vol, annualised
    "adx",               # trend strength
    "rsi",               # momentum
    "atr_pct",           # ATR as a fraction of spot
    "is_condor",         # condors are a bet on stillness, not direction
]

LAMBDAS = [0.3, 1.0, 3.0, 10.0, 30.0, 100.0]
THRESHOLDS = [None] + [round(-0.06 + 0.01 * i, 3) for i in range(22)]   # None = admit all
MIN_ADMITTED = 8          # a rule that admits fewer than this on a fold is not measurable


# --------------------------------------------------------------------- stats
def stat(trades):
    """Net, win rate, profit factor, and expectancy in both dollars and R."""
    if not trades:
        return None
    p = [t["pnl"] for t in trades]
    r = [t["R"] for t in trades]
    w = [x for x in p if x > 0]
    l = [x for x in p if x <= 0]
    gp, gl = sum(w), abs(sum(l))
    return {"n": len(p), "net": round(sum(p), 2), "win": len(w) / len(p),
            "pf": round(gp / gl, 2) if gl else None,
            "exp": round(statistics.mean(p), 2),
            "R": round(statistics.mean(r), 4)}


def row(label, s, width=30):
    if not s:
        print(f"  {label:{width}} — no trades")
        return
    pf = f"{s['pf']:>6.2f}" if s["pf"] is not None else "     —"
    print(f"  {label:{width}} {s['n']:>4} {s['win']*100:>4.0f}% {s['net']:>+9.0f} "
          f"{pf} {s['exp']:>+9.2f} {s['R']:>+8.3f}")


# ------------------------------------------------------------------- context
class Context:
    """Market context at an entry date, built from bars up to and including it."""

    def __init__(self, client, cache_dir):
        self.c = client
        self.dir = Path(cache_dir)
        self.dir.mkdir(parents=True, exist_ok=True)

    def bars(self, underlying, entry):
        import hashlib
        key = f"ctxbars|{underlying}|{entry.isoformat()}"
        f = self.dir / (hashlib.sha1(key.encode()).hexdigest()[:20] + ".json")
        if f.exists():
            try:
                return json.loads(f.read_text())
            except Exception:
                pass
        res = self.c._data("/v2/stocks/bars", {
            "symbols": underlying, "timeframe": "1Day",
            "start": (entry - timedelta(days=520)).isoformat(),
            "end": entry.isoformat(), "limit": 10000, "adjustment": "all",
            "feed": config.STOCK_FEED})
        rows = [r for r in (res.get("bars") or {}).get(underlying, [])
                if r["t"][:10] <= entry.isoformat()]
        try:
            f.write_text(json.dumps(rows))
        except Exception:
            pass
        return rows

    def at(self, underlying, entry):
        """Everything derivable from price history as of `entry`, or None."""
        ohlc = L.bars_from_api(self.bars(underlying, entry))
        if len(ohlc) < 80:
            return None
        closes = [b.c for b in ohlc]
        highs = [b.h for b in ohlc]
        lows = [b.l for b in ohlc]
        spot = closes[-1]
        atr = ind.atr(highs, lows, closes, 14)
        if not atr or atr <= 0:
            return None

        z, zdir = trend_score(closes)
        pv = L.pivots(ohlc)
        struct = L.market_structure(pv)
        zones = L.find_zones(ohlc)

        hi20, lo20 = max(highs[-20:]), min(lows[-20:])
        range_pos = (spot - lo20) / (hi20 - lo20) if hi20 > lo20 else 0.5

        golden = 0.0
        imp = L.last_impulse(ohlc, pv)
        if imp:
            golden = 1.0 if L.fibonacci(*imp).in_golden_pocket(spot) else 0.0

        return {"spot": spot, "atr": atr, "z": z, "zdir": zdir, "structure": struct,
                "zones": zones, "range_pos": range_pos, "golden": golden,
                "rv20": realized_vol(closes) or 0.0,
                "adx": ind.adx(highs, lows, closes, 14) or 0.0,
                "rsi": ind.rsi(closes, 14) or 50.0}


def features_for(ctx, strategy):
    """Context + strategy -> the feature vector for one trade."""
    off, side = STRATS[strategy]
    spot, atr = ctx["spot"], ctx["atr"]
    zones = ctx["zones"]

    def protection(strike, kind):
        z = L.protects_short(zones, spot, strike, kind)
        if not z:
            return 0.0, 0.0, 0.0
        dist = (z.mid - spot) / atr if kind == "C" else (spot - z.mid) / atr
        return 1.0, max(dist, 0.0), float(z.touches)

    if side == "IC":
        # A condor is threatened on both sides, so it is only protected if both
        # sides are, and its barrier is whichever side has less room.
        kc, kp = round(spot * (1 + off)), round(spot * (1 - off))
        pc, dc, tc = protection(kc, "C")
        pp, dp, tp = protection(kp, "P")
        protected = 1.0 if (pc and pp) else 0.0
        pdist = min(dc, dp) if protected else 0.0
        touches = max(tc, tp) if protected else 0.0
        barrier = abs(off) * spot / atr
        threat = abs(ctx["z"])                 # either direction hurts a condor
    else:
        strike = round(spot * (1 + off))
        protected, pdist, touches = protection(strike, side)
        barrier = abs(strike - spot) / atr
        threat = ctx["z"] if side == "C" else -ctx["z"]

    return {
        "struct_up": 1.0 if ctx["structure"] == "up" else 0.0,
        "struct_down": 1.0 if ctx["structure"] == "down" else 0.0,
        "range_pos": ctx["range_pos"],
        "golden": ctx["golden"],
        "barrier_atr": barrier,
        "protected": protected,
        "protect_dist_atr": pdist,
        "protect_touches": touches,
        "threat_trend": threat,
        "rv20": ctx["rv20"],
        "adx": ctx["adx"],
        "rsi": ctx["rsi"],
        "atr_pct": atr / spot,
        "is_condor": 1.0 if side == "IC" else 0.0,
    }


def build_dataset(refresh=False, path="docs/structure_dataset.json"):
    """One row per recorded trade: outcome + no-lookahead features at entry."""
    out = ROOT / path
    if out.exists() and not refresh:
        d = json.loads(out.read_text())
        print(f"  dataset: {len(d['rows'])} trades from {path} (--refresh to rebuild)")
        return d["rows"]

    ctxs = Context(AlpacaClient(), ROOT / ".cache" / "structure")
    rows, skipped = [], 0
    cache = {}
    for label, src in WINDOWS:
        data = json.loads((ROOT / src).read_text())
        for t in data["trades"]:
            if t["strategy"] not in STRATS or not t.get("max_loss"):
                skipped += 1
                continue
            key = (t["underlying"], t["entry"])
            if key not in cache:
                try:
                    cache[key] = ctxs.at(t["underlying"], date.fromisoformat(t["entry"]))
                except AlpacaError as e:
                    print(f"  {key[0]} {key[1]}: skip ({e.status})")
                    cache[key] = None
            ctx = cache[key]
            if ctx is None:
                skipped += 1
                continue
            rows.append({
                "window": label, "underlying": t["underlying"], "entry": t["entry"],
                "strategy": t["strategy"], "pnl": t["pnl"], "max_loss": t["max_loss"],
                "R": round(t["pnl"] / t["max_loss"], 5),
                "structure": ctx["structure"], "z": round(ctx["z"], 3),
                "zdir": ctx["zdir"],
                "rv": round(ctx["rv20"], 4),
                "f": {k: round(v, 5) for k, v in features_for(ctx, t["strategy"]).items()},
            })
        print(f"  {label:16} {sum(1 for r in rows if r['window'] == label):>4} trades")
    if skipped:
        print(f"  skipped {skipped} trades with no usable context")
    out.write_text(json.dumps({"rows": rows}, indent=1))
    print(f"  wrote {path}")
    return rows


# --------------------------------------------------------------- ridge model
def solve(A, b):
    """Gauss-Jordan with partial pivoting. n is ~14, so this is plenty."""
    n = len(A)
    M = [list(A[i]) + [b[i]] for i in range(n)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(M[r][col]))
        if abs(M[piv][col]) < 1e-12:
            return None
        M[col], M[piv] = M[piv], M[col]
        d = M[col][col]
        M[col] = [x / d for x in M[col]]
        for r in range(n):
            if r != col and M[r][col]:
                fac = M[r][col]
                M[r] = [x - fac * y for x, y in zip(M[r], M[col])]
    return [M[i][n] for i in range(n)]


class Ridge:
    """Ridge regression on standardised features, intercept unpenalised.

    Closed form, so there is no learning rate or convergence to argue about:
    beta = (X'X + lam*I)^-1 X'y on centred, scaled columns.
    """

    def __init__(self, cols):
        self.cols = cols
        self.mu = self.sd = self.beta = None
        self.y0 = 0.0

    def fit(self, rows, lam):
        X = [[r["f"][c] for c in self.cols] for r in rows]
        y = [r["R"] for r in rows]
        d = len(self.cols)
        self.mu = [statistics.mean(col) for col in zip(*X)]
        self.sd = [statistics.pstdev(col) or 1.0 for col in zip(*X)]
        Z = [[(v - m) / s for v, m, s in zip(x, self.mu, self.sd)] for x in X]
        self.y0 = statistics.mean(y)
        yc = [v - self.y0 for v in y]

        A = [[sum(Z[i][a] * Z[i][b] for i in range(len(Z))) + (lam if a == b else 0.0)
              for b in range(d)] for a in range(d)]
        rhs = [sum(Z[i][a] * yc[i] for i in range(len(Z))) for a in range(d)]
        self.beta = solve(A, rhs) or [0.0] * d
        return self

    def predict(self, r):
        z = [(r["f"][c] - m) / s for c, m, s in zip(self.cols, self.mu, self.sd)]
        return self.y0 + sum(b * v for b, v in zip(self.beta, z))


# ----------------------------------------------------------------- baselines
def shipped_admits(r):
    """The agent as committed, to the extent these recorded trades can model it.

    strategy.candidates() sells only the side the trend moves away from, and
    offers iron condors only in a RANGE regime below config.MAX_VOL_FOR_CONDOR.
    `zdir` is regime.trend_score()'s own output, so the slow-SMA agreement gate
    is included rather than re-derived from the z-score.

    What this canNOT model, because the recorded trades carry no per-entry
    implied volatility or Greeks: the VRP filter, the EV>=2% gate, and delta-based
    strike selection. So "shipped" here means the DIRECTIONAL filters only, and a
    result about it is a result about those, not about the whole agent.
    """
    _, side = STRATS[r["strategy"]]
    zdir = r["zdir"]
    if side == "IC":
        return zdir == 0 and r["rv"] <= config.MAX_VOL_FOR_CONDOR
    if zdir > 0 and side == "C":
        return False
    if zdir < 0 and side == "P":
        return False
    return True


def select(rows, model, thr):
    if thr is None:
        return list(rows)
    return [r for r in rows if model.predict(r) >= thr]


def fit_and_pick(train_rows, cols, windows):
    """Choose (lambda, threshold) by inner leave-one-window-out on the TRAINING folds.

    The test fold is not involved in any way — this is what makes the outer number
    an out-of-sample number rather than a restatement of the fit.
    """
    best, best_score = None, -1e9
    for lam in LAMBDAS:
        # inner fold models, one per held-out training window
        inner = []
        for w in windows:
            tr = [r for r in train_rows if r["window"] != w]
            te = [r for r in train_rows if r["window"] == w]
            if len(tr) < 30 or not te:
                continue
            inner.append((Ridge(cols).fit(tr, lam), te))
        if not inner:
            continue
        for thr in THRESHOLDS:
            scores = []
            for m, te in inner:
                kept = select(te, m, thr)
                if len(kept) < MIN_ADMITTED:
                    scores = None
                    break
                scores.append(statistics.mean([r["R"] for r in kept]))
            if not scores:
                continue
            s = statistics.mean(scores)
            if s > best_score:
                best_score, best = s, (lam, thr)
    if best is None:
        best = (LAMBDAS[len(LAMBDAS) // 2], None)
    return best


# ------------------------------------------------------------------ one-feature rules
def rule_search(rows, cols, windows, shipped_tot, naive_tot):
    """Leave-one-window-out over SINGLE-feature cut rules.

    277 trades from 19 entry dates cannot support a 14-parameter model — the fold
    table above is what that looks like. A one-parameter rule can be supported, so
    this asks the same question with the smallest hypothesis that still counts as
    learning: pick one feature, pick one cut on the training windows, measure on
    the held-out one.

    The cut is chosen on training folds only, and a rule must keep at least a
    quarter of the training trades — a "rule" that admits six trades is a story
    about six trades.
    """
    print(f"\n{'='*94}")
    print("  ONE-FEATURE CUT RULES — cut fitted on three windows, measured on the fourth")
    print(f"{'='*94}")
    print(f"  {'rule':36} {'n':>4} {'win%':>5} {'net $':>9} "
          f"{'    PF':>6} {'R':>8} {'>naive':>7} {'>ship':>6}")
    print(f"  {'-'*90}")

    n_total = len(rows)
    out, tested = [], 0
    for c in cols:
        for side in ("high", "low"):
            keep = (lambda r, t: r["f"][c] >= t) if side == "high" else (
                    lambda r, t: r["f"][c] <= t)
            per_fold, cuts, beat_s, beat_n = [], [], 0, 0
            for test in windows:
                train = [r for r in rows if r["window"] != test]
                held = [r for r in rows if r["window"] == test]
                vals = sorted(r["f"][c] for r in train)
                grid = sorted({vals[int(len(vals) * q / 12)] for q in range(1, 12)})
                best, bs = None, -1e9
                for t in grid:
                    kept = [r for r in train if keep(r, t)]
                    if len(kept) < 0.25 * len(train):
                        continue
                    m = statistics.mean([r["R"] for r in kept])
                    if m > bs:
                        bs, best = m, t
                if best is None:
                    per_fold = None
                    break
                kept = [r for r in held if keep(r, best)]
                if len(kept) < MIN_ADMITTED:
                    per_fold = None
                    break
                per_fold.append(kept)
                cuts.append(best)
                st_ = stat(kept)
                sh = stat([r for r in held if shipped_admits(r)])
                nv = stat(held)
                beat_s += bool(sh and st_["R"] > sh["R"])
                beat_n += bool(nv and st_["R"] > nv["R"])
            if not per_fold:
                continue
            pooled = stat([r for f in per_fold for r in f])
            tested += 1
            # A "rule" that admits every trade is not a rule, it is the naive run
            # wearing a label. Count it as tested, then drop it.
            if pooled["n"] >= n_total:
                continue
            out.append({"feature": c, "side": side, "cuts": cuts, "pooled": pooled,
                        "beat_shipped": beat_s, "beat_naive": beat_n})

    nf = len(windows)
    for r in sorted(out, key=lambda x: -x["pooled"]["R"]):
        st_ = r["pooled"]
        pf = f"{st_['pf']:>6.2f}" if st_["pf"] is not None else "     —"
        label = f"keep {r['feature']} {'>=' if r['side'] == 'high' else '<='} "
        label += "/".join(f"{c:g}" for c in r["cuts"])
        survives = (r["beat_naive"] >= 3 and r["beat_shipped"] >= 3
                    and st_["net"] > naive_tot)
        print(f"  {label[:36]:36} {st_['n']:>4} {st_['win']*100:>4.0f}% "
              f"{st_['net']:>+9.0f} {pf} {st_['R']:>+8.3f} "
              f"{r['beat_naive']:>5}/{nf} {r['beat_shipped']:>4}/{nf}"
              f"{'  <- survives' if survives else ''}")

    print(f"  {'-'*90}")
    print(f"  {'naive — no rule at all':36} {n_total:>4} {'':>5} {naive_tot:>+9.0f}")
    print(f"  {'shipped — trend-z + vol ceiling':36} {'':>4} {'':>5} {shipped_tot:>+9.0f}")
    print(f"\n  'cuts' lists the threshold each fold independently chose. Cuts that jump")
    print("  around are the fit chasing the training windows, not a level in the market.")
    print(f"  {tested - len(out)} of {tested} candidate rules admitted every trade and were dropped.")
    print(f"  {len(out)} rules were searched over {nf} folds. Beating naive in 3 of 4 by")
    print("  a modest margin is roughly what the best of that many coin flips looks like,")
    print("  so treat a single survivor as a hypothesis to test, not a result to ship.")
    return out


# ---------------------------------------------------------------------- main
def profile(rows, cols):
    """Descriptive: how did trades do inside each half of each feature's range?

    This is IN-SAMPLE and pooled across all four windows. It is here to show what
    the model is looking at, not as evidence of anything — the fold table below is
    the evidence.
    """
    print(f"\n{'='*94}")
    print("  FEATURE PROFILE — pooled, in-sample, descriptive only")
    print(f"{'='*94}")
    print(f"  {'feature':20} {'split':>9} {'low n':>6} {'low R':>8} "
          f"{'high n':>7} {'high R':>8}  {'spread':>8}")
    print(f"  {'-'*90}")
    ranked = []
    for c in cols:
        vals = sorted(r["f"][c] for r in rows)
        med = vals[len(vals) // 2]
        lo = [r for r in rows if r["f"][c] <= med]
        hi = [r for r in rows if r["f"][c] > med]
        if len(lo) < 15 or len(hi) < 15:
            continue
        rl = statistics.mean([r["R"] for r in lo])
        rh = statistics.mean([r["R"] for r in hi])
        ranked.append((abs(rh - rl), c, med, len(lo), rl, len(hi), rh))
    for gap, c, med, nl, rl, nh, rh in sorted(ranked, reverse=True):
        print(f"  {c:20} {med:>9.3f} {nl:>6} {rl:>+8.3f} {nh:>7} {rh:>+8.3f}  "
              f"{rh-rl:>+8.3f}")
    print(f"\n  R = pnl / max loss. 'spread' is the gap between the two halves —")
    print(f"  a large gap means the feature separates outcomes, in this sample.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--features", choices=("all", "structure", "trend"), default="all")
    ap.add_argument("--mode", choices=("model", "rules", "both"), default="both")
    ap.add_argument("--refresh", action="store_true", help="rebuild dataset from the API")
    ap.add_argument("--out", default="docs/structure_model.json")
    a = ap.parse_args()

    cols = {"all": STRUCTURE_FEATURES + TREND_FEATURES,
            "structure": STRUCTURE_FEATURES,
            "trend": TREND_FEATURES}[a.features]

    print("\nbuilding dataset (no lookahead: bars up to and including each entry)...")
    rows = build_dataset(refresh=a.refresh)
    if len(rows) < 60:
        sys.exit("not enough labelled trades to fit anything")
    windows = [w for w, _ in WINDOWS if any(r["window"] == w for r in rows)]
    print(f"\n  {len(rows)} trades · {len(windows)} windows · {len(cols)} features "
          f"[{a.features}]")

    profile(rows, cols)

    naive_tot = sum(stat([r for r in rows if r["window"] == w])["net"] for w in windows)
    shipped_tot = sum((stat([r for r in rows if r["window"] == w and shipped_admits(r)])
                       or {"net": 0.0})["net"] for w in windows)

    folds, stability = [], []
    if a.mode in ("model", "both"):
        folds, stability = run_model(rows, cols, windows)

    rules = []
    if a.mode in ("rules", "both"):
        rules = rule_search(rows, cols, windows, shipped_tot, naive_tot)

    (ROOT / a.out).write_text(json.dumps(
        {"features": cols, "feature_set": a.features, "n_trades": len(rows),
         "lambdas": LAMBDAS, "naive_total": naive_tot, "shipped_total": shipped_tot,
         "folds": folds,
         "rules": [{k: v for k, v in r.items()} for r in rules]}, indent=2))
    print(f"\n  wrote {a.out}\n")


def run_model(rows, cols, windows):
    print(f"\n{'='*94}")
    print("  LEAVE-ONE-WINDOW-OUT — the model never sees the window it is scored on")
    print(f"{'='*94}")
    print(f"  {'window / rule':30} {'n':>4} {'win%':>5} {'net $':>9} {'    PF':>6} "
          f"{'per trade':>9} {'R':>8}")
    print(f"  {'-'*90}")

    folds = []
    for test in windows:
        train = [r for r in rows if r["window"] != test]
        held = [r for r in rows if r["window"] == test]
        lam, thr = fit_and_pick(train, cols, [w for w in windows if w != test])
        model = Ridge(cols).fit(train, lam)

        naive = stat(held)
        ship = stat([r for r in held if shipped_admits(r)])
        learn = stat(select(held, model, thr))

        print(f"  {test:30}")
        row("    naive (everything)", naive)
        row("    shipped (trend-z + ceiling)", ship)
        row(f"    learned (lam={lam:g} thr={thr})", learn)
        print(f"  {'-'*90}")
        folds.append({"window": test, "lam": lam, "thr": thr,
                      "naive": naive, "shipped": ship, "learned": learn,
                      "coef": dict(zip(cols, [round(b, 4) for b in model.beta]))})

    # ---- what the model learned, and whether it learned the same thing 4 times
    print(f"\n{'='*94}")
    print("  COEFFICIENTS — standardised, one column per fold. Signs that flip")
    print("  across folds are noise being fitted, not structure being found.")
    print(f"{'='*94}")
    print(f"  {'feature':20} " + " ".join(f"{f['window'][:11]:>12}" for f in folds)
          + f" {'mean':>9} {'stable':>7}")
    print(f"  {'-'*90}")
    stability = []
    for c in cols:
        vals = [f["coef"][c] for f in folds]
        m = statistics.mean(vals)
        same = all(v > 0 for v in vals) or all(v < 0 for v in vals)
        stability.append((abs(m) if same else 0.0, c, m, same))
        print(f"  {c:20} " + " ".join(f"{v:>+12.4f}" for v in vals)
              + f" {m:>+9.4f} {'  yes' if same else '   NO':>7}")

    # ---- verdict
    print(f"\n{'='*94}")
    print("  VERDICT — did the learned structure model beat the shipped filter?")
    print(f"{'='*94}")
    wins = 0
    scored = [f for f in folds if f["shipped"] and f["learned"]]
    for f in scored:
        d_net = f["learned"]["net"] - f["shipped"]["net"]
        d_R = f["learned"]["R"] - f["shipped"]["R"]
        better = d_R > 0
        wins += better
        print(f"  {f['window']:16} net {d_net:>+8.0f}   R/trade {d_R:>+7.3f}   "
              f"{'learned wins' if better else 'shipped wins or ties'}")
    print(f"\n  learned beat shipped in {wins} of {len(scored)} windows")
    if scored:
        tn = sum(f["naive"]["net"] for f in scored)
        ts = sum(f["shipped"]["net"] for f in scored)
        tl = sum(f["learned"]["net"] for f in scored)
        print(f"  totals — naive {tn:+.0f} · shipped {ts:+.0f} · learned {tl:+.0f}")
    stable = [c for _, c, _, s in sorted(stability, reverse=True) if s]
    print(f"\n  features with a consistent sign across all {len(folds)} folds: "
          f"{', '.join(stable) if stable else 'NONE'}")
    print("  Sign stability is a weak test here: with four windows, any two training")
    print("  sets share two thirds of their trades, so the folds are not independent.")
    return folds, stability


if __name__ == "__main__":
    main()
