# Submission — for Nizar

**Deadline: Fri 4 Sep, 11:00 ET / 18:00 GMT+3.** Everything below is ready except the video.

---

## 1. Paste these into the form

| Field | Value |
|---|---|
| **Alpaca account ID** | `PA3BAT1OOEFE` |
| **Repo** | https://github.com/nizarhazaymeh/tradingbot |
| **Demo URL** | https://nizarhazaymeh.github.io/tradingbot/ |

⚠️ The account ID is the one field that cannot be missed — **without it the P&L is not scored at all.**

---

## 2. Files to upload

| What | Where |
|---|---|
| Slides | `submission/slides.pdf` |
| Cover image | `submission/cover.png` (1920×1080) |
| Write-up | `docs/WRITEUP.md` |
| Video | **not recorded yet** — see §4 |

---

## 3. Description text

Both are already written and within the limits — copy them straight from
[`docs/SUBMISSION_COPY.md`](docs/SUBMISSION_COPY.md):

- **Short** (235 chars) — the "Use this one" block
- **Long** (276 words) — the block under *Long description*
- **Tags** — the list at the bottom of that file

---

## 4. Video — the only thing left to make

MP4, **3:00–5:00** (under 3 or over 5 loses points). Shot list with exact commands:
[`docs/VIDEO_SCRIPT.md`](docs/VIDEO_SCRIPT.md) — every command in it is verified to run.

Lead with the finding, not the features:

> "We measured 60 real spreads at the market's own prices. **Zero were profitable.**
> So the edge had to come from somewhere else — we price with implied volatility
> and score probability with realised volatility, and trade only the gap."

---

## 5. The results, stated honestly

| | |
|---|---|
| Final equity | **$99,798.61** (−0.20%) |
| Max drawdown | −0.24% |
| Closed trades | 14 — 9 winners (64%) |
| Open at judging | **0** — book was flat before the deadline |

**Don't hide the loss, and don't spin it.** It came from two trades:

- 12 trades that followed the rules: **+$433**
- 2 IWM spreads that slipped through a gap in the holding-period gate: **−$628**

Those two bought 6 days of option when the deadline only allowed holding 1. The
stop loss capped both at −60% before the flatten was needed. The gate that now
rejects them is in the repo, with tests. That story — bug, cost, fix, test — is
the strongest thing we have; it reads better than a spun number.

---

## 6. Two things to be accurate about if asked

- **The CLI does not execute orders.** All 14 trades went over the REST API. The
  docs used to claim otherwise and were corrected. The CLI's real contribution:
  inspecting it is how we found it defaults to the OPRA feed, which returns 403
  on a free account — that fixed every options call the agent makes.
- **The MCP server is the surface genuinely wired in**, with a reproducible
  session in `docs/mcp_session_transcript.md`. That satisfies the "MCP **or** CLI"
  requirement.

---

## 7. Do not trade Friday morning

The market opens 09:30 and judging is 11:00. Trading that window means same-day-expiry
options — the highest-variance instrument there is — needing ~$200 to break even and
just as likely to lose $1,000. The agent's own gates reject those trades, so it would
mean overriding the strategy in the logs judges read.

Take the −0.20% with the clean story.
