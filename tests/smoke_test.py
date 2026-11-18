"""Quick end-to-end check of the main flows. Run:  python tests/smoke_test.py   (uses a temporary database)"""
import os
import re
import sys
import tempfile

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
# Ignore the real .env: demo password, no paid speech or LLM calls.
os.environ.update({"CLINIC_PASSWORD": "demo", "SESSION_SECRET": "smoke-test-secret", "VOICELAB_API_KEY": "",
                   "AISHA_API_KEY": "", "ANTHROPIC_API_KEY": "", "LLM_BASE_URL": "", "LLM_API_KEY": "", "LLM_MODEL": "",
                   "STAFF_RELEASE_DELAY_HOURS": "0", "K_MIN": "3"})
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app import ai  # noqa: E402
from app.main import app  # noqa: E402
from app.seed import seed  # noqa: E402


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        check.failed = True


check.failed = False

# masking
m = ai.mask_text("Medsestra Dilnoza qo'pol edi, tel 901234567, xona 4, soat 03:15.")
check("masking removes name, phone, room and time", all(x in m for x in ["[NAME]", "[PHONE]", "[ROOM]", "[TIME]"]) and "Dilnoza" not in m)
check("clock times in words are hidden (7am, soat 7, в 7 утра)",
      all("[TIME]" in ai.mask_text(x) for x in ["noticed at 7am", "soat 7 da keldi", "в 7 утра"]))
check("durations stay (2 soat kutdik, ждали 3 часа)",
      "[TIME]" not in ai.mask_text("2 soat kutdik") + ai.mask_text("ждали 3 часа") + ai.mask_text("7 amazing nurses"))
check("word-boundary keywords (no false 'urgent' on bo'limida)", not ai.rule_triage("Bolalar bo'limida sovuq", "patient")["urgent"])
check("urgent detected", ai.rule_triage("У мужа сильная боль в груди", "patient")["urgent"])

codes = seed()
clinic, anon = TestClient(app), TestClient(app)
check("dashboard locked without login", anon.get("/api/dashboard").status_code == 401)
check("login works", clinic.post("/login", data={"clinic": "demo", "password": "demo"}, follow_redirects=False).status_code == 303)
d = clinic.get("/api/dashboard").json()
check("a cross-channel linked problem is found", d["kpi"]["linked_clusters"] >= 1)
check("small groups are hidden or rolled up", d["kpi"]["hidden_small_groups"] > 0 and all(c["total"] >= d["privacy"]["k_min"] for c in d["clusters"]))
check("staff reports show summaries only", all("[" not in f["text"] or f["source"] == "patient" for f in d["feed"]))

from app import terms  # noqa: E402
TV = terms.TERMS_VERSION
report = {"source": "patient", "ward_code": codes["Therapy ward"], "text": "Tualet iflos, hid keladi.", "lang": "uz"}
check("report without agreeing is refused", anon.post("/api/report", json=report).status_code == 400)
check("report agreeing to old terms is refused",
      anon.post("/api/report", json={**report, "agree": True, "terms_version": "old"}).status_code == 409)
pv = anon.post("/api/preview", json={"text": "Hamshira Dilnoza kelmadi, tel 901234567"}).json()
check("preview shows the masked text and saves nothing",
      "[NAME]" in pv["masked"] and "[PHONE]" in pv["masked"] and "Dilnoza" not in pv["masked"] and pv["time_bucket"])
r = anon.post("/api/report", json={**report, "agree": True, "terms_version": TV})
check("anonymous report accepted + case code", r.status_code == 200 and re.match(r"^[A-Z0-9]{4}-[A-Z0-9]{4}$", r.json()["case_code"]))
code = r.json()["case_code"]
from app.db import db  # noqa: E402
from app.util import hash_code  # noqa: E402
with db() as conn:
    stored = conn.execute("SELECT terms_version FROM reports WHERE case_hash=?", (hash_code(code),)).fetchone()
check("agreed terms version stored with the report", stored and stored["terms_version"] == TV)
check("reply without agreeing is refused", anon.post("/api/case/reply", json={"code": code, "body": "hi"}).status_code == 400)
check("reply after agreeing is accepted",
      anon.post("/api/case/reply", json={"code": code, "body": "Dushanba kuni", "agree": True, "terms_version": TV}).status_code == 200)
pg = anon.get("/privacy").text
check("privacy page in all three languages",
      all(x in pg for x in ("Foydalanish shartlari va maxfiylik", "Условия использования", "Terms of use and privacy", TV)))
pr = anon.get("/pricing").text
check("pricing page in all three languages, free for patients, reports never blocked",
      all(x in pr for x in ("Narxlar", "Цены", "Pricing", "790\u202f000", "No plan ever stops, delays or hides a report")))
pt = anon.get("/r/" + codes["Therapy ward"]).text
check("patient page carries Uzbek and Russian department names", "Terapiya bo&#39;limi" in pt or "Terapiya bo'limi" in pt)
rid = clinic.get("/api/dashboard").json()["feed"][0]["id"]
check("clinic can ask a question", clinic.post("/api/clinic/ask", json={"report_id": rid, "body": "Which day?"}).status_code == 200)
check("reporter sees the question and their reply by code",
      [m["sender"] for m in anon.post("/api/case/open", json={"code": code}).json()["messages"]] == ["reporter", "clinic"])
check("wrong code rejected", anon.post("/api/case/open", json={"code": "AAAA-AAAA"}).status_code == 404)
check("RCA works", clinic.post("/api/clusters/rca", json={"key": d["clusters"][0]["key"]}).json()["fixes"])
check("root-cause help answers in Russian when asked",
      "Почему" in " ".join(clinic.post("/api/clusters/rca", json={"key": d["clusters"][0]["key"], "lang": "ru"}).json()["whys"]))
check("RCA with a malformed key is refused, not a server error",
      clinic.post("/api/clusters/rca", json={"key": "garbage"}).status_code == 422)
check("demo transcription works", anon.post("/api/transcribe", files={"audio": ("v.webm", b"x", "audio/webm")}, data={"lang": "uz"}).json()["text"])


# login sessions: the old fixed cookie (HMAC of the default secret) must not work; logout must end the session
import hashlib, hmac  # noqa: E402,E401
forged = hmac.new(b"change-me", b"clinic-session", hashlib.sha256).hexdigest()
check("forged default-secret cookie rejected",
      TestClient(app, cookies={"clinic_session": forged}).get("/api/dashboard").status_code == 401)
old = clinic.cookies.get("clinic_session")
clinic.get("/logout", follow_redirects=False)
check("logout ends the session",
      TestClient(app, cookies={"clinic_session": old}).get("/api/dashboard").status_code == 401)
check("wrong password rejected", anon.post("/login", data={"clinic": "demo", "password": "nope"}).status_code == 401)

# ---- many clinics: each sees and manages only its own data --------------------------------------
clinic = TestClient(app)  # the earlier demo session was logged out above
clinic.post("/login", data={"clinic": "demo", "password": "demo"})
b = TestClient(app)
r = b.post("/signup", data={"name": "Second Clinic", "slug": "second", "contact": "room 5", "password": "secondpass1",
                            "password2": "secondpass1"}, follow_redirects=False)
check("a new clinic can sign up and lands on its QR codes", r.status_code == 303 and r.headers["location"].startswith("/qr"))
check("sign-up errors carry a translation key", 'data-i18n="su_err_taken"' in TestClient(app).post("/signup", data={
      "name": "Copy", "slug": "demo", "password": "longpass1", "password2": "longpass1"}).text)
check("clinic codes are unique", TestClient(app).post("/signup", data={"name": "Copy", "slug": "second",
      "password": "secondpass1", "password2": "secondpass1"}).status_code == 400)
new_wards = b.get("/api/settings").json()["wards"]
check("new clinic starts with one ready department (Umumiy) and no reports",
      [w["name_uz"] for w in new_wards] == ["Umumiy"] and b.get("/api/dashboard").json()["kpi"]["reports"] == 0)
qr_new = b.get("/qr?new=1").text
check("its QR sheet works right away", "Umumiy" in qr_new and 'class="segno"' in qr_new and 'data-i18n="qr_ready"' in qr_new)
wcode = b.post("/api/wards", json={"name": "Cardiology", "name_uz": "Kardiologiya bo'limi", "name_ru": "Кардиология",
                                   "unit": "Cardiology"}).json()["code"]
check("clinic adds its own department", any(w["code"] == wcode for w in b.get("/api/settings").json()["wards"]))
check("department pages show the clinic", "Second Clinic" in b.get("/r/" + wcode).text and "Kardiologiya" in b.get("/r/" + wcode).text)
check("clinic page lists only its departments", "Kardiologiya" in anon.get("/c/second").text
      and "Terapiya" not in anon.get("/c/second").text and "Kardiologiya" not in anon.get("/c/demo").text)
r = anon.post("/api/report", json={"source": "patient", "ward_code": wcode, "text": "Navbat juda uzun, 3 soat kutdik.",
                                   "lang": "uz", "agree": True, "terms_version": TV})
check("report to the new clinic accepted", r.status_code == 200)
bd = b.get("/api/dashboard").json()
check("new clinic sees its report", bd["kpi"]["reports"] == 1)
check("demo clinic does NOT see it", all("Navbat juda uzun" not in f["text"] for f in clinic.get("/api/dashboard").json()["feed"]))
demo_report = clinic.get("/api/dashboard").json()["feed"][0]["id"]
check("a clinic cannot question another clinic's report",
      b.post("/api/clinic/ask", json={"report_id": demo_report, "body": "?"}).status_code == 404)
demo_action = clinic.get("/api/dashboard").json()["actions"][0]["id"]
check("a clinic cannot close another clinic's action", b.post(f"/api/actions/{demo_action}/done").status_code == 404)
demo_ward = codes["Therapy ward"]
check("a clinic cannot edit another clinic's department",
      b.post("/api/wards/" + demo_ward, json={"name": "Hacked", "active": False}).status_code == 404)
check("login needs the right clinic code", TestClient(app).post("/login", data={"clinic": "demo", "password": "secondpass1"}).status_code == 401)
b.post("/api/wards/" + wcode, json={"name": "Cardiology", "active": False})
check("removed department disappears from forms", anon.get("/r/" + wcode).status_code == 404 and
      anon.post("/api/report", json={"source": "patient", "ward_code": wcode, "text": "Yana bir xabar matni",
                                     "lang": "uz", "agree": True, "terms_version": TV}).status_code == 400)
check("its past report is kept", b.get("/api/dashboard").json()["kpi"]["reports"] == 1)
pv = anon.get("/privacy?c=second").text
check("terms show the clinic's name and contact", "Second Clinic" in pv and "room 5" in pv)
check("old /staff link still works", anon.get("/staff", follow_redirects=False).headers["location"] == "/c/demo/staff")

# ---- PDF nuances: who is speaking, help NOW, privacy check, serious / bribery pointers, no ranking ------
tw = codes["Therapy ward"]
pv = anon.post("/api/preview", json={"text": "Единственный анестезиолог ошибся, пациенту 78 лет"}).json()
check("privacy check flags unique roles and ages", any("Единственный" in f for f in pv["flags"]) and any("78" in f for f in pv["flags"]))
r = anon.post("/api/report", json={"source": "patient", "ward_code": tw, "text": "Otam nafas ololmayapti, hech kim kelmayapti",
                                   "lang": "uz", "reporter": "relative", "urgent": True, "agree": True, "terms_version": TV}).json()
check("help NOW report is urgent", r["urgent"] is True)
with db() as conn:
    row = conn.execute("SELECT reporter, urgent FROM reports WHERE case_hash=?", (hash_code(r["case_code"]),)).fetchone()
check("relative stored as reporter type", row and row["reporter"] == "relative" and row["urgent"] == 1)
r = anon.post("/api/report", json={"source": "patient", "ward_code": tw, "text": "Palata uchun pul so'rashdi, pora berdik",
                                   "lang": "uz", "agree": True, "terms_version": TV}).json()
check("bribery mention flagged for the 1203 pointer", r["bribery"] is True)
r = anon.post("/api/report", json={"source": "staff", "ward_code": tw, "text": "Wrong patient got an overdose, bleeding followed",
                                   "lang": "en", "reporter": "staff", "agree": True, "terms_version": TV}).json()
check("serious harm flagged for the official-channel reminder", r["serious"] is True)
check("bad reporter type refused", anon.post("/api/report", json={"source": "patient", "ward_code": tw, "text": "matn matn matn",
      "lang": "uz", "reporter": "doctor", "agree": True, "terms_version": TV}).status_code == 422)
dd = clinic.get("/api/dashboard").json()
check("headline metric is problems fixed", "fixed" in dd["kpi"])
check("wards are listed A-Z, not ranked", [h["label"].lower() for h in dd["heat"]] == sorted(h["label"].lower() for h in dd["heat"]))

# ---- plans: trial, Start limits, reports never blocked ----------------------------------------
from app import plans  # noqa: E402
from app.db import db as _db  # noqa: E402
with _db() as conn:
    sid = conn.execute("SELECT id FROM clinics WHERE slug='second'").fetchone()[0]
    check("demo clinic is on Network", plans.for_clinic(conn, 1)["key"] == "network" or
          plans.for_clinic(conn, conn.execute("SELECT id FROM clinics WHERE slug='demo'").fetchone()[0])["key"] == "network")
    p = plans.for_clinic(conn, sid)
    check("a new clinic starts on the Klinika trial", p["key"] == "klinika" and p["trial"] and p["days_left"] == 60)
    conn.execute("UPDATE clinics SET trial_until='2000-01-01' WHERE id=?", (sid,))  # trial over -> Start
sc = TestClient(app)
sc.post("/login", data={"clinic": "second", "password": "secondpass1"})
sd = sc.get("/api/dashboard").json()
check("Start: analysis is not sent, urgent and latest reports are",
      sd["plan"]["key"] == "start" and sd["clusters"] == [] and sd["radar"] == [] and sd["kpi"]["linked_clusters"] is None
      and "urgent" in sd and "feed" in sd)
check("Start: root-cause help and actions are refused",
      sc.post("/api/clusters/rca", json={"key": "x|y"}).status_code == 403
      and sc.post("/api/actions", json={"theme": "other", "title": "Fix it"}).status_code == 403)
added = [sc.post("/api/wards", json={"name": f"Dept {i}"}).status_code for i in range(5)]
with _db() as conn:
    used = plans.active_departments(conn, sid)
check("Start: no more than 3 active departments can be added", used == 3 and added[-1] == 403)
sw = [w for w in sc.get("/api/settings").json()["wards"] if w["active"]][0]["code"]
import app.main as _main  # noqa: E402
_main._RATE.clear()  # earlier checks used up this test connection's report allowance
check("Start: reports still go through and are stored",
      TestClient(app).post("/api/report", json={"source": "patient", "ward_code": sw, "text": "Navbat juda uzun edi", "lang": "uz",
                                     "agree": True, "terms_version": TV}).status_code == 200)
with _db() as conn:
    plans.set_plan(conn, sid, "klinika", "2099-12-31")
check("paid Klinika plan brings the analysis back", sc.get("/api/dashboard").json()["plan"]["insights"] is True)

import re as _re  # noqa: E402
_emo = _re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\u2300-\u23FF\uFE0F]")
pages = [anon.get(u).text for u in ("/", "/c/demo", "/c/demo/staff", "/r/" + codes["Therapy ward"], "/case", "/privacy?c=demo")]
pages.append(anon.get("/static/i18n.js").text)
check("web pages and interface text contain no emojis", not any(_emo.search(x) for x in pages))

# Staff reports: without an AI model the summary is only a standard sentence, so managers see the checked text instead
from app import main as _m  # noqa: E402
_m._RATE.clear()  # earlier checks used up this test connection's report limit
sr = anon.post("/api/report", json={"source": "staff", "ward_code": codes["Therapy ward"], "lang": "uz", "agree": True,
               "terms_version": TV, "text": "Kechasi kislorod balloni bo'sh qoldi, ertalab sezdik"})
staff_feed = [f for f in clinic.get("/api/dashboard").json()["feed"] if f["source"] == "staff"]
check("staff report shows its own (masked) words when no AI summary exists",
      sr.status_code == 200 and any("kislorod balloni" in f["text"] for f in staff_feed))
import datetime as _dt  # noqa: E402
check("staff report still shows the week only, not the day",
      all(f["week"] and _dt.date.fromisoformat(f["day"]).weekday() == 0 for f in staff_feed))

# QR codes must scale, not be cropped: a fixed width/height gets cut off by the page's CSS and stops scanning
qr_page = clinic.get("/qr").text
check("QR codes scale to the page (viewBox, no fixed size)",
      'viewBox="0 0 ' in qr_page and not re.search(r'<svg[^>]*class="segno"[^>]*width=|<svg[^>]*width="\d+"[^>]*class="segno"', qr_page))

# attempt limits forget expired connections, so the in-memory store cannot grow without end
import time as _time  # noqa: E402
from app import main as _main  # noqa: E402
_old = _time.time() - 2 * _main._RATE_MAX_WINDOW
for _i in range(10_001):
    _main._RATE[f"old{_i}"].append(_old)
anon.post("/api/preview", json={"text": "hello"})
check("expired attempt records are cleared", len(_main._RATE) < 100)

# ---- Claude needs Python 3.10+ and the anthropic SDK: never claim "Claude is on" when it can't run ----------
_saved_key = ai.config.ANTHROPIC_API_KEY
ai.config.ANTHROPIC_API_KEY = "test-key-not-real"
ai._CLAUDE_CHECK["ok"] = None
expected = "claude" if (sys.version_info >= (3, 10) and __import__("importlib.util").util.find_spec("anthropic")) else None
check("Claude reported on only when it can actually run", ai.llm_provider() == expected)
ai.config.ANTHROPIC_API_KEY = _saved_key
ai._CLAUDE_CHECK["ok"] = None

import pathlib  # noqa: E402
# ---- an AI key pasted into .env while running takes effect without a restart --------------------------
import tempfile as _tf, time as _time  # noqa: E402,E401
from app import config as _cfg  # noqa: E402
_can_claude = sys.version_info >= (3, 10) and __import__("importlib.util").util.find_spec("anthropic") is not None
_saved = (_cfg.DOTENV_PATH, set(_cfg._EXTERNAL), _cfg.ANTHROPIC_API_KEY, _cfg.CLAUDE_MODEL, dict(_cfg._DOTENV_SEEN))
_envfile = pathlib.Path(_tf.mkdtemp()) / ".env"
_envfile.write_text("CLINIC_PASSWORD=x\nANTHROPIC_API_KEY=\n")
_cfg.DOTENV_PATH = _envfile
_cfg._EXTERNAL.discard("ANTHROPIC_API_KEY"); _cfg._EXTERNAL.discard("CLAUDE_MODEL")
_cfg.ANTHROPIC_API_KEY = ""; _cfg._DOTENV_SEEN["mtime"] = None
ai._CLAUDE_CHECK["ok"] = None
check("no key in .env: keyword rules", ai.llm_provider() is None)
_time.sleep(0.02)
_envfile.write_text("CLINIC_PASSWORD=x\nANTHROPIC_API_KEY=test-key-not-real\nCLAUDE_MODEL=claude-sonnet-5-5\n")
import os as _os; _os.utime(_envfile, (_time.time() + 5, _time.time() + 5))
check("key pasted into .env while running: Claude on, no restart",
      ai.llm_provider() == ("claude" if _can_claude else None) and _cfg.ANTHROPIC_API_KEY == "test-key-not-real")
_envfile.write_text("CLINIC_PASSWORD=x\nANTHROPIC_API_KEY=\n")
_os.utime(_envfile, (_time.time() + 10, _time.time() + 10))
check("key removed from .env: back to keyword rules", ai.llm_provider() is None)
_cfg._EXTERNAL.add("ANTHROPIC_API_KEY")
_envfile.write_text("ANTHROPIC_API_KEY=from-file\n"); _os.utime(_envfile, (_time.time() + 15, _time.time() + 15))
ai.llm_provider()
check("a key set outside .env is never overridden by the file", _cfg.ANTHROPIC_API_KEY == "")
_cfg.DOTENV_PATH, _cfg._EXTERNAL, _cfg.ANTHROPIC_API_KEY, _cfg.CLAUDE_MODEL = _saved[0], _saved[1], _saved[2], _saved[3]
_cfg._DOTENV_SEEN.clear(); _cfg._DOTENV_SEEN.update(_saved[4]); ai._CLAUDE_CHECK["ok"] = None; ai._CLAUDE["client"] = None

sys.exit(1 if check.failed else 0)
