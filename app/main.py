import hashlib
import hmac
import io
import secrets
import time
from collections import defaultdict, deque
from datetime import date
from pathlib import Path
from typing import Optional

import httpx
import segno
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from . import ai, analytics, clinics, config, reports, terms, voice
from .db import db, init_db

APP_DIR = Path(__file__).resolve().parent
app = FastAPI(title="Ovoz")
app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")
templates = Jinja2Templates(directory=str(APP_DIR / "templates"))
templates.env.globals["TERMS_VERSION"] = terms.TERMS_VERSION
templates.env.globals["V"] = str(int(time.time()))  # cache-buster: browsers reload CSS/JS after a restart

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


# Clinic login sessions: a fresh random token per login -> (clinic id, expiry), kept in memory only.
# Logging out (or restarting the server) ends the session. Run a single worker process.
SESSION_TTL = 60 * 60 * 12
_SESSIONS: dict = {}


def _new_session(clinic_id: int) -> str:
    now = time.time()
    for tok, (_, exp) in list(_SESSIONS.items()):
        if exp < now:
            _SESSIONS.pop(tok, None)
    tok = secrets.token_urlsafe(32)
    _SESSIONS[tok] = (clinic_id, now + SESSION_TTL)
    return tok


def _login_response(clinic_id: int, to: str):
    resp = RedirectResponse(to, status_code=303)
    resp.set_cookie("clinic_session", _new_session(clinic_id), httponly=True, samesite="strict", max_age=SESSION_TTL)
    return resp


def current_clinic(request: Request) -> Optional[int]:
    """The logged-in clinic's id, or None."""
    got = request.cookies.get("clinic_session", "")
    entry = _SESSIONS.get(got) if got else None
    if entry is None:
        return None
    if entry[1] < time.time():
        _SESSIONS.pop(got, None)
        return None
    return entry[0]


def require_clinic(request: Request) -> int:
    cid = current_clinic(request)
    if cid is None:
        raise HTTPException(status_code=401, detail="login required")
    return cid


_BOT = {"name": None, "checked": 0.0}


def bot_username() -> Optional[str]:
    """The Telegram bot's username, for t.me deep links (from .env, or asked from Telegram once)."""
    if config.TELEGRAM_BOT_USERNAME:
        return config.TELEGRAM_BOT_USERNAME
    if not config.TELEGRAM_BOT_TOKEN or _BOT["name"] or time.time() - _BOT["checked"] < 300:
        return _BOT["name"]
    _BOT["checked"] = time.time()
    try:
        r = httpx.get(f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/getMe", timeout=5)
        _BOT["name"] = r.json()["result"]["username"]
    except Exception:
        pass
    return _BOT["name"]


def tg_link(payload: str) -> Optional[str]:
    name = bot_username()
    return f"https://t.me/{name}?start={payload}" if name else None


def qr_svg(url: str, scale: int = 6) -> str:
    buf = io.BytesIO()
    segno.make(url, error="m").save(buf, kind="svg", scale=scale, border=2, xmldecl=False, svgns=True)
    return buf.getvalue().decode()


def _clinic_or_404(conn, slug: str) -> dict:
    c = clinics.by_slug(conn, slug)
    if not c:
        raise HTTPException(404, "unknown clinic")
    return c


# --------------------------------------------------------------------------------------
# Public pages
# --------------------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    with db() as conn:
        demo = clinics.by_slug(conn, "demo")
    return templates.TemplateResponse(request, "home.html", {
        "demo": demo, "is_clinic": current_clinic(request) is not None, "bot": bot_username()})


@app.get("/c/{slug}", response_class=HTMLResponse)
def clinic_page(request: Request, slug: str):
    """A clinic's public start page: its departments, the staff form and the Telegram bot."""
    with db() as conn:
        c = _clinic_or_404(conn, slug)
        wards = reports.ward_list(conn, c["id"])
    return templates.TemplateResponse(request, "clinic.html", {
        "clinic": c, "wards": wards, "tg": tg_link("c_" + c["slug"]),
        "is_clinic": current_clinic(request) == c["id"]})


@app.get("/r/{ward_code}", response_class=HTMLResponse)
def patient_page(request: Request, ward_code: str):
    with db() as conn:
        w = reports.get_ward(conn, ward_code)
        if not w:
            raise HTTPException(404, "unknown ward code")
        c = clinics.get(conn, w["clinic_id"])
    return templates.TemplateResponse(request, "patient.html",
                                      {"ward": w, "clinic": c, "tg": tg_link("w_" + w["code"])})


@app.get("/c/{slug}/staff", response_class=HTMLResponse)
def staff_page(request: Request, slug: str):
    with db() as conn:
        c = _clinic_or_404(conn, slug)
        wards = reports.ward_list(conn, c["id"])
    return templates.TemplateResponse(request, "staff.html", {"wards": wards, "clinic": c,
                                                              "tg": tg_link("s_" + c["slug"])})


@app.get("/staff")
def staff_redirect():
    """Old link: staff forms now belong to a clinic."""
    return RedirectResponse("/c/demo/staff", status_code=303)


@app.get("/privacy", response_class=HTMLResponse)
def privacy_page(request: Request, c: str = ""):
    with db() as conn:
        clinic = clinics.by_slug(conn, c) if c else None
    return templates.TemplateResponse(request, "privacy.html", {
        "clinic": clinic, "texts": [terms.terms(lang, clinic) for lang in ("uz", "ru", "en")]})


@app.get("/case", response_class=HTMLResponse)
def case_page(request: Request):
    return templates.TemplateResponse(request, "case.html", {})


@app.get("/board/{ward_code}", response_class=HTMLResponse)
def board_page(request: Request, ward_code: str):
    with db() as conn:
        w = reports.get_ward(conn, ward_code)
        if not w:
            raise HTTPException(404, "unknown ward code")
        rows = conn.execute(
            "SELECT * FROM actions WHERE clinic_id=? AND status='done' AND (scope_unit=? OR scope_unit='All') "
            "ORDER BY done_day DESC, id DESC LIMIT 12",
            (w["clinic_id"], w["unit"]),
        ).fetchall()
    return templates.TemplateResponse(request, "board.html", {"ward": w, "actions": [dict(r) for r in rows]})


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
    agree: bool = False          # the person ticked "I agree" after seeing exactly what is sent
    terms_version: str = ""      # the Terms & Privacy version they saw
    reporter: str = Field(default="", pattern="^(|patient|relative|staff)$")
    urgent: bool = False         # "Someone needs help NOW" was pressed


def require_agreement(agree: bool, version: str):
    if not agree:
        raise HTTPException(400, "terms_not_accepted")
    if version != terms.TERMS_VERSION:  # the page is out of date: they must see the current terms
        raise HTTPException(409, "terms_changed")


class PreviewIn(BaseModel):
    text: str = Field(min_length=1, max_length=3000)


@app.post("/api/preview")
def preview(body: PreviewIn, request: Request):
    """Exactly what would be stored: the masked text, the date and the part of the day. Nothing is saved."""
    if rate_limited(request, "preview", limit=60):
        raise HTTPException(429, "too many requests")
    now = analytics.local_now()
    masked = ai.mask_text(body.text)
    return {"masked": masked, "date": now.date().isoformat(), "time_bucket": analytics.time_bucket(now),
            "flags": ai.privacy_flags(masked), "terms_version": terms.TERMS_VERSION}


@app.post("/api/report")
def create_report(body: ReportIn, request: Request):
    require_agreement(body.agree, body.terms_version)
    if rate_limited(request, "report"):
        raise HTTPException(429, "too many reports from this connection, try again later")
    with db() as conn:
        if not reports.ward_exists(conn, body.ward_code):
            raise HTTPException(400, "unknown ward")
        return reports.save_report(conn, body.source, body.ward_code, body.text, body.lang,
                                   body.rating, body.harm, body.near_miss, terms_version=body.terms_version,
                                   reporter=body.reporter or None, urgent=body.urgent)


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
    agree: bool = False
    terms_version: str = ""


@app.post("/api/case/open")
def case_open(body: CaseOpen, request: Request):
    if rate_limited(request, "case", limit=15):
        raise HTTPException(429, "too many attempts")
    with db() as conn:
        msgs = reports.case_messages(conn, body.code)
    if msgs is None:
        raise HTTPException(404, "code not found")
    return {"messages": msgs}


@app.post("/api/case/reply")
def case_reply(body: CaseReply, request: Request):
    require_agreement(body.agree, body.terms_version)
    if rate_limited(request, "case", limit=15):
        raise HTTPException(429, "too many attempts")
    with db() as conn:
        if not reports.add_reporter_reply(conn, body.code, body.body):
            raise HTTPException(404, "code not found")
    return {"ok": True}


# --------------------------------------------------------------------------------------
# Clinic sign-up, login, settings
# --------------------------------------------------------------------------------------
@app.get("/signup", response_class=HTMLResponse)
def signup_page(request: Request):
    return templates.TemplateResponse(request, "signup.html", {"error": "", "form": {},
                                                               "need_code": bool(config.SIGNUP_CODE)})


@app.post("/signup")
def signup(request: Request, name: str = Form(...), slug: str = Form(""), contact: str = Form(""),
           password: str = Form(...), password2: str = Form(...), signup_code: str = Form("")):
    form = {"name": name, "slug": slug, "contact": contact}

    def fail(msg):
        return templates.TemplateResponse(request, "signup.html", {"error": msg, "form": form,
                                                                   "need_code": bool(config.SIGNUP_CODE)},
                                          status_code=400)

    if rate_limited(request, "signup", limit=5, window=3600):
        return fail("Too many sign-ups from this connection. Try again later.")
    if config.SIGNUP_CODE and not hmac.compare_digest(signup_code.strip(), config.SIGNUP_CODE):
        return fail("Wrong sign-up code.")
    name = name.strip()
    slug = (slug.strip().lower() or clinics.slugify(name))
    if len(name) < 3:
        return fail("Please enter the clinic's name.")
    if not clinics.valid_slug(slug):
        return fail("The clinic code may use only latin letters, digits and dashes (3 to 30 characters).")
    if len(password) < 8:
        return fail("The password must be at least 8 characters.")
    if password != password2:
        return fail("The two passwords are different.")
    with db() as conn:
        if clinics.slug_taken(conn, slug):
            form["slug"] = slug
            return fail(f"The clinic code “{slug}” is taken. Please choose another one.")
        cid = clinics.create(conn, name, slug, password, contact)
    return _login_response(cid, "/settings?new=1")


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, c: str = ""):
    return templates.TemplateResponse(request, "login.html", {"error": False, "slug": c})


@app.post("/login")
def login(request: Request, clinic: str = Form(""), password: str = Form(...)):
    if rate_limited(request, "login", limit=10):
        return templates.TemplateResponse(request, "login.html", {"error": True, "slug": clinic}, status_code=429)
    with db() as conn:
        c = clinics.check_login(conn, clinic, password)
    if not c:
        return templates.TemplateResponse(request, "login.html", {"error": True, "slug": clinic}, status_code=401)
    return _login_response(c["id"], "/dashboard")


@app.get("/logout")
def logout(request: Request):
    _SESSIONS.pop(request.cookies.get("clinic_session", ""), None)
    resp = RedirectResponse("/", status_code=303)
    resp.delete_cookie("clinic_session")
    return resp


@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, new: int = 0):
    cid = current_clinic(request)
    if cid is None:
        return RedirectResponse("/login", status_code=303)
    with db() as conn:
        c = clinics.get(conn, cid)
    return templates.TemplateResponse(request, "settings.html", {"clinic": c, "new": bool(new),
                                                                 "base": str(request.base_url).rstrip("/")})


@app.get("/api/settings")
def api_settings(request: Request):
    cid = require_clinic(request)
    with db() as conn:
        return {"clinic": clinics.get(conn, cid), "wards": clinics.wards(conn, cid, include_inactive=True),
                "bot": bot_username()}


class ClinicIn(BaseModel):
    name: str = Field(min_length=3, max_length=120)
    contact: str = Field(default="", max_length=200)


@app.post("/api/settings/clinic")
def api_settings_clinic(body: ClinicIn, request: Request):
    cid = require_clinic(request)
    with db() as conn:
        clinics.update(conn, cid, body.name, body.contact)
    return {"ok": True}


class PasswordIn(BaseModel):
    current: str
    new: str = Field(min_length=8, max_length=200)


@app.post("/api/settings/password")
def api_settings_password(body: PasswordIn, request: Request):
    cid = require_clinic(request)
    with db() as conn:
        if not clinics.password_ok(conn, cid, body.current):
            raise HTTPException(400, "wrong current password")
        clinics.set_password(conn, cid, body.new)
    return {"ok": True}


class WardIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)        # English / default name (dashboard)
    name_uz: str = Field(default="", max_length=80)
    name_ru: str = Field(default="", max_length=80)
    unit: str = Field(default="", max_length=80)           # department group used for privacy roll-up
    active: bool = True


@app.post("/api/wards")
def api_ward_add(body: WardIn, request: Request):
    cid = require_clinic(request)
    with db() as conn:
        return {"code": clinics.add_ward(conn, cid, body.name, body.name_uz, body.name_ru, body.unit)}


@app.post("/api/wards/{code}")
def api_ward_update(code: str, body: WardIn, request: Request):
    cid = require_clinic(request)
    with db() as conn:
        if not clinics.update_ward(conn, cid, code, body.name, body.name_uz, body.name_ru, body.unit, body.active):
            raise HTTPException(404, "department not found")
    return {"ok": True}


# --------------------------------------------------------------------------------------
# Clinic dashboard (every query is limited to the logged-in clinic)
# --------------------------------------------------------------------------------------
@app.get("/dashboard", response_class=HTMLResponse)
def dashboard_page(request: Request):
    cid = current_clinic(request)
    if cid is None:
        return RedirectResponse("/login", status_code=303)
    with db() as conn:
        c = clinics.get(conn, cid)
    return templates.TemplateResponse(request, "dashboard.html", {"clinic": c})


@app.get("/api/dashboard")
def api_dashboard(request: Request):
    cid = require_clinic(request)
    with db() as conn:
        return analytics.build_dashboard(conn, cid)


class RcaIn(BaseModel):
    key: str


@app.post("/api/clusters/rca")
def api_rca(body: RcaIn, request: Request):
    cid = require_clinic(request)
    with db() as conn:
        label, unit, theme, patients, staff = analytics.cluster_inputs(conn, cid, body.key)
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
    cid = require_clinic(request)
    with db() as conn:
        conn.execute(
            "INSERT INTO actions (theme, scope_unit, title, cause, owner, due, public_text, status, created_day, "
            "clinic_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (body.theme, body.unit or "All", body.title, body.cause, body.owner, body.due,
             body.public_text or body.title, "open", date.today().isoformat(), cid),
        )
    return {"ok": True}


@app.post("/api/actions/{action_id}/done")
def api_action_done(action_id: int, request: Request):
    cid = require_clinic(request)
    with db() as conn:
        cur = conn.execute("UPDATE actions SET status='done', done_day=? WHERE id=? AND clinic_id=?",
                           (date.today().isoformat(), action_id, cid))
    if cur.rowcount != 1:
        raise HTTPException(404, "action not found")
    return {"ok": True}


class AskIn(BaseModel):
    report_id: int
    body: str = Field(min_length=1, max_length=2000)


@app.post("/api/clinic/ask")
def api_clinic_ask(body: AskIn, request: Request):
    """Post a follow-up question on a report. The reporter sees it by opening their case code."""
    cid = require_clinic(request)
    with db() as conn:
        r = conn.execute("SELECT case_hash FROM reports WHERE id=? AND clinic_id=?", (body.report_id, cid)).fetchone()
        if not r:
            raise HTTPException(404, "report not found")
        conn.execute("INSERT INTO case_messages (case_hash, sender, body, created_day) VALUES (?,?,?,?)",
                     (r["case_hash"], "clinic", body.body, date.today().isoformat()))
    return {"ok": True}


@app.get("/qr", response_class=HTMLResponse)
def qr_sheet(request: Request):
    """Printable sheet: one QR code per WARD (not per room, so a report cannot point to one patient),
    plus a Telegram QR per ward and the staff links."""
    cid = current_clinic(request)
    if cid is None:
        return RedirectResponse("/login", status_code=303)
    base = str(request.base_url).rstrip("/")
    with db() as conn:
        c = clinics.get(conn, cid)
        wards = reports.ward_list(conn, cid)
    for w in wards:
        w["url"] = f"{base}/r/{w['code']}"
        w["svg"] = qr_svg(w["url"])
        tg = tg_link("w_" + w["code"])
        w["tg_svg"] = qr_svg(tg, scale=3) if tg else None
    staff_url = f"{base}/c/{c['slug']}/staff"
    staff_tg = tg_link("s_" + c["slug"])  # opens the bot straight in the staff form
    return templates.TemplateResponse(request, "qrsheet.html", {
        "wards": wards, "clinic": c, "staff_url": staff_url, "staff_svg": qr_svg(staff_url),
        "staff_tg_svg": qr_svg(staff_tg, scale=3) if staff_tg else None, "bot": bot_username()})


@app.get("/api/health")
def health():
    return {"ok": True, "llm": ai.llm_enabled(), "voice": voice.provider()}
