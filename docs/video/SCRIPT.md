# Demo video — full script

**Options Alpha Agent · Alpaca AI Trading Agents Hackathon**
Runtime **3:31** · 1920×1080 · matches `submission/demo_video.mp4` shot-for-shot.

This is the word-for-word script for the cut that is already built (3:31). Read it into a
mic against the video with the sound muted and you will land on every frame — the
timings below are the real segment boundaries of the file. The current video uses
a macOS `say` voice as a placeholder; this script is what to replace it with.

**Delivery.** Calm, unhurried, a measured analyst — not an ad. ~165 words a
minute. Let the pauses sit; the on-screen numbers do half the work. Bold marks a
word to lean on. `(beat)` is a deliberate one-second pause.

**Total narration: 11 segments, ~2:55 of speech inside a 3:11 runtime.** The
title card and the tail are silent by design.

---

## [0:00–0:04] · TITLE — silent

*On screen: title card, "Options Alpha Agent".*

Hold. No voice. Let it breathe for four seconds, then the first slide comes up as
you start speaking.

---

## [0:04–0:18] · THE QUESTION

*On screen: slide — "Predicting direction is the wrong question".*

> Most trading agents ask which way the market will move. Nobody answers that
> reliably. **(beat)** Ours asks a question that has an answer: is the market
> paying **enough** for this specific risk?

---

## [0:18–0:32] · THE MEASUREMENT

*On screen: slide — "Zero of 60 spreads were positive-EV".*

> We measured before we built. Sixty real spreads, priced with the market's own
> implied volatility. **Zero** were positive expected value. **(beat)** That's
> not a bug — that's an efficient market.

---

## [0:32–0:45] · THE EDGE

*On screen: slide — "Price with implied vol. Score probability with realised vol."*

> So the edge had to be real: the **variance risk premium**. We price with
> implied vol, we score probability with realised vol, and we trade only the gap
> between them.

---

## [0:45–1:08] · THE CYCLE BEGINS

*On screen: terminal — cycle 68 header, reconcile, the seven open positions.*

> Here is one real cycle from the live session — cycle sixty-eight, on a paper
> account, dry-run false. **(beat)** First it reconciles against the broker: the
> broker is the truth, not our database. Then it marks every open position and
> runs the exit logic. Options have no bracket orders — so **this loop is the
> stop-loss.**

---

## [1:08–1:36] · SPY: RICH, AND REFUSED

*On screen: terminal reveals the SPY block, ending on the red `REJECT` line.*

> SPY. Implied vol thirteen percent, realised under seven — nearly twice the
> volatility it's delivering. Rich. **(beat)** But notice — the model was
> unavailable this cycle. The view defaults to neutral, and the agent carries on.
> The model only ever offers an **opinion**; code decides. **(beat)** And then —
> **rejected.** The best structure risks a hundred and fifty-one dollars; the
> budget has sixty-six. The risk gate said no.

---

## [1:36–1:57] · QQQ: SUBMIT

*On screen: terminal reveals the QQQ block, ending on the green `SUBMIT` line.*

> QQQ. Implied nineteen against realised thirteen, trend down. It scores two
> hundred thirty-nine candidates by expected value, and takes the best one that
> **also** clears every gate. **(beat)** Submit — a bear call spread,
> twenty-seven cents credit, a single multi-leg order over Alpaca's REST API.

---

## [1:57–2:16] · IWM AND IBIT: STAND ASIDE

*On screen: terminal reveals IWM (refused) and IBIT (stand aside), then
`cycle 68 done`.*

> IWM — also rich, but refused: the per-expiry budget is nearly spent. **(beat)**
> And IBIT: implied thirty-nine, realised thirty-eight. One-point-oh-two times.
> No premium to sell — so it stands aside. **(beat)** **Standing aside is the
> product.**

---

## [2:16–2:25] · THE FILL

*On screen: terminal — Alpaca's own order record for the QQQ order.*

> That's our log. **This is Alpaca's.** The same order, filled eleven minutes
> later, at exactly the limit. **(beat)** It fills.

---

## [2:25–2:43] · THE FINDING

*On screen: slide — "The model approved trades that lost money by design".*

> We also backtested the agent against **itself** — two years, a hundred and nine
> expiries, net of costs — and found three structure families losing money by
> design. We turned them off. **(beat)** The differentiator isn't the model. It's
> the boundary.

---

## [2:43–2:49] · THE TESTS

*On screen: terminal — the live `pytest` run, "319 passed".*

> Three hundred nineteen tests. The risk gates are the product — and every one of
> them is pinned.

---

## [2:49–3:09] · CLOSE

*On screen: slide — "Where this sits" (competitive analysis).*

> Rules-only bots can't read context. Model-first agents can't be trusted with
> the order ticket. **(beat)** One schema-constrained opinion in; deterministic
> gates before anything is sent. **(beat)** Paper account
> P-A-3-B-A-T-1-O-O-E-F-E. Repo and demo are public. **(beat)** Thank you.

---

## [3:09–3:11] · TAIL — silent

*On screen: title card returns briefly, then out.*

---

## Notes for the reader

- **The account ID is spelled letter by letter on purpose** — a judge writes it
  down. Say it slowly: "P … A … three … B … A … T … one … O … O … E … F … E."
- **Do not rush the two rejects and the stand-aside.** They are the argument. A
  bot that trades looks the same as a bot that gambles; a bot that *refuses*
  three of four is the whole pitch.
- **"a paper account", never "the competition account."** Cycle 68 ran on the
  dev paper account. Same code, same day, both Alpaca paper — but say what's true.
- **Every number you speak is on the screen as you say it.** If you fluff a
  number, stop and match the screen; don't invent one.
- **If a human take runs long**, the built cut has 3–11 seconds of slack over the
  3:00 floor. If it runs short, hold the last slide a moment longer rather than
  speeding up.

## Rebuilding the video with a new voice

Record the eleven segments above as one continuous take (or one file per
segment), then either:

- **one file:** replace the audio under the existing visual track, or
- **per segment:** drop each into `build/video/seg_NN.aiff` and re-run the concat
  in `docs/video/NARRATION.md`.

The visual cut never changes — only the voice. Everything on screen is real
output: `scripts/video_cycle.sh` (the cycle), `scripts/video_fill.sh` (the fill),
`submission/slides.pdf` (the slides), and a live `pytest` run.
