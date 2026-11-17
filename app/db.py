import sqlite3
from contextlib import contextmanager
from pathlib import Path

from . import config

SCHEMA = """
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


def init_db():
    with db() as conn:
        conn.executescript(SCHEMA)
