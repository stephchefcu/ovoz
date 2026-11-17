import hashlib
import hmac
import io
import json
import random
import secrets
import time
from collections import defaultdict, deque
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import segno
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from . import ai, analytics, config, voice
from .db import db, init_db
from .util import hash_code, new_case_code

APP_DIR = Path(__file__).resolve().parent
app = FastAPI(title="Clinic Safety & Feedback Platform")
app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")
templates = Jinja2Templates(directory=str(APP_DIR / "templates"))

init_db()

if config.SECRET in ("", "change-me", "change-me-to-a-long-random-string"):
    print("WARNING: SESSION_SECRET is the default. Set a long random value in .env "
          "(it protects stored case codes). Do not change it once real reports exist.")

# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------
# In-memory only (never persisted, so no IP address is ever stored)
_RATE = defaultdict(deque)


def rate_limited(request: Request, bucket: str, limit: int = 6, window: int = 600) -> bool:
    ip = request.client.host if request.client else "x"
    key = hashlib.sha256((ip + bucket).encode()).hexdigest()
    now = time.time()
    q = _RATE[key]
    while q and now - q[0] > window:
        q.popleft()
    if len(q) >= limit:
        return True
    q.append(now)
    return False


# Clinic login sessions: a fresh random token per login, kept in memory only.
# Logging out (or restarting the server) ends the session. Run a single worker process.
SESSION_TTL = 60 * 60 * 12
_SESSIONS: dict = {}


def _new_session() -> str:
    now = time.time()
    for tok, exp in list(_SESSIONS.items()):
        if exp < now:
            _SESSIONS.pop(tok, None)
    tok = secrets.token_urlsafe(32)
    _SESSIONS[tok] = now + SESSION_TTL
    return tok


def is_clinic(request: Request) -> bool:
    got = request.cookies.get("clinic_session", "")
    exp = _SESSIONS.get(got) if got else None
    if exp is None:
        return False
    if exp < time.time():
        _SESSIONS.pop(got, None)
        return False
    return True


def require_clinic(request: Request):
    if not is_clinic(request):
        raise HTTPException(status_code=401, detail="login required")


def ward_list(conn):
    return [dict(r) for r in conn.execute("SELECT code, name, unit FROM wards ORDER BY unit, name")]


# --------------------------------------------------------------------------------------
# Public pages
# --------------------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    with db() as conn:
        wards = ward_list(conn)
    return templates.TemplateResponse(request, "home.html", {"wards": wards, "is_clinic": is_clinic(request)})


@app.get("/r/{ward_code}", response_class=HTMLResponse)
def patient_page(request: Request, ward_code: str):
    with db() as conn:
        w = conn.execute("SELECT * FROM wards WHERE code=?", (ward_code,)).fetchone()
    if not w:
        raise HTTPException(404, "unknown ward code")
    return templates.TemplateResponse(request, "patient.html", {"ward": dict(w)})


@app.get("/staff", response_class=HTMLResponse)
def staff_page(request: Request):
    with db() as conn:
        wards = ward_list(conn)
    return templates.TemplateResponse(request, "staff.html", {"wards": wards})


@app.get("/case", response_class=HTMLResponse)
def case_page(request: Request):
    return templates.TemplateResponse(request, "case.html", {})


@app.get("/board/{ward_code}", response_class=HTMLResponse)
def board_page(request: Request, ward_code: str):
    with db() as conn:
        w = conn.execute("SELECT * FROM wards WHERE code=?", (ward_code,)).fetchone()
        if not w:
            raise HTTPException(404, "unknown ward code")
        rows = conn.execute(
            "SELECT * FROM actions WHERE status='done' AND (scope_unit=? OR scope_unit='All') "
            "ORDER BY done_day DESC, id DESC LIMIT 12",
            (w["unit"],),
        ).fetchall()
    return templates.TemplateResponse(request, "board.html", {"ward": dict(w), "actions": [dict(r) for r in rows]})


# --------------------------------------------------------------------------------------
# Reporting API (anonymous)
# --------------------------------------------------------------------------------------
class ReportIn(BaseModel):
    source: str = Field(pattern="^(patient|staff)$")
    ward_code: str
    text: str = Field(min_length=5, max_length=3000)
    lang: str = "uz"
    rating: Optional[int] = Field(default=None, ge=1, le=5)
    harm: str = Field(default="none", pattern="^(none|minor|serious)$")
    near_miss: bool = False


@app.post("/api/report")
def create_report(body: ReportIn, request: Request):
    if rate_limited(request, "report"):
        raise HTTPException(429, "too many reports from this connection, try again later")
    with db() as conn:
        if not conn.execute("SELECT 1 FROM wards WHERE code=?", (body.ward_code,)).fetchone():
            raise HTTPException(400, "unknown ward")
        result = ai.analyze(body.text, body.source, body.harm, body.near_miss)
        now = analytics.local_now()
        delay = random.uniform(0, config.STAFF_DELAY_HOURS) * 3600 if body.source == "staff" else 0
        release_at = (datetime.now(timezone.utc) + timedelta(seconds=delay)).strftime("%Y-%m-%dT%H:%M:%S")
        code = new_case_code()
        conn.execute(
            "INSERT INTO reports (source, ward_code, text_masked, summary, category, theme, severity, urgent, "
            "near_miss, rating, lang, created_day, time_bucket, release_at, case_hash) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (body.source, body.ward_code, result["masked"], result["summary"], result["category"], result["theme"],
             result["severity"], int(result["urgent"]), int(result["near_miss"]), body.rating, body.lang,
             now.date().isoformat(), analytics.time_bucket(now), release_at, hash_code(code)),
        )
    return {"case_code": code, "urgent": result["urgent"]}


@app.post("/api/transcribe")
async def transcribe(request: Request, audio: UploadFile = File(...), lang: str = Form("uz")):
    if rate_limited(request, "stt", limit=20):
        raise HTTPException(429, "too many requests")
    data = await audio.read()
    if len(data) > 8 * 1024 * 1024:
        raise HTTPException(413, "audio too large (keep recordings under about 90 seconds)")
    # The speech service call is blocking (up to ~60 s), so run it in a worker thread to keep the server responsive.
    # Audio is discarded inside.
    return await run_in_threadpool(voice.transcribe, data, audio.filename or "audio.webm", lang)


# ---- anonymous follow-up by case code ---------------------------------------------------
class CaseOpen(BaseModel):
    code: str


class CaseReply(BaseModel):
    code: str
    body: str = Field(min_length=1, max_length=2000)


def _find_case(conn, code):
    h = hash_code(code)
    exists = conn.execute("SELECT 1 FROM reports WHERE case_hash=?", (h,)).fetchone()
    return h if exists else None


@app.post("/api/case/open")
def case_open(body: CaseOpen, request: Request):
    if rate_limited(request, "case", limit=15):
        raise HTTPException(429, "too many attempts")
    with db() as conn:
        h = _find_case(conn, body.code)
        if not h:
            raise HTTPException(404, "code not found")
        msgs = [dict(r) for r in conn.execute(
            "SELECT sender, body, created_day FROM case_messages WHERE case_hash=? ORDER BY id", (h,))]
    return {"messages": msgs}


@app.post("/api/case/reply")
def case_reply(body: CaseReply, request: Request):
    if rate_limited(request, "case", limit=15):
        raise HTTPException(429, "too many attempts")
    with db() as conn:
        h = _find_case(conn, body.code)
        if not h:
            raise HTTPException(404, "code not found")
        # the reporter's reply is masked too, in case they type names or numbers
        conn.execute("INSERT INTO case_messages (case_hash, sender, body, created_day) VALUES (?,?,?,?)",
                     (h, "reporter", ai.mask_text(body.body), date.today().isoformat()))
    return {"ok": True}


# --------------------------------------------------------------------------------------
# Clinic login + dashboard
# --------------------------------------------------------------------------------------
@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html", {"error": False})


@app.post("/login")
def login(request: Request, password: str = Form(...)):
    if not hmac.compare_digest(password, config.CLINIC_PASSWORD):
        return templates.TemplateResponse(request, "login.html", {"error": True}, status_code=401)
    resp = RedirectResponse("/dashboard", status_code=303)
    resp.set_cookie("clinic_session", _new_session(), httponly=True, samesite="strict", max_age=SESSION_TTL)
    return resp


@app.get("/logout")
def logout(request: Request):
    _SESSIONS.pop(request.cookies.get("clinic_session", ""), None)
    resp = RedirectResponse("/", status_code=303)
    resp.delete_cookie("clinic_session")
    return resp


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard_page(request: Request):
    if not is_clinic(request):
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse(request, "dashboard.html", {})


@app.get("/api/dashboard")
def api_dashboard(request: Request):
    require_clinic(request)
    with db() as conn:
        return analytics.build_dashboard(conn)


class RcaIn(BaseModel):
    key: str


@app.post("/api/clusters/rca")
def api_rca(body: RcaIn, request: Request):
    require_clinic(request)
    with db() as conn:
        label, unit, theme, patients, staff = analytics.cluster_inputs(conn, body.key)
    result = ai.rca(theme, label, patients, staff)
    result.update({"label": label, "unit": unit, "theme": theme, "theme_name": ai.THEMES.get(theme, theme)})
    return result


class ActionIn(BaseModel):
    theme: str
    unit: str = "All"
    title: str = Field(min_length=3, max_length=200)
    cause: str = ""
    owner: str = ""
    due: str = ""
    public_text: str = ""


@app.post("/api/actions")
def api_action_create(body: ActionIn, request: Request):
    require_clinic(request)
    with db() as conn:
        conn.execute(
            "INSERT INTO actions (theme, scope_unit, title, cause, owner, due, public_text, status, created_day) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (body.theme, body.unit or "All", body.title, body.cause, body.owner, body.due,
             body.public_text or body.title, "open", date.today().isoformat()),
        )
    return {"ok": True}


@app.post("/api/actions/{action_id}/done")
def api_action_done(action_id: int, request: Request):
    require_clinic(request)
    with db() as conn:
        conn.execute("UPDATE actions SET status='done', done_day=? WHERE id=?",
                     (date.today().isoformat(), action_id))
    return {"ok": True}


class AskIn(BaseModel):
    report_id: int
    body: str = Field(min_length=1, max_length=2000)


@app.post("/api/clinic/ask")
def api_clinic_ask(body: AskIn, request: Request):
    """Post a follow-up question on a report. The reporter sees it by opening their case code."""
    require_clinic(request)
    with db() as conn:
        r = conn.execute("SELECT case_hash FROM reports WHERE id=?", (body.report_id,)).fetchone()
        if not r:
            raise HTTPException(404, "report not found")
        conn.execute("INSERT INTO case_messages (case_hash, sender, body, created_day) VALUES (?,?,?,?)",
                     (r["case_hash"], "clinic", body.body, date.today().isoformat()))
    return {"ok": True}


@app.get("/qr", response_class=HTMLResponse)
def qr_sheet(request: Request):
    """Printable sheet: one QR code per WARD (not per room, so a report cannot point to one patient)."""
    if not is_clinic(request):
        return RedirectResponse("/login", status_code=303)
    base = str(request.base_url).rstrip("/")
    with db() as conn:
        wards = ward_list(conn)
    for w in wards:
        url = f"{base}/r/{w['code']}"
        buf = io.BytesIO()
        segno.make(url, error="m").save(buf, kind="svg", scale=6, border=2, xmldecl=False, svgns=True)
        w["svg"] = buf.getvalue().decode()
        w["url"] = url
    return templates.TemplateResponse(request, "qrsheet.html", {"wards": wards})


@app.get("/api/health")
def health():
    return {"ok": True, "llm": ai.llm_enabled(), "voice": bool(config.AISHA_API_KEY)}
