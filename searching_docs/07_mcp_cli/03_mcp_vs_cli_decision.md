# 03 — MCP vs CLI: which to use where (and why you should use both)

## 1. Alpaca's own comparison table (verbatim, from `alpacas-cli.md`)

| Aspect | CLI | MCP Server |
|---|---|---|
| **Invocation** | One command per call, then exits | Background process for an entire session |
| **Context cost** | Minimal, just the command string | **Full tool schemas in the context window** |
| **Output** | Pipes into scripts, files, other tools | Returns through MCP to the AI model |
| **AI host needed** | No, works in any terminal | **Yes**, requires an MCP client |
| **Best for** | **Scripts, cron, CI, focused agent actions** | **Long-lived AI sessions, multi-tool orchestration** |

And from the hackathon event page, Alpaca describing the CLI:
> "Built for **long-running agent sessions, cron jobs and CI, where MCP is heavier than needed.**"

## 2. The hackathon requirement

> "**MCP or CLI** — projects must utilize either Alpaca's MCP server or its CLI tools."

One is sufficient. But **Technology Implementation** is scored on:
> "How effectively the project uses Alpaca's Trading API, **MCP server, CLI**, and other required technologies…"

It names all three. **Use both.** It costs maybe 3 hours and it's a direct scoring lever.

## 3. 🔴 The recommended split — assign each a real job

Don't bolt one on for the checkbox. Give each a job it's genuinely better at:

```
┌──────────────────────────────────────────────────────────────────────┐
│  MCP SERVER  →  the RESEARCH / SUPERVISION surface                   │
│                                                                       │
│  • Interactive analyst sessions: "what's the IV rank across my        │
│    universe today?", "show me the SPY chain for Sep 4"               │
│  • The agent's own doc lookup at runtime:                            │
│      search_alpaca_api_specs / get_alpaca_endpoint_docs               │
│    → the agent debugs its own API errors                              │
│  • Human supervision & override: a mentor/judge can talk to the       │
│    account in natural language during your demo                       │
│  • Strategy exploration during Days 1-3                               │
│  • ALPACA_TOOLSETS scoped to exactly what's needed (a security        │
│    control you can point at)                                          │
├──────────────────────────────────────────────────────────────────────┤
│  ALPACA CLI  →  the AUTONOMOUS EXECUTION surface                     │
│                                                                       │
│  • The cron loop that runs unattended every 5 minutes                │
│  • State snapshot: account / positions / orders / activities → JSON   │
│  • Order submission with --client-order-id idempotency                │
│  • --dry-run previews written to the audit log before every submit   │
│  • Multi-leg orders via `alpaca api POST /v2/orders`                  │
│  • Nightly equity-curve archival (alpaca account portfolio)          │
│  • Zero context cost → the loop can run forever, no LLM host needed  │
└──────────────────────────────────────────────────────────────────────┘
```

### Why this specific split is the *right* answer for the judges
1. It matches Alpaca's own stated design intent word for word.
2. It solves a real problem: an unattended 7-day agent shouldn't need an MCP host alive 24/7.
3. It makes "autonomous" demonstrable — the cron loop trades while nobody is watching.
4. It makes "supervisable" demonstrable — MCP lets a human inspect and intervene.
5. It gives the demo video two distinct, visually different moments: a terminal cron tick placing an mleg order, and a natural-language MCP conversation about the same account.

## 4. Where the LLM actually lives

A common failure: teams put the LLM in the execution path via MCP, and the agent becomes slow, non-deterministic and unauditable.

**Better topology:**
```
        ┌──────────────── LLM (reasoning) ────────────────┐
        │  news + chain + regime → STRUCTURED PROPOSAL     │
        │  (JSON matching a fixed schema)                  │
        └───────────────────────┬──────────────────────────┘
                                │
                    ┌───────────▼───────────┐
                    │  DETERMINISTIC GATES   │  ← plain Python, unit-tested,
                    │  (no model in the loop)│     NO LLM
                    └───────────┬───────────┘
                                │
                    ┌───────────▼───────────┐
                    │  ALPACA CLI execution  │  ← idempotent, logged
                    └────────────────────────┘

        MCP SERVER ──► sits BESIDE this, for research & human oversight,
                       and for the agent's own API-doc lookups.
```

This is precisely the architecture Alpaca's own reference article advocates:
> "Risk checks run as deterministic code, unit-tested, **with no model in the loop**."
> "The agent that generated the idea does not get to validate it."

## 5. What to show in the repo (evidence for the judges)

```
repo/
├── .mcp.json                     ← MCP server config (keys redacted, toolsets scoped)
├── docs/mcp_session_transcript.md ← a real MCP conversation, showing tools called
├── scripts/agent_cycle.sh         ← the CLI cron loop
├── crontab.example                ← the schedule
├── logs/agent-2026-08-31.jsonl    ← audit log, one JSON line per decision
├── intents/done/*.json            ← every mleg payload the agent submitted
└── docs/mleg_sign_convention.md   ← your DEV-account experiment on debit/credit sign
```

Then in the write-up's "Alpaca Infrastructure Implementation" section, one paragraph each on MCP and CLI, naming the specific tools/commands and *why* each surface got that job.

## 6. Quick setup for both (30 minutes)

```bash
# ---- CLI ----
brew install alpacahq/tap/cli
alpaca profile login            # OAuth, paper, DEV account
alpaca doctor
alpaca completion fish > ~/.config/fish/completions/alpaca.fish

# ---- MCP (Claude Code) ----
claude mcp add alpaca --scope user --transport stdio uvx alpaca-mcp-server \
  --env ALPACA_API_KEY="$ALPACA_API_KEY" \
  --env ALPACA_SECRET_KEY="$ALPACA_SECRET_KEY" \
  --env ALPACA_TOOLSETS="account,trading,assets,options-data,stock-data,news,corporate-actions"
# verify in Claude Code:
/mcp

# ---- Skills ----
npx skills add alpacahq/alpaca-skills --skill alpaca-trading-paper-trading-cli
npx skills add alpacahq/alpaca-skills --skill alpaca-trading-paper-trading-mcp
npx skills add alpacahq/alpaca-skills --skill alpaca-trading-backtest

# ---- SDK ----
pip install alpaca-py

# ---- smoke test all four surfaces ----
alpaca clock                                              # CLI
alpaca data option chain --underlying-symbol SPY | head    # CLI + options data
python -c "from alpaca.trading.client import TradingClient; print('sdk ok')"
# in Claude Code, ask: "What's my Alpaca account equity and options trading level?"  # MCP
```

## 7. Sanity checks before you commit to the architecture

| Check | Command | Why |
|---|---|---|
| Does the CLI support mleg natively in your build? | `alpaca order submit --help \| grep -i leg` | Determines whether you use the flag or `alpaca api POST` |
| Does `alpaca api POST /v2/orders` accept stdin JSON? | `echo '{}' \| alpaca api POST /v2/orders` (expect a validation error, not a usage error) | Confirms the escape hatch works |
| Which MCP tools are actually exposed with your toolsets? | `/mcp` in Claude Code | Confirms `place_option_order` + `get_option_chain` are present |
| Does the MCP server see the right account? | ask it "what's my account ID?" | Catches DEV/COMP key mix-ups |
| Is the CLI on paper? | `alpaca account get --jq '.id'` vs the dashboard | Catches accidental live config |

Do all five on Day 1. Each one is a bug you'd otherwise find on Day 5.
