"""Telegram bot flows against a fake Telegram API (no token or network needed).
Run:  python tests/telegram_bot_test.py"""
import os
import sys
import tempfile
import time

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "bot.db")
os.environ.update({"CLINIC_PASSWORD": "demo", "SESSION_SECRET": "bot-test-secret", "VOICELAB_API_KEY": "",
                   "AISHA_API_KEY": "", "LLM_BASE_URL": "", "LLM_API_KEY": "", "LLM_MODEL": "",
                   "STAFF_RELEASE_DELAY_HOURS": "0"})
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import telegram_bot as tb  # noqa: E402
from app.db import db  # noqa: E402
from app.seed import seed  # noqa: E402
from app.util import hash_code  # noqa: E402


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        check.failed = True


check.failed = False


class FakeApi:
    def __init__(self):
        self.calls, self.downloads = [], []

    def call(self, method, _http_timeout=30, **params):
        self.calls.append((method, params))
        return {"message_id": len(self.calls)}

    def download(self, file_id):
        self.downloads.append(file_id)
        return b"OggS fake voice"

    def sent(self):
        return [p for m, p in self.calls if m == "sendMessage"]

    def last(self):
        return self.sent()[-1]

    def buttons(self):
        kb = self.last().get("reply_markup", {}).get("inline_keyboard", [])
        return [b["callback_data"] for row in kb for b in row]


CHAT = 555001
api, uid = FakeApi(), [0]
bot = tb.Bot(api)


def msg(text=None, chat=CHAT, ctype="private", **extra):
    uid[0] += 1
    m = {"message_id": uid[0], "chat": {"id": chat, "type": ctype}, "from": {"id": chat, "language_code": "ru"}}
    if text is not None:
        m["text"] = text
    m.update(extra)
    bot.handle_update({"update_id": uid[0], "message": m})


def press(data, chat=CHAT):
    uid[0] += 1
    bot.handle_update({"update_id": uid[0], "callback_query": {
        "id": str(uid[0]), "data": data, "from": {"id": chat},
        "message": {"message_id": 1, "chat": {"id": chat, "type": "private"}}}})


codes = seed()
ward = codes["Therapy ward"]

# ---- patient: voice report in Russian ------------------------------------------------------
msg("/start")
check("start asks for language", api.buttons() == ["lang:uz", "lang:ru", "lang:en"])
press("lang:ru")
check("without a QR link the bot asks which clinic", "Какая клиника" in api.last()["text"])
msg("no-such-clinic")
check("unknown clinic code refused", "не найдена" in api.last()["text"])
msg("demo")
check("typed clinic code accepted", any("Demo clinic" in p["text"] for p in api.sent()[-2:]))
check("privacy note shown (Russian)", any("Что мы сохраняем" in p["text"] for p in api.sent()))
check("role choice offered", api.buttons() == ["role:patient", "role:staff", "role:case"])
press("role:patient")
check("ward list offered", "ward:" + ward in api.buttons())
labels = [b["text"] for row in api.last()["reply_markup"]["inline_keyboard"] for b in row]
check("department names shown in Russian", "Терапевтическое отделение" in labels and "Therapy ward" not in labels)
press("ward:" + ward)
check("rating offered", "rate:4" in api.buttons() and "rate:skip" in api.buttons())
press("rate:4")
msg(voice={"file_id": "VOICE1", "duration": 7, "mime_type": "audio/ogg", "file_size": 20000})
check("voice downloaded and transcribed", api.downloads == ["VOICE1"] and "send" in api.buttons())
check("draft shown for checking", "никто не подошёл" in api.last()["text"])
msg("Медсестра Гульнара ночью не пришла, звонил 901234567, ждали два часа.")
card = api.last()["text"]
check("typed correction replaces the draft", "ждали два часа" in card and "send" in api.buttons())
check("review shows the MASKED text, not the name or phone",
      "[NAME]" in card and "[PHONE]" in card and "Гульнара" not in card and "901234567" not in card)
check("review lists every field that is sent",
      all(x in card for x in ("Клиника: Demo clinic", "Терапевтическое отделение", "пациент или родственник", "Оценка: 4★", "Дата:", "Язык: Русский")))
check("review says what is NOT sent and asks for agreement",
      "Не отправляется" in card and "/privacy" in card and api.buttons() == ["send", "cancel"])
msg("/privacy")
check("/privacy shows the full terms", "Условия использования и конфиденциальность" in api.sent()[-2]["text"])
check("/privacy puts the review card back", "Будет отправлено ровно это" in api.last()["text"] and api.buttons() == ["send", "cancel"])
press("send")
done = api.sent()[-1]["text"] if "Спасибо" in api.sent()[-1]["text"] else api.sent()[-2]["text"]
code = done.split("<code>")[1].split("</code>")[0]
check("case code returned", len(code) == 9 and code[4] == "-")
with db() as conn:
    r = conn.execute("SELECT * FROM reports WHERE case_hash=?", (hash_code(code),)).fetchone()
check("report stored as patient / ru / rating 4", r and (r["source"], r["lang"], r["rating"], r["ward_code"]) == ("patient", "ru", 4, ward))
check("stored text is masked", r and "Гульнара" not in r["text_masked"] and "901234567" not in r["text_masked"])
check("stored text is exactly what the review card showed", r and r["text_masked"] in card)
from app import terms  # noqa: E402
check("agreed terms version recorded", r and r["terms_version"] == terms.TERMS_VERSION)
check("session forgotten after sending", CHAT not in bot.sessions)

# ---- staff: near miss, typed ----------------------------------------------------------------
msg("/start c_demo"); press("lang:uz"); press("role:staff")
labels = [b["text"] for row in api.last()["reply_markup"]["inline_keyboard"] for b in row]
check("department names shown in Uzbek", "Terapiya bo'limi" in labels and "Therapy ward" not in labels)
press("ward:" + ward)
check("staff harm options offered", api.buttons() == ["harm:near", "harm:none", "harm:minor", "harm:serious"])
press("harm:near")
msg("Dori dozasi noto'g'ri yozilgan edi, berishdan oldin sezib qoldik.")
card = api.last()["text"]
check("staff review shows type and week-only note",
      "Oz qoldi" in card and "faqat haftani" in card and "Roziman" in str(api.last()["reply_markup"]))
press("send")
with db() as conn:
    s = conn.execute("SELECT * FROM reports WHERE source='staff' ORDER BY id DESC LIMIT 1").fetchone()
check("staff near miss stored", s and s["near_miss"] == 1 and s["lang"] == "uz")

# ---- case follow-up -------------------------------------------------------------------------
msg("/case")
msg(code)
check("case with no messages", "Пока сообщений нет" in api.last()["text"])
with db() as conn:
    conn.execute("INSERT INTO case_messages (case_hash, sender, body, created_day) VALUES (?,?,?,?)",
                 (hash_code(code), "clinic", "Какой это был день?", "2026-11-18"))
msg("/case")
msg(code.lower())
check("clinic question shown with reply button", "Какой это был день?" in api.last()["text"] and api.buttons() == ["reply"])
press("reply")
msg("Это было в понедельник, медсестра Гульнара.")
check("reply is reviewed (masked) before sending", "[NAME]" in api.last()["text"] and api.buttons() == ["reply_send", "cancel"])
with db() as conn:
    early = conn.execute("SELECT 1 FROM case_messages WHERE case_hash=? AND sender='reporter'", (hash_code(code),)).fetchone()
check("nothing saved before agreeing", early is None)
press("reply_send")
with db() as conn:
    rep = conn.execute("SELECT body FROM case_messages WHERE case_hash=? AND sender='reporter'", (hash_code(code),)).fetchone()
check("reply stored and masked", rep and "Гульнара" not in rep["body"] and "понедельник" in rep["body"])
msg("/case"); msg("AAAA-BBBB")
check("unknown code rejected", "не найден" in api.last()["text"])

# ---- edge cases -----------------------------------------------------------------------------
n = len(api.calls)
msg("/start", chat=-100123, ctype="group")
check("group chats ignored", len(api.calls) == n)
msg("hello", chat=777)
check("no session -> asks to /start", "/start" in api.last()["text"])
msg("/start c_demo", chat=778); press("lang:en", chat=778); press("role:patient", chat=778); press("ward:" + ward, chat=778)
press("rate:skip", chat=778)
msg(chat=778, voice={"file_id": "LONG", "duration": 600, "mime_type": "audio/ogg"})
check("long voice message refused", "too long" in api.last()["text"] and "LONG" not in api.downloads)
msg("hi", chat=778)
check("too-short text refused", "at least a few words" in api.last()["text"])
msg(chat=778, photo=[{"file_id": "P"}])
check("photo mid-report repeats the question", "Send a voice message" in api.last()["text"] and 778 in bot.sessions)
press("send", chat=778)
check("send ignored without a draft", "Thank you" not in api.last()["text"])
press("cancel", chat=778)
check("cancel ends the session", 778 not in bot.sessions)
with db() as conn:
    cols = [c[1] for c in conn.execute("PRAGMA table_info(reports)")]
check("no chat id or username column exists", not any(c in cols for c in ("chat_id", "user_id", "username")))

# ---- one bot, many clinics ----------------------------------------------------------------
from app import clinics  # noqa: E402
with db() as conn:
    other = clinics.create(conn, "Other Clinic", "other", "otherpass1")
    other_ward = clinics.add_ward(conn, other, "Cardiology", "Kardiologiya bo'limi", "Кардиология", "Cardiology")
C2 = 900100
msg("/start w_" + other_ward, chat=C2)
check("ward QR link names the clinic", "Other Clinic" in api.last()["text"])
press("lang:uz", chat=C2)
check("ward QR link skips the clinic question", api.buttons() == ["role:patient", "role:staff", "role:case"])
press("role:patient", chat=C2)
check("ward QR link skips the department question", "rate:skip" in api.buttons())
press("rate:5", chat=C2)
msg("Qabulxonada navbat juda uzun edi.", chat=C2)
card2 = api.last()["text"]
check("review shows the right clinic and department", "Klinika: Other Clinic" in card2 and "Kardiologiya bo'limi" in card2)
press("send", chat=C2)
with db() as conn:
    rr = conn.execute("SELECT clinic_id, ward_code FROM reports WHERE text_masked LIKE 'Qabulxonada%'").fetchone()
check("report saved for that clinic", rr and rr["clinic_id"] == other and rr["ward_code"] == other_ward)
C3 = 900200
msg("/start c_other", chat=C3); press("lang:ru", chat=C3); press("role:staff", chat=C3)
check("clinic QR link offers only that clinic's departments",
      api.buttons() == ["ward:" + other_ward] and "ward:" + ward not in api.buttons())
press("ward:" + ward, chat=C3)  # a demo-clinic department, not offered: must be refused
check("another clinic's department is refused", "Ошибка" in api.last()["text"] and bot.sessions[C3].ward == "")
with db() as conn:
    clinics.update_ward(conn, other, other_ward, "Cardiology", "", "", "Cardiology", False)
msg("/start w_" + other_ward, chat=900300); press("lang:en", chat=900300)
check("removed department's QR link falls back to asking the clinic", "Which clinic" in api.last()["text"])

# ---- token never appears in errors ------------------------------------------------------------
real = tb.TelegramApi("123456:SECRET-TOKEN-VALUE")
real._base = "http://127.0.0.1:9/bot123456:SECRET-TOKEN-VALUE"
try:
    real.call("getMe", _http_timeout=2)
    err = ""
except tb.TelegramError as e:
    err = str(e)
check("network errors do not leak the token", err and "SECRET" not in err)

# ---- polling loop: one real pass (regression: getUpdates' own "timeout" parameter) ----------
class OnePoll(FakeApi):
    def call(self, method, _http_timeout=30, **params):
        if method == "getUpdates":
            if params.get("offset"):
                raise KeyboardInterrupt  # stop after the first batch
            return [{"update_id": 41, "message": {"message_id": 1, "chat": {"id": 9, "type": "private"},
                                                  "from": {"id": 9}, "text": "/start"}}]
        return super().call(method, _http_timeout, **params)


poll_api = OnePoll()
try:
    tb.Bot(poll_api).run_forever()
except KeyboardInterrupt:
    pass
time.sleep(0.5)
check("polling loop fetches and handles updates", any(m == "sendMessage" for m, _ in poll_api.calls))
try:
    real.call("getUpdates", _http_timeout=2, timeout=50, offset=1)
    err = "no error"
except tb.TelegramError as e:
    err = "telegram error"
except TypeError:
    err = "TypeError"
check("getUpdates accepts Telegram's timeout parameter", err == "telegram error")

sys.exit(1 if check.failed else 0)
