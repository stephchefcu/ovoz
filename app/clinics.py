"""Clinics and their departments. Every clinic sees and manages only its own data."""
import re
import secrets
from datetime import date
from typing import Optional

from .util import hash_password, verify_password

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,28}[a-z0-9]$")
_TRANSLIT = str.maketrans({"'": "", "ʻ": "", "ʼ": "", "‘": "", "’": "", "`": ""})
_CYR = dict(zip("абвгдеёжзийклмнопрстуфхцчшщъыьэюяўқғҳ",
                ["a", "b", "v", "g", "d", "e", "yo", "zh", "z", "i", "y", "k", "l", "m", "n", "o", "p", "r", "s", "t",
                 "u", "f", "kh", "ts", "ch", "sh", "sh", "", "y", "", "e", "yu", "ya", "o", "q", "g", "h"]))


def slugify(name: str) -> str:
    """A clinic code from its name: lowercase latin letters, digits and dashes."""
    s = "".join(_CYR.get(c, c) for c in name.lower().translate(_TRANSLIT))
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:30].strip("-")
    return s if len(s) >= 3 else (s + "-clinic").strip("-")


def valid_slug(slug: str) -> bool:
    return bool(SLUG_RE.match(slug or ""))


def get(conn, clinic_id: int) -> Optional[dict]:
    r = conn.execute("SELECT id, slug, name, contact, created_day FROM clinics WHERE id=?", (clinic_id,)).fetchone()
    return dict(r) if r else None


def by_slug(conn, slug: str) -> Optional[dict]:
    r = conn.execute("SELECT id, slug, name, contact, created_day FROM clinics WHERE slug=?",
                     ((slug or "").strip().lower(),)).fetchone()
    return dict(r) if r else None


def slug_taken(conn, slug: str) -> bool:
    return conn.execute("SELECT 1 FROM clinics WHERE slug=?", (slug,)).fetchone() is not None


def create(conn, name: str, slug: str, password: str, contact: str = "") -> int:
    """A new clinic starts with the free Klinika trial (see plans.py)."""
    from .plans import trial_end  # local import: plans imports pricing only
    return conn.execute(
        "INSERT INTO clinics (slug, name, contact, password_hash, created_day, trial_until) VALUES (?,?,?,?,?,?)",
        (slug, name.strip(), contact.strip() or None, hash_password(password), date.today().isoformat(),
         trial_end())).lastrowid


def check_login(conn, slug: str, password: str) -> Optional[dict]:
    r = conn.execute("SELECT id, password_hash FROM clinics WHERE slug=?", ((slug or "").strip().lower(),)).fetchone()
    if r and verify_password(password, r["password_hash"]):
        return get(conn, r["id"])
    return None


def update(conn, clinic_id: int, name: str, contact: str):
    conn.execute("UPDATE clinics SET name=?, contact=? WHERE id=?", (name.strip(), contact.strip() or None, clinic_id))


def set_password(conn, clinic_id: int, password: str):
    conn.execute("UPDATE clinics SET password_hash=? WHERE id=?", (hash_password(password), clinic_id))


def password_ok(conn, clinic_id: int, password: str) -> bool:
    r = conn.execute("SELECT password_hash FROM clinics WHERE id=?", (clinic_id,)).fetchone()
    return bool(r) and verify_password(password, r["password_hash"])


# ---- departments ---------------------------------------------------------------------------
def wards(conn, clinic_id: int, include_inactive: bool = False) -> list:
    sql = ("SELECT w.code, w.name, w.name_uz, w.name_ru, w.unit, w.active, "
           "(SELECT COUNT(*) FROM reports r WHERE r.ward_code=w.code) AS reports "
           "FROM wards w WHERE w.clinic_id=?" + ("" if include_inactive else " AND w.active=1") +
           " ORDER BY w.active DESC, w.unit, w.name")
    return [dict(r) for r in conn.execute(sql, (clinic_id,))]


def add_ward(conn, clinic_id: int, name: str, name_uz: str = "", name_ru: str = "", unit: str = "") -> str:
    code = secrets.token_urlsafe(6)  # random, so a ward link cannot be guessed from its name
    conn.execute("INSERT INTO wards (code, name, name_uz, name_ru, unit, clinic_id, active) VALUES (?,?,?,?,?,?,1)",
                 (code, name.strip(), name_uz.strip() or None, name_ru.strip() or None,
                  (unit or name).strip(), clinic_id))
    return code


def update_ward(conn, clinic_id: int, code: str, name: str, name_uz: str, name_ru: str, unit: str,
                active: bool) -> bool:
    cur = conn.execute(
        "UPDATE wards SET name=?, name_uz=?, name_ru=?, unit=?, active=? WHERE code=? AND clinic_id=?",
        (name.strip(), name_uz.strip() or None, name_ru.strip() or None, (unit or name).strip(), int(active),
         code, clinic_id))
    return cur.rowcount == 1
