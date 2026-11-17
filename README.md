# Clinic Safety & Feedback Platform (MVP)

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
Smoke test: `python tests/smoke_test.py`.

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

## Connect the real services

**VoiceLab (Aisha) speech-to-text.** Put your key in `.env` as `AISHA_API_KEY`. The server calls
`POST /api/v1/stt/post/` with form fields `audio` and `language` and the `X-Api-Key` header (see `app/voice.py`).
Check the official docs for accepted audio formats, limits and the exact response field names. The parser tries
`transcript`, `text` and `result`. If the service rejects the browser's webm audio, the code retries after converting to
wav with `ffmpeg` (install `ffmpeg` on the server for that fallback).

**Language model (optional).** Any OpenAI-compatible chat API: set `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`.
It improves triage, neutral summaries and root-cause help. Text is **masked before** it is sent.
Without it, rules are used.

## What is implemented

- Voice or text reporting in Uzbek (Latin), Russian and English; transcript is shown for the person to check and edit.
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
- **Not built:** the Telegram bot for staff, the AI phone line, multiple clinics with separate data (one clinic only),
  user accounts and roles (one shared password), HTTPS and backups. Add these before any real use.
- Clinic logins are kept in server memory: restarting the server logs everyone out, and the app must run as a single
  process (no `--workers`). Set `SESSION_SECRET` to a long random value before real use and keep it fixed afterwards,
  because case codes are checked against it.
- Dashboard text is English only. UI strings for uz / ru need review by a native speaker.
- All demo data is invented. Never load real patient data into a demo.
- **Legal checks to do before real use:** where personal data and voice may be stored and processed (in-country
  rules, third-party services), and how confidential reports are protected. The app does not promise legal immunity.

## Code map

```
app/main.py        routes (public pages, report API, case follow-up, clinic dashboard API)
app/ai.py          masking, triage, summaries, root-cause assistant (LLM + rule fallback)
app/voice.py       VoiceLab / Aisha speech-to-text client (audio never stored)
app/analytics.py   dashboard queries with the privacy rules (K_MIN, roll-up, summaries only)
app/db.py          SQLite schema
app/seed.py        synthetic demo data with a planted cross-channel story
app/templates/     pages          app/static/  styles, i18n strings, voice recorder
tests/smoke_test.py  end-to-end check
```
