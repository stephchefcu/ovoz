"""Quick end-to-end check of the main flows. Run:  python tests/smoke_test.py   (uses a temporary database)"""
import os
import re
import sys
import tempfile

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
# Ignore the real .env: demo password, no paid speech or LLM calls.
os.environ.update({"CLINIC_PASSWORD": "demo", "SESSION_SECRET": "smoke-test-secret", "VOICELAB_API_KEY": "",
                   "AISHA_API_KEY": "", "LLM_BASE_URL": "", "LLM_API_KEY": "", "LLM_MODEL": "",
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
check("a new clinic can sign up", r.status_code == 303 and r.headers["location"].startswith("/settings"))
check("clinic codes are unique", TestClient(app).post("/signup", data={"name": "Copy", "slug": "second",
      "password": "secondpass1", "password2": "secondpass1"}).status_code == 400)
check("new clinic starts empty", b.get("/api/settings").json()["wards"] == [] and b.get("/api/dashboard").json()["kpi"]["reports"] == 0)
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

import re as _re  # noqa: E402
_emo = _re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\u2300-\u23FF\uFE0F]")
pages = [anon.get(u).text for u in ("/", "/c/demo", "/c/demo/staff", "/r/" + codes["Therapy ward"], "/case", "/privacy?c=demo")]
pages.append(anon.get("/static/i18n.js").text)
check("web pages and interface text contain no emojis", not any(_emo.search(x) for x in pages))

sys.exit(1 if check.failed else 0)
