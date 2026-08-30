# 05 — Prizes, Terms & Payout

Source: event page "Prizes" section (verbatim), plus `Alpaca_Hackathon_Info.pdf`.

## 1. Prize structure

**🏆 Total prize pool: $6,000**

| Rank | Amount |
|---|---|
| 🥇 1st place | **$2,500** |
| 🥈 2nd place | **$1,500** |
| 🥉 3rd place | **$1,000** |

**Social Engagement prize · 2 winning teams**
- **$500 USD per winning team**
- **1-month Algo Trader Plus** subscription for **each team member** (provided individually)

> "Each of the 2 winning teams will receive $500 USD for the team, plus a one-month Algo Trader Plus subscription for every member of the winning team from Alpaca. The subscriptions are provided individually to each team member to help them continue building and scaling their algorithmic strategies."

Note: $2,500 + $1,500 + $1,000 = $5,000 main prizes; + 2 × $500 social = $6,000 total. The Algo Trader Plus subscriptions are in-kind on top (list price $99/month each — see `../02_alpaca_platform/04_market_data_plans_and_limits.md`).

**Technology partner prizes:** partners TBA before kickoff. To be eligible, the partner's technology must be integrated into a project submitted under the hackathon challenge. **Check the event page on Aug 28** — a late-announced partner prize is often the least-contested money in the event.

## 2. Prize terms (verbatim)

**Sponsor** — AlpacaDB, Inc. pays the $6,000 pool directly in USD.

**Eligibility** — 18+. Not available to Alpaca employees, contractors, immediate family/household members, or participants from sanctioned countries. Void where prohibited. No purchase or Alpaca account required.

**Individual payee** — Prizes are paid to individuals, not teams or companies. If a team wins, designate one member to receive the full amount (or confirm a split with Finance in advance).

**Taxes & documents** — W-9 (US) or W-8BEN (non-US), government photo ID, and bank details are required before payment.

**Payment** — Alpaca pays within 90 days of the event end once documents clear, including international sanctions screening.

**Important:**
- Winners are responsible for applicable taxes.
- US winners receiving more than $600 will receive a **1099-MISC**.
- Non-US payments are generally subject to **30% US withholding** unless a valid treaty claim applies on the **W-8BEN**.
- Gross prizes may be reduced by withholding and wire fees.
- Winners must complete required documentation **within 90 days of winner notification** or the prize may be forfeited.
- This is a **skill contest** and **judging is final**.
- Submissions must be **original and MIT-compliant**.
- Alpaca may use winner name, likeness, and project for publicity without additional compensation.
- Alpaca may modify or cancel prizes if the event is changed or cancelled.
- Alpaca will coordinate payouts directly with winners.

Full terms: https://lablab.ai/terms-of-use (§16 Participation Terms)

## 3. Practical notes for a non-US team

- You'll file a **W-8BEN**, not a W-9.
- Default withholding is **30%** unless a US income tax treaty applies to your country of residence and you claim it on the W-8BEN (Part II). Check whether your country has a US treaty article covering *other income* / *prizes*; many do not, and prize income is often not covered even where a treaty exists.
- Practical implication: a $2,500 first prize may net ~$1,750 before wire fees. Budget accordingly; this is not a reason to skip it, just don't plan around gross.
- Have ready **before** you win, to avoid the 90-day forfeiture clock: passport/national ID scan, bank details incl. SWIFT/IBAN, address, and tax residency info.
- **Designate the payee in advance.** If your team wins and you argue about who receives it, you burn days off a 90-day clock. Agree in writing on Day 1.

## 4. "MIT-compliant" requirement

Prize terms state submissions must be original and **MIT-compliant**. Practical reading: your submitted code must be licensable under MIT, meaning:
- Add a `LICENSE` file with the MIT license to your repo.
- Don't vendor GPL/AGPL-licensed code into the project (that would make MIT-licensing your work impossible).
- Alpaca's own tooling is friendly here: `alpaca-py` (Apache 2.0), `alpaca/cli` (Apache 2.0), `alpaca-skills` (Apache 2.0), `alpaca-mcp-server` — all permissive and MIT-compatible.
- Watch out for: some backtesting/TA libraries and some data providers are GPL or have restrictive data-redistribution terms. `pandas`, `numpy`, `scipy`, `pandas-ta` (MIT), `httpx`, `pydantic` are all fine. **`TA-Lib` Python wrapper is BSD but the C library has its own terms — prefer `pandas-ta` or compute indicators yourself.**
