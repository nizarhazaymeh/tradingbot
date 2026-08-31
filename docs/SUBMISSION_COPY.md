# Submission copy — B8

Paste-ready. **Check the numbers against the final results before submitting** —
anything in `{braces}` must be filled in from the last `run.py status` and
`docs/equity_curve.json`.

Required alongside this (see [`TODO.md`](TODO.md)): the account ID in the
submission form (**`PA3BAT1OOEFE`** — B7), the repo URL, the demo URL, the video,
the slides and the cover image.

---

## Short description (≤255 characters)

**Use this one** — 235 characters:

```
An autonomous options agent on Alpaca that asks whether the market is paying
enough for risk, not which way it will move. It prices with implied vol, scores
probability with realised vol, and refuses to trade the gap it isn't paid for.
```

Shorter alternative — 145 characters:

```
An autonomous Alpaca options agent that sells premium only when implied
volatility exceeds realised. 22 risk gates. The LLM opines; code decides.
```

---

## Long description (≥100 words)

**Use this one** — 276 words:

```
Most trading agents ask which way the market will move. That question has no
reliable answer, so ours asks a narrower one that does: is this specific options
structure priced better than the risk it carries?

We measured it before building. We enumerated 60 real SPY/QQQ/IWM spreads and
scored them using the market's own implied volatility. Zero of 60 were
positive-EV — which is not a bug, it is what an efficient market looks like.

So the edge had to come from somewhere real. It comes from the variance risk
premium: implied volatility persistently exceeds subsequently realised
volatility, because option sellers are paid to bear variance risk. The agent
prices with implied vol, the premium it actually receives, but computes
probabilities with realised vol, how the underlying actually behaves. The gap is
the edge, and it shows up honestly in the expected value. Re-scored that way, 5
of 12 structures cleared a 2%-of-risk threshold, and QQQ — whose implied vol sat
below its realised vol — produced nothing. The agent refuses to trade it.

Every position is options-only: iron condors and credit or debit verticals,
submitted as four-leg mleg orders through Alpaca. Both required surfaces are
used — the CLI drives the unattended five-minute loop, and the MCP server is the
research and oversight surface.

The LLM returns exactly one thing: a JSON view of direction, magnitude and
confidence, which tilts the market-implied probabilities. It never picks a
strike, sizes a position or builds an order. That split is also the prompt-
injection defence: the agent reads news, and a fully compromised response can
only produce a wrong opinion that 22 deterministic gates must still accept.
```

---

## Tags

Pick from these, in this order of relevance:

```
options-trading, autonomous-agent, alpaca, algorithmic-trading, risk-management,
expected-value, iron-condor, multi-leg-options, mcp, llm-agent, python,
quantitative-finance, variance-risk-premium, paper-trading
```

If the form caps the count, the first six carry the most signal.

---

## Things NOT to claim

Written down because they are the easy mistakes to make under deadline.

| Don't say | Why |
|---|---|
| A specific return, win rate or Sharpe | Fill from the real account at submission time. `{total_pnl_pct}` / `{win_rate}` |
| "Backtested profitable" without the caveat | `docs/BACKTEST.md` uses daily bars, no intraday path, and picks strikes by % distance rather than delta. Say "logic-tested"; the honest caveats are already written there |
| "Fully autonomous with no human oversight" | True of the loop, but a human starts it and watches the session |
| Anything about live/real-money trading | Paper only, by design — there is no live path in the codebase |
| "The AI decides the trades" | It does not, and the write-up's whole argument is that it must not |
