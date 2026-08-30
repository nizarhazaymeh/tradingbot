# 06 — Rules, Compliance & Disqualification Traps

Every way this submission can be sunk, and how to avoid each.

## 1. Hard gates — fail one, and you are out or unscored

| # | Trap | Source | Avoidance |
|---|---|---|---|
| 1 | **Reused / old paper account** for the submission | Event page, "Required for judging": *"Projects run on an existing or reused account will not be eligible for judging."* | Create a **brand-new** paper account. Do it Day 1, keep it clean, never test against it. |
| 2 | **Starting balance ≠ $100,000** | Event page: *"Competition account starting balance must be set to $100,000."* | $100k is the **default** for a new paper account. Do not customize it. Verify with `GET /v2/account` → `equity` on Day 1 before any trade. Note: **you cannot change the balance after creation** — if it's wrong, create another account. |
| 3 | **Account ID missing** from submission | Event page: *"required for judging… allows the judging team to identify your trading activity and evaluate your P&L"* | Record the account ID on Day 1. Put it in the README, the write-up, and the submission field. |
| 4 | **No options in the strategy** | Core requirement: *"all strategies must incorporate options trading."* | Options must be the primary instrument, including at least one `mleg` multi-leg trade. |
| 5 | **Neither MCP nor CLI used** | Core requirement | Use both. Show the MCP config and the CLI cron script in the repo. |
| 6 | **Not autonomous** | Core requirement | Ship a scheduled, unattended loop. A human approval gate is fine as a documented *risk control*, but demo the unattended path. |
| 7 | **Private GitHub repo** | Submission guide: *"If you submit a private repository, judges won't be able to fully review your work, which may lower your overall score."* | Public from Day 1. |
| 8 | **Not registered on Discord** | Event page: *"Please register for both to participate."* | Join https://discord.gg/lablabai and use your real profile name so organizers can match you. |
| 9 | **"Enroll" not clicked** | Event page instruction | Click it. Registration ≠ enrollment. |
| 10 | **Under 18** or Alpaca employee/contractor/family, or in a sanctioned country | Prize terms | Nothing to do but be aware. |
| 11 | **Missing the deadline** | Sep 4, 15:00 UTC | Submit by 12:00 UTC. Manual submission is only available 6h post-event **with prior approval**. |
| 12 | **Non-MIT-compliant / non-original code** | Prize terms | MIT LICENSE file; no copyleft dependencies; write your own strategy logic. |

## 2. Ethical conduct — instant disqualification (Rule Book, verbatim)

> Unethical behavior, such as plagiarism or gaming the voting system, will lead to immediate disqualification. If lablab.ai or its event partners determine that a participant has acted in a way that undermines the fairness or proper functioning of a hackathon—such as cheating, tampering with systems, using unauthorized automation, engaging in fraudulent behaviour, or in any other manner we consider grounds for disqualification—the participant may be removed from the event.

### Read this carefully in a *trading* context

"Undermines the fairness or proper functioning" plus the fresh-account rule closes several loopholes people will be tempted by:

| Tempting shortcut | Why it fails |
|---|---|
| Run 10 paper accounts, submit whichever got lucky | The submitted account must be *dedicated to this hackathon* and the judges see one account ID. Multiple submissions/accounts is exactly "gaming". Also: your GitHub history and decision logs would contradict a cherry-picked account. |
| Exploit paper-fill quirks (paper doesn't check your order size against NBBO liquidity) to book impossible fills | Documented paper behaviour — see `../02_alpaca_platform/03_paper_trading_environment.md`. A brokerage judging panel will spot a 5,000-contract fill in an illiquid strike instantly. It reads as fraudulent, not clever. |
| Take one enormous 0DTE lottery position on Sep 3 | Not against the rules, but the P&L criterion says *"how effectively the strategy performs through its trading activity"* — a single coin flip is not a strategy, and the downside is a deeply negative account with nothing to show. |
| Fabricate the P&L numbers in slides | Judges have your account ID. They will look. |
| Backdate commits to fake a 7-day history | Git author/committer dates and push timestamps don't match; trivially detectable. |

**The honest version of "maximize P&L" is in `../08_strategy_playbook/03_pnl_strategy_and_risk_gates.md`** — it wins on process quality, which is what this panel is equipped to reward.

## 3. Other Rule Book provisions

- **Adherence to guidelines:** "Failure to adhere to submission guidelines may result in a lower score or exclusion from the hackathon."
- **Manual submission:** available 6 hours post-hackathon, valid reasons only, **prior approval from organizers or mentors** required.
- **Mentors/organizers may participate but are not eligible for prizes.** If they participate they cannot judge.
- **Judge's code of conduct:** confidentiality of submissions; abstain on conflicts of interest; declare affiliations; must not copy, retain, or share entry materials.

## 4. Trading-specific compliance you should state in your write-up

Include these lines — they cost nothing and signal you understand the domain (which this panel cares about):

- Paper trading is a **simulation**; results are hypothetical and do not represent actual trading. Paper does not account for market impact, information leakage, slippage from latency, order queue position, price improvement, regulatory fees, or dividends. (`../02_alpaca_platform/03_paper_trading_environment.md`)
- Nothing in the project is investment advice or a recommendation.
- Options involve significant risk; long options can expire worthless; short options can lose more than the premium received; assignment risk exists especially near expiration. Read *Characteristics and Risks of Standardized Options*: https://www.theocc.com/company-information/documents-and-archives/options-disclosure-document
- The system uses LLMs, which can produce inconsistent, incomplete, or inaccurate output. Deterministic risk controls and human review reduce but do not eliminate this risk.

## 5. Security hygiene (a real disqualification risk)

- **Never commit API keys.** Before pushing, and again before submitting:
  ```bash
  git log -p | grep -iE 'APCA|ALPACA_(API|SECRET)|PK[A-Z0-9]{16}|sk-'
  ```
  If a key ever hit a public repo, **rotate it in the dashboard immediately** — and if it was on the competition account, that account is compromised and you may need a new one (which restarts your P&L).
- Use `.env` + `.gitignore`; ship `.env.example` with placeholders.
- The MCP server config holds keys in your MCP client config — don't screenshot that file in the demo video or slides. Blur it.
- CLI stores credentials in `~/.config/alpaca/profiles/` at 0600 — don't `cat` that in the demo either.
- Alpaca's own skill guidance: *"NEVER ask for API keys or secrets in chat"*, *"NEVER print credentials, tokens, account numbers, or profile details in plain text."* Follow it — and say you follow it in the write-up.
- **Do NOT set `ALPACA_LIVE_TRADE=true` or `ALPACA_PAPER_TRADE=false` anywhere.** Paper is the default in both CLI and MCP; keep it that way. An accidental live order is a real-money event.
