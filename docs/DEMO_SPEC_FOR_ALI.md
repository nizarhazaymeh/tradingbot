# Demo Website — build spec for Ali

Hi Ali. This is everything you need. **You do not need to understand trading** —
the agent writes plain JSON files, and your job is to display them nicely.

**Deadline: Tuesday 1 Sep, end of day.** Judges must be able to click a link and
immediately understand what our agent does.

---

## 1. Why this matters

lablab's own judging guide says it plainly:

> "Building without deploying — a working local demo that can't be accessed by
> judges **scores as if it doesn't work**."

So: it must be **deployed to a public URL**, and it must **load with no login**.

---

## 2. What to build with

Pick whichever you're fastest in. lablab explicitly accepts these three:

| Option | Best if | Deploy |
|---|---|---|
| **Streamlit** ⭐ recommended | You're OK with Python. Fastest by far — ~100 lines total. | share.streamlit.io, free, connects to GitHub |
| **Next.js / React** | You prefer JS | Vercel, free |
| **Plain HTML + JS** | You want full control | Vercel / Netlify / GitHub Pages |

**My recommendation: Streamlit.** It reads JSON and draws charts in a few lines,
and there is no backend to build.

---

## 3. The data you'll be given

I will produce a single file, `public/dashboard.json`, refreshed automatically.
**You only ever read this one file.** No API keys, no database, no Alpaca access.

```json
{
  "updated_at": "2026-09-02T14:30:05Z",
  "account": {
    "account_id": "PA3BAT1OOEFE",
    "equity": 100842.50,
    "starting_equity": 100000,
    "total_pnl": 842.50,
    "total_pnl_pct": 0.0084,
    "max_drawdown_pct": -0.011,
    "open_positions": 3,
    "closed_trades": 14,
    "win_rate": 0.79
  },
  "equity_curve": [
    {"ts": "2026-08-31T09:30:00Z", "equity": 100000.00},
    {"ts": "2026-08-31T09:45:00Z", "equity": 100015.20}
  ],
  "market": [
    {
      "underlying": "SPY", "spot": 769.28,
      "implied_vol": 0.116, "realized_vol": 0.101, "premium_edge": 0.015,
      "regime": "HIGH_IV_RANGE", "verdict": "trade",
      "reason": "market charges more than the real risk"
    },
    {
      "underlying": "QQQ", "spot": 716.91,
      "implied_vol": 0.172, "realized_vol": 0.177, "premium_edge": -0.005,
      "regime": "LOW_IV_RANGE", "verdict": "stand aside",
      "reason": "market charges LESS than the real risk"
    }
  ],
  "positions": [
    {
      "id": "iron_condor:SPY...", "kind": "iron_condor", "underlying": "SPY",
      "description": "SPY iron condor, expires Sep 4",
      "opened_at": "2026-09-01T14:12:00Z",
      "qty": 2, "credit_received": 134.00,
      "max_loss": 366.00, "unrealized_pnl": 48.20,
      "days_to_expiry": 2, "plain_english": "Profits if SPY stays between $756 and $781"
    }
  ],
  "decisions": [
    {
      "ts": "2026-09-02T14:30:05Z", "underlying": "QQQ",
      "decision": "reject", "gate": "g_expectancy",
      "reason": "expected value +1.26% < required 2%",
      "candidates_considered": 37
    }
  ],
  "funnel": {"considered": 412, "passed_gates": 31, "submitted": 17, "filled": 14},
  "gate_rejections": {
    "g_expectancy": 289, "g_sizing": 41, "g_spread_width": 12, "g_net_delta": 8
  }
}
```

If the file isn't there yet, **hardcode this example** and build against it. I'll
wire the real one in — the shape won't change.

---

## 4. The five panels

### Panel 1 — Headline numbers (top of page)
Four big cards:

```
┌──────────────┬──────────────┬──────────────┬──────────────┐
│   RETURN     │  WIN RATE    │   TRADES     │  MAX DROP    │
│   +0.84%     │     79%      │      14      │    -1.1%     │
│   green/red  │              │   closed     │  always red  │
└──────────────┴──────────────┴──────────────┴──────────────┘
```
Green if return positive, red if negative. Big font. This is the first thing a
judge sees.

### Panel 2 — Equity curve
A line chart of `equity_curve`. X = time, Y = account value.
Horizontal dashed line at **$100,000** (the starting point) so it's obvious
whether we're above or below.

### Panel 3 — 🔴 "Why we trade or skip" (**the most important panel**)
This is our differentiator. Make it look good.

For each row in `market`, show a bar comparing two numbers:

```
SPY   market charges  11.6%  ████████████
      real risk       10.1%  ██████████
      → +1.5% edge — ✅ WORTH TRADING

QQQ   market charges  17.2%  █████████████████
      real risk       17.7%  ██████████████████
      → -0.5% edge — ❌ SKIPPED
```

Add this caption under the panel, word for word:

> Selling options is like selling insurance. It only makes money when the
> premium charged is bigger than the real risk. Our agent measures both and
> **refuses to trade when it isn't being paid enough.**

### Panel 4 — Open positions
A table from `positions`:

| Underlying | Strategy | Expires | Collected | Max Loss | P&L now | What it means |
|---|---|---|---|---|---|---|
| SPY | Iron Condor | Sep 4 | $134 | $366 | **+$48** | Profits if SPY stays $756–$781 |

Use the `plain_english` field for the last column. Colour P&L green/red.

### Panel 5 — Decision log
Last ~20 entries from `decisions`. Show that most are **rejections** — that's the
point, it proves the risk system works.

```
14:30:05  QQQ  ❌ REJECTED  expected value +1.26% < required 2%  (37 candidates checked)
14:25:01  SPY  ✅ TRADED    iron condor, $134 credit, $366 max loss
```

Below it, a small bar chart of `gate_rejections` titled
**"Why trades were rejected"**.

---

## 5. Design

- **Dark theme.** Finance dashboards look right in dark.
- Green `#00C805` for profit, red `#FF3B30` for loss, grey for neutral.
- Monospace font for numbers, normal font for text.
- **Must work on a phone** — a judge may open it on mobile.
- Add a footer: `Alpaca AI Trading Agents Hackathon 2026 · paper trading simulation · not investment advice`
- Show `updated_at` somewhere small, so it's clearly live.

**Don't over-design it.** Clear and readable beats fancy. A judge spends maybe
60 seconds here.

---

## 6. Streamlit starter

```python
import json, streamlit as st, pandas as pd

st.set_page_config(page_title="Options Alpha Agent", layout="wide",
                   initial_sidebar_state="collapsed")

d = json.load(open("public/dashboard.json"))
a = d["account"]

st.title("Options Alpha Agent")
st.caption(f"Alpaca paper account {a['account_id']} · updated {d['updated_at']}")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Return", f"{a['total_pnl_pct']*100:+.2f}%", f"${a['total_pnl']:+,.0f}")
c2.metric("Win rate", f"{a['win_rate']*100:.0f}%")
c3.metric("Trades", a["closed_trades"])
c4.metric("Max drop", f"{a['max_drawdown_pct']*100:.1f}%")

st.subheader("Account value")
eq = pd.DataFrame(d["equity_curve"])
eq["ts"] = pd.to_datetime(eq["ts"])
st.line_chart(eq.set_index("ts")["equity"])

st.subheader("Why we trade — or skip")
st.caption("Selling options is like selling insurance. It only pays when the "
           "premium charged exceeds the real risk. Our agent measures both.")
for m in d["market"]:
    col1, col2 = st.columns([1, 3])
    col1.markdown(f"### {m['underlying']}")
    col2.progress(min(m["implied_vol"]/0.3, 1.0),
                  text=f"market charges {m['implied_vol']*100:.1f}%")
    col2.progress(min(m["realized_vol"]/0.3, 1.0),
                  text=f"real risk      {m['realized_vol']*100:.1f}%")
    verdict = "✅ WORTH TRADING" if m["premium_edge"] > 0.01 else "❌ SKIPPED"
    col2.markdown(f"**{m['premium_edge']*100:+.1f}% edge — {verdict}**")

st.subheader("Open positions")
if d["positions"]:
    st.dataframe(pd.DataFrame(d["positions"])[
        ["underlying","kind","days_to_expiry","credit_received",
         "max_loss","unrealized_pnl","plain_english"]],
        use_container_width=True, hide_index=True)
else:
    st.info("No open positions right now.")

st.subheader("Decision log")
st.caption("Most decisions are rejections — that is the risk system working.")
st.dataframe(pd.DataFrame(d["decisions"]), use_container_width=True, hide_index=True)

st.caption("Alpaca AI Trading Agents Hackathon 2026 · paper trading simulation · "
           "not investment advice")
```

```bash
pip install streamlit pandas
streamlit run dashboard.py
```

**Deploy:** push to the repo → share.streamlit.io → connect GitHub → pick the
file → Deploy. Free, takes about 2 minutes.

---

## 7. Definition of done

- [ ] Deployed to a public URL
- [ ] Opens in an **incognito window** with no login
- [ ] All 5 panels render
- [ ] Doesn't crash when `positions` is empty (market closed = normal)
- [ ] Readable on a phone
- [ ] Disclaimer footer present
- [ ] URL sent to Mahdi

---

## 8. Questions

Ask me (Mahdi) about anything. Two things worth saying up front:

- **You cannot break anything.** The dashboard only reads a file. It has no
  connection to the trading account and cannot place or cancel a trade.
- **You don't need to understand options.** If a panel confuses you, it will
  confuse a judge too — tell me and I'll rewrite the wording.
