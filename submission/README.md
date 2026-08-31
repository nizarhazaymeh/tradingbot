# Submission assets

Generated from HTML so they are diffable and reproducible. Regenerate after any
change rather than editing the outputs by hand.

| File | Deliverable | Spec | Status |
|---|---|---|---|
| `cover.png` | B6 cover image | PNG/JPG, 16:9 | 1920×1080, exactly 16:9 |
| `slides.pdf` | B4 slide deck | PDF, 8–10 pages | 10 pages, 13.333×7.5in (16:9) |
| `cover.html` · `slides.html` | sources | — | edit these, not the outputs |

## Regenerate

```sh
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

# cover — 16:9 PNG
"$CHROME" --headless --disable-gpu --hide-scrollbars --force-device-scale-factor=1 \
  --window-size=1920,1080 --default-background-color=0d1117ff \
  --screenshot=submission/cover.png "file://$PWD/submission/cover.html"

# slides — PDF, page size comes from @page in the CSS
"$CHROME" --headless --disable-gpu --no-pdf-header-footer \
  --print-to-pdf=submission/slides.pdf "file://$PWD/submission/slides.html"
```

`--force-device-scale-factor=1` matters: without it a retina display yields
3840×2160 and the 16:9 check still passes, so the error is easy to miss.

## Deck contents

Ten pages, in order: title · the problem · what we measured · the insight ·
architecture · risk · Alpaca infrastructure · evidence · **competitive
analysis** · **TAM/SAM + revenue model**.

The last two are there deliberately.
`searching_docs/01_hackathon/02_judging_and_scoring.md` notes that Alpaca's
published criteria omit Business Value but the Rule Book judges still score it,
and recommends including them as cheap insurance.

## Before submitting — three things to check

1. **Numbers.** Every figure traces to a repo document: the backtest ladder to
   `docs/BACKTEST.md`, the 0-of-60 and 5-of-12 EV findings to `docs/WRITEUP.md`,
   21/21 to `docs/SAFETY_TESTS.md`, 23 req/cycle to `docs/TODO.md` T7. If a
   number changes, change it here too.

2. **TAM/SAM is a framework, not research.** Slide 10 says so on the slide. The
   ratios are ours and the arithmetic is shown (500k × 1% × $25 × 12 = $1.5M) so
   a judge can disagree precisely rather than be misled. **If you can find a
   citable source for the ~10M and ~500k figures, add it.** Do not present them
   as sourced until then.

3. **The account ID.** `PA3BAT1OOEFE` appears on slide 1. It is the judging gate
   for P&L, so it also needs to be in the submission form itself (B7) — the
   slides alone do not satisfy it.

Still outstanding and not producible here: **B3, the video.** It needs a screen
recording of the agent placing a real options order, 3:00–5:00, MP4. The rubric
penalises anything under 3 minutes. A shot list is in
`searching_docs/08_strategy_playbook/05_writeup_and_demo_templates.md`.
