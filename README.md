# Options Alpha Agent

> An autonomous options-trading agent that only trades when the premium is
> actually worth the risk — and can prove it.

**Alpaca AI Trading Agents Hackathon** · lablab.ai × Alpaca · 28 Aug – 4 Sep 2026

| | |
|---|---|
| 📊 Alpaca paper account | `PA3BAT1OOEFE` (fresh, $100,000 start) |
| 🧠 LLM | Featherless AI · `zai-org/GLM-5.2` |
| ⌨️ Execution | REST `POST /v2/orders` (unattended loop) |
| 🔌 Research & oversight | Alpaca MCP Server |
| 📈 Instrument | US index options — multi-leg (`mleg`) spreads only |

---

## The idea

Most trading agents ask *"which way will the market go?"* — a question nobody
answers reliably. This agent asks a different one:

> **"Is this specific options structure priced better than the risk it carries?"**

That question has a measurable answer, and answering it correctly is what
separates a strategy from a gamble.

### What we found when we measured it

We enumerated 60 real SPY / QQQ / IWM spreads and computed expected value using
delta-implied probabilities.

```
positive-EV structures found: 0 / 60
```

**Zero.** That is not a bug — it is what an efficient market looks like. Under
the market's own implied volatility, every vanilla spread prices at fair value
minus the bid-ask you cross to get in.

So the agent had to find a real edge, not a fabricated one.

### The edge: variance risk premium

Implied volatility persistently exceeds subsequently *realised* volatility —
option sellers are paid for bearing variance risk. That gap is measurable in
real time:

| | implied | realised | premium | verdict |
|---|---|---|---|---|
| SPY | 11.6% | 10.1% | **+1.5%** | sell premium |
| QQQ | 17.2% | 17.7% | **−0.5%** | **stand aside** |
| IWM | 17.2% | 14.2% | **+3.0%** | best opportunity |

So the agent **prices with implied volatility** (that is the premium it
receives) but **computes probabilities with realised volatility** (that is how
the underlying actually behaves). The gap between them *is* the edge, and it
shows up honestly in the expected value.

Re-running the same structures under that model:

```
positive-EV (>=2% of risk): 5 / 12
```

QQQ — where implied sits *below* realised — correctly yields nothing. The agent
refuses to trade it. **An agent that knows when to stand aside is the point.**

---

## How it decides

```
every 5 minutes
  │
  ├─ 1. market open?                      Alpaca /v2/clock — else stop
  ├─ 2. reconcile                         broker is truth; find ghosts & orphans
  ├─ 3. manage open positions             ← options have NO brackets, so this
  │                                          loop IS the stop-loss
  ├─ 4. classify regime         [no LLM]  IV vs realised vol, trend z-score
  ├─ 5. form a view             [ LLM  ]  direction · magnitude · confidence
  │                                          never picks strikes or sizes
  ├─ 6. enumerate candidates    [no LLM]  ~37 structures across deltas & widths
  ├─ 7. score expected value    [no LLM]  N(d₂) probabilities under realised vol,
  │                                          tilted by the view's conviction
  ├─ 8. risk gates              [no LLM]  22 deterministic, unit-tested checks
  └─ 9. execute                           4-leg mleg via REST, idempotent client_order_id
```

**The LLM has exactly one job**: state a directional view with a confidence.
That view shifts the market-implied probabilities — and the agent only trades
when the shift is large enough to overcome transaction costs. Everything that
touches money is deterministic, tested Python.

That split is deliberate. Model output is non-deterministic and hard to audit;
risk decisions must be neither.

---

## Risk

Every position is **defined-risk**. The account cannot blow up.

| Layer | Limit |
|---|---|
| Per trade | 0.55% of equity (~$550 max loss) |
| Portfolio heat | 4.0% total risk deployed |
| Per underlying / per expiry | 1.2% / 2.5% |
| Concurrent positions | 10 |
| Portfolio delta | ±3.0 per $100k |
| Daily drawdown | −2% → halt |
| Total drawdown | −6% → halt |

A halt cancels every working order, flattens the book, and sets
`suspend_trade` on the Alpaca account itself — a server-side kill switch that
survives this process dying.

**Expiry is non-negotiable.** Alpaca auto-exercises ITM options, which would
convert a $400 spread into six-figure equity exposure. The agent force-closes
on expiry day: limit orders from 14:00 ET, market orders from 15:30 ET.

---

## What we verified against the live API

Findings that contradict or sharpen the public documentation — all tested on a
paper account, details in [`docs/FINDINGS.md`](docs/FINDINGS.md):

1. **`mleg` sign convention settled empirically.** Alpaca's docs say positive =
   debit / negative = credit, but their own iron-condor *example* shows the
   opposite. We submitted both and confirmed: **negative = credit.**
2. **Coverage rule corrected.** Our first validator required the protective long
   to be further OTM — which wrongly rejects every debit spread. The real rule is
   per `(root, expiry, type)`: total long quantity ≥ total short quantity.
3. **OPRA returns 403** ("OPRA agreement is not signed"). The Alpaca CLI defaults
   to `--feed opra`, so every options call must pass `--feed indicative`.
4. **Percentage-only spread filters reject cheap wings.** A 50% spread on a $0.04
   option is two cents. Accepting either a % *or* an absolute limit expanded the
   usable SPY call range from strike 785 to 815 — which is what makes iron
   condors constructible at all.
5. **Delta ≠ P(ITM).** Delta is N(d₁); the probability of finishing in the money
   is N(d₂). Delta overstates for calls and understates for puts. We compute d₂.

---

## Quickstart

```bash
git clone <repo> && cd <repo>
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
brew install alpacahq/tap/cli

cp .env.example .env        # add your Alpaca paper keys + Featherless key

pytest -q                   # 205 tests — the risk gates are the product
python run.py status        # account, options level, book
python run.py once          # one full cycle, dry run (no orders)
python run.py once --live   # actually trade
python run.py loop --live   # unattended
```

`--rehearse` pretends the market is open so the full pipeline can be exercised
outside session hours. It is hard-blocked from combining with `--live`.

---

## Layout

| Module | Role |
|---|---|
| `agent/client.py` | Alpaca REST — options-aware, header-driven rate limiting, ambiguous-failure recovery |
| `agent/options.py` | OCC symbology, defensive contract parsing, strike selection |
| `agent/spreads.py` | `mleg` construction + validator enforcing all 5 Alpaca rules |
| `agent/expectancy.py` | N(d₂) probabilities, variance-risk-premium EV model |
| `agent/regime.py` | Deterministic volatility/trend classification |
| `agent/strategy.py` | Candidate enumeration + EV optimisation |
| `agent/risk.py` | 22 gates, sizing, circuit breakers |
| `agent/brain.py` | Featherless LLM — view + critic, JSON-only, always falls back safely |
| `agent/monitor.py` | Exits: profit target, stop, delta breach → roll, time stop, expiry |
| `agent/executor.py` | Idempotent submission, price ladder, kill switch |
| `agent/state.py` | SQLite: intents, decision audit log, IV history, equity curve |
| `agent/cycle.py` | The loop |

Reused from [`nizarhazaymeh/tradingbot`](https://github.com/nizarhazaymeh/tradingbot)
(same team, MIT-relicensed): `indicators.py`, `levels.py`, `tradelog.py`,
`notifier.py`, and the HTTP retry/idempotency patterns in `client.py`.

---

## Disclosure

Paper trading is a simulation. It does not model market impact, latency
slippage, order-queue position, price improvement, regulatory fees, or
dividends. Options quotes on the free plan come from Alpaca's **indicative**
feed, not OPRA, and option trades are delayed 15 minutes — the agent therefore
times entries off the underlying and its edge does not depend on quote
precision. Greeks are Black-Scholes derived while Alpaca's contracts are
American-style, so Greeks are approximations. A handful of trading days is not a
statistically significant sample.

This is not investment advice. Options involve significant risk and are not
suitable for all investors. See
[Characteristics and Risks of Standardized Options](https://www.theocc.com/company-information/documents-and-archives/options-disclosure-document)
and [Alpaca's disclosures](https://alpaca.markets/disclosures).

MIT licensed.
