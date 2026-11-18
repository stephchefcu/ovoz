"""Saving reports and the anonymous case thread. Shared by the web pages and the Telegram bot."""
import random
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from . import ai, analytics, config
from .util import hash_code, new_case_code


def ward_list(conn):
    return [dict(r) for r in conn.execute(
        "SELECT code, name, name_uz, name_ru, unit FROM wards ORDER BY unit, name")]


def ward_name(ward: dict, lang: str) -> str:
    """Department name in the reporter's language; English `name` is the fallback."""
    return (ward.get(f"name_{lang}") if lang in ("uz", "ru") else None) or ward["name"]


def get_ward(conn, ward_code: str) -> Optional[dict]:
    r = conn.execute("SELECT code, name, name_uz, name_ru, unit FROM wards WHERE code=?", (ward_code,)).fetchone()
    return dict(r) if r else None


def ward_exists(conn, ward_code: str) -> bool:
    return conn.execute("SELECT 1 FROM wards WHERE code=?", (ward_code,)).fetchone() is not None


def save_report(conn, source: str, ward_code: str, text: str, lang: str, rating: Optional[int] = None,
                harm: str = "none", near_miss: bool = False, terms_version: Optional[str] = None) -> dict:
    """Mask, triage and store one report. Returns {"case_code", "urgent"}. Only masked text is stored.
    terms_version records which Terms & Privacy version the person agreed to before sending."""
    result = ai.analyze(text, source, harm, near_miss)
    now = analytics.local_now()
    delay = random.uniform(0, config.STAFF_DELAY_HOURS) * 3600 if source == "staff" else 0
    release_at = (datetime.now(timezone.utc) + timedelta(seconds=delay)).strftime("%Y-%m-%dT%H:%M:%S")
    code = new_case_code()
    conn.execute(
        "INSERT INTO reports (source, ward_code, text_masked, summary, category, theme, severity, urgent, "
        "near_miss, rating, lang, created_day, time_bucket, release_at, case_hash, terms_version) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (source, ward_code, result["masked"], result["summary"], result["category"], result["theme"],
         result["severity"], int(result["urgent"]), int(result["near_miss"]), rating, lang,
         now.date().isoformat(), analytics.time_bucket(now), release_at, hash_code(code), terms_version),
    )
    return {"case_code": code, "urgent": result["urgent"]}


def find_case(conn, code: str) -> Optional[str]:
    h = hash_code(code)
    return h if conn.execute("SELECT 1 FROM reports WHERE case_hash=?", (h,)).fetchone() else None


def case_messages(conn, code: str) -> Optional[list]:
    """Messages on a case, oldest first, or None if the code is unknown."""
    h = find_case(conn, code)
    if not h:
        return None
    return [dict(r) for r in conn.execute(
        "SELECT sender, body, created_day FROM case_messages WHERE case_hash=? ORDER BY id", (h,))]


def add_reporter_reply(conn, code: str, body: str) -> bool:
    """The reporter's reply is masked too, in case they type names or numbers."""
    h = find_case(conn, code)
    if not h:
        return False
    conn.execute("INSERT INTO case_messages (case_hash, sender, body, created_day) VALUES (?,?,?,?)",
                 (h, "reporter", ai.mask_text(body), date.today().isoformat()))
    return True
