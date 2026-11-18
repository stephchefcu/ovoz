# Ovoz: team notes

*Ovoz* ("voice") lets patients, relatives and staff report problems in a clinic **anonymously, by voice or text**
(Uzbek, Russian, English), on the **web** or in **Telegram**. AI hides personal details, sorts reports, links what
patients and staff say about the same ward, and helps the clinic fix causes. Hackathon problems #7 and #8.
Every page is in Uzbek, Russian and English.

## Links

- **Live demo:** **https://hunting-grace-type-floor.trycloudflare.com** (changes whenever the tunnel restarts)
- **Code (public):** **https://github.com/stephchefcu/ovoz**
- **Telegram bot:** **https://t.me/ovoz_feedback_bot**

## Try it (demo)

| What | Path (add to the link) |
|---|---|
| Home (add `?lang=ru` or `?lang=en` to open it in that language) | `/` |
| Demo clinic page | `/c/demo` |
| Patient form (Surgery ward A, what the QR opens) | `/r/PDSnB8oz` |
| Staff form | `/c/demo/staff` |
| Follow up a report (demo code with a clinic question: `DEMO-2345`) | `/case` |
| "You said, we did" board for Surgery ward A (for a screen in the ward) | `/board/PDSnB8oz` |
| Clinic login → dashboard, settings, QR codes | `/login` |
| Sign up a new clinic | `/signup` |
| Terms and privacy | `/privacy?c=demo` |

**Telegram:** [@ovoz_feedback_bot](https://t.me/ovoz_feedback_bot)
- Patient (Surgery ward A): `https://t.me/ovoz_feedback_bot?start=w_PDSnB8oz`
- Staff: `https://t.me/ovoz_feedback_bot?start=s_demo`

**Clinic login:** clinic code `demo`. The password is `CLINIC_PASSWORD` in `.env` on the laptop that runs Ovoz
(never in the repo); ask whoever runs it. Or sign up your own test clinic at `/signup`.

## The three codes

- **Case code** (e.g. `K7QM-4TXH`): the reporter gets it after sending. It is their only link to the report: at `/case`
  they see the clinic's questions and answer, still anonymous. Only a scrambled form is stored. Demo: `DEMO-2345`.
- **Clinic code** (e.g. `demo`): the clinic's short name, chosen at sign-up. Used to log in and in the Telegram bot.
- **Department code** (e.g. `PDSnB8oz`): random, inside each QR code (`/r/<code>`). Nobody types it; random so links
  cannot be guessed.

## Languages

- Every page has a **UZ / RU / EN** switch. Uzbek is the default; the browser remembers the choice, and `?lang=ru`
  in a link opens that language. The Telegram bot asks for the language at the start.
- On the dashboard the labels, problem types and root-cause help switch too (the AI model is asked to answer in that
  language). What people wrote stays as written: reports, staff summaries, department names in lists, and actions
  the clinic types.
- The text lives in `app/static/i18n.js` (patient, staff, home pages), `app/static/i18n-clinic.js` (clinic pages and the
  board) and `app/ai.py` (root-cause suggestions). The Uzbek and Russian wording is a draft: have native speakers check it.

## The flows

- **Patient (department QR):** "Help NOW" button (nurse call / 103), I am a patient or a relative,
  good / OK / bad (optional), voice or text, check, send. Under 30 seconds.
- **Staff (staff-room QR):** department, voice or text, check, send. Staff never pick a category or severity: the AI does.
- **Every time, before anything is saved:** a short check screen shows exactly what will be stored: the text with
  names and numbers already hidden, and one line with ward · role · date and part of day. It says "Name, phone and
  voice are not stored", warns about details that could identify someone (e.g. "the only nurse", an age), and they tick
  "I agree to the terms". Then they get a case code and a "See the reply" button.
- **New clinic:** sign up → it lands on its QR page with one ready department, "Umumiy" (General), so it can print
  a working QR code at once. Real departments are optional: add them later in Settings when you want reports linked
  and fixes per department (small clinics can keep just "Umumiy").
- **Clinic:** reports are the first box on the dashboard, newest first. Also on the dashboard (headline = problems fixed; linked patient + staff problems; urgent; early warning),
  root-cause help, actions, "You said, we did" board, questions to reporters via the case code.

## Design rules (keep it simple)

- As little text as possible: a title, the controls, one button. No explanation paragraphs or extra info boxes.
- One short line of help at most; put details on the terms page (`/privacy`), not on the form.
- Every new text goes into all three languages (`app/static/i18n.js` or `app/static/i18n-clinic.js`).
- One blue accent colour, no emojis (a test checks this), big buttons that work on a phone.
- One top bar and footer for every page (`app/templates/base.html`). Page links come from `app/templates/_nav.html`
  (clinic pages: Dashboard, QR codes, Settings, Log out, with the current page highlighted); the language switch is
  always last. Forms like login and sign-up use the narrow layout (`wrap narrow`) with a full-width button.

## Our competitive edge (what to say)

Today clinics use paper complaint books or boxes, official complaint channels and hotlines, general survey tools or
Telegram bots, or (rarely) big international incident-reporting systems that are for staff only and mostly in English.

1. **Patients and staff in one place, linked.** Others collect either patient complaints or staff incidents. Ovoz links
   them: patients complain about waiting at night and nurses report being alone on the night shift in the same ward:
   one **linked** problem, the real cause. This is our main difference.
2. **People actually speak up: truly anonymous.** No name, phone, Telegram ID, IP or audio; names hidden automatically;
   people check what is stored; small groups combined; staff reports week only.
3. **Built for Uzbekistan.** Voice in Uzbek and Russian (works for anyone, whatever their literacy), Telegram, a QR code
   on the wall: no app, no sign-in, under 30 seconds.
4. **It closes the loop.** The case code lets the clinic ask questions and the person answer, still anonymous. The
   "You said, we did" board shows that speaking up changes things.
5. **Fixes, not complaints.** Root-cause help (processes, not blame), an action tracker, and the headline number is
   problems fixed, so clinics are never punished for listening.
6. **Cheap and fast to start.** Sign up and print a working QR code in a minute; free for small clinics, then priced per
   department, never per report.

**Be honest about the gaps:** no real-clinic pilot yet; AI sorting needs a model key (otherwise keyword rules); it runs
from one laptop through a temporary link; no staff roles yet; plans are not enforced in the app. Strongest next step: a
pilot in one clinic with numbers (reports per week, share linked, problems fixed within 30 days).

## What to say about privacy

- We store **no** name, phone, Telegram ID, device, IP address or audio. Voice is deleted after transcription,
  also at VoiceLab.
- Time is stored as day + morning / afternoon / night only. Staff reports reach managers with the week only: as the AI's neutral summary,
  or, without an AI key, as the text the reporter checked (names and numbers hidden).
- Places with fewer than 3 reports are combined, so nobody can be singled out. Wards are never ranked by report count.
- Each clinic sees only its own data.
- "We don't rely on people being perfect. We design so honest behaviour is easy and dishonest behaviour is visible."

## Honest limits

- Name hiding is rule-based and can miss names; the privacy check helps, a language model would do better.
- Triage uses keyword rules. Claude Sonnet 5.5 is ready but **off**: to switch it on, run `pip install -r requirements.txt`,
  put `ANTHROPIC_API_KEY=...` in `.env` and restart the web app and the bot (`/api/health` then shows `"llm": "claude"`).
  About $2 per busy clinic per month. Only text with names already hidden is sent; if Claude is down, the rules take over.
- One shared password per clinic: no roles yet.
- Not built (say "in our pilot design"): instant duty-manager alert, roles (ward head, quality coordinator),
  ACT / WATCH / CLOSE with reasons and audit log, 30-day "did the fix work" check, silence and zero-scan alerts.
- Hosting is a free tunnel from one laptop: if the laptop sleeps or restarts, the link stops or changes.
- Terms text and Uzbek / Russian wording need a lawyer and native speakers before real use.

## Run it (on the laptop)

**Before the first run,** check `.env` (copy it from `.env.example` if it is missing):
- `SESSION_SECRET`: a long random value. It protects stored case codes: set it once and never change it after
  real reports exist, or old case codes stop working.
- `CLINIC_PASSWORD`: the demo clinic's password. Without it, the password is `demo`.
- Optional: `VOICELAB_API_KEY` for real voice (otherwise demo text is filled in), `ANTHROPIC_API_KEY` for AI sorting with Claude (off until set),
  `TELEGRAM_BOT_TOKEN` for the bot.

Three terminal tabs in the project folder:

```bash
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --proxy-headers --forwarded-allow-ips 127.0.0.1 --no-access-log
```
```bash
.venv/bin/python -m app.telegram_bot
```
```bash
~/.local/bin/cloudflared tunnel --no-autoupdate --url http://127.0.0.1:8000
```

New tunnel link → reprint QR codes from `/qr`. Keep the laptop awake (`caffeinate -d`).
Tests: `python tests/smoke_test.py` and `python tests/telegram_bot_test.py` (every line should say PASS).

**Get the latest code** (after a pull request is merged): in a free tab run `git pull origin main`, then restart the
web app in its own tab (Ctrl+C, wait for the `ovoz %` line, then the same command). Restart the bot only if its code
changed. The tunnel can keep running, so the link stays the same. Tab titles show which program runs where; never press
Ctrl+C in the cloudflared tab.

**If something won't start:**
- Web app says `address already in use`, or the bot keeps printing `Conflict … only one bot instance`: an old copy is
  still running (for example from a closed window). Stop all old copies, check nothing is left, then start each again:
  `pkill -f "uvicorn app.main:app"; pkill -f "app.telegram_bot"` and `pgrep -fl "uvicorn|telegram_bot"` (prints nothing).
- `Conflict` still there: the bot is running on another computer with the same token. Only one copy may run.
- `git pull` refuses because of local changes: `git stash push -u -m "laptop changes"`, then pull again (the changes
  are kept in the stash).
- Starting everything over (Cmd+Q) also stops the tunnel: the link changes, so update it here and reprint the QR codes.
Code: https://github.com/stephchefcu/ovoz (public). Keys live only in `.env`: never commit it.

## Logo

**The logo is the name "ovoz"**, where the second "o" has five blue bars inside (a voice). Navy letters
`#0f172a`, blue bars `#2563eb`, rounded lines. On dark backgrounds use the white version (white letters, light-blue bars).

**The icon** is that second "o" on its own (navy ring, white inside, blue bars). Use it only where a square is needed:
Telegram picture, app icon, browser tab.

- `brand-kit/ovoz-logo.png`: the logo on white (2048 px wide), for documents and slides
- `brand-kit/ovoz-logo-transparent.png`: the logo with no background, for light coloured backgrounds
- `brand-kit/ovoz-logo-white.png`: the white logo with no background, for dark backgrounds
- `brand-kit/ovoz-icon.png`: the icon on white (1024 px), also the Telegram bot picture (@BotFather → `/setuserpic`)
- `brand-kit/ovoz-icon-transparent.png`: the icon with no background
- `brand-kit/ovoz-icon-small.png`: three-bar icon, only for tiny sizes (browser tab, 16–32 px)
- `brand-kit/ovoz-logo-overview.png`: all of them on one page
- `brand-kit/svg/`: the same as vectors (`wordmark.svg`, `wordmark-white.svg`, `mark.svg`, `mark-small.svg`);
  `brand-kit/ovoz-logos.zip`: everything in one file

## 2-minute demo

1. Scan a department QR on a phone: tap Patient, a face, record a voice note in Uzbek.
2. Show the check screen: the hidden name, "Name, phone and voice are not stored", "I agree". Send, get the code.
3. Staff side in Telegram: one voice note, AI decides it's a near-miss.
4. Dashboard: the same ward appears as a **linked** problem (patients + staff), root-cause help, create an action.
5. Mark it done: it shows on the "You said, we did" board; reply to the reporter via the case code.
6. Switch the dashboard to **RU** or **UZ**: the whole page and the root-cause help change language.
