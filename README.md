# Ovoz: clinic safety & feedback, by voice (MVP)

*Ovoz* means "voice" in Uzbek.

Anonymous reporting for clinics, covering hackathon items 7 (staff report errors without fear) and 8 (patients give
anonymous feedback). Patients and staff speak up in Uzbek or Russian, by voice or text. AI masks personal details, sorts
reports, links patient and staff reports about the same ward, and helps find root causes. Only the clinic sees the data.

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                   # optional: add keys, change the password
python -m app.seed                                     # loads synthetic demo data (prints a demo case code)
uvicorn app.main:app --reload --port 8000
```

Open http://localhost:8000. Clinic login password: `demo` (change `CLINIC_PASSWORD` in `.env`).
Telegram bot (optional, in a second terminal): `python -m app.telegram_bot` (needs `TELEGRAM_BOT_TOKEN`).
Tests: `python tests/smoke_test.py` and `python tests/telegram_bot_test.py` (both run in demo mode, no keys used).

The app runs with **no keys at all**: voice returns a sample transcript and AI triage uses keyword rules.

## Pages

| Page | Who | What |
|---|---|---|
| `/r/{ward_code}` | patients, relatives | Anonymous feedback by voice or text (the QR code points here), uz / ru / en |
| `/staff` | staff | Anonymous report of a mistake or near-miss, voice or text |
| `/case` | reporter | Enter the case code to read clinic questions and reply anonymously |
| `/login`, `/dashboard` | clinic | Linked problems, urgent items, early-warning radar, action tracker, latest reports |
| `/qr` | clinic | Printable QR codes, one per ward |
| `/board/{ward_code}` | ward screen | "You said, we did": completed actions shown to patients and staff |
| Telegram bot | patients, staff | Same reports by voice message or text: language → patient / staff → ward → rating or harm → message → check → send. `/case` reads clinic questions and replies |

## Connect the real services

**VoiceLab speech-to-text.** Create a key at VoiceLab (it starts with `vlk_`) with **Speech to text = Access** and
everything else off, and put it in `.env` as `VOICELAB_API_KEY`. The server sends the audio to
`POST https://api.voicelab.uz/v1/stt`, polls `/v1/stt/transcriptions/{id}` until it is done, then **deletes the job**,
because VoiceLab otherwise keeps the transcript and audio (see `app/voice.py` and https://docs.voicelab.uz/api/stt).
Browser WebM, iPhone M4A and Telegram OGG audio are accepted as they are. `/api/health` shows which service is active.
Older Aisha keys (`AISHA_API_KEY`, `back.aisha.group`) still work through the previous code path.

**Telegram bot.** In Telegram, open @BotFather, send `/newbot`, pick a name and a username ending in `bot`, and put
the token it gives you in `.env` as `TELEGRAM_BOT_TOKEN`. Run `python -m app.telegram_bot` next to the web app. It
uses long polling, so it needs no public address. Voice messages go through the same speech-to-text as the web form.
The bot stores no chat id, username or audio; the conversation in progress lives in memory for up to 30 minutes.
Telegram itself still knows who sent a message, and the bot says so to users.

**Language model (optional).** Any OpenAI-compatible chat API: set `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`.
It improves triage, neutral summaries and root-cause help. Text is **masked before** it is sent.
Without it, rules are used.

## What is implemented

- Voice or text reporting in Uzbek (Latin), Russian and English; transcript is shown for the person to check and edit.
- **Check and agree, every time.** Before any report or reply is sent (web and bot), the person sees exactly what will
  be stored: the text after masking, the department, their role, rating or harm level, date and part of day, language,
  plus what is *not* sent and who will see it. Nothing is saved until they agree to the Terms of use and privacy
  (`/privacy`, uz / ru / en, `app/terms.py`). The API refuses reports without agreement, and each report records the
  agreed `terms_version`. Set `CLINIC_NAME` and `CLINIC_CONTACT` in `.env` to fill in the terms.
- Department names in Uzbek, Russian and English (`wards.name_uz`, `wards.name_ru`), following the chosen language.
- Visible privacy panel on the report pages; no name, phone, device ID, IP address or audio is stored.
- Masking of phones, IDs, times, room numbers, titled names, common first names and patronymics.
- Triage: category, severity 1-5, urgent flag, near-miss flag, neutral one-sentence summary.
- Cross-channel link: a problem seen by both patients and staff in the same place is marked "linked".
- Small-group privacy: wards or problems with fewer than `K_MIN` reports are rolled up or hidden.
- Staff reports shown to management only as neutral summaries with week-level dates; optional release delay.
- Anonymous two-way follow-up with a random case code (only a hash of the code is stored).
- Root-cause assistant (5-whys and fixes) that turns into a tracked action; completed actions feed the ward board.
- Early-warning radar: a place with clearly more reports than usual this week.
- Per-device rate limits (kept in memory only), room-free QR codes (one per ward).

## Known limits and not built yet

- **Name masking is demo-grade.** Rules catch titled names ("Dr X", "Медсестра X"), a list of common first names,
  patronymics, phones, times and rooms. They do not catch every name. For real use add a language-model or NER pass and
  review what is stored.
- Keyword triage is simple. It works for the demo; accuracy needs real data and testing.
- **Not built:** multiple clinics with separate data (one clinic only),
  user accounts and roles (one shared password), HTTPS and backups. Add these before any real use.
- Clinic logins are kept in server memory: restarting the server logs everyone out, and the app must run as a single
  process (no `--workers`). Set `SESSION_SECRET` to a long random value before real use and keep it fixed afterwards,
  because case codes are checked against it.
- Dashboard text is English only. UI strings for uz / ru need review by a native speaker.
- All demo data is invented. Never load real patient data into a demo.
- The Terms & Privacy text is a draft written for the MVP: have a lawyer and native speakers review it.
- **Legal checks to do before real use:** where personal data and voice may be stored and processed (in-country
  rules, third-party services), and how confidential reports are protected. The app does not promise legal immunity.

## Code map

```
app/main.py        routes (public pages, report API, case follow-up, clinic dashboard API)
app/reports.py     saving reports and the case thread (shared by the web app and the bot)
app/terms.py       Terms of use and privacy (uz / ru / en) and TERMS_VERSION
app/static/review.js  the "check what will be sent, then agree" step on the web pages
app/telegram_bot.py  Telegram bot (uz / ru / en, voice messages and text)
app/ai.py          masking, triage, summaries, root-cause assistant (LLM + rule fallback)
app/voice.py       VoiceLab speech-to-text client, legacy Aisha path (audio never stored, VoiceLab jobs deleted)
app/analytics.py   dashboard queries with the privacy rules (K_MIN, roll-up, summaries only)
app/db.py          SQLite schema
app/seed.py        synthetic demo data with a planted cross-channel story
app/templates/     pages          app/static/  styles, i18n strings, voice recorder
tests/smoke_test.py  end-to-end check of the web app
tests/telegram_bot_test.py  bot flows against a fake Telegram
```
