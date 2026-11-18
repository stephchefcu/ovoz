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
check("login works", clinic.post("/login", data={"password": "demo"}, follow_redirects=False).status_code == 303)
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
check("wrong password rejected", anon.post("/login", data={"password": "nope"}).status_code == 401)

sys.exit(1 if check.failed else 0)
