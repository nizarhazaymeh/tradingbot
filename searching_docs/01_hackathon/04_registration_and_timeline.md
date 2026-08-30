# 04 — Registration & Timeline

## 1. How to join — step by step

From the event page and https://lablab.ai/getting-started-guide:

> The hackathon takes place online on the lablab.ai platform and the lablab.ai Discord server. Please register for both to participate. To join, click the Enroll button at the bottom of the page and read the Hackathon Guidelines, Getting Started Guide and the lablab.ai Hackathon Rule Book.
> Everyone is welcome to participate, regardless of previous AI or coding experience.

### On the lablab.ai platform
1. Register for the event via the event page: https://lablab.ai/ai-hackathons/alpaca-ai-trading-agents-hackathon
2. Complete your participant profile: https://lablab.ai/profile
3. Navigate to the specific event you are attending
4. **Click the "Enroll" button**
5. Create a team or join one. Team leaders invite via the "Add Teammate" button (shareable invitation URL), or click "Invite" on the participant list to send email + Discord notifications.

### On Discord — https://discord.gg/lablabai
1. `#ineedhelp` for mentor assistance — tag `@Mentor`
2. `#faq` for general inquiries
3. "Active Hackathon" channel + "Looking for a Team" thread to find teammates
4. Team coordination under "TEAM VOICE CHANNELS" (each has integrated text chat)

### Required reading (organizers explicitly name these three)
- Hackathon Guidelines — https://lablab.ai/ai-articles/hackathon-guidelines (also https://lablab.ai/guide)
- Getting Started Guide — https://lablab.ai/getting-started-guide
- Hackathon Rule Book — https://lablab.ai/hackathon-rules

### Also useful before kickoff
> "Before the kickoff, browse the AI Tech and tutorials pages to read up on the available technologies and get a head start on your project."
- https://lablab.ai/tech
- https://lablab.ai/ai-tutorials

---

## 2. Event schedule — three timezones

Official times are **UTC** on the live page; the source PDF lists **GMT+3**. ET column added because the market runs on ET.

| Event | UTC | GMT+3 | ET (EDT, UTC−4) |
|---|---|---|---|
| Hackathon Kick-off | Aug 28, 15:00 | Aug 28, 18:00 | Aug 28, 11:00 |
| lablab.ai opening words | Aug 28, 15:05 | Aug 28, 18:05 | Aug 28, 11:05 |
| Alpaca opening words | Aug 28, 15:10 | Aug 28, 18:10 | Aug 28, 11:10 |
| Introduction to the Challenge | Aug 28, 15:15 | Aug 28, 18:15 | Aug 28, 11:15 |
| Hackathon Guide | Aug 28, 15:25 | Aug 28, 18:25 | Aug 28, 11:25 |
| Discord Q&A session | Aug 28, 16:00 | Aug 28, 19:00 | Aug 28, 12:00 |
| **End of Submissions — deadline** | **Sep 4, 15:00** | **Sep 4, 18:00** | **Sep 4, 11:00** |

Kick-off is **live-streamed on Twitch**: https://www.twitch.tv/lablabai — recording later posted to Discord.

Google Calendar link found on the page encodes: `20260828T150000Z/20260904T150000Z` — confirming the UTC window.

---

## 3. Mentor support

- During the event, mentors give feedback and guidance.
- Use the **"Calling for Help"** feature on your team's page, or post in `#ineedhelp` on Discord tagging `@Mentor`.
- Post-kickoff, an email is sent containing scheduling links for **1:1 mentor calls** (optional).
- Note from the Rule Book: for "Mini Hackathon"-classified events, mentor support is limited. This is a 7-day event, so expect normal support — but book a 1:1 early, slots fill.

**Strategic use of mentors:** Alpaca's Trading API team lead (Brandon Meyerowitz) and PM (Grace Gao) are on the mentor/judge bench. A 1:1 where you ask a sharp technical question about `mleg` covered-leg rules or the indicative feed makes you memorable to a judge. Book one for **Day 2–3**, after you have real code and a real question.

---

## 4. Market calendar for the competition window

Trading days available between kickoff and deadline:

| Date | Day | Session | Notes |
|---|---|---|---|
| Aug 28 | Fri | 11:00 → 16:00 ET | ~5h. Weekly options expire today. |
| Aug 29 | Sat | — | closed |
| Aug 30 | Sun | — | closed |
| Aug 31 | Mon | 09:30 → 16:00 ET | full day. Month-end. |
| Sep 1 | Tue | 09:30 → 16:00 ET | full day |
| Sep 2 | Wed | 09:30 → 16:00 ET | full day |
| Sep 3 | Thu | 09:30 → 16:00 ET | full day |
| Sep 4 | Fri | 09:30 → 11:00 ET | ~1.5h before deadline. Weekly options expire today. |

**≈ 5.2 trading days.** Labor Day 2026 is **Mon Sep 7** — after the deadline, so no holiday inside the window.

⚠️ **Verify with the API, don't trust this table** — early-close days and holidays are authoritative from Alpaca:
```bash
alpaca calendar --start 2026-08-28 --end 2026-09-08
alpaca clock
```
(`GET /v2/calendar`, `GET /v2/clock` — see `../03_trading_api/03_assets_clock_calendar.md`)

**Consequences for strategy** — worked through in `../08_strategy_playbook/01_competition_window_analysis.md`:
- Two Friday weekly expirations fall inside the window (Aug 28, Sep 4).
- SPY/QQQ/IWM have Mon/Wed/Fri expirations, giving you expiries on Aug 28, Aug 31, Sep 2, Sep 4.
- Your final P&L snapshot is taken while the Sep 4 session is *still open* — so **close or hedge everything before Sep 4 09:30 ET**, don't leave the judge looking at an open, mid-move position.
