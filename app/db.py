import sqlite3
from contextlib import contextmanager
from pathlib import Path

from . import config

SCHEMA = """
-- Each clinic has its own login, departments, reports and actions. One Ovoz site and bot serve them all.
CREATE TABLE IF NOT EXISTS clinics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT NOT NULL UNIQUE,      -- public clinic code: login, links, typed in the bot
    name TEXT NOT NULL,
    contact TEXT,                   -- shown in the Terms ("ask ... to delete a report")
    password_hash TEXT NOT NULL,
    created_day TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS wards (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    unit TEXT NOT NULL
);

-- Only masked text is stored. No names, phones, device IDs, IPs, audio or room numbers.
CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL CHECK (source IN ('patient','staff')),
    ward_code TEXT NOT NULL,
    text_masked TEXT NOT NULL,
    summary TEXT NOT NULL,
    category TEXT NOT NULL,
    theme TEXT NOT NULL,
    severity INTEGER NOT NULL,
    urgent INTEGER NOT NULL DEFAULT 0,
    near_miss INTEGER NOT NULL DEFAULT 0,
    rating INTEGER,
    lang TEXT,
    created_day TEXT NOT NULL,      -- date only
    time_bucket TEXT NOT NULL,      -- morning / afternoon / night (coarse)
    release_at TEXT NOT NULL,       -- UTC; staff reports can be held back
    case_hash TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reports_ward ON reports(ward_code);
CREATE INDEX IF NOT EXISTS idx_reports_case ON reports(case_hash);

-- Anonymous two-way thread, keyed by a hash of the reporter's case code.
CREATE TABLE IF NOT EXISTS case_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_hash TEXT NOT NULL,
    sender TEXT NOT NULL CHECK (sender IN ('clinic','reporter')),
    body TEXT NOT NULL,
    created_day TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_msg_case ON case_messages(case_hash);

CREATE TABLE IF NOT EXISTS actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    theme TEXT NOT NULL,
    scope_unit TEXT NOT NULL,       -- unit name, or 'All'
    title TEXT NOT NULL,
    cause TEXT,
    owner TEXT,
    due TEXT,
    public_text TEXT,               -- neutral "you said, we did" wording
    status TEXT NOT NULL DEFAULT 'open',
    created_day TEXT NOT NULL,
    done_day TEXT
);
"""


def connect():
    Path(config.DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def db():
    conn = connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


# Columns added after the first version; added in place so existing data (and ward codes / QR codes) survive.
MIGRATIONS = [
    ("wards", "name_uz", "TEXT"),          # department name in Uzbek (falls back to `name`)
    ("wards", "name_ru", "TEXT"),          # department name in Russian (falls back to `name`)
    ("reports", "terms_version", "TEXT"),  # which Terms & Privacy version the reporter agreed to
    ("wards", "clinic_id", "INTEGER"),     # the clinic this department belongs to
    ("wards", "active", "INTEGER NOT NULL DEFAULT 1"),  # 0 = removed from forms, past reports kept
    ("reports", "clinic_id", "INTEGER"),
    ("actions", "clinic_id", "INTEGER"),
    ("reports", "reporter", "TEXT"),       # patient / relative / staff (who is speaking, never who they are)
    ("clinics", "plan", "TEXT"),           # paid plan: klinika / network (empty = not paying), see plans.py
    ("clinics", "paid_until", "TEXT"),     # last paid day (empty = no end date)
    ("clinics", "trial_until", "TEXT"),    # last day of the free Klinika trial
]


def init_db():
    with db() as conn:
        conn.executescript(SCHEMA)
        for table, col, typ in MIGRATIONS:
            if col not in [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
        for table in ("wards", "reports", "actions"):
            conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_clinic ON {table}(clinic_id)")
        _adopt_orphans(conn)
        from . import plans  # local import: plans imports pricing only
        plans.migrate(conn)


def _adopt_orphans(conn):
    """Data from before clinics existed becomes the "demo" clinic (password: CLINIC_PASSWORD from .env)."""
    orphans = any(conn.execute(f"SELECT 1 FROM {t} WHERE clinic_id IS NULL LIMIT 1").fetchone()
                  for t in ("wards", "reports", "actions"))
    if not orphans:
        return
    from .util import hash_password  # local import: util imports config only
    row = conn.execute("SELECT id FROM clinics WHERE slug='demo'").fetchone()
    if row:
        cid = row[0]
    else:
        from datetime import date
        cid = conn.execute(
            "INSERT INTO clinics (slug, name, contact, password_hash, created_day) VALUES (?,?,?,?,?)",
            ("demo", config.CLINIC_NAME or "Demo clinic", config.CLINIC_CONTACT or None,
             hash_password(config.CLINIC_PASSWORD), date.today().isoformat())).lastrowid
    for t in ("wards", "actions"):
        conn.execute(f"UPDATE {t} SET clinic_id=? WHERE clinic_id IS NULL", (cid,))
    conn.execute("UPDATE reports SET clinic_id=(SELECT clinic_id FROM wards WHERE wards.code=reports.ward_code) "
                 "WHERE clinic_id IS NULL")
    conn.execute("UPDATE reports SET clinic_id=? WHERE clinic_id IS NULL", (cid,))
